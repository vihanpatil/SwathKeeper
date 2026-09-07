"""The COMMITTED depth-segmenter score artifact -- the file that authorises the depth detector.

`tests/fieldguard_planning/test_depth_segment.py` pins the MODULE: what the operator computes and
what it refuses. Nothing there reads the artifact the scorer actually wrote, so
`eval/results/depth_segmenter_score_*.json` -- the one the constants' provenance string names, the
one a reviewer and ADR-021 will quote -- could rot, be hand-edited, or be replaced by a run with
different constants, and every test would stay green. **This file reads it**, the same pattern
`test_booking_gate_artifact.py` sets for the flight authorisation.

Two things it does that a schema check would not:

  1. **It closes the loop between the module and its evidence.** `DEFAULT_PARAMS` in `src/` must
     equal the artifact's adopted constants, AND `DEFAULT_PARAMS_PROVENANCE` must name the artifact
     file that chose them. Either half alone is a number with a story; both together are a number
     with a receipt.
  2. **It re-runs the adopted segmenter on the six committed fixture frames and requires the
     artifact's own per-station rows.** The artifact says what the detector did on S015, S026,
     S036, S040, S061 and S080; this makes it say it again, today, from the committed bytes. It
     never regenerates the artifact -- a rewrite would erase exactly the disagreement worth having.

Assertions are HARD, not skipped-if-absent: a missing artifact is the failure, not a reason to pass
quietly. Runs on the host, numpy + scipy, ~2 s.
"""
import json
import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

import numpy as np  # noqa: E402

import score_depth_segmenter as sds  # noqa: E402
from fieldguard_planning.depth_segment import (  # noqa: E402
    DEFAULT_PARAMS, DEFAULT_PARAMS_PROVENANCE, DepthSegmenter,
)

RESULTS_DIR = REPO_ROOT / "eval" / "results"
GLOB = "depth_segmenter_score_*.json"
DATASET = RESULTS_DIR / "depth_dataset_20260907"
FIXTURES = DATASET / "fixtures"

# The adopted run, 2026-09-07: the sweep that chose every constant in `depth_segment.DEFAULT_PARAMS`.
# Re-scored in the same day's fix round -- the merge metric was counting a correct SPLIT as the
# failure it is the fix for, and the median-flip margin (below) did not exist. No constant moved.
ADOPTED = "depth_segmenter_score_20260907T110000Z.json"
ADOPTED_CONSTANTS = {"bg_window_px": 15, "margin_m": 1.5, "min_area_px": 10, "open_iter": 0,
                     "max_boxes": 64, "near_m": 0.1, "far_m": 60.0, "link_break": False}


def artifact() -> dict:
    path = RESULTS_DIR / ADOPTED
    if not path.exists():
        raise AssertionError(
            f"missing {path} -- the depth segmenter's own evidence. Regenerate with\n"
            f"  python3 eval/score_depth_segmenter.py --stamp 20260907T093000Z\n"
            f"and note that it needs the ~100 MB dataset under {DATASET}.")
    return json.loads(path.read_text())


