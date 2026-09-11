---
name: depth-segmenter
description: The forward depth segmenter — built, scored and ADOPTED 2026-09-07 (re-scored same day after a QA fix round); the constants and the sweep that chose them, the design forks the data settled, and the findings that CORRECT the design notes
metadata:
  type: project
---

The operator is a **grey closing / black top-hat** on the depth field:
`cand = isfinite(z) & (near<z<far) & (closing(z,K) - z > margin)`, 8-connected, no `max_area`,
nearest-first box cap. **Built and scored 2026-09-07**: `src/fieldguard_planning/depth_segment.py`
(flight module), `eval/score_depth_segmenter.py` (labeller + scorer),
`eval/results/depth_segmenter_score_20260907T110000Z.json` (the artifact that chose every constant —
the `...093000Z` first pass was DELETED and replaced by the fix round; no constant moved),
`eval/results/depth_dataset_20260907/REPORT.md`. **ALL BARS PASS → ADOPT.** Design notes:
`docs/design/DEPTH_SEGMENTER_DESIGN.md` (tech-lead) + `DEPTH_SEGMENTER_ALGORITHM.md` (mine).

**Why:** the `isfinite` mask D3 and the booking gate ran on only works because the check world is a
bird against sky. In the mission world a bird crossing the ground band merges into it and either an
area ceiling deletes it or the blob survives carrying the BACKGROUND's depth. A closing solves it
because a monotone ramp has no pits, so the ground is never its own candidate.

**How to apply:**

* **Adopted constants (do not retune without re-running the sweep):** K=15, margin 1.5 m,
  min_area 10 px, open_iter 0, max_boxes 64, link_break False. Every one is the OUTPUT of a
  pre-registered rule, and `DEFAULT_PARAMS_PROVENANCE` names the artifact.
* **Fork (a) — K=15 vs the design note's K=21 — SETTLED, K=15**, and *how* K=21 fails is the part
  worth keeping: it does not merely miss the canopy-backed birds, it **merges them into a ~53.9 m
  canopy component**. A one-clause (pixel-only) matcher would have scored those as HITS and adopted
  K=21. Clause 2 of the matcher is what makes the sweep mean anything.
* **Fork (b) — the one-to-many matcher — NOT applied to `matched`, deliberately** (nearest station
  14 m, above the 12.48 m rim-arc crossover; loosening the matcher on a range the data does not
  cover only makes it easier to call something a hit). `fragments` counts the footprint-disc
  candidates. Measured crossover: one component down to 10 m, 4 rim arcs from 8 m in.
* **THE MEDIAN-FLIP MARGIN — the metric `range_error_p95` cannot see, added in the fix round.**
  The reported depth is the component's MEDIAN, so a mixed component tells the truth only while the
  bird holds a majority of its pixels: a CLIFF, not a drift. Measured over 63 matches (5 mixed, 58
  pure bird): **S042/S046 are ONE pixel from a flip** (32 bird px of 60; the other 28 are canopy at
  ~54.5 m), S041 is 3 px. On the far side the SAME detection publishes **54.5 m instead of 29.96 m**
  — a bird at 30 m declared no threat. REPORTED, NOT BARRED (a threshold invented in the pass that
  first sees the number is fitted to its own data). Bird pixels come from the negative-control diff.
* **Fork (c) — `link_break` stays OFF, but the first pass's reason was FALSE.** "ON introduced 2
  merge mislabels and fixed nothing" — both halves wrong. The merge metric flagged any box at the
  bird's pixel carrying the background's depth *without requiring the bird to be unmatched*, so it
  scored a correct SPLIT as the failure it is the fix for. Corrected (`if not matched`), BOTH arms
  have 0 mislabels. The two reasons that survive: (1) ON moves no bar; (2) it fails the design
  note's own precondition — the seam cut drops two adjacent 12 px objects below `min_area_px` and
  returns **nothing**. **Open item, deliberately not acted on:** ON is better on range p95
  (0.1076 → 0.0775 m), worst centroid (4.335 → 0.665 px) and it removes the flip fragility entirely
  (min bird fraction 1.0). The pre-registerable next step is *link_break with cut components exempt
  from min_area_px*, in its own round with a two-bird dataset arm.
