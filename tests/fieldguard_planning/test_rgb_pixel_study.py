"""Regression pins for ADR-003 criterion 2's RGB arm (eval/baseline_rgb.py + eval/rgb_pixel_study.py).

The arm was measured-invalid for 4 days ("bright + achromatic" is false on this world) and its
1.000 FNR was quoted nowhere as RGB's ceiling only because a docstring said not to. What replaces
that docstring is evidence: eval/results/criterion2_rgb_study_*/results.json, 4,566 frames /
1.4027 Gpx / 16,686 bird pixels over 3 birds at 3 depths. These tests pin the four things in that
study a future edit could silently invalidate:

  1. PROVENANCE -- the real-render threshold is RECOMPUTED here from the study's own class means,
     exactly as test_ndvi_detect recomputes -0.61 from gate2_summary.json. A constant whose
     evidence file no longer implies it is a number someone typed.
  2. THE SYNTHETIC ARM IS UNTOUCHED -- ADR-003 was DECIDED on min-channel > 110 (precision 1.000).
     Adding a second render's birdness must not move the deciding run by one box.
  3. THE STRUCTURAL FINDING -- on this world the tree trunk is MORE bird-like in RGB than the most
     bird-like bird pixel. That is why (b)'s precision cannot be recovered by tightening the
     threshold, and why criterion 2's answer is what it is. If it ever stops being true the
     recommendation needs revisiting, so it fails loudly rather than ageing quietly.
  4. THE ARM IS NOT A SECOND SENSOR -- NDVI's Red band IS this RGB image's R channel (ADR-007), so
     the arm shares band, sensor, optics, mount and frame clock with the primary one and cannot buy
     range or lead time. If someone ever gives the RGB camera its own aperture, this test goes red
     and says so.

numpy is imported unconditionally, same convention as test_ndvi_detect.py: CI installs
requirements-eval.txt before the suite runs.
"""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

import baseline_rgb  # noqa: E402
from fieldguard_planning.ndvi_detect import detect_blobs  # noqa: E402

SYNTH_CLIP = REPO_ROOT / "sim" / "spike" / "out" / "spike_seed42"
SYNTH_ARTIFACT = REPO_ROOT / "eval" / "results" / "detections_rgb.json"
WORLD = REPO_ROOT / "sim" / "worlds" / "farmguard_field.sdf"


def study():
    """The most recent committed criterion-2 study, or None if none is on disk."""
    dirs = sorted((REPO_ROOT / "eval" / "results").glob("criterion2_rgb_study_*/results.json"))
    return json.loads(dirs[-1].read_text()) if dirs else None


def grvi_of(r, g):
    return (g - r) / (g + r) if (g + r) else 0.0


class TestThresholdProvenance(unittest.TestCase):
    """A threshold is only as good as the evidence it can be recomputed from."""

    @classmethod
    def setUpClass(cls):
        cls.s = study()
        if cls.s is None:
            raise unittest.SkipTest("no criterion2_rgb_study_* results on disk")

    def test_real_render_threshold_is_the_studys_bird_background_grvi_midpoint(self):
        d = self.s["derived_threshold"]
        midpoint = (d["bird_mean_grvi"] + d["background_mean_grvi"]) / 2.0
        self.assertAlmostEqual(baseline_rgb.REAL_RENDER_GRVI_THRESH, midpoint, places=4)

    def test_the_midpoint_rests_on_a_denominator_the_file_states(self):
        """Every rate in this project carries its denominator; so does every threshold. 16,686 bird
        pixels over 3 birds is thin evidence and the artifact has to keep saying so out loud."""
        d = self.s["derived_threshold"]
        self.assertEqual(d["bird_px"], self.s["denominators"]["bird_pixels"])
        self.assertEqual(d["background_px"], self.s["denominators"]["background_pixels"])
        self.assertGreater(d["background_px"], 1_000_000_000)
        self.assertEqual(sorted(self.s["denominators"]["birds"]),
                         ["bird_0", "bird_1", "bird_2"])

    def test_real_render_birdness_stays_flagged_provisional(self):
        """ADOPT is not CALIBRATED: +0.0322 is a class midpoint, not a scored optimum. Same guard
        the NDVI arm's -0.61 carries."""
        self.assertIn("PROVISIONAL", baseline_rgb.REAL_RENDER_BIRDNESS.provenance)

    def test_the_bird_pixel_oracle_was_validated_not_assumed(self):
        """The study's whole ground truth is `ndvi < -0.50`. It is only usable because the darkest
        NON-bird pixel measured on either clip is -0.4406, and because the frames it fires on are
        the frames the independent applied-pose labels call bird-visible."""
        for tag, o in self.s["oracle_validation"].items():
            with self.subTest(clip=tag):
                self.assertLess(o["background_floor_ndvi"], -0.44)
                self.assertGreater(o["background_floor_ndvi"], o["oracle_threshold"])
                # nothing lies between the two classes -> the partition is exhaustive
                self.assertEqual(o["floor_above_oracle_on_bird_frames"],
                                 o["background_floor_ndvi"])
                # the oracle never misses a frame the measured labels call bird-visible
                self.assertEqual(o["gt_not_in_oracle"], [])


