"""ADR-009 rule 2 end to end: an NDVI blob becomes a world-ENU threat by APPARENT SIZE, never by
ground-plane projection.

The rule reads like a preference until you price it. `pixel_to_ground_enu` answers "where does this
ray meet the ground"; for the world's threat bird -- bird_0, patrolling 4 m below the 15 m cruise
altitude down the row-0 lane (ADR-015) -- that answer is z=0, i.e. 15 m below ownship, which is
OUTSIDE the policy's +/-6 m `vertical_threat_m` band. Ground-plane projection does not merely
mis-place a real bird: it SUPPRESSES it, and the avoidance loop proceeds. That is the one failure
mode this project exists to prevent, so it is pinned here as an executable assertion driven through
the real policy (`test_ground_plane_projection_suppresses_the_real_threat_bird`), not as a comment.

The other half of the file is the seam's arithmetic, checked against hand-derived fixtures rather
than round-trip self-consistency alone (the standing rule for `ndvi_georef`: a sign error round-trips
perfectly and still points the camera at the wrong half of the world).

numpy + scipy tier (the detector core's dependency), unlike `test_avoidance_node_seam.py` which is
stdlib-only.
"""
import json
import math
import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning import ndvi_georef as georef  # noqa: E402
from fieldguard_planning.avoidance_executor import AvoidanceExecutor, SimulatedVehicleSink  # noqa: E402
from fieldguard_planning.avoidance_node import (  # noqa: E402
    NDVI_IMAGE_ENCODING,
    NDVI_IMAGE_TOPIC,
    AvoidanceLoop,
    build_detection_source,
    decode_ndvi_frame,
    detector_config_from_args,
    parse_args,
)
from fieldguard_planning.avoidance_policy import AvoidancePolicy, PolicyParams  # noqa: E402
from fieldguard_planning.avoidance_types import Decision, Detection, DroneState  # noqa: E402
from fieldguard_planning.clip_recorder import STALE_PAIR_BOUND_S  # noqa: E402
from fieldguard_planning.coverage import build_grid, load_field_polygon  # noqa: E402
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402
from fieldguard_planning.ndvi_detect import (  # noqa: E402
    BIRD_RADIUS_PRIOR_M,
    REAL_RENDER_THRESH,
    NdviDetectionSource,
    box_to_detection,
)

DETECT_SRC = (REPO_ROOT / "src" / "fieldguard_planning" / "ndvi_detect.py").read_text()
BIRDS = json.loads((REPO_ROOT / "config" / "birds" / "farm_world_birds.json").read_text())["birds"]
BIRD_0 = next(b for b in BIRDS if b["bird_id"] == "bird_0")
TRUE_BIRD_RADIUS_M = float(BIRD_0["physical_radius_m"])       # 0.18 in the world we fly

INTR = georef.CameraIntrinsics.from_config(640, 480, 1.1033)  # the live camera's own numbers
LEVEL = (0.0, 0.0, 0.0, 1.0)                                  # xyzw identity: nose east, wings level
CRUISE_Z = 15.0
GZ_T0 = 1200.0                                                # absolute Gazebo sim seconds
# The ADR-009 staleness bound has ONE home: the policy default. The node used to declare its own
# copy; reading it back from PolicyParams is what makes this file follow the knob rather than pin a
# second literal beside it.
MAX_DETECTION_AGE_S = PolicyParams().max_detection_age_s


def _yaw_quat(deg):
    """xyzw quaternion for a yaw-only rotation (body FLU -> world ENU)."""
    h = math.radians(deg) / 2.0
    return (0.0, 0.0, math.sin(h), math.cos(h))


def _gt_style_box(u, v, r_px):
    """A box shaped exactly the way eval/label_from_sim.py builds ground truth: [u-r, v-r, u+r, v+r]."""
    return [u - r_px, v - r_px, u + r_px, v + r_px]


def _ndvi_frame_with_blob(u, v, r_px, soil=-0.40, bird=-0.80):
    """A synthetic fused frame: uniform 'soil' above the threshold with one disc below it. Values
    bracket the adopted real-render threshold (-0.61) on the correct sides."""
    h, w = INTR.height_px, INTR.width_px
    frame = np.full((h, w), soil, dtype=np.float32)
    yy, xx = np.mgrid[0:h, 0:w]
    frame[((xx - u) ** 2 + (yy - v) ** 2) <= r_px * r_px] = bird
    return frame


