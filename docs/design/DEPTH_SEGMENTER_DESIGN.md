# The depth segmenter — design note (becomes ADR-021 once built and gated)

**Status: DESIGN, nothing built, nothing measured on a render.** Every number below is either quoted
from a committed artifact (with its provenance) or derived from the pinhole model and labelled as a
prediction. This note is the thing the build is scored against; it is not evidence of anything.

**Owner:** tech-lead (design) → perception-ml-engineer (build + score) → flight-software-engineer
(wiring). **Blocks:** the real-detection dodge take on the forward aperture (ADR-019 / ADR-020).

**The one sentence.** The forward depth camera cannot tell a tree from a bird — it only knows
*nearer* — so the segmenter keys on **depth discontinuity against the local background**, never on
`isfinite`, and the whole design is one operator (a black top-hat on the depth image) plus one
threshold whose value is measured on a cluttered labelled dataset rather than chosen.

### Concurrent work — read this before building either

A prototype was being written in parallel with this note (`eval/depth_segmenter_proto.py`, with a
sibling `docs/design/DEPTH_SEGMENTER_ALGORITHM.md`), and the two arrived **independently at the same
core decision**: discontinuity against a local background, never `isfinite`, for the same measured
reason. That agreement is worth more than either document. **Two substantive deltas remain, and they
should be settled before the score run, not after:**

1. **Background estimator — block-median-of-medians vs morphological closing.** The prototype
   estimates `bg` as a per-block median followed by a coarse median filter over blocks, then a
   nearest upsample; it reports a ground-band residual of **mean 0.070 m / max 0.609 m** over 61,858
   pixels. This note's far-envelope closing is **exactly zero** over the frame interior on the same
   analytic ground model (and 1.425 m only in the K-wide frame border), costs **4.6 ms** where a
   naive `median_filter(size=21)` costs **1061 ms** on the host — which is precisely why the
   prototype's two-stage block scheme exists — and introduces no block quantisation. The choice
   should be made on the §4 dataset with both wired, not by argument; on cost and on ramp residual
   the closing is ahead, and the median's advantage (robustness to a foreground object filling the
   window) is what K ≥ 17 already buys.
2. **The ring test — and this one is a safety-direction disagreement, not a tuning choice.** The
   prototype **withholds** components whose dilated ring is mostly at their own depth, on the
   grounds that they are the near side of a larger surface (measured separation: birds 0.000–0.114,
   rims 0.482–0.524 — a clean split). The concern is that *"the near side of a larger surface"* is
   also what a genuinely large unplanned obstacle looks like, and withholding it happens **before**
   un-projection, i.e. before anything knows where it is. This note gets the same artifacts removed
   **for free and downstream**: a canopy rim un-projects to z ≈ 3.8 m and a cull-edge to z ≈ 0 m,
   both **outside** the policy's ±6 m vertical threat band (which starts at 9 m), so geometry after
   un-projection deletes them without an appearance test that can also delete a wall. If the ring
   test is kept, it should **tag and count, never withhold** — the same annotate-not-suppress rule
   `DepthDetectionSource` rule 9 already imposes on the static map.

Where they do not conflict, prefer the prototype: it has executable numbers and this note does not.

---

## 0. The five facts this design is built on

Everything downstream leans on these; each carries where it came from.

| # | Fact | Provenance |
|---|---|---|
| F1 | The stream is `/fg/depth/image` 32FC1 640×480, `fx=fy=520.0058046927554`, `c=(320,240)`, clips 0.1/60 m, **+inf beyond far, −inf inside near**, value stored is **pinhole Z-depth** while the far cull is on **Euclidean slant** | ADR-020 am. 1 (D2 CULL measured 57.99 m at (289, 374), \|ray\| 1.034 → 59.96 m back-solved); `config/depth_camera.json` |
| F2 | The 46.0 m booked acquisition range is a **best-case-scene UPPER BOUND** — no clutter, static vehicle, noiseless sensor, sky background, on-axis target, blind `isfinite` mask, **no segmenter**; breakeven for the 5 m/s booking gate is **33.591 m** | ADR-020 am. 2, pre-registered invalidation, verbatim |
| F3 | The target's footprint **plateaus at a 12-raw-pixel plus shape from ~40 m to 58 m** and those pixels carry the bird's **own** depth (0.02–0.16 m of true Z), not a blended edge | ADR-020 am. 2, PROBE B on run 2's retained frames; PROBE 5 sub-pixel sweep (12/14/12/13/13 px) |
| F4 | Tree canopies enter the frame from **~24.4 m** and finite ground from **row 374 / ~32.6 m at the bottom edge** — both inside the 33.59 m horizon the booking gate needs at 5 m/s | ADR-020 am. 1/2; `FORWARD_DEPTH_SENSOR.md` §7 |
| F5 | `MIN_RESOLVING_RADIUS_PX = 2.0` was calibrated on **synthetic discs through the NDVI detector's morphology** and the depth render does not shrink that way — the floor must be re-measured against **this** render, **cluttered** | ADR-020 am. 1 open item 3 (`src/fieldguard_planning/depth_detect.py`) |

And the merge hazard this note exists to close, stated by QA and recorded in the runbook's Known
gaps: *a bird projected into the ground band joins the ground component under an `isfinite` mask and
the `max_area` filter deletes the merged blob — the bird disappears, silently.*

---

## 1. The segmenter contract

### 1.1 Signature — already locked, and the design fits it as-is

`src/fieldguard_planning/depth_detect.py` defines:

```python
DepthSegmenter = Callable[[object], Sequence[Tuple[Sequence[float], float]]]
```

One argument in (the depth frame), a sequence of `([x0, y0, x1, y1], depth_m)` pairs out; boxes
half-open, `x` = column, `y` = row, in `detect_blobs`' convention so the two detectors' boxes mean
the same thing. **This design changes nothing about that signature**, which matters: the seam is
built, tested and documented, and a signature change is an ADR-020 amendment rather than a patch.

