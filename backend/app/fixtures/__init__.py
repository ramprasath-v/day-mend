"""Synthetic fixtures used by the DayMend local demonstration."""

from app.fixtures.backup_care_research import get_backup_care_research_scenario
from app.fixtures.demo_date import DemoTimeline, resolve_demo_care_date
from app.fixtures.nanny_cancellation import (
    DemoScenario,
    get_demo_scenario,
    get_legacy_demo_scenario,
)

__all__ = [
    "DemoScenario",
    "DemoTimeline",
    "get_backup_care_research_scenario",
    "get_demo_scenario",
    "get_legacy_demo_scenario",
    "resolve_demo_care_date",
]
