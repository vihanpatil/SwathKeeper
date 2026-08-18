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


if __name__ == "__main__":
    unittest.main()
