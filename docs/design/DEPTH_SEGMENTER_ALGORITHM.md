# The depth segmenter — algorithm, measured

**Owner:** perception-ml-engineer. **Status:** SUPERSEDED AS THE MODULE OF RECORD (2026-09-10) —
the operator that ships is `src/fieldguard_planning/depth_segment.py`, scored by ADR-021 and wired
behind `--detection-source depth`. This note is kept for the *derivations*: it is where each
constant's sweep is written down. **Its numbers came from the prototype, which shipped different
constants** — see the artifacts table.

**Companion:** `docs/design/DEPTH_SEGMENTER_DESIGN.md` (tech-lead) owns the architecture, the
contract and the dataset spec. This note owns the *operator*, its constants, and the numbers that
chose them. Where the two disagree, §8 says so explicitly rather than quietly.

**Artifacts**

| file | what it is |
|---|---|
| `src/fieldguard_planning/depth_segment.py` | **THE MODULE OF RECORD** — the operator that flies, its `DEFAULT_PARAMS` and their `DEFAULT_PARAMS_PROVENANCE`, scored 7/7 by ADR-021 |
| `tests/fieldguard_planning/test_depth_segment.py` | its tests, in CI |
| `eval/score_depth_segmenter.py` + `eval/results/depth_segmenter_score_20260907T110000Z.json` | the 85-station cluttered score that chose the shipped constants |
| ~~`eval/depth_segmenter_proto.py`~~ + its 24 orphan tests | the prototype this note was written against — **DELETED 2026-09-10** (ADR-022: it ran in neither CI job and duplicated a module that ships) |

> **READ THE CONSTANTS OUT OF `depth_segment.py`, NOT OUT OF THIS NOTE.** The shipped values are
> **K 15, margin 1.5 m, min_area 10 px, open_iter 0, max_boxes 64** (chosen by the pre-registered
> sweep rules on the 85-station cluttered render). The prototype this note measured used **margin
> 1.2 m / min_area 6 px** — two of five differ, and where they do, the shipped value wins.

Every number here was produced by that module on the 12 commissioned depth frames (run 2 + probe 5)
or on synthetic frames it renders itself. Nothing in this note is asserted from prose.

---

## 1. The problem the `isfinite` gate cannot solve

Gate D3 and the booking gate segmented birds with a blind `isfinite` mask. That works in the
**check world only**, because there the bird's background is sky. In the mission world the finite
class also contains:

* the **ground band** — rows 374-479 in the commissioned frames, Z 32.568-58.0 m;
* the **tree canopies** — in frame from ~24 m.

A bird projected into the ground band is 4-connected to the ground, so `isfinite` yields one
~62,000-px component. An area ceiling then deletes it and **no counter moves**. So the mask cannot
be *"is there a return"*; it has to be *"is this return significantly nearer than what is behind
it"*.

---

## 2. The rule

```
bg   = closing(z, K)            = minimum_filter(maximum_filter(z, K), K)
step = bg - z
cand = isfinite(z) & (near_clip < z < far_clip) & (step > margin)
cand = link_break(cand, z, margin)          # §2.3
label 8-connected -> min_area -> per-component (bbox, median depth, centroid, area, tags)
```

`closing` is the depth field **with every pit narrower than K px filled in**. That is the definition
of "what is behind this pixel", and it is the whole design.

### 2.1 Why a closing, background by background

| background | what the closing does | measured |
|---|---|---|
| **sky (+inf)** | the bird is a narrow valley in an `+inf` field, filled back to `+inf` | `step = inf`; detected at every range in the sweep, 10 m to 58 m |
| **ground band** | a **monotone ramp** has no pits, so the closing reproduces it | **0 candidate pixels** over the whole 62,534-px band |
| **far cull (finite → +inf at row 374)** | a ramp *ending* is not a pit | **0 candidate pixels** at the horizon row |
| **canopy** (wider than K) | it is its own background, rim included | **0 candidate pixels**; a bird in front of it is a pit and is detected at its own depth |
| **trunk** (narrower than K) | it *is* a pit, so it *is* a candidate — correctly, it is a near object | needs §2.3, or a bird crossing it inherits its depth |

