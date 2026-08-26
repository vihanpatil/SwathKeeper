"""Tests for the ADR-019 forward depth mount: the extrinsic, the seam contract, the static gate.

THE POINT OF THIS FILE is two cross-checks and one measurement, not the unit coverage around them:

  1. `TestMountExtrinsic` -- the general rpy -> optical-axis function, evaluated at the NADIR
     mount's rpy, must reproduce `ndvi_georef.CAMERA_TO_BODY_SIGNS`. That extrinsic was verified in
     the REAL RENDER to 2.2 px against a 15 px bar, so agreeing with it is what licenses trusting
     the same function on a mount nothing has photographed yet. The same tests pin that the
     "obvious" pinhole-Z-forward rpy aims the forward camera at the right flank -- the ADR-007
     amendment 5 bug, made permanently visible instead of merely commented about.

  2. `TestResolvability` -- `MIN_RESOLVING_RADIUS_PX` is re-MEASURED here on every run against the
     adopted morphology (`ndvi_detect.detect_blobs`), at the worst sub-pixel placement, rather than
     trusted as a constant. The ADR-019 booking gate turns that number into an acquisition range,
     so a silent drift in it would move a safety verdict.

  3. `TestSeamContract` -- what ADR-009 still binds after direct range retires the apparent-size
     ray: never a ground plane, one clock domain, no second expiry, counters before guards, and a
     non-finite gz depth is a REFUSAL rather than a clamp to the clip plane.

`TestStaticMountGate` runs `scripts/check_depth_mount.py` in-process so the host gate is part of the
suite and not a thing someone has to remember to run.

Runs on the host: numpy + scipy (the morphology measurement), no rclpy, no Docker.
"""
import json
import math
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import numpy as np  # noqa: E402

import check_depth_mount  # noqa: E402
from fieldguard_planning.depth_detect import (  # noqa: E402
    DEPTH_OPTICAL_TO_BODY, FORWARD_MOUNT_OFFSET_BODY_M, FORWARD_MOUNT_RPY_RAD,
    MIN_RESOLVING_RADIUS_PX, SOURCE_TAG, DepthDetectionSource, acquisition_range_m,
    band_covered_from_m, depth_pixel_to_enu, geofence_annotator, mat_vec, optical_axis_body,
    optical_to_body_matrix,
)
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402
from fieldguard_planning.ndvi_detect import (  # noqa: E402
    DEFAULT_MAX_AREA, DEFAULT_MIN_AREA, detect_blobs,
)
from fieldguard_planning.ndvi_georef import (  # noqa: E402
    CAMERA_TO_BODY_SIGNS, CameraIntrinsics, MOUNT_OFFSET_BODY_M, pixel_to_ground_enu,
)

DEPTH_CONFIG = REPO_ROOT / "config" / "depth_camera.json"
NDVI_CONFIG = REPO_ROOT / "config" / "ndvi_camera.json"

IDENTITY_Q = (0.0, 0.0, 0.0, 1.0)          # (x, y, z, w): nose east, level
INTR = CameraIntrinsics.from_config(640, 480, 1.1033)


