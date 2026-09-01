"""Persistence boundary for resumable DayMend recovery cases."""

from typing import Protocol

from app.models import RecoveryCase


class RecoveryCaseRepositoryError(RuntimeError):
    """Base repository failure."""


class RecoveryCaseNotFound(RecoveryCaseRepositoryError):
    """Requested case does not exist."""


class RecoveryCaseVersionConflict(RecoveryCaseRepositoryError):
    """Saved state changed since the caller loaded it."""


class RecoveryCaseRepository(Protocol):
    """Small storage contract used by deterministic workflow services."""

    def get(self, case_id: str) -> RecoveryCase:
        """Load one case or raise RecoveryCaseNotFound."""

    def save(
        self,
        recovery_case: RecoveryCase,
        *,
        expected_version: int | None = None,
    ) -> RecoveryCase:
        """Persist and return a copy with its incremented version."""


def next_version(
    recovery_case: RecoveryCase,
    expected_version: int | None,
) -> RecoveryCase:
    """Create the stored copy shared by repository implementations."""

    base_version = expected_version if expected_version is not None else recovery_case.version
    return recovery_case.model_copy(update={"version": base_version + 1}, deep=True)
