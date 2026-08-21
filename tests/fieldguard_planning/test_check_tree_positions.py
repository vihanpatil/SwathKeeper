"""Tests for scripts/check_tree_positions.py -- the tree-placement gate.

The point of this file is the FIVE-CLIP REPRODUCTION below. The tree-check method was reconstructed
on 2026-08-21 and was only allowed to judge new clips after it reproduced every already-published
figure exactly. These tests hold that door shut: if a refactor moves any of these five numbers, the
port is wrong, and every claim in docs/BUILD_LOG.md's 2026-08-21 entry that rests on them is now
unsupported. They read committed clip artifacts, so they are real measurements, not fixtures.

The negative case is real too: the three horizon-facing-mount clips of 2026-08-18 are the exact
failure this gate exists to catch, and they are in the repo, so the gate is tested against the
mistake it was written for rather than against a synthetic stand-in.

stdlib unittest only. Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))   # the checker lives in scripts/, not src/

import check_tree_positions as checker  # noqa: E402

CLIPS = REPO_ROOT / "eval" / "results" / "clips"

# (clip, trees imaged, trees canopy-grade) -- every one of these is quoted in the docs.
# The first two are the "5/8 and 5/6" of the 2026-08-18 night entry (canopy/imaged); the last is
# the demo take, whose 12/8 and +0.8692 are the headline of the 2026-08-21 second entry.
PUBLISHED = [
    ("real_flight_20260818T194325Z", 8, 5),    # flight 6
    ("real_flight_20260818T201047Z", 6, 5),    # flight 7
    ("real_flight_20260818T221641Z", 7, 6),
    ("real_flight_20260821T034116Z", 11, 6),
    ("real_flight_20260821T045848Z", 12, 8),   # the demo take
]
DEMO_TAKE = "real_flight_20260821T045848Z"
DEMO_MEDIAN_LIFT = 0.8692                      # BUILD_LOG 2026-08-21: "median lift +0.8692"

# The horizon-facing-mount clips (pre ADR-007 amendment 5): a full-looking grid, canopy 6.4-11.9 m
# from any tree. BUILD_LOG: "imaged *more* cells (697, 586, 450) ... and returned zero canopy-grade".
DISPLACED = ["real_flight_20260818T145932Z",
             "real_flight_20260818T183753Z",
             "real_flight_20260818T190904Z"]

# A 2.5 m cell's centre-to-corner distance -- where every post-fix positive cell sits.
CORNER_DIST_M = 1.7678


class TestPublishedFigures(unittest.TestCase):
    """The five clips reproduce their published imaged/canopy counts exactly."""

    def test_five_clip_reproduction(self):
        for clip, imaged, canopy in PUBLISHED:
            with self.subTest(clip=clip):
                result = checker.analyse(CLIPS / clip)
                self.assertEqual(result["trees_imaged"], imaged)
                self.assertEqual(result["trees_canopy_grade"], canopy)
                self.assertEqual(result["trees_total"], 18)

    def test_demo_take_median_lift(self):
        """+0.8692, the number the demo take was called 'dead on to four decimals' against."""
        result = checker.analyse(CLIPS / DEMO_TAKE)
        self.assertAlmostEqual(result["median_lift"], DEMO_MEDIAN_LIFT, places=4)

    def test_soil_modal_ndvi_is_the_physics_value(self):
        """ADR-007 Gate 2 predicts soil -0.437 from the band arithmetic; every clip reads it."""
        for clip, _, _ in PUBLISHED:
            with self.subTest(clip=clip):
                self.assertAlmostEqual(checker.analyse(CLIPS / clip)["soil_modal_ndvi"],
                                       -0.437687, places=6)


class TestQuadGeometry(unittest.TestCase):
    """The four-cell quad is what makes the denominators 8 and 6 rather than 6 and 5."""

    def test_every_tree_gets_exactly_four_cells_at_the_corner_distance(self):
        trees = checker.load_trees()
        self.assertEqual(len(trees), 18)
        cells = {c["cell_id"]: c for c in json.loads(
            (CLIPS / DEMO_TAKE / "heatmap" / "heatmap.json").read_text())["cells"]}
        for row in checker.analyse(CLIPS / DEMO_TAKE)["trees"]:
            with self.subTest(tree=row["tree_id"]):
                self.assertEqual(len(row["quad_cell_ids"]), 4)
                tx, ty = row["pos_m"]
                for cell_id in row["quad_cell_ids"]:
                    cell = cells[cell_id]
                    dist = ((cell["cx_m"] - tx) ** 2 + (cell["cy_m"] - ty) ** 2) ** 0.5
                    self.assertAlmostEqual(dist, CORNER_DIST_M, places=4)

    def test_imaged_and_canopy_follow_the_quad_rule(self):
        """imaged := >=1 of four non-null; canopy-grade := best-of-four > 0.0."""
        for row in checker.analyse(CLIPS / DEMO_TAKE)["trees"]:
            with self.subTest(tree=row["tree_id"]):
                self.assertEqual(row["imaged"], row["n_quad_cells_imaged"] >= 1)
                self.assertEqual(row["canopy_grade"],
                                 row["mean_ndvi"] is not None and row["mean_ndvi"] > 0.0)


class TestDisplacementGate(unittest.TestCase):
    """The FAIL condition: canopy drawn where no tree exists."""

    def test_published_clips_place_every_positive_cell_on_a_tree(self):
        """100 % of positive cells at 1.7678 m -- the post-mount-fix signature."""
        for clip, _, _ in PUBLISHED:
            with self.subTest(clip=clip):
                result = checker.analyse(CLIPS / clip)
                self.assertTrue(result["passed"])
                self.assertEqual(result["displaced_cells"], [])
                self.assertGreater(result["positive_cells"], 0)

    def test_horizon_mount_clips_are_rejected(self):
        """More cells, more trees imaged, zero canopy -- and the gate still says no."""
        for clip in DISPLACED:
            with self.subTest(clip=clip):
                result = checker.analyse(CLIPS / clip)
                self.assertFalse(result["passed"])
                self.assertEqual(result["trees_canopy_grade"], 0)
                self.assertEqual(len(result["displaced_cells"]), result["positive_cells"])
                worst = max(c["nearest_tree_m"] for c in result["displaced_cells"])
                self.assertGreater(worst, 6.0)   # measured signature: 6.4-11.9 m

    def test_threshold_sits_in_the_measured_gap(self):
        """2.0 m is not a judgement call: nothing observed lands between 1.7678 and 6.3738."""
        self.assertGreater(checker.MAX_DISPLACEMENT_M, CORNER_DIST_M)
        self.assertLess(checker.MAX_DISPLACEMENT_M, 6.3738)

    def test_cells_imaged_is_not_the_metric(self):
        """The all-time-high 697/720 clip fails; the 410/720 demo take passes. That inversion IS
        the reason this gate exists, so it is pinned rather than left to the runbook prose."""
        best_looking = checker.analyse(CLIPS / "real_flight_20260818T145932Z")
        demo = checker.analyse(CLIPS / DEMO_TAKE)
        self.assertGreater(best_looking["cells_imaged"], demo["cells_imaged"])
        self.assertFalse(best_looking["passed"])
        self.assertTrue(demo["passed"])


class TestCli(unittest.TestCase):

    def test_exit_codes(self):
        for clip, expected in [(DEMO_TAKE, 0), (DISPLACED[0], 1)]:
            with self.subTest(clip=clip):
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(checker.main([str(CLIPS / clip)]), expected)

    def test_json_output_carries_the_published_numbers(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(checker.main([str(CLIPS / DEMO_TAKE), "--json"]), 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["trees_imaged"], 12)
        self.assertEqual(payload["trees_canopy_grade"], 8)
        self.assertAlmostEqual(payload["median_lift"], DEMO_MEDIAN_LIFT, places=4)

    def test_missing_clip_fails_loudly(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(checker.main([str(CLIPS / "no_such_clip")]), 1)


if __name__ == "__main__":
    unittest.main()