class TestMountExtrinsic(unittest.TestCase):
    def test_formula_reproduces_the_live_verified_nadir_extrinsic(self):
        """THE cross-check. ADR-007's mount rpy is (-pi/2, +pi/2, 0) and its camera->body map was
        proven in the render; the general function must land on exactly that."""
        m = optical_to_body_matrix(*json.loads(NDVI_CONFIG.read_text())
                                   ["mount"]["mount_pose_xyz_rpy"][3:])
        for i in range(3):
            for j in range(3):
                want = CAMERA_TO_BODY_SIGNS[i] if i == j else 0.0
                self.assertAlmostEqual(m[i][j], want, places=12,
                                       msg=f"nadir optical->body [{i}][{j}]")
        self.assertEqual(tuple(round(a, 12) for a in optical_axis_body(m)), (0.0, 0.0, -1.0))

    def test_forward_mount_looks_along_body_plus_x(self):
        self.assertEqual(tuple(round(a, 12) for a in optical_axis_body(DEPTH_OPTICAL_TO_BODY)),
                         (1.0, 0.0, 0.0))

    def test_image_axes_are_right_and_down(self):
        self.assertEqual(tuple(round(a, 12) for a in mat_vec(DEPTH_OPTICAL_TO_BODY, (1, 0, 0))),
                         (0.0, -1.0, 0.0))     # u+ -> body -Y = the vehicle's right
        self.assertEqual(tuple(round(a, 12) for a in mat_vec(DEPTH_OPTICAL_TO_BODY, (0, 1, 0))),
                         (0.0, 0.0, -1.0))     # v+ -> body -Z = down

    def test_the_pinhole_instinct_rpy_would_aim_at_the_right_flank(self):
        """ADR-007 am. 5 in executable form: rpy (-pi/2, 0, -pi/2) is what a ROS optical-frame
        habit produces for a 'forward' camera, and under Gazebo's sensor-+X convention it points
        the optical axis at body -Y. If this ever equals +X, the convention changed and every
        mount in the repo needs re-deriving."""
        axis = optical_axis_body(optical_to_body_matrix(-math.pi / 2, 0.0, -math.pi / 2))
        self.assertEqual(tuple(round(a, 12) for a in axis), (0.0, -1.0, 0.0))

    def test_the_two_mounts_are_not_the_same_aperture(self):
        self.assertNotEqual(tuple(FORWARD_MOUNT_OFFSET_BODY_M), tuple(MOUNT_OFFSET_BODY_M))
        self.assertNotEqual(optical_axis_body(DEPTH_OPTICAL_TO_BODY), (0.0, 0.0, -1.0))

    def test_code_mirror_matches_the_config(self):
        pose = json.loads(DEPTH_CONFIG.read_text())["mount"]["mount_pose_xyz_rpy"]
        self.assertEqual(list(FORWARD_MOUNT_OFFSET_BODY_M) + list(FORWARD_MOUNT_RPY_RAD),
                         [float(v) for v in pose])


class TestUnprojection(unittest.TestCase):
    """Hand-computed fixtures, the way test_ndvi_georef.py does it: a transform nobody checked
    against arithmetic they did by hand is a transform nobody has checked."""

    def test_principal_pixel_at_depth_lands_straight_ahead(self):
        # Nose east (identity quat), so body +X = world +X. Camera sits 0.15 m ahead of the drone.
        p = depth_pixel_to_enu(INTR.cx, INTR.cy, 25.0, INTR, (10.0, 20.0, 15.0), IDENTITY_Q)
        self.assertAlmostEqual(p[0], 10.0 + 0.15 + 25.0, places=9)
        self.assertAlmostEqual(p[1], 20.0, places=9)
        self.assertAlmostEqual(p[2], 15.0, places=9)

    def test_off_axis_pixel_goes_right_and_down(self):
        """A pixel one focal length right of centre and half a focal length below it, at 20 m,
        must land 20 m ahead, 20 m to the RIGHT (world -Y at nose-east) and 10 m DOWN."""
        p = depth_pixel_to_enu(INTR.cx + INTR.fx, INTR.cy + 0.5 * INTR.fy, 20.0, INTR,
                               (0.0, 0.0, 15.0), IDENTITY_Q)
        self.assertAlmostEqual(p[0], 0.15 + 20.0, places=6)
        self.assertAlmostEqual(p[1], -20.0, places=6)
        self.assertAlmostEqual(p[2], 15.0 - 10.0, places=6)

    def test_never_a_ground_plane_projection(self):
        """ADR-009 rule 2, pinned. A bird 4 m below a 15 m cruise must come back at z=11, inside
        the policy's +/-6 m band -- NOT at z=0, which is where the ground-plane answer puts it and
        which silently suppresses a real threat."""
        drone = (0.0, 0.0, 15.0)
        # A pixel below centre; choose the depth that places the point 4 m below the camera.
        v = INTR.cy + 0.2 * INTR.fy
        p = depth_pixel_to_enu(INTR.cx, v, 20.0, INTR, drone, IDENTITY_Q)
        self.assertAlmostEqual(p[2], 15.0 - 4.0, places=6)
        ground = pixel_to_ground_enu(INTR.cx, v, INTR, drone, IDENTITY_Q)
        self.assertIsNotNone(ground)                    # the ground answer exists...
        self.assertGreater(p[2], 5.0)                   # ...and this is emphatically not it


