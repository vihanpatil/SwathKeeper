#!/usr/bin/env python3
"""The FORWARD depth camera's half of the ADR-009 seam: mount extrinsic + `DepthDetectionSource`.

WHY THIS EXISTS (ADR-019 / Council Ruling 002, ratified 2026-08-26). ADR-017 am. 1 measured that no
mission speed makes the nadir camera safe: `speed_at_which_nadir_becomes_safe_mps = None`, because
bird_0 closes at its own 6.002 m/s and nadir's 2.480 m forward horizon would have to be 17.8-38.8 m.
The answer is a SECOND aperture looking forward, and depth rather than another visible band because
ADR-003 am. 10 measured that a same-optics second band buys exactly zero geometry (gap +0.000).

WHAT THIS MODULE IS, TODAY. The CONTRACT and the geometry, complete and tested; the SEGMENTER --
depth image in, candidate boxes out -- is deliberately NOT here. It lands next session with
perception, and it arrives through the constructor (`DepthDetectionSource(segmenter)`), which is
also what makes every rule below testable without a renderer.

------------------------------------------------------------------------------------------------
WHAT DIRECT RANGE RETIRES, AND WHAT IT DOES NOT
------------------------------------------------------------------------------------------------
RETIRED, for this sensor only:
  * `ndvi_georef.range_from_apparent_size` and `ndvi_detect.BIRD_RADIUS_PRIOR_M`. A depth camera
    MEASURES the range; the monocular apparent-size ray had to INFER it from an assumed object
    radius, so its depth inherited that prior's error linearly (measured on the adopted clip:
    3.27 m estimated against 3.92 m true; median range error 1.65 m over the flown detections).
    There is no radius prior in this file at all -- deliberately, so nobody can reintroduce one.
    The nadir path keeps its ray; nothing here changes `ndvi_detect`.

STILL BINDING, every one of them (ADR-009, unchanged by the sensor swap):
  1. NEVER a ground-plane projection. `pixel_to_ground_enu` answers "where does this ray meet the
     ground", which puts a flying bird at z=0, i.e. 15 m below ownship and OUTSIDE the policy's
     +/-6 m threat cylinder -- a real threat, silently suppressed. `depth_pixel_to_enu` below
     un-projects at the MEASURED depth, exactly as `pixel_at_depth_to_enu` does for the nadir path.
     Pinned as an executable assertion in tests/fieldguard_planning/test_depth_detect.py.
  2. `stamp_s` passes through UNSHIFTED -- absolute Gazebo sim seconds off the depth image's own
     header, the SAME clock `avoidance_node` reads for `now_s`. One clock domain. Making it
     relative to anything here is the inversion the node's clock tripwire exists to catch.
  3. NO SECOND EXPIRY. Staleness is `PolicyParams.max_detection_age_s`'s job and only its job.
  4. Intrinsics arrive LIVE from `/fg/depth/camera_info`, never from `config/depth_camera.json`:
     the config is what we ASKED for, the message is what we GOT.
  5. Every early return is COUNTED before any guard runs, so a silent drop is impossible
     (ADR-013 am. 6a: a silently discarded pre-`camera_info` window is exactly how the recorder
     lost most of a flight).
  6. `track_id` stays None. There is no tracker here, and an id invented at this layer would be
     untested state wearing the appearance of one.

NEW, and specific to depth:
  7. A NON-FINITE DEPTH IS A REFUSAL, NOT A RANGE. gz writes +inf beyond far clip and -inf nearer
     than near clip (gz-rendering8 `Ogre2DepthCamera` dataMaxVal/dataMinVal). Clamping either to
     its clip plane would report a confident obstacle at exactly 60.0 m. Dropped and counted.
  8. A depth outside the clip window is likewise dropped, not clamped -- same reason -- and the
     bounds are EXCLUSIVE. The clip planes are where gz stops MEASURING, not the last place it
     measures, so exactly 60.0 m is what a clamp looks like and must be refused; the inclusive
     bound this class shipped with accepted the one value rule 7 exists to reject.
  9. MAPPED CLUTTER IS ANNOTATED, NEVER SUPPRESSED. Tree canopies enter this frame from ~24.4 m and
     the ground from ~32.5 m -- both inside the 33.6 m horizon the booking gate needs at 5 m/s --
     and depth cannot tell a tree from a bird. An optional `static_map_annotator` flags a detection
     whose estimated position falls inside a known obstacle's 3D geofence
     (`Detection.static_map_hint` + a counter); the POLICY decides what to do with it. Filtering
     here would delete the bird-beside-a-tree case, and a missed obstacle is a safety bug where a
     wasted dodge is not. What this does NOT solve is clutter MERGING -- a bird projected into the
     ground band joins the ground component under an `isfinite` mask and vanishes into the max-area
     filter. That is the segmenter's problem, named in FORWARD_DEPTH_SENSOR.md's Known gaps.

------------------------------------------------------------------------------------------------
THE MOUNT, AND THE LESSON IT IS BUILT ON
------------------------------------------------------------------------------------------------
Gazebo camera sensors look along the SENSOR FRAME's +X, not a pinhole +Z. The ADR-007 nadir mount
was authored under the Z-forward instinct and therefore faced the HORIZON, upside down, for two
weeks while all four of its gates passed -- because every gate measured VALUES, never geometry
(ADR-007 am. 5; five recorded flights lost). So the optical-axis derivation here is a FUNCTION, not
a hand-written sign tuple, and its correctness check is that the same function evaluated at the
NDVI mount's live-verified rpy reproduces `ndvi_georef.CAMERA_TO_BODY_SIGNS` exactly
(`scripts/check_depth_mount.py`, and pinned by test).
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Callable, List, Optional, Sequence, Tuple

from .avoidance_types import Detection
from .clip_recorder import STALE_PAIR_BOUND_S, nearest_rank_p95
from .ndvi_georef import CameraIntrinsics, pixel_to_camera_ray, rotate_body_to_world

Vec3 = Tuple[float, float, float]
QuatXYZW = Tuple[float, float, float, float]
Mat3 = Tuple[Vec3, Vec3, Vec3]          # row-major

# A segmenter turns one depth frame into (box, depth_m) pairs. The DEPTH comes back with the box
# because the right depth statistic is a property of the segmentation MASK, which only the
# segmenter has; re-deriving one here from the bounding box would be a second, worse estimate of
# the same quantity. Boxes are [x0, y0, x1, y1] in the `detect_blobs` convention (x = column,
# y = row, half-open) so the two detectors' boxes mean the same thing.
DepthSegmenter = Callable[[object], Sequence[Tuple[Sequence[float], float]]]

# A static-map annotator answers one question about a world point -- "is this inside a MAPPED
# obstacle's 3D volume, and if so which one?" -- returning the obstacle id or None. Kept as a
# callable so this module never imports a map: the caller owns which map is authoritative.
StaticMapAnnotator = Callable[[Vec3], Optional[str]]

SOURCE_TAG = "depth_blob"


def geofence_annotator(gmap, vertical_margin_m: float = 1.0) -> StaticMapAnnotator:
    """A `StaticMapAnnotator` over an existing `geofence.GeofenceMap` -- the SAME
    `unsafe_obstacle_3d` volume test the executor's setpoint backstop already runs, so the
    annotation and the vetting can never disagree about where a tree is."""
    def annotate(point_enu: Vec3) -> Optional[str]:
        obs = gmap.unsafe_obstacle_3d(point_enu, vertical_margin_m)
        return None if obs is None else obs.id
    return annotate

# --------------------------------------------------------------------------------------------
# Mount extrinsic. Mirrors config/depth_camera.json "mount" -- same pattern (and same reason) as
# ndvi_georef.MOUNT_OFFSET_BODY_M mirroring config/ndvi_camera.json: the transform must be
# importable without reading a file, and tests/fieldguard_planning/test_depth_detect.py pins the
# mirror equal to the config so the two cannot drift.
# --------------------------------------------------------------------------------------------
FORWARD_MOUNT_OFFSET_BODY_M: Vec3 = (0.15, 0.0, 0.0)
FORWARD_MOUNT_RPY_RAD: Vec3 = (0.0, 0.0, 0.0)

# Gazebo's fixed camera convention, as a matrix from OPTICAL axes to SENSOR axes:
#     optical z (into the scene) = sensor +X       <- the whole lesson, in one line
#     optical x (image u+)       = sensor -Y
#     optical y (image v+)       = sensor -Z
# Columns are the images of the optical basis vectors, so this is
#     [[0, 0, 1], [-1, 0, 0], [0, -1, 0]].
OPTICAL_TO_SENSOR: Mat3 = ((0.0, 0.0, 1.0),
                           (-1.0, 0.0, 0.0),
                           (0.0, -1.0, 0.0))


def rpy_to_matrix(roll: float, pitch: float, yaw: float) -> Mat3:
    """SDF `<pose>` rpy -> rotation matrix, sensor/child frame into parent (body) frame.

    SDF's rpy is extrinsic X-then-Y-then-Z, i.e. R = Rz(yaw) @ Ry(pitch) @ Rx(roll)."""
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return (
        (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr),
        (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr),
        (-sp,     cp * sr,                cp * cr),
    )