Concretely the new module is `src/fieldguard_planning/depth_segment.py` (beside `depth_detect.py`,
inside `src/` — the only tree the container, the host gates and the tests can all import; the
`eval/blob.py` mistake `ndvi_detect.py`'s docstring records is not repeated), exposing:

```python
@dataclass(frozen=True)
class DepthSegmenterParams:      # every tunable, one home, frozen
    bg_window_px: int            # K, the flat square SE of the far-envelope
    margin_m: float              # a pixel must be NEARER than background by more than this
    min_area_px: int
    open_iter: int
    max_boxes: int
    near_m: float                # clip window, EXCLUSIVE (mirrors DepthDetectionSource)
    far_m: float

class DepthSegmenter:            # callable object == the locked Callable contract
    def __init__(self, params: DepthSegmenterParams): ...
    def __call__(self, depth) -> list[tuple[list[float], float]]: ...
    def counters(self) -> dict: ...
```

The parameters are bound at **construction**, not passed per call, because the locked callable takes
exactly one argument. A frozen dataclass rather than seven keyword arguments so the flight log can
record the *whole* configuration as one object and a reader can see there is nothing else.

### 1.2 Inputs

* **`depth`**: `float32` `(H, W)` **pinhole Z-depth**, as published. Non-`float32` or non-2-D raises
  — silently coercing is how a `uint16` millimetre encoding would become a metre-valued obstacle.
* **Intrinsics: NOT an input, and that is a decision.** The algorithm below is pure image space; it
  never converts a pixel to a metre. The seam already un-projects with the **live**
  `/fg/depth/camera_info` (`DepthDetectionSource.set_intrinsics`, rule 4), so intrinsics have exactly
  one home. The only design that would need them here is a pose/attitude-driven analytic ground
  model — rejected in §2.4 — and one reason to reject it is precisely that it would force intrinsics
  *and* attitude through a locked one-argument seam.
* **Static map: NOT an input.** `DepthDetectionSource.static_map_annotator` already annotates a
  detection whose **world** position falls inside a mapped obstacle, after un-projection, and
  annotates only (`Detection.static_map_hint` + counter, never a drop). A map here would have to
  suppress in **pixel** space, before a position exists, which is the one direction that can hide a
  real obstacle.

### 1.3 Outputs

The contract pair, and nothing bolted onto it:

* **box** `[x0, y0, x1, y1]` — the connected component's bounding slice.
* **depth_m** — the **median** of the component's own mask pixels. Median, not mean: a component
  clipped by an occluding edge carries a few background-side pixels, and the median is the statistic
  that ignores them. The contract's own comment says the depth comes back with the box *because the
  right statistic is a property of the segmentation mask, which only the segmenter has*.

**The centroid the policy actually gets is the box midpoint**, computed by
`DepthDetectionSource.box_to_detection` (`0.5*(x0+x1)`, `0.5*(y0+y1)`). Recorded as a known,
measured-not-assumed consequence rather than changed: for the plateau's 12-px plus the midpoint and
the centroid coincide to well under a pixel; for the ring-shaped component a large near object
produces (§2.5) the midpoint is the silhouette centre, which is the right answer; for a
half-occluded bird it biases by up to `r_px`. The dataset measures this (§4) and a change to it is a
seam amendment, not a segmenter option.

**Per-frame diagnostics ride in `counters()`**, a sidecar dict alongside `DepthDetectionSource`'s
own — never extra fields on the returned tuple:
`frames`, `candidate_px`, `components_labelled`, `components_below_min_area`, `boxes_returned`,
`boxes_truncated`, `px_pos_inf`, `px_neg_inf`, `px_nan`, `px_outside_clip_window`,
`largest_component_px`, `seg_wall_ms_p95` / `_max` / `_n`. Plain ints and floats only — this dict
crosses a `json.dumps` into the flight log, where a numpy scalar raises `TypeError`.

**Range refusal is NOT re-implemented here.** `DepthDetectionSource.box_to_detection` already
refuses a non-finite depth and any depth outside the **exclusive** `(min_range_m, max_range_m)`
window, and counts both. The segmenter's clip window (`near_m`, `far_m`) exists only to keep refused
pixels out of the *mask*; it never returns a box it expects the seam to reject, and the two windows
are pinned equal by test so there is one number, not two.

### 1.4 Determinism

Pure function of the input array. **No RNG, no wall clock, no frame-to-frame state, no learned
weights.** Same bytes in, same list out, on any machine with the pinned scipy. Two reasons, and the
second is the load-bearing one:

1. The dataset (§5) scores **one frame per station**; a detector carrying state across frames would
   make its score depend on station order, which is not a property anyone can defend.
2. A stateful background model on a vehicle moving at 5 m/s is re-learning a scene that changed 1 m
   per frame — it buys nothing and costs reproducibility on the flight.

Pinned by test: shuffle the station order, re-run, require byte-identical per-station output.

### 1.5 Runtime budget

The tick is **5 Hz → 200 ms**, and the segmenter shares the node's thread with the executor.

* **The comparable measured cost**: the adopted NDVI detector on the **same** 640×480 in the **same**
  container measured **p95 8.211 ms, max 41.917 ms over n = 1302** in-flight calls
  (`eval/results/live_flight_log_20260825T210402Z.json`, `run.detector.counters`).
* **Host timing of the proposed operator** (macOS, numpy/scipy, this session — an order of
  magnitude, not a container number): the far-envelope pass
  `minimum_filter(maximum_filter(D, size=K), size=K)` costs **4.6–6.7 ms/frame** and is **flat in K**
  from 9 to 31 px (scipy's separable rank-filter path); connected-component labelling ~**1.0 ms**.
* **Pre-registered bar, checked on the flight log and not on a bench**: `detect_wall_ms_p95 ≤ 25 ms`
  and `detect_wall_ms_max ≤ 100 ms` (half a frame period) on the counters
  `DepthDetectionSource` **already keeps**. If the depth detector runs alongside the NDVI one, the
  bar is on the **sum**, which is the number that can actually miss a tick.
* **No new dependency**: numpy + scipy are already in the image for `ndvi_detect` (`python3-scipy` in
  `sim/docker/Dockerfile`). The planning core stays stdlib; pixel math gets numpy/scipy — the same
  scoped exception, not a new one.

---

## 2. The algorithm — and what it is instead of

### 2.1 The rule, in one line

> **A pixel is an obstacle candidate iff its depth is nearer than the local far-envelope of the
> depth image by more than `margin_m`.**

Implementation — a **black top-hat on depth**, which is the boring textbook operator for "small near
structure against whatever is behind it":

```
B   = closing(D, K x K flat)     # = minimum_filter(maximum_filter(D, K), K): the LOCAL FAR ENVELOPE
step = B - D                     # how much NEARER this pixel is than its own background
mask = isfinite(D) & (near_m < D < far_m) & (step > margin_m)
label 8-connected -> components -> area filter -> (bbox, median depth of the component's pixels)
```

Five lines, one threshold, one window size. On a whiteboard it is: *dilate the depth to fill in
anything small and near, subtract, and keep what got filled.*

### 2.2 Why it holds on all four backgrounds this world has

| background | what the far-envelope does | result |
|---|---|---|
| **sky (+inf)** | the bird is a narrow valley in a `+inf` field → closing fills it to `+inf` | `step = +inf` → detected (this is D3's case, and it is the easy one) |
| **ground band** | a **monotone ramp** in depth; a flat-SE closing reproduces a monotone profile **exactly** — measured **0.0 m residual** over the frame interior on the analytic 15 m-altitude ground model, K = 21 | the ground is never its own candidate; a bird on it is a filled valley → `step` = the true 21–39 m stand-off |
| **canopy** | wider than K → interior unchanged; a bird in front of it is narrower than K → filled | `step` = bird-to-canopy gap, detected whenever that exceeds the margin |
| **cull boundary (finite → +inf at row ~374)** | erosion recovers the finite side from below the boundary; closing = original right up to it | **no false candidate at the horizon row** — verified in the same analytic check |

The **only** non-zero residual the analytic check found is a **frame-border artifact**: within K
pixels of the image edge there is no farther row to erode back with, and the residual peaks at
**1.425 m** (K = 21, bottom-left corner). That number is why the margin has a floor (§3.3) — and
finding it is exactly the reason this note contains a measurement instead of an assertion.

### 2.3 The geometric fact that makes the margin cheap

For a level camera at 15 m over a flat field with 3.8 m trees, **any obstacle inside the ±6 m threat
band is enormously nearer than whatever is behind it.** A bird at range `R` and drop `d ≤ 6 m`:

* against the ground: background `15R/d`, so `step = R(15−d)/d ≥ 1.5R` → **≥ 19.6 m** at the nearest
  range the band is even fully in frame (13.05 m, `band_covered_from_m`);
* against a canopy (which subtends only the rows 11.2–13.8 m below the axis): the covering tree must
  sit at `Rt ≥ 11.2R/d`, so `step ≥ 0.867R` → **≥ 11.3 m**;
* above the axis (`d ≤ 0`): the background is sky → `step = +inf`.

**Minimum in-band step in the whole 79-station dataset: 16.35 m** (S037). So a 2 m margin has a
**5.6× factor** against the smallest step safety cares about, while sitting **above** the 1.43 m
border artifact. The margin is free — *in this world, at this altitude, with a level camera*. All
three qualifiers are named, and the one that breaks first is attitude (§2.6).

### 2.4 Rejected alternatives, one sentence each

| rejected | one-sentence reason |
|---|---|
| **`isfinite` mask** (what D3 and the booking gate ran on) | It cannot separate a bird from the ground or a canopy it happens to touch, and the merge produces **two** failures, only one of which the runbook names: the blob is either deleted by `max_area` (bird gone) **or survives carrying the background's median depth** — a confident detection 20 m too far, which is worse, because it looks like success. |
| **Pose/attitude-driven analytic ground model** (`Z = h·fy/(v−cy)`, subtract it) | It is exact only at zero pitch and roll, needs attitude and intrinsics pushed through a one-argument locked seam, and fails **dangerous** on a stale pitch — the image already contains its own background. |
| **Temporal background** (frame differencing, running median over frames) | At 5 m/s the background changes ~1 m per frame, so the model is always stale, and it makes the detector stateful — unscoreable per station and unreproducible in flight. |
| **Row-wise percentile background** (cheapest of all) | Iso-depth lines are rows only while roll is zero; a 2-D window does not care which way the ground tilts, and costs the same. |
| **`max_area` filter** (inherited from NDVI) | Deleting the largest thing in the frame is fail-dangerous by construction; saturation is handled by **nearest-first ordering plus a box cap** (§2.5), which throws away the *far* candidates instead of the near one. |
| **A learned segmenter** | Nothing here has yet beaten a five-line operator whose every failure is explainable on a whiteboard, and the dataset in §5 is the thing that would have to justify the complexity — build the boring one first, then it is the baseline. |
| **Reusing `ndvi_detect.detect_blobs` for the mask → box step** | It returns boxes only, so the median depth would have to be re-derived from the bounding box — a second, worse estimate of the quantity the contract says the mask owns. The **convention** is shared, and a test pins the depth segmenter's labelling to agree with `detect_blobs` box-for-box on masks where both apply, which keeps them honest without coupling them. |

### 2.5 Saturation, refusals, and ordering

* **`+inf`** is a legitimate *background* value (sky is the farthest thing there is) and never a
  candidate. **`−inf`** (inside near clip) is a **refusal**, not a range: it is excluded from the
  mask, excluded from the background estimate (it would poison the local max), and **counted**; a
  frame with many of them is an airframe-occlusion alarm, which is what D2 CLEAR exists to prevent.
  `NaN` is not written by gz and is treated as `−inf` and counted separately, so if it ever appears
  we find out from a counter rather than from a wrong dodge.
* **No `max_area`.** If the candidate mask saturates, the segmenter sorts components by **median
  depth ascending** and returns at most `max_boxes`, counting `boxes_truncated`. A truncation drops
  the *farthest* candidates, never the nearest — the opposite of what an area cap does.
* **Large near object**: an object wider than K is not fully filled, so it returns as a **ring** of
  its own silhouette carrying its own depth, not as nothing. Named as a limit, not hidden: the
  size-selectivity of any local-window background estimator is the price of not needing a pose.

### 2.6 Failure modes I expect, before anyone measures

1. **Sub-margin step.** A bird less than `margin_m` in front of the surface behind it is invisible.
   In this world that can only happen **outside** the threat band (§2.3) — dataset group D measures
   exactly where the boundary falls, with steps of 0.75 / 1.5 / 3 / 6 / 12 m bracketing it.
2. **Occlusion.** A bird *behind* a canopy is not in the image at all; group E labels three such
   stations as **expected non-detections** so they are scored as occlusions and never as misses.
3. **Attitude.** The dataset is level-camera only. The flight's worst observed attitude is
   **−12.50°** (ADR-020 am. 2), which shifts the horizon row by ~113 px and tilts the ground ramp.
   The closing is orientation-free so the ramp stays ramp-invariant, but the *derivation* in §2.3
   assumes level. **Named transfer gap, not a claim.**
4. **Noise.** The sensor is noiseless (proposed TG-6). A real depth sensor would need the margin to
   grow with range; today one constant is honest and two knobs would not be.
5. **Slant vs Z.** The stored value is Z-depth; the cull is on slant. The segmenter never converts —
   it compares Z to Z — and the slant cull reaches it only as `+inf`, which is a background. The
   one place slant matters is the corner bound that clamps the booked range, and that lives in
   `depth_detect.corner_ray_ratio`, the single copy (ADR-020 am. 2, QA probe C).

---

## 3. Morphology and area, re-derived for the DEPTH render

F5 is binding: **nothing is inherited from `ndvi_detect`.** `DEFAULT_MIN_AREA = 6`, the 3×3 CROSS
open→close and `MIN_RESOLVING_RADIUS_PX = 2.0` describe synthetic discs through the NDVI detector's
morphology. The depth render floors the footprint at a 12-px plus and the component then survives on
**area**, not on a 2 px radius (ADR-020 am. 1 — the printed `r_apparent 2.00 px` is arithmetic
coincidence).

### 3.1 What to measure, from what

**Already on disk (no render needed):** run 2's **15 retained sweep frames** (10 → 58 m, on-axis,
sky-backed) and **probe 5's six captures** (five sub-pixel offsets + baseline at 46 m). From each,
per frame: the **candidate-pixel count** produced by §2.1, the component's bbox, its median depth,
and its shape. These give the sky-backed footprint-vs-range curve and the sub-pixel spread on the
*same* frames PROBE B validated, which is why they are worth re-reading rather than re-flying.

**From the new dataset (§5):** the same three numbers per station, now split by **background class**
— the number that matters, because sky-backed is the optimistic case and nobody has ever measured
the other three.

Pinhole prediction to compare against (`r_px = fx·0.18/R`, area = `π r²`), so a deviation is visible:

| R (m) | 14 | 20 | 26 | 32 | 38 | 44 | 46 | 50 |
|---|---|---|---|---|---|---|---|---|
| predicted r (px) | 6.69 | 4.68 | 3.60 | 2.93 | 2.46 | 2.13 | 2.03 | 1.87 |
| predicted area (px) | 141 | 69 | 41 | 27 | 19 | 14 | 13 | 11 |
| **measured (sky, on-axis)** | — | — | — | — | **12 raw px plateau from ~40 m** (PROBE B/5) | | | |

### 3.2 How each constant gets chosen — the rule, pre-registered

* **`bg_window_px` (K).** Must exceed the largest target we require to be **filled**, i.e. the bird's
  apparent diameter at the nearest range the threat band is fully in frame: `2·fx·0.18/13.05` =
  **14.3 px** → **K ≥ 17**. Cost is flat in K (§1.5), and larger K widens the border artifact, so:
  **start at K = 21, and adopt the smallest K ≥ 17 that gives FNR 0 on the `FNR_zero` stations.**
  Recorded with the sweep, not just the winner.
* **`margin_m`.** **Not chosen — derived**: the smallest value that yields **zero unmapped false
  positives** on the eight clutter-only negative-control frames (which contain the border artifact,
  the cull boundary, the canopies and the whole ground band), floored at 1.5× the measured border
  residual. Prediction from the analytic check: **≈ 2.0 m**. If the measurement disagrees, the
  measurement wins and the prediction stays in this note as the record of what was expected.
* **`min_area_px`.** The largest value that keeps FNR 0 across every `FNR_zero` station, **minus one
  step of margin**, and never inherited: the plateau is 12–14 raw px, so anything above ~10 is
  already at the edge. Reported with the measured minimum accepted component size, so a reader can
  see the headroom rather than trust the constant.
* **`open_iter`.** **Default 0 — no opening.** An opening's only job is speck rejection and
  `min_area_px` already does that with one knob instead of two, while an opening costs pixels on the
  smallest targets, which is where the horizon is set. Scored **both ways on the dataset**
  (0 and 1); whichever wins is frozen as a constant and the loser's numbers are recorded.
* **`max_boxes`.** 16, from the frame's own worst case (the number of distinct near components a
  cluttered lane pose actually produces, measured on the negatives), not a round number chosen here.

### 3.3 The one number that is not free

The **frame-border residual** (§2.2) puts a hard floor under `margin_m`, and `margin_m` is exactly
the minimum detectable depth step. So the chain is: *border artifact → margin → smallest visible
stand-off*. Today that chain reads **1.43 m → 2.0 m → 2.0 m**, against a ≥ 11.3 m in-band stand-off.
Any future change that widens K widens the artifact and therefore the blind band — which is why K is
adopted at its **smallest** passing value, not its most comfortable one.

---

## 4. Scoring protocol — pre-registered, before a single frame is rendered

### 4.1 Ground truth

Per station, from the **readback** poses, never the commanded ones:

* the **camera LINK pose** (`fg_depth_mount`) as gz reports it — **not** the vehicle model's park
  pose. The wrapper's `base_link` sits 0.195 m above the model origin, and quietly labelling with
  the commanded pose would bake that bias into every expected pixel. This is the ADR-007 am. 5
  family of defect (a value that is correct under a geometry nobody checked), and it is cheap to
  avoid here.
* the **bird pose** readback (already asserted to 0.05 m/axis by the harness).
* expected pixel `(u, v)` and expected Z-depth by the pinhole model at that pose; expected depth of
  the bird's **near surface** = `Z − 0.18`.
* **background class** per station: `sky` / `ground_band` / `canopy` / `*_edge` / `trunk`, computed
  by ray-casting the committed world (the generator that wrote the station file already does this,
  and the labeller recomputes it from the readback pose so the two must agree).

### 4.2 Matching rule — two clauses, and the second is the whole point

A returned box **matches** the bird iff **both**:

1. its box midpoint is within **τ = 5 px** of the expected pixel (the NDVI mount's live-verified
   geometry residual is 2.2 px; 5 px is that with headroom, and small enough that a canopy 20 px
   away cannot claim the match), **and**
2. `|median depth − expected depth| ≤ ε = 0.5 m` (PROBE B measured the plateau's own depths to
   0.02–0.16 m of true, so 0.5 m is ~3× the observed error).

Clause 2 is not decoration. **The merge failure is a centroid hit with the background's depth** — a
one-clause matcher would score it as a success.

### 4.3 Metrics, and the bars they must clear (fixed now)

| metric | definition | **pass bar** |
|---|---|---|
| **FNR, per background class × range bin** | over the **49 `FNR_zero` stations** (in threat band, range ≤ 46.0 m, not occluded) | **0 misses. Any single miss fails the gate.** |
| **Merge assertion** | stations where a box matches the pixel but its depth is within ε of the **background** instead of the bird | **0.** Reported as its own line even when it is zero. |
| **Unmapped FP / frame** | detections on the 8 negative-control frames that are **not** explained by a mapped tree geofence or the ground plane, per frame with the denominator printed | **≤ 0.05 /frame** (i.e. zero over 8 frames) |
| **Mapped FP / frame** | detections that *are* mapped clutter (`static_map_hint` fires, or un-projected z ≤ 4.8 m) | **reported, not barred** — these are real near objects; the policy's ±6 m vertical band already excludes them, and suppressing them here is the thing §1.2 forbids |
| **Range error** | median and p95 of \|median depth − true\| over matches | **p95 ≤ 0.5 m.** Context, quotable: the monocular apparent-size ray it replaces measured **1.65 m median** on the adopted clip |
| **Centroid error** | p95 \|box midpoint − expected pixel\| | reported (sets whether the box-midpoint decision in §1.3 stays) |
| **Occlusion labelling** | the 3 group-E stations | a detection there is **not** counted as an FP; a *missing* detection is the expected outcome and is recorded as such |
| **Runtime** | `seg_wall_ms_p95` / `_max` over all stations | p95 ≤ 25 ms, max ≤ 100 ms (§1.5) |
| **Determinism** | re-run with stations shuffled | byte-identical per-station output |

Every rate ships **with its denominator**, or it does not ship.

### 4.4 The cluttered acquisition range, and how it touches the booking gate

> **Cluttered acquisition range** = the longest **contiguous prefix** of the range ladder, taken over
> the **worst** background class present at each range, for which every `FNR_zero` station is
> matched — then clamped by `far_clip / corner_ray_ratio(...)` on the live intrinsics, exactly the
> D3-bookable rule ADR-020 am. 1 already ratified. The optical prefix is reported beside it and
> never booked.

How it feeds `scripts/predict_forward_lead.py --acq-range-m`, stated so it cannot loosen anything:

* **If it comes in below 46.0 m → it REPLACES 46.0.** The booked number is `min(current, measured)`,
  always, no exceptions, no re-argument.
* **If it comes in at or above 46.0 m → it QUALIFIES 46.0 and does not raise it.** The
  best-case-scene clause (F2) may then be narrowed to name the conditions the dataset actually
  removed — clutter and the blind `isfinite` mask — while **static vehicle, noiseless sensor and
  level attitude remain in the clause**, because this dataset does not measure them. Raising a
  booked horizon needs its own gate, on a flown take.
* **If it comes in below 33.591 m → the booking gate goes red at 5 m/s and the dodge take is not
  bookable at that speed.** That is ADR-020 am. 2's pre-registered invalidation, restated here so it
  cannot be paraphrased away.
* The artifact is a new `eval/results/depth_segmenter_score_<UTC>.json` carrying every number above
  **plus** the station file's own hash, and the booking-gate re-run (if any) writes its own artifact
  as usual. Schema 1.2's `acquisition_clamped_from_optical_prefix` fields already exist to record the
  clamp on the artifact's face.

### 4.5 The check the artifact cannot fake

Three, deliberately:

1. **The negatives have no target in the world at all** — a segmenter that hallucinated a bird to
   pass the ladder scores its own FP bar red on the same run. The two bars pull in opposite
   directions and are measured on the same eight frames.
2. **Clause 2 of the matcher** (§4.2) means the merge failure cannot pass as a detection.
3. **Mutate the conjunct.** Before the score is believed, each term of the mask expression
   (`isfinite`, the clip window, `step > margin`) is deleted in turn and the suite must go **red**
   for each. ADR-020 am. 2 records what a three-term conjunction with two pinned terms cost the
   booking gate; this is that lesson applied up front rather than after.

---

## 5. Dataset spec for the orchestrator

**79 stations**, machine-readable at `docs/design/depth_segmenter_stations.json` (same fields, plus
`slant_m`, `expected_r_px`, `background_depth_m`, `occluded_by`, `static_map_hint_expected`,
`pass_bar`, and the per-station note). Every value there is a **prediction**; the labeller recomputes
from the readback poses (§4.1) and the run **fails** if any station's rendered pixel differs from the
prediction by more than τ — a station file that disagrees with the render is a harness bug, and it
should stop the run rather than quietly redefine the label.

### 5.1 The ground plane question — use the COMMITTED plane, not the check-world extension

**Answer: the 425 m E-W extension must NOT be used for this dataset; render on the committed
125 × 110 m `field_ground` centred (37.5, 30), and assert it is unmodified.**

The extension exists so that D2 CULL could see the 60 m far clip on a *bird* in a scene whose real
ground ended 39.85 m ahead of the parked camera. Here the ground **is** one of the four background
classes the segmenter is being scored on, so its extent is part of the measurement: an extended
plane would move the ground-band/sky boundary and change the very thing under test.

It is also unnecessary, and the arithmetic says so. For a level camera at 15 m with a 60 m **slant**
cull, the region of ground that returns a finite depth at all is bounded — swept over the full
frame: **57.78 m forward** (on-axis, at row 375) and **±30.38 m lateral** (at (u, v) = (0, 398),
Z = 49.4 m). Every station pose in this set keeps that footprint inside the committed plane, with
margin:

| pose | ENU (U = 15 m) | yaw° | plane margin | nearest tree (horiz) | scene |
|---|---|---|---|---|---|
| P1 | (15, 0) | 90 (N) | 9.62 m | 5.00 m | **worst-clutter lane** — straight down orchard row 0; trees on the boresight at 5/15/25/35/45/55 m (the 25 m+ ones in frame) |
| P2 | (30, 0) | 90 | 24.62 m | 11.18 m | row x=40 10 m off-axis right |
| P3 | (45, 20) | 90 | 7.07 m | 7.07 m | mid-field; row x=40 5 m off-axis left |
| P4 | (15, 60) | 270 (S) | 9.72 m | 5.00 m | P1 mirrored — the yaw check |
| P5 | (60, 40) | 270 | 7.07 m | 7.07 m | row x=65 5 m off-axis |
| P6 | (60, 0) | 90 | 9.72 m | 7.07 m | **moderate-clutter contrast arm** for P1 |
| P7 | (45, 5) | 90 | 22.07 m | 5.00 m | clean ground band, no tree on the boresight |
| P8 | (30, 40) | 270 | 7.07 m | 11.18 m | mid-field southbound |

All eight are **real lane poses**: the boustrophedon lanes run north-south at x = 0, 15, 30, 45, 60,
75 at 15 m (`config/field_polygon.json`, `config/missions/boustrophedon.waypoints`), and every pose
sits on a lane at mission altitude with a mission heading. Yaw convention: **degrees in world ENU,
0 = +E, 90 = +N**, as in the SDF `<pose>`.

**Sky-safe for the vehicle, by construction and by check:** cruise is 15 m and the tallest tree is
3.8 m, so no tree can intersect the airframe at any station (11.2 m of vertical clearance); the
horizontal distance to the nearest tree is tabulated above anyway, and no station places the vehicle
above a canopy.

### 5.2 Harness requirements — three things the D2/D3 harness does not do yet

`scripts/verify_depth_mount_geometry.sh` parks the vehicle once and only teleports the bird. This
dataset needs three additions, each with the same fail-closed discipline the existing harness has:

1. **Teleport the VEHICLE between camera stations**, with the same ±0.05 m pose readback the bird
   gets **plus a yaw readback within 0.5°** — the existing harness never rotates anything, and a yaw
   that silently did not apply would relabel every station in that group. Physics kept, gravity
   zeroed (ADR-020 am. 1, edit 1). Eight vehicle teleports, ~10 bird teleports each.
2. **Park `bird_1` and `bird_2` out of every frustum** (e.g. (−200, −200, 50)) with readback, and
   **assert `drive_birds.py` is not running.** A stray second bird in frame would be scored as a
   false positive that is not one.
3. **Assert the world copy's `field_ground` is BYTE-IDENTICAL to the committed one** (i.e. the
   opposite of the D2/D3 edit 2) and refuse to capture otherwise, so this dataset can never be
   rendered on the extended plane by accident. Keep G105's frame-distinctness self-check.

