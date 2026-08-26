"""Tests for the SCHEMA-2 gates in scripts/check_live_flight_log.py -- what a flight flown with the
REAL NDVI detector has to prove (2026-08-24, ADR-013 am. 12 R2/R3 + the ground-truth CPA).

THE FAILURE THIS FILE EXISTS FOR. `closest_approach()` measures the flown path against the LOGGED
DETECTIONS. That is exact for the demo bird (a constant we chose) and self-referential for a real
detector: apparent-size ranging has metre-scale error, and a MISS at closest approach produces no
detection there at all -- so the flight scored "NO-CPA-EVIDENCE -> VALID" precisely when the
detector failed at the worst moment. `test_the_headline_regression_a_missed_bird_at_cpa` flies that
exact log twice, once legacy and once schema-2, and pins VALID -> INVALID on identical evidence.

Everything here is offline and stdlib: synthesised flight logs plus synthesised
`drive_birds`-format truth tracks, both read through the SAME functions the live gate uses.

Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import io
import json
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_live_flight_log as checker  # noqa: E402
from fieldguard_planning.avoidance_executor import RESUME_CLEAR_TICKS  # noqa: E402
from fieldguard_planning.avoidance_policy import PolicyParams, _params_dict  # noqa: E402
from fieldguard_planning.coverage import CELL_COVERED, build_grid, load_field_polygon  # noqa: E402

GRID = build_grid(load_field_polygon())
LEDGER = [{"cell_id": c.cell_id, "status": CELL_COVERED} for c in GRID]

# The flight lives far from every bird's SPAWN pose (bird_0 (15,5,11), bird_1 (5,30,8),
# bird_2 (10,10,6) in config/birds/farm_world_birds.json) so that an undriven bird sitting at spawn
# never accidentally becomes the CPA. Anything the tests want to be close, they drive there.
DRONE_XY = (50.0, 50.0)
CRUISE_Z = 15.0
TICK_SIM = [100.5, 101.5, 102.5]          # this flight's tick stamps, absolute gz sim seconds
TRUTH_SIM = [100.0, 101.0, 102.0, 103.0]  # the driver's tick anchors, same clock
# Every bird the world defines. A real `drive_birds` run drives all of them, and the gate now
# refuses a truth track that never observed one (an undriven bird used to be pinned at its config
# spawn pose and counted as an observation for the whole flight). So the fixtures park the birds a
# test does not care about: far from every flown path AND out of the +/-6 m vertical band, so they
# can never become the CPA, inflate the cylinder count, or move `min_horizontal_any_band_m`.
CONFIG_BIRD_IDS = sorted(b["bird_id"] for b in checker.load_birds(checker.DEFAULT_BIRDS_CONFIG))
PARKED_XY = (95.0, 95.0)
PARKED_Z = 1.0                            # |dz| = 14 m from cruise: outside vertical_threat_m 6.0
# Acknowledgement takes BOTH halves (marker file AND pinned stem), so the fixtures need one log name
# the checker's allowlist pins and one it does not. The pinned one is read FROM the checker: a test
# may never assert an acknowledgement the shipped gate would not grant. The unpinned name is shaped
# like a real future take, because that IS the case this guards -- the next --detect flight.
PINNED_LOG = f"{checker.ACKNOWLEDGED_BREACH_STEMS[0]}.json"
NEW_TAKE_LOG = "live_flight_log_20260901T120000Z.json"
# The truth-track BINDING under test (`TRUTH_BINDINGS`), read from the checker for the same reason
# PINNED_LOG is: a test may not assert a join the shipped gate would not make. The stamp is recovered
# from the bound filename so the fixtures' `write_truth(stamp=...)` lays the file down under exactly
# the name the binding asks for -- `test_the_binding_values_are_shaped_like_applied_logs` proves the
# round trip rather than leaving it to luck.
BOUND_STEM, BOUND_TRUTH_NAME = next(iter(checker.TRUTH_BINDINGS.items()))
BOUND_LOG = f"{BOUND_STEM}.json"
BOUND_STAMP = BOUND_TRUTH_NAME[len("bird_drive_"):-len("_applied.jsonl")]


# ------------------------------------------------------------------------------------ fixtures
def truth_records(poses_by_tick, ok=True, park_undriven=True):
    """A `drive_birds` applied-pose log (schema 1.1) as a list of records.

    `poses_by_tick` = [(tick_sim_s, {bird_id: (x, y, z)}), ...]. Wall and sim time are set equal so
    `applied_sim_brackets`' measured RTF is exactly 1.0 and each call's bracket is a known ~1 ms
    window just after its tick anchor -- the tests can then place a flight stamp inside or outside a
    bracket deliberately rather than by luck.

    Birds the caller does not drive get a landed call at a PARKED pose on every tick, because a real
    driver run drives every bird in the config. `park_undriven=False` builds the pathological track
    the gate has to refuse: one that never observed a bird the world defines."""
    recs = []
    for sim_t, poses in poses_by_tick:
        full = dict(poses)
        if park_undriven:
            for k, bird_id in enumerate(CONFIG_BIRD_IDS):
                full.setdefault(bird_id, (PARKED_XY[0], PARKED_XY[1] + 2.0 * k, PARKED_Z))
        for j, (bird_id, pos) in enumerate(full.items()):
            recs.append({
                "bird_id": bird_id, "t_traj_s": 0.0, "pos_m": [float(c) for c in pos],
                "yaw_rad": 0.0, "ok": ok,
                "tick_sim_s": sim_t, "tick_wall_s": sim_t, "clock_wall_s": sim_t,
                "wall_start_s": sim_t + 0.001 + 0.01 * j,
                "wall_end_s": sim_t + 0.002 + 0.01 * j,
            })
    return recs


def straight_line(bird_id, xy_by_tick, z=CRUISE_Z):
    return [(t, {bird_id: (x, y, z)}) for t, (x, y) in zip(TRUTH_SIM, xy_by_tick)]


def maneuver_event(tick, clearance=1.5, trigger_range=9.0, latch_action="latch",
                   range_degenerate=None, setpoint=None, threats=None, **over):
    """One accepted DIVERT as `AvoidanceExecutor._handle_divert` logs it. `range_degenerate`
    defaults to the value the policy computes (trigger < degenerate_range_m), so a test that wants
    a LYING flag has to say so explicitly.

    `setpoint`/`threats` default to a dodge 10 m east of the drone and one bird `trigger_range` m
    north of it -- 10+ m apart, so R3.7 (the commanded point vs the birds logged with the decision)
    passes for every test that is not about R3.7."""
    degen = PolicyParams().degenerate_range_m
    setpoint = (DRONE_XY[0] + 10.0, DRONE_XY[1], CRUISE_Z) if setpoint is None else setpoint
    threats = ([(DRONE_XY[0], DRONE_XY[1] + trigger_range, CRUISE_Z)] if threats is None
               else threats)
    debug = {"swept_tree_clearance_m": clearance, "trigger_range_m": trigger_range,
             "range_degenerate": (trigger_range < degen if range_degenerate is None
                                  else range_degenerate),
             "threat_ids": [f"bird_{i}" for i in range(len(threats))],
             "threat_positions_enu": [list(t) for t in threats],
             "params": _params_dict(PolicyParams())}
    debug.update(over.pop("debug", {}))
    ev = {"seq": tick, "tick": tick, "kind": "maneuver", "decision": "divert",
          "verdict": "accepted", "debug": debug, "latch_action": latch_action,
          "setpoint_enu": list(setpoint)}
    ev.update(over)
    return ev


def gate_reject_event(tick, bird_clearance_m=1.0, obstacle_id=None,
                      min_bird_clearance_m=None, **over):
    """One refused setpoint as `AvoidanceExecutor._handle_divert` logs it. Defaults to the BIRD
    branch (the backstop stopping a latch that drifted inside the bar) -- the event R3.8 reads, and
    the only live evidence in a log that the backstop ever fired."""
    ev = {"seq": tick, "tick": tick, "kind": "gate_reject",
          "setpoint_enu": [DRONE_XY[0] + 10.0, DRONE_XY[1], CRUISE_Z],
          "obstacle_id": obstacle_id, "bird_clearance_m": bird_clearance_m,
          "bird_track_id": None if bird_clearance_m is None else "bird_0",
          "min_bird_clearance_m": (PolicyParams().min_bird_clearance_m
                                   if min_bird_clearance_m is None else min_bird_clearance_m),
          "latch_action": "relatch_refused_degenerate"}
    ev.update(over)
    return ev


def hold_event(tick, bird_clearance_m=None, **over):
    """One HOLD tick as `AvoidanceExecutor._handle_hold` logs it, carrying the hold's OWN distance
    to the nearest threat -- zero displacement, so it honours no bar; the number is context."""
    ev = {"seq": tick, "tick": tick, "kind": "hold",
          "position_enu": [DRONE_XY[0], DRONE_XY[1], CRUISE_Z],
          "bird_clearance_m": bird_clearance_m,
          "bird_track_id": None if bird_clearance_m is None else "bird_0",
          "min_bird_clearance_m": PolicyParams().min_bird_clearance_m,
          "reason": "gate_reject:bird within min_bird_clearance_m"}
    ev.update(over)
    return ev


def detection_event(tick, pos, track_id="det@0"):
    return {"seq": tick, "tick": tick, "kind": "detection", "track_id": track_id,
            "position_enu": list(pos)}


def detector_counters(**over):
    """`NdviDetectionSource.counters()` as the node logs it -- a HEALTHY take by default (the
    numbers are the 2026-08-24 offline dry run over the adopted clip). Zeroing `frames_detected_on`
    is the "the detector never saw a frame" case the gate has to fail."""
    counters = {"ndvi_msgs_received": 1256, "frames_detected_on": 1256,
                "frames_with_detection": 20, "boxes_total": 24, "dropped_no_intrinsics": 0,
                "dropped_no_pose_pair": 0, "dropped_stale_pose_pair": 0,
                "detect_wall_ms_p95": 4.813, "detect_wall_ms_max": 26.94, "detect_wall_ms_n": 1256,
                "note": "test fixture"}
    counters.update(over)
    return counters


def make_run(detector_source=checker.DET_NDVI_BLOB, stamps=None, n_path=3, counters=None, **over):
    detector = {"source": detector_source, "thresh": -0.61, "thresh_provisional": True}
    if detector_source == checker.DET_NDVI_BLOB:      # the demo/none blocks carry no counters
        detector["counters"] = detector_counters() if counters is None else counters
    run = {
        "schema_version": 2,
        "clock": {"source": checker.CLOCK_SOURCE, "violations": 0},
        "tick_stamp_sim_s": list(TICK_SIM[:n_path] if stamps is None else stamps),
        "policy_params": _params_dict(PolicyParams()),
        "detector": detector,
    }
    run.update(over)
    return run


def make_log(events=None, run=None, path=None, **over):
    """A structurally valid schema-2 flight log flying straight and level at DRONE_XY."""
    flown = ([[DRONE_XY[0], DRONE_XY[1] + 0.0, CRUISE_Z]] * 3) if path is None else path
    log = {
        "scenario": "schema2_test", "seed": 0, "cell_size_m": 2.5, "swath_half_width_m": 7.5,
        "flown_path_enu": [list(p) for p in flown],
        "coverage_ledger": LEDGER,
        "requeue_events": [],
        "events": list(events or []),
    }
    log["run"] = make_run(n_path=len(log["flown_path_enu"])) if run is None else run
    log.update(over)
    return log


class Harness(unittest.TestCase):
    """A tmp dir that is BOTH the flight-log home and the `eval/results` the gate auto-discovers
    truth tracks in, so no test can accidentally pick up committed evidence."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write_log(self, log, name="live_flight_log_TEST.json"):
        p = self.dir / name
        p.write_text(json.dumps(log))
        return p

    def write_truth(self, records, stamp="20260824T000000Z", clock="sim", applied=True):
        """Sidecar + applied log, exactly as `drive_birds` lays them out (the gate discovers via
        the sidecar, which is what screens out wall-clock runs)."""
        sidecar = self.dir / f"bird_drive_{stamp}.json"
        applied_path = self.dir / f"bird_drive_{stamp}_applied.jsonl"
        sidecar.write_text(json.dumps({
            "schema_version": "1.1", "clock": clock, "t0_sim_s": TRUTH_SIM[0],
            "applied_log": applied_path.name, "bird_ids": sorted({r["bird_id"] for r in records}),
        }))
        if applied:
            applied_path.write_text("".join(json.dumps(r) + "\n" for r in records))
        return applied_path

    def check(self, log, truth=None, name="live_flight_log_TEST.json"):
        p = self.write_log(log, name)
        return checker.check_file(p, truth=truth, results_dir=self.dir)

    def mark(self, name="live_flight_log_TEST.json"):
        m = checker.marker_path_for(self.dir / name)
        m.write_text("# acknowledged for test")
        return m

    def assertInvalid(self, result, needle):
        status, messages = result
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn(needle, blob)

    def assertValid(self, result):
        status, messages = result
        self.assertEqual(status, checker.VALID, " ".join(messages))
        return " ".join(messages)


# ================================================================================================
# 1. Version plumbing -- legacy logs keep the verdict they were flown under, and cannot be faked
# ================================================================================================
class TestSchemaDispatch(Harness):
    def test_a_PINNED_pre_seam_log_with_no_run_block_takes_the_legacy_path_untouched(self):
        legacy = make_log()
        legacy.pop("run")
        legacy["events"] = [detection_event(1, (DRONE_XY[0], DRONE_XY[1] + 5.0, CRUISE_Z))]
        msg = self.assertValid(self.check(legacy, name=PINNED_LOG))
        self.assertIn("CPA 5.0000 m", msg)               # the legacy, detection-referenced number
        self.assertNotIn("gt_cpa_m", msg)

    def test_THE_PROBE_deleting_the_run_key_cannot_downgrade_a_failing_flight(self):
        """THE hole this ratchet closes, run as the attack.

        A schema-2 log the bird ground truth FAILS (5 cm, and the detector logged nothing at closest
        approach, so the legacy metric has no evidence at all). `del log["run"]` used to drop it onto
        the legacy path and score it VALID NO-CPA-EVIDENCE -- a ground-truth-gated INVALID turned
        green by deleting ONE key, in a gitignored directory. It must stay INVALID, and name the
        missing run block rather than the CPA it can no longer measure."""
        recs = truth_records([(t, {"bird_0": (50.0, 50.05, CRUISE_Z)}) for t in TRUTH_SIM])
        truth = self.write_truth(recs)
        log = make_log(events=[])
        self.assertInvalid(self.check(log, truth=truth, name=NEW_TAKE_LOG), "CPA BREACH")

        log.pop("run")
        result = self.check(log, truth=truth, name=NEW_TAKE_LOG)
        self.assertInvalid(result, "NO 'run' BLOCK")
        self.assertInvalid(result, "fault or tampering")
        self.assertInvalid(result, "PRE_SEAM_LEGACY_STEMS")
        # ...and it did NOT score the flight on the weaker metric: the only mention of the legacy
        # verdict is inside the refusal, explaining what the deletion would have bought.
        self.assertEqual(len(result[1]), 2, result[1])           # headline + the one refusal

    def test_the_two_committed_breach_logs_are_still_legacy_and_still_acknowledged(self):
        """The regression that protects recorded history: neither historical log grows a `run`
        block, so neither can be re-judged by gates it was never flown under -- and both are pinned
        pre-seam, which is what still lets them onto the legacy path at all."""
        for name in ("live_flight_log_20260818T144711Z.json",
                     "live_flight_log_20260823T004031Z.json"):
            p = checker.RESULTS_DIR / name
            if not p.exists():
                continue                                  # evidence is gitignored in some checkouts
            with self.subTest(log=name):
                log = json.loads(p.read_text())
                self.assertIsNone(checker.schema_version(log))
                self.assertTrue(checker.legacy_pinned(p))
                self.assertIsNone(checker.run_block_problem(log, p))
                status, messages = checker.check_file(p)
                self.assertEqual(status, checker.ACKNOWLEDGED, " ".join(messages))
                self.assertIn("NOT a passing flight", " ".join(messages))

    def test_ci_generated_scenario_logs_stay_on_the_legacy_path(self):
        for p in sorted((REPO_ROOT / "eval" / "scenarios").glob("*/flight_log.json")):
            with self.subTest(log=p.name):
                self.assertIsNone(checker.schema_version(json.loads(p.read_text())))
                self.assertIsNone(checker.run_block_problem(json.loads(p.read_text()), p))

    def test_an_unreadable_schema_version_is_invalid_not_silently_demoted(self):
        """A downgrade attack: making the version unreadable would drop the log onto the weaker
        detection-referenced CPA path. It fails instead."""
        for bad in ("2", 2.0, None, True, [2]):
            with self.subTest(version=bad):
                log = make_log()
                log["run"]["schema_version"] = bad
                self.assertInvalid(self.check(log), "not an integer")

    def test_a_run_block_that_is_not_an_object_is_invalid(self):
        log = make_log()
        log["run"] = "schema_version=2"
        self.assertInvalid(self.check(log), "not an object")

    def test_a_schema_below_the_gate_is_invalid_rather_than_legacy(self):
        log = make_log()
        log["run"]["schema_version"] = 1
        self.assertInvalid(self.check(log), "downgrade")

    def test_ledger_failure_still_wins_over_every_schema_2_gate(self):
        """Additive, not reordering: a corrupt ledger is INVALID before any of this runs."""
        log = make_log()
        log["flown_path_enu"] = []
        self.assertInvalid(self.check(log), "flown_path_enu is EMPTY")