class TestTheCommittedArtifact(unittest.TestCase):
    def setUp(self):
        self.a = artifact()

    def test_exactly_one_score_artifact_is_committed_and_it_is_the_adopted_one(self):
        """More than one and 'the artifact' stops being a definite article: the provenance string
        names ONE file, and a reader must not have to guess which run the constants came from."""
        found = sorted(p.name for p in RESULTS_DIR.glob(GLOB))
        self.assertEqual(found, [ADOPTED], f"committed score artifacts: {found}")

    def test_the_module_default_and_the_artifact_name_each_other(self):
        for k, want in ADOPTED_CONSTANTS.items():
            self.assertEqual(self.a["constants"][k], want, msg=k)
            self.assertEqual(getattr(DEFAULT_PARAMS, k), want, msg=f"DEFAULT_PARAMS.{k}")
        self.assertIs(self.a["constants_match_module_default"], True)
        self.assertIn(ADOPTED, DEFAULT_PARAMS_PROVENANCE,
                      "the module's constants do not name the artifact that chose them")
        self.assertEqual(self.a["module_default_provenance"], DEFAULT_PARAMS_PROVENANCE,
                         "the artifact recorded a DIFFERENT provenance string than src/ carries "
                         "today -- one of them has been edited since the run")

    def test_the_artifact_identifies_the_exact_bytes_it_was_scored_on(self):
        d = self.a["dataset"]
        self.assertEqual(d["n_frames"], 85)
        self.assertEqual(d["n_distinct_frame_sha1"], 82)
        self.assertEqual(len(d["labels_sha256"]), 64)
        self.assertEqual(d["stations_file"], "docs/design/depth_segmenter_stations.json")
        self.assertEqual(sds.sha256_of(REPO_ROOT / d["stations_file"]), d["stations_file_sha256"],
                         "the station file has changed since the score run")
        if (DATASET / "labels.jsonl").exists():
            self.assertEqual(sds.sha256_of(DATASET / "labels.jsonl"), d["labels_sha256"])
        self.assertEqual(self.a["claims_ceiling"], "sim-demonstrated, evidence-gated")

    def test_every_bar_passes_and_each_rate_carries_its_denominator(self):
        m = self.a["metrics"]
        self.assertTrue(self.a["all_bars_pass"],
                        [k for k, v in self.a["bars"].items() if not v])
        self.assertTrue(self.a["verdict"].startswith("ADOPT"))

        fnr = m["fnr"]
        self.assertEqual(fnr["denominator_all_FNR_zero_stations"], 49)
        self.assertEqual(fnr["denominator_detectable"], 49)
        self.assertEqual(fnr["misses"], [])
        self.assertEqual(fnr["fnr"], 0.0)
        # the condition is VACUOUS on the bar -- stated, not assumed
        self.assertEqual(fnr["excluded_by_condition"], [])
        self.assertGreaterEqual(len(fnr["per_background_x_range"]), 8)
        self.assertEqual(sum(c["n"] for c in fnr["per_background_x_range"].values()), 49)

        fp = m["false_positives"]
        self.assertEqual(fp["denominator_frames"], 8)
        self.assertEqual(fp["unmapped_fp_total"], 0)
        self.assertLessEqual(fp["unmapped_fp_per_frame"], 0.05)
        # ...and the mapped column is where the volume is, all of it real clutter
        self.assertEqual(fp["mapped_fp_total"], fp["mapped_by_tree_geofence"])
        self.assertEqual(fp["mapped_by_ground_or_below_geofence_top"], 0)

        self.assertEqual(m["merge"]["count"], 0)
        self.assertGreaterEqual(m["merge"]["denominator_visible_bird_stations"], 60)
        # the corrected rule: a correct SPLIT is counted under its own name, never as a mislabel
        self.assertEqual(m["merge"]["separated_neighbour_count"], 0)
        self.assertIn("was not separately matched", m["merge"]["definition"])
        self.assertLessEqual(m["accuracy"]["range_error_p95_m"], 0.5)
        self.assertGreaterEqual(m["accuracy"]["denominator_matches"], 60)
        self.assertGreater(m["accuracy"]["range_error_signed_min_m"], 0.0,
                           "a NEGATIVE range error would mean a component credited with a depth "
                           "nearer than any surface -- a bug, not noise")
        self.assertLessEqual(m["runtime"]["seg_wall_ms_p95"], 25.0)
        self.assertLessEqual(m["runtime"]["seg_wall_ms_max"], 100.0)
        self.assertGreaterEqual(m["runtime"]["n"], 5 * 85)
        self.assertEqual(m["determinism"]["mismatched"], [])
        self.assertEqual(m["determinism"]["denominator_stations"], 79)

    def test_the_median_flip_margin_is_measured_reported_and_NOT_a_bar(self):
        """The number `range_error_p95` cannot see. A matched component that is part bird and part
        background reports the bird's depth only while the bird holds a MAJORITY of its pixels, so
        the failure is a median FLIP, not a drift: at S042 the same detection would publish 54.5 m
        instead of 29.96 m -- a bird at 30 m declared no threat -- and it is ONE pixel away.

        Pinned here because the metric's whole purpose is that it cannot quietly disappear again.
        It is deliberately NOT in `bars`: this run is the first that measures it, and a threshold
        invented in the pass that first sees a number is a threshold fitted to its own data."""
        fl = self.a["metrics"]["median_flip_margin"]
        self.assertNotIn("median_flip_margin", self.a["bars"],
                         "REPORTED, not barred -- see the docstring")
        self.assertEqual(fl["denominator_matched_stations"],
                         self.a["metrics"]["accuracy"]["denominator_matches"])
        self.assertEqual(fl["mixed_components"] + fl["pure_bird_components"],
                         fl["denominator_matched_stations"])
        self.assertEqual(fl["min_px_to_median_flip"], 1)
        self.assertAlmostEqual(fl["min_bird_pixel_fraction"], 0.5333, places=4)
        self.assertEqual(sorted(fl["stations_within_3_px_of_a_flip"]), ["S041", "S042", "S046"])
        self.assertIs(fl["all_bird_pixels_are_nearest"], True,
                      "the flip margin's arithmetic assumes the bird's pixels are the NEAREST in "
                      "the component; if that stops holding, the margin stops meaning this")
        worst = {x["id"]: x for x in fl["worst_five"]}
        s42 = worst["S042"]
        self.assertEqual((s42["component_px"], s42["bird_px"], s42["other_px"]), (60, 32, 28))
        self.assertAlmostEqual(s42["reported_depth_m"], 29.956, places=3)
        self.assertGreater(s42["flipped_depth_m"], 50.0,
                           "the flipped depth is the safety number: what the SAME detection would "
                           "report on the far side of the cliff")
        # ...and the per-station fields really are on the rows a reader would look at
        rows = {r["id"]: r for r in self.a["stations"]}
        self.assertEqual(rows["S042"]["px_to_median_flip"], 1)
        self.assertEqual(rows["S015"]["bird_pixel_fraction"], 1.0)

    def test_the_link_break_decision_rests_on_two_measured_clauses_not_on_a_miscount(self):
        """The first pass rejected `link_break` because it "introduced 2 merge mislabels and fixed
        nothing". Both halves were wrong: those 2 were correct SPLITS mis-counted by a merge rule
        that did not require the bird to be unmatched, and the rule ON does fix something (it is
        what separates the two components sitting 1 px from a flip).

        The rule stays OFF, and this pins the two reasons that survive the correction: it moves no
        bar, AND it fails the design note's own precondition that it never withholds a component."""
        lb = self.a["constants_sweep"]["link_break"]
        self.assertIs(lb["adopted"], False)
        self.assertIs(lb["moves_a_bar"], False)
        self.assertIs(lb["withholds_a_component"], True)
        off, on = lb["rows"][0], lb["rows"][1]
        self.assertIs(off["link_break"], False)
        self.assertIs(on["link_break"], True)
        for arm in (off, on):
            self.assertEqual(arm["misses"], [])
            self.assertEqual(arm["unmapped_fp"], 0)
            self.assertEqual(arm["merge_mislabels"], 0,
                             "under the corrected rule NEITHER arm has a merge mislabel; the 2 the "
                             "first pass reported were correct splits")
        self.assertEqual(on["separated_neighbour_ids"], ["S042", "S046"])
        # ON is measurably BETTER on the reported quantities -- recorded, not acted on
        self.assertLess(on["range_error_p95_m"], off["range_error_p95_m"])
        self.assertLess(on["centroid_error_max_px"], off["centroid_error_max_px"])
        self.assertIsNone(on["min_px_to_median_flip"], "ON leaves no mixed component at all")
        self.assertIn("open_item_for_a_pre_registered_round", lb)
        self.assertIn("correction_to_the_first_pass", lb)
        self.assertIn("link_break", DEFAULT_PARAMS_PROVENANCE)
        self.assertNotIn("fixed nothing", DEFAULT_PARAMS_PROVENANCE,
                         "the receipt in src/ still carries the miscounted sentence")

    def test_the_multi_object_probe_names_the_dataset_gap_it_cannot_close(self):
        """Every one of the 85 stations has exactly one bird; CLAUDE.md's MVP obstacle density is
        2-3. The probe is what stands in for the missing arm, and it measures the fail-dangerous
        direction: two touching near objects come back as ONE component at a median belonging to
        NEITHER of them."""
        mo = self.a["multi_object_probe"]["cases"]
        small, large = mo["small_pair_3x4_px"], mo["large_pair_3x20_px"]
        self.assertEqual(small["link_break_False"]["depths_m"], [25.0],
                         "20 m beside 30 m must report the merged 25 m this exists to name")
        self.assertEqual(small["link_break_True"]["n_boxes"], 0)
        self.assertEqual(small["link_break_True"]["components_below_min_area"], 2)
        self.assertEqual(large["link_break_True"]["depths_m"], [20.0, 30.0],
                         "with both halves above min_area the cut splits correctly -- which is what "
                         "makes the small case an INTERACTION and not a defect of the cut")

    def test_the_acquisition_number_says_how_far_it_is_actually_clutter_backed(self):
        """`cluttered acquisition 46.0 m` reads as a clutter measurement at 46 m and is not one:
        above 30 m every rung in this world is sky-backed, because an in-band bird at 46 m has its
        ground background past the 60 m Euclidean cull. Geometrically forced, not a sampling gap --
        and a qualifier the artifact owed rather than more stations."""
        aq = self.a["acquisition"]
        self.assertEqual(aq["clutter_backed_max_range_m"], 28.0)
        self.assertEqual(aq["clutter_backed_max_range_by_background"]["canopy"], 28.0)
        self.assertEqual(aq["clutter_backed_max_range_by_background"]["ground_band"], 22.0)
        self.assertEqual(aq["sky_backed_only_from_range_m"], 30.0)
        self.assertIn("CLUTTER CLAIM", aq["verdict"])
        self.assertEqual(aq["booked_m"], 46.0, "the qualifier must not move the booked number")
        for row in aq["ladder"]:
            if row["range_m"] >= aq["sky_backed_only_from_range_m"]:
                self.assertTrue(all(b.startswith("sky") for b in row["backgrounds"]), msg=row)

    def test_the_runtime_rate_cannot_be_quoted_against_the_wrong_denominator(self):
        """Two wall-ms trios live in this artifact -- the 5-rep bench (n = 425) and the single
        scoring pass's cumulative counters (n = 79) -- and the smaller one is the one a reader
        reaches for by accident. The bench is the number; the note says so in the file."""
        rt = self.a["metrics"]["runtime"]
        self.assertEqual(rt["n"], 5 * 85)
        self.assertEqual(self.a["segmenter_counters"]["seg_wall_ms_n"], 79)
        self.assertIn("metrics.runtime", self.a["segmenter_counters_note"])
        self.assertLessEqual(rt["seg_wall_ms_p95"], 25.0)
        self.assertLessEqual(rt["seg_wall_ms_max"], 100.0)

    def test_the_labeller_agreed_with_the_render_and_with_the_flight_primitive(self):
        lab = self.a["labeller"]
        self.assertEqual(lab["tau_px"], 5.0)
        self.assertLess(lab["max_rendered_vs_recomputed_px"], 5.0)
        self.assertLess(lab["max_rendered_vs_recomputed_px"], 1.0,
                        "the recompute drifted toward tau -- investigate before trusting a label")
        self.assertLess(lab["max_stationfile_vs_recomputed_px"], 1.0)
        self.assertLess(lab["max_raycast_vs_render_background_m"], 0.5)
        self.assertLess(self.a["roundtrip"]["max_roundtrip_error_m"], 1e-3)
        self.assertEqual(self.a["roundtrip"]["inverse_primitive"],
                         "fieldguard_planning.depth_detect.depth_pixel_to_enu")

    def test_the_occlusion_stations_proved_the_occluder_BEFORE_they_scored_the_miss(self):
        occ = self.a["metrics"]["occlusion"]
        self.assertEqual(occ["denominator_stations"], 3)
        for sid, row in occ["stations"].items():
            self.assertEqual(row["rendered_bird_pixels"], 0, msg=sid)
            self.assertIs(row["occluder_proved_first"], True, msg=sid)
            self.assertIs(row["detected_at_expected_pixel"], False, msg=sid)

    def test_the_mutation_check_ran_and_recorded_the_ONE_redundant_conjunct(self):
        mu = self.a["mutation"]
        self.assertIs(mu["all_three_red"], True)
        self.assertIs(mu["reds"]["step_over_margin"], True)
        self.assertIs(mu["reds"]["clip_window"], True)
        self.assertIs(mu["reds"]["isfinite+clip_window"], True)
        # The finding, pinned so it cannot quietly become a claim of three independent safeguards.
        self.assertIs(mu["isfinite_redundant_with_clip_window"], True)
        self.assertIs(mu["reds"]["isfinite"], False)
        self.assertIn("redundant", mu["redundancy_finding"])
        self.assertEqual(mu["intact"]["canned_boxes"], 1)
        self.assertEqual(mu["mutants"]["step_over_margin"]["dataset_fnr_misses"], 20)

    def test_the_acquisition_number_can_only_lower_the_booked_horizon(self):
        aq = self.a["acquisition"]
        self.assertEqual(aq["previously_booked_m"], 46.0)
        self.assertEqual(aq["cluttered_acquisition_m"], 46.0)
        self.assertEqual(aq["optical_prefix_m"], 50.0)
        self.assertAlmostEqual(aq["corner_ray_ratio"], 1.261627, places=6)
        self.assertAlmostEqual(aq["clamp_bound_m"], 47.558, places=3)
        self.assertEqual(aq["booked_m"], min(46.0, aq["acquisition_after_clamp_m"]))
        self.assertIs(aq["bookable_at_5mps"], True)
        self.assertGreaterEqual(aq["booked_m"], 33.591)
        self.assertIs(aq["limited_by_ladder"], True)
        self.assertIsNone(aq["first_failing_range_m"])
        self.assertIn("QUALIFIES", aq["verdict"])

    def test_the_group_D_ladder_locates_the_margins_own_boundary(self):
        gd = self.a["group_d"]["stations"]
        self.assertEqual(len(gd), 10)
        for sid in ("S048", "S053"):                     # the 0.75 m rungs
            self.assertIs(gd[sid]["detected"], False, msg=sid)
            self.assertLess(gd[sid]["measured_standoff_m"], 0.6, msg=sid)
        for sid in ("S049", "S050", "S051", "S052", "S054", "S055", "S056", "S057"):
            self.assertIs(gd[sid]["detected"], True, msg=sid)
        # 1.5 m rungs detect at a MEASURED centre stand-off of ~1.33 m, i.e. below margin_m: the
        # stand-off varies across the footprint on a sloped background, so the top of the bird sees
        # more than its centre. Recorded because it is what makes the 1.5 m rung pass at all.
        for sid in ("S049", "S054"):
            self.assertLess(gd[sid]["measured_standoff_m"], DEFAULT_PARAMS.margin_m, msg=sid)
            self.assertIs(gd[sid]["sub_margin"], True, msg=sid)

    def test_the_pitched_arm_is_its_own_block_and_never_folded_into_a_bar(self):
        p = self.a["pitched"]
        self.assertEqual(p["denominator_birds"], 5)
        self.assertEqual(p["detected"], 5)
        self.assertEqual(p["fnr"], 0.0)
        self.assertEqual(p["pitch_deg"], -12.5)
        self.assertLessEqual(p["accuracy"]["range_error_p95_m"], 0.5)
        self.assertEqual(p["fp"]["denominator_frames"], 1)
        self.assertEqual(p["fp"]["unmapped_fp_total"], 0)
        # and the bars really did exclude it: 49 + 8 + 3 + 19 = 79 LEVEL stations
        self.assertEqual(self.a["metrics"]["determinism"]["denominator_stations"], 79)
        self.assertEqual(self.a["dataset"]["n_frames"] - 79, 6)

    def test_the_resolving_floor_booked_for_this_session_was_re_measured(self):
        s = self.a["size_and_near_field"]
        self.assertEqual(s["resolving_floor_px"], 2.0)
        self.assertAlmostEqual(s["resolving_floor_implied_range_m"], 46.8, places=1)
        self.assertEqual(s["resolving_floor_px_at_min_area_6"], 1.6)
        self.assertAlmostEqual(s["resolving_floor_implied_range_m_at_min_area_6"], 58.5, places=1)
        self.assertGreater(s["resolving_floor_implied_range_m"],
                           self.a["acquisition"]["booked_m"],
                           "the morphology floor must not sit BELOW the booked horizon")
        self.assertIs(s["morphology_is_the_binding_horizon"], True)

    def test_the_large_object_blind_spot_is_on_the_record(self):
        """The measured correction to DESIGN §2.5 / ALGORITHM §2.4. If a later change makes a large
        near object visible, this test goes red and the design notes get to be right again -- which
        is the outcome to want, and it should require touching this line to claim."""
        s = self.a["size_and_near_field"]
        self.assertEqual(s["object_size_sweep"]["radius_1.3m"]["blind_ranges_m"], [20.0, 10.0, 5.0])
        self.assertGreater(len(s["object_size_sweep"]["radius_5.0m"]["blind_ranges_m"]), 4)
        self.assertIn("ZERO candidates", s["large_object_blind_zone"])
        for row in s["bird_ladder_radius_0.18m"]:
            self.assertGreaterEqual(row["components"], 1,
                                    f"a 0.18 m bird went undetected at {row['range_m']} m")

    def test_the_artifact_names_what_it_does_NOT_measure(self):
        gaps = " ".join(self.a["transfer_gaps"]).upper()
        for token in ("STATIC VEHICLE", "NOISELESS", "LEVEL ATTITUDE", "HOST TIMING",
                      "ONE TARGET PER FRAME", "VERSION SPREAD"):
            self.assertIn(token, gaps)

    def test_the_stack_these_numbers_were_computed_on_is_recorded_and_is_neither_target(self):
        """The 3-decimal fixture assertions come out of a scipy morphology. They were measured on
        the `environment` stack; CI pins another and the flight container a third, and DESIGN §1.4's
        "byte-identical on any machine with the pinned scipy" has never been executed on either.
        Recording the triple is what turns that from an assumption into a booked 60-second check."""
        env = self.a["environment"]
        for key in ("python", "numpy", "scipy"):
            self.assertRegex(str(env[key]), r"^\d+\.\d+")
        self.assertIn("scipy", env["ci_pins"])
        self.assertIn("scipy", env["flight_container_pins"])
        gaps = " ".join(self.a["transfer_gaps"])
        self.assertIn("test_depth_segment.py", gaps,
                      "the version gap must name the command that closes it")