Retain per station: the raw `float32` frame, the camera-link and bird pose readbacks, the frame's own
`camera_info`, and the gz sim stamp. **Commit** the scoring summary, the station file and **six**
canonical frames (one per background class plus two merge cases) as the regression fixture; the full
~79-frame set lives under `eval/results/` and stays out of git.

### 5.3 The stations

Groups: **A** sky ladder (resolving-floor re-measure, clean vs cluttered lane) · **B** ground-band /
merge · **C** canopy-backed threat bird · **D** small-step ladder (measures the margin's own
boundary) · **E** occluded (labelled non-detections) · **F** negative controls · **G** off-axis /
frame edge · **H** annotator exercise. `band` = inside the ±6 m threat band. `bar` = **FNR** (safety,
49 stations) / **FP** (8) / occl (3) / diag (19).

| id | grp | pose | cam E,N | yaw | bird ENU | R (m) | px | background | step (m) | band | bar |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S001 | A | P6 | 60,0 | 90 | 60.00, 14.15, 15.00 | 14.0 | 320,240 | sky | inf | Y | **FNR** |
| S002 | A | P6 | 60,0 | 90 | 60.00, 20.15, 15.00 | 20.0 | 320,240 | sky | inf | Y | **FNR** |
| S003 | A | P6 | 60,0 | 90 | 60.00, 26.15, 15.00 | 26.0 | 320,240 | sky | inf | Y | **FNR** |
| S004 | A | P6 | 60,0 | 90 | 60.00, 32.15, 15.00 | 32.0 | 320,240 | sky | inf | Y | **FNR** |
| S005 | A | P6 | 60,0 | 90 | 60.00, 38.15, 15.00 | 38.0 | 320,240 | sky | inf | Y | **FNR** |
| S006 | A | P6 | 60,0 | 90 | 60.00, 44.15, 15.00 | 44.0 | 320,240 | sky | inf | Y | **FNR** |
| S007 | A | P6 | 60,0 | 90 | 60.00, 46.15, 15.00 | 46.0 | 320,240 | sky | inf | Y | **FNR** |
| S008 | A | P6 | 60,0 | 90 | 60.00, 50.15, 15.00 | 50.0 | 320,240 | sky | inf | Y | diag |
| S009 | A | P1 | 15,0 | 90 | 15.00, 14.15, 15.00 | 14.0 | 320,240 | sky | inf | Y | **FNR** |
| S010 | A | P1 | 15,0 | 90 | 15.00, 20.15, 15.00 | 20.0 | 320,240 | sky | inf | Y | **FNR** |
| S011 | A | P1 | 15,0 | 90 | 15.00, 26.15, 15.00 | 26.0 | 320,240 | sky | inf | Y | **FNR** |
| S012 | A | P1 | 15,0 | 90 | 15.00, 32.15, 15.00 | 32.0 | 320,240 | sky | inf | Y | **FNR** |
| S013 | A | P1 | 15,0 | 90 | 15.00, 38.15, 15.00 | 38.0 | 320,240 | sky | inf | Y | **FNR** |
| S014 | A | P1 | 15,0 | 90 | 15.00, 44.15, 15.00 | 44.0 | 320,240 | sky | inf | Y | **FNR** |
| S015 | A | P1 | 15,0 | 90 | 15.00, 46.15, 15.00 | 46.0 | 320,240 | sky | inf | Y | **FNR** |
| S016 | A | P1 | 15,0 | 90 | 15.00, 50.15, 15.00 | 50.0 | 320,240 | sky | inf | Y | diag |
| S017 | A | P1 | 15,0 | 90 | 15.00, 20.15, 12.00 | 20.0 | 320,318 | sky | inf | Y | **FNR** |
| S018 | A | P1 | 15,0 | 90 | 15.00, 30.15, 12.00 | 30.0 | 320,292 | sky | inf | Y | **FNR** |
| S019 | A | P1 | 15,0 | 90 | 15.00, 40.15, 12.00 | 40.0 | 320,279 | sky | inf | Y | **FNR** |
| S020 | A | P1 | 15,0 | 90 | 15.00, 46.15, 12.00 | 46.0 | 320,274 | sky | inf | Y | **FNR** |
| S021 | B | P7 | 45,5 | 90 | 45.00, 19.15, 11.00 | 14.0 | 320,389 | ground_band | 38.7 | Y | **FNR** |
| S022 | B | P7 | 45,5 | 90 | 45.00, 21.15, 11.00 | 16.0 | 320,370 | sky_edge | inf | Y | **FNR** |
| S023 | B | P7 | 45,5 | 90 | 45.00, 23.15, 11.00 | 18.0 | 320,356 | sky | inf | Y | **FNR** |
| S024 | B | P7 | 45,5 | 90 | 45.00, 25.15, 11.00 | 20.0 | 320,344 | sky | inf | Y | **FNR** |
| S025 | B | P7 | 45,5 | 90 | 45.00, 27.15, 11.00 | 22.0 | 320,335 | sky | inf | Y | **FNR** |
| S026 | B | P7 | 45,5 | 90 | 45.00, 19.15, 10.00 | 14.0 | 320,426 | ground_band | 28.2 | Y | **FNR** |
| S027 | B | P7 | 45,5 | 90 | 45.00, 21.15, 10.00 | 16.0 | 320,402 | ground_band | 32.2 | Y | **FNR** |
| S028 | B | P7 | 45,5 | 90 | 45.00, 23.15, 10.00 | 18.0 | 320,384 | ground_band | 36.2 | Y | **FNR** |
| S029 | B | P7 | 45,5 | 90 | 45.00, 25.15, 10.00 | 20.0 | 320,370 | sky_edge | inf | Y | **FNR** |
| S030 | B | P7 | 45,5 | 90 | 45.00, 27.15, 10.00 | 22.0 | 320,358 | sky | inf | Y | **FNR** |
| S031 | B | P7 | 45,5 | 90 | 45.00, 19.15, 9.00 | 14.0 | 320,463 | ground_band | 21.2 | Y | **FNR** |
| S032 | B | P7 | 45,5 | 90 | 45.00, 21.15, 9.00 | 16.0 | 320,435 | ground_band | 24.2 | Y | **FNR** |
| S033 | B | P7 | 45,5 | 90 | 45.00, 23.15, 9.00 | 18.0 | 320,413 | ground_band | 27.2 | Y | **FNR** |
| S034 | B | P7 | 45,5 | 90 | 45.00, 25.15, 9.00 | 20.0 | 320,396 | ground_band | 30.2 | Y | **FNR** |
| S035 | B | P7 | 45,5 | 90 | 45.00, 27.15, 9.00 | 22.0 | 320,382 | ground_band | 33.2 | Y | **FNR** |
| S036 | B | P1 | 15,0 | 90 | 15.00, 14.15, 9.00 | 14.0 | 320,463 | trunk_edge | 20.9 | Y | **FNR** |
| S037 | B | P1 | 15,0 | 90 | 15.00, 18.15, 9.00 | 18.0 | 320,413 | canopy | 16.4 | Y | **FNR** |
| S038 | C | P1 | 15,0 | 90 | 15.00, 22.15, 9.00 | 22.0 | 320,382 | canopy | 21.9 | Y | **FNR** |
| S039 | C | P1 | 15,0 | 90 | 15.00, 24.15, 9.00 | 24.0 | 320,370 | canopy_edge | 21.0 | Y | **FNR** |
| S040 | C | P1 | 15,0 | 90 | 15.00, 26.15, 9.00 | 26.0 | 320,360 | canopy | 27.7 | Y | **FNR** |
| S041 | C | P1 | 15,0 | 90 | 15.00, 28.15, 9.00 | 28.0 | 320,351 | canopy | 26.1 | Y | **FNR** |
| S042 | C | P1 | 15,0 | 90 | 15.00, 30.15, 9.00 | 30.0 | 320,344 | sky_edge | inf | Y | **FNR** |
| S043 | C | P1 | 15,0 | 90 | 15.00, 32.15, 9.00 | 32.0 | 320,338 | sky | inf | Y | **FNR** |
| S044 | C | P1 | 15,0 | 90 | 15.00, 34.15, 9.00 | 34.0 | 320,332 | sky | inf | Y | **FNR** |
| S045 | C | P4 | 15,60 | 270 | 15.00, 33.85, 9.00 | 26.0 | 320,360 | canopy | 27.7 | Y | **FNR** |
| S046 | C | P4 | 15,60 | 270 | 15.00, 29.85, 9.00 | 30.0 | 320,344 | sky_edge | inf | Y | **FNR** |
| S047 | C | P4 | 15,60 | 270 | 15.00, 25.85, 9.00 | 34.0 | 320,332 | sky | inf | Y | **FNR** |
| S048 | D | P1 | 15,0 | 90 | 15.00, 43.19, 3.04 | 43.0 | 320,384 | canopy | 0.8 | - | diag |
| S049 | D | P1 | 15,0 | 90 | 15.00, 42.44, 3.25 | 42.3 | 320,384 | canopy | 1.5 | - | diag |
| S050 | D | P1 | 15,0 | 90 | 15.00, 40.94, 3.67 | 40.8 | 320,384 | canopy | 3.0 | - | diag |
| S051 | D | P1 | 15,0 | 90 | 15.00, 37.94, 4.50 | 37.8 | 320,384 | canopy | 6.0 | - | diag |
| S052 | D | P1 | 15,0 | 90 | 15.00, 31.94, 6.17 | 31.8 | 320,384 | canopy | 12.0 | - | diag |
| S053 | D | P1 | 15,0 | 90 | 15.00, 33.22, 3.19 | 33.1 | 320,426 | canopy | 0.8 | - | diag |
| S054 | D | P1 | 15,0 | 90 | 15.00, 32.47, 3.46 | 32.3 | 320,426 | canopy | 1.5 | - | diag |
| S055 | D | P1 | 15,0 | 90 | 15.00, 30.97, 3.99 | 30.8 | 320,426 | canopy | 3.0 | - | diag |
| S056 | D | P1 | 15,0 | 90 | 15.00, 27.97, 5.06 | 27.8 | 320,426 | canopy | 6.0 | - | diag |
| S057 | D | P1 | 15,0 | 90 | 15.00, 21.97, 7.21 | 21.8 | 320,426 | canopy | 12.0 | - | diag |
| S058 | E | P1 | 15,0 | 90 | 15.00, 37.15, 1.79 | 37.0 | 320,426 | ground_band | 5.2 | - | occl |
| S059 | E | P1 | 15,0 | 90 | 15.00, 47.15, 1.94 | 47.0 | 320,384 | ground_band_edge | 7.2 | - | occl |
| S060 | E | P1 | 15,0 | 90 | 15.00, 45.15, 2.50 | 45.0 | 320,384 | canopy | 1.3 | - | occl |
| S061 | F | P1 | 15,0 | 90 | -200.00, -200.00, 50.00 | — | — | (parked out) | — | - | **FP** |
| S062 | F | P2 | 30,0 | 90 | -200.00, -200.00, 50.00 | — | — | (parked out) | — | - | **FP** |
| S063 | F | P3 | 45,20 | 90 | -200.00, -200.00, 50.00 | — | — | (parked out) | — | - | **FP** |
| S064 | F | P4 | 15,60 | 270 | -200.00, -200.00, 50.00 | — | — | (parked out) | — | - | **FP** |
| S065 | F | P5 | 60,40 | 270 | -200.00, -200.00, 50.00 | — | — | (parked out) | — | - | **FP** |
| S066 | F | P6 | 60,0 | 90 | -200.00, -200.00, 50.00 | — | — | (parked out) | — | - | **FP** |
| S067 | F | P7 | 45,5 | 90 | -200.00, -200.00, 50.00 | — | — | (parked out) | — | - | **FP** |
| S068 | F | P8 | 30,40 | 270 | -200.00, -200.00, 50.00 | — | — | (parked out) | — | - | **FP** |
| S069 | G | P1 | 15,0 | 90 | 30.00, 30.15, 15.00 | 30.0 | 580,240 | sky | inf | Y | **FNR** |
| S070 | G | P1 | 15,0 | 90 | 0.00, 30.15, 15.00 | 30.0 | 60,240 | sky | inf | Y | **FNR** |
| S071 | G | P1 | 15,0 | 90 | 15.00, 30.15, 8.08 | 30.0 | 320,360 | canopy | 23.7 | - | diag |
| S072 | G | P1 | 15,0 | 90 | 38.00, 46.15, 15.00 | 46.0 | 580,240 | sky | inf | Y | **FNR** |
| S073 | G | P1 | 15,0 | 90 | -8.00, 46.15, 15.00 | 46.0 | 60,240 | sky | inf | Y | **FNR** |
| S074 | G | P1 | 15,0 | 90 | 15.00, 46.15, 4.38 | 46.0 | 320,360 | canopy | 7.7 | - | diag |
| S075 | G | P1 | 15,0 | 90 | 38.00, 46.15, 30.92 | 46.0 | 580,60 | sky | inf | - | diag |
| S076 | H | P2 | 30,0 | 90 | 16.20, 34.20, 3.20 | 34.0 | 109,420 | canopy | 0.5 | - | diag |
| S077 | H | P3 | 45,20 | 90 | 41.20, 54.20, 3.20 | 34.0 | 262,420 | canopy_edge | 0.7 | - | diag |
| S078 | H | P6 | 60,0 | 90 | 41.20, 34.20, 3.20 | 34.0 | 33,420 | canopy | 0.5 | - | diag |
| S079 | H | P5 | 60,40 | 270 | 66.20, 4.20, 3.20 | 35.6 | 230,412 | ground_band | 9.8 | - | diag |

