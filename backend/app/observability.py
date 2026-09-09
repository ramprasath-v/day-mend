"""Safe structured events for CloudWatch-compatible application telemetry."""

import json
import logging
from decimal import Decimal
from enum import Enum
from typing import Any

LOGGER_NAME = "daymend.recovery"
_LOGGER = logging.getLogger(LOGGER_NAME)
_LOGGER.setLevel(logging.INFO)
if not _LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _LOGGER.addHandler(_handler)

_SAFE_FIELDS = {
    "action_id",
    "action_type",
    "agent_role",
    "architecture",
    "approval_id",
    "attempt_number",
    "affected_segment_count",
    "affected_window_count",
    "affected_windows",
    "candidate_count",
    "cost",
    "decision",
    "duration_ms",
    "eligible_candidate_count",
    "error_type",
    "invalidated_count",
    "has_previous_candidate",
    "issue_count",
    "model_id",
    "model_call_count",
    "operation",
    "phase",
    "planning_mode",
    "planner_input_digest",
    "plan_id",
    "preserved_count",
    "preserved_segment_count",
    "recovery_case_id",
    "recommended_candidate_id",
    "research_id",
    "requires_approval",
    "request_id",
    "response_status",
    "status",
    "stage",
    "success",
    "tools_used",
    "tool_call_count",
    "valid",
    "validator_issue_count",
    "version",
}


def log_event(event_type: str, **fields: Any) -> None:
    """Emit one allow-listed JSON event without accepting arbitrary sensitive fields."""

    unexpected = set(fields) - _SAFE_FIELDS
    if unexpected:
        names = ", ".join(sorted(unexpected))
        raise ValueError(f"unsafe observability fields: {names}")
    payload = {
        "event_type": event_type,
        **{key: _json_value(value) for key, value in fields.items() if value is not None},
    }
    logging.getLogger(LOGGER_NAME).info(json.dumps(payload, separators=(",", ":")))


def _json_value(value: Any) -> Any:
    if isinstance(value, (Decimal, Enum)):
        return str(value.value if isinstance(value, Enum) else value)
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError(f"unsupported observability value type: {type(value).__name__}")
