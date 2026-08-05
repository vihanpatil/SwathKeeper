"""Unit tests for src/fieldguard_planning/mission_waypoints.py.

stdlib unittest only -- see test_geofence.py for the "why".
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.mission_waypoints import (  # noqa: E402
    latlon_to_enu, mission_xy_path, parse_qgc_wpl,
)

MISSION_PATH = REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints"
HOME_LAT, HOME_LON = -35.363262, 149.165237


class TestParseQgcWpl(unittest.TestCase):
    def test_parses_all_15_items(self):
        items = parse_qgc_wpl(MISSION_PATH)
        self.assertEqual(len(items), 15)
        self.assertEqual(items[0].seq, 0)
        self.assertEqual(items[-1].command, 20)  # NAV_RTL

    def test_rejects_missing_header(self):
        bad = REPO_ROOT / "tests" / "fieldguard_planning" / "_not_a_mission.txt"
        bad.write_text("not a mission file\n")
        try:
            with self.assertRaises(ValueError):
                parse_qgc_wpl(bad)
        finally:
            bad.unlink()


class TestLatLonToEnu(unittest.TestCase):
    def test_home_maps_to_origin(self):
        east, north = latlon_to_enu(HOME_LAT, HOME_LON, HOME_LAT, HOME_LON)
        self.assertAlmostEqual(east, 0.0, places=6)
        self.assertAlmostEqual(north, 0.0, places=6)

    def test_known_offset_round_trips(self):
        # Inverse of scripts/gen_boustrophedon.py's to_ll(north=0, east=15) for this home.
        lat, lon = HOME_LAT, 149.1654022321657
        east, north = latlon_to_enu(lat, lon, HOME_LAT, HOME_LON)
        self.assertAlmostEqual(east, 15.0, places=3)
        self.assertAlmostEqual(north, 0.0, places=3)


class TestMissionXyPath(unittest.TestCase):
    def setUp(self):
        self.items = parse_qgc_wpl(MISSION_PATH)
        self.path = mission_xy_path(self.items, HOME_LAT, HOME_LON)

    def test_first_point_is_home_origin(self):
        east, north = self.path[0]
        self.assertAlmostEqual(east, 0.0, places=3)
        self.assertAlmostEqual(north, 0.0, places=3)

    def test_takeoff_item_does_not_produce_a_bogus_00_offset_point(self):
        # Regression guard for the placeholder-lat/lon trap documented in mission_waypoints.py:
        # NAV_TAKEOFF's literal lat/lon fields are 0.0/0.0, which -- if taken literally instead of
        # being mapped to "current position" -- would produce a point ~149 degrees of longitude
        # and ~35 degrees of latitude away from the field (a real position, just a nonsensical one
        # for this mission). Confirm every path point stays within the field's extent instead.
        for east, north in self.path:
            self.assertGreaterEqual(east, -1.0)
            self.assertLessEqual(east, 76.0)
            self.assertGreaterEqual(north, -1.0)
            self.assertLessEqual(north, 61.0)

    def test_path_covers_all_six_lanes(self):
        # 1 home + 1 takeoff(in-place) + 12 waypoints + 1 RTL(in-place) = 15 points.
        self.assertEqual(len(self.path), 15)
        xs = sorted({round(e, 1) for e, n in self.path})
        self.assertEqual(xs, [0.0, 15.0, 30.0, 45.0, 60.0, 75.0])


if __name__ == "__main__":
    unittest.main()
