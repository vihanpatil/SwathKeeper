"""The DEPTH-SOURCE gates in scripts/check_live_flight_log.py -- P1 of
`docs/runbooks/DODGE_TAKE_PREREGISTRATION_20260907.md`, built 2026-09-07, RED-FIRST.

WHAT CHANGED AND WHY IT NEEDED A TEST FILE OF ITS OWN. Until today `depth_blob` was deliberately
absent from `DETECTOR_SOURCES`, so a forward-depth take produced an UNSCOREABLE log (INVALID,
exit 1) by construction: every schema-2 detector gate was written for the NADIR NDVI camera. The
unlock is not the name in that tuple -- it is the SEVEN BARS qa-safety pre-registered before any
depth take existed. Adding the name without them would have turned a refusal-to-score into a green
verdict on the other sensor's evidence, which is the exact failure the gate exists to prevent.

NO DEPTH LOG EXISTS YET, so every bar is proven on SYNTHETIC schema-2 logs and every one of them has
BOTH fixtures: one that must fail it and one that must pass it. A gate with only a passing fixture
is a gate nobody has seen fire.

FOUR PINS THAT ARE NOT ABOUT A BAR, and each closes a way this file could quietly stop meaning
anything:
  * THE BLOCK IS THE REAL ONE. The fixtures' `run.detector` comes from
    `avoidance_node._depth_detector_log_block` itself, driven by a real `DepthDetectionSource` +
    `DepthSegmenter` -- so a field the node renames breaks these tests instead of silently
    un-gating a bar six weeks later.
  * THE QUOTES ARE THE PRE-REGISTERED ONES. Every gate message quotes its bar; each quote is
    asserted to be a substring of §P1 of the pre-registration itself, normalised. A bar cannot be
    re-aimed at something easier after a flight fails it.
  * THE GEOMETRY AGREES WITH THE FLIGHT CODE. `checker.depth_bearing_deg` is a stdlib re-derivation
    of the inverse of `depth_detect.depth_pixel_to_enu` (the gate may not import numpy). It is
    round-tripped against that function through the real mount matrix, so the two cannot drift.
  * THE NDVI PATH IS BYTE-IDENTICAL. The three committed flight logs are scored through the real
    CLI and diffed against a stored snapshot of the output this file produced BEFORE the depth diff
    landed (2 ACKNOWLEDGED, 1 INVALID, exit 1).

Runs on the host: stdlib + numpy (the fixtures build a real segmenter), no rclpy, no renderer.
"""
import json
import math
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_live_flight_log as checker  # noqa: E402
from fieldguard_planning import avoidance_node as node  # noqa: E402
from fieldguard_planning import depth_detect  # noqa: E402
from fieldguard_planning.avoidance_executor import RESUME_CLEAR_TICKS  # noqa: E402
from fieldguard_planning.avoidance_policy import PolicyParams, _params_dict  # noqa: E402
from fieldguard_planning.coverage import CELL_COVERED, build_grid, load_field_polygon  # noqa: E402
from fieldguard_planning.depth_segment import DepthSegmenter  # noqa: E402
from fieldguard_planning.ndvi_georef import CameraIntrinsics  # noqa: E402

GRID = build_grid(load_field_polygon())
LEDGER = [{"cell_id": c.cell_id, "status": CELL_COVERED} for c in GRID]

PREREG = REPO_ROOT / "docs" / "runbooks" / "DODGE_TAKE_PREREGISTRATION_20260907.md"
SNAPSHOT = Path(__file__).parent / "fixtures" / "check_live_flight_log_committed_output.txt"
COMMITTED_LOGS = ("eval/results/live_flight_log_20260818T144711Z.json",
                  "eval/results/live_flight_log_20260823T004031Z.json",
                  "eval/results/live_flight_log_20260825T210402Z.json")

# --- the flight the fixtures fly -----------------------------------------------------------------
# Straight and level, due EAST, 1.0 m per 0.2 s tick = 5.0 m/s -- the speed ADR-020's booking gate
# authorised, so the numbers here are the ones a real take would carry. Five ticks; the encounter is
# takeover 2 -> resume 4 with one accepted maneuver and one detection on tick 2.
CRUISE_Z = 15.0
PATH = [[50.0 + i, 50.0, CRUISE_Z] for i in range(5)]
STAMPS = [100.0, 100.2, 100.4, 100.6, 100.8]
DET_TICK = 2
DRONE_AT_DET = tuple(PATH[DET_TICK - 1])                       # (51, 50, 15)
# 40 m dead ahead: past the 33.591 m breakeven (bar 5) and dead centre of the frustum (bar 4).
# READ THIS BEFORE TRUSTING THE GREEN FIXTURE. Today's executor CANNOT write a detection event at
# 40 m -- `_log_detection` only fires for a threat already inside `threat_radius_m` (12.0 m), so
# every real depth log will fail bar 5 as CENSORED until the seam's longest-range detection reaches
# the artifact (see TestBar5Acquisition, and P1's disposition note in the pre-registration). The
# green fixture is therefore what a log MUST look like to pass the bar, not what the node produces
# tonight -- which is the point of writing the gate before the flight.
DET_POS = (DRONE_AT_DET[0] + 40.0, DRONE_AT_DET[1], CRUISE_Z)
TRUTH_SIM = [99.8, 100.0, 100.2, 100.4, 100.6, 100.8, 101.0]
CONFIG_BIRD_IDS = sorted(b["bird_id"] for b in checker.load_birds(checker.DEFAULT_BIRDS_CONFIG))
PARKED = (95.0, 95.0, 1.0)          # far away AND 14 m out of the +/-6 m band: never the CPA
INTRINSICS = CameraIntrinsics(width_px=640, height_px=480, fx=520.0058, fy=520.0058,
                              cx=320.0, cy=240.0)
# `DepthDetectionSource.counters()` on a HEALTHY take: 1199 of 1200 frames reached the segmenter
# (the one loss is the startup frame before `/fg/depth/camera_info` landed), nothing dropped for
# shape, and the runtime bars inside 25 / 100 ms.
#
# THESE NUMBERS BALANCE, and that is now load-bearing (QA round 1, 2026-09-07). `on_frame` takes
# exactly one of five paths per call, so the four per-frame drop counters plus `frames_detected_on`
# SUM to `depth_msgs_received`; and it times every call in a `finally`, so `detect_wall_ms_n` EQUALS
# `depth_msgs_received` -- this fixture said 1199 until the gate learned to check, which is exactly
# the fixture bug that let an impossible counter through. Every mutation below balances too, so a
# red fixture fails the bar it is aimed at and not the arithmetic.
HEALTHY_COUNTERS = {
    "depth_msgs_received": 1200, "frames_detected_on": 1199, "frames_with_detection": 40,
    "boxes_total": 52, "dropped_no_intrinsics": 1, "dropped_no_pose_pair": 0,
    "dropped_stale_pose_pair": 0, "dropped_frame_shape_mismatch": 0, "dropped_non_finite_depth": 0,
    "dropped_out_of_range": 0, "detections_near_known_obstacle": 7, "static_map_annotator_errors": 0,
    "detect_wall_ms_p95": 8.211, "detect_wall_ms_max": 19.402, "detect_wall_ms_n": 1200,
}


def real_depth_block(counters=None, **over):
    """`run.detector` as `avoidance_node._depth_detector_log_block` REALLY writes it.

    The node's own writer is called, on a real `DepthDetectionSource` wrapping a real
    `DepthSegmenter`, so the fixture cannot describe a block the node does not produce. Only the
    counters are substituted (a freshly-constructed source has flown nothing), and
    `test_the_fixture_counters_are_the_seams_own_keys` pins that substitution to the seam's own
    key set."""
    source = depth_detect.DepthDetectionSource(DepthSegmenter(), intr=INTRINSICS)
    cfg = node.DetectorConfig(
        depth_params=source.segmenter.params,
        depth_params_provenance="eval/results/depth_segmenter_score_20260907T110000Z.json",
        depth_params_provisional=False)
    block = node._depth_detector_log_block(source, cfg)
    block["counters"] = dict(block["counters"], **dict(HEALTHY_COUNTERS, **(counters or {})))
    block.update(over)
    return block


def detection_event(tick=DET_TICK, pos=DET_POS, **over):
    """One `detection` event as `AvoidanceExecutor._log_detection` writes it: track_id, frame_id,
    confidence, position_enu, source, decision. NOTE WHAT IS NOT THERE -- `static_map_hint`, which
    the seam puts on the `Detection` and the executor does not log (bar 6 depends on the
    distinction between an absent key and a null one)."""
    ev = {"seq": tick, "tick": tick, "kind": "detection", "track_id": None, "frame_id": 812,
          "confidence": 1.0, "position_enu": list(pos), "source": checker.DET_DEPTH_BLOB,
          "decision": "divert"}
    ev.update(over)
    return ev


def maneuver_event(tick=DET_TICK, **over):
    """One ACCEPTED divert, as `_handle_divert` logs it. The dodge is 10 m east of ownship and the
    threat 9 m north of it, so R2/R3/R3.7 pass for every test that is not about them."""
    drone = PATH[tick - 1]
    debug = {"swept_tree_clearance_m": 3.2, "trigger_range_m": 9.0, "range_degenerate": False,
             "threat_ids": ["bird_0"],
             "threat_positions_enu": [[drone[0], drone[1] + 9.0, CRUISE_Z]],
             "params": _params_dict(PolicyParams())}
    ev = {"seq": tick, "tick": tick, "kind": "maneuver", "decision": "divert",
          "verdict": "accepted", "debug": debug, "latch_action": "latch",
          "setpoint_enu": [drone[0] + 10.0, drone[1], CRUISE_Z],
          "policy_setpoint_enu": [drone[0] + 10.0, drone[1], CRUISE_Z], "track_id": None}
    ev.update(over)
    return ev


def encounter_events(det=None, maneuver=None, takeover_tick=DET_TICK, resume_tick=4):
    return [
        {"seq": 0, "tick": takeover_tick, "kind": "takeover", "reason": "divert",
         "from_mode": "AUTO", "to_mode": "GUIDED", "wp_index_at_takeover": 3, "track_id": None},
        detection_event() if det is None else det,
        maneuver_event() if maneuver is None else maneuver,
        {"seq": 3, "tick": resume_tick, "kind": "resume", "trigger": "threat_cleared",
         "resumed_wp_index": 3, "wp_index_at_takeover": 3, "resumed_same_waypoint": True,
         "latched_setpoint_enu": None, "clear_ticks_required": RESUME_CLEAR_TICKS,
         "ticks_in_guided": 3},
    ]


def depth_log(events=None, detector=None, path=None, stamps=None, **over):
    """A structurally valid schema-2 DEPTH flight log."""
    flown = PATH if path is None else path
    log = {
        "scenario": "depth_p1_test", "seed": 0, "cell_size_m": 2.5, "swath_half_width_m": 7.5,
        "executor_params": {"resume_clear_ticks": RESUME_CLEAR_TICKS, "guided_ceiling_ticks": 50,
                            "relatch_threshold_m": 2.0, "vertical_margin_m": 1.0},
        "flown_path_enu": [list(p) for p in flown],
        "coverage_ledger": LEDGER,
        "requeue_events": [],
        "events": list(encounter_events() if events is None else events),
        "run": {
            "schema_version": 2,
            "clock": {"source": checker.CLOCK_SOURCE, "violations": 0},
            "tick_stamp_sim_s": list(STAMPS if stamps is None else stamps),
            "policy_params": _params_dict(PolicyParams()),
            "detector": real_depth_block() if detector is None else detector,
        },
    }
    log.update(over)
    return log


def truth_records(poses_by_tick, park_undriven=True):
    """A `drive_birds` applied-pose log as a list of records -- same shape (and same reasoning) as
    tests/fieldguard_planning/test_check_live_flight_log_schema2.py's fixture."""
    recs = []
    for sim_t, poses in poses_by_tick:
        full = dict(poses)
        if park_undriven:
            for k, bird_id in enumerate(CONFIG_BIRD_IDS):
                full.setdefault(bird_id, (PARKED[0], PARKED[1] + 2.0 * k, PARKED[2]))
        for j, (bird_id, pos) in enumerate(full.items()):
            recs.append({
                "bird_id": bird_id, "t_traj_s": 0.0, "pos_m": [float(c) for c in pos],
                "yaw_rad": 0.0, "ok": True,
                "tick_sim_s": sim_t, "tick_wall_s": sim_t, "clock_wall_s": sim_t,
                "wall_start_s": sim_t + 0.001 + 0.01 * j, "wall_end_s": sim_t + 0.002 + 0.01 * j,
            })
    return recs


def bird_parked_at(pos):
    """bird_0 held at `pos` for the whole flight window; the other two birds parked far away."""
    return truth_records([(t, {"bird_0": tuple(pos)}) for t in TRUTH_SIM])


