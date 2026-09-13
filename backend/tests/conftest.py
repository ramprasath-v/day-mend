"""Shared deterministic test configuration."""

from datetime import date

import pytest

from app.fixtures.demo_date import DEMO_CARE_DATE_ENV

TEST_DEMO_CARE_DATE = date(2026, 8, 27)


@pytest.fixture(autouse=True)
def fixed_demo_care_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let canonical fixture tests depend on the machine's calendar date."""

    monkeypatch.setenv(DEMO_CARE_DATE_ENV, TEST_DEMO_CARE_DATE.isoformat())
