"""Live Milestone 2 smoke: valid Plan A, caregiver decline, and validated Plan B."""

import json
import sys
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.agent.config import RecoveryAgentConfig
from app.agent.recovery_agent import (
    ToolInvocationRecorder,
    build_recovery_agent,
    run_initial_planning_session,
)
from app.agent.replanning import process_external_event
from app.fixtures import get_demo_scenario
from app.models import CoverageWindow, RecoveryEvent, RecoveryEventType
from app.services import create_active_recovery_case

PACIFIC = ZoneInfo("America/Los_Angeles")


def _json_default(value: Any) -> str:
    return str(value)


def main() -> int:
    """Run the real same-agent Plan A → decline → Plan B workflow."""

    scenario = get_demo_scenario()
    config = RecoveryAgentConfig.from_environment()
    recorder = ToolInvocationRecorder()
    agent = build_recovery_agent(config, recorder)
    try:
        initial = run_initial_planning_session(
            agent=agent,
            recorder=recorder,
            disruption=scenario.disruption,
            scenario=scenario,
            model_id=config.model_id,
        )
        if not initial.success or initial.final_plan is None:
            print(
                json.dumps(
                    {
                        "model_id": config.model_id,
                        "success": False,
                        "stage": "initial_planning",
                        "initial_result": initial.model_dump(mode="json"),
                    },
                    indent=2,
                    default=_json_default,
                )
            )
            return 2

        grandma_segments = [
            segment
            for segment in initial.final_plan.coverage_segments
            if segment.assigned_person_id == "grandma"
        ]
        if not grandma_segments:
            print(
                json.dumps(
                    {
                        "model_id": config.model_id,
                        "success": False,
                        "stage": "demo_precondition",
                        "message": "Live valid Plan A did not depend on Grandma.",
                        "plan_a": initial.final_plan.model_dump(mode="json"),
                    },
                    indent=2,
                )
            )
            return 3

        affected_window = CoverageWindow(
            start=min(segment.window.start for segment in grandma_segments),
            end=max(segment.window.end for segment in grandma_segments),
        )
        case = create_active_recovery_case(
            case_id="demo-recovery-case",
            disruption=scenario.disruption,
            validated_plan=initial.final_plan,
            required_coverage=scenario.required_coverage,
            now=datetime(2026, 8, 27, 7, 10, tzinfo=PACIFIC),
        )
        event = RecoveryEvent(
            event_id="demo-grandma-declined",
            event_type=RecoveryEventType.CAREGIVER_DECLINED,
            caregiver_id="grandma",
            relevant_window=affected_window,
            occurred_at=datetime(2026, 8, 27, 9, 5, tzinfo=PACIFIC),
            message="Sorry, I can't help today.",
        )
        replan = process_external_event(
            recovery_case=case,
            event=event,
            scenario=scenario,
            agent=agent,
            recorder=recorder,
        )
    except Exception as exc:  # noqa: BLE001 - smoke must surface provider/runtime failures.
        print(
            "IMPLEMENTED — LIVE SMOKE BLOCKED\n"
            f"model_id: {config.model_id}\n"
            f"error: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    output = {
        "model_id": config.model_id,
        "initial_planning": {
            "success": initial.success,
            "tools_used": initial.tools_used,
            "attempts": initial.total_attempts,
            "plan_a": initial.final_plan.model_dump(mode="json"),
        },
        "world_state_change": {
            "event_received": replan.triggering_event.model_dump(mode="json"),
            "invalidated_assumptions": [
                assumption.model_dump(mode="json") for assumption in replan.invalidated_assumptions
            ],
            "impacted_segments": [
                segment.model_dump(mode="json") for segment in replan.impacted_segments
            ],
            "uncovered_windows": [
                window.model_dump(mode="json") for window in replan.uncovered_windows
            ],
            "preserved_segments": [
                segment.model_dump(mode="json") for segment in replan.preserved_segments
            ],
            "status_history": [status.value for status in replan.status_history],
        },
        "replanning": {
            "same_agent": True,
            "tools_used_after_world_change": replan.tools_used,
            "attempts": [
                {
                    "attempt_number": attempt.attempt_number,
                    "proposal": attempt.proposed_plan.model_dump(mode="json"),
                    "validation": {
                        "valid": attempt.validation.valid,
                        "issues": [
                            issue.model_dump(mode="json") for issue in attempt.validation.issues
                        ],
                        "deterministic_total_cost": (attempt.validation.deterministic_total_cost),
                        "requires_approval": attempt.validation.requires_approval,
                    },
                }
                for attempt in replan.planning_attempts
            ],
            "success": replan.success,
            "plan_b": (
                replan.final_plan.model_dump(mode="json") if replan.final_plan is not None else None
            ),
            "final_validation": replan.final_validation.model_dump(mode="json"),
            "deterministic_total_cost": replan.deterministic_total_cost,
            "requires_approval": replan.requires_approval,
            "plan_a_history": [
                plan.model_dump(mode="json") for plan in replan.recovery_case.previous_plans
            ],
            "active_plan_id": (
                replan.recovery_case.active_recovery_plan.plan_id
                if replan.recovery_case.active_recovery_plan is not None
                else None
            ),
        },
    }
    print(json.dumps(output, indent=2, default=_json_default))
    return 0 if replan.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
