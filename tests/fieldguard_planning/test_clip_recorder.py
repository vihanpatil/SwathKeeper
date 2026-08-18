"""Tests for clip_recorder.ClipWriter — the live-flight recorder's pure core.

The one that matters most: `test_written_clip_is_stitchable` closes the recorder->stitcher
contract by feeding a ClipWriter-produced clip STRAIGHT into scripts/stitch_ndvi.stitch_clip —
if the two ever drift (schema keys, path layout, quat order), that test fails, not the one
scarce Docker recording session. numpy allowed (ndvi_* module family).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from fieldguard_planning.clip_recorder import ClipWriter  # noqa: E402
from fieldguard_planning.coverage import build_grid, load_field_polygon  # noqa: E402
import stitch_ndvi  # noqa: E402

CAM = {"image_width_px": 64, "image_height_px": 48, "fx": 52.0, "fy": 52.0, "cx": 32.0, "cy": 24.0}
IDENTITY_XYZW = (0.0, 0.0, 0.0, 1.0)


class TestClipWriter(unittest.TestCase):
    def test_written_clip_is_stitchable(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM, mount_offset_body_m=(0.0, 0.0, 0.0))
            ndvi = np.full((48, 64), 0.7, dtype=np.float32)
            w.add_frame(100.0, ndvi, (40.0, 20.0, 15.0), IDENTITY_XYZW, pose_age_wall_s=0.05)
            w.add_frame(100.2, ndvi, (41.0, 20.0, 15.0), IDENTITY_XYZW, pose_age_wall_s=0.06)
            summary = w.finalize()
            self.assertEqual(summary["n_frames"], 2)

            grid, stats = stitch_ndvi.stitch_clip(Path(td), build_grid(load_field_polygon()))
            self.assertEqual(stats["frames_total"], 2)
            self.assertFalse(stats["clip_synthetic"])          # the real thing at last
            means = grid.mean_grid()
            cell = min(grid.cells, key=lambda c: (c.cx_m - 40.5) ** 2 + (c.cy_m - 20.0) ** 2)
            self.assertAlmostEqual(means[cell.cell_id], 0.7, places=5)

    def test_quat_conversion_xyzw_to_wxyz(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            w.add_frame(0.0, np.zeros((48, 64), np.float32),
                        (0.0, 0.0, 15.0), IDENTITY_XYZW, pose_age_wall_s=0.0)
            w.finalize()
            line = json.loads((Path(td) / "poses.jsonl").read_text().splitlines()[0])
            self.assertEqual(line["drone"]["quat_wxyz"], [1.0, 0.0, 0.0, 0.0])  # w first

    def test_t_s_relative_to_first_frame_and_extras_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            z = np.zeros((48, 64), np.float32)
            w.add_frame(500.0, z, (0, 0, 15.0), IDENTITY_XYZW, pose_age_wall_s=0.11)
            w.add_frame(500.2, z, (1, 0, 15.0), IDENTITY_XYZW, pose_age_wall_s=0.02)
            w.finalize()
            lines = [json.loads(s) for s in (Path(td) / "poses.jsonl").read_text().splitlines()]
            self.assertEqual([ln["t_s"] for ln in lines], [0.0, 0.2])
            self.assertEqual(lines[0]["stamp_sim_s"], 500.0)     # absolute stamp kept for audit
            self.assertEqual(lines[0]["pose_age_wall_s"], 0.11)  # staleness quantified, not hidden

    def test_rgb_optional_and_injected_writer_called(self):
        calls = []
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM, png_writer=lambda p, a: calls.append((p, a.shape)))
            z = np.zeros((48, 64), np.float32)
            w.add_frame(0.0, z, (0, 0, 15.0), IDENTITY_XYZW, 0.0,
                        rgb=np.zeros((48, 64, 3), np.uint8))
            w.add_frame(0.2, z, (1, 0, 15.0), IDENTITY_XYZW, 0.0)  # no rgb this frame
            s = w.finalize()
            self.assertEqual(s["n_rgb"], 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], (48, 64, 3))
            lines = [json.loads(x) for x in (Path(td) / "poses.jsonl").read_text().splitlines()]
            self.assertIn("rgb_path", lines[0])
            self.assertNotIn("rgb_path", lines[1])

    def test_no_png_writer_skips_rgb_dir(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM, png_writer=None)
            w.add_frame(0.0, np.zeros((48, 64), np.float32), (0, 0, 15.0), IDENTITY_XYZW, 0.0,
                        rgb=np.zeros((48, 64, 3), np.uint8))  # rgb passed but no writer -> skipped
            s = w.finalize()
            self.assertEqual(s["n_rgb"], 0)
            self.assertFalse((Path(td) / "frames" / "rgb").exists())

    def test_meta_honesty_fields(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            w.origin = {"x": 1.0, "y": 2.0, "z": 3.0, "note": "PoseStamped passthrough",
                        "lat_deg?": None}
            w.add_frame(0.0, np.zeros((48, 64), np.float32), (0, 0, 15.0), IDENTITY_XYZW, 0.0)
            w.finalize()
            meta = json.loads((Path(td) / "meta.json").read_text())
            self.assertFalse(meta["synthetic"])
            self.assertFalse(meta["pending_gazebo_replacement"])
            self.assertEqual(meta["camera"]["fx"], 52.0)
            self.assertIn("clock_note", meta)
            self.assertEqual(meta["gps_global_origin"]["x"], 1.0)


if __name__ == "__main__":
    unittest.main()
