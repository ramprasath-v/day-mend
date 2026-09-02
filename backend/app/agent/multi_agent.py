"""Two-agent recovery orchestration with deterministic validation and invalidation boundaries."""

from time import perf_counter

from app.agent.config import RecoveryAgentConfig
from app.agent.constraint_planner import (
    ConstraintPlannerLike,
    build_constraint_planner,
    run_constraint_planning,
)
from app.agent.recovery_agent import InitialPlanningResult, ToolInvocationRecorder
from app.agent.recovery_orchestrator import (
    PlanningBrief,
    RecoveryOrchestratorLike,
    build_recovery_orchestrator,
    create_initial_planning_brief,
    create_replanning_brief,
)
from app.agent.replanning import ReplanningResult, build_replanning_result
from app.fixtures import DemoScenario
from app.models import RecoveryCase, RecoveryEvent
from app.observability import log_event
from app.services import PlanInvalidationService, PlanValidator


def run_multi_agent_initial_planning(
    *,
    disruption: str,
    scenario: DemoScenario,
    config: RecoveryAgentConfig,
    orchestrator: RecoveryOrchestratorLike | None = None,
    planner: ConstraintPlannerLike | None = None,
    orchestrator_recorder: ToolInvocationRecorder | None = None,
    planner_recorder: ToolInvocationRecorder | None = None,
    validator: PlanValidator | None = None,
) -> tuple[InitialPlanningResult, PlanningBrief]:
    """Run Orchestrator → Planner for a new disruption and return the transient brief."""

    resolved_orchestrator_recorder = orchestrator_recorder or ToolInvocationRecorder()
    resolved_planner_recorder = planner_recorder or ToolInvocationRecorder()
    resolved_orchestrator = orchestrator or build_recovery_orchestrator(
        config, resolved_orchestrator_recorder
    )
    resolved_planner = planner or build_constraint_planner(config, resolved_planner_recorder)

    mode = "initial"
    log_event(
        "orchestrator_invocation_started",
        architecture="multi",
        agent_role="recovery_orchestrator",
        planning_mode=mode,
        model_id=config.model_id,
    )
    orchestrator_started = perf_counter()
    orchestration = create_initial_planning_brief(
        orchestrator=resolved_orchestrator,
        recorder=resolved_orchestrator_recorder,
        disruption=disruption,
        scenario=scenario,
    )
    log_event(
        "orchestrator_invocation_completed",
        architecture="multi",
        agent_role="recovery_orchestrator",
        planning_mode=mode,
        model_id=config.model_id,
        duration_ms=_duration_ms(orchestrator_started),
        model_call_count=orchestration.model_call_count,
        tool_call_count=len(orchestration.tools_used),
        tools_used=orchestration.tools_used,
        success=True,
    )
    log_event(
        "planner_invocation_started",
        architecture="multi",
        agent_role="constraint_planner",
        planning_mode=mode,
        model_id=config.model_id,
    )
    planner_started = perf_counter()
    planning = run_constraint_planning(
        planner=resolved_planner,
        recorder=resolved_planner_recorder,
        brief=orchestration.brief,
        scenario=scenario,
        model_id=config.model_id,
        validator=validator,
    )
    _log_planner_result(planning, mode=mode, started=planner_started)
    tools_used = [*orchestration.tools_used, *planning.tools_used]
    planning = planning.model_copy(
        update={
            "tools_used": tools_used,
            "tool_call_count": len(tools_used),
            "model_call_count": orchestration.model_call_count + planning.model_call_count,
        }
    )
    return planning, orchestration.brief