def mat_mul(a: Mat3, b: Mat3) -> Mat3:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3))
                 for i in range(3))  # type: ignore[return-value]


def mat_vec(m: Mat3, v: Sequence[float]) -> Vec3:
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


def optical_to_body_matrix(roll: float, pitch: float, yaw: float) -> Mat3:
    """THE function the ADR-007 am. 5 bug would have been caught by: a mount's SDF rpy -> the map
    from OPTICAL axes (x right, y down, z into the scene) to BODY FLU axes.

    Composition is `R_sensor_to_body @ OPTICAL_TO_SENSOR`. Evaluated at the NDVI mount's
    (-pi/2, +pi/2, 0) it returns diag(1, -1, -1), which IS `ndvi_georef.CAMERA_TO_BODY_SIGNS` --
    the extrinsic that was verified in the real render to 2.2 px. That agreement is the reason this
    general form can be trusted for a mount nothing has photographed yet."""
    return mat_mul(rpy_to_matrix(roll, pitch, yaw), OPTICAL_TO_SENSOR)


def optical_axis_body(m: Mat3) -> Vec3:
    """Where the camera LOOKS, in body FLU: the image of optical +z, i.e. the matrix's 3rd column.
    For the forward mount this must be (1, 0, 0); for the nadir mount it is (0, 0, -1)."""
    return (m[0][2], m[1][2], m[2][2])