# ================================================================================================
# 2. Clock domain (assertion 7) -- without ONE clock nothing else here means anything
# ================================================================================================
class TestClockGate(Harness):
    def _run_with_clock(self, **clock_over):
        run = make_run(detector_source=checker.DET_NONE)
        if clock_over.pop("drop", False):
            run.pop("clock")
        else:
            run["clock"].update(clock_over)
        return make_log(run=run)

    def test_missing_clock_block_is_invalid(self):
        self.assertInvalid(self.check(self._run_with_clock(drop=True)), "run.clock missing")

    def test_a_foreign_clock_source_is_invalid(self):
        self.assertInvalid(self.check(self._run_with_clock(source="node_elapsed")),
                           "run.clock.source is 'node_elapsed'")

    def test_missing_violation_count_is_a_defect_not_a_zero(self):
        log = self._run_with_clock()
        log["run"]["clock"].pop("violations")
        self.assertInvalid(self.check(log), "absence of the clock-domain tripwire is a defect")

    def test_a_non_integer_violation_count_cannot_pass(self):
        for bad in ("0", 0.0, True, None):
            with self.subTest(violations=bad):
                self.assertInvalid(self.check(self._run_with_clock(violations=bad)),
                                   "not an integer")

    def test_any_violation_fails_the_flight(self):
        """The node's tripwire fires when a detection stamp is >0.5 s in the FUTURE of now_s --
        which is what an elapsed clock against absolute gz stamps produces on EVERY tick. R-B."""
        self.assertInvalid(self.check(self._run_with_clock(violations=1)),
                           "run.clock.violations = 1")

    def test_one_stamp_per_flown_position_or_the_join_is_guesswork(self):
        run = make_run(detector_source=checker.DET_NONE, stamps=TICK_SIM[:2])
        self.assertInvalid(self.check(make_log(run=run)), "flown_path_enu has 3")

    def test_missing_tick_stamps_is_invalid(self):
        run = make_run(detector_source=checker.DET_NONE)
        run.pop("tick_stamp_sim_s")
        self.assertInvalid(self.check(make_log(run=run)), "no time axis")

    def test_a_clean_clock_is_reported_not_merely_assumed(self):
        msg = self.assertValid(self.check(make_log(run=make_run(checker.DET_NONE))))
        self.assertIn("clock gz_clock_stream, 0 domain violations", msg)


# ================================================================================================
# 2b. The axis has to MOVE -- a frozen clock re-dates the whole flight onto one instant
# ================================================================================================
class TestTheTimeAxisAdvances(Harness):
    """`run.clock` reports source, violations and length; NONE of them notice a clock that stopped.
    The node's `gz topic -e -t /clock` thread can die (or Gazebo can pause) with `_gz_readings`
    already > 0, so the source string stays `gz_clock_stream` and `_gz_now` simply never changes.
    The domain tripwire can only fire on a tick that carries a detection -- 8 frames in 1256 on the
    adopted clip -- so the freeze is silent for ~99 % of a flight, while `ground_truth_cpa` joins
    EVERY tick to the truth track by that stamp."""

    def _flight(self, stamps, bird_by_anchor):
        recs = truth_records([(t, {"bird_0": p}) for t, p in zip(TRUTH_SIM, bird_by_anchor)])
        truth = self.write_truth(recs)
        run = make_run(stamps=stamps, n_path=len(stamps))
        log = make_log(run=run, path=[[DRONE_XY[0], DRONE_XY[1], CRUISE_Z]] * len(stamps))
        return self.check(log, truth=truth), truth

    def test_a_frozen_axis_cannot_convert_a_breach_into_a_pass(self):
        """THE probe, one flown path and one truth track, scored on two stamp axes. The bird is 20 m
        away early and 5 cm away late. An advancing axis measures the pass and FAILS it; a frozen
        axis joins every tick to the early instant and the same flight reads clean -- both printing
        full truth coverage and a spotless `gz_clock_stream` clock."""
        far_then_near = [(50.0, 70.0, CRUISE_Z), (50.0, 70.0, CRUISE_Z),
                         (50.0, 50.05, CRUISE_Z), (50.0, 50.05, CRUISE_Z)]
        (status, messages), _ = self._flight(list(TICK_SIM), far_then_near)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("CPA BREACH: flew within 0.0500 m", blob)

        (status, messages), _ = self._flight([TICK_SIM[0]] * 3, far_then_near)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)      # NOT VALID: that was the whole defect
        self.assertIn("NEVER ADVANCED", blob)
        self.assertIn("gt_cpa_m 20.0000", blob)              # the flattering, re-dated number
        self.assertIn("truth coverage 3/3 ticks", blob)      # ...at 100 % coverage, as measured

    def test_THE_PROBE_a_five_tick_freeze_can_no_longer_certify_a_strike(self):
        """QA ROUND 2, FINDING 1, the probe verbatim. The old bound (5 ticks, "just inside the 1.0 s
        ADR-009 staleness bound") was sized against DETECTION FRESHNESS, which has nothing to do
        with the truth JOIN -- and 0.8 s of frozen sim time is 5.6 m of bird_1, 1.9x the 3.00 m bar
        the gate exists to enforce. The drone holds station; the bird crosses through its exact
        position; five consecutive ticks straddling the pass read the same stamp 0.5 s early, so the
        join scores the whole flight against the bird's EARLY pose and reported
        `gt_cpa_m 3.5000 m -> PASS` at 45/45 truth coverage. It now fails, and as a CLOCK fault (not
        a debited breach): a freeze this long could hide the entire bar, so nothing was measured."""
        bird = [(50.0, 46.5, CRUISE_Z)] * 4                    # 3.5 m from the drone at the frozen
        stamps = [100.5] * 5 + [101.5]                         # instant; through it later on
        (status, messages), _ = self._flight(stamps, bird)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("FROZE", blob)
        self.assertIn("5 consecutive ticks", blob)
        self.assertIn("min_bird_clearance_m", blob)
        # ...and the flattering number is NOT what certified anything.
        self.assertNotEqual(status, checker.VALID)

    def test_a_shorter_stall_is_priced_into_the_gated_number_rather_than_waved_through(self):
        """The exactly-conservative half: a 3-tick freeze whose next advancing stamp is 0.4 s later
        hides 0.4 s = 2.80 m of bird_1, so a measured 3.5000 m join is gated at 0.7000 m and
        BREACHES. Nothing here is a judgement call -- the window is read off the flight's own
        stamps and multiplied by the fastest speed the birds config scripts."""
        debit = checker.freeze_debit_m(0.4)
        self.assertAlmostEqual(debit, 2.8017, places=4)        # 0.4 s x 7.0043 m/s, from the config
        (status, messages), _ = self._flight([100.5] * 3 + [100.9],
                                             [(50.0, 46.5, CRUISE_Z)] * 4)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("gt_cpa_m 3.5000", blob)                 # the measured join, still printed
        self.assertIn(f"gt_cpa_gated_m {3.5 - debit:.4f}", blob)   # ...and what the bar actually saw
        self.assertIn("CPA BREACH", blob)

    def test_a_stall_the_debit_absorbs_is_reported_and_passes(self):
        """A tick or two of repeated sim time is scheduler jitter, not a dead clock: the flight is
        still scored, at a number that already carries the cost of the stall. 20 m - 2.80 m."""
        debit = checker.freeze_debit_m(0.4)
        msg = self.assertValid(self._flight([100.5] * 3 + [100.9],
                                            [(50.0, 70.0, CRUISE_Z)] * 4)[0])
        self.assertIn("longest frozen run 3 tick(s), worst hidden window 0.400 s -> gt_cpa_m "
                      f"freeze debit {debit:.4f} m", msg)
        self.assertIn(f"gt_cpa_gated_m {20.0 - debit:.4f}", msg)

    def test_THE_ROUND_3_PROBE_the_debit_is_measured_from_the_stamps_not_a_nominal_rate(self):
        """QA ROUND 3, FINDING 5. The old debit was `(N-1)/CONTROL_HZ` at a hard-coded 5 Hz, which
        is only an upper bound if the ROS timer really fires at 5 Hz -- and it runs on a WALL clock
        on a box this project has twice documented starving. Measured under-pricing at the finding's
        own achieved rates: 1.75x at 0.35 s/tick, 2.5x at 0.50, 5.0x at 1.00.

        THE PROBE, dt = 0.5 s/tick: three ticks frozen at 100.5 and the axis resuming at 102.0. The
        old arithmetic priced that at 0.400 s = 2.802 m and PASSED a 3.5000 m join at 0.698 m of
        margin. The stamps say 1.500 s = 10.507 m -- past the whole 3.00 m bar, so it is a CLOCK
        fault, not a debited breach: the join could hide a strike outright."""
        self.assertAlmostEqual(checker.freeze_debit_m(0.4), 2.8017, places=4)    # what it used to be
        (status, messages), _ = self._flight([100.5] * 3 + [102.0],
                                             [(50.0, 46.5, CRUISE_Z)] * 4)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("FROZE", blob)
        self.assertIn("1.500 s of sim time", blob)
        self.assertIn("10.506 m", blob)
        # Never DEBITED: subtracting a window bigger than the bar would print a negative
        # separation and a CPA BREACH on a flight that measured nothing.
        self.assertIn("gt_cpa_gated_m NOT COMPUTED", blob)
        self.assertNotIn("CPA BREACH", blob)

    def test_the_hidden_window_is_read_off_the_stamps_in_every_shape_it_comes_in(self):
        """The unit, four ways, because the window is now the whole bound:
        no freeze -> 0; a run closed by an advancing stamp -> that gap; a run at the START of the
        flight -> still that gap (the frozen VALUE is its own lower bound); and a run that never
        recovers -> the flight's OWN measured mean step, never a nominal one."""
        self.assertEqual(checker.stamp_advance([1.0, 1.2, 1.4])["frozen_window_s"], 0.0)
        adv = checker.stamp_advance([1.0, 1.2, 1.2, 1.2, 1.6])
        self.assertAlmostEqual(adv["frozen_window_s"], 0.4, places=6)
        self.assertEqual(adv["frozen_at"], (2, 3, 1.2))        # (start tick, length, value)
        self.assertAlmostEqual(checker.stamp_advance([1.2, 1.2, 1.2, 1.6])["frozen_window_s"], 0.4,
                               places=6)
        trailing = checker.stamp_advance([1.0, 1.2, 1.4, 1.4, 1.4])   # mean step 0.2 x 3 ticks
        self.assertAlmostEqual(trailing["mean_step_s"], 0.2, places=6)
        self.assertAlmostEqual(trailing["frozen_window_s"], 0.6, places=6)

    def test_the_WORST_run_is_priced_not_the_longest(self):
        """Seconds hidden, not ticks repeated: a 2-tick freeze straddling a 5 s clock gap hides more
        than a 4-tick one straddling 0.1 s, and pricing the longest run would read the wrong one."""
        adv = checker.stamp_advance([1.0, 1.1, 1.1, 1.1, 1.1, 1.2, 5.0, 5.0, 9.0])
        self.assertEqual(adv["longest_frozen_run"], 4)
        self.assertAlmostEqual(adv["frozen_window_s"], 4.0, places=6)   # the 2-tick run at 5.0
        self.assertEqual(adv["frozen_at"], (7, 2, 5.0))

    def test_the_freeze_bound_is_derived_from_the_bar_and_the_birds_not_chosen_freely(self):
        """The one inequality both halves come from: debit = hidden sim seconds x fastest scripted
        bird, failed hard once it reaches `min_bird_clearance_m`. Both inputs are read from files
        this repo owns, so a faster bird or a higher bar re-derives the bound with no edit here."""
        self.assertAlmostEqual(checker.max_bird_speed_m_s(), 7.0, places=2)   # bird_1: 65 m / 9.29 s
        self.assertEqual(checker.freeze_debit_m(0.0), 0.0)                    # no freeze, no debit
        self.assertAlmostEqual(checker.freeze_debit_m(0.6), 4.2, places=2)
        bar = PolicyParams().min_bird_clearance_m
        self.assertLess(checker.freeze_debit_m(0.4), bar)        # 2.80 m -> priced
        self.assertGreaterEqual(checker.freeze_debit_m(0.6), bar)  # 4.20 m -> hard clock failure
        # And the wrong denominators BOTH versions used are gone as CONSTANTS -- the derivation
        # still names them, because a bound that was wrong twice is worth explaining once.
        source = (REPO_ROOT / "scripts" / "check_live_flight_log.py").read_text()
        self.assertNotIn("MAX_FROZEN_TICKS", source)
        self.assertNotIn("CONTROL_HZ =", source)
        self.assertNotIn("frozen_span_s", source)

    def test_a_clock_that_runs_backwards_is_not_a_clock(self):
        (status, messages), _ = self._flight([100.5, 102.5, 101.5], [(50.0, 70.0, CRUISE_Z)] * 4)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("goes BACKWARDS at tick 3", blob)

    def test_unstamped_ticks_are_gaps_not_freezes(self):
        """A null stamp is a tick with no clock reading -- already counted as missing truth
        coverage. Treating it as a repeat would fail honest flights for the wrong reason."""
        msg = self.assertValid(self._flight([100.5, None, 102.5],
                                            [(50.0, 70.0, CRUISE_Z)] * 4)[0])
        self.assertIn("stamps_advanced 1/1", msg)
        self.assertIn("truth coverage 2/3 ticks", msg)

    def test_the_advance_is_printed_with_a_denominator_on_a_healthy_flight(self):
        msg = self.assertValid(self.check(make_log(run=make_run(checker.DET_NONE))))
        self.assertIn("stamps_advanced 2/2", msg)
        self.assertIn("span 2.000 s", msg)


# ================================================================================================
# 3. Knob floors (R2.2 / R3.6 / the CPA bar) -- flown at or above today's control law
# ================================================================================================
class TestKnobFloors(Harness):
    def _with_knob(self, knob, value):
        run = make_run(detector_source=checker.DET_NONE)
        run["policy_params"][knob] = value
        return make_log(run=run)

    def test_a_weakened_knob_fails_whichever_knob_it_is(self):
        for knob, weaker in (("lateral_tree_margin_m", 0.0),
                             ("min_bird_clearance_m", 1.0),
                             ("degenerate_range_m", 0.5)):
            with self.subTest(knob=knob):
                self.assertInvalid(self.check(self._with_knob(knob, weaker)),
                                   f"run.policy_params.{knob}")

    def test_flying_ABOVE_the_bar_is_fine(self):
        self.assertValid(self.check(self._with_knob("lateral_tree_margin_m", 2.0)))

    def test_a_missing_or_non_numeric_knob_is_invalid(self):
        for value in (None, "1.0", True, [1.0]):
            with self.subTest(value=value):
                self.assertInvalid(self.check(self._with_knob("min_bird_clearance_m", value)),
                                   "does not record the safety knob it flew")

    def test_missing_policy_params_is_invalid(self):
        run = make_run(detector_source=checker.DET_NONE)
        run.pop("policy_params")
        self.assertInvalid(self.check(make_log(run=run)), "run.policy_params missing")

    def test_the_bars_come_from_the_policy_not_from_literals_here(self):
        """Mutation proof of the wiring: a log flown at today's defaults goes INVALID the moment
        the POLICY raises a knob, with no edit to the checker. That is what stops the gate and the
        control law drifting apart."""
        log = make_log(run=make_run(checker.DET_NONE))
        self.assertValid(self.check(log))
        with patched_params(lateral_tree_margin_m=2.0):
            self.assertInvalid(self.check(log), "BELOW today's policy default")
        self.assertValid(self.check(log))                # restored


