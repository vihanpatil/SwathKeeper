"""Tests for scripts/predict_bird_visibility.py -- the offline pre-flight bird-visibility predictor.

THE POINT OF THIS FILE is the two reproduction tests, not the unit coverage around them. A
predictor that cannot reproduce a measurement is a random number generator with a table formatter:

  1. `TestBacktestDemoTake` -- replay the FLOWN demo take (`real_flight_20260821T045848Z`, the clip
     ADR-003 amendment 1 was written from) through this tool's geometry. It must return that
     flight's own measured numbers: 0 bird-visible frames of 454, closest approach 14.15 m slant,
     nearest miss ~341 px outside the frame edge. Those three numbers are quoted in ADR-003
     amendment 1 and were produced by a DIFFERENT implementation (`eval/label_from_sim.py` when it
     still carried its own from-scratch projection), so agreeing with them is a real cross-check,
     not a tautology.

  2. `TestSyntheticReproduction` -- predict that same mission x bird config from PURE CONFIG, with
     no clip involved, and land on the same answer: zero. Run at the demo take's own airborne frame
     rate (derived from the clip here, ~0.41 Hz -- see the docstring on that test for why the
     nominal 5 Hz sensor tick is the wrong number to reproduce a recording with). Its bird config is
     the FROZEN `fixtures/farm_world_birds_asflown_20260821.json`, not the live one: ADR-015 moved
     the birds, and a past measurement can only be reproduced from the geometry that produced it.
     What the LIVE config must do now is a different contract, pinned in
     `test_bird_geometry_contract.py`.

The rest pins the seams: the in-frame predicate against `eval/spike_common.clip_box` (so ground
truth and prediction can never drift apart), the mission model against the committed boustrophedon,
and the honesty guards.

Runs on the host: no rclpy, no Docker, no numpy needed by the tool itself (spike_common, imported
only for the clip_box equivalence test, does use numpy -- eval family, same as
test_label_real_clip.py).
"""
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

import predict_bird_visibility as pbv  # noqa: E402
from fieldguard_planning.ndvi_georef import (  # noqa: E402
    CameraIntrinsics, project_world_point, world_enu_to_pixel,
)

DEMO_CLIP = REPO_ROOT / "eval" / "results" / "clips" / "real_flight_20260821T045848Z"
# The bird geometry AS FLOWN on that clip, frozen (ADR-015 moved the live one). See its own
# frozen_note: reproducing a measurement needs the config that produced it.
ASFLOWN_BIRDS = REPO_ROOT / "tests" / "fieldguard_planning" / "fixtures" / \
    "farm_world_birds_asflown_20260821.json"
INTR = CameraIntrinsics(width_px=640, height_px=480, fx=520.0, fy=520.0, cx=320.0, cy=240.0)
LEVEL = (0.0, 0.0, 0.0, 1.0)  # identity attitude, nose east


def default_intrinsics():
    cfg = json.loads((REPO_ROOT / "config" / "ndvi_camera.json").read_text())["camera"]
    return CameraIntrinsics.from_config(cfg["image_width_px"], cfg["image_height_px"],
                                        cfg["horizontal_fov_rad"])


def home_latlon():
    poly = json.loads((REPO_ROOT / "config" / "field_polygon.json").read_text())
    return poly["home_lat"], poly["home_lon"]


