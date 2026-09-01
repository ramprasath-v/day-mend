"""Deterministic completion verification: the only path to RESOLVED."""

from datetime import datetime

from pydantic import Field

from app.fixtures import DemoScenario
from app.models import (
    ApprovalStatus,
    ContractModel,
    CoverageSource,
    ExecutionActionStatus,
    PlanAssumptionStatus,
    RecoveryCase,
    RecoveryEvent,
    RecoveryEventType,
    RecoveryStatus,
)
from app.repositories import RecoveryCaseRepository
from app.services.execution_service import required_execution_actions
from app.services.plan_validator import PlanValidator


class CompletionVerificationResult(ContractModel):
    """Auditable completion decision and persisted case state."""

    verified: bool
    errors: list[str] = Field(default_factory=list)
    recovery_case: RecoveryCase


class CompletionVerifier:
    """Verify coverage, authorization, actions, dependencies, and consistency."""

    def __init__(
        self,
        repository: RecoveryCaseRepository,
        *,
        validator: PlanValidator | None = None,
    ) -> None:
        self._repository = repository
        self._validator = validator or PlanValidator()

    def verify_and_resolve(
        self,
        case_id: str,
        scenario: DemoScenario,
        *,
        now: datetime,
    ) -> CompletionVerificationResult:
        recovery_case = self._repository.get(case_id)
        errors: list[str] = []
        plan = recovery_case.active_recovery_plan
        if recovery_case.status is not RecoveryStatus.EXECUTING:
            errors.append("Case is not in EXECUTING state.")
        if plan is None:
            errors.append("Case has no active plan.")
            return CompletionVerificationResult(
                verified=False,
                errors=errors,
                recovery_case=recovery_case,
            )

        validation = self._validator.validate(plan, scenario)
        if not validation.valid:
            errors.extend(validation.errors)
        if recovery_case.pending_approval is not None:
            errors.append("Mandatory approval is still pending.")
        if validation.requires_approval and not any(
            approval.status is ApprovalStatus.APPROVED and approval.plan_id == plan.plan_id
            for approval in recovery_case.approval_history
        ):
            errors.append("The active plan lacks its required approval.")

        expected_actions = required_execution_actions(plan, now=now)
        actions = {action.action_id: action for action in recovery_case.execution_history}
        for expected in expected_actions:
            actual = actions.get(expected.action_id)
            if actual is None or actual.status is not ExecutionActionStatus.SUCCEEDED:
                errors.append(f"Required action {expected.action_id} did not succeed.")

        for assumption in recovery_case.assumptions:
            if (
                assumption.status is not PlanAssumptionStatus.INVALIDATED
                or assumption.relevant_window is None
            ):
                continue
            for segment in plan.coverage_segments:
                if (
                    segment.source is CoverageSource.CAREGIVER
                    and segment.assigned_person_id == assumption.subject_id
                    and _overlap(segment.window, assumption.relevant_window)
                ):
                    errors.append(
                        f"Active plan still relies on invalidated assumption "
                        f"{assumption.assumption_id}."
                    )

        if errors:
            return CompletionVerificationResult(
                verified=False,
                errors=errors,
                recovery_case=recovery_case,
            )

        event_ids = {event.event_id for event in recovery_case.events}
        events = recovery_case.events.copy()
        verified_event_id = f"completion-verified:{plan.plan_id}"
        if verified_event_id not in event_ids:
            events.append(
                RecoveryEvent(
                    event_id=verified_event_id,
                    event_type=RecoveryEventType.COMPLETION_VERIFIED,
                    occurred_at=now,
                    details={"plan_id": plan.plan_id},
                )
            )
            events.append(
                RecoveryEvent(
                    event_id=f"case-resolved:{recovery_case.case_id}",
                    event_type=RecoveryEventType.CASE_RESOLVED,
                    occurred_at=now,
                    details={"plan_id": plan.plan_id},
                )
            )
        updated = recovery_case.model_copy(
            update={
                "status": RecoveryStatus.RESOLVED,
                "completion_verified_at": now,
                "events": events,
                "updated_at": now,
            }
        )
        saved = self._repository.save(updated, expected_version=recovery_case.version)
        return CompletionVerificationResult(
            verified=True,
            recovery_case=saved,
        )


def _overlap(left, right) -> bool:
    return left.start < right.end and right.start < left.end
