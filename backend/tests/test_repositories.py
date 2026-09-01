"""RecoveryCase persistence and serialization tests."""

from decimal import Decimal

import pytest

from app.models import ApprovalStatus, PlanAssumptionStatus, RecoveryCase, RecoveryStatus
from app.repositories import (
    DynamoDBRecoveryCaseRepository,
    InMemoryRecoveryCaseRepository,
    RecoveryCaseVersionConflict,
)
from app.services import ApprovalService
from tests.milestone2_helpers import at
from tests.milestone3_helpers import milestone3_case


class FakeTable:
    def __init__(self) -> None:
        self.items = {}

    def get_item(self, *, Key, ConsistentRead):
        del ConsistentRead
        item = self.items.get(Key["recovery_case_id"])
        return {} if item is None else {"Item": item.copy()}

    def put_item(self, **kwargs):
        item = kwargs["Item"]
        self.items[item["recovery_case_id"]] = item.copy()


class FakeDynamoResource:
    def __init__(self) -> None:
        self.table = FakeTable()

    def Table(self, table_name):
        del table_name
        return self.table


def test_recovery_case_json_round_trip_preserves_domain_types_and_history() -> None:
    recovery_case, _, _ = milestone3_case()

    restored = RecoveryCase.model_validate_json(recovery_case.model_dump_json())

    assert restored == recovery_case
    assert restored.status is RecoveryStatus.EXECUTING
    assert restored.active_recovery_plan is not None
    assert restored.active_recovery_plan.estimated_cost == Decimal("92.00")
    assert restored.updated_at.tzinfo is not None
    assert restored.previous_plans[0].plan_id == "plan-a"
    assert restored.events[0].event_id == "event-grandma-declined"
    assert any(
        assumption.status is PlanAssumptionStatus.INVALIDATED for assumption in restored.assumptions
    )


def test_in_memory_repository_returns_deep_process_boundary_copies() -> None:
    recovery_case, _, _ = milestone3_case()
    repository = InMemoryRecoveryCaseRepository()

    saved = repository.save(recovery_case)
    loaded = repository.get(recovery_case.case_id)
    loaded.context_state["local_mutation"] = True

    assert saved.version == 1
    assert repository.get(recovery_case.case_id).context_state.get("local_mutation") is None


def test_in_memory_repository_enforces_optimistic_versions() -> None:
    recovery_case, _, _ = milestone3_case()
    repository = InMemoryRecoveryCaseRepository()
    saved = repository.save(recovery_case)

    with pytest.raises(RecoveryCaseVersionConflict):
        repository.save(saved, expected_version=0)


def test_dynamodb_repository_round_trips_single_json_item() -> None:
    recovery_case, _, _ = milestone3_case()
    resource = FakeDynamoResource()
    repository = DynamoDBRecoveryCaseRepository(
        table_name="test-table",
        dynamodb_resource=resource,
    )

    saved = repository.save(recovery_case)
    loaded = repository.get(recovery_case.case_id)
    item = resource.table.items[recovery_case.case_id]

    assert loaded == saved
    assert set(item) == {"recovery_case_id", "version", "status", "updated_at", "payload"}
    assert item["status"] == "EXECUTING"


def test_pending_approval_and_all_histories_survive_reload() -> None:
    recovery_case, scenario, validation = milestone3_case()
    repository = InMemoryRecoveryCaseRepository()
    service = ApprovalService(repository, id_factory=lambda: "approval-1")

    gated = service.apply_autonomy_gate(
        recovery_case,
        validation,
        scenario.policy,
        now=at(9, 15),
    )
    loaded = repository.get(recovery_case.case_id)

    assert gated.approval_required is True
    assert loaded.status is RecoveryStatus.APPROVAL_REQUIRED
    assert loaded.pending_approval is not None
    assert loaded.pending_approval.status is ApprovalStatus.PENDING
    assert loaded.approval_history == [loaded.pending_approval]
    assert loaded.previous_plans[0].plan_id == "plan-a"
    assert loaded.events[0].event_id == "event-grandma-declined"
