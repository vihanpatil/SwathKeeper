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

from check_render_alive import verdict  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
