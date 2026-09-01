"""Persistence adapters for complete RecoveryCase aggregates."""

from app.repositories.dynamodb_recovery_case_repository import (
    DEFAULT_RECOVERY_TABLE,
    DynamoDBRecoveryCaseRepository,
    ensure_recovery_case_table,
)
from app.repositories.in_memory_recovery_case_repository import (
    InMemoryRecoveryCaseRepository,
)
from app.repositories.recovery_case_repository import (
    RecoveryCaseNotFound,
    RecoveryCaseRepository,
    RecoveryCaseRepositoryError,
    RecoveryCaseVersionConflict,
)

__all__ = [
    "DEFAULT_RECOVERY_TABLE",
    "DynamoDBRecoveryCaseRepository",
    "InMemoryRecoveryCaseRepository",
    "RecoveryCaseNotFound",
    "RecoveryCaseRepository",
    "RecoveryCaseRepositoryError",
    "RecoveryCaseVersionConflict",
    "ensure_recovery_case_table",
]
