"""Offline family edits, policy enforcement and snapshot isolation."""

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.agent.constraint_planner import PlannerOperation, build_planner_invocation_input
from app.agent.runtime_contracts import ScenarioContract
from app.application import RecoveryApplicationService, StartRecoveryCommand
from app.application.family_service import FamilyService
from app.fixtures import get_demo_scenario, get_legacy_demo_scenario
from app.main import create_app
from app.models import PlanApprovalReason, RecoveryStatus
from app.models.family import FamilyUpdate, PolicyUpdate, PreferencesUpdate
from app.repositories import InMemoryRecoveryCaseRepository
from app.repositories.family_repository import FamilyVersionConflict, InMemoryFamilyRepository
from app.services import (
    PlanValidator,
    add_researched_caregiver,
    assess_known_option_recovery_need,
    search_backup_care_candidates,
)
from tests.milestone2_helpers import at, showcase_plan_a
from tests.test_api import DeterministicPlanningGateway
from tests.test_location_transport import initial_showcase_brief, plan_b


def service():
    return FamilyService(InMemoryFamilyRepository())


def family_edit(profile):
    keys = {
        "caregiver_id",
        "name",
        "relationship",
        "availability",
        "can_transport_child",
        "location_id",
        "is_trusted",
    }
    return {
        "expected_version": profile.version,
        "required_care_schedule": profile.required_care_schedule.model_dump(mode="json"),
        "caregivers": [c.model_dump(mode="json", include=keys) for c in profile.caregivers],
    }


def policy_edit(profile, **changes):
    return PolicyUpdate(
        expected_version=profile.version,
        automatic_spend_limit=changes.get(
            "automatic_spend_limit", profile.policy.automatic_spend_limit
        ),
        require_approval_for_unfamiliar_provider=changes.get("unfamiliar", True),
        allow_external_backup_providers=changes.get("external", True),
        allow_provider_transport=changes.get("transport", True),
        notification_mode=changes.get("notification_mode", "meaningful_changes"),
    )


def matrix(scenario):
    return build_planner_invocation_input(
        operation=PlannerOperation.INITIAL_PLANNING,
        brief=initial_showcase_brief(scenario),
        scenario=scenario,
    ).feasible_assignment_matrix


def test_default_profile_preserves_canonical_scenario_and_plan_a():
    family = service()
    profile = family.get()
    assert family.get() == profile
    assert profile.version == 1
    assert family.scenario(profile) == get_demo_scenario()
    assert profile.policy.automatic_spend_limit == Decimal("30")
    assert profile.policy.require_approval_for_unfamiliar_paid_caregiver
    assert PlanValidator().validate(showcase_plan_a(), family.scenario(profile)).valid


def test_family_http_get_put_and_separate_sections():
    app_service = RecoveryApplicationService(
        InMemoryRecoveryCaseRepository(), DeterministicPlanningGateway()
    )
    client = TestClient(create_app(app_service))
    initial = client.get("/family")
    assert initial.status_code == 200
    profile = app_service.family_service.get()
    edit = family_edit(profile)
    edit["caregivers"][0].update(
        name="Family helper", can_transport_child=False, is_trusted=False, location_id="family_home"
    )
    updated = client.put("/family", json=edit)
    assert updated.status_code == 200
    caregiver = updated.json()["caregivers"][0]
    assert caregiver["name"] == "Family helper"
    assert not caregiver["can_transport_child"] and not caregiver["is_trusted"]
    assert caregiver["travel_minutes_from_family_home"] == 0
    assert client.get("/family").json() == updated.json()
    assert client.get("/family/preferences").status_code == 200
    assert client.get("/family/policy").status_code == 200
    assert client.put("/family", json=edit).status_code == 409
    preferences = client.put(
        "/family/preferences",
        json={
            "expected_version": 2,
            "prefer_trusted_caregivers": True,
            "prefer_in_home_care": True,
            "minimize_handoffs": False,
            "protect_critical_meetings": True,
        },
    )
    assert preferences.status_code == 200
    updated_profile = app_service.family_service.get()
    result = client.put(
        "/family/policy",
        json=policy_edit(
            updated_profile,
            automatic_spend_limit="87.75",
            notification_mode="decisions_only",
        ).model_dump(mode="json"),
    )
    assert result.status_code == 200
    assert result.json()["policy"]["automatic_spend_limit"] == "87.75"
    assert result.json()["notification_mode"] == "decisions_only"


