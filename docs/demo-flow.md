# DayMend Primary Demo Flow

DayMend has one primary demonstration scenario:

1. At 7:02 AM, the nanny reports that she is sick.
2. The family's expected childcare coverage from 8:00 AM to 4:00 PM disappears.
3. DayMend gathers parent calendar, trusted caregiver, availability, family policy, and cost
   context through tools.
4. The Recovery Agent builds a structured Plan A.
5. Deterministic validation confirms that Plan A satisfies the hard constraints.
6. A caregiver later declines.
7. That external response updates the world state and invalidates the corresponding plan
   assumption.
8. DayMend preserves still-valid portions of Plan A where possible.
9. It recomputes the uncovered segment and replans only the recovery work that remains.
10. The viable paid option costs more than the family's automatic-spend threshold.
11. The parent receives one meaningful approval request.
12. The parent approves the expense.
13. DayMend records the decision and resumes the same `RecoveryCase`.
14. The approved actions complete and their outcomes are observed.
15. A final deterministic check confirms complete childcare coverage.
16. Only then does the case become `RESOLVED`.

The caregiver decline is an external state change, not a scripted “next demo screen.” No code
should check for this named scenario and select a predetermined backup. The normal invalidation,
gap calculation, reasoning, validation, approval, execution, and verification path must drive
the result.

## Milestone 1 boundary

The current implementation covers steps 1–5 only: the nanny-cancellation fixture, agent-directed
context gathering, bounded initial-plan repair, and deterministic acceptance of Plan A. Fixture
facts are synthetic, while Strands tool selection and plan generation are real when Bedrock
credentials are available. Context is gathered once. An invalid draft receives structured
validator findings in the same agent conversation and may be repaired, with a hard cap of three
planning attempts.

A real Nova Pro smoke invoked all five tools and reached a valid plan on attempt 3. Attempts 1
and 2 were rejected for separate missing movable-calendar changes. The final plan covered
08:00–16:00, respected caregiver availability and critical commitments, included both required
calendar changes, cost `$92.00` deterministically, and reported `requires_approval=true` against
the `$30` automatic-spend threshold.

This correction loop does not process external responses: it repairs an initial proposal that
was never valid while world state is unchanged. It is not the caregiver-decline replanning shown
in steps 6–9.

## Milestone 2 boundary

The current Milestone 2 implementation covers steps 6–9 as a real state transition rather than
a scripted branch. A `CAREGIVER_DECLINED` event records Grandma's response and affected window.
Deterministic code removes that window from authoritative availability, invalidates the matching
Plan A assumption, identifies the Grandma segment as impacted, exposes all other segments as
preserved, and stores valid Plan A in case history. The same Recovery Agent refreshes tools from
the updated state and proposes Plan B; deterministic validation and the existing bounded draft
repair apply before Plan B can become active.

The event says only that Grandma declined. No application branch selects a particular
replacement caregiver. The agent reasons from updated tools and the validator rejects any Plan B
that assigns Grandma during the declined window.

This differs from Milestone 1 repair: Plan A was already valid, and replanning starts only after
the event changes authoritative world state. Any invalid Plan B draft is then corrected by the
inner Milestone 1-style validation loop without applying another external event.

Milestone 2 stops before steps 10–16. It may report `requires_approval`, but its own orchestration
does not request approval, execute actions, persist state, or mark the case `RESOLVED`.

## Milestone 3 boundary

Milestone 3 covers steps 10–16 with persistence and simulated integrations. A valid Plan B is
still feasible when its deterministic `$92` cost exceeds the `$30` automatic-spend threshold;
the autonomy gate creates a plan-specific pending request, sets `APPROVAL_REQUIRED`, and persists
the whole case. A new service instance reloads it, applies the human decision to the same case ID,
and resumes without asking for context again.

