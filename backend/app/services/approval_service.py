"""Deterministic autonomy gating and idempotent human approval decisions."""

from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from app.models import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalType,
    ContractModel,
    FamilyPolicy,
    RecoveryCase,
    RecoveryEvent,
    RecoveryEventType,
    RecoveryStatus,
)
from app.repositories import RecoveryCaseRepository
from app.services.plan_validator import PlanValidationResult


class WorkflowInvariantError(RuntimeError):
    """The requested workflow transition would violate deterministic case state."""


class AutonomyGateResult(ContractModel):
    """Persisted outcome of deterministic policy evaluation for a valid plan."""

    recovery_case: RecoveryCase
    approval_required: bool
    approval_request: ApprovalRequest | None = None


class ApprovalDecisionResult(ContractModel):
    """Observable, idempotent result of an approve or reject command."""

    recovery_case: RecoveryCase
    approval: ApprovalRequest
    idempotent: bool = False


class ApprovalService:
    """Create autonomy-boundary requests and apply later human decisions."""

    def __init__(
        self,
        repository: RecoveryCaseRepository,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._id_factory = id_factory or (lambda: str(uuid4()))

    def apply_autonomy_gate(
        self,
        recovery_case: RecoveryCase,
        validation: PlanValidationResult,
        policy: FamilyPolicy,
        *,
        now: datetime,
    ) -> AutonomyGateResult:
        """Persist a pause only when deterministic policy requires human permission."""

        plan = recovery_case.active_recovery_plan
        if plan is None or not validation.valid:
            raise WorkflowInvariantError("only a deterministically valid active plan may proceed")
        if validation.validated_plan.plan_id != plan.plan_id:
            raise WorkflowInvariantError("validation does not apply to the active plan")
        if validation.requires_approval != (
            validation.deterministic_total_cost > policy.automatic_spend_limit
        ):
            raise WorkflowInvariantError("approval requirement disagrees with deterministic policy")

        if not validation.requires_approval:
            updated = recovery_case.model_copy(
                update={
                    "status": RecoveryStatus.EXECUTING,
                    "active_recovery_plan": validation.validated_plan,
                    "updated_at": now,
                }
            )
            saved = _save(self._repository, updated, recovery_case.version)
            return AutonomyGateResult(
                recovery_case=saved,
                approval_required=False,
            )

        pending = recovery_case.pending_approval
        if (
            pending is not None
            and pending.status is ApprovalStatus.PENDING
            and pending.plan_id == plan.plan_id
        ):
            return AutonomyGateResult(
                recovery_case=recovery_case,
                approval_required=True,
                approval_request=pending,
            )

        approval = ApprovalRequest(
            approval_id=self._id_factory(),
            recovery_case_id=recovery_case.case_id,
            approval_type=ApprovalType.SPEND_ABOVE_AUTONOMY_LIMIT,
            plan_id=plan.plan_id,
            reason=(
                f"Deterministic plan cost {validation.deterministic_total_cost} exceeds the "
                f"automatic-spend limit {policy.automatic_spend_limit}."
            ),
            summary="Paid backup care is needed to preserve today's critical commitments.",
            consequence="Approving permits simulated execution of the active recovery plan.",
            requested_at=now,
            amount=validation.deterministic_total_cost,
            currency=policy.currency,
        )
        event = RecoveryEvent(
            event_id=f"approval-requested:{approval.approval_id}",
            event_type=RecoveryEventType.APPROVAL_REQUESTED,
            occurred_at=now,
            details={
                "approval_id": approval.approval_id,
                "plan_id": plan.plan_id,
                "amount": str(approval.amount),
                "currency": approval.currency,
            },
        )
        updated = recovery_case.model_copy(
            update={
                "status": RecoveryStatus.APPROVAL_REQUIRED,
                "active_recovery_plan": validation.validated_plan,
                "pending_approval": approval,
                "approval_history": [*recovery_case.approval_history, approval],
                "events": [*recovery_case.events, event],
                "updated_at": now,
            }
        )
        saved = _save(self._repository, updated, recovery_case.version)
        return AutonomyGateResult(
            recovery_case=saved,
            approval_required=True,
            approval_request=approval,
        )

    def approve(
        self,
        case_id: str,
        approval_id: str,
        *,
        now: datetime,
    ) -> ApprovalDecisionResult:
        return self._decide(case_id, approval_id, ApprovalStatus.APPROVED, now=now)

    def reject(
        self,
        case_id: str,
        approval_id: str,
        *,
        now: datetime,
        reason: str | None = None,
    ) -> ApprovalDecisionResult:
        return self._decide(
            case_id,
            approval_id,
            ApprovalStatus.REJECTED,
            now=now,
            reason=reason,
        )

    def _decide(
        self,
        case_id: str,
        approval_id: str,
        decision: ApprovalStatus,
        *,
        now: datetime,
        reason: str | None = None,
    ) -> ApprovalDecisionResult:
        recovery_case = self._repository.get(case_id)
        matching = [
            approval
            for approval in recovery_case.approval_history
            if approval.approval_id == approval_id
        ]
        if not matching:
            raise WorkflowInvariantError(
                f"approval {approval_id} does not belong to case {case_id}"
            )
        approval = matching[-1]
        if approval.status is decision:
            return ApprovalDecisionResult(
                recovery_case=recovery_case,
                approval=approval,
                idempotent=True,
            )
        if approval.status is not ApprovalStatus.PENDING:
            raise WorkflowInvariantError(
                f"cannot change finalized approval {approval_id} from {approval.status}"
            )
        if recovery_case.status is not RecoveryStatus.APPROVAL_REQUIRED:
            raise WorkflowInvariantError("case is not waiting for approval")
        if recovery_case.pending_approval is None:
            raise WorkflowInvariantError("case has no pending approval")
        if recovery_case.pending_approval.approval_id != approval_id:
            raise WorkflowInvariantError("approval is stale or is not the current request")
        plan = recovery_case.active_recovery_plan
        if plan is None or approval.plan_id != plan.plan_id:
            raise WorkflowInvariantError("approval does not authorize the current active plan")

        decided = approval.model_copy(update={"status": decision, "decided_at": now})
        history = [
            decided if item.approval_id == approval_id else item
            for item in recovery_case.approval_history
        ]
        approved = decision is ApprovalStatus.APPROVED
        event = RecoveryEvent(
            event_id=f"approval-{decision.value.lower()}:{approval_id}",
            event_type=(
                RecoveryEventType.APPROVAL_APPROVED
                if approved
                else RecoveryEventType.APPROVAL_REJECTED
            ),
            occurred_at=now,
            details={
                "approval_id": approval_id,
                "plan_id": approval.plan_id,
                "reason": reason,
            },
        )
        updated = recovery_case.model_copy(
            update={
                "status": RecoveryStatus.EXECUTING if approved else RecoveryStatus.REPLANNING,
                "pending_approval": None,
                "approval_history": history,
                "events": [*recovery_case.events, event],
                "latest_replan_trigger_event_id": (
                    recovery_case.latest_replan_trigger_event_id if approved else event.event_id
                ),
                "updated_at": now,
            }
        )
        saved = self._repository.save(updated, expected_version=recovery_case.version)
        return ApprovalDecisionResult(recovery_case=saved, approval=decided)


def _save(
    repository: RecoveryCaseRepository,
    recovery_case: RecoveryCase,
    previous_version: int,
) -> RecoveryCase:
    expected_version = previous_version if previous_version > 0 else None
    return repository.save(recovery_case, expected_version=expected_version)