class TestResolvability(unittest.TestCase):
    @staticmethod
    def _disc(r_px, dx, dy, size=41):
        c = size // 2
        yy, xx = np.mgrid[0:size, 0:size]
        return ((xx - c - dx) ** 2 + (yy - c - dy) ** 2) <= r_px * r_px

    def _survives(self, r_px):
        offsets = [(0, 0), (0.5, 0), (0, 0.5), (0.5, 0.5), (0.25, 0.25), (0.5, 0.25)]
        return all(len(detect_blobs(self._disc(r_px, dx, dy), DEFAULT_MIN_AREA, DEFAULT_MAX_AREA))
                   == 1 for dx, dy in offsets)

    def test_the_constant_is_the_measured_floor(self):
        """Re-measures rather than restates: MIN_RESOLVING_RADIUS_PX must survive the adopted
        morphology at every sub-pixel offset, and one tenth of a pixel smaller must not."""
        self.assertTrue(self._survives(MIN_RESOLVING_RADIUS_PX),
                        f"r={MIN_RESOLVING_RADIUS_PX} px should survive detect_blobs at all offsets")
        self.assertFalse(self._survives(MIN_RESOLVING_RADIUS_PX - 0.1),
                         f"r={MIN_RESOLVING_RADIUS_PX - 0.1} px should NOT survive -- if it does, "
                         f"the floor moved and the booking gate's acquisition range is understated")

    def test_config_mirrors_the_measured_constant(self):
        cfg = json.loads(DEPTH_CONFIG.read_text())["detection"]
        self.assertEqual(cfg["min_resolving_radius_px"], MIN_RESOLVING_RADIUS_PX)

    def test_acquisition_and_band_arithmetic(self):
        fx = (640 / 2) / math.tan(1.1033 / 2)
        self.assertAlmostEqual(acquisition_range_m(fx, 0.18), fx * 0.18 / 2.0, places=9)
        self.assertAlmostEqual(band_covered_from_m(fx, 240.0, 6.0), 6.0 * fx / 240.0, places=9)
        # A window must exist where a bird is BOTH in frame and resolvable, or the mount is useless.
        self.assertLess(band_covered_from_m(fx, 240.0, 6.0), acquisition_range_m(fx, 0.18))
        for bad in ((0.0, 0.18), (fx, 0.0), (-1.0, 0.18)):
            with self.assertRaises(ValueError):
                acquisition_range_m(*bad)


def _one_box_segmenter(depth_m, box=(300.0, 220.0, 340.0, 260.0)):
    return lambda _frame: [(box, depth_m)]


