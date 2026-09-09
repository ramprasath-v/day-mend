"""Live local proof for the complete opt-in three-agent recovery lifecycle."""

import json
import sys
from datetime import datetime
from time import perf_counter
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.agent.config import AgentArchitecture, RecoveryAgentConfig
from app.application import (
    ApprovalCommand,
    ApprovalDecision,
    EventCommand,
    RecoveryApplicationService,
    StartRecoveryCommand,
    StrandsRecoveryPlanningGateway,
)
from app.models import CoverageWindow, RecoveryEventType, RecoveryStatus
from app.repositories import InMemoryRecoveryCaseRepository

PACIFIC = ZoneInfo("America/Los_Angeles")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 27, hour, minute, tzinfo=PACIFIC)


def _json_default(value: Any) -> str:
    return str(value)


def main() -> int:
    """Run Orchestrator → Planner twice, then prove approval and deterministic completion."""

    initial_only = "--initial-only" in sys.argv[1:]
    config = RecoveryAgentConfig.from_environment()
    case_id = f"daymend-multi-{uuid4()}"
    if config.architecture is not AgentArchitecture.MULTI_RESEARCH:
        print(
            "LIVE SMOKE REQUIRES DAYMEND_AGENT_ARCHITECTURE=multi_research",
            file=sys.stderr,
        )
        return 1

    times = iter([at(7, 10), at(9, 10), at(9, 15), at(9, 20), at(9, 25)])
    ids = iter([case_id, f"{case_id}:grandma-declined"])
    repository = InMemoryRecoveryCaseRepository()
    gateway = StrandsRecoveryPlanningGateway(config)
    service = RecoveryApplicationService(
        repository,
        gateway,
        clock=lambda: next(times),
        id_factory=lambda: next(ids),
    )

    try:
        initial_started = perf_counter()
        plan_a_case = service.start_recovery(
            StartRecoveryCommand(
                disruption_type="CHILDCARE_UNAVAILABLE",
                occurred_at=at(7, 2),
                caregiver_id="nanny",
                message="I'm sick and can't come today.",
            )
        )
        initial_duration_ms = _duration_ms(initial_started)
        initial = gateway.last_initial_result
        if initial is None or initial.final_plan is None or gateway.last_initial_brief is None:
            raise RuntimeError("multi-agent initial planning diagnostics were not captured")
        if initial_only:
            print(
                json.dumps(
                    {
                        "architecture": config.architecture,
                        "model_id": config.model_id,
                        "recovery_case_id": case_id,
                        "initial_planning": {
                            "success": True,
                            "duration_ms": initial_duration_ms,
                            "brief": _safe_brief_summary(gateway.last_initial_brief),
                            "plan_id": initial.final_plan.plan_id,
                            "attempts": initial.total_attempts,
                            "validator_diagnostics": _safe_validator_diagnostics(initial),
                            "deterministic_total_cost": initial.deterministic_total_cost,
                            "bedrock_model_calls": initial.model_call_count,
                            "tool_calls": initial.tool_call_count,
                            "tools_used": initial.tools_used,
                        },
                    },
                    indent=2,
                    default=_json_default,
                )
            )
            return 0
        grandma_segments = [
            segment
            for segment in initial.final_plan.coverage_segments
            if segment.assigned_person_id == "grandma"
        ]
        if not grandma_segments:
            raise RuntimeError("valid Plan A did not depend on Grandma; decline smoke cannot run")
        affected_window = CoverageWindow(
            start=min(segment.window.start for segment in grandma_segments),
            end=max(segment.window.end for segment in grandma_segments),
        )

        replan_started = perf_counter()
        after_replan = service.process_event(
            case_id,
            EventCommand(
                event_type=RecoveryEventType.CAREGIVER_DECLINED,
                caregiver_id="grandma",
                occurred_at=at(8, 20),
                relevant_window=affected_window,
                message="Sorry, I can't help today.",
                expected_version=plan_a_case.version,
            ),
        )
        replan_duration_ms = _duration_ms(replan_started)
        replan = gateway.last_replanning_result
        if replan is None or replan.final_plan is None or gateway.last_replanning_brief is None:
            raise RuntimeError("multi-agent replanning diagnostics were not captured")
        if (
            after_replan.status is RecoveryStatus.APPROVAL_REQUIRED
            and after_replan.pending_approval is not None
        ):
            completion_started = perf_counter()
            resolved = service.decide_approval(
                case_id,
                after_replan.pending_approval.approval_id,
                ApprovalCommand(
                    decision=ApprovalDecision.APPROVE,
                    expected_version=after_replan.version,
                ),
            )
            completion_duration_ms = _duration_ms(completion_started)
            approval_outcome = {
                "required": True,
                "approval_id": resolved.approval_history[-1].approval_id,
                "status": resolved.approval_history[-1].status,
            }
        elif after_replan.status is RecoveryStatus.RESOLVED:
            resolved = after_replan
            completion_duration_ms = 0
            approval_outcome = {"required": False, "status": "NOT_REQUIRED"}
        else:
            raise RuntimeError("valid Plan B reached neither deterministic approval nor completion")
        if resolved.status is not RecoveryStatus.RESOLVED:
            raise RuntimeError("deterministic completion did not resolve the recovery case")
    except Exception as exc:  # noqa: BLE001 - smoke must surface provider failures.
        diagnostics = {
            "initial": _safe_validator_diagnostics(gateway.last_initial_result),
            "replanning": _safe_validator_diagnostics(gateway.last_replanning_result),
        }
        print(
            "IMPLEMENTED — LIVE MULTI-AGENT SMOKE FAILED\n"
            f"model_id: {config.model_id}\n"
            f"case_id: {case_id}\n"
            f"error: {type(exc).__name__}: {exc}\n"
            f"safe_validator_diagnostics: {json.dumps(diagnostics, default=_json_default)}",
            file=sys.stderr,
        )
        return 1

    output = {
        "architecture": config.architecture,
        "model_id": config.model_id,
        "repository": "in-memory local smoke",
        "recovery_case_id": case_id,
        "initial_planning": {
            "duration_ms": initial_duration_ms,
            "brief": _safe_brief_summary(gateway.last_initial_brief),
            "plan_id": initial.final_plan.plan_id,
            "attempts": initial.total_attempts,
            "validator_diagnostics": _safe_validator_diagnostics(initial),
            "deterministic_total_cost": initial.deterministic_total_cost,
            "orchestrator_invocations": initial.orchestrator_invocation_count,
            "planner_invocations": initial.planner_invocation_count,
            "bedrock_model_calls": initial.model_call_count,
            "tool_calls": initial.tool_call_count,
            "tools_used": initial.tools_used,
        },
        "world_state_change": {
            "caregiver": "grandma",
            "event_id": replan.triggering_event.event_id,
            "affected_windows": [
                window.model_dump(mode="json") for window in replan.uncovered_windows
            ],
            "invalidated_assumptions": [
                {
                    "assumption_id": assumption.assumption_id,
                    "subject_id": assumption.subject_id,
                }
                for assumption in replan.invalidated_assumptions
            ],
            "impacted_segment_ids": [segment.segment_id for segment in replan.impacted_segments],
            "preserved_segment_ids": [segment.segment_id for segment in replan.preserved_segments],
        },
        "replanning": {
            "duration_ms": replan_duration_ms,
            "brief": _safe_brief_summary(gateway.last_replanning_brief),
            "plan_id": replan.final_plan.plan_id,
            "attempts": replan.total_attempts,
            "validator_diagnostics": _safe_validator_diagnostics(replan),
            "deterministic_total_cost": replan.deterministic_total_cost,
            "orchestrator_invocations": replan.orchestrator_invocation_count,
            "planner_invocations": replan.planner_invocation_count,
            "research_agent_invocations": replan.research_agent_invocation_count,
            "researched_candidate_id": (
                replan.researched_candidate.candidate_id
                if replan.researched_candidate is not None
                else None
            ),
            "bedrock_model_calls": replan.model_call_count,
            "tool_calls": replan.tool_call_count,
            "tools_used": replan.tools_used,
        },
        "approval_and_completion": {
            "duration_ms": completion_duration_ms,
            "automatic_spend_limit": resolved.family_policy.automatic_spend_limit,
            "requires_approval": replan.requires_approval,
            "approval": approval_outcome,
            "execution_action_count": len(resolved.execution_history),
            "execution_actions": [
                {
                    "action_id": action.action_id,
                    "action_type": action.action_type,
                    "status": action.status,
                }
                for action in resolved.execution_history
            ],
            "all_actions_succeeded": all(
                action.status.value == "SUCCEEDED" for action in resolved.execution_history
            ),
            "completion_verified": resolved.completion_verified_at is not None,
            "final_status": resolved.status,
            "version": resolved.version,
            "plan_history_ids": [plan.plan_id for plan in resolved.previous_plans],
            "same_recovery_case_id": resolved.case_id == case_id,
        },
        "totals": {
            "orchestrator_invocations": (
                initial.orchestrator_invocation_count + replan.orchestrator_invocation_count
            ),
            "planner_invocations": (
                initial.planner_invocation_count + replan.planner_invocation_count
            ),
            "research_agent_invocations": (
                initial.research_agent_invocation_count + replan.research_agent_invocation_count
            ),
            "bedrock_model_calls": initial.model_call_count + replan.model_call_count,
            "tool_calls": initial.tool_call_count + replan.tool_call_count,
        },
    }
    print(json.dumps(output, indent=2, default=_json_default))
    return 0


