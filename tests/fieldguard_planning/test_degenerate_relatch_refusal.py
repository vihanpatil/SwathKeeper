"""R3: the degenerate-range flag and the executor's re-latch refusal (ADR-013 amendment 12).

WHAT R3 IS
----------
Two halves, deliberately split across the two modules so `decide` stays pure:

  POLICY   `avoidance_policy.decide_multi` publishes `debug["range_degenerate"]` on EVERY
           threat-branch maneuver -- True when the trigger range is below
           `PolicyParams.degenerate_range_m` (1.0 m). It still returns its best-effort dodge:
           refusing to decide would mean not dodging a bird we are on top of.

  EXECUTOR `avoidance_executor._handle_divert` refuses to RE-LATCH on a tick carrying that flag.
           Below a metre the away-vector's direction is noise (a position error >= the range flips
           the commanded bearing through 180 deg), so a setpoint jump past `RELATCH_THRESHOLD_M` on
           such a tick is the estimator moving, not the threat. The flown 2026-08-23 encounter
           re-latched on a 20.9 m jump produced by a bird that never moved
           (`test_degenerate_range_avoidance.py`, S4). The refusal keeps flying the already-vetted
           latched point and is logged as `latch_action: "relatch_refused_degenerate"`.

WHY THE FLAG IS COMPUTED FROM THE *LOGGED* RANGE
The maneuver debug carries `trigger_range_m` rounded to 3 dp. The flag is derived from that same
rounded number, so the flight-log consistency check the safety gate runs --
`range_degenerate == (trigger_range_m < degenerate_range_m)` -- holds by construction at the
boundary instead of holding "usually". A flag computed from a number nobody can see is a flag
nobody can audit. `TestFlagIsDerivedFromTheLoggedNumber` is the mutation-proof for this.

SCOPE, STATED SO IT IS A DEFERRAL AND NOT A BLIND SPOT
  * A FIRST latch at degenerate range is still permitted (am. 12 scoped R3 to re-latch; refusing
    the first latch would mean not dodging at all). Pinned in `test_a_first_latch_at_degenerate_
    range_is_still_permitted`.
  * R3 does not change the dodge DIRECTION, so it does not fix S1 (CPA 0.0518 m). R4 -- the
    reversal-preferring candidate order -- is open, and `test_R4_is_still_open` is its tripwire.
  * The latched point's swept path is not re-vetted as ownship moves; the executor re-vets the
    POINT (`is_safe_3d`), not the segment. Unchanged by R3, and unchanged by R2.

stdlib unittest only. Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.avoidance_executor import (  # noqa: E402
    AvoidanceExecutor, RELATCH_THRESHOLD_M, SimulatedVehicleSink,
)
from fieldguard_planning.avoidance_policy import (  # noqa: E402
    _CANDIDATE_ANGLES_DEG, AvoidancePolicy, PolicyParams,
)
from fieldguard_planning.avoidance_types import (  # noqa: E402
    AvoidanceManeuver, Decision, Detection, DroneState,
)
from fieldguard_planning.coverage import load_field_polygon  # noqa: E402
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402

from test_degenerate_range_avoidance import (  # noqa: E402
    CRUISE_ALT_M, DEMO_BIRD_ENU, ENCOUNTER, SETPOINT_329, TICK_329,
)

REFUSED = "relatch_refused_degenerate"


def _drone(pos, hdg=math.pi / 2.0, wp=6):
    return DroneState(position_enu=pos, heading_rad=hdg, current_wp_index=wp)


def _bird(pos, fid=1, tid="demo_bird_0"):
    return Detection(position_enu=pos, frame_id=fid, track_id=tid)


def _maneuver(setpoint, *, range_degenerate=None, tid="bird_0", fid=1):
    """A DIVERT maneuver as the executor sees it. `range_degenerate=None` builds a maneuver with NO
    flag at all -- the pre-R3 shape, which must keep pre-R3 behaviour."""
    debug = {} if range_degenerate is None else {"range_degenerate": range_degenerate}
    return AvoidanceManeuver(
        decision=Decision.DIVERT, setpoint_enu=setpoint, reason="test divert", debug=debug,
        triggering_detection=Detection((setpoint[0] + 3.0, setpoint[1], setpoint[2]),
                                       frame_id=fid, track_id=tid))


def _exec(cells=None):
    geo = GeofenceMap.from_file()
    sink = SimulatedVehicleSink(initial_wp_index=6)
    ex = AvoidanceExecutor(geo, cells or [], sink, swath_half_width_m=3.0, alt_bounds=(2.0, 30.0))
    return ex, sink


def _kinds(ex, kind):
    return [e for e in ex.event_log if e["kind"] == kind]


def _latch_actions(ex):
    return [e["latch_action"] for e in ex.event_log if e["kind"] in ("maneuver", "gate_reject")]


# ==================================================================================================
class TestPolicyPublishesTheFlag(unittest.TestCase):
    """The flag is a CONTRACT, read by the executor and by the flight-log gate. Its absence must be
    a defect, never a quiet 'no' -- so it is asserted present on every threat-branch maneuver,
    whatever the decision."""

    @classmethod
    def setUpClass(cls):
        cls.geo = GeofenceMap.from_file()
        cls.pol = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=CRUISE_ALT_M)

    def _decide_at_range(self, d_m, **overrides):
        """Bird `d_m` due east of the drone at cruise, in open field -> trigger_range_m == d_m."""
        drone_xy = (30.0, 30.0)
        return self.pol.decide(_bird((drone_xy[0] + d_m, drone_xy[1], CRUISE_ALT_M)),
                               _drone((*drone_xy, CRUISE_ALT_M)), self.geo, **overrides)

    def test_divert_carries_the_flag_true_below_the_threshold(self):
        m = self._decide_at_range(0.052)
        self.assertIs(m.decision, Decision.DIVERT)
        self.assertEqual(m.debug["trigger_range_m"], 0.052)
        self.assertTrue(m.debug["range_degenerate"])

    def test_divert_carries_the_flag_false_above_the_threshold(self):
        m = self._decide_at_range(9.272)
        self.assertIs(m.decision, Decision.DIVERT)
        self.assertEqual(m.debug["trigger_range_m"], 9.272)
        self.assertFalse(m.debug["range_degenerate"])

    def test_a_boxed_in_HOLD_still_carries_the_flag(self):
        """HOLD is a threat-branch decision too. If the flag only rode on DIVERT, a log full of
        HOLDs would look like a log with no degenerate ticks."""
        pol = AvoidancePolicy(field_polygon=[(28.0, 28.0), (32.0, 28.0), (32.0, 32.0), (28.0, 32.0)])
        m = pol.decide(_bird((30.05, 30.0, CRUISE_ALT_M)), _drone((30.0, 30.0, CRUISE_ALT_M)),
                       self.geo)
        self.assertIs(m.decision, Decision.HOLD)
        self.assertTrue(m.debug["range_degenerate"])
        self.assertEqual(m.debug["trigger_range_m"], 0.05)

    def test_PROCEED_carries_neither_range_nor_flag(self):
        """No threat -> no trigger range -> no flag. The pair travels together or not at all; a
        `range_degenerate` without a `trigger_range_m` would be unauditable."""
        far = self._decide_at_range(30.0)                      # outside the 12 m cylinder
        self.assertIs(far.decision, Decision.PROCEED)
        self.assertNotIn("range_degenerate", far.debug)
        self.assertNotIn("trigger_range_m", far.debug)

        none = self.pol.decide(None, _drone((30.0, 30.0, CRUISE_ALT_M)), self.geo)
        self.assertIs(none.decision, Decision.PROCEED)
        self.assertNotIn("range_degenerate", none.debug)

    def test_a_stale_detection_produces_no_flag_because_it_produced_no_threat(self):
        """The staleness gate drops the detection BEFORE the threat geometry runs, so a stale bird
        0.05 m away is absent, not degenerate -- and the log says PROCEED with n_stale_dropped."""
        pol = AvoidancePolicy(max_detection_age_s=0.5)
        det = Detection((30.05, 30.0, CRUISE_ALT_M), frame_id=1, track_id="old", stamp_s=100.0)
        m = pol.decide(det, _drone((30.0, 30.0, CRUISE_ALT_M)), self.geo, now_s=101.0)
        self.assertIs(m.decision, Decision.PROCEED)
        self.assertNotIn("range_degenerate", m.debug)
        self.assertEqual(m.debug["n_stale_dropped"], 1)

    def test_the_threshold_is_a_param_and_travels_in_the_logged_params(self):
        """One home (`PolicyParams.degenerate_range_m`), per-call overridable like every other knob,
        and always written into `debug["params"]` so a log can be replayed against the threshold it
        was flown under rather than against today's."""
        self.assertEqual(PolicyParams().degenerate_range_m, 1.0)
        default = self._decide_at_range(2.0)
        self.assertFalse(default.debug["range_degenerate"])
        self.assertEqual(default.debug["params"]["degenerate_range_m"], 1.0)

        widened = self._decide_at_range(2.0, degenerate_range_m=5.0)
        self.assertTrue(widened.debug["range_degenerate"])
        self.assertEqual(widened.debug["params"]["degenerate_range_m"], 5.0)

        disabled = self._decide_at_range(0.052, degenerate_range_m=0.0)
        self.assertFalse(disabled.debug["range_degenerate"],
                         "degenerate_range_m=0.0 must disable the flag entirely (as-flown replay)")

    def test_the_flown_degenerate_tick_is_flagged_and_its_neighbours_are_not(self):
        """The real encounter: exactly one of the 19 ticks is degenerate (0.052 m); its neighbours
        at 1.280 m and 1.192 m are not. If a change starts flagging half the encounter, the number
        moved -- and every re-latch of that encounter would then be refused."""
        pol = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=CRUISE_ALT_M)
        flagged = []
        for tick, pos, rng, _, _, _ in ENCOUNTER:
            m = pol.decide(_bird(DEMO_BIRD_ENU), _drone(pos), self.geo)
            self.assertEqual(m.debug["trigger_range_m"], rng)
            if m.debug["range_degenerate"]:
                flagged.append(tick)
        self.assertEqual(flagged, [TICK_329[0]])


