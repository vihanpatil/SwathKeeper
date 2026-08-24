#!/usr/bin/env python3
"""The ADOPTED dynamic-obstacle detector: birdness -> threshold -> blobs, on NDVI frames.

ONE home for the detector core. Before this module the code lived in `eval/blob.py` + the mask line
in `eval/baseline_ndvi.py`, which was fine while the detector only ever ran offline -- and wrong the
moment ADR-003 adopted it for flight: `eval/` is not importable inside the sim container, so the
live seam would have had to grow a second implementation, and a second implementation is a DIFFERENT
DETECTOR WEARING THE SAME VERDICT. The measured numbers below belong to this code; nothing else may
claim them.

WHAT THIS CODE MEASURED (ADR-003 amendment 7, ADOPT, 2026-08-23) on the real Gazebo render
(clip `eval/results/clips/real_flight_20260823T073644Z`, 1256 frames, measured applied-pose labels,
thresh -0.61 / min_area 6 / max_area 5000, IoU 0.3):
    precision 0.708   recall 0.850   frame FNR 0.150
    per-bird-track FNR 0.000  <-- the safety metric: every bird seen before closest approach
    denominator: 20 visible bird-frames over 3/3 birds
and on the synthetic seed-42 spike clip (the ADR-003 deciding run, thresh 0.05):
    precision 0.445   recall 0.981   per-bird-track FNR 0.000
    -- 0.445 is the bar any learned model must beat before it earns its complexity.

WHY scipy AND NOT A NUMPY REIMPLEMENTATION. Those numbers are what `scipy.ndimage` computed. A
hand-rolled morphology would be a new detector that has never been scored, so re-earning the verdict
would cost a flight. The image carries the dependency instead of the detector carrying a second
implementation (`sim/docker/Dockerfile` installs `python3-scipy`). This is the same scoped
third-party exception `ndvi_fusion.py` documents for numpy: pixel math gets numpy/scipy, the
planning core stays stdlib.

WHY THE THRESHOLD IS AN ARGUMENT AND NEVER A HIDDEN DEFAULT. `mask = ndvi < thresh` IS the detector,
and the right value differs by half a unit between renders (see the constants below). A defaulted
threshold would let a caller run the synthetic number against a real render and get zero detections
from a detector that looked like it ran -- ADR-003 amendment 1's actual defect. So `detect_ndvi`
takes it positionally, and each caller must say where its value came from:
  * offline scoring -> `eval/baseline_ndvi.resolve_threshold()` reads the clip's own `meta.json`
    (a clip knows which render it is; refuses rather than guessing when it does not say);
  * live flight    -> an explicit node parameter, recorded into the flight log with its provenance
    (a node has no clip to ask).

WHAT THIS MODULE DELIBERATELY IS NOT: a tracker, a classifier, or a range estimator. Frame-to-frame
association is not built (the policy's threat test is per-frame and the executor latches on
geometry, so a track id would be untested state), and turning a box into a world position is
`ndvi_georef`'s apparent-size ray under ADR-009 rule 2 -- never a ground-plane projection, which
puts a flying bird at z=0 and outside the threat cylinder.
"""
from __future__ import annotations

import time
from collections import deque
from typing import List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

from .avoidance_types import Detection
from .clip_recorder import STALE_PAIR_BOUND_S, nearest_rank_p95
from .ndvi_georef import (
    MOUNT_OFFSET_BODY_M,
    CameraIntrinsics,
    pixel_at_depth_to_enu,
    range_from_apparent_size,
)

Vec3 = Tuple[float, float, float]
QuatXYZW = Tuple[float, float, float, float]

# --------------------------------------------------------------------------------------
# Per-render thresholds. `mask = ndvi < thresh`, so `thresh` must sit BELOW the background the bird
# is seen against and ABOVE the bird itself; the two renders' backgrounds are half a unit apart.
# --------------------------------------------------------------------------------------

# Synthetic spike clips (sim/spike/gen_spike_clip.py). Unchanged, and deliberately so: this is the
# number ADR-003 was DECIDED on (precision 0.445 / recall 0.981 / per-bird-track FNR 0.000, seed 42)
# and `scripts/check_spike_regression.py` re-checks those figures. It sits below the synthetic
# soil (0.15) and above the synthetic bird core (~-0.08).
SYNTHETIC_THRESH = 0.05