class Harness(unittest.TestCase):
    """A tmp dir that is BOTH the flight-log home and the `eval/results` the gate scans, so no test
    can pick up committed evidence."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write_truth(self, records, stamp="20260907T120000Z"):
        applied = self.dir / f"bird_drive_{stamp}_applied.jsonl"
        (self.dir / f"bird_drive_{stamp}.json").write_text(json.dumps({
            "schema_version": "1.1", "clock": "sim", "t0_sim_s": TRUTH_SIM[0],
            "applied_log": applied.name, "bird_ids": sorted({r["bird_id"] for r in records}),
        }))
        applied.write_text("".join(json.dumps(r) + "\n" for r in records))
        return applied

    def check(self, log, truth=None, name="live_flight_log_TEST.json", no_birds=False):
        p = self.dir / name
        p.write_text(json.dumps(log))
        return checker.check_file(p, truth=truth, results_dir=self.dir, no_birds=no_birds)

    def green(self, log=None, truth_pos=DET_POS):
        """The take everything else is a mutation of: a clean depth flight with bird ground truth."""
        truth = self.write_truth(bird_parked_at(truth_pos))
        return self.check(depth_log() if log is None else log, truth=truth)

    def blob(self, result):
        return " ".join(result[1])

    def assertInvalid(self, result, needle):
        text = self.blob(result)
        self.assertEqual(result[0], checker.INVALID, text)
        self.assertIn(needle, text)
        return text

    def assertValid(self, result):
        text = self.blob(result)
        self.assertEqual(result[0], checker.VALID, text)
        return text


# ================================================================================================
# 0. The unlock itself, and the fixture's own honesty
# ================================================================================================
class TestTheSourceIsScoreableNow(Harness):
    def test_depth_blob_is_in_DETECTOR_SOURCES(self):
        self.assertIn(checker.DET_DEPTH_BLOB, checker.DETECTOR_SOURCES)

    def test_a_clean_depth_take_is_VALID_and_no_longer_refused_at_the_door(self):
        text = self.assertValid(self.green())
        self.assertNotIn("refuses to score the flight", text)
        self.assertNotIn("expected one of", text)

    def test_an_unknown_source_is_still_refused(self):
        """The tuple grew by ONE reviewed name with its own gates; it did not become a wildcard."""
        log = depth_log()
        log["run"]["detector"]["source"] = "yolov8"
        self.assertInvalid(self.check(log), "refuses to score the flight")

    def test_the_fixture_block_is_the_nodes_own_writer(self):
        """Not a hand-written dict: the node's real `_depth_detector_log_block`, so a renamed field
        turns these tests red instead of silently un-gating a bar."""
        block = real_depth_block()
        for key in ("source", "module", "seam_module", "params", "params_provenance",
                    "params_provisional", "min_range_m", "max_range_m", "range_model",
                    "static_map_annotator", "intrinsics", "counters", "segmenter_counters"):
            self.assertIn(key, block)
        self.assertEqual(block["source"], checker.DET_DEPTH_BLOB)
        self.assertEqual(block["seam_module"], checker.DEPTH_SEAM_MODULE)
        self.assertEqual(block["range_model"], checker.DEPTH_RANGE_MODEL)
        self.assertTrue(block["intrinsics"]["provenance"].startswith(
            checker.DEPTH_INTRINSICS_PROVENANCE))

    def test_the_fixture_counters_are_the_seams_own_keys(self):
        """A counter this file invents is a bar tested against nothing."""
        real = depth_detect.DepthDetectionSource(DepthSegmenter(), intr=INTRINSICS).counters()
        self.assertEqual(sorted(HEALTHY_COUNTERS), sorted(k for k in real if k != "note"))
        for key in checker.DEPTH_DETECTOR_COUNTER_KEYS + checker.DEPTH_WALL_MS_KEYS:
            self.assertIn(key, real)

    def test_every_bar_quote_is_the_pre_registered_text(self):
        """The bars were written BEFORE the data existed (ADR-016 doctrine). Each quote in the gate
        must still be a substring of §P1 -- otherwise a bar could be re-aimed after a failure.

        The haystack STOPS at the first disposition note. §P1 is append-only and the notes under it
        are written by the people the bars are pointed at (mine included), so leaving them in would
        mean every paragraph added below a bar widened the text that bar is pinned against (QA round
        2). The pin now reads only the pre-registered bars themselves."""
        section = PREREG.read_text().split("### P1", 1)[1].split("### P2", 1)[0]
        section = section.split("> **P1 disposition", 1)[0]
        self.assertNotIn("disposition", section)

        def norm(s):
            s = (s.replace("≥", ">=").replace("≤", "<=").replace("—", "--")
                  .replace("–", "--").replace("±", "+/-").replace("°", " deg")
                  .replace("`", "").replace("*", ""))
            return re.sub(r"\s+", " ", s).strip()

        haystack = norm(section)
        for n, quote in checker.P1_BARS.items():
            with self.subTest(bar=n):
                self.assertIn(norm(quote), haystack)

    def test_the_mount_offset_matches_the_flight_codes_and_the_config(self):
        """`DEPTH_MOUNT_FORWARD_M` is restated in the gate because `depth_detect` imports numpy and
        this gate is stdlib-only. Restated copies drift unless something pins them."""
        self.assertEqual(checker.DEPTH_MOUNT_FORWARD_M,
                         depth_detect.FORWARD_MOUNT_OFFSET_BODY_M[0])
        cfg = json.loads((REPO_ROOT / "config" / "depth_camera.json").read_text())
        self.assertEqual(checker.DEPTH_MOUNT_FORWARD_M,
                         cfg["mount"]["mount_pose_xyz_rpy"][0])


# ================================================================================================
# 1. BAR 1 -- the detect rate, over the RIGHT denominator
# ================================================================================================
class TestBar1DetectRate(Harness):
    def test_green_a_healthy_rate_prints_with_its_denominator(self):
        text = self.assertValid(self.green())
        self.assertIn("detect rate 99.91% of 1200", text)
        self.assertIn("depth_msgs_received=1200", text)

    def test_red_below_the_floor(self):
        """300 frames lost to a stale pose pair: 900 of 1200 = 75 %, and the drops still balance."""
        log = depth_log(detector=real_depth_block({"frames_detected_on": 900,
                                                   "dropped_stale_pose_pair": 299}))
        text = self.assertInvalid(self.green(log), "DEPTH DETECTOR BARELY RAN")
        self.assertIn("900 of 1200", text)
        self.assertIn("75.00%", text)
        self.assertNotIn("IMPOSSIBLE COUNTERS", text)      # the fixture fails BAR 1, not arithmetic

    def test_red_zero_frames_is_a_hard_failure_not_a_vacuous_pass(self):
        """`camera_info` never arrived, so every frame was dropped before the segmenter."""
        log = depth_log(detector=real_depth_block({"frames_detected_on": 0, "boxes_total": 0,
                                                   "frames_with_detection": 0,
                                                   "dropped_no_intrinsics": 1200}))
        text = self.assertInvalid(self.green(log), "DEPTH DETECTOR NEVER RAN")
        self.assertNotIn("IMPOSSIBLE COUNTERS", text)

    def test_red_a_zero_DENOMINATOR_is_a_problem_and_never_a_pass(self):
        """0/0 is a shrug, not a rate. The NDVI gate printed `n/a` here and passed."""
        nothing = dict(dict.fromkeys(HEALTHY_COUNTERS, 0),
                       detect_wall_ms_p95=None, detect_wall_ms_max=None)
        log = depth_log(detector=real_depth_block(nothing))
        text = self.assertInvalid(self.green(log), "DEPTH DETECT RATE HAS NO DENOMINATOR")
        self.assertIn("UNMEASURED (0 depth messages)", text)
        self.assertNotIn("IMPOSSIBLE COUNTERS", text)
        self.assertNotIn("IMPOSSIBLE RUNTIME DENOMINATOR", text)   # 0 timed of 0 received is fine

    def test_red_a_missing_counter_is_not_a_zero(self):
        block = real_depth_block()
        block["counters"].pop("frames_detected_on")
        self.assertInvalid(self.green(depth_log(detector=block)), "'frames_detected_on'")

    def test_the_floor_is_the_same_one_the_ndvi_gate_uses(self):
        self.assertEqual(checker.MIN_DETECT_RATE, 0.90)


# ================================================================================================
# 2. BAR 2 -- dropped_frame_shape_mismatch == 0, HARD
# ================================================================================================
class TestBar2FrameShapeMismatch(Harness):
    def test_green_zero_prints_with_its_denominator(self):
        self.assertIn("dropped_frame_shape_mismatch 0 of 1200", self.assertValid(self.green()))

    def test_red_any_nonzero_is_invalid(self):
        """`frames_detected_on` moves with the mismatch count because the five per-frame paths sum
        to `depth_msgs_received` -- at 1 and 17 the detect rate is still over its floor, so bar 2 is
        the only bar these two fail. The all-blind case necessarily fails bar 1 as well: that is
        arithmetic, not a confound."""
        for n in (1, 17, 1199):
            with self.subTest(mismatched=n):
                log = depth_log(detector=real_depth_block(
                    {"dropped_frame_shape_mismatch": n, "frames_detected_on": 1199 - n,
                     **({"frames_with_detection": 0, "boxes_total": 0} if n == 1199 else {})}))
                text = self.assertInvalid(self.green(log), "FRAME SHAPE MISMATCH")
                self.assertIn("tens of metres from where it is", text)
                self.assertIn("This bar is HARD", text)
                self.assertNotIn("IMPOSSIBLE COUNTERS", text)
                if n != 1199:
                    self.assertNotIn("DEPTH DETECTOR", text)      # bar 1 stays silent


# ================================================================================================
# 3. BAR 3 -- the range MODEL (declared) and the range ERROR (measured, gated at 0.5 m)
# ================================================================================================
class TestBar3RangeModel(Harness):
    def test_green_the_declarations_print(self):
        text = self.assertValid(self.green())
        self.assertIn(checker.DEPTH_RANGE_MODEL, text)
        self.assertIn("live /fg/depth/camera_info", text)

    def test_red_an_apparent_size_ray_is_refused(self):
        block = real_depth_block()
        block["range_model"] = "apparent_size_ray (ADR-009 rule 2)"
        self.assertInvalid(self.green(depth_log(detector=block)), "RANGE MODEL NOT DECLARED")

    def test_red_a_ground_plane_projection_is_refused_by_name(self):
        block = real_depth_block()
        block["range_model"] = "ground-plane projection"
        text = self.assertInvalid(self.green(depth_log(detector=block)),
                                  "RANGE MODEL NOT DECLARED")
        self.assertIn("outside the threat cylinder", text)

    def test_red_intrinsics_from_the_config_are_refused(self):
        block = real_depth_block()
        block["intrinsics"]["provenance"] = "config/depth_camera.json"
        text = self.assertInvalid(self.green(depth_log(detector=block)),
                                  "INTRINSICS PROVENANCE")
        self.assertIn("what we ASKED for", text)

    def test_red_no_intrinsics_block_at_all(self):
        block = real_depth_block()
        block["intrinsics"] = None
        self.assertInvalid(self.green(depth_log(detector=block)), "NO INTRINSICS BLOCK")

    def test_red_the_un_projection_module_must_be_named(self):
        block = real_depth_block()
        block["seam_module"] = "fieldguard_planning.ndvi_detect"
        self.assertInvalid(self.green(depth_log(detector=block)),
                           "UN-PROJECTION MODULE NOT NAMED")


class TestBar3RangeError(Harness):
    def test_green_a_measured_range_that_matches_the_truth(self):
        text = self.assertValid(self.green())
        self.assertIn("range_estimate_error_at_cpa_m 0.0000 m", text)
        self.assertIn("p95 0.0000 m", text)

    def test_red_a_range_error_over_the_bar_at_cpa(self):
        """The bird really is 2 m further away than the detection says: 2.0 m against a 0.5 m bar
        (the segmenter's own scored p95 was 0.1076 m over 63 matches)."""
        truth_pos = (DET_POS[0] + 2.0, DET_POS[1], DET_POS[2])
        text = self.assertInvalid(self.green(truth_pos=truth_pos), "RANGE ERROR OVER BAR AT CPA")
        self.assertIn("2.0000 m", text)
        self.assertIn("0.5 m bar", text)

    def test_no_truth_prints_UNMEASURED_and_never_PASS(self):
        """`--truth` refusal is a hard problem of its own; the range bar must not ALSO read as
        passed. The line has to say UNMEASURED in those words."""
        problems, notes, measured = checker.depth_range_error(depth_log(), None, None)
        self.assertFalse(measured)
        self.assertEqual(problems, [])
        line = " ".join(notes)
        self.assertIn("RANGE ERROR UNMEASURED", line)
        self.assertIn("Never a PASS", line)

    def test_no_detection_prints_UNMEASURED(self):
        log = depth_log(events=[e for e in encounter_events() if e["kind"] != "detection"])
        problems, notes, measured = checker.depth_range_error(log, None, None)
        self.assertFalse(measured)
        self.assertEqual(problems, [])
        self.assertIn("RANGE ERROR UNMEASURED", " ".join(notes))

    def test_the_association_distance_is_printed_so_a_mis_match_is_visible(self):
        self.assertIn("association", self.blob(self.green()))


# ================================================================================================
# 4. BAR 4 -- frustum containment, on the flight's OWN intrinsics
# ================================================================================================
class TestBar4Frustum(Harness):
    def test_the_half_angles_are_derived_not_constants(self):
        """+/-31.6 deg h and +/-24.775 deg v at this sensor -- and something else at another one."""
        intr = {"fx": 520.0058, "fy": 520.0058, "image_width_px": 640, "image_height_px": 480}
        h, v = checker._frustum_half_angles_rad(intr)
        # atan(320/520.0058) and atan(240/520.0058) -- the pre-registration's +/-31.6 / +/-24.775,
        # to the digits the arithmetic really produces.
        self.assertAlmostEqual(math.degrees(h), 31.607, places=3)
        self.assertAlmostEqual(math.degrees(v), 24.775, places=3)
        wide = dict(intr, fx=260.0)
        self.assertGreater(checker._frustum_half_angles_rad(wide)[0], h)
        self.assertIsNone(checker._frustum_half_angles_rad({"fx": 0.0, "fy": 1.0,
                                                            "image_width_px": 4,
                                                            "image_height_px": 4}))

    def test_the_bearing_is_the_inverse_of_the_flight_codes_un_projection(self):
        """THE PIN THAT MAKES A SECOND IMPLEMENTATION SAFE. `depth_bearing_deg` is stdlib (this gate
        may not import numpy, and `depth_detect` pulls it in through `clip_recorder`), so it is a
        re-derivation. Round-tripped through the real `depth_pixel_to_enu` at the real mount matrix:
        un-project a pixel at a depth, then ask the gate where that world point sits."""
        drone = (12.0, -34.0, CRUISE_Z)
        for yaw_deg in (0.0, 37.0, 180.0, -95.0):
            q = (0.0, 0.0, math.sin(math.radians(yaw_deg) / 2.0),
                 math.cos(math.radians(yaw_deg) / 2.0))
            course = (math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg)))
            for u, v, depth in ((320.0, 240.0, 30.0), (600.0, 100.0, 12.5), (40.0, 460.0, 44.0)):
                with self.subTest(yaw=yaw_deg, u=u, v=v):
                    world = depth_detect.depth_pixel_to_enu(
                        u, v, depth, INTRINSICS, drone, q,
                        depth_detect.FORWARD_MOUNT_OFFSET_BODY_M,
                        depth_detect.DEPTH_OPTICAL_TO_BODY)
                    az, el, z = checker.depth_bearing_deg(world, drone, course)
                    self.assertAlmostEqual(
                        az, math.degrees(math.atan((u - INTRINSICS.cx) / INTRINSICS.fx)), places=6)
                    self.assertAlmostEqual(
                        el, math.degrees(math.atan((v - INTRINSICS.cy) / INTRINSICS.fy)), places=6)
                    self.assertAlmostEqual(z, depth, places=6)

    def test_green_a_detection_dead_ahead_is_inside(self):
        text = self.assertValid(self.green())
        self.assertIn("frustum containment: 1 of 1 detection(s)", text)
        self.assertIn("depth 39.850 m", text)              # 40 m ahead, less the 0.15 m mount
        self.assertNotIn("OUTSIDE THE FRUSTUM", text)

    def test_red_a_detection_outside_the_horizontal_half_angle(self):
        """40 deg off the course axis against a 31.608 deg half-angle: the sensor could not have
        made this detection, and a dodge was flown on it."""
        off = math.radians(40.0)
        pos = (DRONE_AT_DET[0] + 20.0 * math.cos(off), DRONE_AT_DET[1] + 20.0 * math.sin(off),
               CRUISE_Z)
        log = depth_log(events=encounter_events(det=detection_event(pos=pos)))
        text = self.assertInvalid(self.green(log, truth_pos=pos), "DETECTION OUTSIDE THE FRUSTUM")
        self.assertIn("31.607 deg h", text)

    def test_red_a_detection_outside_the_vertical_half_angle(self):
        pos = (DRONE_AT_DET[0] + 20.0, DRONE_AT_DET[1], CRUISE_Z + 20.0)
        log = depth_log(events=encounter_events(det=detection_event(pos=pos)))
        text = self.assertInvalid(self.green(log, truth_pos=pos), "DETECTION OUTSIDE THE FRUSTUM")
        self.assertIn("24.775 deg v", text)

    def test_red_a_detection_behind_the_camera(self):
        pos = (DRONE_AT_DET[0] - 20.0, DRONE_AT_DET[1], CRUISE_Z)
        log = depth_log(events=encounter_events(det=detection_event(pos=pos)))
        self.assertInvalid(self.green(log, truth_pos=pos), "DETECTION BEHIND THE CAMERA")

    def test_red_intrinsics_that_cannot_produce_a_frustum(self):
        block = real_depth_block()
        block["intrinsics"] = dict(block["intrinsics"], fx=0.0)
        self.assertInvalid(self.green(depth_log(detector=block)), "FRUSTUM NOT COMPUTABLE")

    def test_a_take_with_no_course_measures_nothing_and_says_so(self):
        """A parked vehicle has no course, and the log records no orientation, so there is no
        forward axis to test against. That is UNMEASURED, and when it is EVERY detection it is a
        problem -- otherwise a hovering take would skip bar 4 in silence."""
        parked = [[50.0, 50.0, CRUISE_Z]] * 5
        log = depth_log(path=parked)
        text = self.assertInvalid(self.green(log, truth_pos=(50.0, 90.0, CRUISE_Z)),
                                  "FRUSTUM CONTAINMENT UNMEASURED")
        self.assertIn("measured nothing at all", text)

    def test_an_accepted_maneuver_with_no_detection_on_its_tick_is_UNMEASURED(self):
        log = depth_log(events=[e for e in encounter_events() if e["kind"] != "detection"])
        problems, notes, _measured = checker.gate_depth_frustum(log, log["run"])
        self.assertEqual(problems, [])
        self.assertIn("FRUSTUM CONTAINMENT UNMEASURED", " ".join(notes))
        self.assertIn("Never a PASS", " ".join(notes))

    def test_only_ACCEPTED_maneuvers_are_in_scope(self):
        """A `gate_reject` is the backstop refusing to fly a point and a HOLD commands zero
        displacement; neither is a dodge taken on a detection."""
        off = math.radians(40.0)
        pos = (DRONE_AT_DET[0] + 20.0 * math.cos(off), DRONE_AT_DET[1] + 20.0 * math.sin(off),
               CRUISE_Z)
        events = [e for e in encounter_events(det=detection_event(pos=pos))
                  if e["kind"] != "maneuver"]
        log = depth_log(events=events)
        problems, _notes, _measured = checker.gate_depth_frustum(log, log["run"])
        self.assertEqual(problems, [])


