"""Milestone 6.5B proof for grounded conditional backup-care research."""

import json
import logging
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from strands import Agent

from app.agent.backup_care_researcher import (
    BACKUP_CARE_RESEARCH_INSTRUCTIONS,
    BackupCareResearchResult,
    RankedBackupCareCandidate,
    build_backup_care_researcher,
    run_backup_care_research,
)
from app.agent.config import AgentArchitecture, RecoveryAgentConfig
from app.agent.constraint_planner import build_constraint_planner
from app.agent.recovery_agent import MAX_PLAN_ATTEMPTS, ToolInvocationRecorder
from app.agent.recovery_orchestrator import (
    ConstraintCategory,
    PlanningBrief,
    PlanningMode,
    build_recovery_orchestrator,
)
from app.agent.research_multi_agent import run_research_multi_agent_initial_planning
from app.application import (
    ApprovalCommand,
    ApprovalDecision,
    RecoveryApplicationService,
    StartRecoveryCommand,
)
from app.fixtures import (
    get_backup_care_research_scenario,
    get_demo_scenario,
    get_legacy_demo_scenario,
)
from app.models import (
    CoverageSource,
    PlanApprovalReason,
    RecoveryEvent,
    RecoveryPlan,
    RecoveryPlanSegment,
    RecoveryStatus,
)
from app.observability import LOGGER_NAME
from app.repositories import InMemoryRecoveryCaseRepository
from app.services import (
    PlanValidator,
    add_researched_caregiver,
    assess_known_option_recovery_need,
    search_backup_care_candidates,
)
from app.tools import search_backup_care, use_backup_care_request, use_scenario
from tests.milestone2_helpers import at, window


def config() -> RecoveryAgentConfig:
    return RecoveryAgentConfig(
        model_id="offline-research-model",
        region_name="us-east-1",
        architecture=AgentArchitecture.MULTI_RESEARCH,
    )


def research_brief(*, research_needed: bool) -> PlanningBrief:
    scenario = get_backup_care_research_scenario()
    return PlanningBrief(
        planning_mode=PlanningMode.INITIAL,
        planning_required=True,
        objective="Restore childcare coverage using research only if known options are short.",
        required_coverage_window=scenario.required_coverage,
        affected_windows=[scenario.required_coverage],
        relevant_constraint_categories=list(ConstraintCategory),
        planner_directives=["Restore complete coverage and protect critical commitments."],
        backup_research_needed=research_needed,
    )


class StubOrchestrator:
    def __init__(self, brief: PlanningBrief) -> None:
        self.brief = brief
        self.calls = []

    def __call__(self, prompt: str, *, structured_output_model=None):
        self.calls.append((prompt, structured_output_model))
        return SimpleNamespace(structured_output=self.brief)


class StubResearcher:
    def __init__(
        self,
        recorder: ToolInvocationRecorder,
        *,
        recommended: str = "harbor_nanny_coop",
        ranked_ids: list[str] | None = None,
    ) -> None:
        self.recorder = recorder
        self.recommended = recommended
        self.ranked_ids = ranked_ids or [
            "harbor_nanny_coop",
            "willow_family_care",
            "bright_start_agency",
        ]
        self.calls = []

    def __call__(self, prompt: str, *, structured_output_model=None):
        self.calls.append((prompt, structured_output_model))
        self.recorder.tool_names.append("search_backup_care")
        return SimpleNamespace(
            structured_output=BackupCareResearchResult(
                research_id="model-research-id",
                requested_windows=[window(9, 10)],
                considered_candidate_ids=self.ranked_ids,
                eligible_candidate_ids=self.ranked_ids,
                ranked_candidates=[
                    RankedBackupCareCandidate(
                        candidate_id=candidate_id,
                        rank=rank,
                        fit_summary=f"Comparative fit for {candidate_id}.",
                        tradeoffs=["Balances cost, distance, rating, and review history."],
                    )
                    for rank, candidate_id in enumerate(self.ranked_ids, start=1)
                ],
                recommended_candidate_id=self.recommended,
            )
        )


