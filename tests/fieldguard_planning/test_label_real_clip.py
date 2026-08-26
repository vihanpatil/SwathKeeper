"""Tests for eval/label_from_sim.py's oriented projection path (real recorded clips).

Real clips carry only the yawing drone pose, so GT projection must handle full orientation. Rather
than a second set of hand fixtures, these tests pin CONSISTENCY with the two already-trusted
implementations: (1) at identity attitude + zero offset the oriented projector must equal
spike_common.project_bird (the fixed-extrinsic spike model — same camera, same convention), and
(2) at ARBITRARY attitude its (u, v) must equal ndvi_georef.world_enu_to_pixel (the hand-fixture-
tested transform the heatmap stitch uses) — one camera model across GT labels and the map.
numpy allowed (eval family).
"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "eval"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "spike"))

import label_from_sim  # noqa: E402
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


# --------------------------------------------------------------------------------------
# The overlay stills (--overlay-frames / --overlay-detections)
# --------------------------------------------------------------------------------------
# These figures leave the repo -- they go in a README and a demo video -- so they are the one
# artifact a reader judges by eye instead of by a metric, and the eye cannot check provenance.
# What is pinned here is exactly the part a picture cannot show: that the frames drawn are the
# frames asked for, that a still with no box says so out loud, and that a detections file from
# ANOTHER clip is refused rather than drawn (a box near a bird looks equally convincing either way).
OVL_W, OVL_H = 64, 48
OVL_INTR = {"fx": 100.0, "fy": 100.0, "cx": 32.0, "cy": 24.0,
            "image_width_px": OVL_W, "image_height_px": OVL_H}
CAM_POS = [0.0, 0.0, 10.0]
BIRD_IN_VIEW = [0.0, 0.0, 8.0]      # straight below the camera -> box centred, r = fx*R/Zc = 10 px
BIRD_OFF_IMAGE = [100.0, 0.0, 8.0]  # same depth, 5000 px off-axis -> clipped out, visible=False


def _write_overlay_clip(clip_dir: Path, frames):
    """Minimal legacy-extrinsic spike clip. `frames` = [(frame_id, bird_world_pos, range_m)]."""
    (clip_dir / "frames" / "ndvi").mkdir(parents=True, exist_ok=True)
    (clip_dir / "frames" / "rgb").mkdir(parents=True, exist_ok=True)
    (clip_dir / "meta.json").write_text(json.dumps({
        "synthetic": True, "seed": 1, "image_width_px": OVL_W, "image_height_px": OVL_H,
        "camera": OVL_INTR}))
    lines = []
    for fid, pos, rng in frames:
        np.save(clip_dir / "frames" / "ndvi" / f"frame_{fid:06d}.npy",
                np.zeros((OVL_H, OVL_W), dtype=np.float32))
        sc.write_png(clip_dir / "frames" / "rgb" / f"frame_{fid:06d}.png",
                     np.zeros((OVL_H, OVL_W, 3), dtype=np.uint8))
        lines.append(json.dumps({
            "frame_id": fid, "t_s": 0.2 * fid, "camera": {"pos_m": CAM_POS},
            "ndvi_path": f"frames/ndvi/frame_{fid:06d}.npy",
            "rgb_path": f"frames/rgb/frame_{fid:06d}.png",
            "birds": [{"bird_id": "bird_0", "pos_m": pos, "physical_radius_m": 0.2,
                       "range_m": rng}]}))
    (clip_dir / "poses.jsonl").write_text("\n".join(lines) + "\n")


def _run_label(argv):
    """Run label_from_sim.main() with argv; returns (stdout, stderr). Raises SystemExit through."""
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(sys, "argv", ["label_from_sim.py"] + argv):
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            label_from_sim.main()
    return out.getvalue(), err.getvalue()


def _has_color(png_path: Path, color):
    img = sc.read_png(png_path)
    return bool(np.any(np.all(img == np.array(color, dtype=np.uint8), axis=-1)))


class TestOverlayStills(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.clip = self.tmp / "clip"
        # frame 1 is the closest approach; 0 and 2 also show the bird; 3 has it off-image.
        _write_overlay_clip(self.clip, [(0, BIRD_IN_VIEW, 3.0), (1, BIRD_IN_VIEW, 2.0),
                                        (2, BIRD_IN_VIEW, 4.0), (3, BIRD_OFF_IMAGE, 9.0)])
        self.overlay = self.tmp / "overlays"
        self.gt_out = self.tmp / "gt.json"
        self.addCleanup(self._tmp.cleanup)

    def _base_argv(self):
        return ["--clip", str(self.clip), "--out", str(self.gt_out),
                "--overlay", str(self.overlay)]

    def _write_detections(self, path, clip, approach="a_ndvi_direct", frames=None):
        path.write_text(json.dumps({
            "approach": approach, "clip": str(clip),
            "frames": frames if frames is not None else [
                {"frame_id": 0, "boxes": [[20.0, 12.0, 44.0, 36.0]]},
                {"frame_id": 2, "boxes": [[21.0, 13.0, 43.0, 35.0]]}]}))

    def test_default_pick_is_still_closest_approach_per_bird(self):
        """Regression pin: --overlay-frames must not change what plain --overlay does."""
        _run_label(self._base_argv())
        self.assertEqual(sorted(p.name for p in self.overlay.iterdir()),
                         ["gt_ndvi_frame_000001.png", "gt_rgb_frame_000001.png"])

    def test_overlay_frames_writes_exactly_the_frames_asked_for(self):
        """The 2026-08-25 take's whole encounter is 2 frames; the default pick shows ONE of them."""
        _run_label(self._base_argv() + ["--overlay-frames", "0", "2"])
        self.assertEqual(sorted(p.name for p in self.overlay.iterdir()),
                         ["gt_ndvi_frame_000000.png", "gt_ndvi_frame_000002.png",
                          "gt_rgb_frame_000000.png", "gt_rgb_frame_000002.png"])
        for name in ("gt_ndvi_frame_000000.png", "gt_rgb_frame_000000.png"):
            self.assertTrue(_has_color(self.overlay / name, label_from_sim.GT_COLOR), name)

    def test_unknown_overlay_frame_is_refused_not_silently_dropped(self):
        """A shorter set of figures than requested is how a missing frame becomes an unnoticed
        editorial choice. Ask for 4 frames, get 4 or an error."""
        with self.assertRaises(SystemExit) as ctx:
            _run_label(self._base_argv() + ["--overlay-frames", "0", "9999"])
        self.assertIn("9999", str(ctx.exception))
        self.assertFalse(self.overlay.exists() and any(self.overlay.iterdir()))

    def test_frame_with_no_visible_bird_is_named_on_stderr(self):
        """A bare frame is exactly what the 2026-08-21 'EVIDENCE INSUFFICIENT' run would emit."""
        _, err = _run_label(self._base_argv() + ["--overlay-frames", "3"])
        self.assertIn("NO visible GT box", err)
        self.assertIn("[3]", err)
        self.assertFalse(_has_color(self.overlay / "gt_ndvi_frame_000003.png",
                                    label_from_sim.GT_COLOR))

    def test_detections_overlay_is_arm_tagged_and_leaves_the_gt_still_clean(self):
        det = self.tmp / "detections_ndvi.json"
        self._write_detections(det, self.clip)
        out, _ = _run_label(self._base_argv() + ["--overlay-frames", "0",
                                                 "--overlay-detections", str(det)])
        gtdet_ndvi = self.overlay / "gtdet_a_ndvi_direct_ndvi_frame_000000.png"
        gtdet_rgb = self.overlay / "gtdet_a_ndvi_direct_rgb_frame_000000.png"
        self.assertTrue(gtdet_ndvi.exists() and gtdet_rgb.exists())
        self.assertIn("gtdet_a_ndvi_direct", out)
        for p in (gtdet_ndvi, gtdet_rgb):
            self.assertTrue(_has_color(p, label_from_sim.DET_COLOR), p.name)
            self.assertTrue(_has_color(p, label_from_sim.GT_COLOR), p.name)
        # ...and the plain GT still stays a GT still: one file, one question.
        self.assertFalse(_has_color(self.overlay / "gt_ndvi_frame_000000.png",
                                    label_from_sim.DET_COLOR))

    def test_detections_from_another_clip_are_refused(self):
        """The failure this exists for: a box near a bird is equally convincing whichever run's
        detections drew it, so the pairing has to be checked by the tool, not by the reader."""
        det = self.tmp / "detections_other.json"
        self._write_detections(det, self.tmp / "some_other_clip")
        with self.assertRaises(SystemExit) as ctx:
            _run_label(self._base_argv() + ["--overlay-frames", "0",
                                            "--overlay-detections", str(det)])
        self.assertIn("some_other_clip", str(ctx.exception))
        # Refused before anything was drawn -- no half-written figure set to mistake for evidence.
        self.assertEqual([], list(self.overlay.glob("*")) if self.overlay.exists() else [])

    def test_arm_id_separates_the_two_arms_on_the_same_frame(self):
        """Both baselines detect into the SAME image space, so the filename is the only thing that
        says which detector drew the cyan box."""
        det_a = self.tmp / "det_a.json"
        det_b = self.tmp / "det_b.json"
        self._write_detections(det_a, self.clip, approach="a_ndvi_direct")
        self._write_detections(det_b, self.clip, approach="b_synthetic_rgb")
        for det in (det_a, det_b):
            _run_label(self._base_argv() + ["--overlay-frames", "0",
                                            "--overlay-detections", str(det)])
        names = {p.name for p in self.overlay.iterdir()}
        self.assertIn("gtdet_a_ndvi_direct_ndvi_frame_000000.png", names)
        self.assertIn("gtdet_b_synthetic_rgb_ndvi_frame_000000.png", names)


if __name__ == "__main__":
    unittest.main()