class TestTheSyntheticArmIsUntouched(unittest.TestCase):
    """ADR-003's deciding run must not move because a second render got a birdness."""

    def test_synthetic_birdness_is_min_channel_above_110(self):
        b = baseline_rgb.SYNTHETIC_BIRDNESS
        self.assertEqual((b.name, b.thresh, b.low_is_bird), ("min_channel", 110, False))

    def test_min_channel_masks_bright_achromatic_pixels_only(self):
        """Hand-derived: white passes, a bright-but-green pixel does not (its R and B are low)."""
        rgb = np.zeros((1, 3, 3), dtype=np.uint8)
        rgb[0, 0] = (200, 200, 200)     # white bird -> min 200 > 110
        rgb[0, 1] = (52, 200, 52)       # bright green canopy -> min 52
        rgb[0, 2] = (111, 111, 111)     # one count over the line
        self.assertEqual(baseline_rgb.SYNTHETIC_BIRDNESS.mask(rgb).tolist(),
                         [[True, False, True]])

    @unittest.skipUnless((SYNTH_CLIP / "poses.jsonl").exists() and SYNTH_ARTIFACT.exists(),
                         "seed-42 spike clip not on disk")
    def test_reproduces_the_committed_deciding_run_box_for_box(self):
        frames, skipped = baseline_rgb.run(SYNTH_CLIP, baseline_rgb.SYNTHETIC_BIRDNESS, 6, 5000)
        self.assertEqual(skipped, [])
        self.assertEqual(frames, json.loads(SYNTH_ARTIFACT.read_text())["frames"])


class TestBirdnessResolution(unittest.TestCase):
    """ADR-003 am. 1's failure class: guessing a render produces a plausible run that detected
    nothing, not a crash. So refuse instead."""

    def test_refuses_a_clip_that_does_not_say_which_render_it_is(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            baseline_rgb.resolve_birdness(d)
        (d / "meta.json").write_text('{"synthetic": true}')
        self.assertEqual(baseline_rgb.resolve_birdness(d).name, "min_channel")
        (d / "meta.json").write_text('{"synthetic": false}')
        self.assertEqual(baseline_rgb.resolve_birdness(d).name, "grvi")

    def test_an_explicit_threshold_overrides_the_value_never_the_feature(self):
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "meta.json").write_text('{"synthetic": false}')
        b = baseline_rgb.resolve_birdness(d, 0.5)
        self.assertEqual((b.name, b.thresh, b.low_is_bird), ("grvi", 0.5, True))
        self.assertNotIn("PROVISIONAL", b.provenance)

    def test_a_black_pixel_is_called_bird_and_that_is_the_safe_direction(self):
        """GRVI is 0/0 at R=G=0 and the sentinel is 0.0, which sits BELOW a positive threshold --
        so black reads as bird. Wasteful dodge, not missed bird (ADR-003's own tiebreak). Pinned
        because the docstring's claim and the code's behaviour must not drift apart."""
        rgb = np.zeros((1, 2, 3), dtype=np.uint8)
        rgb[0, 1] = (138, 161, 115)     # this render's modal soil pixel
        self.assertEqual(baseline_rgb.REAL_RENDER_BIRDNESS.mask(rgb).tolist(), [[True, False]])