# ================================================================================================
# 4. Staleness gate armed (ADR-009) -- a real detector may not fly with age-checking OFF
# ================================================================================================
class TestStalenessGate(Harness):
    def test_a_real_detector_flown_with_the_age_gate_off_is_invalid(self):
        run = make_run(checker.DET_NDVI_BLOB)
        run["policy_params"]["max_detection_age_s"] = None
        truth = self.write_truth(truth_records(straight_line("bird_0", [(0, 0)] * 4)))
        self.assertInvalid(self.check(make_log(run=run), truth=truth),
                           "ADR-009 staleness gate was OFF")

    def test_the_demo_source_is_not_held_to_it(self):
        """The demo bird carries no stamp, so the gate cannot fire for it and failing the log
        would be gating on a parameter that has nothing to check."""
        run = make_run(checker.DET_DEMO_VIRTUAL)
        run["policy_params"]["max_detection_age_s"] = None
        self.assertValid(self.check(make_log(run=run)))

    def test_a_flight_that_tolerated_staler_frames_than_the_policy_fails(self):
        run = make_run(checker.DET_NDVI_BLOB)
        run["policy_params"]["max_detection_age_s"] = 5.0
        truth = self.write_truth(truth_records(straight_line("bird_0", [(0, 0)] * 4)))
        with patched_params(max_detection_age_s=1.0):
            self.assertInvalid(self.check(make_log(run=run), truth=truth),
                               "exceeds today's policy default")

    def test_the_upper_bound_is_LIVE_and_not_dead_code(self):
        """The branch above used to need `patched_params` to fire at all, because
        `PolicyParams.max_detection_age_s` was None while the node armed 1.0 s from a constant of
        its own -- one knob, two homes. A log flown at an hour of staleness tolerance passed as
        current behaviour. No patching here: the bound is the policy's own default."""
        self.assertEqual(PolicyParams().max_detection_age_s, 1.0)
        truth = self.write_truth(truth_records(straight_line("bird_0", [(0, 0)] * 4)))
        run = make_run(checker.DET_NDVI_BLOB)
        run["policy_params"]["max_detection_age_s"] = 3600.0
        self.assertInvalid(self.check(make_log(run=run), truth=truth),
                           "exceeds today's policy default")
        # ...and at the unit the probe used, so the branch itself is pinned, not just the verdict.
        self.assertTrue(checker.gate_staleness({"policy_params": {"max_detection_age_s": 3600.0}}))
        self.assertEqual(
            checker.gate_staleness({"policy_params": {"max_detection_age_s": 1.0}}), [])

    def test_flying_at_the_policys_own_bound_passes(self):
        truth = self.write_truth(truth_records(straight_line("bird_0", [(0, 0)] * 4)))
        self.assertValid(self.check(make_log(run=make_run(checker.DET_NDVI_BLOB)), truth=truth))


# ================================================================================================
# 5. R2 -- swept-path tree clearance, per accepted decision
# ================================================================================================
class TestR2SweptTreeClearance(Harness):
    def _log(self, **kw):
        return make_log(events=[maneuver_event(1, **kw)], run=make_run(checker.DET_DEMO_VIRTUAL))

    def test_a_dodge_that_swept_inside_the_margin_fails_and_names_the_numbers(self):
        status, messages = self.check(self._log(clearance=0.846))
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("R2 BREACH tick 1", blob)
        self.assertIn("0.846", blob)                  # the reference tick from the 2026-08-23 log
        self.assertIn("1.000", blob)

    def test_exactly_at_the_margin_passes_and_that_is_pinned_deliberately(self):
        """CURRENT: the gate is `>=`, so a dodge at exactly the margin is accepted. ADR-015 says
        never rest a safety claim ON a boundary -- the margin itself is the standoff, so equality
        is the intended pass. Pinned so a change here is a decision, not a drift."""
        self.assertValid(self.check(self._log(clearance=PolicyParams().lateral_tree_margin_m)))

    def test_an_accepted_dodge_with_no_recorded_clearance_is_unvetted_evidence(self):
        log = self._log()
        log["events"][0]["debug"].pop("swept_tree_clearance_m")
        self.assertInvalid(self.check(log), "no debug.swept_tree_clearance_m")

    def test_a_maneuver_with_no_debug_at_all_did_not_come_from_this_policy(self):
        log = self._log()
        log["events"][0].pop("debug")
        self.assertInvalid(self.check(log), "no debug dict")

    def test_the_gate_reads_the_FLOWN_margin_so_a_stronger_flight_is_held_to_its_own_bar(self):
        run = make_run(checker.DET_DEMO_VIRTUAL)
        run["policy_params"]["lateral_tree_margin_m"] = 2.0      # flown stronger than the default
        log = make_log(events=[maneuver_event(1, clearance=1.5)], run=run)
        self.assertInvalid(self.check(log), "below the flown lateral_tree_margin_m 2.000")

    def test_every_maneuver_is_checked_not_just_the_first(self):
        log = make_log(events=[maneuver_event(1, clearance=5.0),
                               maneuver_event(2, clearance=5.0),
                               maneuver_event(3, clearance=0.2)],
                       run=make_run(checker.DET_DEMO_VIRTUAL))
        self.assertInvalid(self.check(log), "R2 BREACH tick 3")


# ================================================================================================
# 6. R3 -- no re-latch on a degenerate tick, gated on the NUMBER
# ================================================================================================
class TestR3DegenerateRelatch(Harness):
    def _log(self, *events):
        return make_log(events=list(events), run=make_run(checker.DET_DEMO_VIRTUAL))

    def test_a_relatch_below_the_degenerate_range_is_a_breach(self):
        status, messages = self.check(self._log(
            maneuver_event(1, trigger_range=0.052, latch_action="relatch")))
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("R3 BREACH tick 1", blob)
        self.assertIn("0.052", blob)

    def test_a_relatch_above_it_is_ordinary_behaviour(self):
        self.assertValid(self.check(self._log(
            maneuver_event(1, trigger_range=20.9, latch_action="relatch"))))

    def test_a_LYING_flag_cannot_buy_a_relatch_because_the_gate_reads_the_NUMBER(self):
        """The whole reason R3.4 is written against trigger_range_m and not range_degenerate."""
        status, messages = self.check(self._log(
            maneuver_event(1, trigger_range=0.052, latch_action="relatch",
                           range_degenerate=False)))
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("R3 BREACH tick 1", blob)                       # the number caught it
        self.assertIn("policy and executor are at different versions", blob)   # so did the identity

    def test_flag_and_number_must_agree_even_when_no_relatch_happened(self):
        self.assertInvalid(self.check(self._log(
            maneuver_event(1, trigger_range=9.0, latch_action="latch", range_degenerate=True))),
            "range_degenerate is True")

    def test_the_identity_holds_at_the_boundary_in_both_directions(self):
        degen = PolicyParams().degenerate_range_m
        for trig, flag, ok in ((degen, False, True), (degen, True, False),
                               (degen - 0.001, True, True), (degen - 0.001, False, False)):
            with self.subTest(trigger=trig, flag=flag):
                result = self.check(self._log(
                    maneuver_event(1, trigger_range=trig, range_degenerate=flag)))
                if ok:
                    self.assertValid(result)
                else:
                    self.assertInvalid(result, "different versions")

    def test_missing_either_half_of_the_pair_makes_R3_unauditable(self):
        for key in ("trigger_range_m", "range_degenerate"):
            with self.subTest(missing=key):
                log = self._log(maneuver_event(1))
                log["events"][0]["debug"].pop(key)
                self.assertInvalid(self.check(log), "Both travel together or R3 is unauditable")

    def test_R3_7_a_COMMANDED_setpoint_inside_the_bird_bar_is_a_breach(self):
        """QA ROUND 2, FINDING 3, the artifact half. The executor now HOLDs rather than commanding
        such a point -- this is the offline re-check of the same inequality, so a log that reaches
        the gate with one is failed whatever produced it. The numbers are the probe's: a latch at
        (30,30,15) re-commanded while the bird sat at (29,30,15), 1.000 m away, against 3.00 m."""
        status, messages = self.check(self._log(maneuver_event(
            1, trigger_range=0.4, latch_action="relatch_refused_degenerate",
            setpoint=(30.0, 30.0, 15.0), threats=[(29.0, 30.0, 15.0)])))
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("R3.7 BREACH tick 1", blob)
        self.assertIn("1.000 m from bird bird_0", blob)
        self.assertIn("3.000", blob)

    def test_R3_7_scores_the_NEAREST_threat_to_the_setpoint_not_the_trigger(self):
        """A dodge away from bird A must not be re-commanded into bird B. Bird B is 12 m from the
        drone (outside nothing) and 1 m from the commanded point; the trigger is 9 m away and
        irrelevant to the point that was flown."""
        self.assertInvalid(self.check(self._log(maneuver_event(
            1, setpoint=(60.0, 50.0, 15.0),
            threats=[(50.0, 59.0, 15.0), (61.0, 50.0, 15.0)]))), "R3.7 BREACH tick 1")

    def test_R3_7_at_exactly_the_bar_passes_because_that_is_where_the_policy_accepts(self):
        """`min_bird_clearance_m` is the standoff itself, and the policy's own gate 4 is `<`. The
        two comparisons must be the same one or a decision the policy accepted fails its own gate."""
        self.assertValid(self.check(self._log(maneuver_event(
            1, setpoint=(60.0, 50.0, 15.0), threats=[(63.0, 50.0, 15.0)]))))

    def test_a_dodge_with_no_recorded_threat_positions_cannot_be_checked_and_fails(self):
        """Same doctrine as the missing `swept_tree_clearance_m`: an accepted dodge whose commanded
        point cannot be measured against the bird is unvetted evidence, not a passing decision."""
        log = self._log(maneuver_event(1))
        log["events"][0]["debug"].pop("threat_positions_enu")
        self.assertInvalid(self.check(log), "cannot be checked against the bird")
        log = self._log(maneuver_event(1))
        log["events"][0].pop("setpoint_enu")
        self.assertInvalid(self.check(log), "cannot be checked against the bird")

    def test_R3_doing_its_job_is_visible_not_inferred(self):
        """A refusal emits no latch event and changes no state, so the ONLY way to count it is this
        field. If the gate did not report it, "R3 fired 6 times" would be unfalsifiable."""
        msg = self.assertValid(self.check(self._log(
            maneuver_event(1, trigger_range=0.052, latch_action="relatch_refused_degenerate"),
            maneuver_event(2, trigger_range=0.052, latch_action="relatch_refused_degenerate"))))
        self.assertIn("relatch_refused_degenerate=2", msg)
        self.assertIn("maneuvers=2", msg)

    def test_a_refusal_logged_on_a_gate_reject_event_is_counted_too(self):
        self.assertIn("relatch_refused_degenerate=1",
                      self.assertValid(self.check(self._log(gate_reject_event(1)))))

    def test_R3_8_a_bird_reject_is_the_BACKSTOP_WORKING_and_is_reported_with_its_numbers(self):
        """QA ROUND 3, FINDING 3. R3.7 reads `maneuver` events -- and the executor's whole job is to
        make sure a point inside the bar never becomes one: it writes a `gate_reject` instead. So on
        a log the CURRENT executor produced, R3.7's breach branch is unreachable (proved by
        exhaustion: 10,000 control ticks through the real policy + executor, 22 refusals, zero
        maneuvers inside the bar) and the live evidence the backstop fired was read by nothing.
        These are the numbers it wrote."""
        msg = self.assertValid(self.check(self._log(
            gate_reject_event(1, bird_clearance_m=1.0),
            gate_reject_event(2, bird_clearance_m=0.4))))
        self.assertIn("gate_rejects=2 (bird-bar rejects=2", msg)
        self.assertIn("closest refused point 0.400 m from a bird", msg)
        self.assertIn("backstop WORKING", msg)

    def test_R3_8_a_geofence_reject_is_counted_but_is_not_a_bird_reject(self):
        msg = self.assertValid(self.check(self._log(
            gate_reject_event(1, bird_clearance_m=None, obstacle_id="tree_r2_07"))))
        self.assertIn("gate_rejects=1 (bird-bar rejects=0)", msg)

    def test_R3_8_a_reject_that_explains_itself_with_NOTHING_is_a_defect(self):
        """A reject records either an obstacle or a sub-bar bird gap -- those are the only two
        branches in the executor. One that records neither means the field names drifted, and the
        drift would be silent: the count would keep rising while the numbers behind it went blank."""
        self.assertInvalid(self.check(self._log(
            gate_reject_event(1, bird_clearance_m=None))), "explains itself with neither")

    def test_R3_8_a_reject_is_scored_against_the_bar_the_FLIGHT_flew(self):
        """Same doctrine as R2/R3.7: a replayed log is checked against the bar it was flown under.
        A 4.0 m gap is a real reject on a flight flown at a 5.0 m bar, not an unexplained one."""
        self.assertValid(self.check(self._log(
            gate_reject_event(1, bird_clearance_m=4.0, min_bird_clearance_m=5.0))))

    def test_a_HOLD_reports_how_close_it_got_as_CONTEXT_and_is_never_gated(self):
        """QA ROUND 3, FINDING 2. A HOLD commands ZERO displacement, so it honours no clearance bar
        -- and in the R3-refusal branch the vehicle is inside `degenerate_range_m` by construction,
        so the hold is inside the 3.00 m bar too and can be NEARER the bird than the point just
        refused (measured: a reject at 1.000 m holding at 0.400 m). The number is printed; gating it
        would be gating escape geometry, which is R4 and open."""
        msg = self.assertValid(self.check(self._log(
            hold_event(1, bird_clearance_m=2.5), hold_event(2, bird_clearance_m=0.288))))
        self.assertIn("holds with a threat=2 of 2 hold(s) [CONTEXT, NEVER GATED]: min hold-tick "
                      "bird clearance 0.288 m", msg)
        self.assertIn("R4", msg)

    def test_the_hold_line_carries_a_DENOMINATOR_when_only_some_holds_named_a_threat(self):
        """`holds with a threat=N` alone is a numerator. A take with 1 threatened hold out of 9 and
        a take with 1 out of 1 are different flights, and R4 is booked off this number."""
        msg = self.assertValid(self.check(self._log(
            hold_event(1, bird_clearance_m=2.5), hold_event(2), hold_event(3))))
        self.assertIn("holds with a threat=1 of 3 hold(s)", msg)

    def test_a_flight_with_no_holds_still_prints_the_count_rather_than_going_silent(self):
        """ROUND 4. The line used to appear only when some hold carried a number, so "no hold ever
        named a threat" and "the hold events stopped carrying the field" printed the SAME nothing --
        and the second is field drift (below). Zero is a measurement; print it."""
        msg = self.assertValid(self.check(self._log(maneuver_event(1, clearance=5.0))))
        self.assertIn("holds with a threat=0 of 0 hold(s)", msg)
        self.assertNotIn("min hold-tick bird clearance", msg)   # no number to report, and it says so
        self.assertIn("unmeasured, not clean", msg)

    def test_holds_that_lost_the_bird_clearance_FIELD_are_field_drift_not_a_quiet_zero(self):
        """The same rule R3.8 applies to a gate_reject. `_handle_hold` writes bird_clearance_m on
        EVERY hold (None when the decision names no threat), so a missing KEY means the fields the
        executor writes and the fields read here have parted -- and the hold count would go on
        rising with nothing behind it."""
        drifted = hold_event(1)
        drifted.pop("bird_clearance_m")
        self.assertInvalid(self.check(self._log(drifted, hold_event(2, bird_clearance_m=0.4))),
                           "1 of 2 hold event(s) carry no USABLE bird_clearance_m")

    def test_an_UNUSABLE_bird_clearance_is_drift_too_not_a_hold_that_named_no_threat(self):
        """ROUND 5. The quieter half of the same defect: a present value of the wrong TYPE.
        `_num` refuses it (rightly -- a gate that reads `True` as 1.0 can be passed with the wrong
        type), so the tick fell into the "named no threat" bucket and a hold whose clearance had
        become a string read exactly like a hold with no bird near it, while `holds with a threat=N
        of M` kept counting M. An unusable value is not an absent threat."""
        for bad in ("2.5", {"m": 2.5}, [2.5], True):
            with self.subTest(value=bad):
                result = self.check(self._log(hold_event(1, bird_clearance_m=bad),
                                              hold_event(2, bird_clearance_m=0.4)))
                self.assertInvalid(result, "1 of 2 hold event(s) carry no USABLE bird_clearance_m")
                self.assertInvalid(result, "first at tick 1")
                # ...and it never counted as a hold that measured something.
                self.assertIn("holds with a threat=1 of 2 hold(s)", " ".join(result[1]))

    def test_a_hold_that_names_NO_threat_keeps_the_key_and_is_not_drift(self):
        """None is a legitimate value -- a hand-built HOLD or a geofence-only reject names no bird.
        Only an ABSENT key or an UNUSABLE value is drift, and the three must not be conflated."""
        msg = self.assertValid(self.check(self._log(hold_event(1), hold_event(2))))
        self.assertIn("holds with a threat=0 of 2 hold(s)", msg)


