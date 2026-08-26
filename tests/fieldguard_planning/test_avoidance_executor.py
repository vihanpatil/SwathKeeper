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

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.avoidance_types import (  # noqa: E402
    AvoidanceManeuver, Decision, Detection, DroneState,
)
from fieldguard_planning.avoidance_executor import (  # noqa: E402
    AvoidanceExecutor, SimulatedVehicleSink, GUIDED_CEILING_TICKS, MODE_AUTO, MODE_GUIDED,
    RELATCH_THRESHOLD_M, RESUME_CLEAR_TICKS,
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


def _exec(sink=None, cells=None, **kwargs):
    geo = GeofenceMap.from_file()
    sink = sink or SimulatedVehicleSink(initial_wp_index=3)
    return AvoidanceExecutor(geo, cells or _cells(), sink, swath_half_width_m=SWATH,
                             alt_bounds=(2.0, 30.0), **kwargs), sink


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
        # 3) ONE clear frame is not a cleared threat (design note 4): still GUIDED, still no resume
        ex.step(_drone(30.0, 24.0, wp=3), AvoidanceManeuver(decision=Decision.PROCEED))
        self.assertEqual(sink.mode, MODE_GUIDED)
        self.assertEqual(_events(ex, "resume"), [])
        # 4) it stays clear -> single resume back to AUTO at the SAME waypoint (MIS_RESTART=0)
        for i in range(RESUME_CLEAR_TICKS - 1):
            ex.step(_drone(30.0, 26.0 + i, wp=3), AvoidanceManeuver(decision=Decision.PROCEED))
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
        for i in range(RESUME_CLEAR_TICKS):        # the threat must stay gone, not blink (note 4)
            ex.step(_drone(30.0, 22.0 + i, wp=3), AvoidanceManeuver(decision=Decision.PROCEED))
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


class TestThreatClearHysteresis(unittest.TestCase):
    """ONE EMPTY FRAME MUST NOT END AN ENCOUNTER (ADR-016, 2026-08-25).

    The 2026-08-25 take's GUIDED window closed after 0.434 s, on `threat_cleared`, the instant the
    first tick with no in-cylinder detection arrived (4 detection ticks, resume on the 5th) -- the
    threat test was per-frame instantaneous. A real detector drops frames: the ADOPT evidence is
    3 FN in n=20 visible bird-frames (ADR-003 am. 7), so a one-frame hole inside an encounter is an
    ordinary event, and handing the mission back on one means resuming toward a bird that is still
    there, ~0.2 s into a dodge the vehicle has barely started.

    Owned here and nowhere else: this is about how long ABSENCE must persist, not about how old a
    detection may be (`PolicyParams.max_detection_age_s`) and not about entry (the policy's threat
    cylinder). Neither is touched."""

    def _mv(self):
        return _divert((30.0, 30.0, 15.0))

    def _fly(self, decisions, **kwargs):
        """One tick per character: 'd' = DIVERT, 'p' = PROCEED (clear frame), 'h' = HOLD."""
        ex, sink = _exec(**kwargs)
        for i, d in enumerate(decisions):
            mv = {"d": self._mv(),
                  "p": AvoidanceManeuver(decision=Decision.PROCEED),
                  "h": AvoidanceManeuver(decision=Decision.HOLD, reason="boxed in")}[d]
            ex.step(_drone(30.0, 20.0 + i, wp=3), mv)
        return ex, sink

    def test_a_single_empty_frame_does_not_resume(self):
        """THE regression. Pre-fix this resumed on tick 2 and took over again on tick 3."""
        ex, sink = self._fly("dpd")
        self.assertEqual(_events(ex, "resume"), [])
        self.assertEqual(sink.mode, MODE_GUIDED)
        self.assertEqual(len(_events(ex, "takeover")), 1)   # one encounter, not two

    def test_the_gap_resets_the_clear_counter_but_the_encounter_is_still_bounded(self):
        """Two properties, and the second is why the first is allowed to exist.

        RESET: 2 clear ticks, a detection, 2 more clear ticks -- never 3 in a row, so no resume.
        BOUNDED: repeating that pattern must NOT hold GUIDED forever. Before the ceiling landed
        (QA C1, 2026-08-25) it did: 90 ticks of `dpp` gave 1 takeover, 0 resumes, and the mission
        booked the rest of the field as debt while `resume_pending` cycled 1,2,1,2 -- an artifact
        that reads healthy. This test pinned the stall as DESIRED behaviour until QA caught it."""
        ex, sink = self._fly("dppdpp")
        self.assertEqual(_events(ex, "resume"), [])
        self.assertEqual(sink.mode, MODE_GUIDED)
        # ... and the same pattern, run past the ceiling, terminates.
        ex2, sink2 = self._fly("dpp" * (GUIDED_CEILING_TICKS // 3 + 2))
        resumes = _events(ex2, "resume")
        self.assertTrue(resumes, "a duty-cycled detector held GUIDED with no bound -- QA C1")
        self.assertEqual(resumes[0]["trigger"], "guided_ceiling")

    def test_n_consecutive_clear_frames_resume_exactly_once(self):
        ex, sink = self._fly("dppp")
        resume = _events(ex, "resume")
        self.assertEqual(len(resume), 1)
        self.assertEqual(sink.mode, MODE_AUTO)
        self.assertTrue(resume[0]["resumed_same_waypoint"])
        self.assertEqual(resume[0]["clear_ticks_required"], RESUME_CLEAR_TICKS)
        # and the encounter really is over: the latch was dropped, so the next threat latches fresh
        self.assertIsNone(ex._latched_setpoint)

    def test_a_hold_tick_resets_the_counter_too(self):
        """A HOLD is a threat the policy could not dodge, not a clear frame."""
        ex, sink = self._fly("dpphp")
        self.assertEqual(_events(ex, "resume"), [])
        self.assertEqual(sink.mode, MODE_GUIDED)

    def test_the_wait_is_visible_in_the_log_and_costs_a_clean_flight_nothing(self):
        ex, _ = self._fly("dpppp")
        pending = [e.get("resume_pending") for e in _events(ex, "proceed")]
        self.assertEqual([(p["clear_ticks"], p["required"], p["ticks_in_guided"])
                          for p in pending[:2]],
                         [(1, RESUME_CLEAR_TICKS, 2), (2, RESUME_CLEAR_TICKS, 3)])
        self.assertIsNone(pending[2])                  # the resuming tick is not "pending"
        # AUTO ticks (never took over, or already resumed) pay nothing -- no key at all.
        ex2, _ = self._fly("ppp")
        self.assertEqual(_events(ex2, "resume"), [])
        self.assertTrue(all("resume_pending" not in e for e in _events(ex2, "proceed")))

    def test_it_is_configurable_and_one_tick_is_the_old_instantaneous_behaviour(self):
        ex, sink = self._fly("dp", resume_clear_ticks=1)
        self.assertEqual(len(_events(ex, "resume")), 1)
        self.assertEqual(sink.mode, MODE_AUTO)

    def test_the_default_cannot_outlast_the_policys_own_staleness_gate(self):
        """By-construction bound, not taste: holding GUIDED for longer than the policy will keep a
        detection alive would mean waiting on evidence it has already declared ABSENT.

        This is the NOMINAL-rate floor -- 3 ticks x 1/CONTROL_HZ = 0.6 s against
        `max_detection_age_s` 1.0 s -- and it is the conservative end: the flown tick period is a
        median 0.160 s (2026-08-25, n=1855), so the real budget is 0.48 s. The flight's OWN measured
        rate is checked per-log by `check_live_flight_log.gate_encounter_closure`; this static bound
        is the floor under it, not a substitute (QA M3)."""
        from fieldguard_planning.avoidance_node import CONTROL_HZ
        from fieldguard_planning.avoidance_policy import PolicyParams
        self.assertGreaterEqual(RESUME_CLEAR_TICKS, 2)   # 1 = no hysteresis at all
        self.assertLessEqual(RESUME_CLEAR_TICKS / CONTROL_HZ, PolicyParams().max_detection_age_s)

    def test_it_does_not_touch_threat_entry(self):
        """Entry is still instantaneous: the FIRST detection takes over on its own tick. Hysteresis
        that delayed entry would be a safety regression, not a fix."""
        ex, sink = self._fly("d")
        self.assertEqual(len(_events(ex, "takeover")), 1)
        self.assertEqual(sink.mode, MODE_GUIDED)
        self.assertEqual(sink.setpoints_sent, [(30.0, 30.0, 15.0)])

    # -- M2: unreadable evidence is not absence ------------------------------------------------
    def test_a_tick_whose_detections_were_all_stale_is_not_a_clear_tick(self):
        """The staleness gate returning PROCEED means "I cannot see", not "nothing is there".

        The 2026-08-24 QA probe produced exactly this stream -- a bird 2 m away, every detection
        60 s stale, 20 consecutive PROCEEDs -- and before this fix three of them resumed the mission
        with `trigger: threat_cleared`, booking unreadable evidence as confirmed absence."""
        ex, sink = _exec()
        ex.step(_drone(30.0, 20.0, wp=3), self._mv())
        for i in range(RESUME_CLEAR_TICKS + 2):
            ex.step(_drone(30.0, 22.0 + i, wp=3),
                    AvoidanceManeuver(decision=Decision.PROCEED,
                                      debug={"n_stale_dropped": 2, "stale_ids": ["b0", "b1"]}))
        self.assertEqual(_events(ex, "resume"), [])
        self.assertEqual(sink.mode, MODE_GUIDED)
        # and the artifact says why on every waiting tick: the stale count rides the proceed event
        self.assertEqual(_events(ex, "proceed")[0]["debug"]["n_stale_dropped"], 2)

    def test_a_permanently_stale_stream_still_terminates_on_the_ceiling(self):
        """The two fixes are load-bearing together: M2 makes stale ticks never clear the encounter,
        which is only safe because C1's ceiling bounds it."""
        ex, sink = _exec()
        ex.step(_drone(30.0, 20.0, wp=3), self._mv())
        for i in range(GUIDED_CEILING_TICKS + 1):
            ex.step(_drone(30.0, 21.0, wp=3),
                    AvoidanceManeuver(decision=Decision.PROCEED, debug={"n_stale_dropped": 1}))
        self.assertEqual([e["trigger"] for e in _events(ex, "resume")], ["guided_ceiling"])
        self.assertEqual(sink.mode, MODE_AUTO)

    def test_a_fresh_proceed_after_stale_ones_still_clears_normally(self):
        """M2 must not break the ordinary path: readable clear ticks still end the encounter."""
        ex, sink = _exec()
        ex.step(_drone(30.0, 20.0, wp=3), self._mv())
        ex.step(_drone(30.0, 21.0, wp=3),
                AvoidanceManeuver(decision=Decision.PROCEED, debug={"n_stale_dropped": 1}))
        for i in range(RESUME_CLEAR_TICKS):
            ex.step(_drone(30.0, 22.0 + i, wp=3), AvoidanceManeuver(decision=Decision.PROCEED))
        self.assertEqual([e["trigger"] for e in _events(ex, "resume")], ["threat_cleared"])
        self.assertEqual(sink.mode, MODE_AUTO)

    # -- knob validation -------------------------------------------------------------------------
    def test_a_hysteresis_below_one_tick_is_refused_at_construction(self):
        """0 and -5 silently restore the instantaneous pre-2026-08-25 resume while every log still
        advertises hysteresis. Refuse rather than absorb."""
        for bad in (0, -5):
            with self.subTest(resume_clear_ticks=bad), self.assertRaises(ValueError):
                _exec(resume_clear_ticks=bad)

    def test_a_ceiling_below_the_hysteresis_is_refused_at_construction(self):
        """Every encounter would then end on the backstop and none on a cleared threat."""
        with self.assertRaises(ValueError):
            _exec(resume_clear_ticks=3, guided_ceiling_ticks=2)


class TestGuidedCeiling(unittest.TestCase):
    """NO ENCOUNTER HOLDS GUIDED FOREVER (QA C1, 2026-08-25).

    Hysteresis resets the clear counter on every threat tick, so a detection duty cycle of
    1-in-`RESUME_CLEAR_TICKS` ticks or denser never reaches the count. Measured on the real executor
    before the fix: `DIVERT, PROCEED, PROCEED` x30 = 90 ticks, 1 takeover, **0 resumes**, locked in
    GUIDED for the rest of the flight -- every remaining cell booking as coverage debt, with no
    bound, no gate coverage, and instrumentation (`resume_pending` cycling 1,2,1,2) that made the
    locked flight look healthy."""

    def _mv(self):
        return _divert((30.0, 30.0, 15.0))

    def _duty_cycle(self, cycles, **kwargs):
        """`DIVERT, PROCEED, PROCEED` repeated -- the stall stream, on the real executor."""
        ex, sink = _exec(**kwargs)
        for i in range(cycles):
            ex.step(_drone(30.0, 20.0 + 0.02 * i, wp=3), self._mv())
            ex.step(_drone(30.0, 20.0 + 0.02 * i, wp=3), AvoidanceManeuver(decision=Decision.PROCEED))
            ex.step(_drone(30.0, 20.0 + 0.02 * i, wp=3), AvoidanceManeuver(decision=Decision.PROCEED))
        return ex, sink

    def test_the_duty_cycled_detector_no_longer_locks_the_mission_in_guided(self):
        ex, _sink = self._duty_cycle(GUIDED_CEILING_TICKS // 3 + 2)
        resumes = _events(ex, "resume")
        self.assertTrue(resumes, "0 resumes over an encounter past the ceiling -- QA C1 regression")
        self.assertEqual(resumes[0]["trigger"], "guided_ceiling")
        self.assertEqual(resumes[0]["ticks_in_guided"], GUIDED_CEILING_TICKS)

    def test_the_backstop_never_calls_itself_a_cleared_threat(self):
        """The whole point of a separate trigger: a reader must not be able to mistake the two."""
        ex, _sink = self._duty_cycle(GUIDED_CEILING_TICKS // 3 + 2)
        resume = _events(ex, "resume")[0]
        self.assertNotEqual(resume["trigger"], "threat_cleared")
        self.assertEqual(resume["ceiling_ticks"], GUIDED_CEILING_TICKS)
        self.assertIn("BACKSTOP", resume["reason"])
        self.assertIn("not on a cleared threat", resume["reason"])

    def test_the_ceiling_restarts_the_encounter_it_does_not_disable_avoidance(self):
        """Entry stays instantaneous, so a threat that is still there takes over again immediately
        with a freshly latched, freshly vetted point. The ceiling breaks a stuck STATE."""
        ex, sink = self._duty_cycle(GUIDED_CEILING_TICKS // 3 + 4)
        ceiling_tick = _events(ex, "resume")[0]["tick"]
        later = [e for e in _events(ex, "takeover") if e["tick"] > ceiling_tick]
        self.assertEqual(len(later), 1, "the still-present threat did not re-engage the loop")
        self.assertTrue([e for e in _events(ex, "latch") if e["tick"] > ceiling_tick],
                        "re-engaging must latch a FRESH vetted point, not inherit the dead one")
        self.assertEqual(sink.mode, MODE_GUIDED)

    def test_a_waiting_tick_reports_how_long_guided_has_held(self):
        """The instrumentation half of C1: `clear_ticks` cycling 1,2,1,2 is identical in a healthy
        encounter and a locked one. `ticks_in_guided` is the number that tells them apart."""
        ex, _sink = self._duty_cycle(20)
        pending = [e["resume_pending"] for e in _events(ex, "proceed") if "resume_pending" in e]
        self.assertEqual([p["clear_ticks"] for p in pending[:4]], [1, 2, 1, 2])   # the ambiguous one
        self.assertLess(pending[0]["ticks_in_guided"], pending[-1]["ticks_in_guided"])
        self.assertEqual(pending[-1]["ceiling_ticks"], GUIDED_CEILING_TICKS)

    def test_the_longest_encounter_ever_flown_is_nowhere_near_the_ceiling(self):
        """Sized off evidence, and the evidence is RE-DERIVED here rather than quoted: a values-gate
        checked against a prose figure is this repo's named defect (QA N3). Reads the committed
        flight logs, pairs takeover with resume, and counts INCLUSIVELY -- the same count
        `_ticks_in_guided()` reports, which is what the ceiling is compared against. Longest today:
        62 ticks (2026-08-18); a ceiling a real dodge could reach would turn a backstop into a
        control parameter."""
        import json
        windows = []
        for path in sorted((REPO_ROOT / "eval" / "results").glob("live_flight_log_*.json")):
            events = json.loads(path.read_text()).get("events") or []
            takeovers = [e["tick"] for e in events if e.get("kind") == "takeover"]
            resumes = [e["tick"] for e in events if e.get("kind") == "resume"]
            windows += [b - a + 1 for a, b in zip(takeovers, resumes)]
        if not windows:                                   # pragma: no cover -- evidence is committed
            self.skipTest("no committed flight logs to derive the longest encounter from")
        longest_flown = max(windows)
        self.assertEqual(longest_flown, 62)               # today's evidence, stated so a change shows
        self.assertGreaterEqual(GUIDED_CEILING_TICKS, 5 * longest_flown)
        ex, sink = _exec()
        ex.step(_drone(30.0, 20.0, wp=3), self._mv())
        for i in range(longest_flown - 1):          # a genuine sustained encounter, threat present
            ex.step(_drone(30.0, 20.0 + 0.05 * i, wp=3), self._mv())
        for i in range(RESUME_CLEAR_TICKS):         # then it really clears
            ex.step(_drone(30.0, 25.0 + i, wp=3), AvoidanceManeuver(decision=Decision.PROCEED))
        self.assertEqual([e["trigger"] for e in _events(ex, "resume")], ["threat_cleared"])
        self.assertEqual(sink.mode, MODE_AUTO)

    def test_no_tick_ever_emits_more_than_one_mode_switch(self):
        """QA N1: the ceiling runs at the BOTTOM of `step()`, not the top.

        At the top, an expiry landing on a DIVERT tick emitted `set_mode(AUTO)` ->
        `set_mode(GUIDED)` -> `send_setpoint` inside ONE control callback. `Ros2VehicleSink.set_mode`
        is a non-blocking `call_async` whose own comment states the invariant that breaks -- "the
        executor asserts the mode exactly ONCE per takeover and once per hand-back" -- and two racing
        ModeSwitch calls in one callback is the shape that let a failed GUIDED takeover pass
        silently. Nothing pinned the placement, so moving it broke no test; this is that pin."""
        # THE case that breaks it: the expiry must land ON a DIVERT tick, where the old ordering
        # resumed and then immediately took over again. With a 1-in-3 duty cycle the DIVERT ticks
        # are 1, 4, 7 ... so a ceiling of 10 expires on one; the default 310 does too (310 = 3k+1),
        # and both are exercised here so neither placement can pass on a lucky phase.
        for ceiling in (10, GUIDED_CEILING_TICKS):
            with self.subTest(ceiling=ceiling):
                self.assertEqual(ceiling % 3, 1, "this stream must expire ON a DIVERT tick")
                ex, sink = _exec(guided_ceiling_ticks=ceiling)
                per_tick = []
                for i in range(ceiling // 3 + 4):
                    for mv in (self._mv(), AvoidanceManeuver(decision=Decision.PROCEED),
                               AvoidanceManeuver(decision=Decision.PROCEED)):
                        before = len(sink.mode_history)
                        ex.step(_drone(30.0, 20.0 + 0.01 * i, wp=3), mv)
                        per_tick.append(len(sink.mode_history) - before)
                self.assertEqual(max(per_tick), 1, "a tick issued more than one mode switch")
                # And the hand-back really happened, one tick's decision at a time: resume on the
                # ceiling tick, re-takeover on the NEXT DIVERT tick, with a FRESH latch.
                switches = [(e["kind"], e["tick"]) for e in ex.event_log
                            if e["kind"] in ("takeover", "resume")]
                self.assertEqual(switches[:3], [("takeover", 1), ("resume", ceiling),
                                                ("takeover", ceiling + 3)])
                self.assertIn(ceiling + 3, [e["tick"] for e in _events(ex, "latch")])

    def test_the_ceiling_is_configurable_and_measured_from_the_takeover_tick(self):
        ex, sink = _exec(guided_ceiling_ticks=10)
        for i in range(6):                     # AUTO ticks first: they must not count toward it
            ex.step(_drone(30.0, 10.0 + i, wp=3), AvoidanceManeuver(decision=Decision.PROCEED))
        self.assertEqual(_events(ex, "resume"), [])
        ex.step(_drone(30.0, 20.0, wp=3), self._mv())          # takeover here = ticks_in_guided 1
        for i in range(9):
            ex.step(_drone(30.0, 21.0, wp=3), self._mv())
        self.assertEqual([e["trigger"] for e in _events(ex, "resume")], ["guided_ceiling"])
        self.assertEqual(_events(ex, "resume")[0]["ticks_in_guided"], 10)


class TestExecutorParamsAreInTheArtifact(unittest.TestCase):
    """QA F-condition: the executor's knobs live in module constants (adjudicated correct -- the
    policy is pure and stateless and these are executor concepts), ON CONDITION that the flown value
    is readable in the artifact even on a flight with no encounter, where no resume event exists to
    carry it."""

    def _log(self, *decisions):
        ex, _sink = _exec()
        for i, d in enumerate(decisions):
            ex.step(_drone(30.0, 10.0 + i, wp=3), AvoidanceManeuver(decision=Decision.PROCEED)
                    if d == "p" else _divert((30.0, 30.0, 15.0)))
        ex.finalize()
        return ex.flight_log("t", seed=0, cell_size_m=2.5)

    def test_an_encounter_free_flight_still_records_what_it_flew(self):
        params = self._log("p", "p", "p")["executor_params"]
        self.assertEqual(params["resume_clear_ticks"], RESUME_CLEAR_TICKS)
        self.assertEqual(params["guided_ceiling_ticks"], GUIDED_CEILING_TICKS)
        self.assertEqual(params["relatch_threshold_m"], RELATCH_THRESHOLD_M)

    def test_it_reports_the_INSTANCE_value_not_the_module_default(self):
        """A log that printed the module constant while the flight flew an override would be worse
        than no block at all."""
        ex, _sink = _exec(resume_clear_ticks=2, guided_ceiling_ticks=40)
        ex.step(_drone(30.0, 10.0), AvoidanceManeuver(decision=Decision.PROCEED))
        ex.finalize()
        params = ex.flight_log("t", seed=0, cell_size_m=2.5)["executor_params"]
        self.assertEqual((params["resume_clear_ticks"], params["guided_ceiling_ticks"]), (2, 40))

    def test_the_long_standing_top_level_keys_are_untouched(self):
        log = self._log("p")
        for key in ("scenario", "seed", "cell_size_m", "swath_half_width_m", "flown_path_enu",
                    "coverage_ledger", "requeue_events", "events"):
            self.assertIn(key, log)


if __name__ == "__main__":
    unittest.main()
