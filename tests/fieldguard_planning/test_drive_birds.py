"""Tests for scripts/drive_birds.py's interpolation core (ADR-012).

The gz service calls are exercised live in the container (runbook); what THESE tests pin is
`pose_at` — the piecewise-linear replacement for the SDF <actor><script> interpolation the birds
lost when they became models. A subtle wrap/hold bug here silently changes the committed bird
trajectories, which are safety-scenario inputs. Stdlib unittest, bare python.
"""
import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from drive_birds import pose_at, set_pose_request  # noqa: E402

WPS = [
    {"t_s": 0.0, "x_m": 0.0, "y_m": 0.0, "z_m": 10.0, "yaw_deg": 0.0},
    {"t_s": 10.0, "x_m": 20.0, "y_m": 0.0, "z_m": 10.0, "yaw_deg": 90.0},
    {"t_s": 20.0, "x_m": 20.0, "y_m": 30.0, "z_m": 14.0, "yaw_deg": 90.0},
]


class TestPoseAt(unittest.TestCase):
    def test_exact_waypoints(self):
        self.assertEqual(pose_at(0.0, WPS), (0.0, 0.0, 10.0, 0.0))
        x, y, z, yaw = pose_at(10.0, WPS)
        self.assertEqual((x, y, z), (20.0, 0.0, 10.0))
        self.assertAlmostEqual(yaw, math.pi / 2)

    def test_midpoint_interpolates_all_channels(self):
        x, y, z, yaw = pose_at(5.0, WPS)
        self.assertAlmostEqual(x, 10.0)
        self.assertAlmostEqual(y, 0.0)
        self.assertAlmostEqual(z, 10.0)
        self.assertAlmostEqual(yaw, math.pi / 4)  # 45 deg, halfway to 90
        x, y, z, _ = pose_at(15.0, WPS)
        self.assertAlmostEqual((y, z)[0], 15.0)
        self.assertAlmostEqual(z, 12.0)

    def test_loop_wraps_modulo_last_time(self):
        # t=25 with loop -> t=5 (25 % 20): same pose as the t=5 midpoint
        self.assertEqual(pose_at(25.0, WPS, loop=True), pose_at(5.0, WPS))

    def test_no_loop_holds_last_waypoint(self):
        x, y, z, yaw = pose_at(999.0, WPS, loop=False)
        self.assertEqual((x, y, z), (20.0, 30.0, 14.0))
        self.assertAlmostEqual(yaw, math.pi / 2)

    def test_before_start_holds_first(self):
        self.assertEqual(pose_at(-3.0, WPS, loop=False), (0.0, 0.0, 10.0, 0.0))

    def test_empty_waypoints_raise(self):
        with self.assertRaises(ValueError):
            pose_at(0.0, [])


class TestSetPoseRequest(unittest.TestCase):
    def test_yaw_to_quaternion(self):
        req = set_pose_request("bird_0", (1.0, 2.0, 3.0, math.pi))  # 180 deg: z=1, w=0
        self.assertIn('name: "bird_0"', req)
        self.assertIn("z: 1.000000", req)
        self.assertIn("w: 0.000000", req)

    def test_zero_yaw_identity_quaternion(self):
        req = set_pose_request("bird_1", (0.0, 0.0, 0.0, 0.0))
        self.assertIn("z: 0.000000", req)
        self.assertIn("w: 1.000000", req)


if __name__ == "__main__":
    unittest.main()
