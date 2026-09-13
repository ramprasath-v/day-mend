"""DynamoDB contract tests without AWS calls."""

from copy import deepcopy

import pytest
from botocore.exceptions import ClientError

from app.application.family_service import FamilyService
from app.repositories.family_repository import (
    PROFILE_KEY,
    DynamoDBFamilyRepository,
    FamilyVersionConflict,
)


class Table:
    def __init__(self):
        self.items = {"unrelated-case": {"payload": "untouched"}}
        self.reads = []
        self.writes = []

    def get_item(self, **kwargs):
        self.reads.append(kwargs)
        item = self.items.get(kwargs["Key"]["recovery_case_id"])
        return {"Item": deepcopy(item)} if item else {}

    def put_item(self, **kwargs):
        self.writes.append(kwargs)
        item = kwargs["Item"]
        current = self.items.get(item["recovery_case_id"])
        expected = kwargs.get("ExpressionAttributeValues", {}).get(":expected")
        if (current.get("version") if current else None) != expected:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.items[item["recovery_case_id"]] = deepcopy(item)


def test_dynamodb_profile_is_independent_seeded_once_and_decimal_exact():
    table = Table()
    repository = DynamoDBFamilyRepository(table=table)
    family = FamilyService(repository)
    profile = family.get()
    assert profile.version == 1
    assert family.get() == profile
    assert len(table.writes) == 1
    assert table.writes[0]["ConditionExpression"] == "attribute_not_exists(recovery_case_id)"
    assert table.writes[0]["Item"]["entity_type"] == "FamilyProfile"
    assert all(read["ConsistentRead"] for read in table.reads)
    stored = repository.save(profile, profile.version)
    assert stored.version == 2
    assert repository.get() == stored
    assert table.items["unrelated-case"] == {"payload": "untouched"}
    assert set(table.items) == {"unrelated-case", PROFILE_KEY}
    with pytest.raises(FamilyVersionConflict):
        repository.save(profile, profile.version)
    assert repository.get() == stored


def test_seed_race_reads_winner_instead_of_overwriting():
    table = Table()
    repository = DynamoDBFamilyRepository(table=table)
    real_get = repository.get
    winner = FamilyService(repository).get()
    first = True

    def missing_once():
        nonlocal first
        if first:
            first = False
            return None
        return real_get()

    repository.get = missing_once
    assert FamilyService(repository).get() == winner
    assert real_get() == winner


def test_dynamodb_errors_are_not_replaced_with_demo_defaults():
    class Broken(Table):
        def get_item(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDeniedException"}}, "GetItem")

    with pytest.raises(ClientError):
        FamilyService(DynamoDBFamilyRepository(table=Broken())).get()
