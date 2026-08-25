---
name: safety-asterisk-and-story-bank
description: The strongest SwathKeeper interview/pitch stories (safety asterisk, mount forensics, ledger honesty fix, self-catching gates) and which audience each one lands with
metadata:
  type: project
---

The stories that sell this portfolio, ranked. Each is "a gate that caught itself failing" — which
beats any architecture answer.

**1. The safety asterisk (the single strongest paragraph available).** The avoidance loop vetted
19/19 dodge *setpoints* against a 3.00 m bird bar and every gate was green — then a gate added
afterward measured the distance actually *flown*: CPA 0.0518 m and 0.0597 m on two independent
flights, ~58× inside the bar. "Vetting setpoints" had been silently reading as a claim about
separation. Both logs stay as ACKNOWLEDGED SAFETY FINDINGS (recorded history, NOT passing flights),
and acknowledging one costs **two halves** — a marker file *and* a stem pinned in
`ACKNOWLEDGED_BREACH_STEMS`, a reviewed diff on the gate — so an operator cannot green their own
bird strike in one file. The next flight is **pre-registered as possibly failing its own gate**,
because that failure is the measurement that ranks the next fix (R4, escape geometry).
**Never soften "breach", never let ACKNOWLEDGED read as "passed", never move it to a footnote.**

**2. ADR-007 am. 5 — mount forensics.** Every value-gate measured real values and PASSED while the
camera faced the horizon upside down since authoring (Gazebo cameras look along +X). Fix shipped
with the gate that makes the bug class impossible: `scripts/verify_mount_geometry.sh`, 2.2 px.
So-what: value gates can't see geometry faults; each fix must ship its own gate.

**3. Coverage-ledger honesty fix.** A commanded dodge setpoint was briefly recorded as *flown*,
understating debt by up to 32 cells/scenario — a never-visited cell could finalize COVERED. Fixed,
regression-pinned, logs honestly regenerated the same day.

**4. Evidence-floor guards.** `eval/score.py`'s zero-denominator ADOPT bug;
`check_tree_positions.py`'s "PASS (vacuous)"; the CI flight-log step that printed SKIP…PASS having
validated nothing and now hard-fails on zero matched files; QA's 2026-08-24 adversarial pass finding
six ways the safety gate could print a false PASS (a 0.8 s frozen clock = 5.6 m of bird motion
reported a 0.0000 m strike as a 3.5000 m PASS), all six closed before any flight was booked.

**Audience mapping (hypothesis, not yet validated against real interviews):**
- **Autonomy/robotics** — lead with the reactive loop + story 1 (safety verification, pre-registered
  failure, gate-vs-control-law separation).
- **Applied ML / perception** — lead with ADR-003 criterion 3: a decision reopened, re-measured on
  the real render, closed with numbers; classical blob detector ADOPTED because no learned model
  beat it on the same harness. Then story 4 (eval rigor).
- **Ag-tech** — lead with the operator assumption (trees are a *known* pre-surveyed geofence, so the
  hard problem is the obstacle nobody surveyed) and coverage debt as an operator-facing guarantee;
  sensor-ROI comparison arm is contract-locked but has **no number yet** — say so.

Numbers live in [[headline-metrics]]; framing rules in [[narrative-guardrails]].
