"""Deterministic autonomy boundary and approval decision tests."""

from decimal import Decimal

import pytest

from app.models import ApprovalStatus, RecoveryEventType, RecoveryStatus
from app.repositories import InMemoryRecoveryCaseRepository
from app.services import ApprovalService, PlanValidator, WorkflowInvariantError
from tests.milestone2_helpers import at, validated_plan_a
from tests.milestone3_helpers import milestone3_case, twenty_dollar_case


def gate_expensive_case():
    recovery_case, scenario, validation = milestone3_case()
    repository = InMemoryRecoveryCaseRepository()
    service = ApprovalService(repository, id_factory=lambda: "approval-plan-b")
    result = service.apply_autonomy_gate(
        recovery_case,
        validation,
        scenario.policy,
        now=at(9, 15),
    )
    return result, repository, scenario


def test_valid_92_plan_crosses_30_limit_without_becoming_invalid() -> None:
    result, _, _ = gate_expensive_case()

    assert result.approval_required is True
    assert result.recovery_case.status is RecoveryStatus.APPROVAL_REQUIRED
    assert result.approval_request is not None
    assert result.approval_request.amount == Decimal("92.00")
    assert result.approval_request.plan_id == "plan-b-approval"
    assert result.approval_request.status is ApprovalStatus.PENDING
    assert result.recovery_case.active_recovery_plan is not None
    assert result.recovery_case.active_recovery_plan.validation_state.value == "VALID"
    assert result.recovery_case.events[-1].event_type is RecoveryEventType.APPROVAL_REQUESTED


def test_valid_20_plan_under_30_limit_continues_without_approval() -> None:
    recovery_case, scenario, validation = twenty_dollar_case()
    repository = InMemoryRecoveryCaseRepository()

    result = ApprovalService(repository).apply_autonomy_gate(
        recovery_case,
        validation,
        scenario.policy,
        now=at(9, 15),
    )

    assert result.approval_required is False
    assert result.approval_request is None
    assert result.recovery_case.status is RecoveryStatus.EXECUTING
    assert result.recovery_case.pending_approval is None


def test_invalid_plan_cannot_reach_approval_or_execution() -> None:
    recovery_case, scenario, _ = milestone3_case()
    invalid_validation = PlanValidator().validate(validated_plan_a(), scenario)

    with pytest.raises(WorkflowInvariantError, match="deterministically valid"):
        ApprovalService(InMemoryRecoveryCaseRepository()).apply_autonomy_gate(
            recovery_case,
            invalid_validation,
            scenario.policy,
            now=at(9, 15),
        )


def test_approve_reloads_and_resumes_same_case_id_idempotently() -> None:
    gated, repository, _ = gate_expensive_case()
    service_after_restart = ApprovalService(repository)

    approved = service_after_restart.approve(
        gated.recovery_case.case_id,
        "approval-plan-b",
        now=at(9, 20),
    )
    duplicate = service_after_restart.approve(
        gated.recovery_case.case_id,
        "approval-plan-b",
        now=at(9, 21),
    )

    assert approved.recovery_case.case_id == gated.recovery_case.case_id
    assert approved.approval.status is ApprovalStatus.APPROVED
    assert approved.recovery_case.status is RecoveryStatus.EXECUTING
    assert approved.recovery_case.pending_approval is None
    assert duplicate.idempotent is True
    assert duplicate.recovery_case.version == approved.recovery_case.version
    assert (
        sum(
            event.event_type is RecoveryEventType.APPROVAL_APPROVED
            for event in duplicate.recovery_case.events
        )
        == 1
    )


def test_reject_is_idempotent_records_new_fact_and_enters_replanning() -> None:
    gated, repository, _ = gate_expensive_case()
    service = ApprovalService(repository)

    rejected = service.reject(
        gated.recovery_case.case_id,
        "approval-plan-b",
        now=at(9, 20),
        reason="Use a lower-cost alternative.",
    )
    duplicate = service.reject(
        gated.recovery_case.case_id,
        "approval-plan-b",
        now=at(9, 21),
    )

    assert rejected.approval.status is ApprovalStatus.REJECTED
    assert rejected.recovery_case.status is RecoveryStatus.REPLANNING
    assert rejected.recovery_case.execution_history == []
    assert rejected.recovery_case.events[-1].event_type is RecoveryEventType.APPROVAL_REJECTED
    assert (
        rejected.recovery_case.latest_replan_trigger_event_id
        == rejected.recovery_case.events[-1].event_id
    )
    assert duplicate.idempotent is True


def test_finalized_approval_cannot_be_reversed() -> None:
    gated, repository, _ = gate_expensive_case()
    service = ApprovalService(repository)
    service.approve(gated.recovery_case.case_id, "approval-plan-b", now=at(9, 20))

    with pytest.raises(WorkflowInvariantError, match="cannot change finalized"):
        service.reject(gated.recovery_case.case_id, "approval-plan-b", now=at(9, 21))

    gated, repository, _ = gate_expensive_case()
    service = ApprovalService(repository)
    service.reject(gated.recovery_case.case_id, "approval-plan-b", now=at(9, 20))

    with pytest.raises(WorkflowInvariantError, match="cannot change finalized"):
        service.approve(gated.recovery_case.case_id, "approval-plan-b", now=at(9, 21))


def test_stale_plan_approval_cannot_authorize_current_plan() -> None:
    gated, repository, _ = gate_expensive_case()
    loaded = repository.get(gated.recovery_case.case_id)
    stale = loaded.model_copy(update={"active_recovery_plan": loaded.previous_plans[0]})
    repository.save(stale, expected_version=loaded.version)

    with pytest.raises(WorkflowInvariantError, match="does not authorize the current active plan"):
        ApprovalService(repository).approve(
            gated.recovery_case.case_id,
            "approval-plan-b",
            now=at(9, 20),
        )
