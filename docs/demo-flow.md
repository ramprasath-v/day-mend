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
