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

Steps 6–16 remain future milestones. No caregiver decline, invalidation, replanning, approval,
execution, or completion branch has been scripted or implemented.
