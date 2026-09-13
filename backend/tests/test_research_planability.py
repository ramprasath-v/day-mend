"""Deterministic post-research planability-gate regression coverage."""

import json
import logging
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.agent.backup_care_researcher import (
    BackupCareResearchResult,
    BackupCareResearchRun,
    RankedBackupCareCandidate,
)
from app.agent.config import AgentArchitecture, RecoveryAgentConfig
from app.agent.multi_agent import run_multi_agent_replanning
from app.agent.recovery_agent import ToolInvocationRecorder
from app.agent.recovery_orchestrator import (
    ConstraintCategory,
    PlanningBrief,
    PlanningMode,
)
from app.agent.research_planability import (
    NoPlanableResearchCandidateError,
    select_planable_research_candidate,
)
from app.fixtures import get_demo_scenario
from app.models import CareLocationType
from app.observability import LOGGER_NAME
from app.services import (
    PlanInvalidationService,
    assess_known_option_recovery_need,
    create_active_recovery_case,
    search_backup_care_candidates,
)
from tests.milestone2_helpers import at, showcase_plan_a
from tests.test_location_transport import decline_event


def _outcome(scenario=None):
    scenario = scenario or get_demo_scenario()
    active = create_active_recovery_case(
        case_id="planability-case",
        disruption=scenario.disruption,
        validated_plan=showcase_plan_a(),
        required_coverage=scenario.required_coverage,
        now=at(8, 10),
    )
    return PlanInvalidationService().apply_caregiver_decline(active, decline_event(), scenario)


def _brief(outcome) -> PlanningBrief:
    return PlanningBrief(
        recovery_case_id=outcome.recovery_case.case_id,
        planning_mode=PlanningMode.WORLD_STATE_REPLAN,
        planning_required=True,
        objective="Repair only affected care and preserve valid work.",
        required_coverage_window=outcome.updated_scenario.required_coverage,
        affected_windows=list(outcome.uncovered_windows),
        affected_segments=list(outcome.impacted_segments),
        preserved_segments=list(outcome.preserved_segments),
        excluded_caregiver_ids=["grandma"],
        relevant_constraint_categories=list(ConstraintCategory),
        known_options_insufficient=True,
        unresolved_known_option_windows=list(outcome.uncovered_windows),
        backup_research_needed=True,
    )


def _research_run(scenario, *, ranked_ids: list[str]) -> BackupCareResearchRun:
    need = assess_known_option_recovery_need(scenario)
    search = search_backup_care_candidates(scenario, need.requested_windows)
    candidates = {candidate.candidate_id: candidate for candidate in search.eligible_candidates}
    result = BackupCareResearchResult(
        research_id="grounded-planability-test",
        requested_windows=need.requested_windows,
        considered_candidate_ids=[
            assessment.candidate.candidate_id for assessment in search.considered_candidates
        ],
        eligible_candidate_ids=[candidate.candidate_id for candidate in search.eligible_candidates],
        ranked_candidates=[
            RankedBackupCareCandidate(
                candidate_id=candidate_id,
                rank=rank,
                fit_summary="Grounded research ranking.",
                tradeoffs=["Location and transport burden."],
            )
            for rank, candidate_id in enumerate(ranked_ids, start=1)
        ],
        recommended_candidate_id=ranked_ids[0],
    )
    return BackupCareResearchRun(
        result=result,
        search_result=search,
        recommended_candidate=candidates[ranked_ids[0]],
    )