class StubPlanner:
    def __init__(self, proposals: list[RecoveryPlan]) -> None:
        self.proposals = proposals.copy()
        self.calls = []

    def __call__(self, prompt: str, *, structured_output_model=None):
        self.calls.append((prompt, structured_output_model))
        if structured_output_model is None:
            return SimpleNamespace(structured_output=None)
        return SimpleNamespace(structured_output=self.proposals.pop(0))


def researched_plan(candidate_id: str = "harbor_nanny_coop") -> RecoveryPlan:
    return RecoveryPlan(
        plan_id="model-reused-plan-id",
        coverage_segments=[
            RecoveryPlanSegment(
                segment_id="grandma-morning",
                window=window(8, 10),
                assigned_person_id="grandma",
                source=CoverageSource.CAREGIVER,
            ),
            RecoveryPlanSegment(
                segment_id="researched-gap",
                window=window(10, 12),
                assigned_person_id=candidate_id,
                source=CoverageSource.CAREGIVER,
            ),
            RecoveryPlanSegment(
                segment_id="known-afternoon",
                window=window(12, 16),
                assigned_person_id="known_backup_sitter",
                source=CoverageSource.CAREGIVER,
            ),
        ],
    )


def _run_research_flow(*, researcher=None, recorder=None, planner=None, scenario=None):
    resolved_recorder = recorder or ToolInvocationRecorder(
        allowed_tool_names={"search_backup_care"}
    )
    return run_research_multi_agent_initial_planning(
        disruption="nanny unavailable",
        scenario=scenario or get_backup_care_research_scenario(),
        config=config(),
        orchestrator=StubOrchestrator(research_brief(research_needed=True)),
        researcher=researcher or StubResearcher(resolved_recorder),
        planner=planner or StubPlanner([researched_plan()]),
        researcher_recorder=resolved_recorder,
    )


def test_exact_three_specialized_roles_are_real_strands_agents_with_narrow_tools() -> None:
    orchestrator = build_recovery_orchestrator(config(), ToolInvocationRecorder())
    planner = build_constraint_planner(config(), ToolInvocationRecorder())
    researcher = build_backup_care_researcher(
        config(),
        ToolInvocationRecorder(allowed_tool_names={"search_backup_care"}),
    )

    assert all(isinstance(agent, Agent) for agent in (orchestrator, planner, researcher))
    assert {agent.name for agent in (orchestrator, planner, researcher)} == {
        "daymend_recovery_orchestrator",
        "daymend_constraint_planner",
        "daymend_backup_care_researcher",
    }
    assert set(researcher.tool_registry.registry) == {"search_backup_care"}
    assert "do not construct or validate a RecoveryPlan" in BACKUP_CARE_RESEARCH_INSTRUCTIONS


def test_research_trigger_is_deterministic_and_not_caregiver_name_specific() -> None:
    ordinary_need = assess_known_option_recovery_need(get_demo_scenario())
    research_scenario = get_backup_care_research_scenario()
    research_need = assess_known_option_recovery_need(research_scenario)
    renamed = replace(
        research_scenario,
        caregivers=tuple(
            caregiver.model_copy(update={"caregiver_id": f"renamed-{index}"})
            for index, caregiver in enumerate(research_scenario.caregivers)
        ),
    )

    assert ordinary_need.research_needed is False
    assert research_need.research_needed is True
    assert research_need.requested_windows == [window(10, 12)]
    assert assess_known_option_recovery_need(renamed).requested_windows == [window(10, 12)]


def test_research_agent_is_not_invoked_when_known_options_are_sufficient() -> None:
    planner = StubPlanner([get_demo_scenario_plan()])
    scenario = get_legacy_demo_scenario()
    result, brief, research, need = run_research_multi_agent_initial_planning(
        disruption=scenario.disruption,
        scenario=scenario,
        config=config(),
        orchestrator=StubOrchestrator(research_brief(research_needed=True)),
        researcher=pytest.fail,
        planner=planner,
    )

    assert result.success
    assert brief.backup_research_needed is False
    assert research is None
    assert need.known_options_insufficient is False
    assert result.research_agent_invocation_count == 0


