"""Three-agent initial recovery flow with conditional grounded provider research."""

from time import perf_counter

from app.agent.backup_care_researcher import (
    BackupCareResearcherLike,
    BackupCareResearchRun,
    build_backup_care_researcher,
    run_backup_care_research,
)
from app.agent.config import RecoveryAgentConfig
from app.agent.constraint_planner import (
    ConstraintPlannerLike,
    build_constraint_planner,
    run_constraint_planning,
)
from app.agent.multi_agent import _log_planner_result
from app.agent.recovery_agent import InitialPlanningResult, ToolInvocationRecorder
from app.agent.recovery_orchestrator import (
    PlanningBrief,
    RecoveryOrchestratorLike,
    build_recovery_orchestrator,
    create_initial_planning_brief,
)
from app.agent.research_planability import select_planable_research_candidate
from app.fixtures import DemoScenario
from app.observability import log_event
from app.services import (
    PlanValidator,
    RecoveryNeed,
    assess_known_option_recovery_need,
)


def run_research_multi_agent_initial_planning(
    *,
    disruption: str,
    scenario: DemoScenario,
    config: RecoveryAgentConfig,
    orchestrator: RecoveryOrchestratorLike | None = None,
    researcher: BackupCareResearcherLike | None = None,
    planner: ConstraintPlannerLike | None = None,
    orchestrator_recorder: ToolInvocationRecorder | None = None,
    researcher_recorder: ToolInvocationRecorder | None = None,
    planner_recorder: ToolInvocationRecorder | None = None,
    validator: PlanValidator | None = None,
) -> tuple[InitialPlanningResult, PlanningBrief, BackupCareResearchRun | None, RecoveryNeed]:
    """Run Orchestrator → optional Researcher → Planner from authoritative need analysis."""

    need = assess_known_option_recovery_need(scenario)
    orchestrator_recorder = orchestrator_recorder or ToolInvocationRecorder()
    researcher_recorder = researcher_recorder or ToolInvocationRecorder(
        allowed_tool_names={"search_backup_care"}
    )
    planner_recorder = planner_recorder or ToolInvocationRecorder()
    orchestrator = orchestrator or build_recovery_orchestrator(config, orchestrator_recorder)
    planner = planner or build_constraint_planner(config, planner_recorder)

    log_event(
        "orchestrator_invocation_started",
        architecture="multi_research",
        agent_role="recovery_orchestrator",
        planning_mode="initial",
        model_id=config.model_id,
    )
    orchestrator_started = perf_counter()
    orchestration = create_initial_planning_brief(
        orchestrator=orchestrator,
        recorder=orchestrator_recorder,
        disruption=disruption,
        scenario=scenario,
        recovery_need=need,
    )
    orchestrator_duration_ms = _duration_ms(orchestrator_started)
    log_event(
        "orchestrator_invocation_completed",
        architecture="multi_research",
        agent_role="recovery_orchestrator",
        planning_mode="initial",
        model_id=config.model_id,
        duration_ms=orchestrator_duration_ms,
        model_call_count=orchestration.model_call_count,
        tool_call_count=len(orchestration.tools_used),
        tools_used=orchestration.tools_used,
        success=True,
    )

    brief = orchestration.brief
    research_run: BackupCareResearchRun | None = None
    researched_candidate = None
    planning_scenario = scenario
    if brief.backup_research_needed:
        windows = [
            f"{window.start.isoformat()}/{window.end.isoformat()}"
            for window in need.requested_windows
        ]
        log_event(
            "backup_research_requested",
            architecture="multi_research",
            agent_role="recovery_orchestrator",
            planning_mode="initial",
            model_id=config.model_id,
            affected_windows=windows,
        )
        log_event(
            "backup_research_started",
            architecture="multi_research",
            agent_role="backup_care_researcher",
            planning_mode="initial",
            model_id=config.model_id,
        )
        researcher = researcher or build_backup_care_researcher(config, researcher_recorder)
        research_run = run_backup_care_research(
            researcher=researcher,
            recorder=researcher_recorder,
            scenario=scenario,
            recovery_need=need,
        )
        result = research_run.result
        log_event(
            "backup_candidates_received",
            architecture="multi_research",
            agent_role="backup_care_researcher",
            planning_mode="initial",
            model_id=config.model_id,
            candidate_count=len(result.considered_candidate_ids),
            eligible_candidate_count=len(result.eligible_candidate_ids),
        )
        log_event(
            "backup_candidate_recommended",
            architecture="multi_research",
            agent_role="backup_care_researcher",
            planning_mode="initial",
            model_id=config.model_id,
            research_id=result.research_id,
            recommended_candidate_id=result.recommended_candidate_id,
        )
        log_event(
            "backup_research_completed",
            architecture="multi_research",
            agent_role="backup_care_researcher",
            planning_mode="initial",
            model_id=config.model_id,
            duration_ms=research_run.duration_ms,
            model_call_count=research_run.model_call_count,
            tool_call_count=research_run.tool_call_count,
            tools_used=research_run.tools_used,
            success=True,
        )
        selection = select_planable_research_candidate(
            research_run=research_run,
            scenario=scenario,
            brief=brief,
        )
        researched_candidate = selection.candidate
        planning_scenario = selection.scenario
        brief = brief.model_copy(
            update={
                "researched_candidate_ids": result.eligible_candidate_ids,
                "recommended_backup_care_candidate_id": researched_candidate.candidate_id,
                "planner_directives": [
                    *brief.planner_directives[:7],
                    "Use the grounded recommended backup-care candidate where needed for the "
                    "unresolved known-options window; final feasibility remains deterministic.",
                ],
            }
        )

    log_event(
        "planner_invocation_started",
        architecture="multi_research",
        agent_role="constraint_planner",
        planning_mode="initial",
        model_id=config.model_id,
    )
    planner_started = perf_counter()
    planning = run_constraint_planning(
        planner=planner,
        recorder=planner_recorder,
        brief=brief,
        scenario=planning_scenario,
        model_id=config.model_id,
        validator=validator,
    )
    planner_duration_ms = _duration_ms(planner_started)
    _log_planner_result(
        planning,
        mode="initial",
        started=planner_started,
        architecture="multi_research",
    )
    research_tools = research_run.tools_used if research_run is not None else []
    research_model_calls = research_run.model_call_count if research_run is not None else 0
    research_duration_ms = research_run.duration_ms if research_run is not None else 0
    tools_used = [*orchestration.tools_used, *research_tools, *planning.tools_used]
    planning = planning.model_copy(
        update={
            "architecture": "multi_research",
            "tools_used": tools_used,
            "tool_call_count": len(tools_used),
            "model_call_count": (
                orchestration.model_call_count + research_model_calls + planning.model_call_count
            ),
            "research_agent_invocation_count": 1 if research_run is not None else 0,
            "research_tool_call_count": len(research_tools),
            "orchestrator_duration_ms": orchestrator_duration_ms,
            "research_duration_ms": research_duration_ms,
            "planner_duration_ms": planner_duration_ms,
            "known_options_uncovered_windows": need.requested_windows,
            "researched_candidate": researched_candidate,
        }
    )
    return planning, brief, research_run, need


def _duration_ms(started: float) -> int:
    return round((perf_counter() - started) * 1000)
