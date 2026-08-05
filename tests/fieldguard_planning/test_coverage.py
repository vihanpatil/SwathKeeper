"""Coverage-grid + coverage-debt ledger tests (Week 2 safety scaffolding).

These are RUNNABLE NOW: they are pure geometry / bookkeeping over the CURRENT mission path, field
polygon, and static-obstacle map -- no Gazebo/ROS 2, no not-yet-built avoidance loop. They pin the
baseline the Week 3-4 avoidance loop must never regress below:

  * the NOMINAL boustrophedon plan already covers every field cell (if it didn't, coverage would be
    broken before avoidance is even in the picture);
  * the coverage checker actually has teeth (a narrower swath opens detectable gaps -- negative
    control, so a passing coverage test is not vacuously green);
  * the coverage-debt ledger invariant catches a silently-skipped cell, a double-logged cell, and a
    lie about coverage.

stdlib unittest only (see test_geofence.py header for why).
Run:  python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.coverage import (  # noqa: E402
    CELL_COVERED, CELL_DEBT, DEFAULT_SWATH_HALF_WIDTH_M,
    build_grid, check_ledger, coverage_from_path, ledger_from_covered_map, load_field_polygon,
)
from fieldguard_planning.mission_waypoints import mission_xy_path, parse_qgc_wpl  # noqa: E402

FIELD_POLYGON = REPO_ROOT / "config" / "field_polygon.json"
MISSION = REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints"


def _nominal_path():
    import json
    field = json.loads(FIELD_POLYGON.read_text())
    items = parse_qgc_wpl(MISSION)
    return mission_xy_path(items, field["home_lat"], field["home_lon"])


class TestGrid(unittest.TestCase):
    def test_grid_is_deterministic_and_covers_field(self):
        poly = load_field_polygon(FIELD_POLYGON)
        g1 = build_grid(poly)
        g2 = build_grid(poly)
        self.assertEqual([c.cell_id for c in g1], [c.cell_id for c in g2])
        # 75x60 field at 2.5 m cells, rectangle -> exactly 30 x 24 = 720 cells, all centers inside.
        self.assertEqual(len(g1), 720)

    def test_cell_ids_unique(self):
        cells = build_grid(load_field_polygon(FIELD_POLYGON))
        ids = [c.cell_id for c in cells]
        self.assertEqual(len(ids), len(set(ids)))


class TestNominalCoverage(unittest.TestCase):
    """The core baseline: the nominal boustrophedon plan (no avoidance) leaves ZERO cells uncovered.
    This is the bar the Week 3-4 avoidance loop must not silently drop below."""

    def setUp(self):
        self.cells = build_grid(load_field_polygon(FIELD_POLYGON))
        self.path = _nominal_path()

    def test_nominal_mission_covers_every_cell(self):
        covered = coverage_from_path(self.cells, self.path, DEFAULT_SWATH_HALF_WIDTH_M)
        uncovered = [cid for cid, hit in covered.items() if not hit]
        self.assertEqual(uncovered, [],
                         msg=f"{len(uncovered)} field cell(s) NOT covered by the nominal plan at "
                             f"swath +/-{DEFAULT_SWATH_HALF_WIDTH_M} m: {uncovered[:8]}")

    def test_negative_control_narrow_swath_opens_gaps(self):
        # If the real camera swath is narrower than lane spacing, strips between lanes go uncovered.
        # Proves the coverage check can FAIL -- a passing coverage test is therefore meaningful.
        # 5.0 m (< 7.5 = half the 15 m spacing) opens a mid-field gap wider than the 2.5 m cell grid
        # can miss (a 7.0 m swath leaves only a ~1 m strip, too thin for a cell center to fall in).
        narrow = 5.0
        covered = coverage_from_path(self.cells, self.path, narrow)
        uncovered = [cid for cid, hit in covered.items() if not hit]
        self.assertGreater(len(uncovered), 0,
                           msg="coverage checker failed to detect gaps with a sub-spacing swath -- "
                               "the checker would be vacuous")


class TestCoverageDebtLedger(unittest.TestCase):
    """The executable coverage-debt invariant (eval/scenarios/README.md). These prove the invariant
    catches exactly the failure modes it exists for."""

    def setUp(self):
        self.cells = build_grid(load_field_polygon(FIELD_POLYGON))
        self.grid_ids = [c.cell_id for c in self.cells]

    def test_perfect_nominal_ledger_passes_with_zero_debt(self):
        covered = coverage_from_path(self.cells, _nominal_path(), DEFAULT_SWATH_HALF_WIDTH_M)
        ledger = ledger_from_covered_map(covered)
        result = check_ledger(self.grid_ids, ledger)
        self.assertTrue(result.ok, msg="; ".join(result.errors))
        self.assertEqual(result.debt_count, 0)
        self.assertEqual(result.covered_count, len(self.grid_ids))

    def test_explicit_debt_is_allowed_v1(self):
        # ADR-002 v1 bar: dropping a cell is allowed IF it is explicitly logged as debt, not absent.
        ledger = ledger_from_covered_map(
            coverage_from_path(self.cells, _nominal_path(), DEFAULT_SWATH_HALF_WIDTH_M))
        ledger[0]["status"] = CELL_DEBT  # loop chose to drop one cell but LOGGED it
        result = check_ledger(self.grid_ids, ledger)
        self.assertTrue(result.ok, msg="explicit debt must satisfy the v1 invariant")
        self.assertEqual(result.debt_count, 1)

    def test_silently_skipped_cell_is_caught(self):
        # THE headline bug: a cell simply missing from the ledger (dropped, not logged) must fail.
        ledger = ledger_from_covered_map(
            coverage_from_path(self.cells, _nominal_path(), DEFAULT_SWATH_HALF_WIDTH_M))
        dropped = ledger.pop()  # cell vanishes from the plan with no record at all
        result = check_ledger(self.grid_ids, ledger)
        self.assertFalse(result.ok)
        self.assertIn(dropped["cell_id"], result.missing)

    def test_double_logged_cell_is_caught(self):
        ledger = ledger_from_covered_map(
            coverage_from_path(self.cells, _nominal_path(), DEFAULT_SWATH_HALF_WIDTH_M))
        ledger.append(dict(ledger[0]))  # same cell logged twice -> ambiguous accounting
        result = check_ledger(self.grid_ids, ledger)
        self.assertFalse(result.ok)
        self.assertTrue(result.duplicates)

    def test_unknown_status_is_caught(self):
        ledger = ledger_from_covered_map(
            coverage_from_path(self.cells, _nominal_path(), DEFAULT_SWATH_HALF_WIDTH_M))
        ledger[0]["status"] = "requeued"  # requeued is an EVENT, never a terminal status
        result = check_ledger(self.grid_ids, ledger)
        self.assertFalse(result.ok)
        self.assertTrue(result.bad_status)


if __name__ == "__main__":
    unittest.main()
