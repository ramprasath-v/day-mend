"""One authoritative local calendar date for canonical demo data."""

import os
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.models import CoverageWindow

DEMO_TIME_ZONE = ZoneInfo("America/Los_Angeles")
DEMO_CARE_DATE_ENV = "DAYMEND_DEMO_CARE_DATE"


def resolve_demo_care_date(now: datetime | None = None) -> date:
    """Resolve the care date once; tests may inject a date through the environment."""

    configured = os.getenv(DEMO_CARE_DATE_ENV)
    if configured:
        return date.fromisoformat(configured)
    current = now or datetime.now(DEMO_TIME_ZONE)
    if current.tzinfo is None:
        current = current.replace(tzinfo=DEMO_TIME_ZONE)
    return current.astimezone(DEMO_TIME_ZONE).date()


@dataclass(frozen=True)
class DemoTimeline:
    """Create every fixture timestamp from one care date and timezone."""

    care_date: date

    def at(self, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(
            self.care_date,
            datetime.min.time(),
            tzinfo=DEMO_TIME_ZONE,
        ).replace(hour=hour, minute=minute)

    def window(
        self,
        start_hour: int,
        end_hour: int,
        start_minute: int = 0,
        end_minute: int = 0,
    ) -> CoverageWindow:
        return CoverageWindow(
            start=self.at(start_hour, start_minute),
            end=self.at(end_hour, end_minute),
        )