# The forward camera's optical->body map, derived from the pose above rather than typed out, so the
# rpy stays the single source of truth. Value: ((0,0,1), (-1,0,0), (0,-1,0)) -- optical z -> body
# +X (forward), optical u+ -> body -Y (right), optical v+ -> body -Z (down).
DEPTH_OPTICAL_TO_BODY: Mat3 = optical_to_body_matrix(*FORWARD_MOUNT_RPY_RAD)


def depth_pixel_to_enu(u_px: float, v_px: float, depth_m: float, intr: CameraIntrinsics,
                       drone_position_enu: Vec3, orientation_q: QuatXYZW,
                       mount_offset_body_m: Vec3 = FORWARD_MOUNT_OFFSET_BODY_M,
                       optical_to_body: Mat3 = DEPTH_OPTICAL_TO_BODY) -> Vec3:
    """(pixel, MEASURED pinhole depth) -> world-ENU point. The forward mount's sibling of
    `ndvi_georef.pixel_at_depth_to_enu`, and structurally identical to it -- same
    `pixel_to_camera_ray`, same `rotate_body_to_world`, same camera-position offset -- differing
    only in that the camera->body step is a full matrix instead of a diagonal sign tuple, because
    this mount's map is not diagonal.

    `depth_m` is PINHOLE Z-DEPTH along the optical axis, which is exactly what the gz depth camera
    writes (`point.x = -viewSpacePos.z` in gz-rendering8's ogre2 depth shader) -- not slant range.
    `pixel_to_camera_ray` returns a ray whose z component is exactly 1, so scaling the rotated ray
    by `depth_m` lands on the measured point with no normalisation step."""
    ray_cam = pixel_to_camera_ray(u_px, v_px, intr)          # z == 1 by construction
    ray_world = rotate_body_to_world(mat_vec(optical_to_body, ray_cam), orientation_q)
    ox, oy, oz = rotate_body_to_world(mount_offset_body_m, orientation_q)
    return (drone_position_enu[0] + ox + depth_m * ray_world[0],
            drone_position_enu[1] + oy + depth_m * ray_world[1],
            drone_position_enu[2] + oz + depth_m * ray_world[2])