# ==================================================================================================
class TestFlagIsDerivedFromTheLoggedNumber(unittest.TestCase):
    """The by-construction property the safety gate depends on: for EVERY maneuver,
    `range_degenerate == (trigger_range_m < degenerate_range_m)` using the values as LOGGED.

    Mutation-proof: computing the flag from the unrounded range instead would pass a coarse test and
    fail on the ~0.05 % of ranges that round across the threshold -- exactly the ticks a gate would
    then call a policy/executor version mismatch."""

    @classmethod
    def setUpClass(cls):
        cls.geo = GeofenceMap.from_file()
        cls.pol = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=CRUISE_ALT_M)

    def _decide_at_range(self, d_m):
        return self.pol.decide(_bird((30.0 + d_m, 30.0, CRUISE_ALT_M)),
                               _drone((30.0, 30.0, CRUISE_ALT_M)), self.geo)

    def test_a_range_that_rounds_UP_across_the_threshold_is_not_degenerate(self):
        """0.99962 m is below 1.0 m but LOGS as 1.0. The flag follows the log, not the float."""
        m = self._decide_at_range(0.99962)
        self.assertEqual(m.debug["trigger_range_m"], 1.0)
        self.assertFalse(m.debug["range_degenerate"])

    def test_a_range_just_under_the_threshold_after_rounding_is_degenerate(self):
        m = self._decide_at_range(0.99942)
        self.assertEqual(m.debug["trigger_range_m"], 0.999)
        self.assertTrue(m.debug["range_degenerate"])

    def test_exactly_at_the_threshold_is_not_degenerate(self):
        """Strictly `<`: 1.000 m is the first non-degenerate range, matching the gate's own
        comparison. A boundary owned by two different operators is a boundary that drifts."""
        m = self._decide_at_range(1.0)
        self.assertEqual(m.debug["trigger_range_m"], 1.0)
        self.assertFalse(m.debug["range_degenerate"])

    def test_the_identity_holds_across_the_whole_boundary_neighbourhood(self):
        """201 ranges straddling the threshold at 0.1 mm steps -- the region where rounding and the
        comparison can disagree -- plus a coarse sweep out to 12 m."""
        bar = PolicyParams().degenerate_range_m
        n_true = n_false = 0
        ranges = [0.99 + 0.0001 * k for k in range(201)]
        ranges += [0.05 * k for k in range(1, 240)]
        for d in ranges:
            m = self._decide_at_range(d)
            with self.subTest(d=d):
                self.assertEqual(m.debug["range_degenerate"], m.debug["trigger_range_m"] < bar)
            n_true += m.debug["range_degenerate"]
            n_false += not m.debug["range_degenerate"]
        self.assertGreater(n_true, 20, "the sweep never produced a degenerate tick")
        self.assertGreater(n_false, 20, "the sweep never produced a non-degenerate tick")


