# SwathKeeper — Roadmap (living document)

Owner: `product-lead`. Update at each `/standup`. History lives in `docs/BUILD_LOG.md`; decisions
in `docs/DECISIONS.md`; this file is only ever **the current truth and what's next**.

**Deadline status (2026-08-18):** the original ~7-8-week / Europe-trip hard stop is **dropped**
(user decision). Quality over calendar — but the **standing scope guard survives the deadline**:
nothing gets added to scope without something else being cut in the same breath, and every
`/standup` is still measured against protecting the demo + dashboard exit.

## Where we are (2026-08-21)

| Phase | Status |
|---|---|
| Weeks 1-2 — sim foundation + detection decision | ✅ complete (2026-08-04) |
| Weeks 3-4 — reactive avoidance + coverage-debt loop | ✅ complete, **demonstrated live** (2026-08-05) |
| Week 5 — NDVI pipeline | 🟢 validation DONE: **all four gates GREEN live** (Gate 0 2026-08-05, Gates 1-3 2026-08-18); mount geometry corrected + gated (ADR-007 am. 5, 2.2 px); first tree-verified heatmaps committed. Recording throughput instrumented + 3× improved 2026-08-21 (5.1× frames, 2.3× cells, ADR-013 am. 6). **Demo take flown 2026-08-21** — best canopy evidence to date (8 canopy-grade trees, median lift +0.8692), item 2. Open: the two-stage frame loss (am. 6a) |
| Week 6 — real detector on the seam + comparison arm | ⏳ contract locked (ADR-009); implementation gated on the batched session. **New blocker, measured 2026-08-21:** no clip yet puts a bird in the nadir FOV, so both ADR-003 criterion 3 and the criterion-2 comparison arm have nothing to score (item 3) |
| Week 7 — dashboard, demo video, README/GTM | ⏳ not started (deliberately last) |