# ================================================================================================
# 7. Detector source dispatch -- what the logged detections are WORTH
# ================================================================================================
class TestDetectorSource(Harness):
    def test_no_detector_and_no_events_is_an_honest_valid(self):
        msg = self.assertValid(self.check(make_log(run=make_run(checker.DET_NONE))))
        self.assertIn("no avoidance claimed", msg)

    def test_no_detector_but_avoidance_events_is_a_log_lying_about_its_own_provenance(self):
        log = make_log(events=[detection_event(1, (50.0, 60.0, 15.0))],
                       run=make_run(checker.DET_NONE))
        self.assertInvalid(self.check(log), "cannot also claim avoidance evidence")

    def test_an_unknown_source_is_refused_rather_than_guessed(self):
        for src in ("yolov8", None, "", 3):
            with self.subTest(source=src):
                self.assertInvalid(self.check(make_log(run=make_run(src))),
                                   "refuses to score the flight")

    def test_a_missing_detector_block_is_invalid(self):
        run = make_run()
        run.pop("detector")
        self.assertInvalid(self.check(make_log(run=run)), "refuses to score the flight")

    def test_the_demo_bird_is_still_gated_on_its_own_logged_position(self):
        """`demo_virtual` needs no truth track: the logged bird IS exact truth, a constant we
        chose. R1's gate is the correct one and runs unchanged."""
        near = detection_event(1, (DRONE_XY[0], DRONE_XY[1] + 0.05, CRUISE_Z))
        log = make_log(events=[near], run=make_run(checker.DET_DEMO_VIRTUAL))
        status, messages = self.check(log)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("CPA BREACH", blob)
        self.assertIn("0.0500", blob)
        self.assertIn("the logged bird IS truth", blob)

    def test_a_clean_demo_flight_passes_with_its_number_printed(self):
        far = detection_event(1, (DRONE_XY[0], DRONE_XY[1] + 8.0, CRUISE_Z))
        msg = self.assertValid(self.check(make_log(events=[far],
                                                   run=make_run(checker.DET_DEMO_VIRTUAL))))
        self.assertIn("CPA 8.0000 m", msg)

    def test_a_demo_flight_with_no_positioned_detection_says_so(self):
        msg = self.assertValid(self.check(make_log(run=make_run(checker.DET_DEMO_VIRTUAL))))
        self.assertIn("NO-CPA-EVIDENCE", msg)


# ================================================================================================
# 7b. The DETECT half -- a detector that never saw a frame did not fly the take
# ================================================================================================
class TestDetectorActuallyRan(Harness):
    """`NdviDetectionSource.on_frame` drops every frame while it has no intrinsics, and the node
    refuses to start without a Gazebo clock but has NO equivalent guard on `/fg/ndvi/camera_info`.
    So a take whose ndvi_node came up after the avoidance shell flies to completion and writes a
    clean schema-2 log. The counters have been written since the seam landed and read by nothing --
    the take's headline claim ("detect -> avoid, at a measured separation") would have been quoted
    off a flight whose detect half was never measured."""

    def _check(self, counters, path=None):
        truth = self.write_truth(truth_records(straight_line("bird_0", [(50.0, 58.0)] * 4)))
        run = make_run(checker.DET_NDVI_BLOB, counters=counters)
        return self.check(make_log(run=run, path=path), truth=truth)

    def test_a_detector_that_never_saw_a_frame_fails_instead_of_certifying_the_take(self):
        status, messages = self._check(detector_counters(
            ndvi_msgs_received=1200, frames_detected_on=0, frames_with_detection=0, boxes_total=0,
            dropped_no_intrinsics=1200))
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("DETECTOR NEVER RAN: 0 of 1200 NDVI message(s)", blob)
        self.assertIn("no_intrinsics=1200", blob)
        # ...and the flight was otherwise spotless, which is exactly why this had to be a gate.
        self.assertIn("gt_cpa_m 8.0000", blob)

    def test_a_detector_fed_a_handful_of_frames_fails_the_floor_not_just_the_zero(self):
        """QA ROUND 2, FINDING 6. `frames_detected_on == 0` was a hard INVALID and
        `frames_detected_on == 1` of 1256 passed with no comment -- the same broken bringup one tick
        later (`/fg/ndvi/camera_info` arriving four minutes into a five minute take, or a starved
        PoseBuffer). This project's own precedent (ADR-013 am. 4) is that evidence bars are FLOORS
        with a number behind them."""
        status, messages = self._check(detector_counters(
            ndvi_msgs_received=1256, frames_detected_on=1, frames_with_detection=0, boxes_total=0,
            dropped_no_intrinsics=1255))
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("DETECTOR BARELY RAN: 1 of 1256", blob)
        self.assertIn("0.07%", blob)                  # truncated, never rounded up to the floor
        self.assertIn("90.00%", blob)                 # the floor, named in the message

    def test_the_floor_is_a_rate_with_both_numbers_printed_on_every_flight(self):
        msg = self.assertValid(self._check(detector_counters()))
        self.assertIn("detect rate 100.00% (floor 90.00%)", msg)

    def test_THE_ROUND_3_PROBE_a_log_that_FAILS_the_floor_never_prints_the_floor(self):
        """QA ROUND 3, FINDING 7. `1130/1256 = 0.899681` fails the 0.90 floor and printed
        "= 90.0%, below the 90% floor" -- a sentence that reads as a gate bug in a scrollback and
        invites someone to widen the floor after a failure, which this gate's own open item warns
        against. The rate is now TRUNCATED to the printed digits, so the printed number is a true
        statement about the comparison. 1130 is the row that will actually be met in the field: a
        floor is met near the floor."""
        status, messages = self._check(detector_counters(
            ndvi_msgs_received=1256, frames_detected_on=1130, dropped_no_intrinsics=126))
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("DETECTOR BARELY RAN: 1130 of 1256", blob)
        self.assertIn("89.96%", blob)
        self.assertNotIn("= 90.0%", blob)
        self.assertNotIn("= 90.00%", blob)
        # And the unit, at the boundary from both sides -- truncation, never rounding.
        self.assertEqual(checker._floor_pct(1130 / 1256), "89.96%")
        self.assertEqual(checker._floor_pct(0.8999999), "89.99%")
        self.assertEqual(checker._floor_pct(0.9), "90.00%")
        self.assertEqual(checker._floor_pct(1.0), "100.00%")

    def test_the_floor_is_where_it_says_it_is_in_both_directions(self):
        """A startup transient (frames published before intrinsics land) is legitimate and must not
        fail a take; 90 % is ~3x the worst plausible one at 5 Hz. Pinned in both directions so
        moving it is a decision, not a drift."""
        self.assertValid(self._check(detector_counters(ndvi_msgs_received=1000,
                                                       frames_detected_on=900,
                                                       dropped_no_intrinsics=100)))
        self.assertInvalid(self._check(detector_counters(ndvi_msgs_received=1000,
                                                         frames_detected_on=899,
                                                         dropped_no_intrinsics=101)),
                           "DETECTOR BARELY RAN")

    def test_the_same_flight_with_a_working_detector_passes(self):
        """The control arm: only the counters differ between this and the case above."""
        msg = self.assertValid(self._check(detector_counters()))
        self.assertIn("frames_detected_on=1256", msg)

    def test_missing_counters_are_a_defect_not_a_zero(self):
        truth = self.write_truth(truth_records(straight_line("bird_0", [(50.0, 58.0)] * 4)))
        run = make_run(checker.DET_NDVI_BLOB)
        run["detector"].pop("counters")
        self.assertInvalid(self.check(make_log(run=run), truth=truth),
                           "run.detector.counters missing")

    def test_a_half_written_counter_block_is_refused_key_by_key(self):
        for key in checker.DETECTOR_COUNTER_KEYS:
            with self.subTest(missing=key):
                counters = detector_counters()
                counters.pop(key)
                self.assertInvalid(self._check(counters), "missing or non-numeric")

    def test_a_non_numeric_counter_cannot_pass_as_a_number(self):
        self.assertInvalid(self._check(detector_counters(frames_detected_on="1256")),
                           "missing or non-numeric")

    def test_a_detector_that_ran_and_saw_no_bird_is_reported_not_failed(self):
        """The honest zero: 1256 frames through the detector, no blob above threshold. That is a
        perception finding (and the missed-detection line says so), not a broken flight."""
        msg = self.assertValid(self._check(detector_counters(frames_with_detection=0,
                                                             boxes_total=0)))
        self.assertIn("frames_detected_on=1256", msg)
        self.assertIn("frames_with_detection=0", msg)

    def test_the_counters_reach_the_operator_on_a_passing_flight(self):
        msg = self.assertValid(self._check(detector_counters(dropped_no_pose_pair=7)))
        self.assertIn("detector counters:", msg)
        self.assertIn("ndvi_msgs_received=1256", msg)
        self.assertIn("no_pose_pair=7", msg)

    def test_the_demo_and_idle_sources_are_not_held_to_counters_they_never_write(self):
        for source in (checker.DET_DEMO_VIRTUAL, checker.DET_NONE):
            with self.subTest(source=source):
                self.assertValid(self.check(make_log(run=make_run(source))))

    def test_a_flight_whose_every_detection_EXPIRED_cannot_certify_itself(self):
        """QA ROUND 2, FINDING 2, the artifact half. The staleness gate can disable avoidance for a
        whole flight -- a sub-second clock offset ages every detection out, the policy PROCEEDs on
        every tick, and the log then reads exactly like a quiet sky: 0 detections, 0 maneuvers,
        `R2/R3 PASS (vacuous)`, everything else green. The executor now records the drops on the
        proceed events, and drops > 0 with 0 engagements is a hard failure, not a note."""
        proceeds = [{"seq": i, "tick": i, "kind": "proceed", "position_enu": [50.0, 50.0, 15.0],
                     "debug": {"n_stale_dropped": 1, "stale_ids": ["bird_0"]}} for i in (1, 2, 3)]
        truth = self.write_truth(truth_records(straight_line("bird_0", [(50.0, 58.0)] * 4)))
        run = make_run(checker.DET_NDVI_BLOB, counters=detector_counters(boxes_total=3))
        status, messages = self.check(make_log(events=proceeds, run=run), truth=truth)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("AVOIDANCE WAS DEAD", blob)
        self.assertIn("dropped 3 detection(s)", blob)
        self.assertIn("n_stale_dropped=3 over 0 detection event(s)", blob)

    def test_boxes_with_no_engagement_and_no_drops_is_the_honest_reading_and_says_so(self):
        """The opposite diagnosis, which must stay PASSING: the detector saw birds and every one of
        them fell outside the threat cylinder. That is a real flight -- but it is now stated in
        words rather than left as an absent number beside a vacuous R2/R3 pass."""
        truth = self.write_truth(truth_records(straight_line("bird_0", [(50.0, 58.0)] * 4)))
        run = make_run(checker.DET_NDVI_BLOB, counters=detector_counters(boxes_total=24))
        msg = self.assertValid(self.check(make_log(events=[], run=run), truth=truth))
        self.assertIn("engaged on 0 tick(s), with 0 stale drops", msg)
        self.assertIn("outside", msg.lower())
        self.assertIn("n_stale_dropped=0 over 0 detection event(s)", msg)

    def test_drops_alongside_a_working_loop_are_reported_and_not_failed(self):
        """A stale frame here and there with the loop still engaging is a render stall, not a dead
        flight. The gate fires on the combination, never on the count alone."""
        truth = self.write_truth(truth_records(straight_line("bird_0", [(50.0, 58.0)] * 4)))
        run = make_run(checker.DET_NDVI_BLOB, counters=detector_counters(boxes_total=24))
        events = [detection_event(1, (50.0, 58.0, CRUISE_Z)),
                  {"seq": 2, "tick": 2, "kind": "proceed", "position_enu": [50.0, 50.0, 15.0],
                   "debug": {"n_stale_dropped": 5, "stale_ids": ["bird_0"]}}]
        msg = self.assertValid(self.check(make_log(events=events, run=run), truth=truth))
        self.assertIn("n_stale_dropped=5 over 1 detection event(s)", msg)

    def test_the_keys_the_gate_reads_are_the_keys_the_DETECTOR_writes(self):
        """Field-name drift is otherwise silent: a renamed counter would make this gate report
        'missing' forever, or (worse) stop noticing a detector that never ran."""
        try:
            from fieldguard_planning.ndvi_detect import NdviDetectionSource
        except ImportError as exc:                    # numpy/scipy tier; the gate itself is stdlib
            self.skipTest(f"detector core not importable here ({exc})")
        written = set(NdviDetectionSource(-0.61).counters())
        self.assertTrue(set(checker.DETECTOR_COUNTER_KEYS) <= written,
                        sorted(set(checker.DETECTOR_COUNTER_KEYS) - written))