class TestRangeFromApparentSize(unittest.TestCase):
    """`depth = fx * R / r_px` -- the exact inverse of the relation `project_world_point` documents."""

    def test_it_inverts_the_projection_relation_exactly(self):
        for depth in (1.0, 3.92, 8.0, 25.0):
            r_px = INTR.fx * TRUE_BIRD_RADIUS_M / depth
            back = georef.range_from_apparent_size(r_px, INTR.fx, TRUE_BIRD_RADIUS_M)
            self.assertAlmostEqual(back, depth, places=9)

    def test_hand_computed_fixture(self):
        # fx 520.006 px, bird radius 0.18 m, depth 3.92 m -> 23.878 px apparent radius.
        r_px = georef.range_from_apparent_size(23.878, INTR.fx, TRUE_BIRD_RADIUS_M)
        self.assertAlmostEqual(r_px, 3.9200, places=3)

    def test_a_zero_or_negative_apparent_radius_refuses_rather_than_inventing_infinity(self):
        for bad in (0.0, -1.0, -1e-12):
            self.assertIsNone(georef.range_from_apparent_size(bad, INTR.fx, 0.18))
        self.assertIsNone(georef.range_from_apparent_size(10.0, 0.0, 0.18))
        self.assertIsNone(georef.range_from_apparent_size(10.0, INTR.fx, 0.0))

    def test_range_is_inverse_linear_in_apparent_size(self):
        near = georef.range_from_apparent_size(48.0, INTR.fx, 0.18)
        far = georef.range_from_apparent_size(24.0, INTR.fx, 0.18)
        self.assertAlmostEqual(far, 2.0 * near, places=9)

    def test_the_radius_prior_biases_the_estimate_NEARER_which_is_the_safe_direction(self):
        """0.15 m assumed against 0.18 m true: the estimate must under-read the range (dodge early),
        never over-read it (dodge late). The ratio is exact because depth is linear in radius."""
        self.assertLess(BIRD_RADIUS_PRIOR_M, TRUE_BIRD_RADIUS_M)
        true_depth = 3.92
        r_px = INTR.fx * TRUE_BIRD_RADIUS_M / true_depth
        est = georef.range_from_apparent_size(r_px, INTR.fx, BIRD_RADIUS_PRIOR_M)
        self.assertLess(est, true_depth)
        self.assertAlmostEqual(est, true_depth * BIRD_RADIUS_PRIOR_M / TRUE_BIRD_RADIUS_M, places=9)
        # The measured consequence recorded in ADR-003 am. 7: 3.27 m estimated vs 3.92 m true.
        self.assertAlmostEqual(est, 3.267, places=3)


class TestPixelAtDepthToEnu(unittest.TestCase):
    def test_it_round_trips_project_world_point_over_poses_and_points(self):
        for quat in (LEVEL, _yaw_quat(45), _yaw_quat(90), _yaw_quat(180),
                     (0.06, -0.04, 0.31, 0.948)):   # a little roll+pitch on top of yaw
            for drone in ((0.0, 0.0, 15.0), (37.5, 30.0, 15.0), (12.0, 51.0, 9.5)):
                for point in ((0.3, 0.4, 11.0), (-1.2, 2.0, 13.7), (0.0, 0.0, 3.0)):
                    world = (drone[0] + point[0], drone[1] + point[1], point[2])
                    proj = georef.project_world_point(world, drone, quat, INTR)
                    if proj is None:
                        continue
                    u, v, depth = proj
                    back = georef.pixel_at_depth_to_enu(u, v, depth, INTR, drone, quat)
                    for got, want in zip(back, world):
                        self.assertAlmostEqual(got, want, places=9)

    def test_hand_computed_nadir_fixtures(self):
        """Level drone at (0,0,15); the camera sits 0.08 m below the airframe origin, so the optical
        centre is at z=14.92 and the optical axis points straight down."""
        drone = (0.0, 0.0, 15.0)
        centre = georef.pixel_at_depth_to_enu(INTR.cx, INTR.cy, 4.0, INTR, drone, LEVEL)
        self.assertAlmostEqual(centre[0], 0.0, places=9)
        self.assertAlmostEqual(centre[1], 0.0, places=9)
        self.assertAlmostEqual(centre[2], 15.0 - 0.08 - 4.0, places=9)

        # +u (right in the image) is body +X = FORWARD = east at yaw 0 (ADR-007 mount note).
        east = georef.pixel_at_depth_to_enu(INTR.cx + 0.1 * INTR.fx, INTR.cy, 4.0, INTR, drone, LEVEL)
        self.assertAlmostEqual(east[0], 0.4, places=9)
        self.assertAlmostEqual(east[1], 0.0, places=9)

        # +v (down in the image) is body -Y = RIGHT = south at yaw 0.
        south = georef.pixel_at_depth_to_enu(INTR.cx, INTR.cy + 0.1 * INTR.fy, 4.0, INTR, drone, LEVEL)
        self.assertAlmostEqual(south[0], 0.0, places=9)
        self.assertAlmostEqual(south[1], -0.4, places=9)

    def test_yaw_rotates_the_footprint_with_the_airframe(self):
        drone = (0.0, 0.0, 15.0)
        p = georef.pixel_at_depth_to_enu(INTR.cx + 0.1 * INTR.fx, INTR.cy, 4.0, INTR, drone,
                                         _yaw_quat(90))
        self.assertAlmostEqual(p[0], 0.0, places=9)     # forward is now north
        self.assertAlmostEqual(p[1], 0.4, places=9)

    def test_depth_is_pinhole_depth_and_not_slant_range(self):
        """The distinction that makes the apparent-size relation valid: `r_px = fx*R/depth` uses
        depth along the optical axis. For an off-axis pixel the euclidean distance is strictly
        larger, and using it would under-read every range."""
        drone = (0.0, 0.0, 15.0)
        off = georef.pixel_at_depth_to_enu(INTR.cx + 200.0, INTR.cy + 150.0, 4.0, INTR, drone, LEVEL)
        cam = georef.camera_world_position(drone, LEVEL)
        self.assertAlmostEqual(cam[2] - off[2], 4.0, places=9)      # depth == the axial drop
        self.assertGreater(math.dist(off, cam), 4.0)                # slant range is longer


