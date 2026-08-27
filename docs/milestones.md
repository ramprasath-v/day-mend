# DayMend Milestones

## Milestone 1 — Core Strands planning

**Goal:** A nanny cancellation causes the agent to gather context through tools, produce a
structured Plan A, and submit it to deterministic validation.

**Status:** Complete. All offline tests and quality checks pass. Live Nova Pro execution invoked
all five tools once, used structured deterministic findings to repair two invalid proposals in
the same agent conversation, and reached a valid third proposal. The final plan covered the full
window, respected availability and calendars, and retained the correct autonomy-threshold
behavior.

**Exit criterion:** An automated test or repeatable local demonstration shows real Strands
reasoning and tool calls producing a typed `RecoveryPlan`, and the deterministic validator
accepts a complete valid plan and rejects representative hard-constraint violations.

Initial validation repair is limited to three proposals while world state is unchanged. It does
not include Milestone 2 invalidation or replanning after an external event.

## Milestone 2 — Plan invalidation and replanning

**Goal:** A caregiver decline invalidates the relevant assumption, recomputes the uncovered
segment, and causes the agent to replan from updated world state.

**Exit criterion:** A recorded external decline updates the case without a hardcoded branch,
preserves still-valid plan portions, and produces a newly validated plan for the remaining gap.

## Milestone 3 — Persistence + autonomy + approval/resume

**Goal:** Persist `RecoveryCase` state, apply family policy thresholds, pause for approval, and
resume the same case after an approve or reject decision.

**Exit criterion:** A case survives process restart, an over-threshold action cannot execute
without approval, and both approval outcomes resume the same case with an auditable event trail.

## Milestone 4 — FastAPI

**Goal:** Expose the real recovery workflow through APIs.

**Exit criterion:** Documented FastAPI endpoints can create/read a recovery case, accept
external events and approval decisions, advance the actual workflow, and pass API tests.

## Milestone 5 — Angular recovery UI

**Goal:** Show the disruption, recovery progress, plan changes, approval decision, and resolved
outcome without a chatbot UI.

**Exit criterion:** A parent can follow and act on the primary demo scenario end to end in a
workflow/status interface that accurately reflects backend state.

## Milestone 6 — AWS deployment + observability

**Goal:** Use Bedrock, DynamoDB, CloudWatch, deployment infrastructure, AgentCore if practical,
and one useful real external integration.

**Exit criterion:** The primary scenario runs in a deployed environment with persistent state,
searchable logs/metrics, documented operations, and at least one verified external integration;
an explicit decision records whether AgentCore is used.

## Milestone 7 — Submission polish

**Goal:** Prepare the architecture diagram, README, tests, public repository, license, demo
video, and Devpost submission.

**Exit criterion:** Submission materials accurately describe the verified build, the public
repository is runnable from its documentation, the demo video shows the primary scenario, and
all event requirements have been checked before submission.
