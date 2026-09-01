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

## Milestone 1 implementation

Milestone 1 uses exactly one Strands `Agent`, backed by `BedrockModel`. The agent receives the
disruption rather than a preassembled context bundle and chooses among five read-only `@tool`
capabilities:

- `get_childcare_schedule`
- `get_parent_calendars`
- `get_caregivers`
- `get_family_preferences`
- `get_family_policy`

The agent returns a typed `RecoveryPlan` through Strands structured output. Application code
forcibly resets its state to `NOT_VALIDATED`; the model cannot certify its own proposal.

`PlanValidator` then independently reads the authoritative synthetic scenario and checks full
coverage, gaps, supported identities, caregiver trust and availability, parent calendar
conflicts, handoff feasibility, costs, and hard policy. It returns a validated plan copy with
deterministically recomputed segment and total costs.

Initial planning uses a bounded proposal/validation/repair loop. The five tools gather context
once in a single Strands agent conversation. If validation fails, the validator's structured
issues—stable code, message, and relevant subject/segment/event identifiers—are sent back to the
same agent. The unchanged context is reused and the agent returns a complete repaired proposal.
The loop stops immediately on success or after `MAX_PLAN_ATTEMPTS = 3`; after three invalid
proposals it returns a structured failure with no accepted plan. Application code never inserts
a fallback plan, and the agent cannot waive an issue.

This is initial-plan repair: Plan A has never been valid and the authoritative world state has
not changed. It is distinct from Milestone 2 replanning, where an external event invalidates a
previously valid or executing plan. No external-event invalidation behavior is implemented here.

`FamilyPreferences` are soft. The validator may warn that a proposal did not follow them but
does not reject an otherwise allowed plan. `FamilyPolicy` is hard. `Caregiver.is_trusted` is the
authoritative per-caregiver trust fact; policy states whether that fact is required.

Validation separates three decisions:

1. **Feasibility:** full coverage, supported people, trust, availability, calendars, and
   handoffs determine whether the recovery strategy works safely.
2. **Cost:** authoritative caregiver pricing deterministically replaces all model-proposed
   segment and total amounts.
3. **Autonomy:** cost above `automatic_spend_limit` sets `requires_approval=true`. The threshold
   is not a budget, does not invalidate the plan, and must never cause the planner to leave a
   coverage gap. Approval interaction remains a future milestone.

### Handoff abstraction

Maps and routing are intentionally out of scope. Each caregiver may declare a required handoff
buffer, and policy may declare a family-wide minimum. Adjacent assignments to different people
must overlap by exactly the larger required buffer. Less overlap leaves the handoff infeasible;
more overlap is treated as an inconsistent schedule. The primary fixture uses zero-minute
buffers because its handoffs are explicitly assumed feasible.

### Verified live boundary

The Bedrock smoke command executed successfully with `amazon.nova-pro-v1:0`. It invoked all five
context tools once. Attempt 1 was rejected for omitting the `parent_a_standup` calendar change;
attempt 2 repaired that issue but was rejected for omitting the `parent_a_internal_sync` change;
attempt 3 included both changes and passed deterministic validation. Its five coverage segments
spanned 08:00–16:00, all caregivers were inside authoritative availability, deterministic cost
was `$92.00`, and the `$30` threshold produced `requires_approval=true` without a feasibility
error. Model choice remains environment-configurable.

No execution, replanning, approval/resume, persistence, API, external calendar, or UI behavior
is implemented in Milestone 1.

## Milestone 2 implementation

Milestone 2 introduces a separate world-state replanning path around the same Recovery Agent.
A typed `CAREGIVER_DECLINED` `RecoveryEvent` records caregiver, message, relevant window, and
timestamp. `PlanInvalidationService` applies it deterministically:

1. subtract the declined window from the caregiver's authoritative availability;
2. invalidate only active `CAREGIVER_AVAILABLE` assumptions for that caregiver and overlapping
   window, recording reason, time, and triggering event ID;
3. identify impacted coverage segments and newly uncovered windows;
4. identify every other segment as preserved work; and
5. append the event and valid Plan A snapshot to the in-memory `RecoveryCase` history before
   entering `REPLANNING`.

Context tools read a request-local `DemoScenario` snapshot. Initial planning sees the original
fixture; after an event, the same tools see the updated caregiver availability. Preferences,
policy, calendars, and unrelated caregiver facts are unchanged.

The same Strands agent receives the recorded event, invalidated assumptions, active invalidated
plan, impacted/preserved segments, uncovered windows, and refreshed tool context. It proposes a
complete Plan B. `PlanValidator` checks Plan B against the updated scenario. If a Plan B draft is
invalid, the shared bounded draft-repair function may make at most three total Plan B proposals;
this inner repair does not apply another world-state event.

On success, validated Plan B becomes active and the case returns to `EXECUTING`, meaning a valid
plan is ready for later execution behavior. The case is never marked `RESOLVED`. On failure,
invalid Plan B is not activated; the invalidated Plan A remains observable as the active affected
plan and its previously valid snapshot remains in history.

```text
INITIAL PLAN REPAIR                 WORLD-STATE REPLANNING
invalid draft                       previously valid Plan A
unchanged world                     recorded external event
validator feedback                  authoritative state update + impact analysis
same planning cycle                 new Plan B planning cycle
        │                                      │
        └──── bounded validator repair ─────────┘
```

No persistence, approval interaction, external messaging/provider integration, API, UI, or
multi-agent behavior is included.
