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