def get_demo_scenario_plan() -> RecoveryPlan:
    from tests.milestone2_helpers import validated_plan_a

    return validated_plan_a()


def test_search_filters_hard_rules_but_preserves_soft_ranking_attributes() -> None:
    scenario = get_backup_care_research_scenario()
    need = assess_known_option_recovery_need(scenario)
    result = search_backup_care_candidates(scenario, need.requested_windows)
    assessments = {item.candidate.candidate_id: item for item in result.considered_candidates}

    assert len(result.considered_candidates) == 6
    assert [candidate.candidate_id for candidate in result.eligible_candidates] == [
        "harbor_nanny_coop",
        "willow_family_care",
        "bright_start_agency",
    ]
    assert [code.value for code in assessments["value_sitter_collective"].ineligibility_codes] == [
        "UNAVAILABLE"
    ]
    assert [code.value for code in assessments["neighborhood_helper"].ineligibility_codes] == [
        "BACKGROUND_CHECK_REQUIRED"
    ]
    assert [code.value for code in assessments["school_age_specialist"].ineligibility_codes] == [
        "CHILD_AGE_UNSUPPORTED"
    ]
    eligible = result.eligible_candidates
    assert len({candidate.hourly_rate or candidate.flat_rate for candidate in eligible}) == 3
    assert len({candidate.distance_miles for candidate in eligible}) == 3
    assert len({candidate.rating for candidate in eligible}) == 3

    with use_scenario(scenario), use_backup_care_request(need.requested_windows):
        tool_result = search_backup_care()
    assert len(tool_result["eligible_candidates"]) == 3


def test_research_result_is_grounded_ranked_and_has_no_validation_or_approval_authority() -> None:
    recorder = ToolInvocationRecorder(allowed_tool_names={"search_backup_care"})
    run = run_backup_care_research(
        researcher=StubResearcher(recorder),
        recorder=recorder,
        scenario=get_backup_care_research_scenario(),
        recovery_need=assess_known_option_recovery_need(get_backup_care_research_scenario()),
    )

    assert run.result.recommended_candidate_id == "harbor_nanny_coop"
    assert [item.rank for item in run.result.ranked_candidates] == [1, 2, 3]
    assert run.result.recommended_candidate_id in run.result.eligible_candidate_ids
    assert run.tools_used == ["search_backup_care"]
    assert "valid" not in BackupCareResearchResult.model_fields
    assert "requires_approval" not in BackupCareResearchResult.model_fields


def test_research_agent_cannot_invent_or_omit_grounded_candidate_ids() -> None:
    recorder = ToolInvocationRecorder(allowed_tool_names={"search_backup_care"})
    researcher = StubResearcher(
        recorder,
        recommended="invented-provider",
        ranked_ids=["harbor_nanny_coop", "willow_family_care", "invented-provider"],
    )
    with pytest.raises(RuntimeError, match="grounded to eligible IDs"):
        run_backup_care_research(
            researcher=researcher,
            recorder=recorder,
            scenario=get_backup_care_research_scenario(),
            recovery_need=assess_known_option_recovery_need(get_backup_care_research_scenario()),
        )


def test_recommendation_reaches_planner_and_existing_validator_accepts_plan() -> None:
    planner = StubPlanner([researched_plan()])
    planning, brief, research, need = _run_research_flow(planner=planner)

    assert research is not None
    assert need.requested_windows == [window(10, 12)]
    assert brief.recommended_backup_care_candidate_id == "harbor_nanny_coop"
    assert '"feasible_assignment_matrix"' in planner.calls[0][0]
    assert '"planning_brief"' in planner.calls[0][0]
    assert brief.recommended_backup_care_candidate_id in planner.calls[0][0]
    assert planning.success is True
    assert planning.total_attempts == 1
    assert planning.final_plan is not None
    assert any(
        segment.assigned_person_id == "harbor_nanny_coop"
        for segment in planning.final_plan.coverage_segments
    )
    assert planning.attempts[-1].validation.valid is True
    assert MAX_PLAN_ATTEMPTS == 3


