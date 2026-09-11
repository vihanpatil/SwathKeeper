---
name: project-portfolio-floor-decision
description: ADR-022 (owner decision 2026-09-10) — SwathKeeper is a PORTFOLIO project first, then a ~10-conversation market test of the evidence METHOD; drone-as-product deferred, ADR-019 wire program CUT, NDVI/depth frozen. How it re-ranks QA work.
metadata:
  type: project
---

**The owner decided, 2026-09-10, on an end-to-end audit: SwathKeeper is a PORTFOLIO project first.**
Recorded as ADR-022 (`docs/DECISIONS.md:4446`), restated in `CLAUDE.md:14-21`, `docs/SPEC.md:9-14`
and `docs/ROADMAP.md:113-171`.

The sequence, in order, and nothing else opens before the one above it lands:
1. the portfolio floor (state docs reconciled, debris deleted, honesty artifacts **widened**,
   LICENSE + GitHub Pages + demo video);
2. **~10 conversations, zero code**, about running pre-registered evidence gates on other people's
   flight logs. Kill criterion fixed in advance: **0 of 10 interested → "strong portfolio, no
   product."**
3. only then ONE of (C) extract the method or (B) close the control loop in sim. B's own kill
   criterion is pre-written: **≥20 seeded headless encounters must clear 3.00 m**.

CUT or FROZEN, recorded so it is not re-opened: the **ADR-019 wire program** (am. 1), further
**NDVI/crop-health** work, an NDVI analytics product (rejected), the **depth segmenter** (frozen
until a depth flight exists). Deletion is AGGRESSIVE. Claims ceiling everywhere:
**"sim-demonstrated, evidence-gated."**

**Why:** the audit measured the apparatus at 2.28× `src/` and the `src/` share of each phase's
output falling 31.9 % → 5.3 %, with the stated #1 differentiator unproven (three live avoidance
flights, three breaches) and a never-flown sensor consuming the last arc. The discipline, not the
drone, is the only thing a stranger might pay for.

**How to apply (QA specifically):**
- The honesty artifacts are now **load-bearing product**, not internal hygiene: the three
  `eval/results/live_flight_log_*.json` + `.SAFETY_FINDING.md`, the INVALID verdict, and the ONE
  declared red CI test. Treat any softening of them as the top-severity class, and re-verify
  byte-identity against HEAD on every round that touches them.
- Rank findings by what a reader can check in 90 seconds from the front page. A wrong count a
  `grep -c` falsifies now costs more than a deep gate nuance nobody will run.
- Do NOT open new depth-sensor or NDVI gate work, and push back on any finding whose remedy is
  "one more bar" on a frozen subsystem — record it in [[project-open-safety-gaps]] instead.
- The achieved-displacement number is **REPORTED, never GATED** by deliberate decision (G1/G2 stay
  open and belong to branch B). A doc that implies it is gated is a finding; the gap itself is not.
