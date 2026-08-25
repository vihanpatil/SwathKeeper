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

# A stem the checker's own allowlist pins, read FROM the checker so a test can never assert an
# acknowledgement the shipped gate would not grant. Tests write it into their tmp dir: the pin is by
# stem, which is what makes "acknowledged" a property of a reviewed decision rather than of a
# directory anyone can drop a file into.
PINNED_STEM = checker.ACKNOWLEDGED_BREACH_STEMS[0]
# ...and the OTHER ratchet, which every test in this file now has to satisfy to reach the legacy CPA
# gate at all: since the 2026-08-24 run-block seam a log with no `run` block is scored on the
# detection-referenced path ONLY if its stem is pinned pre-seam (or it is an eval/scenarios fixture).
# The logs here carry no run block, so they are written under a pinned stem -- read from the checker,
# never spelled out, for the same reason as above. The two lists coincide today (both pre-seam live
# logs happened to breach) and are deliberately separate constants.
LEGACY_STEM, LEGACY_STEM_2 = checker.PRE_SEAM_LEGACY_STEMS
NEW_TAKE_LOG = "live_flight_log_20260901T120000Z.json"       # shaped like the next real take


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
        p = self._write(f"{LEGACY_STEM}.json", json.dumps(make_log()))
        status, messages = checker.check_file(p)
        self.assertEqual(status, checker.VALID)
        self.assertIn("covered=720", messages[0])

    def test_main_exit_codes(self):
        good = self._write(f"{LEGACY_STEM}.json", json.dumps(make_log()))
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

    def _write_log(self, log, name=f"{LEGACY_STEM}.json"):
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

    def test_breach_with_neither_half_of_an_acknowledgement_is_invalid(self):
        """Both halves missing, checked on the function that decides it.

        Not end-to-end here on purpose: since the run-block ratchet, the ONLY logs that reach this
        legacy CPA gate are the pinned pre-seam stems -- which are also the acknowledged ones -- so a
        legacy log with neither half no longer exists. The end-to-end case is a NEW take, i.e. a
        schema-2 log, and it is pinned there
        (test_check_live_flight_log_schema2.TestMarkerSemantics)."""
        problem = checker.acknowledgement_problem(self.dir / NEW_TAKE_LOG)
        self.assertIn("no acknowledgement", problem)
        self.assertIn("ACKNOWLEDGED_BREACH_STEMS", problem)
        self.assertIn(checker.MARKER_SUFFIX, problem)

    def test_breach_with_BOTH_halves_is_acknowledged_and_never_reads_as_valid(self):
        p = self._write_log(make_cpa_log(0.05), f"{PINNED_STEM}.json")
        self._mark(p)
        status, messages = checker.check_file(p)
        self.assertEqual(status, checker.ACKNOWLEDGED)
        self.assertNotEqual(status, checker.VALID)
        self.assertIn("NOT a passing flight", " ".join(messages))
        self.assertIn("CPA 0.0500 m", messages[0])       # the number is still printed, loudly

    def test_a_MARKER_ALONE_on_an_unpinned_log_is_invalid(self):
        """THE fix of 2026-08-24. A marker file is a `touch` in a gitignored directory, and the
        runbook told the operator to write one after a breach -- so the documented remedy for the
        next bird strike was also the one-file way to make it green. Acknowledging now costs a
        reviewed diff on this gate too, and half an acknowledgement acknowledges nothing.

        On the function again, for the reason above: a new take is a schema-2 log, and the
        end-to-end proof lives with the schema-2 gates."""
        p = self.dir / NEW_TAKE_LOG
        self._mark(p)
        problem = checker.acknowledgement_problem(p)
        self.assertIn("NOT pinned in ACKNOWLEDGED_BREACH_STEMS", problem)
        self.assertIn("THE FLIGHT FAILED", problem)

    def test_a_PIN_ALONE_with_no_marker_file_is_invalid_too(self):
        """The context half is mandatory in the same way: an acknowledged breach with no written
        finding beside the evidence hands the next reader a verdict with no reason."""
        p = self._write_log(make_cpa_log(0.05), f"{PINNED_STEM}.json")
        status, messages = checker.check_file(p)
        self.assertEqual(status, checker.INVALID)
        self.assertIn("is MISSING", " ".join(messages))
        self.assertIn(checker.MARKER_SUFFIX, " ".join(messages))

    def test_the_allowlist_is_the_two_historical_breaches_and_nothing_else(self):
        """The allowlist is the whole point of the fix, so its CONTENTS are pinned: a stem added
        here shows up as a failing test until the diff that adds it is deliberate."""
        self.assertEqual(checker.ACKNOWLEDGED_BREACH_STEMS,
                         ("live_flight_log_20260818T144711Z", "live_flight_log_20260823T004031Z"))

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

    def test_exit_codes_acknowledged_is_zero_and_an_UNPINNED_legacy_log_still_exits_one(self):
        """The exit code is the whole attack surface: CI reads nothing else.

        Two ratchets in one run: an acknowledged historical breach exits 0 only with BOTH halves,
        and a log wearing the legacy shape (no `run` block) that nothing pins exits 1 whatever else
        is beside it -- including a marker. A marker cannot buy the legacy path any more than it can
        buy an acknowledgement."""
        unpinned = self._write_log(make_cpa_log(0.05), NEW_TAKE_LOG)
        acknowledged = self._write_log(make_cpa_log(0.05), f"{PINNED_STEM}.json")
        clean = self._write_log(make_cpa_log(5.0), f"{LEGACY_STEM_2}.json")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(checker.main([str(unpinned)]), 1)
            self._mark(unpinned)
            self.assertEqual(checker.main([str(unpinned)]), 1)      # marker alone: still a failure
            self.assertEqual(checker.main([str(acknowledged)]), 1)  # pin alone: also a failure
            self._mark(acknowledged)
            self.assertEqual(checker.main([str(acknowledged)]), 0)  # both halves
            self.assertEqual(checker.main([str(acknowledged), str(clean)]), 0)
            self.assertEqual(checker.main([str(acknowledged), str(unpinned)]), 1)

    def test_acknowledged_output_goes_to_stderr_with_its_own_word(self):
        p = self._write_log(make_cpa_log(0.05), f"{PINNED_STEM}.json")
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


