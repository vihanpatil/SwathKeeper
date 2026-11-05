---
name: scenario-fixtures-are-open-loop
description: eval/scenarios/*/flight_log.json are OPEN-LOOP stimulus fixtures — their CPA is a scenario parameter, so the CPA gate is scoped to live logs only (ADR-013 am. 16)
metadata:
  type: project
---

`eval/scenarios/*/flight_log.json` are **open-loop** fixtures: `generate_flight_logs.py` prescribes
the drone's `DroneState` from `nominal_path()` every tick and never feeds the executor's commanded
setpoint back in. So `flown_path_enu` is byte-identical to the scripted lawnmower, and their closest
approach to the scripted bird (0.00 / 7.00 / 1.00 / 1.00 m) is a **scenario parameter** — the bird is
parked on the lane to force the dodge — not a flown outcome.

**Why:** decided 2026-08-24 (ADR-013 amendment 16) after a QA finding reported three of the four
fixtures "in CPA breach" and proposed adding them to CI's `check_live_flight_log.py` line.
Regenerating all four under the newly landed R2/R3 control law moved commanded setpoints up to
17.205 m and left every CPA bit-identical — a number a 17 m control-law change cannot move by 1 nm is
not measuring the control law. Filing them as `SAFETY_FINDING.md` would also dilute the marker
channel carrying the two real historical breaches (0.0597 m / 0.0518 m).

**How to apply:** never point the CPA / ground-truth-CPA gate at `eval/scenarios/`; those fixtures are
gated by the regenerate+diff reproducibility step and `test_safety_scenarios_pending.py`
(ledger P1-P4, no-lying-covered, tree band, field polygon). The CPA gate belongs to
`eval/results/live_flight_log_*.json`, which are **committed** (`.gitignore` re-includes them) and are
what CI actually scores. If `tests/test_ci_evidence_gate.py`'s open-loop test ever goes red, the
generator has become closed-loop and this decision must be re-read before CI changes. Related open
gap: **no scenario in the repo exercises separation at all** — that is the R4 (escape geometry) hole,
cut from v1; a green scenario suite is not evidence of clearance. See
[[project_avoidance-take-blockers]].
