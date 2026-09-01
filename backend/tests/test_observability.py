"""Structured observability remains useful, bounded, and free of arbitrary fields."""

import json
import logging
from decimal import Decimal

import pytest

from app.observability import LOGGER_NAME, log_event


def test_log_event_emits_machine_readable_safe_fields(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=LOGGER_NAME)

    log_event(
        "planning_validated",
        recovery_case_id="case-observable",
        plan_id="plan-a",
        model_id="amazon.nova-pro-v1:0",
        attempt_number=2,
        duration_ms=1234,
        cost=Decimal("48.00"),
        valid=True,
    )

    payload = json.loads(caplog.records[-1].message)
    assert payload == {
        "event_type": "planning_validated",
        "recovery_case_id": "case-observable",
        "plan_id": "plan-a",
        "model_id": "amazon.nova-pro-v1:0",
        "attempt_number": 2,
        "duration_ms": 1234,
        "cost": "48.00",
        "valid": True,
    }


def test_log_event_rejects_unreviewed_or_sensitive_fields() -> None:
    with pytest.raises(ValueError, match="unsafe observability fields"):
        log_event("recovery_failed", raw_prompt="private family context")