# --------------------------------------------------------------------------------------------
# Resolvability. Used by the ADR-019 booking gate (scripts/predict_forward_lead.py) to turn the
# optics into an acquisition range: range = fx * object_radius / MIN_RESOLVING_RADIUS_PX.
# --------------------------------------------------------------------------------------------
# MEASURED, not asserted: the smallest apparent radius at which a filled disc still survives the
# ADOPTED morphology (`ndvi_detect.detect_blobs` -- 3x3 binary open, then close, then
# DEFAULT_MIN_AREA = 6 px) at the WORST sub-pixel placement. r = 1.9 px (9 raw pixels) is erased by
# the opening at a pixel-centred placement; r = 2.0 px (13 raw pixels) survives at every offset
# swept. tests/fieldguard_planning/test_depth_detect.py re-measures this on every run against the
# real `detect_blobs`, so the constant cannot drift away from the code that produced it.
MIN_RESOLVING_RADIUS_PX = 2.0


def acquisition_range_m(fx_px: float, object_radius_m: float,
                        min_radius_px: float = MIN_RESOLVING_RADIUS_PX) -> float:
    """Range at which an object of `object_radius_m` shrinks to `min_radius_px` apparent radius.

    A GEOMETRIC UPPER BOUND from the pinhole model plus the morphology -- NOT a render measurement.
    gz's depth camera runs `SetAntiAliasing(2)`, and what that does to a 4-px target's depth values
    at 46 m is unmeasured. ADR-019 item 6 requires the booking gate to run on the sensor's own
    live-measured horizon, which is why `predict_forward_lead.py` takes `--acq-range-m`."""
    if fx_px <= 0.0 or object_radius_m <= 0.0 or min_radius_px <= 0.0:
        raise ValueError("acquisition_range_m needs positive fx, radius and min_radius_px")
    return fx_px * object_radius_m / min_radius_px


def band_covered_from_m(fy_px: float, cy_px: float, band_half_height_m: float) -> float:
    """Nearest range at which the full +/-`band_half_height_m` threat band fits in the frame.

    A level forward camera's vertical half-extent at range R is R * cy / fy, so the band fits for
    R >= band_half_height * fy / cy. With this mount (fy 520.006, cy 240) and ADR-019's +/-6 m band
    that is 13.00 m -- comfortably inside the 17.8-38.8 m horizon the replay requires, which is the
    reason the mount carries no down-tilt (see config/depth_camera.json mount.tilt_rejected_note).
    Nearer than this the band is wider than the frustum, which is a NEAR-field limit, not a horizon
    limit: by then the maneuver is already committed."""
    if fy_px <= 0.0 or cy_px <= 0.0:
        raise ValueError("band_covered_from_m needs positive fy and cy")
    return band_half_height_m * fy_px / cy_px