# Real Gazebo render (ADR-007 thermal-as-NIR). Midpoint of the two classes the mask must separate,
# from the committed real-render evidence in `eval/results/gate2_summary.json` (996 frames):
#   bird mean NDVI -0.7888  |  soil mean NDVI -0.4285  ->  midpoint -0.6087
# PROVISIONAL, still, even after ADR-003 amendment 7 adopted the detector at this value: it was
# derived from per-class PIXEL statistics, and the detection evidence that now exists (n=20 visible
# bird-frames, 7 FP / 3 FN, 8 of 20 labels ambiguous) is a confirmation that it WORKS, not a
# characterisation of where it should sit. Lifting PROVISIONAL needs the false-positive study, not
# another passing run. Pinned to its source file by tests/fieldguard_planning/test_ndvi_detect.py
# and test_baseline_ndvi_threshold.py, which recompute the midpoint -- so the constant cannot
# quietly drift away from the evidence it came from.
REAL_RENDER_THRESH = -0.61

# The area window ADR-003 amendment 7 adopted, in pixels of the post-morphology component. On that
# clip all 24 accepted components measured 94-1781 px, so neither bar was binding -- they are a
# guard against speck noise and whole-image saturation, not a tuned filter.
DEFAULT_MIN_AREA = 6
DEFAULT_MAX_AREA = 5000


def detect_blobs(mask: np.ndarray, min_area: int, max_area: int, open_iter: int = 1,
                 close_iter: int = 1):
    """mask: bool (H,W) of candidate (bird) pixels. Returns list of [x0,y0,x1,y1] boxes.
    Morphological open (drop specks) then close (fill), 3x3 structure; label; area-filter.

    Boxes are half-open in image coordinates (x0,y0 inclusive, x1,y1 exclusive -- they are the
    label slice's start/stop), x = column, y = row, and come back in raster order of each
    component's first pixel. The area filter counts the POST-morphology component, not the raw
    mask. Shared verbatim by both ADR-003 arms so approach (a) and (b) differ only in the signal,
    not the machinery."""
    struct = ndimage.generate_binary_structure(2, 1)  # 4-connectivity 3x3 cross
    m = mask
    if open_iter > 0:
        m = ndimage.binary_opening(m, structure=struct, iterations=open_iter)
    if close_iter > 0:
        m = ndimage.binary_closing(m, structure=struct, iterations=close_iter)
    labels, n = ndimage.label(m, structure=ndimage.generate_binary_structure(2, 2))  # 8-conn
    boxes = []
    if n == 0:
        return boxes
    slices = ndimage.find_objects(labels)
    for i, sl in enumerate(slices, start=1):
        if sl is None:
            continue
        area = int((labels[sl] == i).sum())
        if area < min_area or area > max_area:
            continue
        ys, xs = sl
        boxes.append([float(xs.start), float(ys.start), float(xs.stop), float(ys.stop)])
    return boxes


def detect_ndvi(ndvi: np.ndarray, thresh: float, min_area: int = DEFAULT_MIN_AREA,
                max_area: int = DEFAULT_MAX_AREA):
    """The whole adopted detector: NDVI frame -> [x0,y0,x1,y1] boxes.

    Birdness is INVERSE NDVI: a bird is non-vegetation, so it reads low/negative against both the
    canopy and the soil, and `ndvi < thresh` isolates it even when it is seen over bare ground (the
    bird-over-soil hard case that decided ADR-003). NaN pixels compare False, so a hole in the frame
    is never a candidate.

    `thresh` is positional and undefaulted on purpose -- see the module docstring."""
    return detect_blobs(ndvi < thresh, min_area, max_area)


# ==================================================================================================
# THE LIVE SEAM (ADR-009 rule 2): boxes -> world-ENU `Detection`s the avoidance policy can consume.
# Everything above this line is the offline-scored detector core; everything below turns its output
# into a threat estimate, and is what `avoidance_node.py --detect` plugs into `detection_source`.
# ==================================================================================================

# The bird radius the range estimate assumes, in metres. The world's birds are 0.18 m
# (`config/birds/farm_world_birds.json`), and this is DELIBERATELY smaller, for two reasons:
#   1. Range scales linearly with the assumed radius, so under-estimating it places the bird NEARER
#      than it is along the ray -- the error direction that dodges too early rather than too late.
#   2. Reading 0.18 out of the world config would let the detector recover the exact answer it is
#      supposed to be INFERRING; a real deployment has a species guess, not a spec sheet.
# ADR-009's separately-proposed "conservative inflation factor" is COLLAPSED into this one number:
# depth scales linearly with radius, so two multiplicative knobs for one scalar is a second source
# of truth with no second degree of freedom. Measured consequence on the adopted clip: 3.27 m
# estimated against 3.92 m true.
BIRD_RADIUS_PRIOR_M = 0.15


