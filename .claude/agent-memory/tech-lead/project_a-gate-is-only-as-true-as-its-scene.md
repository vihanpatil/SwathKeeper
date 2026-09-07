---
name: a-gate-is-only-as-true-as-its-scene
description: The green-tick-over-nothing pattern, four instances (latest 2026-09-07) — a geometry gate passed with its target absent, a correct measurement reasoned about at an unmeasured speed, plus the guard-side twins (an unpinned safety conjunct, and a tolerance that could not tell the defect it was written to reject)
metadata:
  type: project
---

**Rule: demand a check the artifact cannot fake — and then ask the same question one level up, of
the harness that built the scene the check scores.**

**Why:** the pattern now has three instances in this repo, and the third one is the general form.
1. **ADR-007 am. 5** — four *value* gates green while the camera faced the horizon. Lesson filed as
   "a gate that measures VALUES cannot catch GEOMETRY."
2. **ADR-013 am. 18** — a 99.92 % detector-floor green on a take where the detector saw a bird on
   2 of 1301 frames.
3. **ADR-020 am. 1 (2026-09-06)** — the *geometry* gate written to answer #1 ran, and **D2 CLEAR and
   D2 FAR PASSED while `bird_0` had never moved**: the harness stripped the physics plugin so the
   parked vehicle would not free-fall, and `/world/<w>/set_pose` is applied ONLY by the Physics
   system (`UserCommands::PoseCommand::Execute` merely creates `components::WorldPoseCmd`;
   `PhysicsPrivate::UpdatePhysics` is its sole consumer). The service still replied `data: true` —
   **that Boolean means QUEUED, not MOVED.** The two assertions that passed are the two that are
   bird-independent.

4. **ADR-020 am. 2 (2026-09-07) — the same defect moved from the gate to the INFERENCE.** D6's pitch
   was measured correctly (−1.175° median) and then reasoned about under an assumption nobody had
   measured: that the window was flown at `test-flight`'s ~10 m/s `WPNAV_SPD` default, making it an
   **upper** bound on the booked 5 m/s pitch. The clip's own `poses.jsonl` said the window was flown
   at **3.50 m/s median** — slower than the booked speed — so the reading is a lower bound on the
   pitch **MAGNITUDE**, and the sentence was **retracted**. Same shape as a rate with no
   denominator: the number was fine, the thing it was divided by was invented.
   *(And the retraction itself had to be re-written 2026-09-07: "a lower bound on the booked pitch"
   on a signed quantity where nose-down is negative reads as pitch ≥ −1.18°, which IS the retracted
   claim. On a signed quantity, always say whether the bound is on the value or the magnitude.)*

**So the generalisation is not "values can't catch geometry" — it is: a gate is only as true as the
scene it thinks it built, and a measurement is only as true as the conditions you MEASURED it
under.** Ask of every flight-borne number: at what speed, over what window, against what
denominator — and get each from the clip, not from the mission's nominal config. The fix pattern
that worked: the harness asserts its own preconditions
(every commanded pose read back within 0.05 m off `pose/info`; the vehicle's park pose checked at
world-up AND after the last capture; the world copy's edits grepped before launch), and any failure
exits on a **distinct code (4) that disowns every number printed above it** — "NOTHING PRINTED IS A
MEASUREMENT" — rather than wearing the gate-fail code.

**How to apply:**
- When commissioning any new gate, ask what it prints if its *target is absent*. If the answer is
  "some of it still passes", the harness needs a self-check before the gate is trusted.
- A service ack is not an effect. Read the state back.
- Watch for gate-fail codes worn by aborts: an unmatched `grep` exits 1 and a `timeout` exits 124;
  under `set -e` either can impersonate a verdict.
- Python `for` targets leak: a sweep loop named `ok` overwrote the folded verdict and would have
  printed PASS over a failed mount (pinned by an AST test in
  `tests/test_verify_depth_mount_geometry.py`).
- **Probe the FORMULA, not just the number.** Two 2026-09-07 defects were latent-but-dangerous and
  invisible in today's outputs because this sensor is symmetric: the frame-corner bound spelled
  `cy/fx` with a config `cx` (at a live cy of 120 it published 50.14 m where the truth is 44.05 —
  exit 0 BOOKABLE on an unmeasurable range), and `band_covered_from_m` used `cy` instead of
  `min(cy, H−1−cy)`. Both were found by feeding the formula intrinsics it will never see, not by
  re-reading the render. Do that for any arithmetic that CLAMPS a flight authorisation.
- **A safety property stated in a docstring is a CLAIM that a test exists. Mutate the conjunct and
  see.** 2026-09-07: `bookable = passed and live_intrinsics and acq_range_m is not None` — the
  booking gate's headline property, "exit 0 is unreachable without a MEASURED horizon", with the
  docstring line "That is the property, and it is pinned by test." Deleting the third conjunct broke
  **zero** tests in a 1254-test suite, and the mutant booked a 5 m/s flight on host arithmetic. Every
  neighbouring property was pinned; the headline one was not, because the redundancy that held it
  (`main`'s separate `live_inputs`) was refactored away in the pass that wrote the docstring.
- **Never rest a claim ON a boundary — including the boundary of the guard that enforces it.**
  Same day: `check_depth_mount.py` pinned "band from 13.05 m" as `abs(from_m − 13.05) ≤ 0.05`, and
  the exact defect it was written to reject prints 13.000145 — inside the window by **0.15 mm**. The
  operator gate stayed PASS 23/23 while printing a value its own text calls wrong. When you write a
  tolerance, compute how far the mutant you fear actually lands from it.
- **A "residual, named not fixed" claim in a multi-builder session must be re-grepped before the
  commit.** Mine went into an append-only ADR describing a `.sh` file that another lane had already
  repaired hours earlier, in the same pass. An append-only log that records a fixed defect as open
  is worse than silence.
- **A scripted test-flight that writes into `eval/results/` has changed the evidence.** The
  2026-09-06 test-flights left two `bird_drive_*_applied.jsonl` tracks there; the CPA gate
  auto-discovers applied tracks, so they turned `check_live_flight_log`'s `TestCli` red and would
  have made the next real take's CPA binding AMBIGUOUS by default. Delete test-flight artefacts in
  the session that produces them.

Related: [[adr020-depth-commissioning]], [[adr007-ndvi-render]], [[avoidance-take-blockers]].