class TestTheStructuralFinding(unittest.TestCase):
    """Why (b)'s precision cannot be bought back by moving the threshold."""

    def test_the_trunk_material_is_more_bird_like_than_any_bird_pixel(self):
        """Authored in sim/worlds/farmguard_field.sdf: trunk 0.35/0.22/0.10 against bird_1
        0.30/0.22/0.10 -- identical green and blue, 0.05 apart in red. In GRVI the trunk is the
        MORE extreme of the two, so no threshold catches a bird without also catching trunks."""
        trunk = grvi_of(0.35, 0.22)
        bird_1 = grvi_of(0.30, 0.22)
        soil = grvi_of(0.30, 0.42)          # ground plane material
        canopy = grvi_of(0.12, 0.32)
        self.assertLess(trunk, bird_1)                                   # trunk is "birdier"
        self.assertLess(bird_1, 0.0)
        self.assertLess(baseline_rgb.REAL_RENDER_GRVI_THRESH, soil)      # soil stays out
        self.assertLess(soil, canopy)
        for material, name in ((trunk, "trunk"), (bird_1, "bird_1")):
            with self.subTest(material=name):
                self.assertLess(material, baseline_rgb.REAL_RENDER_GRVI_THRESH)

    def test_the_world_still_authors_those_materials(self):
        """The pin above is arithmetic on constants; this is the check that the constants are the
        world's. Trees are ADR-001 known-static, so the collision is tolerable -- but only while
        the geofence knows about every object wearing that colour."""
        sdf = WORLD.read_text()
        self.assertIn("<ambient>0.35 0.22 0.10 1</ambient>", sdf)        # trunk
        self.assertIn("<ambient>0.3 0.22 0.1 1.0</ambient>", sdf)        # bird_1

    @unittest.skipUnless(study() is not None, "no criterion2_rgb_study_* results on disk")
    def test_the_pixel_dominant_rival_loses_a_bird_which_is_why_grvi_ships(self):
        """Forecloses the obvious reviewer objection (raised by adversarial QA, 2026-08-26): GRVI is
        8th of 12 on the pixel table, so why did it ship? Because at its own class-mean midpoint the
        pixel-dominant rival G-B scores per-bird-track FNR 0.333 -- it never sees bird_1, whose brown
        G-B of 24 sits on the background minimum of 23 -- while GRVI holds 0.000 at indistinguishable
        precision. Safety is decided at the detector, not in the pixel table."""
        riv = study()["rival_features"]["results"]
        self.assertEqual(riv["G_minus_B"]["per_bird_track_fnr"], 1 / 3)
        missed = [b for b in riv["G_minus_B"]["per_bird"] if not b["detected_before_closest"]]
        self.assertEqual([b["bird_id"] for b in missed], ["bird_1"])
        # ...and G-B got there by being BETTER on the pixel axis, which is the whole point
        feats = study()["features"]
        self.assertLess(feats["G_minus_B"]["bird_is_LOW"]["fnr_at_zero_fpr"],
                        feats["GRVI"]["bird_is_LOW"]["fnr_at_zero_fpr"])
        for name in ("GRVI", "ExG_2G_minus_R_minus_B", "G_minus_R"):
            with self.subTest(feature=name):
                self.assertEqual(riv[name]["per_bird_track_fnr"], 0.0)
                self.assertAlmostEqual(riv[name]["precision"], 0.22, delta=0.02)

    @unittest.skipUnless(study() is not None, "no criterion2_rgb_study_* results on disk")
    def test_every_false_positive_the_rgb_arm_adds_is_a_surveyed_tree(self):
        """The measured version of the same claim, and the load-bearing one for criterion 2's
        verdict: (b) matches (a) on both safety metrics and loses only precision, and every FP box
        it has that (a) does not lands inside the ADR-001 tree geofence."""
        s = study()
        for tag, arms in s["detector_arm"].items():
            a, b = arms["a_ndvi_direct"], arms["b_rgb_grvi"]
            with self.subTest(clip=tag):
                self.assertEqual(b["FN"], a["FN"])                       # safety parity
                self.assertEqual(b["per_bird_track_fnr"], a["per_bird_track_fnr"])
                self.assertGreaterEqual(b["FP"], a["FP"])                # the price is precision
                extra_fp = b["FP"] - a["FP"]
                extra_on_trees = (b["fp_vs_static_map"]["inside_tree_geofence"]
                                  - a["fp_vs_static_map"]["inside_tree_geofence"])
                self.assertEqual(extra_fp, extra_on_trees)


