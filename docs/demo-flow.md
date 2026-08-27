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