def _duration_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)


def _safe_brief_summary(brief) -> dict[str, Any]:
    """Expose factual brief scope without event messages or model reasoning."""

    event = brief.triggering_event
    return {
        "recovery_case_id": brief.recovery_case_id,
        "planning_mode": brief.planning_mode,
        "planning_required": brief.planning_required,
        "objective": brief.objective,
        "triggering_event": (
            {
                "event_id": event.event_id,
                "event_type": event.event_type,
                "caregiver_id": event.caregiver_id,
                "relevant_window": (
                    event.relevant_window.model_dump(mode="json")
                    if event.relevant_window is not None
                    else None
                ),
            }
            if event is not None
            else None
        ),
        "current_active_plan_id": brief.current_active_plan_id,
        "current_recovery_status": brief.current_recovery_status,
        "invalidated_assumption_ids": brief.invalidated_assumption_ids,
        "required_coverage_window": brief.required_coverage_window.model_dump(mode="json"),
        "affected_windows": [window.model_dump(mode="json") for window in brief.affected_windows],
        "preserved_segment_ids": [segment.segment_id for segment in brief.preserved_segments],
        "excluded_caregiver_ids": brief.excluded_caregiver_ids,
        "relevant_constraint_categories": brief.relevant_constraint_categories,
    }


def _safe_validator_diagnostics(result) -> list[dict[str, Any]]:
    """Return allow-listed deterministic findings without prompts or model reasoning."""

    if result is None:
        return []
    diagnostics: list[dict[str, Any]] = []
    attempts = getattr(result, "attempts", None)
    if attempts is None:
        attempts = result.planning_attempts
    for attempt in attempts:
        segments = {
            segment.segment_id: segment for segment in attempt.proposed_plan.coverage_segments
        }
        for issue in attempt.validation.issues:
            diagnostic: dict[str, Any] = {
                "attempt_number": attempt.attempt_number,
                "issue_code": issue.code.value,
                "message": issue.message,
            }
            if issue.subject_id is not None:
                diagnostic["subject_id"] = issue.subject_id
            if issue.segment_id is not None:
                diagnostic["segment_id"] = issue.segment_id
                segment = segments.get(issue.segment_id)
                if segment is not None:
                    diagnostic["affected_window"] = segment.window.model_dump(mode="json")
                    diagnostic["assigned_person_id"] = segment.assigned_person_id
            if issue.event_id is not None:
                diagnostic["event_id"] = issue.event_id
            diagnostics.append(diagnostic)
    return diagnostics


if __name__ == "__main__":
    raise SystemExit(main())