Notes on the design of the set, so nobody re-derives them:

* **The merge case is 15 stations, not one.** QA's scenario (a bird 4–6 m below cruise at 15–23 m) is
  a *band*, and the interesting part is the transition: at drop 6 m the bird crosses from sky-backed
  into the ground band at ~23 m, so B walks a 3 × 5 grid across it and the station file records which
  side of the boundary each landed on.
* **Group H found a real limit while being generated.** A bird beside a mapped tree at nearly the
  same range has a depth step of **0.5–0.7 m** — the weakest possible case for a discontinuity test.
  It is `diag`, not a safety bar, because such a bird is ~11.8 m below cruise and outside the threat
  band. The stronger statement, which falls out of §2.3: **no in-band detection in this world can
  ever be annotated**, because trees top out at 3.8 m (geofence 4.8 m with margin) and the band
  starts at 9 m. `detections_near_known_obstacle` is a **clutter accountant, not a bird
  discriminator** — the annotator is exercised by the canopy detections in every cluttered frame.
* **S075 is a geometry probe, not a bird scenario** (a target 16 m above cruise at the far corner):
  the lower corners at 46 m are underground, so the upper corner is the only place the corner cull
  can be exercised on a target.
* **Two ladders, one clean-ish and one down the tree row** (P6 vs P1, S001–S016), so the headline
  question — *does clutter shorten acquisition?* — is answered by a paired comparison rather than by
  one number.

