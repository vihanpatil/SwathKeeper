"""Tests for the reactive-avoidance executor (avoidance_executor.py) — ADR-006.

Covers the guarantees the module exists to make impossible-by-construction:
  1. never fly an unvetted setpoint (safety backstop re-vets is_safe_3d -> HOLD on reject),
  2. never silently drop a coverage cell (finalize's ledger satisfies the partition invariant), and
  3. command ONE dodge point per encounter (the setpoint latch + its re-latch escape hatch).
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
    AvoidanceExecutor, SimulatedVehicleSink, MODE_AUTO, MODE_GUIDED, RELATCH_THRESHOLD_M,
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


def _divert(setpoint, track_id="bird_0", frame_id=1, reason="test divert"):
    """A DIVERT maneuver whose bird sits 3 m east of the dodge target (contents irrelevant to the
    executor -- it only ever reads decision/setpoint/detection-for-logging)."""
    bird = (setpoint[0] + 3.0, setpoint[1], setpoint[2])
    return AvoidanceManeuver(decision=Decision.DIVERT, setpoint_enu=setpoint, reason=reason,
                             triggering_detection=Detection(bird, frame_id=frame_id,
                                                            track_id=track_id))


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

    # -- setpoint latch: ONE commanded dodge point per encounter --------------
    def test_setpoint_latches_so_policy_drift_is_not_recommanded(self):
        """The policy recomputes its dodge every tick, so consecutive DIVERTs carry slightly
        different setpoints. The executor must keep flying the FIRST vetted one -- otherwise the
        commanded point walks around every tick (jumpy on film; a live log showed a 6 m outlier)."""
        ex, sink = _exec()
        first = (30.0, 30.0, 15.0)
        drift = (30.4, 30.3, 15.0)   # 0.5 m away -- recompute drift, well under the threshold
        self.assertLess(((drift[0] - first[0]) ** 2 + (drift[1] - first[1]) ** 2) ** 0.5,
                        RELATCH_THRESHOLD_M)
        ex.step(_drone(30.0, 20.0, wp=3), _divert(first))
        ex.step(_drone(30.0, 22.0, wp=3), _divert(drift, frame_id=2))
        self.assertEqual(sink.setpoints_sent, [first, first])   # same point commanded twice
        self.assertEqual(len(set(sink.setpoints_sent)), 1)
        self.assertNotIn(drift, sink.setpoints_sent)            # the drifted point never flew
        self.assertEqual(len(_events(ex, "latch")), 1)          # latched once...
        self.assertEqual(_events(ex, "relatch"), [])            # ...and never re-latched
        # both ticks still commanded a dodge, and the log keeps the ignored policy point on record
        maneuvers = _events(ex, "maneuver")
        self.assertEqual([m["latch_action"] for m in maneuvers], ["latch", "recommand_latched"])
        self.assertEqual(maneuvers[1]["policy_setpoint_enu"], drift)
        self.assertEqual(maneuvers[1]["setpoint_enu"], first)

    def test_policy_setpoint_beyond_threshold_relatches(self):
        """Escape hatch: a genuinely moving threat pushes the policy's dodge far enough that the
        latch must yield -- re-vetted, re-latched, and logged as such."""
        ex, sink = _exec()
        first = (30.0, 30.0, 15.0)
        moved = (34.5, 30.0, 15.0)   # 4.5 m away -- past the threshold, and safe
        self.assertGreater(moved[0] - first[0], RELATCH_THRESHOLD_M)
        self.assertTrue(ex.geofence.is_safe_3d(moved, alt_bounds=(2.0, 30.0)))
        ex.step(_drone(30.0, 20.0, wp=3), _divert(first))
        ex.step(_drone(30.0, 22.0, wp=3), _divert(moved, frame_id=2))
        self.assertEqual(sink.setpoints_sent, [first, moved])   # the new point really flew
        relatch = _events(ex, "relatch")
        self.assertEqual(len(relatch), 1)
        self.assertEqual(relatch[0]["setpoint_enu"], moved)
        self.assertEqual(relatch[0]["previous_setpoint_enu"], first)
        self.assertAlmostEqual(relatch[0]["offset_m"], 4.5)
        self.assertEqual(len(_events(ex, "takeover")), 1)       # still ONE takeover (no thrash)
        # a third tick back near the new latch is absorbed by it, not re-commanded
        ex.step(_drone(30.0, 24.0, wp=3), _divert((34.7, 30.0, 15.0), frame_id=3))
        self.assertEqual(sink.setpoints_sent, [first, moved, moved])

    def test_unsafe_relatch_candidate_holds_and_keeps_the_latch(self):
        """A re-latch candidate that fails the 3D re-vet must not weaken the backstop: HOLD per the
        existing behavior, never command it -- and the already-vetted latch survives for later ticks."""
        ex, sink = _exec()
        first = (18.0, 5.0, 15.0)    # safe, above the tree row
        unsafe = (15.0, 5.0, 2.0)    # inside tree_row0_0's canopy band, and >threshold from `first`
        self.assertTrue(ex.geofence.is_safe_3d(first, alt_bounds=(2.0, 30.0)))
        self.assertFalse(ex.geofence.is_safe_3d(unsafe, alt_bounds=(2.0, 30.0)))
        ex.step(_drone(21.0, 5.0, wp=4), _divert(first))
        ex.step(_drone(20.0, 5.0, wp=4), _divert(unsafe, frame_id=2))
        self.assertNotIn(unsafe, sink.setpoints_sent)           # rejected point NEVER commanded
        self.assertEqual(len(_events(ex, "gate_reject")), 1)
        self.assertEqual(len(_events(ex, "hold")), 1)           # fell back to HOLD as before
        self.assertEqual(_events(ex, "relatch"), [])            # rejection did not re-latch
        # the latch survived: the next in-threshold DIVERT re-commands the ORIGINAL vetted point
        ex.step(_drone(20.0, 5.0, wp=4), _divert((18.5, 5.0, 15.0), frame_id=3))
        self.assertEqual(sink.setpoints_sent[-1], first)
        self.assertEqual(len(_events(ex, "latch")), 1)          # still the one original latch

    def test_latch_is_cleared_on_resume_so_the_next_encounter_latches_fresh(self):
        """Latch lifecycle == the encounter (same as `_wp_at_takeover`): a second encounter must
        latch its own point, not inherit the stale one from the first."""
        ex, sink = _exec()
        first = (30.0, 30.0, 15.0)
        second = (30.5, 30.0, 15.0)  # within the threshold of `first` -- would be swallowed by a
                                     # stale latch, so commanding it proves the latch really cleared
        ex.step(_drone(30.0, 20.0, wp=3), _divert(first))
        ex.step(_drone(30.0, 22.0, wp=3), AvoidanceManeuver(decision=Decision.PROCEED))  # resume
        self.assertEqual(sink.mode, MODE_AUTO)
        self.assertEqual(_events(ex, "resume")[0]["latched_setpoint_enu"], first)  # logged on the way out
        ex.step(_drone(30.0, 24.0, wp=3), _divert(second, frame_id=9))             # 2nd encounter
        self.assertEqual(sink.setpoints_sent, [first, second])          # PROCEED commands nothing
        self.assertEqual(len(_events(ex, "latch")), 2)
        self.assertEqual(_events(ex, "relatch"), [])
        self.assertEqual(len(_events(ex, "takeover")), 2)               # one takeover per encounter

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

    # -- ledger honesty: a COMMANDED setpoint is not a FLOWN position ---------
    def test_commanded_but_unflown_setpoint_does_not_cover(self):
        """Regression for the 2026-08-18 ledger-honesty bug: `_handle_divert` used to record the
        commanded DIVERT setpoint into flown_path as if flown, so a cell the vehicle never visited
        finalized as COVERED -- the exact silent-coverage lie the ledger exists to prevent."""
        ex, sink = _exec()
        dodge = (30.0, 30.0, 15.0)  # dead-center of c2 -- which the drone will NEVER reach
        mv = AvoidanceManeuver(decision=Decision.DIVERT, setpoint_enu=dodge, reason="test divert",
                               triggering_detection=Detection((33.0, 30.0, 15.0), frame_id=1,
                                                              track_id="bird_0"))
        ex.step(_drone(30.0, 10.0, wp=3), mv)   # divert commanded toward c2...
        # ...but the threat clears before the vehicle moves; mission resumes over c0/c1 only
        ex.step(_drone(30.0, 10.0, wp=3), AvoidanceManeuver(decision=Decision.PROCEED))
        ex.step(_drone(30.0, 20.0, wp=3), AvoidanceManeuver(decision=Decision.PROCEED))
        ledger = ex.finalize()
        self.assertIn(dodge, sink.setpoints_sent)      # the dodge WAS commanded...
        self.assertNotIn(dodge, ex.flown_path)         # ...but never recorded as flown
        res = check_ledger([c.cell_id for c in _cells()], ledger)
        self.assertTrue(res.ok, res.errors)
        status = {r["cell_id"]: r["status"] for r in ledger}
        self.assertEqual(status["c2"], CELL_DEBT)      # pre-fix: COVERED (the lie)
        self.assertEqual(status["c0"], CELL_COVERED)
        self.assertEqual(status["c1"], CELL_COVERED)

    # -- guards ---------------------------------------------------------------
    def test_step_after_finalize_raises(self):
        ex, _ = _exec()
        ex.finalize()
        with self.assertRaises(RuntimeError):
            ex.step(_drone(30.0, 10.0), AvoidanceManeuver(decision=Decision.PROCEED))

    def test_finalize_is_idempotent(self):
        ex, _ = _exec()
        for y in (10.0, 20.0):
            ex.step(_drone(30.0, y), AvoidanceManeuver(decision=Decision.PROCEED))
        first = ex.finalize()
        events_after_first = len(ex.event_log)
        second = ex.finalize()
        self.assertEqual(first, second)                        # same ledger back
        self.assertEqual(len(ex.event_log), events_after_first)  # no duplicated debt events


class TestTheStalenessGateCannotKillAFlightSILENTLY(unittest.TestCase):
    """QA ROUND 2, FINDING 2, the probe: 20 ticks with a bird 2 m horizontal / 1 m below the drone
    -- squarely inside the threat cylinder on every one -- flown through the REAL policy and the
    REAL executor, twice. Fresh stamps: 20 detections, 20 maneuvers. Every stamp 60 s old: 0
    detections, 0 maneuvers, 20 PROCEEDs -- avoidance completely dead.

    The defect was that `n_stale_dropped` rode ONLY on an accepted-DIVERT `maneuver` event, and
    all-stale is precisely the case that never produces one. So the counter whose whole job is to
    tell "every detection expired" from "no bird was ever seen" read **0 in both arms**, and the
    flight certified VALID with `R2/R3 PASS (vacuous)` and `n_stale_dropped=0`. Trigger in the air:
    any systematic sub-second clock offset (the node's domain tripwire only fires on stamps in the
    FUTURE), or a render stall longer than the 1.0 s bound."""

    def _fly(self, stamp_age_s):
        from fieldguard_planning.avoidance_policy import AvoidancePolicy
        from fieldguard_planning.coverage import load_field_polygon
        pol = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=15.0)
        ex, sink = _exec()
        now = 1000.0
        for i in range(20):
            drone = _drone(30.0, 10.0 + 0.1 * i)
            bird = Detection((32.0, 10.0 + 0.1 * i, 14.0), frame_id=i, track_id="bird_0",
                             stamp_s=now + 0.2 * i - stamp_age_s)
            ex.step(drone, pol.decide(bird, drone, ex.geofence, now_s=now + 0.2 * i))
        return ex

    @staticmethod
    def _stale_total(ex):
        """`check_live_flight_log.stale_dropped_total`'s rule, applied to the live event log."""
        return sum(e["debug"].get("n_stale_dropped") or 0 for e in ex.event_log
                   if isinstance(e.get("debug"), dict))

    def test_fresh_detections_engage_the_loop_and_drop_nothing(self):
        ex = self._fly(stamp_age_s=0.0)
        self.assertEqual(len(_events(ex, "detection")), 20)
        self.assertEqual(len(_events(ex, "maneuver")), 20)
        self.assertEqual(self._stale_total(ex), 0)

    def test_every_detection_expiring_is_COUNTABLE_and_not_a_silent_zero(self):
        ex = self._fly(stamp_age_s=60.0)
        self.assertEqual(_events(ex, "detection"), [])        # the loop never engaged...
        self.assertEqual(_events(ex, "maneuver"), [])
        self.assertEqual(len(_events(ex, "proceed")), 20)
        self.assertEqual(self._stale_total(ex), 20)           # ...and the artifact says WHY
        proceed = _events(ex, "proceed")[0]
        self.assertEqual(proceed["debug"]["n_stale_dropped"], 1)
        self.assertEqual(proceed["debug"]["stale_ids"], ["bird_0"])
        self.assertEqual(proceed["debug"]["max_detection_age_s"], 1.0)

    def test_a_flight_that_saw_nothing_stays_distinguishable_from_one_that_expired(self):
        """The other half of the diagnosis: no detections at all must NOT grow a stale count, or the
        two cases become the same artifact again from the opposite direction."""
        ex, _ = _exec()
        for i in range(5):
            ex.step(_drone(30.0, 10.0 + i), AvoidanceManeuver(decision=Decision.PROCEED))
        self.assertEqual(self._stale_total(ex), 0)
        self.assertTrue(all("debug" not in e for e in _events(ex, "proceed")),
                        "a healthy tick must not pay for a debug dict it has nothing to put in")

    def test_a_HOLD_carries_the_count_too_so_a_partial_drop_is_not_lost(self):
        """Stale drops travel with whatever decision the tick produced -- a tick that dropped an old
        bird and HELD for a live one must not lose the count on its way to the log."""
        ex, _ = _exec()
        mv = AvoidanceManeuver(decision=Decision.HOLD, reason="boxed in",
                               debug={"n_stale_dropped": 2, "stale_ids": ["a", "b"]})
        ex.step(_drone(30.0, 10.0), mv)
        self.assertEqual(_events(ex, "hold")[0]["debug"]["n_stale_dropped"], 2)
        self.assertEqual(self._stale_total(ex), 2)


if __name__ == "__main__":
    unittest.main()