# ================================================================================================
# 5. BAR 5 -- first-detection range per encounter, against the 33.591 m breakeven
# ================================================================================================
class TestBar5Acquisition(Harness):
    def test_the_breakeven_is_the_pre_registered_number(self):
        self.assertEqual(checker.BREAKEVEN_ACQUISITION_M, 33.591)
        self.assertIn("33.591", PREREG.read_text())

    def test_green_a_first_detection_beyond_the_breakeven(self):
        text = self.assertValid(self.green())
        self.assertIn("first detection at tick 2, range 40.000 m", text)
        self.assertIn("at or beyond the breakeven", text)

    def test_red_a_late_acquisition_ranks_the_horizon_lever(self):
        """Beyond the threat cylinder, so this IS a sensor reading: acquired at 20 m against a
        33.591 m budget."""
        pos = (DRONE_AT_DET[0] + 20.0, DRONE_AT_DET[1], CRUISE_Z)
        log = depth_log(events=encounter_events(det=detection_event(pos=pos)))
        text = self.assertInvalid(self.green(log, truth_pos=pos), "ACQUISITION BELOW BREAKEVEN")
        self.assertIn("THE HORIZON LEVER", text)
        self.assertIn("50.8 m", text)
        self.assertNotIn("CENSORED", text)

    def test_red_an_in_cylinder_first_detection_is_named_as_CENSORED_not_as_a_sensor_result(self):
        """THE STRUCTURAL FINDING, pinned so it cannot be forgotten: the executor logs a `detection`
        event only for a threat already inside `threat_radius_m`, so a first detection at 10 m is
        the POLICY's ceiling, not the sensor's horizon. The bar still fails -- an unevidenced
        authorisation is not a verified one -- but it must rank the logging gap, not the optics."""
        pos = (DRONE_AT_DET[0] + 10.0, DRONE_AT_DET[1], CRUISE_Z)
        log = depth_log(events=encounter_events(det=detection_event(pos=pos)))
        text = self.assertInvalid(self.green(log, truth_pos=pos), "ACQUISITION BELOW BREAKEVEN")
        self.assertIn("CENSORED, NOT MEASURED", text)
        self.assertIn("_log_detection", text)
        self.assertNotIn("THE HORIZON LEVER", text)

    def test_red_an_encounter_window_with_no_detection_at_all(self):
        log = depth_log(events=[e for e in encounter_events() if e["kind"] != "detection"])
        self.assertInvalid(self.green(log), "ACQUISITION RANGE UNMEASURED on takeover 2")

    def test_a_take_with_no_encounter_says_UNMEASURED_rather_than_passing(self):
        log = depth_log(events=[])
        problems, notes, _measured = checker.gate_depth_acquisition(log, log["run"])
        self.assertEqual(problems, [])
        self.assertIn("ACQUISITION RANGE UNMEASURED", " ".join(notes))
        self.assertIn("Never a PASS", " ".join(notes))

    def test_the_range_is_the_one_the_pre_registrations_own_analysis_plan_computes(self):
        """§6 of the pre-registration prints `math.dist(e["position_enu"], fp[e["tick"]-1][:3])`.
        The gate must not mean something else by "detection range"."""
        log = depth_log()
        det = checker.depth_detections(log)[0]
        self.assertAlmostEqual(det["range_m"],
                               math.dist(DET_POS, PATH[DET_TICK - 1]), places=9)


# ================================================================================================
# 6. BAR 6 -- no dodge against the map
# ================================================================================================
class TestBar6StaticMap(Harness):
    def test_red_an_accepted_dodge_on_a_hinted_detection(self):
        log = depth_log(events=encounter_events(
            det=detection_event(static_map_hint="tree_07")))
        text = self.assertInvalid(self.green(log), "DODGE AGAINST THE MAP")
        self.assertIn("'tree_07'", text)
        self.assertIn("annotate-and-count only", text)

    def test_green_an_explicit_null_hint_passes_the_bar(self):
        log = depth_log(events=encounter_events(det=detection_event(static_map_hint=None)))
        text = self.assertValid(self.green(log))
        self.assertIn("no dodge against the map", text)

    def test_an_ABSENT_hint_key_is_UNMEASURED_and_names_the_missing_field(self):
        """What the executor writes TODAY. `_log_detection` does not carry `static_map_hint`, so the
        bar has nothing to read -- and it must say so rather than pass. The seam's own
        `detections_near_known_obstacle` is printed as the denominator that does exist."""
        text = self.assertValid(self.green())
        self.assertIn("STATIC-MAP BAR UNMEASURED", text)
        self.assertIn("NOT A PASS", text)
        self.assertIn("_log_detection", text)
        self.assertIn("detections_near_known_obstacle = 7", text)

    def test_the_executor_really_does_not_log_the_hint_today(self):
        """The claim the UNMEASURED message makes about the code, checked against the code. When
        this goes red the message is stale and the bar can finally bite."""
        source = (REPO_ROOT / "src" / "fieldguard_planning" / "avoidance_executor.py").read_text()
        body = source.split("def _log_detection", 1)[1].split("\n    def ", 1)[0]
        self.assertNotIn("static_map_hint", body)

    def test_only_ACCEPTED_maneuvers_are_in_scope(self):
        events = [e for e in encounter_events(det=detection_event(static_map_hint="tree_07"))
                  if e["kind"] != "maneuver"]
        log = depth_log(events=events)
        problems, notes, _measured = checker.gate_depth_static_map(log, log["run"])
        self.assertEqual(problems, [])
        self.assertIn("STATIC-MAP BAR UNMEASURED", " ".join(notes))


# ================================================================================================
# 7. BAR 7 -- the NDVI-family gates print `N/A (depth take)`, never PASS
# ================================================================================================
class TestBar7NotApplicable(Harness):
    FAMILIES = ("ndvi_msgs_received", "apparent-size estimator check", "nadir-footprint reasoning",
                "ADR-003 evidence")

    def test_every_ndvi_family_line_says_N_A_depth_take_and_never_PASS(self):
        _status, messages = self.green()
        for family in self.FAMILIES:
            with self.subTest(family=family):
                lines = [m for m in messages if family in m]
                self.assertEqual(len(lines), 1, msg=f"{family}: {lines}")
                self.assertIn(checker.NA_DEPTH, lines[0])
                # The bar's own quoted text ends "...never PASS", so the claim under test is about
                # what the gate SAYS, i.e. everything before the quote.
                said = lines[0].split("P1 bar 7", 1)[0]
                self.assertIn(checker.NA_DEPTH, said)
                self.assertNotIn("PASS", said)

    def test_the_ndvi_only_numbers_never_appear_on_a_depth_take(self):
        """`detection_cpa_m` is the monocular estimator's own number and the NADIR footprint
        argument is the wrong scoping for a forward camera. Neither may be printed as if measured."""
        text = self.blob(self.green())
        self.assertNotIn("monocular apparent-size estimate", text)
        self.assertNotIn("the camera is NADIR", text)
        self.assertNotIn("detector counters: ndvi_msgs_received", text)

    def test_the_gt_cpa_gate_still_runs_because_it_is_not_an_ndvi_gate(self):
        """The bird ground-truth CPA knows nothing about which camera saw the bird -- it is the
        flown path against the applied-pose track. It must NOT be N/A'd away."""
        text = self.blob(self.green())
        self.assertIn("gt_cpa_m", text)
        self.assertIn("truth coverage", text)

    def test_a_cpa_breach_on_a_depth_take_is_still_a_breach(self):
        """The one verdict that must survive the sensor swap. The bird sits 1 m off the flown path
        at cruise altitude."""
        result = self.green(truth_pos=(52.0, 51.0, CRUISE_Z))
        self.assertInvalid(result, checker.CPA_BREACH_TAG)


