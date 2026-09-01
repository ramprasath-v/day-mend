"""Single-item DynamoDB persistence for complete RecoveryCase aggregates."""

import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

from app.models import RecoveryCase
from app.repositories.recovery_case_repository import (
    RecoveryCaseNotFound,
    RecoveryCaseVersionConflict,
    next_version,
)

DEFAULT_RECOVERY_TABLE = "daymend-recovery-cases-dev"


class DynamoDBRecoveryCaseRepository:
    """Persist each case as one versioned JSON payload under recovery_case_id."""

    def __init__(
        self,
        *,
        table_name: str | None = None,
        region_name: str | None = None,
        dynamodb_resource: Any | None = None,
    ) -> None:
        self.table_name = table_name or os.getenv(
            "DAYMEND_RECOVERY_TABLE",
            DEFAULT_RECOVERY_TABLE,
        )
        resource = dynamodb_resource or boto3.resource(
            "dynamodb",
            region_name=region_name or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
        )
        self._table = resource.Table(self.table_name)

    def get(self, case_id: str) -> RecoveryCase:
        response = self._table.get_item(
            Key={"recovery_case_id": case_id},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None:
            raise RecoveryCaseNotFound(f"recovery case {case_id} was not found")
        return RecoveryCase.model_validate_json(item["payload"])

    def save(
        self,
        recovery_case: RecoveryCase,
        *,
        expected_version: int | None = None,
    ) -> RecoveryCase:
        stored = next_version(recovery_case, expected_version)
        item = {
            "recovery_case_id": stored.case_id,
            "version": stored.version,
            "status": stored.status.value,
            "updated_at": stored.updated_at.isoformat(),
            "payload": stored.model_dump_json(),
        }
        if expected_version is None:
            condition = "attribute_not_exists(recovery_case_id)"
            values = None
        else:
            condition = "#version = :expected_version"
            values = {":expected_version": expected_version}
        kwargs: dict[str, Any] = {
            "Item": item,
            "ConditionExpression": condition,
        }
        if values is not None:
            kwargs["ExpressionAttributeNames"] = {"#version": "version"}
            kwargs["ExpressionAttributeValues"] = values
        try:
            self._table.put_item(**kwargs)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise RecoveryCaseVersionConflict(
                    f"version conflict while saving recovery case {stored.case_id}"
                ) from exc
            raise
        return stored


def ensure_recovery_case_table(
    *,
    table_name: str | None = None,
    region_name: str | None = None,
) -> str:
    """Create the named development table if absent and wait until it is usable."""

    resolved_name = table_name or os.getenv(
        "DAYMEND_RECOVERY_TABLE",
        DEFAULT_RECOVERY_TABLE,
    )
    resource = boto3.resource(
        "dynamodb",
        region_name=region_name or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION"),
    )
    table = resource.Table(resolved_name)
    try:
        table.load()
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
        table = resource.create_table(
            TableName=resolved_name,
            KeySchema=[{"AttributeName": "recovery_case_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "recovery_case_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
    return resolved_name
