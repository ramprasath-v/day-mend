"""Grounded synthetic provider search available only to the Research Agent."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from strands import tool

from app.models import CoverageWindow
from app.services import search_backup_care_candidates
from app.tools.recovery_context import get_active_scenario

_REQUESTED_WINDOWS: ContextVar[tuple[CoverageWindow, ...] | None] = ContextVar(
    "daymend_backup_care_requested_windows",
    default=None,
)


@contextmanager
def use_backup_care_request(windows: list[CoverageWindow]) -> Iterator[None]:
    """Bind authoritative uncovered windows to one request-local research invocation."""

    token = _REQUESTED_WINDOWS.set(tuple(windows))
    try:
        yield
    finally:
        _REQUESTED_WINDOWS.reset(token)


@tool
def search_backup_care() -> dict[str, Any]:
    """Search synthetic backup-care inventory for the active uncovered childcare windows.

    Hard availability, provider verification, background-check, and child-age eligibility are
    applied deterministically. Eligible records retain price, distance, rating, review count,
    and prior-use attributes so the Research Agent can compare soft tradeoffs.

    Returns:
        Structured considered and eligible synthetic candidate records.
    """

    requested = _REQUESTED_WINDOWS.get()
    if requested is None:
        raise RuntimeError("backup-care search requires request-local uncovered windows")
    result = search_backup_care_candidates(get_active_scenario(), list(requested))
    return result.model_dump(mode="json")


BACKUP_CARE_RESEARCH_TOOLS = [search_backup_care]