Test suite: **364 green, 2 skipped** (measured 2026-08-21 post-PR #26) — 331 in
`tests/fieldguard_planning` plus 33 host-side launcher tests in `tests/test_fly_pipeline.py`, which
need neither Docker nor tmux. CI discovers both (it ran only the first until 2026-08-18) and also
gates seed-42 FNR, scenario-log drift, flight-log evidence. The 10 added 2026-08-21
(`test_score_evidence.py`) pin the eval harness's evidence guards — the reason a real-render re-run
can no longer return a verdict it did not measure; PR #26 added the predictor, tree-gate, and
ADR-015 geometry pins.
Public main: current as of PR #26 (2026-08-21). Full narrative of how we got here:
`docs/BUILD_LOG.md`.

## Next up, in order

1. **Recording throughput — instrumented, 3× better, still the gap (2026-08-21).** Four `test-flight`s, one
   variable at a time, same `test_2lane` mission, with `camera_info_frames` (692 / 699 / 696 / 698)
   as the control that all four saw the same exposure window. The fuser counters built on 2026-08-20
   (ADR-013 am. 5) flew for the first time and **named the starving stage on flight one**: the RGB
   *image* band alone — `red_frames` 73 against 692 `camera_info` messages off the *same sensor
   tick*, with `dropped_pair_count` **0**. Not a render problem, and not the stale-pair guard: for
   the frames that never arrive, a payload-size-dependent transport loss. (Pairing turns out to lose
   a further ~38 % of the frames that *do* arrive — ADR-013 am. 6a, found after these flights.)

   | flight | config | red/ticks | fused | recorded | cells |
   |---|---|---|---|---|---|
   | baseline | as-was | 73 / 692 = **10.5 %** | 45 | 17 | 158 |
   | lever A | bridge QoS best_effort | 126 / 699 = 18.0 % | 78 | 41 | 125 |
   | lever B | preview publish gated | 113 / 696 = 16.2 % | 76 | 36 | 150 |
   | **both (kept)** | A + B | **217 / 698 = 31.1 %** | **129** | **86** | **368 / 720** |

   **Both levers KEPT — nothing reverted.** *A:* the ros_gz bridge publishes images RELIABLE while
   every consumer subscribes BEST_EFFORT, so the reliable half was retransmission machinery for
   ~900 KB samples nobody wanted retransmitted; it is **not settable in the bridge yaml** at the
   pinned SHA (`bridge_config.cpp:28-36` — nine keys, no QoS, unknown keys silently ignored) but is
   a per-topic ROS parameter (`factory.hpp:66-79`), now on the Shell-2 one-liner and verified bound
   before it flew. *B:* `/fg/ndvi/preview` is human-only and **nothing subscribes to it**, yet every
   fused frame paid a colormap plus two 921,600 B copies plus a no-reader publish on the executor
   that should have been draining the RGB subscription; now guarded by `get_subscription_count()`.
   Full record + rejected alternatives: **ADR-013 amendment 6**. Clips
   `eval/results/clips/real_flight_20260821T03{2316,3001,3644,4116}Z`, gate records
   `eval/results/testflight_gate_20260821T03{2657,3342,4029,4504}Z.json`.

   **Honest reading:** recorded frames are up **5.1×** and cells imaged **2.3×** against the same
   day's baseline; 368/720 also beats the previous all-time valid 2-lane best (291 off 48 frames,
   2026-08-18). It is *not* solved, and the remaining loss is in **two** stages, not one: 69 % of RGB
   frames still die in transport, and ~38 % of the survivors then never pair — `red_frames −
   fused_count − dropped_pair_count` = 28 / 48 / 37 / 88 across the four flights, flat across both
   levers because neither touched pairing. End to end that is 12.3 % of sensor ticks reaching the
   clip, so **the next lever is not necessarily another transport lever** (ADR-013 am. 6a).
   Two traps for whoever picks this up: (a) judge levers by
   `red_frames / camera_info_frames`, **not** by `cells_imaged` — lever A's own flight imaged fewer
   cells than baseline (125 vs 158) on 2.4× the frames, purely because its extra frames landed while
   the vehicle was slow (climb, far-end turn), and coverage is bought by frames *spread along the
   lanes* (survey-altitude frames off the takeoff point: 6 → 42); (b) the amendment-4 evidence floor
   (12 frames / 40 cells) was deliberately **not** raised to match the new yield — one healthy run at
   the new config is not enough, and it should rise after a second.
   **First FULL-mission datapoint on the tuned config (2026-08-21 demo take, item 2).** The four
   flights above were all the short `test_2lane` mission; the demo take flew the full boustrophedon
   and its `meta.json` carries the first full-mission fuser telemetry. The two-stage picture from
   amendment 6a holds at 5× the duration, and both stage fractions land where the short flights put
   them:

   | stage | count | of previous stage | of sensor ticks |
   |---|---|---|---|
   | `camera_info_frames` (sensor ticks) | 4257 | — | 100 % |
   | `red_frames` (RGB images that survived transport) | 962 | **22.6 %** | 22.6 % |
   | `fused_count` (paired with NIR) | 634 | 65.9 % | 14.9 % |
   | frames recorded into the clip | 454 | 71.6 % | **10.7 %** |

   `dropped_pair_count` **0**, `nir_frames` 2970. The unpaired remainder — `red_frames −
   fused_count − dropped_pair_count` = **328, i.e. 34.1 % of the RGB frames that did arrive** — sits
   squarely inside amendment 6a's 33-41 % band, confirming on a full mission that pairing is a
   second, independent loss stage that neither kept lever touched. End to end 10.7 % against the
   short flights' 12.3 %.
   **But the throughput number is not the coverage number, and this flight is where that stops being
   theoretical:** of the 454 frames recorded, only **51 painted a cell**. 403 painted nothing (401 of
   them parked at home before arm and after land) and only 42 were above 12 m. Judge a lever by
   `red_frames / camera_info_frames`, judge a *map* by painting frames — and start reporting the
   second, because "454 frames" reads five times better than the 51-frame artifact it produced.

   **Lever already disproven — do not retry:** `camera.update_rate_hz` 5 → 2 (2026-08-19) made
   delivery 16× worse (3 frames / 1 of 720 cells against 48 / 291), with RTF unchanged (0.585 vs
   0.561) and the mission flown identically; `eval/results/testflight_gate_20260819T021136Z.json` vs
   `..._20260818T222031Z.json`, reasons preserved in `config/ndvi_camera.json`'s `update_rate_note`.

   **Round 2 (2026-08-22): attribution complete — see ADR-013 amendment 7.** Six counters settled
   what flights would have: pairing is the NIR band's transport loss re-expressed (slop lever
   disproven twice, `dropped_pair_count` structurally zero), NIR render and the recorder's own
   logic/disk both exonerated — every remaining loss is transport. F5's baseline came back VOID
   twice on measured **environment drift** (an unrelated 12-container stack now shares the Docker
   VM; F4's 31.1 % remains the only clean anchor, n=1). **Closed 2026-08-22, ADR-013 am. 8:**
   F5c re-baselined clean (red/ci 25.6 %, drift confirmed end-to-end; tree lift +0.9888, best on
   record) and **L1 KEPT** — the NDVI→recorder hop closed 62.5 %→0 % with the attribution identity
   at zero unaccounted; painting cadence **0.2823 → 0.4767 Hz (1.69×)**.

   **ROUND 3 CLOSES THE THREAD (2026-08-22, ADR-013 am. 9).** Root cause source-verified in Fast
   DDS 2.6.11: samples fragment at 65,384 B even over shared memory and the default 512 KiB
   segment holds 8 fragment slots against the 10–19 our frames need; overflow discards silently.
   Fix = `config/dds/fg_fastdds.xml` (SHM segment → 8 MiB) + `--shm-size=1g`, injected in-pane
   with runbook parity intact. **F9: 100.00 % delivery on BOTH bands, zero unpaired reds,
   end-to-end 96.46 %, painting cadence 5.0 Hz** — the full sensor tick; transport is no longer
   the bottleneck. L1 re-check closed (KEEP, dead heat, old cost vanished). **Predictor: PASS,
   medians 8/6/11 → the item-3 re-fly is BOOKABLE.** Caveat: 5.0 Hz on 3-min `test_2lane` is not
   yet proven at boustrophedon length (run-age decay, am. 7); `meta["dds"]` makes it checkable.
2. **The full-coverage demo take — FLOWN 2026-08-21.** Clip
   `eval/results/clips/real_flight_20260821T045848Z`, the first full boustrophedon on the tuned
   (both-levers) config, and the first flight anyone flew through the one-command launcher rather
   than seven hand-driven shells. **454 frames, 410/720 cells imaged.** Runbook:
   `docs/runbooks/FULL_PIPELINE_DEMO.md`; the launcher stays a bringup wrapper — the flight itself
   was human-flown at the MAVProxy prompt, as demo flights always are (ADR-013).

   **Against the runbook's own proof standard, this clip is HALF a pass — and the half it misses was
   never exercised, not failed.**

   | half of the standard | verdict | evidence |
   |---|---|---|
   | 18 trees at their 18 known positions | **PASS — best canopy evidence to date** | 12/18 imaged, **8 canopy-grade**, median lift **+0.8692** |
   | birds visible / avoidance exercised | **NOT EXERCISED** | **0 bird-visible frames of 454** |

   *Trees.* Method (reconstructed and pinned by reproducing all three published 2026-08-18 figures
   exactly — flight 6 at 5/8, flight 7 at 5/6, and the "+0.87 typical lift" that `README.md` and
   `BUILD_LOG.md` both quote, which recomputes to **+0.869196** pooled): every tree centre sits on a
   grid corner, so its canopy straddles the **four** cells sharing that corner; `imaged` = ≥1 of the
   four has a mean; `canopy-grade` = best-of-four > 0.0; `lift` = best-of-four − soil modal
   (−0.437687, on 311 of 410 imaged cells). This clip returns median lift **+0.8692 against the
   +0.8692 baseline** — dead on to four decimals — and **8 canopy-grade trees against a previous
   best of 6**. Precision is the strongest single result: **all 9 positive-NDVI cells in the whole
   410-cell map sit at exactly 1.7678 m from a tree centre** (= a 2.5 m cell's centre-to-corner
   distance), zero canopy signal anywhere a tree is not, and a 6 m sweep around each soil-grade tree
   finds no displaced canopy cell — so those are genuine non-detections, not ADR-007-am.5-class
   mislocation. **Read "best to date" precisely:** three earlier clips imaged *more* cells (697, 586,
   450) and *more* trees (17, 16, 15) — and returned **zero** canopy-grade trees, with 100 % of their
   positive cells sitting **6.4-11.9 m** off the nearest tree. That is the pre-mount-fix signature;
   every post-fix clip puts 100 % of its positive cells at 1.7678 m. Cells imaged is not the metric.
   *Birds.* 0/0/0 in-frame across all 454 frames and across the 51 that painted a cell — see item 3.
   Not a regression. **Both causes, separated on 2026-08-21 by `scripts/predict_bird_visibility.py`:**
   bird_0 was STRUCTURAL (5.0 m off the nearest lane, 1.81 m outside the frame edge at its best
   moment, unreachable at any cadence) — **fixed by ADR-015**, which moved its patrol line onto the
   x=15 lane; bird_1 and bird_2 were TIMING (they do cross the lanes, median 3 and 11 frames at the
   5 Hz sensor tick) and are **still gated on item 1's throughput** — at this take's actual 0.407 Hz
   even the new geometry predicts medians 0/0/1. The earlier reading of this line ("geometry, not
   throughput") was half right and is corrected here.

   *The tree half is now a gate, not a look.* The method above was reconstructed by hand; it is now
   `scripts/check_tree_positions.py` (+ 12 tests reproducing all five published clip figures exactly
   and rejecting the three horizon-mount clips). Exit 1 on the georef-displacement signature —
   a positive-NDVI cell farther than 2 m from every tree centre. See the ADR-007 amendment.

   **Open question this raises, worth one line and no more:** all three trees on row 0 sit **on** the
   x=15 flight lane and returned +0.000 / +0.614 / +0.622, while every tree imaged from *between*
   lanes returned +0.85…+0.92. Hypothesis (n=3, **unproven**): near-nadir a canopy projects near its
   true 5.31 m² footprint and splits four ways across the corner it straddles (~21 % fill per 6.25 m²
   cell → diluted mean), while off-nadir parallax smears a 3.8 m-tall object over more ground-plane
   area and fills a cell. It predicts that lane spacing which puts orchard rows *under* the lanes
   systematically under-reads its own trees — which would matter for the NDVI product, not just for
   this check. **Not established:** two off-lane trees (row2_0 at 10.7 m, row2_5 at 5.4 m) also read
   soil-grade, both off single-sample cells, so sample poverty is an unseparated competing
   explanation. No ADR amendment until someone separates them.

   **Also honest about coverage: this is a 51-effective-frame map.** Only **51 of 454** frames painted
   a single cell (frames 275-325, contiguous); 403 painted nothing and 401 of those sat at home
   before arm and after land, with just 42 frames above 12 m. All 6 unimaged trees have **24/24** of
   their quad cells inside the 310 unimaged — the misses are pure coverage, not weak signal.
3. **ADR-003 real-render re-run (criterion 3) — RUN 2026-08-21, returned EVIDENCE INSUFFICIENT. Open,
   and its blocker has CHANGED.** Full record: **ADR-003 amendment 1**. The re-run executed cleanly
   end to end on the item-2 clip and produced **nothing to score**: `annotate_real_clip.py` labelled
   454/454 frames with 0 refusals (ADR-012 amendment 1 working as intended — 280 pre-driver-start
   frames labelled at the spawn pose), and `label_from_sim.py` then returned **0 visible bird-boxes
   over 454 frames**. Precision / recall / FNR / per-bird-track FNR are **undefined** on this clip;
   the synthetic 0.445 bar has nothing to be compared against. Criterion 2's comparison arm is
   blocked on the same missing clip.

   **The blocker was geometry, and the geometry half is now CLOSED (ADR-015).** A nadir camera at
   15 m over birds at 6/8/11 m AGL had a footprint *at bird altitude* of just 4.9×3.7 to 11.1×8.3 m
   against a **15 m lane pitch**: the ground plane tiles, the bird-altitude plane does not. bird_0
   patrolled x=20, a fixed 5.0 m off lane x=15 — outside frame on every pass. Closest approach all
   flight: **14.15 m** slant range, ≈341 px outside the image edge. Cheapest unblocks, in order:
   (a) **move the birds** in `config/birds/farm_world_birds.json` — **DONE 2026-08-21, ADR-015**, and
   *not* by lowering them: the recommendation this line used to carry ("2-3 m AGL") was measured to
   put every bird 12-13 m under cruise, i.e. twice outside the ±6 m avoidance threat cylinder, which
   trades priority #1 for #2. bird_0's patrol line moved onto the x=15 lane instead (cross-track
   offset 0, so altitude is free) and took the threat role at 11 m; bird_1 took its 8 m. Predictor
   now says **PASS**, medians **8/6/11**, no bird structural, threat cylinder still occupied at an
   unchanged **4.00 m** closest approach. (b) **an offline pre-flight predictor** — **BUILT
   2026-08-21, see below**; (c) recalibrate both detector thresholds, which the real render moved —
   **NDVI arm done (provisional), RGB arm still blocked**.

   **What is still open on this item is THROUGHPUT, not geometry.** At the demo take's own 0.407 Hz
   the new geometry predicts the same medians **0/0/1** as the old; ADR-015 raised the ceiling (total
   median 14 → 25 frames at the 5 Hz tick) and removed the one bird no cadence could ever reach, but
   item 1's recording-throughput work is what converts opportunity into a scoreable clip. Run
   `python3 scripts/predict_bird_visibility.py` before booking the session — it is 1 s on the host.

   **Why the next Docker session is worth booking: ONE re-fly clears four blockers at once** — all
   four are waiting on the same artifact, a clip with a bird actually in frame:
   1. **criterion 3** — the NDVI-direct per-bird-track FNR on the real render (this item);
   2. **criterion 2** — the NDVI-vs-RGB comparison arm, blocked on the same missing clip;
   3. **item 2's second half** — the runbook proof standard's "birds visible / avoidance exercised",
      NOT EXERCISED on the demo take;
   4. **both detector thresholds** — `baseline_ndvi.py`'s −0.61 is PROVISIONAL until it is calibrated
      against precision/recall rather than pixel means, and `baseline_rgb.py`'s inverted birdness is
      deliberately untouched until there is a bird to calibrate its absolute scale against.

   **The precondition is not optional, and it is the whole lesson of 2026-08-21:** geometry alone does
   not deliver that clip. Land item 1's throughput work first, then re-run the predictor at the
   cadence you actually achieve — if it still reports medians 0/0/1, the session will produce a
   fourth unscoreable clip and should not be booked.
   **The premise survives:** class ordering on the real render is canopy +0.531 > trunk −0.026 >
   soil −0.429 > bird −0.789, a bird-vs-soil gap of **0.360** against ~0.23 synthetic. What broke is
   a threshold value, not the hypothesis.

   **(b) DONE — `scripts/predict_bird_visibility.py` (ADR-003 amendment 2).** Host-only, 0.8 s, exit 1
   on a shortfall. Validated by reproduction: replaying the demo take's own poses returns its measured
   0-of-454, 14.15 m and 341.2 px, and agrees with `label_from_sim.py` on all **1,362 frame×bird
   decisions**; predicting the same mission from **pure config** at that take's actual 0.407 Hz frame
   rate gives medians **0/0/1**, i.e. under one expected bird-visible frame in the whole flight.
   **It also splits the blocker in two, which changes what to do next:** sweeping all 55
   driver-start offsets at the 5 Hz sensor tick, bird_0 is **0/0/0 at 0 of 55 offsets** — STRUCTURAL,
   1.81 m outside the frame edge at its best moment, and no throughput or luck can ever show it —
   while **bird_1 (median 3) and bird_2 (median 11) do cross the lanes** and are limited by *cadence*,
   not geometry. So (a) is required for bird_0 and item 1's throughput work is what buys the other
   two. Amendment 1's "more frames cannot fix this" holds for bird_0 only; its 4.31 m half-width was
   the along-track axis — cross-track is **3.23 m** (ADR-007 mount extrinsic), so the miss is larger
   than stated, not smaller.

   **(c) NDVI half DONE — threshold `-0.61`, PROVISIONAL (ADR-003 amendment 3).** `baseline_ndvi.py`
   now resolves its threshold per render from the clip's `meta.json`: synthetic keeps ADR-003's
   deciding `0.05`, real render gets the gate2 bird/soil midpoint (bird −0.7888, soil −0.4285 →
   −0.6087), recomputed from `gate2_summary.json` by test so the constant cannot drift from its
   evidence. Measured on the demo take: at `0.05` the mask covers **≥99.9 % of pixels on 438 of 454
   frames** (0 detections *by saturation*); at `-0.61` the mask is **empty on all 454**, so the same 0
   now means "nothing was there". It stays PROVISIONAL — calibrated on pixel means, never on
   precision/recall — until a bird-visible clip exists. `baseline_rgb.py` is untouched by design.

   **Three harness defects found and fixed on the way** (pinned by `tests/fieldguard_planning/
   test_score_evidence.py`), the first of which is the reason this item reads "insufficient" rather
   than "confirmed": `score.py` used to print `-> ADOPT (a) NDVI-direct` on an **empty** ground truth
   (TP=FP=FN=0 makes every rate 0.000, and the decision rule read four zeros as a clean sweep) —
   reproduced live against the pre-fix file on this clip's own artifacts, `ADOPT` before,
   `EVIDENCE INSUFFICIENT` after. Also: `label_from_sim.py` never derived `range_m` on real clips, so
   per-bird-track FNR silently degraded from "detected before closest approach" to "detected on first
   sight"; and `baseline_rgb.py` KeyError-ed on any clip with partial RGB (243 of 454 here).
4. **Doc long-tail**: apply the remaining documentation-review fix-list (78 items, ~70 remaining —
   list + exact edits preserved; criticals already applied).
5. **Week 7**: dashboard (replay + avoidance log + NDVI overlay on the shared cell grid), demo
   video, GTM pass.

## Explicit stretch goals (documented, NOT v1 blockers)
- Full coverage-debt reconciliation (v1 ships "avoid, return to next waypoint" + honest debt,
  ADR-002; AP_DDS exposes no mission-current service at the pinned SHA, so this is genuinely
  harder, not just deferred — source-verified, see ADR-006).
- Scaling from 2-3 birds to a flock / higher obstacle density.
- Second-sensor config promoted from comparison arm to a supported operating mode.
- Live in-node NDVI stitching (offline is the v1 decision, ADR-010).

## Cut / deferred log
_(product-lead records cuts here with date + reason — interview material.)_

- **2026-08-18 — code-identifier rename deferred (ADR-011):** `fieldguard_planning`, `fg_`/`/fg/*`,
  `farmguard_field.sdf`, `fieldguard-sim` image stay under the old name; the `/fg/*` contract is
  embedded in ADR-007 and partially live-verified, and renaming verified interfaces for cosmetics
  re-opens confirmed state for zero functional gain.
- **2026-08-05 — no YOLOv8 bolt-on for resume keywords.** The metric-driven story is stronger:
  a classical blob baseline cleared the safety bar; any learned model must beat it on the same
  harness (the 0.445 synthetic-clip precision bar) before it earns a place.
- **2026-08-05 — no retrofitted startup narrative.** Sim-only, solo, portfolio-honest framing is
  the asset; inflating it converts the honesty in every ADR into an interview red flag.
- **2026-08-05 — colcon/ament packaging of the planning package.** Zero demo value; PYTHONPATH
  works in-container. Restated 2026-08-18 (audit re-confirmed the cut).
