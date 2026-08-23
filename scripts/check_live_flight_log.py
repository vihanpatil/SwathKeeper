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
     is not evidence of a flight);
  5. CLOSEST POINT OF APPROACH to every logged detection is at least the policy's own
     `min_bird_clearance_m` (ADR-013 amendment 12, R1).

WHY (5) EXISTS -- the 2026-08-23 encounter: every gate was green (19/19 maneuvers vetted, ledger
720 covered / 0 debt, this checker PASS) while the vehicle passed **0.0518 m** from the bird. The
policy already refuses to place a *setpoint* nearer than `min_bird_clearance_m`, so flying nearer
than it is inconsistent on its face -- but nothing in the pipeline computed the distance actually
FLOWN. "19/19 vetted" is a claim about setpoints, not about separation. The CPA is now printed for
every log, every run, so the number exists whether or not it is in breach: absence of a metric is
how the miss stayed invisible.

ACKNOWLEDGED-FINDING MARKERS. Recorded history cannot be re-flown, and deleting the evidence would
be worse than keeping it. A log in CPA breach may carry a sibling marker file
`<log-stem>.SAFETY_FINDING.md` (mirroring the clips' INVALID_DO_NOT_USE.md convention); with it the
breach reports as **ACKNOWLEDGED** -- a deliberately different word from VALID, printed to stderr,
never green -- and does not fail CI. Without it the breach is a hard INVALID. A marker beside a log
that PASSES is itself a defect (a stale acknowledgment silently pre-authorises the next regression),
so it fails too.

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
import math
import sys
from pathlib import Path
from typing import List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.avoidance_policy import PolicyParams  # noqa: E402
from fieldguard_planning.coverage import (  # noqa: E402
    CELL_COVERED, CELL_DEBT, DEFAULT_CELL_SIZE_M, build_grid, check_ledger, load_field_polygon,
)

RESULTS_DIR = REPO_ROOT / "eval" / "results"
# Per-file verdicts (check_file return values). SKIP is deliberately not a failure -- see the
# module docstring's gitignored-glob CI contract. ACKNOWLEDGED is a CPA breach with a marker file:
# loud, on stderr, exit 0 -- never folded into VALID.
SKIP, VALID, INVALID, ACKNOWLEDGED = "SKIP", "VALID", "INVALID", "ACKNOWLEDGED"
MARKER_SUFFIX = ".SAFETY_FINDING.md"


def min_bird_clearance_m() -> float:
    """The CPA bar, read from the POLICY that owns it (`PolicyParams.min_bird_clearance_m`) rather
    than duplicated here. A second literal 3.0 in this file would let the gate and the control law
    drift apart silently -- and the gate would go on passing flights the policy would refuse to
    command. Read per call, not captured at import, so the two can never disagree."""
    return float(PolicyParams().min_bird_clearance_m)


def marker_path_for(log_path: Path) -> Path:
    """`<...>/live_flight_log_X.json` -> `<...>/live_flight_log_X.SAFETY_FINDING.md`."""
    return log_path.with_name(log_path.stem + MARKER_SUFFIX)


def detection_positions(log) -> List[Tuple[str, float, float]]:
    """Every logged detection as (track_id, x, y). Ignores malformed entries rather than raising --
    a truncated event must not crash the gate, it must fail to provide CPA evidence."""
    out: List[Tuple[str, float, float]] = []
    if not isinstance(log, dict):
        return out
    for ev in log.get("events") or []:
        if not isinstance(ev, dict) or ev.get("kind") != "detection":
            continue
        pos = ev.get("position_enu")
        if not isinstance(pos, (list, tuple)) or len(pos) < 2:
            continue
        try:
            out.append((str(ev.get("track_id") or ev.get("frame_id") or "?"),
                        float(pos[0]), float(pos[1])))
        except (TypeError, ValueError):
            continue
    return out


def closest_approach(log) -> Optional[Tuple[float, str]]:
    """(cpa_m, track_id) -- the smallest HORIZONTAL distance between any flown path point and any
    logged detection -- or None when the log carries no CPA evidence.

    Horizontal (XY) on purpose: it is the separation the policy's own `min_bird_clearance_m` is
    expressed in, and ADR-009 is explicit that a bird's z is the estimate we cannot trust, so
    folding altitude in here would let an untrusted number manufacture clearance.

    None, never a number, when there are no detections or no path: 'nothing came close' and 'we
    never looked' are opposite claims and the caller must be able to tell them apart."""
    dets = detection_positions(log)
    path = log.get("flown_path_enu") if isinstance(log, dict) else None
    if not dets or not isinstance(path, list) or not path:
        return None
    best: Optional[Tuple[float, str]] = None
    for point in path:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            px, py = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            continue
        for track_id, dx, dy in dets:
            d = math.hypot(px - dx, py - dy)
            if best is None or d < best[0]:
                best = (d, track_id)
    return best


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
    headline = f"covered={n_cov} debt={n_debt} path_points={len(log['flown_path_enu'])}"

    # --- CPA (ADR-013 am. 12 R1). Printed ALWAYS, whatever the verdict. -------------------------
    bar = min_bird_clearance_m()
    cpa = closest_approach(log)
    marker = marker_path_for(path)
    if cpa is None:
        return VALID, [f"{headline} | CPA NO-CPA-EVIDENCE (no logged detections with a position, "
                       f"or no flown path) -- this log says nothing about separation"]
    cpa_m, track_id = cpa
    cpa_note = f"CPA {cpa_m:.4f} m to {track_id} (bar: min_bird_clearance_m {bar:.2f} m)"

    if cpa_m < bar:
        breach = (f"{cpa_note} -- FLEW CLOSER THAN THE POLICY WILL COMMAND. The policy refuses to "
                  f"place a setpoint within {bar:.2f} m of a threat; this path came within "
                  f"{cpa_m:.4f} m of one (ADR-013 amendment 12, S1).")
        if marker.exists():
            return ACKNOWLEDGED, [f"{headline} | {breach}",
                                  f"acknowledged by {marker.name} -- recorded history, kept as "
                                  f"evidence, NOT a passing flight"]
        return INVALID, [breach,
                         f"no acknowledgement marker present. If this is recorded history that "
                         f"cannot be re-flown, add {marker.name} citing the finding; if it is a "
                         f"new flight, the flight failed."]

    if marker.exists():
        return INVALID, [f"{headline} | {cpa_note} -- PASSES",
                         f"but a stale acknowledgement marker {marker.name} is present. An "
                         f"acknowledgement beside a passing log pre-authorises the next regression "
                         f"on this file; delete the marker."]
    return VALID, [f"{headline} | {cpa_note}"]


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

    n_invalid = n_acknowledged = 0
    for path in paths:
        status, messages = check_file(path)
        if status == INVALID:
            n_invalid += 1
            print(f"[check_live_flight_log] INVALID: {path}", file=sys.stderr)
            for m in messages:
                print(f"    - {m}", file=sys.stderr)
        elif status == ACKNOWLEDGED:
            # stderr, own word, own counter: an acknowledged safety finding must never read like a
            # pass in a scrollback or a CI log.
            n_acknowledged += 1
            print(f"[check_live_flight_log] ACKNOWLEDGED SAFETY FINDING: {path}", file=sys.stderr)
            for m in messages:
                print(f"    - {m}", file=sys.stderr)
        elif status == SKIP:
            print(f"[check_live_flight_log] SKIP: {messages[0]}")
        else:
            print(f"[check_live_flight_log] VALID: {path} ({messages[0]})")

    if n_invalid:
        print(f"[check_live_flight_log] FAIL: {n_invalid} of {len(paths)} flight log(s) invalid -- "
              "this file is not evidence of a real flight (idle-run clobber, corrupt ledger, or a "
              "closest-approach breach); do not keep/commit it as the demo artifact.",
              file=sys.stderr)
        return 1
    if n_acknowledged:
        print(f"[check_live_flight_log] PASS WITH {n_acknowledged} ACKNOWLEDGED SAFETY FINDING(S): "
              f"{len(paths) - n_acknowledged} of {len(paths)} log(s) clean. The acknowledged log(s) "
              f"above are kept as recorded history and are NOT evidence of a safe flight.",
              file=sys.stderr)
        return 0
    print("[check_live_flight_log] PASS: all present flight logs valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
