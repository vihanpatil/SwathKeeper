"""Tests for eval/baseline_ndvi.py's per-render NDVI threshold (ADR-003 amendment 1 recalibration).

The threshold is the whole detector: `mask = ndvi < thresh`. ADR-003's 0.05 was chosen below the
SYNTHETIC spike's soil (+0.15); the real Gazebo render's soil sits at -0.4377, so on a real clip
that same 0.05 passes every pixel, yields one whole-image component, and the area filter throws it
away -- zero detections from a detector that looked like it ran. These tests pin the two things
that keeps honest:

  1. the synthetic path still uses the number ADR-003 was DECIDED on (0.05) -- the spike stays
     reproducible, which `scripts/check_spike_regression.py` depends on;
  2. the real-render number is the midpoint of the bird and soil classes as MEASURED in the
     committed evidence (`eval/results/gate2_summary.json`), recomputed here rather than trusted --
     so the constant in the source can never quietly drift away from the file it came from.

Stdlib only (the threshold logic does not touch pixels; numpy/scipy are not imported).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "eval"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "spike"))

GATE2 = REPO_ROOT / "eval" / "results" / "gate2_summary.json"
DEMO_CLIP = REPO_ROOT / "eval" / "results" / "clips" / "real_flight_20260821T045848Z"
SPIKE_SAMPLE = REPO_ROOT / "sim" / "spike" / "sample"


def baseline_ndvi():
    """Import the module, skipping if the eval extras (numpy/scipy) are not installed on this host
    -- the threshold logic is stdlib, but the module it lives in reads pixels."""
    try:
        import baseline_ndvi
    except ImportError as exc:  # pragma: no cover - host without requirements-eval.txt
        raise unittest.SkipTest(f"eval harness unavailable: {exc}")
    return baseline_ndvi


class TestRealRenderThresholdComesFromTheEvidence(unittest.TestCase):
    def test_is_the_gate2_bird_soil_midpoint(self):
        """-0.61 is not a taste call: it is (bird + soil)/2 from the 996-frame real-render band
        measurement. Recomputed from the committed file, so editing one without the other fails."""
        bn = baseline_ndvi()
        classes = json.loads(GATE2.read_text())["classes"]
        bird = classes["bird"]["mean_proxy_ndvi"]
        soil = classes["soil"]["mean_proxy_ndvi"]
        self.assertAlmostEqual(bird, -0.7888, delta=0.001)
        self.assertAlmostEqual(soil, -0.4285, delta=0.001)
        self.assertAlmostEqual(bn.REAL_RENDER_THRESH, (bird + soil) / 2.0, delta=0.01)

    def test_separates_bird_from_soil_where_the_old_threshold_saturated(self):
        """The actual defect, in one assertion. Against the real render's measured modal soil cell
        (-0.437687, 311 of 410 imaged cells in the demo take's committed heatmap), the synthetic
        0.05 puts SOIL on the bird side of the mask -- everything is a candidate. The gate2 midpoint
        puts soil outside and the bird inside, which is what a threshold is for."""
        bn = baseline_ndvi()
        cells = json.loads((DEMO_CLIP / "heatmap" / "heatmap.json").read_text())["cells"]
        values = [c["mean_ndvi"] for c in cells if c["mean_ndvi"] is not None]
        modal_soil = max(set(values), key=values.count)
        bird = json.loads(GATE2.read_text())["classes"]["bird"]["mean_proxy_ndvi"]

        self.assertAlmostEqual(modal_soil, -0.437687, places=6)
        self.assertLess(modal_soil, bn.SYNTHETIC_THRESH)          # old: soil masked IN -> saturation
        self.assertGreater(modal_soil, bn.REAL_RENDER_THRESH)     # new: soil masked OUT
        self.assertLess(bird, bn.REAL_RENDER_THRESH)              # new: bird still masked IN

    def test_stays_flagged_provisional(self):
        """It is calibrated on pixel-class means, not on precision/recall -- there is still no real
        clip with a bird in frame to score against. If this word ever disappears from the module,
        someone has promoted an unverified number, and that is the failure ADR-003 am. 1 is about."""
        bn = baseline_ndvi()
        self.assertIn("PROVISIONAL", Path(bn.__file__).read_text())
        _, source = bn.resolve_threshold(DEMO_CLIP, None)
        self.assertIn("PROVISIONAL", source)


class TestThresholdResolution(unittest.TestCase):
    def test_synthetic_clip_keeps_the_adr_003_deciding_value(self):
        bn = baseline_ndvi()
        thresh, source = bn.resolve_threshold(SPIKE_SAMPLE, None)
        self.assertEqual(thresh, 0.05)
        self.assertEqual(thresh, bn.SYNTHETIC_THRESH)
        self.assertIn("synthetic", source)

    def test_real_clip_gets_the_real_render_value(self):
        bn = baseline_ndvi()
        thresh, _ = bn.resolve_threshold(DEMO_CLIP, None)
        self.assertEqual(thresh, bn.REAL_RENDER_THRESH)

    def test_explicit_thresh_always_wins(self):
        bn = baseline_ndvi()
        for clip in (SPIKE_SAMPLE, DEMO_CLIP):
            thresh, source = bn.resolve_threshold(clip, -0.2)
            self.assertEqual(thresh, -0.2)
            self.assertIn("explicit", source)

    def test_refuses_a_clip_that_does_not_declare_its_render(self):
        """Half a unit apart in either direction: guessing produces a run that detects nothing (or
        everything) and reports no problem at all."""
        bn = baseline_ndvi()
        with tempfile.TemporaryDirectory() as td:
            clip = Path(td)
            (clip / "meta.json").write_text(json.dumps({"image_width_px": 640}))
            with self.assertRaises(ValueError) as ctx:
                bn.resolve_threshold(clip, None)
            self.assertIn("--thresh", str(ctx.exception))
            # ... and with no meta.json at all, same refusal rather than a silent default
            (clip / "meta.json").unlink()
            with self.assertRaises(ValueError):
                bn.resolve_threshold(clip, None)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
