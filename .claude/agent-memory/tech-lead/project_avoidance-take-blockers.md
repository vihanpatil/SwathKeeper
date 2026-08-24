---
name: avoidance-take-blockers
description: The avoidance-with-real-detection take is GATE-CLEAR as of 2026-08-24 after THREE adversarial rounds (13 findings fixed); only the scipy image rebuild gates it — plus the frozen SAFETY_FINDING marker set and 6 ranked non-blocking open items, ADR-013 am. 13-17
metadata:
  type: project
---

The whole offline half of the avoidance-with-real-detection take landed 2026-08-24 (ADR-003 am. 8,
ADR-004 am. 1, ADR-009 am. 1, ADR-012 am. 2, ADR-013 am. 13-17). The new safety gate was reviewed
**three times**; every finding was fixed the same day, each pinned by a test proven RED against the
pre-fix file, and each re-verified by a reviewer who rebuilt the pre-fix code in a shadow tree rather
than re-running the author's tests.

**The call, so it does not get re-argued: the GATE no longer blocks the take.** What still gates it is
operational — the Docker image must be rebuilt for `python3-scipy` (multi-hour) and the in-container
scipy-1.8.0 transfer check must re-score the am. 7 clip to bit-identical boxes.

**Decision worth remembering because its tripwire is OWED, not built (ADR-013 am. 17):** the
ACKNOWLEDGED `SAFETY_FINDING.md` marker set is **FROZEN at the two historical logs** (2026-08-18,
2026-08-23). A marker turns a CPA breach into exit 0, and R4 is open — so an unbounded marker set
would make "add a file" the documented remedy for a red gate. A NEW breaching take is a FAILED take,
never acknowledged. **Round 4 (2026-08-24) made this a TWO-STEP contract in code:** exit 0 needs the
`SAFETY_FINDING.md` marker AND the log stem pinned in `ACKNOWLEDGED_BREACH_STEMS` in
`scripts/check_live_flight_log.py`; either half alone is INVALID and the message names the missing
half. A marker alone was rejected because the operator who produced the red gate can author the
remedy unreviewed; the pinned stem forces a diff on the safety gate a reviewer already reads.
Still owed: the `AVOIDANCE_REAL_DETECTION.md` §6 row that instructs adding a marker without the
second step.

**Shapes worth carrying forward (the fixes, not their diffs):**
- A safety bound gets DERIVED from the physics it protects, never picked as a constant — and then
  MEASURED, never converted from a nominal rate: the freeze debit is now the hidden sim-time window
  read off the flight's own stamps × the fastest bird in the config.
- A discretised safety number must bias conservative on EVERY axis: `gt_cpa_m` is point-to-segment
  over the drone polyline AND over each landed bird pose's own in-effect window. Closing one axis
  left the faster body unscored for a whole round.
- Every rate needs its own denominator; two axes need two (`truth coverage K/N ticks` reads 100 %
  while bird poses go unscored — hence `truth_poses_scored/total`).
- Widen a fix past the reported instance when the neighbouring path has the identical hole.
- When a fix cannot reach as far as the prose did, narrow the CLAIM and print the number instead of
  building the missing feature (the HOLD is exempt by construction; its clearance is now logged as
  ungated CONTEXT so the first take quantifies R4's gap).
- Executor fails OPEN on missing data, the offline gate fails CLOSED on it. Say which is which.

**Open after round 3, ranked, none blocking** (full text + numbers in am. 17): R4 escape geometry
(cut, unchanged — book it on the first take's hold-clearance line, do not re-fly for it);
`MIN_DETECT_RATE = 0.90` unmeasured in the air; the clock gate's false-positive rate unpriced and
un-acknowledgeable by design (0.428 s of hidden sim time crosses the whole bar, and `/clock` is read
by a subprocess thread on a box that has starved twice) — it needs a row in the runbook's §6 booking
table; the hold CONTEXT note has no denominator and vanishes silently if the field is dropped; two
stated residual assumptions in the freeze bound (trailing frozen run, a recovering-but-lagging
reader). `docs/ROADMAP.md` was reconciled to am. 13-17 in round 4.

**How to apply:** before scheduling the flight, verify the image rebuild happened — read the code and
the preflight, not this file. The expectation stays PRE-REGISTERED in ADR-013 am. 13: because R4 is
deliberately cut-to-open, the flight may honestly FAIL its own GT-CPA gate — that ranks R4 next, it
is not a wasted take, and it is NOT acknowledged with a marker.
Related: [[adr-log-must-track-the-gate]], [[week6-detection-seam-open-questions]],
[[adr006-avoidance-executor]], [[scenario-fixtures-are-open-loop]], [[adr003-ndvi-detection]].
