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
4. Validate all hard constraints deterministically.
5. Execute valid actions and observe their real outcomes.
6. Continue, replan from updated state, or request approval as needed.
7. Resume the same case after a decision or response.
8. Mark the case `RESOLVED` only after deterministic completion verification.

## Current status

**Phase 0 — repository foundation.** The repository currently contains typed domain contracts,
project guardrails, architecture and scenario documentation, and contract-level tests. It does
not yet implement the Strands agent, Bedrock connection, planning, deterministic business
validation, execution, replanning, persistence, APIs, integrations, or frontend.

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

Run the contract tests and quality checks:

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