* **THREE findings that correct the design notes — do not re-assert the old prose:**
  1. **A large near object returns NOTHING, not a ring.** DESIGN §2.5 and ALGORITHM §2.4 both say a
     pit wider than K comes back as a rim; a grey closing by definition *preserves* such a pit, so
     `closing-D = 0` across it. Measured: a 1.3 m canopy sphere is invisible inside ~25 m, a flat
     300 px wall at 8 m entirely. Survivable here only because this world's large objects are the
     geofenced trees (ADR-001) and its unplanned obstacle is a 0.18 m bird detectable to ~2 m.
     **A large unplanned obstacle at close range is a named blind spot of this operator.**
  1b. **The +inf substitution before the closing is load-bearing for NaN and ONLY NaN.** The source
     used to blame `-inf`; measured, `-inf` is INERT because the *dilation runs first* (it never
     survives a max over its own window) and substituting it only costs one extra FAR component. A
     **NaN** patch overlapping a target's KxK window poisons the filter pair and erases the target
     (68 candidate px → 2, below `min_area`). It had NO test and source-mutation `closing(zb)` →
     `closing(z)` survived all 49 tests; it now has one and the mutant dies.
  2. **`isfinite` is REDUNDANT with the exclusive clip window** — `-inf > near_m`, `+inf < far_m`
     and every NaN comparison are already False. Deleting it alone changes nothing on the canned
     frame or on all 85 dataset frames; the *pair* deletion is the red one. Three pre-registered
     conjuncts are two independent terms. Never count `isfinite` as a second safeguard.
  3. **The resolving floor is set by `min_area_px`, not by the opening.** min_area 10 → 2.0 px →
     46.80 m; min_area 6 → 1.6 px → 58.50 m (reproduces the prototype). The earlier note that
     `open_iter=0` buys 58.5 m was wrong about the mechanism. 46.80 m sits just BELOW the 47.558 m
     corner clamp, so on this sensor the **morphology binds the horizon by 0.76 m**, not the cull.
* **The margin was chosen by its FLOOR, not by the FP measurement** — unmapped FP is 0.0/frame at
  every K and every margin down to 0.5 m, because the ground-band border artifact un-projects to
  z≈0 and therefore scores as *mapped* clutter. The floor is 1.5 x the measured border residual
  (0.9805 m at K=15). If real foliage with sub-K pits ever appears, the FP term is what binds.
* **The labeller trick worth reusing:** every camera pose in the dataset was rendered twice, once
  per station and once with the birds parked out of the world, so **diffing a frame against its own
  group's negative control locates the rendered bird with no detector in the loop** — and proves the
  occlusion stations (S058/S059/S060 change zero pixels). Max |rendered − recomputed| 0.4415 px.
  Forward projection is mine, the inverse is the flight primitive `depth_pixel_to_enu`; requiring
  them to agree is a geometry check a value-only gate cannot fake.
* Still true from the prototype, do not re-propose: the **two-stage 52 px median background** was
  built, scored and rejected (498 false candidate px, needed a second rule, 19.6 ms, blind below
  4.2 m); a **size/apparent-radius filter cannot separate clutter from birds** (canopy-rim fragment
  31 px vs a bird's 33 px at 24 m).
* **The 46.0 m acquisition is only CLUTTER-BACKED TO 28 m** (canopy; ground band 22 m). Every ladder
  rung from 30 m up is 100 % sky-backed, and that is geometrically forced, not a sampling gap: an
  in-band bird at 46 m and 6 m below the axis has its ground background at ~86 m, past the 60 m
  Euclidean cull. The booked number does not move; the claim's reach does.
* **Two objects at once is UNMEASURED and fails dangerous.** Every station has exactly one bird
  while CLAUDE.md's MVP density is 2-3. Constructed: two touching near objects at 20.0 and 30.0 m
  return ONE component reporting **25.0 m** — a median belonging to neither. Cheap close: one extra
  teleport per camera pose in whatever renders next.
* **The dataset is ~100 MB and gitignored** (`eval/results/*`). The artifact, `REPORT.md` and the
  six `fixtures/*.npz` (16-25 KB each) need un-ignore lines before the pinning test can survive a
  fresh clone; the tests hard-assert, matching `test_booking_gate_artifact.py`'s discipline. The
  remedy is VERIFIED (`git ls-files --others --exclude-from=`, yields exactly the 8 wanted paths):
  `!eval/results/depth_segmenter_score_*.json`, `!eval/results/depth_dataset_20260907/`,
  `eval/results/depth_dataset_20260907/*`, `!eval/results/depth_dataset_20260907/REPORT.md`,
  `!eval/results/depth_dataset_20260907/fixtures/` — in that order, a bare `!` alone will not work.
* **Quote runtime as 6.708 ms p95 / 10.786 ms max over n=425** (5 reps × 85, host). `metrics.runtime`
  is the bench; `segmenter_counters`' wall-ms trio is the single scoring pass (n=79) and is the one
  a reader grabs by accident. Numbers move run to run — read them from the artifact, not from here.
* **These numbers were computed on python 3.9.6 / numpy 1.26.4 / scipy 1.13.1.** CI pins numpy 2.5.1
  / scipy 1.18.0 (py3.12); the flight container is numpy 1.21.5 / scipy 1.8.0 (py3.10). The 3-dp
  fixture assertions have run on NEITHER target. Booked, 60 s: `python3 -m pytest
  tests/fieldguard_planning/test_depth_segment.py -q` inside the sim image.

Related: [[eval-harness]], [[ndvi-rgb-spike]], [[sensor-horizon]].
