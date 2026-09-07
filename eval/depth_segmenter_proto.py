#!/usr/bin/env python3
"""PROTOTYPE depth segmenter: depth frame -> near-obstacle components, by LOCAL DEPTH DISCONTINUITY.

STATUS: prototype. NOT wired into `src/`. It exists so the algorithm can be scored on real frames and
stress-tested on synthetic ones BEFORE it becomes flight code, and so every number in
`docs/design/DEPTH_SEGMENTER_ALGORITHM.md` has an executable that produced it. The seam it is built
for is `fieldguard_planning.depth_detect.DepthSegmenter`
(`Callable[[frame], Sequence[Tuple[box, depth_m]]]`); `as_segmenter()` returns exactly that shape.

WHY NOT `isfinite`. The in-render gate (FORWARD_DEPTH_SENSOR.md D3) segmented birds with a blind
`isfinite` mask, which works only because the check world is a bird against SKY. In the mission world
the finite class also holds the ground band (rows 374-479 here, Z 32.5-58.0 m) and the tree canopies
(in frame from ~24 m). A bird projected into the ground band is 4-connected to the ground, merges
into one component, and an area ceiling then deletes it -- the bird disappears with no counter
moving. So the mask cannot be "is there a return", it has to be "is this return significantly NEARER
than what is behind it".

THE ALGORITHM, in one line:

    candidate  <=>  isfinite(z)  AND  grey_closing(z, K) - z > margin

`grey_closing` = `minimum_filter(maximum_filter(z, K), K)`, the depth field with every pit narrower
than K px FILLED IN. That is the definition of "what is behind this pixel", and it is the whole
design: a monotone ground ramp has no pits, so closing reproduces it EXACTLY and the ground never
becomes a candidate; a canopy wider than K is its own background including at its rim, so it never
becomes a candidate either; a bird narrower than K is a pit and its full depth step survives. The
far cull -- where the ground band ends against sky -- is a ramp ending, not a pit, so the horizon
line is not reported. Measured on the commissioned frames: ZERO false candidate pixels on the whole
ground band and ZERO on a canopy, with the bird's 12 px the only candidates in the frame.

WHY NOT A LARGE-WINDOW MEDIAN, which was built first and scored: on the same real ground band a
52 px two-stage median leaves 498 false candidate pixels forming 11 components along the far cull,
plus 10 more around a canopy's rim -- so it needs a second rule to suppress them, and that rule then
has to be prevented from suppressing near birds. It also costs 8.0 ms against the closing's 4.0 ms
and goes BLIND (not fragmented -- blind) on any object nearer than 4.2 m. The closing needs no
second rule at all. Kept as a rejected alternative with its numbers, not as an option.

WHAT K MEANS, because it is the only shape parameter: K is the largest apparent size an object may
have and still be reported WHOLE. An object wider than K is not a pit, so only a rim of it is
flagged -- it is still detected, at its own correct depth, but as a broken annulus rather than a
blob. For a 0.18 m bird at fx 520.006, K = 15 px means "whole out to 12.5 m, arcs from there in".
Raising K raises that crossover and, on this render, raises the ground-ramp residual in the bottom
K/2 rows one-for-one (0.981 m at K=15, 1.419 at 21, 2.176 at 31, 4.664 at 61) -- and the margin has
to clear that residual, so K and the minimum resolvable standoff trade directly.

WHY THE MARGIN DOES NOT SCALE WITH RANGE, contrary to the obvious guess. For a depth camera,
background depth STRUCTURE IS METRIC: a canopy 1.5 m deep is 1.5 m deep at 20 m and at 50 m. What
changes with range is how many PIXELS that structure subtends, and that is K's business, not the
margin's. The measurement agrees and is worth stating because it is counter-intuitive: the closing's
residual on the real ground band is 0.981 m in the 32-40 m rows and EXACTLY 0.000 above 40 m -- it
falls with range, because it is an image-edge truncation effect (the ramp is cut off by the bottom
of the frame, so the closing cannot restore it) and not an angular one. `MARGIN_FRAC` therefore
defaults to 0.0: the knob exists for the cluttered dataset to set from evidence, and shipping it
non-zero today would be a constant invented from prose.

WHAT +inf MEANS HERE. `+inf` (beyond far clip) flows through the closing UNCHANGED and is a
legitimate background -- sky is the farthest thing there is -- so a sky-backed bird gets an infinite
step and is detected at any range. It is never a candidate itself. NaN is mapped to +inf and counted
(an unknown background is treated as far, the direction that produces detections rather than hides
them). `-inf` (inside the near clip) is a REFUSAL, never a range -- see `SegmentResult`.

numpy/scipy only, and scipy for the same scoped reason `ndvi_detect` gives: these numbers are what
`scipy.ndimage` computed, and a hand-rolled reimplementation would be a different detector wearing
the same measurements.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

# ==================================================================================================
# Constants. Every one carries the measurement that produced it, or says it has none.
# ==================================================================================================

# --- K, the closing window ----------------------------------------------------------------------
# 15 px. Two measured bounds meet here:
#   UPPER: the closing's residual on the real ground ramp lives in the bottom K/2 rows and grows
#          one-for-one with K -- 0.981 m at K=15, 1.419 at 21, 2.176 at 31, 4.664 at 61 (max over
#          61,858 ground-band pixels; rows 473-479 at K=15). The margin must clear it, so K sets the
#          floor on the minimum resolvable bird-to-background standoff.
#   LOWER: K is the apparent size an object may have and still be reported whole; K=15 keeps a
#          0.18 m bird whole out to 2*fx*R/K = 12.5 m, and closer than that it returns as arcs of
#          its own rim at its own correct depth (measured: 4 components, never zero, down to ~1.6 m).
# At K=15 and MARGIN_ABS_M=1.2 the ground band produces ZERO candidate pixels; at K=21 it produces a
# single 1,280 px component along the bottom edge. That is the binding measurement.
# Cost is FLAT in K (scipy's separable rank-filter path): 4.0 ms at K=15, 4.1 ms at K=61. So K is
# free to choose on accuracy alone, which is why the choice is documented and not tuned.
CLOSING_K_PX = 15

# --- the nearness margin --------------------------------------------------------------------
# MARGIN_ABS_M = 1.2 m: 1.22x the measured worst-case background residual (0.981 m, K=15). float32
# over a 60 m range quantises at ~4e-6 m, so precision is not what this clears -- background
# structure is.
# CONSEQUENCE, stated because it is a false-negative mechanism and it is what the labeller must
# record: a bird less than margin(z) in FRONT of the surface behind it is not separable from it.
# 1.2 m is 0.24 s of closing at 5 m/s. Measured boundary on a synthetic canopy: 1.0 m standoff
# MISSES, 1.5 m standoff DETECTS.
MARGIN_ABS_M = 1.2
# 0.0 on purpose -- see the module docstring. The knob exists for the cluttered dataset.
MARGIN_FRAC = 0.0

# --- morphology + area -------------------------------------------------------------------------
# NO OPENING. `ndvi_detect.detect_blobs` opens with a 3x3 CROSS before labelling; the real bird patch
# on the DEPTH render is a 12-px plus from ~40 m out, and the cross-opening ERASES it (probe 5,
# frame 46_on: raw 12 px -> post-morphology 0 px). Closing is off too: the depth mask on a noiseless
# render has no speckle to fill, and a binary close can BRIDGE a bird to an adjacent candidate --
# the merge this design exists to prevent. Both are parameters, both default off, and both must be
# re-measured if transfer-gap TG-6 (sensor noise) is ever modelled.
OPEN_ITER = 0
CLOSE_ITER = 0

# min_area 6 px is `ndvi_detect.DEFAULT_MIN_AREA`, reused because it is NON-BINDING here and a second
# constant would need a second justification: the smallest real bird patch measured anywhere on this
# render is 12 px (at 46 m AND at 58 m -- the render's antialiasing floors the footprint), so there
# is 2x headroom. `resolving_floor_px()` measures what it actually costs rather than asserting it.
MIN_AREA_PX = 6

# max_area is DELIBERATELY absent. An area ceiling is precisely the mechanism that silently deletes a
# bird merged into something larger. Oversize is a TAG (`size_ratio`) and a counter, never a drop.

# --- the size-consistency TAG (not a filter) ----------------------------------------------------
# A depth camera measures range AND apparent size, so the radius prior `ndvi_detect` had to ASSUME
# can here be CHECKED: a component of area A at measured depth z has apparent radius sqrt(A/pi), and
# a sphere of radius R at z subtends fx*R/z. Measured on the real frames with R = 0.15 m (the same
# conservative prior `ndvi_detect.BIRD_RADIUS_PRIOR_M` uses -- not the world's true 0.18, which would
# be reading the answer out of the world config): 1.11 .. 1.75 across the 10 detected bird frames.
#
# IT IS A TAG AND NOT A FILTER, and the reason is measured, not cautious: a canopy-rim fragment at
# 24 m is 31 px against the 33 px a 0.15 m bird subtends at that range. Apparent size CANNOT tell
# them apart. Filtering on it would buy nothing and cost near-range birds, whose rim arcs are much
# smaller than their true footprint. Both bounds default to None; the cluttered dataset is what sets
# them, if anything does.
SIZE_PRIOR_RADIUS_M = 0.15

# ==================================================================================================


@dataclass(frozen=True)
class Intrinsics:
    """Pinhole intrinsics, corner-origin: a point projects to `u = fx*X/Z + cx`, and pixel INDEX j
    covers [j, j+1). Field-for-field compatible with `ndvi_georef.CameraIntrinsics`, which is what
    the wired version takes; kept local so this prototype imports nothing from `src/`."""
    fx: float
    fy: float
    cx: float
    cy: float
    width: int
    height: int

    @classmethod
    def from_gz_camera_info(cls, path) -> "Intrinsics":
        """Read the LIVE `/fg/depth/camera_info` dump, never `config/depth_camera.json`: the config
        is what was asked for, the message is what was got (`clip_recorder`'s rule)."""
        d = json.loads(Path(path).read_text())
        k = d["intrinsics"]["k"]
        return cls(float(k[0]), float(k[4]), float(k[2]), float(k[5]),
                   int(d["width"]), int(d["height"]))


@dataclass(frozen=True)
class SegmenterParams:
    closing_k_px: int = CLOSING_K_PX
    margin_abs_m: float = MARGIN_ABS_M
    margin_frac: float = MARGIN_FRAC
    min_area_px: int = MIN_AREA_PX
    open_iter: int = OPEN_ITER
    close_iter: int = CLOSE_ITER
    near_clip_m: float = 0.1
    far_clip_m: float = 60.0
    size_prior_radius_m: float = SIZE_PRIOR_RADIUS_M
    size_ratio_lo: Optional[float] = None    # opt-in tags-become-filters; see SIZE_PRIOR_RADIUS_M
    size_ratio_hi: Optional[float] = None
    cull_edge_margin_m: Optional[float] = None   # opt-in; see Component.cull_headroom_m
    link_break: bool = True


@dataclass
class Component:
    """One near-obstacle. `bbox` is half-open slice bounds in CORNER-ORIGIN coordinates, identical in
    convention to `ndvi_detect.detect_blobs`, so its midpoint IS the pinhole (u,v) that
    `depth_pixel_to_enu` expects -- no half-pixel fudge anywhere downstream."""
    bbox: Tuple[float, float, float, float]
    area_px: int
    centroid_px: Tuple[float, float]      # mask centroid, corner-origin (index + 0.5)
    bbox_centre_px: Tuple[float, float]   # what the seam consumes
    depth_median_m: float
    depth_min_m: float
    depth_p05_m: float
    depth_max_m: float
    cull_headroom_m: float                # median over the component of far/|ray| - z
    size_ratio: float                     # measured apparent radius / prior-predicted
    tags: Tuple[str, ...] = ()


@dataclass
class SegmentResult:
    """`refused` is NOT "no obstacles". A caller that reads `not result.components` as "clear"
    without checking `refused` has reproduced the exact defect `score.py.evidence_shortfall()` exists
    to prevent: zeros reading as a clean sweep. `DepthDetectionSource` must surface a refusal as a
    FAULT and the flight log must carry the count."""
    components: List[Component] = field(default_factory=list)
    rejected: List[Component] = field(default_factory=list)
    refused: Optional[str] = None
    counters: Dict[str, int] = field(default_factory=dict)
    # Depth of the NEAREST component this frame withheld, whatever the reason -- so that anything
    # dropped is still visible in the flight log rather than silent. No threshold and no policy
    # knowledge here: the number is reported, and whoever owns the clearance bar decides.
    nearest_withheld_depth_m: Optional[float] = None

    def as_boxes(self) -> List[Tuple[List[float], float]]:
        """The `depth_detect.DepthSegmenter` return shape: [(box, depth_m), ...]."""
        return [(list(c.bbox), c.depth_median_m) for c in self.components]


# ------------------------------------------------------------------------------- geometry cache
_CULL_CACHE: Dict[Tuple, np.ndarray] = {}


def cull_depth_map(intr: Intrinsics, far_clip_m: float) -> np.ndarray:
    """Per-pixel Z-depth at which gz stops returning: `far / |ray|`, because the FAR cull is on the
    EUCLIDEAN length of the camera-space point while the value stored is pinhole Z-depth
    (config/depth_camera.json clip_note; measured in-render by gate D2 CULL, which read 57.99 m at
    pixel (289,374) where |ray| = 1.034, not the on-axis 60.0). Cached per (shape, intrinsics, far).

    `DepthDetectionSource`'s range window uses the ON-AXIS 60.0 for every pixel, so a corner
    component at 50 m is at its own cull and still passes; `Component.cull_headroom_m` is the
    per-pixel number that check is missing."""
    key = (intr.width, intr.height, intr.fx, intr.fy, intr.cx, intr.cy, float(far_clip_m))
    hit = _CULL_CACHE.get(key)
    if hit is not None:
        return hit
    u = np.arange(intr.width, dtype=np.float64)[None, :] + 0.5
    v = np.arange(intr.height, dtype=np.float64)[:, None] + 0.5
    ray = np.sqrt(((u - intr.cx) / intr.fx) ** 2 + ((v - intr.cy) / intr.fy) ** 2 + 1.0)
    out = (float(far_clip_m) / ray).astype(np.float32)
    _CULL_CACHE[key] = out
    return out


# ------------------------------------------------------------------------------------ the steps
def estimate_background(z: np.ndarray, k_px: int = CLOSING_K_PX) -> np.ndarray:
    """Local background depth = grey CLOSING of the depth field: every pit narrower than `k_px` is
    filled with what surrounds it, everything else is left alone.

    `maximum_filter` then `minimum_filter` rather than `ndimage.grey_closing` so the two halves are
    visible and separately timeable; the result is identical. Border mode is `nearest` and MEASURED
    not to matter: `reflect` and `mirror` give a bit-identical residual, because the residual at the
    frame's bottom edge comes from the ground ramp being TRUNCATED by the image, which no padding
    rule can restore (`wrap` is worse -- 2.022 m against 0.981 m at K=15 -- and is the one to avoid).

    +inf flows through untouched (sky stays sky). -inf must be removed by the caller BEFORE this is
    called: a single -inf would be spread over a KxK neighbourhood by the erosion half and would
    poison a whole window's background."""
    dil = ndimage.maximum_filter(z, size=k_px, mode="nearest")
    return ndimage.minimum_filter(dil, size=k_px, mode="nearest")


def nearness_margin(z: np.ndarray, params: SegmenterParams) -> np.ndarray:
    """`max(abs, frac*z)`, elementwise. ONE margin function with TWO uses -- the candidate test and
    the link-break test -- so "significantly nearer" cannot come to mean two different things inside
    one detector.

    Short-circuits at `frac == 0` rather than computing `0 * inf`, which is NaN and would make the
    margin at every sky pixel silently undefined."""
    if params.margin_frac == 0.0:
        return np.full(z.shape, params.margin_abs_m, dtype=np.float32)
    return np.maximum(params.margin_abs_m, params.margin_frac * np.abs(z))


def _link_break(cand: np.ndarray, z: np.ndarray, margin: np.ndarray) -> np.ndarray:
    """Cut the candidate mask wherever two 8-adjacent candidates differ in depth by more than the
    margin, so two near objects at different depths cannot label as one.

    The case this exists for is in this world already: a tree TRUNK is narrower than K, so unlike a
    canopy it IS a pit and IS a candidate (the RGB pixel study's `trunk == bird_1` confusion, from
    the other sensor, is the same geometry). A bird crossing in front of a trunk would otherwise
    merge with it and inherit the trunk's depth -- a confident detection metres too far, which is
    worse than a miss because it looks like success.

    It is surgical: a bird's own rim pixels have no candidate neighbours outside the bird (sky and
    background are not candidates), so their local spread is the bird's own diameter, 0.15-0.18 m
    measured, far under any margin. Cut pixels are removed from BOTH sides rather than assigned to
    the nearer one; the alternative is a tie-break rule with no evidence behind it."""
    big = np.where(cand, z, -np.inf)
    small = np.where(cand, z, np.inf)
    hi = ndimage.maximum_filter(big, size=3, mode="nearest")
    lo = ndimage.minimum_filter(small, size=3, mode="nearest")
    with np.errstate(invalid="ignore"):
        spread = hi - lo
    cut = cand & np.isfinite(spread) & (spread > margin)
    return cand & ~cut


def segment(depth: np.ndarray, intr: Intrinsics,
            params: SegmenterParams = SegmenterParams()) -> SegmentResult:
    """One depth frame -> `SegmentResult`. Pure: no state, no I/O, no clock, no pose."""
    z = np.asarray(depth, dtype=np.float32)
    if z.ndim != 2:
        raise ValueError(f"depth must be HxW, got shape {z.shape}")
    if z.shape != (intr.height, intr.width):
        raise ValueError(f"frame {z.shape} does not match camera_info "
                         f"{(intr.height, intr.width)} -- refusing to guess which is right")

    counters: Dict[str, int] = {}
    nan_px = int(np.isnan(z).sum())
    neg_inf = np.isneginf(z)
    counters["nan_px"] = nan_px
    counters["neg_inf_px"] = int(neg_inf.sum())

    # NaN -> +inf ("unknown background is far"), counted. Never silently coerced to a range.
    if nan_px:
        z = np.where(np.isnan(z), np.inf, z)

    # -inf = something inside the near clip. There is no range for it, so there is nothing honest to
    # report and the frame is REFUSED -- never "no detections". The trigger reuses `min_area_px`
    # rather than inventing a second area constant: one stray pixel is counted, a blob is a refusal.
    if neg_inf.any():
        lab, n = ndimage.label(neg_inf, structure=np.ones((3, 3), dtype=bool))
        if n:
            sizes = ndimage.sum(neg_inf, lab, index=np.arange(1, n + 1))
            if float(sizes.max()) >= params.min_area_px:
                counters["near_clip_blob_px"] = int(sizes.max())
                return SegmentResult(refused="near_clip", counters=counters)
        # Below the blob threshold: still removed before the closing, which would otherwise spread
        # one -inf pixel over a KxK window and blind it.
        z = np.where(neg_inf, np.inf, z)

    # A finite value AT or outside a clip plane is the clamp signature, not a measurement
    # (config/depth_camera.json no_return_semantics). Excluded from candidacy AND from the
    # background, counted, never clamped back.
    finite = np.isfinite(z)
    invalid = finite & ((z <= params.near_clip_m) | (z >= params.far_clip_m))
    counters["invalid_range_px"] = int(invalid.sum())
    if counters["invalid_range_px"]:
        z = np.where(invalid, np.inf, z)
        finite = np.isfinite(z)

    counters["finite_px"] = int(finite.sum())
    if not finite.any():
        # Legitimately empty (all sky), NOT a refusal: the sensor answered and the answer was
        # "nothing within range". The distinction matters to whoever reads the flight log.
        counters["candidate_px"] = 0
        return SegmentResult(counters=counters)

    bg = estimate_background(z, params.closing_k_px)
    margin = nearness_margin(z, params)
    with np.errstate(invalid="ignore"):
        step = np.where(finite, bg - z, -np.inf)
    cand = finite & (step > margin)
    counters["candidate_px"] = int(cand.sum())

    if params.link_break:
        before = int(cand.sum())
        cand = _link_break(cand, z, margin)
        counters["link_cut_px"] = before - int(cand.sum())

    struct = ndimage.generate_binary_structure(2, 1)   # 3x3 cross, as ndvi_detect uses
    m = cand
    if params.open_iter > 0:
        m = ndimage.binary_opening(m, structure=struct, iterations=params.open_iter)
    if params.close_iter > 0:
        m = ndimage.binary_closing(m, structure=struct, iterations=params.close_iter)

    labels, n = ndimage.label(m, structure=ndimage.generate_binary_structure(2, 2))  # 8-conn
    counters["components_raw"] = int(n)
    if n == 0:
        return SegmentResult(counters=counters)

    cull = cull_depth_map(intr, params.far_clip_m)
    kept: List[Component] = []
    rejected: List[Component] = []
    n_speck = n_cull = n_size = 0
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        sub = labels[sl] == i
        area = int(sub.sum())
        if area < params.min_area_px:
            n_speck += 1
            continue
        zs = z[sl][sub]
        zmed = float(np.median(zs))
        ys, xs = np.nonzero(sub)
        y0, x0 = sl[0].start, sl[1].start
        head = float(np.median(cull[sl][sub] - zs))
        r_meas = math.sqrt(area / math.pi)
        r_pred = intr.fx * params.size_prior_radius_m / zmed if zmed > 0 else float("inf")
        comp = Component(
            bbox=(float(sl[1].start), float(sl[0].start), float(sl[1].stop), float(sl[0].stop)),
            area_px=area,
            centroid_px=(float(xs.mean() + x0 + 0.5), float(ys.mean() + y0 + 0.5)),
            bbox_centre_px=(0.5 * (sl[1].start + sl[1].stop), 0.5 * (sl[0].start + sl[0].stop)),
            depth_median_m=zmed,
            depth_min_m=float(zs.min()),
            depth_p05_m=float(np.percentile(zs, 5)),
            depth_max_m=float(zs.max()),
            cull_headroom_m=head,
            size_ratio=float(r_meas / r_pred) if r_pred > 0 else float("inf"),
        )
        tags: List[str] = []
        if params.cull_edge_margin_m is not None and head < params.cull_edge_margin_m:
            tags.append("cull_edge")
            n_cull += 1
        if params.size_ratio_lo is not None and comp.size_ratio < params.size_ratio_lo:
            tags.append("too_small_for_range")
            n_size += 1
        if params.size_ratio_hi is not None and comp.size_ratio > params.size_ratio_hi:
            tags.append("too_large_for_range")
            n_size += 1
        comp.tags = tuple(tags)
        (rejected if tags else kept).append(comp)

    counters["rejected_speck"] = n_speck
    counters["rejected_cull_edge"] = n_cull
    counters["rejected_size_ratio"] = n_size
    counters["components_kept"] = len(kept)
    return SegmentResult(components=kept, rejected=rejected, counters=counters,
                         nearest_withheld_depth_m=(min(c.depth_median_m for c in rejected)
                                                   if rejected else None))


def as_segmenter(intr: Intrinsics, params: SegmenterParams = SegmenterParams()):
    """A `depth_detect.DepthSegmenter`-shaped callable: frame -> [(box, depth_m), ...].

    A REFUSED frame returns [] here because the seam's type has nowhere else to put it -- which is
    exactly why the wired version must NOT ship this adapter as-is: `DepthDetectionSource.on_frame`
    needs the refusal reason so it can bump a counter instead of recording a clear frame. Widening
    `DepthSegmenter` to carry a refusal is a contract change, and it belongs in the design note, not
    in a lambda."""
    def _seg(frame):
        return segment(frame, intr, params).as_boxes()
    return _seg


# ==================================================================================================
# Measurement helpers. These produce numbers quoted in the design doc, so they live with the code
# that produces them rather than in a scratch script nobody reruns.
# ==================================================================================================

def render_disc(shape: Tuple[int, int], cu: float, cv: float, r_px: float, depth_m: float,
                background: Optional[np.ndarray] = None) -> np.ndarray:
    """A filled disc of apparent radius `r_px` at pinhole centre (cu,cv), over `background` (default
    all +inf = sky). Pixel INDEX j is sampled at its centre, j+0.5, matching the corner-origin
    convention used everywhere here. The nearer surface wins, so an occluder really occludes."""
    h, w = shape
    z = (np.full((h, w), np.inf, dtype=np.float32) if background is None
         else background.astype(np.float32).copy())
    u = np.arange(w, dtype=np.float64)[None, :] + 0.5
    v = np.arange(h, dtype=np.float64)[:, None] + 0.5
    m = ((u - cu) ** 2 + (v - cv) ** 2) <= r_px * r_px
    z[m] = np.minimum(z[m], depth_m)
    return z


def ground_band(shape: Tuple[int, int], intr: Intrinsics, height_m: float,
                far_clip_m: float = 60.0) -> np.ndarray:
    """A flat ground plane `height_m` below a LEVEL camera, culled on Euclidean slant range exactly
    as gz does: `Z(v) = fy*h/(v-cy)` below the optical axis, +inf elsewhere.

    Reproduces the commissioned frames' ground band to the pixel (rows 374-479, Z 32.568-57.993,
    finite fraction 0.2036), which is what lets the self-test derive constants without shipping
    16 MB of base64."""
    h, w = shape
    v = np.arange(h, dtype=np.float64)[:, None] + 0.5
    with np.errstate(divide="ignore", invalid="ignore"):
        zrow = np.where(v > intr.cy, intr.fy * height_m / (v - intr.cy), np.inf)
    z = np.repeat(zrow, w, axis=1)
    z = np.where(z > 0, z, np.inf)
    cull = cull_depth_map(intr, far_clip_m)
    return np.where(z <= cull, z, np.inf).astype(np.float32)


def resolving_floor_px(intr: Intrinsics, params: SegmenterParams = SegmenterParams(),
                       depth_m: float = 30.0, offsets: Sequence[float] = (0.0, 0.25, 0.5),
                       lo: float = 0.5, hi: float = 4.0, step: float = 0.05) -> float:
    """Smallest apparent radius a sky-backed filled disc can have and still be detected, at the WORST
    sub-pixel placement over `offsets` in both axes.

    Same protocol as `tests/fieldguard_planning/test_depth_detect.py` used for the NDVI morphology's
    2.0 px, so the two are comparable. This is the re-measurement
    `config/depth_camera.json:min_resolving_radius_source` books for the segmenter session."""
    r = lo
    while r <= hi + 1e-9:
        ok = True
        for du in offsets:
            for dv in offsets:
                frame = render_disc((intr.height, intr.width),
                                    intr.cx + du, intr.cy + dv, r, depth_m)
                if not segment(frame, intr, params).components:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            return round(r, 4)
        r += step
    return float("nan")


def whole_object_range_m(intr: Intrinsics, params: SegmenterParams = SegmenterParams(),
                         object_radius_m: float = 0.18) -> float:
    """The range at which an object stops fitting inside K and starts returning as rim arcs instead
    of one blob: `2*fx*R/K`. Closer than this it is still DETECTED at its correct depth, but as
    several components offset from its centre, so a scoring rule that expects one box per bird must
    know where the crossover is."""
    return 2.0 * intr.fx * object_radius_m / params.closing_k_px


def near_detection_limit_m(intr: Intrinsics, params: SegmenterParams = SegmenterParams(),
                           object_radius_m: float = 0.18, lo: float = 0.2, hi: float = 20.0,
                           step: float = 0.1) -> float:
    """Nearest range at which a sky-backed sphere still yields ANY component. Measured, not reasoned
    about: below `whole_object_range_m` the object returns as arcs, and the arcs eventually fall
    under `min_area_px`. Returns the smallest swept range that still detects; `nan` if none does."""
    z = hi
    best = None
    while z >= lo - 1e-9:
        frame = render_disc((intr.height, intr.width), intr.cx, intr.cy,
                            intr.fx * object_radius_m / z, z)
        if segment(frame, intr, params).components:
            best = z
            z -= step
        else:
            break
    return float("nan") if best is None else round(best, 3)


# ==================================================================================================
# CLI -- score frames against labels.
# ==================================================================================================

def load_gz_depth_json(path) -> np.ndarray:
    """A `gz topic -e --json-output` dump of gz.msgs.Image: little-endian float32, HxW."""
    d = json.loads(Path(path).read_text())
    a = np.frombuffer(base64.b64decode(d["data"]), dtype="<f4")
    return a.reshape(int(d["height"]), int(d["width"])).astype(np.float32)


LABEL_SCHEMA = """--labels JSON schema. Every field is REQUIRED unless marked opt; a field that is
unknown must be null and explicitly so, because a missing field and a null one score differently:
{
  "intrinsics_from": "path to the LIVE camera_info dump (not config/depth_camera.json)",
  "frames": [
    {"path": "frame.json",
     "expect_refuse": false,          # opt: true == a REFUSAL is the correct answer, and a frame
                                      #      that returns 0 components instead has FAILED
     "birds": [                       # [] == a frame with no bird. NOT the same as the key absent.
       {"id": "bird_0",
        "u_px": 320.0, "v_px": 240.0, # pinhole corner-origin, of the bird CENTRE
        "z_depth_m": 46.0,            # Z-depth of the CENTRE (not slant, not surface)
        "radius_m": 0.18,
        "background": "sky|ground|canopy|mixed",
        "bg_depth_m": 58.0,           # Z-depth of what is directly BEHIND the bird; null for sky
        "standoff_m": 12.0,           # bg_depth_m - z_depth_m, or null for sky. THE field that
                                      #   attributes a miss: under margin(z) it is a KNOWN limit,
                                      #   over it, it is a detector bug
        "occluded": false,            # true == not in the image at all: an expected non-detection
        "visible_px": 12}             # opt: rendered footprint, for attributing a small-target miss
     ]}
  ]
}"""


def _score(frames: Sequence[dict], intr: Intrinsics, params: SegmenterParams,
           match_px: float = 12.0) -> List[dict]:
    rows = []
    for spec in frames:
        z = load_gz_depth_json(spec["path"])
        t0 = time.perf_counter()
        res = segment(z, intr, params)
        ms = (time.perf_counter() - t0) * 1000.0
        birds = spec.get("birds", [])
        used = set()
        if spec.get("expect_refuse"):
            # A refusal is the CORRECT answer here, and "0 components" is the WRONG one that looks
            # identical in any table printing only a detection count. Scored as its own outcome.
            rows.append({
                "frame": Path(spec["path"]).stem, "bird": (birds[0]["id"] if birds else "-"),
                "background": "near", "expect_miss": True, "detected": False,
                "refused": res.refused,
                "outcome": ("REFUSED-ok" if res.refused else "NOT-REFUSED-FAIL"),
                "centroid_err_px": None, "mask_centroid_err_px": None, "depth_err_m": None,
                "depth_med_m": None, "area_px": None, "size_ratio": None,
                "cull_headroom_m": None, "false_components": len(res.components),
                "rejected": len(res.rejected), "ms": round(ms, 2),
            })
            continue
        for b in birds:
            gu, gv = float(b["u_px"]), float(b["v_px"])
            zc, rad = float(b["z_depth_m"]), float(b.get("radius_m", 0.18))
            best, bestd = None, None
            for k, c in enumerate(res.components):
                if k in used:
                    continue
                d = math.hypot(c.bbox_centre_px[0] - gu, c.bbox_centre_px[1] - gv)
                if bestd is None or d < bestd:
                    best, bestd = k, d
            hit = best is not None and bestd <= match_px
            if hit:
                used.add(best)
            c = res.components[best] if hit else None
            rows.append({
                "frame": Path(spec["path"]).stem, "bird": b["id"],
                "background": b.get("background", "?"), "expect_miss": bool(b.get("occluded")),
                "detected": bool(hit), "refused": res.refused,
                "outcome": ("REFUSED" if res.refused else
                            ("miss-ok" if (not hit and b.get("occluded")) else
                             ("FALSE-HIT" if (hit and b.get("occluded")) else
                              ("det" if hit else "MISS")))),
                "centroid_err_px": None if not hit else round(bestd, 3),
                "mask_centroid_err_px": None if not hit else round(
                    math.hypot(c.centroid_px[0] - gu, c.centroid_px[1] - gv), 3),
                # Scored against the sphere's NEAREST SURFACE (centre minus radius): that is the
                # quantity an avoidance clearance is measured from.
                "depth_err_m": None if not hit else round(c.depth_median_m - (zc - rad), 4),
                "depth_med_m": None if not hit else round(c.depth_median_m, 3),
                "area_px": None if not hit else c.area_px,
                "size_ratio": None if not hit else round(c.size_ratio, 3),
                "cull_headroom_m": None if not hit else round(c.cull_headroom_m, 3),
                "false_components": len(res.components) - len(used),
                "rejected": len(res.rejected), "ms": round(ms, 2),
            })
        if not birds:
            rows.append({
                "frame": Path(spec["path"]).stem, "bird": "-", "background": "-",
                "expect_miss": True, "detected": False, "refused": res.refused,
                "outcome": ("REFUSED" if res.refused else "empty-ok"),
                "centroid_err_px": None, "mask_centroid_err_px": None, "depth_err_m": None,
                "depth_med_m": None, "area_px": None, "size_ratio": None,
                "cull_headroom_m": None, "false_components": len(res.components),
                "rejected": len(res.rejected), "ms": round(ms, 2),
            })
    return rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=LABEL_SCHEMA)
    ap.add_argument("--labels", required=True, help="label JSON (schema in --help)")
    ap.add_argument("--camera-info", help="override intrinsics_from in the label file")
    ap.add_argument("--json", action="store_true", help="emit rows as JSON instead of a table")
    ap.add_argument("--match-px", type=float, default=12.0,
                    help="centroid distance that counts as a match (default 12)")
    a = ap.parse_args(argv)

    spec = json.loads(Path(a.labels).read_text())
    intr = Intrinsics.from_gz_camera_info(a.camera_info or spec["intrinsics_from"])
    rows = _score(spec["frames"], intr, SegmenterParams(), a.match_px)
    if a.json:
        print(json.dumps(rows, indent=2))
        return 0
    fmt = "{:<16}{:<8}{:<7}{:<17}{:<9}{:<9}{:<7}{:<8}{:<9}{:<5}{:<7}"
    print(fmt.format("frame", "bird", "bg", "outcome", "cerr_px", "dz_m", "area", "ratio",
                     "cull_hr", "FP", "ms"))
    for r in rows:
        print(fmt.format(
            r["frame"], r["bird"], str(r["background"])[:6], r["outcome"],
            str(r["centroid_err_px"]), str(r["depth_err_m"]), str(r["area_px"]),
            str(r["size_ratio"]), str(r["cull_headroom_m"]),
            str(r["false_components"]), str(r["ms"])))
    n = len([r for r in rows if not r["expect_miss"]])
    det = len([r for r in rows if r["detected"] and not r["expect_miss"]])
    # A rate needs a denominator, and the denominator is printed next to the rate or not at all.
    print(f"\nvisible bird-frames (denominator): {n}   detected: {det}   "
          f"FNR: {'UNDEFINED (n=0) -- no verdict available' if n == 0 else round(1 - det / n, 4)}")
    print(f"false components/frame: "
          f"{round(sum(r['false_components'] for r in rows) / max(1, len(rows)), 3)}   "
          f"frames: {len(spec['frames'])}")
    bad = [r["frame"] for r in rows if r["outcome"] in ("NOT-REFUSED-FAIL", "FALSE-HIT", "MISS")]
    if bad:
        print("FAILING FRAMES: " + ", ".join(bad))
    return 0


if __name__ == "__main__":
    sys.exit(main())