Approval permits explicit simulated calendar updates and caregiver reservations. It does not
itself mean execution succeeded. After all actions return success, `CompletionVerifier`
revalidates the active plan against current world state, checks approval/action/dependency
history, and only then persists `RESOLVED`. A final reload proves Plan A, Plan B, Grandma's
decline, invalidated assumption, approval, execution, and completion history survived.

Rejecting the current request records a new external decision fact, executes nothing, and moves
the same case to `REPLANNING`; offline tests cover this path. Real provider integrations and the
rejection-driven alternative-plan live demo remain later work.

The verified live Milestone 3 harness used `daymend-recovery-cases-dev` and a unique case ID. It
reloaded `APPROVAL_REQUIRED`, approved the exact active Plan B, completed four simulated actions,
verified completion, and reloaded the same case as `RESOLVED` at version 4. The harness reuses the
tested Milestone 2 aggregate so that storage/approval evidence is independent from fresh model
variance; the separate Milestone 2 smoke remains the real agent/replanning proof.

## Milestone 4 boundary

The entire primary flow is now available over HTTP. `POST /recoveries` records the disruption,
invokes the existing initial-planning workflow, persists Plan A, and returns the new case ID.
`GET /recoveries/{id}` returns a frontend-safe snapshot. A caregiver response sent to the event
endpoint follows the same authoritative invalidation and replanning path from Milestone 2, then
the existing autonomy gate exposes any pending approval. The approval endpoint uses Milestone 3
decision, execution, and completion services; it does not reproduce those rules in a controller.

The offline API demo substitutes a deterministic planning boundary only. Its real deterministic
services preserve the case ID from `WAITING_FOR_RESPONSE` through `APPROVAL_REQUIRED`, four
successful actions, and `RESOLVED`. The live API smoke additionally proved the real Nova Pro and
DynamoDB path with case `d436c360-bda5-4625-9521-67d8932f87b0`: Grandma's response invalidated
one Plan A assumption, Nova produced valid `plan_B`, approval resumed the same persisted case,
and completion reached `RESOLVED` at version 6.

FastAPI does not decide plans, validity, approval requirements, or completion. There is no UI,
authentication, paid-provider search, real calendar/messaging integration, or deployment work in
this milestone.

## Milestone 5 boundary

The primary story is now visible in one Angular recovery screen. Before disruption, it shows the
normal 8:00 AM–4:00 PM nanny window. The demo control sends the real create request and displays a
loading explanation while Nova plans. Plan A renders as friendly coverage rows rather than entity
IDs. The Grandma control sends the real `CAREGIVER_DECLINED` event; Angular changes no recovery
state itself.

After replanning, the UI uses the persisted previous plan and invalidated assumptions to mark
Grandma's broken window and count Plan A segments that remained valid. The approval card uses the
backend's pending request, deterministic cost, and persisted `$30` policy limit. Approve/reject
commands include the current optimistic version. Only returned execution actions and completion
state can produce completed progress and the final “Day recovered” view.

The live browser smoke resolved case `d8c9ebdb-b1ac-423b-b6e3-67e20eb8fc92`. Nova created Plan A,
Grandma's decline invalidated one assumption, and Nova produced `plan_B_v2`. That fresh model run
selected a valid `$48` employer-backup plan rather than the offline `$92` mixed-care example. The
plan still crossed the `$30` autonomy limit, so the UI presented one real approval. Approval
resumed the same case, both required actions succeeded, deterministic completion passed, and the
UI rendered `RESOLVED` at version 6. Model variability is reported rather than hidden or overridden.

## Milestone 6 hosted boundary

The public demo at <https://d28bm0qb8qheeh.cloudfront.net> completed the full browser story on
case `e8cc73fe-6556-427c-a523-fb40151c3bfa`. Nova Pro created `$92` Plan A
`recovery_plan_2`; Grandma's real event invalidated three assumptions and preserved five Plan A
segments; Nova produced valid `$114` Plan B `recovery_plan_4`; and deterministic policy paused at
the `$30` automatic-spend boundary. The parent approved, all seven simulated actions succeeded,
and deterministic completion set `RESOLVED` at version 6. Reloading the entire CloudFront page
restored that same state from `daymend-demo-recovery-cases`.

