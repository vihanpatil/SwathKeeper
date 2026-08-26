"""ADR-015: the committed bird geometry must clear BOTH gates, and this file is what stops one
from being traded away for the other.

`config/birds/farm_world_birds.json` is the only file in the repo that two priorities pull on in
opposite directions (CLAUDE.md's contractual order: #1 reactive avoidance, #2 NDVI mapping):

  * CAMERA gate -- a nadir camera at 15 m sees a footprint that shrinks with the bird's DEPTH below
    it, so a bird is photographable when it flies LOW. `scripts/predict_bird_visibility.py` must
    report >= 5 median frames in view for every bird over the driver-start phase sweep.
  * AVOIDANCE gate -- `avoidance_policy` only treats a bird as a threat inside a cylinder of
    `threat_radius_m` 12 m and `vertical_threat_m` +/-6 m, so a bird is dangerous when it flies
    HIGH (z >= 9 m at the 15 m cruise). At least one bird must still trip the REAL policy into
    DIVERT on the nominal mission.

Lowering every bird until the camera gate goes green would delete the avoidance story silently --
nothing else in the suite would have gone red. That is the specific regression this file exists to
make loud, so its tests assert the TRADE, not just the two numbers: `TestNoAltitudeFixesTheOldLine`
pins WHY the fix had to be a patrol-line move, and `TestNotAWeakening` recomputes the as-flown
baseline from the frozen fixture instead of hardcoding it, so the comparison cannot rot.

Detections are injected at each bird's TRUE world position: the subject here is world/mission
geometry, not the detector. ADR-009's apparent-size range estimate adds error on top of this, in
the fail-safe direction (an inflated range reads as a closer bird), so a geometry that trips the
policy here trips it there too.

Stdlib only; ~2 s; no sim, no container.
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

import predict_bird_visibility as pbv  # noqa: E402
from drive_birds import pose_at  # noqa: E402
from fieldguard_planning.avoidance_policy import AvoidancePolicy, PolicyParams  # noqa: E402
from fieldguard_planning.avoidance_types import Decision, Detection, DroneState  # noqa: E402
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402
from fieldguard_planning.ndvi_georef import (  # noqa: E402
    MOUNT_OFFSET_BODY_M, CameraIntrinsics, project_world_point,
)

MISSION = REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints"
BIRDS = REPO_ROOT / "config" / "birds" / "farm_world_birds.json"
ASFLOWN_BIRDS = REPO_ROOT / "tests" / "fieldguard_planning" / "fixtures" / \
    "farm_world_birds_asflown_20260821.json"

MIN_FRAMES = pbv.DEFAULT_MIN_FRAMES   # 5, the camera gate
THREAT_BIRD = "bird_0"                # the bird ADR-015 assigns the avoidance role to


def _intrinsics():
    cam = json.loads((REPO_ROOT / "config" / "ndvi_camera.json").read_text())["camera"]
    return CameraIntrinsics.from_config(cam["image_width_px"], cam["image_height_px"],
                                        cam["horizontal_fov_rad"])


def _home():
    poly = json.loads((REPO_ROOT / "config" / "field_polygon.json").read_text())
    return poly["home_lat"], poly["home_lon"]


def predict(birds_path, cadence_hz=pbv.DEFAULT_CADENCE_HZ, phase_step_s=1.0):
    return pbv.predict(MISSION, birds_path, _intrinsics(), pbv.REFERENCE_SPEED_MPS, cadence_hz,
                       phase_step_s, MIN_FRAMES, _home())


def approach_scan(birds_path, params=PolicyParams(), cadence_hz=2.0, phase_step_s=2.0):
    """Per bird: the closest the nominal mission ever brings the drone to it, and the closest
    approach that happens INSIDE the policy's threat cylinder (None = never a threat).

    Plain geometry on purpose -- it is a complete sweep, and the REAL policy is then invoked at the
    extremum it finds (`TestAvoidanceGate`), which is the frame the verdict actually turns on."""
    birds = json.loads(Path(birds_path).read_text())["birds"]
    samples = pbv.sample_path(pbv.build_legs(MISSION, *_home(), pbv.REFERENCE_SPEED_MPS), cadence_hz)
    t_gate = pbv.bird_start_time_s(samples)
    span = max(b["waypoints"][-1]["t_s"] for b in birds)
    phases = [k * phase_step_s for k in range(max(1, int(math.ceil(span / phase_step_s))))]

    out = {}
    for bird in birds:
        wps, loop = bird["waypoints"], bird.get("loop", True)
        best = {"bird_id": bird["bird_id"], "min_slant_m": math.inf, "min_threat_slant_m": None,
                "threat_sample": None, "phases_with_threat": 0, "n_phases": len(phases)}
        for phase in phases:
            hit = False
            for s in samples:
                bx, by, bz, _yaw = pose_at(s.t_s - t_gate + phase, wps, loop)
                dx, dy, dz = bx - s.pos[0], by - s.pos[1], bz - s.pos[2]
                hrange = math.hypot(dx, dy)
                slant = math.hypot(hrange, dz)
                best["min_slant_m"] = min(best["min_slant_m"], slant)
                if hrange <= params.threat_radius_m and abs(dz) <= params.vertical_threat_m:
                    hit = True
                    if best["min_threat_slant_m"] is None or slant < best["min_threat_slant_m"]:
                        best["min_threat_slant_m"] = slant
                        best["threat_sample"] = (s, (bx, by, bz))
            best["phases_with_threat"] += hit
        out[bird["bird_id"]] = best
    return out


def _drone_state(sample):
    """pbv.Sample -> the policy's DroneState. Yaw back out of the yaw-only quaternion."""
    _, _, qz, qw = sample.quat
    return DroneState(position_enu=sample.pos, heading_rad=2.0 * math.atan2(qz, qw),
                      current_wp_index=0, ground_speed_mps=pbv.REFERENCE_SPEED_MPS)


