"""Proof that DayMend's opt-in two-agent split is real, bounded, and safe."""

import json
import logging
from types import SimpleNamespace

import pytest
from strands import Agent
from strands.types.exceptions import MaxTokensReachedException

from app.agent.config import AgentArchitecture, RecoveryAgentConfig
from app.agent.constraint_planner import (
    CONSTRAINT_PLANNER_INSTRUCTIONS,
    build_constraint_planner,
)
from app.agent.multi_agent import (
    run_multi_agent_initial_planning,
    run_multi_agent_replanning,
)
from app.agent.multi_agent_demo import _safe_brief_summary, _safe_validator_diagnostics
from app.agent.recovery_agent import MAX_PLAN_ATTEMPTS, ToolInvocationRecorder
from app.agent.recovery_orchestrator import (
    ORCHESTRATOR_INSTRUCTIONS,
    ConstraintCategory,
    PlanningBrief,
    PlanningMode,
    ReplanningBriefDecision,
    build_recovery_orchestrator,
    create_replanning_brief,
)
from app.fixtures import get_legacy_demo_scenario
from app.models import PlanValidationState, RecoveryPlan, RecoveryStatus
from app.observability import LOGGER_NAME
from app.services import (
    PlanInvalidationService,
    PlanValidator,
    ValidationErrorCode,
    create_active_recovery_case,
)
from tests.milestone2_helpers import (
    at,
    grandma_decline_event,
    valid_plan_b,
    validated_plan_a,
    window,
)


class StubOrchestrator:
    def __init__(self, brief: PlanningBrief) -> None:
        self.brief = brief
        self.calls: list[tuple[str, object]] = []

    def __call__(self, prompt: str, *, structured_output_model=None) -> SimpleNamespace:
        self.calls.append((prompt, structured_output_model))
        return SimpleNamespace(structured_output=self.brief)


class StubPlanner:
    def __init__(self, proposals: list[RecoveryPlan]) -> None:
        self.proposals = proposals.copy()
        self.calls: list[tuple[str, object]] = []

    def __call__(self, prompt: str, *, structured_output_model=None) -> SimpleNamespace:
        self.calls.append((prompt, structured_output_model))
        if structured_output_model is None:
            return SimpleNamespace(structured_output=None)
        return SimpleNamespace(structured_output=self.proposals.pop(0))


class SequencedOrchestrator:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses.copy()
        self.calls: list[tuple[str, object]] = []

    def __call__(self, prompt: str, *, structured_output_model=None) -> SimpleNamespace:
        self.calls.append((prompt, structured_output_model))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(structured_output=response)


class CountingValidator(PlanValidator):
    def __init__(self) -> None:
        self.calls = 0

    def validate(self, plan, scenario):
        self.calls += 1
        return super().validate(plan, scenario)


def config(architecture: AgentArchitecture = AgentArchitecture.MULTI) -> RecoveryAgentConfig:
    return RecoveryAgentConfig(
        model_id="offline-multi-agent-model",
        region_name="us-east-1",
        architecture=architecture,
    )


def initial_brief(**updates) -> PlanningBrief:
    values = {
        "planning_mode": PlanningMode.INITIAL,
        "planning_required": True,
        "objective": "Restore complete childcare coverage for the disrupted workday.",
        "required_coverage_window": window(8, 16),
        "affected_windows": [window(8, 16)],
        "relevant_constraint_categories": list(ConstraintCategory),
        "planner_directives": ["Protect critical commitments and restore full coverage."],
    }
    values.update(updates)
    return PlanningBrief(**values)


def replanning_brief(**updates) -> PlanningBrief:
    values = {
        "recovery_case_id": "case-multi-replan",
        "planning_mode": PlanningMode.WORLD_STATE_REPLAN,
        "planning_required": True,
        "objective": "Replace affected coverage while retaining feasible Plan A work.",
        "required_coverage_window": window(8, 16),
        "affected_windows": [window(10, 13)],
        "excluded_caregiver_ids": ["grandma"],
        "relevant_constraint_categories": list(ConstraintCategory),
        "planner_directives": ["Prefer preserved segments when full feasibility permits."],
    }
    values.update(updates)
    return PlanningBrief(**values)