def box_to_detection(box: Sequence[float], intr: CameraIntrinsics, drone_pos_enu: Vec3,
                     drone_quat_xyzw: QuatXYZW, stamp_s: float, frame_id: int,
                     radius_prior_m: float = BIRD_RADIUS_PRIOR_M,
                     mount_offset_body_m: Vec3 = MOUNT_OFFSET_BODY_M) -> Optional[Detection]:
    """One detector box -> one world-ENU `Detection`, ranged by APPARENT SIZE (ADR-009 rule 2).

    `ndvi_georef.pixel_to_ground_enu` is never called here and must never be: it answers "where does
    this ray meet the ground", which places a flying bird at z=0 and therefore OUTSIDE the policy's
    vertical threat band -- a real threat, silently suppressed. See `pixel_at_depth_to_enu`.

    Conventions, matched to the ground-truth labeller so the estimate and the label mean the same
    thing (`eval/label_from_sim.py` builds its boxes as [u-r, v-r, u+r, v+r]):
      * centre  = the box's mid-point in both axes -> (u, v);
      * r_px    = a quarter of the summed sides = half the MEAN side = the labeller's r.
    Returns None when the box has no positive extent (a zero-area box implies infinite range;
    `range_from_apparent_size` refuses rather than dividing by zero).

    `stamp_s` is passed through UNSHIFTED: it is the `/fg/ndvi/image` header stamp, i.e. absolute
    Gazebo sim seconds (ADR-007 makes the RGB header the georef anchor), and the policy's staleness
    gate subtracts it from a `now_s` read off the SAME gz clock stream. Making it relative to
    anything here is the clock-domain inversion that avoidance_node's tripwire exists to catch.

    `track_id` is deliberately None: this detector has no frame-to-frame association, the policy's
    threat test is per-frame, and the executor latches on geometry -- an id invented here would be
    untested state wearing the appearance of a tracker. The event log falls back to `det@{frame_id}`.
    """
    x0, y0, x1, y1 = (float(c) for c in box)
    r_px = 0.25 * ((x1 - x0) + (y1 - y0))
    depth_m = range_from_apparent_size(r_px, intr.fx, radius_prior_m)
    if depth_m is None:
        return None
    pos = pixel_at_depth_to_enu(0.5 * (x0 + x1), 0.5 * (y0 + y1), depth_m, intr,
                                drone_pos_enu, drone_quat_xyzw, mount_offset_body_m)
    return Detection(position_enu=pos, frame_id=int(frame_id), stamp_s=float(stamp_s),
                     source="ndvi_blob", track_id=None, confidence=1.0)