# --------------------------------------------------------------------------------------------
# THE SEAM
# --------------------------------------------------------------------------------------------
class DepthDetectionSource:
    """The ADR-009 `detection_source` seam, depth flavour: depth frames in, world-ENU
    `Detection`s out. Same two-halves shape as `ndvi_detect.NdviDetectionSource`, on purpose --
    `on_frame(...)` runs on the camera subscription, `__call__(t, drone)` runs on the control tick
    and returns the LATEST frame's detections unconditionally.

    Construction takes the SEGMENTER because that is the part that does not exist yet: it lands
    next session with perception, and injecting it means every rule this class owns (guards,
    counters, stamp passthrough, un-projection, range refusal) is testable today with a fake.

    `min_range_m` / `max_range_m` default to the SDF clip planes because gz writes -inf/+inf
    outside them, and the bounds are EXCLUSIVE: a value AT a clip plane is the renderer saying "no
    return", not a measurement, and this class refuses rather than clamps.

    `static_map_annotator` is optional. Given one, a detection whose estimated position falls inside
    a mapped obstacle's 3D volume is FLAGGED (`Detection.static_map_hint`) and counted -- never
    dropped. See rule 9 in the module docstring for why annotate-not-filter is the safety-correct
    direction here."""

    WALL_MS_WINDOW = 10000      # ~30 min at 5 Hz; same window as the NDVI source's

    def __init__(self, segmenter: DepthSegmenter, *,
                 intr: Optional[CameraIntrinsics] = None,
                 min_range_m: float = 0.1,
                 max_range_m: float = 60.0,
                 mount_offset_body_m: Vec3 = FORWARD_MOUNT_OFFSET_BODY_M,
                 optical_to_body: Mat3 = DEPTH_OPTICAL_TO_BODY,
                 static_map_annotator: Optional[StaticMapAnnotator] = None,
                 max_pose_pair_residual_s: float = STALE_PAIR_BOUND_S):
        if segmenter is None:
            raise ValueError(
                "DepthDetectionSource needs a segmenter (depth frame -> [(box, depth_m)]). It is a "
                "constructor argument and not a default so that a node can never come up with a "
                "detector that silently detects nothing -- the ADR-013 am. 6a failure mode.")
        if not (0.0 < min_range_m < max_range_m):
            raise ValueError(f"need 0 < min_range_m < max_range_m, got {min_range_m}/{max_range_m}")
        self.segmenter = segmenter
        self.intr = intr
        self.min_range_m = float(min_range_m)
        self.max_range_m = float(max_range_m)
        self.mount_offset_body_m = tuple(mount_offset_body_m)
        self.optical_to_body = optical_to_body
        self.static_map_annotator = static_map_annotator
        self.max_pose_pair_residual_s = float(max_pose_pair_residual_s)

        self._latest: List[Detection] = []
        self._frame_index = 0
        self.depth_msgs_received = 0
        self.dropped_no_intrinsics = 0
        self.dropped_no_pose_pair = 0
        self.dropped_stale_pose_pair = 0
        self.dropped_non_finite_depth = 0
        self.dropped_out_of_range = 0
        self.detections_near_known_obstacle = 0
        self.static_map_annotator_errors = 0
        self.frames_with_detection = 0
        self.boxes_total = 0
        self._wall_ms: deque = deque(maxlen=self.WALL_MS_WINDOW)
        self._wall_ms_n = 0
        self._wall_ms_max: Optional[float] = None

    def set_intrinsics(self, intr: CameraIntrinsics) -> None:
        """Armed from the LIVE `/fg/depth/camera_info`, never from the config file."""
        self.intr = intr

    def box_to_detection(self, box: Sequence[float], depth_m: float, drone_pos_enu: Vec3,
                         drone_quat_xyzw: QuatXYZW, stamp_s: float,
                         frame_id: int) -> Optional[Detection]:
        """One (box, measured depth) -> one world-ENU `Detection`, or None with a counter bumped.

        No apparent-size ray, no radius prior, no ground plane: the depth IS the range, and the
        only judgement this method makes is whether the renderer actually returned one."""
        if self.intr is None:
            return None
        d = float(depth_m)
        if not math.isfinite(d):
            # +inf = beyond far clip, -inf = inside near clip. Both mean "no return".
            self.dropped_non_finite_depth += 1
            return None
        # EXCLUSIVE, both ends: gz stops measuring AT the clip planes, so exactly min/max is what a
        # clamp would look like -- the one value this method's own docstring promises to refuse.
        if not (self.min_range_m < d < self.max_range_m):
            self.dropped_out_of_range += 1
            return None
        x0, y0, x1, y1 = (float(c) for c in box)
        pos = depth_pixel_to_enu(0.5 * (x0 + x1), 0.5 * (y0 + y1), d, self.intr,
                                 drone_pos_enu, drone_quat_xyzw,
                                 self.mount_offset_body_m, self.optical_to_body)
        hint = self._static_map_hint(pos)
        return Detection(position_enu=pos, frame_id=int(frame_id), stamp_s=float(stamp_s),
                         source=SOURCE_TAG, track_id=None, confidence=1.0,
                         static_map_hint=hint)

    def _static_map_hint(self, pos: Vec3) -> Optional[str]:
        """Annotate, never filter (rule 9). A broken map degrades to 'unannotated' and is counted --
        never to 'undetected', which is the one direction that could hide a real obstacle."""
        if self.static_map_annotator is None:
            return None
        try:
            hint = self.static_map_annotator(pos)
        except Exception:
            self.static_map_annotator_errors += 1
            return None
        if hint is not None:
            self.detections_near_known_obstacle += 1
        return None if hint is None else str(hint)

    def on_frame(self, stamp_s: float, depth, drone_pos_enu: Optional[Vec3],
                 drone_quat_xyzw: Optional[QuatXYZW],
                 pose_pair_residual_s: Optional[float] = None) -> List[Detection]:
        """Segment one depth frame and REPLACE the latest detection set.

        `drone_pos_enu`/`drone_quat_xyzw` are the pose paired to THIS frame's own gz stamp
        (`clip_recorder.PoseBuffer.nearest`), not the latest pose: the render stalls and bursts, and
        arrival-pairing would put an obstacle metres down-track. A pair whose residual exceeds
        `max_pose_pair_residual_s` is DROPPED rather than used -- at cruise that residual is metres
        of position error, and a confidently-wrong world position is worse than an absent one.

        A frame that produces nothing CLEARS the previous frame's detections: "the bird left the
        frame" and "no frame arrived" must never look alike to the policy."""
        t0 = time.monotonic()
        self.depth_msgs_received += 1
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
            dets: List[Detection] = []
            for box, depth_m in self.segmenter(depth):
                det = self.box_to_detection(box, depth_m, drone_pos_enu, drone_quat_xyzw,
                                            stamp_s, frame_id)
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
        from camera frames, and ageing its output is the policy's staleness gate's job."""
        return list(self._latest)

    def counters(self) -> dict:
        """Plain ints/floats only -- this dict crosses a `json.dumps` boundary into the flight log,
        where a numpy scalar raises TypeError."""
        p95 = nearest_rank_p95(self._wall_ms)
        return {
            "depth_msgs_received": int(self.depth_msgs_received),
            "dropped_no_intrinsics": int(self.dropped_no_intrinsics),
            "dropped_no_pose_pair": int(self.dropped_no_pose_pair),
            "dropped_stale_pose_pair": int(self.dropped_stale_pose_pair),
            "dropped_non_finite_depth": int(self.dropped_non_finite_depth),
            "dropped_out_of_range": int(self.dropped_out_of_range),
            "detections_near_known_obstacle": int(self.detections_near_known_obstacle),
            "static_map_annotator_errors": int(self.static_map_annotator_errors),
            "frames_detected_on": int(self._frame_index),
            "frames_with_detection": int(self.frames_with_detection),
            "boxes_total": int(self.boxes_total),
            "detect_wall_ms_p95": (None if p95 is None else round(float(p95), 3)),
            "detect_wall_ms_max": (None if self._wall_ms_max is None
                                   else round(float(self._wall_ms_max), 3)),
            "detect_wall_ms_n": int(self._wall_ms_n),
            "note": ("depth_msgs_received counts every frame handed to on_frame BEFORE any guard; "
                     "frames_detected_on is the subset that reached the segmenter. "
                     "dropped_non_finite_depth counts gz's +/-inf no-return pixels reaching a box "
                     "(never clamped to a clip plane); dropped_out_of_range counts finite depths "
                     "outside the EXCLUSIVE (min_range_m, max_range_m) window. Both are per-BOX, "
                     "not per-frame. detections_near_known_obstacle is an ANNOTATION count, not a "
                     "drop count -- those detections were returned to the policy."),
        }