def active_case():
    scenario = get_legacy_demo_scenario()
    return create_active_recovery_case(
        case_id="case-multi-replan",
        disruption=scenario.disruption,
        validated_plan=validated_plan_a(),
        required_coverage=scenario.required_coverage,
        now=at(7, 10),
    )


def replanning_outcome():
    return PlanInvalidationService().apply_caregiver_decline(
        active_case(),
        grandma_decline_event(),
        get_legacy_demo_scenario(),
    )


def compact_replanning_decision() -> ReplanningBriefDecision:
    return ReplanningBriefDecision(
        planning_required=True,
        objective="Replace the affected care while retaining preserved coverage.",
        affected_window_ids=["affected_window_1"],
        affected_segment_ids=["grandma-midday"],
        preserved_segment_ids=["parent-morning", "backup-afternoon"],
        backup_research_needed=True,
        relevant_constraint_categories=[
            ConstraintCategory.COVERAGE,
            ConstraintCategory.PLAN_PRESERVATION,
        ],
        planner_directives=["Repair only the affected coverage and connected handoffs."],
    )


def test_both_roles_are_real_distinct_strands_agents_with_deliberate_tools() -> None:
    orchestrator = build_recovery_orchestrator(config(), ToolInvocationRecorder())
    planner = build_constraint_planner(config(), ToolInvocationRecorder())

    assert isinstance(orchestrator, Agent)
    assert isinstance(planner, Agent)
    assert orchestrator.name == "daymend_recovery_orchestrator"
    assert planner.name == "daymend_constraint_planner"
    assert set(orchestrator.tool_registry.registry) == {"get_childcare_schedule"}
    assert set(planner.tool_registry.registry) == {
        "get_childcare_schedule",
        "get_parent_calendars",
        "get_caregivers",
        "get_family_preferences",
        "get_family_policy",
    }


def test_initial_multi_agent_flow_uses_brief_then_planner_and_deterministic_repair() -> None:
    orchestrator = StubOrchestrator(initial_brief())
    invalid = validated_plan_a().model_copy(
        update={
            "plan_id": "invalid-claim",
            "coverage_segments": [],
            "validation_state": PlanValidationState.VALID,
        }
    )
    planner = StubPlanner([invalid, validated_plan_a()])
    validator = CountingValidator()

    result, brief = run_multi_agent_initial_planning(
        disruption=get_legacy_demo_scenario().disruption,
        scenario=get_legacy_demo_scenario(),
        config=config(),
        orchestrator=orchestrator,
        planner=planner,
        validator=validator,
    )

    assert len(orchestrator.calls) == 1
    assert orchestrator.calls[0][1] is PlanningBrief
    assert [call[1] for call in planner.calls] == [RecoveryPlan, RecoveryPlan]
    assert '"planning_brief"' in planner.calls[0][0]
    assert '"feasible_assignment_matrix"' in planner.calls[0][0]
    assert '"soft_ranking_preferences"' in planner.calls[0][0]
    assert '"authoritative_context"' not in planner.calls[0][0]
    assert '"transport_primitives"' in planner.calls[0][0]
    assert "Compose the plan only from FeasibleAssignmentMatrix" in planner.calls[0][0]
    assert "Do not shorten, extend, combine, or invent primitives" in planner.calls[0][0]
    assert validator.calls == 2
    assert result.total_attempts == 2
    assert result.success is True
    assert result.final_plan is not None
    assert result.final_plan.plan_id == "plan-a"
    assert result.attempts[0].validation.valid is False
    assert result.attempts[0].proposed_plan.validation_state is PlanValidationState.NOT_VALIDATED
    assert ValidationErrorCode.COVERAGE_GAP.value in planner.calls[1][0]
    assert '"previous_candidate"' in planner.calls[1][0]
    assert "invalid-claim" in planner.calls[1][0]
    assert '"feasible_assignment_matrix"' in planner.calls[1][0]
    assert "Compose the plan only from FeasibleAssignmentMatrix" in planner.calls[1][0]
    assert result.architecture == "multi"
    assert result.orchestrator_invocation_count == 1
    assert result.planner_invocation_count == 2


