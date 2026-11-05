---
name: adr-log-must-track-the-gate
description: A fix that changes a gate's behaviour is not done until the ADR text describing that gate changes in the same session — the log went stale on the SAME gate two rounds running (2026-08-24)
metadata:
  type: project
---

**Rule: a fix that changes a gate's behaviour is not done until the ADR text describing that gate is
corrected in the same session.**

**Why:** on 2026-08-24 `docs/DECISIONS.md` went stale on the *same* gate two adversarial rounds in a
row. Round 2 deleted `MAX_FROZEN_TICKS` and the log kept prescribing it; round 3 replaced the
nominal-rate freeze bound and the log kept stating it as `(N−1)/CONTROL_HZ`, kept quoting a
`gt_cpa_gated_m` print that had been removed, and kept prescribing a fix using a symbol that no
longer existed — while the test suite asserted those symbols were ABSENT from the checker. The doc
and the tests contradicted each other inside the same repo, which is the same family of defect as a
green gate that measured nothing: a future session would have re-implemented the removed assumption
because the log told it to.

**Third instance, 2026-08-25 — same family, opposite direction: the TEST contradicted the RUNBOOK.**
`test_every_breaching_committed_log_has_BOTH_halves_of_an_acknowledgement` demands the
`ACKNOWLEDGED_BREACH_STEMS` pin whenever a `SAFETY_FINDING.md` marker exists — which is exactly the
state runbook §6a *requires* after a new breach (marker, no pin, INVALID). Executing the contract
correctly turned the suite red on the first real breach. **So the rule generalises: whenever a
contract is written in prose AND enforced in a test, run the suite in the state the prose prescribes
before calling the contract done.** Nobody had ever executed the marker-without-pin state.

**How to apply:**
- Amendments written **today and still uncommitted** are corrected **IN PLACE**. Once committed,
  `docs/DECISIONS.md` is APPEND-ONLY and the identical correction becomes a new dated amendment.
- Never delete the record of what a round FOUND. Mark superseded numbers as superseded — "the bound
  was sized wrong twice, and here is each wrong denominator" is the interview answer.
- When a residual list is closed by a later round, give every item its disposition in place
  (→ CLOSED / → STILL OPEN) rather than leaving a to-do that outlived its fix.
- Check for the contradiction directly: grep the ADR log for the symbols the tests assert are absent
  from the source.
Related: [[avoidance-take-blockers]].