@pytest.mark.parametrize("invalid", ["window", "overlap", "location", "duplicate", "extra"])
def test_invalid_family_facts_return_422_without_saving(invalid):
    app_service = RecoveryApplicationService(
        InMemoryRecoveryCaseRepository(), DeterministicPlanningGateway()
    )
    client = TestClient(create_app(app_service))
    profile = app_service.family_service.get()
    edit = family_edit(profile)
    caregiver = edit["caregivers"][0]
    if invalid == "window":
        caregiver["availability"][0]["end"] = caregiver["availability"][0]["start"]
    elif invalid == "overlap":
        caregiver["availability"].append(caregiver["availability"][0])
    elif invalid == "location":
        caregiver["location_id"] = "invented-route"
    elif invalid == "duplicate":
        edit["caregivers"].append(caregiver)
    else:
        caregiver["hourly_rate"] = "0"
    assert client.put("/family", json=edit).status_code == 422
    assert app_service.family_service.get() == profile


@pytest.mark.parametrize("amount", ["-1", "1.001", "NaN", "Infinity"])
def test_invalid_spending_values_rejected(amount):
    with pytest.raises(ValueError):
        policy_edit(service().get(), automatic_spend_limit=amount)


def test_profile_facts_change_care_and_transport_primitives():
    family = service()
    profile = family.get()
    edit = family_edit(profile)
    caregiver = edit["caregivers"][0]
    caregiver["can_transport_child"] = False
    caregiver["availability"][0]["start"] = at(10).isoformat()
    updated = family.update(FamilyUpdate.model_validate(edit))
    result = matrix(family.scenario(updated))
    assert all(p.transporter_id != caregiver["caregiver_id"] for p in result.transport_primitives)
    person = next(p for p in result.people if p.person_id == caregiver["caregiver_id"])
    assert person.permitted_care_windows[0].start == at(10)


def test_connected_need_detects_missing_caregiver_transport_despite_time_coverage():
    scenario = get_demo_scenario()
    scenario = replace(
        scenario,
        caregivers=(
            scenario.caregivers[0].model_copy(update={"can_transport_child": False}),
            *scenario.caregivers[1:],
        ),
    )

    need = assess_known_option_recovery_need(scenario)

    assert need.known_options_insufficient
    assert need.research_needed
    assert need.requested_windows == [
        type(scenario.required_coverage)(
            start=at(8, 45),
            end=at(12, 15),
        )
    ]
    assert not matrix(scenario).care_primitives
    assert not matrix(scenario).transport_primitives


def test_shortened_required_care_uses_connected_path_only_through_new_end():
    scenario = get_demo_scenario()
    shortened = replace(
        scenario,
        required_coverage=scenario.required_coverage.model_copy(
            update={"end": scenario.required_coverage.end - timedelta(hours=2)}
        ),
    )

    need = assess_known_option_recovery_need(shortened)
    result = matrix(shortened)

    assert not need.known_options_insufficient
    assert need.requested_windows == []
    assert result.required_coverage_window.end == at(14)
    assert any(item.window.end == at(14) for item in result.care_primitives)
    assert all(item.window.end <= at(14) for item in result.care_primitives)


def test_untrusted_edit_obeys_existing_hard_rule():
    family = service()
    edit = family_edit(family.get())
    edit["caregivers"][0]["is_trusted"] = False
    scenario = family.scenario(family.update(FamilyUpdate.model_validate(edit)))
    assert "grandma" not in {person.person_id for person in matrix(scenario).people}
    assert not PlanValidator().validate(showcase_plan_a(), scenario).valid


def test_location_edit_changes_feasible_care_and_authoritative_travel():
    family = service()
    edit = family_edit(family.get())
    edit["caregivers"][0]["location_id"] = "family_home"
    updated = family.update(FamilyUpdate.model_validate(edit))
    scenario = family.scenario(updated)
    person = next(p for p in matrix(scenario).people if p.person_id == "grandma")
    assert person.allowed_care_location_ids == ["family_home"]
    assert scenario.caregivers[0].travel_minutes_from_family_home == 0
    assert ScenarioContract.from_scenario(scenario).to_scenario() == scenario


def test_preferences_are_soft_and_remote_snapshot_equivalent():
    family = service()
    profile = family.get()
    updated = family.update_preferences(
        PreferencesUpdate(
            expected_version=profile.version,
            prefer_trusted_caregivers=True,
            prefer_in_home_care=True,
            minimize_handoffs=False,
            protect_critical_meetings=True,
        )
    )
    scenario = family.scenario(updated)
    assert matrix(scenario) == matrix(get_demo_scenario())
    assert PlanValidator().validate(showcase_plan_a(), scenario).valid
    remote = ScenarioContract.from_scenario(scenario).to_scenario()
    kwargs = {
        "operation": PlannerOperation.INITIAL_PLANNING,
        "brief": initial_showcase_brief(scenario),
    }
    assert build_planner_invocation_input(scenario=scenario, **kwargs) == (
        build_planner_invocation_input(scenario=remote, **kwargs)
    )
    assert scenario.preferences.prefer_in_home_care