class TestSeamContract(unittest.TestCase):
    def _src(self, segmenter=None, **kw):
        src = DepthDetectionSource(segmenter or _one_box_segmenter(20.0), **kw)
        src.set_intrinsics(INTR)
        return src

    def test_constructor_refuses_a_missing_segmenter(self):
        with self.assertRaises(ValueError):
            DepthDetectionSource(None)

    def test_constructor_refuses_an_inverted_range_window(self):
        with self.assertRaises(ValueError):
            DepthDetectionSource(_one_box_segmenter(20.0), min_range_m=60.0, max_range_m=1.0)

    def test_detection_carries_stamp_unshifted_and_no_track_id(self):
        src = self._src()
        dets = src.on_frame(1234.5678, object(), (0.0, 0.0, 15.0), IDENTITY_Q)
        self.assertEqual(len(dets), 1)
        self.assertEqual(dets[0].stamp_s, 1234.5678)
        self.assertIsNone(dets[0].track_id)
        self.assertEqual(dets[0].source, SOURCE_TAG)

    def test_range_is_the_measured_depth_not_an_apparent_size_prior(self):
        """The same box at two different depths must produce two different world positions. Under
        the retired apparent-size ray the box alone fixed the range, so this would be one point."""
        near = self._src(_one_box_segmenter(10.0)).on_frame(1.0, object(), (0, 0, 15), IDENTITY_Q)
        far = self._src(_one_box_segmenter(40.0)).on_frame(1.0, object(), (0, 0, 15), IDENTITY_Q)
        self.assertAlmostEqual(far[0].position_enu[0] - near[0].position_enu[0], 30.0, places=6)

    def test_no_intrinsics_counts_and_keeps_the_previous_set(self):
        src = DepthDetectionSource(_one_box_segmenter(20.0))       # never armed
        self.assertEqual(src.on_frame(1.0, object(), (0, 0, 15), IDENTITY_Q), [])
        c = src.counters()
        self.assertEqual((c["depth_msgs_received"], c["dropped_no_intrinsics"],
                          c["frames_detected_on"]), (1, 1, 0))

    def test_missing_and_stale_pose_pairs_are_counted_not_used(self):
        src = self._src()
        src.on_frame(1.0, object(), None, IDENTITY_Q)
        src.on_frame(2.0, object(), (0, 0, 15), None)
        src.on_frame(3.0, object(), (0, 0, 15), IDENTITY_Q, pose_pair_residual_s=9.0)
        c = src.counters()
        self.assertEqual(c["dropped_no_pose_pair"], 2)
        self.assertEqual(c["dropped_stale_pose_pair"], 1)
        self.assertEqual(c["frames_detected_on"], 0)
        self.assertEqual(c["depth_msgs_received"], 3)   # counted BEFORE every guard

    def test_non_finite_depth_is_refused_never_clamped(self):
        """gz writes +inf beyond far clip and -inf inside near clip. Clamping either would report a
        confident obstacle at exactly the clip plane."""
        for bad in (float("inf"), float("-inf"), float("nan")):
            src = self._src(_one_box_segmenter(bad))
            self.assertEqual(src.on_frame(1.0, object(), (0, 0, 15), IDENTITY_Q), [])
            self.assertEqual(src.counters()["dropped_non_finite_depth"], 1)

    def test_depth_outside_the_clip_window_is_refused(self):
        src = self._src(_one_box_segmenter(75.0), min_range_m=0.1, max_range_m=60.0)
        self.assertEqual(src.on_frame(1.0, object(), (0, 0, 15), IDENTITY_Q), [])
        self.assertEqual(src.counters()["dropped_out_of_range"], 1)

    def test_depth_exactly_AT_a_clip_plane_is_refused(self):
        """The clip planes are where gz stops measuring, not the last place it measures. A value of
        exactly 60.0 m is what a clamp would look like -- and this class's whole docstring promise is
        that it refuses rather than clamps. Inclusive bounds accepted precisely that value."""
        for bad in (60.0, 0.1):
            src = self._src(_one_box_segmenter(bad), min_range_m=0.1, max_range_m=60.0)
            self.assertEqual(src.on_frame(1.0, object(), (0, 0, 15), IDENTITY_Q), [],
                             msg=f"depth exactly {bad} m must be refused, not accepted")
            self.assertEqual(src.counters()["dropped_out_of_range"], 1, msg=str(bad))
        # ...and a hair inside each plane is still a measurement.
        for good in (59.999, 0.101):
            src = self._src(_one_box_segmenter(good), min_range_m=0.1, max_range_m=60.0)
            self.assertEqual(len(src.on_frame(1.0, object(), (0, 0, 15), IDENTITY_Q)), 1,
                             msg=str(good))


    def test_an_empty_frame_clears_the_previous_detections(self):
        """'The bird left the frame' and 'no frame arrived' must not look alike to the policy."""
        src = self._src()
        self.assertEqual(len(src.on_frame(1.0, object(), (0, 0, 15), IDENTITY_Q)), 1)
        src.segmenter = lambda _f: []
        self.assertEqual(src.on_frame(2.0, object(), (0, 0, 15), IDENTITY_Q), [])
        self.assertEqual(src(2.0), [])

    def test_no_second_expiry(self):
        """Staleness is PolicyParams.max_detection_age_s's job and only its job. A second timeout
        here would be a second source of truth that drifts the first time either number moves."""
        src = self._src()
        src.on_frame(100.0, object(), (0, 0, 15), IDENTITY_Q)
        self.assertEqual(len(src(1e9)), 1)

    def test_call_hands_back_a_copy(self):
        src = self._src()
        src.on_frame(1.0, object(), (0, 0, 15), IDENTITY_Q)
        got = src(1.0)
        got.clear()
        self.assertEqual(len(src(1.0)), 1)

    def test_counters_are_json_serialisable_plain_types(self):
        src = self._src()
        src.on_frame(1.0, object(), (0, 0, 15), IDENTITY_Q)
        c = src.counters()
        json.dumps(c)                                     # would raise on a numpy scalar
        for k, v in c.items():
            if k.startswith("detect_wall_ms") or k == "note":
                continue
            self.assertIsInstance(v, int, msg=k)