# ======================================================================================
# 1. BACKTEST: reproduce what the demo take actually measured
# ======================================================================================
class TestBacktestDemoTake(unittest.TestCase):
    """The flown clip, replayed. Numbers per docs/DECISIONS.md ADR-003 amendment 1."""

    @classmethod
    def setUpClass(cls):
        if not (DEMO_CLIP / "poses.jsonl").exists():  # pragma: no cover - clip is committed
            raise unittest.SkipTest(f"{DEMO_CLIP} not present")
        cls.rep = pbv.backtest(DEMO_CLIP)

    def test_reproduces_the_measured_zero(self):
        """0 visible bird-boxes over 454 frames -- the number that made ADR-003 criterion 3
        'EVIDENCE INSUFFICIENT' rather than confirmed."""
        self.assertEqual(self.rep["frames"], 454)
        self.assertEqual(self.rep["total_frames_in_view"], 0)
        self.assertEqual([b["frames_in_view"] for b in self.rep["birds"]], [0, 0, 0])
        self.assertEqual([b["bird_id"] for b in self.rep["birds"]],
                         ["bird_0", "bird_1", "bird_2"])

    def test_reproduces_closest_approach_14_15_m(self):
        c = self.rep["closest_approach"]
        self.assertEqual(c["bird_id"], "bird_2")
        self.assertAlmostEqual(c["slant_range_m"], 14.15, places=2)
        self.assertEqual(c["frame_id"], 275)

    def test_reproduces_341_px_outside_the_edge(self):
        """ADR-003 am. 1's '~341 px outside the image edge (bird_2, frame 279)'."""
        n = self.rep["nearest_miss"]
        self.assertEqual(n["bird_id"], "bird_2")
        self.assertEqual(n["frame_id"], 279)
        self.assertAlmostEqual(n["px_outside_edge"], 341.2, delta=0.5)

    def test_agrees_with_the_ground_truth_labeller_frame_by_frame(self):
        """`eval/label_from_sim.py` is what actually produced the record's '454 frames, 0 visible
        bird-boxes'. Its visible flag and this tool's in_frame must agree on EVERY frame x bird --
        if they ever disagree, one of the two is lying about what the camera saw, and the ADR record
        would be wrong either way.

        SCOPE, stated so this is not read as more than it is: since the one-projection refactor both
        sides call `ndvi_georef.project_world_point`, so this pins the apparent-size radius and the
        in-frame predicate against real poses -- NOT the projection, which they share. The
        independent check on the projection is the three reproduced ADR numbers above (produced
        before that refactor) plus the hand-computed fixtures in test_ndvi_georef.py."""
        try:
            from label_from_sim import build_ground_truth  # needs numpy (eval family)
        except ImportError as exc:  # pragma: no cover - environment without numpy
            raise unittest.SkipTest(f"eval harness unavailable: {exc}")
        gt, _ = build_ground_truth(DEMO_CLIP)
        meta = json.loads((DEMO_CLIP / "meta.json").read_text())
        intr = CameraIntrinsics.from_meta(meta["camera"])
        mount = tuple(meta["camera_extrinsic"]["offset_from_drone_m"])
        lines = [json.loads(l) for l in (DEMO_CLIP / "poses.jsonl").read_text().splitlines() if l]
        gt_by_fid = {f["frame_id"]: {b["bird_id"]: b["visible"] for b in f["birds"]}
                     for f in gt["frames"]}
        checked = 0
        for line in lines:
            w, x, y, z = line["drone"]["quat_wxyz"]
            sample = pbv.Sample(0.0, tuple(line["drone"]["pos_m"]), (x, y, z, w), "")
            for b in line["birds"]:
                mine = pbv.look_at_bird(sample, tuple(b["pos_m"]), b["physical_radius_m"],
                                        intr, mount).in_frame
                self.assertEqual(mine, gt_by_fid[line["frame_id"]][b["bird_id"]],
                                 f"disagreement on frame {line['frame_id']} {b['bird_id']}")
                checked += 1
        self.assertEqual(checked, 454 * 3)

    def test_refuses_a_clip_with_no_bird_labels(self):
        """An unannotated clip must fail loudly: its zero would mean 'no labels', not 'no birds'
        -- exactly the empty-denominator trap `eval/score.py` fell into (ADR-003 am. 1, defect 1)."""
        meta = json.loads((DEMO_CLIP / "meta.json").read_text())
        line = json.loads((DEMO_CLIP / "poses.jsonl").read_text().splitlines()[0])
        line.pop("birds")
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td)
            (clip / "meta.json").write_text(json.dumps(meta))
            (clip / "poses.jsonl").write_text(json.dumps(line) + "\n")
            with self.assertRaises(ValueError) as ctx:
                pbv.backtest(clip)
            self.assertEqual(pbv.main(["--backtest", str(clip)]), 2)  # refusal != scoring zero
        self.assertIn("annotate", str(ctx.exception))


