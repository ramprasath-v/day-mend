"""Real FastAPI → Strands/Bedrock → DynamoDB lifecycle smoke."""

import json
import os
import sys
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.main import create_app


def main() -> int:
    """Run the required live HTTP path and print only observable workflow evidence."""

    if os.getenv("DAYMEND_RECOVERY_REPOSITORY", "").lower() != "dynamodb":
        print(
            "LIVE API SMOKE BLOCKED: DAYMEND_RECOVERY_REPOSITORY must be dynamodb",
            file=sys.stderr,
        )
        return 1
    client = TestClient(create_app())
    started_at = datetime.now(UTC)
    create = client.post(
        "/recoveries",
        json={
            "disruption_type": "CHILDCARE_UNAVAILABLE",
            "occurred_at": started_at.isoformat(),
            "caregiver_id": "nanny",
            "message": "I'm sick and can't come today.",
        },
    )
    if create.status_code != 201:
        print(f"LIVE API SMOKE BLOCKED: create={create.status_code} {create.text}", file=sys.stderr)
        return 2
    created = create.json()
    case_id = created["recovery_case_id"]
    event_at = datetime.now(UTC)
    event = client.post(
        f"/recoveries/{case_id}/events",
        json={
            "event_type": "CAREGIVER_DECLINED",
            "caregiver_id": "grandma",
            "occurred_at": event_at.isoformat(),
            "relevant_window": {
                "start": "2026-08-27T10:00:00-07:00",
                "end": "2026-08-27T13:00:00-07:00",
            },
            "message": "Sorry, I can't help today.",
            "expected_version": created["version"],
        },
    )
    if event.status_code != 200:
        print(f"LIVE API SMOKE BLOCKED: event={event.status_code} {event.text}", file=sys.stderr)
        return 3
    pending = event.json()
    approval = pending.get("pending_approval")
    if not approval:
        print("LIVE API SMOKE BLOCKED: expected a pending approval", file=sys.stderr)
        return 4
    approved = client.post(
        f"/recoveries/{case_id}/approvals/{approval['approval_id']}",
        json={"decision": "APPROVE", "expected_version": pending["version"]},
    )
    final = client.get(f"/recoveries/{case_id}")
    output = {
        "recovery_case_id": case_id,
        "create_status": created["status"],
        "event_status": pending["status"],
        "active_plan_after_event": pending["active_plan"]["plan_id"],
        "invalidated_assumptions": len(pending["invalidated_assumptions"]),
        "approval_id": approval["approval_id"],
        "approval_http_status": approved.status_code,
        "final_http_status": final.status_code,
        "final_status": final.json().get("status"),
        "same_case": final.json().get("recovery_case_id") == case_id,
        "version": final.json().get("version"),
    }
    print(json.dumps(output, indent=2))
    return 0 if approved.status_code == 200 and output["final_status"] == "RESOLVED" else 5


if __name__ == "__main__":
    raise SystemExit(main())
