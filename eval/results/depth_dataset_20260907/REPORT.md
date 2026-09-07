# Depth segmenter — score report

**Artifact:** `depth_segmenter_score_20260907T110000Z.json` · schema 1.0 · generated 2026-09-07T10:19:29+00:00
**Verdict:** ADOPT: K=15 margin=1.5 m min_area=10 open_iter=0 max_boxes=64 -- FNR 0.0 over 49 detectable stations, unmapped FP 0.0/frame over 8, range p95 0.1076 m over 63 matches, seg p95 6.708 ms host; cluttered acquisition 46.0 m -> booked 46.0 m. ALL BARS PASS

Claims ceiling: **sim-demonstrated, evidence-gated**. Every rate below carries its denominator. This is a HOST score on a rendered dataset; nothing here is a flight measurement, and the runtime bar is settled in the air, not on this bench.

## The dataset, and what the capture already proved

- `eval/results/depth_dataset_20260907` — **85 frames**, float32 (480, 640), pinhole Z-depth in m; `+inf` beyond the 60 m far clip (culled on Euclidean slant), `-inf` inside the 0.1 m near clip.
- `labels.jsonl` sha256 `08514c681be52e0f…`; station file `docs/design/depth_segmenter_stations.json` sha256 `a1b96e5a8e128302…`.
- **82 distinct frame sha1** over 85 frames. The repeats are the occlusion stations against their pose's negative control: a hidden bird leaves the scene pixel-identical to the empty one, which is both the expected outcome AND the occlusion proof.
- Capture facts, verified fail-closed by the render harness: every vehicle pose within 0.05 m / 0.5° of command, every bird teleport within 0.05 m, the committed 125×110 m `field_ground` (NOT the 425 m check-world extension), birds 1 and 2 parked out of every frustum, zero gravity so nothing drifts.
- Each frame was re-hashed on load; a mismatch stops the run.

### The labeller, and the three things it cannot fake

1. **The bird is located by diffing each frame against its own group's negative control** — no detector in the labelling loop. Max |rendered − recomputed| = **0.4415 px** (at S052), against τ = 5.0 px, over every visible station.
2. **Forward and inverse projections are different code.** Round-trip through the flight primitive `fieldguard_planning.depth_detect.depth_pixel_to_enu` closes to **0.0 m**.
3. **The world model is checked against the render.** Max |ray-cast − rendered| background depth = **0.0344 m** (at S039).

The station file's own `expected_px` differs from the readback recompute by at most **0.0133 px** (S055) — the predictions hold, but every label used here is the recompute.

## Adopted constants

| constant | adopted | rule (pre-registered, DESIGN §3.2) |
|---|---|---|
| `bg_window_px` (K) | **15** | smallest K in [15, 17, 21, 25] with FNR 0 |
| `margin_m` | **1.5** | smallest with zero unmapped FP on the 8 negatives, floored at 1.5× the border residual |
| `min_area_px` | **10** | largest keeping FNR 0, minus one step |
| `open_iter` | **0** | both scored |
| `max_boxes` | **64** | 2× worst-case component count over ALL stations |
| `link_break` | **False** | kept only if it moves a bar |
| `near_m` / `far_m` | 0.1 / 60.0 | the seam's own exclusive window, pinned equal by test |

### The sweeps, as run

**Border residual** (max `closing(D,K) − D` on a 15 m analytic ground ramp — a frame-border effect, exactly zero over the interior). It is what floors the margin, so the chain reads *border artifact → margin → smallest visible stand-off*:

| K | 15 | 17 | 21 | 25 |
|---|---|---|---|---|
| residual (m) | 0.981 | 1.125 | 1.419 | 1.718 |
| 1.5x floor on margin (m) | 1.471 | 1.688 | 2.129 | 2.577 |

