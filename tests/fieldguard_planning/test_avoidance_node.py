"""Tests for the import-safe helpers in avoidance_node.py (the rclpy node itself is verified live).

`scripted_bird_source` (the demo detector stand-in) and `_nearest_upcoming_wp` (the current-waypoint
derivation) are pure/stdlib and must be right: the first drives what the loop reacts to, the second
feeds the resume bookkeeping.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fieldguard_planning.avoidance_node import (  # noqa: E402
    scripted_bird_source, _nearest_upcoming_wp, DEMO_BIRDS,
)


class TestScriptedBirdSource(unittest.TestCase):
    def test_emits_within_window_only(self):
        src = scripted_bird_source([("b0", (30.0, 30.0, 15.0), 2.0, 5.0)])
        self.assertEqual(src(0.0), [])                 # before window
        self.assertEqual(len(src(3.0)), 1)             # inside
        self.assertEqual(src(9.0), [])                 # after window
        det = src(3.0)[0]
        self.assertEqual(det.track_id, "b0")
        self.assertEqual(det.position_enu, (30.0, 30.0, 15.0))

    def test_default_demo_bird_is_a_threat_on_lane_x30(self):
        src = scripted_bird_source(DEMO_BIRDS)
        dets = src(1.0)
        self.assertEqual(len(dets), 1)
        self.assertEqual(dets[0].position_enu[0], 30.0)  # on lane x=30


class TestNearestWaypoint(unittest.TestCase):
    def test_picks_nearest(self):
        mission = [(0.0, 0.0), (0.0, 30.0), (0.0, 60.0)]
        self.assertEqual(_nearest_upcoming_wp((0.0, 2.0), mission), 0)
        self.assertEqual(_nearest_upcoming_wp((0.0, 28.0), mission), 1)
        self.assertEqual(_nearest_upcoming_wp((0.0, 55.0), mission), 2)


if __name__ == "__main__":
    unittest.main()