The **only** non-zero residual on the analytic ground model is a **frame-border artifact**: within
K/2 rows of the image bottom there is no farther row to erode back with. Measured max residual over
the band, and where it lives:

| K | max residual | rows carrying it | residual above 40 m |
|---|---|---|---|
| 15 | **0.981 m** | 473-479 | **0.000 m** |
| 21 | 1.419 m | 470-479 | 0.000 m |
| 31 | 2.176 m | 465-479 | 0.000 m |
| 61 | 4.664 m | 450-479 | 0.000 m |

(Independent agreement worth recording: the design note's analytic check found **1.425 m at K=21**;
this one measures **1.419 m**. Two derivations, same number.)

Border mode is irrelevant and was checked: `nearest`, `reflect` and `mirror` give a bit-identical
residual, because the ramp is *truncated by the image*, which no padding rule can restore. `wrap` is
worse (2.022 m at K=15) and is the one to avoid.

### 2.2 The margin — and why it does **not** scale with range

`margin(z) = max(MARGIN_ABS_M, MARGIN_FRAC * z)`, with **`MARGIN_ABS_M = 1.2`** and
**`MARGIN_FRAC = 0.0`**.

* float32 over 60 m quantises at ~4e-6 m. **Precision is not what the margin clears** — background
  structure is.
* `1.2 m` is **1.22× the measured worst-case residual** (0.981 m at K=15).
* `MARGIN_FRAC = 0.0` is the counter-intuitive half and it is measured, not assumed. For a depth
  camera **background depth structure is metric**: a canopy 1.5 m deep is 1.5 m deep at 20 m and at
  50 m. What changes with range is how many *pixels* that structure subtends — which is **K's**
  business, not the margin's. The measurement agrees: the residual is 0.981 m in the 32-40 m rows
  and **exactly 0.000 above 40 m**. It *falls* with range, because it is an edge effect, not an
  angular one. The knob exists for the cluttered dataset to set from evidence; shipping it non-zero
  today would be a constant invented from prose.

**The cost, which is a false-negative mechanism and therefore a label field.** A bird less than
`margin(z)` in front of the surface behind it is not separable from it. 1.2 m is **0.24 s of closing
at 5 m/s**. Measured boundary against a synthetic canopy: **1.0 m standoff MISSES, 1.5 m standoff
DETECTS.**

One refinement the measurement produced: against a *sloped* background the standoff varies across
the bird's own footprint, so a bird at nominal 1.0 m standoff over the ground band can still be
detected via the top of its footprint (measured at v=400, where the ramp adds 0.3 m over 2 rows).
`standoff_m` in the labels is the standoff **at the bird's centre**, and the ± is the footprint
height times the background's depth gradient.

### 2.3 The link break — the one rule the design note does not have, and the case that needs it

Two 8-adjacent candidates whose depths differ by more than `margin` are cut apart before labelling.

Measured on a synthetic tree trunk (0.3 m wide at 24 m = 6.5 px, narrower than K, over the ground
band) with a bird at 20 m crossing it:

| | components | reported depth |
|---|---|---|
| **without link break** | **1** | **24.0 m** — the bird is invisible and the answer is 4 m too far |
| **with link break** | 3 (trunk above, **bird 52 px @ 20.000 m**, trunk below) | correct |

That is the failure mode the design note itself calls *"worse, because it looks like success"*, and
the check world already contains the geometry (`trunk ≡ bird_1` was the same confusion on the other
sensor). It is surgical: a bird's own rim pixels have no candidate neighbours outside the bird, so
their local spread is the bird's own diameter (0.15-0.18 m measured), far under any margin. Cost
**3.7 ms**; `link_cut_px` is a counter.

### 2.4 K — the only shape parameter, pinned in both directions

**K is the largest apparent size an object may have and still be reported WHOLE.** Wider than K and
it is not a pit, so only a rim of it is flagged: still detected, still at its own correct depth, but
as **arcs** rather than a blob. Crossover `= 2·fx·R/K`; for a 0.18 m bird at K=15 that is **12.48 m**.