class TestTheArmIsNotASecondSensor(unittest.TestCase):
    """ADR-007 built the comparison arm out of the primary sensor's own Red band. Measured, so the
    day that stops being true, criterion 2 reopens with a test failure rather than an assumption."""

    @classmethod
    def setUpClass(cls):
        cls.s = study()
        if cls.s is None:
            raise unittest.SkipTest("no criterion2_rgb_study_* results on disk")

    def test_ndvi_inverts_against_the_rgb_red_channel_and_the_red_levels_collapse(self):
        """THE COLLAPSE is the proof. Dozens of distinct 8-bit red levels folding onto a handful of
        rho_nir values is only possible under bit-for-bit band identity.

        The values themselves are a weaker, secondary check and are labelled as such: they match
        gate2_summary.json's MEASURED `mean_rho_nir`, not config/ndvi_camera.json's AUTHORED
        `calibrated_rho_nir` (0.05 / 0.20 / 0.85). gate2 came from this same render pipeline, so
        that agreement is self-consistency plus code identity (ndvi_fusion.rescale_red:85-87), NOT
        cross-validation against config."""
        for tag, frames in self.s["band_independence"]["frames"].items():
            for f in frames:
                with self.subTest(clip=tag, frame=f["frame_id"]):
                    self.assertTrue(f["all_within_unit_interval"])
                    self.assertLessEqual(f["distinct_reconstructed_rho_nir"], 4)
                    self.assertGreaterEqual(f["red_levels"], 20)
                    self.assertGreaterEqual(f["collapse_ratio"], 10.0)
                    self.assertEqual([round(v, 3) for v in f["values"]][:3],
                                     [0.040, 0.212, 0.854])   # gate2 MEASURED means

    def test_the_recovered_values_are_gate2s_measured_means_not_configs_authored_ones(self):
        """Pinning the correction itself: if someone later rewrites the docstring to claim these
        are the authored calibration targets, this fails and points at the real source."""
        gate2 = json.loads((REPO_ROOT / "eval" / "results" / "gate2_summary.json").read_text())
        recovered = self.s["band_independence"]["frames"]
        vals = next(iter(recovered.values()))[0]["values"][:3]
        for v, cls in zip(vals, ("bird", "soil", "canopy")):
            with self.subTest(material=cls):
                self.assertAlmostEqual(v, gate2["classes"][cls]["mean_rho_nir"], places=5)
                self.assertNotAlmostEqual(v, gate2["classes"][cls]["calibrated_rho_nir"], places=5)


