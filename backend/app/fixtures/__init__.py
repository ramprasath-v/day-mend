"""Synthetic fixtures used by the DayMend local demonstration."""

from app.fixtures.backup_care_research import get_backup_care_research_scenario
from app.fixtures.nanny_cancellation import (
    DemoScenario,
    get_demo_scenario,
    get_legacy_demo_scenario,
)

__all__ = [
    "DemoScenario",
    "get_backup_care_research_scenario",
    "get_demo_scenario",
    "get_legacy_demo_scenario",
]