class TestOnlyPinnedPreSeamLogsReachTheLegacyGate(unittest.TestCase):
    """The 2026-08-24 run-block ratchet, from the legacy side.

    The legacy path scores CPA against the drone's OWN detections; the schema-2 path scores it
    against the bird ground truth. So `del log["run"]` was a ONE-KEY DOWNGRADE: a flight the truth
    track failed came back VALID. `avoidance_node.py` writes the run block on every take since the
    seam, so an absent one is only legal on a log that predates it -- and that list is closed, in the
    same shape and for the same reason as `ACKNOWLEDGED_BREACH_STEMS`."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_the_pre_seam_list_is_the_two_historical_logs_and_nothing_else(self):
        """Pinned contents, like the acknowledgement list: a third stem must arrive as a failing
        test until the diff that adds it is deliberate."""
        self.assertEqual(checker.PRE_SEAM_LEGACY_STEMS,
                         ("live_flight_log_20260818T144711Z", "live_flight_log_20260823T004031Z"))

    def test_an_unpinned_log_with_no_run_block_is_invalid_and_says_why(self):
        p = self.dir / NEW_TAKE_LOG
        p.write_text(json.dumps(make_cpa_log(5.0)))          # a CLEAN CPA: the run block is the fault
        status, messages = checker.check_file(p)
        self.assertEqual(status, checker.INVALID)
        blob = " ".join(messages)
        self.assertIn("NO 'run' BLOCK", blob)
        self.assertIn("PRE_SEAM_LEGACY_STEMS", blob)
        self.assertIn("fault or tampering", blob)
        self.assertIn("covered=720", messages[0])            # the numbers are still printed first

    def test_the_pinned_stems_still_take_the_legacy_path(self):
        for stem in checker.PRE_SEAM_LEGACY_STEMS:
            with self.subTest(stem=stem):
                p = self.dir / f"{stem}.json"
                p.write_text(json.dumps(make_cpa_log(5.0)))
                status, messages = checker.check_file(p)
                self.assertEqual(status, checker.VALID, " ".join(messages))
                self.assertIn("CPA 5.0000 m", messages[0])

    def test_the_scenario_fixtures_are_pinned_by_SHAPE_not_by_name(self):
        """`eval/scenarios/<name>/flight_log.json` is generated OFF-ROS (no clock, no detector, no
        bird driver), so there is nothing for a run block to record -- and the scenario set is meant
        to grow, so the pin is the path shape. Anchored at this repo: the same filename two
        directories deep anywhere else is not one of ours."""
        fixtures = sorted((REPO_ROOT / "eval" / "scenarios").glob("*/flight_log.json"))
        self.assertTrue(fixtures, "no scenario fixtures committed -- the shape pin guards nothing")
        for p in fixtures:
            with self.subTest(fixture=p.parent.name):
                self.assertTrue(checker.legacy_pinned(p))
                self.assertIsNone(checker.run_block_problem(json.loads(p.read_text()), p))
        self.assertFalse(checker.legacy_pinned(self.dir / "flight_log.json"))
        elsewhere = self.dir / "eval" / "scenarios" / "faked" / "flight_log.json"
        self.assertFalse(checker.legacy_pinned(elsewhere))

    def test_the_pin_is_by_STEM_so_the_historical_logs_survive_being_copied(self):
        """CI's evidence step (and tests/test_ci_evidence_gate.py) copy the committed logs into a
        tmp tree and run this gate there. A directory-anchored pin would fail them."""
        self.assertTrue(checker.legacy_pinned(self.dir / f"{LEGACY_STEM}.json"))
        self.assertTrue(checker.legacy_pinned(Path("/somewhere/else") / f"{LEGACY_STEM_2}.json"))


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
        p = Path(tmp.name) / f"{LEGACY_STEM}.json"
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
    """The committed evidence set must be honestly LABELLED. It is NOT required to be green.

    That distinction was implicit until 2026-08-25 and this class asserted the stronger thing. A NEW
    breach is a FAILED flight: the runbook's answer (AVOIDANCE_REAL_DETECTION.md 6a) is a written
    finding beside the evidence and NO pin, which is HALF an acknowledgement -- INVALID, exit 1, and
    correct. Requiring both halves of every breaching committed log would have made "pin it" the way
    to get the suite green, i.e. exactly the self-service acknowledgement the two-half rule exists to
    prevent, wearing a test's clothes."""

    def _committed(self):
        """(path, parsed log, verdict, messages) for every committed flight log, scored the way CI
        scores it: no --truth, so the truth join is whatever TRUTH_BINDINGS + discovery resolve."""
        for p in sorted(checker.RESULTS_DIR.glob("*flight_log*.json")):
            status, messages = checker.check_file(p)
            yield p, json.loads(p.read_text()), status, messages

    @staticmethod
    def _breaches(log, messages) -> bool:
        """Does this log breach the bar THE GATE THAT GOVERNS IT measures against?

        A schema-2 log is asked its OWN verdict; only pre-seam legacy logs are scored on
        `closest_approach()`, which is the gate they were flown under. Deciding this on the
        detection-referenced number for a schema-2 log is wrong in BOTH directions and both are
        live: on the 2026-08-25 take the demoted detection CPA reads 0.2096 m while the gated
        ground-truth CPA is 0.0067 m (the estimator's metre-scale error is why ADR-013 am. 12
        demoted it), and a MISS at closest approach produces no detection there at all -- so a real
        breach can carry no detection CPA whatsoever and this loop would skip the log in silence."""
        if checker.schema_version(log) is None:
            cpa = checker.closest_approach(log)
            return cpa is not None and cpa[0] < checker.min_bird_clearance_m()
        return any(checker.CPA_BREACH_TAG in m for m in messages)

    def test_every_breaching_committed_log_carries_its_written_finding(self):
        for p, log, status, messages in self._committed():
            if not self._breaches(log, messages):
                continue
            with self.subTest(log=p.name):
                self.assertTrue(checker.marker_path_for(p).exists(),
                                f"{p.name} breaches CPA with no {checker.MARKER_SUFFIX} marker -- "
                                f"the finding is the one thing that must exist beside the evidence")
                if p.stem in checker.ACKNOWLEDGED_BREACH_STEMS:
                    self.assertEqual(status, checker.ACKNOWLEDGED, " ".join(messages))
                else:
                    # HALF an acknowledgement: the documented, correct state of a NEW breach.
                    self.assertEqual(status, checker.INVALID, " ".join(messages))
                    blob = " ".join(messages)
                    self.assertIn("HALF an acknowledgement", blob)
                    self.assertNotIn("stale acknowledgement marker", blob)

    def test_every_committed_real_detector_log_can_be_JOINED_to_its_bird_track(self):
        """QA finding G47, on the real evidence. Sim time restarts near 0 every run, so the first
        committed applied log overlaps every later take: the 2026-08-25 take scored "AMBIGUOUS TAKE
        -> INVALID" with NO CPA printed, and the gate then called the take's own marker stale.

        This is also the guard on the test above, which decides marker-need from the verdict: a log
        the gate cannot join reports no breach, needs no marker, and passes that test in silence.
        A committed schema-2 real-detector log whose CPA cannot be measured is evidence of nothing
        -- bind it in TRUTH_BINDINGS or do not commit it."""
        for p, log, _status, messages in self._committed():
            if (log.get("run") or {}).get("detector", {}).get("source") != checker.DET_NDVI_BLOB:
                continue                       # demo/none/legacy logs have no ground-truth join
            with self.subTest(log=p.name):
                blob = " ".join(messages)
                for cannot_tell in ("AMBIGUOUS TAKE", "ambiguous truth track", "no truth track"):
                    self.assertNotIn(cannot_tell, blob)
                # A measured answer, either shape: a number, or NONE-IN-BAND with its denominator.
                # Bare "gt_cpa_m" would also match the freeze-debit line every flight prints.
                self.assertRegex(blob, r"gt_cpa_m (NONE-IN-BAND|-?\d)")
                self.assertIn(checker.TRUTH_BINDINGS.get(p.stem, "bird_drive_"), blob)

    def test_both_historical_breaches_are_still_ACKNOWLEDGED_end_to_end(self):
        """Byte-for-byte the verdict they were flown under: the two logs the allowlist pins keep
        reporting ACKNOWLEDGED / exit 0, on the real committed evidence, through main()."""
        for stem in checker.ACKNOWLEDGED_BREACH_STEMS:
            p = checker.RESULTS_DIR / f"{stem}.json"
            if not p.exists():
                continue                       # evidence is gitignored in some checkouts
            with self.subTest(log=p.name):
                status, messages = checker.check_file(p)
                self.assertEqual(status, checker.ACKNOWLEDGED, " ".join(messages))
                self.assertIn(f"acknowledged by {stem}{checker.MARKER_SUFFIX} -- recorded history, "
                              f"kept as evidence, NOT a passing flight", messages)
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(checker.main([str(p)]), 0)

    # Every committed doc that can put an operator at the prompt of a live flight. AVOIDANCE_DEMO.md
    # earns its place by history: BOTH acknowledged breaches were flown on its --demo arm, and it
    # carried no CPA bar at all until 2026-08-25. ROADMAP.md is where the next take is booked.
    DOCS_THAT_SEND_SOMEONE_FLYING = (
        ("docs", "runbooks", "AVOIDANCE_REAL_DETECTION.md"),
        ("docs", "runbooks", "AVOIDANCE_DEMO.md"),
        ("docs", "ROADMAP.md"),
    )

    def test_the_runbook_tells_the_operator_about_BOTH_halves(self):
        """The bug was as much documentation as code: the runbook's remedy for a breach was "add
        `<log-stem>.SAFETY_FINDING.md`", which was also the one-file way to make the next strike
        green. A doc that names only the marker half sends the operator back down that path, so it
        must name the reviewed half too -- by the constant's own name, in the same file. Checked
        across every such doc, not just one, so the asterisk stops being hand-maintained."""
        for rel in self.DOCS_THAT_SEND_SOMEONE_FLYING:
            doc = REPO_ROOT.joinpath(*rel)
            with self.subTest(doc=doc.name):
                self.assertTrue(doc.exists(),                       # committed docs; absence is news
                                f"{doc.name} is gone -- if it moved, move it in this list too")
                text = doc.read_text()
                self.assertIn(checker.MARKER_SUFFIX, text)          # the context half
                self.assertIn("ACKNOWLEDGED_BREACH_STEMS", text)    # the reviewed half

    def test_markers_are_git_allowlisted_so_ci_sees_them(self):
        """eval/results/* is gitignored; the LOGS are re-included. If the markers are not, CI
        checks out breaching logs without their acknowledgements and goes red on history."""
        rules = (REPO_ROOT / ".gitignore").read_text()
        self.assertIn("!eval/results/live_flight_log_*.SAFETY_FINDING.md", rules)

    def test_bound_truth_tracks_are_git_allowlisted_so_CI_can_join_them(self):
        """The third file CI needs per real-detector take. A flight log checked out without the
        applied log it is bound to scores "no truth track" -- the gate would report that it could
        not tell, on evidence whose whole point is a measured separation."""
        rules = (REPO_ROOT / ".gitignore").read_text()
        self.assertIn("!eval/results/bird_drive_*_applied.jsonl", rules)


if __name__ == "__main__":
    unittest.main()