class TestTheCommittedArtifactsAgreeWithTheStudy(unittest.TestCase):
    """The defect this class exists to stop (found by adversarial QA, 2026-08-26): the study's
    headline lived only inside its own results.json while `eval/results/adr003_*/` still held the
    superseded min-channel run. Anyone re-scoring the COMMITTED artifacts -- the reproducible path,
    and the one an interviewer would take -- got gap -0.850 and arm-(b) FNR 1.000, i.e. exactly the
    numbers the study retires. Committed evidence must not contradict committed evidence."""

    ADR003 = REPO_ROOT / "eval" / "results" / "adr003_20260823"
    IN_AIR = REPO_ROOT / "eval" / "results" / "adr003_20260825"

    def _score(self, d):
        import score as scoring
        _gt, by_fid = scoring.load_gt(d / "ground_truth.json")
        arms = {}
        for name in ("detections_ndvi", "detections_rgb"):
            det = json.loads((d / f"{name}.json").read_text())
            arms[det["approach"]] = (scoring.score(by_fid, det["frames"], 0.3), det["params"])
        birds = len({b["bird_id"] for f in by_fid.values() for b in f["birds"]})
        return arms, birds, scoring

    def test_the_committed_rgb_arm_is_the_measured_birdness_not_the_retired_one(self):
        for d in (self.ADR003, self.IN_AIR):
            with self.subTest(artifact=d.name):
                params = json.loads((d / "detections_rgb.json").read_text())["params"]
                self.assertEqual(params["birdness"], "grvi")
                self.assertEqual(params["thresh"], baseline_rgb.REAL_RENDER_GRVI_THRESH)
                self.assertTrue(params["low_is_bird"])

    def test_rescoring_the_committed_adopted_artifacts_prints_adopt_at_gap_zero(self):
        arms, birds, scoring = self._score(self.ADR003)
        a, b = arms["a_ndvi_direct"][0], arms["b_synthetic_rgb"][0]
        lines, verdict = scoring.decide(a, b, birds)
        self.assertIn("ADOPT (a) NDVI-direct", verdict)
        self.assertAlmostEqual(a["fnr"] - b["fnr"], 0.0, places=6)
        self.assertIn("gap +0.000", " ".join(lines))

    def test_regenerating_the_rgb_arm_did_not_disturb_the_am7_adopt_record(self):
        """ADR-003 am. 7's numbers are arm (a)'s and must survive untouched -- the whole point of
        regenerating (b) is that (a) is not what moved."""
        a = self._score(self.ADR003)[0]["a_ndvi_direct"][0]
        self.assertEqual((a["TP"], a["FP"], a["FN"]), (17, 7, 3))
        self.assertAlmostEqual(a["precision"], 0.708, places=3)
        self.assertAlmostEqual(a["recall"], 0.850, places=3)
        self.assertEqual(a["per_bird_track_fnr"], 0.0)
        self.assertEqual(a["visible_bird_frames"], 20)
        self.assertEqual(a["birds_with_visible_frames"], 3)

    def test_the_in_air_clip_still_refuses_to_decide(self):
        """A working (b) must not talk score.py out of its denominator guard: 1 of 3 birds ever
        visible is EVIDENCE INSUFFICIENT no matter how good either arm looks on n=2."""
        arms, birds, scoring = self._score(self.IN_AIR)
        _lines, verdict = scoring.decide(arms["a_ndvi_direct"][0], arms["b_synthetic_rgb"][0], birds)
        self.assertIn("EVIDENCE INSUFFICIENT", verdict)

    def test_the_committed_scores_file_matches_a_fresh_rescore(self):
        """spike_scores.json sits beside the detections it was computed from; if one is regenerated
        and the other is not, the directory disagrees with itself."""
        for d in (self.ADR003, self.IN_AIR):
            with self.subTest(artifact=d.name):
                arms, _birds, _s = self._score(d)
                committed = json.loads((d / "spike_scores.json").read_text())["approaches"]
                for approach, (fresh, _p) in arms.items():
                    for metric in ("TP", "FP", "FN", "precision", "recall", "fnr",
                                   "per_bird_track_fnr"):
                        self.assertAlmostEqual(committed[approach][metric], fresh[metric], places=9,
                                               msg=f"{d.name}/{approach}.{metric}")


class TestOneBlobDetector(unittest.TestCase):
    def test_the_rgb_arm_runs_the_same_blob_machinery_as_the_ndvi_arm(self):
        self.assertIs(baseline_rgb.detect_blobs, detect_blobs)


if __name__ == "__main__":
    unittest.main()
