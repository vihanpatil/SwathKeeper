---
name: headline-metrics
description: The current quotable SwathKeeper metrics as of 2026-08-25, each with the artifact file that proves it, plus the two numbers that must never be quoted
metadata:
  type: project
---

Every headline number I quote in README/resume/pitches, with its source. Re-verify against
`docs/ROADMAP.md` "Where we are" + the file before each reuse — these decay fast.

| Claim | Number | Source file |
|---|---|---|
| Bird detection, REAL RENDER (ADR-003 criterion 3 CLOSED 2026-08-23, ADOPT NDVI-direct) | per-bird-track FNR **0.000**, every bird detected before closest approach; precision **0.708** / recall **0.850**; TP 17 / FP 7 / FN 3 over **20** bird-visible frames, 3/3 birds | `eval/results/adr003_20260823/spike_scores.json` |
| Map completeness | **720/720** cells, 2.5 m grid, 624 painting frames | `eval/results/clips/real_flight_20260823T073644Z/heatmap/heatmap.json` |
| Recording cadence (was 0.41 Hz — Fast DDS SHM segment was the root cause) | **5.0 Hz** flat, 100 % delivery both bands | same clip's `meta.json` |
| Tree localization, hero clip `real_flight_20260823T073644Z` | **18/18** imaged, **9/18** canopy-grade, median lift **+0.5402**, all 12 positive cells <2 m from a tree centre, gate PASS | `scripts/check_tree_positions.py` on that clip |
| Canopy contrast | median NDVI lift **+0.8692** (2026-08-21 take: 12 imaged / 8 canopy-grade). Best on record is +0.9888 but that was a PARTIAL map (F5c), so +0.8692 is the honest headline | pinned in `tests/fieldguard_planning/test_check_tree_positions.py` |
| Coverage integrity, live flight | **720 covered / 0 debt**, 19/19 dodges vetted | ADR-013 am. 11 in `docs/DECISIONS.md` |
| Bird clearance (the safety asterisk) | CPA **0.0518 m** and **0.0597 m** vs a **3.00 m** bar — ACKNOWLEDGED findings, never "passes" | the two `eval/results/live_flight_log_*.SAFETY_FINDING.md` markers |
| Test suite | **877 passed / 2 skipped / 0 xfail** (822 in `tests/fieldguard_planning` + 57 host-side via `-p 'test_*.py'`) | `tests/README.md` — declared the ONE home 2026-08-25; README + SETUP quote it |

**Two numbers that may NEVER be quoted:**
1. The −0.61 real-render detection threshold is **PROVISIONAL** (n=20, false-positive
   characterisation owed). Say "provisional" or don't say the number.
2. `baseline_rgb.py`'s **1.000 FNR / 0.000 across the board** measures an **inverted** birdness
   signal on this world. It is NOT RGB's ceiling, so the NDVI-vs-RGB second-sensor delta has **no
   quotable number yet** (criterion 2's independent pixel study is deferred).

**Two labels that are easy to get wrong (both were wrong in a draft README, 2026-08-25):**
- What landed 2026-08-24 is **R2 (1 m lateral tree margin) + R3 (no re-latch on a degenerate range)
  + the ground-truth CPA gate** — **NOT** the escape-geometry fix. R4 (escape geometry) is the cause
  of both breaches and is deliberately RECORDED-OPEN. Never write "the escape-geometry fixes landed".
- The NDVI-vs-RGB **comparison arm is ADR-003 criterion 2** (deferred, ~1 h offline, clip exists).
  ADR-009 is the *detector evidence contract* (stamps, staleness, apparent-size ray) — different thing.

**Per-clip tree numbers differ; quote the clip.** The README hero clip
`real_flight_20260823T073644Z` re-measured on host 2026-08-25: **18/18 imaged, 9/18 canopy-grade,
median lift +0.5402**, all 12 positive cells within 2.0 m, gate PASS. So "all 18 trees show as bright
cells" is NOT supportable for that map — "18/18 imaged, every bright cell on a real tree" is.
The **+0.8692** headline belongs to the 2026-08-21 take (12 imaged / 8 canopy-grade).

**Not yet true, don't narrate forward:** the real-detection avoidance stack landed OFFLINE
2026-08-24 and awaits ONE user-flown take — pre-registered as possibly failing its own GT-CPA gate.
Week 7 (dashboard, demo video) is NOT STARTED. See [[safety-asterisk-and-story-bank]].
