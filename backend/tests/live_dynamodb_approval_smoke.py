"""Opt-in real DynamoDB smoke for Milestone 3 deterministic lifecycle services.

This harness uses the tested Milestone 2 aggregate fixture. It proves live storage and workflow
behavior, not fresh LLM behavior; the separate approval_demo runs the combined agent path.
"""

import json
from uuid import uuid4

from app.repositories import DynamoDBRecoveryCaseRepository
from app.services import ApprovalService, CompletionVerifier, RecoveryExecutionService
from tests.milestone2_helpers import at
from tests.milestone3_helpers import milestone3_case


def main() -> int:
    recovery_case, scenario, validation = milestone3_case()
    recovery_case = recovery_case.model_copy(update={"case_id": f"daymend-m3-live-{uuid4()}"})
    repository = DynamoDBRecoveryCaseRepository()
    gated = ApprovalService(repository, id_factory=lambda: "approval-live").apply_autonomy_gate(
        recovery_case,
        validation,
        scenario.policy,
        now=at(9, 15),
    )
    reloaded = DynamoDBRecoveryCaseRepository().get(recovery_case.case_id)
    approved = ApprovalService(DynamoDBRecoveryCaseRepository()).approve(
        recovery_case.case_id,
        "approval-live",
        now=at(9, 20),
    )
    executed = RecoveryExecutionService(DynamoDBRecoveryCaseRepository()).execute(
        recovery_case.case_id,
        scenario.policy,
        now=at(9, 25),
    )
    verified = CompletionVerifier(DynamoDBRecoveryCaseRepository()).verify_and_resolve(
        recovery_case.case_id,
        scenario,
        now=at(9, 30),
    )
    final = DynamoDBRecoveryCaseRepository().get(recovery_case.case_id)
    output = {
        "table": repository.table_name,
        "case_id_before": recovery_case.case_id,
        "case_id_after": final.case_id,
        "plan_id": final.active_recovery_plan.plan_id,
        "cost": validation.deterministic_total_cost,
        "limit": scenario.policy.automatic_spend_limit,
        "requires_approval": validation.requires_approval,
        "persisted_status": gated.recovery_case.status.value,
        "reload_status": reloaded.status.value,
        "approval_status": approved.approval.status.value,
        "execution_succeeded": executed.succeeded,
        "action_count": len(executed.actions),
        "completion_verified": verified.verified,
        "final_status": final.status.value,
        "plan_history": [plan.plan_id for plan in final.previous_plans],
        "caregiver_decline_retained": any(
            event.event_type.value == "CAREGIVER_DECLINED" for event in final.events
        ),
        "invalidated_assumptions": sum(
            assumption.status.value == "INVALIDATED" for assumption in final.assumptions
        ),
        "approval_history": [approval.status.value for approval in final.approval_history],
        "execution_history": len(final.execution_history),
        "version": final.version,
    }
    print(json.dumps(output, indent=2, default=str))
    return 0 if verified.verified else 2


if __name__ == "__main__":
    raise SystemExit(main())
