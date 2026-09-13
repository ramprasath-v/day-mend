"""Deterministic validation for agent-proposed recovery plans."""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import Field

from app.fixtures import DemoScenario
from app.models import (
    CalendarEvent,
    Caregiver,
    ContractModel,
    CoverageSource,
    CoverageWindow,
    FamilyPreferences,
    ParentTransportCapability,
    PlanApprovalReason,
    PlanSegmentType,
    PlanValidationState,
    RecoveryPlan,
    RecoveryPlanSegment,
)

MONEY_QUANTUM = Decimal("0.01")


def _preserved_work_survives(
    preserved: RecoveryPlanSegment,
    candidate: RecoveryPlanSegment,
) -> bool:
    """Whether candidate retains the full accepted interval with identical material semantics."""

    return (
        candidate.window.start <= preserved.window.start
        and candidate.window.end >= preserved.window.end
        and candidate.assigned_person_id == preserved.assigned_person_id
        and candidate.source is preserved.source
        and candidate.segment_type is preserved.segment_type
        and candidate.location_id == preserved.location_id
        and candidate.destination_location_id == preserved.destination_location_id
        and candidate.transporter_id == preserved.transporter_id
    )


class ValidationErrorCode(StrEnum):
    """Stable error taxonomy exposed to the Recovery Agent's repair loop."""

    DUPLICATE_SEGMENT_ID = "duplicate_segment_id"
    COVERAGE_GAP = "coverage_gap"
    COVERAGE_OVERLAP = "coverage_overlap"
    HANDOFF_INFEASIBLE = "handoff_infeasible"
    CAREGIVER_UNAVAILABLE = "caregiver_unavailable"
    CAREGIVER_UNTRUSTED = "caregiver_untrusted"
    PARENT_CRITICAL_CONFLICT = "parent_critical_conflict"
    MOVABLE_EVENT_CHANGE_REQUIRED = "movable_event_change_required"
    UNSUPPORTED_PERSON = "unsupported_person"
    UNSUPPORTED_CALENDAR_EVENT = "unsupported_calendar_event"
    HARD_POLICY_VIOLATION = "hard_policy_violation"
    LOCATION_TRANSITION_INVALID = "location_transition_invalid"
    INSUFFICIENT_TRAVEL_TIME = "insufficient_travel_time"
    TRANSPORTER_UNAVAILABLE = "transporter_unavailable"
    PRESERVED_SEGMENT_CHANGED = "preserved_segment_changed"


class PlanValidationIssue(ContractModel):
    """One actionable deterministic finding suitable for structured model feedback."""

    code: ValidationErrorCode
    message: str
    subject_id: str | None = None
    segment_id: str | None = None
    event_id: str | None = None
    suggested_alternatives: list[str] = Field(default_factory=list)


class PlanValidationResult(ContractModel):
    """Auditable result of deterministic validation."""

    valid: bool
    issues: list[PlanValidationIssue] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    deterministic_total_cost: Decimal = Field(ge=0)
    requires_approval: bool = False
    validated_plan: RecoveryPlan