# ======================================================================================
# 2. SYNTHETIC REPRODUCTION: same answer, from config alone
# ======================================================================================
class TestSyntheticReproduction(unittest.TestCase):
    """Predict the flown mission x the AS-FLOWN bird config (the frozen fixture), no clip in the loop.

    WHICH CADENCE: the demo take did not sample the mission at the sensor's 5 Hz. It recorded 53
    airborne frames across 127.8 s of flight -- 0.41 Hz, the two-stage transport/pairing loss of
    ADR-013 amendment 6a. Reproducing a RECORDING therefore means running the model at the rate
    that recording actually achieved (derived from the clip below, never hardcoded). At 5 Hz the
    same config predicts a median 11 frames for bird_2, and the difference between those two
    answers is the throughput problem, not a modelling disagreement -- which is itself the finding:
    at the flown frame rate this mission was always going to return zero.

    The model is if anything OPTIMISTIC at that rate, which is the safe direction for a check whose
    job is to say 'do not bother': it spreads frames uniformly along the path, whereas the take's
    frames were bursty and clustered where the vehicle was slow -- only 29 of the 53 landed at
    survey altitude away from the takeoff point, with inter-frame gaps up to 18.4 s (the same
    effect ADR-013 am. 6 records for lever A). So the real chance of catching a mid-lane crossing
    was lower than what is asserted below."""

    @classmethod
    def setUpClass(cls):
        if not (DEMO_CLIP / "poses.jsonl").exists():  # pragma: no cover - clip is committed
            raise unittest.SkipTest(f"{DEMO_CLIP} not present")
        lines = [json.loads(l) for l in (DEMO_CLIP / "poses.jsonl").read_text().splitlines() if l]
        air = [l for l in lines if l["drone"]["pos_m"][2] > 1.0]
        span = air[-1]["stamp_sim_s"] - air[0]["stamp_sim_s"]
        cls.n_airborne = len(air)
        cls.flown_hz = (len(air) - 1) / span
        cls.mission = REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints"
        cls.birds = ASFLOWN_BIRDS   # the geometry the take was flown with, not today's

    def _predict(self, cadence_hz):
        return pbv.predict(self.mission, self.birds, default_intrinsics(),
                           speed_mps=pbv.DEFAULT_SPEED_MPS, cadence_hz=cadence_hz,
                           phase_step_s=pbv.DEFAULT_PHASE_STEP_S, min_frames=pbv.DEFAULT_MIN_FRAMES,
                           home=home_latlon())

    def test_flown_cadence_is_the_clips_own_0_41_hz(self):
        self.assertAlmostEqual(self.flown_hz, 0.41, delta=0.02)

    def test_predicts_zero_or_near_zero_at_the_flown_cadence(self):
        """The reproduction, stated as the model can honestly state it.

        From config alone, at the rate this take actually sampled: bird_0 and bird_1 are in frame
        for a median of ZERO frames, bird_2 for ONE, and the luckiest driver-start offset in the
        sweep never reaches three. Scaled to the number of frames the take actually recorded
        airborne, that is **less than one expected bird-visible frame in the entire flight** -- so
        the measured 0/454 is the single most likely outcome of this mission, not a surprise. The
        model is not claiming the flight was impossible; it is claiming the flight was never worth
        the Docker session, which is the decision this tool exists to inform."""
        rep = self._predict(self.flown_hz)
        for b in rep["birds"]:
            self.assertLessEqual(b["frames_in_view"]["median"], 1, b["bird_id"])
            self.assertLessEqual(b["frames_in_view"]["max"], 3, b["bird_id"])
        self.assertEqual([b["frames_in_view"]["median"] for b in rep["birds"]], [0, 0, 1])
        expected_frames = (sum(b["frames_in_view"]["median"] for b in rep["birds"])
                           * self.n_airborne / rep["model"]["frames"])
        self.assertLess(expected_frames, 1.0)
        self.assertFalse(rep["verdict"]["pass"])
        self.assertEqual(rep["verdict"]["failing_birds"], ["bird_0", "bird_1", "bird_2"])

    def test_bird_0_is_structurally_invisible_at_any_cadence(self):
        """The claim that does NOT depend on throughput: AS FLOWN, bird_0 patrolled x=20.0, a fixed
        5.0 m off lane x=15, and the cross-track half-footprint at its 7 m depth is 3.23 m. Zero
        frames at every one of the swept driver-start offsets, at the flown rate AND at the full
        sensor tick -- so no amount of recording throughput could ever have shown it. This is the
        finding ADR-015 acted on by moving the patrol line onto the lane (lowering it could not
        help: the miss is cross-track, and no altitude closes 5.0 m -- see
        test_bird_geometry_contract.py)."""
        for cadence in (self.flown_hz, pbv.DEFAULT_CADENCE_HZ):
            rep = self._predict(cadence)
            bird_0 = next(b for b in rep["birds"] if b["bird_id"] == "bird_0")
            self.assertEqual(bird_0["frames_in_view"]["max"], 0, f"at {cadence:.2f} Hz")
            self.assertEqual(bird_0["phases_with_any_view"], 0, f"at {cadence:.2f} Hz")
            self.assertEqual(bird_0["limited_by"], "structural")
            self.assertAlmostEqual(bird_0["closest_miss_m"], 1.81, delta=0.05)
            # cross-track half-footprint at bird_0's depth, the number the miss comes from
            self.assertAlmostEqual(bird_0["footprint_at_bird_alt_m"][1] / 2.0, 3.23, delta=0.02)

    def test_the_other_two_birds_are_timing_limited_not_structural(self):
        """Stated as a separate finding because ADR-003 am. 1 reads as though all three were
        geometrically impossible: bird_1 and bird_2 DO cross the lanes. At the 5 Hz sensor tick
        they are in frame for a median 3 and 11 frames of ~900 -- rare, but not never, and that
        distinction is what tells you whether to change geometry or throughput."""
        rep = self._predict(pbv.DEFAULT_CADENCE_HZ)
        for bird_id, floor in (("bird_1", 1), ("bird_2", 5)):
            b = next(x for x in rep["birds"] if x["bird_id"] == bird_id)
            self.assertEqual(b["limited_by"], "timing")
            self.assertGreaterEqual(b["frames_in_view"]["median"], floor, bird_id)
            self.assertGreater(b["phases_with_any_view"], 0, bird_id)

    def test_runs_fast_enough_to_be_used(self):
        """A pre-flight check nobody waits for is a pre-flight check nobody runs."""
        import time
        t0 = time.monotonic()
        self._predict(pbv.DEFAULT_CADENCE_HZ)
        self.assertLess(time.monotonic() - t0, 5.0)


