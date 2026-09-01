"""Simulated execution and deterministic completion-verification tests."""

import pytest

from app.models import (
    PlanAssumption,
    PlanAssumptionStatus,
    RecoveryEventType,
    RecoveryStatus,
)
from app.repositories import InMemoryRecoveryCaseRepository
from app.services import (
    ApprovalService,
    CompletionVerifier,
    RecoveryExecutionService,
    SimulatedExecutionAdapter,
    WorkflowInvariantError,
)
from tests.milestone2_helpers import at, window
from tests.milestone3_helpers import milestone3_case, twenty_dollar_case


def approved_case(*, adapter=None):
    recovery_case, scenario, validation = milestone3_case()
    repository = InMemoryRecoveryCaseRepository()
    approval = ApprovalService(repository, id_factory=lambda: "approval-plan-b")
    gated = approval.apply_autonomy_gate(
        recovery_case,
        validation,
        scenario.policy,
        now=at(9, 15),
    )
    approval.approve(gated.recovery_case.case_id, "approval-plan-b", now=at(9, 20))
    execution = RecoveryExecutionService(repository, adapter=adapter)
    return repository, execution, scenario


def test_execution_is_blocked_before_mandatory_approval() -> None:
    recovery_case, scenario, validation = milestone3_case()
    repository = InMemoryRecoveryCaseRepository()
    gated = ApprovalService(repository, id_factory=lambda: "approval-plan-b").apply_autonomy_gate(
        recovery_case,
        validation,
        scenario.policy,
        now=at(9, 15),
    )

    with pytest.raises(WorkflowInvariantError, match="pending approval"):
        RecoveryExecutionService(repository).execute(
            gated.recovery_case.case_id,
            scenario.policy,
            now=at(9, 25),
        )


def test_execution_runs_once_after_approval_and_records_actions() -> None:
    repository, service, scenario = approved_case()

    first = service.execute("case-milestone-3", scenario.policy, now=at(9, 25))
    duplicate = service.execute("case-milestone-3", scenario.policy, now=at(9, 26))

    assert first.succeeded is True
    assert len(first.actions) == 4
    assert duplicate.idempotent is True
    assert duplicate.recovery_case.version == first.recovery_case.version
    assert len(duplicate.recovery_case.execution_history) == 4
    assert (
        sum(
            event.event_type is RecoveryEventType.EXECUTION_STARTED
            for event in duplicate.recovery_case.events
        )
        == 1
    )


def test_below_limit_plan_executes_without_human_approval() -> None:
    recovery_case, scenario, validation = twenty_dollar_case()
    repository = InMemoryRecoveryCaseRepository()
    gated = ApprovalService(repository).apply_autonomy_gate(
        recovery_case,
        validation,
        scenario.policy,
        now=at(9, 15),
    )

    result = RecoveryExecutionService(repository).execute(
        gated.recovery_case.case_id,
        scenario.policy,
        now=at(9, 20),
    )

    assert result.succeeded is True
    assert gated.recovery_case.approval_history == []


def test_execution_failure_prevents_resolution() -> None:
    repository, service, scenario = approved_case(
        adapter=SimulatedExecutionAdapter(fail_targets={"backup_sitter"})
    )
    execution = service.execute("case-milestone-3", scenario.policy, now=at(9, 25))

    verification = CompletionVerifier(repository).verify_and_resolve(
        "case-milestone-3",
        scenario,
        now=at(9, 30),
    )

    assert execution.succeeded is False
    assert execution.recovery_case.status is RecoveryStatus.FAILED
    assert verification.verified is False
    assert verification.recovery_case.status is not RecoveryStatus.RESOLVED


def test_successful_execution_is_resolved_only_after_deterministic_verification() -> None:
    repository, service, scenario = approved_case()
    execution = service.execute("case-milestone-3", scenario.policy, now=at(9, 25))

    assert execution.recovery_case.status is RecoveryStatus.EXECUTING
    verification = CompletionVerifier(repository).verify_and_resolve(
        "case-milestone-3",
        scenario,
        now=at(9, 30),
    )
    reloaded = repository.get("case-milestone-3")

    assert verification.verified is True
    assert reloaded.status is RecoveryStatus.RESOLVED
    assert reloaded.completion_verified_at == at(9, 30)
    assert reloaded.case_id == "case-milestone-3"
    assert reloaded.active_recovery_plan is not None
    assert reloaded.active_recovery_plan.plan_id == "plan-b-approval"
    assert reloaded.previous_plans[0].plan_id == "plan-a"
    assert any(event.event_type is RecoveryEventType.CASE_RESOLVED for event in reloaded.events)


def test_coverage_gap_never_resolves() -> None:
    repository, service, scenario = approved_case()
    executed = service.execute("case-milestone-3", scenario.policy, now=at(9, 25))
    plan = executed.recovery_case.active_recovery_plan
    assert plan is not None
    broken = plan.model_copy(update={"coverage_segments": plan.coverage_segments[:-1]})
    mutated = executed.recovery_case.model_copy(update={"active_recovery_plan": broken})
    repository.save(mutated, expected_version=executed.recovery_case.version)

    result = CompletionVerifier(repository).verify_and_resolve(
        "case-milestone-3",
        scenario,
        now=at(9, 30),
    )

    assert result.verified is False
    assert any("does not end" in error for error in result.errors)


def test_pending_approval_never_resolves() -> None:
    recovery_case, scenario, validation = milestone3_case()
    repository = InMemoryRecoveryCaseRepository()
    gated = ApprovalService(repository, id_factory=lambda: "approval-plan-b").apply_autonomy_gate(
        recovery_case,
        validation,
        scenario.policy,
        now=at(9, 15),
    )

    result = CompletionVerifier(repository).verify_and_resolve(
        gated.recovery_case.case_id,
        scenario,
        now=at(9, 20),
    )

    assert result.verified is False
    assert any("pending" in error.lower() for error in result.errors)


def test_active_plan_reliance_on_invalidated_dependency_never_resolves() -> None:
    repository, service, scenario = approved_case()
    executed = service.execute("case-milestone-3", scenario.policy, now=at(9, 25))
    invalidated = PlanAssumption(
        assumption_id="invalidated-current-employer",
        assumption_type="CAREGIVER_AVAILABLE",
        subject_id="employer_backup_care",
        relevant_window=window(9, 13),
        value=False,
        status=PlanAssumptionStatus.INVALIDATED,
        invalidated_at=at(9, 26),
        invalidation_reason="No longer available.",
        triggering_event_id="later-event",
    )
    mutated = executed.recovery_case.model_copy(
        update={"assumptions": [*executed.recovery_case.assumptions, invalidated]}
    )
    repository.save(mutated, expected_version=executed.recovery_case.version)

    result = CompletionVerifier(repository).verify_and_resolve(
        "case-milestone-3",
        scenario,
        now=at(9, 30),
    )

    assert result.verified is False
    assert any("invalidated assumption" in error for error in result.errors)
