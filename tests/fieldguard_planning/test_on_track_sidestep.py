"""R4 (2026-11-10): an on-track threat is answered with a perpendicular sidestep, not a reversal.

The 2026-08-26 point-mass replay measured that the 0 deg reversal resolves a head-on closure at NO
lead time, and the +/-90 deg sidesteps resolve from 1.25 s. Every flown dodge took candidate 0 and
every one struck. These tests pin the new candidate order and, just as deliberately, where it does
NOT apply: a bird abeam, and the R3 regime inside on_track_sidestep_min_range_m.
"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from fieldguard_planning.avoidance_policy import (  # noqa: E402
    _CANDIDATE_ANGLES_DEG, _ON_TRACK_CANDIDATE_ANGLES_DEG, ON_TRACK_HALF_ANGLE_DEG,
    SIDESTEP_SIDE_DEADBAND_M, AvoidancePolicy, Decision, PolicyParams,
)
from fieldguard_planning.avoidance_types import Detection, DroneState  # noqa: E402
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402

CRUISE = 15.0
FIELD = [(0.0, 0.0), (75.0, 0.0), (75.0, 60.0), (0.0, 60.0)]
NORTH = math.pi / 2.0


def _drone(x, y, heading=NORTH, track=None):
    return DroneState(position_enu=(x, y, CRUISE), heading_rad=heading, current_wp_index=3,
                      track_heading_rad=track)


def _bird(x, y, z=11.0):
    return Detection(position_enu=(x, y, z), frame_id=1, confidence=1.0, track_id="bird_0")


class OnTrackSidestep(unittest.TestCase):
    def setUp(self):
        self.geo = GeofenceMap(obstacles=[])              # open field: only the order is under test
        self.pol = AvoidancePolicy(field_polygon=FIELD, threat_radius_m=45.0)

    def test_head_on_bird_gets_a_perpendicular_sidestep_first(self):
        m = self.pol.decide(_bird(15.0, 50.0), _drone(15.0, 10.0), self.geo)   # 40 m dead ahead
        self.assertIs(m.decision, Decision.DIVERT)
        self.assertEqual(m.debug["candidate_order"], "on_track_sidestep")
        self.assertIn(m.debug["candidate_angle_deg"], (90.0, -90.0))
        self.assertEqual(m.debug["bird_bearing_off_track_deg"], 0.0)
        # the setpoint is 10 m ABEAM of the lane, not 10 m back down it
        self.assertAlmostEqual(abs(m.setpoint_enu[0] - 15.0), 10.0, places=6)
        self.assertAlmostEqual(m.setpoint_enu[1], 10.0, places=6)

    def test_overtaking_bird_astern_is_on_track_too(self):
        m = self.pol.decide(_bird(15.0, 0.0), _drone(15.0, 30.0), self.geo)    # 30 m dead astern
        self.assertEqual(m.debug["candidate_order"], "on_track_sidestep")
        self.assertIn(m.debug["candidate_angle_deg"], (90.0, -90.0))

    def test_a_bird_clearly_left_is_passed_on_the_right(self):
        # bird 1.5 m LEFT of the northbound track (west), outside the dead-band: sidestep EAST
        off = SIDESTEP_SIDE_DEADBAND_M + 0.5
        m = self.pol.decide(_bird(15.0 - off, 50.0), _drone(15.0, 10.0), self.geo)
        self.assertEqual(m.debug["candidate_order"], "on_track_sidestep")
        self.assertEqual(m.debug["sidestep_side_rule"], "away_from_offset")
        self.assertGreater(m.setpoint_enu[0], 15.0, "dodged onto the bird's own side")
        m2 = self.pol.decide(_bird(15.0 + off, 50.0), _drone(15.0, 10.0), self.geo)
        self.assertLess(m2.setpoint_enu[0], 15.0)

    def test_a_bird_dead_ahead_is_passed_on_the_field_interior_side_whichever_way_it_jitters(self):
        # inside the dead-band the offset's SIGN is noise: both jitters go EAST, toward the field
        # centroid (37.5, 30) from lane x=15 -- the choice that dithered RL/LR on run 3 (2026-11-10)
        for dx in (-0.5, 0.0, +0.5):
            m = self.pol.decide(_bird(15.0 + dx, 50.0), _drone(15.0, 10.0), self.geo)
            self.assertEqual(m.debug["sidestep_side_rule"], "field_interior", dx)
            self.assertGreater(m.setpoint_enu[0], 15.0, f"dx={dx} went west, away from the interior")
        # ...and from lane x=60 the interior is WEST
        m = self.pol.decide(_bird(60.0, 50.0), _drone(60.0, 10.0), self.geo)
        self.assertLess(m.setpoint_enu[0], 60.0)

    def test_the_track_axis_not_the_yaw_decides_on_track(self):
        # mid-dodge the airframe yaws EAST toward its setpoint; the bird is still dead ahead ON THE
        # LANE (north). With the leg heading supplied, the order is still the sidestep; on yaw
        # alone the same geometry reads as a bird abeam.
        with_track = self.pol.decide(_bird(15.0, 50.0), _drone(15.0, 10.0, heading=0.0, track=NORTH), self.geo)
        self.assertEqual(with_track.debug["candidate_order"], "on_track_sidestep")
        self.assertEqual(with_track.debug["bird_bearing_off_track_deg"], 0.0)
        yaw_only = self.pol.decide(_bird(15.0, 50.0), _drone(15.0, 10.0, heading=0.0), self.geo)
        self.assertEqual(yaw_only.debug["candidate_order"], "away_first")

    def test_the_node_derives_the_leg_heading_from_the_mission(self):
        from fieldguard_planning.avoidance_node import _leg_heading_rad
        lane = [(0.0, 0.0), (15.0, 0.0), (15.0, 60.0), (15.0, 0.0)]
        self.assertIsNone(_leg_heading_rad(lane, 0))
        self.assertAlmostEqual(_leg_heading_rad(lane, 1), 0.0)             # east
        self.assertAlmostEqual(_leg_heading_rad(lane, 2), math.pi / 2.0)   # north
        self.assertAlmostEqual(_leg_heading_rad(lane, 3), -math.pi / 2.0)  # south
        self.assertIsNone(_leg_heading_rad(lane, 4))
        self.assertIsNone(_leg_heading_rad([(1.0, 1.0), (1.0, 1.0)], 1))

    def test_a_bird_abeam_keeps_the_away_first_order(self):
        m = self.pol.decide(_bird(40.0, 10.0), _drone(15.0, 10.0), self.geo)   # 25 m to the east
        self.assertIs(m.decision, Decision.DIVERT)
        self.assertEqual(m.debug["candidate_order"], "away_first")
        self.assertEqual(m.debug["candidate_angle_deg"], 0.0)
        self.assertEqual(m.debug["bird_bearing_off_track_deg"], 90.0)

    def test_the_on_track_cone_edge_is_the_constant(self):
        rng = 30.0
        inside = math.radians(ON_TRACK_HALF_ANGLE_DEG - 1.0)
        outside = math.radians(ON_TRACK_HALF_ANGLE_DEG + 1.0)
        d = _drone(15.0, 10.0)
        m_in = self.pol.decide(_bird(15.0 + rng * math.sin(inside), 10.0 + rng * math.cos(inside)), d, self.geo)
        m_out = self.pol.decide(_bird(15.0 + rng * math.sin(outside), 10.0 + rng * math.cos(outside)), d, self.geo)
        self.assertEqual(m_in.debug["candidate_order"], "on_track_sidestep")
        self.assertEqual(m_out.debug["candidate_order"], "away_first")

    def test_inside_the_min_range_the_R3_regime_is_untouched(self):
        p = PolicyParams()
        close = p.on_track_sidestep_min_range_m - 0.5
        # mid-field, so the 0 deg reversal is not refused by the field-edge gate instead
        m = self.pol.decide(_bird(15.0, 30.0 + close), _drone(15.0, 30.0), self.geo)
        self.assertEqual(m.debug["candidate_order"], "away_first")
        self.assertEqual(m.debug["candidate_angle_deg"], 0.0)

    def test_the_two_orders_are_the_same_set_and_the_knob_is_logged(self):
        self.assertEqual(sorted(_CANDIDATE_ANGLES_DEG), sorted(_ON_TRACK_CANDIDATE_ANGLES_DEG))
        self.assertEqual(_CANDIDATE_ANGLES_DEG[0], 0.0)
        self.assertEqual(_ON_TRACK_CANDIDATE_ANGLES_DEG[:2], (90.0, -90.0))
        m = self.pol.decide(_bird(15.0, 50.0), _drone(15.0, 10.0), self.geo)
        self.assertEqual(m.debug["params"]["on_track_sidestep_min_range_m"],
                         PolicyParams().on_track_sidestep_min_range_m)


class SweptMarginIsAltitudeAware(unittest.TestCase):
    """Gate 2 (R2's swept-path tree margin) applies only where the dodge can meet a tree. Lane x=15
    runs over tree row 0 (trees at y = 5, 15, ..., 55; exclusion 2.0 m; 3.8 m tall), so at cruise the
    vehicle is inside a column 40 % of the time -- and the 2026-11-10 baseline encounter HOLDed there."""

    @classmethod
    def setUpClass(cls):
        cls.geo = GeofenceMap.from_file()
        cls.pol = AvoidancePolicy(field_polygon=FIELD, threat_radius_m=45.0)

    def test_band_top_is_the_tallest_tree_plus_the_margin(self):
        self.assertAlmostEqual(self.geo.canopy_band_top_m(1.0), 3.8 + 1.0, places=6)
        self.assertEqual(GeofenceMap(obstacles=[]).canopy_band_top_m(1.0), -math.inf + 1.0)

    def test_over_a_tree_column_at_cruise_the_vehicle_still_dodges(self):
        # drone XY inside tree_row0_1's column at (15, 15); bird 40 m dead ahead down the lane
        m = self.pol.decide(_bird(15.0, 55.5), _drone(15.0, 15.5), self.geo)
        self.assertIs(m.decision, Decision.DIVERT, m.reason)
        self.assertFalse(m.debug["swept_margin_applied"])
        self.assertEqual(m.debug["candidate_order"], "on_track_sidestep")

    def test_inside_the_canopy_band_the_margin_still_bites(self):
        # same XY geometry flown at 4.0 m, inside the 4.8 m band: gate 2 is live again
        drone = DroneState(position_enu=(15.0, 15.5, 4.0), heading_rad=NORTH, current_wp_index=3)
        m = self.pol.decide(_bird(15.0, 55.5, 4.0), drone, self.geo, cruise_alt_m=4.0)
        if m.decision is Decision.DIVERT:
            self.assertTrue(m.debug["swept_margin_applied"])
            self.assertGreaterEqual(m.debug["swept_tree_clearance_m"], PolicyParams().lateral_tree_margin_m)
        else:
            self.assertIs(m.decision, Decision.HOLD)   # boxed in by the column: the documented answer
        rejected = m.debug["candidates_rejected"]
        self.assertTrue(any("canopy band" in r["why"] for r in rejected), rejected)


class DepthSourceThreatRadius(unittest.TestCase):
    def test_the_depth_radius_sits_inside_the_acquisition_bound(self):
        import json
        from fieldguard_planning.avoidance_node import DEPTH_THREAT_RADIUS_M
        from fieldguard_planning.depth_detect import acquisition_range_m, MIN_RESOLVING_RADIUS_PX
        cfg = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "config", "depth_camera.json")))
        fx = (cfg["camera"]["image_width_px"] / 2.0) / math.tan(cfg["camera"]["horizontal_fov_rad"] / 2.0)
        acq = acquisition_range_m(fx, 0.18, MIN_RESOLVING_RADIUS_PX)
        self.assertLess(DEPTH_THREAT_RADIUS_M, acq)
        self.assertGreater(DEPTH_THREAT_RADIUS_M, 3 * PolicyParams().threat_radius_m)


if __name__ == "__main__":
    unittest.main()
