---
name: headline-metrics
description: The current quotable SwathKeeper metrics as of 2026-08-26 (the first real-detection flight plus the offline session that fired the no-safe-speed tripwire), each with the artifact file that proves it, plus the numbers that must never be quoted
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

## THE OFFLINE SESSION — 2026-08-26 (four new quotable results, all host-side)

Artifact: `eval/results/replay_point_mass_20260826T160218Z.json`; ADRs 016 am. 1-2, 013 am. 19,
017 am. 1, 003 am. 10. **Uncommitted working tree as of 2026-08-26.**

| Claim | Number | So-what (the resume line) |
|---|---|---|
| **The tripwire FIRED — no safe nadir speed** | `speed_at_which_nadir_becomes_safe_mps = null` across **81 cells** (2-10 m/s × every escape candidate × 3 plants to the ANGLE_MAX ceiling). Lead caps at **0.4132 s from a hover** because bird_0 closes at its own 6.002 m/s; cheapest physical escape **1.25 s**; nadir horizon **2.480 m** vs **17.752-38.748 m** required at the flown 9.2 m/s | An offline replay killed a planned flight *and* promoted a sensor into scope. "The system found its own sensor's limit and refused to fly what it can't pass." Strongest single line in the deck |
| **Criterion 2 CLOSED — RETIRE-ARM (band identity)** | The RGB PNG's R channel **is** the NDVI Red band **bit-for-bit** (`rescale_red` = R/255; ≥24× level collapse, pinned by test). So the "comparison arm" shared band/aperture/mount/clock and **never was a second sensor**. At its honest ceiling RGB matches the adopted detector's safety numbers **identically**; precision 0.708 → 0.227 (3.1×) on the adopted clip, 1.000 → 0.037 (27×) in the air; **gap +0.000 → ADOPT re-confirmed against a WORKING arm** | Killed my own comparison arm by measuring that it couldn't answer the question — and the ADOPT verdict got *stronger*, not weaker. Retiring an experiment on evidence beats running it for the appearance of rigor |
| **Estimator agreement 3.3 mm** | `detection_cpa_m` 0.2096 → **0.0035**, `range_estimate_error_at_cpa_m` −0.2028 → **+0.0033** vs `gt_cpa_m` 0.0067. The 20 cm "estimator error" was the *gate's* geometry, not the estimator | I corrected a claim that had flattered my own decision: the monocular ray was better than I said. **The demotion still stands on its other leg** (a miss at CPA produces no detection at all, so detection-CPA can never be a gate) — right call, wrong reason, both recorded |
| **Segment-CPA fix (vertex → path)** | `closest_approach()` minimised over 5 Hz path *vertices*. Red-first fix: `cov_bird_at_turnaround` **7.0000 → 0.0000 m** (the one fixture that "passed" was a direct hit); `cov_two_birds_simultaneous` 1.0000 → 0.0000; live 2026-08-18 0.0597 → **0.0393**, 2026-08-23 0.0518 → **0.0391**; verdict lines byte-identical. A property test now pins the two CPA implementations to agree on a deliberate fly-through | A fix that landed in one place and was never back-ported left a **direct hit reading as 7 m of clearance for weeks**. Found by comparing two geometries on the same bytes. Every safety number got *worse* and I published all of them |

Also from that session, quotable with care: `predict_bird_visibility.py --speed` is now REQUIRED
(missing speed exits 2 — a refusal, distinct from PASS 0 / FAIL 1) and the gate **FAILs every speed
the vehicle actually flies** on this geometry; its own "faster is conservative" justification
measured **empirically false** (non-monotone via lane-arrival phase aliasing). Swath half-width now
derives from `camera_info`: **6.886 m**, not the prose 7.5 — an **8.19 %** area over-claim killed
before any dashboard could quote it, at the cost of a knowingly-booked 1.228 m unimaged strip per
lane pair.

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