---

## 6. Wiring plan (flight-software, after the score is green)

1. **`build_detection_source`** grows a kind: `build_detection_source(cfg, kind)` with
   `kind ∈ {'ndvi', 'depth'}`, selected by `--detection-source {ndvi,depth}` **defaulting to
   `ndvi`** — the depth path ships OFF. `DetectorConfig` gains the depth fields (K, margin,
   min_area, open_iter, max_boxes) with their provenance string, in the same shape the NDVI
   threshold already uses (`thresh_provenance`, `thresh_provisional`), so the log says whether a
   number was the adopted constant or something someone typed.
2. **`detection_source_name` is a bug on this path today** and must be fixed with the wiring:
   `return "ndvi_blob" if hasattr(source, "on_frame") else DEMO_SOURCE_TAG` labels a **depth** flight
   `ndvi_blob`. Derive it from the source's own `SOURCE_TAG` (`depth_detect.SOURCE_TAG ==
   "depth_blob"`) — provenance read from what ran, which is that function's own stated principle.
3. **`detector_log_block`** grows a depth branch: module, the frozen params, the **live** intrinsics
   with `provenance: "live /fg/depth/camera_info"`, `range_model: "measured depth (ADR-020); no
   radius prior, no ground-plane projection"`, and both `counters()` dicts.
