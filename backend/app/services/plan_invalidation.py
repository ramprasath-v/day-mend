"""Deterministic world-state updates and localized active-plan impact analysis."""

from dataclasses import dataclass, replace
from datetime import datetime

from app.fixtures import DemoScenario
from app.models import (
    Caregiver,
    CoverageSource,
    CoverageWindow,
    PlanAssumption,
    PlanAssumptionStatus,
    PlanSegmentType,
    PlanValidationState,
    RecoveryCase,
    RecoveryEvent,
    RecoveryEventType,
    RecoveryPlan,
    RecoveryPlanSegment,
    RecoveryStatus,
)

CAREGIVER_AVAILABLE_ASSUMPTION = "CAREGIVER_AVAILABLE"


@dataclass(frozen=True)
class InvalidationOutcome:
    """Internal deterministic output consumed by replanning orchestration."""

    recovery_case: RecoveryCase
    previous_status: RecoveryStatus
    updated_scenario: DemoScenario
    original_valid_plan: RecoveryPlan
    invalidated_assumptions: tuple[PlanAssumption, ...]
    impacted_segments: tuple[RecoveryPlanSegment, ...]
    preserved_segments: tuple[RecoveryPlanSegment, ...]
    uncovered_windows: tuple[CoverageWindow, ...]


def materialize_caregiver_assumptions(plan: RecoveryPlan) -> RecoveryPlan:
    """Attach canonical segment-to-availability dependencies to a validated plan."""

    other_assumptions = [
        assumption
        for assumption in plan.assumptions
        if assumption.assumption_type
        not in {CAREGIVER_AVAILABLE_ASSUMPTION, "CAREGIVER_AVAILABILITY"}
    ]
    caregiver_assumptions = [
        PlanAssumption(
            assumption_id=f"caregiver-availability:{plan.plan_id}:{segment.segment_id}",
            assumption_type=CAREGIVER_AVAILABLE_ASSUMPTION,
            subject_id=segment.assigned_person_id,
            relevant_window=segment.window,
            value=True,
        )
        for segment in plan.coverage_segments
        if segment.source is CoverageSource.CAREGIVER
    ]
    return plan.model_copy(update={"assumptions": other_assumptions + caregiver_assumptions})


def create_active_recovery_case(
    *,
    case_id: str,
    disruption: str,
    validated_plan: RecoveryPlan,
    required_coverage: CoverageWindow,
    now: datetime,
) -> RecoveryCase:
    """Create the minimum in-memory aggregate required to observe later invalidation."""

    if validated_plan.validation_state is not PlanValidationState.VALID:
        raise ValueError("an active recovery case requires a deterministically valid plan")
    active_plan = materialize_caregiver_assumptions(validated_plan)
    return RecoveryCase(
        case_id=case_id,
        status=RecoveryStatus.WAITING_FOR_RESPONSE,
        disruption=disruption,
        coverage_gap=required_coverage,
        uncovered_windows=[],
        active_recovery_plan=active_plan,
        assumptions=active_plan.assumptions,
        created_at=now,
        updated_at=now,
    )


