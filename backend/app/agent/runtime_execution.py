"""Request-scoped execution of the existing DayMend reasoning roles."""

from time import perf_counter

from app.agent.backup_care_researcher import (
    build_backup_care_researcher,
    run_backup_care_research,
)
from app.agent.config import AgentArchitecture, RecoveryAgentConfig
from app.agent.constraint_planner import (
    PlannerOperation,
    build_constraint_planner,
    propose_constraint_plan,
)
from app.agent.recovery_agent import ToolInvocationRecorder
from app.agent.recovery_orchestrator import (
    build_recovery_orchestrator,
    create_initial_planning_brief,
    create_replanning_brief,
)
from app.agent.research_planability import select_planable_research_candidate
from app.agent.runtime_contracts import (
    AgentRuntimeRequest,
    AgentRuntimeResponse,
    RuntimeMetrics,
    RuntimeOperation,
)
from app.observability import log_event
from app.services import (
    InvalidationOutcome,
    add_researched_caregiver,
    assess_known_option_recovery_need,
)


def execute_runtime_request(
    request: AgentRuntimeRequest,
    *,
    config: RecoveryAgentConfig | None = None,
) -> AgentRuntimeResponse:
    """Run reasoning only; never validate, persist, approve, execute, or resolve."""

    started = perf_counter()
    resolved_config = config or RecoveryAgentConfig.from_environment()
    if resolved_config.architecture is AgentArchitecture.SINGLE:
        raise ValueError("AgentCore reasoning runtime does not host the single-agent fallback")
    scenario = request.scenario.to_scenario()
    orchestrator_calls = 0
    research_calls = 0
    model_calls = 0
    tools_used: list[str] = []
    research_result = None
    researched_candidate = request.researched_candidate

    log_event(
        "agent_runtime_request_received",
        request_id=request.request_id,
        recovery_case_id=request.recovery_case_id,
        operation=request.operation,
        architecture=request.architecture,
    )

    if request.operation is RuntimeOperation.PLAN_REPAIR:
        assert request.planning_brief is not None
        assert request.previous_plan is not None
        brief = request.planning_brief
        if researched_candidate is not None:
            scenario = add_researched_caregiver(scenario, researched_candidate)
    else:
        orchestrator_recorder = ToolInvocationRecorder()
        orchestrator = build_recovery_orchestrator(resolved_config, orchestrator_recorder)
        if request.operation is RuntimeOperation.INITIAL_PLANNING:
            assert request.disruption is not None
            need = (
                assess_known_option_recovery_need(scenario)
                if request.architecture == "multi_research"
                else None
            )
            orchestration = create_initial_planning_brief(
                orchestrator=orchestrator,
                recorder=orchestrator_recorder,
                disruption=request.disruption,
                scenario=scenario,
                recovery_need=need,
            )
            brief = orchestration.brief
            if brief.backup_research_needed:
                research_recorder = ToolInvocationRecorder(
                    allowed_tool_names={"search_backup_care"}
                )
                researcher = build_backup_care_researcher(resolved_config, research_recorder)
                research_run = run_backup_care_research(
                    researcher=researcher,
                    recorder=research_recorder,
                    scenario=scenario,
                    recovery_need=need,
                )
                research_result = research_run.result
                selection = select_planable_research_candidate(
                    research_run=research_run,
                    scenario=scenario,
                    brief=brief,
                )
                researched_candidate = selection.candidate
                scenario = selection.scenario
                brief = brief.model_copy(
                    update={
                        "researched_candidate_ids": research_result.eligible_candidate_ids,
                        "recommended_backup_care_candidate_id": (researched_candidate.candidate_id),
                    }
                )
                research_calls = 1
                model_calls += research_run.model_call_count
                tools_used.extend(research_run.tools_used)
        else:
            assert request.replanning_context is not None
            context = request.replanning_context
            outcome = InvalidationOutcome(
                recovery_case=context.recovery_case,
                previous_status=context.previous_status,
                updated_scenario=scenario,
                original_valid_plan=context.original_valid_plan,
                invalidated_assumptions=tuple(context.invalidated_assumptions),
                impacted_segments=tuple(context.impacted_segments),
                impact_reasons=tuple(context.impact_reasons),
                preserved_segments=tuple(context.preserved_segments),
                uncovered_windows=tuple(context.uncovered_windows),
            )
            orchestration = create_replanning_brief(
                orchestrator=orchestrator,
                recorder=orchestrator_recorder,
                outcome=outcome,
            )
            brief = orchestration.brief
            if request.architecture == "multi_research":
                need = assess_known_option_recovery_need(scenario)
                if need.research_needed:
                    research_recorder = ToolInvocationRecorder(
                        allowed_tool_names={"search_backup_care"}
                    )
                    researcher = build_backup_care_researcher(resolved_config, research_recorder)
                    research_run = run_backup_care_research(
                        researcher=researcher,
                        recorder=research_recorder,
                        scenario=scenario,
                        recovery_need=need,
                    )
                    research_result = research_run.result
                    selection = select_planable_research_candidate(
                        research_run=research_run,
                        scenario=scenario,
                        brief=brief,
                    )
                    researched_candidate = selection.candidate
                    scenario = selection.scenario
                    brief = brief.model_copy(
                        update={
                            "known_options_insufficient": True,
                            "unresolved_known_option_windows": need.requested_windows,
                            "backup_research_needed": True,
                            "researched_candidate_ids": (research_result.eligible_candidate_ids),
                            "recommended_backup_care_candidate_id": (
                                researched_candidate.candidate_id
                            ),
                        }
                    )
                    research_calls = 1
                    model_calls += research_run.model_call_count
                    tools_used.extend(research_run.tools_used)
        orchestrator_calls = 1
        model_calls += orchestration.model_call_count
        tools_used.extend(orchestration.tools_used)

    planner_recorder = ToolInvocationRecorder()
    planner = build_constraint_planner(resolved_config, planner_recorder)
    proposal, planner_model_calls = propose_constraint_plan(
        planner=planner,
        recorder=planner_recorder,
        brief=brief,
        scenario=scenario,
        operation=PlannerOperation(request.operation.value),
        previous_plan=request.previous_plan,
        validator_feedback=request.validator_feedback,
    )
    model_calls += planner_model_calls
    tools_used.extend(planner_recorder.tool_names)
    response = AgentRuntimeResponse(
        request_id=request.request_id,
        recovery_case_id=request.recovery_case_id,
        operation=request.operation,
        success=True,
        planning_brief=brief,
        plan_candidate=proposal,
        backup_care_research=research_result,
        researched_candidate=researched_candidate,
        metrics=RuntimeMetrics(
            duration_ms=round((perf_counter() - started) * 1000),
            orchestrator_invocation_count=orchestrator_calls,
            research_agent_invocation_count=research_calls,
            planner_invocation_count=1,
            model_call_count=model_calls,
            tools_used=tools_used,
        ),
    )
    log_event(
        "agent_runtime_response_ready",
        request_id=request.request_id,
        recovery_case_id=request.recovery_case_id,
        operation=request.operation,
        duration_ms=response.metrics.duration_ms,
        success=True,
        tools_used=tools_used,
    )
    return response
