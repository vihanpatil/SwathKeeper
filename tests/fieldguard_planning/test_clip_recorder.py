"""Tests for clip_recorder — the live-flight recorder's pure core (ClipWriter + PoseBuffer).

The one that matters most: `test_written_clip_is_stitchable` closes the recorder->stitcher
contract by feeding a ClipWriter-produced clip STRAIGHT into scripts/stitch_ndvi.stitch_clip —
if the two ever drift (schema keys, path layout, quat order), that test fails, not the one
scarce Docker recording session. PoseBuffer is the burst-proof stamp pairing that replaced
arrival pairing after the 2026-08-18 flight mislabeled every canopy frame (0/18 trees showed).
numpy allowed (ndvi_* module family).
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

from fieldguard_planning.clip_recorder import (  # noqa: E402
    ClipWriter, PoseBuffer, STALE_PAIR_BOUND_S, StreamingClockParser,
)
from fieldguard_planning.coverage import build_grid, load_field_polygon  # noqa: E402
import stitch_ndvi  # noqa: E402

CAM = {"image_width_px": 64, "image_height_px": 48, "fx": 52.0, "fy": 52.0, "cx": 32.0, "cy": 24.0}
IDENTITY_XYZW = (0.0, 0.0, 0.0, 1.0)


class TestStreamingClockParser(unittest.TestCase):
    """The native gz clock stream parser (replaced the bridged /fg/gz_clock topic, which at ~350
    msgs/s starved the image pipeline — measured live 2026-08-18)."""

    def test_full_message_stream(self):
        p = StreamingClockParser()
        lines = ["system {", "  sec: 1", "}", "real {", "  sec: 99", "  nsec: 5", "}",
                 "sim {", "  sec: 123", "  nsec: 500000000", "}", ""]
        out = [t for t in (p.feed(l) for l in lines) if t is not None]
        self.assertEqual(out, [123.5])

    def test_consecutive_messages(self):
        p = StreamingClockParser()
        stream = ["sim {", "  sec: 10", "  nsec: 0", "}", "sim {", "  sec: 11", "  nsec: 250000000", "}"]
        out = [t for t in (p.feed(l) for l in stream) if t is not None]
        self.assertEqual(out, [10.0, 11.25])

    def test_sim_block_without_nsec(self):
        p = StreamingClockParser()
        out = [t for t in (p.feed(l) for l in ["sim {", "  sec: 42", "}"]) if t is not None]
        self.assertEqual(out, [42.0])

    def test_non_sim_blocks_yield_nothing(self):
        p = StreamingClockParser()
        out = [t for t in (p.feed(l) for l in ["real {", "  sec: 9", "}"]) if t is not None]
        self.assertEqual(out, [])


class TestPoseBuffer(unittest.TestCase):
    def test_nearest_picks_closest_gz_tag(self):
        b = PoseBuffer()
        b.tag(10.0, (0, 0, 15), IDENTITY_XYZW)
        b.tag(10.5, (1, 0, 15), IDENTITY_XYZW)
        b.tag(11.0, (2, 0, 15), IDENTITY_XYZW)
        pos, quat, residual = b.nearest(10.6)
        self.assertEqual(pos, (1, 0, 15))
        self.assertAlmostEqual(residual, -0.1)  # tag(10.5) - stamp(10.6): pose from BEFORE frame

    def test_burst_scenario_pairs_old_frame_with_old_pose(self):
        """The exact 2026-08-18 failure: a render burst delivers a frame stamped seconds ago.
        Arrival pairing grabbed the CURRENT pose; stamp pairing must reach back to the pose
        tagged near the frame's render time."""
        b = PoseBuffer()
        for i in range(60):  # drone flying north at 3 m/s, poses tagged every 0.1 sim-s
            b.tag(100.0 + i * 0.1, (15.0, 5.0 + i * 0.3, 15.0), IDENTITY_XYZW)
        # frame rendered at t=101.0 (drone was at y=8.0), arriving late at t=106.0
        pos, _, residual = b.nearest(101.0)
        self.assertAlmostEqual(pos[1], 8.0)         # y at render time, NOT y=23 (current)
        self.assertAlmostEqual(residual, 0.0)

    def test_empty_buffer_returns_none(self):
        self.assertIsNone(PoseBuffer().nearest(1.0))

    def test_maxlen_bounds_memory(self):
        b = PoseBuffer(maxlen=10)
        for i in range(25):
            b.tag(float(i), (i, 0, 15), IDENTITY_XYZW)
        self.assertEqual(len(b), 10)
        self.assertIsNotNone(b.nearest(24.0))