# ================================================================================================
# 8. THE TRUTH TRACK -- "we never looked" must never score VALID
# ================================================================================================
class TestTruthTrackRequired(Harness):
    def test_a_real_detector_flight_with_no_truth_track_anywhere_is_invalid(self):
        self.assertInvalid(self.check(make_log()), "no truth track")

    def test_it_is_required_even_when_the_flight_claims_nothing_happened(self):
        """The most important case in this file: zero detections is what a MISSED bird looks like.
        Without truth, "the detector saw nothing" and "nothing was there" are the same log."""
        status, messages = self.check(make_log(events=[]))
        self.assertEqual(status, checker.INVALID, " ".join(messages))
        self.assertIn("measured nothing about separation", " ".join(messages))

    def test_an_explicit_truth_path_that_does_not_exist_is_invalid(self):
        self.assertInvalid(self.check(make_log(), truth=self.dir / "nope.jsonl"), "no truth track")

    def test_a_wall_clock_driver_run_is_not_a_truth_track(self):
        """`clock: "wall"` has no sim anchor at all, so its poses can never be placed on the clock
        the flight is stamped in. It must not be auto-discovered into a green verdict."""
        self.write_truth(truth_records(straight_line("bird_0", [(0, 0)] * 4)), clock="wall")
        self.assertInvalid(self.check(make_log()), "no truth track")

    def test_a_sidecar_whose_applied_log_never_landed_on_disk_is_not_a_truth_track(self):
        self.write_truth(truth_records(straight_line("bird_0", [(0, 0)] * 4)), applied=False)
        self.assertInvalid(self.check(make_log()), "no truth track")

    def test_a_log_where_every_set_pose_failed_answers_for_nothing(self):
        self.write_truth(truth_records(straight_line("bird_0", [(0, 0)] * 4), ok=False))
        self.assertInvalid(self.check(make_log()), "no truth track")

    def test_a_non_overlapping_truth_track_is_a_DIFFERENT_take_not_a_pass(self):
        """Gazebo sim time restarts near 0 each run. Accepting a non-overlapping log would score
        every tick against birds frozen at spawn: confidently wrong, not unmeasured."""
        far = [(t + 9000.0, {"bird_0": (0.0, 0.0, 15.0)}) for t in TRUTH_SIM]
        truth = self.write_truth(truth_records(far))
        self.assertInvalid(self.check(make_log(), truth=truth), "no overlap")
        self.assertInvalid(self.check(make_log()), "no truth track")     # not discovered either

    def test_two_overlapping_candidates_are_ambiguous_and_the_operator_must_choose(self):
        self.write_truth(truth_records(straight_line("bird_0", [(0, 0)] * 4)), stamp="A")
        self.write_truth(truth_records(straight_line("bird_1", [(0, 0)] * 4)), stamp="B")
        self.assertInvalid(self.check(make_log()), "ambiguous truth track")

    def test_an_explicit_truth_does_not_silence_the_exactly_one_guard(self):
        """QA ROUND 2, FINDING 5. `--truth` used to skip candidate discovery entirely, and the
        runbook's own invocation is `ls -t …_applied.jsonl | head -1` -- so ONE aborted takeoff (the
        runbook warns about `Arm: Accels inconsistent` and a retry) or one `fly_pipeline.sh birds`
        override leaves two applied logs for a single take, `head -1` picks the one covering the
        TAIL, and every earlier tick is answered from the birds' config SPAWN poses. bird_0 spawns
        4 m below cruise directly under mission lane x=15, so that either fabricates a ~0 m breach
        or hides a real one, and the only signal was a non-gating note."""
        self.write_truth(truth_records(straight_line("bird_0", [(50.0, 58.0)] * 4)), stamp="FIRST")
        second = self.write_truth(truth_records(straight_line("bird_0", [(50.0, 58.0)] * 4)),
                                  stamp="SECOND")
        status, messages = self.check(make_log(), truth=second)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("AMBIGUOUS TAKE", blob)
        self.assertIn("bird_drive_FIRST_applied.jsonl", blob)     # the log it named, by name

    def test_one_applied_log_plus_an_explicit_truth_is_the_normal_green_path(self):
        """The control arm -- the guard must not fire on the take it was written for."""
        truth = self.write_truth(truth_records(straight_line("bird_0", [(50.0, 58.0)] * 4)))
        self.assertIn("gt_cpa_m 8.0000", self.assertValid(self.check(make_log(), truth=truth)))

    def test_a_sibling_log_that_does_NOT_overlap_this_take_is_not_an_ambiguity(self):
        """Old evidence from a previous session is the normal state of eval/results/. Only a log
        that could answer for THIS flight's window can be the wrong answer to it."""
        self.write_truth(truth_records([(t + 9000.0, {"bird_0": (0.0, 0.0, CRUISE_Z)})
                                        for t in TRUTH_SIM]), stamp="OLD")
        truth = self.write_truth(truth_records(straight_line("bird_0", [(50.0, 58.0)] * 4)))
        self.assertValid(self.check(make_log(), truth=truth))

    def test_exactly_one_overlapping_candidate_is_discovered_and_named(self):
        self.write_truth(truth_records(straight_line("bird_0", [(0, 0)] * 4)), stamp="A")
        self.write_truth(truth_records(straight_line("bird_1", [(0, 0)] * 4)), stamp="B9",
                         clock="wall")                        # unusable -> not a candidate
        msg = self.assertValid(self.check(make_log()))
        self.assertIn("bird_drive_A_applied.jsonl", msg)

    def test_a_truth_track_for_a_bird_the_world_does_not_define_is_refused(self):
        truth = self.write_truth(truth_records(straight_line("seagull_7", [(0, 0)] * 4)))
        self.assertInvalid(self.check(make_log(), truth=truth), "the flown world disagree")

    def _driver_stopped_early(self):
        """A truth track whose last landed call is at sim 101.002 -- so this flight's ticks
        (100.5 / 101.5 / 102.5) are covered, then not."""
        return self.write_truth(truth_records(
            [(TRUTH_SIM[0], {"bird_0": (0.0, 0.0, 15.0)}),
             (TRUTH_SIM[1], {"bird_0": (0.0, 0.0, 15.0)})]))

    def test_an_encounter_tick_with_no_truth_cannot_certify_itself(self):
        """The driver stopped before the flight did, and a later tick logged a maneuver.
        Forward-extrapolating 'the bird held its last pose' there is an assertion nothing
        observed."""
        truth = self._driver_stopped_early()
        log = make_log(events=[maneuver_event(3, clearance=5.0)])
        self.assertInvalid(self.check(log, truth=truth), "cannot certify its own encounter")

    def test_the_same_gap_is_tolerated_when_nothing_happened_in_it(self):
        truth = self._driver_stopped_early()
        log = make_log(events=[maneuver_event(1, clearance=5.0)])
        self.assertIn("truth coverage 1/3 ticks", self.assertValid(self.check(log, truth=truth)))

    def test_partial_coverage_without_events_is_reported_with_a_denominator_not_hidden(self):
        truth = self._driver_stopped_early()
        msg = self.assertValid(self.check(make_log(), truth=truth))
        self.assertIn("truth coverage 1/3 ticks", msg)

    def test_an_event_on_a_tick_the_path_never_recorded_is_blind_not_skipped(self):
        """An encounter tick outside 1..len(flown_path) has no recorded POSITION at all, so it is
        unlocatable rather than merely untruthed. Walking only the path's own range would let a
        corrupt log hide its encounter past the end of the array."""
        truth = self.write_truth(truth_records(
            [(t, {"bird_0": (0.0, 0.0, 15.0)}) for t in TRUTH_SIM]))
        for tick in (0, 99):
            with self.subTest(tick=tick):
                log = make_log(events=[maneuver_event(tick, clearance=5.0)])
                self.assertInvalid(self.check(log, truth=truth),
                                   "cannot certify its own encounter")

    def test_a_single_call_truth_track_has_a_point_span_and_cannot_be_matched(self):
        """Documented edge: with one tick there is no MEASURED real-time factor anywhere, so
        `applied_sim_brackets` collapses the bracket to the poll instant rather than inventing a
        rate. A point span overlaps essentially nothing -- correct, and refused loudly."""
        truth = self.write_truth(truth_records([(TRUTH_SIM[0], {"bird_0": (0.0, 0.0, 15.0)})]))
        self.assertInvalid(self.check(make_log(), truth=truth), "no overlap")


# ================================================================================================
# 8b. TRUTH_BINDINGS -- which truth track belongs to which take (QA finding G47, 2026-08-25)
# ================================================================================================
class TestTruthBindings(Harness):
    """A flight reaches its bird track by a REVIEWED PIN, not by sim-time overlap.

    THE FAILURE THIS CLASS EXISTS FOR. Gazebo sim time restarts near 0 every run, so the first
    committed applied log overlaps EVERY later take. From the second committed track onward the
    overlap scan could only say AMBIGUOUS: measured on the 2026-08-25 take, the gate printed no CPA
    at all (the 0.0067 m breach was unreachable), and then told the operator the take's own
    SAFETY_FINDING marker was stale "beside a log that does not breach CPA". CI could never have
    reproduced the breach verdict. Overlap cannot identify a take; a pin can.

    Every fixture here uses the SHIPPED binding rather than a hand-typed stem -- a test may not
    assert a join the shipped gate would not make.
    """

    OTHER_XY = (50.0, 62.0)          # the rival track's bird: 12.0 m away, a DIFFERENT number
    BOUND_XY = (50.0, 58.0)          # the bound track's bird: 8.0 m away

    def _rival(self):
        """The role the committed 2026-08-23 track plays in the real results dir: a perfectly
        readable applied log, overlapping this flight's window, belonging to another take."""
        return self.write_truth(truth_records(straight_line("bird_0", [self.OTHER_XY] * 4)),
                                stamp="RIVALTAKE")

    def _bound(self):
        return self.write_truth(truth_records(straight_line("bird_0", [self.BOUND_XY] * 4)),
                                stamp=BOUND_STAMP)

    def test_a_bound_take_joins_its_OWN_track_with_a_rival_log_sitting_right_there(self):
        """The headline: no --truth, two overlapping logs, and the flight is still scored."""
        self._rival()
        self._bound()
        msg = self.assertValid(self.check(make_log(), name=BOUND_LOG))
        self.assertIn("gt_cpa_m 8.0000", msg)                    # the BOUND bird, not the rival's
        self.assertIn(BOUND_TRUTH_NAME, msg)                     # and it names what it joined
        self.assertNotIn("AMBIGUOUS", msg)
        self.assertNotIn("ambiguous truth track", msg)

    def test_an_explicit_truth_that_AGREES_with_the_binding_is_the_runbook_invocation(self):
        """`--truth <the driver's own log>` is what AVOIDANCE_REAL_DETECTION.md tells the operator
        to type. With a rival log present that used to be a hard AMBIGUOUS TAKE."""
        self._rival()
        truth = self._bound()
        msg = self.assertValid(self.check(make_log(), truth=truth, name=BOUND_LOG))
        self.assertIn("gt_cpa_m 8.0000", msg)

    def test_a_truth_the_command_line_SUBSTITUTES_for_the_binding_is_refused(self):
        """A pin the command line can override is not a pin. The rival log is readable, overlapping
        and wrong -- and it is exactly what `ls -t …_applied.jsonl | head -1` hands you after an
        aborted takeoff."""
        rival = self._rival()
        self._bound()
        result = self.check(make_log(), truth=rival, name=BOUND_LOG)
        self.assertInvalid(result, "CONTRADICTS the reviewed binding")
        self.assertInvalid(result, BOUND_TRUTH_NAME)             # names the log it wanted
        blob = " ".join(result[1])
        for either_track in ("gt_cpa_m 12.0000", "gt_cpa_m 8.0000"):
            self.assertNotIn(either_track, blob)                 # neither track scored the flight

    def test_THE_PROBE_a_bound_track_that_is_MISSING_is_never_replaced_by_the_rival(self):
        """The dangerous shape of a fallback. With the bound log absent, the overlap scan finds
        EXACTLY ONE candidate -- the rival -- so a binding that fell back would score this flight
        against another take's bird and report a confident 12.0000 m PASS. The pin is not a hint."""
        self._rival()
        result = self.check(make_log(), name=BOUND_LOG)
        self.assertInvalid(result, "no truth track")
        self.assertInvalid(result, "TRUTH_BINDINGS")
        blob = " ".join(result[1])
        self.assertNotIn("gt_cpa_m 12.0000", blob)               # the rival's answer, never given
        self.assertNotIn("bird_drive_RIVALTAKE_applied.jsonl", blob)

    def test_an_explicit_truth_that_does_not_exist_is_still_the_first_thing_reported(self):
        """A typo'd path on a bound flight must not be silently healed by the binding."""
        self._bound()
        self.assertInvalid(self.check(make_log(), truth=self.dir / "nope.jsonl", name=BOUND_LOG),
                           "does not exist")

    def test_the_bound_track_must_still_OVERLAP_the_flight_it_is_bound_to(self):
        """The pin says which log; it does not say the flight and the log are the same take. A
        binding pointing at a non-overlapping track is a bad pin, and stays a hard refusal."""
        self.write_truth(truth_records([(t + 9000.0, {"bird_0": (0.0, 0.0, CRUISE_Z)})
                                        for t in TRUTH_SIM]), stamp=BOUND_STAMP)
        self.assertInvalid(self.check(make_log(), name=BOUND_LOG), "no overlap")

    def test_an_UNPINNED_flight_is_left_exactly_as_it_was(self):
        """The other half of the contract, and the reason the binding is a dict rather than a
        loosened rule: a take nobody reviewed still has to prove which track is its own."""
        self._rival()
        rival2 = self.write_truth(truth_records(straight_line("bird_0", [self.BOUND_XY] * 4)),
                                  stamp="SECOND")
        self.assertInvalid(self.check(make_log(), name=NEW_TAKE_LOG), "ambiguous truth track")
        self.assertInvalid(self.check(make_log(), truth=rival2, name=NEW_TAKE_LOG),
                           "AMBIGUOUS TAKE")

    def test_the_binding_values_are_shaped_like_applied_logs(self):
        """Structural, and it proves this file's own BOUND_STAMP round trip: every value must be a
        `bird_drive_<stamp>_applied.jsonl` filename (never a path) -- that is the name the driver
        writes, the name `.gitignore` re-includes so CI checks it out, and the name resolved BESIDE
        the flight log."""
        for stem, name in checker.TRUTH_BINDINGS.items():
            with self.subTest(stem=stem):
                self.assertTrue(stem.startswith("live_flight_log_"), stem)
                self.assertEqual(Path(name).name, name, "a binding value is a filename, not a path")
                self.assertTrue(name.startswith("bird_drive_"), name)
                self.assertTrue(name.endswith("_applied.jsonl"), name)
        self.assertEqual(f"bird_drive_{BOUND_STAMP}_applied.jsonl", BOUND_TRUTH_NAME)

    def test_a_bound_flight_that_is_COMMITTED_has_its_track_committed_beside_it(self):
        """If the flight log is in eval/results, the log it is bound to must be there too -- else
        the committed evidence is unscoreable and CI reports 'no truth track' instead of the
        flight's real verdict. Skips per binding whose flight log is not present (eval/results is
        gitignored in some checkouts)."""
        for stem, name in checker.TRUTH_BINDINGS.items():
            log = checker.RESULTS_DIR / f"{stem}.json"
            if not log.exists():
                continue
            with self.subTest(stem=stem):
                self.assertTrue(log.with_name(name).exists(),
                                f"{stem} is bound to {name}, which is not beside it in "
                                f"{checker.RESULTS_DIR.name}/ -- the gate cannot score the take")


# ================================================================================================
# 9. The ground-truth CPA itself
# ================================================================================================
class TestGroundTruthCpa(Harness):
    def _fly(self, bird_xyz_by_tick, events=None, truth_kw=None, log_kw=None):
        recs = truth_records([(t, {"bird_0": p}) for t, p in zip(TRUTH_SIM, bird_xyz_by_tick)])
        truth = self.write_truth(recs, **(truth_kw or {}))
        return self.check(make_log(events=events, **(log_kw or {})), truth=truth)

    def test_a_clean_pass_reports_the_measured_number_and_where_it_happened(self):
        msg = self.assertValid(self._fly([(50.0, 58.0, 15.0)] * 4))
        self.assertIn("gt_cpa_m 8.0000 m to bird_0", msg)
        self.assertIn("vertical sep 0.0000", msg)
        self.assertIn("3D 8.0000", msg)

    def test_a_true_breach_fails_even_though_no_gate_the_policy_ran_noticed(self):
        status, messages = self._fly([(50.0, 50.05, 15.0)] * 4)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("CPA BREACH", blob)
        self.assertIn("0.0500", blob)

    def test_the_bar_is_the_policys_own_and_moves_with_it(self):
        log_at_5m = [(50.0, 55.0, 15.0)] * 4
        self.assertValid(self._fly(log_at_5m))
        with patched_params(min_bird_clearance_m=10.0):
            self.assertInvalid(self._fly(log_at_5m), "CPA BREACH")

    def test_vertical_scoping_is_what_stops_the_gate_meaning_nothing(self):
        """bird_1 and bird_2 patrol 7-9 m below cruise and pass under the lanes constantly. An
        unscoped horizontal bar would fail every flight forever; the band is the POLICY's own
        `vertical_threat_m`, so gate and control law cannot drift."""
        under = [(50.0, 50.0, CRUISE_Z - 9.0)] * 4        # directly underneath, 9 m below
        msg = self.assertValid(self._fly(under))
        self.assertIn("NONE-IN-BAND", msg)
        self.assertIn("Nearest bird in ANY band: 0.0000 m", msg)   # the number still exists

    def test_the_band_edge_is_inclusive_and_pinned(self):
        vt = PolicyParams().vertical_threat_m
        self.assertInvalid(self._fly([(50.0, 50.5, CRUISE_Z - vt)] * 4), "CPA BREACH")
        self.assertValid(self._fly([(50.0, 50.5, CRUISE_Z - vt - 0.001)] * 4))

    def test_widening_the_policys_threat_band_pulls_a_bird_back_into_scope(self):
        under = [(50.0, 50.0, CRUISE_Z - 9.0)] * 4
        self.assertValid(self._fly(under))
        with patched_params(vertical_threat_m=12.0):
            self.assertInvalid(self._fly(under), "CPA BREACH")

    def test_horizontal_not_3d_because_3d_can_only_manufacture_clearance(self):
        """5 m below and 1 m to the side is a 5.1 m 3D separation and a 1 m MISS distance. ADR-009:
        bird z is the estimate we cannot trust, so it does not get to buy clearance."""
        status, messages = self._fly([(50.0, 51.0, CRUISE_Z - 5.0)] * 4)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("CPA BREACH: flew within 1.0000 m", blob)
        self.assertIn("3D 5.0990", blob)                  # reported as context, not as the gate

    def test_ambiguity_is_resolved_AGAINST_the_flight(self):
        """A tick inside a `set_pose` bracket is genuinely undecidable: the render showed either the
        held pose or the new one. The gate takes the NEARER: uncertainty must not buy clearance."""
        recs = truth_records([(TRUTH_SIM[0], {"bird_0": (50.0, 70.0, 15.0)}),
                              (TRUTH_SIM[1], {"bird_0": (50.0, 50.1, 15.0)})])
        truth = self.write_truth(recs)
        second = [r for r in recs if r["bird_id"] == "bird_0"][1]
        inside_bracket = second["wall_start_s"] + 0.0005      # strictly inside the second bracket
        # Three DISTINCT stamps inside that ~1 ms bracket: the axis still has to advance (a frozen
        # one is its own failure), and ambiguity is what is under test here.
        run = make_run(stamps=[inside_bracket + i * 0.0001 for i in range(3)])
        status, messages = self.check(make_log(run=run), truth=truth)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("0.1000", blob)                     # the NEAR candidate decided the verdict

    def test_before_the_first_landed_call_the_bird_is_at_its_exact_spawn_pose(self):
        """ADR-012 am. 1: the model is <static> at waypoints[0] until the first set_pose lands.
        bird_0 spawns at (15, 5, 11) -- 4 m below cruise, so it IS in band; a flight that passes
        over the spawn point before the driver starts must still be measured."""
        recs = truth_records([(TRUTH_SIM[2], {"bird_0": (0.0, 0.0, 15.0)}),
                              (TRUTH_SIM[3], {"bird_0": (0.0, 0.0, 15.0)})])
        truth = self.write_truth(recs)
        # Tick 1 predates the driver's first landed call (102.001); ticks 2-3 are after it.
        run = make_run(stamps=[101.9, 102.5, 102.9])
        log = make_log(run=run, path=[[15.0, 5.5, CRUISE_Z]] * 3)
        status, messages = self.check(log, truth=truth)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("CPA BREACH: flew within 0.5000 m", blob)
        self.assertIn("at tick 1", blob)                  # the spawn-pose tick, not a driven one
        self.assertIn("truth coverage 3/3 ticks", blob)   # spawn is COVERAGE, not a gap

    def test_an_unstamped_tick_has_no_truth_and_is_counted_as_such(self):
        recs = truth_records([(t, {"bird_0": (0.0, 0.0, 15.0)}) for t in TRUTH_SIM])
        truth = self.write_truth(recs)
        run = make_run(stamps=[TICK_SIM[0], None, TICK_SIM[2]])
        msg = self.assertValid(self.check(make_log(run=run), truth=truth))
        self.assertIn("truth coverage 2/3 ticks", msg)

    def test_a_malformed_path_point_does_not_crash_the_gate(self):
        recs = truth_records([(t, {"bird_0": (0.0, 0.0, 15.0)}) for t in TRUTH_SIM])
        truth = self.write_truth(recs)
        log = make_log(path=[[50.0, 50.0, 15.0], ["x", 50.0, 15.0], [50.0, 50.0, 15.0]])
        msg = self.assertValid(self.check(log, truth=truth))
        self.assertIn("truth coverage 2/3 ticks", msg)


