---
name: adr022-direction-reset
description: ADR-022 (2026-09-10) reset the program — portfolio floor first, then a ~10-conversation market test of the METHOD, drone-as-product deferred, wire program CUT, four standing freezes including a tests:src cap
metadata:
  type: project
---

**On 2026-09-10 the owner reset the program (ADR-022), after an end-to-end audit.** The sequence is:
(1) portfolio floor (reconcile the state docs, delete debris, widen honesty, LICENSE + Pages +
video); (2) a **market test of the METHOD** — ~10 conversations with ArduPilot/PX4 teams about
running pre-registered evidence gates on *their* logs, zero code, **kill criterion 0 of 10 → strong
portfolio, no product**; (3) drone-as-product (closing the loop in sim, ≥20 seeded headless
encounters clearing 3.00 m) **deferred behind that answer**, hardware behind that. The **ADR-019
wire program is CUT** (am. 1); an NDVI analytics product is **REJECTED**.

**Why:** the audit measured that the effort curve had inverted (`src/` share per phase 31.9 % →
5.3 %), the apparatus is 2.28× `src/`, the #1 differentiator had flown 3 times and breached 3 times
(0.0393 / 0.0391 / 0.0067 m vs a 3.00 m bar), the flagship dodge moved 0.018 m in a 0.434 s GUIDED
window against a 10 m command, the depth sensor has zero flights, and five state docs contradicted
each other. Three independent critics agreed the method — not the drone — is the sellable asset.

**Four freezes, standing — check these before proposing work:**
(a) `docs/DECISIONS.md` amendments **≤ 10 lines**; (b) **no new ADR without a cut**;
(c) **tests:src capped at 3.70:1** (re-baselined 2026-09-10 by ADR-022 am. 1 — it shipped at 3.45, the tree measured 3.70) — every new test file retires one;
(d) the **NDVI pipeline** is frozen (ADR-019 §7) and the **depth segmenter until a depth flight
exists** — no more bars, no more design notes.

**How to apply:** ADR-022 is the tiebreak for "what should we build next" — anything that is not the
floor, the ten conversations, or the branch chosen after them needs a cut recorded in the same
breath. Claims ceiling everywhere stays **"sim-demonstrated, evidence-gated"**. The honesty
artifacts (three breaches, the INVALID verdict, the declared red CI) are **load-bearing assets** —
never soften them to make a page read better.

**Open, carried forward:** R8 — the committed coverage mission violates its own XY geofence by
−1.997 m on leg 4 and CI runs the check `|| true`; recorded OPEN, owed a diff.
Related: [[avoidance-take-blockers]], [[adr021-segmenter-design]], [[a-gate-is-only-as-true-as-its-scene]].