# ================================================================================================
# 8. The mislabel refusal stays EXCLUSIVE in both directions
# ================================================================================================
class TestMislabelExclusivity(Harness):
    def test_a_depth_block_labelled_ndvi_is_refused(self):
        block = real_depth_block()
        block["source"] = checker.DET_NDVI_BLOB
        text = self.assertInvalid(self.green(depth_log(detector=block)),
                                  "the label and the contents are different detectors")
        self.assertIn("'params'", text)

    def test_an_ndvi_block_labelled_depth_is_refused(self):
        block = {"source": checker.DET_DEPTH_BLOB, "module": "fieldguard_planning.ndvi_detect",
                 "thresh": -0.61, "thresh_provenance": "ADR-003 am. 7", "thresh_provisional": True,
                 "min_area": 6, "max_area": 4000, "radius_prior_m": 0.12,
                 "range_model": checker.DEPTH_RANGE_MODEL,
                 "counters": {"ndvi_msgs_received": 1256, "frames_detected_on": 1256}}
        self.assertInvalid(self.green(depth_log(detector=block)),
                           "the label and the contents are different detectors")

    def test_a_depth_log_carrying_an_ndvi_COUNTER_is_refused(self):
        block = real_depth_block()
        block["counters"]["ndvi_msgs_received"] = 1256
        self.assertInvalid(self.green(depth_log(detector=block)),
                           "'counters.ndvi_msgs_received'")

    def test_the_clean_block_passes_the_rule(self):
        self.assertEqual(checker.gate_detector_block_matches_source(depth_log()["run"]), [])


# ================================================================================================
# 9. The runtime bars, on the node's OWN counters
# ================================================================================================
class TestRuntimeBars(Harness):
    def test_green_inside_both_bars(self):
        text = self.assertValid(self.green())
        self.assertIn("detect wall time p95 8.211 ms (bar 25) max 19.402 ms (bar 100) over n = 1200",
                      text)

    def test_red_p95_over_25_ms(self):
        log = depth_log(detector=real_depth_block({"detect_wall_ms_p95": 31.4}))
        self.assertInvalid(self.green(log), "detect_wall_ms_p95 31.400 ms exceeds 25 ms")

    def test_red_max_over_100_ms(self):
        log = depth_log(detector=real_depth_block({"detect_wall_ms_max": 140.0}))
        self.assertInvalid(self.green(log), "detect_wall_ms_max 140.000 ms exceeds 100 ms")

    def test_red_a_missing_runtime_counter_is_a_problem_not_a_fast_detector(self):
        block = real_depth_block()
        block["counters"].pop("detect_wall_ms_p95")
        self.assertInvalid(self.green(depth_log(detector=block)), "['detect_wall_ms_p95']")

    def test_zero_timed_frames_is_UNMEASURED_never_a_pass(self):
        block = real_depth_block({"detect_wall_ms_n": 0, "detect_wall_ms_p95": None,
                                  "detect_wall_ms_max": None})
        problems, notes = checker.gate_depth_detector_ran(depth_log(detector=block),
                                                          depth_log(detector=block)["run"])
        self.assertIn("detect wall time UNMEASURED", " ".join(notes))
        self.assertNotIn("DETECT WALL TIME OVER BAR", " ".join(problems))


# ================================================================================================
# 10. The booking half is unchanged -- a depth take is an AVOIDANCE take
# ================================================================================================
class TestBookingStillApplies(Harness):
    def test_a_depth_take_with_no_booking_is_warned_at(self):
        text = self.assertValid(self.green())
        self.assertIn("NO BOOKING BOUND -- WARNING", text)
        self.assertIn("depth_blob", text)

    def test_the_flown_speed_is_measured_either_way(self):
        self.assertIn("flown_ground_speed_mps median 5.000", self.blob(self.green()))


# ================================================================================================
# 11. THE NDVI PATH IS UNTOUCHED -- byte-for-byte, through the real CLI
# ================================================================================================
class TestTheNdviPathIsByteIdentical(unittest.TestCase):
    """The three committed logs, scored by the real command line, against a snapshot of the output
    this gate produced BEFORE the depth diff. Two ACKNOWLEDGED, one INVALID, exit 1 -- and not one
    character of it may move because a second sensor grew its own gates.

    A stored snapshot rather than a `git show HEAD` comparison on purpose: once this diff is
    committed, HEAD IS the new file and that comparison would compare the checker with itself. The
    snapshot keeps biting for every future change, and regenerating it is a reviewed diff."""

    def test_the_committed_logs_score_exactly_as_they_did(self):
        missing = [p for p in COMMITTED_LOGS if not (REPO_ROOT / p).exists()]
        if missing:
            self.skipTest(f"committed evidence absent in this checkout: {missing}")
        proc = subprocess.run([sys.executable, "scripts/check_live_flight_log.py", *COMMITTED_LOGS],
                              cwd=REPO_ROOT, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1, msg=proc.stderr)
        self.assertEqual(proc.stdout + proc.stderr, SNAPSHOT.read_text())

    def test_the_snapshot_still_says_what_it_is_supposed_to_say(self):
        """A snapshot nobody reads can be regenerated wrong. These three facts are the point of it:
        the two historical breaches stay ACKNOWLEDGED and the 2026-08-25 take stays INVALID."""
        text = SNAPSHOT.read_text()
        self.assertEqual(text.count("ACKNOWLEDGED SAFETY FINDING"), 2)
        self.assertIn("INVALID: eval/results/live_flight_log_20260825T210402Z.json", text)
        self.assertIn("gt_cpa_m 0.0067 m", text)


# ================================================================================================
# 12. QA ROUND 1 (qa-safety, 2026-09-07) -- the two ENFORCEMENT pins the bars above were missing
# ================================================================================================
# FOUND BY MUTATION, not by reading. Rewriting bar 4's two `problems.append(...)` calls as
# `notes.append(...)` -- i.e. turning the frustum bar from a FAILURE into a remark -- left all 65
# tests above GREEN. The cause is a CONFOUND, not an oversight: bar 4's red fixtures place the
# detection 20 m out, which independently trips bar 5 (20 m < the 33.591 m breakeven), so
# `assertInvalid` was satisfied by the ACQUISITION problem while the frustum text was found among
# the NOTES. Nothing in the file proved bar 4 could make a log INVALID.
#
# That matters more than a missing assertion usually does. Bar 4 is the confidently-wrong-perception
# bar: it is the only gate that asks whether the sensor could have made the detection an accepted
# dodge was flown on (a wrong pose pair, a stale pair at cruise, a wrong un-projection). A gate that
# silently degrades to a remark is the "vacuous green" family wearing a gate's clothes.
#
# The fix is the fixture, not the gate: put the out-of-frustum detection at a range bar 5 is HAPPY
# with (>= 33.591 m), so the only problem on the log is the frustum one, and assert on the gate's
# own `problems` list rather than on the joined message blob.
class TestBar4EnforcesRatherThanReports(Harness):
    OFF_AXIS_DEG = 40.0                      # against a 31.607 deg half-angle
    FAR_M = 40.0                             # >= BREAKEVEN_ACQUISITION_M, so bar 5 stays silent

    def _off_axis_pos(self):
        off = math.radians(self.OFF_AXIS_DEG)
        return (DRONE_AT_DET[0] + self.FAR_M * math.cos(off),
                DRONE_AT_DET[1] + self.FAR_M * math.sin(off), CRUISE_Z)

    def _behind_pos(self):
        return (DRONE_AT_DET[0] - self.FAR_M, DRONE_AT_DET[1], CRUISE_Z)

    def test_the_fixtures_really_are_unconfounded_by_bar_5(self):
        """The premise of the two tests below: at 40 m the BREAKEVEN comparison is green, so an
        `ACQUISITION BELOW BREAKEVEN` can never be what makes these logs INVALID.

        Bar 5 grew a geometry conjunct in QA round 2 (a range this sensor cannot have measured is
        refused, not credited), so the BEHIND fixture now trips that too -- from the other side of
        the same fact. It is still not the breakeven, and bar 4's own `problems` list is asserted
        directly below, so neither test can be satisfied by a neighbour."""
        for pos, also in ((self._off_axis_pos(), None),
                          (self._behind_pos(), "ACQUISITION BEHIND THE CAMERA")):
            with self.subTest(pos=pos):
                log = depth_log(events=encounter_events(det=detection_event(pos=pos)))
                self.assertAlmostEqual(checker.depth_detections(log)[0]["range_m"], self.FAR_M,
                                       places=9)
                acq_problems, _notes, _m = checker.gate_depth_acquisition(log, log["run"])
                self.assertNotIn("ACQUISITION BELOW BREAKEVEN", " ".join(acq_problems))
                if also is None:
                    self.assertEqual(acq_problems, [])
                else:
                    self.assertEqual(len(acq_problems), 1, msg=str(acq_problems))
                    self.assertIn(also, acq_problems[0])

    def test_a_detection_outside_the_frustum_is_a_PROBLEM(self):
        pos = self._off_axis_pos()
        log = depth_log(events=encounter_events(det=detection_event(pos=pos)))
        problems, _notes, _measured = checker.gate_depth_frustum(log, log["run"])
        self.assertEqual(len(problems), 1, msg=str(problems))
        self.assertIn("DETECTION OUTSIDE THE FRUSTUM", problems[0])
        # ...and it is the ONLY thing that fails this flight, end to end.
        status, messages = self.green(log, truth_pos=pos)
        self.assertEqual(status, checker.INVALID, msg=" ".join(messages))
        self.assertNotIn("ACQUISITION BELOW BREAKEVEN", " ".join(messages))

    def test_a_detection_behind_the_camera_is_a_PROBLEM(self):
        pos = self._behind_pos()
        log = depth_log(events=encounter_events(det=detection_event(pos=pos)))
        problems, _notes, _measured = checker.gate_depth_frustum(log, log["run"])
        self.assertEqual(len(problems), 1, msg=str(problems))
        self.assertIn("DETECTION BEHIND THE CAMERA", problems[0])
        status, messages = self.green(log, truth_pos=pos)
        self.assertEqual(status, checker.INVALID, msg=" ".join(messages))
        self.assertNotIn("ACQUISITION BELOW BREAKEVEN", " ".join(messages))


# Bar 7's whole content is "must print `N/A (depth take)` IN THOSE WORDS". Every assertion above
# spells that requirement as `checker.NA_DEPTH`, which is the constant the gate itself prints -- so
# rewriting `NA_DEPTH = "not applicable"` left all 65 tests green (mutation, QA 2026-09-07). A pin
# that reads the value under test cannot pin the value. The words are asserted here as LITERALS, and
# against the pre-registration that demanded them.
class TestBar7WordsAreLiteral(Harness):
    WORDS = "N/A (depth take)"

    def test_the_constant_is_the_pre_registered_wording(self):
        self.assertEqual(checker.NA_DEPTH, self.WORDS)
        self.assertIn(self.WORDS, PREREG.read_text())

    def test_the_words_really_reach_the_output(self):
        messages = self.green()[1]
        said = [m for m in messages if self.WORDS in m]
        self.assertEqual(len(said), len(TestBar7NotApplicable.FAMILIES), msg=str(said))


