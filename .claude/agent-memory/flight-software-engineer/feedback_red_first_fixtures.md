---
name: feedback-red-first-fixtures
description: A red fixture must fail the gate under test and nothing else — put it where every OTHER bar is green, assert on the gate's own problems list, and never pin a required literal by reading the constant that prints it
metadata:
  type: feedback
---

Writing a red fixture is not enough: it must be red **for the gate under test**. Two shapes of
false confidence, both found by mutating gates rather than reading them (QA + me, 2026-09-07, the
depth-log bars):

* **A neighbouring bar satisfies the assertion.** Bar 4's out-of-frustum fixtures sat at 20 m, which
  independently trips bar 5's 33.591 m breakeven, so `assertInvalid` passed on the ACQUISITION
  problem while the frustum text was found among the NOTES. Rewriting both of bar 4's
  `problems.append(...)` as `notes.append(...)` — demoting the confidently-wrong-perception gate to
  a remark — left all 65 tests green. I then reproduced the same shape twice in my own round-2 tests.
* **The pin reads the value under test.** Every assertion spelled bar 7's requirement as
  `checker.NA_DEPTH`, so rewriting that constant to `"not applicable"` left the suite green.

* **The fixture picks the one geometry where the mechanism cannot fail.** (2026-09-11, R8.) The
  mission-geofence gate's adversarial test was a LEVEL leg grazing a tree for 0.4 m — shorter than
  the sampling step, so it looked like a resolution test. It is not: on a level leg the in-volume
  window can only end at the obstacle circle, which the gate sampled explicitly, so the test passed
  by construction. Sloped legs, where the window is bounded by a canopy-band crossing and can be
  arbitrarily short, false-passed **57 of 2,500**. Mutating `SAMPLE_STEP_M` 0.5 → 5.0 → 1e9 left the
  whole suite green: the sole survivor of nine mutants.

**Why:** these gates exist because a green verdict on a measurement nobody made is this project's
recurring defect (`eval/score.py`, 2026-08-21). A test that cannot see its gate degrade is the same
defect one level up.

**How to apply:** put the red fixture where every other bar is **provably** green (assert that too —
`test_the_fixtures_really_are_unconfounded_by_bar_5`), assert on the gate function's own `problems`
list rather than the joined message blob, spell required literals as literals, and finish by
mutating each new rule (`problems.append` → `notes.append`, the rule deleted) to confirm a named
test dies. Beware `scripts/__pycache__` when mutating quickly — `time.sleep(1.1)` between writes.
For anything sampled, mutate the RESOLUTION constant too (widen it 10x and 2e9x); if nothing goes
red, the resolution is unguarded no matter how adversarial the fixture reads. And enumerate the
geometries the mechanism can fail on before choosing the fixture — level/sloped, entering/leaving,
inside/outside — rather than picking the one that is easiest to write down.

Related: [[evidence_consumption_seams]].

**A DEFAULT ARGUMENT THAT READS THE MODULE UNDER TEST FREEZES IT AT IMPORT — AND BREAKS THE RED RUN
(2026-09-11).** `def record(self, birds=checker.LAUNCHER_BIRDS_ARMED, ...)` is evaluated when the
class body runs, so against the PRE-FIX module it is an `AttributeError` at COLLECTION: the whole
test file errors out and the red-first run reports one error instead of "25 red, 6 green, and here
are the six controls". Use a sentinel (`ARMED = object()`) and resolve from the module inside the
method. **Why:** the value of a red-first run is the per-test verdict — which new tests are red and
which greens are the controls that must stay green. A collection error destroys exactly that.
**How to apply:** any fixture default that names a constant in the code under test.
