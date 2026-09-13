"""Independent versioned profile item in the existing demo DynamoDB table."""

from threading import Lock
from typing import Protocol

from botocore.exceptions import ClientError

from app.models.family import FamilyProfile
from app.repositories.dynamodb_recovery_case_repository import DynamoDBRecoveryCaseRepository

PROFILE_KEY = "family-profile:demo"


class FamilyVersionConflict(RuntimeError):
    pass


class FamilyRepository(Protocol):
    def get(self) -> FamilyProfile | None: ...
    def save(self, profile: FamilyProfile, expected_version: int | None) -> FamilyProfile: ...


class InMemoryFamilyRepository:
    def __init__(self) -> None:
        self._profile: FamilyProfile | None = None
        self._lock = Lock()

    def get(self) -> FamilyProfile | None:
        with self._lock:
            return self._profile.model_copy(deep=True) if self._profile else None

    def save(self, profile: FamilyProfile, expected_version: int | None) -> FamilyProfile:
        with self._lock:
            actual = self._profile.version if self._profile else None
            if actual != expected_version:
                raise FamilyVersionConflict("Family settings changed; reload before saving.")
            self._profile = profile.model_copy(
                update={"version": (expected_version or 0) + 1}, deep=True
            )
            return self._profile.model_copy(deep=True)


class DynamoDBFamilyRepository:
    def __init__(self, *, table=None) -> None:
        # Same table and IAM; a distinct namespaced aggregate, never a RecoveryCase.
        self._table = table if table is not None else DynamoDBRecoveryCaseRepository()._table

    def get(self) -> FamilyProfile | None:
        item = self._table.get_item(Key={"recovery_case_id": PROFILE_KEY}, ConsistentRead=True).get(
            "Item"
        )
        return FamilyProfile.model_validate_json(item["payload"]) if item else None

    def save(self, profile: FamilyProfile, expected_version: int | None) -> FamilyProfile:
        stored = profile.model_copy(update={"version": (expected_version or 0) + 1}, deep=True)
        kwargs = {
            "Item": {
                "recovery_case_id": PROFILE_KEY,
                "entity_type": "FamilyProfile",
                "version": stored.version,
                "payload": stored.model_dump_json(),
            },
            "ConditionExpression": "attribute_not_exists(recovery_case_id)",
        }
        if expected_version is not None:
            kwargs.update(
                {
                    "ConditionExpression": "#version = :expected",
                    "ExpressionAttributeNames": {"#version": "version"},
                    "ExpressionAttributeValues": {":expected": expected_version},
                }
            )
        try:
            self._table.put_item(**kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise FamilyVersionConflict(
                    "Family settings changed; reload before saving."
                ) from exc
            raise
        return stored
