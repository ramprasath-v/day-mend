"""Canonical demo-date rebasing and snapshot-isolation proofs."""

from collections.abc import Iterator
from datetime import date, datetime

from fastapi.testclient import TestClient

from app.agent.constraint_planner import PlannerOperation, build_planner_invocation_input
from app.agent.recovery_agent import InitialPlanningResult, PlanningAttempt
from app.agent.recovery_orchestrator import ConstraintCategory, PlanningBrief, PlanningMode
from app.application import RecoveryApplicationService, StartRecoveryCommand
from app.application.family_service import FamilyService
from app.fixtures import DemoScenario, DemoTimeline, get_demo_scenario
from app.main import create_app
from app.models import CoverageWindow, RecoveryPlan
from app.repositories import InMemoryRecoveryCaseRepository
from app.repositories.family_repository import InMemoryFamilyRepository
from app.services import (
    PlanInvalidationService,
    PlanValidator,
    add_researched_caregiver,
    create_active_recovery_case,
)
from tests.milestone2_helpers import showcase_plan_a
from tests.test_location_transport import decline_event, plan_b


def _on_date(value: datetime, care_date: date) -> datetime:
    return value.replace(year=care_date.year, month=care_date.month, day=care_date.day)


def _rebase_plan(plan: RecoveryPlan, care_date: date) -> RecoveryPlan:
    segments = [
        segment.model_copy(
            update={
                "window": CoverageWindow(
                    start=_on_date(segment.window.start, care_date),
                    end=_on_date(segment.window.end, care_date),
                )
            }
        )
        for segment in plan.coverage_segments
    ]
    return plan.model_copy(update={"coverage_segments": segments})


def _scenario_dates(scenario: DemoScenario) -> set[date]:
    values = [scenario.required_coverage.start, scenario.required_coverage.end]
    values.extend(
        timestamp
        for event in scenario.parent_events
        for timestamp in (event.window.start, event.window.end)
    )
    values.extend(
        timestamp
        for caregiver in scenario.caregivers
        for window in caregiver.availability
        for timestamp in (window.start, window.end)
    )
    values.extend(
        timestamp
        for capability in scenario.parent_transport_capabilities
        for window in capability.availability
        for timestamp in (window.start, window.end)
    )
    values.extend(
        timestamp
        for candidate in scenario.backup_care_candidates
        for window in candidate.availability
        for timestamp in (window.start, window.end)
    )
    return {value.date() for value in values}


def test_arbitrary_demo_date_rebases_every_authoritative_window_and_plan_a() -> None:
    care_date = date(2031, 2, 3)
    scenario = get_demo_scenario(care_date)
    plan = _rebase_plan(showcase_plan_a(), care_date)

    assert _scenario_dates(scenario) == {care_date}
    assert [
        (
            segment.window.start.strftime("%H:%M"),
            segment.window.end.strftime("%H:%M"),
            segment.assigned_person_id,
            segment.location_id,
        )
        for segment in plan.coverage_segments
    ] == [
        ("08:00", "08:45", "parent_a", "family_home"),
        ("08:45", "09:00", "parent_a", "family_home"),
        ("09:00", "12:00", "grandma", "grandma_home"),
        ("12:00", "12:15", "grandma", "grandma_home"),
        ("12:15", "16:00", "backup_sitter", "family_home"),
    ]
    assert PlanValidator().validate(plan, scenario).valid


def test_arbitrary_demo_date_preserves_decline_and_plan_b_matrix() -> None:
    care_date = date(2032, 11, 9)
    timeline = DemoTimeline(care_date)
    scenario = get_demo_scenario(care_date)
    plan_a = _rebase_plan(showcase_plan_a(), care_date)
    active = create_active_recovery_case(
        case_id="rebased-case",
        disruption=scenario.disruption,
        validated_plan=plan_a,
        required_coverage=scenario.required_coverage,
        now=timeline.at(8, 10),
    )
    event = decline_event().model_copy(
        update={
            "occurred_at": timeline.at(9, 5),
            "relevant_window": timeline.window(9, 12, 0, 15),
        }
    )
    outcome = PlanInvalidationService().apply_caregiver_decline(active, event, scenario)
    candidate = next(
        item
        for item in outcome.updated_scenario.backup_care_candidates
        if item.candidate_id == "harbor_nanny_coop"
    )
    updated = add_researched_caregiver(outcome.updated_scenario, candidate)
    brief = PlanningBrief(
        recovery_case_id=active.case_id,
        planning_mode=PlanningMode.WORLD_STATE_REPLAN,
        planning_required=True,
        objective="Repair affected care while preserving valid work.",
        required_coverage_window=updated.required_coverage,
        affected_windows=list(outcome.uncovered_windows),
        affected_segments=list(outcome.impacted_segments),
        preserved_segments=list(outcome.preserved_segments),
        excluded_caregiver_ids=["grandma"],
        relevant_constraint_categories=list(ConstraintCategory),
        known_options_insufficient=True,
        unresolved_known_option_windows=list(outcome.uncovered_windows),
        backup_research_needed=True,
        researched_candidate_ids=[candidate.candidate_id],
        recommended_backup_care_candidate_id=candidate.candidate_id,
    )
    matrix = build_planner_invocation_input(
        operation=PlannerOperation.REPLANNING,
        brief=brief,
        scenario=updated,
    ).feasible_assignment_matrix

    assert matrix is not None
    assert [
        (
            item.assigned_person_id,
            item.window.start.strftime("%H:%M"),
            item.window.end.strftime("%H:%M"),
            item.location_id,
            item.immutable,
        )
        for item in matrix.care_primitives
    ] == [
        ("parent_a", "08:00", "08:45", "family_home", True),
        ("harbor_nanny_coop", "08:45", "12:15", "family_home", False),
        ("backup_sitter", "12:15", "16:00", "family_home", True),
    ]
    assert matrix.transport_primitives == []
    canonical_plan_b, _ = plan_b()
    rebased_plan_b = _rebase_plan(canonical_plan_b, care_date)
    assert (
        PlanValidator()
        .validate_repair(
            rebased_plan_b,
            updated,
            list(outcome.preserved_segments),
        )
        .valid
    )


