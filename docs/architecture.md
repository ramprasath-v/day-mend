# DayMend Architecture

## System boundary

DayMend is a childcare disruption recovery agent. Its central unit of work is a persistent
`RecoveryCase`, not a chat session or a one-shot babysitter search. The case retains the facts,
plans, assumptions, decisions, external outcomes, and status needed to recover safely across
pauses and replanning cycles.

## Recovery flow

```text
Disruption / external event
        ↓
Recovery Case
        ↓
Strands Recovery Agent
        ↓
Context/tool gathering
        ↓
Recovery strategy
        ↓
Structured RecoveryPlan
        ↓
Deterministic Validator
        ↓
Execution
        ↓
Observe external outcome
        ↓
Either: continue | replan | request approval
        ↓
Resume if necessary
        ↓
Completion verification
        ↓
RESOLVED
```

The agent may propose a strategy and structured plan, but a deterministic validator decides
whether that plan satisfies hard constraints. Execution outcomes update the case's world state.
If an assumption becomes false, the system recalculates the remaining coverage gap and asks the
agent to repair the plan from current facts rather than following a prewritten branch.

Approval is a persisted state transition. When the parent decides, the same case resumes with
that decision recorded. Final deterministic verification is the only path to `RESOLVED`.

## Responsibility boundary

Agent/LLM reasoning is appropriate for:

- interpreting a natural-language disruption;
- deciding which context and tools are needed;
- balancing hard constraints and soft family preferences;
- proposing a recovery strategy and structured plan;
- deciding which portion of a plan needs repair after a change; and
- selecting the next action from valid options.

Deterministic code must enforce:

- complete childcare coverage;
- trusted or explicitly approved caregivers;
- caregiver availability and non-overlapping assignments;
- feasible handoffs and travel;
- spending thresholds and approval requirements; and
- final action and coverage verification.

## Future tool categories

The Recovery Agent may eventually use tools for:

- childcare schedules;
- parent calendars;
- trusted caregivers;
- caregiver availability;
- caregiver communication and responses;
- family policy;
- backup-care availability;
- calendar actions;
- approval;
- booking and action execution; and
- final coverage verification.

Tools are not separate agents by default. They expose data or deterministic actions to the one
core Recovery Agent. Multi-agent specialization is justified only if future implementation
reveals genuinely separate, durable reasoning responsibilities.

## Phase 0 shape

Phase 0 contains domain contracts only. It does not contain the Strands agent, Bedrock access,
workflow services, deterministic business validation, persistence, APIs, integrations, or UI.