| K | margin | ground FP px | canopy FP px | whole-object beyond | near limit | standoff resolved |
|---|---|---|---|---|---|---|
| **15** | **1.2** | **0** | **0** | 12.48 m | 2.85 m | **1.5 m** |
| 21 | 2.0 | 0 | 64 (4 comps) | 8.91 m | 1.65 m | 2.5 m |
| 25 | 2.0 | 0 | 64 | 7.49 m | 1.00 m | 2.5 m |
| 31 | 2.5 | 0 | 176 | 6.04 m | 0.55 m | 3.0 m |
| 31 | 3.0 | 0 | 176 | 6.04 m | 0.55 m | **none ≤ 3 m** |

**K=15 / margin 1.2 is the only operating point in this table with zero false candidates on BOTH
backgrounds**, and it resolves the tightest standoff. What it gives up is near-field: the bird
breaks into arcs below 12.48 m instead of below 8.91 m. Since the booking gate needs detection at
20-46 m and anything inside 12 m is already past the commit point, that trade is taken. The
canopy-FP column is the one that would move with real foliage rather than a flat disc, so **the
cluttered dataset should re-run this table before K is frozen** (§7 pre-registers the prediction).

Cost is **flat in K** (scipy's separable rank-filter path): 4.07 ms at K=15, 4.28 ms at K=61. So K
is chosen on accuracy alone.

### 2.5 Morphology and area — re-derived for the DEPTH render, inherited from nothing

* **No opening.** `ndvi_detect.detect_blobs` opens with a 3×3 CROSS. The real depth bird patch is a
  **12-px plus** from ~40 m out, and the cross-opening **erases it** (probe 5, `frame_46_on`: raw
  12 px → post-morphology **0 px**). This is the single most important thing not to inherit.
* **No binary closing.** The depth mask on a noiseless render has no speckle to fill, and a close can
  *bridge* a bird to an adjacent candidate — the merge the whole design exists to prevent.
* **`min_area = 6 px`**, the NDVI arm's number, reused because it is **non-binding here**: the
  smallest real bird patch measured anywhere on this render is **12 px** (at 46 m *and* at 58 m — the
  render's antialiasing floors the footprint), so there is 2× headroom. A second constant would need
  a second justification.
* **No `max_area`, at all.** An area ceiling is precisely the mechanism that silently deletes a bird
  merged into something larger. Oversize is a tag and a counter, never a drop.

**The resolving floor, re-measured** (this is the gap `config/depth_camera.json:
min_resolving_radius_source` books for this session), at the worst sub-pixel placement over
{0, 0.25, 0.5} px in both axes:

| morphology | min resolving radius | 0.18 m bird reaches it at |
|---|---|---|
| NDVI's open→close + min_area 6 | **2.0 px** (reproduces the booked number exactly) | 46.80 m |
| **this segmenter (no open, min_area 6)** | **1.6 px** | **58.50 m** |

So the detector's morphology is **no longer the binding horizon** — the far cull is
(`far/|ray|`: 60.0 m on axis, 47.56 m at the corner; D2 measured the greatest finite Z-depth at
57.99 m). Consequence for the booking gate: the 58.0 m the D3 sweep measured is **not** reduced by
this segmenter, so ADR-020's booked lead stands. Per §4.4 of the design note that **qualifies**
46.0 m and does not raise it.

### 2.6 Range comes from the sensor, not from a prior

ADR-009 rule 2 holds — never a ground-plane projection — but the apparent-size ray it mandated is
**superseded by a measurement**: the component's median depth *is* the range. The 0.15 m radius
prior therefore stops being a range input and becomes a **checkable** quantity: a component of area
A at depth z has apparent radius `sqrt(A/π)`, and a 0.15 m sphere at z subtends `fx·0.15/z`. That
ratio is reported per component (`size_ratio`, measured **1.15-1.45** across the 10 detected real
frames).

**It is a tag, not a filter, and the reason is measured:** a canopy-rim fragment at 24 m (from the
rejected median background) is **31 px** against the **33 px** a 0.15 m bird subtends at that range.
Apparent size *cannot* tell them apart. Any size band must come from the cluttered dataset's
negatives, not from the positives alone; both bounds default to `None`.

Reported depth is the component **median**. Measured bias against the sphere's nearest surface:
**+0.045 to +0.144 m**, always positive, always under the object's radius — i.e. the median places
the bird slightly **farther** than its nearest surface, which is the fail-dangerous direction.
`depth_p05_m` is carried alongside as the safety-forward alternative and the seam can switch with
one field.

### 2.7 Refusals — and the one thing a caller must never do

| input | answer | why |
|---|---|---|
| whole-frame or blob-sized `-inf` | **`refused = "near_clip"`** | something is inside 0.1 m. There is no range for it, so there is nothing honest to report |
| a single stray `-inf` pixel | counted, mapped to `+inf`, frame proceeds | but removed **before** the closing: one `-inf` would be spread over a K×K window by the erosion and blind it |
| `NaN` | mapped to `+inf`, counted | an unknown background is treated as far — the direction that *produces* detections rather than hides them |
| finite `≤ near_clip` or `≥ far_clip` | excluded, counted `invalid_range_px` | a value **at** a clip plane is the clamp signature, not a measurement |
| all sky | `components = []`, **`refused = None`** | the sensor answered and the answer was "nothing in range". Different fact from "I could not tell" |

**`refused` is not "no obstacles".** A caller that reads `not result.components` as *clear* without
checking `refused` has reproduced the defect `score.py.evidence_shortfall()` exists to prevent.
`SegmentResult` also carries `nearest_withheld_depth_m` so that anything dropped for any reason is
still visible in the flight log.

---

## 3. Score on the 12 real frames

*(Historical: run with the now-deleted prototype at its own defaults, match radius 12 px. The
equivalent today is `python3 eval/score_depth_segmenter.py`, which scored the shipped module on 85
cluttered stations — a superset of these 12.)*
Depth error is against the sphere's **nearest surface** (`centre − 0.18`), the quantity a clearance
is measured from. Centroid error is on the **bbox midpoint**, which is what the seam consumes.

| frame | bird | background | outcome | centroid err px | depth err m | area px | size_ratio | cull headroom m | false comps |
|---|---|---|---|---|---|---|---|---|---|
| `frame_10` | 10.0 m on-axis | sky | **det** | 0.00 | +0.0505 | 276 | 1.19 | 50.13 | 0 |
| `frame_40` | 40.0 m on-axis | sky | **det** | 0.00 | +0.0479 | 16 | 1.15 | 20.13 | 0 |
| `frame_46` | 46.0 m on-axis | sky | **det** | 0.00 | +0.0668 | 12 | 1.15 | 14.11 | 0 |
| `frame_58` | 58.0 m on-axis | sky | **det** | 0.00 | +0.1442 | 12 | 1.45 | 2.04 | 0 |
| `frame_offaxis` | 20.0 m @ (560,120) | sky | **det** | 0.00 | +0.0581 | 78 | 1.27 | 33.44 | 0 |
| `frame_near` | 0.25 m, whole frame −inf | near clip | **REFUSED-ok** | — | — | — | — | — | 0 |
| `frame_46_on` | 46.0 m on-axis | sky | **det** | 0.00 | +0.0668 | 12 | 1.15 | 14.11 | 0 |
| `frame_46_u50` | 46.0 m, +0.5 px u | sky | **det** | 0.00 | +0.0446 | 12 | 1.15 | 14.14 | 0 |
| `frame_46_d50` | 46.0 m, +0.5 px u,v | sky | **det** | 0.00 | +0.0506 | 13 | 1.20 | 14.13 | 0 |
| `frame_cull_z50` | 50.0 m @ (580,60) | sky | **det** | 0.00 | +0.0612 | 14 | 1.35 | 1.36 | 0 |
| `frame_cull_z52` | 52.0 m @ (580,60), **culled** | sky | **miss-ok** | — | — | — | — | — | 0 |
| `frame_below_z46` | 46.0 m, 6 m below axis | sky | **det** | 0.17 | +0.0670 | 14 | 1.24 | 13.61 | 0 |

```
visible bird-frames (denominator): 10   detected: 10   FNR: 0.0000
false components/frame: 0.000   over 12 frames
```

**Read this narrowly.** Four caveats, in order of how much they matter:

1. **Every one of these birds is SKY-BACKED.** `frame_below_z46` is the only clutter-*adjacent*
   case, and it is still sky-backed: at row 308 the ground would be at `fy·15/68.5 = 113.9 m`,
   beyond the cull, so the pixel behind it is `+inf`. It sits 66 rows above the ground band's top
   edge. **The FNR 0.000 above is a sky-background number and nothing else.**
2. **The ground band is identical in all 12 frames** (static camera, static world). The 0.000
   false-components figure is **one background geometry measured 12 times**, not 12 independent
   samples.
3. **n = 10.** No confidence interval is available and none is quoted.
4. `frame_cull_z52` is a *correct* miss — the bird is beyond the Euclidean cull at that pixel
   (60/1.1704 = 51.26 m), so the renderer returns `+inf` and there is nothing to detect. It is
   scored as `miss-ok`, not as a hit and not as a false negative, because the label says so.

---

## 4. Synthetic stress frames (in the self-test)

| case | expectation | measured |
|---|---|---|
| ground-band bird, 20/30/20/25 m at rows 400/440/470/390 | detect, own depth, ground not reported | **1 component each, depth exact to 1e-3 m** |
| canopy alone (flat disc, 140 px, 24 m) | 0 candidates | **0** |
| bird 20 m on canopy interior (u=340) | detect at 20 m | **1 comp, 20.000 m** |
| bird 20 m straddling the canopy outline (u=410) | detect at 20 m, no depth inheritance | **1 comp, 20.000 m** |
| bird 30 m **behind** the canopy | miss — and the bird must contribute **0 pixels** first | **0 bird px asserted, then 0 components** |
| trunk (6.5 px @ 24 m) + bird 20 m crossing it | bird at 20 m, trunk separate | **with link break: 20.000 m. Without: 1 comp @ 24.0 m** |
| two birds 16 px apart at 20 m | 2 components | **2** |
| pure sky | `[]`, **not** refused | as expected |
| all `-inf` | **refused `near_clip`** | as expected |
| one stray `-inf` px | counted, frame still detects | as expected |
| a 20×20 patch at exactly 60.0 m | `invalid_range_px = 400`, no detection | as expected |

An occlusion test that does not first assert the occluder occluded is not a test — it passes for a
detector that never detects anything. `test_bird_beyond_a_canopy_is_missed_because_it_is_occluded`
asserts the zero-pixel count **before** it asserts the miss.

### 4.1 The resolving floor and the near field

* **Resolving floor: 1.6 px** (worst sub-pixel placement) → a 0.18 m bird reaches it at
  **58.50 m**, against **2.0 px / 46.80 m** for the NDVI morphology measured in the same function.
* **Whole-object crossover: 12.48 m.** Beyond it, one component. Closer, the object returns as **4
  arcs** of its own rim, each at its correct depth, with bbox midpoints offset from truth by
  ~`fx·R/z`:

  | range | 16 m | 12.5 m | 10 m | 8 m | 6 m | 4 m | 3 m |
  |---|---|---|---|---|---|---|---|
  | components | 1 | 1 | 1 | **4** | 4 | 4 | 4 |
  | offset px | 0.0 | 0.0 | 0.0 | 10.5 | 15.0 | 22.5 | 30.5 |

* **Near limit: 2.85 m.** Below that the arcs fall under `min_area`. Inside the near clip (0.1 m)
  the frame is refused. So the accounting is complete and there is no silent hole: detected → arcs →
  under-area (counted) → refused.

**This directly threatens the design note's §4.2 matcher.** Clause 1 is `τ = 5 px` on the box
midpoint. At 8 m the arc offsets are 10.5 px, so **every station inside ~12.5 m would score as a
MISS plus 4 false positives** under a one-box-per-bird matcher. See §7.

---

## 5. Runtime

Host: macOS arm64, numpy 1.26.4 / scipy 1.13.1, 640×480, n = 200 after warm-up.

| frame | median | p95 | max |
|---|---|---|---|
| `frame_46` (bird + ground band) | **10.07 ms** | 10.52 | 38.90 |
| `frame_10` (276 px bird) | 9.87 ms | 10.54 | 11.19 |
| `frame_near` (refusal, early out) | 2.86 ms | 3.01 | 3.36 |

Stage breakdown on `frame_46`: `estimate_background` **4.07 ms** (of which `maximum_filter`
2.11 ms), `_link_break` **3.73 ms**, `label` + `find_objects` **1.14 ms**, the rest ~1 ms.

**Does it fit?** The comparable *measured in-container* number is the adopted NDVI detector's
`detect_wall_ms_p95 = 8.211 ms` (max 41.917, n = 1302,
`eval/results/live_flight_log_20260825T210402Z.json`). On this host the same detector medians
**6.94 ms** on a comparable synthetic frame, so host and container are within ~1.2× for this class of
numpy/scipy work — which puts this segmenter at roughly **12 ms p95 in-container**, against the
design note's pre-registered **25 ms** bar and a 200 ms tick. At the container's measured 0.2-0.9
RTF a 5 Hz sim-time stream arrives every 222-1000 ms of wall time, so this is **1-5 % of the
budget**.

That is an extrapolation and is labelled as one. **The number that settles it already exists**:
`DepthDetectionSource.counters()['detect_wall_ms_p95']` on the first flight. If it comes in over
25 ms, cut in this order, with the measured costs:

1. **`_link_break` → 3.73 ms.** It runs its two 3×3 rank filters over all 307,200 pixels when only
   the candidates matter (510 on a real frame). Gathering 3×3 neighbourhoods for candidate indices
   only is the same result at ~0.2 ms. **Do this first — it is a pure win with no accuracy cost.**
2. **Drop `depth_p05_m`** (one `np.percentile` per component) — negligible unless components are
   many; it exists for a decision not yet taken.
3. **Raise K.** Cost is flat in K, so this buys nothing — do *not* reach for it as a speed knob.
4. **Only then**: run the closing at half resolution and upsample. Costs accuracy at the small-target
   end (the 12-px patch at 46 m is 3 px at half res) and would need the whole §3 table re-run.

---

## 6. What was rejected, with its numbers

| rejected | measured reason |
|---|---|
| **`isfinite` mask** (what D3 ran) | one ~62,000-px component the moment a bird crosses the ground band; deleted by any area ceiling, silently |
| **Two-stage large-window median background** (52 px; built first and fully scored) | **498 false candidate pixels in 11 components** along the far cull on the real ground band, plus **10 more** around a canopy rim — so it needs a second rule to suppress them, and that rule then has to be stopped from suppressing near birds. Also **19.6 ms** vs 10.1, and it goes **blind** (not fragmented — blind) below **4.2 m**. The closing needs no second rule at all. |
| **A "ring test"** (is the component an island, or the near side of a larger surface?) | Built and measured on the median arm, where it separated cleanly — birds 0.000-0.114, artifacts 0.482-0.524, midpoint 0.30. **Deleted with the median**: under the closing there are no artifacts for it to reject, so it would be a filter with no measured negatives that can only cost recall (it rejects the near-field rim arcs of a real bird). |
| **A far-cull-edge rejection rule** | Same fate. Its classes separated on the median arm (11 cull-edge components at `far/|ray| − z` = 0.203-0.282 m against 10 birds at 1.362-50.125 m, midpoint 0.82) and it costs 0.82 m of horizon at the frame corner. Under the closing the horizon row produces nothing, so the rule is unnecessary. `cull_headroom_m` survives as a **reported field**, because `DepthDetectionSource`'s range window uses the on-axis 60.0 m for every pixel and a corner component at 50 m is at *its own* cull while still passing. |
| **Union with a coarser background scale** (block 16, 208 px) to fix the median's near blindness | would push the near limit to ~1.1 m, but its own residual flags **9,054** ground-band pixels against the fine scale's 510 — an 18× FP cost for 3 m of range inside a regime where the encounter is already lost |
| **A size-consistency filter** | measured non-separating: a canopy-rim fragment at 24 m is 31 px against a bird's predicted 33 px |
| **Row-wise / pose-driven ground model** | needs to be told where the horizon is and what the pitch is — a value a mount error changes silently (ADR-007 am. 5). The closing is told nothing and handles canopies with the same code |

---

## 7. Pre-registered scoring bars — stated before the cluttered dataset exists

The design note's §4.3 table is **adopted as-is**. What follows is what this *operator* adds to it,
and it is registered now because three of these are predictions that can embarrass me later.

### 7.1 Falsifiable predictions

| # | prediction | what falsifies it |
|---|---|---|
| P1 | **Group D standoff ladder** (0.75 / 1.5 / 3 / 6 / 12 m): at K=15 / margin 1.2 → **0.75 MISS, 1.5 HIT, 3 HIT, 6 HIT, 12 HIT**. At the design note's K=21 / margin 2.0 → **0.75 MISS, 1.5 MISS**, rest HIT. | any other pattern means the closing residual on real clutter is larger than the analytic ground model's, and the margin must be re-derived from that data, not from this note |
| P2 | **Unmapped FP ≤ 0.05/frame is met with room**, because the ground band and canopies produce *zero* candidates by construction | a canopy with real foliage self-depth structure containing pits narrower than K would break this. This is the single most likely prediction to fail, and §7.3 says what to do |
| P3 | **Merge assertion = 0 on every trunk station**, with `link_cut_px > 0` on each | `link_cut_px = 0` on a trunk station means the trunk was not a candidate (wider than K in pixels than assumed) and the test proved nothing |
| P4 | **Range error p95 ≤ 0.15 m**, not merely the ≤ 0.5 m bar — measured spread on real frames is +0.045 to +0.144 m and always positive | a *negative* error would mean a component is being credited with a depth nearer than any surface, which is a bug, not noise |
| P5 | **Cluttered acquisition range ≥ 46.0 m**, so it QUALIFIES the booked number rather than replacing it (§4.4 of the design note) | anything below 46.0 replaces it; anything below **33.591 m** turns the booking gate red at 5 m/s, per ADR-020 am. 2 |

### 7.2 Two bars the design note's table cannot express, and must gain

* **FNR must be reported conditioned on `standoff_m > margin`.** A station whose bird is inside the
  resolving standoff is a **known physical limit**, not a detector miss, and folding it into
  `FNR_zero` makes the bar unachievable for a reason that has nothing to do with the detector.
  Proposed classes, scored separately and each with its own denominator printed:
  `detectable` (unoccluded, standoff > margin, range ≤ acq) — **bar: 0 misses**;
  `sub_margin` (standoff ≤ margin) — **reported, not barred**;
  `occluded` — **expected non-detection**, already in §4.3.
* **The matcher must be one-to-many below the whole-object crossover.** For stations at range
  < 12.48 m a bird legitimately returns up to 4 arcs at offsets exceeding τ = 5 px (10.5 px at 8 m,
  15.0 px at 6 m). Rule: **a component whose bbox intersects the bird's expected footprint disc
  (radius `fx·R/z + τ`) matches the bird and is never an FP; the bird counts as detected if at least
  one such component has a median depth within ε.** Without this, every near station scores as a miss
  *and* four false positives, and the segmenter is condemned for behaving as designed.

### 7.3 What to do if P2 fails

Do **not** reach for a size filter (§2.6 measured that it cannot separate). In order:
raise the margin (re-derive from the measured residual on real foliage, keep it metric);
then lower K (fewer pits qualify, at the cost of the whole-object crossover — the §2.4 table is the
price list); then, and only then, consider a second rule, and re-derive the ring test from §6 rather
than inventing a third.

### 7.4 Label fields this operator requires

Beyond §4.1's list, every bird record must carry — and `null` must be written explicitly, because a
missing field and a null one score differently:

| field | why the segmenter needs it |
|---|---|
| `bg_depth_m` | the Z-depth of what is **directly behind the bird's centre**, `null` for sky |
| `standoff_m` | `bg_depth_m − z_depth_m`. **The field that attributes a miss**: under `margin(z)` it is a known limit; over it, a bug |
| `background` | `sky` / `ground_band` / `canopy` / `trunk` / `*_edge`, per §4.1 — FNR is reported per class or not at all |
| `occluded` + reason | an expected non-detection, scored as its own outcome |
| `visible_px` | the rendered footprint; attributes a small-target miss to the area filter rather than to the mask |
| `expected_arcs` | `true` when `z < 2·fx·R/K`, so the one-to-many matcher (§7.2) is armed by the label and not by a magic constant in the scorer |

### 7.5 Mutation check (design note §4.5.3), predicted per term

Deleting each conjunct of `isfinite(z) & (near < z < far) & (step > margin)` must turn the suite red,
and here is what each should look like so a *silent* pass is recognisable:
drop `isfinite` → `inf − inf = NaN`, comparisons go False, **detections drop to zero** (a red that
looks like a broken detector, which is the point);
drop the clip window → the 60.0 m clamp-signature test starts detecting;
drop `step > margin` → the ground band returns as one ~62,000-px component.

---

## 8. Where this diverges from `DEPTH_SEGMENTER_DESIGN.md`

Agreement is the headline: the design note specifies a **black top-hat on depth** and this
prototype, arrived at from the frames, is the same operator. Two derivations of the border artifact
also agree (1.425 m vs 1.419 m at K=21). The differences:

| | design note | here | resolution |
|---|---|---|---|
| **K / margin** | K=21, margin ~2.0 m (argued free: minimum in-band step 16.35 m over 79 stations) | **K=15, margin 1.2 m** — the only point measured with **zero** false candidates on ground *and* canopy, and it resolves a 1.5 m standoff | Both are defensible and **group D decides it directly** (P1). Recommend running the ladder at both settings on the same frames — it costs one extra pass, not a render. |
| **link break** | not present | **present, §2.3** — without it a bird crossing a trunk reports as one component at the trunk's depth | Recommend adopting. The trunk is narrower than K and therefore *is* a candidate; this is the design note's own §2.4 merge failure, one geometry further in. |
| **matcher τ** | 5 px, one box per bird | insufficient below 12.48 m (arcs at 10.5-30.5 px) | §7.2 — the harness change is small and must land **before** scoring, not after a red run |
| **`max_boxes` / nearest-first truncation** | specified at §2.5 | not implemented here | Agreed it belongs at the **seam** (`DepthDetectionSource`), not in the operator. Noted so it is not forgotten. |
| **`NaN` handling** | "treated as `−inf`" | treated as **`+inf`** (far), counted | `−inf` triggers a refusal; a stray NaN should not ground the aircraft, and "unknown background is far" is the direction that *produces* detections. Worth one line of agreement before wiring. |

---

## 9. The three riskiest assumptions

1. **Every bird ever scored by this operator has been sky-backed.** All 10 real detections, and the
   whole D3 acquisition sweep behind the booking gate. The ground-band, canopy and trunk cases are
   **synthetic**, and their backgrounds are analytic — a flat plane and a flat disc with *zero*
   self-depth structure. Real foliage has pits, and a pit narrower than K is a candidate by
   construction. **P2 is the prediction most likely to fail and the FP bar is where it will show.**
2. **The camera is level in every frame and every model here.** `Z(v) = fy·h/(v−cy)` and the whole
   "ramp has no pits" argument assume it. The flown stack's worst observed attitude is **−12.50°**
   (ADR-020 am. 2), which moves the horizon by ~113 px and tilts the ramp. A closing is
   orientation-free, so the ramp *stays* a ramp and the argument should survive — but "should" is
   the word, and nothing here measures it. Named transfer gap, not a claim.
3. **The sensor is noiseless** (proposed TG-6), and the margin is 1.2 m against a background whose
   measured residual is an *analytic* 0.981 m. A real depth sensor's per-pixel noise enters the
   `maximum_filter` as a *maximum over K² samples*, which is biased upward — so noise inflates the
   background estimate and pushes the FP rate up, not the FN rate. That is the safer direction, but
   it is unquantified, and the day a datasheet exists both the margin and `min_area` must be
   re-measured, not scaled.
