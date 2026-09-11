---
name: project-direction-20260910
description: The owner's 2026-09-10 decision — portfolio first, then ~10 market conversations about the METHOD; drone-as-product deferred, ADR-019 wire program CUT, NDVI analytics rejected, deletion aggressive, honesty artifacts widened
metadata:
  type: project
---

On **2026-09-10**, after an end-to-end audit, the owner decided: **SwathKeeper is a PORTFOLIO
project first.** After the reconciliation floor, the owner tests the market for the **METHOD**
(pre-registered evidence gates) with ~10 conversations *before writing more code*. The
drone-as-product path (closing the control loop in sim) is **deferred behind that test**. The
ADR-019 **wire program is CUT** from scope. An NDVI/crop-health analytics product is **REJECTED**.
Deletion is **AGGRESSIVE**. The honesty artifacts stay on the front page and are **WIDENED**: all
three bird-clearance breaches disclosed, the INVALID verdict and the declared red CI kept.

**Why:** three independent critiques (market strategist, principal autonomy engineer,
founder/investor) agreed on all of it — the differentiator has no identified paying buyer (every
shipping ag OEM already ships radar detect-and-avoid), the NDVI map has no health signal to sell,
and the one asset a stranger would pay for is the verification discipline. The effort curve was the
clincher: `src/` share of each phase's output fell 31.9 % → 5.3 %, and 93.6 % of post-pivot output
went to grading a sensor that has never flown.

**How to apply:**
* **Do not write another gate, bar, or pre-registration document** unless it retires one. The
  reflex this decision is correcting is "build a 3,500-line gate instead of talking to ten people".
* Prefer DELETING to adding; every new test file should retire one. Lifetime deletion rate was
  1.7 % and every option on the table needs it higher.
* Measurement that was missing is still worth adding — but as a **REPORTED note**, not a bar,
  unless a decision record sizes the bar (that is what the achieved-displacement work of this date
  did; see [[evidence-consumption-seams]]).
* When a change would soften a breach, an INVALID verdict, or the red CI: **stop and ask.** Those
  are the deliverable now, not an embarrassment to manage.
* The depth segmenter, `depth_detect`, and the whole NDVI pipeline are FROZEN. Do not extend them.