# ==================================================================================================
class TestExecutorRefusesTheRelatch(unittest.TestCase):
    """The behaviour change itself, driven with hand-built maneuvers so the executor is tested
    independently of the policy (the flag is a contract, not an implementation detail)."""

    def setUp(self):
        self.first = (30.0, 30.0, 15.0)
        self.jumped = (30.0, 50.0, 15.0)          # 20 m away -- the flown 20.9 m jump, rounded off
        self.assertGreater(math.dist(self.jumped, self.first), RELATCH_THRESHOLD_M)

    def test_a_degenerate_tick_keeps_the_latched_point_and_says_so(self):
        ex, sink = _exec()
        ex.step(_drone((30.0, 20.0, 15.0)), _maneuver(self.first, range_degenerate=False))
        ex.step(_drone((30.0, 22.0, 15.0)), _maneuver(self.jumped, range_degenerate=True))
        self.assertEqual(sink.setpoints_sent, [self.first, self.first])
        self.assertNotIn(self.jumped, sink.setpoints_sent)
        self.assertEqual(_kinds(ex, "relatch"), [], "R3 must not emit a latch event on refusal")
        self.assertEqual(_latch_actions(ex), ["latch", REFUSED])
        self.assertEqual(ex._latched_setpoint, self.first)
        # the refused point is still on the record -- refusing is not hiding
        self.assertEqual(_kinds(ex, "maneuver")[1]["policy_setpoint_enu"], self.jumped)

    def test_an_ordinary_recommand_on_a_degenerate_tick_is_not_relabelled(self):
        """The label means 'a re-latch was refused', not 'the tick was degenerate'. Only a jump PAST
        the threshold can produce it, or the count of refusals stops meaning anything."""
        ex, sink = _exec()
        drift = (30.4, 30.3, 15.0)                 # 0.5 m -- inside the threshold
        ex.step(_drone((30.0, 20.0, 15.0)), _maneuver(self.first, range_degenerate=False))
        ex.step(_drone((30.0, 22.0, 15.0)), _maneuver(drift, range_degenerate=True))
        self.assertEqual(_latch_actions(ex), ["latch", "recommand_latched"])
        self.assertEqual(sink.setpoints_sent, [self.first, self.first])

    def test_a_non_degenerate_jump_still_relatches(self):
        """The escape hatch survives: R3 removes exactly one case, not the mechanism. A genuinely
        moving threat at usable range must still move the dodge."""
        ex, sink = _exec()
        ex.step(_drone((30.0, 20.0, 15.0)), _maneuver(self.first, range_degenerate=False))
        ex.step(_drone((30.0, 22.0, 15.0)), _maneuver(self.jumped, range_degenerate=False))
        self.assertEqual(sink.setpoints_sent, [self.first, self.jumped])
        self.assertEqual(len(_kinds(ex, "relatch")), 1)
        self.assertEqual(_latch_actions(ex), ["latch", "relatch"])
        self.assertEqual(ex._latched_setpoint, self.jumped)

    def test_a_maneuver_with_no_flag_at_all_behaves_exactly_as_before_R3(self):
        """Fail OPEN on a missing flag, deliberately: a maneuver built by a pre-R3 caller (or by any
        test double) must keep its historical behaviour rather than silently acquiring a refusal.
        The policy always writes the flag, so a missing one means 'not from the policy'."""
        ex, sink = _exec()
        ex.step(_drone((30.0, 20.0, 15.0)), _maneuver(self.first))
        ex.step(_drone((30.0, 22.0, 15.0)), _maneuver(self.jumped))
        self.assertEqual(sink.setpoints_sent, [self.first, self.jumped])
        self.assertEqual(_latch_actions(ex), ["latch", "relatch"])

    def test_a_first_latch_at_degenerate_range_is_still_permitted(self):
        """DEFERRED BY DESIGN (am. 12 scoped R3 to re-latch): with no latch yet, a degenerate tick
        still latches -- the alternative is not dodging a bird we are on top of. Pinned so the
        deferral is a decision on the record, not an oversight."""
        ex, sink = _exec()
        ex.step(_drone((30.0, 20.0, 15.0)), _maneuver(self.first, range_degenerate=True))
        self.assertEqual(sink.setpoints_sent, [self.first])
        self.assertEqual(_latch_actions(ex), ["latch"])
        self.assertEqual(len(_kinds(ex, "latch")), 1)

    def test_refusal_does_not_weaken_the_3d_backstop(self):
        """Guarantee 1 is untouched: the point a refusal keeps flying is re-vetted on the tick it is
        re-commanded, like every other. Here the latched point has become unsafe (the vehicle is
        descending through the canopy band), so the refusing tick must still gate-reject, drop the
        dead latch and HOLD -- and must NOT fall through to the policy's noise-driven point."""
        ex, sink = _exec()
        over_tree = (15.0, 5.0, 15.0)      # dead over tree_row0_0: safe at cruise, unsafe in-band
        noise = (60.0, 5.0, 15.0)          # >> RELATCH_THRESHOLD_M from the latch
        self.assertTrue(ex.geofence.is_safe_3d(over_tree, 1.0, (2.0, 30.0)))
        ex.step(_drone((21.0, 5.0, 15.0)), _maneuver(over_tree, range_degenerate=False))
        self.assertEqual(sink.setpoints_sent, [over_tree])
        # the latched point is now unsafe (stand in for a descent into the canopy band)
        ex.vertical_margin_m = 20.0        # tree volume now tops out at 23.8 m, above the setpoint
        self.assertFalse(ex.geofence.is_safe_3d(over_tree, 20.0, (2.0, 30.0)))
        ex.step(_drone((20.0, 5.0, 15.0)), _maneuver(noise, range_degenerate=True))
        self.assertEqual(len(_kinds(ex, "gate_reject")), 1)
        self.assertEqual(_kinds(ex, "gate_reject")[0]["latch_action"], REFUSED)
        self.assertEqual(len(_kinds(ex, "hold")), 1)
        self.assertIsNone(ex._latched_setpoint, "a dead latch must be dropped, refusal or not")
        self.assertNotIn(noise, sink.setpoints_sent, "refusal must not fall through to the noise")
        self.assertEqual(sink.setpoints_sent[-1], (20.0, 5.0, 15.0), "HOLD hovers where it is")

    def test_a_refusal_whose_latch_has_drifted_onto_the_bird_HOLDS_instead(self):
        """QA ROUND 2, FINDING 3, the probe end to end through the REAL policy, executor and
        geofence -- not a hand-built maneuver, because the defect was that every hand-built check
        passed.

        Tick 1: bird (45,30,15), drone (40,30,15) -> DIVERT, latch (30,30,15), 15 m clear of the
        bird. Tick 2: the bird has flown to (29,30,15) and the drone is on top of it at (29.4,30,15)
        -- trigger range 0.400 m, `range_degenerate` True. The policy's fresh setpoint (39.4,30,15)
        is 10.400 m clear, a 9.400 m jump, so R3 refuses it. The refusal then RE-COMMANDED the
        latch, which the bird had walked to within **1.000 m** of, versus the policy's own 3.00 m
        bar -- `verdict: accepted`, no gate_reject, and the only backstop (is_safe_3d) cannot see a
        bird at all. The 1.000 m point is now REFUSED and never commanded.

        What the refusal is NOT is a safer alternative -- see
        `TestAHoldHonoursNoClearanceBarAndSaysSo`, which measures this same tick's HOLD at 0.400 m,
        nearer the bird than the point that was refused. R4 owns that."""
        pol = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=15.0)
        ex, sink = _exec()
        geo = ex.geofence

        d1, b1 = _drone((40.0, 30.0, 15.0)), _bird((45.0, 30.0, 15.0), tid="bird_0")
        m1 = pol.decide(b1, d1, geo)
        self.assertEqual(m1.setpoint_enu, (30.0, 30.0, 15.0), "fixture drift: tick 1 latch moved")
        ex.step(d1, m1)

        d2, b2 = _drone((29.4, 30.0, 15.0)), _bird((29.0, 30.0, 15.0), fid=2, tid="bird_0")
        m2 = pol.decide(b2, d2, geo)
        self.assertTrue(m2.debug["range_degenerate"])
        self.assertEqual(m2.debug["trigger_range_m"], 0.4)
        self.assertGreater(math.dist(m2.setpoint_enu, (30.0, 30.0, 15.0)), RELATCH_THRESHOLD_M)
        ex.step(d2, m2)

        # THE assertion: the 1.000 m point is never commanded, by any route.
        self.assertNotIn((30.0, 30.0, 15.0), sink.setpoints_sent[1:])
        self.assertEqual(sink.setpoints_sent, [(30.0, 30.0, 15.0), (29.4, 30.0, 15.0)])
        reject = _kinds(ex, "gate_reject")
        self.assertEqual(len(reject), 1)
        self.assertEqual(reject[0]["latch_action"], REFUSED)   # R3 still visible, not swallowed
        self.assertEqual(reject[0]["bird_clearance_m"], 1.0)
        self.assertEqual(reject[0]["bird_track_id"], "bird_0")
        self.assertIn("min_bird_clearance_m", reject[0]["reason"])
        self.assertEqual(len(_kinds(ex, "hold")), 1)
        self.assertIsNone(ex._latched_setpoint, "a latch the birds have overtaken is dead")

    def test_the_reject_reason_does_not_present_the_HOLD_as_the_safer_option(self):
        """QA ROUND 3, FINDING 2 (b). The reason string read `... falling back to HOLD`, which in
        the branch that produced it is backwards: the executor has no escape geometry, so it
        commands ZERO displacement, and at degenerate range that is inside the bar too. The string
        is the thing an operator reads in the artifact, so it has to say which of those it is."""
        ex, _ = _exec()
        m = _maneuver(self.first, range_degenerate=False)
        m.debug["params"] = {"min_bird_clearance_m": 3.0}
        m.debug["threat_ids"] = ["bird_0"]
        m.debug["threat_positions_enu"] = [[31.0, 30.0, 15.0]]
        ex.step(_drone((30.0, 20.0, 15.0)), m)
        reason = _kinds(ex, "gate_reject")[0]["reason"]
        self.assertNotIn("falling back to HOLD", reason)
        self.assertIn("REFUSED", reason)
        self.assertIn("zero displacement", reason)
        self.assertIn("honours NO clearance bar", reason)
        self.assertIn("R4", reason)

    def test_the_bird_check_covers_every_threat_the_decision_names_not_just_the_trigger(self):
        """A dodge away from bird A must not be re-commanded into bird B. The executor reads
        `debug["threat_positions_enu"]` -- every in-cylinder threat, written by the policy beside
        `threat_ids` -- so the nearest bird to the SETPOINT decides, not the nearest to the drone."""
        ex, sink = _exec()
        m = _maneuver(self.first, range_degenerate=False)
        m.debug["params"] = {"min_bird_clearance_m": 3.0}
        m.debug["threat_ids"] = ["far_trigger", "bird_on_the_setpoint"]
        m.debug["threat_positions_enu"] = [[45.0, 30.0, 15.0], [31.0, 30.0, 15.0]]
        ex.step(_drone((30.0, 20.0, 15.0)), m)
        self.assertEqual(sink.setpoints_sent, [(30.0, 20.0, 15.0)], "HOLD hovers where it is")
        self.assertEqual(_kinds(ex, "gate_reject")[0]["bird_track_id"], "bird_on_the_setpoint")
        self.assertEqual(_kinds(ex, "gate_reject")[0]["bird_clearance_m"], 1.0)

    def test_a_maneuver_with_no_logged_params_keeps_pre_round2_behaviour(self):
        """Fail OPEN on missing data, the same doctrine as the missing `range_degenerate` flag: the
        bar has ONE home (`PolicyParams`, logged into `debug["params"]` per decision), so a maneuver
        that carries no params did not come from this policy and the executor has no bar to check
        against. Every real maneuver carries them -- pinned by the end-to-end probe above."""
        ex, sink = _exec()
        m = _maneuver(self.first, range_degenerate=False)
        m.triggering_detection = Detection((30.5, 30.0, 15.0), frame_id=1, track_id="on_top")
        self.assertNotIn("params", m.debug)
        ex.step(_drone((30.0, 20.0, 15.0)), m)
        self.assertEqual(sink.setpoints_sent, [self.first])
        self.assertEqual(_kinds(ex, "gate_reject"), [])

    def test_the_refusal_does_not_survive_the_encounter(self):
        """Latch lifecycle is unchanged: resume clears the latch, so the next encounter latches its
        own point even if its first tick is degenerate."""
        ex, sink = _exec()
        second = (30.5, 30.0, 15.0)     # within the threshold of `first`: only a CLEARED latch flies it
        ex.step(_drone((30.0, 20.0, 15.0)), _maneuver(self.first, range_degenerate=False))
        ex.step(_drone((30.0, 22.0, 15.0)), _maneuver(self.jumped, range_degenerate=True))
        ex.step(_drone((30.0, 24.0, 15.0)), AvoidanceManeuver(decision=Decision.PROCEED))
        ex.step(_drone((30.0, 26.0, 15.0)), _maneuver(second, range_degenerate=True, fid=9))
        self.assertEqual(sink.setpoints_sent, [self.first, self.first, second])
        self.assertEqual(_latch_actions(ex), ["latch", REFUSED, "latch"])
        self.assertEqual(len(_kinds(ex, "takeover")), 2)

    def test_refusals_are_countable_from_the_log(self):
        """R3 doing its job must be VISIBLE (a non-gating report in the flight-log checker), so the
        label has to be exact and countable -- not inferred from a missing `relatch` event."""
        ex, _ = _exec()
        ex.step(_drone((30.0, 20.0, 15.0)), _maneuver(self.first, range_degenerate=False))
        for i in range(3):
            ex.step(_drone((30.0, 22.0 + i, 15.0)), _maneuver(self.jumped, range_degenerate=True))
        self.assertEqual(sum(a == REFUSED for a in _latch_actions(ex)), 3)
        self.assertEqual(_kinds(ex, "relatch"), [])
        self.assertEqual(len(ex.flown_path), 4, "every tick still records exactly one position")


