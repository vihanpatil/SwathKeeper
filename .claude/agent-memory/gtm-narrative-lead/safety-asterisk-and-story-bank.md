---
name: safety-asterisk-and-story-bank
description: The strongest SwathKeeper interview/pitch stories (safety asterisk, mount forensics, ledger honesty fix, self-catching gates) and which audience each one lands with
metadata:
  type: project
---

The stories that sell this portfolio, ranked. Each is "a gate that caught itself failing" — which
beats any architecture answer.

**0. THE PRE-REGISTERED NEGATIVE RESULT (new 2026-08-25, now the strongest story in the bank).**
The flagship flight — first time the avoidance loop engaged on a bird the drone *detected itself* —
**failed its own safety gate**, and that outcome had been **written down in the runbook before the
flight** (`AVOIDANCE_REAL_DETECTION.md` §7: "this flight may honestly FAIL its own GT-CPA gate…
written here *before* the flight so it cannot be reinterpreted afterwards"). `gt_cpa_m` 0.0067 m vs
a 3.00 m bar; take INVALID, exit 1. **The gate that failed it was built the day before the flight,
by the same process that predicted the failure** — and torn apart adversarially five times first.
The record was kept per contract: marker file written, pin deliberately NOT added, so nobody can
green their own bird strike.
So-what, three ways: (a) *pre-registration* — an engineer who writes the failure condition down
first is not fooling themselves; (b) *a safety gate you only trust when green is not a safety gate* —
this one cost the project its flagship take on day one, which is the whole point; (c) *a negative
result that ranks the next fix* is a deliverable, not a wasted week.
**Never spin this as a pass. Never soften "breach". The honesty IS the pitch.**

**0b. The finding underneath it — geometry, not the control law.** The obvious read is "the dodge
was too slow." The measurement says otherwise: first detection arrived **on the CPA tick** — sensor
lead 0.175 s, policy lead 0.000 s — because the nadir camera images ~4 % of the threat cylinder at
that depth. The detector converted every opportunity it got (2 boxes on the only 2 bird-visible
frames of 3310) and `eval/score.py` *still* refused to score it: EVIDENCE INSUFFICIENT, 1 of 3 birds
visible. So-what: **no escape geometry can buy warning time the sensor never had** — the fix is a
sensing/speed decision, and diagnosing that before building R4 saved building the wrong thing.
It also surfaced a real product tension (nadir mount = best-ever NDVI tree gate vs forward tilt =
lead time) that was **escalated as a decision, not guessed** — good "knows what isn't theirs" story.

**1. The safety asterisk (still the strongest *historical* paragraph).** The avoidance loop vetted
19/19 dodge *setpoints* against a 3.00 m bird bar and every gate was green — then a gate added
afterward measured the distance actually *flown*: CPA 0.0518 m and 0.0597 m on two independent
flights, ~58× inside the bar. "Vetting setpoints" had been silently reading as a claim about
separation. Both logs stay as ACKNOWLEDGED SAFETY FINDINGS (recorded history, NOT passing flights),
and acknowledging one costs **two halves** — a marker file *and* a stem pinned in
`ACKNOWLEDGED_BREACH_STEMS`, a reviewed diff on the gate — so an operator cannot green their own
bird strike in one file. The next flight is **pre-registered as possibly failing its own gate**,
because that failure is the measurement that ranks the next fix (R4, escape geometry).
**Never soften "breach", never let ACKNOWLEDGED read as "passed", never move it to a footnote.**

**2. ADR-007 am. 5 — mount forensics, and it happened AGAIN in a different costume.** Every
value-gate measured real values and PASSED while the camera faced the horizon upside down since
authoring (Gazebo cameras look along +X). Fix shipped with the gate that makes the bug class
impossible: `scripts/verify_mount_geometry.sh`, 2.2 px. **Second instance, 2026-08-25:** a green
**99.92 %** detector-rate gate sat on top of a flight where the detector saw a bird on **2 of 1301
frames** — correct pixels, correct pointing, every counter in range, and the vehicle still flew
through a bird. So-what (strongest one-liner in the deck): **a gate that measures values cannot see
geometry** — every geometry assumption needs its own geometry gate. Two independent instances makes
it a pattern I recognised, not an anecdote.

**3. Coverage-ledger honesty fix.** A commanded dodge setpoint was briefly recorded as *flown*,
understating debt by up to 32 cells/scenario — a never-visited cell could finalize COVERED. Fixed,
regression-pinned, logs honestly regenerated the same day.

**4. Evidence-floor guards.** `eval/score.py`'s zero-denominator ADOPT bug;
`check_tree_positions.py`'s "PASS (vacuous)"; the CI flight-log step that printed SKIP…PASS having
validated nothing and now hard-fails on zero matched files; QA's 2026-08-24 adversarial pass finding
six ways the safety gate could print a false PASS (a 0.8 s frozen clock = 5.6 m of bird motion
reported a 0.0000 m strike as a 3.5000 m PASS), all six closed before any flight was booked.

**Audience mapping (hypothesis, not yet validated against real interviews):**
- **Autonomy/robotics** — lead with story 0 (pre-registered failure, gate-vs-control-law separation,
  a gate that costs the flagship take), then the reactive loop, then story 1. Safety-critical teams
  buy the willingness to publish a failed flight faster than they buy a green number.
- **Applied ML / perception** — lead with story 0b: the detector scored 1.000/1.000 and the harness
  **refused to call it evidence** (1 of 3 birds visible). Then ADR-003 criterion 3 — a decision
  reopened, re-measured on the real render, closed with numbers; classical blob detector ADOPTED
  because no learned model beat it on the same harness. Then story 4 (eval rigor). The
  1-micrometre live↔offline equivalence across two scipy versions is the "I don't trust a port
  until I've diffed it" proof point.
- **Ag-tech** — lead with the operator assumption (trees are a *known* pre-surveyed geofence, so the
  hard problem is the obstacle nobody surveyed) and coverage debt as an operator-facing guarantee;
  then the sensing-ROI framing story 0b hands you for free: one nadir NDVI camera sees ~4 % of the
  threat volume, which is the concrete business case for a second sensor. Numbers for the
  NDVI-vs-RGB delta itself still **do not exist** — say so.

Numbers live in [[headline-metrics]]; bullets in [[resume-bullet-bank]]; framing rules in
[[narrative-guardrails]].
