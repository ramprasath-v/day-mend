"""Explicit simulated recovery actions with approval and idempotency guards."""

from datetime import datetime

from app.models import (
    ApprovalStatus,
    ContractModel,
    CoverageSource,
    ExecutionAction,
    ExecutionActionStatus,
    ExecutionActionType,
    FamilyPolicy,
    PlanValidationState,
    RecoveryCase,
    RecoveryEvent,
    RecoveryEventType,
    RecoveryPlan,
    RecoveryStatus,
)
from app.repositories import RecoveryCaseRepository
from app.services.approval_service import WorkflowInvariantError


class ExecutionResult(ContractModel):
    """Persisted outcome of one idempotent execution request."""

    recovery_case: RecoveryCase
    actions: list[ExecutionAction]
    succeeded: bool
    idempotent: bool = False


class SimulatedExecutionAdapter:
    """Synthetic external systems adapter with injectable deterministic failures."""

    def __init__(self, *, fail_targets: set[str] | None = None) -> None:
        self.fail_targets = fail_targets or set()

    def execute(self, action: ExecutionAction, *, now: datetime) -> ExecutionAction:
        if action.target_id in self.fail_targets:
            return action.model_copy(
                update={
                    "status": ExecutionActionStatus.FAILED,
                    "completed_at": now,
                    "error": f"Synthetic execution failure for {action.target_id}.",
                }
            )
        return action.model_copy(
            update={
                "status": ExecutionActionStatus.SUCCEEDED,
                "completed_at": now,
                "result": "Simulated action completed.",
            }
        )


class RecoveryExecutionService:
    """Run required plan actions once, and only after deterministic authorization."""

    def __init__(
        self,
        repository: RecoveryCaseRepository,
        *,
        adapter: SimulatedExecutionAdapter | None = None,
    ) -> None:
        self._repository = repository
        self._adapter = adapter or SimulatedExecutionAdapter()

    def execute(
        self,
        case_id: str,
        policy: FamilyPolicy,
        *,
        now: datetime,
    ) -> ExecutionResult:
        recovery_case = self._repository.get(case_id)
        plan = recovery_case.active_recovery_plan
        if plan is None or plan.validation_state is not PlanValidationState.VALID:
            raise WorkflowInvariantError("execution requires a deterministically valid active plan")
        if recovery_case.pending_approval is not None:
            raise WorkflowInvariantError("execution is blocked by pending approval")
        if recovery_case.status is not RecoveryStatus.EXECUTING:
            raise WorkflowInvariantError(f"case status {recovery_case.status} cannot execute")
        if plan.estimated_cost > policy.automatic_spend_limit and not any(
            approval.status is ApprovalStatus.APPROVED and approval.plan_id == plan.plan_id
            for approval in recovery_case.approval_history
        ):
            raise WorkflowInvariantError("required current-plan approval has not been granted")

        required = required_execution_actions(plan, now=now)
        existing = {action.action_id: action for action in recovery_case.execution_history}
        if required and all(
            action.action_id in existing
            and existing[action.action_id].status is ExecutionActionStatus.SUCCEEDED
            for action in required
        ):
            return ExecutionResult(
                recovery_case=recovery_case,
                actions=[existing[action.action_id] for action in required],
                succeeded=True,
                idempotent=True,
            )

        events = recovery_case.events.copy()
        start_event_id = f"execution-started:{plan.plan_id}"
        if start_event_id not in {event.event_id for event in events}:
            events.append(
                RecoveryEvent(
                    event_id=start_event_id,
                    event_type=RecoveryEventType.EXECUTION_STARTED,
                    occurred_at=now,
                    details={"plan_id": plan.plan_id},
                )
            )
        history = recovery_case.execution_history.copy()
        completed: list[ExecutionAction] = []
        for action in required:
            prior = existing.get(action.action_id)
            if prior is not None and prior.status is ExecutionActionStatus.SUCCEEDED:
                completed.append(prior)
                continue
            result = self._adapter.execute(action, now=now)
            history = [item for item in history if item.action_id != result.action_id]
            history.append(result)
            completed.append(result)
            events.append(
                RecoveryEvent(
                    event_id=f"action-{result.status.value.lower()}:{result.action_id}",
                    event_type=(
                        RecoveryEventType.ACTION_COMPLETED
                        if result.status is ExecutionActionStatus.SUCCEEDED
                        else RecoveryEventType.ACTION_FAILED
                    ),
                    occurred_at=now,
                    details={
                        "action_id": result.action_id,
                        "plan_id": plan.plan_id,
                        "target_id": result.target_id,
                    },
                )
            )
        succeeded = all(action.status is ExecutionActionStatus.SUCCEEDED for action in completed)
        updated = recovery_case.model_copy(
            update={
                "status": RecoveryStatus.EXECUTING if succeeded else RecoveryStatus.FAILED,
                "execution_history": history,
                "events": events,
                "updated_at": now,
            }
        )
        saved = self._repository.save(updated, expected_version=recovery_case.version)
        return ExecutionResult(
            recovery_case=saved,
            actions=completed,
            succeeded=succeeded,
        )


def required_execution_actions(plan: RecoveryPlan, *, now: datetime) -> list[ExecutionAction]:
    """Derive stable action identities from the active plan without executing anything."""

    actions = [
        ExecutionAction(
            action_id=f"calendar:{plan.plan_id}:{event.event_id}",
            action_type=ExecutionActionType.UPDATE_CALENDAR,
            target_id=event.event_id,
            plan_id=plan.plan_id,
            attempted_at=now,
        )
        for event in plan.calendar_changes
    ]
    actions.extend(
        ExecutionAction(
            action_id=f"caregiver:{plan.plan_id}:{segment.segment_id}",
            action_type=ExecutionActionType.RESERVE_CAREGIVER,
            target_id=segment.assigned_person_id,
            plan_id=plan.plan_id,
            attempted_at=now,
        )
        for segment in plan.coverage_segments
        if segment.source is CoverageSource.CAREGIVER
    )
    return actions
