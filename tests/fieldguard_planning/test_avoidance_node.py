"""Tests for the import-safe helpers in avoidance_node.py (only the rclpy wiring is verified live).

The scripted detection sources (the ADR-013 am. 2 regression arm, and the A/B against the real
detector) and `_nearest_upcoming_wp` are pure/stdlib and must be right: they drive what the loop
reacts to and the resume bookkeeping.

Two sibling files cover the rest of this node, split by dependency tier:
  * `test_avoidance_node_seam.py` -- `AvoidanceLoop` (clock domain, staleness gate, tick axis), the
    `run` block, the CLI. Stdlib-only, like this file.
  * `test_detection_seam.py`      -- the real detector on the seam and the ADR-009 apparent-size
    ray. numpy + scipy.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fieldguard_planning.avoidance_node import (  # noqa: E402
    scripted_bird_source, proximity_bird_source, _nearest_upcoming_wp, DEMO_BIRD_ENU,
)
from fieldguard_planning.avoidance_types import DroneState  # noqa: E402


def _drone(x, y, z=15.0):
    return DroneState(position_enu=(x, y, z), heading_rad=0.0, current_wp_index=0)


class TestScriptedBirdSource(unittest.TestCase):
    def test_emits_within_window_only(self):
        src = scripted_bird_source([("b0", (30.0, 30.0, 15.0), 2.0, 5.0)])
        self.assertEqual(src(0.0, None), [])            # before window
        self.assertEqual(len(src(3.0, None)), 1)        # inside
        self.assertEqual(src(9.0, None), [])            # after window
        self.assertEqual(src(3.0, None)[0].track_id, "b0")


class TestProximityBirdSource(unittest.TestCase):
    def test_appears_on_proximity_lingers_then_clears(self):
        src = proximity_bird_source(DEMO_BIRD_ENU, trigger_radius_m=15.0, linger_s=8.0)
        # far away -> nothing, and the trigger has NOT armed
        self.assertEqual(src(1.0, _drone(0.0, 0.0)), [])
        # drone arrives within 15 m of the bird at (30,30) -> bird appears
        self.assertEqual(len(src(10.0, _drone(30.0, 40.0))), 1)   # 10 m away, triggers at t=10
        # lingers while within linger_s of the trigger, even if the drone moves off
        self.assertEqual(len(src(15.0, _drone(0.0, 0.0))), 1)     # t=15, 5s since trigger -> still present
        # after linger_s it has "flown off"
        self.assertEqual(src(19.0, _drone(30.0, 30.0)), [])       # t=19, 9s since trigger -> gone

    def test_none_drone_is_safe(self):
        src = proximity_bird_source(DEMO_BIRD_ENU)
        self.assertEqual(src(1.0, None), [])


class TestNearestWaypoint(unittest.TestCase):
    def test_picks_nearest(self):
        mission = [(0.0, 0.0), (0.0, 30.0), (0.0, 60.0)]
        self.assertEqual(_nearest_upcoming_wp((0.0, 2.0), mission), 0)
        self.assertEqual(_nearest_upcoming_wp((0.0, 28.0), mission), 1)
        self.assertEqual(_nearest_upcoming_wp((0.0, 55.0), mission), 2)


if __name__ == "__main__":
    unittest.main()