class PlanInvalidationService:
    """Apply an external caregiver decline and locate only the plan work it breaks."""

    def apply_caregiver_decline(
        self,
        recovery_case: RecoveryCase,
        event: RecoveryEvent,
        scenario: DemoScenario,
    ) -> InvalidationOutcome:
        if event.event_type is not RecoveryEventType.CAREGIVER_DECLINED:
            raise ValueError("PlanInvalidationService only handles caregiver declines")
        if event.event_id in {existing.event_id for existing in recovery_case.events}:
            raise ValueError(f"event {event.event_id} has already been recorded")
        if recovery_case.active_recovery_plan is None:
            raise ValueError("recovery case has no active plan")
        if recovery_case.active_recovery_plan.validation_state is not PlanValidationState.VALID:
            raise ValueError("world-state replanning must start from a valid active plan")

        original_plan = materialize_caregiver_assumptions(
            recovery_case.active_recovery_plan.model_copy(deep=True)
        )
        assert event.caregiver_id is not None
        assert event.relevant_window is not None
        assert event.message is not None

        assumptions = recovery_case.assumptions or original_plan.assumptions
        updated_assumptions: list[PlanAssumption] = []
        invalidated: list[PlanAssumption] = []
        for assumption in assumptions:
            matches = (
                assumption.status is PlanAssumptionStatus.ACTIVE
                and assumption.assumption_type == CAREGIVER_AVAILABLE_ASSUMPTION
                and assumption.subject_id == event.caregiver_id
                and assumption.relevant_window is not None
                and _windows_overlap(assumption.relevant_window, event.relevant_window)
            )
            if matches:
                assumption = assumption.model_copy(
                    update={
                        "status": PlanAssumptionStatus.INVALIDATED,
                        "invalidated_at": event.occurred_at,
                        "invalidation_reason": event.message,
                        "triggering_event_id": event.event_id,
                    }
                )
                invalidated.append(assumption)
            updated_assumptions.append(assumption)

        impacted = [
            segment
            for segment in original_plan.coverage_segments
            if segment.source is CoverageSource.CAREGIVER
            and segment.assigned_person_id == event.caregiver_id
            and _windows_overlap(segment.window, event.relevant_window)
        ]
        declined = next(
            (
                caregiver
                for caregiver in scenario.caregivers
                if caregiver.caregiver_id == event.caregiver_id
            ),
            None,
        )
        if declined is None:
            raise ValueError(f"unknown caregiver {event.caregiver_id}")
        ordered = sorted(
            original_plan.coverage_segments,
            key=lambda segment: (segment.window.start, segment.window.end),
        )
        impacted_ids = {segment.segment_id for segment in impacted}
        for index, segment in enumerate(ordered):
            if segment.segment_id not in impacted_ids:
                continue
            if index > 0:
                previous = ordered[index - 1]
                if (
                    previous.segment_type is PlanSegmentType.TRANSPORT
                    and previous.window.end == segment.window.start
                    and previous.destination_location_id == declined.location_id
                ):
                    impacted_ids.add(previous.segment_id)
            if index + 1 < len(ordered):
                following = ordered[index + 1]
                if (
                    following.segment_type is PlanSegmentType.TRANSPORT
                    and following.window.start == segment.window.end
                    and following.location_id == declined.location_id
                ):
                    impacted_ids.add(following.segment_id)
        impacted = [segment for segment in ordered if segment.segment_id in impacted_ids]
        if not impacted or not invalidated:
            raise ValueError("caregiver decline did not invalidate an active plan dependency")
        preserved = [
            segment
            for segment in original_plan.coverage_segments
            if segment.segment_id not in impacted_ids
        ]
        uncovered = _merge_windows([segment.window for segment in impacted])

        invalidated_plan = original_plan.model_copy(
            update={
                "assumptions": updated_assumptions,
                "validation_state": PlanValidationState.INVALID,
                "validation_errors": [
                    f"External event {event.event_id} invalidated caregiver availability."
                ],
            }
        )
        previous_plans = recovery_case.previous_plans.copy()
        if original_plan.plan_id not in {plan.plan_id for plan in previous_plans}:
            previous_plans.append(original_plan)
        updated_scenario = apply_caregiver_decline_to_scenario(scenario, event)
        context_state = recovery_case.context_state.copy()
        context_state.update(
            {
                "latest_caregiver_response": event.model_dump(mode="json"),
                "caregiver_availability": _caregiver_availability_snapshot(updated_scenario),
            }
        )
        updated_case = recovery_case.model_copy(
            update={
                "status": RecoveryStatus.REPLANNING,
                "coverage_gap": uncovered[0],
                "uncovered_windows": uncovered,
                "context_state": context_state,
                "active_recovery_plan": invalidated_plan,
                "previous_plans": previous_plans,
                "assumptions": updated_assumptions,
                "events": [*recovery_case.events, event],
                "latest_replan_trigger_event_id": event.event_id,
                "updated_at": max(
                    recovery_case.created_at,
                    recovery_case.updated_at,
                    event.occurred_at,
                ),
            }
        )
        return InvalidationOutcome(
            recovery_case=updated_case,
            previous_status=recovery_case.status,
            updated_scenario=updated_scenario,
            original_valid_plan=original_plan,
            invalidated_assumptions=tuple(invalidated),
            impacted_segments=tuple(impacted),
            preserved_segments=tuple(preserved),
            uncovered_windows=tuple(uncovered),
        )


def apply_caregiver_decline_to_scenario(
    scenario: DemoScenario,
    event: RecoveryEvent,
) -> DemoScenario:
    """Replay a recorded caregiver decline to rebuild authoritative in-memory state."""

    assert event.caregiver_id is not None
    assert event.relevant_window is not None
    found = False
    caregivers: list[Caregiver] = []
    for caregiver in scenario.caregivers:
        if caregiver.caregiver_id != event.caregiver_id:
            caregivers.append(caregiver)
            continue
        found = True
        availability = [
            remaining
            for window in caregiver.availability
            for remaining in _subtract_window(window, event.relevant_window)
        ]
        caregivers.append(caregiver.model_copy(update={"availability": availability}))
    if not found:
        raise ValueError(f"unknown caregiver {event.caregiver_id}")
    return replace(scenario, caregivers=tuple(caregivers))


def _subtract_window(
    available: CoverageWindow,
    unavailable: CoverageWindow,
) -> list[CoverageWindow]:
    if not _windows_overlap(available, unavailable):
        return [available]
    remaining: list[CoverageWindow] = []
    if available.start < unavailable.start:
        remaining.append(CoverageWindow(start=available.start, end=unavailable.start))
    if unavailable.end < available.end:
        remaining.append(CoverageWindow(start=unavailable.end, end=available.end))
    return remaining


def _merge_windows(windows: list[CoverageWindow]) -> list[CoverageWindow]:
    ordered = sorted(windows, key=lambda window: (window.start, window.end))
    merged: list[CoverageWindow] = []
    for window in ordered:
        if not merged or window.start > merged[-1].end:
            merged.append(window)
            continue
        merged[-1] = CoverageWindow(
            start=merged[-1].start,
            end=max(merged[-1].end, window.end),
        )
    return merged


def _caregiver_availability_snapshot(scenario: DemoScenario) -> dict[str, list[dict[str, str]]]:
    return {
        caregiver.caregiver_id: [
            window.model_dump(mode="json") for window in caregiver.availability
        ]
        for caregiver in scenario.caregivers
    }


def _windows_overlap(left: CoverageWindow, right: CoverageWindow) -> bool:
    return left.start < right.end and right.start < left.end
