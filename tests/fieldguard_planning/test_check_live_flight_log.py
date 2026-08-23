"""Tests for scripts/check_live_flight_log.py -- the flight-log evidence gate.

Pins the exact failure that motivated the checker (see its module docstring): the 2026-08-05 live
demo's eval/results/live_flight_log.json was silently clobbered by an idle run -- empty
flown_path_enu, all 720 cells "debt" -- and nothing noticed. That clobbered shape MUST come back
INVALID, a genuine covered run MUST be VALID, explicit partial debt MUST stay allowed (the ADR-002
v1 bar: honest debt is not a failure), and partition-invariant breakage (the silent-skip bug
check_ledger exists to catch) must surface through the checker too.

stdlib unittest only. Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))   # the checker lives in scripts/, not src/

import check_live_flight_log as checker  # noqa: E402
from fieldguard_planning.coverage import (  # noqa: E402
    CELL_COVERED, CELL_DEBT, build_grid, load_field_polygon,
)

# The canonical grid at the default 2.5 m cell size (720 cells over the 75x60 field) -- the same
# grid the checker rebuilds from the log's own cell_size_m.
GRID = build_grid(load_field_polygon())


def make_log(flown_path=None, ledger=None):
    """A structurally complete flight log (AvoidanceExecutor.flight_log shape). Defaults model a
    genuine covered run: nonempty flown path, every cell terminally covered."""
    return {
        "scenario": "test_run",
        "seed": 0,
        "cell_size_m": 2.5,
        "swath_half_width_m": 7.5,
        "flown_path_enu": [[0.0, 0.0, 15.0], [75.0, 0.0, 15.0]] if flown_path is None else flown_path,
        "coverage_ledger": ([{"cell_id": c.cell_id, "status": CELL_COVERED} for c in GRID]
                            if ledger is None else ledger),
        "requeue_events": [],
        "events": [],
    }


class TestValidateFlightLog(unittest.TestCase):
    def test_genuine_covered_run_is_valid(self):
        self.assertEqual(checker.validate_flight_log(make_log()), [])

    def test_explicit_partial_debt_is_still_valid(self):
        # ADR-002 v1 bar: explicit debt is honest accounting, not a failure -- only ALL-debt is.
        ledger = [{"cell_id": c.cell_id,
                   "status": CELL_DEBT if c.cell_id == "cell_0_0" else CELL_COVERED}
                  for c in GRID]
        self.assertEqual(checker.validate_flight_log(make_log(ledger=ledger)), [])

    def test_clobbered_idle_run_shape_is_invalid(self):
        # THE regression: the exact shape that overwrote the 2026-08-05 live-demo evidence.
        idle = make_log(flown_path=[],
                        ledger=[{"cell_id": c.cell_id, "status": CELL_DEBT} for c in GRID])
        problems = checker.validate_flight_log(idle)
        self.assertTrue(any("EMPTY" in p for p in problems), problems)          # empty flown path
        self.assertTrue(any("ALL" in p and "debt" in p for p in problems), problems)  # 720/720 debt

    def test_all_debt_alone_is_invalid_even_with_a_flown_path(self):
        log = make_log(ledger=[{"cell_id": c.cell_id, "status": CELL_DEBT} for c in GRID])
        problems = checker.validate_flight_log(log)
        self.assertTrue(any("ALL" in p for p in problems), problems)

    def test_silently_skipped_cell_fails_partition_invariant(self):
        # Drop one grid cell from the ledger entirely -- the P1 silent-skip failure.
        ledger = [{"cell_id": c.cell_id, "status": CELL_COVERED} for c in GRID][:-1]
        problems = checker.validate_flight_log(make_log(ledger=ledger))
        self.assertTrue(any("SILENTLY SKIPPED" in p for p in problems), problems)

    def test_missing_contract_keys_are_invalid(self):
        problems = checker.validate_flight_log({"scenario": "test_run"})
        self.assertTrue(any("flown_path_enu" in p for p in problems), problems)
        self.assertTrue(any("coverage_ledger" in p for p in problems), problems)

    def test_non_dict_log_is_invalid(self):
        self.assertTrue(checker.validate_flight_log(["not", "a", "dict"]))


class TestCheckFileAndExitCodes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def _write(self, name, text):
        p = self.dir / name
        p.write_text(text)
        return p

    def test_absent_file_skips(self):
        status, _ = checker.check_file(self.dir / "no_such_flight_log.json")
        self.assertEqual(status, checker.SKIP)

    def test_unparseable_json_is_invalid(self):
        p = self._write("bad_flight_log.json", "{not json")
        status, _ = checker.check_file(p)
        self.assertEqual(status, checker.INVALID)

    def test_valid_file_reports_headline_numbers(self):
        p = self._write("good_flight_log.json", json.dumps(make_log()))
        status, messages = checker.check_file(p)
        self.assertEqual(status, checker.VALID)
        self.assertIn("covered=720", messages[0])

    def test_main_exit_codes(self):
        good = self._write("good_flight_log.json", json.dumps(make_log()))
        bad = self._write("idle_flight_log.json", json.dumps(make_log(flown_path=[])))
        absent = self.dir / "absent_flight_log.json"
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(checker.main([str(good)]), 0)
            self.assertEqual(checker.main([str(absent)]), 0)   # skip-with-exit-0, per contract
            self.assertEqual(checker.main([str(good), str(bad)]), 1)


# --------------------------------------------------------------------------------------------------
# Closest point of approach (ADR-013 amendment 12, R1)
# --------------------------------------------------------------------------------------------------
BIRD = (30.0, 30.0, 15.0)


def detection_event(pos=BIRD, track_id="demo_bird_0", kind="detection"):
    return {"kind": kind, "track_id": track_id, "position_enu": list(pos)}


def make_cpa_log(closest_m, **kw):
    """A structurally valid log whose flown path passes exactly `closest_m` from one detection."""
    path = [[BIRD[0] - 20.0, BIRD[1] + closest_m, 15.0],
            [BIRD[0], BIRD[1] + closest_m, 15.0],
            [BIRD[0] + 20.0, BIRD[1] + closest_m, 15.0]]
    log = make_log(flown_path=path, **kw)
    log["events"] = [detection_event()]
    return log


class TestClosestApproach(unittest.TestCase):
    """The metric whose ABSENCE let two flights pass every gate at ~6 cm from the threat."""

    def test_cpa_is_the_minimum_over_path_and_detections(self):
        cpa, track = checker.closest_approach(make_cpa_log(4.0))
        self.assertAlmostEqual(cpa, 4.0, places=6)
        self.assertEqual(track, "demo_bird_0")

    def test_cpa_is_horizontal_so_an_untrusted_bird_altitude_cannot_manufacture_clearance(self):
        """ADR-009: a bird's z is the estimate we cannot trust. Folding it in would let a bad
        altitude report separation the vehicle did not have."""
        log = make_cpa_log(2.0)
        log["flown_path_enu"] = [[BIRD[0], BIRD[1] + 2.0, 500.0]]   # 485 m above the bird
        cpa, _ = checker.closest_approach(log)
        self.assertAlmostEqual(cpa, 2.0, places=6)

    def test_no_detections_is_no_evidence_not_zero_and_not_infinity(self):
        log = make_log()
        log["events"] = []
        self.assertIsNone(checker.closest_approach(log))

    def test_no_path_is_no_evidence(self):
        log = make_cpa_log(4.0)
        log["flown_path_enu"] = []
        self.assertIsNone(checker.closest_approach(log))

    def test_malformed_events_do_not_crash_the_gate(self):
        """A truncated event must fail to provide evidence, never take the checker down."""
        log = make_cpa_log(4.0)
        log["events"] = [{"kind": "detection"}, {"kind": "detection", "position_enu": "nope"},
                         {"kind": "proceed", "position_enu": [0, 0]}, detection_event()]
        cpa, _ = checker.closest_approach(log)
        self.assertAlmostEqual(cpa, 4.0, places=6)

    def test_the_nearest_of_several_detections_wins_and_is_named(self):
        log = make_cpa_log(9.0)
        log["events"].append(detection_event(pos=(10.0, 39.0, 15.0), track_id="bird_close"))
        cpa, track = checker.closest_approach(log)
        self.assertAlmostEqual(cpa, 0.0, places=6)      # the path passes through (10, 39)
        self.assertEqual(track, "bird_close")

    def test_reproduces_the_flown_encounters_cpa(self):
        """Both real logs, from the committed evidence set -- the numbers ADR-013 am. 12 cites."""
        for name, want in (("live_flight_log_20260823T004031Z.json", 0.0518),
                           ("live_flight_log_20260818T144711Z.json", 0.0597)):
            p = checker.RESULTS_DIR / name
            if not p.exists():
                continue                                 # evidence is gitignored in some checkouts
            with self.subTest(log=name):
                cpa, _ = checker.closest_approach(json.loads(p.read_text()))
                self.assertAlmostEqual(cpa, want, places=4)


class TestCpaVerdicts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def _write_log(self, log, name="cpa_flight_log.json"):
        p = self.dir / name
        p.write_text(json.dumps(log))
        return p

    def _mark(self, log_path):
        m = checker.marker_path_for(log_path)
        m.write_text("# acknowledged for test")
        return m

    def test_clean_cpa_passes_and_prints_the_number(self):
        p = self._write_log(make_cpa_log(5.0))
        status, messages = checker.check_file(p)
        self.assertEqual(status, checker.VALID)
        self.assertIn("CPA 5.0000 m", messages[0])
        self.assertIn("covered=720", messages[0])        # ledger headline unchanged, additive

    def test_breach_without_a_marker_is_invalid(self):
        p = self._write_log(make_cpa_log(0.05))
        status, messages = checker.check_file(p)
        self.assertEqual(status, checker.INVALID)
        self.assertIn("FLEW CLOSER THAN THE POLICY WILL COMMAND", messages[0])
        self.assertIn("no acknowledgement marker present", messages[1])

    def test_breach_with_a_marker_is_acknowledged_and_never_reads_as_valid(self):
        p = self._write_log(make_cpa_log(0.05))
        self._mark(p)
        status, messages = checker.check_file(p)
        self.assertEqual(status, checker.ACKNOWLEDGED)
        self.assertNotEqual(status, checker.VALID)
        self.assertIn("NOT a passing flight", " ".join(messages))
        self.assertIn("CPA 0.0500 m", messages[0])       # the number is still printed, loudly

    def test_a_marker_beside_a_passing_log_is_a_stale_acknowledgement_and_fails(self):
        """An acknowledgement for a log that does NOT breach pre-authorises the next regression on
        that file -- so it is a defect in its own right, not a harmless leftover."""
        p = self._write_log(make_cpa_log(5.0))
        self._mark(p)
        status, messages = checker.check_file(p)
        self.assertEqual(status, checker.INVALID)
        self.assertIn("stale acknowledgement marker", " ".join(messages))

    def test_no_detections_reports_no_cpa_evidence_and_does_not_pass_silently(self):
        log = make_log()
        log["events"] = []
        p = self._write_log(log)
        status, messages = checker.check_file(p)
        self.assertEqual(status, checker.VALID)          # the LEDGER is still valid
        self.assertIn("NO-CPA-EVIDENCE", messages[0])    # ...but separation is explicitly unclaimed
        self.assertNotIn("CPA 0", messages[0])

    def test_exit_codes_acknowledged_is_zero_unmarked_breach_is_one(self):
        breach = self._write_log(make_cpa_log(0.05), "breach_flight_log.json")
        clean = self._write_log(make_cpa_log(5.0), "clean_flight_log.json")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(checker.main([str(breach)]), 1)
            self._mark(breach)
            self.assertEqual(checker.main([str(breach)]), 0)
            self.assertEqual(checker.main([str(breach), str(clean)]), 0)

    def test_acknowledged_output_goes_to_stderr_with_its_own_word(self):
        p = self._write_log(make_cpa_log(0.05))
        self._mark(p)
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            checker.main([str(p)])
        self.assertIn("ACKNOWLEDGED SAFETY FINDING", err.getvalue())
        self.assertNotIn("VALID", out.getvalue())
        self.assertNotIn("PASS: all present flight logs valid", out.getvalue())

    def test_ledger_failure_still_wins_over_cpa(self):
        """Additive, not reordering: a corrupt ledger is INVALID whatever the CPA says."""
        log = make_cpa_log(5.0)
        log["flown_path_enu"] = []          # idle-run shape, with detections still logged
        p = self._write_log(log)
        status, messages = checker.check_file(p)
        self.assertEqual(status, checker.INVALID)
        self.assertTrue(any("flown_path_enu is EMPTY" in m for m in messages))


class TestMinBirdClearanceSourceOfTruth(unittest.TestCase):
    """The bar must come from the POLICY, not a second literal in the gate -- otherwise the gate
    goes on passing flights the control law would refuse to command."""

    def test_the_bar_matches_the_policy_dataclass(self):
        from fieldguard_planning.avoidance_policy import PolicyParams
        self.assertEqual(checker.min_bird_clearance_m(), PolicyParams().min_bird_clearance_m)

    def test_mutating_the_policy_moves_the_verdict(self):
        """Mutation proof of the wiring: a log at 5 m is clean at the real 3 m bar and a breach at a
        10 m bar, with no edit to the checker."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = Path(tmp.name) / "mut_flight_log.json"
        p.write_text(json.dumps(make_cpa_log(5.0)))
        self.assertEqual(checker.check_file(p)[0], checker.VALID)

        class WiderBar:
            min_bird_clearance_m = 10.0

        real = checker.PolicyParams
        checker.PolicyParams = WiderBar
        try:
            self.assertEqual(checker.check_file(p)[0], checker.INVALID)
        finally:
            checker.PolicyParams = real
        self.assertEqual(checker.check_file(p)[0], checker.VALID)   # restored


class TestAcknowledgementMarkersOnRealEvidence(unittest.TestCase):
    """The committed evidence set must not fail CI, and must not be green either."""

    def test_every_breaching_committed_log_has_a_marker(self):
        for p in sorted(checker.RESULTS_DIR.glob("*flight_log*.json")):
            log = json.loads(p.read_text())
            cpa = checker.closest_approach(log)
            if cpa is None or cpa[0] >= checker.min_bird_clearance_m():
                continue
            with self.subTest(log=p.name):
                self.assertTrue(checker.marker_path_for(p).exists(),
                                f"{p.name} breaches CPA at {cpa[0]:.4f} m with no "
                                f"{checker.MARKER_SUFFIX} marker -- CI will fail hard")

    def test_markers_are_git_allowlisted_so_ci_sees_them(self):
        """eval/results/* is gitignored; the LOGS are re-included. If the markers are not, CI
        checks out breaching logs without their acknowledgements and goes red on history."""
        rules = (REPO_ROOT / ".gitignore").read_text()
        self.assertIn("!eval/results/live_flight_log_*.SAFETY_FINDING.md", rules)


if __name__ == "__main__":
    unittest.main()
