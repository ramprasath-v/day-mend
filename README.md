# DayMend

> “When childcare falls through, your whole day shouldn’t.”

DayMend is a childcare disruption recovery agent for working parents. When normal childcare
unexpectedly falls through, the problem is larger than finding an available babysitter: the
parent must reconcile coverage windows, calendars, trusted people, handoffs, costs, family
preferences, approvals, and changing responses while the workday is already beginning.

DayMend recovers that day end to end. Unlike a backup-care marketplace, it maintains a recovery
case, gathers the family's relevant context, proposes coordinated coverage and calendar changes,
reacts when assumptions become false, pauses only for meaningful approval decisions, resumes the
same case, and verifies that coverage was actually restored.

## Why an agent

Recovery is a changing decision process rather than a fixed lookup. An agent is useful for
understanding the disruption, choosing which context and tools it needs, reasoning over hard and
soft preferences, proposing a recovery strategy, and deciding what to repair after an external
change.

The agent does not get the final word on safety or completion. Deterministic code must validate
coverage, trust, availability, overlaps, handoffs, travel feasibility, spending limits, approval
requirements, action outcomes, and final completion. The LLM proposes a plan; deterministic code
decides whether it is valid. A case cannot become `RESOLVED` until final deterministic coverage
verification succeeds.

## Recovery loop

1. Record a disruption as a persistent `RecoveryCase`.
2. Gather current family, calendar, caregiver, availability, and policy context.
3. Have one Strands Recovery Agent produce a structured `RecoveryPlan`.
4. Validate all hard constraints deterministically; during initial planning, return structured
   findings to that same agent for at most two repairs (three proposals total).
5. Accept only a valid Plan A, then execute valid actions and observe their real outcomes.
6. Continue, replan from updated state, or request approval as needed.
7. Resume the same case after a decision or response.
8. Mark the case `RESOLVED` only after deterministic completion verification.

## Current status

**Milestone 1 — COMPLETE.** The repository contains one real Strands Recovery Agent, five
read-only context tools, typed structured plan output, the synthetic primary scenario, and an
independent deterministic validator. Initial planning now has a bounded validation-and-repair
loop: context is gathered once, each proposal is validated, and structured findings are returned
to the same agent for up to three total proposals. A real Nova Pro smoke invoked all five tools,
repaired two rejected drafts, and reached `valid=true` on attempt 3. The final plan fully covered
08:00–16:00, respected caregiver availability and parent calendars, cost `$92.00`
deterministically, and correctly reported `requires_approval=true` against the `$30` automatic
spend threshold. All offline tests and quality checks pass.

**Milestone 2 — COMPLETE.** A typed caregiver-decline event updates request-local authoritative
world state, invalidates only matching plan assumptions, calculates impacted and preserved
segments plus newly uncovered windows, and sends that state to the same Recovery Agent. A real
Nova Pro smoke produced a deterministically valid Plan B while retaining valid Plan A in history.

**Milestone 3 — COMPLETE.** Complete `RecoveryCase`
aggregates now round-trip through in-memory or DynamoDB repositories. Deterministic policy pauses
a valid `$92` plan at `APPROVAL_REQUIRED` because it exceeds the `$30` autonomy limit. A later
approve/reject command reloads and resumes the same versioned case. Approved simulated actions
execute exactly once, and only the deterministic completion verifier can set `RESOLVED`. A real
`daymend-recovery-cases-dev` DynamoDB smoke persisted and reloaded the same case through approval,
four successful actions, completion verification, and final `RESOLVED` state at version 4.

**Milestone 4 — COMPLETE.** A thin FastAPI boundary now exposes health, recovery creation/read,
external caregiver events, and approval decisions. `RecoveryApplicationService` coordinates the
existing planning, invalidation, repository, autonomy, execution, and completion services; routes
contain no recovery policy or persistence logic. The offline HTTP lifecycle reaches `RESOLVED`
through the real deterministic services, and a live Nova Pro + DynamoDB API smoke resolved the
same case after Plan B approval.

These are deliberately separate mechanisms:

- **Initial-plan repair:** a draft was never valid; world state is unchanged; validator findings
  correct the draft.
- **World-state replanning:** Plan A was valid; a recorded external event changes authoritative
  facts; deterministic impact analysis begins a new Plan B planning cycle.

Execution still uses simulated explicit actions only; there is no real booking, payment,
calendar, messaging, authentication, or frontend integration.

## Preferences, policy, and trust

`FamilyPreferences` contains soft priorities used by the agent to rank otherwise valid plans,
such as preferring family coverage or fewer handoffs. A preference violation can produce a
validator warning but cannot make a plan invalid.

`FamilyPolicy` contains hard rules enforced by deterministic code, including caregiver trust,
whether unapproved caregivers may be used, the automatic-spend boundary, and the minimum
handoff buffer. `Caregiver.is_trusted` is the sole authoritative trust state for an individual
caregiver; policy does not duplicate a caregiver allowlist.

The automatic-spend limit determines whether a valid proposal would require approval before
execution. It is not a planning budget: exceeding it does not make an otherwise feasible plan
invalid, and coverage must never be sacrificed to avoid approval. Milestone 1 reports the
boundary; Milestone 3 deterministically pauses and resumes execution around it.