class NdviDetectionSource:
    """The ADR-009 `detection_source` seam: fused NDVI frames in, world-ENU `Detection`s out.

    Two halves, on two different threads of causation, which is exactly why this is one object:
      * `on_frame(...)` is called from the node's NDVI subscription, whenever a frame arrives
        (~5 Hz, bursty);
      * `__call__(t, drone)` is called from the 5 Hz control tick and returns the LATEST frame's
        detections, unconditionally.

    NO SECOND EXPIRY, on purpose. `__call__` never ages anything out: staleness is
    `PolicyParams.max_detection_age_s`'s job and only its job, evaluated against the stamp this
    class carries through untouched. A second timeout here would be a second source of truth for
    "too old", and the two would drift the first time either number moved.

    Intrinsics arrive LIVE (`/fg/ndvi/camera_info`), not from `config/ndvi_camera.json` -- the
    config is what we ASKED for, the message is what we GOT (`clip_recorder`'s rule). So this is
    constructed without them and armed by `set_intrinsics()`; frames arriving before that window
    closes are COUNTED (`dropped_no_intrinsics`) rather than silently discarded, because a silently
    discarded pre-`camera_info` window is precisely the defect ADR-013 am. 6a found in the recorder.

    Every counter is a plain int/float: this dict crosses a `json.dumps` boundary into the flight
    log, where a numpy scalar raises TypeError."""

    # ~30 min of frames at 5 Hz; the p95 is over the most recent window, `_n` reports the total so a
    # truncated window is visible rather than implied (same shape as RecorderCounters).
    WALL_MS_WINDOW = 10000

    def __init__(self, thresh: float, *, intr: Optional[CameraIntrinsics] = None,
                 min_area: int = DEFAULT_MIN_AREA, max_area: int = DEFAULT_MAX_AREA,
                 radius_prior_m: float = BIRD_RADIUS_PRIOR_M,
                 mount_offset_body_m: Vec3 = MOUNT_OFFSET_BODY_M,
                 max_pose_pair_residual_s: float = STALE_PAIR_BOUND_S):
        """`thresh` is required and positional for the same reason `detect_ndvi`'s is: the live node
        must state where its value came from and record it in the flight log."""
        self.thresh = float(thresh)
        self.intr = intr
        self.min_area = int(min_area)
        self.max_area = int(max_area)
        self.radius_prior_m = float(radius_prior_m)
        self.mount_offset_body_m = tuple(mount_offset_body_m)
        self.max_pose_pair_residual_s = float(max_pose_pair_residual_s)

        self._latest: List[Detection] = []
        self._frame_index = 0
        self.ndvi_msgs_received = 0
        self.dropped_no_intrinsics = 0
        self.dropped_no_pose_pair = 0
        self.dropped_stale_pose_pair = 0
        self.frames_with_detection = 0
        self.boxes_total = 0
        self._wall_ms: deque = deque(maxlen=self.WALL_MS_WINDOW)
        self._wall_ms_n = 0
        self._wall_ms_max: Optional[float] = None

    def set_intrinsics(self, intr: CameraIntrinsics) -> None:
        self.intr = intr

    def on_frame(self, stamp_s: float, ndvi, drone_pos_enu: Optional[Vec3],
                 drone_quat_xyzw: Optional[QuatXYZW],
                 pose_pair_residual_s: Optional[float] = None) -> List[Detection]:
        """Detect on one fused NDVI frame and REPLACE the latest detection set. Returns what it
        stored (also handy in tests). Every early return is counted; the counter is incremented
        before any guard, so `fuser.fused_count - ndvi_msgs_received` is transport loss on this hop
        and nothing else.

        `drone_pos_enu`/`drone_quat_xyzw` are the pose the node paired to this frame's own gz stamp
        (`clip_recorder.PoseBuffer.nearest`), NOT the latest pose: the render stalls and bursts, so
        arrival-pairing puts a bird metres down-track. A pair whose residual exceeds
        `max_pose_pair_residual_s` (the recorder's own measured bound) is DROPPED rather than used:
        at cruise speed that residual is metres of bird-position error, and a confidently-wrong
        world position is worse for the policy than an absent one.

        A frame that produces nothing clears the previous frame's detections -- "the bird left the
        frame" and "no frame arrived" must not look alike to the policy."""
        t0 = time.monotonic()
        self.ndvi_msgs_received += 1
        try:
            if self.intr is None:
                self.dropped_no_intrinsics += 1
                return self._latest
            if drone_pos_enu is None or drone_quat_xyzw is None:
                self.dropped_no_pose_pair += 1
                return self._latest
            if (pose_pair_residual_s is not None
                    and abs(float(pose_pair_residual_s)) > self.max_pose_pair_residual_s):
                self.dropped_stale_pose_pair += 1
                return self._latest

            frame_id = self._frame_index
            self._frame_index += 1
            boxes = detect_ndvi(ndvi, self.thresh, self.min_area, self.max_area)
            dets: List[Detection] = []
            for box in boxes:
                det = box_to_detection(box, self.intr, drone_pos_enu, drone_quat_xyzw,
                                       stamp_s, frame_id, self.radius_prior_m,
                                       self.mount_offset_body_m)
                if det is not None:
                    dets.append(det)
            self._latest = dets
            self.boxes_total += len(dets)
            if dets:
                self.frames_with_detection += 1
            return dets
        finally:
            ms = (time.monotonic() - t0) * 1000.0
            self._wall_ms.append(ms)
            self._wall_ms_n += 1
            if self._wall_ms_max is None or ms > self._wall_ms_max:
                self._wall_ms_max = ms

    def __call__(self, t: float, drone=None) -> List[Detection]:
        """The `DetectionSource` seam signature. `t` and `drone` are ignored: this detector works
        from camera frames, and ageing its output is the policy's staleness gate's job (see the
        class docstring). Returns the live list by reference-free copy so a caller cannot mutate
        the source's state."""
        return list(self._latest)

    def counters(self) -> dict:
        p95 = nearest_rank_p95(self._wall_ms)
        return {
            "ndvi_msgs_received": int(self.ndvi_msgs_received),
            "dropped_no_intrinsics": int(self.dropped_no_intrinsics),
            "dropped_no_pose_pair": int(self.dropped_no_pose_pair),
            "dropped_stale_pose_pair": int(self.dropped_stale_pose_pair),
            "frames_detected_on": int(self._frame_index),
            "frames_with_detection": int(self.frames_with_detection),
            "boxes_total": int(self.boxes_total),
            "detect_wall_ms_p95": (None if p95 is None else round(float(p95), 3)),
            "detect_wall_ms_max": (None if self._wall_ms_max is None
                                   else round(float(self._wall_ms_max), 3)),
            "detect_wall_ms_n": int(self._wall_ms_n),
            "note": ("ndvi_msgs_received counts every frame handed to on_frame BEFORE any guard; "
                     "frames_detected_on is the subset that actually reached the detector. "
                     "detect_wall_ms times the whole on_frame body on the node's single-threaded "
                     "executor, which shares it with the 5 Hz control tick; null means no sample, "
                     "never zero."),
        }