def test_orchestrator_cannot_override_authoritative_initial_facts() -> None:
    invented = initial_brief(
        recovery_case_id="invented",
        planning_mode=PlanningMode.WORLD_STATE_REPLAN,
        required_coverage_window=window(10, 12),
        affected_windows=[window(10, 12)],
        excluded_caregiver_ids=["invented-caregiver"],
    )
    result, brief = run_multi_agent_initial_planning(
        disruption=get_legacy_demo_scenario().disruption,
        scenario=get_legacy_demo_scenario(),
        config=config(),
        orchestrator=StubOrchestrator(invented),
        planner=StubPlanner([validated_plan_a()]),
    )

    assert result.success
    assert brief.recovery_case_id is None
    assert brief.planning_mode is PlanningMode.INITIAL
    assert brief.required_coverage_window == get_legacy_demo_scenario().required_coverage
    assert brief.affected_windows == [get_legacy_demo_scenario().required_coverage]
    assert brief.excluded_caregiver_ids == []


def test_replanning_brief_receives_deterministic_impact_and_planner_builds_plan_b() -> None:
    orchestrator = StubOrchestrator(replanning_brief(affected_windows=[window(8, 9)]))
    planner = StubPlanner([validated_plan_a(), valid_plan_b()])
    validator = CountingValidator()

    result, brief = run_multi_agent_replanning(
        recovery_case=active_case(),
        event=grandma_decline_event(),
        scenario=get_legacy_demo_scenario(),
        config=config(),
        orchestrator=orchestrator,
        planner=planner,
        validator=validator,
    )

    assert len(orchestrator.calls) == 1
    assert orchestrator.calls[0][1] is ReplanningBriefDecision
    assert brief.planning_mode is PlanningMode.WORLD_STATE_REPLAN
    assert brief.affected_windows == [window(10, 13)]
    assert len(brief.affected_segments) == 1
    assert brief.excluded_caregiver_ids == ["grandma"]
    assert len(brief.preserved_segments) == 4
    assert brief.triggering_event == grandma_decline_event()
    assert brief.current_active_plan_id == "plan-a"
    assert brief.current_recovery_status is RecoveryStatus.REPLANNING
    assert len(brief.invalidated_assumption_ids) == 1
    assert "Planner input digest:" in planner.calls[0][0]
    assert '"planning_brief"' in planner.calls[1][0]
    assert '"preserved_segments"' in planner.calls[1][0]
    assert validator.calls == 2
    assert result.success is True
    assert result.final_plan is not None
    assert result.final_plan.plan_id == "plan-b"
    assert result.recovery_case.previous_plans[0].plan_id == "plan-a"
    assert result.recovery_case.status is RecoveryStatus.EXECUTING
    assert result.invalidated_assumptions[0].subject_id == "grandma"
    assert [segment.segment_id for segment in result.impacted_segments] == ["grandma-midday"]
    assert ValidationErrorCode.CAREGIVER_UNAVAILABLE.value in planner.calls[2][0]


def test_replanning_orchestrator_receives_only_compact_identified_scope() -> None:
    orchestrator = SequencedOrchestrator([compact_replanning_decision()])

    result = create_replanning_brief(
        orchestrator=orchestrator,
        recorder=ToolInvocationRecorder(),
        outcome=replanning_outcome(),
    )

    prompt, output_model = orchestrator.calls[0]
    assert output_model is ReplanningBriefDecision
    assert '"affected_segment_ids":["grandma-midday"]' in prompt
    assert '"preserved_segment_ids"' in prompt
    assert '"current_active_plan":' not in prompt
    assert '"coverage_segments"' not in prompt
    assert '"invalidated_assumptions"' not in prompt
    assert '"family_policy"' not in prompt
    assert '"feasible_assignment_matrix"' not in prompt
    assert '"validator_feedback"' not in prompt
    assert result.brief.affected_segments == list(replanning_outcome().impacted_segments)
    assert result.brief.preserved_segments == list(replanning_outcome().preserved_segments)
    assert result.brief.triggering_event == grandma_decline_event()


