"""Focused safe progress-contract and replay tests."""

import pytest

from app.observability import log_event
from app.progress import (
    ProgressActorType,
    ProgressStatus,
    RecoveryProgressBuffer,
    progress_buffer,
    progress_scope,
)


def test_progress_buffer_orders_events_and_replays_without_duplicates() -> None:
    buffer = RecoveryProgressBuffer()
    progress_id = "progress-test-0001"
    buffer.start(progress_id)
    first = buffer.append(
        progress_id,
        recovery_case_id="case-progress-0001",
        event_type="RECOVERY_STARTED",
        actor_type=ProgressActorType.SYSTEM,
        actor_name="daymend",
        stage="RECOVERY",
        status=ProgressStatus.COMPLETED,
        summary="Recovery case started",
    )
    second = buffer.append(
        progress_id,
        recovery_case_id="case-progress-0001",
        event_type="ORCHESTRATOR_STARTED",
        actor_type=ProgressActorType.AGENT,
        actor_name="recovery_orchestrator",
        stage="PLAN_A",
        status=ProgressStatus.ACTIVE,
        summary="Coordinating the recovery",
    )

    assert [event.sequence for event in buffer.snapshot(progress_id)] == [1, 2]
    assert buffer.snapshot("case-progress-0001") == [first, second]
    assert buffer.after(progress_id, first.sequence) == [second]


def test_log_translation_exposes_only_reviewed_structured_details() -> None:
    progress_buffer.clear()
    progress_id = "progress-test-0002"
    with progress_scope(progress_id, recovery_case_id="case-progress-0002"):
        with pytest.raises(ValueError, match="unsafe observability fields"):
            log_event(
                "planner_validation_failed",
                recovery_case_id="case-progress-0002",
                prompt="must never be retained",
                chain_of_thought="must never be retained",
            )
        log_event(
            "planner_validation_failed",
            recovery_case_id="case-progress-0002",
            attempt_number=2,
            issue_count=1,
            issue_codes=["COVERAGE_GAP"],
        )

    event = progress_buffer.snapshot(progress_id)[0]
    assert event.event_type == "VALIDATION_FAILED"
    assert event.details == {
        "attempt_number": 2,
        "issue_codes": ["COVERAGE_GAP"],
        "issue_count": 1,
    }
    assert "prompt" not in event.model_dump_json()
    assert "chain_of_thought" not in event.model_dump_json()


@pytest.mark.parametrize(
    "source_event",
    [
        "orchestrator_invocation_started",
        "planner_invocation_started",
        "backup_research_started",
        "no_recovery_option",
        "validation_started",
        "approval_requested",
        "execution_started",
        "recovery_resolved",
    ],
)
def test_each_major_control_point_has_a_safe_presentation(source_event: str) -> None:
    progress_buffer.clear()
    with progress_scope("progress-control-points", recovery_case_id="case-control-points"):
        log_event(source_event, recovery_case_id="case-control-points")

    assert len(progress_buffer.snapshot("progress-control-points")) == 1