class TestGroundPlaneProjectionSuppressesARealThreat(unittest.TestCase):
    """The ADR-009 rule 2 rationale, as a test, driven through the REAL policy."""

    def _setup(self):
        # bird_0 flies its patrol at z=11 down the row-0 lane x=15; the mission cruises the same
        # lane at 15 m. Offset it half a metre along the lane so it is off the exact optical axis.
        bird = (15.0, 30.5, float(BIRD_0["waypoints"][0]["z_m"]))
        drone_pos = (15.0, 30.0, CRUISE_Z)
        u, v, depth = georef.project_world_point(bird, drone_pos, LEVEL, INTR)
        box = _gt_style_box(u, v, INTR.fx * TRUE_BIRD_RADIUS_M / depth)
        return bird, drone_pos, u, v, box

    def test_the_apparent_size_ray_keeps_the_bird_inside_the_threat_cylinder(self):
        bird, drone_pos, _u, _v, box = self._setup()
        det = box_to_detection(box, INTR, drone_pos, LEVEL, stamp_s=GZ_T0, frame_id=0)
        self.assertIsNotNone(det)
        p = PolicyParams()
        self.assertLessEqual(abs(det.position_enu[2] - CRUISE_Z), p.vertical_threat_m)
        self.assertLessEqual(math.hypot(det.position_enu[0] - drone_pos[0],
                                        det.position_enu[1] - drone_pos[1]), p.threat_radius_m)
        # ...and it is a genuinely good estimate, not merely inside the band.
        self.assertLess(math.dist(det.position_enu, bird), 1.0)

    def test_ground_plane_projection_suppresses_the_real_threat_bird(self):
        """THE SLIDE. Same pixel, same pose, two un-projections: the policy dodges one and proceeds
        past the other. The suppressed one is the bird that is really there."""
        bird, drone_pos, u, v, box = self._setup()
        drone = DroneState(position_enu=drone_pos, heading_rad=0.0, current_wp_index=3)
        policy = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=CRUISE_Z)
        geofence = GeofenceMap.from_file()

        ray_det = box_to_detection(box, INTR, drone_pos, LEVEL, stamp_s=GZ_T0, frame_id=0)
        self.assertIs(policy.decide(ray_det, drone, geofence).decision, Decision.DIVERT)

        gx, gy = georef.pixel_to_ground_enu(u, v, INTR, drone_pos, LEVEL)
        ground_det = Detection((gx, gy, georef.DEFAULT_GROUND_Z_M), frame_id=0, stamp_s=GZ_T0)
        self.assertEqual(ground_det.position_enu[2], 0.0)
        self.assertIs(policy.decide(ground_det, drone, geofence).decision, Decision.PROCEED)

        # WHY it is suppressed, stated numerically so the failure mode is legible in the diff:
        self.assertAlmostEqual(abs(ground_det.position_enu[2] - CRUISE_Z), CRUISE_Z, places=9)
        self.assertGreater(CRUISE_Z, PolicyParams().vertical_threat_m)
        self.assertLess(abs(ray_det.position_enu[2] - CRUISE_Z), PolicyParams().vertical_threat_m)

    def test_the_detector_module_never_reaches_for_the_ground_plane(self):
        """A text tripwire on the rule itself: `pixel_to_ground_enu` is a plausible-looking edit
        away, and it is the one un-projection this seam may never make. Call form, not bare name --
        the name appears in the module's prose precisely to warn against it."""
        self.assertNotIn("pixel_to_ground_enu(", DETECT_SRC)
        self.assertNotIn("intersect_ground_enu(", DETECT_SRC)
        self.assertNotIn("    pixel_to_ground_enu,", DETECT_SRC)   # nor imported
        self.assertIn("pixel_at_depth_to_enu(", DETECT_SRC)