4. **Node subscriptions**: `/fg/depth/image` + `/fg/depth/camera_info`, feeding
   `DepthDetectionSource.on_frame(stamp_s, depth, pose, quat, residual)` with the pose paired to the
   frame's **own gz stamp** from the existing `PoseBuffer.nearest` — the same pairing the NDVI path
   uses, on the same clock. `set_intrinsics` from the live `camera_info`, never from config.
5. **`static_map_annotator = geofence_annotator(gmap)`** wired on: **annotate + counter only, never
   suppress.** It costs one geofence test per detection and gives the flight log a clutter
   denominator.
6. **Mutual exclusion.** `--detect` and `--demo` are already exclusive; `--detection-source depth`
   with the NDVI detector also armed is a **product decision**, not a default (§7 Q2).

**Tests that pin it** (all host-side, no renderer):

* segmenter unit: ramp invariance (a pure analytic ground ramp yields **zero** candidates in the
  frame interior); sky case; the merge case (a synthetic sphere on a ramp → one component whose
  median depth is the sphere's, **not** the ramp's); `−inf` counted and never a candidate; `+inf`
  never a candidate but always a valid background; determinism under station shuffling; box
  convention agreement with `detect_blobs` on shared masks; `max_boxes` truncation drops the
  **farthest**; the largest component is never deleted.
