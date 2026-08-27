"""Local real-agent smoke entrypoint for the Milestone 1 recovery loop."""

import json
import sys
from typing import Any

from app.agent.config import RecoveryAgentConfig
from app.agent.recovery_agent import run_initial_planning
from app.fixtures import get_demo_scenario
from app.services import ValidationErrorCode


def _json_default(value: Any) -> str:
    return str(value)


def main() -> int:
    """Run the real bounded Strands initial-planning and validation loop."""

    scenario = get_demo_scenario()
    config = RecoveryAgentConfig.from_environment()
    try:
        planning_run = run_initial_planning(scenario.disruption, scenario, config)
    except Exception as exc:  # noqa: BLE001 - CLI must report provider failures clearly.
        print(
            "IMPLEMENTED — LIVE SMOKE BLOCKED\n"
            f"model_id: {config.model_id}\n"
            f"error: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    final_validation = planning_run.attempts[-1].validation
    final_codes = {issue.code for issue in final_validation.issues}
    output = {
        "model_id": planning_run.model_id,
        "tools_used": list(planning_run.tools_used),
        "planning_attempts": [
            {
                "attempt_number": attempt.attempt_number,
                "proposal": attempt.proposed_plan.model_dump(mode="json"),
                "validation": attempt.validation.model_dump(mode="json"),
            }
            for attempt in planning_run.attempts
        ],
        "final_result": {
            "success": planning_run.success,
            "total_attempts": planning_run.total_attempts,
            "final_plan": (
                planning_run.final_plan.model_dump(mode="json")
                if planning_run.final_plan is not None
                else None
            ),
            "deterministic_total_cost": planning_run.deterministic_total_cost,
            "requires_approval": planning_run.requires_approval,
            "final_errors": [issue.model_dump(mode="json") for issue in planning_run.final_errors],
            "safety_summary": {
                "full_coverage": not bool(
                    final_codes
                    & {
                        ValidationErrorCode.COVERAGE_GAP,
                        ValidationErrorCode.COVERAGE_OVERLAP,
                        ValidationErrorCode.HANDOFF_INFEASIBLE,
                    }
                ),
                "caregiver_availability_compliant": (
                    ValidationErrorCode.CAREGIVER_UNAVAILABLE not in final_codes
                ),
                "parent_calendar_feasible": not bool(
                    final_codes
                    & {
                        ValidationErrorCode.PARENT_CRITICAL_CONFLICT,
                        ValidationErrorCode.MOVABLE_EVENT_CHANGE_REQUIRED,
                        ValidationErrorCode.UNSUPPORTED_CALENDAR_EVENT,
                    }
                ),
            },
        },
    }
    print(json.dumps(output, indent=2, default=_json_default))
    return 0 if planning_run.success else 2


if __name__ == "__main__":
    raise SystemExit(main())
