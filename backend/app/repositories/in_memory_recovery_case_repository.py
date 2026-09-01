"""Process-local RecoveryCase repository used by tests and local demos."""

from app.models import RecoveryCase
from app.repositories.recovery_case_repository import (
    RecoveryCaseNotFound,
    RecoveryCaseVersionConflict,
    next_version,
)


class InMemoryRecoveryCaseRepository:
    """Store deep copies so reloads behave like a real process boundary."""

    def __init__(self) -> None:
        self._cases: dict[str, RecoveryCase] = {}

    def get(self, case_id: str) -> RecoveryCase:
        try:
            return self._cases[case_id].model_copy(deep=True)
        except KeyError as exc:
            raise RecoveryCaseNotFound(f"recovery case {case_id} was not found") from exc

    def save(
        self,
        recovery_case: RecoveryCase,
        *,
        expected_version: int | None = None,
    ) -> RecoveryCase:
        existing = self._cases.get(recovery_case.case_id)
        if expected_version is None:
            if existing is not None:
                raise RecoveryCaseVersionConflict(
                    f"recovery case {recovery_case.case_id} already exists"
                )
        elif existing is None or existing.version != expected_version:
            actual = None if existing is None else existing.version
            raise RecoveryCaseVersionConflict(
                f"expected version {expected_version}, found {actual}"
            )
        stored = next_version(recovery_case, expected_version)
        self._cases[stored.case_id] = stored
        return stored.model_copy(deep=True)