* **mutation tests**: delete each conjunct of the mask expression in turn, require red (§4.5).
* seam: `DepthDetectionSource(real_segmenter)` over a canned frame → a `Detection` at the expected
  ENU; the existing assertion that `pixel_to_ground_enu` is never called stays.
* node: `--detection-source depth` builds a `DepthDetectionSource` and the log block reports
  `depth_blob`; the **default** still builds the NDVI source; a depth flight log fails validation if
  it claims `ndvi_blob`.
* artifact: the committed scoring summary is pinned by test as the record of what authorised the
  flight (the pattern `test_booking_gate_artifact.py` already sets), and is **not** regenerated.

---

## 7. Open questions — I am not guessing these

1. **Ordering.** Is the dodge take booked on 46.0 m *now*, with this dataset as a post-hoc
   qualification — or does the take wait for the cluttered number? The safety direction is
   unambiguous (`min(current, measured)` either way), but which comes first costs a session, and
   that is a product-lead call.
2. **One detector or two in the air?** Running the depth segmenter and the NDVI detector in the same
   node costs up to ~50 ms of a 200 ms tick and gives one flight two detection sources; disarming
   NDVI keeps the tick clean but costs ADR-003's in-air evidence on that take. Recommendation:
   exclusive by default. **Not decided here.**
