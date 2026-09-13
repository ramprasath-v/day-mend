"""Controlled offline verification: only model proposals are fixtures, never live inference."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app.agent.backup_care_researcher import BackupCareResearchResult, RankedBackupCareCandidate
from app.agent.config import AgentArchitecture, RecoveryAgentConfig
from app.agent.constraint_planner import PrimitiveSelection
from app.agent.multi_agent import run_multi_agent_replanning
from app.agent.recovery_agent import ToolInvocationRecorder
from app.agent.recovery_orchestrator import ConstraintCategory, PlanningBrief, PlanningMode
from app.agent.research_multi_agent import run_research_multi_agent_initial_planning
from app.application import RecoveryApplicationService
from app.application.family_service import FamilyService
from app.fixtures import get_demo_scenario
from app.main import create_app
from app.models import CareLocationType
from app.models.family import FamilyUpdate
from app.repositories import InMemoryRecoveryCaseRepository
from app.repositories.family_repository import InMemoryFamilyRepository
from app.services import PlanValidator, assess_known_option_recovery_need
from tests.milestone2_helpers import at, minute_window, showcase_plan_a
from tests.test_family import family_edit, matrix, policy_edit
from tests.test_location_transport import plan_b


class FixtureGateway:
    """Exercise all existing three-agent orchestration with deterministic proposal doubles."""

    def __init__(self):
        self.results = []
        self.replan_calls = 0

    def agents(self, scenario, replan=False):
        recorder = ToolInvocationRecorder(allowed_tool_names={"search_backup_care"})
        research_needed = assess_known_option_recovery_need(scenario).research_needed

        class Orchestrator:
            def __call__(self, prompt, *, structured_output_model=None):
                return SimpleNamespace(
                    structured_output=PlanningBrief(
                        planning_mode=PlanningMode.WORLD_STATE_REPLAN
                        if replan
                        else PlanningMode.INITIAL,
                        planning_required=True,
                        objective="Restore coverage.",
                        required_coverage_window=scenario.required_coverage,
                        relevant_constraint_categories=list(ConstraintCategory),
                        backup_research_needed=research_needed,
                    )
                )

        class Researcher:
            def __call__(self, prompt, *, structured_output_model=None):
                recorder.tool_names.append("search_backup_care")
                return SimpleNamespace(
                    structured_output=BackupCareResearchResult(
                        research_id="offline-research",
                        requested_windows=[minute_window(9, 0, 12)],
                        ranked_candidates=[
                            RankedBackupCareCandidate(
                                candidate_id=c.candidate_id,
                                rank=i,
                                fit_summary="Fixture ranking.",
                                tradeoffs=["Synthetic inventory; simulated reservation."],
                            )
                            for i, c in enumerate(scenario.backup_care_candidates, 1)
                        ],
                        recommended_candidate_id=scenario.backup_care_candidates[0].candidate_id,
                    )
                )

        class Planner:
            def __call__(self, prompt, *, structured_output_model=None):
                if replan and structured_output_model is PrimitiveSelection:
                    candidate = plan_b()[0]
                    selected_ids = [
                        candidate.coverage_segments[0].segment_id,
                        (
                            f"care:{candidate.coverage_segments[1].assigned_person_id}:"
                            f"{candidate.coverage_segments[1].window.start.isoformat()}"
                        ),
                        candidate.coverage_segments[-1].segment_id,
                    ]
                    return SimpleNamespace(
                        structured_output=PrimitiveSelection(selected_primitive_ids=selected_ids)
                    )
                return SimpleNamespace(
                    structured_output=(
                        (plan_b()[0] if replan or research_needed else showcase_plan_a())
                        if structured_output_model
                        else None
                    )
                )

        return dict(
            orchestrator=Orchestrator(),
            planner=Planner(),
            researcher=Researcher(),
            researcher_recorder=recorder,
        )

    def plan_initial(self, disruption, scenario):
        result, *_ = run_research_multi_agent_initial_planning(
            disruption=disruption,
            scenario=scenario,
            config=RecoveryAgentConfig(
                "offline-fixture", "us-east-1", AgentArchitecture.MULTI_RESEARCH
            ),
            **self.agents(scenario),
        )
        self.results.append(result)
        return result

    def replan(self, recovery_case, event, scenario):
        self.replan_calls += 1
        result, _ = run_multi_agent_replanning(
            recovery_case=recovery_case,
            event=event,
            scenario=scenario,
            config=RecoveryAgentConfig(
                "offline-fixture", "us-east-1", AgentArchitecture.MULTI_RESEARCH
            ),
            **self.agents(scenario, True),
        )
        self.results.append(result)
        return result


def harness():
    gateway = FixtureGateway()
    ids = iter(f"offline-verification-{i}" for i in range(1, 100))
    service = RecoveryApplicationService(
        InMemoryRecoveryCaseRepository(),
        gateway,
        id_factory=lambda: next(ids),
    )
    return service, gateway, TestClient(create_app(service))


def start(client):
    return client.post(
        "/recoveries",
        json={
            "disruption_type": "CHILDCARE_UNAVAILABLE",
            "occurred_at": at(7).isoformat(),
            "caregiver_id": "nanny",
            "message": "Nanny unavailable.",
        },
    )


def decline(client, case):
    return client.post(
        f"/recoveries/{case['recovery_case_id']}/events",
        json={
            "event_type": "CAREGIVER_DECLINED",
            "caregiver_id": "grandma",
            "occurred_at": at(8, 20).isoformat(),
            "relevant_window": minute_window(9, 0, 12, 15).model_dump(mode="json"),
            "message": "Grandma cannot help.",
            "expected_version": case["version"],
        },
    )


def test_default_and_spending_snapshot_lifecycles():
    service, gateway, client = harness()
    family = service.family_service
    default = family.get()
    created = start(client)
    assert created.status_code == 201
    plan_a = created.json()
    assert gateway.results[-1].total_attempts == 1
    assert gateway.results[-1].research_agent_invocation_count == 0
    # Edit after creation; the old case must retain its original policy.
    family.update_policy(policy_edit(default, automatic_spend_limit="100"))
    new_case = start(client).json()
    assert new_case["automatic_spend_limit"] == "100"
    pending = decline(client, plan_a)
    assert pending.status_code == 200, pending.text
    plan_b_case = pending.json()
    replan = gateway.results[-1]
    assert replan.success and replan.total_attempts == 1
    assert replan.research_agent_invocation_count == 1
    assert len(replan.preserved_segments) == 2
    assert plan_b_case["automatic_spend_limit"] == "30"
    reason = plan_b_case["pending_approval"]["reason"]
    assert "exceeds" in reason and "unfamiliar" in reason
    approved = client.post(
        f"/recoveries/{plan_a['recovery_case_id']}/approvals/"
        f"{plan_b_case['pending_approval']['approval_id']}",
        json={"decision": "APPROVE", "expected_version": plan_b_case["version"]},
    )
    assert approved.status_code == 200
    final = approved.json()
    assert final["status"] == "RESOLVED"
    assert len(final["execution_actions"]) == 2
    assert all(a["status"] == "SUCCEEDED" for a in final["execution_actions"])
    assert final["timestamps"]["completion_verified_at"]
    assert client.get(f"/recoveries/{final['recovery_case_id']}").json() == final
    assert final["family_profile_version"] == default.version
    high_limit = decline(client, new_case).json()
    assert high_limit["automatic_spend_limit"] == "100"
    assert "exceeds" not in high_limit["pending_approval"]["reason"]
    assert "unfamiliar" in high_limit["pending_approval"]["reason"]
    assert client.get(f"/recoveries/{final['recovery_case_id']}").json() == final
    family.update_policy(policy_edit(family.get(), automatic_spend_limit="30"))
    assert family.get().policy.automatic_spend_limit == default.policy.automatic_spend_limit
    print(
        "VERIFICATION "
        + json.dumps(
            {
                "case_id": final["recovery_case_id"],
                "profile_version": default.version,
                "plan_a_attempts": 1,
                "plan_b_attempts": replan.total_attempts,
                "provider": replan.researched_candidate.candidate_id,
                "cost": final["current_deterministic_cost"],
                "approval_reasons": reason,
                "actions": [a["status"] for a in final["execution_actions"]],
                "status": final["status"],
                "version": final["version"],
                "reload_identical": True,
                "spend_100_case": new_case["recovery_case_id"],
                "spend_100_reason": high_limit["pending_approval"]["reason"],
            }
        )
    )


def test_external_disabled_is_unresolved_without_research_or_provider_acceptance():
    service, gateway, client = harness()
    family = service.family_service
    family.update_policy(policy_edit(family.get(), external=False))
    created = start(client)
    assert created.status_code == 201
    case = created.json()
    results_before_decline = len(gateway.results)
    declined = decline(client, case)
    assert declined.status_code == 200
    assert gateway.replan_calls == 0
    assert len(gateway.results) == results_before_decline
    outcome = declined.json()
    decline_event = outcome["events"][-1]
    assert decline_event["details"]["outcome_code"] == "NO_RECOVERY_OPTION"
    assert decline_event["details"]["reason_code"] == "EXTERNAL_BACKUP_DISABLED"
    assert decline_event["details"]["message"] == (
        "No recovery option is available with your current settings."
    )
    assert decline_event["details"]["supporting_text"] == (
        "Known caregivers cannot cover the remaining gap, and external backup care is turned off."
    )
    assert decline_event["details"]["uncovered_windows"] == [
        {
            "start": "2026-08-27T08:45:00-07:00",
            "end": "2026-08-27T12:15:00-07:00",
        }
    ]
    assert len(decline_event["details"]["preserved_segment_ids"]) == 2
    assert outcome["status"] == "NO_RECOVERY_OPTION"
    assert outcome["pending_approval"] is None
    assert not outcome["execution_actions"]
    saved = client.get(f"/recoveries/{case['recovery_case_id']}").json()
    assert saved == outcome
    assert saved["status"] != "RESOLVED"
    assert not saved["execution_actions"]
    assert not any(
        s["assigned_person_id"] == "harbor_nanny_coop"
        for s in (saved["active_plan"] or {}).get("coverage_segments", [])
    )
    family.update_policy(policy_edit(family.get(), external=True))
    print(
        "EXTERNAL_DISABLED "
        + json.dumps(
            {
                "status_code": declined.status_code,
                "outcome": decline_event["details"]["outcome_code"],
                "persisted_status": saved["status"],
                "research_calls": 0,
                "planner_calls": gateway.replan_calls,
            }
        )
    )


def test_transport_disabled_researches_connected_external_replacement():
    service, gateway, client = harness()
    family = service.family_service
    original = family.get()
    edit = family_edit(original)
    edit["caregivers"][0]["can_transport_child"] = False
    updated = family.update(FamilyUpdate.model_validate(edit))
    scenario = family.scenario(updated)
    caregiver_id = updated.caregivers[0].caregiver_id
    feasible = matrix(scenario)
    assert caregiver_id in {person.person_id for person in feasible.people}
    assert caregiver_id not in {p.transporter_id for p in feasible.transport_primitives}
    assert "transporter_unavailable" in {
        issue.code for issue in PlanValidator().validate(showcase_plan_a(), scenario).issues
    }
    response = start(client)
    assert response.status_code == 201
    assert gateway.results[-1].success
    assert gateway.results[-1].total_attempts == 1
    assert gateway.results[-1].research_agent_invocation_count == 1
    body = response.json()
    assert body["active_plan"]["validation_state"] == "VALID"
    assert all(
        segment["segment_type"] == "CARE" for segment in body["active_plan"]["coverage_segments"]
    )
    assert any(
        segment["assigned_person_id"] == "harbor_nanny_coop"
        for segment in body["active_plan"]["coverage_segments"]
    )
    restore = family_edit(original)
    restore["expected_version"] = family.get().version
    family.update(FamilyUpdate.model_validate(restore))
    print(
        "TRANSPORT_DISABLED "
        + json.dumps(
            {
                "status_code": response.status_code,
                "attempts": gateway.results[-1].total_attempts,
                "care_eligible": True,
                "transport_primitive_present": False,
                "research_calls": gateway.results[-1].research_agent_invocation_count,
            }
        )
    )


def test_transport_disabled_and_external_disabled_stops_before_planner():
    service, gateway, client = harness()
    family = service.family_service
    profile = family.update_policy(policy_edit(family.get(), external=False))
    edit = family_edit(profile)
    edit["caregivers"][0]["can_transport_child"] = False
    family.update(FamilyUpdate.model_validate(edit))

    response = start(client)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "NO_RECOVERY_OPTION"
    assert body["events"][-1]["details"]["reason_code"] == "EXTERNAL_BACKUP_DISABLED"
    assert gateway.results == []


def test_untrusted_required_sitter_returns_clean_no_option_before_planner():
    service, gateway, client = harness()
    family = service.family_service
    edit = family_edit(family.get())
    edit["caregivers"][1]["is_trusted"] = False
    family.update(FamilyUpdate.model_validate(edit))

    response = start(client)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "NO_RECOVERY_OPTION"
    assert body["events"][-1]["details"]["reason_code"] == "NO_PLANABLE_BACKUP_CARE"
    assert body["events"][-1]["details"]["uncovered_windows"] == [
        minute_window(14, 0, 15).model_dump(mode="json")
    ]
    assert gateway.results == []


def test_disconnected_caregiver_location_is_not_treated_as_sufficient_time_coverage():
    service, gateway, client = harness()
    family = service.family_service
    edit = family_edit(family.get())
    edit["caregivers"][1]["location_id"] = "grandma_home"
    family.update(FamilyUpdate.model_validate(edit))

    response = start(client)

    assert response.status_code == 201
    assert response.json()["status"] == "NO_RECOVERY_OPTION"
    assert gateway.results == []


def _all_offsite_provider_service():
    def scenario_factory(care_date=None):
        scenario = get_demo_scenario(care_date)
        return replace(
            scenario,
            caregivers=(
                scenario.caregivers[0].model_copy(update={"can_transport_child": False}),
                *scenario.caregivers[1:],
            ),
            policy=scenario.policy.model_copy(update={"allow_provider_transport": False}),
            backup_care_candidates=tuple(
                candidate.model_copy(
                    update={
                        "care_location_type": CareLocationType.CAREGIVER_HOME,
                        "location_id": f"{candidate.candidate_id}_home",
                        "location_label": f"{candidate.display_name} home",
                        "travel_minutes_from_family_home": 15,
                        "can_transport_child": True,
                    }
                )
                for candidate in scenario.backup_care_candidates
            ),
        )

    gateway = FixtureGateway()
    family = FamilyService(InMemoryFamilyRepository(), scenario_factory)
    service = RecoveryApplicationService(
        InMemoryRecoveryCaseRepository(),
        gateway,
        scenario_factory=lambda: scenario_factory(),
        family_service=family,
        id_factory=lambda: "offsite-provider-case",
    )
    return gateway, TestClient(create_app(service))


def test_provider_transport_disabled_exhaustion_returns_no_option_without_planner():
    gateway, client = _all_offsite_provider_service()

    response = start(client)

    assert response.status_code == 201
    assert response.json()["status"] == "NO_RECOVERY_OPTION"
    assert response.json()["events"][-1]["details"]["reason_code"] == ("NO_PLANABLE_BACKUP_CARE")
    assert gateway.results == []


def test_replanning_research_exhaustion_preserves_plan_and_skips_planner():
    def scenario_factory(care_date=None):
        return replace(get_demo_scenario(care_date), backup_care_candidates=())

    gateway = FixtureGateway()
    family = FamilyService(InMemoryFamilyRepository(), scenario_factory)
    service = RecoveryApplicationService(
        InMemoryRecoveryCaseRepository(),
        gateway,
        scenario_factory=lambda: scenario_factory(),
        family_service=family,
        id_factory=iter(f"research-exhaustion-{index}" for index in range(10)).__next__,
    )
    client = TestClient(create_app(service))
    created = start(client)
    assert created.status_code == 201

    response = decline(client, created.json())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NO_RECOVERY_OPTION"
    assert body["events"][-1]["details"]["reason_code"] == "NO_PLANABLE_BACKUP_CARE"
    assert len(body["events"][-1]["details"]["preserved_segment_ids"]) == 2
    assert gateway.replan_calls == 0


def preview_app():
    """Local-only browser fixture app with real API/policy and model doubles."""
    service, _, _ = harness()
    app = create_app(service)
    app.mount(
        "/",
        StaticFiles(
            directory=Path(__file__).parents[2] / "frontend/dist/frontend/browser", html=True
        ),
        name="preview",
    )
    return app