class PlanValidator:
    """Validate a proposed plan against authoritative scenario facts without an LLM."""

    def validate(self, plan: RecoveryPlan, scenario: DemoScenario) -> PlanValidationResult:
        """Return a validated copy of the plan and all deterministic findings."""

        issues: list[PlanValidationIssue] = []
        warnings: list[str] = []
        segments = sorted(
            plan.coverage_segments,
            key=lambda segment: (segment.window.start, segment.window.end),
        )
        caregivers = {caregiver.caregiver_id: caregiver for caregiver in scenario.caregivers}
        parent_ids = set(scenario.parent_ids)

        # Feasibility: can this plan safely cover the entire disruption window?
        self._validate_unique_segment_ids(segments, issues)
        self._validate_coverage_and_handoffs(segments, scenario, caregivers, issues)
        self._validate_assignments(segments, scenario, caregivers, parent_ids, issues)
        self._validate_locations_and_transport(segments, scenario, caregivers, issues)
        self._validate_parent_calendars(segments, plan.calendar_changes, scenario, issues)

        # Cost: authoritative prices replace every model-proposed amount.
        deterministic_segments, total_cost = self._recompute_costs(segments, caregivers)
        self._warn_on_cost_mismatches(plan, deterministic_segments, total_cost, warnings)
        self._add_preference_warnings(
            deterministic_segments,
            caregivers,
            scenario.preferences,
            warnings,
        )

        # Autonomy: spending affects future execution authority, never feasibility.
        approval_reasons: list[PlanApprovalReason] = []
        if total_cost > scenario.policy.automatic_spend_limit:
            approval_reasons.append(PlanApprovalReason.COST_ABOVE_AUTOMATIC_LIMIT)
            warnings.append(
                "Plan cost exceeds the automatic-spend limit and would require approval "
                "before execution."
            )
        uses_unfamiliar_paid_caregiver = any(
            segment.source is CoverageSource.CAREGIVER
            and (caregiver := caregivers.get(segment.assigned_person_id)) is not None
            and caregiver.external_provider
            and not caregiver.known_to_family
            and (
                (caregiver.hourly_rate is not None and caregiver.hourly_rate > 0)
                or (caregiver.flat_rate is not None and caregiver.flat_rate > 0)
            )
            for segment in deterministic_segments
        )
        if (
            scenario.policy.require_approval_for_unfamiliar_paid_caregiver
            and uses_unfamiliar_paid_caregiver
        ):
            approval_reasons.append(PlanApprovalReason.UNFAMILIAR_PAID_CAREGIVER)
            warnings.append(
                "Plan uses an unfamiliar paid caregiver and requires approval before execution."
            )
        requires_approval = bool(approval_reasons)

        errors = [issue.message for issue in issues]
        validation_state = PlanValidationState.INVALID if issues else PlanValidationState.VALID
        validated_plan = plan.model_copy(
            update={
                "coverage_segments": deterministic_segments,
                "estimated_cost": total_cost,
                "validation_state": validation_state,
                "validation_errors": errors.copy(),
                "approval_reasons": approval_reasons,
            }
        )
        return PlanValidationResult(
            valid=not issues,
            issues=issues,
            errors=errors,
            warnings=warnings,
            deterministic_total_cost=total_cost,
            requires_approval=requires_approval,
            validated_plan=validated_plan,
        )

    def validate_repair(
        self,
        plan: RecoveryPlan,
        scenario: DemoScenario,
        preserved_segments: list[RecoveryPlanSegment],
    ) -> PlanValidationResult:
        """Validate feasibility plus the application-owned Plan A preservation contract."""

        result = self.validate(plan, scenario)
        preservation_issues: list[PlanValidationIssue] = []
        for preserved in preserved_segments:
            if any(
                _preserved_work_survives(preserved, candidate)
                for candidate in plan.coverage_segments
            ):
                continue
            preservation_issues.append(
                PlanValidationIssue(
                    code=ValidationErrorCode.PRESERVED_SEGMENT_CHANGED,
                    message=(
                        f"Previously accepted segment {preserved.segment_id} must remain "
                        "materially unchanged because deterministic impact analysis preserved it."
                    ),
                    subject_id=preserved.assigned_person_id,
                    segment_id=preserved.segment_id,
                )
            )
        if not preservation_issues:
            return result

        issues = [*result.issues, *preservation_issues]
        errors = [issue.message for issue in issues]
        validated_plan = result.validated_plan.model_copy(
            update={
                "validation_state": PlanValidationState.INVALID,
                "validation_errors": errors.copy(),
            }
        )
        return result.model_copy(
            update={
                "valid": False,
                "issues": issues,
                "errors": errors,
                "validated_plan": validated_plan,
            }
        )

    @staticmethod
    def _validate_unique_segment_ids(
        segments: list[RecoveryPlanSegment], issues: list[PlanValidationIssue]
    ) -> None:
        segment_ids = [segment.segment_id for segment in segments]
        if len(segment_ids) != len(set(segment_ids)):
            issues.append(
                PlanValidationIssue(
                    code=ValidationErrorCode.DUPLICATE_SEGMENT_ID,
                    message="Coverage segment IDs must be unique.",
                )
            )

    @staticmethod
    def _validate_coverage_and_handoffs(
        segments: list[RecoveryPlanSegment],
        scenario: DemoScenario,
        caregivers: dict[str, Caregiver],
        issues: list[PlanValidationIssue],
    ) -> None:
        required = scenario.required_coverage
        if not segments:
            issues.append(
                PlanValidationIssue(
                    code=ValidationErrorCode.COVERAGE_GAP,
                    message="Required childcare window has no coverage segments.",
                )
            )
            return

        if segments[0].window.start != required.start:
            issues.append(
                PlanValidationIssue(
                    code=ValidationErrorCode.COVERAGE_GAP,
                    message="Coverage does not start at the beginning of the required window.",
                    segment_id=segments[0].segment_id,
                )
            )
        if segments[-1].window.end != required.end:
            issues.append(
                PlanValidationIssue(
                    code=ValidationErrorCode.COVERAGE_GAP,
                    message="Coverage does not end at the end of the required window.",
                    segment_id=segments[-1].segment_id,
                )
            )

        for segment in segments:
            if segment.window.start < required.start or segment.window.end > required.end:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.HARD_POLICY_VIOLATION,
                        message=(
                            f"Segment {segment.segment_id} extends outside the required window."
                        ),
                        segment_id=segment.segment_id,
                    )
                )

        for previous, current in zip(segments, segments[1:], strict=False):
            boundary_delta = current.window.start - previous.window.end
            different_people = previous.assigned_person_id != current.assigned_person_id
            if not different_people:
                if boundary_delta > timedelta(0):
                    issues.append(
                        PlanValidationIssue(
                            code=ValidationErrorCode.COVERAGE_GAP,
                            message=f"Uncovered gap before segment {current.segment_id}: "
                            f"{int(boundary_delta.total_seconds() // 60)} minutes.",
                            segment_id=current.segment_id,
                        )
                    )
                elif boundary_delta < timedelta(0):
                    issues.append(
                        PlanValidationIssue(
                            code=ValidationErrorCode.COVERAGE_OVERLAP,
                            message=f"Inconsistent overlap before segment {current.segment_id} "
                            "for the same assigned person.",
                            segment_id=current.segment_id,
                        )
                    )
                continue

            required_buffer = scenario.policy.minimum_handoff_minutes
            if current.source is CoverageSource.CAREGIVER:
                caregiver = caregivers.get(current.assigned_person_id)
                if caregiver is not None:
                    required_buffer = max(required_buffer, caregiver.handoff_buffer_minutes)

            actual_overlap = max(
                0,
                int((-boundary_delta).total_seconds() // 60),
            )
            if boundary_delta > timedelta(0):
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.COVERAGE_GAP,
                        message=f"Uncovered gap before segment {current.segment_id}: "
                        f"{int(boundary_delta.total_seconds() // 60)} minutes.",
                        segment_id=current.segment_id,
                    )
                )
            if actual_overlap < required_buffer:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.HANDOFF_INFEASIBLE,
                        message=f"Handoff before segment {current.segment_id} provides "
                        f"{actual_overlap} of {required_buffer} required buffer minutes.",
                        segment_id=current.segment_id,
                    )
                )
            elif actual_overlap > required_buffer:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.COVERAGE_OVERLAP,
                        message=f"Unexpected overlap before segment {current.segment_id}: "
                        f"{actual_overlap} minutes with only {required_buffer} required.",
                        segment_id=current.segment_id,
                    )
                )

    @staticmethod
    def _validate_assignments(
        segments: list[RecoveryPlanSegment],
        scenario: DemoScenario,
        caregivers: dict[str, Caregiver],
        parent_ids: set[str],
        issues: list[PlanValidationIssue],
    ) -> None:
        for segment in segments:
            person_id = segment.assigned_person_id
            if segment.source is CoverageSource.PARENT:
                if person_id not in parent_ids:
                    issues.append(
                        PlanValidationIssue(
                            code=ValidationErrorCode.UNSUPPORTED_PERSON,
                            message=(
                                f"Segment {segment.segment_id} invents unsupported parent "
                                f"{person_id}."
                            ),
                            subject_id=person_id,
                            segment_id=segment.segment_id,
                        )
                    )
                continue

            caregiver = caregivers.get(person_id)
            if caregiver is None:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.UNSUPPORTED_PERSON,
                        message=(
                            f"Segment {segment.segment_id} invents unsupported caregiver "
                            f"{person_id}."
                        ),
                        subject_id=person_id,
                        segment_id=segment.segment_id,
                    )
                )
                continue
            if person_id in scenario.unavailable_caregiver_ids:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.CAREGIVER_UNAVAILABLE,
                        message=(
                            f"Caregiver {person_id} is unavailable due to the disruption for "
                            f"segment {segment.segment_id} from "
                            f"{segment.window.start.isoformat()} to "
                            f"{segment.window.end.isoformat()}."
                        ),
                        subject_id=person_id,
                        segment_id=segment.segment_id,
                    )
                )
            if caregiver.external_provider and not scenario.policy.allow_external_backup_providers:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.HARD_POLICY_VIOLATION,
                        message="External backup providers are disabled by family policy.",
                        subject_id=person_id,
                        segment_id=segment.segment_id,
                    )
                )
            if (
                scenario.policy.require_trusted_caregiver
                or not scenario.policy.unapproved_caregiver_allowed
            ) and not caregiver.is_trusted:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.CAREGIVER_UNTRUSTED,
                        message=f"Caregiver {person_id} is not trusted/approved by family policy.",
                        subject_id=person_id,
                        segment_id=segment.segment_id,
                    )
                )
            if not any(
                window.start <= segment.window.start and window.end >= segment.window.end
                for window in caregiver.availability
            ):
                authoritative_availability = (
                    ", ".join(
                        f"{window.start.isoformat()} to {window.end.isoformat()}"
                        for window in caregiver.availability
                    )
                    or "none"
                )
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.CAREGIVER_UNAVAILABLE,
                        message=(
                            f"Caregiver {person_id} is unavailable for segment "
                            f"{segment.segment_id} from {segment.window.start.isoformat()} to "
                            f"{segment.window.end.isoformat()}. Authoritative availability: "
                            f"{authoritative_availability}."
                        ),
                        subject_id=person_id,
                        segment_id=segment.segment_id,
                    )
                )

    @staticmethod
    def _validate_parent_calendars(
        segments: list[RecoveryPlanSegment],
        calendar_changes: list[CalendarEvent],
        scenario: DemoScenario,
        issues: list[PlanValidationIssue],
    ) -> None:
        original_events = {event.event_id: event for event in scenario.parent_events}
        changes = {event.event_id: event for event in calendar_changes}

        for change in calendar_changes:
            original = original_events.get(change.event_id)
            if original is None:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.UNSUPPORTED_CALENDAR_EVENT,
                        message=f"Calendar change invents unsupported event {change.event_id}.",
                        subject_id=change.owner_id,
                        event_id=change.event_id,
                    )
                )
            elif original.critical or not original.movable:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.PARENT_CRITICAL_CONFLICT,
                        message=f"Calendar event {change.event_id} cannot be moved.",
                        subject_id=change.owner_id,
                        event_id=change.event_id,
                    )
                )
            elif change.owner_id != original.owner_id:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.UNSUPPORTED_CALENDAR_EVENT,
                        message=f"Calendar change {change.event_id} changes the event owner.",
                        subject_id=change.owner_id,
                        event_id=change.event_id,
                    )
                )

        for segment in segments:
            if segment.source is not CoverageSource.PARENT:
                continue
            for event in scenario.parent_events:
                if event.owner_id != segment.assigned_person_id:
                    continue
                if not _windows_overlap(segment.window, event.window):
                    continue
                if event.critical or not event.movable:
                    issues.append(
                        PlanValidationIssue(
                            code=ValidationErrorCode.PARENT_CRITICAL_CONFLICT,
                            message=f"Parent {segment.assigned_person_id} is assigned during "
                            f"critical or non-movable event {event.event_id}.",
                            subject_id=segment.assigned_person_id,
                            segment_id=segment.segment_id,
                            event_id=event.event_id,
                        )
                    )
                    continue
                changed_event = changes.get(event.event_id)
                if changed_event is None:
                    issues.append(
                        PlanValidationIssue(
                            code=ValidationErrorCode.MOVABLE_EVENT_CHANGE_REQUIRED,
                            message=f"Parent coverage overlaps movable event {event.event_id} "
                            "without a proposed calendar change.",
                            subject_id=segment.assigned_person_id,
                            segment_id=segment.segment_id,
                            event_id=event.event_id,
                        )
                    )
                elif _windows_overlap(segment.window, changed_event.window):
                    issues.append(
                        PlanValidationIssue(
                            code=ValidationErrorCode.MOVABLE_EVENT_CHANGE_REQUIRED,
                            message=(
                                f"Moved calendar event {event.event_id} still overlaps parent "
                                "coverage."
                            ),
                            subject_id=segment.assigned_person_id,
                            segment_id=segment.segment_id,
                            event_id=event.event_id,
                        )
                    )

    @staticmethod
    def _validate_locations_and_transport(
        segments: list[RecoveryPlanSegment],
        scenario: DemoScenario,
        caregivers: dict[str, Caregiver],
        issues: list[PlanValidationIssue],
    ) -> None:
        home = scenario.family_home_location_id
        known_locations = {home, *(caregiver.location_id for caregiver in caregivers.values())}
        travel_from_home = {
            caregiver.location_id: caregiver.travel_minutes_from_family_home
            for caregiver in caregivers.values()
            if caregiver.location_id != home
        }
        parent_transport = {item.parent_id: item for item in scenario.parent_transport_capabilities}

        for segment in segments:
            if segment.location_id not in known_locations:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.LOCATION_TRANSITION_INVALID,
                        message=f"Segment {segment.segment_id} uses unknown location "
                        f"{segment.location_id}.",
                        segment_id=segment.segment_id,
                    )
                )
            if segment.segment_type is PlanSegmentType.CARE:
                caregiver = caregivers.get(segment.assigned_person_id)
                if caregiver is not None and segment.location_id != caregiver.location_id:
                    issues.append(
                        PlanValidationIssue(
                            code=ValidationErrorCode.LOCATION_TRANSITION_INVALID,
                            message=f"Caregiver {caregiver.caregiver_id} provides care at "
                            f"{caregiver.location_id}, not {segment.location_id}.",
                            subject_id=caregiver.caregiver_id,
                            segment_id=segment.segment_id,
                        )
                    )
                continue

            destination = segment.destination_location_id
            assert destination is not None
            if destination not in known_locations or destination == segment.location_id:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.LOCATION_TRANSITION_INVALID,
                        message=f"Transport segment {segment.segment_id} needs distinct, known "
                        "origin and destination locations.",
                        segment_id=segment.segment_id,
                    )
                )
            required_minutes = _travel_minutes(
                segment.location_id,
                destination,
                home,
                travel_from_home,
            )
            actual_minutes = int((segment.window.end - segment.window.start).total_seconds() // 60)
            if required_minutes is None:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.LOCATION_TRANSITION_INVALID,
                        message=f"No authoritative travel duration exists for transport segment "
                        f"{segment.segment_id}.",
                        segment_id=segment.segment_id,
                    )
                )
            elif actual_minutes < required_minutes:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.INSUFFICIENT_TRAVEL_TIME,
                        message=f"Transport segment {segment.segment_id} provides "
                        f"{actual_minutes} of {required_minutes} required travel minutes.",
                        segment_id=segment.segment_id,
                    )
                )
            PlanValidator._validate_transporter(
                segment, scenario, caregivers, parent_transport, issues
            )

        for previous, current in zip(segments, segments[1:], strict=False):
            previous_end = (
                previous.destination_location_id
                if previous.segment_type is PlanSegmentType.TRANSPORT
                else previous.location_id
            )
            if previous_end != current.location_id:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.LOCATION_TRANSITION_INVALID,
                        message=f"Child cannot move from {previous_end} to "
                        f"{current.location_id} before segment {current.segment_id} without "
                        "an explicit transport segment.",
                        segment_id=current.segment_id,
                    )
                )

    @staticmethod
    def _validate_transporter(
        segment: RecoveryPlanSegment,
        scenario: DemoScenario,
        caregivers: dict[str, Caregiver],
        parent_transport: dict[str, ParentTransportCapability],
        issues: list[PlanValidationIssue],
    ) -> None:
        transporter_id = segment.transporter_id
        assert transporter_id is not None
        capability = parent_transport.get(transporter_id)
        caregiver = caregivers.get(transporter_id)
        capable = (capability is not None and capability.can_transport_child) or (
            caregiver is not None
            and caregiver.can_transport_child
            and (
                not caregiver.external_provider
                or (
                    scenario.policy.allow_provider_transport
                    and scenario.policy.allow_external_backup_providers
                )
            )
        )
        availability = (
            capability.availability
            if capability is not None
            else caregiver.availability
            if caregiver is not None
            else []
        )
        available = any(
            window.start <= segment.window.start and window.end >= segment.window.end
            for window in availability
        )
        if not capable or not available:
            issues.append(
                PlanValidationIssue(
                    code=ValidationErrorCode.TRANSPORTER_UNAVAILABLE,
                    message=f"Transporter {transporter_id} is not capable and available for "
                    f"segment {segment.segment_id}.",
                    subject_id=transporter_id,
                    segment_id=segment.segment_id,
                )
            )
        for event in scenario.parent_events:
            if event.owner_id != transporter_id or not _windows_overlap(
                segment.window, event.window
            ):
                continue
            if event.critical or not event.movable:
                issues.append(
                    PlanValidationIssue(
                        code=ValidationErrorCode.PARENT_CRITICAL_CONFLICT,
                        message=f"Parent {transporter_id} transports during critical or "
                        f"non-movable event {event.event_id}.",
                        subject_id=transporter_id,
                        segment_id=segment.segment_id,
                        event_id=event.event_id,
                    )
                )

    @staticmethod
    def _recompute_costs(
        segments: list[RecoveryPlanSegment],
        caregivers: dict[str, Caregiver],
    ) -> tuple[list[RecoveryPlanSegment], Decimal]:
        total = Decimal("0")
        charged_flat_rates: set[str] = set()
        deterministic_segments: list[RecoveryPlanSegment] = []

        for segment in segments:
            cost = Decimal("0")
            caregiver = caregivers.get(segment.assigned_person_id)
            if segment.source is CoverageSource.CAREGIVER and caregiver is not None:
                if caregiver.flat_rate is not None:
                    if caregiver.caregiver_id not in charged_flat_rates:
                        cost = caregiver.flat_rate
                        charged_flat_rates.add(caregiver.caregiver_id)
                elif caregiver.hourly_rate is not None:
                    hours = Decimal(
                        str(segment.window.end.timestamp() - segment.window.start.timestamp())
                    )
                    hours /= Decimal("3600")
                    cost = caregiver.hourly_rate * hours
            cost = cost.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
            total += cost
            deterministic_segments.append(segment.model_copy(update={"estimated_cost": cost}))

        return deterministic_segments, total.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)

    @staticmethod
    def _warn_on_cost_mismatches(
        proposed_plan: RecoveryPlan,
        deterministic_segments: list[RecoveryPlanSegment],
        total_cost: Decimal,
        warnings: list[str],
    ) -> None:
        proposed_by_id = {
            segment.segment_id: segment.estimated_cost
            for segment in proposed_plan.coverage_segments
        }
        for segment in deterministic_segments:
            if proposed_by_id.get(segment.segment_id) != segment.estimated_cost:
                warnings.append(
                    f"Recomputed cost for segment {segment.segment_id}: {segment.estimated_cost}."
                )
        if proposed_plan.estimated_cost != total_cost:
            warnings.append(f"Recomputed plan total cost: {total_cost}.")

    @staticmethod
    def _add_preference_warnings(
        segments: list[RecoveryPlanSegment],
        caregivers: dict[str, Caregiver],
        preferences: FamilyPreferences,
        warnings: list[str],
    ) -> None:
        used_caregivers = [
            caregivers[segment.assigned_person_id]
            for segment in segments
            if segment.source is CoverageSource.CAREGIVER
            and segment.assigned_person_id in caregivers
        ]
        if (
            preferences.prefer_family_first
            and used_caregivers
            and not any(item.relationship == "family" for item in used_caregivers)
        ):
            warnings.append("Plan does not satisfy the soft preference to use family first.")

        handoffs = sum(
            previous.assigned_person_id != current.assigned_person_id
            for previous, current in zip(segments, segments[1:], strict=False)
        )
        if preferences.prefer_fewer_handoffs and handoffs > 1:
            warnings.append("Plan has multiple handoffs despite the soft preference for fewer.")


def _windows_overlap(left: CoverageWindow, right: CoverageWindow) -> bool:
    return left.start < right.end and right.start < left.end


def _travel_minutes(
    origin: str,
    destination: str,
    family_home: str,
    travel_from_home: dict[str, int],
) -> int | None:
    if origin == destination:
        return 0
    if origin == family_home:
        return travel_from_home.get(destination)
    if destination == family_home:
        return travel_from_home.get(origin)
    return None