# ================================================================================================
# 13. QA ROUND 2 (qa-safety, 2026-09-07) -- two holes IN the bars, both reading as success
# ================================================================================================
# Neither is a deviation from a pre-registered bar; both are things the bars did not say and the
# implementation faithfully inherited. Both fixes are STRICTLY TIGHTENING -- they can only turn a
# credited number into a refused one, never the reverse -- and both are red-first here.
class TestBar5RefusesARangeTheSensorCannotMeasure(Harness):
    """Bar 5 is the ONLY bar whose failure class is INVALID-for-authorisation, and as pre-registered
    it compares one number against 33.591 m and nothing else. So a first detection at 500 m from a
    block whose own `max_range_m` is 60.0 printed "at or beyond the breakeven" and the take was
    VALID. The bar that decides authorisation was the one bar with no plausibility check, in the
    direction that reads as success -- and P2's fix for bar 5's censoring (getting the seam's
    longest-range detection into the artifact) is exactly the work that will start feeding this bar
    raw un-projected ranges, i.e. the one number a wrong un-projection produces."""

    def far_log(self, metres, **block_over):
        pos = (DRONE_AT_DET[0] + metres, DRONE_AT_DET[1], CRUISE_Z)
        return pos, depth_log(events=encounter_events(det=detection_event(pos=pos)),
                              detector=real_depth_block(**block_over))

    def test_red_a_range_beyond_anything_the_block_declares_is_refused_not_credited(self):
        pos, log = self.far_log(500.0)
        text = self.assertInvalid(self.green(log, truth_pos=pos),
                                  "ACQUISITION RANGE THIS SENSOR CANNOT MEASURE")
        self.assertIn("FURTHER than max_range_m", text)
        self.assertIn("max_range_m 60", text)                      # the block's OWN number
        self.assertNotIn("at or beyond the breakeven", text)       # never credited

    def test_the_upper_bound_is_the_FRUSTUM_CORNER_s_not_the_bare_max(self):
        """The exact bound, so this can never fire on a sound log: the camera sits 0.15 m ahead of
        the body origin and every detection came through a pixel, so a position at range R implies
        an along-axis depth of at least (R - 0.15) / corner, where corner = sqrt(1 + tan^2 h +
        tan^2 v) = 1.2616 at this sensor. 60 m x 1.2616 + 0.15 = 75.85 m: below it the gate says
        nothing, above it no in-frustum depth the seam would have accepted can explain the point."""
        corner = math.sqrt(1.0 + (320.0 / 520.0058) ** 2 + (240.0 / 520.0058) ** 2)
        bound = 60.0 * corner + checker.DEPTH_MOUNT_FORWARD_M
        self.assertAlmostEqual(bound, 75.848, places=3)
        for metres, refused in ((bound - 1.0, False), (bound + 1.0, True)):
            with self.subTest(metres=metres):
                pos, log = self.far_log(metres)
                problems, _n, _m = checker.gate_depth_acquisition(log, log["run"])
                self.assertEqual(bool(problems), refused, msg=str(problems))

    def test_red_a_range_nearer_than_the_declared_minimum(self):
        """Asserted on the gate's own `problems`, not on the message blob: at 1.0 m the BREAKEVEN
        half of bar 5 fails too, so an `assertInvalid` here would be satisfied by that instead and
        would survive this refusal being demoted to a remark."""
        pos, log = self.far_log(1.0, min_range_m=3.0)
        problems, _n, _m = checker.gate_depth_acquisition(log, log["run"])
        hit = [p for p in problems if "ACQUISITION RANGE THIS SENSOR CANNOT MEASURE" in p]
        self.assertEqual(len(hit), 1, msg=str(problems))
        self.assertIn("NEARER than min_range_m", hit[0])
        self.assertIn("min_range_m 3", hit[0])
        self.assertInvalid(self.green(log, truth_pos=pos),
                           "ACQUISITION RANGE THIS SENSOR CANNOT MEASURE")

    def test_red_a_detection_BEHIND_the_camera_on_a_tick_with_no_accepted_maneuver(self):
        """The second half of the same hole. Bar 4 is scoped to ACCEPTED maneuvers as
        pre-registered, so a first detection 40 m BEHIND the vehicle on a tick carrying only a hold
        was credited as a 40 m acquisition and the take was VALID."""
        pos = (DRONE_AT_DET[0] - 40.0, DRONE_AT_DET[1], CRUISE_Z)
        events = [e for e in encounter_events(det=detection_event(pos=pos))
                  if e["kind"] != "maneuver"]
        log = depth_log(events=events)
        text = self.assertInvalid(self.green(log, truth_pos=pos), "ACQUISITION BEHIND THE CAMERA")
        self.assertIn("Bar 4 does NOT catch it here", text)
        self.assertIn("FRUSTUM CONTAINMENT UNMEASURED", text)      # ...which is why bar 5 must
        self.assertNotIn("at or beyond the breakeven", text)

    def test_red_the_block_must_DECLARE_the_window_it_is_judged_against(self):
        for missing in ("min_range_m", "max_range_m"):
            with self.subTest(missing=missing):
                block = real_depth_block()
                block.pop(missing)
                log = depth_log(detector=block)
                text = self.assertInvalid(self.green(log), "ACQUISITION RANGE BOUNDED BY NOTHING")
                self.assertIn("_depth_detector_log_block", text)

    def test_red_a_nonsense_window_is_refused_too(self):
        _pos, log = self.far_log(40.0, min_range_m=60.0, max_range_m=0.1)
        self.assertInvalid(self.green(log), "ACQUISITION RANGE BOUNDED BY NOTHING")

    def test_green_the_plausible_range_is_still_credited(self):
        text = self.assertValid(self.green())
        self.assertIn("at or beyond the breakeven", text)
        self.assertNotIn("CANNOT MEASURE", text)
        self.assertNotIn("BOUNDED BY NOTHING", text)

    def test_the_window_the_gate_reads_is_the_seams_own(self):
        """`min_range_m`/`max_range_m` are the EXCLUSIVE window `box_to_detection` refuses outside
        of -- read off the seam that flew, not written down here."""
        source = depth_detect.DepthDetectionSource(DepthSegmenter(), intr=INTRINSICS)
        block = real_depth_block()
        self.assertEqual(checker._declared_range_window({"detector": block}),
                         (source.min_range_m, source.max_range_m))


class TestImpossibleCountersAreRefused(Harness):
    """"A counter that is absent is not a counter that is zero" was already the gate's doctrine. The
    missing half: a counter LARGER than its own denominator is not a counter at all -- and the
    runtime bars could be skipped entirely by one that cannot occur on a flown log."""

    def test_green_the_healthy_fixture_satisfies_every_relation(self):
        values, _raw, problem = checker.depth_detector_counters(depth_log()["run"])
        self.assertIsNone(problem)
        self.assertEqual(checker.depth_counter_contradictions(values), [])

    def test_the_relations_are_the_SEAMS_OWN_ARITHMETIC_not_this_gates_opinion(self):
        """Driven through the real `DepthDetectionSource` over every path `on_frame` has -- no
        intrinsics, a shape mismatch, no pose pair, a stale pair, and a clean frame -- so the gate's
        model of the counters is pinned to the code that writes them."""
        import numpy as np

        good = np.full((480, 640), 30.0, dtype=np.float32)
        source = depth_detect.DepthDetectionSource(DepthSegmenter(), intr=None)
        pose, quat = (0.0, 0.0, 15.0), (0.0, 0.0, 0.0, 1.0)
        source.on_frame(1.0, good, pose, quat)                       # no intrinsics
        source.set_intrinsics(INTRINSICS)
        source.on_frame(2.0, np.full((240, 320), 30.0, dtype=np.float32), pose, quat)  # shape
        source.on_frame(3.0, good, None, None)                       # no pose pair
        source.on_frame(4.0, good, pose, quat, pose_pair_residual_s=99.0)   # stale pair
        source.on_frame(5.0, good, pose, quat)                       # clean
        c = source.counters()
        self.assertEqual(c["depth_msgs_received"], 5)
        self.assertEqual(c["detect_wall_ms_n"], c["depth_msgs_received"])   # timed in a `finally`
        self.assertEqual(c["dropped_no_intrinsics"] + c["dropped_frame_shape_mismatch"]
                         + c["dropped_no_pose_pair"] + c["dropped_stale_pose_pair"]
                         + c["frames_detected_on"], c["depth_msgs_received"])
        self.assertLessEqual(c["frames_with_detection"], c["frames_detected_on"])
        self.assertGreaterEqual(c["boxes_total"], c["frames_with_detection"])
        values = {k: float(c[k]) for k in checker.DEPTH_DETECTOR_COUNTER_KEYS}
        self.assertEqual(checker.depth_counter_contradictions(values), [])

    def test_red_a_detect_rate_over_1_0_cannot_clear_the_floor(self):
        """`frames_detected_on: 5000` over 1200 is a rate of 4.17 and passed bar 1 in silence."""
        log = depth_log(detector=real_depth_block({"frames_detected_on": 5000}))
        text = self.assertInvalid(self.green(log), "IMPOSSIBLE COUNTERS")
        self.assertIn("depth_msgs_received = 1200", text)
        self.assertIn("exactly one of those five paths", text)

    def test_red_more_frames_with_a_detection_than_frames_looked_at(self):
        log = depth_log(detector=real_depth_block({"frames_with_detection": 99999,
                                                   "boxes_total": 99999}))
        text = self.assertInvalid(self.green(log), "IMPOSSIBLE COUNTERS")
        self.assertIn("frames_with_detection 99999 > frames_detected_on 1199", text)

    def test_red_fewer_boxes_than_frames_that_had_one(self):
        log = depth_log(detector=real_depth_block({"boxes_total": 3}))
        text = self.assertInvalid(self.green(log), "IMPOSSIBLE COUNTERS")
        self.assertIn("boxes_total 3 < frames_with_detection 40", text)

    def test_red_a_drop_count_that_does_not_balance(self):
        log = depth_log(detector=real_depth_block({"dropped_no_pose_pair": 7}))
        self.assertInvalid(self.green(log), "IMPOSSIBLE COUNTERS")

    def test_red_zero_timed_frames_over_a_live_denominator_is_a_CONTRADICTION(self):
        """THE SKIP THAT WAS FREE: `detect_wall_ms_n: 0` printed UNMEASURED and the log was VALID --
        in a block claiming p95 125 ms and max 300 ms, 5x and 3x the bars, read by nothing."""
        log = depth_log(detector=real_depth_block({"detect_wall_ms_n": 0,
                                                   "detect_wall_ms_p95": 125.0,
                                                   "detect_wall_ms_max": 300.0}))
        # On the gate's OWN problems list: the p95 over its bar makes this log INVALID by itself, so
        # a blob assertion would survive the contradiction being demoted to a note.
        problems, _n = checker.gate_depth_detector_ran(log, log["run"])[:2]
        hit = [p for p in problems if "IMPOSSIBLE RUNTIME DENOMINATOR" in p]
        self.assertEqual(len(hit), 1, msg=str(problems))
        self.assertIn("times EVERY call in a `finally`", hit[0])
        self.assertIn("125.0", hit[0])                 # it quotes what the block claimed
        text = self.assertInvalid(self.green(log), "IMPOSSIBLE RUNTIME DENOMINATOR")
        # ...and the numbers it was hiding are now read against their bars as well.
        self.assertIn("detect_wall_ms_p95 125.000 ms exceeds 25 ms", text)
        self.assertIn("detect_wall_ms_max 300.000 ms exceeds 100 ms", text)

    def test_red_even_a_one_frame_gap_is_a_contradiction(self):
        """The bug this file shipped with: the HEALTHY fixture said 1199 timed of 1200 received."""
        log = depth_log(detector=real_depth_block({"detect_wall_ms_n": 1199}))
        text = self.assertInvalid(self.green(log), "IMPOSSIBLE RUNTIME DENOMINATOR")
        self.assertIn("A gap of 1 frame(s)", text)

    def test_zero_timed_frames_over_a_zero_denominator_is_still_only_UNMEASURED(self):
        """The one combination that is honest: no frame arrived, so none was timed. Bar 1 has
        already failed that take for having no denominator -- this must not double-count it as a
        contradiction as well."""
        nothing = dict(dict.fromkeys(HEALTHY_COUNTERS, 0),
                       detect_wall_ms_p95=None, detect_wall_ms_max=None)
        log = depth_log(detector=real_depth_block(nothing))
        problems, notes, = checker.gate_depth_detector_ran(log, log["run"])[:2]
        self.assertIn("detect wall time UNMEASURED", " ".join(notes))
        self.assertNotIn("IMPOSSIBLE RUNTIME DENOMINATOR", " ".join(problems))


class TestTheMeasuredCountIsInTheArtifact(Harness):
    """A depth take that logged no encounter at all is VALID with exit 0 and four bars reading
    UNMEASURED. Each of them says "Never a PASS"; the verdict word and the exit code -- what CI and
    the runbook's step 1 actually read -- do not. The count is the honest half of that. Whether a
    BOOKED dodge take with no encounter should be AMBIGUOUS rather than VALID is a product-lead
    call and is NOT decided here."""

    def test_a_take_with_no_encounter_counts_all_four_as_unmeasured(self):
        text = self.assertValid(self.green(depth_log(events=[])))
        self.assertIn("DEPTH BARS MEASURED: 0 of 4", text)
        for bar in ("3b range error", "5 acquisition", "4 frustum", "6 static map"):
            with self.subTest(bar=bar):
                self.assertIn(f"bar {bar}: UNMEASURED", text)

    def test_the_count_moves_with_the_evidence(self):
        """The green take measures three: bar 6 stays UNMEASURED because `_log_detection` does not
        carry the hint (see TestBar6StaticMap)."""
        self.assertIn("DEPTH BARS MEASURED: 3 of 4", self.assertValid(self.green()))
        log = depth_log(events=encounter_events(det=detection_event(static_map_hint=None)))
        self.assertIn("DEPTH BARS MEASURED: 4 of 4", self.assertValid(self.green(log)))

    def test_no_truth_takes_the_range_bar_out_of_the_count(self):
        log = depth_log()
        p = self.dir / "live_flight_log_TEST.json"
        p.write_text(json.dumps(log))
        _status, messages = checker.check_file(p, truth=None, results_dir=self.dir)
        self.assertIn("DEPTH BARS MEASURED: 2 of 4", " ".join(messages))


