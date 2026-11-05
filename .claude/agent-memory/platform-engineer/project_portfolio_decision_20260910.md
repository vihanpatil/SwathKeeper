---
name: project-portfolio-decision-20260910
description: The owner's 2026-09-10 direction call after the end-to-end audit — portfolio first, market-test the METHOD, wire program CUT, deletion is aggressive, honesty artifacts WIDENED
metadata:
  type: project
---

**2026-09-10, the owner's decision after an end-to-end audit of the whole repo:**

* SwathKeeper is a **PORTFOLIO project first**. After a finishing floor (~2-3 weeks, no new
  engineering), the owner will test the market for the **METHOD** — pre-registered evidence gates —
  with ~10 conversations *before writing more code*.
* The drone-as-product path (closing the control loop in sim) is **deferred behind that test**.
* The **ADR-019 wire program is CUT** from scope.
* An **NDVI/crop-health analytics product is REJECTED** (commodity; and this world has no health
  variation to show — both bands are per-class uniform).
* **Deletion is AGGRESSIVE.** Lifetime deletion rate was 1.7 %; every option on the table needs it
  to rise. Prefer deleting a job/test/doc to adding a flag.
* The **honesty artifacts stay on the front page and are WIDENED**: all three bird-clearance
  breaches disclosed (gate-recomputed CPA 0.0393 / 0.0391 / 0.0067 m against a 3.00 m bar; the two
  2026-08 `--demo` takes are ACKNOWLEDGED exit 0, the 2026-08-25 real-detection take is INVALID
  exit 1), the INVALID verdict kept, and the declared red CI kept.

**Why:** three independent critiques (market strategist, principal autonomy engineer,
founder/investor) agreed the differentiated asset is the verification method, not the drone; that a
sim-demonstrated bird dodge has no identified paying buyer; and that the finishing floor is the
non-negotiable prerequisite for every option.

**How to apply:** price any new gate, test or workflow against "does a stranger reading this repo
in 90 seconds believe it?" — not against completeness. Claims ceiling everywhere stays
"sim-demonstrated, evidence-gated". Do not propose new apparatus for the never-flown depth sensor,
new ADRs without a cut, or anything that softens a published breach. See
[[project_ci_pipeline]] for the CI-honesty work this decision produced.