class TestFixturesReproduceTheArtifactsRows(unittest.TestCase):
    """Re-run TODAY's `DepthSegmenter(DEFAULT_PARAMS)` on the six committed frames and require the
    artifact's own numbers. This is the half that would catch a change to the operator that leaves
    every synthetic unit test green."""

    def setUp(self):
        self.a = artifact()
        self.rows = {r["id"]: r for r in self.a["stations"]}

    def _fixture(self, sid):
        path = FIXTURES / f"{sid}.npz"
        if not path.exists():
            self.fail(f"missing committed fixture {path} -- written by "
                      f"eval/score_depth_segmenter.py alongside the artifact")
        with np.load(path, allow_pickle=False) as d:
            return d["depth"], json.loads(str(d["meta"]))

    def test_all_six_fixtures_are_committed_small_and_faithful_to_the_dataset(self):
        recorded = {f["station_id"]: f for f in self.a["fixtures"]}
        self.assertEqual(sorted(recorded), sorted(sds.FIXTURE_STATIONS))
        for sid, rec in recorded.items():
            frame, meta = self._fixture(sid)
            self.assertLess(rec["size_kb"], 500.0, msg=sid)
            self.assertIs(rec["under_500kb"], True, msg=sid)
            self.assertEqual(frame.dtype, np.float32, msg=sid)
            self.assertEqual(frame.shape, (480, 640), msg=sid)
            import hashlib
            self.assertEqual(hashlib.sha1(frame.tobytes()).hexdigest(), meta["frame_sha1"],
                             f"{sid}: the fixture is not the dataset frame it claims to be")

    def test_each_fixture_reproduces_the_artifacts_per_station_row(self):
        for sid in sds.FIXTURE_STATIONS:
            frame, meta = self._fixture(sid)
            row = self.rows[sid]
            got = DepthSegmenter(DEFAULT_PARAMS)(frame)
            self.assertEqual(len(got), row["n_boxes"], msg=f"{sid} box count")
            if row["expected_px"] is None:
                self.assertIsNone(row["matched_depth_m"], msg=sid)
                continue
            eu, ev = row["expected_px"]
            hit = [(b, d) for b, d in got
                   if math.hypot(0.5 * (b[0] + b[2]) - eu, 0.5 * (b[1] + b[3]) - ev) <= sds.TAU_PX
                   and abs(d - row["expected_depth_m"]) <= sds.EPS_M]
            self.assertEqual(bool(hit), row["matched"], msg=f"{sid} match")
            if row["matched"]:
                self.assertAlmostEqual(min(d for _, d in hit), row["matched_depth_m"], places=3,
                                       msg=f"{sid} depth")

    def test_the_negative_control_fixture_still_puts_nothing_in_empty_space(self):
        frame, meta = self._fixture("S061")
        row = self.rows["S061"]
        self.assertEqual(row["fp_unmapped"], 0)
        self.assertEqual(row["fp_total"], row["fp_mapped"])
        self.assertEqual(len(DepthSegmenter(DEFAULT_PARAMS)(frame)), row["fp_total"])

    def test_the_pitched_fixture_still_detects_its_bird_at_the_right_range(self):
        frame, meta = self._fixture("S080")
        row = self.rows["S080"]
        self.assertIs(row["matched"], True)
        got = DepthSegmenter(DEFAULT_PARAMS)(frame)
        near = [d for _, d in got if abs(d - row["expected_depth_m"]) <= sds.EPS_M]
        self.assertTrue(near, "the -12.5 deg pitched frame lost its bird")
        self.assertAlmostEqual(min(near), row["matched_depth_m"], places=3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
