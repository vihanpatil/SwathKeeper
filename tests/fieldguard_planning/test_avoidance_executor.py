"""Tests for the reactive-avoidance executor (avoidance_executor.py) — ADR-006.

Covers the two guarantees the module exists to make impossible-by-construction:
  1. never fly an unvetted setpoint (safety backstop re-vets is_safe_3d -> HOLD on reject), and
  2. never silently drop a coverage cell (finalize's ledger satisfies the partition invariant).
Plus the ADR-006 AUTO->GUIDED->AUTO takeover/resume flow. Stdlib unittest, bare python.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fieldguard_planning.avoidance_types import (  # noqa: E402
    AvoidanceManeuver, Decision, Detection, DroneState,
)
from fieldguard_planning.avoidance_executor import (  # noqa: E402
    AvoidanceExecutor, SimulatedVehicleSink, MODE_AUTO, MODE_GUIDED,
)
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402
from fieldguard_planning.coverage import CoverageCell, check_ledger, CELL_DEBT, CELL_COVERED  # noqa: E402

SWATH = 3.0


def _cells():
    # three cells along a column in open field (away from trees at x in {15,40,65})
    return [
        CoverageCell(cell_id="c0", i=0, j=0, cx_m=30.0, cy_m=10.0),
        CoverageCell(cell_id="c1", i=0, j=1, cx_m=30.0, cy_m=20.0),
        CoverageCell(cell_id="c2", i=0, j=2, cx_m=30.0, cy_m=30.0),
    ]


def _drone(x, y, z=15.0, wp=3):
    return DroneState(position_enu=(x, y, z), heading_rad=0.0, current_wp_index=wp)


def _exec(sink=None, cells=None):
    geo = GeofenceMap.from_file()
    sink = sink or SimulatedVehicleSink(initial_wp_index=3)
    return AvoidanceExecutor(geo, cells or _cells(), sink, swath_half_width_m=SWATH,
                             alt_bounds=(2.0, 30.0)), sink


def _events(ex, kind):
    return [e for e in ex.event_log if e["kind"] == kind]


class TestAvoidanceExecutor(unittest.TestCase):
    # -- nominal coverage -----------------------------------------------------
    def test_proceed_path_covers_all_cells_partition_ok(self):
        ex, sink = _exec()
        for y in (10.0, 20.0, 30.0):
            ex.step(_drone(30.0, y), AvoidanceManeuver(decision=Decision.PROCEED))
        ledger = ex.finalize()
        res = check_ledger([c.cell_id for c in _cells()], ledger)
        self.assertTrue(res.ok, res.errors)
        self.assertEqual(len(res.debt), 0)
        self.assertEqual(len(res.covered), 3)
        self.assertEqual(sink.mode, MODE_AUTO)  # never left AUTO on a clean run

    # -- ADR-006 latch: take over once, hold GUIDED, resume once on clear ------
    def test_divert_latches_then_resumes_on_clear(self):
        ex, sink = _exec()  # sink initial_wp_index=3
        mv = AvoidanceManeuver(decision=Decision.DIVERT, setpoint_enu=(30.0, 30.0, 15.0),
                               reason="test divert",
                               triggering_detection=Detection((33.0, 30.0, 15.0), frame_id=1, track_id="bird_0"))
        # 1) threat present -> take over, hold GUIDED, command the dodge, do NOT resume yet
        ex.step(_drone(30.0, 20.0, wp=3), mv)
        self.assertEqual(sink.mode, MODE_GUIDED)                 # latched in GUIDED, not toggled back
        self.assertIn((30.0, 30.0, 15.0), sink.setpoints_sent)
        self.assertEqual(len(_events(ex, "takeover")), 1)
        self.assertEqual(_events(ex, "resume"), [])             # no resume while threat persists
        # 2) a second DIVERT tick must NOT re-take-over (this is what kills the 5 Hz thrash)
        ex.step(_drone(30.0, 22.0, wp=3), mv)
        self.assertEqual(len(_events(ex, "takeover")), 1)       # STILL exactly one takeover
        self.assertEqual(sink.mode, MODE_GUIDED)
        # 3) threat clears (PROCEED) -> single resume back to AUTO at the SAME waypoint (MIS_RESTART=0)
        ex.step(_drone(30.0, 24.0, wp=3), AvoidanceManeuver(decision=Decision.PROCEED))
        self.assertEqual(sink.mode, MODE_AUTO)
        resume = _events(ex, "resume")
        self.assertEqual(len(resume), 1)
        self.assertTrue(resume[-1]["resumed_same_waypoint"])

    # -- safety backstop: unsafe setpoint -> HOLD, never sent -----------------
    def test_unsafe_divert_setpoint_is_rejected_and_never_sent(self):
        ex, sink = _exec()
        unsafe = (15.0, 5.0, 2.0)  # inside tree_row0_0's canopy band (z=2 < 3.5) -> is_safe_3d False
        self.assertFalse(ex.geofence.is_safe_3d(unsafe, alt_bounds=(2.0, 30.0)))
        mv = AvoidanceManeuver(decision=Decision.DIVERT, setpoint_enu=unsafe, reason="bad dodge",
                               triggering_detection=Detection((12.0, 5.0, 15.0), frame_id=2, track_id="bird_1"))
        ex.step(_drone(18.0, 5.0, wp=4), mv)
        # the rejection was logged and the executor fell back to HOLD
        self.assertTrue(_events(ex, "gate_reject"))
        self.assertTrue(_events(ex, "hold"))
        # the unsafe point was NEVER commanded to the vehicle
        self.assertNotIn(unsafe, sink.setpoints_sent)

    # -- coverage-debt: a skipped cell is DEBT, never missing -----------------
    def test_skipped_cell_becomes_explicit_debt_not_missing(self):
        ex, sink = _exec()
        # only fly over c0 and c1; c2 (30,30) is never imaged -> must end as explicit debt
        for y in (10.0, 20.0):
            ex.step(_drone(30.0, y), AvoidanceManeuver(decision=Decision.PROCEED))
        ledger = ex.finalize()
        res = check_ledger([c.cell_id for c in _cells()], ledger)
        self.assertTrue(res.ok, res.errors)          # partition still holds (no missing cell)
        self.assertEqual(len(res.debt), 1)
        status = {r["cell_id"]: r["status"] for r in ledger}
        self.assertEqual(status["c2"], CELL_DEBT)
        self.assertEqual(status["c0"], CELL_COVERED)
        self.assertTrue(_events(ex, "debt"))

    # -- guards ---------------------------------------------------------------
    def test_step_after_finalize_raises(self):
        ex, _ = _exec()
        ex.finalize()
        with self.assertRaises(RuntimeError):
            ex.step(_drone(30.0, 10.0), AvoidanceManeuver(decision=Decision.PROCEED))


if __name__ == "__main__":
    unittest.main()