class TestCameraGate(unittest.TestCase):
    """Gate 1: every bird gets a real in-frame opportunity."""

    @classmethod
    def setUpClass(cls):
        cls.rep = predict(BIRDS)

    def test_every_bird_clears_the_frame_floor(self):
        for b in self.rep["birds"]:
            self.assertGreaterEqual(b["frames_in_view"]["median"], MIN_FRAMES,
                                    f"{b['bird_id']} below the {MIN_FRAMES}-frame floor -- "
                                    f"run scripts/predict_bird_visibility.py")
        self.assertTrue(self.rep["verdict"]["pass"])

    def test_no_bird_is_structurally_invisible(self):
        """STRUCTURAL means no driver-start offset, cadence or luck can ever show it. One
        structurally invisible bird is what made the 2026-08-21 real-render re-run unscoreable."""
        for b in self.rep["birds"]:
            self.assertEqual(b["limited_by"], "timing", b["bird_id"])

    def test_the_threat_bird_is_the_one_never_invisible(self):
        """The safety-relevant bird must not be the one you only see if you are lucky: bird_0 is
        in frame at EVERY swept driver-start offset, which the two lane-crossing birds are not."""
        b = next(x for x in self.rep["birds"] if x["bird_id"] == THREAT_BIRD)
        self.assertEqual(b["phases_with_any_view"], b["n_phases"])


class TestAvoidanceGate(unittest.TestCase):
    """Gate 2: the committed geometry still produces a real threat, judged by the real policy."""

    @classmethod
    def setUpClass(cls):
        cls.scan = approach_scan(BIRDS)
        cls.geo = GeofenceMap.from_file()

    def test_exactly_the_designated_bird_enters_the_threat_cylinder(self):
        threats = [k for k, v in self.scan.items() if v["min_threat_slant_m"] is not None]
        self.assertEqual(threats, [THREAT_BIRD])

    def test_it_is_a_threat_at_every_driver_start_offset(self):
        b = self.scan[THREAT_BIRD]
        self.assertEqual(b["phases_with_threat"], b["n_phases"])

    def test_the_real_policy_diverts_at_the_closest_approach(self):
        """The assertion that is not re-derived geometry: feed the policy the drone state and the
        bird position at the closest in-cylinder approach and require DIVERT with a setpoint. HOLD
        would also mean 'threat seen', but a bird 4 m below open sky must have somewhere to go --
        HOLD here would mean the dodge is boxed in by the orchard, which is a different bug."""
        sample, bird_pos = self.scan[THREAT_BIRD]["threat_sample"]
        m = AvoidancePolicy().decide(
            Detection(position_enu=bird_pos, frame_id=0, track_id=THREAT_BIRD),
            _drone_state(sample), self.geo)
        self.assertIs(m.decision, Decision.DIVERT, m.reason)
        self.assertIsNotNone(m.setpoint_enu)
        # And it is not a free dodge: the threat bird patrols the lane that runs down orchard row 0,
        # so the straight away-from-bird candidate sweeps a tree column and is REJECTED -- the
        # nominal world now reaches the "avoidance must not create a new collision" branch that only
        # the hand-built geo_avoid_into_tree scenario used to. (ADR-015)
        self.assertTrue(m.debug["candidates_rejected"], "expected the 0-deg candidate to be refused")
        self.assertGreaterEqual(m.debug["swept_tree_clearance_m"], 0.0)

    def test_the_other_birds_are_below_the_cylinder_and_the_policy_proceeds(self):
        """Deliberate, not accidental: bird_1 (8 m) and bird_2 (6 m) sit 7 and 9 m under cruise, so
        the policy correctly ignores them however close they pass in XY. Raising either into the
        band to 'add threats' costs them the camera gate -- that is the trade this file guards."""
        pol, params = AvoidancePolicy(), PolicyParams()
        for bird_id, rec in self.scan.items():
            if bird_id == THREAT_BIRD:
                continue
            self.assertIsNone(rec["min_threat_slant_m"], bird_id)
            # directly under the drone, at that bird's altitude: still not a threat
            z = json.loads(BIRDS.read_text())
            z = next(b for b in z["birds"] if b["bird_id"] == bird_id)["waypoints"][0]["z_m"]
            self.assertGreater(params.cruise_alt_m - z, params.vertical_threat_m, bird_id)
            m = pol.decide(Detection((30.0, 30.0, z), frame_id=0, track_id=bird_id),
                           DroneState((30.0, 30.0, 15.0), 0.0, 0), self.geo)
            self.assertIs(m.decision, Decision.PROCEED)


