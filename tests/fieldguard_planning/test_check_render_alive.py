"""Tests for the render-sanity probe's pure verdict logic (scripts/check_render_alive.py).

The probe exists because a long-lived Gazebo instance degraded to rendering channel-balanced
near-white in both bands (2026-08-18) and a whole recorded flight was content-free; these pin the
three verdicts so the discriminator can't silently drift. Stdlib + numpy-free (verdict takes any
3-sequence).
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_render_alive import depth_expected, depth_verdict, verdict  # noqa: E402

WORLD = REPO_ROOT / "sim" / "worlds" / "farmguard_field.sdf"


class TestVerdict(unittest.TestCase):
    def test_sky_flat_degradation_is_exit_1(self):
        code, msg = verdict((238.0, 238.0, 235.0))  # the measured 2026-08-18 signature
        self.assertEqual(code, 1)
        self.assertIn("DEGRADED", msg)

    def test_healthy_green_dominant_world_is_exit_0(self):
        code, msg = verdict((130.0, 182.0, 88.0))  # authored soil under full light
        self.assertEqual(code, 0)
        self.assertIn("ALIVE", msg)

    def test_ambiguous_scene_is_exit_1_suspect(self):
        code, msg = verdict((180.0, 150.0, 120.0))  # neither signature
        self.assertEqual(code, 1)
        self.assertIn("SUSPECT", msg)

    def test_bright_but_unbalanced_is_not_called_degraded(self):
        # bright green-ish (e.g. washed-out but real world) must not read as sky
        code, msg = verdict((205.0, 245.0, 190.0))
        self.assertEqual(code, 0)


class TestDepthLiveness(unittest.TestCase):
    """M5: the MANDATORY pre-flight probe `fly_pipeline.sh` gates on subscribed to the RGB band
    only, so `up` went all-green with the ADR-019 depth camera dead -- the exact shape of the
    2026-08-18 failure this probe was built for, on the newer sensor."""

    def test_the_committed_world_declares_a_depth_camera_so_the_probe_must_require_it(self):
        self.assertTrue(depth_expected(WORLD))

    def test_a_world_without_the_depth_mount_does_not_demand_a_depth_frame(self):
        """The requirement is derived from the world actually being flown, not asserted: an older
        or camera-stripped world must not fail a probe for a sensor it does not have."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            stripped = Path(td) / "w.sdf"
            stripped.write_text(WORLD.read_text().replace("fg/depth/image", "nope/image"))
            self.assertFalse(depth_expected(stripped))
        self.assertFalse(depth_expected(Path("/nonexistent/world.sdf")))

    def test_no_depth_frame_when_one_is_expected_is_exit_2(self):
        code, msg = depth_verdict(None)
        self.assertEqual(code, 2)
        self.assertIn("NO DEPTH FRAME", msg)

    def test_an_all_non_finite_depth_frame_is_degraded(self):
        """Parked or flying, the ground is always somewhere in a forward frustum. A frame that is
        entirely +/-inf means the depth pass produced nothing, not that the world is empty."""
        code, msg = depth_verdict({"finite_frac": 0.0, "min_m": None, "max_m": None})
        self.assertEqual(code, 1)
        self.assertIn("DEGRADED", msg)

    def test_a_normal_depth_frame_is_alive(self):
        code, msg = depth_verdict({"finite_frac": 0.42, "min_m": 6.1, "max_m": 58.7})
        self.assertEqual(code, 0)
        self.assertIn("ALIVE", msg)


if __name__ == "__main__":
    unittest.main()