3. **A pitched arm on the dataset?** Six extra stations with the vehicle parked at −12.5° pitch would
   turn §2.6 failure mode 3 from a named transfer gap into a measurement, at maybe 10 minutes of
   render. I would take it; it is the user's session time.
4. **Target size sensitivity.** Every station uses the world's 0.18 m bird. A second radius (0.10 m /
   0.30 m) would bound the resolving floor's sensitivity — extra stations, extra time, and only worth
   it if the acquisition number lands near the 33.591 m breakeven.
5. **ADR-020 am. 1 open item 4 is still open**: does `predict_bird_visibility.py` remain a
   *reported* precondition of the take (gating the NDVI map, not the dodge)? Recommended there,
   unratified, and unchanged by this note.

### ADR-021 skeleton (to be written when the gate has numbers, not before)

> **ADR-021: the forward depth segmenter keys on depth DISCONTINUITY against a local far-envelope,
> not on `isfinite` — and its constants are measured on a cluttered labelled dataset, not inherited
> from the NDVI detector**  (date, status: **confirmation-pending** until the §4 gate flips it)
>
> * **Decision** — one black-top-hat operator (`closing(D) − D`, K×K flat SE) + one margin + one area
>   floor; no `max_area`; nearest-first box cap; image-space only, no pose, no intrinsics; median
>   depth over the component's mask.
> * **Why** — a depth camera only knows *nearer*; `isfinite` cannot separate a bird from the ground
>   or canopy it touches, and the merge fails **two** ways (deleted blob, or a detection carrying the
>   background's range). Every in-band obstacle in this world is ≥ 11.3 m nearer than its background,
>   so a discontinuity test has an enormous margin where a brightness-style test has none.
> * **Alternatives rejected** — `isfinite`; pose-driven analytic ground model; temporal background;
>   row-wise percentile; `max_area`; a learned segmenter; reusing `detect_blobs` for the box step.
>   (One sentence each, §2.4.)
> * **Consequences** — a blind band of `margin_m` in front of any surface (measured, out-of-band in
>   this world); large near objects return as silhouette rings; the level-camera derivation is a
>   named transfer gap; +1 module in `src/`, 0 new dependencies, 0 changes to the ADR-020 seam or the
>   ADR-009 rules.
> * **Gates** — the §4.3 table, pre-registered here **before** any frame was rendered: FNR 0 on 49
>   in-band ≤ 46 m stations across four background classes; 0 merge-mislabels; ≤ 0.05 unmapped FP per
>   frame over 8 clutter-only frames; range-error p95 ≤ 0.5 m; runtime p95 ≤ 25 ms; determinism;
>   mutation tests red. Then the cluttered acquisition range under the §4.4 rule, which can only
>   **lower** the booked 46.0 m.
> * **Amendment slots owed on the day** — the measured constants (K, `margin_m`, `min_area_px`,
>   `open_iter`, `max_boxes`) with the sweep that chose each, and the cluttered acquisition range
>   with its clamp.

---

*Reading order for whoever builds this: `src/fieldguard_planning/depth_detect.py` (the seam and its
nine rules) → `docs/runbooks/FORWARD_DEPTH_SENSOR.md` §7 (the gaps this closes) → ADR-020 amendments
1 and 2 in `docs/DECISIONS.md` (what is measured and at what speed) → this note → the station file.*
