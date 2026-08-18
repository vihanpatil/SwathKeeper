#!/usr/bin/env python3
"""Evidence gate for flight-log JSONs (eval/results/*flight_log*.json) -- qa-safety-owned.

WHY THIS EXISTS: eval/results/live_flight_log.json -- the only machine artifact of the 2026-08-05
live end-to-end avoidance demo (docs/runbooks/AVOIDANCE_DEMO.md) -- was silently OVERWRITTEN by a
later idle run: `flown_path_enu` = [] and all 720 cells at status "debt". Nothing validated the
file, so nothing noticed. This script is that missing validation; avoidance_node.py now also writes
timestamped filenames (live_flight_log_<UTCstamp>.json) so a new run can never clobber prior
evidence again.

A flight log is VALID iff all of:
  1. it parses as JSON and carries the flight-log contract keys checked here
     (`flown_path_enu`, `coverage_ledger` -- see AvoidanceExecutor.flight_log);
  2. the coverage ledger satisfies the check_ledger partition invariant (P1-P3) against the
     canonical grid (repo field polygon, at the log's own `cell_size_m`);
  3. `flown_path_enu` is non-empty -- an empty path means the node never received a pose: an idle
     bringup, not flight evidence;
  4. NOT every grid cell is "debt" -- an all-debt ledger imaged nothing, which is again an idle
     run wearing a flight log's clothes (that is honest accounting per the ADR-002 v1 bar, but it
     is not evidence of a flight).

Absent paths SKIP with exit 0: eval/results/ is gitignored, so in CI the glob usually matches
nothing (bash passes the literal pattern through unmatched) and this gate only bites when evidence
is deliberately committed/force-added. Exit 0 = every present log valid (or none present);
exit 1 = at least one present log invalid.

Usage:
    python3 scripts/check_live_flight_log.py                          # all eval/results/*flight_log*.json
    python3 scripts/check_live_flight_log.py eval/results/*flight_log*.json
"""
import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.coverage import (  # noqa: E402
    CELL_COVERED, CELL_DEBT, DEFAULT_CELL_SIZE_M, build_grid, check_ledger, load_field_polygon,
)

RESULTS_DIR = REPO_ROOT / "eval" / "results"
# Per-file verdicts (check_file return values). SKIP is deliberately not a failure -- see the
# module docstring's gitignored-glob CI contract.
SKIP, VALID, INVALID = "SKIP", "VALID", "INVALID"


def validate_flight_log(log) -> List[str]:
    """Pure validation of one parsed flight-log dict; returns a list of problems ([] == valid).
    Importable and unit-tested (tests/fieldguard_planning/test_check_live_flight_log.py)."""
    if not isinstance(log, dict):
        return ["top-level JSON is not an object (expected the AvoidanceExecutor.flight_log dict)"]
    problems: List[str] = []

    path_enu = log.get("flown_path_enu")
    if not isinstance(path_enu, list):
        problems.append("'flown_path_enu' missing or not a list")
    elif not path_enu:
        problems.append("flown_path_enu is EMPTY -- the node never received a pose; this is an "
                        "idle run, not flight evidence")

    ledger = log.get("coverage_ledger")
    if not isinstance(ledger, list):
        problems.append("'coverage_ledger' missing or not a list")
        return problems

    cell_size = log.get("cell_size_m", DEFAULT_CELL_SIZE_M)
    try:
        grid = build_grid(load_field_polygon(), cell_size_m=float(cell_size))
    except Exception as e:  # unparseable cell_size_m, or field-polygon config trouble
        problems.append(f"cannot build canonical grid (cell_size_m={cell_size!r}): {e}")
        return problems

    result = check_ledger([c.cell_id for c in grid], ledger)
    problems.extend(f"ledger invariant: {e}" for e in result.errors)
    # All-debt = zero cells imaged. Distinct from the invariant above: an all-debt ledger is
    # perfectly HONEST accounting (P1-P3 pass) of a run that surveyed nothing -- i.e. not a flight.
    if result.n_cells > 0 and result.debt_count == result.n_cells:
        problems.append(f"ALL {result.n_cells} cells have status 'debt' (covered=0) -- an idle "
                        "run's ledger, not survey evidence")
    return problems


def check_file(path: Path) -> Tuple[str, List[str]]:
    """Validate one path -> (SKIP|VALID|INVALID, messages). For VALID the message is the headline
    numbers (CLAUDE.md: no 'it works' without a metric); for INVALID it is the problem list."""
    if not path.exists():
        return SKIP, [f"{path} absent -- nothing to validate"]
    try:
        log = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        return INVALID, [f"unreadable / not valid JSON: {e}"]
    problems = validate_flight_log(log)
    if problems:
        return INVALID, problems
    ledger = log["coverage_ledger"]
    n_cov = sum(1 for r in ledger if r.get("status") == CELL_COVERED)
    n_debt = sum(1 for r in ledger if r.get("status") == CELL_DEBT)
    return VALID, [f"covered={n_cov} debt={n_debt} path_points={len(log['flown_path_enu'])}"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", type=Path, nargs="*",
                     help="flight-log JSONs to validate (default: eval/results/*flight_log*.json)")
    args = ap.parse_args(argv)

    paths = args.logs or sorted(RESULTS_DIR.glob("*flight_log*.json"))
    if not paths:
        print("[check_live_flight_log] SKIP: no eval/results/*flight_log*.json present -- "
              "nothing to validate (eval/results/ is gitignored; exit 0).")
        return 0

    n_invalid = 0
    for path in paths:
        status, messages = check_file(path)
        if status == INVALID:
            n_invalid += 1
            print(f"[check_live_flight_log] INVALID: {path}", file=sys.stderr)
            for m in messages:
                print(f"    - {m}", file=sys.stderr)
        elif status == SKIP:
            print(f"[check_live_flight_log] SKIP: {messages[0]}")
        else:
            print(f"[check_live_flight_log] VALID: {path} ({messages[0]})")

    if n_invalid:
        print(f"[check_live_flight_log] FAIL: {n_invalid} of {len(paths)} flight log(s) invalid -- "
              "this file is not evidence of a real flight (idle-run clobber or corrupt ledger); "
              "do not keep/commit it as the demo artifact.", file=sys.stderr)
        return 1
    print("[check_live_flight_log] PASS: all present flight logs valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
