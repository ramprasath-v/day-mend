"""Create the configured DayMend development RecoveryCase table if needed."""

import os

from app.repositories.dynamodb_recovery_case_repository import ensure_recovery_case_table


def main() -> int:
    table_name = ensure_recovery_case_table()
    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "SDK default"
    print(f"DynamoDB table ready: {table_name} (region: {region})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
