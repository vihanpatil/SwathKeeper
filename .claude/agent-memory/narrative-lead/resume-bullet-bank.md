---
name: resume-bullet-bank
description: Drafted, source-traced SwathKeeper resume bullets (impact by approach) as of 2026-08-25, plus the claims that are explicitly NOT earned yet
metadata:
  type: project
---

Bullets in `<impact/metric> by <technical approach>` form. Every number re-verify against
[[headline-metrics]] before use — none of these has shipped to a resume yet.

## Earned by the 2026-08-25 first real-detection avoidance flight

- **Closed a perception→avoidance loop in the air on a self-detected obstacle** by wiring an adopted
  NDVI blob detector onto an ArduPilot/ROS 2 avoidance node under a stamped-detection contract
  (staleness gate, apparent-size ranging — never ground-plane projection, which is fail-dangerous at
  altitude); offline replay reproduced the flight's own logged obstacle positions to **1 µm** across
  two SciPy versions, proving the port neutral before it flew.
- **Caught a 0.0067 m closest-approach breach against a 3.00 m safety bar on the project's flagship
  flight** by building the ground-truth CPA gate the day before the take — polyline lower bound on
  both the vehicle and obstacle axes, plus a frozen-clock debit priced in metres of obstacle motion —
  and by **pre-registering the possible failure in writing before flying**. The take stands INVALID;
  acknowledging a breach costs two independent halves (marker file + reviewed source pin) so no
  operator can green their own strike in one file.
- **Diagnosed a safety failure as a sensing-geometry limit rather than a control-law one** by
  measuring warning time end to end: **0.175 s** sensor lead, **0.000 s** policy lead, with the nadir
  camera imaging only **~4 %** of the 12 m threat cylinder at the encounter's depth — redirecting the
  next fix away from escape geometry, which alone could not have helped.
- **Kept a 1.000-precision / 1.000-recall detector result from being reported as a win** by an
  evidence floor that refused the verdict on a 2-frame, 1-of-3-obstacle denominator
  (`EVIDENCE INSUFFICIENT`, not ADOPT).
- **Held 5.0 Hz recording and 720/720 grid coverage across a third independent flight** — 18/18 trees
  imaged, **11/18 canopy-grade, median NDVI lift +0.5562** (best on record) — after root-causing a
  12× throughput collapse to a Fast DDS shared-memory segment that silently discarded fragments and
  reported success.

## Earned by the 2026-08-26 offline session (four new bullets)

- **Cancelled a planned flight and redirected the project's roadmap on an offline measurement** by
  replaying three logged flights through a jerk/accel/velocity-limited point-mass model of the
  autopilot (every firmware constant cited to source at the pinned SHA) and sweeping **81
  configurations** — 2-10 m/s × every escape candidate × three plant models: **no mission speed
  makes the nadir sensor geometry safe** (warning capped at **0.41 s** by the intruder's own 6.0 m/s
  closing speed vs a **1.25 s** minimum escape; 2.48 m of sensor horizon against 17.8-38.7 m
  required), which promoted a second forward-facing sensor from growth path into scope.
- **Retired a long-open comparison experiment on evidence rather than leaving it in limbo** —
  measuring across 4,566 frames / 1.40 Gpx that the candidate "second sensor" shared the primary's
  band **bit-for-bit**, so it could never answer the question it was open for; the incumbent
  detector's ADOPT verdict was simultaneously **re-confirmed against a working rival at gap +0.000**
  (safety metrics identical, 3.1×/27× better precision).
- **Corrected a metric that had flattered my own decision**, showing a demoted monocular range
  estimator actually agrees with ground truth at closest approach to **3.3 mm** (not the 20 cm
  previously cited) — the error was the evaluation geometry, not the estimator — while leaving the
  demotion in place on its load-bearing argument.
- **Found a safety check that reported a direct hit as 7.00 m of clearance** by diffing two
  implementations of the same closest-approach metric on identical bytes: a segment-vs-vertex fix had
  never been back-ported to the legacy path. Fixed red-first (7.0000 → **0.0000 m**; two historical
  breach figures deepened to 0.0393 / 0.0391 m and were republished) and pinned by a property test
  that forbids the two implementations from ever disagreeing again.

## Earned earlier (still current)

- **Closed a deferred detection decision with measured evidence** — per-bird-track false-negative
  rate **0.000** against a ≤0.1 bar, precision 0.708 / recall 0.850 on real-render labels — by
  building a two-arm eval harness and adopting a classical blob detector over a learned model on the
  same scoring path (ADR-003 criterion 3).
- **Found that two "green" avoidance flights were 5 cm bird strikes** (CPA 0.0518 / 0.0597 m vs a
  3.00 m bar) by adding a gate that measured distance *flown* rather than setpoints *vetted*; both
  logs are retained as acknowledged findings, never as passes.
- **Recovered up to 32 silently-lost coverage cells per scenario** by fixing a ledger that recorded
  commanded setpoints as flown, then pinning the honesty property with a regression test.
- **Closed six false-PASS paths in the safety gate before any flight was booked** (incl. a 0.8 s
  frozen clock reporting a true 0.0000 m strike as a 3.5000 m PASS) by adversarially re-reading it
  five times, reproducing every finding with a probe against real code and pinning each fix with a
  test proven red first; suite 530 → **877 passed / 2 skipped / 0 xfail**.
- **Made a value-gate blind spot impossible to repeat** by shipping a 2.2 px mount-geometry gate
  after every value gate passed while the camera faced the horizon upside down.

## NOT earned — do not draft these

- "Verified reactive avoidance on the real render" / "avoided a bird in flight" as a **success**.
  The only real-detection take is INVALID. The honest verb is *engaged*, not *avoided*; the loop
  displaced the vehicle **1.8 cm** against a 10 m command.
- Any NDVI-vs-RGB **second-sensor** delta. The study RAN and closed (ADR-003 am. 10) by measuring
  that the arm was never a second sensor — so a sensor-diversity number does not exist and cannot
  come from it. Quote the detector-vs-detector figures instead. The old "birdness is inverted"
  caveat is **retired** (wrong feature, not wrong sign).
- The −0.61 threshold as settled (PROVISIONAL; range half narrowed 2026-08-26 across a 2.3× depth
  span, open beyond ~11 m).
- Any test-suite count until it is re-measured into `tests/README.md` — the tree currently
  contradicts itself (877/2 there vs 1028 + 902 in BUILD_LOG, one red by design).
- Dashboard / demo video / README as **shipped**. Week 7 went active 2026-08-26; drafts only.
- "3310 frames" as a clip size — 2639 are post-landing parked frames. Quote 671 airborne / 649
  painting.

Framing rules: [[narrative-guardrails]]. Story-level versions: [[safety-asterisk-and-story-bank]].
