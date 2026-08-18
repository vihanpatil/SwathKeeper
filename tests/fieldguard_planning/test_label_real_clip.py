"""Tests for eval/label_from_sim.py's oriented projection path (real recorded clips).

Real clips carry only the yawing drone pose, so GT projection must handle full orientation. Rather
than a second set of hand fixtures, these tests pin CONSISTENCY with the two already-trusted
implementations: (1) at identity attitude + zero offset the oriented projector must equal
spike_common.project_bird (the fixed-extrinsic spike model — same camera, same convention), and
(2) at ARBITRARY attitude its (u, v) must equal ndvi_georef.world_enu_to_pixel (the hand-fixture-
tested transform the heatmap stitch uses) — one camera model across GT labels and the map.
numpy allowed (eval family).
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "eval"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "spike"))

import spike_common as sc  # noqa: E402
from label_from_sim import project_bird_oriented  # noqa: E402
from fieldguard_planning.ndvi_georef import CameraIntrinsics, world_enu_to_pixel  # noqa: E402

INTR = {"fx": 520.0, "fy": 520.0, "cx": 320.0, "cy": 240.0,
        "image_width_px": 640, "image_height_px": 480}
IDENTITY = (0.0, 0.0, 0.0, 1.0)


class TestOrientedProjection(unittest.TestCase):
    def test_identity_attitude_matches_spike_fixed_extrinsic(self):
        drone = (30.0, 20.0, 15.0)
        for bird in [(30.0, 20.0, 8.0), (33.0, 24.0, 9.5), (26.5, 18.0, 5.0)]:
            with self.subTest(bird=bird):
                got = project_bird_oriented(bird, drone, IDENTITY, (0.0, 0.0, 0.0), INTR)
                want = sc.project_bird(list(bird), list(drone), INTR)
                self.assertIsNotNone(got)
                self.assertIsNotNone(want)
                for g, w in zip(got, want):
                    self.assertAlmostEqual(g, w, places=9)

    def test_arbitrary_attitude_matches_georef_inverse_transform(self):
        import math
        drone = (15.0, 30.0, 15.0)
        offset = (0.0, 0.0, -0.08)
        intr_obj = CameraIntrinsics(width_px=640, height_px=480, fx=520.0, fy=520.0,
                                    cx=320.0, cy=240.0)
        # yaw 90, and a combined yaw+pitch quat (order-of-magnitude arbitrary attitude)
        s45, c45 = math.sin(math.pi / 4), math.cos(math.pi / 4)
        quats = [(0.0, 0.0, s45, c45),
                 (0.02, 0.12, 0.69, 0.71)]  # denormalized on purpose: georef re-normalizes
        for q in quats:
            for bird in [(15.0, 36.0, 8.0), (10.0, 27.0, 10.0)]:
                with self.subTest(q=q, bird=bird):
                    got = project_bird_oriented(bird, drone, q, offset, INTR)
                    want = world_enu_to_pixel(bird, drone, q, intr_obj, offset)
                    if want is None:
                        self.assertIsNone(got)
                        continue
                    self.assertIsNotNone(got)
                    self.assertAlmostEqual(got[0], want[0], places=9)
                    self.assertAlmostEqual(got[1], want[1], places=9)
                    self.assertGreater(got[2], 0.0)  # zc: the extra the bbox radius needs

    def test_bird_behind_camera_returns_none(self):
        # nose-down 180-degree roll would do it; simpler: bird ABOVE a nadir camera
        self.assertIsNone(project_bird_oriented((30.0, 20.0, 25.0), (30.0, 20.0, 15.0),
                                                IDENTITY, (0.0, 0.0, 0.0), INTR))


if __name__ == "__main__":
    unittest.main()
