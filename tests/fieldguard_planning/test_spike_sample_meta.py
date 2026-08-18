"""`sim/spike/sample/`'s meta.json must describe the frames that are actually in it.

The fixture shipped 640x480 intrinsics (fx=fy=520, cx=320, cy=240) on top of 160x120 frames, so its
principal point sat outside its own image. Every pixel back-projected into a ground footprint that
doesn't exist, and `scripts/stitch_ndvi.py` rejects the clip at load rather than "succeeding" with
an empty heatmap (that guard stays -- these tests pin that the SAMPLE no longer trips it).
2026-08-18 audit item 24; the 640x480 `sim/spike/out/spike_seed42` clip was already self-consistent
and is deliberately untouched.

Deliberately stdlib-only (no numpy): frame dimensions are read straight out of the PNG IHDR chunk,
so this stays runnable in a bare interpreter.

Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import json
import struct
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = REPO_ROOT / "sim" / "spike" / "sample"
META = SAMPLE / "meta.json"
SCENARIO = SAMPLE / "scenario.json"


def png_size(path: Path):
    """(width, height) from the IHDR chunk -- bytes 16..24 of any valid PNG."""
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path} is not a PNG"
    return struct.unpack(">II", head[16:24])


class TestSampleClipIntrinsics(unittest.TestCase):
    def setUp(self):
        self.meta = json.loads(META.read_text())
        self.cam = self.meta["camera"]

    def test_declared_size_matches_the_actual_frames(self):
        for png in sorted((SAMPLE / "frames" / "rgb").glob("frame_*.png")):
            self.assertEqual(png_size(png),
                             (self.cam["image_width_px"], self.cam["image_height_px"]),
                             msg=f"{png.name} does not match meta.json's declared image size")

    def test_camera_block_agrees_with_top_level_size(self):
        self.assertEqual(self.cam["image_width_px"], self.meta["image_width_px"])
        self.assertEqual(self.cam["image_height_px"], self.meta["image_height_px"])

    def test_principal_point_lies_inside_the_image(self):
        """The exact condition scripts/stitch_ndvi.py refuses to load a clip on."""
        self.assertTrue(0.0 < self.cam["cx"] < self.cam["image_width_px"],
                        msg=f"cx={self.cam['cx']} outside 0..{self.cam['image_width_px']}")
        self.assertTrue(0.0 < self.cam["cy"] < self.cam["image_height_px"],
                        msg=f"cy={self.cam['cy']} outside 0..{self.cam['image_height_px']}")

    def test_intrinsics_are_the_scenario_values_scaled_by_the_resolution_ratio(self):
        """Pins HOW they were fixed: a uniform 1/4 downscale of scenario.json's 640x480 intrinsics,
        not hand-invented numbers. Regenerating the fixture at another size must rescale too."""
        src = json.loads(SCENARIO.read_text())["camera"]
        ratio = self.cam["image_width_px"] / src["image_width_px"]
        self.assertAlmostEqual(ratio, self.cam["image_height_px"] / src["image_height_px"], places=9)
        for k in ("fx", "fy", "cx", "cy"):
            self.assertAlmostEqual(self.cam[k], src[k] * ratio, places=6,
                                   msg=f"{k}={self.cam[k]} is not {src[k]} * {ratio}")
        self.assertEqual((self.cam["fx"], self.cam["fy"], self.cam["cx"], self.cam["cy"]),
                         (130.0, 130.0, 80.0, 60.0))

    def test_the_rescale_is_documented_in_the_file(self):
        """The frames were rendered with the pre-rescale intrinsics; the note is what stops the next
        reader from treating this fixture's absolute georeferencing as authoritative."""
        self.assertIn("gen_spike_clip.py", self.meta["intrinsics_note"])


if __name__ == "__main__":
    unittest.main()