class TestTheRunbookDoesNotTellAnOperatorToScoreNothing(unittest.TestCase):
    """`AVOIDANCE_REAL_DETECTION.md` §1a is the DEPTH-SOURCE shell-8 procedure -- the section a human
    executes at the MAVProxy prompt. It still ends "**Then score nothing.** ... a `depth_blob` log is
    refused by `check_live_flight_log.py` as UNSCOREABLE", which since P1 landed is false, and
    following it skips step 1 of the pre-registration's own analysis plan.

    Six documents of record carry that stale claim; this diff was scoped to §5, so §5 supersedes the
    rest BY NAME. The assertion is a disjunction on purpose: it is green today because §5 says so,
    it stays green when someone fixes §1a properly, and it goes red if the supersession is deleted
    while the stale instruction is still in the file."""

    RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "AVOIDANCE_REAL_DETECTION.md"

    def test_either_1a_is_fixed_or_5_supersedes_it_by_name(self):
        doc = self.RUNBOOK.read_text()
        section_1a = doc.split("### 1a.", 1)[1].split("\n## ", 1)[0]
        section_5 = doc.split("## 5. Post-flight gates", 1)[1].split("\n## ", 1)[0]
        stale = "Then score nothing" in section_1a or "UNSCOREABLE" in section_1a
        if stale:
            self.assertIn("§1a", section_5)
            self.assertIn("SCOREABLE since 2026-09-07", section_5)

    def test_section_5_tells_the_operator_the_depth_take_IS_scored(self):
        section_5 = self.RUNBOOK.read_text().split("## 5. Post-flight gates", 1)[1]
        self.assertIn("SCOREABLE since 2026-09-07", section_5)
        self.assertIn("seven bars", section_5)

    def test_the_claim_it_makes_about_the_code_is_true(self):
        self.assertIn(checker.DET_DEPTH_BLOB, checker.DETECTOR_SOURCES)


# ================================================================================================
# 14. THE DECLARED BIRD-LESS FLIGHT -- `--no-birds` (2026-09-11, ADR-020 am. 6's checker gap)
# ================================================================================================
# THE GAP, MEASURED ON A REAL TAKE. The P2 step-0 depth flight drove no birds by design, so no
# `bird_drive_*_applied.jsonl` was ever written for it -- and because Gazebo sim time restarts near
# 0 every run, two OLD applied logs overlapped its window. The gate printed "ambiguous truth track"
# and INVALID, with no way to be told there was nothing to track. "We could not tell" and "there was
# nothing to tell" had landed on the same verdict.
#
# WHAT THESE TESTS MUST PROVE, and the order matters: first that the flag CLOSES the gap, then that
# it cannot LAUNDER anything. A mode that turns an INVALID log green is worse than the gap it fixes,
# so every falsifier gets a fixture that fails the gate under test -- the takeover, the in-cylinder
# detection, the self-named truth file, the reviewed pin -- plus the one that matters most: the real
# 2026-09-11 log, still INVALID under the flag, on its runtime bar and nothing else.
NO_BIRDS_PROCEED = "no in-cylinder threat"


def birdless_events(n=len(PATH)):
    """A wiring flight's whole event log: one `proceed` per tick and nothing else.

    Shaped after the real 2026-09-11 take, whose 6090 events were `proceed` x6089 plus one
    `divert_audit_summary` -- no takeover, no maneuver, no detection, because nothing was ever in
    the cylinder."""
    return [{"seq": i, "tick": i + 1, "kind": "proceed", "position_enu": list(PATH[i]),
             "reason": NO_BIRDS_PROCEED,
             "debug": {"n_detections": 0, "threat_radius_m": PolicyParams().threat_radius_m,
                       "vertical_threat_m": PolicyParams().vertical_threat_m}}
            for i in range(n)]


def birdless_depth_log(extra_events=(), **over):
    return depth_log(events=list(birdless_events()) + list(extra_events), **over)


class NoBirdsHarness(Harness):
    # THE FIXTURE FLIES UNDER A REAL UTC STEM, and that is now load-bearing: falsifier 5 places this
    # take on the WALL clock (the one clock Gazebo does not restart) and a log whose NAME carries no
    # stamp cannot be separated in time from the bird tracks beside it -- a refusal of its own
    # (TestTheWallClockFalsifier). `avoidance_node` always writes `live_flight_log_<UTC>.json`.
    # 2026-09-11T09:42:35Z is the real wiring take's stamp; the stale tracks below are 16.5 days
    # from it, which is the separation the whole mode leans on.
    NAME = "live_flight_log_20260911T094235Z.json"

    def check(self, log, truth=None, name=None, no_birds=False):
        return super().check(log, truth=truth, name=name or self.NAME, no_birds=no_birds)

    def two_stale_truths(self):
        """The 2026-09-11 situation, reproduced: two applied logs from OTHER takes overlapping this
        flight's sim window. Sim time restarts near 0 every run, so overlap is the default, not the
        exception -- which is why the scan can only ever report ambiguity here."""
        self.write_truth(bird_parked_at(PARKED), stamp="20260823T073836Z")
        self.write_truth(bird_parked_at(PARKED), stamp="20260825T210030Z")

    def na_lines(self, text_lines):
        return [m for m in text_lines if checker.NA_NO_BIRDS in m]

    def assertRefused(self, result, needle):
        text = self.assertInvalid(result, "--no-birds REFUSED")
        self.assertIn(needle, text)
        # A refused declaration scores NOTHING -- no gate may report on a fiction.
        self.assertNotIn(checker.NA_NO_BIRDS, text)
        return text


class TestTheGapItCloses(NoBirdsHarness):
    def test_without_the_flag_a_birdless_take_is_INVALID_on_ambiguity(self):
        """The bug, pinned first: this log is honest, complete and unscoreable."""
        self.two_stale_truths()
        self.assertInvalid(self.check(birdless_depth_log()), "ambiguous truth track")

    def test_with_the_flag_the_same_log_is_VALID(self):
        self.two_stale_truths()
        text = self.assertValid(self.check(birdless_depth_log(), no_birds=True))
        self.assertNotIn("ambiguous truth track", text)
        self.assertNotIn("no truth track", text)

    def test_the_verdict_block_says_a_DECLARATION_produced_the_N_A_lines(self):
        """(e) of the design: a reader must be able to tell a declaration from a measurement."""
        self.two_stale_truths()
        _status, messages = self.check(birdless_depth_log(), no_birds=True)
        self.assertIn("truth: none (declared --no-birds)", " ".join(messages))

    def test_every_CPA_family_line_says_N_A_in_those_words_and_none_of_them_PASSES(self):
        self.two_stale_truths()
        _status, messages = self.check(birdless_depth_log(), no_birds=True)
        na = self.na_lines(messages)
        # FIVE, and the count is the assertion: the declaration itself, gt_cpa_m, the
        # truth-coverage denominators, depth bar 3b (the truth-referenced range error) and the
        # DEPTH BARS MEASURED summary that has to agree with 3b. A sixth means a gate started
        # printing N/A that was never in the truth family; four means one stopped.
        self.assertEqual(len(na), 5, msg="\n".join(na))
        for line in na:
            # "Never a PASS" is this gate's house phrase for exactly this situation, so the
            # assertion is that no N/A line CLAIMS one -- strip the disclaimer, then no PASS may
            # remain anywhere in the sentence.
            self.assertNotIn("PASS", re.sub(r"[Nn]ever (a )?PASS", "", line))
        joined = " ".join(na)
        for needle in ("gt_cpa_m", "truth coverage", "RANGE ERROR", "DEPTH BARS MEASURED"):
            self.assertIn(needle, joined)

    def test_gt_cpa_m_is_never_given_a_NUMBER(self):
        """`N/A`, not `0.0000 m`. A zero would read as a breach; any number would be invented."""
        self.two_stale_truths()
        _status, messages = self.check(birdless_depth_log(), no_birds=True)
        self.assertEqual([], [m for m in messages if re.search(r"gt_cpa_(gated_)?m\s+-?[\d.]", m)])

    def test_the_NDVI_arm_of_the_family_names_the_estimator_check_too(self):
        """A bird-less take on the NADIR detector is scored by the same flag, and prints one line
        the depth arm does not: the monocular estimator check and the in-cylinder missed-detection
        signal. Both are measured against the truth track, so both are N/A here."""
        depth_notes = checker.no_birds_notes(True, "falsifiers scanned: (fixture)")
        ndvi_notes = checker.no_birds_notes(False, "falsifiers scanned: (fixture)")
        self.assertEqual(len(ndvi_notes), len(depth_notes) + 1)
        self.assertIn("detection_cpa_m", ndvi_notes[-1])
        for line in ndvi_notes:
            self.assertIn(checker.NA_NO_BIRDS, line)

    def test_the_depth_bar_summary_calls_3b_N_A_rather_than_UNMEASURED(self):
        """One word for one fact: UNMEASURED means the evidence could have been there."""
        self.two_stale_truths()
        _status, messages = self.check(birdless_depth_log(), no_birds=True)
        (summary,) = [m for m in messages if m.startswith("DEPTH BARS MEASURED")]
        self.assertIn(f"bar {checker.DEPTH_BAR_NEEDS_TRUTH}: {checker.NA_NO_BIRDS}", summary)
        self.assertIn("bar 5 acquisition: UNMEASURED", summary)      # still a live bar, untouched


class TestEveryOtherGateStaysLive(NoBirdsHarness):
    """(c) of the design. The flag skips the truth join and NOTHING else -- proved by making each
    surviving gate FAIL under the flag, which is the only way to know it still bites."""

    def setUp(self):
        super().setUp()
        self.two_stale_truths()

    def test_the_runtime_max_bar_still_fails(self):
        log = birdless_depth_log(
            detector=real_depth_block({"detect_wall_ms_max": 141.16}))
        self.assertInvalid(self.check(log, no_birds=True), "DETECT WALL TIME OVER BAR")

    def test_the_detect_rate_floor_still_fails(self):
        log = birdless_depth_log(detector=real_depth_block(
            {"frames_detected_on": 0, "dropped_no_intrinsics": 1200, "frames_with_detection": 0,
             "boxes_total": 0}))
        self.assertInvalid(self.check(log, no_birds=True), "DEPTH DETECTOR NEVER RAN")

    def test_the_frame_shape_bar_still_fails(self):
        log = birdless_depth_log(detector=real_depth_block(
            {"frames_detected_on": 1190, "dropped_frame_shape_mismatch": 9}))
        self.assertInvalid(self.check(log, no_birds=True), "FRAME SHAPE MISMATCH")

    def test_the_clock_gate_still_fails(self):
        log = birdless_depth_log()
        log["run"]["clock"]["source"] = "wall"
        self.assertInvalid(self.check(log, no_birds=True), "clock")

    def test_the_ledger_invariant_still_fails(self):
        log = birdless_depth_log()
        log["coverage_ledger"] = [dict(r, status="debt") for r in LEDGER]
        self.assertInvalid(self.check(log, no_birds=True), "debt")

    def test_the_booked_speed_gate_still_fails(self):
        booking = self.dir / "booking_gate_TEST.json"
        booking.write_text(json.dumps(json.loads(
            (REPO_ROOT / "eval" / "results" / "booking_gate_20260907T064136Z.json").read_text())))
        # PATH is 1.0 m per 0.2 s tick = 5.0 m/s at cruise; halve the booked speed and the same
        # flight is twice its authorisation.
        rep = json.loads(booking.read_text())
        rep["encounter"]["mission_speed_mps"] = 2.0
        booking.write_text(json.dumps(rep))
        p = self.dir / self.NAME
        p.write_text(json.dumps(birdless_depth_log()))
        status, messages = checker.check_file(p, results_dir=self.dir, booking=booking,
                                              no_birds=True)
        self.assertEqual(status, checker.INVALID, " ".join(messages))
        self.assertIn("FLOWN FASTER THAN BOOKED", " ".join(messages))

    def test_a_stale_acknowledgement_marker_is_still_a_defect(self):
        p = self.dir / self.NAME
        p.write_text(json.dumps(birdless_depth_log()))
        (self.dir / self.NAME.replace(".json", ".SAFETY_FINDING.md")).write_text("# finding\n")
        status, messages = checker.check_file(p, results_dir=self.dir, no_birds=True)
        self.assertEqual(status, checker.INVALID, " ".join(messages))
        self.assertIn("stale acknowledgement marker", " ".join(messages))


