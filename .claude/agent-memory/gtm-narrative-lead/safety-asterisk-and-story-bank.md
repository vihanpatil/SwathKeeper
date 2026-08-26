---
name: safety-asterisk-and-story-bank
description: The strongest SwathKeeper interview/pitch stories (pre-registered failure, the no-safe-speed tripwire, retired comparison arm, safety asterisk, mount forensics, self-catching gates) and which audience each lands with
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

**0c. THE TRIPWIRE FIRED — the measurement that cancelled a flight and rewrote the roadmap (new
2026-08-26; this is now the *ending* the story needed).** The pre-registered failure (story 0) ranked
"escape geometry" as the next fix. Instead of building it, the next session replayed all three
committed flights through a jerk/accel-limited point-mass model of the autopilot and asked the
question directly — is there any mission speed at which this sensor geometry clears the 3 m bar?
**81 cells, answer: none.** The intruder brings its own 6.0 m/s of closing speed, capping warning at
**0.41 s even from a hover**, against a **1.25 s** cheapest physical escape; nadir sees 2.48 m ahead
and would need 17.8-38.7 m. A tripwire written *before* the sweep then fired on its own terms: the
second forward-facing sensor was promoted from growth path to scope, the tilt stayed rejected, and
the pre-flight abort gate now refuses every speed the vehicle actually flies.
So-what: (a) **the roadmap changed on a number, not an opinion** — and the number came from ~50
lines of offline replay instead of a booked sim session; (b) it **retired R4 before a line of it was
built** (the 0° reversal never resolves at any lead × plant — candidate ordering was never the
binding constraint); (c) the one-liner that closes any interview answer: *"the system found its own
sensor's limit and refused to fly what it can't pass."*
Careful: the replay is **not a gate** and cannot be wired into CI, and its plant fit (1.05 m/s²) is
ESTIMATED from one admissible axis of one flight. Say so.

**0d. I killed my own comparison arm by measuring that it couldn't answer the question (criterion 2,
CLOSED 2026-08-26).** The NDVI-vs-RGB arm had been open for weeks. The forced-binary study
(4,566 frames / 1.40 Gpx / 16,686 measured bird pixels) found the decisive fact: **the RGB R channel
IS the NDVI Red band, bit-for-bit** — same band, aperture, mount, FOV, clock. It never was a second
sensor, so it cannot answer what a second sensor buys. RETIRE-ARM; the budget moved to the forward
sensor. Two things travel with it: the old "RGB scores 1.000 FNR" caveat was **wrong about itself**
(the feature was wrong, not the sign — the real RGB signal is chromatic), and at its honest ceiling
RGB **matches the adopted detector's safety numbers exactly**, losing only on precision (3.1× on the
adopted clip, 27× in the air) to a trunk-vs-intruder material collision that only the thermal band
separates. **ADOPT is now re-confirmed against a *working* rival at gap +0.000** — a stronger verdict
than the one it replaced.
So-what: killing an experiment on evidence is a senior move; "we ran the study and retired the arm"
beats both "we ran the study" and "it's on the backlog". Best applied-ML story after 0b.

**0e. The estimator I demoted was better than I said (3.3 mm), and I published the correction.**
The monocular apparent-size range estimator was demoted from gate to labelled check partly on a
"20 cm disagreement with ground truth." The 2026-08-26 segment-geometry fix showed that
disagreement was **the gate's geometry, not the estimator**: it actually agrees with ground truth at
closest approach to **3.3 mm** (`detection_cpa_m` 0.2096 → 0.0035; error −0.2028 → +0.0033).
So-what: **right call, wrong reason — both recorded.** The demotion still stands on its load-bearing
leg (a miss at CPA produces no detection at all, so detection-CPA can never be a gate), and the
citation that flattered the decision was corrected in the log rather than quietly left. Interviewers
probe for exactly this: can you tell which of your reasons was actually doing the work?

**0f. A fix that was never back-ported let a direct hit read as 7 m of clearance.** The segment-vs-
vertex CPA fix landed in the new schema-2 path and was **never applied to the legacy
`closest_approach()`** that scores pre-seam logs and the scenario fixtures. Found by QA comparing the
two geometries **on the same bytes**. `cov_bird_at_turnaround` — the one fixture that "passed" the
bar — was a fly-through reading **7.0000 m**; fixed red-first to **0.0000 m**. Both historical
breaches deepened (0.0597 → 0.0393, 0.0518 → 0.0391) with verdict lines byte-identical, and a
property test now pins the two implementations to agree on a deliberate fly-through so they cannot
diverge again.
So-what: **two implementations of one safety concept is the bug**; the durable fix is the property
test that forbids them from disagreeing, not the six lines of geometry. And every number the fix
produced was *worse* — published anyway.

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
- **Autonomy/robotics** (the chosen primary audience, 2026-08-26) — lead with **0 → 0b → 0c as one
  three-beat arc**: pre-registered failure, diagnosed as geometry not control law, then the offline
  measurement that cancelled the next flight and rewrote the roadmap. That arc has a *conclusion*,
  which the failure alone did not. Then the reactive loop + coverage debt, then story 1.
  Safety-critical teams buy the willingness to publish a failed flight faster than a green number.
- **Applied ML / perception** — lead with story 0b: the detector scored 1.000/1.000 and the harness
  **refused to call it evidence** (1 of 3 birds visible). Then **0d** (criterion 2 retired on the
  band-identity measurement; ADOPT re-confirmed at gap +0.000 against a working rival) and ADR-003
  criterion 3 — a decision reopened, re-measured on the real render, closed with numbers; classical
  blob detector ADOPTED because no learned model beat it on the same harness. Then story 4 (eval
  rigor) and **0e** (the estimator I demoted was better than I said). The 1-micrometre live↔offline
  equivalence across two scipy versions is the "I don't trust a port until I've diffed it" proof.
- **Ag-tech** — lead with the operator assumption (trees are a *known* pre-surveyed geofence, so the
  hard problem is the obstacle nobody surveyed) and coverage debt as an operator-facing guarantee
  (720 covered / 0 debt; 116 at-risk cells recovered across 4 diverts). Then the sensing-ROI case,
  now **quantified** by 0c: one nadir camera sees ~4 % of the threat volume and gives 0.41 s of
  warning at best, against 17.8-38.7 m of forward horizon required — that is the second-sensor
  business case in one sentence. Also honest here: the swath over-claim (7.5 m prose vs 6.886 m from
  `camera_info`, **8.19 %** of area) was caught before any dashboard quoted coverage. Still **no
  sensor-diversity delta exists** — the arm shared the primary's band bit-for-bit; say so.

Numbers live in [[headline-metrics]]; bullets in [[resume-bullet-bank]]; framing rules in
[[narrative-guardrails]].