**margin × K on the 8 negatives** (unmapped FP / frame; `*` = at or above that K's floor):

| K \ margin | 0.5 | 0.75 | 1.0 | 1.2 | 1.5 | 1.75 | 2.0 | 2.5 | 3.0 |
|---|---|---|---|---|---|---|---|---|---|
| 15 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0* | 0.0* | 0.0* | 0.0* | 0.0* |
| 17 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0* | 0.0* | 0.0* | 0.0* |
| 21 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0* | 0.0* |
| 25 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0* |

**The FP term never bound.** Every cell above is 0.0 unmapped FP per frame — at every K and every margin down to 0.5 m — so `margin_m` was chosen entirely by its FLOOR. That is a real limit of this measurement, and naming it is the point: the ground band's border artifact un-projects to z ≈ 0, i.e. to *mapped* clutter, so the unmapped-FP metric is structurally blind to the very artifact the floor exists to clear. The prediction that would falsify the floor's sufficiency is foliage with self-depth structure containing pits narrower than K; this world's canopies are smooth spheres.

**K ladder** at each K's own chosen margin:

| K | margin (m) | denominator | misses | FNR | merge mislabels |
|---|---|---|---|---|---|
| 15 | 1.5 | 49 | [] | 0.0 | [] |
| 17 | 1.75 | 49 | [] | 0.0 | [] |
| 21 | 2.5 | 49 | ['S039', 'S040', 'S041', 'S042', 'S045', 'S046'] | 0.1224 | ['S040', 'S045'] |
| 25 | 3.0 | 49 | ['S038', 'S039', 'S040', 'S041', 'S042', 'S045', 'S046'] | 0.1429 | [] |

DESIGN §3.2 argued **K ≥ 17** from the fill requirement (2·fx·0.18/13.05 = 14.3 px). The dataset adopted **K = 15** — so that argument was conservative, and it is recorded as such rather than quietly overridden.

**How the large-K arms fail is the interesting part.** K = 21 and K = 25 do not merely lose the canopy-backed birds — the merge-mislabel column shows they lose some of them *by merging the bird into a ~53.9 m canopy component*, which is the failure DESIGN §2.4 calls *worse than a miss, because it looks like success*. A one-clause matcher (pixel only, no depth) would have scored those stations as HITS and adopted K = 21. Clause 2 is what makes the K sweep mean anything.

**min_area ladder** and **open_iter**:

| min_area_px | 4 | 6 | 8 | 10 | 12 | 14 | 16 | 20 |
|---|---|---|---|---|---|---|---|---|
| misses | 0 | 0 | 0 | 0 | 0 | 3 | 3 | 10 |

The ladder BRACKETS the smallest accepted component in [12, 14) px, and the smallest rendered bird footprint anywhere in the FNR_zero set is **12 px** (three 46 m stations — the render's antialiasing floor, and the same 12 px PROBE B measured on the commissioning frames). Adopted **10**, i.e. 1.2× headroom.

- `open_iter=0`: 0 misses over 49 detectable, unmapped FP 0
- `open_iter=1`: 0 misses over 49 detectable, unmapped FP 0

**link_break**, scored on both arms under the CORRECTED merge rule:

| arm | misses | unmapped FP | merge mislabels | correct splits | range p95 / max (m) | worst centroid (px) | min bird-pixel fraction | link_cut_px |
|---|---|---|---|---|---|---|---|---|
| `link_break=False` | 0 | 0 | 0 | 0 | 0.1076 / 0.1362 | 4.335 (S037) | 0.5333 | 0 |
| `link_break=True` | 0 | 0 | 0 | 2 | 0.0775 / 0.0846 | 0.665 (S037) | 1.0 | 1688 |

> **OFF. Under the CORRECTED merge rule the ON arm moves no bar -- 0 misses, 0 unmapped FP and 0 merge mislabels on both arms -- so clause (a) is not met, and clause (b) fails outright: the seam cut drops a pair of adjacent 12 px objects below min_area_px and returns nothing (multi_object_probe). Either clause alone keeps it off.**

*Correction to the first pass:* the first scoring pass recorded 'ON introduced 2 merge mislabels (S042, S046) and fixed nothing'. BOTH halves were wrong. The 2 were correct SPLITS mis-counted by a merge rule that did not require the bird to be unmatched, and ON does fix something: it separates exactly the two components whose medians sit 1 px from a flip.

*Open item, not acted on here:* ON is measurably better on two REPORTED (unbarred) quantities -- range error p95/max and worst centroid -- and it removes the median-flip fragility at S042/S046 by giving the bird its own component. It is NOT adopted here because choosing it now would mean widening the adoption rule after seeing which way the numbers fell, on the same data. The pre-registerable next step is 'link_break=True with cut components exempt from min_area_px', which would satisfy clause (b) by construction; it needs its own round and its own dataset arm (a two-bird station), not a flip in a fix round.

## Bars

| metric | value | denominator | bar | result |
|---|---|---|---|---|
| FNR (per background × range bin) | 0.0 | 49 detectable of 49 FNR_zero | 0 misses | **PASS** |
| merge mislabels (bird NOT separately matched) | 0 | 71 visible bird stations | 0 | **PASS** |
| unmapped FP / frame | 0.0 | 8 negative frames | ≤ 0.05 | **PASS** |
| range error p95 | 0.1076 m | 63 matches | ≤ 0.5 m | **PASS** |
| runtime p95 / max | 6.708 / 10.786 ms | n=425 (5× per station) | 25 / 100 ms | **PASS** |
| determinism | 0 mismatched | 79 stations | 0 | **PASS** |
| mutation (mask conjuncts) | 3/4 red | 1 canned frame + 85 dataset frames | the 2 independent terms + the pair | **PASS** |

**Quote the runtime row, not the counters.** `metrics.runtime` is the bench: p95 **6.708 ms**, max **10.786 ms**, **n = 425** (5× per station, host). The separate `segmenter_counters` block carries a wall-ms trio too, but over the single scoring pass (n = 79); its numbers are smaller and they are the ones a reader reaches for by accident. Note the max is 1.6× the p95 — both clear the 25 / 100 ms bars, and that ratio is the part not to lose.

**Merge mislabels are counted only where the bird was NOT also returned as its own component.** the same pixel/depth geometry WITH the bird also returned as its own component is a correct SPLIT, not a mislabel, and is counted here instead of in the bar. The first scoring pass conflated the two, which made a strictly better detector score the 0-merge bar red and became the stated reason for an adopted constant. On this run the corrected column is 0 and the correct-split column is 0 (none).

Mapped FP — **reported, not barred** — 14.375 per frame over 8 negative frames (115 inside a tree's 3D geofence, 0 at or below the 4.8 m geofence top). mapped FPs are REPORTED, NOT BARRED: a cluttered lane pose is nothing but real near canopies, the policy's +/-6 m band around a 15 m cruise already excludes them, and depth_detect rule 9 forbids suppressing them here

**Read the FP bar with its mechanism in view.** Nearly every detection on a negative frame un-projects to a real near object — a canopy or the ground — so the *mapped* column is where the volume is and the *unmapped* bar is a check that nothing was detected in EMPTY SPACE. The two bars pull in opposite directions on the same eight frames: a segmenter that hallucinated a bird to pass the range ladder would score its own FP bar red on the same run.

Centroid error (reported, not barred — it is what decides whether the box-midpoint decision of DESIGN §1.3 stays): p95 **0.93 px**, max **4.335 px** at `S037` — **0.665 px of headroom** against the matcher's τ = 5.0 px. Range error is **signed positive at every match** (0.042 to 0.1362 m): the median places the bird slightly FARTHER than its nearest surface, which is the fail-dangerous direction and is bounded here by the object's own 0.18 m radius.

### Median-flip margin — REPORTED, NOT BARRED, and the number `range_error_p95` cannot see

The depth that ships with a box is the component's MEDIAN, so a component that is part bird and part background tells the truth **only while the bird holds a majority of its pixels**. That is a cliff, not a drift. Over **63 matched stations** (5 of them mixed, 58 pure bird), the minimum bird-pixel fraction is **0.5333** and the closest approach to a flip is **1 px** (['S041', 'S042', 'S046'] are within 3 px). Bird pixels come from the negative-control diff, so no detector is in this loop either.

| station | range (m) | background | component px | bird px | fraction | px to flip | reports (m) | would report after a flip (m) |
|---|---|---|---|---|---|---|---|---|
| S042 | 30.0 | sky_edge | 60 | 32 | 0.5333 | 1 | 29.956 | 54.511 |
| S046 | 30.0 | sky_edge | 60 | 32 | 0.5333 | 1 | 29.956 | 54.51 |
| S041 | 28.0 | canopy | 64 | 36 | 0.5625 | 3 | 27.954 | 54.573 |
| S037 | 18.0 | canopy | 146 | 88 | 0.6027 | 14 | 17.928 | 44.131 |
| S039 | 24.0 | canopy | 66 | 52 | 0.7879 | 18 | 23.899 | 44.902 |

Read the worst row as the safety statement it is: lose 1 pixel(s) of the bird's silhouette to a different sub-pixel placement, to antialiasing, or to the motion this static dataset does not contain, and the SAME detection reports the canopy's depth instead — a bird at ~30 m published at ~54 m, which is no threat at all. **The published `range_error_p95` of 0.1076 m cannot see this**: until the flip the range is right to within 0.1362 m. It is not a bar because this fix round is the first run that measures it, and a threshold invented in the same pass that first sees the number is a threshold fitted to its own data.

### FNR cells (background × range)

| cell | n | missed | FNR |
|---|---|---|---|
| canopy | 10-20m | 1 | 0 | 0.0 |
| canopy | 20-30m | 5 | 0 | 0.0 |
| ground_band | 10-20m | 7 | 0 | 0.0 |
| ground_band | 20-30m | 2 | 0 | 0.0 |
| ground_band_edge | 10-20m | 1 | 0 | 0.0 |
| sky | 10-20m | 3 | 0 | 0.0 |
| sky | 20-30m | 8 | 0 | 0.0 |
| sky | 30-40m | 10 | 0 | 0.0 |
| sky | 40-50m | 8 | 0 | 0.0 |
| sky_edge | 10-20m | 1 | 0 | 0.0 |
| sky_edge | 20-30m | 1 | 0 | 0.0 |
| sky_edge | 30-40m | 2 | 0 | 0.0 |

FNR is conditioned on `standoff_m > margin_m (1.5 m), unoccluded`. **That condition is vacuous for the 49 FNR_zero stations** — it excludes 0 of them (none) — which is the geometry DESIGN §2.3 predicted: in this world a sub-margin stand-off can only occur outside the ±6 m threat band. The stations it does exclude are diagnostics: ['S078', 'S048', 'S049', 'S053', 'S054', 'S076', 'S077'].

### Occlusion (group E) — expected non-detections, never misses, never FPs

- **S058**: rendered bird pixels 0 (occluder proved first: True) → expected non-detection (occluded)
- **S059**: rendered bird pixels 0 (occluder proved first: True) → expected non-detection (occluded)
- **S060**: rendered bird pixels 0 (occluder proved first: True) → expected non-detection (occluded)

## Acquisition range (DESIGN §4.4)

- **cluttered acquisition: 46.0 m** — longest contiguous prefix of the range ladder, worst background class per range, every FNR_zero station matched. First failing range: None.
- **clutter-backed only to 28.0 m** — 28.0 m (canopy), 22.0 m (ground_band), 14.0 m (ground_band_edge); every rung from 30.0 m up is sky-backed. Geometrically forced in this world, not a sampling gap: an in-band bird at 46 m and 6 m below the optical axis has its ground background at ~86 m, past the 60 m Euclidean cull, so there is nothing behind it to BE clutter. The booked number does not change; the claim's reach does.
- optical prefix (sky-backed arm, never booked): **50.0 m**.
- clamp = far_clip / `corner_ray_ratio` = 60.0 / 1.261627 = **47.558 m** on the group's live intrinsics.
- **booked = min(46.0, measured) = 46.0 m**; breakeven at 5 m/s is 33.591 m → bookable: **True**.

> measured 46.00 m QUALIFIES the booked 46.0 m and does not raise it; the best-case-scene clause loses 'no clutter' and 'blind isfinite mask' and KEEPS static vehicle, noiseless sensor and level attitude. READ THE CLUTTER CLAIM TO 28 M, NOT TO 46: clutter-backed FNR_zero stations exist to 28 m (canopy), 22 m (ground_band), 14 m (ground_band_edge), and every rung from 30 m up is sky-backed. That is geometrically forced in this world rather than a sampling gap: an in-band bird at 46 m and 6 m below the optical axis has its ground background at ~86 m, past the 60 m Euclidean cull, so there is nothing behind it to be clutter. The booked number does not change

**Read the number as `≥`, not `=`.** NO station in the scored set failed, so the measured prefix is the LAST RUNG OF THE LADDER and not a detector horizon: read it as '>= this range', which is exactly why the §4.4 rule lets it QUALIFY the booked number and never raise it. Raising a booked horizon needs its own gate, on a flown take.

| range (m) | n | matched | worst background | all matched |
|---|---|---|---|---|
| 14.0 | 6 | 6 | sky | True |
| 16.0 | 3 | 3 | sky_edge | True |
| 18.0 | 4 | 4 | sky | True |
| 20.0 | 6 | 6 | sky_edge | True |
| 22.0 | 4 | 4 | sky | True |
| 24.0 | 1 | 1 | canopy | True |
| 26.0 | 4 | 4 | sky | True |
| 28.0 | 1 | 1 | canopy | True |
| 30.0 | 5 | 5 | sky_edge | True |
| 32.0 | 3 | 3 | sky | True |
| 34.0 | 2 | 2 | sky | True |
| 38.0 | 2 | 2 | sky | True |
| 40.0 | 1 | 1 | sky | True |
| 44.0 | 2 | 2 | sky | True |
| 46.0 | 5 | 5 | sky | True |

## Near field and object size — a SYNTHETIC arm, and the one correction it forces

*SYNTHETIC analytic spheres against sky -- not a render measurement.* The dataset's nearest station is 14 m and its only object radius is 0.18 m, so the near field and the large-object case are unmeasured by it.

**Resolving floor, re-measured against THIS operator: 2.0 px → 46.8 m for a 0.18 m target.** Closes the re-measurement config/depth_camera.json:min_resolving_radius_source BOOKED for the segmenter session, and ADR-020 am. 1 open item 3 with it. depth_detect.MIN_RESOLVING_RADIUS_PX = 2.0 px was measured through the NDVI detector's morphology, which this segmenter does NOT use. Re-measured against the adopted operator at the worst sub-pixel placement it is 2.0 px -> 46.8 m for a 0.18 m target, i.e. the booked geometric bound is REPRODUCED rather than moved -- and that is arithmetic coincidence, not inheritance: it comes from min_area_px, where the NDVI number came from a 3x3 cross opening. It sits just BELOW the 47.558 m corner clamp, so on this sensor the morphology binds the horizon by 0.76 m rather than the far cull. The pre-registered min_area rule cost horizon here and the number is on the record: at min_area_px=6 the floor is 1.6 px -> 58.5 m. Both are above the 46.0 m booked range, so the booked number does not move either way.

| bird range (m) | 46.0 | 30.0 | 20.0 | 16.0 | 14.0 | 12.5 | 12.0 | 10.0 | 8.0 | 6.0 | 4.0 | 3.0 | 2.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| apparent diameter (px) | 4.1 | 6.2 | 9.4 | 11.7 | 13.4 | 15.0 | 15.6 | 18.7 | 23.4 | 31.2 | 46.8 | 62.4 | 93.6 |
| components | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 4 | 4 | 4 | 4 | 4 |

one component down to 10 m, then 4 rim arcs from 8 m in; the pinhole prediction 2*fx*R/K = 12.48 m brackets it — a 0.18 m bird is never invisible over 46 → 2 m; below the crossover it returns as rim arcs at its own correct depth, which is what the one-to-many clause of the matcher exists for.

| object radius | blind ranges (m) | blind from apparent diameter (px) |
|---|---|---|
| `radius_0.18m` | [60.0] | 3.1 |
| `radius_1.3m` | [20.0, 10.0, 5.0] | 67.6 |
| `radius_5.0m` | [60.0, 40.0, 25.0, 20.0, 15.0, 10.0, 5.0] | 86.7 |

> **MEASURED CORRECTION to DESIGN §2.5 and ALGORITHM §2.4: a near object wide enough that the closing's erosion can recover its own depth across the whole silhouette produces ZERO candidates -- not a ring. A 1.3 m canopy sphere is invisible inside ~25 m and a flat 300 px wall at 8 m is invisible entirely. In THIS world the large objects are the mapped, geofenced trees and the unplanned obstacle is a 0.18 m bird detectable to ~2 m, so the mission case holds -- but an unplanned LARGE obstacle at close range is a named blind spot of this operator, and no bar on this dataset can see it.**

## Two objects at once — the mission's own obstacle density, unmeasured by the render

*SYNTHETIC two-object construction -- not a render measurement.*

| construction | `link_break=False` | `link_break=True` |
|---|---|---|
| `small_pair_3x4_px` | 1 box(es) at [25.0] m | 0 box(es) at [] m (cut 6 px, 2 below min_area) |
| `large_pair_3x20_px` | 1 box(es) at [25.0] m | 2 box(es) at [20.0, 30.0] m (cut 6 px, 0 below min_area) |

1. **two touching near objects at 20.0 m and 30.0 m return ONE component reporting [25.0] m. The dataset's nearest analogue is the partial fusion at S042/S046 (bird plus canopy rim), which reports the bird's depth ONLY because the bird holds 53% of the pixels -- see metrics.median_flip_margin. Every one of the 85 stations has exactly one bird in the world (birds 1 and 2 are parked at (-200, -190/-180, 50)), so multi-object merging is UNMEASURED on the render and this is the direction it fails in.**

2. with the rule ON the small pair returns 0 boxes: the seam cut drops both halves below min_area_px. The large pair returns [20.0, 30.0] m, i.e. the rule does what it promises whenever both sides clear the floor -- so this is an INTERACTION with min_area_px, not a defect of the cut, and the honest statement of the guarantee is 'withholds no component still larger than min_area_px after the cut'.

## Group D — where the margin's own boundary falls

| station | declared step (m) | measured stand-off (m) | range (m) | v px | detected |
|---|---|---|---|---|---|
| S048 | 0.75 | 0.573 | 43.04 | 384.44 | no |
| S049 | 1.5 | 1.323 | 42.29 | 384.45 | **yes** |
| S050 | 3.0 | 2.823 | 40.79 | 384.44 | **yes** |
| S051 | 6.0 | 5.826 | 37.79 | 384.45 | **yes** |
| S052 | 12.0 | 11.831 | 31.79 | 384.44 | **yes** |
| S053 | 0.75 | 0.577 | 33.07 | 425.71 | no |
| S054 | 1.5 | 1.327 | 32.32 | 425.71 | **yes** |
| S055 | 3.0 | 2.82 | 30.82 | 425.71 | **yes** |
| S056 | 6.0 | 5.827 | 27.82 | 425.71 | **yes** |
| S057 | 12.0 | 11.832 | 21.82 | 425.71 | **yes** |

## Pitched arm (group I, S080–S085) — its own block, never folded into a bar

The dataset's only non-level stations: −12.5° nose-down, the flight's worst observed attitude (ADR-020 am. 2). DESIGN §2.6 failure mode 3 called the level-camera derivation a named transfer gap; this measures it, on 5 bird stations and 1 negative.

- detected: **5/5** (FNR 0.0), misses none
- range error median / p95: 0.0581 / 0.0641 m over 5 matches
- unmapped FP: 0.0 /frame over 1 frame(s); mapped 20.0

| station | range (m) | background | matched | centroid err (px) | depth err (m) |
|---|---|---|---|---|---|
| S080 | 14.53 | canopy | True | 0.347 | 0.0526 |
| S081 | 20.39 | sky_edge | True | 0.132 | 0.0641 |
| S082 | 30.15 | sky | True | 0.194 | 0.0581 |
| S083 | 39.91 | sky | True | 0.162 | 0.0532 |
| S084 | 45.77 | sky | True | 0.114 | 0.0593 |
| S085 | None | none_target_parked_out_of_world | False | None | None |

## Mutation check — each mask conjunct deleted in turn (DESIGN §4.5.3)

| removed term | canned boxes | dataset boxes | dataset FNR misses | unmapped FP/frame | suite |
|---|---|---|---|---|---|
| *(none — intact)* | 1 | 1358 | 0 | 0.0 | — |
| `isfinite` | 1 | 1358 | 0 | 0.0 | GREEN — term not load-bearing |
| `clip_window` | 2 | 1358 | 0 | 0.0 | **RED** |
| `step_over_margin` | 1 | 121 | 20 | 0.0 | **RED** |
| `isfinite+clip_window` | 3 | 1358 | 0 | 0.0 | **RED** |

**Finding.** MEASURED, and it is the mutation check doing its job rather than failing it: deleting `isfinite` ALONE changes nothing, on the canned frame or on all 85 dataset frames, because the exclusive clip window already rejects every non-finite value -- `-inf > near_m`, `+inf < far_m` and every NaN comparison are all False. The three pre-registered conjuncts are therefore only TWO independent terms. Deleting the PAIR is red (the -inf blob returns as a candidate with an infinite step), which is the mutation that actually exercises non-finite rejection. `isfinite` is kept in the source because it states the intent the clip window only implies, and because a future window that is not exclusive at both ends would make it load-bearing again -- but it is documented here as redundant so nobody counts it as a second, independent safeguard.

## Per-group results

| group | world | stations | visible birds | sub-margin (diag) | matched / scoreable | unmapped FP |
|---|---|---|---|---|---|---|
| 1 | dset1 | 10 | 9 | 1 | 8/8 | 0 |
| 2 | dset2 | 42 | 38 | 4 | 34/34 | 0 |
| 3 | dset3 | 16 | 15 | 0 | 15/15 | 0 |
| 4 | dset4 | 4 | 3 | 0 | 3/3 | 0 |
| 5 | dset5 | 2 | 1 | 1 | 0/0 | 0 |
| 6 | dset6 | 2 | 1 | 1 | 0/0 | 0 |
| 7 | dset7 | 2 | 1 | 0 | 1/1 | 0 |
| 8 | dset8 | 1 | 0 | 0 | 0/0 | 0 |
| 9 | dset9 | 6 | 5 | 0 | 5/5 | 0 |

Sub-margin stations are group D and group H diagnostics — a bird 0.3–0.6 m in front of a canopy at 33–43 m, which is a **known physical limit of a discontinuity test**, not a detector miss, and is ~11.8 m below cruise in every case (outside the ±6 m threat band). They are excluded from the FNR bar by the pre-registered condition and listed by name above.

## Fixtures committed as the regression set

| station | size (KB) | < 500 KB | why |
|---|---|---|---|
| `S015` | 15.7 | True | sky, 46 m, down the worst-clutter lane -- the far end of the FNR bar |
| `S026` | 23.8 | True | ground_band MERGE: bird 5 m below cruise at 14 m, projected into the ground band |
| `S036` | 16.2 | True | trunk_edge MERGE: the bird's footprint straddles a trunk base and the ground behind it |
| `S040` | 15.7 | True | canopy-backed threat bird at 26 m |
| `S061` | 15.7 | True | NEGATIVE CONTROL, P1 worst-clutter lane -- no bird in the world at all |
| `S080` | 24.4 | True | PITCHED arm: -12.5 deg nose-down, the level-camera transfer gap made a measurement |

## What this run does NOT measure

Computed on python 3.9.6 / numpy 1.26.4 / scipy 1.13.1 (darwin). CI pins requirements-eval.txt: numpy==2.5.1, scipy==1.18.0 (python 3.12); the flight container is sim/docker/Dockerfile python3-numpy/python3-scipy, jammy: numpy 1.21.5, scipy 1.8.0 (python 3.10) — three different stacks, and the 3-decimal fixture assertions have only ever run on this one.

- STATIC VEHICLE. Every frame is a parked teleport; motion blur, rolling shutter and pose/frame pairing error are not in this measurement.
- NOISELESS SENSOR (proposed TG-6). gz writes no depth noise. Noise enters the maximum_filter as a max over K^2 samples, which is biased UPWARD -- it inflates the background and pushes FP up rather than FN, the safer direction, but it is unquantified.
- ONE TARGET RADIUS. Every station uses the world's 0.18 m bird; the resolving floor's sensitivity to target size is unbounded by this run.
- ONE TARGET PER FRAME. Every one of the 85 stations has exactly one bird in the world (birds 1 and 2 are parked out of every frustum), while CLAUDE.md's MVP obstacle density is 2-3 scripted birds. Multi-object merging is therefore UNMEASURED on the render, and `multi_object_probe` shows the direction it fails in: two touching near objects return ONE component at a median belonging to NEITHER (20 m beside 30 m reads 25 m). The cheap close is one extra teleport per camera pose in whatever renders next.
- VERSION SPREAD. The constants and every 3-decimal number here were computed on the `environment` block's stack. CI runs the pinned numpy 2.5.1 / scipy 1.18.0 on python 3.12 and the flight container runs jammy's numpy 1.21.5 / scipy 1.8.0 on python 3.10 -- and the artifact test asserts box counts and depths out of a scipy morphology, while DESIGN §1.4 claims byte-identical output on any machine with the pinned scipy, which has never been executed on either target. BOOKED, 60 seconds on the next container session: `python3 -m pytest tests/fieldguard_planning/test_depth_segment.py -q` inside the sim image. If scipy 1.8.0 moves one pixel on one fixture, the 3-dp assertions in test_depth_segmenter_score_artifact.py are where it surfaces.
- LEVEL ATTITUDE for every bar. The pitched arm is 5 bird stations at one attitude, reported separately; roll is not sampled at all.
- HOST TIMING. The runtime numbers are macOS; the container measured ~1.2x on comparable work and the number that settles it is the first flight's own counter.
- ONE WORLD. Eight camera poses in one orchard; foliage here is a smooth sphere, and real foliage has self-depth structure with pits narrower than K.

## Post-QA container check (orchestrator, 2026-09-07 ~11:20Z) — the VERSION SPREAD gap's container half CLOSES

Run inside the pinned sim image (`fieldguard-sim`, python 3.10.12 / numpy 1.21.5 / scipy 1.8.0), on the same tree
that produced the artifact above:

```
python3 -m unittest discover -s tests/fieldguard_planning -p "test_depth_segment*.py"   # Ran 59 tests, OK
```

Both new test files pass there — including the six fixtures' 3-decimal box/depth assertions — so the flight
container's scipy 1.8.0 morphology reproduces the host's numbers on those frames. The CI stack (numpy 2.5.1 /
scipy 1.18.0 / python 3.12) is exercised by the first push of this branch; it remains the one unexecuted target.

## Provenance files beside this report

- `stations_rendered.json` — the EXACT station file the renderer consumed: the tech-lead's 79 stations
  (`docs/design/depth_segmenter_stations.json`, v1.0) plus the six pitched-arm stations S080–S085 (v1.1; group I,
  `cam_rpy_deg` [0, 12.5, 90] = nose-down 12.5°, diagnostic). `labels.jsonl` embeds each station record verbatim.
- `CAPTURE_LOG.txt` — the harness log: every vehicle/link/bird readback, per-station frame sha1 / finite fraction /
  nearest finite depth, and the final tally (85/85, 82 distinct sha1, repeats = the three P1 occlusion stations).
- `eval/capture_depth_dataset.sh` — the in-container harness (one gz launch per camera pose, zero-g, readback-verified
  teleports, committed 125×110 plane asserted, bird_1/bird_2 parked). `labels.jsonl`, the 85 `.npy` frames and the
  per-group `camera_info_dset*.json` are NOT committed (~100 MB); they regenerate from the harness + this station file.