## Repository structure

```text
.
├── AGENTS.md
├── LICENSE
├── README.md
├── backend
│   ├── app
│   │   ├── agent
│   │   ├── api
│   │   ├── fixtures
│   │   ├── models
│   │   ├── repositories
│   │   ├── services
│   │   └── tools
│   ├── tests
│   └── pyproject.toml
└── docs
    ├── architecture.md
    ├── demo-flow.md
    └── milestones.md
```

## Local setup

Prerequisites: Python 3.11 or newer and
[`uv`](https://docs.astral.sh/uv/getting-started/installation/).

```bash
cd backend
uv sync --dev
```

The project uses `strands-agents` with its native Amazon Bedrock provider. AWS credentials are
resolved through the normal AWS SDK credential chain and are never stored in this repository.
Configure a region and, optionally, override the default model:

```bash
export AWS_REGION=us-west-2
export DAYMEND_BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-4-6
```

Your AWS identity must have Bedrock model access and permission to invoke the configured model.
Run the real planning and validation smoke path from `backend/`:

```bash
uv run python -m app.agent.demo
```

Run the live Milestone 2 Plan A → caregiver decline → Plan B smoke:

```bash
DAYMEND_BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 \
uv run python -m app.agent.replanning_demo
```

For DynamoDB-backed Milestone 3 development, configure the table and create it if absent:

```bash
export DAYMEND_RECOVERY_TABLE=daymend-recovery-cases-dev
uv run python -m app.repositories.dynamodb_setup
```

The table uses `recovery_case_id` as its string partition key and on-demand billing. Each case is
one versioned item whose `payload` is the complete Pydantic JSON aggregate; no secrets or model
reasoning are stored. Run the live persistence/approval/resume smoke with:

```bash
DAYMEND_RECOVERY_TABLE=daymend-recovery-cases-dev \
uv run python -m tests.live_dynamodb_approval_smoke
```

That harness uses the deterministically validated Milestone 2 test aggregate and proves the real
DynamoDB/service lifecycle, not fresh model behavior. To combine fresh Nova Pro planning with the
same DynamoDB lifecycle, run:

```bash
DAYMEND_BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 \
DAYMEND_RECOVERY_TABLE=daymend-recovery-cases-dev \
uv run python -m app.agent.approval_demo
```

The combined command preserves the strict three-attempt planning cap and may stop before
persistence if a fresh model session does not produce a valid Plan A or Plan B.

The smoke output contains the configured model ID, tools used, proposal and validation summaries
for each attempt, and the final safety/cost/autonomy result. It does not expose model
chain-of-thought.

Run the offline tests and quality checks:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## FastAPI

Run the local API from `backend/` with process-local persistence:

```bash
export DAYMEND_RECOVERY_REPOSITORY=memory
export DAYMEND_ALLOWED_ORIGINS=http://localhost:4200
.venv/bin/uvicorn app.main:app --reload --port 8000
```

Use `DAYMEND_RECOVERY_REPOSITORY=dynamodb` plus `DAYMEND_RECOVERY_TABLE` and `AWS_REGION`
for the AWS demo repository. Planning uses `DAYMEND_BEDROCK_MODEL_ID` through the existing
Recovery Agent configuration. Startup never creates a DynamoDB table; use the explicit setup
helper above.

The API exposes:

- `GET /health`
- `POST /recoveries`
- `GET /recoveries/{recovery_case_id}`
- `POST /recoveries/{recovery_case_id}/events`
- `POST /recoveries/{recovery_case_id}/approvals/{approval_id}`

Interactive OpenAPI documentation is available at `/docs`, with the schema at `/openapi.json`.
Mutation requests may include `expected_version`; stale versions return `409` without overwriting
newer state. CORS origins are a comma-separated allowlist and default only to
`http://localhost:4200`.

Example create request:

```json
{
  "disruption_type": "CHILDCARE_UNAVAILABLE",
  "occurred_at": "2026-08-27T07:02:00-07:00",
  "caregiver_id": "nanny",
  "message": "I'm sick and can't come today."
}
```

Run the live API lifecycle smoke with:

```bash
AWS_REGION=us-east-1 \
DAYMEND_BEDROCK_MODEL_ID=amazon.nova-pro-v1:0 \
DAYMEND_RECOVERY_REPOSITORY=dynamodb \
DAYMEND_RECOVERY_TABLE=daymend-recovery-cases-dev \
.venv/bin/python -m tests.live_api_smoke
```

## Roadmap

The planned increments are core Strands planning; plan invalidation and replanning; persistence,
autonomy, and approval/resume; FastAPI; an Angular recovery UI; AWS deployment and observability;
and submission polish. Each milestone and its exit criterion is documented in
[`docs/milestones.md`](docs/milestones.md).

The primary end-to-end scenario is documented in
[`docs/demo-flow.md`](docs/demo-flow.md), and architectural boundaries are documented in
[`docs/architecture.md`](docs/architecture.md).

The fixture is deterministic and synthetic. Tool selection and structured plan generation in
the smoke path are performed by the real Strands/Bedrock agent; no Plan A is hardcoded.