def test_unfamiliar_paid_care_approval_is_deterministic_and_independent_of_cost() -> None:
    scenario = get_backup_care_research_scenario()
    need = assess_known_option_recovery_need(scenario)
    candidate = search_backup_care_candidates(scenario, need.requested_windows).eligible_candidates[
        0
    ]
    high_limit = scenario.policy.model_copy(update={"automatic_spend_limit": Decimal("500")})
    scenario = replace(
        add_researched_caregiver(scenario, candidate),
        policy=high_limit,
    )
    result = PlanValidator().validate(researched_plan(), scenario)

    assert result.valid
    assert result.deterministic_total_cost < high_limit.automatic_spend_limit
    assert result.requires_approval is True
    assert result.validated_plan.approval_reasons == [PlanApprovalReason.UNFAMILIAR_PAID_CAREGIVER]

    known_candidate = scenario.caregivers[-1].model_copy(
        update={"known_to_family": True, "external_provider": True}
    )
    known_scenario = replace(
        scenario,
        caregivers=(*scenario.caregivers[:-1], known_candidate),
    )
    known = PlanValidator().validate(researched_plan(), known_scenario)
    assert known.valid
    assert known.requires_approval is False


class OfflineResearchGateway:
    def __init__(self) -> None:
        self.research_run = None

    def plan_initial(self, disruption, scenario):
        recorder = ToolInvocationRecorder(allowed_tool_names={"search_backup_care"})
        result, _, self.research_run, _ = run_research_multi_agent_initial_planning(
            disruption=disruption,
            scenario=scenario,
            config=config(),
            orchestrator=StubOrchestrator(research_brief(research_needed=True)),
            researcher=StubResearcher(recorder),
            planner=StubPlanner([researched_plan()]),
            researcher_recorder=recorder,
        )
        return result

    def replan(self, recovery_case, event: RecoveryEvent, scenario):
        raise AssertionError("research fixture resolves without a world-state replan")


def test_end_to_end_research_lifecycle_preserves_identity_and_reaches_verified_resolved() -> None:
    repository = InMemoryRecoveryCaseRepository()
    gateway = OfflineResearchGateway()
    times = iter([at(7, 10), at(7, 11), at(7, 12), at(7, 13), at(7, 14)])
    service = RecoveryApplicationService(
        repository,
        gateway,
        scenario_factory=get_backup_care_research_scenario,
        clock=lambda: next(times),
        id_factory=lambda: "case-research-offline",
    )

    pending = service.start_recovery(
        StartRecoveryCommand(
            disruption_type="CHILDCARE_UNAVAILABLE",
            occurred_at=at(7, 2),
            caregiver_id="nanny",
            message="Unavailable today.",
        )
    )
    assert pending.status is RecoveryStatus.APPROVAL_REQUIRED
    assert pending.active_recovery_plan is not None
    assert pending.active_recovery_plan.plan_id == "case-research-offline:plan:1"
    assert pending.pending_approval is not None
    assert pending.pending_approval.plan_id == pending.active_recovery_plan.plan_id
    assert "unfamiliar paid caregiver" in pending.pending_approval.reason

    resolved = service.decide_approval(
        pending.case_id,
        pending.pending_approval.approval_id,
        ApprovalCommand(decision=ApprovalDecision.APPROVE, expected_version=pending.version),
    )
    assert resolved.case_id == pending.case_id
    assert resolved.status is RecoveryStatus.RESOLVED
    assert resolved.completion_verified_at is not None
    assert any(
        segment.assigned_person_id == "harbor_nanny_coop"
        for segment in resolved.active_recovery_plan.coverage_segments
    )
    assert all(action.status.value == "SUCCEEDED" for action in resolved.execution_history)
    assert repository.get(pending.case_id).status is RecoveryStatus.RESOLVED


def test_research_observability_is_safe_and_complete(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)
    _run_research_flow()
    events = [json.loads(record.message) for record in caplog.records]
    event_types = {event["event_type"] for event in events}

    assert {
        "backup_research_requested",
        "backup_research_started",
        "backup_candidates_received",
        "backup_candidate_recommended",
        "backup_research_completed",
    } <= event_types
    assert not any("prompt" in event or "reasoning" in event for event in events)