class TestBoxToDetection(unittest.TestCase):
    def test_it_uses_the_same_centre_and_radius_convention_as_the_ground_truth_labeller(self):
        """eval/label_from_sim.py builds boxes as [u-r, v-r, u+r, v+r]; feeding one back must
        recover exactly (u, v) and exactly r -- otherwise the estimate and the label are measuring
        two different things and every scored range error is partly a convention error."""
        drone_pos = (30.0, 30.0, CRUISE_Z)
        for u, v, r in ((320.0, 240.0, 24.0), (100.0, 400.0, 6.5), (555.5, 33.25, 12.0)):
            det = box_to_detection(_gt_style_box(u, v, r), INTR, drone_pos, LEVEL,
                                   stamp_s=GZ_T0, frame_id=1,
                                   radius_prior_m=TRUE_BIRD_RADIUS_M)
            depth = georef.range_from_apparent_size(r, INTR.fx, TRUE_BIRD_RADIUS_M)
            want = georef.pixel_at_depth_to_enu(u, v, depth, INTR, drone_pos, LEVEL)
            for got, exp in zip(det.position_enu, want):
                self.assertAlmostEqual(got, exp, places=9)

    def test_a_degenerate_box_returns_None_rather_than_a_bird_at_infinity(self):
        for box in ([10.0, 10.0, 10.0, 10.0], [10.0, 10.0, 9.0, 9.0]):
            self.assertIsNone(box_to_detection(box, INTR, (0.0, 0.0, 15.0), LEVEL,
                                               stamp_s=GZ_T0, frame_id=0))

    def test_the_stamp_is_passed_through_absolutely_unshifted(self):
        """The clock-domain contract at its source: `stamp_s` is the /fg/ndvi/image header stamp in
        absolute Gazebo sim seconds. Any offset applied here re-creates the inversion the node's
        tripwire exists to catch."""
        det = box_to_detection(_gt_style_box(320.0, 240.0, 20.0), INTR, (0.0, 0.0, 15.0), LEVEL,
                               stamp_s=GZ_T0, frame_id=17)
        self.assertEqual(det.stamp_s, GZ_T0)
        self.assertEqual(det.frame_id, 17)

    def test_provenance_and_the_deliberate_absence_of_a_tracker(self):
        det = box_to_detection(_gt_style_box(320.0, 240.0, 20.0), INTR, (0.0, 0.0, 15.0), LEVEL,
                               stamp_s=GZ_T0, frame_id=0)
        self.assertEqual(det.source, "ndvi_blob")
        self.assertIsNone(det.track_id)      # no frame-to-frame association is built (by decision)
        self.assertEqual(det.confidence, 1.0)

    def test_a_detection_is_never_placed_on_the_ground_plane(self):
        det = box_to_detection(_gt_style_box(320.0, 240.0, 20.0), INTR, (0.0, 0.0, 15.0), LEVEL,
                               stamp_s=GZ_T0, frame_id=0)
        self.assertNotEqual(det.position_enu[2], georef.DEFAULT_GROUND_Z_M)
        self.assertGreater(det.position_enu[2], 5.0)