# ======================================================================================
# Seams
# ======================================================================================
class TestInFramePredicate(unittest.TestCase):
    """`frame_geometry`'s in_frame must equal `spike_common.clip_box(...) is not None` -- the
    definition `eval/label_from_sim.py` writes ground-truth `visible` with. Two definitions of
    'in frame' would make prediction and ground truth silently incomparable."""

    def test_matches_spike_common_clip_box(self):
        try:
            import spike_common as sc  # needs numpy (eval family)
        except ImportError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"spike_common unavailable: {exc}")
        w, h = 640, 480
        cases = [(u, v, r) for u in (-40.0, -5.0, 0.0, 3.0, 320.0, 637.0, 640.0, 700.0)
                 for v in (-40.0, -5.0, 0.0, 3.0, 240.0, 479.0, 480.0, 700.0)
                 for r in (0.5, 4.0, 41.0)]
        for u, v, r in cases:
            expected = sc.clip_box([u - r, v - r, u + r, v + r], w, h) is not None
            self.assertEqual(pbv.frame_geometry(u, v, r, w, h)[0], expected, (u, v, r))

    def test_px_outside_is_zero_only_once_the_centre_is_inside(self):
        self.assertEqual(pbv.frame_geometry(320.0, 240.0, 5.0, 640, 480)[1], 0.0)
        self.assertAlmostEqual(pbv.frame_geometry(700.0, 240.0, 5.0, 640, 480)[1], 60.0)
        self.assertAlmostEqual(pbv.frame_geometry(-20.0, -30.0, 5.0, 640, 480)[1], 30.0)