# ==================================================================================================
class TestAHoldHonoursNoClearanceBarAndSaysSo(unittest.TestCase):
    """QA ROUND 3, FINDING 2. The round-2 fix vets the DIVERT candidate and then falls through to a
    HOLD that vets nothing -- and the docstring claimed otherwise ("Every point this module is about
    to command is re-vetted ... against BOTH halves").

    The honest statement, and the one the code now makes: a HOLD commands
    `drone_state.position_enu`, i.e. ZERO displacement. It chooses no point, so there is nothing to
    vet and no bar it can honour. In the R3-refusal branch that is structural, not incidental: the
    branch is only entered when `range_degenerate` is True, so the vehicle is within
    `degenerate_range_m` (1.0 m) of the trigger bird BY CONSTRUCTION and the hold is inside the
    3.00 m bird bar every single time. Measured by exhaustion: 400 random encounters x 25 ticks
    through the real policy + executor + geofence gave 22 refusals and 41 hold ticks inside the bar,
    closest 0.288 m.

    So the fix is measurement and wording, not a new control law. Escape geometry -- commanding a
    point that IS outside the bar -- is R4, open and deliberately uncut. These tests pin that the
    number reaches the artifact and that no string in the executor claims the HOLD is safe."""

    def test_THE_PROBE_the_hold_is_NEARER_the_bird_than_the_point_the_refusal_declined(self):
        """The finding's own geometry, end to end through the real policy/executor/geofence. The
        refusal rejects a latch 1.000 m from the bird -- and then commands a hold 0.400 m from the
        same bird, 2.5x worse. Both numbers are now in the log, on the events that made them."""
        pol = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=15.0)
        ex, sink = _exec()
        geo = ex.geofence
        d1, b1 = _drone((40.0, 30.0, 15.0)), _bird((45.0, 30.0, 15.0), tid="bird_0")
        ex.step(d1, pol.decide(b1, d1, geo))
        d2, b2 = _drone((29.4, 30.0, 15.0)), _bird((29.0, 30.0, 15.0), fid=2, tid="bird_0")
        ex.step(d2, pol.decide(b2, d2, geo))

        reject, hold = _kinds(ex, "gate_reject")[0], _kinds(ex, "hold")[0]
        self.assertEqual(reject["bird_clearance_m"], 1.0)      # the point declined
        self.assertEqual(hold["bird_clearance_m"], 0.4)        # ...and what was commanded instead
        self.assertEqual(hold["bird_track_id"], "bird_0")
        self.assertEqual(hold["min_bird_clearance_m"], PolicyParams().min_bird_clearance_m)
        self.assertLess(hold["bird_clearance_m"], reject["bird_clearance_m"])
        self.assertLess(hold["bird_clearance_m"], PolicyParams().min_bird_clearance_m)
        # The vehicle really was commanded to stand still at its own position.
        self.assertEqual(sink.setpoints_sent[-1], d2.position_enu)

    def test_a_policy_HOLD_records_its_clearance_too_not_only_the_reject_path(self):
        """Boxed-in HOLDs come straight from the policy and never touch `_handle_divert`, so a
        clearance logged only on the reject path would miss them -- and they are exactly the ticks
        where the vehicle is closest to something."""
        ex, _ = _exec()
        m = AvoidanceManeuver(
            decision=Decision.HOLD, reason="boxed in",
            debug={"threat_ids": ["bird_0"], "threat_positions_enu": [[30.0, 22.0, 15.0]],
                   "params": {"min_bird_clearance_m": 3.0}},
            triggering_detection=Detection((30.0, 22.0, 15.0), frame_id=1, track_id="bird_0"))
        ex.step(_drone((30.0, 20.0, 15.0)), m)
        self.assertEqual(_kinds(ex, "hold")[0]["bird_clearance_m"], 2.0)
        self.assertEqual(_kinds(ex, "hold")[0]["min_bird_clearance_m"], 3.0)

    def test_a_hold_naming_no_threat_records_None_and_not_a_number(self):
        """Absence of a threat is not a clearance of zero, and it is not a clearance of infinity
        either. `None` is the honest entry; the gate's note skips holds that have one."""
        ex, _ = _exec()
        ex.step(_drone((30.0, 20.0, 15.0)),
                AvoidanceManeuver(decision=Decision.HOLD, reason="no threat named"))
        self.assertIsNone(_kinds(ex, "hold")[0]["bird_clearance_m"])
        self.assertIsNone(_kinds(ex, "hold")[0]["bird_track_id"])
        self.assertIsNone(_kinds(ex, "hold")[0]["min_bird_clearance_m"])

    def test_the_clearance_is_measured_against_EVERY_threat_the_decision_names(self):
        """Same rule as the divert backstop: the nearest bird to the point being commanded decides,
        not the one that triggered the decision."""
        ex, _ = _exec()
        m = AvoidanceManeuver(
            decision=Decision.HOLD, reason="boxed in",
            debug={"threat_ids": ["trigger", "the_close_one"],
                   "threat_positions_enu": [[30.0, 12.0, 15.0], [30.0, 20.5, 15.0]]},
            triggering_detection=Detection((30.0, 12.0, 15.0), frame_id=1, track_id="trigger"))
        ex.step(_drone((30.0, 20.0, 15.0)), m)
        self.assertEqual(_kinds(ex, "hold")[0]["bird_clearance_m"], 0.5)
        self.assertEqual(_kinds(ex, "hold")[0]["bird_track_id"], "the_close_one")

    def test_the_module_docstring_states_the_guarantee_at_its_TRUE_scope(self):
        """The overclaim was in prose, so the pin is on prose. Guarantee 1 covers commanded
        DISPLACEMENT; the HOLD carve-out and R4's ownership of escape geometry are stated, not
        implied. A future edit that quietly restores "every point ... is re-vetted" fails here."""
        import fieldguard_planning.avoidance_executor as mod
        doc = mod.__doc__
        self.assertIn("Never fly an unvetted DISPLACEMENT", doc)
        self.assertIn("A HOLD IS EXEMPT, BY CONSTRUCTION", doc)
        self.assertIn("R4, open", doc)
        self.assertNotIn("Never fly an unvetted setpoint", doc)