class TestNdviDetectionSource(unittest.TestCase):
    DRONE = (30.0, 30.0, CRUISE_Z)

    def _source(self, **kw):
        kw.setdefault("intr", INTR)
        return NdviDetectionSource(REAL_RENDER_THRESH, **kw)

    def test_a_blob_becomes_a_ranged_detection_at_the_expected_place(self):
        src = self._source()
        frame = _ndvi_frame_with_blob(320.0, 200.0, 24.0)
        dets = src.on_frame(GZ_T0, frame, self.DRONE, LEVEL, pose_pair_residual_s=0.01)
        self.assertEqual(len(dets), 1)
        # Derived independently of the detector: the disc's own centre and radius through the same
        # camera model. The detector's box may differ by a pixel of morphology, not by a metre.
        depth = georef.range_from_apparent_size(24.5, INTR.fx, BIRD_RADIUS_PRIOR_M)
        want = georef.pixel_at_depth_to_enu(320.5, 200.5, depth, INTR, self.DRONE, LEVEL)
        self.assertLess(math.dist(dets[0].position_enu, want), 0.05)
        self.assertEqual(dets[0].stamp_s, GZ_T0)

    def test_the_threshold_argument_really_is_the_detector(self):
        """`mask = ndvi < thresh` IS the detector, so `--ndvi-thresh` must reach the mask. Three
        values, three different worlds from one frame."""
        frame = _ndvi_frame_with_blob(320.0, 200.0, 24.0, soil=-0.40, bird=-0.80)
        blind = NdviDetectionSource(-0.95, intr=INTR)      # below the bird: nothing is a candidate
        seeing = self._source()                            # between soil and bird: the bird only
        self.assertEqual(len(blind.on_frame(GZ_T0, frame, self.DRONE, LEVEL)), 0)
        self.assertEqual(len(seeing.on_frame(GZ_T0, frame, self.DRONE, LEVEL)), 1)

        # Above the soil, the whole frame becomes one component -- and DEFAULT_MAX_AREA rejects it.
        # That is what the saturation guard is for, and the two effects are separated here so a
        # future reader cannot mistake "the area filter ate it" for "the threshold saw nothing".
        greedy = NdviDetectionSource(-0.30, intr=INTR)
        self.assertEqual(len(greedy.on_frame(GZ_T0, frame, self.DRONE, LEVEL)), 0)
        unguarded = NdviDetectionSource(-0.30, intr=INTR, max_area=10 ** 9)
        self.assertEqual(len(unguarded.on_frame(GZ_T0, frame, self.DRONE, LEVEL)), 1)

    def test_frames_before_camera_info_are_counted_not_silently_dropped(self):
        src = self._source(intr=None)
        frame = _ndvi_frame_with_blob(320.0, 200.0, 24.0)
        self.assertEqual(src.on_frame(GZ_T0, frame, self.DRONE, LEVEL), [])
        self.assertEqual(src.counters()["dropped_no_intrinsics"], 1)
        self.assertEqual(src.counters()["ndvi_msgs_received"], 1)
        self.assertEqual(src.counters()["frames_detected_on"], 0)
        # ...and arming it later works, from the LIVE intrinsics.
        src.set_intrinsics(INTR)
        self.assertEqual(len(src.on_frame(GZ_T0, frame, self.DRONE, LEVEL)), 1)

    def test_a_frame_with_no_paired_pose_is_counted_not_guessed(self):
        src = self._source()
        frame = _ndvi_frame_with_blob(320.0, 200.0, 24.0)
        self.assertEqual(src.on_frame(GZ_T0, frame, None, None), [])
        self.assertEqual(src.counters()["dropped_no_pose_pair"], 1)

    # A byte-perfect frame at HALF the armed resolution carrying the SAME physical bird: the disc's
    # centre and radius scale with the frame. Everything about it is wire-valid; only its geometry
    # disagrees with the intrinsics it would be ranged with.
    @staticmethod
    def _frame_at(shape_hw, u, v, r_px, soil=-0.40, bird=-0.80):
        h, w = shape_hw
        frame = np.full((h, w), soil, dtype=np.float32)
        yy, xx = np.mgrid[0:h, 0:w]
        frame[((xx - u) ** 2 + (yy - v) ** 2) <= r_px * r_px] = bird
        return frame

    def _same_bird_full_and_half_res(self):
        """bird_0's lane, 5 m under a 15 m cruise, half a metre off the optical axis (the
        `TestGroundPlaneProjectionSuppressesARealThreat` geometry): projected into the armed 640x480
        frame, and the identical scene rendered at 320x240."""
        bird = (15.0, 30.5, CRUISE_Z - 5.0)
        drone_pos = (15.0, 30.0, CRUISE_Z)
        u, v, depth = georef.project_world_point(bird, drone_pos, LEVEL, INTR)
        r_px = INTR.fx * TRUE_BIRD_RADIUS_M / depth
        full = self._frame_at((INTR.height_px, INTR.width_px), u, v, r_px)
        half = self._frame_at((INTR.height_px // 2, INTR.width_px // 2), u / 2.0, v / 2.0, r_px / 2.0)
        return bird, drone_pos, full, half

    def test_a_frame_whose_shape_is_not_the_armed_camera_infos_is_dropped_and_counted(self):
        """2026-09-10 QA (portfolio floor): the depth seam makes frame-shape-vs-intrinsics a HARD
        `== 0` pre-registered bar; the band that has flown had no analogue. Mirror it: the frame is
        refused BEFORE the detector, the drop is counted under its own name, and the latest
        detection set is left alone (a refused frame is 'no frame', not 'the bird left')."""
        _bird, drone_pos, full, half = self._same_bird_full_and_half_res()
        src = self._source()
        seen = src.on_frame(GZ_T0, full, drone_pos, LEVEL)
        self.assertEqual(len(seen), 1)
        got = src.on_frame(GZ_T0 + 0.2, half, drone_pos, LEVEL)
        c = src.counters()
        self.assertEqual(c["dropped_frame_shape_mismatch"], 1)
        self.assertEqual(c["ndvi_msgs_received"], 2)
        self.assertEqual(c["frames_detected_on"], 1)        # the half-res frame never reached it
        self.assertEqual(got, seen)                          # latest set untouched, not cleared
        self.assertEqual(c["dropped_no_intrinsics"], 0)
        self.assertEqual(c["dropped_no_pose_pair"], 0)
        self.assertEqual(c["dropped_stale_pose_pair"], 0)

    def test_negative_control_the_unguarded_seam_turns_a_threat_bird_into_a_PROCEED(self):
        """What the guard prevents, driven through the REAL policy so it cannot be argued away.
        Same scene, two frames: the armed-resolution frame ranges the bird ~4 m under the vehicle
        (inside the +/-6 m threat band -> DIVERT). Un-project the half-resolution frame with the
        full-resolution intrinsics -- what `on_frame` did before 2026-09-10 -- and half the pixels
        read as roughly TWICE the range on a ray tilted ~20 deg off nadir: the same bird lands
        outside `vertical_threat_m` and the policy PROCEEDS, with every drop counter at zero. (On
        the 2026-08-25 flight's own intrinsics QA measured the same failure as 20.9 m and an ENU z
        of -4.58 m -- below the ground plane.)"""
        bird, drone_pos, full, half = self._same_bird_full_and_half_res()
        drone = DroneState(position_enu=drone_pos, heading_rad=0.0, current_wp_index=3)
        policy = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=CRUISE_Z)
        geofence = GeofenceMap.from_file()
        p = PolicyParams()

        guarded = self._source()
        real = guarded.on_frame(GZ_T0, full, drone_pos, LEVEL)
        self.assertEqual(len(real), 1)
        self.assertLess(math.dist(real[0].position_enu, bird), 1.5)        # a genuine estimate
        self.assertLess(abs(real[0].position_enu[2] - CRUISE_Z), p.vertical_threat_m)
        self.assertIs(policy.decide(real[0], drone, geofence).decision, Decision.DIVERT)

        unguarded = self._source()
        unguarded._frame_matches_intrinsics = lambda frame: True    # the pre-2026-09-10 behaviour
        wrong = unguarded.on_frame(GZ_T0, half, drone_pos, LEVEL)
        self.assertEqual(len(wrong), 1)                      # it "detects" -- confidently, wrongly
        self.assertEqual(unguarded.counters()["dropped_frame_shape_mismatch"], 0)
        self.assertGreater(abs(wrong[0].position_enu[2] - CRUISE_Z), p.vertical_threat_m)
        self.assertIs(policy.decide(wrong[0], drone, geofence).decision, Decision.PROCEED)
        # ...at roughly twice the slant range: half the pixels, same radius prior, same fx.
        ratio = math.dist(drone_pos, wrong[0].position_enu) / math.dist(drone_pos, real[0].position_enu)
        self.assertAlmostEqual(ratio, 2.0, delta=0.2)

    def test_a_frame_object_without_a_2d_shape_is_left_to_the_detectors_own_contract(self):
        """Same scoping as the depth seam: this guard judges 2-D shapes only."""
        src = self._source()
        self.assertTrue(src._frame_matches_intrinsics(object()))
        self.assertTrue(src._frame_matches_intrinsics(np.zeros((4, 4, 3), dtype=np.float32)))
        self.assertFalse(src._frame_matches_intrinsics(np.zeros((240, 320), dtype=np.float32)))
        self.assertTrue(src._frame_matches_intrinsics(np.zeros((480, 640), dtype=np.float32)))

    def test_a_pose_pair_too_stale_to_georeference_is_dropped(self):
        """The recorder's measured bound, reused rather than re-invented: beyond it the frame's
        pose is metres away from where the frame was taken, so the bird's world position would be
        confidently wrong -- worse for the policy than absent."""
        src = self._source()
        frame = _ndvi_frame_with_blob(320.0, 200.0, 24.0)
        self.assertEqual(src.on_frame(GZ_T0, frame, self.DRONE, LEVEL,
                                      pose_pair_residual_s=STALE_PAIR_BOUND_S + 0.01), [])
        self.assertEqual(src.counters()["dropped_stale_pose_pair"], 1)
        self.assertEqual(len(src.on_frame(GZ_T0, frame, self.DRONE, LEVEL,
                                          pose_pair_residual_s=-STALE_PAIR_BOUND_S)), 1)

    def test_the_call_seam_returns_the_latest_frame_and_never_expires_it_itself(self):
        """Ageing detections out is `max_detection_age_s`'s job and only its job -- a second
        timeout here would be a second source of truth for 'too old'."""
        src = self._source()
        src.on_frame(GZ_T0, _ndvi_frame_with_blob(320.0, 200.0, 24.0), self.DRONE, LEVEL)
        first = src(GZ_T0, None)
        self.assertEqual(len(first), 1)
        for later in (GZ_T0 + 5.0, GZ_T0 + 500.0):
            self.assertEqual(len(src(later, None)), 1)
            self.assertEqual(src(later, None)[0].stamp_s, GZ_T0)   # still honestly stamped old
        first.clear()                                              # a caller cannot mutate state
        self.assertEqual(len(src(GZ_T0, None)), 1)

    def test_an_empty_frame_clears_the_previous_detections(self):
        """'the bird left the frame' and 'no frame arrived' must not look alike to the policy."""
        src = self._source()
        src.on_frame(GZ_T0, _ndvi_frame_with_blob(320.0, 200.0, 24.0), self.DRONE, LEVEL)
        self.assertEqual(len(src(GZ_T0, None)), 1)
        src.on_frame(GZ_T0 + 0.2, np.full((480, 640), -0.40, dtype=np.float32), self.DRONE, LEVEL)
        self.assertEqual(src(GZ_T0 + 0.2, None), [])

    def test_counters_are_json_safe_and_have_denominators(self):
        src = self._source()
        src.on_frame(GZ_T0, _ndvi_frame_with_blob(320.0, 200.0, 24.0), self.DRONE, LEVEL)
        src.on_frame(GZ_T0 + 0.2, np.full((480, 640), -0.40, dtype=np.float32), self.DRONE, LEVEL)
        c = src.counters()
        self.assertEqual(json.loads(json.dumps(c)), c)     # no numpy scalars: they raise here
        self.assertEqual(c["ndvi_msgs_received"], 2)
        self.assertEqual(c["frames_detected_on"], 2)
        self.assertEqual(c["frames_with_detection"], 1)
        self.assertEqual(c["boxes_total"], 1)
        self.assertEqual(c["detect_wall_ms_n"], 2)
        self.assertIsNotNone(c["detect_wall_ms_p95"])

    def test_wall_ms_is_null_not_zero_before_the_first_frame(self):
        c = self._source().counters()
        self.assertIsNone(c["detect_wall_ms_p95"])
        self.assertIsNone(c["detect_wall_ms_max"])
        self.assertEqual(c["detect_wall_ms_n"], 0)


class TestTheWholeSeam(unittest.TestCase):
    """Real detector -> real policy -> real executor, one tick, no doubles."""

    def _loop(self, src):
        polygon = load_field_polygon()
        geofence = GeofenceMap.from_file()
        policy = AvoidancePolicy(field_polygon=polygon, cruise_alt_m=CRUISE_Z)
        executor = AvoidanceExecutor(geofence, build_grid(polygon), SimulatedVehicleSink(),
                                     swath_half_width_m=7.5, alt_bounds=(2.0, 30.0))
        return AvoidanceLoop(policy, geofence, executor, src)

    def _drone(self):
        return DroneState(position_enu=(30.0, 30.0, CRUISE_Z), heading_rad=0.0, current_wp_index=3)

    def test_a_fresh_frame_makes_the_vehicle_dodge(self):
        src = NdviDetectionSource(REAL_RENDER_THRESH, intr=INTR)
        src.on_frame(GZ_T0, _ndvi_frame_with_blob(320.0, 200.0, 24.0),
                     (30.0, 30.0, CRUISE_Z), LEVEL, pose_pair_residual_s=0.01)
        loop = self._loop(src)
        m = loop.tick(self._drone(), now_s=GZ_T0 + 0.15, source_t=GZ_T0 + 0.15)
        self.assertIs(m.decision, Decision.DIVERT)
        self.assertEqual(loop.clock_domain_violations, 0)
        self.assertEqual(m.triggering_detection.source, "ndvi_blob")

    def test_the_same_frame_gone_stale_does_not(self):
        """The detector keeps returning its last frame forever (by design); the staleness gate is
        what stops a frozen render from flying the vehicle around a bird that is long gone."""
        src = NdviDetectionSource(REAL_RENDER_THRESH, intr=INTR)
        src.on_frame(GZ_T0, _ndvi_frame_with_blob(320.0, 200.0, 24.0),
                     (30.0, 30.0, CRUISE_Z), LEVEL, pose_pair_residual_s=0.01)
        loop = self._loop(src)
        m = loop.tick(self._drone(), now_s=GZ_T0 + MAX_DETECTION_AGE_S + 0.2,
                      source_t=GZ_T0 + MAX_DETECTION_AGE_S + 0.2)
        self.assertIs(m.decision, Decision.PROCEED)
        self.assertEqual(m.debug["n_stale_dropped"], 1)
        self.assertEqual(loop.clock_domain_violations, 0)

    def test_the_node_builds_this_exact_source_from_the_command_line(self):
        cfg = detector_config_from_args(parse_args(["--detect"]))
        src = build_detection_source(cfg)
        self.assertIsInstance(src, NdviDetectionSource)
        self.assertEqual(src.thresh, REAL_RENDER_THRESH)
        self.assertEqual(src.radius_prior_m, BIRD_RADIUS_PRIOR_M)
        self.assertTrue(cfg.thresh_provisional)

        explicit = detector_config_from_args(parse_args(["--detect", "--ndvi-thresh", "-0.61"]))
        self.assertEqual(explicit.thresh, REAL_RENDER_THRESH)
        self.assertFalse(explicit.thresh_provisional)   # same number, different provenance


class _NdviMsg:
    """A duck-typed `sensor_msgs/Image` on `/fg/ndvi/image`. The decoder is a module-scope pure
    function precisely so this is enough to drive it -- no rclpy, no renderer, no Docker. Defaults
    are what `ndvi_node.ndvi_image_fields` actually publishes (32FC1, little-endian, step = 4w)."""

    class _Stamp:
        def __init__(self, t):
            self.sec = int(t)
            self.nanosec = int(round((t - int(t)) * 1e9))

    class _Header:
        def __init__(self, t):
            self.stamp = _NdviMsg._Stamp(t)
            self.frame_id = "fg_ndvi_mount"        # frame_ids lie on this stack; content is truth

    def __init__(self, frame, stamp_s=GZ_T0, encoding=NDVI_IMAGE_ENCODING, is_bigendian=0,
                 step=None, data=None, height=None, width=None):
        self.header = _NdviMsg._Header(stamp_s)
        self.height = int(frame.shape[0]) if height is None else height
        self.width = int(frame.shape[1]) if width is None else width
        self.encoding = encoding
        self.is_bigendian = is_bigendian
        self.step = (self.width * 4) if step is None else step
        if data is None:
            data = (frame.astype(">f4") if is_bigendian else frame.astype("<f4")).tobytes()
        self.data = data


class TestNdviFrameDecode(unittest.TestCase):
    """G10: the NDVI decoder makes the same four refusals `decode_depth_frame` makes.

    It is the band that has FLOWN -- 1302 frames on the 2026-08-25 take -- and until 2026-09-10 it
    was `np.frombuffer(...).reshape(h, w)` with nothing checked, while the never-flown depth decoder
    checked encoding, stride, length and byte order. The asymmetry was the whole finding."""

    def _frame(self):
        return _ndvi_frame_with_blob(320.0, 200.0, 24.0)

    def test_a_valid_frame_decodes_exactly_as_it_always_did(self):
        """The refusals are the change; the accepted frame is NOT. Byte-identical to the old
        expression, and identical to the array the publisher fused -- a decoder refactor that also
        moved a pixel would be a silent change to the adopted detector."""
        frame = self._frame()
        msg = _NdviMsg(frame)
        old_expression = np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width)
        got = decode_ndvi_frame(msg)
        np.testing.assert_array_equal(got, old_expression)
        np.testing.assert_array_equal(got, frame)
        self.assertEqual(got.dtype, np.dtype("float32"))
        self.assertEqual(got.shape, frame.shape)

    def test_the_decoded_frame_still_detects_the_bird(self):
        """End of the seam, not just the array: the decoded frame drives the real detector to the
        same single detection the in-memory frame does."""
        src = NdviDetectionSource(REAL_RENDER_THRESH, intr=INTR)
        dets = src.on_frame(GZ_T0, decode_ndvi_frame(_NdviMsg(self._frame())),
                            (30.0, 30.0, CRUISE_Z), LEVEL)
        self.assertEqual(len(dets), 1)

    def test_a_big_endian_frame_is_byte_swapped_not_believed(self):
        """THE SILENT ONE. A byte-swapped float32 buffer reshapes perfectly into plausible-looking
        numbers: the old decoder would have read denormal noise as NDVI, found nothing under the
        -0.61 threshold, and logged a healthy detector that saw no birds."""
        frame = self._frame()
        np.testing.assert_array_equal(decode_ndvi_frame(_NdviMsg(frame, is_bigendian=1)), frame)
        # ...and the flag is load-bearing: read a big-endian payload as little-endian and the frame
        # is garbage. This is exactly what the node used to do on every frame.
        mislabelled = _NdviMsg(frame, is_bigendian=1)
        mislabelled.is_bigendian = 0
        self.assertFalse(np.array_equal(decode_ndvi_frame(mislabelled), frame))

    def test_the_preview_encoding_is_refused_by_name(self):
        """`/fg/ndvi/preview` is rgb8 off the same fused array, one word away in a launch line."""
        for encoding in ("rgb8", "mono16", "32FC2", "", None):
            with self.subTest(encoding=encoding):
                with self.assertRaises(ValueError) as cm:
                    decode_ndvi_frame(_NdviMsg(self._frame(), encoding=encoding))
                self.assertIn(NDVI_IMAGE_TOPIC, str(cm.exception))
                self.assertIn(repr(NDVI_IMAGE_ENCODING), str(cm.exception))

    def test_a_padded_or_mis_strided_row_is_refused(self):
        frame = self._frame()
        for step in (frame.shape[1] * 4 + 4, frame.shape[1] * 4 - 4, frame.shape[1], 0):
            with self.subTest(step=step):
                with self.assertRaisesRegex(ValueError, "step"):
                    decode_ndvi_frame(_NdviMsg(frame, step=step))

    def test_a_stride_that_would_have_reshaped_silently_is_refused(self):
        """The case that matters: a padded row whose payload STILL divides evenly. 4 bytes of
        padding on a 640-wide row makes 641 floats per row; `frombuffer().reshape(480, 640)` on the
        first 480*640 of them succeeds and puts every pixel one column further left on each
        successive row -- a detection that then georeferences to the wrong cell."""
        frame = self._frame()
        h, w = frame.shape
        padded = np.zeros((h, w + 1), dtype="<f4")
        padded[:, :w] = frame
        msg = _NdviMsg(frame, step=(w + 1) * 4, data=padded.tobytes())
        with self.assertRaisesRegex(ValueError, "step"):
            decode_ndvi_frame(msg)

    def test_a_truncated_payload_is_refused_with_both_numbers(self):
        frame = self._frame()
        msg = _NdviMsg(frame)
        truncated = _NdviMsg(frame, data=msg.data[:-8])
        with self.assertRaisesRegex(ValueError, "payload is"):
            decode_ndvi_frame(truncated)

    def test_a_degenerate_frame_is_refused(self):
        frame = self._frame()
        for height, width in ((0, 640), (480, 0)):
            with self.subTest(height=height, width=width):
                with self.assertRaisesRegex(ValueError, "degenerate"):
                    decode_ndvi_frame(_NdviMsg(frame, height=height, width=width, data=b""))

    def test_the_publishers_own_frame_round_trips_through_this_decoder(self):
        """The two ends of the wire, in one test. `ndvi_node.assemble_ndvi_msg_fields` builds the
        message this node consumes; every field the decoder asserts is taken from that builder
        rather than from a literal here, so a change at either end fails rather than drifting."""
        from fieldguard_planning import ndvi_node
        frame = self._frame()
        fields = ndvi_node.assemble_ndvi_msg_fields(frame, rgb_header=None, nir_header=None)
        self.assertEqual(NDVI_IMAGE_ENCODING, ndvi_node.NDVI_ENCODING)
        self.assertEqual(fields.encoding, NDVI_IMAGE_ENCODING)
        msg = _NdviMsg(frame, encoding=fields.encoding, is_bigendian=fields.is_bigendian,
                       step=fields.step, data=fields.data,
                       height=fields.height, width=fields.width)
        np.testing.assert_array_equal(decode_ndvi_frame(msg), frame)



if __name__ == "__main__":
    unittest.main()