**Numbers that may NEVER be quoted:**
1. The −0.61 real-render detection threshold is **PROVISIONAL**. Background half DONE (2026-08-25:
   1.02 Gpx over 3310 frames, darkest non-bird pixel −0.4406 on every frame, **zero** pixels below
   −0.50, warmest bird pixel −0.6697 → a 0.229-wide empty band). Range half **partially** closed
   2026-08-26: the adopted clip exercises it over a **2.3× depth span** (3.9 / 6.9 / 9.0 m, every
   bird core ≤ −0.8276) — this **corrects** the old "only ever exercised at ~4 m" line. Still
   PROVISIONAL beyond ~11 m; say "provisional" or don't say the number.
2. **Any NDVI-vs-RGB *second-sensor* delta.** Not because the study is missing — it ran (ADR-003
   am. 10) — but because it measured that the arm shares the primary's band bit-for-bit, so no
   sensor-diversity number exists or can exist from it. Quote the *detector-vs-detector* figures
   (3.1× / 27× precision, gap +0.000) and say plainly the arm was never a second sensor.
   **Retired caveat:** "birdness is INVERTED" is superseded — the feature was wrong, not the sign.
3. ~~Test-suite count contradictory~~ **RESOLVED 2026-08-26 into the named home.** `tests/README.md`
   now reads, measured on the verified host: `pytest tests -q` → **1058 passed, 1 FAILED, 2 skipped,
   0 xfail**; `unittest discover -s tests/fieldguard_planning` → 911 OK (2 skipped);
   `discover -s tests -p 'test_*.py'` → 150, 1 failure. **The 1 failure is deliberate and
   load-bearing** (`test_ci_evidence_gate…test_step_passes_on_the_committed_evidence`, red on the
   committed 2026-08-25 breach until the clean re-fly). Always quote the failure *with* its reason —
   the old 877/2/0 is stale.

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

**Not yet true, don't narrate forward (as of 2026-08-26):**
- The 2026-08-25 take is **INVALID and stays INVALID**. There is no passing real-detection
  avoidance flight, and there cannot be one on nadir — the re-fly now sits **behind the forward
  sensor**. Never write "avoidance verified on the real render".
- R4 (escape geometry) is still open, and the replay proved **candidate ordering was never the
  binding constraint** — lead time is. Don't sell R4 as the fix.
- The **forward-facing second sensor is scoped, not built** (ADR-017 am. 1). The tilt is rejected.
- Week 7 is **ACTIVE as of 2026-08-26** (user chose option A). The **dashboard now EXISTS**
  (`dashboard/` — three views, every figure computed in-browser from committed artifacts, sha256
  provenance footer, 5-step tour) but **GitHub Pages is not enabled**: use a marked placeholder
  URL + the local `python3 -m http.server 8000` → `/dashboard/` one-liner. **No demo video exists**
  (no `*.mp4|gif|mov|webm` anywhere in the tree) — every video link is TODO.
  README/demo drafts live in `docs/drafts/`, **not applied to `README.md`**.
  See [[week7-gtm-decisions]], [[safety-asterisk-and-story-bank]], [[resume-bullet-bank]].
- **Claims ceiling is BINDING (ADR-019 / Ruling 002): "sim-demonstrated, evidence-gated."**
  "Essential / field-ready / production / pay-for-this" is vetoed until external hardware data or
  an outside conversation exists. Sweep every outward draft for prose that reads as field-ready.
- **Wire avoidance is scoped future work only** (mapped infrastructure from a fresh per-field
  survey; metres of buffer from 0.15–1.4 m catenary sag). Never a capability claim.
- A3 positioning line, now on the record and usable: phased-array radar is standard on shipping
  mid-to-flagship ag platforms, the leaders' own manuals disclaim wire bypass (DJI T50 FAQ +
  specular-reflection physics), and **no commercial mapping platform does live reactive avoidance
  mid-flight** — that gap is the product's position. Sourced tone, no competitor-bashing.
