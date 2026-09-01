"""Live Milestone 3 smoke: persist, approve, resume, execute, verify, reload."""

import json
import os
import sys
from datetime import datetime
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.agent.config import RecoveryAgentConfig
from app.agent.replanning_demo import run_live_replanning
from app.repositories import (
    DynamoDBRecoveryCaseRepository,
    InMemoryRecoveryCaseRepository,
    ensure_recovery_case_table,
)
from app.services import (
    ApprovalService,
    CompletionVerifier,
    RecoveryExecutionService,
    apply_caregiver_decline_to_scenario,
)

PACIFIC = ZoneInfo("America/Los_Angeles")


def _json_default(value: Any) -> str:
    return str(value)


def main() -> int:
    """Prove approval continuity across persisted process-boundary reloads."""

    config = RecoveryAgentConfig.from_environment()
    case_id = f"daymend-m3-{uuid4()}"
    table_name = os.getenv("DAYMEND_RECOVERY_TABLE")
    try:
        base_scenario, _, replan = run_live_replanning(
            config,
            case_id=case_id,
            progress=lambda message: print(f"stage: {message}", file=sys.stderr, flush=True),
        )
        if replan.final_plan is None or not replan.final_validation.valid:
            raise RuntimeError("Milestone 3 requires a deterministically valid Plan B")
        updated_scenario = apply_caregiver_decline_to_scenario(
            base_scenario,
            replan.triggering_event,
        )

        if table_name:
            ensure_recovery_case_table(table_name=table_name, region_name=config.region_name)
            repository = DynamoDBRecoveryCaseRepository(
                table_name=table_name,
                region_name=config.region_name,
            )
        else:
            repository = InMemoryRecoveryCaseRepository()

        approval_service = ApprovalService(
            repository,
            id_factory=lambda: f"approval:{case_id}:{replan.final_plan.plan_id}",
        )
        gated = approval_service.apply_autonomy_gate(
            replan.recovery_case,
            replan.final_validation,
            updated_scenario.policy,
            now=datetime(2026, 8, 27, 9, 15, tzinfo=PACIFIC),
        )
        if not gated.approval_required or gated.approval_request is None:
            raise RuntimeError("Live Plan B did not cross the deterministic autonomy boundary")
        print("stage: approval_required_persisted", file=sys.stderr, flush=True)

        if table_name:
            restarted_repository = DynamoDBRecoveryCaseRepository(
                table_name=table_name,
                region_name=config.region_name,
            )
        else:
            restarted_repository = repository
        reloaded_before_approval = restarted_repository.get(case_id)
        print("stage: process_boundary_reloaded", file=sys.stderr, flush=True)
        decision = ApprovalService(restarted_repository).approve(
            case_id,
            gated.approval_request.approval_id,
            now=datetime(2026, 8, 27, 9, 20, tzinfo=PACIFIC),
        )
        execution = RecoveryExecutionService(restarted_repository).execute(
            case_id,
            updated_scenario.policy,
            now=datetime(2026, 8, 27, 9, 25, tzinfo=PACIFIC),
        )
        completion = CompletionVerifier(restarted_repository).verify_and_resolve(
            case_id,
            updated_scenario,
            now=datetime(2026, 8, 27, 9, 30, tzinfo=PACIFIC),
        )
        final_repository = (
            DynamoDBRecoveryCaseRepository(
                table_name=table_name,
                region_name=config.region_name,
            )
            if table_name
            else restarted_repository
        )
        final_case = final_repository.get(case_id)
        print("stage: resolved_case_reloaded", file=sys.stderr, flush=True)
    except Exception as exc:  # noqa: BLE001 - smoke must expose provider/storage blockers.
        print(
            "IMPLEMENTED — LIVE SMOKE BLOCKED\n"
            f"model_id: {config.model_id}\n"
            f"table_name: {table_name or 'in-memory'}\n"
            f"case_id: {case_id}\n"
            f"error: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    output = {
        "model_id": config.model_id,
        "repository": {
            "type": "DynamoDB" if table_name else "in-memory",
            "table_name": table_name,
        },
        "autonomy_gate": {
            "case_id_before_persistence": replan.recovery_case.case_id,
            "plan_id": replan.final_plan.plan_id,
            "plan_valid": replan.final_validation.valid,
            "deterministic_total_cost": replan.deterministic_total_cost,
            "automatic_spend_limit": updated_scenario.policy.automatic_spend_limit,
            "requires_approval": replan.requires_approval,
            "approval_request": gated.approval_request.model_dump(mode="json"),
            "persisted_status": gated.recovery_case.status.value,
            "persisted_version": gated.recovery_case.version,
        },
        "process_boundary_reload": {
            "case_id_after_reload": reloaded_before_approval.case_id,
            "status": reloaded_before_approval.status.value,
            "version": reloaded_before_approval.version,
        },
        "approval": {
            "status": decision.approval.status.value,
            "case_status": decision.recovery_case.status.value,
            "same_case_id": decision.recovery_case.case_id == case_id,
        },
        "execution": {
            "succeeded": execution.succeeded,
            "actions": [action.model_dump(mode="json") for action in execution.actions],
            "case_status_before_verification": execution.recovery_case.status.value,
        },
        "completion": {
            "verified": completion.verified,
            "errors": completion.errors,
            "final_status": final_case.status.value,
        },
        "final_persistence_proof": {
            "same_case_id": final_case.case_id == case_id,
            "version": final_case.version,
            "active_plan_id": (
                final_case.active_recovery_plan.plan_id
                if final_case.active_recovery_plan is not None
                else None
            ),
            "plan_history_ids": [plan.plan_id for plan in final_case.previous_plans],
            "caregiver_decline_retained": any(
                event.event_type.value == "CAREGIVER_DECLINED" for event in final_case.events
            ),
            "invalidated_assumption_count": sum(
                assumption.status.value == "INVALIDATED" for assumption in final_case.assumptions
            ),
            "approval_history": [
                approval.model_dump(mode="json") for approval in final_case.approval_history
            ],
            "execution_action_count": len(final_case.execution_history),
            "structured_event_types": [event.event_type.value for event in final_case.events],
            "completion_verified_at": final_case.completion_verified_at,
        },
    }
    print(json.dumps(output, indent=2, default=_json_default))
    return 0 if completion.verified else 2


if __name__ == "__main__":
    raise SystemExit(main())