def test_gate_skips_infeasible_rank_one_and_selects_feasible_rank_two(caplog) -> None:
    outcome = _outcome()
    research = _research_run(
        outcome.updated_scenario,
        ranked_ids=["willow_family_care", "harbor_nanny_coop"],
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        selected = select_planable_research_candidate(
            research_run=research,
            scenario=outcome.updated_scenario,
            brief=_brief(outcome),
        )

    assert research.result.ranked_candidates[0].candidate_id == "willow_family_care"
    assert selected.candidate.candidate_id == "harbor_nanny_coop"
    assert selected.rank == 2
    assert [
        (
            primitive.assigned_person_id,
            primitive.window.start.strftime("%H:%M"),
            primitive.window.end.strftime("%H:%M"),
            primitive.location_id,
            primitive.immutable,
        )
        for primitive in selected.matrix.care_primitives
    ] == [
        ("parent_a", "08:00", "08:45", "family_home", True),
        ("harbor_nanny_coop", "08:45", "12:15", "family_home", False),
        ("backup_sitter", "12:15", "16:00", "family_home", True),
    ]
    assert selected.matrix.transport_primitives == []

    events = [json.loads(record.message) for record in caplog.records]
    evaluated = [event for event in events if event["event_type"] == "research_candidate_evaluated"]
    assert evaluated == [
        {
            "event_type": "research_candidate_evaluated",
            "candidate_id": "willow_family_care",
            "rank": 1,
            "feasible": False,
            "care_primitive_count": 0,
            "transport_primitive_count": 0,
        },
        {
            "event_type": "research_candidate_evaluated",
            "candidate_id": "harbor_nanny_coop",
            "rank": 2,
            "feasible": True,
            "care_primitive_count": 3,
            "transport_primitive_count": 0,
        },
    ]


def _all_offsite_scenario():
    scenario = get_demo_scenario()
    offsite = tuple(
        candidate.model_copy(
            update={
                "care_location_type": CareLocationType.CAREGIVER_HOME,
                "location_id": f"{candidate.candidate_id}_home",
                "location_label": f"{candidate.display_name} home",
                "travel_minutes_from_family_home": 12,
                "can_transport_child": False,
            }
        )
        for candidate in scenario.backup_care_candidates[:2]
    )
    return replace(scenario, backup_care_candidates=offsite)


def test_gate_fails_safely_when_every_grounded_candidate_is_disconnected(caplog) -> None:
    scenario = _all_offsite_scenario()
    outcome = _outcome(scenario)
    research = _research_run(
        outcome.updated_scenario,
        ranked_ids=[candidate.candidate_id for candidate in scenario.backup_care_candidates],
    )

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        with pytest.raises(NoPlanableResearchCandidateError, match="cannot form"):
            select_planable_research_candidate(
                research_run=research,
                scenario=outcome.updated_scenario,
                brief=_brief(outcome),
            )

    events = [json.loads(record.message) for record in caplog.records]
    assert [
        event["candidate_id"]
        for event in events
        if event["event_type"] == "research_candidate_evaluated"
    ] == [candidate.candidate_id for candidate in scenario.backup_care_candidates]
    assert events[-1]["event_type"] == "research_candidates_exhausted"


def test_local_replanning_does_not_invoke_planner_when_research_has_no_planable_candidate() -> None:
    scenario = _all_offsite_scenario()
    active = create_active_recovery_case(
        case_id="no-planable-candidate-case",
        disruption=scenario.disruption,
        validated_plan=showcase_plan_a(),
        required_coverage=scenario.required_coverage,
        now=at(8, 10),
    )
    recorder = ToolInvocationRecorder(allowed_tool_names={"search_backup_care"})
    ranked_ids = [candidate.candidate_id for candidate in scenario.backup_care_candidates]

    class Orchestrator:
        def __call__(self, _prompt, *, structured_output_model=None):
            return SimpleNamespace(
                structured_output=PlanningBrief(
                    planning_mode=PlanningMode.WORLD_STATE_REPLAN,
                    planning_required=True,
                    objective="Repair affected care while preserving valid work.",
                    required_coverage_window=scenario.required_coverage,
                    relevant_constraint_categories=list(ConstraintCategory),
                )
            )

    class Researcher:
        def __call__(self, _prompt, *, structured_output_model=None):
            recorder.tool_names.append("search_backup_care")
            return SimpleNamespace(
                structured_output=BackupCareResearchResult(
                    research_id="model-id-is-normalized",
                    requested_windows=[],
                    ranked_candidates=[
                        RankedBackupCareCandidate(
                            candidate_id=candidate_id,
                            rank=rank,
                            fit_summary="Grounded ranking.",
                            tradeoffs=["Offsite transport is required."],
                        )
                        for rank, candidate_id in enumerate(ranked_ids, start=1)
                    ],
                    recommended_candidate_id=ranked_ids[0],
                )
            )

    class Planner:
        calls = 0

        def __call__(self, _prompt, *, structured_output_model=None):
            self.calls += 1
            pytest.fail("Planner must not run with an empty feasible matrix")

    planner = Planner()
    with pytest.raises(NoPlanableResearchCandidateError, match="cannot form"):
        run_multi_agent_replanning(
            recovery_case=active,
            event=decline_event(),
            scenario=scenario,
            config=RecoveryAgentConfig(
                model_id="offline-planability-test",
                region_name="us-east-1",
                architecture=AgentArchitecture.MULTI_RESEARCH,
            ),
            orchestrator=Orchestrator(),
            researcher=Researcher(),
            planner=planner,
            researcher_recorder=recorder,
        )

    assert planner.calls == 0
