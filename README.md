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

Milestone 1 does not execute plan actions. Its repairs correct a proposal that was never valid
while the authoritative world state remains unchanged. Replanning after an external world-state
change, approval/resume, persistence, APIs, integrations, and frontend work remain future
milestones.

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
invalid, and coverage must never be sacrificed to avoid approval. Milestone 1 reports that
boundary but does not implement approval or execute the plan.

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

The smoke output contains the configured model ID, tools used, proposal and validation summaries
for each attempt, and the final safety/cost/autonomy result. It does not expose model
chain-of-thought.

Run the offline tests and quality checks:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
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