class TestClipWriter(unittest.TestCase):
    def test_written_clip_is_stitchable(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM, mount_offset_body_m=(0.0, 0.0, 0.0))
            ndvi = np.full((48, 64), 0.7, dtype=np.float32)
            w.add_frame(100.0, ndvi, (40.0, 20.0, 15.0), IDENTITY_XYZW, pose_pair_residual_s=0.02)
            w.add_frame(100.2, ndvi, (41.0, 20.0, 15.0), IDENTITY_XYZW, pose_pair_residual_s=0.01)
            summary = w.finalize()
            self.assertEqual(summary["n_frames"], 2)

            grid, stats = stitch_ndvi.stitch_clip(Path(td), build_grid(load_field_polygon()))
            self.assertEqual(stats["frames_total"], 2)
            self.assertFalse(stats["clip_synthetic"])          # the real thing at last
            self.assertEqual(stats["frames_stale_pose_skipped"], [])
            means = grid.mean_grid()
            cell = min(grid.cells, key=lambda c: (c.cx_m - 40.5) ** 2 + (c.cy_m - 20.0) ** 2)
            self.assertAlmostEqual(means[cell.cell_id], 0.7, places=5)

    def test_stale_pose_pair_is_flagged_and_stitch_skips_it(self):
        """A residual beyond bound flags the frame; the stitch must SKIP it, not paint it —
        the exact plausible-but-wrong mode the first real flight produced."""
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            good = np.full((48, 64), 0.2, dtype=np.float32)
            bad = np.full((48, 64), 0.9, dtype=np.float32)   # would poison the mean if painted
            w.add_frame(10.0, good, (40.0, 20.0, 15.0), IDENTITY_XYZW, pose_pair_residual_s=0.05)
            w.add_frame(10.2, bad, (40.0, 20.0, 15.0), IDENTITY_XYZW,
                        pose_pair_residual_s=STALE_PAIR_BOUND_S + 1.0)
            s = w.finalize()
            self.assertEqual(s["n_frames"], 2)

            lines = [json.loads(x) for x in (Path(td) / "poses.jsonl").read_text().splitlines()]
            self.assertNotIn("pose_pair_stale", lines[0])
            self.assertTrue(lines[1]["pose_pair_stale"])
            meta = json.loads((Path(td) / "meta.json").read_text())
            self.assertEqual(meta["num_stale_pose_pairs"], 1)

            grid, stats = stitch_ndvi.stitch_clip(Path(td), build_grid(load_field_polygon()))
            self.assertEqual(stats["frames_stale_pose_skipped"], [1])
            cell = min(grid.cells, key=lambda c: (c.cx_m - 40.0) ** 2 + (c.cy_m - 20.0) ** 2)
            self.assertAlmostEqual(grid.mean_grid()[cell.cell_id], 0.2, places=5)  # only the good frame

    def test_quat_conversion_xyzw_to_wxyz(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            w.add_frame(0.0, np.zeros((48, 64), np.float32),
                        (0.0, 0.0, 15.0), IDENTITY_XYZW, pose_pair_residual_s=0.0)
            w.finalize()
            line = json.loads((Path(td) / "poses.jsonl").read_text().splitlines()[0])
            self.assertEqual(line["drone"]["quat_wxyz"], [1.0, 0.0, 0.0, 0.0])  # w first

    def test_t_s_relative_and_honesty_extras(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            z = np.zeros((48, 64), np.float32)
            w.add_frame(500.0, z, (0, 0, 15.0), IDENTITY_XYZW, pose_pair_residual_s=0.11,
                        frame_age_sim_s=2.5)
            w.add_frame(500.2, z, (1, 0, 15.0), IDENTITY_XYZW, pose_pair_residual_s=-0.02)
            w.finalize()
            lines = [json.loads(s) for s in (Path(td) / "poses.jsonl").read_text().splitlines()]
            self.assertEqual([ln["t_s"] for ln in lines], [0.0, 0.2])
            self.assertEqual(lines[0]["stamp_sim_s"], 500.0)      # absolute stamp kept for audit
            self.assertEqual(lines[0]["pose_pair_residual_s"], 0.11)
            self.assertEqual(lines[0]["frame_age_sim_s"], 2.5)    # burst delay, quantified
            self.assertNotIn("frame_age_sim_s", lines[1])

    def test_nan_residual_serializes_as_null(self):
        """Arrival-fallback mode (no gz clock) has no residual — must be JSON null, never NaN."""
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            w.add_frame(0.0, np.zeros((48, 64), np.float32), (0, 0, 15.0), IDENTITY_XYZW,
                        pose_pair_residual_s=float("nan"))
            w.finalize()
            raw = (Path(td) / "poses.jsonl").read_text()
            self.assertNotIn("NaN", raw)
            line = json.loads(raw.splitlines()[0])
            self.assertIsNone(line["pose_pair_residual_s"])
            self.assertNotIn("pose_pair_stale", line)  # unknowable, not flagged

    def test_rgb_raw_in_flight_png_at_finalize(self):
        """RGB saves as raw .npy per frame (fast path); PNGs appear only at finalize, and the
        raw dir is cleaned away."""
        calls = []
        with tempfile.TemporaryDirectory() as td:
            def stub_png(path, arr):
                Path(path).write_bytes(b"png")
                calls.append((Path(path).name, arr.shape))
            w = ClipWriter(Path(td), CAM, png_writer=stub_png)
            z = np.zeros((48, 64), np.float32)
            w.add_frame(0.0, z, (0, 0, 15.0), IDENTITY_XYZW, 0.0,
                        rgb=np.zeros((48, 64, 3), np.uint8))
            self.assertEqual(calls, [])                                    # nothing during flight
            self.assertTrue((Path(td) / "frames/rgb_raw/frame_000000.npy").exists())
            w.add_frame(0.2, z, (1, 0, 15.0), IDENTITY_XYZW, 0.0)          # no rgb this frame
            s = w.finalize()
            self.assertEqual(s["n_rgb"], 1)
            self.assertEqual(calls, [("frame_000000.png", (48, 64, 3))])   # converted at finalize
            self.assertFalse((Path(td) / "frames/rgb_raw").exists())       # raw cleaned up
            lines = [json.loads(x) for x in (Path(td) / "poses.jsonl").read_text().splitlines()]
            self.assertEqual(lines[0]["rgb_path"], "frames/rgb/frame_000000.png")
            self.assertNotIn("rgb_path", lines[1])

    def test_no_png_writer_skips_rgb(self):
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
            self.assertEqual(meta["pose_pairing"], "gz_clock_stamp")
            self.assertEqual(meta["stale_pair_bound_s"], STALE_PAIR_BOUND_S)
            self.assertEqual(meta["gps_global_origin"]["x"], 1.0)


if __name__ == "__main__":
    unittest.main()
