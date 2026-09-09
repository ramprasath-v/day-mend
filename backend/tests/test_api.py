"""Offline HTTP coverage for the complete DayMend recovery lifecycle."""

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agent.recovery_agent import InitialPlanningResult, PlanningAttempt
from app.agent.replanning import ReplanningResult, process_external_event
from app.api.dependencies import allowed_origins, build_recovery_repository
from app.application import RecoveryApplicationService
from app.fixtures import DemoScenario, get_legacy_demo_scenario
from app.main import create_app
from app.models import RecoveryCase, RecoveryEvent, RecoveryStatus
from app.repositories import InMemoryRecoveryCaseRepository
from app.services import ApprovalService, PlanValidator, WorkflowInvariantError
from tests.milestone2_helpers import at, validated_plan_a
from tests.milestone3_helpers import plan_b_proposal


class _AgentResult:
    def __init__(self, structured_output=None) -> None:
        self.structured_output = structured_output


class _PlanBAgent:
    def __call__(self, _prompt: str, *, structured_output_model=None) -> _AgentResult:
        if structured_output_model is None:
            return _AgentResult()
        return _AgentResult(
            plan_b_proposal().model_copy(update={"plan_id": "repaired_recovery_plan"})
        )


class DeterministicPlanningGateway:
    """Replace only the model boundary while retaining all deterministic workflow code."""

    def plan_initial(self, _disruption: str, scenario: DemoScenario) -> InitialPlanningResult:
        plan = validated_plan_a().model_copy(update={"plan_id": "repaired_recovery_plan"})
        validation = PlanValidator().validate(plan, scenario)
        return InitialPlanningResult(
            success=True,
            total_attempts=1,
            model_id="offline-deterministic-boundary",
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

    def replan(
        self,
        recovery_case: RecoveryCase,
        event: RecoveryEvent,
        scenario: DemoScenario,
    ) -> ReplanningResult:
        from app.agent.recovery_agent import ToolInvocationRecorder

        return process_external_event(
            recovery_case=recovery_case,
            event=event,
            scenario=scenario,
            agent=_PlanBAgent(),
            recorder=ToolInvocationRecorder(),
        )


@pytest.fixture
def repository() -> InMemoryRecoveryCaseRepository:
    return InMemoryRecoveryCaseRepository()


@pytest.fixture
def client(repository: InMemoryRecoveryCaseRepository) -> TestClient:
    ids: Iterator[str] = iter(["case-api-offline", "event-api-offline"])
    times: Iterator[datetime] = iter(
        [
            at(9, 10),
            at(9, 11),
            at(9, 15),
            at(9, 16),
            at(9, 17),
            at(9, 18),
            at(9, 19),
        ]
    )
    service = RecoveryApplicationService(
        repository,
        DeterministicPlanningGateway(),
        clock=lambda: next(times),
        id_factory=lambda: next(ids),
        scenario_factory=get_legacy_demo_scenario,
    )
    return TestClient(create_app(service))


def _create(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/recoveries",
        json={
            "disruption_type": "CHILDCARE_UNAVAILABLE",
            "occurred_at": at(7, 2).isoformat(),
            "caregiver_id": "nanny",
            "message": "I'm sick and can't come today.",
        },
    )
    assert response.status_code == 201
    return response.json()


def _decline(client: TestClient, case_id: str, **extra: Any) -> Any:
    body = {
        "event_type": "CAREGIVER_DECLINED",
        "caregiver_id": "grandma",
        "occurred_at": at(9, 5).isoformat(),
        "relevant_window": {"start": at(10).isoformat(), "end": at(13).isoformat()},
        "message": "Sorry, I can't help today.",
        **extra,
    }
    return client.post(f"/recoveries/{case_id}/events", json=body)


def test_health_is_lightweight(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "daymend-api"}


def test_create_returns_201_id_and_persists(
    client: TestClient,
    repository: InMemoryRecoveryCaseRepository,
) -> None:
    body = _create(client)
    assert body["recovery_case_id"] == "case-api-offline"
    assert body["status"] == "WAITING_FOR_RESPONSE"
    assert body["version"] == 1
    assert body["automatic_spend_limit"] == "30"
    assert body["currency"] == "USD"
    assert repository.get("case-api-offline").case_id == body["recovery_case_id"]


def test_create_rejects_malformed_request(client: TestClient) -> None:
    response = client.post("/recoveries", json={"disruption_type": "CHILDCARE_UNAVAILABLE"})
    assert response.status_code == 422


def test_event_rejects_malformed_window(client: TestClient) -> None:
    created = _create(client)
    response = _decline(
        client,
        created["recovery_case_id"],
        relevant_window={"start": at(13).isoformat(), "end": at(10).isoformat()},
    )
    assert response.status_code == 422


def test_get_existing_and_missing_case(client: TestClient) -> None:
    created = _create(client)
    found = client.get(f"/recoveries/{created['recovery_case_id']}")
    missing = client.get("/recoveries/missing")
    assert found.status_code == 200
    assert found.json()["recovery_case_id"] == created["recovery_case_id"]
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RECOVERY_CASE_NOT_FOUND"


def test_caregiver_decline_replans_same_persisted_case(client: TestClient) -> None:
    created = _create(client)
    response = _decline(client, created["recovery_case_id"])
    assert response.status_code == 200
    body = response.json()
    assert body["recovery_case_id"] == created["recovery_case_id"]
    assert body["status"] == "APPROVAL_REQUIRED"
    assert body["active_plan"]["plan_id"] == "case-api-offline:plan:2"
    assert body["plan_history"][0]["plan_id"] == "case-api-offline:plan:1"
    assert body["previous_plans"][0]["plan_id"] == "case-api-offline:plan:1"
    assert len(body["previous_plans"][0]["coverage_segments"]) == 5
    assert body["latest_trigger"] == "event:event-api-offline"
    assert len(body["invalidated_assumptions"]) == 1
    assert body["pending_approval"]["status"] == "PENDING"
    decline = next(event for event in body["events"] if event["event_type"] == "CAREGIVER_DECLINED")
    assert decline["occurred_at"] == at(9, 5).isoformat()
    assert datetime.fromisoformat(body["timestamps"]["updated_at"]) >= datetime.fromisoformat(
        body["timestamps"]["created_at"]
    )
    persisted = client.get(f"/recoveries/{created['recovery_case_id']}").json()
    assert persisted == body


def test_application_owns_accepted_plan_ids_and_stale_approval_identity(
    client: TestClient,
    repository: InMemoryRecoveryCaseRepository,
) -> None:
    created = _create(client)
    case_id = created["recovery_case_id"]
    plan_a_id = created["active_plan"]["plan_id"]
    pending = _decline(client, case_id).json()
    plan_b_id = pending["active_plan"]["plan_id"]

    assert plan_a_id == f"{case_id}:plan:1"
    assert plan_b_id == f"{case_id}:plan:2"
    assert plan_a_id != plan_b_id
    assert pending["previous_plans"][0]["plan_id"] == plan_a_id
    assert pending["pending_approval"]["plan_id"] == plan_b_id

    loaded = repository.get(case_id)
    assert loaded.previous_plans[0].plan_id == plan_a_id
    assert len(loaded.previous_plans) == 1
    assert loaded.active_recovery_plan is not None
    assert loaded.active_recovery_plan.plan_id == plan_b_id
    stale = loaded.model_copy(update={"active_recovery_plan": loaded.previous_plans[0]})
    repository.save(stale, expected_version=loaded.version)

    with pytest.raises(
        WorkflowInvariantError,
        match="does not authorize the current active plan",
    ):
        ApprovalService(repository).approve(
            case_id,
            pending["pending_approval"]["approval_id"],
            now=at(9, 20),
        )


def test_unrelated_event_returns_safe_conflict(client: TestClient) -> None:
    created = _create(client)
    response = _decline(client, created["recovery_case_id"], caregiver_id="unknown")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EVENT_NOT_APPLICABLE"


def test_stale_event_version_returns_conflict(client: TestClient) -> None:
    created = _create(client)
    response = _decline(client, created["recovery_case_id"], expected_version=99)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PERSISTENCE_CONFLICT"


def test_approve_executes_and_resolves_same_case(client: TestClient) -> None:
    created = _create(client)
    pending = _decline(client, created["recovery_case_id"]).json()
    approval_id = pending["pending_approval"]["approval_id"]
    response = client.post(
        f"/recoveries/{created['recovery_case_id']}/approvals/{approval_id}",
        json={"decision": "APPROVE", "expected_version": pending["version"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["recovery_case_id"] == created["recovery_case_id"]
    assert body["status"] == "RESOLVED"
    assert body["pending_approval"] is None
    assert body["approval_history"][-1]["status"] == "APPROVED"
    assert len(body["execution_actions"]) == 4
    assert {action["status"] for action in body["execution_actions"]} == {"SUCCEEDED"}
    assert body["timestamps"]["completion_verified_at"] is not None


def test_duplicate_approve_is_idempotent(client: TestClient) -> None:
    created = _create(client)
    pending = _decline(client, created["recovery_case_id"]).json()
    approval_id = pending["pending_approval"]["approval_id"]
    path = f"/recoveries/{created['recovery_case_id']}/approvals/{approval_id}"
    first = client.post(path, json={"decision": "APPROVE"})
    second = client.post(path, json={"decision": "APPROVE"})
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()


def test_stale_and_unknown_approval_are_safe_errors(client: TestClient) -> None:
    created = _create(client)
    pending = _decline(client, created["recovery_case_id"]).json()
    approval_id = pending["pending_approval"]["approval_id"]
    stale = client.post(
        f"/recoveries/{created['recovery_case_id']}/approvals/{approval_id}",
        json={"decision": "APPROVE", "expected_version": 1},
    )
    unknown = client.post(
        f"/recoveries/{created['recovery_case_id']}/approvals/unknown",
        json={"decision": "APPROVE"},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "PERSISTENCE_CONFLICT"
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "APPROVAL_NOT_FOUND"


def test_reject_records_decision_without_execution(client: TestClient) -> None:
    created = _create(client)
    pending = _decline(client, created["recovery_case_id"]).json()
    approval_id = pending["pending_approval"]["approval_id"]
    response = client.post(
        f"/recoveries/{created['recovery_case_id']}/approvals/{approval_id}",
        json={"decision": "REJECT", "reason": "Too expensive"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REPLANNING"
    assert body["approval_history"][-1]["status"] == "REJECTED"
    assert body["execution_actions"] == []


def test_response_excludes_internal_context_and_sensitive_fields(client: TestClient) -> None:
    body = _create(client)
    encoded = str(body).lower()
    assert "context_state" not in body
    assert "chain_of_thought" not in encoded
    assert "aws_secret" not in encoded
    assert "model_id" not in encoded


def test_unexpected_failure_returns_safe_500() -> None:
    class FailingGateway(DeterministicPlanningGateway):
        def plan_initial(self, _disruption: str, _scenario: DemoScenario) -> InitialPlanningResult:
            raise RuntimeError("AWS_SECRET_ACCESS_KEY=do-not-expose")

    service = RecoveryApplicationService(
        InMemoryRecoveryCaseRepository(),
        FailingGateway(),
    )
    safe_client = TestClient(create_app(service), raise_server_exceptions=False)
    response = safe_client.post(
        "/recoveries",
        json={
            "disruption_type": "CHILDCARE_UNAVAILABLE",
            "occurred_at": at(7, 2).isoformat(),
            "caregiver_id": "nanny",
            "message": "Unavailable today.",
        },
    )
    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "DayMend could not complete the request.",
        }
    }
    assert "AWS_SECRET" not in response.text


def test_cors_allows_configured_localhost(client: TestClient) -> None:
    response = client.options(
        "/recoveries",
        headers={
            "Origin": "http://localhost:4200",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:4200"


def test_openapi_exposes_required_routes(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/health" in paths
    assert "/recoveries" in paths
    assert "/recoveries/{recovery_case_id}" in paths
    assert "/recoveries/{recovery_case_id}/events" in paths
    assert "/recoveries/{recovery_case_id}/approvals/{approval_id}" in paths


def test_repository_and_cors_environment_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAYMEND_RECOVERY_REPOSITORY", "memory")
    monkeypatch.setenv(
        "DAYMEND_ALLOWED_ORIGINS",
        "http://localhost:4200,http://127.0.0.1:4200",
    )
    assert isinstance(build_recovery_repository(), InMemoryRecoveryCaseRepository)
    assert allowed_origins() == ["http://localhost:4200", "http://127.0.0.1:4200"]


def test_end_to_end_offline_http_lifecycle_reaches_resolved(client: TestClient) -> None:
    created = _create(client)
    case_id = created["recovery_case_id"]
    assert client.get(f"/recoveries/{case_id}").json()["status"] == "WAITING_FOR_RESPONSE"
    pending = _decline(client, case_id).json()
    assert pending["status"] == "APPROVAL_REQUIRED"
    approval_id = pending["pending_approval"]["approval_id"]
    approved = client.post(
        f"/recoveries/{case_id}/approvals/{approval_id}",
        json={"decision": "APPROVE"},
    )
    assert approved.status_code == 200
    final = client.get(f"/recoveries/{case_id}").json()
    assert final["recovery_case_id"] == case_id
    assert final["status"] == RecoveryStatus.RESOLVED
    assert final["version"] == approved.json()["version"]
