"""Tests for scripts/stitch_ndvi.py -- the offline heatmap stitch runner (Weeks 5-6 exit
criterion 1's producer).

The georef math itself is fixture-tested in test_ndvi_georef.py; what THESE tests pin is the
runner's plumbing, where the audit-identified failure modes live:
  1. the poses.jsonl wxyz -> georef xyzw quaternion conversion (one wrong index = a map mirrored
     about the flight line that "looks plausible"),
  2. per-frame accumulation onto the canonical grid (right cells, right means, unimaged cells
     explicitly None),
  3. the no-silent-empty-stitch guards (empty clip / nothing imaged / inconsistent meta must
     raise, never exit 0 with a blank map).

Fixture design: nadir camera at 15 m with fx=fy=52, cx=32, cy=24 (64x48 frames) -> the ground
half-footprint along x is (cx/fx)*z = (32/52)*15 = 9.23 m, so single frames dropped at
x = 10 / 40 / 70 (y=20) have non-overlapping footprints and each canonical 2.5 m cell under a
frame center samples EXACTLY one frame -> its mean equals that frame's constant NDVI, no
averaging ambiguity in the assertion.

numpy allowed here (ndvi_* test, requirements-eval.txt) -- same policy as test_ndvi_fusion.py.
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

from fieldguard_planning.coverage import build_grid, load_field_polygon  # noqa: E402
import stitch_ndvi  # noqa: E402

W, H = 64, 48
FX = FY = 52.0
CX, CY = 32.0, 24.0
ALT = 15.0
IDENTITY_WXYZ = [1.0, 0.0, 0.0, 0.0]


def _write_clip(clip_dir: Path, frames):
    """frames: list of (pos_xyz, quat_wxyz, ndvi_array). Emits the minimal spike-schema subset
    the runner consumes (meta.json camera block + poses.jsonl + frames/ndvi/*.npy)."""
    (clip_dir / "frames" / "ndvi").mkdir(parents=True)
    meta = {
        "synthetic": True, "seed": 0,
        "camera": {"image_width_px": W, "image_height_px": H,
                   "fx": FX, "fy": FY, "cx": CX, "cy": CY},
        "camera_extrinsic": {"offset_from_drone_m": [0.0, 0.0, 0.0]},
    }
    (clip_dir / "meta.json").write_text(json.dumps(meta))
    lines = []
    for k, (pos, quat_wxyz, ndvi) in enumerate(frames):
        rel = f"frames/ndvi/frame_{k:06d}.npy"
        np.save(clip_dir / rel, ndvi.astype(np.float32))
        lines.append(json.dumps({
            "frame_id": k, "t_s": float(k),
            "drone": {"pos_m": list(pos), "quat_wxyz": list(quat_wxyz)},
            "ndvi_path": rel,
        }))
    (clip_dir / "poses.jsonl").write_text("\n".join(lines) + "\n")


def _const(v):
    return np.full((H, W), v, dtype=np.float32)


def _cells():
    return build_grid(load_field_polygon())  # the canonical 2.5 m / 720-cell grid


def _mean_at(grid, x, y):
    """Mean NDVI of the canonical cell whose center is nearest (x, y)."""
    means = grid.mean_grid()
    cell = min(grid.cells, key=lambda c: (c.cx_m - x) ** 2 + (c.cy_m - y) ** 2)
    return means[cell.cell_id]


class TestStitchClip(unittest.TestCase):
    def test_disjoint_frames_stitch_to_their_own_cells(self):
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td)
            _write_clip(clip, [
                ((10.0, 20.0, ALT), IDENTITY_WXYZ, _const(0.8)),   # healthy canopy patch
                ((40.0, 20.0, ALT), IDENTITY_WXYZ, _const(0.4)),   # stressed patch
                ((70.0, 20.0, ALT), IDENTITY_WXYZ, _const(-0.2)),  # bare soil patch
            ])
            grid, stats = stitch_ndvi.stitch_clip(clip, _cells())
            # each frame's constant lands (exactly, no cross-frame averaging: footprints disjoint)
            self.assertAlmostEqual(_mean_at(grid, 10.0, 20.0), 0.8, places=5)
            self.assertAlmostEqual(_mean_at(grid, 40.0, 20.0), 0.4, places=5)
            self.assertAlmostEqual(_mean_at(grid, 70.0, 20.0), -0.2, places=5)
            # a cell no footprint reached is EXPLICITLY None (ledger discipline), never a number
            self.assertIsNone(_mean_at(grid, 110.0, 37.0))
            self.assertEqual(stats["frames_total"], 3)
            self.assertEqual(stats["frames_zero_update"], [])
            self.assertGreater(stats["cells_unimaged"], 0)

    def test_gradient_frame_orients_east(self):
        """Catches the two plumbing bugs a constant frame cannot: a wxyz/xyzw mix-up or an
        axis-sign error mirrors the image, so the east-of-drone cell would read the LOW end of a
        u-gradient instead of the high end. Identity heading => body X = East = camera X (u+):
        NDVI rising with pixel column u must put higher values on the EAST side of the drone."""
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td)
            gradient = np.tile(np.linspace(-0.5, 0.5, W, dtype=np.float32), (H, 1))
            _write_clip(clip, [((40.0, 20.0, ALT), IDENTITY_WXYZ, gradient)])
            grid, _ = stitch_ndvi.stitch_clip(clip, _cells())
            east = _mean_at(grid, 45.0, 20.0)   # +5 m East of the drone
            west = _mean_at(grid, 35.0, 20.0)   # -5 m
            self.assertIsNotNone(east)
            self.assertIsNotNone(west)
            self.assertGreater(east, 0.0)
            self.assertLess(west, 0.0)

    def test_zero_update_frame_is_counted_not_hidden(self):
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td)
            _write_clip(clip, [
                ((40.0, 20.0, ALT), IDENTITY_WXYZ, _const(0.5)),
                ((-500.0, -500.0, ALT), IDENTITY_WXYZ, _const(0.5)),  # images nothing in-field
            ])
            _, stats = stitch_ndvi.stitch_clip(clip, _cells())
            self.assertEqual(stats["frames_zero_update"], [1])

    # -- no-silent-empty-stitch guards ---------------------------------------
    def test_empty_clip_raises(self):
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td)
            _write_clip(clip, [((40.0, 20.0, ALT), IDENTITY_WXYZ, _const(0.5))])
            (clip / "poses.jsonl").write_text("")
            with self.assertRaises(ValueError):
                stitch_ndvi.stitch_clip(clip, _cells())

    def test_nothing_imaged_raises(self):
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td)
            _write_clip(clip, [((-500.0, -500.0, ALT), IDENTITY_WXYZ, _const(0.5))])
            with self.assertRaises(ValueError):
                stitch_ndvi.stitch_clip(clip, _cells())

    def test_inconsistent_meta_intrinsics_raise(self):
        """General clip-validity guard (originally found via a broken sim/spike/sample): a principal point outside the image would stitch
        every frame out of bounds and 'succeed' empty -- must be rejected at load."""
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td)
            _write_clip(clip, [((40.0, 20.0, ALT), IDENTITY_WXYZ, _const(0.5))])
            meta = json.loads((clip / "meta.json").read_text())
            meta["camera"]["cx"] = 320.0  # authored for 640-wide, image is 64-wide
            (clip / "meta.json").write_text(json.dumps(meta))
            with self.assertRaises(ValueError):
                stitch_ndvi.stitch_clip(clip, _cells())

    def test_frame_shape_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td)
            _write_clip(clip, [((40.0, 20.0, ALT), IDENTITY_WXYZ,
                                np.zeros((H + 1, W), dtype=np.float32))])
            with self.assertRaises(ValueError):
                stitch_ndvi.stitch_clip(clip, _cells())

    # -- end-to-end CLI -------------------------------------------------------
    def test_main_writes_artifacts_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td) / "clip"
            clip.mkdir()
            _write_clip(clip, [((40.0, 20.0, ALT), IDENTITY_WXYZ, _const(0.6))])
            out = Path(td) / "out"
            rc = stitch_ndvi.main(["--clip", str(clip), "--out", str(out)])
            self.assertEqual(rc, 0)
            doc = json.loads((out / "heatmap.json").read_text())
            self.assertEqual(doc["cells_total"], 720)          # canonical grid
            self.assertEqual(len(doc["cells"]), 720)
            imaged = [c for c in doc["cells"] if c["mean_ndvi"] is not None]
            self.assertEqual(len(imaged), doc["cells_imaged"])
            self.assertTrue(all(abs(c["mean_ndvi"] - 0.6) < 1e-5 for c in imaged))
            self.assertTrue((out / "heatmap.png").exists())
            self.assertGreater((out / "heatmap.png").stat().st_size, 100)

    def test_main_exits_one_on_empty_stitch(self):
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td) / "clip"
            clip.mkdir()
            _write_clip(clip, [((-500.0, -500.0, ALT), IDENTITY_WXYZ, _const(0.5))])
            rc = stitch_ndvi.main(["--clip", str(clip)])
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