class TestTheThreatIsDetectable(unittest.TestCase):
    """The gap between `TestAvoidanceGate` and the real loop: that test INJECTS a Detection at the
    bird's true position, which the live system cannot do. Under ADR-009 a bird has to be an NDVI
    blob before it has a range at all, so a threat the camera never sees is a threat the loop never
    acts on -- and that is exactly what the as-flown geometry had (its threat bird was in frame at
    37 of 55 driver-start offsets, for a median 3 frames, below the floor). ADR-015's threat bird is
    in frame at every offset; this pins that, and pins that the apparent-size range does not push it
    back out of the cylinder."""

    @classmethod
    def setUpClass(cls):
        cls.rep = predict(BIRDS)
        cls.scan = approach_scan(BIRDS)

    def test_the_threat_bird_is_in_frame_at_every_driver_start_offset(self):
        b = next(x for x in self.rep["birds"] if x["bird_id"] == THREAT_BIRD)
        self.assertEqual(b["phases_with_any_view"], b["n_phases"])
        self.assertGreaterEqual(b["frames_in_view"]["min"], 1)   # never a blind offset

    def test_it_is_in_frame_at_the_closest_in_cylinder_approach(self):
        """Threat moment and visible moment must COINCIDE, not merely both exist."""
        sample, bird_pos = self.scan[THREAT_BIRD]["threat_sample"]
        radius = next(b for b in json.loads(BIRDS.read_text())["birds"]
                      if b["bird_id"] == THREAT_BIRD)["physical_radius_m"]
        sight = pbv.look_at_bird(sample, bird_pos, radius, _intrinsics())
        self.assertTrue(sight.in_frame, "threat bird is not in frame when it is closest")

    def test_apparent_size_range_keeps_it_inside_the_cylinder(self):
        """ADR-009 places the bird along the pixel ray at Zc = f*R_prior/r_px. The prior (0.15 m)
        is SMALLER than this world's bird (0.18 m), so the estimate reads the bird ~17 % CLOSER than
        it is -- the fail-safe direction for avoidance. Pinned because the reverse (an estimate that
        pushed |dz| past vertical_threat_m) would silently delete the only threat in the world."""
        r_prior_m = 0.15                       # ADR-009's physical-radius prior
        sample, bird_pos = self.scan[THREAT_BIRD]["threat_sample"]
        intr = _intrinsics()
        radius = next(b for b in json.loads(BIRDS.read_text())["birds"]
                      if b["bird_id"] == THREAT_BIRD)["physical_radius_m"]
        proj = project_world_point(bird_pos, sample.pos, sample.quat, intr, MOUNT_OFFSET_BODY_M)
        self.assertIsNotNone(proj)
        depth = proj[2]
        r_px = intr.fx * radius / depth
        self.assertGreater(2 * r_px, 20.0, "blob too small to be a credible NDVI detection")
        est_range = intr.fx * r_prior_m / r_px
        self.assertLess(est_range, depth)                       # reads closer, not farther
        self.assertLess(est_range, PolicyParams().vertical_threat_m)  # still a threat