# ================================================================================================
# 9a. gt_cpa_m over the flown POLYLINE, not its 5 Hz vertices (QA round 2, finding 4)
# ================================================================================================
class TestTheCpaIsMeasuredOverThePathNotItsVertices(Harness):
    """A minimum sampled at vertices is always >= the true minimum: the one direction a safety
    number may not be wrong in. Both probes below are built only from MEASURED numbers -- drone step
    p50 0.747 / p95 1.892 / max 2.052 m per tick on the 2026-08-23 log, and a 3.16 m bird teleport
    per `set_pose` at ~1.9 Hz per bird over the committed 860-record applied log -- so this is not a
    contrived geometry, it is the flight's own discretisation against a 3.00 m bar."""

    def _fly(self, path, bird_by_anchor):
        recs = truth_records([(t, {"bird_0": p}) for t, p in zip(TRUTH_SIM, bird_by_anchor)])
        truth = self.write_truth(recs)
        run = make_run(n_path=len(path))
        return self.check(make_log(run=run, path=path), truth=truth), truth

    def test_a_bird_the_drone_passed_BETWEEN_two_ticks_is_measured_not_missed(self):
        """PROBE 1. Stationary bird, drone stepping the measured MAX 2.052 m/tick, bird 2.8200 m off
        the track at the midpoint of a step. Vertex sampling reports 3.0008 m -> PASS
        (sqrt(1.026^2 + 2.82^2), the two bounding vertices); the flown path came 2.8200 m from it
        and BREACHES."""
        path = [[50.0, 50.0, CRUISE_Z], [52.052, 50.0, CRUISE_Z], [54.104, 50.0, CRUISE_Z]]
        bird = (51.026, 52.82, CRUISE_Z)
        self.assertAlmostEqual(min(math.dist(p[:2], bird[:2]) for p in path), 3.0008, places=4)
        (status, messages), _ = self._fly(path, [bird] * 4)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("gt_cpa_m 2.8200", blob)
        self.assertIn("CPA BREACH", blob)

    def test_a_strike_between_two_ticks_reads_as_a_strike(self):
        """The same geometry with the bird ON the track: a true 0.0000 m pass used to report
        1.0260 m -- inside the bar either way here, but the number itself was wrong by half a step
        and would have been a PASS anywhere the step lands beside the bar."""
        path = [[50.0, 50.0, CRUISE_Z], [52.052, 50.0, CRUISE_Z], [54.104, 50.0, CRUISE_Z]]
        (status, messages), _ = self._fly(path, [(51.026, 50.0, CRUISE_Z)] * 4)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("gt_cpa_m 0.0000", blob)

    def test_a_bird_TELEPORT_between_two_ticks_is_scored_against_the_segment_it_appeared_on(self):
        """PROBE 2. The truth track is a list of `set_pose` calls, so the bird jumps 3.16 m between
        landed calls while the drone flies a 1.892 m step. Vertex sampling pairs (P_i, pre-teleport)
        = 5.7600 m and (P_i+1, post-teleport) = 3.0500 m and reports 3.0500 -> PASS. The bird that
        was RENDERED for that whole step came 2.6332 m from the flown path: over-report +0.4168 m
        against a 3.00 m bar. Each tick's candidate set is now scored against BOTH bounding
        segments, so the post-teleport pose meets the segment the drone was actually flying."""
        path = [[50.0, 50.0, CRUISE_Z], [51.892, 50.0, CRUISE_Z], [53.784, 50.0, CRUISE_Z]]
        pre, post = (50.0, 55.76, CRUISE_Z), (50.3529, 52.6332, CRUISE_Z)
        self.assertAlmostEqual(math.dist(path[0][:2], pre[:2]), 5.76, places=4)
        self.assertAlmostEqual(math.dist(path[1][:2], post[:2]), 3.05, places=4)
        (status, messages), _ = self._fly(path, [pre, post, post, post])
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("gt_cpa_m 2.6332", blob)
        self.assertIn("CPA BREACH", blob)

    def test_a_single_point_path_still_measures_the_point(self):
        """No neighbours, no segments: the vertex distance is the answer, not a crash or a skip."""
        (status, messages), _ = self._fly([[50.0, 50.0, CRUISE_Z]],
                                          [(50.0, 58.0, CRUISE_Z)] * 4)
        self.assertIn("gt_cpa_m 8.0000", " ".join(messages))
        self.assertEqual(status, checker.VALID, " ".join(messages))

    def test_a_malformed_vertex_breaks_the_segments_it_bounds_and_nothing_else(self):
        """One unusable point must not silently join the two points either side of it into a
        segment the drone never flew -- that would invent a shortcut through the field."""
        path = [[50.0, 50.0, CRUISE_Z], ["x", 50.0, CRUISE_Z], [54.104, 50.0, CRUISE_Z]]
        (status, messages), _ = self._fly(path, [(52.052, 54.0, CRUISE_Z)] * 4)
        blob = " ".join(messages)
        self.assertEqual(status, checker.VALID, blob)
        self.assertIn("truth coverage 2/3 ticks", blob)
        # 4.4956 = the honest vertex distance. A phantom segment across the gap would read 4.0000.
        self.assertIn("gt_cpa_m 4.4956", blob)
        self.assertNotIn("gt_cpa_m 4.0000", blob)

    def test_the_segment_primitive_itself_clamps_to_the_ends(self):
        """Point-to-SEGMENT, not point-to-LINE: a bird behind the start of a step is measured from
        the start, not from an infinite extension of it."""
        self.assertAlmostEqual(checker._point_segment_xy_m(0.0, 0.0, 3.0, 0.0, 6.0, 0.0), 3.0)
        self.assertAlmostEqual(checker._point_segment_xy_m(9.0, 0.0, 3.0, 0.0, 6.0, 0.0), 3.0)
        self.assertAlmostEqual(checker._point_segment_xy_m(4.5, 2.0, 3.0, 0.0, 6.0, 0.0), 2.0)
        self.assertAlmostEqual(checker._point_segment_xy_m(4.0, 3.0, 4.0, 0.0, 4.0, 0.0), 3.0)
        # ...and it reports WHERE on the segment, which is what pass 2 interpolates z and t from.
        self.assertEqual(checker._point_segment_xy(0.0, 0.0, 3.0, 0.0, 6.0, 0.0)[1], 0.0)
        self.assertEqual(checker._point_segment_xy(9.0, 0.0, 3.0, 0.0, 6.0, 0.0)[1], 1.0)
        self.assertAlmostEqual(checker._point_segment_xy(4.5, 2.0, 3.0, 0.0, 6.0, 0.0)[1], 0.5)


# ================================================================================================
# 9c. ...and the BIRD is not vertex-sampled either (QA round 3, finding 1)
# ================================================================================================
class TestTheBirdIsNotSampledAtTickInstants(Harness):
    """Round 2 closed the DRONE half of the discretisation (vertices -> polyline). The BIRD half
    survived it: `candidates_at(t_i)` is asked at the flight's TICK instants, so a landed `set_pose`
    call whose entire in-effect window falls strictly between two ticks is never returned and never
    scored -- and the bird is the faster body (7.00 m/s scripted vs the drone's measured p50
    0.747 m/tick). Nothing counted it: `truth coverage K/N ticks` is ticks-covered-by-truth and
    reads 100 % regardless; the inverse rate had no denominator anywhere.

    Every number below is the finding's: the driver's MEASURED cadence of 1.84 calls/s/bird
    (0.543 s between calls, 283 calls / 153.4 s on the committed applied log) against a control tick
    of 0.70 s of sim time. Today's margin is genuine -- a 5 Hz wall timer at the measured RTF 0.605
    covers 0.121 s of sim per tick, 4.5x finer than the driver -- so this takes a ~4.5x control-loop
    starvation to bite. The defect was that the margin was unmeasured, unprinted and undefended."""

    HOVER = (50.0, 50.0, CRUISE_Z)
    FAR = (50.0, 70.0, CRUISE_Z)                 # 20 m away: a comfortable, flattering PASS
    ANCHORS = [100.0, 100.543, 101.086, 101.629, 102.172]      # the driver's measured 1.84 calls/s
    TICKS = [100.4, 101.1, 101.8]                              # 0.70 s of sim per control tick

    def _fly(self, poses, ticks=None, path=None):
        recs = truth_records([(a, {"bird_0": p}) for a, p in zip(self.ANCHORS, poses)])
        truth = self.write_truth(recs)
        stamps = list(self.TICKS if ticks is None else ticks)
        run = make_run(stamps=stamps, n_path=len(stamps))
        log = make_log(run=run, path=[list(self.HOVER)] * len(stamps) if path is None else path)
        return self.check(log, truth=truth)

    def test_THE_PROBE_a_bird_driven_through_the_drone_BETWEEN_two_ticks_is_a_strike(self):
        """The drone hovers; the bird is driven onto it by the call at sim 100.543 and driven off
        again by the call at 101.086. That pose was in effect from 100.544 to 101.088 -- and the
        ticks either side are 100.4 and 101.1, so no tick instant ever falls inside it. Pass 1 alone
        answers 'the bird was 20 m away' at 3/3 truth coverage, 0 domain violations, no freeze, and
        certifies the flight. The pose's OWN window meets the drone polyline at 0.0000 m."""
        strike = [self.FAR, self.HOVER, self.FAR, self.FAR, self.FAR]
        status, messages = self._fly(strike)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("gt_cpa_m 0.0000 m to bird_0", blob)
        self.assertIn("joined via pose_window", blob)          # the pass that caught it, named
        self.assertIn("CPA BREACH", blob)
        # ...and every reason the OLD verdict looked trustworthy is still true of this log.
        self.assertIn("truth coverage 3/3 ticks", blob)
        self.assertIn("0 domain violations", blob)
        self.assertIn("worst hidden window 0.000 s", blob)

    def test_the_tick_pass_alone_really_does_miss_it_which_is_why_pass_2_exists(self):
        """The A/B, on the same artifact: at the tick instants the truth track answers 20 m every
        time. If this ever stops being true the probe above has stopped probing anything."""
        recs = truth_records([(a, {"bird_0": p}) for a, p in
                              zip(self.ANCHORS, [self.FAR, self.HOVER, self.FAR, self.FAR,
                                                 self.FAR])])
        truth = checker.TruthTrack(self.write_truth(recs), recs,
                                   checker.load_birds(checker.DEFAULT_BIRDS_CONFIG))
        for t in self.TICKS:
            answers = truth.candidates_at(t)
            self.assertNotIn(tuple(self.HOVER), answers["bird_0"].positions, f"tick {t}")

    def test_the_same_geometry_with_the_bird_never_driven_onto_the_drone_still_passes(self):
        """The control arm: pass 2 must not invent proximity. Same cadence, same ticks, the bird
        merely 8 m away on the pose no tick sees."""
        near_miss = [self.FAR, (50.0, 58.0, CRUISE_Z), self.FAR, self.FAR, self.FAR]
        msg = self.assertValid(self._fly(near_miss))
        self.assertIn("gt_cpa_m 8.0000 m to bird_0", msg)

    def test_the_bird_axis_has_its_own_denominator_because_tick_coverage_is_not_it(self):
        """`truth coverage 3/3 ticks` was printed on the false pass above and says nothing about
        whether a bird pose was ever looked at. The second denominator is the fix the finding asked
        for: 15 landed calls (3 birds x 5 anchors), 12 of them in the flight's window."""
        msg = self.assertValid(self._fly([self.FAR] * 5))
        self.assertIn("truth coverage 3/3 ticks", msg)
        self.assertIn("truth poses scored 12/12", msg)

    def test_a_pose_window_no_stamped_drone_segment_covers_is_counted_UNSCORED(self):
        """Honest accounting on the other side: with only one stamped tick there is no drone
        SEGMENT at all, so pass 2 scores nothing -- and it still prints the denominator (3 poses
        were in effect at that instant, one per bird). '0 of 3' is a rate; '0/0' is a shrug."""
        msg = self.assertValid(self._fly([self.FAR] * 5, ticks=[100.4], path=[list(self.HOVER)]))
        self.assertIn("truth poses scored 0/3", msg)

    def test_the_window_a_pose_is_scored_over_is_the_widest_the_track_can_defend(self):
        """The unit. A pose OPENS its window when the set_pose request went out (from there the
        render may already show it -- `pose_from_applied` calls exactly that interval ambiguous) and
        CLOSES it when the NEXT landed call's reply came back. Uncertainty must not buy clearance,
        so the wider bound is the one used; the last pose holds to the end of what was observed."""
        recs = truth_records([(a, {"bird_0": (float(i), 0.0, CRUISE_Z)})
                              for i, a in enumerate(self.ANCHORS)])
        truth = checker.TruthTrack(self.write_truth(recs), recs,
                                   checker.load_birds(checker.DEFAULT_BIRDS_CONFIG))
        windows = [w for w in checker.pose_windows(truth) if w[0] == "bird_0"]
        self.assertEqual(len(windows), len(self.ANCHORS))
        for i, (_bird, _pos, w0, w1) in enumerate(windows):
            self.assertAlmostEqual(w0, self.ANCHORS[i] + 0.001, places=6)
            self.assertAlmostEqual(w1, (self.ANCHORS[i + 1] + 0.002
                                        if i + 1 < len(self.ANCHORS) else truth.span[1]), places=6)