# ==================================================================================================
class TestTheFlownEncounterUnderTheNewControlLaw(unittest.TestCase):
    """End to end on the real thing: the 19 flown ticks replayed through the REAL policy and the
    REAL executor, first reproducing the flight and then showing exactly what R2+R3 change.

    The drone positions are the flown ones -- the vehicle's response to a different dodge cannot be
    replayed offline (no dynamics model, ADR-013 am. 12 "not tested, stated plainly"), so this
    measures the DECISIONS, not the trajectory. That is precisely the half R2/R3 touch."""

    @classmethod
    def setUpClass(cls):
        cls.geo = GeofenceMap.from_file()

    def _replay(self, **overrides):
        pol = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=CRUISE_ALT_M,
                              **overrides)
        ex, sink = _exec()
        for _, pos, _, _, _, _ in ENCOUNTER:
            drone = _drone(pos)
            ex.step(drone, pol.decide(_bird(DEMO_BIRD_ENU), drone, self.geo))
        return ex, sink

    def test_as_flown_params_reproduce_the_flown_latch_column_exactly(self):
        """Validates the harness before it is used to claim a delta: at the as-flown params the
        replay reproduces all 19 `latch_action` values from the flight log, including the 20.9 m
        re-latch on the degenerate tick."""
        ex, _ = self._replay(lateral_tree_margin_m=0.0, degenerate_range_m=0.0)
        self.assertEqual(_latch_actions(ex), [row[5] for row in ENCOUNTER])
        self.assertEqual(len(_kinds(ex, "relatch")), 7)

    def test_todays_params_refuse_the_20_9_metre_relatch_on_the_degenerate_tick(self):
        """THE R3 headline. Same 19 ticks, today's defaults: the tick that re-latched onto a 20.9 m
        setpoint jump -- produced by a static bird the vehicle had just crossed -- now refuses, and
        keeps flying the point that was already vetted."""
        ex, sink = self._replay()
        actions = _latch_actions(ex)
        idx = [i for i, row in enumerate(ENCOUNTER) if row[0] == TICK_329[0]][0]
        self.assertEqual([row[5] for row in ENCOUNTER][idx], "relatch", "fixture drift")
        self.assertEqual(actions[idx], REFUSED)
        self.assertEqual(sink.setpoints_sent[idx], sink.setpoints_sent[idx - 1],
                         "the refusing tick must re-command the point it was already flying")
        self.assertEqual(sum(a == REFUSED for a in actions), 1)

    def test_the_new_law_never_commands_the_noise_driven_setpoint(self):
        """WHAT R3 ACTUALLY BUYS, measured rather than asserted in prose: the flown setpoint of the
        degenerate tick -- computed from an away-vector of (0.758, 0.652) that a 5 cm estimate error
        could have pointed anywhere -- is never commanded. The vehicle keeps flying the point it had
        already vetted, and the encounter re-latches one tick later at 1.192 m, where the away
        vector is (0.033, 0.999) and reflects geometry again.

        Stated honestly: R3 costs the noise setpoint ONE tick of delay (0.2 s at 5 Hz), it does not
        abolish the jump. That is the whole claim -- the setpoint that was pure estimator noise
        never reaches the vehicle."""
        _, flown_sink = self._replay(lateral_tree_margin_m=0.0, degenerate_range_m=0.0)
        self.assertIn(SETPOINT_329, flown_sink.setpoints_sent,
                      "fixture drift: the as-flown replay no longer commands the flown setpoint")
        today, sink = self._replay()
        self.assertNotIn(SETPOINT_329, sink.setpoints_sent)
        idx = [i for i, row in enumerate(ENCOUNTER) if row[0] == TICK_329[0]][0]
        self.assertEqual(sink.setpoints_sent[idx], sink.setpoints_sent[idx - 1],
                         "the refusing tick must re-command the already-vetted point")
        # The deferred re-latch lands on the very next tick -- named here rather than hidden, and
        # pinned to the range/away-vector that make it a geometric decision instead of a noisy one.
        self.assertEqual(_latch_actions(today)[idx + 1], "relatch")
        next_man = _kinds(today, "maneuver")[idx + 1]
        self.assertEqual(next_man["debug"]["trigger_range_m"], ENCOUNTER[idx + 1][2])
        self.assertFalse(next_man["debug"]["range_degenerate"])
        self.assertEqual(tuple(next_man["debug"]["away_unit"]), ENCOUNTER[idx + 1][3])

    def test_the_new_law_still_dodges_every_tick_and_costs_one_relatch(self):
        """The price of R2+R3 on the flown encounter: 19/19 ticks still command a vetted dodge
        (nothing became a HOLD or a gate_reject), one takeover, and the re-latch count goes 7 -> 6
        with one refusal in its place."""
        flown, _ = self._replay(lateral_tree_margin_m=0.0, degenerate_range_m=0.0)
        ex, _ = self._replay()
        self.assertEqual(len(_kinds(ex, "maneuver")), 19)
        self.assertEqual(_kinds(ex, "hold"), [])
        self.assertEqual(_kinds(ex, "gate_reject"), [])
        self.assertEqual(len(_kinds(ex, "takeover")), 1)
        self.assertEqual(len(_kinds(flown, "relatch")), 7)
        self.assertEqual(len(_kinds(ex, "relatch")), 6)
        self.assertEqual(sum(a == REFUSED for a in _latch_actions(ex)), 1)

    def test_R2_alone_would_still_have_flown_a_noise_driven_dodge(self):
        """Why R3 is not redundant with R2. At margin 1.0 the degenerate tick's 0-deg candidate is
        rejected and the dodge is ROTATED -- but a rotation of a noise direction is still a noise
        direction, and the executor re-latches onto it. R2 fixes what the dodge sweeps past; only R3
        stops it being commanded at all."""
        r2_only, sink = self._replay(degenerate_range_m=0.0)
        idx = [i for i, row in enumerate(ENCOUNTER) if row[0] == TICK_329[0]][0]
        self.assertEqual(_latch_actions(r2_only)[idx], "relatch")
        rotated = sink.setpoints_sent[idx]
        self.assertNotEqual(rotated, SETPOINT_329)                    # R2 moved it...
        self.assertNotEqual(rotated, sink.setpoints_sent[idx - 1])    # ...but it still got flown
        self.assertEqual(_kinds(r2_only, "maneuver")[idx]["debug"]["candidate_angle_deg"], 45.0)

    def test_every_commanded_dodge_of_the_replay_clears_the_tree_margin(self):
        """The R2 invariant as the flight-log gate will assert it: every accepted maneuver's
        `swept_tree_clearance_m` is at or above the margin the policy logged for that decision."""
        ex, _ = self._replay()
        for ev in _kinds(ex, "maneuver"):
            with self.subTest(tick=ev["tick"]):
                self.assertGreaterEqual(ev["debug"]["swept_tree_clearance_m"],
                                        ev["debug"]["params"]["lateral_tree_margin_m"])
                self.assertGreaterEqual(ev["debug"]["params"]["lateral_tree_margin_m"], 1.0)

    def test_every_maneuver_carries_both_numbers_the_gate_checks(self):
        """Absence from the log IS the bug: the gate fails a schema-2 log missing either field, so
        the executor must be passing the policy's whole debug dict through untouched."""
        ex, _ = self._replay()
        bar = PolicyParams().degenerate_range_m
        for ev in _kinds(ex, "maneuver"):
            with self.subTest(tick=ev["tick"]):
                self.assertIn("trigger_range_m", ev["debug"])
                self.assertIn("range_degenerate", ev["debug"])
                self.assertEqual(ev["debug"]["range_degenerate"],
                                 ev["debug"]["trigger_range_m"] < bar)
                self.assertEqual(ev["debug"]["params"]["degenerate_range_m"], bar)

    def test_R4_is_still_open(self):
        """Tripwire, not an endorsement: candidate 0 deg (straight away from the bird) is still
        tried FIRST, which in a head-on closure is a full reversal -- the escape ownship momentum
        forbids, and the reason the flown dodge bought 45 mm. R2/R3 do not touch it. The day the
        candidate order changes, this fails and whoever changed it lands R4 in the ADR."""
        self.assertEqual(_CANDIDATE_ANGLES_DEG[0], 0.0)
        ex, _ = self._replay()
        angles = [ev["debug"]["candidate_angle_deg"] for ev in _kinds(ex, "maneuver")]
        self.assertEqual(angles.count(0.0), 18, "18 of 19 ticks still take the reversal candidate")


if __name__ == "__main__":
    unittest.main()