class TestNotAWeakening(unittest.TestCase):
    """The comparison against the geometry ADR-015 replaced, recomputed both ways every run.

    Hardcoding "4.01 m" would rot the moment either config moved; deriving it from the frozen
    as-flown fixture keeps the claim 'no worse on avoidance, strictly better on camera' honest."""

    @classmethod
    def setUpClass(cls):
        cls.old_scan, cls.new_scan = approach_scan(ASFLOWN_BIRDS), approach_scan(BIRDS)
        cls.old_rep, cls.new_rep = predict(ASFLOWN_BIRDS), predict(BIRDS)

    def test_closest_threat_approach_is_no_further_than_before(self):
        old = min(v["min_threat_slant_m"] for v in self.old_scan.values()
                  if v["min_threat_slant_m"] is not None)
        new = min(v["min_threat_slant_m"] for v in self.new_scan.values()
                  if v["min_threat_slant_m"] is not None)
        self.assertLessEqual(new, old + 0.05, f"near-miss weakened: {old:.2f} m -> {new:.2f} m")

    def test_the_number_of_birds_in_the_threat_band_is_unchanged(self):
        n = lambda scan: sum(v["min_threat_slant_m"] is not None for v in scan.values())  # noqa: E731
        self.assertEqual(n(self.new_scan), n(self.old_scan))

    def test_the_altitude_multiset_is_unchanged(self):
        """ADR-015 moved one patrol line and SWAPPED two altitudes; it did not lower the flock.
        {6, 8, 11} before and after is the compact statement of 'the threat band is still
        occupied' -- and the reason this change cannot be a disguised altitude giveaway."""
        alts = lambda p: sorted(b["altitude_m"] for b in predict(p, phase_step_s=8.0)["birds"])  # noqa: E731
        self.assertEqual(alts(BIRDS), alts(ASFLOWN_BIRDS))

    def test_every_bird_improved_or_held_on_the_camera_gate(self):
        old = {b["bird_id"]: b["frames_in_view"]["median"] for b in self.old_rep["birds"]}
        new = {b["bird_id"]: b["frames_in_view"]["median"] for b in self.new_rep["birds"]}
        self.assertFalse(self.old_rep["verdict"]["pass"])
        self.assertTrue(self.new_rep["verdict"]["pass"])
        self.assertGreater(sum(new.values()), sum(old.values()))


class TestNoAltitudeFixesTheOldLine(unittest.TestCase):
    """Why the fix HAD to move the patrol line -- the alternative ADR-003 amendment 1 recommended
    ("lower the birds to 2-3 m AGL") could not have worked for bird_0, and this proves it.

    bird_0's old miss was CROSS-TRACK: it patrolled x=20, a fixed 5.0 m from lane x=15. Lowering it
    grows the cross-track half-footprint by 0.4615 m per metre of depth, so closing 5.0 m needs
    10.8 m of depth -- 4.2 m AGL -- and by then the bird is 10.8 m under cruise, far outside the
    threat cylinder AND near the 3.8 m canopy tops. Below is the measurement, not the algebra."""

    def _bird_0_only(self, x_m, z_m):
        cfg = json.loads(ASFLOWN_BIRDS.read_text())
        bird = next(b for b in cfg["birds"] if b["bird_id"] == "bird_0")
        for wp in bird["waypoints"]:
            wp["x_m"], wp["z_m"] = x_m, z_m
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "birds.json"
            p.write_text(json.dumps({"birds": [bird]}))
            return predict(p, phase_step_s=2.0)["birds"][0]

    def test_no_altitude_in_the_threat_band_rescues_x_20(self):
        for z in (9.0, 10.0, 11.0, 12.0):
            b = self._bird_0_only(20.0, z)
            self.assertEqual(b["frames_in_view"]["max"], 0, f"x=20 z={z}")
            self.assertEqual(b["limited_by"], "structural", f"x=20 z={z}")

    def test_the_altitude_that_would_rescue_x_20_costs_the_threat(self):
        """4 m AGL does clear the floor from x=20 -- and puts the bird 11 m below cruise, i.e. a
        bird that photographs well and threatens nothing. That is the trade ADR-015 refused."""
        b = self._bird_0_only(20.0, 4.0)
        self.assertGreaterEqual(b["frames_in_view"]["median"], MIN_FRAMES)
        self.assertGreater(15.0 - 4.0, PolicyParams().vertical_threat_m)

    def test_moving_the_line_to_the_lane_rescues_it_at_the_threat_altitude(self):
        b = self._bird_0_only(15.0, 11.0)
        self.assertGreaterEqual(b["frames_in_view"]["median"], MIN_FRAMES)
        self.assertEqual(b["limited_by"], "timing")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
