"""Deterministic proof for the location-aware showcase lifecycle."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from app.agent.backup_care_researcher import (
    BackupCareResearchResult,
    RankedBackupCareCandidate,
)
from app.agent.config import AgentArchitecture, RecoveryAgentConfig
from app.agent.constraint_planner import (
    PlannerOperation,
    build_planner_invocation_input,
)
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


def initial_showcase_brief(scenario=None) -> PlanningBrief:
    scenario = scenario or get_demo_scenario()
    return PlanningBrief(
        planning_mode=PlanningMode.INITIAL,
        planning_required=True,
        objective="Restore complete childcare coverage.",
        required_coverage_window=scenario.required_coverage,
        affected_windows=[scenario.required_coverage],
        relevant_constraint_categories=list(ConstraintCategory),
    )


def test_feasible_matrix_is_derived_and_soft_preferences_are_separate() -> None:
    scenario = get_demo_scenario()
    planner_input = build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=initial_showcase_brief(scenario),
        scenario=scenario,
    )
    matrix = planner_input.feasible_assignment_matrix

    assert matrix is not None
    assert planner_input.authoritative_context is None
    assert planner_input.soft_ranking_preferences == scenario.preferences.model_dump(mode="json")
    assert matrix.required_coverage_window == scenario.required_coverage
    assert matrix.family_home_location_id == scenario.family_home_location_id
    assert matrix.require_trusted_caregiver == scenario.policy.require_trusted_caregiver
    assert matrix.minimum_handoff_minutes == scenario.policy.minimum_handoff_minutes
    people = {item.person_id: item for item in matrix.people}
    for caregiver in scenario.caregivers:
        primitive = people[caregiver.caregiver_id]
        assert primitive.permitted_care_windows == caregiver.availability
        assert primitive.allowed_care_location_ids == [caregiver.location_id]
        assert primitive.source is CoverageSource.CAREGIVER
    transporters = {item.transporter_id for item in matrix.transport_primitives}
    assert transporters == {"grandma", "parent_a"}
    assert len(matrix.transport_primitives) > 1
    assert all(item.capability == "ALLOWED" for item in matrix.transport_primitives)
    assert matrix.continuous_supervision_required
    assert matrix.explicit_transport_for_location_changes_required


def test_canonical_initial_facts_require_sitter_afternoon_instead_of_parent_a() -> None:
    scenario = get_demo_scenario()
    matrix = build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=initial_showcase_brief(scenario),
        scenario=scenario,
    ).feasible_assignment_matrix

    assert matrix is not None
    people = {item.person_id: item for item in matrix.people}
    assert people["parent_a"].permitted_care_windows == [minute_window(8, 0, 9)]
    assert people["grandma"].permitted_care_windows == [minute_window(9, 0, 12, 15)]
    assert people["backup_sitter"].permitted_care_windows == [minute_window(12, 15, 16)]

    plan = showcase_plan_a()
    assert PlanValidator().validate(plan, scenario).valid
    assert plan.coverage_segments[-1].assigned_person_id == "backup_sitter"
    parent_afternoon = plan.model_copy(deep=True)
    parent_afternoon.coverage_segments[-1] = parent_afternoon.coverage_segments[-1].model_copy(
        update={
            "assigned_person_id": "parent_a",
            "source": CoverageSource.PARENT,
        }
    )
    assert ValidationErrorCode.PARENT_CRITICAL_CONFLICT in issue_codes(parent_afternoon, scenario)


def test_feasible_matrix_tracks_changed_generic_caregiver_and_route_facts() -> None:
    original = get_demo_scenario()
    changed_caregiver = original.caregivers[0].model_copy(
        update={
            "caregiver_id": "relative_x",
            "availability": [minute_window(10, 30, 13, 45)],
            "location_id": "relative_x_home",
            "travel_minutes_from_family_home": 23,
            "can_transport_child": True,
        }
    )
    scenario = replace(
        original,
        caregivers=(changed_caregiver, *original.caregivers[1:]),
        unavailable_caregiver_ids=("ordinary_provider_x",),
    )
    matrix = build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=initial_showcase_brief(scenario),
        scenario=scenario,
    ).feasible_assignment_matrix

    assert matrix is not None
    changed = next(item for item in matrix.people if item.person_id == "relative_x")
    assert changed.permitted_care_windows == [minute_window(10, 30, 13, 45)]
    assert changed.allowed_care_location_ids == ["relative_x_home"]
    assert any(
        primitive.transporter_id == "relative_x" for primitive in matrix.transport_primitives
    )
    assert {
        (
            primitive.origin_location_id,
            primitive.destination_location_id,
            primitive.required_duration_minutes,
        )
        for primitive in matrix.transport_primitives
        if "relative_x_home"
        in {
            primitive.origin_location_id,
            primitive.destination_location_id,
        }
    } == {
        ("family_home", "relative_x_home", 23),
        ("relative_x_home", "family_home", 23),
    }


def test_feasible_matrix_normalizes_parent_transport_capability_and_availability() -> None:
    original = get_demo_scenario()
    changed_parent = original.parent_transport_capabilities[0].model_copy(
        update={"availability": [minute_window(8, 15, 8, 45)]}
    )
    scenario = replace(
        original,
        parent_transport_capabilities=(
            changed_parent,
            *original.parent_transport_capabilities[1:],
        ),
    )
    matrix = build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=initial_showcase_brief(scenario),
        scenario=scenario,
    ).feasible_assignment_matrix

    assert matrix is not None
    parent_primitives = [
        item for item in matrix.transport_primitives if item.transporter_id == "parent_a"
    ]
    assert parent_primitives
    assert all(item.permitted_window == minute_window(8, 15, 8, 45) for item in parent_primitives)

    disabled = replace(
        scenario,
        parent_transport_capabilities=(
            changed_parent.model_copy(update={"can_transport_child": False}),
            *scenario.parent_transport_capabilities[1:],
        ),
    )
    disabled_matrix = build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=initial_showcase_brief(disabled),
        scenario=disabled,
    ).feasible_assignment_matrix
    assert disabled_matrix is not None
    assert all(item.transporter_id != "parent_a" for item in disabled_matrix.transport_primitives)


def test_transport_primitives_bind_capable_person_window_and_route() -> None:
    matrix = build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=initial_showcase_brief(),
        scenario=get_demo_scenario(),
    ).feasible_assignment_matrix

    assert matrix is not None
    outward = next(
        item
        for item in matrix.transport_primitives
        if item.transporter_id == "parent_a"
        and item.origin_location_id == "family_home"
        and item.destination_location_id == "grandma_home"
    )
    assert outward.permitted_window == minute_window(8, 45, 9)
    assert outward.required_duration_minutes == 15
    assert outward.capability == "ALLOWED"


def test_changing_caregiver_transport_capability_changes_transport_primitives() -> None:
    original = get_demo_scenario()
    capable_id = original.caregivers[0].caregiver_id
    original_matrix = build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=initial_showcase_brief(original),
        scenario=original,
    ).feasible_assignment_matrix
    changed = replace(
        original,
        caregivers=(
            original.caregivers[0].model_copy(update={"can_transport_child": False}),
            *original.caregivers[1:],
        ),
    )
    changed_matrix = build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=initial_showcase_brief(changed),
        scenario=changed,
    ).feasible_assignment_matrix

    assert original_matrix is not None and changed_matrix is not None
    assert any(item.transporter_id == capable_id for item in original_matrix.transport_primitives)
    assert all(item.transporter_id != capable_id for item in changed_matrix.transport_primitives)


def test_feasible_matrix_excludes_unavailable_or_hard_policy_ineligible_caregivers() -> None:
    original = get_demo_scenario()
    untrusted = original.caregivers[1].model_copy(
        update={"caregiver_id": "untrusted_x", "is_trusted": False}
    )
    scenario = replace(
        original,
        caregivers=(*original.caregivers, untrusted),
        unavailable_caregiver_ids=("nanny", original.caregivers[0].caregiver_id),
    )
    matrix = build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=initial_showcase_brief(scenario),
        scenario=scenario,
    ).feasible_assignment_matrix

    assert matrix is not None
    person_ids = {item.person_id for item in matrix.people}
    assert original.caregivers[0].caregiver_id not in person_ids
    assert "untrusted_x" not in person_ids


def test_feasible_matrix_uses_only_start_end_timestamp_fields() -> None:
    planner_input = build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=initial_showcase_brief(),
        scenario=get_demo_scenario(),
    )
    payload = planner_input.model_dump_json()

    assert '"feasible_assignment_matrix"' in payload
    assert '"start"' in payload and '"end"' in payload
    assert "available_from" not in payload
    assert "available_to" not in payload
    assert "starts_at" not in payload
    assert "ends_at" not in payload


def test_building_initial_brief_does_not_change_validator_result() -> None:
    scenario = replace(
        get_demo_scenario(),
        unavailable_caregiver_ids=("nanny", "grandma"),
        parent_transport_capabilities=tuple(
            item.model_copy(update={"can_transport_child": False})
            for item in get_demo_scenario().parent_transport_capabilities
        ),
    )
    before = PlanValidator().validate(showcase_plan_a(), scenario)

    build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=initial_showcase_brief(scenario),
        scenario=scenario,
    )
    after = PlanValidator().validate(showcase_plan_a(), scenario)

    assert after == before
    assert {issue.code for issue in after.issues} >= {
        ValidationErrorCode.CAREGIVER_UNAVAILABLE,
        ValidationErrorCode.TRANSPORTER_UNAVAILABLE,
    }


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
        minute_window(9, 0, 12, 15)
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


def test_connected_handoffs_are_reclassified_with_deterministic_reasons() -> None:
    outcome = declined_outcome()
    reasons = {item.segment_id: item for item in outcome.impact_reasons}

    assert reasons["grandma-care"].reason_code == "caregiver_availability_invalidated"
    for segment_id in ("to-grandma", "grandma-to-home"):
        assert reasons[segment_id].reason_code == "connected_handoff_invalidated"
        assert reasons[segment_id].depends_on_segment_id == "grandma-care"
        assert segment_id not in {segment.segment_id for segment in outcome.preserved_segments}
    assert outcome.recovery_case.context_state["segment_impact_reasons"] == [
        reason.model_dump(mode="json") for reason in outcome.impact_reasons
    ]


def test_repair_validator_rejects_unnecessary_change_to_preserved_afternoon() -> None:
    outcome = declined_outcome()
    plan, scenario = plan_b()
    assert PlanValidator().validate_repair(plan, scenario, list(outcome.preserved_segments)).valid

    provider_id = "harbor_nanny_coop"
    expanded_caregivers = tuple(
        caregiver.model_copy(update={"availability": [minute_window(8, 45, 16)]})
        if caregiver.caregiver_id == provider_id
        else caregiver
        for caregiver in scenario.caregivers
    )
    expanded_scenario = replace(scenario, caregivers=expanded_caregivers)
    reoptimized = plan.model_copy(
        update={
            "coverage_segments": [
                plan.coverage_segments[0],
                plan.coverage_segments[1].model_copy(update={"window": minute_window(8, 45, 16)}),
            ]
        }
    )

    assert PlanValidator().validate(reoptimized, expanded_scenario).valid
    guarded = PlanValidator().validate_repair(
        reoptimized,
        expanded_scenario,
        list(outcome.preserved_segments),
    )
    assert not guarded.valid
    assert {
        issue.segment_id
        for issue in guarded.issues
        if issue.code is ValidationErrorCode.PRESERVED_SEGMENT_CHANGED
    } == {"sitter-late"}


def test_decline_requires_grounded_research_and_exposes_transport_facts() -> None:
    outcome = declined_outcome()
    need = assess_known_option_recovery_need(outcome.updated_scenario)
    search = search_backup_care_candidates(outcome.updated_scenario, need.requested_windows)

    assert need.research_needed
    assert need.requested_windows == [minute_window(9, 0, 12, 15)]
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
    planner_source = (root / "agent/constraint_planner.py").read_text().lower()
    for showcase_literal in ("backup_sitter", "parent_a", "08:45", "8:45", "12:15"):
        assert showcase_literal not in planner_source


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
                    requested_windows=[minute_window(9, 0, 12, 15)],
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
    assert [segment.segment_id for segment in result.preserved_segments] == [
        "parent-early",
        "sitter-late",
    ]
    assert [segment.assigned_person_id for segment in result.final_plan.coverage_segments] == [
        "parent_a",
        "harbor_nanny_coop",
        "backup_sitter",
    ]
    assert brief.affected_segment_reasons