Observed browser durations were approximately 24 seconds for initial planning, 51 seconds for
replanning, and 3.3 seconds for approval/execution/completion. A second public API run on the
observability-enabled revision recorded real Nova Pro latency, all five Strands tools, validation
attempts, invalidation, approval, actions, and resolution as structured JSON in CloudWatch. Costs
and plan identifiers are evidence from these runs, not fixture branches or promised future
outputs.

## Milestone 6.5A local multi-agent boundary

The opt-in local flow preserves the same parent-visible story while separating two reasoning
responsibilities. The Recovery Orchestrator creates a factual, transient planning brief for the
initial disruption and another brief after deterministic caregiver-decline invalidation. The
Constraint Planner constructs Plan A/Plan B and receives any validator repair findings directly.
All later autonomy, persistence, simulated execution, and completion behavior is unchanged.

The complete live Nova Pro proof used case
`daymend-multi-dda7ca5c-3b15-47ce-bc56-48699635e332`. Plan A passed on proposal 2 at `$92`.
Grandma's decline recorded event
`daymend-multi-dda7ca5c-3b15-47ce-bc56-48699635e332:grandma-declined`, invalidated one matching
assumption, and preserved five segments. The replanning brief identified the recorded event,
active plan/case state, affected window, preserved segments, and Grandma exclusion. Plan B passed
on proposal 3 at `$114`; deterministic policy requested and recorded approval. Six simulated
actions succeeded, final coverage verification passed, and the same case reached `RESOLVED` at
version 6. This path is not deployed and the single-agent architecture remains the default.

## Milestone 6.5B local research-agent boundary

The dedicated research fixture begins with a nanny unavailable from 08:00–16:00. Grandma can
cover 08:00–10:00 and a known backup sitter can cover 12:00–16:00, while both parents have
critical commitments from 10:00–12:00. Deterministic union-of-availability analysis therefore
establishes a real two-hour gap without checking any caregiver name or wasting three impossible
Planner proposals.

The Recovery Orchestrator receives that authoritative need and requests research. The Backup
Care Research Agent calls one read-only tool over six synthetic records. Deterministic rules
remove one unavailable candidate, one candidate without the required background check, and one
whose age range does not cover the child. Nova Pro compares all three remaining options and
returns this grounded ranking:

1. `harbor_nanny_coop` — recommended for the balance of 4.9 rating, `$27/hour`, and 2.2 miles.
2. `willow_family_care` — closer at 1.2 miles but more expensive at `$31/hour` and fewer reviews.
3. `bright_start_agency` — largest review history and exact-window availability, but farther away
   with a `$58` flat rate.

The Planner sees only the recommended provider added to authoritative caregiver context and
constructs the entire day. In the controlled live run, proposal 1 covered the full window and
passed deterministic validation with no issue codes. The `$142` total includes known afternoon
care as well as researched care. Policy independently required one approval because the plan was
both above the `$30` automatic threshold and used unfamiliar paid care. The approval referenced
the system ID
`daymend-research-f98e0e7b-f47f-45d3-8485-9627c77bc9ef:plan:1`.

All three simulated caregiver actions succeeded. `CompletionVerifier` rebuilt the researched
candidate from internal case context, revalidated coverage and authorization, and set the same
case to `RESOLVED` at version 5. The lifecycle used seven Bedrock cycles and took 53,952 ms:
7,110 ms Orchestrator, 29,810 ms Research, and 16,650 ms Planner. No raw prompts or hidden
reasoning are recorded. There is no real provider marketplace, search scraping, booking, payment,
frontend change, production deployment change, or AgentCore implementation.
