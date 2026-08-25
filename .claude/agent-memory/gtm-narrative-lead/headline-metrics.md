---
name: headline-metrics
description: The current quotable SwathKeeper metrics as of 2026-08-25 (incl. the first real-detection avoidance flight), each with the artifact file that proves it, plus the numbers that must never be quoted
metadata:
  type: project
---

Every headline number I quote in README/resume/pitches, with its source. Re-verify against
`docs/ROADMAP.md` "Where we are" + the file before each reuse — these decay fast.

## THE FLIGHT — 2026-08-25, first real-detection avoidance take (VERDICT: INVALID)

Artifacts (all UNCOMMITTED on `feat/throughput-instrumentation` as of 2026-08-25):
`eval/results/live_flight_log_20260825T210402Z.json` (schema 2),
`eval/results/bird_drive_20260825T210030Z_applied.jsonl` (truth),
`eval/results/clips/real_flight_20260825T205705Z/`, `eval/results/adr003_20260825/`.

| Claim | Number |
|---|---|
| **The milestone** | first flight where the avoidance loop engaged on a bird the drone **detected itself** — real render, adopted blob detector on `detection_source`, apparent-size range, GUIDED |
| **The verdict — quote it every time** | **INVALID.** `gt_cpa_m` **0.0067 m** to `bird_0` at tick 991 (`t_sim` 202.775 s) vs a **3.00 m** bar; freeze debit **1.1277 m** → gated **−1.1210 m**; exit 1 |
| Detector rate, first in-air | **1301/1302 = 99.9232 %** vs a 0.90 floor (single loss = `dropped_no_intrinsics`) |
| Detection quality on this take | TP 2 / FP 0 / FN 0 — but `eval/score.py` returned **EVIDENCE INSUFFICIENT** (1 of 3 birds ever visible). ADR-003's ADOPT is neither challenged nor confirmed |
| Warning time (the expensive finding) | sensor lead **0.175 s**, policy lead **0.000 s** (first detection arrived ON the CPA tick); dwell in-cylinder 1.4 s / in-image 0.4 s; closing **14.4 m/s** |
| Visibility, not detection | bird truly in-cylinder 16 ticks, 7 frames captured, **2 in image**; nadir camera images ~**4.0 %** of the threat cylinder at 4.03 m depth. `predict_bird_visibility.py --backtest` reproduces 2/0/0 |
| Displacement achieved | **0.018 m** against a 10 m command, 0.434 s GUIDED window — "the avoidance loop moved the vehicle 1.8 cm" |
| R2 flew, not vacuous | 4 accepted maneuvers, swept tree clearances 1.393/1.756/1.340/1.857 m ≥ 1.0; 8 candidate rejections; **0 `is_safe_3d` violations / 1858 points**. R3 missed activating by **15 mm** |
| Live↔offline equivalence | offline boxes reproduce the flight log's `Detection.position_enu` to **1 micrometre** across scipy 1.8.0 (air) vs 1.13.1 (host) — closes ADR-013's one-scipy-version caveat |
| NDVI half, best on record | **720/720** cells, **649 painting frames @ 5.0 Hz flat**; **18/18 trees imaged, 11/18 canopy-grade, median lift +0.5562**, all 11 positive cells <2 m from a tree centre, PASS |
| Ledger | **720 covered / 0 debt**, 0 clock-domain violations |

**Quote 671 airborne / 649 painting, NEVER 3310 frames** — teardown was skipped, so 2639 of the
3310 are post-landing parked frames (harmless, all zero-update, but 22 min of a parked drone).

## Standing metrics

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
1. The −0.61 real-render detection threshold is **PROVISIONAL**. The **background** half of the
   false-positive study is now DONE (2026-08-25: 1.02 Gpx over 3310 frames, darkest non-bird pixel
   −0.4406 on every frame, **zero** pixels below −0.50, warmest bird pixel −0.6697 → a 0.229-wide
   empty band). The **range** half is not — only ever exercised at ~4 m depth on a 47 px bird. So it
   stays PROVISIONAL; say "provisional" or don't say the number.
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

**Not yet true, don't narrate forward (as of 2026-08-25 post-flight):**
- The 2026-08-25 take is **INVALID and stays INVALID** until re-flown behind R4. There is no
  passing real-detection avoidance flight. Never write "avoidance verified on the real render".
- R4 (escape geometry) is still open — and this flight proved R4 **alone cannot fix it**: the
  sensor gave 0.175 s of lead, so the re-fly also needs a lead-time lever (speed, tilt, or a second
  sensor). Whether the camera stays nadir is an open **product-lead/ADR decision**, not mine.
- `scripts/predict_bird_visibility.py` `DEFAULT_SPEED_MPS = 3.0` PASSes the abort gate at 3 m/s and
  FAILs at the flown ~9.4 m/s — the defect that booked this session. Unfixed.
- Week 7 (dashboard, demo video, README/GTM) is **NOT STARTED**. See [[safety-asterisk-and-story-bank]]
  and [[resume-bullet-bank]].
