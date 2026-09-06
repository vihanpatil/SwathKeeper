---
name: a-gate-is-only-as-true-as-its-scene
description: Third instance of the green-tick-over-nothing pattern (2026-09-06) — a GEOMETRY gate passed 2 of 8 assertions while its own target was never in the scene; harnesses need their own gate
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

**So the generalisation is not "values can't catch geometry" — it is: a gate is only as true as the
scene it thinks it built.** The fix pattern that worked: the harness asserts its own preconditions
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

Related: [[adr020-depth-commissioning]], [[adr007-ndvi-render]], [[avoidance-take-blockers]].
