#!/usr/bin/env python3
"""The FORWARD depth segmenter: one depth frame -> near-obstacle boxes, by DEPTH DISCONTINUITY.

This is the flight-side module the `depth_detect.DepthSegmenter` seam takes in its constructor. The
prototype that chose the operator (`eval/depth_segmenter_proto.py`, DELETED 2026-09-10 under ADR-022
-- it ran in no CI job and duplicated this module with different constants) is recorded in
`docs/design/DEPTH_SEGMENTER_ALGORITHM.md`; the numbers that chose the
CONSTANTS are in the committed score artifact named by `DEFAULT_PARAMS_PROVENANCE` below. Nothing
here is tunable at call time -- the seam's callable takes exactly one argument, so every knob is
bound at construction and travels as one frozen object into the flight log.

THE RULE, in one line (DESIGN §2.1, ALGORITHM §2 -- two notes that converged on it independently):

    candidate  <=>  isfinite(D)  AND  near_m < D < far_m  AND  closing(D, K) - D > margin_m

`closing(D, K) = minimum_filter(maximum_filter(D, K), K)` is the LOCAL FAR ENVELOPE: the depth field
with every pit narrower than K px filled in with what surrounds it. That is the operational
definition of "what is behind this pixel", and it is the whole design:

  * a monotone ground ramp has no pits, so the closing reproduces it and the ground is never its own
    candidate (residual is an image-BORDER effect only -- see `border_residual_m`, which is what
    puts the floor under `margin_m`);
  * a canopy wider than K is its own background including at its rim;
  * a bird narrower than K is a pit, and its full depth step survives;
  * the far cull -- ground band ending against +inf -- is a ramp ENDING, not a pit.

WHY NOT `isfinite`, which is what gate D3 and the ADR-020 booking gate ran on: it works only when
the bird's background is sky. In the mission world the finite class also holds the ground band and
the tree canopies, so a bird projected into the ground band 8-connects to the ground and merges --
and the merge fails TWO ways, only one of which is a visible failure: an area ceiling deletes the
blob (bird gone, no counter moves), or the blob survives carrying the BACKGROUND's median depth, a
confident detection ~20 m too far. The second is worse because it looks like success, which is why
the scorer's matcher has a depth clause and this module has no `max_area` at all.

SATURATION IS HANDLED BY ORDERING, NOT BY AN AREA CEILING. Components come back sorted by median
depth ASCENDING and are cut at `max_boxes`, counting `boxes_truncated`: a truncation drops the
FARTHEST candidates, never the nearest. `max_boxes` is measured on the dataset's own worst-case
component count (the cluttered lane poses produce dozens of canopy components, all of them real
near objects) -- a round number chosen here would be the thing that deletes a far bird behind a
frame full of near canopies.

+inf (beyond far clip) is a legitimate BACKGROUND -- sky is the farthest thing there is -- and never
a candidate: `bg - (+inf)` is NaN, which compares False, and the clip window excludes it too.
-inf (inside near clip) and NaN are REFUSALS: excluded from the mask, excluded from the BACKGROUND
estimate, and COUNTED.

The substitution of +inf for them before the closing is LOAD-BEARING FOR NaN AND ONLY FOR NaN, and
that is measured, not argued. A NaN patch overlapping a target's KxK neighbourhood poisons the
filter pair and can ERASE the target: a 31x31 NaN patch beside a 20 m bird on a 46 m ramp takes the
bird from 68 candidate pixels to 2, i.e. below `min_area_px`, i.e. gone
(`tests/.../test_depth_segment.py::test_a_NaN_patch_...`). The -inf branch is INERT by contrast, and
the reason is the ORDER of the two halves: the DILATION runs first, so an -inf never survives a
maximum over its own window and its influence on the closing is confined to its own footprint --
which the clip window already rejects. Substituting it is a pure cost, and the measured cost is one
small FARTHER false component, never the near true one. It is kept because that direction is the
safe one and because `px_neg_inf` is 0 over the whole scored dataset, so removing it would be an
unmeasured change to a path no evidence covers. This module does not raise a frame-level refusal --
the seam's contract has nowhere to put one -- so `px_neg_inf` is the counter a reader watches for
airframe occlusion.

PURE FUNCTION: no RNG, no clock in the result, no state across frames, no learned weights, no
intrinsics, no pose, no static map. Same bytes in, same list out. Intrinsics live once, at the seam
(`DepthDetectionSource.set_intrinsics`, from the LIVE camera_info); a static map that suppressed in
PIXEL space, before a position exists, is the one direction that can hide a real obstacle
(depth_detect rule 9: annotate, never suppress).

numpy + scipy only, and for the same scoped reason `ndvi_detect` gives: these numbers are what
`scipy.ndimage` computed, and a hand-rolled reimplementation would be a different detector wearing
the same measurements. Both are already in the sim image (`python3-scipy`); no new dependency.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

from .clip_recorder import nearest_rank_p95

__all__ = [
    "DepthSegmenterParams",
    "DepthSegmenter",
    "DEFAULT_PARAMS",
    "DEFAULT_PARAMS_PROVENANCE",
    "MASK_TERMS",
    "closing",
    "border_residual_m",
    "analytic_ground_ramp",
]

# The three conjuncts of the mask expression, named so the mutation check (DESIGN §4.5 item 3) can
# delete one at a time by name instead of by editing the source. Deleting any one of them must turn
# the suite red; `tests/fieldguard_planning/test_depth_segment.py` runs all three.
MASK_TERMS: Tuple[str, str, str] = ("isfinite", "clip_window", "step_over_margin")


@dataclass(frozen=True)
class DepthSegmenterParams:
    """Every tunable, one home, frozen -- so the flight log can record the WHOLE configuration as
    one object and a reader can see there is nothing else.

    `near_m` / `far_m` mirror `DepthDetectionSource`'s EXCLUSIVE range window and exist only to keep
    pixels the seam would refuse out of the MASK; this module never returns a box it expects the
    seam to reject, and a test pins the two windows equal so there is one number, not two."""

    bg_window_px: int          # K: the flat square SE of the far-envelope closing
    margin_m: float            # a pixel must be NEARER than its background by MORE than this
    min_area_px: int           # components smaller than this are dropped and counted
    open_iter: int             # 3x3 cross binary opening before labelling; 0 = none
    max_boxes: int             # nearest-first cap; truncation drops the FARTHEST
    near_m: float              # clip window, EXCLUSIVE, both ends
    far_m: float
    link_break: bool = False   # cut 8-adjacent candidates differing by more than margin_m

    def __post_init__(self) -> None:
        if int(self.bg_window_px) < 3 or int(self.bg_window_px) % 2 == 0:
            raise ValueError(f"bg_window_px must be an odd int >= 3, got {self.bg_window_px!r}: an "
                             f"even window has no centre pixel, so the closing would be shifted by "
                             f"half a pixel and every box with it")
        if not (self.margin_m > 0.0):
            raise ValueError(f"margin_m must be > 0, got {self.margin_m!r}: at 0 the ground ramp's "
                             f"own border residual becomes a candidate")
        if int(self.min_area_px) < 1:
            raise ValueError(f"min_area_px must be >= 1, got {self.min_area_px!r}")
        if int(self.open_iter) < 0:
            raise ValueError(f"open_iter must be >= 0, got {self.open_iter!r}")
        if int(self.max_boxes) < 1:
            raise ValueError(f"max_boxes must be >= 1, got {self.max_boxes!r}")
        if not (0.0 < self.near_m < self.far_m):
            raise ValueError(f"need 0 < near_m < far_m, got {self.near_m!r}/{self.far_m!r}")


# --------------------------------------------------------------------------------------------
# THE ADOPTED CONSTANTS. Each line names the artifact section that chose it. Nothing here is a
# number anyone typed; `eval/score_depth_segmenter.py` re-derives all five from the dataset on
# every run and `tests/fieldguard_planning/test_depth_segmenter_score_artifact.py` pins these
# against the committed artifact, so the module and its evidence cannot drift apart.
# --------------------------------------------------------------------------------------------
DEFAULT_PARAMS_PROVENANCE = (
    "eval/results/depth_segmenter_score_20260907T110000Z.json -- the 85-frame cluttered dataset "
    "eval/results/depth_dataset_20260907, rendered in the pinned Gazebo Harmonic container on "
    "2026-09-07 and scored by eval/score_depth_segmenter.py under the rules DESIGN §3.2 "
    "pre-registered. Every value below is the OUTPUT of a recorded sweep, not a number anyone "
    "typed. "
    "bg_window_px=15: the smallest K in {15,17,21,25} with FNR 0 over the FNR_zero stations; "
    "K=21 and K=25 lose 6-7 canopy-backed birds, and they lose them by MERGING the bird into a "
    "53.9 m canopy component -- the failure the matcher's depth clause exists to catch "
    "(constants_sweep.k). "
    "margin_m=1.5: the smallest ladder value at or above 1.5x the measured K=15 border residual "
    "(0.9805 m -> floor 1.4708 m) with zero unmapped FP on the 8 level negatives. The FLOOR binds; "
    "the FP term is already satisfied at 0.5 m (constants_sweep.margin). "
    "min_area_px=10: the largest value keeping FNR 0 (12) minus one ladder step, against a "
    "smallest rendered bird footprint of 12 px at 46 m (constants_sweep.min_area). "
    "open_iter=0: scored both ways, identical on this dataset; 0 ships because min_area already "
    "does speck rejection with one knob instead of two, and an opening costs pixels on the "
    "smallest targets, which is where the horizon is set (constants_sweep.open_iter). "
    "max_boxes=64: 2x the worst-case component count over ALL 85 stations (24, on S062), rounded "
    "to a power of two -- NOT over the negatives alone, because nearest-first truncation drops the "
    "FARTHEST candidate and a cluttered lane is two dozen real near canopies (constants_sweep."
    "max_boxes). "
    "link_break=False: scored on and off under the CORRECTED merge rule (a neighbouring component "
    "at the background's depth is only a mislabel when the bird was not separately matched -- the "
    "first pass counted the correct SPLIT at S042/S046 as the failure it is the fix for). ON moves "
    "no bar: 0 misses, 0 unmapped FP, 0 merge mislabels either way. It is off because the design "
    "note's own precondition for keeping it -- never withholds a component -- is FALSIFIED: the "
    "seam cut can push two adjacent small objects below min_area_px and return nothing "
    "(multi_object_probe). ON's measured improvements (range p95 and worst centroid) are recorded "
    "in constants_sweep.link_break as an OPEN ITEM for a pre-registered round, not acted on here "
    "(constants_sweep.link_break)."
)

DEFAULT_PARAMS = DepthSegmenterParams(
    bg_window_px=15,
    margin_m=1.5,
    min_area_px=10,
    open_iter=0,
    max_boxes=64,
    near_m=0.1,
    far_m=60.0,
    link_break=False,
)


def closing(depth: np.ndarray, k_px: int) -> np.ndarray:
    """The LOCAL FAR ENVELOPE: `minimum_filter(maximum_filter(D, K), K)`.

    Spelled as the two halves rather than `ndimage.grey_closing` so each is separately timeable and
    visible; the result is identical. Border mode `nearest`, and that choice was MEASURED not to
    matter: `reflect` and `mirror` give a bit-identical residual, because the residual at the
    frame's bottom edge comes from the ground ramp being TRUNCATED by the image, which no padding
    rule can restore (`wrap` is worse and is the one to avoid).

    THE CALLER MUST HAVE REPLACED NaN WITH +inf FIRST, and NaN is the case that matters: scipy's
    filter pair compares, and every comparison against NaN is False, so a NaN inside a KxK window can
    survive the maximum and then be eroded ACROSS the window -- blinding the background of every
    pixel within K/2 of it and deleting any real obstacle there. -inf needs no such guard (the
    dilation runs first, so it never survives its own window); it is substituted anyway, and the
    measured price of that is one extra FAR component. See the module docstring."""
    return ndimage.minimum_filter(
        ndimage.maximum_filter(depth, size=int(k_px), mode="nearest"),
        size=int(k_px), mode="nearest")


class DepthSegmenter:
    """A `depth_detect.DepthSegmenter`: `__call__(depth) -> [([x0,y0,x1,y1], median_depth_m), ...]`.

    Boxes are half-open, x = column, y = row, in `ndvi_detect.detect_blobs`' convention, so the two
    detectors' boxes mean the same thing (pinned by a test that runs both on one shared mask).

    The depth that comes back with the box is the MEDIAN of the component's own mask pixels. Median,
    not mean: a component clipped by an occluding edge carries a few background-side pixels, and the
    median is the statistic that ignores them.

    `_mask_terms` is a TEST HOOK and nothing else -- it is how the mutation check deletes one
    conjunct of the mask expression at a time (DESIGN §4.5 item 3) without editing this file. It is
    private, it is not in `DepthSegmenterParams`, and therefore it can never reach the flight log or
    a config: the only supported value in flight is all three terms."""

    WALL_MS_WINDOW = 10000      # ~30 min at 5 Hz; the same window the two seams keep

    def __init__(self, params: DepthSegmenterParams = DEFAULT_PARAMS, *,
                 _mask_terms: Sequence[str] = MASK_TERMS):
        if not isinstance(params, DepthSegmenterParams):
            raise TypeError(f"DepthSegmenter needs a DepthSegmenterParams, got "
                            f"{type(params).__name__} -- the frozen dataclass is the whole "
                            f"configuration and the thing the flight log records")
        unknown = [t for t in _mask_terms if t not in MASK_TERMS]
        if unknown:
            raise ValueError(f"unknown mask term(s) {unknown}; known: {list(MASK_TERMS)}")
        self.params = params
        self._mask_terms = tuple(_mask_terms)
        self._frames = 0
        self._candidate_px = 0
        self._components_labelled = 0
        self._components_below_min_area = 0
        self._boxes_returned = 0
        self._boxes_truncated = 0
        self._px_pos_inf = 0
        self._px_neg_inf = 0
        self._px_nan = 0
        self._px_outside_clip_window = 0
        self._link_cut_px = 0
        self._largest_component_px = 0
        self._wall_ms: List[float] = []
        self._wall_ms_n = 0
        self._wall_ms_max: Optional[float] = None

    # ---------------------------------------------------------------- the operator
    def _mask(self, z: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """(candidate mask, sanitised depth). Split out so the mutation hook has exactly one place
        to act and the box step below cannot accidentally re-apply a deleted term."""
        p = self.params
        finite = np.isfinite(z)
        nan = np.isnan(z)
        neg_inf = np.isneginf(z)
        self._px_nan += int(nan.sum())
        self._px_neg_inf += int(neg_inf.sum())
        self._px_pos_inf += int(np.isposinf(z).sum())

        # -inf and NaN are refusals, not ranges: out of the mask AND out of the BACKGROUND estimate.
        # +inf is what they become for the closing only -- an unknown pixel is treated as FAR, the
        # direction that produces detections rather than hides them, and never as a range.
        #
        # THIS LINE IS LOAD-BEARING FOR NaN. Without it a NaN patch can survive the maximum_filter
        # and then be eroded across a KxK window, blinding the background of every pixel within K/2
        # and DELETING a real obstacle there (measured: 68 candidate px -> 2). It is inert for -inf,
        # which the dilation-first ordering already confines to its own footprint.
        zb = z
        if neg_inf.any() or nan.any():
            zb = np.where(neg_inf | nan, np.float32(np.inf), z)

        bg = closing(zb, p.bg_window_px)
        with np.errstate(invalid="ignore"):
            step = bg - z            # +inf - +inf = NaN -> False: sky is a background, never a
                                     # candidate. -inf gives +inf, which `isfinite` is what stops.
        in_window = (z > p.near_m) & (z < p.far_m)
        self._px_outside_clip_window += int((finite & ~in_window).sum())

        terms = []
        if "isfinite" in self._mask_terms:
            terms.append(finite)
        if "clip_window" in self._mask_terms:
            terms.append(in_window)
        if "step_over_margin" in self._mask_terms:
            with np.errstate(invalid="ignore"):
                terms.append(step > p.margin_m)
        cand = terms[0].copy() if terms else np.ones(z.shape, dtype=bool)
        for t in terms[1:]:
            cand &= t
        return cand, zb

    def _link_break(self, cand: np.ndarray, z: np.ndarray) -> np.ndarray:
        """Cut the candidate mask wherever two 8-adjacent candidates differ in depth by more than
        `margin_m`, so two near objects at different depths cannot label as one.

        SPLITS AND TAGS RATHER THAN REJECTING: it removes the pixels ON the seam between two
        candidate surfaces, so each side can survive as its own component -- it is not a
        component-level rejection rule, which is the direction DESIGN's §"concurrent work" note
        forbids (a rule that deletes "the near side of a larger surface" also deletes a wall).

        BUT IT DOES NOT SATISFY "NEVER WITHHOLDS A COMPONENT", and that was the design note's stated
        CONDITION for keeping it at all, so the weaker true claim is the one written here: it
        withholds no component that is still larger than `min_area_px` AFTER the cut. Cutting the
        seam costs pixels, and two adjacent small objects can both fall below the floor -- measured,
        3x4 px at 20.0 m touching 3x4 px at 30.0 m returns ONE box at 25.0 m with the rule off and
        NOTHING with it on (`multi_object_probe` in eval/score_depth_segmenter.py, pinned by
        tests/fieldguard_planning/test_depth_segment.py).

        OFF by default, and the reason is that falsified precondition rather than the merge column
        the first scoring pass mis-counted: under the corrected merge rule the rule ON moves no bar
        (it does improve range p95 and the centroid, which is recorded in the artifact's
        `constants_sweep.link_break` as the open item a future pre-registered round can act on).
        Kept in the source, with its counters, because the geometry it exists for -- a bird crossing
        a trunk narrower than K -- is in this world and only happens to be sub-margin here."""
        big = np.where(cand, z, -np.inf)
        small = np.where(cand, z, np.inf)
        hi = ndimage.maximum_filter(big, size=3, mode="nearest")
        lo = ndimage.minimum_filter(small, size=3, mode="nearest")
        with np.errstate(invalid="ignore"):
            spread = hi - lo
        cut = cand & np.isfinite(spread) & (spread > self.params.margin_m)
        self._link_cut_px += int(cut.sum())
        return cand & ~cut

    def __call__(self, depth) -> List[Tuple[List[float], float]]:
        t0 = time.monotonic()
        try:
            p = self.params
            z = depth
            if not isinstance(z, np.ndarray):
                raise TypeError(f"depth must be a numpy ndarray, got {type(z).__name__} -- "
                                f"coercing is how a list of lists or a uint16 millimetre encoding "
                                f"becomes a metre-valued obstacle")
            if z.dtype != np.float32:
                raise TypeError(f"depth must be float32 (the 32FC1 the sensor publishes), got "
                                f"{z.dtype} -- see above")
            if z.ndim != 2:
                raise ValueError(f"depth must be 2-D (H, W), got shape {z.shape}")
            self._frames += 1

            cand, zb = self._mask(z)
            if p.link_break:
                cand = self._link_break(cand, zb)
            self._candidate_px += int(cand.sum())

            if p.open_iter > 0:
                cand = ndimage.binary_opening(
                    cand, structure=ndimage.generate_binary_structure(2, 1),
                    iterations=int(p.open_iter))

            labels, n = ndimage.label(cand, structure=ndimage.generate_binary_structure(2, 2))
            self._components_labelled += int(n)
            if n == 0:
                return []

            found: List[Tuple[float, int, int, List[float]]] = []
            for i, sl in enumerate(ndimage.find_objects(labels), start=1):
                if sl is None:
                    continue
                sub = labels[sl] == i
                area = int(sub.sum())
                if area > self._largest_component_px:
                    self._largest_component_px = area
                if area < p.min_area_px:
                    self._components_below_min_area += 1
                    continue
                med = float(np.median(z[sl][sub]))
                found.append((med, int(sl[0].start), int(sl[1].start),
                              [float(sl[1].start), float(sl[0].start),
                               float(sl[1].stop), float(sl[0].stop)]))

            # NEAREST FIRST, then cap. No max_area: deleting the largest thing in the frame is
            # fail-dangerous by construction, and a truncation here throws away the FAR candidates.
            # Ties broken by (row, column) so the order is total and the output is byte-stable.
            found.sort(key=lambda r: (r[0], r[1], r[2]))
            if len(found) > p.max_boxes:
                self._boxes_truncated += len(found) - p.max_boxes
                found = found[:p.max_boxes]
            self._boxes_returned += len(found)
            return [(r[3], r[0]) for r in found]
        finally:
            ms = (time.monotonic() - t0) * 1000.0
            if len(self._wall_ms) >= self.WALL_MS_WINDOW:
                self._wall_ms.pop(0)
            self._wall_ms.append(ms)
            self._wall_ms_n += 1
            if self._wall_ms_max is None or ms > self._wall_ms_max:
                self._wall_ms_max = ms

    def counters(self) -> Dict[str, object]:
        """Plain ints and floats only -- this dict crosses a `json.dumps` into the flight log, where
        a numpy scalar raises TypeError.

        CUMULATIVE since construction, except `largest_component_px` (a running MAX) and the wall-ms
        trio. The wall clock is here and NOT in the returned boxes, which is what keeps the RESULT
        deterministic while the diagnostics stay honest about cost."""
        p95 = nearest_rank_p95(self._wall_ms)
        return {
            "frames": int(self._frames),
            "candidate_px": int(self._candidate_px),
            "components_labelled": int(self._components_labelled),
            "components_below_min_area": int(self._components_below_min_area),
            "boxes_returned": int(self._boxes_returned),
            "boxes_truncated": int(self._boxes_truncated),
            "px_pos_inf": int(self._px_pos_inf),
            "px_neg_inf": int(self._px_neg_inf),
            "px_nan": int(self._px_nan),
            "px_outside_clip_window": int(self._px_outside_clip_window),
            "link_cut_px": int(self._link_cut_px),
            "largest_component_px": int(self._largest_component_px),
            "seg_wall_ms_p95": (None if p95 is None else round(float(p95), 3)),
            "seg_wall_ms_max": (None if self._wall_ms_max is None
                                else round(float(self._wall_ms_max), 3)),
            "seg_wall_ms_n": int(self._wall_ms_n),
            "note": ("cumulative since construction; largest_component_px is a running max. "
                     "px_neg_inf counts gz's inside-near-clip refusals -- a frame with many of "
                     "them is an airframe-occlusion alarm, not an empty scene. "
                     "px_outside_clip_window counts FINITE depths at or outside the exclusive "
                     "(near_m, far_m) window, i.e. the clamp signature. boxes_truncated counts "
                     "components dropped by the nearest-first max_boxes cap: they are the FARTHEST "
                     "candidates, and a non-zero value means the frame saturated."),
        }


# ==================================================================================================
# The one measurement this module owns about ITSELF, because `margin_m`'s floor is derived from it
# and a constant whose derivation lives in a scratch script is a constant nobody can re-check.
# ==================================================================================================

def analytic_ground_ramp(height_px: int, width_px: int, fy: float, cy: float,
                         altitude_m: float, far_clip_m: float,
                         fx: float, cx: float) -> np.ndarray:
    """A flat ground plane `altitude_m` below a LEVEL camera, culled on Euclidean slant exactly as
    gz does: `Z(v) = fy*h/(v-cy)` below the optical axis, +inf elsewhere and beyond the cull.

    Reproduces the dataset's own ground band (rows 374-479, finite fraction ~0.204) closely enough
    that the residual measured on it is the residual the render has -- which is the point: this is
    the analytic stand-in the test can re-derive `margin_m`'s floor from without a 100 MB dataset."""
    v = np.arange(height_px, dtype=np.float64)[:, None] + 0.5
    u = np.arange(width_px, dtype=np.float64)[None, :] + 0.5
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(v > cy, fy * float(altitude_m) / (v - cy), np.inf)
    z = np.repeat(z, width_px, axis=1)
    ray = np.sqrt(((u - cx) / fx) ** 2 + ((v - cy) / fy) ** 2 + 1.0)
    return np.where((z > 0) & (z * ray <= float(far_clip_m)), z, np.inf).astype(np.float32)


def border_residual_m(depth: np.ndarray, k_px: int) -> float:
    """Max `closing(D, K) - D` over the finite pixels of a background-only frame.

    THE ONE NUMBER THAT IS NOT FREE (DESIGN §3.3). Over the frame INTERIOR a flat-SE closing
    reproduces a monotone ramp exactly, so this is entirely a frame-BORDER artifact: within K/2 rows
    of the image bottom there is no farther row to erode back with. It grows one-for-one with K, and
    `margin_m` must clear it -- so the chain is *border artifact -> margin -> smallest visible
    stand-off*, and that is why K is adopted at its smallest passing value rather than its most
    comfortable one."""
    finite = np.isfinite(depth)
    if not finite.any():
        return 0.0
    with np.errstate(invalid="ignore"):
        step = closing(depth, k_px) - depth
    return float(np.nanmax(np.where(finite, step, -np.inf)))


def params_with(base: DepthSegmenterParams, **kw) -> DepthSegmenterParams:
    """`dataclasses.replace` under a name the sweep can read. Exists so the scorer never constructs
    a params object field-by-field and silently omits one the dataclass later grows."""
    return replace(base, **kw)