def test_replanning_brief_retries_one_max_token_failure_with_smaller_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    orchestrator = SequencedOrchestrator(
        [
            MaxTokensReachedException("truncated"),
            compact_replanning_decision(),
        ]
    )

    result = create_replanning_brief(
        orchestrator=orchestrator,
        recorder=ToolInvocationRecorder(),
        outcome=replanning_outcome(),
    )

    assert len(orchestrator.calls) == 2
    assert all(call[1] is ReplanningBriefDecision for call in orchestrator.calls)
    assert len(orchestrator.calls[1][0]) < len(orchestrator.calls[0][0])
    assert '"affected_windows"' not in orchestrator.calls[1][0]
    assert result.brief.planning_required
    assert result.model_call_count == 1
    events = [json.loads(record.message) for record in caplog.records]
    assert {
        "event_type": "replanning_brief_retry",
        "operation": "REPLANNING",
        "retry_number": 1,
        "retry_reason": "max_tokens",
        "error_type": "MaxTokensReachedException",
    } in events


def test_replanning_brief_second_max_token_failure_propagates_after_one_retry() -> None:
    orchestrator = SequencedOrchestrator(
        [
            MaxTokensReachedException("first truncation"),
            MaxTokensReachedException("second truncation"),
        ]
    )

    with pytest.raises(MaxTokensReachedException, match="second truncation"):
        create_replanning_brief(
            orchestrator=orchestrator,
            recorder=ToolInvocationRecorder(),
            outcome=replanning_outcome(),
        )

    assert len(orchestrator.calls) == 2


def test_replanning_brief_does_not_retry_other_exceptions() -> None:
    orchestrator = SequencedOrchestrator([RuntimeError("service failure")])

    with pytest.raises(RuntimeError, match="service failure"):
        create_replanning_brief(
            orchestrator=orchestrator,
            recorder=ToolInvocationRecorder(),
            outcome=replanning_outcome(),
        )

    assert len(orchestrator.calls) == 1


def test_multi_agent_repair_never_exceeds_existing_three_attempt_cap() -> None:
    planner = StubPlanner([validated_plan_a()] * MAX_PLAN_ATTEMPTS)
    result, _ = run_multi_agent_replanning(
        recovery_case=active_case(),
        event=grandma_decline_event(),
        scenario=get_legacy_demo_scenario(),
        config=config(),
        orchestrator=StubOrchestrator(replanning_brief()),
        planner=planner,
    )

    assert result.success is False
    assert result.total_attempts == MAX_PLAN_ATTEMPTS
    assert len(planner.calls) == 1 + MAX_PLAN_ATTEMPTS


def test_orchestrator_decision_prevents_planner_invocation_when_planning_is_declined() -> None:
    planner = StubPlanner([validated_plan_a()])
    with pytest.raises(RuntimeError, match="declined required childcare planning"):
        run_multi_agent_initial_planning(
            disruption=get_legacy_demo_scenario().disruption,
            scenario=get_legacy_demo_scenario(),
            config=config(),
            orchestrator=StubOrchestrator(initial_brief(planning_required=False)),
            planner=planner,
        )

    assert planner.calls == []


def test_single_agent_remains_the_deliberate_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DAYMEND_AGENT_ARCHITECTURE", raising=False)
    assert RecoveryAgentConfig.from_environment().architecture is AgentArchitecture.SINGLE

    monkeypatch.setenv("DAYMEND_AGENT_ARCHITECTURE", "multi")
    assert RecoveryAgentConfig.from_environment().architecture is AgentArchitecture.MULTI

    monkeypatch.setenv("DAYMEND_AGENT_ARCHITECTURE", "multi_research")
    assert RecoveryAgentConfig.from_environment().architecture is AgentArchitecture.MULTI_RESEARCH

    monkeypatch.setenv("DAYMEND_AGENT_ARCHITECTURE", "unknown")
    with pytest.raises(ValueError, match="multi_research"):
        RecoveryAgentConfig.from_environment()


def test_gateway_single_mode_executes_only_the_proven_single_agent_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.application import recovery_service

    planner = StubPlanner([validated_plan_a()])
    monkeypatch.setattr(recovery_service, "build_recovery_agent", lambda *_args: planner)
    monkeypatch.setattr(
        recovery_service,
        "run_multi_agent_initial_planning",
        lambda **_kwargs: pytest.fail("multi-agent path must not run in single mode"),
    )

    gateway = recovery_service.StrandsRecoveryPlanningGateway(config(AgentArchitecture.SINGLE))
    scenario = get_legacy_demo_scenario()
    result = gateway.plan_initial(scenario.disruption, scenario)

    assert result.success is True
    assert result.architecture == "single"
    assert [call[1] for call in planner.calls] == [None, RecoveryPlan]
    assert gateway.last_initial_brief is None


