# DayMend demo flow

## What the demo proves

The demo is one continuous, persisted childcare recovery—not a scripted sequence of disconnected
screens. Agents propose both plans through the deployed AgentCore runtime. Deterministic services
validate the plans, apply family policy, guard execution, and decide whether the case is complete.

All family, calendar, caregiver, travel, and backup-provider data is synthetic. Harbor Nanny Coop
is a fictional fixture; there is no Care.com or real marketplace integration.

## Proven sequence

### 1. Normal day

The family begins with continuous nanny coverage. The browser has no active local case reference.

### 2. Nanny unavailable

Click **Nanny unavailable** once.

The frontend creates a progress correlation ID, opens SSE, and sends one `POST /recoveries` with
the disruption timestamp. FastAPI creates a new lifecycle only after a valid Plan A is available.

The live panel shows safe progress from the Recovery Orchestrator, Constraint Planner, and
deterministic validator. The deployed v12 proof produced valid Plan A on the first Planner attempt
in about 32.0 seconds server-side.

### 3. Plan A

Plan A provides continuous childcare and includes Grandma in a real care/transport dependency.
It is accepted only after deterministic coverage, calendar, location, travel, handoff, caregiver,
and policy validation succeeds.

### 4. Grandma declines

Click **Grandma can’t help** once.

The event is appended to the same `RecoveryCase`. Its semantic `occurred_at` timestamp is preserved
while the aggregate `updated_at` remains monotonic. Application code invalidates the assumptions
and plan segments that depend on Grandma, identifies uncovered coverage, and preserves only
segments that materially survive into Plan B.

The UI’s **What changed** section compares Plan A and Plan B by time, person/transporter, segment
type, and location/route semantics. A transport segment that disappears is not labeled preserved.

### 5. Backup Care Research

Known family options cannot cover the affected window. Deterministic interval analysis therefore
invokes the Backup Care Research Agent exactly once.

The agent ranks eligible synthetic records and recommends Harbor Nanny Coop. It does not book care
or bypass validation. A deterministic post-research planability gate rejects providers that cannot
join the preserved plan before the Planner runs. The viable record then enters the authoritative
planning context.

### 6. Plan B

The Constraint Planner selects from authoritative primitive IDs for this preservation-aware Plan B,
and application code materializes the exact segments before independent validation. The hosted
proof reached valid Plan B on the first Planner attempt in about 60.5 seconds, including research.

Plan B replaces the affected window with Harbor Nanny Coop while preserving still-valid late-day
coverage. Deterministic cost is `$94.50`.

### 7. Human approval

The family’s automatic-spend threshold is `$30`. Because `$94.50 > $30`, deterministic policy sets
the case to `APPROVAL_REQUIRED` and the UI presents the proposed provider, coverage window, cost,
threshold, and reason for the pause.

Click **Approve** once. Approval updates the same versioned case. The rejection path is separately
tested: `REJECTED` runs no execution actions and never emits `RECOVERY_RESOLVED`.

### 8. Execution and completion

Approval triggers two simulated, guarded actions. Both return successful results. The deterministic
completion verifier then checks the final plan and current world state. Only after that check passes
does the case transition to `RESOLVED`.

### 9. Persistence

Reload the page. The browser’s local storage contains only the case ID; Angular reloads the same
complete aggregate from DynamoDB. The final plan, previous plan, events, approval, action results,
version, and `RESOLVED` status remain attached to that case.

## What to point out to judges

- The live timeline reflects structured backend events, not animated fake steps.
- The agents can propose and explain, but cannot mark their work valid.
- Plan B is triggered by a real world-state change on the same case.
- DayMend preserves materially surviving coverage rather than rebuilding history cosmetically.
- Research is conditional and grounded in eligible synthetic inventory.
- The parent controls the meaningful autonomy boundary.
- `RESOLVED` is a deterministic fact, not model text.

## Proven result

| Evidence | Result |
| --- | --- |
| AgentCore runtime | Deployed v12, `READY` |
| Model | Claude Sonnet 4.5 inference profile |
| Plan A | Valid on Planner attempt 1; ~32.0 s server-side |
| World-state change | Grandma decline recorded on the same case |
| Research | One Backup Care Research invocation |
| Plan B | Valid on Planner attempt 1; ~60.5 s |
| Cost and approval | `$94.50`; approval required above `$30` |
| Execution | Two simulated actions succeeded |
| Completion | Deterministic verification passed |
| Final status | `RESOLVED` |
| Persistence | Same versioned case returned after reload |
| Live progress | SSE healthy; no duplicate rendering or browser console errors |