# ================================================================================================
# 9b. An UNOBSERVED bird is not invented -- spawn poses are an observation only if this track drove
# ================================================================================================
class TestAnUnobservedBirdIsNotInvented(Harness):
    """`unknown_bird_ids` (driven but not defined) was one-directional. The inverse -- DEFINED but
    never driven -- used to be answered at the config spawn pose for the entire flight and counted
    as coverage. It matters more than it sounds: config/birds/farm_world_birds.json puts bird_0 at
    z=11 (|dz| = 4 from cruise, IN band) and bird_1/bird_2 at z=8/z=6 (|dz| = 7/9, outside
    `vertical_threat_m`), so bird_0 is the ONLY bird the vertical scoping ever gates. The design's
    guard against a wrong track ("exactly one overlapping candidate") fails precisely when THIS
    session's driver wrote no log: the only file on disk is a prior take's, and sim time restarts
    near 0 so the spans overlap trivially."""

    def _drive(self, driven_poses, path):
        recs = truth_records([(t, dict(driven_poses)) for t in TRUTH_SIM], park_undriven=False)
        truth = self.write_truth(recs)
        return self.check(make_log(path=[list(path)] * 3), truth=truth)

    OTHERS = {"bird_1": (95.0, 95.0, PARKED_Z), "bird_2": (95.0, 97.0, PARKED_Z)}

    def test_a_bird_the_track_never_drove_is_named_not_pinned_at_its_spawn_pose(self):
        """The flown path goes straight over bird_0's spawn point (15, 5). With bird_0 stripped from
        the track the gate used to answer 'bird_0 is at (15,5,11)' for every tick and report a
        fabricated 0.0000 m breach at 100 % truth coverage -- a bird nobody observed. The mirror
        image (a REAL breach hidden behind an invented static bird parked elsewhere) was equally
        available, which is why this is a refusal and not a warning."""
        status, messages = self._drive(self.OTHERS, (15.0, 5.0, CRUISE_Z))
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("NO landed set_pose call for ['bird_0']", blob)
        self.assertNotIn("gt_cpa_m 0.0000", blob)              # the fabricated number is gone
        self.assertIn("bird_0=0", blob)                        # ...and the count says why

    def test_the_same_flight_over_a_bird_the_track_DID_drive_is_still_measured(self):
        """The control arm: nothing here weakens the gate. Driven to the same place, the breach is
        real evidence and is failed on."""
        driven = dict(self.OTHERS, bird_0=(15.0, 5.0, 11.0))
        status, messages = self._drive(driven, (15.0, 5.0, CRUISE_Z))
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("CPA BREACH: flew within 0.0000 m", blob)
        self.assertNotIn("NO landed set_pose call", blob)

    def test_a_bird_with_only_FAILED_calls_counts_as_unobserved(self):
        """A failed set_pose changed nothing in the render, so it is not an observation. Consistent
        with `applied_timeline`, which drops failed calls -- the two must not disagree."""
        recs = truth_records([(t, {"bird_0": (50.0, 58.0, CRUISE_Z)}) for t in TRUTH_SIM],
                             park_undriven=False)
        for r in recs:
            r["ok"] = False
        recs += truth_records([(t, dict(self.OTHERS)) for t in TRUTH_SIM], park_undriven=False)
        truth = self.write_truth(recs)
        self.assertInvalid(self.check(make_log(), truth=truth),
                           "NO landed set_pose call for ['bird_0']")

    def test_per_bird_landed_call_counts_are_printed_on_a_healthy_track(self):
        truth = self.write_truth(truth_records(straight_line("bird_0", [(50.0, 58.0)] * 4)))
        msg = self.assertValid(self.check(make_log(), truth=truth))
        self.assertIn("truth landed set_pose calls per bird: bird_0=4 bird_1=4 bird_2=4", msg)

    def test_spawn_answers_are_counted_with_a_denominator(self):
        """A spawn answer IS an observation while the track really is this flight's (the model is
        <static> until the first set_pose lands, ADR-012 am. 1) -- and it is also what the WRONG
        take's track produces for a whole flight. So it is reported separately from coverage rather
        than blended into it."""
        recs = truth_records([(TRUTH_SIM[2], {"bird_0": (0.0, 0.0, 15.0)}),
                              (TRUTH_SIM[3], {"bird_0": (0.0, 0.0, 15.0)})])
        truth = self.write_truth(recs)
        run = make_run(stamps=[101.9, 102.5, 102.9])     # tick 1 predates the first landed call
        msg = self.assertValid(self.check(make_log(run=run), truth=truth))
        self.assertIn("truth coverage 3/3 ticks", msg)
        self.assertIn("answered_from_spawn 1/3 ticks", msg)

    def test_a_fully_driven_flight_answers_from_spawn_zero_times(self):
        truth = self.write_truth(truth_records(straight_line("bird_0", [(50.0, 58.0)] * 4)))
        self.assertIn("answered_from_spawn 0/3 ticks",
                      self.assertValid(self.check(make_log(), truth=truth)))


# ================================================================================================
# 10. Detection-derived CPA: relabelled, reported, NEVER gated
# ================================================================================================
class TestDetectionCpaIsEstimatorErrorOnly(Harness):
    def _fly(self, bird_xy, detection_xy, **kw):
        recs = truth_records([(t, {"bird_0": (bird_xy[0], bird_xy[1], CRUISE_Z)})
                              for t in TRUTH_SIM])
        truth = self.write_truth(recs)
        events = [detection_event(1, (detection_xy[0], detection_xy[1], CRUISE_Z))]
        return self.check(make_log(events=events, **kw), truth=truth)

    def test_a_wildly_wrong_estimate_over_a_safe_truth_is_reported_not_failed(self):
        """The detector ranged the bird almost on top of the drone; the truth says 8 m. That is an
        ESTIMATOR error -- the measured argument ADR-009's second-sensor arm exists to make -- not
        a safety failure, and it must not fail the flight."""
        msg = self.assertValid(self._fly(bird_xy=(50.0, 58.0), detection_xy=(50.0, 50.01)))
        self.assertIn("gt_cpa_m 8.0000", msg)
        self.assertIn("detection_cpa_m 0.0100", msg)
        self.assertIn("ESTIMATOR CHECK, NOT A SAFETY GATE", msg)
        self.assertIn("range_estimate_error_at_cpa_m +7.9900", msg)

    def test_a_flattering_estimate_over_a_true_breach_still_fails(self):
        """The mirror image, and the reason the gate changed: the detector says 8 m of clearance,
        the truth says 5 cm. The estimate does not get to be the referee."""
        status, messages = self._fly(bird_xy=(50.0, 50.05), detection_xy=(50.0, 58.0))
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("CPA BREACH: flew within 0.0500", blob)
        self.assertIn("detection_cpa_m 8.0000", blob)
        self.assertIn("range_estimate_error_at_cpa_m -7.9500", blob)

    def test_no_detection_at_all_is_labelled_not_scored(self):
        recs = truth_records([(t, {"bird_0": (50.0, 58.0, CRUISE_Z)}) for t in TRUTH_SIM])
        truth = self.write_truth(recs)
        msg = self.assertValid(self.check(make_log(), truth=truth))
        self.assertIn("detection_cpa_m NONE", msg)
        self.assertIn("ESTIMATOR CHECK, NOT A SAFETY GATE", msg)

    def test_the_headline_regression_a_missed_bird_at_cpa(self):
        """THE case this whole schema exists for, A/B on ONE artifact.

        The detector misses the bird entirely at closest approach (0.05 m, no detection logged).
        Legacy gate: no detections -> NO-CPA-EVIDENCE -> VALID. Schema-2 gate: the truth track says
        5 cm -> INVALID. Same flown path, same (absent) detections, opposite verdicts.

        The legacy half is flown under a PINNED pre-seam stem, because that is now the only way onto
        that path at all -- an unpinned log dropping its run block is refused outright
        (`test_THE_PROBE_deleting_the_run_key_cannot_downgrade_a_failing_flight`)."""
        recs = truth_records([(t, {"bird_0": (50.0, 50.05, CRUISE_Z)}) for t in TRUTH_SIM])
        truth = self.write_truth(recs)
        log = make_log(events=[])

        legacy = dict(log)
        legacy.pop("run")
        self.assertIsNone(checker.closest_approach(legacy))            # the OLD metric: no evidence
        status, messages = self.check(legacy, name=PINNED_LOG)
        self.assertEqual(status, checker.VALID, " ".join(messages))    # ...and it scored GREEN
        self.assertIn("NO-CPA-EVIDENCE", messages[0])

        status, messages = self.check(log, truth=truth)                # same flight, schema-2
        self.assertEqual(status, checker.INVALID, " ".join(messages))
        self.assertIn("CPA BREACH: flew within 0.0500 m", " ".join(messages))


# ================================================================================================
# 11. Non-gating diagnostics that make the artifact readable
# ================================================================================================
class TestReportedDiagnostics(Harness):
    def test_the_missed_detection_signal_has_a_denominator(self):
        """A bird truly inside the threat cylinder on N ticks, the loop engaged on M of them.
        Reported, never gated: the camera is NADIR (ADR-007 am. 5 -- it looks straight down), so a
        bird inside the cylinder is routinely outside the downward footprint at its own altitude and
        one above the drone is never in frame at all. Gating this would measure geometry, not
        detection quality."""
        recs = truth_records([(t, {"bird_0": (50.0, 55.0, CRUISE_Z)}) for t in TRUTH_SIM])
        truth = self.write_truth(recs)
        log = make_log(events=[detection_event(1, (50.0, 55.0, CRUISE_Z))])
        msg = self.assertValid(self.check(log, truth=truth))
        self.assertIn("threat cylinder on 3 tick(s); the loop engaged on 1 of them", msg)

    def test_a_bird_outside_the_cylinder_does_not_inflate_the_denominator(self):
        recs = truth_records([(t, {"bird_0": (50.0, 90.0, CRUISE_Z)}) for t in TRUTH_SIM])
        truth = self.write_truth(recs)
        msg = self.assertValid(self.check(make_log(), truth=truth))
        self.assertIn("threat cylinder on 0 tick(s)", msg)

    def test_stale_drops_are_reported_because_expired_and_unseen_are_opposite_diagnoses(self):
        log = make_log(events=[maneuver_event(1, debug={"n_stale_dropped": 4}),
                               maneuver_event(2, debug={"n_stale_dropped": 3})],
                       run=make_run(checker.DET_DEMO_VIRTUAL))
        self.assertIn("n_stale_dropped=7", self.assertValid(self.check(log)))

    def test_zero_stale_drops_is_stated_rather_than_left_to_inference(self):
        self.assertIn("n_stale_dropped=0",
                      self.assertValid(self.check(make_log(run=make_run(checker.DET_NONE)))))

    def test_R2_and_R3_say_PASS_VACUOUS_when_there_was_nothing_to_check(self):
        """The newest failure family: a gate that passed because it measured nothing. R2/R3
        constrain ACCEPTED DODGES, so a flight with none has not exercised them -- and the
        pre-registered expectation for the next take is that it may produce exactly zero."""
        msg = self.assertValid(self.check(make_log(run=make_run(checker.DET_NONE))))
        self.assertIn("R2/R3 PASS (vacuous): 0 accepted dodges to check", msg)

    def test_and_it_stops_saying_so_the_moment_one_dodge_exists(self):
        log = make_log(events=[maneuver_event(1, clearance=5.0)],
                       run=make_run(checker.DET_DEMO_VIRTUAL))
        self.assertNotIn("vacuous", self.assertValid(self.check(log)))


# ================================================================================================
# 12. Acknowledgement markers under schema 2 -- a marker covers a FINDING, never a broken gate
# ================================================================================================
class TestMarkerSemantics(Harness):
    """ACKNOWLEDGED takes BOTH halves: the marker file beside the evidence AND the log stem pinned
    in the checker's own `ACKNOWLEDGED_BREACH_STEMS`. Before 2026-08-24 the marker alone did it,
    which made the runbook's documented remedy for a breach ("keep the log, add the marker") the
    one-file way to turn the NEXT bird strike green -- with R4 open and the next take pre-registered
    as possibly breaching."""

    def _breach_log(self):
        recs = truth_records([(t, {"bird_0": (50.0, 50.05, CRUISE_Z)}) for t in TRUTH_SIM])
        return make_log(), self.write_truth(recs)

    def test_BOTH_halves_turn_a_schema_2_breach_into_ACKNOWLEDGED_never_VALID(self):
        log, truth = self._breach_log()
        self.write_log(log, PINNED_LOG)
        self.mark(PINNED_LOG)
        status, messages = self.check(log, truth=truth, name=PINNED_LOG)
        self.assertEqual(status, checker.ACKNOWLEDGED, " ".join(messages))
        self.assertNotEqual(status, checker.VALID)
        self.assertIn("NOT a passing flight", " ".join(messages))
        self.assertIn("0.0500", " ".join(messages))       # the number is still printed, loudly

    def test_a_MARKER_ALONE_on_a_NEW_breach_is_INVALID_and_exits_nonzero(self):
        """THE regression this round exists for: a new take, a real strike, and a marker file
        dropped beside it in a gitignored directory. Unpinned stem -> half an acknowledgement ->
        INVALID, and main() exits 1."""
        log, truth = self._breach_log()
        p = self.write_log(log, NEW_TAKE_LOG)
        self.mark(NEW_TAKE_LOG)
        status, messages = self.check(log, truth=truth, name=NEW_TAKE_LOG)
        self.assertEqual(status, checker.INVALID, " ".join(messages))
        self.assertIn("NOT pinned in ACKNOWLEDGED_BREACH_STEMS", " ".join(messages))
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(checker.main([str(p), "--truth", str(truth)]), 1)

    def test_a_PIN_ALONE_with_no_marker_file_is_INVALID(self):
        """The context half is mandatory too: a pinned stem with no written finding beside the
        evidence is a verdict with no reason attached."""
        log, truth = self._breach_log()
        status, messages = self.check(log, truth=truth, name=PINNED_LOG)
        self.assertEqual(status, checker.INVALID, " ".join(messages))
        self.assertIn("is MISSING", " ".join(messages))
        self.assertIn(checker.MARKER_SUFFIX, " ".join(messages))

    def test_a_full_acknowledgement_does_NOT_acknowledge_a_failed_gate(self):
        """An acknowledgement records a separation finding on a flight that happened. It is not a
        waiver for a broken clock or an R2 breach -- even with both halves present."""
        log, truth = self._breach_log()
        log["events"] = [maneuver_event(1, clearance=0.2)]
        self.write_log(log, PINNED_LOG)
        self.mark(PINNED_LOG)
        status, messages = self.check(log, truth=truth, name=PINNED_LOG)
        self.assertEqual(status, checker.INVALID, " ".join(messages))
        self.assertIn("R2 BREACH", " ".join(messages))
        self.assertIn("NOT acknowledgeable", " ".join(messages))

    def test_a_marker_beside_a_passing_schema_2_log_is_a_stale_acknowledgement(self):
        recs = truth_records([(t, {"bird_0": (50.0, 58.0, CRUISE_Z)}) for t in TRUTH_SIM])
        truth = self.write_truth(recs)
        log = make_log()
        self.write_log(log)
        self.mark()
        self.assertInvalid(self.check(log, truth=truth), "stale acknowledgement marker")

    def test_an_unacknowledged_schema_2_breach_tells_the_operator_exactly_what_to_do(self):
        log, truth = self._breach_log()
        result = self.check(log, truth=truth)
        self.assertInvalid(result, "no acknowledgement")
        self.assertInvalid(result, "ACKNOWLEDGED_BREACH_STEMS")


# ================================================================================================
# 13. CLI: exit codes, --truth plumbing, and every measured number reaching the operator
# ================================================================================================
class TestCli(Harness):
    def test_exit_codes_and_the_truth_flag_end_to_end(self):
        recs = truth_records([(t, {"bird_0": (50.0, 50.05, CRUISE_Z)}) for t in TRUTH_SIM])
        truth = self.write_truth(recs)
        p = self.write_log(make_log(), PINNED_LOG)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(checker.main([str(p), "--truth", str(truth)]), 1)   # pin, no marker
            self.mark(PINNED_LOG)
            self.assertEqual(checker.main([str(p), "--truth", str(truth)]), 0)   # acknowledged

    def test_a_valid_schema_2_log_prints_every_measured_number_not_just_the_headline(self):
        recs = truth_records([(t, {"bird_0": (50.0, 58.0, CRUISE_Z)}) for t in TRUTH_SIM])
        truth = self.write_truth(recs)
        p = self.write_log(make_log())
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            self.assertEqual(checker.main([str(p), "--truth", str(truth)]), 0)
        printed = out.getvalue()
        for needle in ("gt_cpa_m 8.0000", "truth coverage 3/3", "clock gz_clock_stream",
                       "n_stale_dropped=0", "ESTIMATOR CHECK"):
            self.assertIn(needle, printed)

    def test_a_missing_truth_track_exits_nonzero_and_says_so_on_stderr(self):
        p = self.write_log(make_log())
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            self.assertEqual(checker.main([str(p)]), 1)
        self.assertIn("no truth track", err.getvalue())

    def test_the_gate_stays_stdlib_only(self):
        """It runs in a CI step that only needs `src/` importable, and the whole truth path
        (drive_birds -> annotate_real_clip) is stdlib. numpy/scipy must not leak in."""
        source = (REPO_ROOT / "scripts" / "check_live_flight_log.py").read_text()
        for banned in ("import numpy", "import scipy", "from numpy", "from scipy"):
            self.assertNotIn(banned, source)


