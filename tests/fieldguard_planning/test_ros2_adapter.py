"""Tests for the import-safe parts of the ROS 2 adapter (ros2_adapter.py).

Only the pure ENU<->geodetic conversion and the mode map are testable off-sim; the rclpy pieces
(Ros2VehicleSink) import ardupilot_msgs lazily and are verified live in the container. This test
guards the one piece that MUST be exactly right off-sim: the setpoint coordinate conversion, because
a wrong ENU->lat/lon transform sends the drone to the wrong place — a safety issue, not cosmetic.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fieldguard_planning.ros2_adapter import (  # noqa: E402
    enu_to_geodetic, load_home, AP_COPTER_MODE,
)
from fieldguard_planning.mission_waypoints import latlon_to_enu  # noqa: E402


class TestEnuGeodetic(unittest.TestCase):
    def setUp(self):
        self.home_lat, self.home_lon, self.home_alt = load_home()

    def test_home_maps_to_itself(self):
        lat, lon, alt = enu_to_geodetic(0.0, 0.0, 0.0, self.home_lat, self.home_lon, self.home_alt)
        self.assertAlmostEqual(lat, self.home_lat, places=9)
        self.assertAlmostEqual(lon, self.home_lon, places=9)
        self.assertAlmostEqual(alt, self.home_alt, places=6)

    def test_altitude_is_home_plus_up(self):
        _, _, alt = enu_to_geodetic(0.0, 0.0, 15.0, self.home_lat, self.home_lon, self.home_alt)
        self.assertAlmostEqual(alt, self.home_alt + 15.0, places=6)

    def test_roundtrip_against_latlon_to_enu(self):
        """enu_to_geodetic must be the exact inverse of mission_waypoints.latlon_to_enu (the transform
        used to BUILD the mission), so a setpoint round-trips to the same ENU point sub-millimetre."""
        for e, n, u in [(10.0, 5.0, 15.0), (-20.0, 40.0, 12.0), (75.0, 60.0, 20.0), (0.0, 0.0, 0.0)]:
            lat, lon, _ = enu_to_geodetic(e, n, u, self.home_lat, self.home_lon, self.home_alt)
            e2, n2 = latlon_to_enu(lat, lon, self.home_lat, self.home_lon)
            self.assertAlmostEqual(e2, e, places=6, msg=f"east round-trip off for ENU=({e},{n},{u})")
            self.assertAlmostEqual(n2, n, places=6, msg=f"north round-trip off for ENU=({e},{n},{u})")

    def test_mode_numbers(self):
        self.assertEqual(AP_COPTER_MODE["AUTO"], 3)
        self.assertEqual(AP_COPTER_MODE["GUIDED"], 4)


if __name__ == "__main__":
    unittest.main()