def test_multi_agent_flow_emits_safe_role_and_validation_events(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    run_multi_agent_initial_planning(
        disruption=get_legacy_demo_scenario().disruption,
        scenario=get_legacy_demo_scenario(),
        config=config(),
        orchestrator=StubOrchestrator(initial_brief()),
        planner=StubPlanner([validated_plan_a()]),
    )

    events = [json.loads(record.message) for record in caplog.records]
    event_types = {event["event_type"] for event in events}
    assert {
        "orchestrator_invocation_started",
        "orchestrator_invocation_completed",
        "planner_invocation_started",
        "planner_attempt_completed",
        "planner_validation_succeeded",
        "planner_invocation_completed",
    } <= event_types
    assert all(
        event.get("architecture") == "multi"
        for event in events
        if event["event_type"] != "planner_input_prepared"
    )
    prepared = [event for event in events if event["event_type"] == "planner_input_prepared"]
    assert [event["stage"] for event in prepared] == ["proposal"]
    assert len({event["planner_input_digest"] for event in prepared}) == 1
    assert all("prompt" not in event and "authoritative_context" not in event for event in prepared)
    assert not any("prompt" in event or "reasoning" in event for event in events)


def test_agent_prompts_keep_deterministic_ownership_and_never_persist_reasoning() -> None:
    assert "do not construct a RecoveryPlan" in ORCHESTRATOR_INSTRUCTIONS
    assert "do not" in ORCHESTRATOR_INSTRUCTIONS.lower()
    assert "mark a case RESOLVED" in ORCHESTRATOR_INSTRUCTIONS
    assert "Do not claim the plan is valid" in CONSTRAINT_PLANNER_INSTRUCTIONS
    assert "Deterministic code will independently recompute costs" in (
        CONSTRAINT_PLANNER_INSTRUCTIONS
    )
    assert "chain-of-thought" in ORCHESTRATOR_INSTRUCTIONS
    assert "planning_brief" not in active_case().model_dump()


def test_live_failure_diagnostics_include_only_safe_validator_fields() -> None:
    result, _ = run_multi_agent_initial_planning(
        disruption=get_legacy_demo_scenario().disruption,
        scenario=get_legacy_demo_scenario(),
        config=config(),
        orchestrator=StubOrchestrator(initial_brief()),
        planner=StubPlanner(
            [
                RecoveryPlan(plan_id=f"unsafe-window-{number}", coverage_segments=[])
                for number in range(1, MAX_PLAN_ATTEMPTS + 1)
            ]
        ),
    )

    diagnostics = _safe_validator_diagnostics(result)
    assert [diagnostic["attempt_number"] for diagnostic in diagnostics] == [1, 2, 3]
    assert {diagnostic["issue_code"] for diagnostic in diagnostics} == {"coverage_gap"}
    assert {diagnostic["message"] for diagnostic in diagnostics} == {
        "Required childcare window has no coverage segments."
    }
    assert "prompt" not in str(diagnostics).lower()
    assert "reasoning" not in str(diagnostics).lower()


def test_safe_replanning_brief_summary_excludes_event_message() -> None:
    result, brief = run_multi_agent_replanning(
        recovery_case=active_case(),
        event=grandma_decline_event(),
        scenario=get_legacy_demo_scenario(),
        config=config(),
        orchestrator=StubOrchestrator(replanning_brief()),
        planner=StubPlanner([valid_plan_b()]),
    )
    assert result.success

    summary = _safe_brief_summary(brief)
    assert summary["triggering_event"]["event_id"] == "event-grandma-declined"
    assert summary["current_active_plan_id"] == "plan-a"
    assert summary["current_recovery_status"] is RecoveryStatus.REPLANNING
    assert summary["excluded_caregiver_ids"] == ["grandma"]
    assert "message" not in str(summary).lower()
    assert _safe_validator_diagnostics(result) == []