class TestOneProjection(unittest.TestCase):
    """`project_world_point` is the single projection the heatmap stitch, the GT labeller and this
    predictor all share (the refactor that made this file possible)."""

    def test_pixel_agrees_with_world_enu_to_pixel(self):
        pt, drone, q = (12.0, -3.0, 6.0), (10.0, 1.0, 15.0), (0.1, -0.05, 0.3, 0.948)
        proj = project_world_point(pt, drone, q, INTR)
        self.assertEqual(proj[:2], world_enu_to_pixel(pt, drone, q, INTR))

    def test_depth_matches_the_spike_fixed_extrinsic_at_identity_attitude(self):
        try:
            import spike_common as sc
        except ImportError as exc:  # pragma: no cover
            raise unittest.SkipTest(f"spike_common unavailable: {exc}")
        intr = {"fx": 520.0, "fy": 520.0, "cx": 320.0, "cy": 240.0}
        bird, drone = (4.0, -2.0, 6.0), (2.0, 1.0, 15.0)
        u, v, depth = project_world_point(bird, drone, LEVEL, INTR, (0.0, 0.0, 0.0))
        su, sv, szc = sc.project_bird(bird, drone, intr)
        self.assertAlmostEqual(depth, szc, places=9)
        self.assertAlmostEqual(u, su, places=6)
        self.assertAlmostEqual(v, sv, places=6)

    def test_nadir_footprint_is_the_documented_18_5_x_13_8_m_at_15_m(self):
        """Sanity fixture for the whole tool: at 15 m, the 640-px axis spans 2*15*320/520 = 18.46 m
        ALONG track and the 480-px axis 13.85 m ACROSS it (ADR-007 mount extrinsic). Getting these
        two axes the wrong way round would flatter every cross-track miss by 34 %."""
        drone, q = (0.0, 0.0, 15.0), (0.0, 0.0, 0.0, 1.0)  # nose east
        edge_along = project_world_point((18.46 / 2 - 0.01, 0.0, 0.0), drone, q, INTR,
                                         (0.0, 0.0, 0.0))
        edge_cross = project_world_point((0.0, -(13.85 / 2 - 0.01), 0.0), drone, q, INTR,
                                         (0.0, 0.0, 0.0))
        self.assertTrue(pbv.frame_geometry(*edge_along[:2], 0.0, 640, 480)[0])
        self.assertTrue(pbv.frame_geometry(*edge_cross[:2], 0.0, 640, 480)[0])
        out_cross = project_world_point((0.0, -(13.85 / 2 + 0.5), 0.0), drone, q, INTR,
                                        (0.0, 0.0, 0.0))
        self.assertFalse(pbv.frame_geometry(*out_cross[:2], 0.0, 640, 480)[0])


class TestMissionModel(unittest.TestCase):
    def setUp(self):
        self.legs = pbv.build_legs(REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints",
                                   *home_latlon(), speed_mps=3.0)

    def test_climbs_first_and_lands_last(self):
        self.assertEqual(self.legs[0].label, "climb")
        self.assertEqual(self.legs[-1].label, "descend")
        self.assertAlmostEqual(self.legs[0].p1[2], 15.0, places=3)
        self.assertAlmostEqual(self.legs[-1].p1[2], 0.0, places=3)

    def test_six_lanes_at_the_committed_15_m_pitch(self):
        lanes = sorted({round(lg.p0[0]) for lg in self.legs if lg.label.startswith("lane")})
        self.assertEqual(lanes, [0, 15, 30, 45, 60, 75])

    def test_takeoff_yaw_is_inherited_from_the_first_lane(self):
        """The climb leg has no heading of its own; the vehicle has already yawed to face the first
        waypoint. The demo take's frame 0 confirms it: quat_wxyz (0.7071, 0, 0, 0.7071), yaw +90
        deg = north, the first lane's direction."""
        self.assertAlmostEqual(self.legs[0].yaw_rad, math.pi / 2, places=6)

    def test_timing_is_distance_over_speed(self):
        total = self.legs[-1].t0_s + self.legs[-1].duration_s
        dist = sum(math.dist(lg.p0, lg.p1) for lg in self.legs)
        self.assertAlmostEqual(total, dist / 3.0, places=6)
        self.assertAlmostEqual(dist, 510.0 + 30.0, delta=1.0)  # 6x60 lanes + 5x15 cross + 75 RTL

    def test_samples_land_on_the_path_at_the_requested_cadence(self):
        samples = pbv.sample_path(self.legs, cadence_hz=2.0)
        self.assertAlmostEqual(samples[1].t_s - samples[0].t_s, 0.5, places=9)
        self.assertLessEqual(max(s.pos[2] for s in samples), 15.0 + 1e-9)
        self.assertAlmostEqual(max(s.pos[0] for s in samples), 75.0, delta=0.5)
        self.assertAlmostEqual(max(s.pos[1] for s in samples), 60.0, delta=0.5)

    def test_bird_start_is_the_10_m_altitude_gate(self):
        samples = pbv.sample_path(self.legs, cadence_hz=5.0)
        t_gate = pbv.bird_start_time_s(samples)
        at_gate = next(s for s in samples if s.t_s == t_gate)
        self.assertGreater(at_gate.pos[2], 10.0)
        self.assertLessEqual(at_gate.pos[2], 10.0 + 3.0 / 5.0 + 1e-9)  # one frame of climb, no more

    def test_min_depth_gate_survives_the_descent_through_bird_altitude(self):
        """On the landing leg the camera passes through the birds' altitude band. A bird 14 m away
        at ~zero depth must NOT be reported in frame -- without the MIN_DEPTH_M gate its projection
        blows up and the predictor invents a sighting where the flight would see nothing."""
        sample = pbv.Sample(0.0, (0.0, 0.0, 6.2), (0.0, 0.0, 0.0, 1.0), "descend")
        s = pbv.look_at_bird(sample, (10.0, 10.0, 6.0), 0.18, INTR)
        self.assertFalse(s.in_frame)
        self.assertIsNone(s.px_outside)