def run_multi_agent_replanning(
    *,
    recovery_case: RecoveryCase,
    event: RecoveryEvent,
    scenario: DemoScenario,
    config: RecoveryAgentConfig,
    orchestrator: RecoveryOrchestratorLike | None = None,
    planner: ConstraintPlannerLike | None = None,
    orchestrator_recorder: ToolInvocationRecorder | None = None,
    planner_recorder: ToolInvocationRecorder | None = None,
    validator: PlanValidator | None = None,
    invalidation_service: PlanInvalidationService | None = None,
) -> tuple[ReplanningResult, PlanningBrief]:
    """Apply deterministic impact analysis before Orchestrator → Planner Plan B work."""

    service = invalidation_service or PlanInvalidationService()
    outcome = service.apply_caregiver_decline(recovery_case, event, scenario)
    resolved_orchestrator_recorder = orchestrator_recorder or ToolInvocationRecorder()
    resolved_planner_recorder = planner_recorder or ToolInvocationRecorder()
    resolved_orchestrator = orchestrator or build_recovery_orchestrator(
        config, resolved_orchestrator_recorder
    )
    resolved_planner = planner or build_constraint_planner(config, resolved_planner_recorder)

    mode = "world_state_replan"
    case_id = recovery_case.case_id
    log_event(
        "orchestrator_invocation_started",
        architecture="multi",
        agent_role="recovery_orchestrator",
        planning_mode=mode,
        recovery_case_id=case_id,
        model_id=config.model_id,
    )
    orchestrator_started = perf_counter()
    orchestration = create_replanning_brief(
        orchestrator=resolved_orchestrator,
        recorder=resolved_orchestrator_recorder,
        outcome=outcome,
    )
    log_event(
        "orchestrator_invocation_completed",
        architecture="multi",
        agent_role="recovery_orchestrator",
        planning_mode=mode,
        recovery_case_id=case_id,
        model_id=config.model_id,
        duration_ms=_duration_ms(orchestrator_started),
        model_call_count=orchestration.model_call_count,
        tool_call_count=len(orchestration.tools_used),
        tools_used=orchestration.tools_used,
        success=True,
    )
    log_event(
        "planner_invocation_started",
        architecture="multi",
        agent_role="constraint_planner",
        planning_mode=mode,
        recovery_case_id=case_id,
        model_id=config.model_id,
    )
    planner_started = perf_counter()
    planning = run_constraint_planning(
        planner=resolved_planner,
        recorder=resolved_planner_recorder,
        brief=orchestration.brief,
        scenario=outcome.updated_scenario,
        model_id=config.model_id,
        validator=validator,
    )
    _log_planner_result(planning, mode=mode, started=planner_started, case_id=case_id)
    tools_used = [*orchestration.tools_used, *planning.tools_used]
    replanning = build_replanning_result(
        outcome=outcome,
        event=event,
        attempts=planning.attempts,
        tools_used=tools_used,
        architecture="multi",
        orchestrator_invocation_count=1,
        planner_invocation_count=planning.planner_invocation_count,
        model_call_count=orchestration.model_call_count + planning.model_call_count,
    )
    return replanning, orchestration.brief


def _log_planner_result(
    planning: InitialPlanningResult,
    *,
    mode: str,
    started: float,
    case_id: str | None = None,
) -> None:
    for attempt in planning.attempts:
        fields = {
            "architecture": "multi",
            "agent_role": "constraint_planner",
            "planning_mode": mode,
            "recovery_case_id": case_id,
            "model_id": planning.model_id,
            "attempt_number": attempt.attempt_number,
            "plan_id": attempt.proposed_plan.plan_id,
            "valid": attempt.validation.valid,
            "issue_count": len(attempt.validation.issues),
            "model_call_count": attempt.model_call_count,
        }
        log_event("planner_attempt_completed", **fields)
        log_event(
            "planner_validation_succeeded"
            if attempt.validation.valid
            else "planner_validation_failed",
            **fields,
        )
    log_event(
        "planner_invocation_completed",
        architecture="multi",
        agent_role="constraint_planner",
        planning_mode=mode,
        recovery_case_id=case_id,
        model_id=planning.model_id,
        duration_ms=_duration_ms(started),
        model_call_count=planning.model_call_count,
        tool_call_count=planning.tool_call_count,
        tools_used=planning.tools_used,
        success=planning.success,
    )


def _duration_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)