# ================================================================================================
# 14. The committed real artifact -- the truth reader works on the log a flight actually produced
# ================================================================================================
class TestRealTruthArtifact(unittest.TestCase):
    PATH = checker.RESULTS_DIR / "bird_drive_20260823T073836Z_applied.jsonl"

    def setUp(self):
        if not self.PATH.exists():
            self.skipTest(f"{self.PATH.name} absent (eval/results is gitignored in some checkouts)")
        self.truth = checker.TruthTrack.load(self.PATH)

    def test_it_loads_covers_the_documented_window_and_names_only_known_birds(self):
        self.assertEqual(len(self.truth.records), 860)
        self.assertEqual(self.truth.unknown_bird_ids, [])
        lo, hi = self.truth.span
        self.assertAlmostEqual(lo, 110.408, places=2)
        self.assertAlmostEqual(hi, 263.842, places=2)

    def test_the_real_take_observed_every_bird_the_world_defines(self):
        """Both directions of the set difference on a real artifact: nothing driven that the world
        does not define, and nothing defined that the track never drove."""
        self.assertEqual(self.truth.unobserved_bird_ids, [])
        self.assertEqual(sorted(self.truth.landed_counts), ["bird_0", "bird_1", "bird_2"])
        for bird_id, n in self.truth.landed_counts.items():
            self.assertGreater(n, 100, bird_id)

    def test_it_answers_inside_the_window_and_refuses_after_it(self):
        mid = self.truth.candidates_at((self.truth.span[0] + self.truth.span[1]) / 2.0)
        self.assertEqual(sorted(mid), ["bird_0", "bird_1", "bird_2"])
        self.assertTrue(all(len(v.positions) >= 1 for v in mid.values()))
        self.assertFalse(any(v.from_spawn for v in mid.values()))   # mid-window: all driven
        self.assertIsNone(self.truth.candidates_at(self.truth.span[1] + 0.001))
        self.assertIsNone(self.truth.candidates_at(None))

    def test_before_the_first_landed_call_every_bird_is_at_its_config_spawn_pose(self):
        early = self.truth.candidates_at(self.truth.span[0] - 50.0)
        self.assertEqual(early["bird_0"].positions, [(15.0, 5.0, 11.0)])
        self.assertEqual(early["bird_1"].positions, [(5.0, 30.0, 8.0)])
        self.assertEqual(early["bird_2"].positions, [(10.0, 10.0, 6.0)])
        # ...and says so, so "observed at spawn" never blends into "observed".
        self.assertTrue(all(v.from_spawn for v in early.values()))

    def test_it_is_discoverable_by_sim_time_overlap_from_the_real_results_dir(self):
        lo, hi = self.truth.span
        found = checker.truth_candidates((lo + 1.0, hi - 1.0))
        self.assertIn(self.PATH, found)


# ================================================================================================
# 15. END TO END -- the gate reads what the NODE writes, on a log nothing here hand-typed
# ================================================================================================
class TestNodeContract(Harness):
    """Every fixture above is a hand-written flight log, which pins the GATE but not the JOIN. This
    class flies the real `AvoidanceLoop` over the real policy/executor/geofence and scores the log
    it actually produces. If the node ever renames a field the gate reads, this goes red before a
    flight is booked -- which is the whole point of building the gate before the take."""

    def _flight(self, bird_enu=(34.0, 30.0, 15.0), drone_enu=(30.0, 30.0, 15.0), n_ticks=4,
                t0=1200.0, detector_source=None):
        from fieldguard_planning.avoidance_executor import (AvoidanceExecutor,
                                                            SimulatedVehicleSink)
        from fieldguard_planning.avoidance_node import (AvoidanceLoop, build_run_block,
                                                        detector_log_block)
        from fieldguard_planning.avoidance_policy import AvoidancePolicy
        from fieldguard_planning.avoidance_types import Detection, DroneState
        from fieldguard_planning.geofence import GeofenceMap

        polygon = load_field_polygon()
        geofence = GeofenceMap.from_file()
        policy = AvoidancePolicy(field_polygon=polygon, cruise_alt_m=15.0)
        executor = AvoidanceExecutor(geofence, build_grid(polygon), SimulatedVehicleSink(),
                                     swath_half_width_m=7.5, alt_bounds=(2.0, 30.0))
        state = {"i": 0}

        def source(t, drone):
            # The bird is present for `n_ticks`, then GONE -- so this fixture flies a COMPLETE
            # encounter (takeover ... resume) rather than ending mid-dodge. A log that stops while
            # still in GUIDED is a truncated survey and `gate_encounter_closure` now says so
            # (QA C1); it was passing here only because nothing paired takeovers with resumes.
            i = state["i"]
            state["i"] += 1
            if i >= n_ticks:
                return []
            return [Detection(bird_enu, frame_id=i, track_id="b0", source="ndvi_blob",
                              stamp_s=t0 + i * 0.2)]

        loop = AvoidanceLoop(policy, geofence, executor, source)
        drone = DroneState(position_enu=drone_enu, heading_rad=0.0, current_wp_index=3)
        for i in range(n_ticks + RESUME_CLEAR_TICKS):     # + the clear ticks that end the encounter
            loop.tick(drone, now_s=t0 + i * 0.2, source_t=t0 + i * 0.2)
        executor.finalize()
        log = executor.flight_log("integration", 0, 2.5)
        log["run"] = build_run_block(
            policy_params=_params_dict(policy.params),
            clock=loop.clock_block(readings=n_ticks + RESUME_CLEAR_TICKS),
            tick_stamp_sim_s=loop.tick_stamp_sim_s,
            detector=(detector_log_block(source, None) if detector_source is None
                      else detector_source))
        return log

    def test_the_constants_the_two_files_share_actually_agree(self):
        from fieldguard_planning import avoidance_node as node
        self.assertEqual(node.RUN_SCHEMA_VERSION, checker.GATED_SCHEMA_VERSION)
        self.assertEqual(node.DEMO_SOURCE_TAG, checker.DET_DEMO_VIRTUAL)
        self.assertEqual(node.detector_log_block(None, None)["source"], checker.DET_NONE)
        self.assertEqual(node.AvoidanceLoop.clock_block(
            _FakeLoop(), readings=1)["source"], checker.CLOCK_SOURCE)

    def test_a_flight_that_never_read_the_gazebo_clock_is_rejected_by_its_own_fallback_label(self):
        """The node labels a clockless run `node_elapsed_fallback` rather than lying about the
        source. The gate must refuse exactly that string -- a flight with no sim-time axis has no
        comparable detection ages and no ground-truth CPA."""
        from fieldguard_planning import avoidance_node as node
        fallback = node.AvoidanceLoop.clock_block(_FakeLoop(), readings=0)
        self.assertNotEqual(fallback["source"], checker.CLOCK_SOURCE)
        run = make_run(checker.DET_NONE)
        run["clock"] = fallback
        run["tick_stamp_sim_s"] = list(TICK_SIM)
        self.assertInvalid(self.check(make_log(run=run)), "run.clock.source is")

    def test_a_real_node_flight_is_scored_not_merely_parsed(self):
        """A real DIVERT encounter: real maneuver debug, real params, real tick stamps."""
        log = self._flight()
        status, messages = self.check(log)
        blob = " ".join(messages)
        self.assertEqual(status, checker.VALID, blob)
        self.assertIn("CPA 4.0000 m", blob)            # demo_virtual -> detection-referenced
        self.assertIn("clock gz_clock_stream, 0 domain violations", blob)
        self.assertGreaterEqual(int(blob.split("maneuvers=")[1].split()[0]), 1)

    def test_the_real_R2_field_the_policy_writes_is_the_one_the_gate_reads(self):
        """Field-name drift is silent otherwise: a renamed debug key would make the gate stop
        checking and start passing everything."""
        log = self._flight()
        maneuvers = [e for e in log["events"] if e["kind"] == "maneuver"]
        self.assertTrue(maneuvers)
        for ev in maneuvers:
            self.assertIn("swept_tree_clearance_m", ev["debug"])
            self.assertIn("trigger_range_m", ev["debug"])
            self.assertIn("range_degenerate", ev["debug"])
        # Corrupt exactly the field the gate claims to read; the gate must notice.
        maneuvers[0]["debug"]["swept_tree_clearance_m"] = 0.1
        self.assertInvalid(self.check(log), "R2 BREACH")

    def test_the_threat_positions_the_policy_writes_are_the_ones_R3_7_reads(self):
        """The R3.7 join is `event.setpoint_enu` against `debug.threat_positions_enu`, and both
        sides are written by code in another file. A rename on either side would make this gate
        stop checking and start passing everything -- so it is asserted on a real node flight and
        then mutation-proved by moving a bird onto the point that was actually commanded."""
        log = self._flight()
        maneuvers = [e for e in log["events"] if e["kind"] == "maneuver"]
        self.assertTrue(maneuvers)
        for ev in maneuvers:
            self.assertIn("setpoint_enu", ev)
            self.assertEqual(len(ev["debug"]["threat_positions_enu"]),
                             len(ev["debug"]["threat_ids"]))
            gap = checker._min_setpoint_bird_gap_m(ev["setpoint_enu"],
                                                   ev["debug"]["threat_positions_enu"])
            self.assertGreaterEqual(gap[0], PolicyParams().min_bird_clearance_m)
        maneuvers[0]["debug"]["threat_positions_enu"] = [list(maneuvers[0]["setpoint_enu"])]
        self.assertInvalid(self.check(log), "R3.7 BREACH")

    def test_a_real_flight_relabelled_as_the_real_detector_needs_a_truth_track(self):
        """Same artifact, `detector.source` = ndvi_blob (what the node writes when `--detect` is
        armed). The demo path passed on its own detections; the real path may not."""
        log = self._flight(detector_source={"source": checker.DET_NDVI_BLOB,
                                            "module": "fieldguard_planning.ndvi_detect",
                                            "counters": detector_counters()})
        self.assertInvalid(self.check(log), "no truth track")

    def test_and_with_a_truth_track_the_real_artifact_scores_against_the_bird(self):
        log = self._flight(detector_source={"source": checker.DET_NDVI_BLOB,
                                            "module": "fieldguard_planning.ndvi_detect",
                                            "counters": detector_counters()})
        stamps = log["run"]["tick_stamp_sim_s"]
        anchors = [stamps[0] - 1.0, stamps[0], stamps[-1] + 1.0]
        # The detector said the bird was at (34, 30); the TRUTH says it was 2 m from the drone.
        truth = self.write_truth(truth_records(
            [(a, {"bird_0": (32.0, 30.0, 15.0)}) for a in anchors]))
        status, messages = self.check(log, truth=truth)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("gt_cpa_m 2.0000 m to bird_0", blob)
        self.assertIn("detection_cpa_m 4.0000", blob)          # what the detector believed
        self.assertIn("range_estimate_error_at_cpa_m -2.0000", blob)
        self.assertIn("CPA BREACH", blob)


class _FakeLoop:
    """Minimum state `AvoidanceLoop.clock_block` reads -- it is a pure formatter over these."""
    clock_domain_violations = 0
    clock_domain_bound_s = 0.5
    ticks_without_clock = 0
    tick_stamp_sim_s = ()


# ------------------------------------------------------------------------------------ utilities
class patched_params:
    """Swap the POLICY the gate reads its bars from, for one block. Every bar in the checker is
    `PolicyParams()` evaluated per call, so this is enough to prove the wiring -- and a test that
    edits the checker instead would prove nothing about drift."""

    def __init__(self, **overrides):
        self.overrides = overrides

    def __enter__(self):
        self.real = checker.PolicyParams
        real = self.real
        over = self.overrides
        checker.PolicyParams = lambda: real(**over)
        return self

    def __exit__(self, *exc):
        checker.PolicyParams = self.real
        return False


class TestEncounterClosureGate(Harness):
    """`gate_encounter_closure` -- the live half of QA C1 (2026-08-25).

    The executor's threat-clear hysteresis resets on every threat tick, so a detection duty cycle
    denser than 1-in-`resume_clear_ticks` never reaches the count: 90 ticks of
    `DIVERT, PROCEED, PROCEED` on the real executor gave 1 takeover and **0 resumes**, the mission
    never came back, and no gate could see it -- `ENCOUNTER_KINDS` does not even contain `resume`,
    and nothing paired takeovers with resumes."""

    def _log(self, *events, executor_params=None, **over):
        # demo_virtual: the one source whose logged bird IS truth, so a fixture can carry
        # takeover/resume events without also needing a bird track beside it.
        log = make_log(events=[dict(e) for e in events],
                       run=make_run(detector_source=checker.DET_DEMO_VIRTUAL), **over)
        if executor_params is not None:
            log["executor_params"] = executor_params
        return log

    TAKEOVER = {"seq": 0, "tick": 1, "kind": "takeover", "reason": "divert"}
    RESUME = {"seq": 1, "tick": 2, "kind": "resume", "trigger": "threat_cleared"}
    CEILING = {"seq": 1, "tick": 306, "kind": "resume", "trigger": "guided_ceiling",
               "ticks_in_guided": 305, "ceiling_ticks": 305}

    def test_a_flight_that_never_came_back_out_of_guided_is_invalid(self):
        self.assertInvalid(self.check(self._log(self.TAKEOVER)), "UNCLOSED ENCOUNTER")

    def test_the_failure_names_the_tick_and_the_known_cause(self):
        _status, messages = self.check(self._log(self.TAKEOVER))
        blob = " ".join(messages)
        self.assertIn("1 takeover(s) but 0 resume(s)", blob)
        self.assertIn("last takeover tick 1", blob)
        self.assertIn("duty cycle", blob)

    def test_a_matched_pair_says_nothing_at_all(self):
        """Silence is the property: every committed log has matched pairs, and this gate must not
        change one byte of what they print."""
        messages = self.assertValid(self.check(self._log(self.TAKEOVER, self.RESUME)))
        self.assertNotIn("UNCLOSED", messages)
        self.assertNotIn("hysteresis budget", messages)

    def test_two_encounters_one_resume_is_still_unclosed(self):
        second = dict(self.TAKEOVER, seq=2, tick=3)
        self.assertInvalid(self.check(self._log(self.TAKEOVER, self.RESUME, second)),
                           "2 takeover(s) but 1 resume(s)")

    def test_a_ceiling_resume_is_reported_loudly_but_the_flight_still_scores(self):
        messages = self.assertValid(self.check(self._log(self.TAKEOVER, self.CEILING)))
        self.assertIn("GUIDED-CEILING BACKSTOP FIRED at tick 306", messages)
        self.assertIn("305 ticks in GUIDED", messages)
        self.assertIn("NOT by a cleared threat", messages)

    def test_the_hysteresis_budget_is_priced_on_the_flights_own_measured_tick(self):
        """M3: 3 ticks is 0.48 s at the FLOWN 0.160 s median, not the 0.6 s a nominal 5 Hz implies.
        The fixture's stamps step 1.0 s, so 3 ticks reads 3.0 s -- well past the 1.0 s bound."""
        log = self._log(executor_params={"resume_clear_ticks": 3, "guided_ceiling_ticks": 305})
        self.assertInvalid(self.check(log), "hysteresis budget 3.000 s")
        _s, messages = self.check(log)
        self.assertIn("already declared ABSENT", " ".join(messages))

    def test_a_budget_inside_the_staleness_bound_is_reported_as_context(self):
        log = self._log(executor_params={"resume_clear_ticks": 1, "guided_ceiling_ticks": 305})
        # 1 tick x the fixture's 1.0 s mean step = 1.0 s, exactly the max_detection_age_s bound.
        self.assertIn("hysteresis budget 1.000 s", self.assertValid(self.check(log)))

    def test_a_log_that_records_no_executor_params_is_not_scored_on_them(self):
        """Pre-2026-08-25 logs (every committed one) carry no `executor_params`. Absence must be
        silent here, not an invented pass and not a failure."""
        self.assertNotIn("hysteresis budget", self.assertValid(self.check(self._log())))


if __name__ == "__main__":
    unittest.main()
