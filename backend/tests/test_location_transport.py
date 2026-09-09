"""Deterministic proof for the location-aware showcase lifecycle."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from app.agent.backup_care_researcher import (
    BackupCareResearchResult,
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
from app.agent.runtime_contracts import ScenarioContract
from app.fixtures import get_demo_scenario
from app.models import (
    CoverageSource,
    ParentTransportCapability,
    PlanSegmentType,
    RecoveryEvent,
    RecoveryEventType,
    RecoveryPlan,
    RecoveryPlanSegment,
)
from app.services import (
    PlanInvalidationService,
    PlanValidator,
    ValidationErrorCode,
    add_researched_caregiver,
    assess_known_option_recovery_need,
    create_active_recovery_case,
    search_backup_care_candidates,
)
from tests.milestone2_helpers import at, minute_window, showcase_plan_a


def decline_event() -> RecoveryEvent:
    return RecoveryEvent(
        event_id="showcase-grandma-decline",
        event_type=RecoveryEventType.CAREGIVER_DECLINED,
        caregiver_id="grandma",
        relevant_window=minute_window(9, 0, 12, 15),
        occurred_at=at(8, 20),
        message="Unavailable for today's care and return trip.",
    )


def declined_outcome():
    scenario = get_demo_scenario()
    active = create_active_recovery_case(
        case_id="showcase-case",
        disruption=scenario.disruption,
        validated_plan=showcase_plan_a(),
        required_coverage=scenario.required_coverage,
        now=at(8, 10),
    )
    return PlanInvalidationService().apply_caregiver_decline(active, decline_event(), scenario)


def plan_b() -> tuple[RecoveryPlan, object]:
    outcome = declined_outcome()
    candidate = next(
        candidate
        for candidate in outcome.updated_scenario.backup_care_candidates
        if candidate.candidate_id == "harbor_nanny_coop"
    )
    scenario = add_researched_caregiver(outcome.updated_scenario, candidate)
    plan = RecoveryPlan(
        plan_id="showcase-plan-b",
        coverage_segments=[
            outcome.preserved_segments[0],
            RecoveryPlanSegment(
                segment_id="in-home-backup",
                window=minute_window(8, 45, 12, 15),
                assigned_person_id=candidate.candidate_id,
                source=CoverageSource.CAREGIVER,
            ),
            outcome.preserved_segments[-1],
        ],
    )
    return plan, scenario


def issue_codes(plan: RecoveryPlan, scenario=None) -> set[ValidationErrorCode]:
    result = PlanValidator().validate(plan, scenario or get_demo_scenario())
    return {issue.code for issue in result.issues}


def test_location_facts_round_trip_through_agentcore_contract() -> None:
    scenario = get_demo_scenario()
    restored = ScenarioContract.model_validate_json(
        ScenarioContract.from_scenario(scenario).model_dump_json()
    ).to_scenario()

    assert restored == scenario
    grandma = next(item for item in restored.caregivers if item.caregiver_id == "grandma")
    assert grandma.location_id == "grandma_home"
    assert grandma.travel_minutes_from_family_home == 15
    assert restored.parent_transport_capabilities[0].availability == [minute_window(8, 45, 9)]


def test_showcase_plan_a_is_physically_feasible_and_depends_on_grandma() -> None:
    scenario = get_demo_scenario()
    plan = showcase_plan_a()

    assert PlanValidator().validate(plan, scenario).valid
    assert any(
        segment.assigned_person_id == "grandma" and segment.segment_type is PlanSegmentType.CARE
        for segment in plan.coverage_segments
    )
    without_grandma = replace(
        scenario,
        unavailable_caregiver_ids=(*scenario.unavailable_caregiver_ids, "grandma"),
    )
    assert assess_known_option_recovery_need(without_grandma).requested_windows == [
        minute_window(9, 0, 12)
    ]


def test_travel_duration_is_respected() -> None:
    plan = showcase_plan_a().model_copy(deep=True)
    drive = plan.coverage_segments[1]
    plan.coverage_segments[1] = drive.model_copy(update={"window": minute_window(8, 50, 9)})

    assert ValidationErrorCode.INSUFFICIENT_TRAVEL_TIME in issue_codes(plan)


def test_child_cannot_teleport_between_care_locations() -> None:
    plan = showcase_plan_a().model_copy(deep=True)
    plan.coverage_segments = [
        plan.coverage_segments[0].model_copy(update={"window": minute_window(8, 0, 9)}),
        *plan.coverage_segments[2:],
    ]

    assert ValidationErrorCode.LOCATION_TRANSITION_INVALID in issue_codes(plan)


def test_transporter_must_be_capable_and_available() -> None:
    scenario = replace(
        get_demo_scenario(),
        parent_transport_capabilities=(
            ParentTransportCapability(parent_id="parent_a", can_transport_child=False),
            ParentTransportCapability(parent_id="parent_b", can_transport_child=False),
        ),
    )

    assert ValidationErrorCode.TRANSPORTER_UNAVAILABLE in issue_codes(showcase_plan_a(), scenario)


def test_parent_transport_cannot_overlap_critical_meeting() -> None:
    scenario = get_demo_scenario()
    event = scenario.parent_events[0].model_copy(update={"window": minute_window(8, 50, 12)})
    scenario = replace(scenario, parent_events=(event, *scenario.parent_events[1:]))

    assert ValidationErrorCode.PARENT_CRITICAL_CONFLICT in issue_codes(showcase_plan_a(), scenario)


def test_transport_time_is_continuous_supervision() -> None:
    plan = showcase_plan_a()
    assert plan.coverage_segments[0].window.end == plan.coverage_segments[1].window.start
    assert plan.coverage_segments[1].window.end == plan.coverage_segments[2].window.start
    assert PlanValidator().validate(plan, get_demo_scenario()).valid


def test_decline_invalidates_related_handoffs_and_preserves_other_care() -> None:
    outcome = declined_outcome()

    assert [item.segment_id for item in outcome.impacted_segments] == [
        "to-grandma",
        "grandma-care",
        "grandma-to-home",
    ]
    assert [item.segment_id for item in outcome.preserved_segments] == [
        "parent-early",
        "sitter-late",
    ]
    assert list(outcome.uncovered_windows) == [minute_window(8, 45, 12, 15)]


def test_decline_requires_grounded_research_and_exposes_transport_facts() -> None:
    outcome = declined_outcome()
    need = assess_known_option_recovery_need(outcome.updated_scenario)
    search = search_backup_care_candidates(outcome.updated_scenario, need.requested_windows)

    assert need.research_needed
    assert need.requested_windows == [minute_window(9, 0, 12)]
    assert len(search.eligible_candidates) == 2
    assert any(
        item.location_id == "family_home" and item.travel_minutes_from_family_home == 0
        for item in search.eligible_candidates
    )
    assert any(
        item.location_id != "family_home" and item.travel_minutes_from_family_home > 0
        for item in search.eligible_candidates
    )


def test_in_home_plan_b_is_valid_and_keeps_existing_approval_rules() -> None:
    plan, scenario = plan_b()
    result = PlanValidator().validate(plan, scenario)

    assert result.valid
    assert result.requires_approval
    assert result.deterministic_total_cost == 94.50
    assert all(
        segment.segment_type is PlanSegmentType.CARE
        for segment in result.validated_plan.coverage_segments
    )


def test_generic_planning_and_validation_do_not_name_demo_caregiver() -> None:
    root = Path(__file__).parents[1] / "app"
    for relative in (
        "services/plan_validator.py",
        "services/plan_invalidation.py",
        "agent/instructions.py",
        "agent/constraint_planner.py",
    ):
        assert "grandma" not in (root / relative).read_text().lower()


def test_multi_research_replan_invokes_existing_research_agent() -> None:
    scenario = get_demo_scenario()
    active = create_active_recovery_case(
        case_id="showcase-research-case",
        disruption=scenario.disruption,
        validated_plan=showcase_plan_a(),
        required_coverage=scenario.required_coverage,
        now=at(8, 10),
    )
    research_recorder = ToolInvocationRecorder(allowed_tool_names={"search_backup_care"})

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
            research_recorder.tool_names.append("search_backup_care")
            ids = ["harbor_nanny_coop", "willow_family_care"]
            return SimpleNamespace(
                structured_output=BackupCareResearchResult(
                    research_id="untrusted-model-id",
                    requested_windows=[minute_window(9, 0, 12)],
                    ranked_candidates=[
                        RankedBackupCareCandidate(
                            candidate_id=candidate_id,
                            rank=index,
                            fit_summary="Grounded synthetic candidate.",
                            tradeoffs=["Location and transport burden."],
                        )
                        for index, candidate_id in enumerate(ids, start=1)
                    ],
                    recommended_candidate_id="harbor_nanny_coop",
                )
            )

    candidate_plan, _ = plan_b()

    class Planner:
        def __call__(self, _prompt, *, structured_output_model=None):
            return SimpleNamespace(
                structured_output=candidate_plan if structured_output_model else None
            )

    result, brief = run_multi_agent_replanning(
        recovery_case=active,
        event=decline_event(),
        scenario=scenario,
        config=RecoveryAgentConfig(
            model_id="offline-location-test",
            region_name="us-east-1",
            architecture=AgentArchitecture.MULTI_RESEARCH,
        ),
        orchestrator=Orchestrator(),
        researcher=Researcher(),
        planner=Planner(),
        researcher_recorder=research_recorder,
    )

    assert result.success
    assert result.research_agent_invocation_count == 1
    assert result.researched_candidate is not None
    assert brief.backup_research_needed