class TestTheDeclarationIsRefusable(NoBirdsHarness):
    """(d) of the design: the four falsifiers that read THIS FLIGHT'S LOG. A declaration nothing can
    contradict is a hole -- and so is one that only the detector can contradict, which is why
    falsifiers 5 and 6 have classes of their own below."""

    def setUp(self):
        super().setUp()
        self.two_stale_truths()

    def test_a_takeover_event_refuses_it(self):
        takeover = {"seq": 99, "tick": 2, "kind": "takeover", "reason": "divert",
                    "from_mode": "AUTO", "to_mode": "GUIDED", "wp_index_at_takeover": 3,
                    "track_id": None}
        text = self.assertRefused(self.check(birdless_depth_log([takeover]), no_birds=True),
                                  "`takeover` at tick 2")
        self.assertIn("takeover x1", text)

    def test_every_threat_only_event_kind_refuses_it(self):
        """One fixture per kind, so a kind quietly dropped from the list is a red test."""
        for kind in checker.TARGET_EVIDENCE_KINDS:
            with self.subTest(kind=kind):
                ev = {"seq": 99, "tick": 3, "kind": kind, "track_id": None}
                self.assertRefused(self.check(birdless_depth_log([ev]), no_birds=True),
                                   f"`{kind}` at tick 3")

    def test_a_proceed_only_log_is_NOT_refused(self):
        """The other half of the pin above: the kinds that a bird-less flight legitimately writes
        must not refuse it, or the flag would be unusable on the flight it was built for."""
        self.assertValid(self.check(birdless_depth_log(), no_birds=True))

    def test_a_detection_INSIDE_the_threat_cylinder_refuses_it(self):
        pp = PolicyParams()
        inside = (DRONE_AT_DET[0] + pp.threat_radius_m - 2.0, DRONE_AT_DET[1], CRUISE_Z)
        text = self.assertRefused(
            self.check(birdless_depth_log([detection_event(pos=inside)]), no_birds=True),
            "INSIDE the policy's own threat cylinder")
        self.assertIn("run.policy_params", text)

    def test_a_canopy_at_30_m_and_11_m_below_is_ALLOWED(self):
        """The case the flag exists for: the 2026-09-11 take boxed 33,029 mapped canopies and every
        one of them fell outside the cylinder. If that refused the declaration, no depth wiring
        flight could ever be declared bird-less."""
        canopy = (DRONE_AT_DET[0] + 30.0, DRONE_AT_DET[1], CRUISE_Z - 11.0)
        self.assertValid(self.check(birdless_depth_log([detection_event(pos=canopy)]),
                                    no_birds=True))

    def test_the_cylinder_boundary_is_inclusive_exactly_as_the_policy_is(self):
        """`AvoidancePolicy._threats` tests `<=` on both axes; so does this."""
        pp = PolicyParams()
        on_the_rim = (DRONE_AT_DET[0] + pp.threat_radius_m, DRONE_AT_DET[1],
                      CRUISE_Z + pp.vertical_threat_m)
        self.assertRefused(self.check(birdless_depth_log([detection_event(pos=on_the_rim)]),
                                      no_birds=True),
                           "INSIDE the policy's own threat cylinder")

    def test_a_detection_the_gate_cannot_PLACE_refuses_it(self):
        """Unplaceable is not outside. "We could not tell" may not clear a declaration."""
        unplaceable = dict(detection_event(), position_enu=None)
        self.assertRefused(self.check(birdless_depth_log([unplaceable]), no_birds=True),
                           "cannot PLACE")

    def test_a_truth_FILENAME_anywhere_in_the_log_refuses_it(self):
        log = birdless_depth_log()
        log["note"] = "flown against bird_drive_20260825T210030Z_applied.jsonl"
        self.assertRefused(self.check(log, no_birds=True), "names bird ground-truth file(s)")

    def test_a_stem_pinned_in_TRUTH_BINDINGS_refuses_it(self):
        """A reviewed diff already joined that take to a bird track; a command-line word does not
        get to overrule it -- the same doctrine that stops `--truth` overriding a binding."""
        (stem,) = list(checker.TRUTH_BINDINGS)[:1]
        self.assertRefused(self.check(birdless_depth_log(), name=f"{stem}.json", no_birds=True),
                           "TRUTH_BINDINGS")

    def test_the_refusal_names_the_way_back(self):
        takeover = {"seq": 99, "tick": 2, "kind": "takeover", "track_id": None}
        text = self.assertRefused(self.check(birdless_depth_log([takeover]), no_birds=True),
                                  "Re-run WITHOUT --no-birds")
        self.assertIn("--truth", text)

    def test_it_refuses_on_the_LEGACY_path_too(self):
        """Declaration checking happens before the schema dispatch, so a pre-seam log (whose CPA is
        measured against its own detections) cannot be declared bird-less either."""
        legacy = birdless_depth_log([detection_event(pos=DRONE_AT_DET)])
        del legacy["run"]
        stem = checker.PRE_SEAM_LEGACY_STEMS[0]
        self.assertRefused(self.check(legacy, name=f"{stem}.json", no_birds=True),
                           "INSIDE the policy's own threat cylinder")

    def test_truth_and_no_birds_cannot_both_be_true_in_process(self):
        truth = self.write_truth(bird_parked_at(PARKED), stamp="20260907T120000Z")
        self.assertInvalid(self.check(birdless_depth_log(), truth=truth, no_birds=True),
                           "cannot both be true")


class TestTheRealWiringFlight(NoBirdsHarness):
    """(e) of the design, on the REAL 2026-09-11 artifact -- the log that named the gap.

    UNCOMMITTED BY DESIGN (it is INVALID, not a breach record: ADR-020 am. 6 keeps it out of git and
    its counters ride in the committed `depth_delivery_d5d6_*.json`), so this class SKIPS when the
    file is absent rather than pretending to have run."""

    LOG = (REPO_ROOT / "eval" / "results" / "step0_wiring_20260911"
           / "live_flight_log_20260911T094235Z.json")
    BOOKING = REPO_ROOT / "eval" / "results" / "booking_gate_20260907T064136Z.json"

    def setUp(self):
        super().setUp()
        if not self.LOG.exists():
            self.skipTest(f"the 2026-09-11 wiring flight is not in this checkout ({self.LOG})")
        self.log = json.loads(self.LOG.read_text())

    def score(self, log, **kw):
        p = self.dir / self.LOG.name
        p.write_text(json.dumps(log))
        return checker.check_file(p, results_dir=self.dir, booking=self.BOOKING, **kw)

    def test_it_still_fails_its_own_runtime_bar_under_the_flag(self):
        text = self.assertInvalid(self.score(self.log, no_birds=True),
                                  "DETECT WALL TIME OVER BAR")
        self.assertIn("141.160 ms exceeds 100 ms", text)
        self.assertNotIn("ambiguous truth track", text)

    def test_the_runtime_bar_is_the_ONLY_reason_it_is_invalid(self):
        """Proved by mutation rather than by counting message lines: put the one failing counter
        back inside its bar and the SAME take comes out VALID. Anything else still wrong with it
        would survive that edit and keep the log red."""
        healed = json.loads(json.dumps(self.log))
        healed["run"]["detector"]["counters"]["detect_wall_ms_max"] = 19.402
        self.assertValid(self.score(healed, no_birds=True))

    def test_the_wiring_flights_33029_canopy_boxes_do_not_refuse_the_declaration(self):
        """The take's own numbers: 2613 frames with a detection and 32,597 boxes near a mapped
        canopy, and NOT ONE of them reached the event log as a `detection` -- the loop engaged on 0
        ticks. That is why the declaration stands on this artifact."""
        self.assertEqual(checker.no_birds_refusal(self.log, self.LOG), [])
        self.assertEqual(checker.depth_detections(self.log), [])

    def test_without_the_flag_it_is_the_gap_ADR_020_am_6_recorded(self):
        """The gap itself, reproduced against the REAL eval/results (read-only): the two committed
        applied logs from OTHER takes overlap this flight's sim window, because Gazebo sim time
        restarts near 0 every run. Two problems, and only one of them is about the flight."""
        p = self.dir / self.LOG.name
        p.write_text(json.dumps(self.log))
        status, messages = checker.check_file(p, results_dir=REPO_ROOT / "eval" / "results",
                                              booking=self.BOOKING)
        text = " ".join(messages)
        self.assertEqual(status, checker.INVALID, text)
        self.assertIn("ambiguous truth track", text)
        self.assertIn("DETECT WALL TIME OVER BAR", text)


class TestTheCylinderTheRefusalTestsIsFloored(NoBirdsHarness):
    """The refusal reads `run.policy_params`, and the SAME RUN writes the knobs and the detections.
    Unfloored, that is a way to shrink the falsifier until nothing is inside it: QA measured it on
    the 2026-08-25 breach log (cylinder set to 0.1 m, four breach-close detections pushed "outside",
    declaration stands, VALID, exit 0). The floor is today's `PolicyParams()` and it is one-sided --
    a take that flew a WIDER cylinder is still judged against the wider one."""

    def shrunk(self, radius, vertical, pos):
        log = birdless_depth_log([detection_event(pos=pos)])
        log["run"]["policy_params"] = dict(log["run"]["policy_params"],
                                           threat_radius_m=radius, vertical_threat_m=vertical)
        return log

    def test_a_shrunken_cylinder_cannot_push_a_close_detection_outside(self):
        """0.21 m from the vehicle -- inside ANY honest cylinder, and outside a 0.1 m one."""
        near = (DRONE_AT_DET[0] + 0.21, DRONE_AT_DET[1], CRUISE_Z)
        text = self.assertRefused(self.check(self.shrunk(0.1, 0.1, near), no_birds=True),
                                  "INSIDE the policy's own threat cylinder")
        self.assertIn("WIDENED to today's floor", text)
        # ...and the message says what it flew, so a reader is not told a number the log denies.
        self.assertIn("threat_radius_m 0.1 m", text)

    def test_the_same_detection_under_the_flown_cylinder_is_what_it_always_was(self):
        """The control: unshrunk, that detection refuses for the ordinary reason and the provenance
        line does NOT claim a widening that did not happen."""
        near = (DRONE_AT_DET[0] + 0.21, DRONE_AT_DET[1], CRUISE_Z)
        text = self.assertRefused(self.check(birdless_depth_log([detection_event(pos=near)]),
                                             no_birds=True), "run.policy_params")
        self.assertNotIn("WIDENED", text)

    def test_a_WIDER_flown_cylinder_is_still_the_one_judged(self):
        """One-sided by construction: `max()` keeps the larger, so a take that flew a 40 x 20 m
        cylinder is refused on a canopy 30 m out that a 12 x 6 m cylinder would allow. (This is
        also the old `test_the_cylinder_is_the_FLIGHTS_OWN_not_todays_default`, retired into this
        class: the flown cylinder and its floor are one concept and belong in one place.)"""
        canopy = (DRONE_AT_DET[0] + 30.0, DRONE_AT_DET[1], CRUISE_Z - 11.0)
        self.assertRefused(self.check(self.shrunk(40.0, 20.0, canopy), no_birds=True),
                           "threat_radius_m 40 m")

    def test_the_floor_is_read_from_the_policy_not_retyped(self):
        pp = PolicyParams()
        radius, vertical, prov = checker.threat_cylinder({"policy_params": {
            "threat_radius_m": 0.1, "vertical_threat_m": 0.1}})
        self.assertEqual((radius, vertical), (pp.threat_radius_m, pp.vertical_threat_m))
        self.assertIn("PolicyParams()", prov)


class TestTheWallClockFalsifier(NoBirdsHarness):
    """FALSIFIER 5, and the reason it exists: falsifiers 1-4 are all DETECTOR-SIDE.
    `AvoidanceExecutor._log_detection` writes a `detection` only for a detection the policy already
    classified as an in-cylinder THREAT, so a bird the detector never saw leaves NO trace in the log
    -- a total false negative writes exactly the log a bird-less flight writes (QA, 2026-09-11).

    The wall clock is the one clock Gazebo does NOT restart. Sim time restarting near 0 every run is
    what made the truth scan ambiguous in the first place; the driver's own artifact is stamped in
    UTC, and on the real takes the separation is three orders of magnitude: 3.5 min for the take
    that drove birds, 23,802 min for the bird-less wiring take."""

    def test_a_bird_track_written_minutes_from_this_take_refuses_it(self):
        self.write_truth(bird_parked_at(PARKED), stamp="20260911T093235Z")      # -10.0 min
        text = self.assertRefused(self.check(birdless_depth_log(), no_birds=True),
                                  "bird-track artifact written 10.0 min")
        self.assertIn("bird_drive_20260911T093235Z", text)

    def test_the_total_false_negative_ladder_is_what_this_falsifier_is_for(self):
        """QA's ladder, step 4, which needs no tampering to reach: a flight whose detector saw
        NOTHING writes no avoidance event, no `detection` and boxes_total 0. Falsifiers 1-4 pass it
        unanimously. The driver's artifact 3.5 min away is what refuses it -- the same 3.5 min the
        real 2026-08-25 take (gt_cpa 0.0067 m) carries."""
        blind = birdless_depth_log(detector=real_depth_block(
            {"frames_with_detection": 0, "boxes_total": 0}))
        self.assertEqual(checker.no_birds_refusal(blind, self.dir / self.NAME, self.dir), [])
        self.write_truth(bird_parked_at(PARKED), stamp="20260911T093905Z")      # -3.5 min
        self.assertRefused(self.check(blind, no_birds=True), "3.5 min")

    def test_the_stale_tracks_16_days_out_do_not_refuse_it(self):
        """The control the mode exists for. Same log, same directory, tracks from OTHER takes."""
        self.two_stale_truths()
        self.assertValid(self.check(birdless_depth_log(), no_birds=True))

    def test_the_window_edge_is_the_constant_and_it_is_inclusive(self):
        """Mutation on the constant, not the fixture: 30 min 00 s refuses, 30 min 01 s does not."""
        self.write_truth(bird_parked_at(PARKED), stamp="20260911T091235Z")      # exactly -30 min
        self.assertRefused(self.check(birdless_depth_log(), no_birds=True), "30.0 min")
        for stale in self.dir.glob("bird_drive_*"):
            stale.unlink()
        self.write_truth(bird_parked_at(PARKED), stamp="20260911T091234Z")      # -30 min 01 s
        self.assertValid(self.check(birdless_depth_log(), no_birds=True))
        self.assertEqual(checker.BIRD_TRACK_WALL_WINDOW_S, 30.0 * 60.0)

    def test_the_sidecars_own_written_utc_beats_a_renamed_file(self):
        """`drive_birds.py` stamps the artifact from inside; renaming the file does not move it."""
        self.write_truth(bird_parked_at(PARKED), stamp="20260101T000000Z")
        sidecar = self.dir / "bird_drive_20260101T000000Z.json"
        sidecar.write_text(json.dumps(dict(json.loads(sidecar.read_text()),
                                           written_utc="2026-09-11T09:40:00Z")))
        self.assertRefused(self.check(birdless_depth_log(), no_birds=True), "2.6 min")

    def test_an_applied_log_with_no_sidecar_is_still_placed_by_its_name(self):
        (self.dir / "bird_drive_20260911T094000Z_applied.jsonl").write_text("{}\n")
        self.assertRefused(self.check(birdless_depth_log(), no_birds=True),
                           "bird_drive_20260911T094000Z_applied.jsonl")

    def test_a_track_that_cannot_be_PLACED_in_time_refuses_it(self):
        """Same rule as the unplaceable detection: "we could not tell" does not clear a
        declaration. A renamed track is the obvious way to put one out of the window."""
        (self.dir / "bird_drive_take.jsonl").write_text("{}\n")
        self.assertRefused(self.check(birdless_depth_log(), no_birds=True),
                           "wall-clock stamp cannot be read")

    def test_a_log_whose_own_NAME_has_no_stamp_cannot_run_the_falsifier(self):
        self.two_stale_truths()
        self.assertRefused(self.check(birdless_depth_log(), name="live_flight_log_TEST.json",
                                      no_birds=True), "NAME carries no UTC stamp")

    def test_and_with_no_tracks_in_scope_there_is_nothing_to_exclude(self):
        """The other half: the falsifier refuses because tracks EXIST and cannot be excluded, not
        because a name is unusual. An empty directory refuses nothing."""
        self.assertValid(self.check(birdless_depth_log(), name="live_flight_log_TEST.json",
                                    no_birds=True))

    def test_it_scans_the_results_dir_AND_the_logs_own_directory(self):
        """The real take sits in `eval/results/step0_wiring_20260911/` while the bird tracks sit in
        `eval/results/`. Looking in one place only would scan the wrong half."""
        sub_dir = self.dir / "step0"
        sub_dir.mkdir()
        p = sub_dir / self.NAME
        p.write_text(json.dumps(birdless_depth_log()))
        self.write_truth(bird_parked_at(PARKED), stamp="20260911T094000Z")     # in self.dir only
        status, messages = checker.check_file(p, results_dir=self.dir, no_birds=True)
        self.assertEqual(status, checker.INVALID, " ".join(messages))
        self.assertIn("--no-birds REFUSED", " ".join(messages))