class TestWindows(unittest.TestCase):
    def test_contiguous_runs_become_windows(self):
        def sight(t, seen, leg="lane x=15 N"):
            return pbv.Sighting(t, leg, seen, 0.0 if seen else 5.0, 9.0 + t)
        runs = [sight(0.0, False), sight(1.0, True), sight(2.0, True), sight(3.0, False),
                sight(4.0, True)]
        w = pbv.windows_from(runs)
        self.assertEqual([(x["t_start_s"], x["t_end_s"], x["n_frames"]) for x in w],
                         [(1.0, 2.0, 2), (4.0, 4.0, 1)])
        self.assertEqual(w[0]["leg"], "lane x=15 N")
        self.assertAlmostEqual(w[0]["min_slant_range_m"], 10.0)


class TestCli(unittest.TestCase):
    def test_json_report_and_failing_exit_code(self):
        """--json is the tooling contract; a FAIL must exit non-zero so a pre-flight check can gate
        a run instead of being read by eye."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "pred.json"
            rc = pbv.main(["--fps", "0.4", "--phase-step", "4.0", "--json", str(out)])
            self.assertEqual(rc, 1)
            rep = json.loads(out.read_text())
        self.assertEqual(rep["schema_version"], "1.0")
        self.assertFalse(rep["verdict"]["pass"])
        self.assertEqual(len(rep["birds"]), 3)
        self.assertIn("phase_sweep", rep["model"])

    def test_backtest_cli_prints_the_measured_numbers(self):
        if not (DEMO_CLIP / "poses.jsonl").exists():  # pragma: no cover
            raise unittest.SkipTest("demo clip not present")
        rc = pbv.main(["--backtest", str(DEMO_CLIP)])
        self.assertEqual(rc, 0)  # a backtest reports, it does not pass/fail a floor

    def test_passing_floor_reports_pass(self):
        """The verdict must be able to say PASS -- a check that can only fail teaches nothing.
        (The live config clears the real 5-frame floor too; that is the contract test's job, and
        this one stays on min_frames=0 so it keeps testing the VERDICT, not the world.)"""
        rep = pbv.predict(REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints",
                          REPO_ROOT / "config" / "birds" / "farm_world_birds.json",
                          default_intrinsics(), speed_mps=3.0, cadence_hz=5.0, phase_step_s=4.0,
                          min_frames=0, home=home_latlon())
        self.assertTrue(rep["verdict"]["pass"])


class TestCameraIntrinsicsFromMeta(unittest.TestCase):
    def test_reads_a_clips_recorded_intrinsics(self):
        meta = json.loads((DEMO_CLIP / "meta.json").read_text())
        intr = CameraIntrinsics.from_meta(meta["camera"])
        self.assertEqual((intr.width_px, intr.height_px), (640, 480))
        self.assertAlmostEqual(intr.fx, 520.0, delta=0.01)
        self.assertEqual((intr.cx, intr.cy), (320.0, 240.0))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
