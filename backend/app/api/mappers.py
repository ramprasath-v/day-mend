"""Pure mappings from internal recovery aggregates to public API contracts."""

from datetime import datetime
from typing import Any

from app.api.models import (
    ApprovalResponse,
    AssumptionResponse,
    CalendarChangeResponse,
    CoverageSegmentResponse,
    CoverageWindowResponse,
    DisruptionResponse,
    ExecutionActionResponse,
    RecoveryCaseResponse,
    RecoveryEventResponse,
    RecoveryPlanResponse,
    RecoveryPlanSummaryResponse,
    RecoveryTimestampsResponse,
)
from app.models import PlanAssumptionStatus, RecoveryCase


def recovery_case_response(recovery_case: RecoveryCase) -> RecoveryCaseResponse:
    """Build a safe view without context snapshots, credentials, or model internals."""

    active = recovery_case.active_recovery_plan
    active_plan_id = active.plan_id if active is not None else None
    requires_approval = active_plan_id is not None and any(
        approval.plan_id == active_plan_id for approval in recovery_case.approval_history
    )
    return RecoveryCaseResponse(
        recovery_case_id=recovery_case.case_id,
        status=recovery_case.status,
        original_disruption=_original_disruption(recovery_case),
        active_plan=(
            RecoveryPlanResponse(
                plan_id=active.plan_id,
                coverage_segments=[
                    CoverageSegmentResponse(
                        segment_id=segment.segment_id,
                        window=_window(segment.window),
                        assigned_person_id=segment.assigned_person_id,
                        source=segment.source,
                        estimated_cost=segment.estimated_cost,
                    )
                    for segment in active.coverage_segments
                ],
                calendar_changes=[
                    CalendarChangeResponse(
                        event_id=event.event_id,
                        owner_id=event.owner_id,
                        title=event.title,
                        window=_window(event.window),
                        location=event.location,
                    )
                    for event in active.calendar_changes
                ],
                estimated_cost=active.estimated_cost,
                validation_state=active.validation_state,
                validation_errors=active.validation_errors,
            )
            if active is not None
            else None
        ),
        plan_history=[
            RecoveryPlanSummaryResponse(
                plan_id=plan.plan_id,
                validation_state=plan.validation_state,
                estimated_cost=plan.estimated_cost,
                coverage_segment_count=len(plan.coverage_segments),
            )
            for plan in recovery_case.previous_plans
        ],
        events=[
            RecoveryEventResponse(
                event_id=event.event_id,
                event_type=event.event_type,
                occurred_at=event.occurred_at,
                caregiver_id=event.caregiver_id,
                relevant_window=_window(event.relevant_window) if event.relevant_window else None,
                message=event.message,
                details=event.details,
            )
            for event in recovery_case.events
        ],
        invalidated_assumptions=[
            AssumptionResponse(
                assumption_id=assumption.assumption_id,
                assumption_type=assumption.assumption_type,
                subject_id=assumption.subject_id,
                relevant_window=(
                    _window(assumption.relevant_window) if assumption.relevant_window else None
                ),
                status=assumption.status,
                invalidated_at=assumption.invalidated_at,
                invalidation_reason=assumption.invalidation_reason,
                triggering_event_id=assumption.triggering_event_id,
            )
            for assumption in recovery_case.assumptions
            if assumption.status is PlanAssumptionStatus.INVALIDATED
        ],
        pending_approval=(
            ApprovalResponse.model_validate(
                recovery_case.pending_approval.model_dump(exclude={"recovery_case_id"})
            )
            if recovery_case.pending_approval
            else None
        ),
        approval_history=[
            ApprovalResponse.model_validate(approval.model_dump(exclude={"recovery_case_id"}))
            for approval in recovery_case.approval_history
        ],
        execution_actions=[
            ExecutionActionResponse.model_validate(action.model_dump())
            for action in recovery_case.execution_history
        ],
        current_deterministic_cost=active.estimated_cost if active is not None else 0,
        requires_approval=requires_approval,
        latest_trigger=recovery_case.latest_replan_trigger_event_id,
        timestamps=RecoveryTimestampsResponse(
            created_at=recovery_case.created_at,
            updated_at=recovery_case.updated_at,
            completion_verified_at=recovery_case.completion_verified_at,
        ),
        version=recovery_case.version,
    )


def _original_disruption(recovery_case: RecoveryCase) -> DisruptionResponse:
    stored = recovery_case.context_state.get("original_disruption")
    if isinstance(stored, dict):
        return DisruptionResponse(
            disruption_type=str(stored.get("disruption_type", "CHILDCARE_UNAVAILABLE")),
            occurred_at=_datetime(stored.get("occurred_at"), recovery_case.created_at),
            caregiver_id=str(stored.get("caregiver_id", "unknown")),
            message=str(stored.get("message", recovery_case.disruption)),
        )
    first = recovery_case.events[0] if recovery_case.events else None
    return DisruptionResponse(
        disruption_type="CHILDCARE_UNAVAILABLE",
        occurred_at=first.occurred_at if first else recovery_case.created_at,
        caregiver_id=first.caregiver_id if first and first.caregiver_id else "unknown",
        message=first.message if first and first.message else recovery_case.disruption,
    )


def _datetime(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return fallback


def _window(window) -> CoverageWindowResponse:
    return CoverageWindowResponse(start=window.start, end=window.end)