class TestTheBringupRecordReconciles(NoBirdsHarness):
    """FALSIFIER 6. `fly_pipeline.sh up` writes `eval/results/live_flight_booking_<UTC>.json` BEFORE
    the flight and records which pane list it built. Until this round nothing read it: the same fact
    was declared twice (at bringup and at scoring) and reconciled zero times, so an operator who
    brought a take up WITH birds and scored it `--no-birds` was never contradicted by the
    machine-written record of the bringup (QA, 2026-09-11)."""

    ARMED = object()          # resolved from the gate at CALL time, never frozen at import time

    def record(self, birds=ARMED, stamp="20260911T092105Z", **over):
        birds = checker.LAUNCHER_BIRDS_ARMED if birds is self.ARMED else birds
        doc = {"schema_version": "1.1", "kind": "live_flight_booking",
               "written_utc": f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:11]}:{stamp[11:13]}:"
                              f"{stamp[13:15]}Z",
               "written_by": "scripts/fly_pipeline.sh up",
               "booking": {"path": "eval/results/booking_gate_TEST.json",
                           "booked_speed_mps": 5.0, "parameter": "WP_SPD"}}
        if birds is not None:
            doc["birds"] = birds
        doc.update(over)
        (self.dir / f"live_flight_booking_{stamp}.json").write_text(json.dumps(doc))
        return doc

    def test_a_bringup_that_ARMED_the_pane_refuses_the_declaration(self):
        self.record()
        text = self.assertRefused(self.check(birdless_depth_log(), no_birds=True),
                                  "ARMED the birds pane")
        self.assertIn("live_flight_booking_20260911T092105Z.json", text)
        self.assertIn(checker.LAUNCHER_BIRDS_ARMED, text)

    def test_a_bringup_that_DECLARED_it_reconciles_and_says_so(self):
        self.record(birds=checker.LAUNCHER_BIRDS_DECLARED)
        text = self.assertValid(self.check(birdless_depth_log(), no_birds=True))
        self.assertIn("bringup record RECONCILES", text)

    def test_a_record_with_no_birds_field_reconciles_NOTHING_and_says_that_too(self):
        """The real 2026-09-11 record, written before this field existed. Absence is not a
        declaration, and the note may not read as agreement."""
        self.record(birds=None)
        text = self.assertValid(self.check(birdless_depth_log(), no_birds=True))
        self.assertIn("UNRECONCILED", text)
        self.assertIn("older than 2026-09-11", text)

    def test_no_record_at_all_is_UNRECONCILED_not_agreement(self):
        """`up` writes the sidecar only when the bringup was given --booking."""
        text = self.assertValid(self.check(birdless_depth_log(), no_birds=True))
        self.assertIn("bringup record: NONE", text)

    def test_a_record_stamped_AFTER_this_flight_belongs_to_a_later_take(self):
        self.record(stamp="20260911T095000Z")                     # 7 min after the log's stamp
        text = self.assertValid(self.check(birdless_depth_log(), no_birds=True))
        self.assertIn("bringup record: NONE", text)

    def test_a_record_from_yesterday_is_not_this_takes_bringup(self):
        self.record(stamp="20260910T090000Z")                     # 24.7 h before
        self.assertValid(self.check(birdless_depth_log(), no_birds=True))

    def test_the_NEWEST_record_before_the_flight_is_the_one_read(self):
        """Two bringups in one session: the second one is the one this take flew out of."""
        self.record(birds=checker.LAUNCHER_BIRDS_DECLARED, stamp="20260911T080000Z")
        self.record(birds=checker.LAUNCHER_BIRDS_ARMED, stamp="20260911T092105Z")
        self.assertRefused(self.check(birdless_depth_log(), no_birds=True), "ARMED the birds pane")

    def test_a_file_that_is_not_a_bringup_record_is_not_read_as_one(self):
        self.record(kind="something_else")
        self.assertValid(self.check(birdless_depth_log(), no_birds=True))

    def test_the_symmetric_half_fires_WITHOUT_the_flag(self):
        """A take whose bringup declared bird-less, scored without `--no-birds`: truth resolution
        ran against whatever overlapped, and the artifact says so rather than staying silent."""
        self.record(birds=checker.LAUNCHER_BIRDS_DECLARED)
        truth = self.write_truth(bird_parked_at(PARKED), stamp="20260907T120000Z")
        text = self.assertValid(self.check(birdless_depth_log(), truth=truth))
        self.assertIn("BRINGUP DECLARED BIRD-LESS, SCORED WITHOUT THE FLAG", text)

    def test_the_symmetric_half_stays_QUIET_for_an_ordinary_take(self):
        """The byte-identity rule: without the flag, a take whose record armed the pane (or has no
        record at all) prints nothing new -- which is why the three committed logs cannot move."""
        self.record()
        truth = self.write_truth(bird_parked_at(PARKED), stamp="20260907T120000Z")
        text = self.assertValid(self.check(birdless_depth_log(), truth=truth))
        self.assertNotIn("BRINGUP DECLARED", text)
        self.assertNotIn("bringup record", text)


class TestTheFalsifiersPrintTheirDenominators(NoBirdsHarness):
    """A rate with no denominator is EVIDENCE INSUFFICIENT (CLAUDE.md), and "all six ran and found
    nothing" is a rate with no denominator. On the real 2026-09-11 take the in-cylinder falsifier
    scanned ZERO detection events while the segmenter produced 33,029 boxes."""

    def scanned(self, extra_events=()):
        _status, messages = self.check(birdless_depth_log(extra_events), no_birds=True)
        (line,) = [m for m in messages if m.startswith("truth: none")]
        return line

    def test_every_falsifier_reports_what_it_scanned(self):
        self.two_stale_truths()
        line = self.scanned()
        self.assertIn(f"{len(PATH)} event(s), 0 of them `detection` event(s)", line)
        self.assertIn(f"{HEALTHY_COUNTERS['boxes_total']} detector box(es)", line)
        self.assertIn("0 bird-track filename(s) named by the log", line)
        self.assertIn(f"{len(checker.TRUTH_BINDINGS)} reviewed TRUTH_BINDINGS pin(s)", line)
        self.assertIn("4 bird-track artifact(s)", line)         # 2 sidecars + 2 applied logs
        self.assertIn("refusal window +/-30 min", line)

    def test_an_EMPTY_scan_does_not_read_like_a_clean_one(self):
        """Zero tracks in scope is not "checked and clear", and the line has to show it."""
        line = self.scanned()
        self.assertIn("0 bird-track artifact(s)", line)
        self.assertIn("none of them placeable in time", line)

    def test_the_detection_denominator_counts_detections_not_boxes(self):
        canopy = (DRONE_AT_DET[0] + 30.0, DRONE_AT_DET[1], CRUISE_Z - 11.0)
        line = self.scanned([detection_event(pos=canopy)])
        self.assertIn("1 of them `detection` event(s)", line)

    def test_the_blind_spot_is_stated_in_the_artifact_itself(self):
        """The critical finding's own sentence: the failure this mode cannot see must be printed on
        every run, not left to a doc a log reader does not have."""
        line = self.scanned()
        self.assertIn("BLIND SPOT", line)
        self.assertIn("a bird the detector NEVER SAW leaves no trace here", line)
        self.assertIn("only evidence of a bird the log itself does not carry", line)


class TestTheVerdictWordCarriesTheDeclaration(NoBirdsHarness):
    """`VALID` and `PASS` are the strings CI, the dashboard and a scrollback reader consume. A take
    whose safety bar was never measured may not print the same word as one that cleared it -- the
    same doctrine as `check_tree_positions`' "PASS (vacuous)" (QA, 2026-09-11).

    Run through the real CLI, because this is a `main()` behaviour: the stem is deliberately far in
    the future so no artifact in anyone's `eval/results` is within the falsifiers' windows."""

    NAME = "live_flight_log_20991231T235959Z.json"

    def setUp(self):
        super().setUp()
        self.log = self.dir / self.NAME
        self.log.write_text(json.dumps(birdless_depth_log()))

    def cli(self, *args):
        return subprocess.run([sys.executable, "scripts/check_live_flight_log.py", *args],
                              cwd=REPO_ROOT, capture_output=True, text=True)

    def test_the_headline_and_the_footer_both_say_the_bar_was_not_measured(self):
        proc = self.cli(str(self.log), "--no-birds")
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("VALID (DECLARED BIRD-LESS", proc.stdout)
        self.assertIn(checker.NA_NO_BIRDS, proc.stdout.splitlines()[0])
        self.assertIn("1 of 1 DECLARED BIRD-LESS", proc.stdout)
        self.assertIn("clearance bar was NOT measured", proc.stdout)

    def test_without_the_flag_the_two_strings_are_the_plain_ones(self):
        """Byte-identity's half of this: the qualifier is built from `args.no_birds` and cannot
        reach a run that did not pass it."""
        applied = self.write_truth(bird_parked_at(PARKED), stamp="20991231T235000Z")
        proc = self.cli(str(self.log), "--truth", str(applied))
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn(f"VALID: {self.log}", proc.stdout)
        self.assertIn("PASS: all present flight logs valid.", proc.stdout)
        self.assertNotIn("DECLARED BIRD-LESS", proc.stdout)

    def test_a_REFUSED_log_is_never_counted_as_a_declared_one(self):
        """The count is of takes that were SCORED under the declaration, so a refusal cannot pad
        it -- and a refusal exits 1, where no PASS line is printed at all."""
        self.log.write_text(json.dumps(birdless_depth_log(
            [{"seq": 9, "tick": 2, "kind": "takeover", "track_id": None}])))
        proc = self.cli(str(self.log), "--no-birds")
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        self.assertIn("--no-birds REFUSED", proc.stderr)
        self.assertNotIn("DECLARED BIRD-LESS", proc.stdout + proc.stderr)


class TestTheCliContract(unittest.TestCase):
    """The flag as an operator meets it: argparse, and the three COMMITTED logs it may not touch."""

    def cli(self, *args):
        return subprocess.run([sys.executable, "scripts/check_live_flight_log.py", *args],
                              cwd=REPO_ROOT, capture_output=True, text=True)

    def test_no_birds_and_truth_are_mutually_exclusive_at_the_command_line(self):
        proc = self.cli(COMMITTED_LOGS[0], "--no-birds", "--truth", "whatever.jsonl")
        self.assertEqual(proc.returncode, 2, msg=proc.stderr)
        self.assertIn("not allowed with argument", proc.stderr)

    def test_the_flag_is_documented_in_the_help(self):
        proc = self.cli("--help")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("--no-birds", proc.stdout)
        # argparse re-wraps the help text, so the phrase is asserted without its line break.
        self.assertIn("no birds driven", proc.stdout)
        self.assertIn("REFUSED", proc.stdout)

    def test_every_committed_log_REFUSES_the_declaration(self):
        """The laundering test. All three flew with birds -- two breached and are ACKNOWLEDGED, one
        is the INVALID 2026-08-25 take -- so no command line may re-score them as bird-less."""
        missing = [p for p in COMMITTED_LOGS if not (REPO_ROOT / p).exists()]
        if missing:
            self.skipTest(f"committed evidence absent in this checkout: {missing}")
        proc = self.cli(*COMMITTED_LOGS, "--no-birds")
        self.assertEqual(proc.returncode, 1, msg=proc.stderr)
        self.assertEqual(proc.stderr.count("--no-birds REFUSED"), len(COMMITTED_LOGS))
        self.assertNotIn(checker.NA_NO_BIRDS, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