class TestStaticMapAnnotation(unittest.TestCase):
    """M7: the forward frame is full of MAPPED clutter -- tree canopies enter from ~24.4 m and the
    ground from ~32.5 m, both inside the 33.6 m horizon the booking gate needs at 5 m/s -- and depth
    cannot tell a tree from a bird. The contract's answer is to ANNOTATE, never to suppress: a bird
    hovering beside a known tree is exactly the detection a suppression rule would delete."""

    def _src(self, annotator, depth=20.0):
        src = DepthDetectionSource(_one_box_segmenter(depth), static_map_annotator=annotator)
        src.set_intrinsics(INTR)
        return src

    def test_a_flagged_detection_is_still_returned(self):
        src = self._src(lambda p: "tree_row0_3")
        dets = src.on_frame(1.0, object(), (0.0, 0.0, 15.0), IDENTITY_Q)
        self.assertEqual(len(dets), 1, "annotation must never suppress -- the policy decides")
        self.assertEqual(dets[0].static_map_hint, "tree_row0_3")
        self.assertEqual(src.counters()["detections_near_known_obstacle"], 1)

    def test_no_annotator_means_no_hint_and_no_counter(self):
        src = DepthDetectionSource(_one_box_segmenter(20.0))
        src.set_intrinsics(INTR)
        dets = src.on_frame(1.0, object(), (0.0, 0.0, 15.0), IDENTITY_Q)
        self.assertIsNone(dets[0].static_map_hint)
        self.assertEqual(src.counters()["detections_near_known_obstacle"], 0)

    def test_a_clear_detection_is_not_flagged(self):
        src = self._src(lambda p: None)
        dets = src.on_frame(1.0, object(), (0.0, 0.0, 15.0), IDENTITY_Q)
        self.assertIsNone(dets[0].static_map_hint)
        self.assertEqual(src.counters()["detections_near_known_obstacle"], 0)

    def test_geofence_annotator_uses_the_committed_map(self):
        """Not a hypothetical hook: it wraps `GeofenceMap.unsafe_obstacle_3d`, the same vetted 3D
        test the executor's setpoint backstop uses."""
        gmap = GeofenceMap.from_file()
        tree = gmap.obstacles[0]
        annotate = geofence_annotator(gmap)
        self.assertEqual(annotate((tree.x_m, tree.y_m, tree.z_m + 1.0)), tree.id)
        self.assertIsNone(annotate((tree.x_m, tree.y_m, 15.0)))     # cruise altitude clears it

    def test_an_annotator_that_raises_does_not_lose_the_detection(self):
        """A broken map must degrade to 'unannotated', never to 'undetected'."""
        def boom(_p):
            raise RuntimeError("map unavailable")
        src = self._src(boom)
        dets = src.on_frame(1.0, object(), (0.0, 0.0, 15.0), IDENTITY_Q)
        self.assertEqual(len(dets), 1)
        self.assertIsNone(dets[0].static_map_hint)
        self.assertEqual(src.counters()["static_map_annotator_errors"], 1)


class TestStaticMountGate(unittest.TestCase):
    """The host gate is part of the suite, not a thing to remember to run."""

    def test_check_depth_mount_passes_on_the_committed_artifacts(self):
        ok, lines = check_depth_mount.check()
        self.assertTrue(ok, msg="\n".join(lines))
        self.assertGreaterEqual(len(lines), 15, msg="the gate lost checks")

    def test_the_script_runs_from_any_cwd_and_exits_zero(self):
        proc = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "check_depth_mount.py")],
                              capture_output=True, text=True, cwd=str(Path(REPO_ROOT).parent))
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("VERDICT: PASS", proc.stdout)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