@pytest.mark.parametrize(
    "limit,unfamiliar,reasons",
    [
        (
            "30",
            True,
            {
                PlanApprovalReason.COST_ABOVE_AUTOMATIC_LIMIT,
                PlanApprovalReason.UNFAMILIAR_PAID_CAREGIVER,
            },
        ),
        ("100", True, {PlanApprovalReason.UNFAMILIAR_PAID_CAREGIVER}),
        ("100", False, set()),
        ("87.75", False, set()),
    ],
)
def test_spending_or_unfamiliar_provider_approval(limit, unfamiliar, reasons):
    plan, scenario = plan_b()
    # This independently feasible proposal uses parent care until 9, then paid care.
    plan.coverage_segments[0].window.end = at(9)
    plan.coverage_segments[1].window.start = at(9)
    family = service()
    policy = family.update_policy(
        policy_edit(
            family.get(),
            automatic_spend_limit=limit,
            unfamiliar=unfamiliar,
        )
    ).policy
    validation = PlanValidator().validate(plan, replace(scenario, policy=policy))
    assert validation.valid
    assert validation.deterministic_total_cost == Decimal("87.75")
    assert set(validation.validated_plan.approval_reasons) == reasons
    assert validation.requires_approval == bool(reasons)


def test_external_providers_disabled_in_analysis_search_matrix_and_validation():
    plan, scenario = plan_b()
    policy = scenario.policy.model_copy(update={"allow_external_backup_providers": False})
    scenario = replace(scenario, policy=policy)
    need = assess_known_option_recovery_need(scenario)
    assert need.known_options_insufficient and not need.research_needed
    assert not search_backup_care_candidates(scenario, need.requested_windows).eligible_candidates
    assert "harbor_nanny_coop" not in {p.person_id for p in matrix(scenario).people}
    result = PlanValidator().validate(plan, scenario)
    assert "hard_policy_violation" in {i.code for i in result.issues}
    with pytest.raises(ValueError, match="disabled"):
        add_researched_caregiver(scenario, scenario.backup_care_candidates[0])


def test_provider_transport_disabled_but_care_remains_eligible():
    plan, scenario = plan_b()
    caregivers = tuple(
        c.model_copy(update={"can_transport_child": True}) if c.external_provider else c
        for c in scenario.caregivers
    )
    scenario = replace(
        scenario,
        caregivers=caregivers,
        policy=scenario.policy.model_copy(update={"allow_provider_transport": False}),
    )
    assert PlanValidator().validate(plan, scenario).valid
    assert "harbor_nanny_coop" in {p.person_id for p in matrix(scenario).people}
    assert all(
        p.transporter_id != "harbor_nanny_coop" for p in matrix(scenario).transport_primitives
    )
    transport = (
        showcase_plan_a()
        .coverage_segments[1]
        .model_copy(update={"transporter_id": "harbor_nanny_coop"})
    )
    bad = plan.model_copy(update={"coverage_segments": [transport, *plan.coverage_segments]})
    result = PlanValidator().validate(bad, scenario)
    assert "transporter_unavailable" in {i.code for i in result.issues}


def test_recovery_snapshot_isolated_from_later_edits_and_repository_copies():
    family = FamilyService(InMemoryFamilyRepository(), get_legacy_demo_scenario)
    app = RecoveryApplicationService(
        InMemoryRecoveryCaseRepository(),
        DeterministicPlanningGateway(),
        scenario_factory=get_legacy_demo_scenario,
        family_service=family,
    )
    case = app.start_recovery(
        StartRecoveryCommand(
            disruption_type="CHILDCARE_UNAVAILABLE",
            occurred_at=at(7),
            caregiver_id="nanny",
            message="Unavailable",
        )
    )
    snapshot = app._scenario_for(case)
    assert case.status is RecoveryStatus.APPROVAL_REQUIRED
    updated = family.update_policy(
        policy_edit(
            family.get(),
            automatic_spend_limit="100",
            external=False,
        )
    )
    edit = family_edit(updated)
    edit["caregivers"][0]["can_transport_child"] = False
    edit["caregivers"][0]["availability"] = []
    family.update(FamilyUpdate.model_validate(edit))
    assert app._scenario_for(app.get_recovery(case.case_id)) == snapshot
    assert app.get_recovery(case.case_id).family_policy.automatic_spend_limit == Decimal("30")
    next_profile = family.get()
    next_profile.caregivers.clear()
    assert family.get().caregivers
    assert family.scenario(family.get()) != snapshot


def test_versioned_updates_do_not_overwrite_concurrent_sections():
    family = service()
    profile = family.get()
    family.update_policy(policy_edit(profile, automatic_spend_limit="42.50"))
    with pytest.raises(FamilyVersionConflict):
        family.update(FamilyUpdate.model_validate(family_edit(profile)))
    assert family.get().policy.automatic_spend_limit == Decimal("42.50")