class _ScenarioPlanGateway:
    def plan_initial(self, _disruption: str, scenario: DemoScenario) -> InitialPlanningResult:
        care_date = scenario.required_coverage.start.date()
        plan = _rebase_plan(showcase_plan_a(), care_date)
        validation = PlanValidator().validate(plan, scenario)
        return InitialPlanningResult(
            success=validation.valid,
            total_attempts=1,
            model_id="date-rebase-test",
            attempts=[
                PlanningAttempt(
                    attempt_number=1,
                    proposed_plan=plan,
                    validation=validation,
                )
            ],
            final_plan=validation.validated_plan,
            deterministic_total_cost=validation.deterministic_total_cost,
            requires_approval=validation.requires_approval,
        )

    def replan(self, *_args, **_kwargs):
        raise AssertionError("Replanning is outside this date snapshot test.")


def test_reset_reseeds_profile_without_mutating_existing_recovery_snapshot() -> None:
    dates: Iterator[date] = iter([date(2026, 8, 27), date(2033, 6, 14)])
    family = FamilyService(
        InMemoryFamilyRepository(),
        get_demo_scenario,
        demo_date_source=lambda: next(dates),
    )
    repository = InMemoryRecoveryCaseRepository()
    case_ids = iter(["historical-case", "new-case"])
    app = RecoveryApplicationService(
        repository,
        _ScenarioPlanGateway(),
        family_service=family,
        id_factory=lambda: next(case_ids),
    )
    old_profile = family.get()
    old_case = app.start_recovery(
        StartRecoveryCommand(
            disruption_type="CHILDCARE_UNAVAILABLE",
            occurred_at=DemoTimeline(date(2026, 8, 27)).at(7, 2),
            caregiver_id="nanny",
            message="Unavailable",
        )
    )

    reseeded = family.reset_demo()
    old_snapshot_after_reset = app._scenario_for(app.get_recovery(old_case.case_id))
    new_case = app.start_recovery(
        StartRecoveryCommand(
            disruption_type="CHILDCARE_UNAVAILABLE",
            occurred_at=DemoTimeline(date(2033, 6, 14)).at(7, 2),
            caregiver_id="nanny",
            message="Unavailable",
        )
    )

    assert old_profile.required_care_schedule.start.date() == date(2026, 8, 27)
    assert reseeded.version == old_profile.version + 1
    assert reseeded.required_care_schedule.start.date() == date(2033, 6, 14)
    assert old_snapshot_after_reset.required_coverage.start.date() == date(2026, 8, 27)
    assert app._scenario_for(new_case).required_coverage.start.date() == date(2033, 6, 14)
    assert repository.get(old_case.case_id) == old_case


def test_family_reset_endpoint_replaces_the_old_seed_with_one_new_date() -> None:
    dates: Iterator[date] = iter([date(2026, 8, 27), date(2034, 4, 18)])
    family = FamilyService(
        InMemoryFamilyRepository(),
        get_demo_scenario,
        demo_date_source=lambda: next(dates),
    )
    service = RecoveryApplicationService(
        InMemoryRecoveryCaseRepository(),
        _ScenarioPlanGateway(),
        family_service=family,
    )
    client = TestClient(create_app(service))

    original = client.get("/family")
    reset = client.post("/family/reset")

    assert original.status_code == 200
    assert reset.status_code == 200
    assert original.json()["required_care_schedule"]["start"].startswith("2026-08-27")
    assert reset.json()["required_care_schedule"]["start"].startswith("2034-04-18")
    assert reset.json()["version"] == original.json()["version"] + 1
