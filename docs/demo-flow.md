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

Steps 10–16 remain future milestones. Milestone 2 may report `requires_approval`, but it does not
request approval, execute actions, persist state, or mark the case `RESOLVED`.
