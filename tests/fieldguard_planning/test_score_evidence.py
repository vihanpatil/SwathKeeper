"""Tests for the eval harness's evidence guards — the three defects the 2026-08-21 ADR-003
real-render re-run exposed, all of which would have written a WRONG number into the record rather
than failing loudly.

1. `score.py` decided ADR-003 on an EMPTY ground truth. The demo take put no bird in the nadir FOV,
   so TP=FP=FN=0; every rate guard yielded 0.000; `decide()` read four zeros as a clean sweep and
   printed "ADOPT (a) NDVI-direct". A rate needs a denominator, so the denominator is checked first.
2. `label_from_sim.py` never derived `range_m` on real clips, so `score.py`'s closest-approach
   lookup fell back to `1e9` for every record and silently redefined the safety-critical per-bird
   -track FNR from "detected before closest approach" to "detected on first sight".
3. `baseline_rgb.py` did an unconditional `d["rgb_path"]`, KeyError-ing on any real clip (they carry
   RGB on a subset only — the demo take: 243 of 454 frames), which killed `run_spike.sh` outright.

stdlib unittest; `sc.read_png` is monkeypatched so no image decoding is needed.
Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "eval"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "spike"))

import baseline_rgb  # noqa: E402
import score  # noqa: E402
import spike_common as sc  # noqa: E402
from label_from_sim import bird_range_m  # noqa: E402

# The shape score.score() returns for an ADOPT-worthy run: the committed seed-42 NDVI-direct numbers
# (ADR-003), with the evidence counts the guard now requires. Every case below starts here so a
# regression that re-opens the vacuous path fails on the difference, not on unrelated drift.
GOOD_A = {"TP": 100, "FP": 125, "FN": 2, "precision": 0.445, "recall": 0.98, "fnr": 0.02,
          "per_bird_track_fnr": 0.0, "birds_with_visible_frames": 3, "visible_bird_frames": 102,
          "label_srcs": {"generator": 102}, "unscoreable_label_frames": 0,
          "ambiguous_label_frames": 0, "per_bird": []}
GOOD_B = {"TP": 102, "FP": 0, "FN": 2, "precision": 1.0, "recall": 0.981, "fnr": 0.019,
          "per_bird_track_fnr": 0.0, "birds_with_visible_frames": 3, "visible_bird_frames": 102,
          "label_srcs": {"generator": 102}, "unscoreable_label_frames": 0,
          "ambiguous_label_frames": 0, "per_bird": []}
# What the demo take actually produced: nothing at all, every rate 0.0.
EMPTY = {"TP": 0, "FP": 0, "FN": 0, "precision": 0.0, "recall": 0.0, "fnr": 0.0,
         "per_bird_track_fnr": 0.0, "birds_with_visible_frames": 0, "visible_bird_frames": 0,
         "label_srcs": {}, "unscoreable_label_frames": 0, "ambiguous_label_frames": 0,
         "per_bird": []}
# What the 2026-08-22 flagship take produced: a real denominator (10 bird-frames, 3/3 birds) whose
# labels described a bird the render never showed — every rate 1.000 from a detector that had in
# fact fired on all three birds.
MODELED_A = dict(GOOD_A, TP=0, FP=22, FN=10, precision=0.0, recall=0.0, fnr=1.0,
                 per_bird_track_fnr=1.0, visible_bird_frames=10,
                 label_srcs={"modeled": 10}, unscoreable_label_frames=10)


class TestDecideRefusesWithoutEvidence(unittest.TestCase):
    def test_empty_ground_truth_no_longer_adopts(self):
        """THE regression. Before 2026-08-21 this exact input printed ADOPT on zero bird-frames."""
        _lines, verdict = score.decide(EMPTY, EMPTY, birds_in_clip=3)
        self.assertIn("EVIDENCE INSUFFICIENT", verdict)
        self.assertNotIn("ADOPT", verdict)

    def test_refusal_names_the_shortfall_not_just_the_refusal(self):
        lines, _verdict = score.decide(EMPTY, EMPTY, birds_in_clip=3)
        self.assertTrue(any("0 visible bird-frames" in l for l in lines), lines)

    def test_partial_bird_coverage_is_refused(self):
        """One bird of three seen is not a per-bird-track FNR of 0.000 — it is one third of a
        measurement. The rates alone cannot tell those apart."""
        one_bird = dict(GOOD_A, birds_with_visible_frames=1)
        _lines, verdict = score.decide(one_bird, GOOD_B, birds_in_clip=3)
        self.assertIn("EVIDENCE INSUFFICIENT", verdict)
        self.assertIn("1 of 3 birds", score.evidence_shortfall(one_bird, 3))

    def test_real_evidence_still_reaches_the_decision_rule(self):
        """The guard must not become a blanket refusal: the committed seed-42 numbers still ADOPT."""
        self.assertIsNone(score.evidence_shortfall(GOOD_A, 3))
        _lines, verdict = score.decide(GOOD_A, GOOD_B, birds_in_clip=3)
        self.assertIn("ADOPT", verdict)

    def test_modeled_labels_are_refused_even_with_a_full_denominator(self):
        """THE 2026-08-22 regression (ADR-003 am. 6). 10 bird-frames, 3/3 birds — the count guard
        passes — and the verdict was still meaningless: the labels were pose_at(stamp - t0), which
        is where the driver ASKED the bird to be, a mean 198 px from where the render put it.
        A rate needs a denominator AND a numerator that measured the same thing."""
        _lines, verdict = score.decide(MODELED_A, GOOD_B, birds_in_clip=3)
        self.assertIn("EVIDENCE INSUFFICIENT", verdict)
        self.assertNotIn("AMBIGUOUS", verdict)   # what it printed before the guard
        shortfall = score.evidence_shortfall(MODELED_A, 3)
        self.assertIn("10 of 10 visible bird-frames", shortfall)
        self.assertIn("modeled", shortfall)

    def test_unknown_provenance_is_refused_the_same_as_modeled(self):
        """A real clip labelled by a pre-2026-08-22 annotator carries no provenance at all. Unknown
        timing scores exactly as badly as known-wrong timing — fail closed, not open."""
        unknown = dict(MODELED_A, label_srcs={"unknown": 10})
        self.assertIn("unknown", score.evidence_shortfall(unknown, 3))

    def test_measured_and_exact_provenance_still_decide(self):
        """The guard must not become a blanket refusal: applied (measured), spawn (exact) and
        generator (synthetic) labels all support a rate."""
        for src in ("applied", "spawn", "generator"):
            with self.subTest(src=src):
                m = dict(GOOD_A, label_srcs={src: 102}, unscoreable_label_frames=0)
                self.assertIsNone(score.evidence_shortfall(m, 3))
                self.assertIn("ADOPT", score.decide(m, GOOD_B, birds_in_clip=3)[1])

    def test_a_mixed_clip_is_refused_on_the_modelled_part(self):
        mixed = dict(GOOD_A, label_srcs={"applied": 100, "modeled": 2},
                     unscoreable_label_frames=2)
        self.assertIn("2 of 102", score.evidence_shortfall(mixed, 3))

    def test_provenance_counts_come_out_of_score_itself(self):
        """The guard is only as good as the tally feeding it: score() must read label_src off the
        GT boxes it actually scored, not be told."""
        gt_by_fid = {
            0: {"frame_id": 0, "t_s": 0.0,
                "birds": [{"bird_id": "b0", "bbox": [10, 10, 20, 20], "visible": True,
                           "range_m": 9.0, "label_src": "modeled"},
                          {"bird_id": "b1", "bbox": [30, 30, 40, 40], "visible": True,
                           "range_m": 8.0, "label_src": "applied", "label_ambiguous": True},
                          # not visible -> not scored -> must not enter the tally
                          {"bird_id": "b2", "bbox": None, "visible": False, "range_m": None,
                           "label_src": "modeled"}]},
        }
        m = score.score(gt_by_fid, [], iou_thresh=0.3)
        self.assertEqual(m["label_srcs"], {"modeled": 1, "applied": 1})
        self.assertEqual(m["unscoreable_label_frames"], 1)
        self.assertEqual(m["ambiguous_label_frames"], 1)

    def test_legacy_ground_truth_without_the_key_still_scores(self):
        """Committed synthetic GT predates label_src; treating its absence as unscoreable would
        retroactively void the seed-42 numbers ADR-003 was decided on."""
        gt_by_fid = {0: {"frame_id": 0, "t_s": 0.0,
                         "birds": [{"bird_id": "b", "bbox": [0, 0, 10, 10], "visible": True,
                                    "range_m": 5.0}]}}
        m = score.score(gt_by_fid, [{"frame_id": 0, "boxes": [[0, 0, 10, 10]]}], iou_thresh=0.3)
        self.assertEqual(m["unscoreable_label_frames"], 0)

    def test_evidence_counts_come_out_of_score_itself(self):
        """The guard is only as good as the counts feeding it — pin that score() emits them."""
        gt_by_fid = {
            0: {"frame_id": 0, "t_s": 0.0,
                "birds": [{"bird_id": "bird_0", "bbox": [10, 10, 20, 20], "visible": True,
                           "range_m": 9.0},
                          {"bird_id": "bird_1", "bbox": None, "visible": False, "range_m": None}]},
            1: {"frame_id": 1, "t_s": 1.0,
                "birds": [{"bird_id": "bird_0", "bbox": [12, 12, 22, 22], "visible": True,
                           "range_m": 7.0}]},
        }
        m = score.score(gt_by_fid, [{"frame_id": 0, "boxes": [[10, 10, 20, 20]]}], iou_thresh=0.3)
        self.assertEqual(m["birds_with_visible_frames"], 1)   # bird_1 never visible
        self.assertEqual(m["visible_bird_frames"], 2)


class TestBirdRangeDerivation(unittest.TestCase):
    def test_recorded_range_wins(self):
        """The synthetic generator writes range_m; deriving over it would silently change the
        meaning of every committed seed-42 number."""
        bird = {"pos_m": [0.0, 0.0, 0.0], "range_m": 42.0}
        self.assertEqual(bird_range_m(bird, (100.0, 100.0, 100.0)), 42.0)

    def test_derived_when_absent(self):
        bird = {"pos_m": [3.0, 4.0, 0.0]}          # 3-4-5 triangle from the camera
        self.assertAlmostEqual(bird_range_m(bird, (0.0, 0.0, 0.0)), 5.0, places=6)

    def test_derived_range_makes_closest_approach_mean_closest_approach(self):
        """The end-to-end point of fix 2: with real ranges, score() picks the CLOSEST frame as
        closest approach. With the old all-None ranges it picked the FIRST frame, so a detector that
        first saw a bird only on the way out still scored 'detected before closest approach'."""
        gt_by_fid = {
            0: {"frame_id": 0, "t_s": 0.0,
                "birds": [{"bird_id": "b", "bbox": [0, 0, 10, 10], "visible": True,
                           "range_m": bird_range_m({"pos_m": [0.0, 0.0, 0.0]}, (0.0, 0.0, 30.0))}]},
            1: {"frame_id": 1, "t_s": 1.0,
                "birds": [{"bird_id": "b", "bbox": [0, 0, 10, 10], "visible": True,
                           "range_m": bird_range_m({"pos_m": [0.0, 0.0, 0.0]}, (0.0, 0.0, 5.0))}]},
        }
        # Detected ONLY on frame 1 (the closest-approach frame): the bird was missed on approach.
        m = score.score(gt_by_fid, [{"frame_id": 1, "boxes": [[0, 0, 10, 10]]}], iou_thresh=0.3)
        self.assertEqual(m["per_bird"][0]["closest_range_m"], 5.0)
        # Detected on frame 0, before closest approach at frame 1: the safe case.
        m2 = score.score(gt_by_fid, [{"frame_id": 0, "boxes": [[0, 0, 10, 10]]}], iou_thresh=0.3)
        self.assertTrue(m2["per_bird"][0]["detected_before_closest"])


class TestRgbArmSurvivesPartialRgbClips(unittest.TestCase):
    def setUp(self):
        self._real_read_png = sc.read_png
        sc.read_png = lambda path: __import__("numpy").zeros((4, 4, 3), dtype="uint8")
        self.addCleanup(lambda: setattr(sc, "read_png", self._real_read_png))

    def _clip(self, poses):
        d = Path(tempfile.mkdtemp())
        (d / "poses.jsonl").write_text("".join(json.dumps(p) + "\n" for p in poses))
        return d

    def test_frames_without_rgb_are_skipped_not_a_keyerror(self):
        """Real clips carry RGB on a subset; the unconditional lookup killed run_spike.sh."""
        clip = self._clip([{"frame_id": 0, "rgb_path": "frames/rgb/frame_000000.png"},
                           {"frame_id": 1},
                           {"frame_id": 2, "rgb_path": "frames/rgb/frame_000002.png"}])
        frames, skipped = baseline_rgb.run(clip, thresh=110, min_area=6, max_area=5000)
        self.assertEqual([f["frame_id"] for f in frames], [0, 2])
        self.assertEqual(skipped, [1])

    def test_full_rgb_clip_skips_nothing(self):
        clip = self._clip([{"frame_id": i, "rgb_path": f"frames/rgb/frame_{i:06d}.png"}
                           for i in range(3)])
        frames, skipped = baseline_rgb.run(clip, thresh=110, min_area=6, max_area=5000)
        self.assertEqual(len(frames), 3)
        self.assertEqual(skipped, [])


if __name__ == "__main__":
    unittest.main()
