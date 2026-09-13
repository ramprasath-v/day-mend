"""Controlled offline verification: only model proposals are fixtures, never live inference."""

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from app.agent.backup_care_researcher import BackupCareResearchResult, RankedBackupCareCandidate
from app.agent.config import AgentArchitecture, RecoveryAgentConfig
from app.agent.multi_agent import run_multi_agent_replanning
from app.agent.recovery_agent import ToolInvocationRecorder
from app.agent.recovery_orchestrator import ConstraintCategory, PlanningBrief, PlanningMode
from app.agent.research_multi_agent import run_research_multi_agent_initial_planning
from app.application import RecoveryApplicationService
from app.main import create_app
from app.models.family import FamilyUpdate
from app.repositories import InMemoryRecoveryCaseRepository
from app.services import PlanValidator
from tests.milestone2_helpers import at, minute_window, showcase_plan_a
from tests.test_family import family_edit, matrix, policy_edit
from tests.test_location_transport import plan_b


class FixtureGateway:
    """Exercise all existing three-agent orchestration with deterministic proposal doubles."""

    def __init__(self):
        self.results = []

    def agents(self, scenario, replan=False):
        recorder = ToolInvocationRecorder(allowed_tool_names={"search_backup_care"})

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
                return SimpleNamespace(
                    structured_output=(
                        (plan_b()[0] if replan else showcase_plan_a())
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
    declined = decline(client, case)
    assert declined.status_code == 409
    result = gateway.results[-1]
    assert not result.success
    assert result.research_agent_invocation_count == 0
    saved = client.get(f"/recoveries/{case['recovery_case_id']}").json()
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
                "error": declined.json(),
                "persisted_status": saved["status"],
                "research_calls": result.research_agent_invocation_count,
            }
        )
    )


def test_transport_disabled_rejects_invalid_proposal_without_removing_care():
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
    assert response.status_code == 409
    assert not gateway.results[-1].success
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
            }
        )
    )


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
