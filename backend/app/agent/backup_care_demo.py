"""One controlled live Nova proof of conditional three-agent backup-care recovery."""

import json
import sys
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.agent.config import AgentArchitecture, RecoveryAgentConfig
from app.agent.multi_agent_demo import _safe_validator_diagnostics
from app.application import (
    ApprovalCommand,
    ApprovalDecision,
    RecoveryApplicationService,
    StartRecoveryCommand,
    StrandsRecoveryPlanningGateway,
)
from app.fixtures import DemoTimeline, get_backup_care_research_scenario
from app.models import RecoveryStatus
from app.repositories import InMemoryRecoveryCaseRepository


def main() -> int:
    """Research once, plan within the existing cap, approve once, execute, and stop."""

    config = RecoveryAgentConfig.from_environment()
    case_id = f"daymend-research-{uuid4()}"
    if config.architecture is not AgentArchitecture.MULTI_RESEARCH:
        print(
            "LIVE SMOKE REQUIRES DAYMEND_AGENT_ARCHITECTURE=multi_research",
            file=sys.stderr,
        )
        return 1

    repository = InMemoryRecoveryCaseRepository()
    gateway = StrandsRecoveryPlanningGateway(config)
    scenario = get_backup_care_research_scenario()
    timeline = DemoTimeline(scenario.required_coverage.start.date())
    times = iter(
        [
            timeline.at(7, 10),
            timeline.at(7, 11),
            timeline.at(7, 12),
            timeline.at(7, 13),
            timeline.at(7, 14),
        ]
    )
    service = RecoveryApplicationService(
        repository,
        gateway,
        scenario_factory=lambda _care_date=None: scenario,
        clock=lambda: next(times),
        id_factory=lambda: case_id,
    )
    total_started = perf_counter()
    try:
        pending = service.start_recovery(
            StartRecoveryCommand(
                disruption_type="CHILDCARE_UNAVAILABLE",
                occurred_at=timeline.at(7, 2),
                caregiver_id="nanny",
                message="The normal caregiver is unavailable today.",
            )
        )
        planning = gateway.last_initial_result
        research = gateway.last_backup_care_research
        need = gateway.last_recovery_need
        if planning is None or planning.final_plan is None or research is None or need is None:
            raise RuntimeError("three-agent planning diagnostics were not captured")
        if pending.status is not RecoveryStatus.APPROVAL_REQUIRED:
            raise RuntimeError("researched plan did not reach deterministic approval")
        if pending.pending_approval is None:
            raise RuntimeError("approval-required case has no current request")

        approval_reason = pending.pending_approval.reason
        approval_id = pending.pending_approval.approval_id
        resolved = service.decide_approval(
            case_id,
            approval_id,
            ApprovalCommand(
                decision=ApprovalDecision.APPROVE,
                expected_version=pending.version,
            ),
        )
        if resolved.status is not RecoveryStatus.RESOLVED:
            raise RuntimeError("deterministic completion did not resolve the recovery case")
    except Exception as exc:  # noqa: BLE001 - controlled smoke reports provider failures safely.
        print(
            json.dumps(
                {
                    "result": "IMPLEMENTED — LIVE RESEARCH SMOKE FAILED",
                    "model_id": config.model_id,
                    "recovery_case_id": case_id,
                    "error_type": type(exc).__name__,
                    "error": "Live provider or bounded planning step failed.",
                    "safe_validator_diagnostics": _safe_validator_diagnostics(
                        gateway.last_initial_result
                    ),
                },
                indent=2,
                default=str,
            ),
            file=sys.stderr,
        )
        return 1

    total_duration_ms = round((perf_counter() - total_started) * 1000)
    ranked = research.result.ranked_candidates
    active_plan = resolved.active_recovery_plan
    assert active_plan is not None
    researched_id = research.result.recommended_candidate_id
    output = {
        "result": "LIVE RESEARCH LIFECYCLE SUCCEEDED",
        "architecture": config.architecture,
        "model_id": config.model_id,
        "recovery_case_id": case_id,
        "triggering_disruption": "normal caregiver unavailable for required workday coverage",
        "known_options": {
            "insufficient": need.known_options_insufficient,
            "unresolved_windows": [
                window.model_dump(mode="json") for window in need.requested_windows
            ],
            "already_considered_caregiver_ids": need.already_considered_caregiver_ids,
        },
        "agent_counts": {
            "orchestrator_invocations": planning.orchestrator_invocation_count,
            "research_agent_invocations": planning.research_agent_invocation_count,
            "planner_invocations": planning.planner_invocation_count,
        },
        "research": {
            "research_id": research.result.research_id,
            "research_tool_calls": planning.research_tool_call_count,
            "tools_used": research.tools_used,
            "candidate_count": len(research.result.considered_candidate_ids),
            "eligible_candidate_count": len(research.result.eligible_candidate_ids),
            "ranked_candidate_ids": [item.candidate_id for item in ranked],
            "recommended_candidate_id": researched_id,
            "recommendation_fit_summary": next(
                item.fit_summary for item in ranked if item.candidate_id == researched_id
            ),
            "recommendation_tradeoffs": next(
                item.tradeoffs for item in ranked if item.candidate_id == researched_id
            ),
        },
        "planning": {
            "plan_attempts": planning.total_attempts,
            "validator_diagnostics": _safe_validator_diagnostics(planning),
            "accepted_plan_id": active_plan.plan_id,
            "researched_caregiver_used": any(
                segment.assigned_person_id == researched_id
                for segment in active_plan.coverage_segments
            ),
            "deterministic_total_cost": active_plan.estimated_cost,
        },
        "approval": {
            "required": planning.requires_approval,
            "reason": approval_reason,
            "approval_id": approval_id,
            "outcome": resolved.approval_history[-1].status,
            "approved_plan_id": resolved.approval_history[-1].plan_id,
        },
        "execution_and_completion": {
            "action_count": len(resolved.execution_history),
            "all_actions_succeeded": all(
                action.status.value == "SUCCEEDED" for action in resolved.execution_history
            ),
            "completion_verified": resolved.completion_verified_at is not None,
            "final_status": resolved.status,
            "same_recovery_case_id": resolved.case_id == case_id,
            "version": resolved.version,
        },
        "calls_and_latency": {
            "total_bedrock_calls": planning.model_call_count,
            "orchestrator_latency_ms": planning.orchestrator_duration_ms,
            "research_latency_ms": planning.research_duration_ms,
            "planner_latency_ms": planning.planner_duration_ms,
            "total_lifecycle_latency_ms": total_duration_ms,
        },
    }
    print(json.dumps(output, indent=2, default=_json_default))
    return 0


def _json_default(value: Any) -> str:
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
