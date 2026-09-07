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

**Why:** these gates exist because a green verdict on a measurement nobody made is this project's
recurring defect (`eval/score.py`, 2026-08-21). A test that cannot see its gate degrade is the same
defect one level up.

**How to apply:** put the red fixture where every other bar is **provably** green (assert that too —
`test_the_fixtures_really_are_unconfounded_by_bar_5`), assert on the gate function's own `problems`
list rather than the joined message blob, spell required literals as literals, and finish by
mutating each new rule (`problems.append` → `notes.append`, the rule deleted) to confirm a named
test dies. Beware `scripts/__pycache__` when mutating quickly — `time.sleep(1.1)` between writes.

Related: [[evidence_consumption_seams]].
