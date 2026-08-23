"""Degenerate-range avoidance: the near-zero-trigger-range boundary class (ADR-013 amendment 11).

WHY THIS FILE EXISTS
--------------------
In the 2026-08-23 delegated avoidance demo (`eval/results/live_flight_log_20260823T004031Z.json`)
one tick of the single 19-tick encounter came in at `trigger_range_m 0.052` -- the drone was
effectively ON the bird. On that tick the away-vector swung from (0.024, -1.0) to (0.758, 0.652)
and the vet ACCEPTED a setpoint carrying `swept_tree_clearance_m 0.846` where every other tick of
the same encounter carried 7-8 m. The flight was not a failure. The BOUNDARY is the point.

Three separate mechanisms meet at that tick, and this file pins each one against today's code so a
fix can be proven to move them:

  M1  DIRECTION.  `avoidance_policy._plan_divert` builds the away-vector as
      `_unit(drone_xy - trigger_xy)` (avoidance_policy.py:323) and only falls back to the
      heading-perpendicular sidestep when `_unit` returns None -- which happens below 1e-9 m
      (avoidance_policy.py:105-109). Between 1e-9 m and ~1 m the vector is numerically valid and
      physically meaningless: a bird-position error of eps rotates it by up to 2*asin(eps/r), which
      saturates at 180 deg as soon as eps >= r. ADR-009 ranges birds by apparent size; its error at
      15 m is metres, so at r = 0.052 m the commanded dodge direction is 100% noise.

  M2  MARGIN.   Gate 2 of the vet is `if seg.clearance_m < p.lateral_tree_margin_m`
      (avoidance_policy.py:385) and `lateral_tree_margin_m` defaults to 0.0
      (avoidance_policy.py:80) and is set by NO caller -- `avoidance_node.py:122` constructs the
      policy with `field_polygon=` and `cruise_alt_m=` only. So the ACCEPTANCE boundary coincides
      exactly with the EXCLUSION boundary: a swept path tangent to a tree column is accepted with
      0.000 m to spare. This is range-independent; the degenerate tick merely sampled it.

  M3  SELECTION. At r -> 0 the other gates stop discriminating: every candidate direction increases
      separation from a bird you are already on top of, and every 10 m dodge clears
      `min_bird_clearance_m`. So the direction from M1 is filtered only by M2.

WHAT IS AND IS NOT BOUNDED (see the class docstrings for the numbers)
  * A tree STRIKE is bounded, but not by a gate: by `obstacle_radius_m` 2.0 vs `canopy_radius_m` 1.3
    (0.700 m of padding) and, at cruise, by 15.0 m vs a 4.8 m tree band. Both are properties of the
    nominal world, not decisions the vet made. ADR-015 rejected resting a safety claim on exactly
    this kind of boundary.
  * A field-polygon BREACH by an accepted dodge is bounded by the polygon being CONVEX -- the vet
    checks the SETPOINT's containment, never the swept path's (avoidance_policy.py:390-395).
    `test_convexity_is_what_makes_setpoint_containment_imply_path_containment` is the tripwire.
  * Separation from the BIRD is not bounded at all: the flown CPA was 0.0518 m.

CONVENTIONS
  * `test_CURRENT_*` pins today's behaviour, including where today's behaviour is wrong. Each one
    names the recommendation that should break it. When the fix lands these tests MUST fail -- that
    is the point; update them with the ADR amendment, do not weaken them.
  * `test_WANT_*` is `@unittest.expectedFailure`: the invariant we want. It flips to "unexpected
    success" (a RED unittest run) the moment a fix makes it true. Self-activating, zero edits.
    NOTE: pytest reports an unexpected success as xpass, which is not red by default -- the
    canonical CI invocation `python3 -m unittest discover -s tests/fieldguard_planning` is what
    makes these bite. The `test_CURRENT_*` pins fail under BOTH runners; they are the real gate.

No policy/executor/geofence code is modified by this file. A control-law change cannot be
live-gated offline and is not QA's to ship.

stdlib unittest only. Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import json
import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.avoidance_policy import (  # noqa: E402
    _CANDIDATE_ANGLES_DEG, AvoidancePolicy, PolicyParams, _unit,
)
from fieldguard_planning.avoidance_types import Decision, Detection, DroneState  # noqa: E402
from fieldguard_planning.coverage import load_field_polygon  # noqa: E402
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402

# --------------------------------------------------------------------------------------------------
# The flown encounter, transcribed from eval/results/live_flight_log_20260823T004031Z.json so these
# assertions do not depend on a gitignore-exception artifact staying on disk. Committed evidence is
# still cross-checked against this table by TestFlightLogArtifact (skips if the file is absent).
# (tick, drone_enu, trigger_range_m, away_unit, swept_tree_clearance_m, latch_action)
# --------------------------------------------------------------------------------------------------
DEMO_BIRD_ENU = (30.0, 30.0, 15.0)          # avoidance_node.DEMO_BIRD_ENU -- static all 19 ticks
CRUISE_ALT_M = 15.0                          # avoidance_node.CRUISE_ALT_M

ENCOUNTER = (
    (323, (29.993885040283203, 20.727569580078125, 15.0), 9.272, (-0.001, -1.0), 8.01, "latch"),
    (324, (29.993886947631836, 22.341691970825195, 15.0), 7.658, (-0.001, -1.0), 8.012, "recommand_latched"),
    (325, (30.021121978759766, 23.944683074951172, 15.0), 6.055, (0.003, -1.0), 7.948, "relatch"),
    (326, (30.0211238861084, 25.50314712524414, 14.989999771118164), 4.497, (0.005, -1.0), 7.945, "recommand_latched"),
    (327, (30.03020477294922, 27.050479888916016, 14.989999771118164), 2.95, (0.01, -1.0), 7.948, "relatch"),
    (328, (30.030208587646484, 28.72026252746582, 14.989999771118164), 1.28, (0.024, -1.0), 7.879, "recommand_latched"),
    (329, (30.039291381835938, 30.033824920654297, 14.969999313354492), 0.052, (0.758, 0.652), 0.846, "relatch"),
    (330, (30.039291381835938, 31.191539764404297, 14.969999313354492), 1.192, (0.033, 0.999), 7.83, "relatch"),
    (331, (30.057449340820312, 32.271331787109375, 14.949999809265137), 2.272, (0.025, 1.0), 7.87, "recommand_latched"),
    (332, (30.10284423828125, 33.440181732177734, 14.90999984741211), 3.442, (0.03, 1.0), 7.725, "recommand_latched"),
    (333, (30.148235321044922, 34.34186553955078, 14.880000114440918), 4.344, (0.034, 0.999), 7.534, "relatch"),
    (334, (30.19362449645996, 35.21015167236328, 14.84999942779541), 5.214, (0.037, 0.999), 7.437, "recommand_latched"),
    (335, (30.239015579223633, 36.200889587402344, 14.819999694824219), 6.205, (0.039, 0.999), 7.415, "recommand_latched"),
    (336, (30.275333404541016, 37.046913146972656, 14.799999237060547), 7.052, (0.039, 0.999), 7.407, "recommand_latched"),
    (337, (30.293487548828125, 37.89293670654297, 14.779999732971191), 7.898, (0.037, 0.999), 7.436, "relatch"),
    (338, (30.32072639465332, 38.90593719482422, 14.779999732971191), 8.912, (0.036, 0.999), 7.454, "recommand_latched"),
    (339, (30.338882446289062, 39.75196075439453, 14.779999732971191), 9.758, (0.035, 0.999), 7.473, "recommand_latched"),
    (340, (30.366117477416992, 40.78722381591797, 14.779999732971191), 10.793, (0.034, 0.999), 7.485, "recommand_latched"),
    (341, (30.38427734375, 41.644378662109375, 14.779999732971191), 11.651, (0.033, 0.999), 7.5, "relatch"),
)
TICK_329 = ENCOUNTER[6]
SETPOINT_329 = (37.61786866565316, 36.558023442557925, 15.0)   # the accepted, flown setpoint
LATCHED_BEFORE_329 = (30.13260512337695, 17.051004194249206, 15.0)   # latched at tick 327

LIVE_LOG = REPO_ROOT / "eval" / "results" / "live_flight_log_20260823T004031Z.json"

# Physical constants of the 18-tree world (config/static_obstacles.json), asserted in
# TestConsequenceIsBoundedByGeometryNotByTheGate rather than trusted.
OBSTACLE_R_M = 2.0
CANOPY_R_M = 1.3
TREE_HEIGHT_M = 3.8


def _drone(pos, hdg=math.pi / 2.0, wp=6):
    return DroneState(position_enu=pos, heading_rad=hdg, current_wp_index=wp)


def _bird(pos, fid=1, tid="demo_bird_0"):
    return Detection(position_enu=pos, frame_id=fid, track_id=tid)


def _bearing_deg(frm, to):
    return math.degrees(math.atan2(to[1] - frm[1], to[0] - frm[0])) % 360.0


def _angular_span(bearings):
    """Width of the smallest arc containing every bearing (deg). 360 means fully unconstrained."""
    if not bearings:
        return 0.0
    b = sorted(bearings)
    gaps = [(b[(i + 1) % len(b)] - b[i]) % 360.0 for i in range(len(b))]
    return 360.0 - max(gaps)


class _SweepMixin:
    """One sweep of the degenerate regime over the REAL 18-tree map and field polygon, shared by
    every test that needs it: drone on a 1 m grid within +/-6 m of three representative trees (one
    per row), bird placed so the away-unit points at each of 24 bearings, at the flown range
    0.052 m. ~12k policy decisions, ~0.5 s -- cheap enough to be a gate, dense enough to find the
    tangent tail."""

    RANGE_M = 0.052
    N_BEARINGS = 24
    SWEEP_TREES = ((15.0, 5.0), (40.0, 25.0), (65.0, 45.0))

    @classmethod
    def build_sweep(cls, margin_m=None):
        """`margin_m=None` means 'whatever the policy's own default is' -- deliberately NOT pinned
        to 0.0, so that the day `lateral_tree_margin_m` gains a nonzero default this sweep follows
        it and the CURRENT/WANT pair below flips on its own. Pass a number only to PRICE a margin."""
        overrides = {} if margin_m is None else {"lateral_tree_margin_m": margin_m}
        geo = GeofenceMap.from_file()
        poly = load_field_polygon()
        pol = AvoidancePolicy(field_polygon=poly, cruise_alt_m=CRUISE_ALT_M)
        results = []          # (drone_xy, setpoint, swept_clearance_m, angle_deg)
        n_hold = n_case = 0
        for tx, ty in cls.SWEEP_TREES:
            for i in range(13):
                for j in range(13):
                    x, y = tx + i - 6.0, ty + j - 6.0
                    if not (0.0 <= x <= 75.0 and 0.0 <= y <= 60.0):
                        continue
                    for k in range(cls.N_BEARINGS):
                        th = 2 * math.pi * k / cls.N_BEARINGS
                        bird = (x - cls.RANGE_M * math.cos(th),
                                y - cls.RANGE_M * math.sin(th), CRUISE_ALT_M)
                        m = pol.decide(_bird(bird), _drone((x, y, CRUISE_ALT_M)), geo, **overrides)
                        n_case += 1
                        if m.decision is Decision.HOLD:
                            n_hold += 1
                            continue
                        if m.decision is not Decision.DIVERT:
                            continue
                        sp = m.setpoint_enu
                        clr = geo.segment_clearance((x, y), (sp[0], sp[1])).clearance_m
                        results.append(((x, y), sp, clr, m.debug["candidate_angle_deg"]))
        return {"geo": geo, "poly": poly, "policy": pol, "accepted": results,
                "n_hold": n_hold, "n_case": n_case}

    def accepted_clearances(self, sweep=None):
        """Swept-tree clearances of every accepted dodge in a sweep, with an explicit failure if the
        sweep accepted nothing -- an empty sweep is a vacuous green, not a clean bill of health."""
        sweep = sweep if sweep is not None else self.sweep
        clears = [c for _, _, c, _ in sweep["accepted"]]
        self.assertTrue(clears,
                        f"sweep accepted 0 of {sweep['n_case']} degenerate-range cases "
                        f"({sweep['n_hold']} HOLD) -- it measured nothing; re-scope the sweep "
                        f"before reading any clearance number off it")
        return clears


# ==================================================================================================
class TestFlownTick329(unittest.TestCase):
    """M1+M2 reproduced from the flown numbers. Pure replay: the policy is a pure function of
    (detection, drone state, geofence, params), so the flight log's own tick must come back
    bit-identical on a bare interpreter. Heading is irrelevant here and deliberately so -- the
    heading-fallback branch needs |r| < 1e-9 m, which no tick of this encounter reached.

    THIS WHOLE CLASS IS PINNED TO THE AS-FLOWN CONTROL LAW. Any change to the policy is expected to
    break it -- that is the alarm working. Re-pin it against the flight log of the flight that
    proves the change, never against a replay of the change itself."""

    @classmethod
    def setUpClass(cls):
        cls.geo = GeofenceMap.from_file()
        cls.pol = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=CRUISE_ALT_M)

    def _decide(self, tick_row, **overrides):
        _, pos, _, _, _, _ = tick_row
        return self.pol.decide(_bird(DEMO_BIRD_ENU), _drone(pos), self.geo, **overrides)

    def test_whole_encounter_replays_bit_identically(self):
        """All 19 ticks: same decision, same away-unit, same swept clearance, same trigger range."""
        for row in ENCOUNTER:
            tick, pos, rng, away, clr, _ = row
            with self.subTest(tick=tick):
                m = self._decide(row)
                self.assertIs(m.decision, Decision.DIVERT)
                self.assertEqual(m.debug["trigger_range_m"], rng)
                self.assertEqual(tuple(m.debug["away_unit"]), away)
                self.assertEqual(m.debug["swept_tree_clearance_m"], clr)

    def test_flown_setpoint_reproduces_exactly(self):
        m = self._decide(TICK_329)
        self.assertIs(m.decision, Decision.DIVERT, "tick 329 no longer DIVERTs -- re-pin this class")
        self.assertEqual(m.setpoint_enu, SETPOINT_329)
        self.assertEqual(m.debug["candidate_angle_deg"], 0.0)
        self.assertEqual(m.debug["candidates_rejected"], [],
                         "the vet rejected NOTHING on the degenerate tick -- the first candidate, "
                         "whose direction is noise, was taken")

    def test_CURRENT_vet_accepts_the_degenerate_tick_because_the_margin_is_zero(self):
        """R2 (nonzero lateral_tree_margin_m) must break this test. 0.846 m of swept clearance is
        accepted only because the required margin is 0.0."""
        m = self._decide(TICK_329)
        self.assertEqual(m.debug["params"]["lateral_tree_margin_m"], 0.0)
        self.assertEqual(m.debug["swept_tree_clearance_m"], 0.846)
        seg = self.geo.segment_clearance(TICK_329[1][:2], SETPOINT_329[:2])
        self.assertEqual(seg.obstacle.id, "tree_row1_3")
        self.assertAlmostEqual(seg.clearance_m + OBSTACLE_R_M, 2.846, places=3,
                               msg="distance from the swept path to the TRUNK")

    def test_one_tick_of_range_collapse_costs_7_metres_of_tree_clearance(self):
        """tick 328 -> 329: range 1.280 -> 0.052 m, clearance 7.879 -> 0.846 m. The discontinuity,
        not the absolute value, is the smell -- a 7.03 m swing from a 1.23 m change in range."""
        prev, deg = self._decide(ENCOUNTER[5]), self._decide(TICK_329)
        self.assertAlmostEqual(prev.debug["swept_tree_clearance_m"] - deg.debug["swept_tree_clearance_m"],
                               7.033, places=3)

    def test_relatch_fired_20_9_m_although_the_bird_never_moved(self):
        """The executor re-latches when the POLICY SETPOINT moves > RELATCH_THRESHOLD_M (3.0 m),
        which it reads as 'a genuinely moving threat' (avoidance_executor.py:70-81, 314-318). The
        demo bird was static at (30,30,15) for all 19 ticks: the setpoint moved because the DRONE
        crossed the bird, not because the threat did. Setpoint delta is not threat motion."""
        m = self._decide(TICK_329)
        self.assertIs(m.decision, Decision.DIVERT, "tick 329 no longer DIVERTs -- re-pin this class")
        jump = math.dist(m.setpoint_enu, LATCHED_BEFORE_329)
        self.assertAlmostEqual(jump, 20.894, places=3)
        self.assertGreater(jump, 3.0, "RELATCH_THRESHOLD_M")

    def test_margin_of_one_metre_would_have_rotated_this_tick_and_kept_all_19_diverts(self):
        """R2 priced on the flown encounter: at lateral_tree_margin_m=1.0 the degenerate tick is
        rejected at +0 deg and taken at +45 deg with 7.563 m of clearance, and every one of the 19
        ticks still DIVERTs -- the 19/19 vetted encounter is preserved, not traded away."""
        n_divert = 0
        for row in ENCOUNTER:
            m = self._decide(row, lateral_tree_margin_m=1.0)
            n_divert += (m.decision is Decision.DIVERT)
        self.assertEqual(n_divert, 19, "a margin that costs a DIVERT is not free -- re-price it")

        m = self._decide(TICK_329, lateral_tree_margin_m=1.0)
        self.assertIs(m.decision, Decision.DIVERT)
        self.assertEqual(m.debug["candidate_angle_deg"], 45.0)
        self.assertEqual(len(m.debug["candidates_rejected"]), 1)
        clr = self.geo.segment_clearance(TICK_329[1][:2], m.setpoint_enu[:2]).clearance_m
        self.assertAlmostEqual(clr, 7.563, places=3)


# ==================================================================================================
class TestAwayVectorDegeneracy(unittest.TestCase):
    """M1: why near-zero range destabilises the away-vector. The direction of a ~0-length vector is
    the ratio of two ~0 numbers; the guard that exists (`_unit` -> None) is 7 orders of magnitude
    below the range where the physics stops being meaningful."""

    @classmethod
    def setUpClass(cls):
        cls.geo = GeofenceMap.from_file()
        cls.pol = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=CRUISE_ALT_M)

    def test_the_only_degenerate_guard_is_1e9_metres(self):
        """avoidance_policy._unit returns None below 1e-9 m -- one nanometre. Everything above that,
        including the flown 0.052 m, takes the 'valid' branch."""
        self.assertIsNone(_unit((0.0, 0.0)))
        self.assertIsNone(_unit((5e-10, 0.0)))
        self.assertIsNotNone(_unit((2e-9, 0.0)))
        self.assertIsNotNone(_unit((0.052, 0.0)),
                             "the flown degenerate range is NOT caught by the existing guard")

    def test_no_range_floor_parameter_exists(self):
        """Source-of-truth tripwire for R1: the day a range floor is added to PolicyParams this
        fails, and whoever added it updates this file and the ADR together."""
        self.assertNotIn("min_trigger_range_m", PolicyParams.__dataclass_fields__)
        self.assertFalse([f for f in PolicyParams.__dataclass_fields__ if "range_floor" in f])

    def _bearing_set(self, r, eps, n=48):
        """Commanded dodge bearings as the bird ESTIMATE is perturbed by `eps` m in every direction,
        with the true drone-bird range held at `r`. This is the detector being wrong by eps."""
        dx, dy = TICK_329[1][0], TICK_329[1][1]
        true_bird = (dx - r, dy, CRUISE_ALT_M)
        out = []
        for k in range(n):
            th = 2 * math.pi * k / n
            est = (true_bird[0] + eps * math.cos(th), true_bird[1] + eps * math.sin(th), CRUISE_ALT_M)
            m = self.pol.decide(_bird(est), _drone((dx, dy, CRUISE_ALT_M)), self.geo)
            if m.decision is Decision.DIVERT:
                out.append(_bearing_deg((dx, dy), m.setpoint_enu))
        return out

    def test_CURRENT_half_metre_of_position_error_unconstrains_the_dodge_at_flown_range(self):
        """R1 (range floor / explicit degenerate branch) must break this test.

        ADR-009 ranges a bird from its apparent size, an estimator whose error at 15 m is metres,
        not centimetres. At the flown range of 0.052 m, a 0.5 m position error lets the commanded
        dodge point almost anywhere: measured bearing span 337.1 deg (the residual ~23 deg gap is
        where the tree gate rotates the candidate, not where the geometry constrains it). Even a
        5 cm error -- the size of the range itself -- spans 153.2 deg. At 9.27 m, the range this
        same encounter triggered at, the same 0.5 m error moves the dodge by 6.2 deg.

        Threshold 300 deg, not 337: this test is about M1 (direction) and must NOT be tripped by an
        M2 margin change, which only rotates a few more candidates (measured 323.3 deg at margin
        1.0). Only a real range floor collapses it -- to 0.0 deg, since no dodge is emitted."""
        near = self._bearing_set(TICK_329[2], eps=0.5, n=72)
        near_tiny = self._bearing_set(TICK_329[2], eps=0.05, n=72)
        far = self._bearing_set(9.272, eps=0.5, n=72)
        self.assertGreaterEqual(_angular_span(near), 300.0,
                                "at r=0.052 m the dodge direction is unconstrained by the geometry")
        self.assertGreaterEqual(_angular_span(near_tiny), 150.0,
                                "even a 5 cm estimate error swings the dodge through >150 deg")
        self.assertLessEqual(_angular_span(far), 10.0,
                             "at r=9.27 m the same detector error barely moves it")

    def test_direction_error_follows_2_asin_eps_over_r_until_it_saturates(self):
        """The mechanism in closed form, so the fix has a number to hit: any position error >= the
        range flips the away-vector through 180 deg. At the flown tick that threshold is 5.2 cm."""
        def analytic(r, eps):
            return 180.0 if eps >= r else 2.0 * math.degrees(math.asin(eps / r))
        self.assertEqual(analytic(0.052, 0.052), 180.0)
        self.assertAlmostEqual(analytic(0.052, 0.05), 148.115, places=2)
        self.assertAlmostEqual(analytic(9.272, 0.5), 6.183, places=2)
        for r, eps in ((0.052, 0.5), (0.052, 3.0), (0.5, 0.5)):
            self.assertEqual(analytic(r, eps), 180.0)

    def test_bird_gates_stop_discriminating_at_degenerate_range(self):
        """M3: at r -> 0 every one of the 7 candidate directions passes the bird gates (each moves
        ~10 m away from a bird you are on top of, all clear min_bird_clearance_m 3.0). Selection
        therefore rests entirely on the zero-margin tree gate."""
        dx, dy = TICK_329[1][0], TICK_329[1][1]
        params = PolicyParams()
        n_ok = 0
        for angle in _CANDIDATE_ANGLES_DEG:
            th = math.radians(angle)
            sp = (dx + 10.0 * math.cos(th), dy + 10.0 * math.sin(th))
            new_d = math.dist(sp, DEMO_BIRD_ENU[:2])
            cur_d = math.dist((dx, dy), DEMO_BIRD_ENU[:2])
            n_ok += (new_d >= params.min_bird_clearance_m and new_d >= cur_d)
        self.assertEqual(n_ok, len(_CANDIDATE_ANGLES_DEG),
                         "all 7 candidates pass the bird gates -- zero discrimination")


# ==================================================================================================
class TestZeroLateralTreeMargin(_SweepMixin, unittest.TestCase):
    """M2: `lateral_tree_margin_m` is 0.0 BY CODE DEFAULT and by no caller overriding it, so the
    vet's accept boundary IS the exclusion boundary. Range-independent: the degenerate tick did not
    create this tail, it sampled it."""

    @classmethod
    def setUpClass(cls):
        cls.sweep = cls.build_sweep()   # policy default margin, whatever it currently is

    def test_margin_default_is_zero_and_the_live_node_leaves_it_zero(self):
        """The answer to 'margin floor 0.0 by config or by code?': by CODE. There is no config for
        it, and avoidance_node.py builds the policy with field_polygon + cruise_alt_m only."""
        self.assertEqual(PolicyParams().lateral_tree_margin_m, 0.0)
        as_flown = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=CRUISE_ALT_M)
        self.assertEqual(as_flown.params.lateral_tree_margin_m, 0.0)
        node_src = (REPO_ROOT / "src" / "fieldguard_planning" / "avoidance_node.py").read_text()
        self.assertNotIn("lateral_tree_margin_m", node_src,
                         "if the node starts setting the margin, re-price this whole file")

    def test_CURRENT_a_swept_path_exactly_tangent_to_a_tree_column_is_accepted(self):
        """R2 must break this test. Exact geometry, no float fuzz: drone (9,3), bird 0.052 m due
        west, dodge due east to (19,3). tree_row0_0 sits at (15,5) with obstacle_radius 2.0, so the
        segment y=3 is EXACTLY tangent to its exclusion column -- clearance 0.000 m -- and the vet
        accepts, because the test is `clearance < 0.0`."""
        geo, pol = self.sweep["geo"], self.sweep["policy"]
        drone_xy = (9.0, 3.0)
        m = pol.decide(_bird((8.948, 3.0, CRUISE_ALT_M)), _drone((*drone_xy, CRUISE_ALT_M)), geo)
        self.assertIs(m.decision, Decision.DIVERT)
        self.assertEqual(m.setpoint_enu, (19.0, 3.0, CRUISE_ALT_M))
        seg = geo.segment_clearance(drone_xy, m.setpoint_enu[:2])
        self.assertEqual(seg.obstacle.id, "tree_row0_0")
        self.assertEqual(seg.clearance_m, 0.0)
        self.assertEqual(m.debug["swept_tree_clearance_m"], 0.0)

    def test_CURRENT_sweep_finds_a_sub_centimetre_accepted_clearance(self):
        """R2 must break this test. Population statistic over the degenerate regime, so nobody can
        call the flown 0.846 m a one-off: on a 1 m grid around three trees at the flown range,
        today's vet accepts dodges down to 0.000 m of swept clearance."""
        clears = self.accepted_clearances()
        self.assertGreater(len(clears), 5000, "sweep degenerated -- it must actually measure something")
        self.assertLessEqual(min(clears), 0.01)
        self.assertGreaterEqual(sum(1 for c in clears if c < 0.1) / len(clears), 0.04,
                                ">=4% of accepted degenerate-range dodges clear a tree by <0.1 m")
        self.assertGreaterEqual(sum(1 for c in clears if c < 1.0) / len(clears), 0.25,
                                ">=25% clear by <1 m")

    @unittest.expectedFailure
    def test_WANT_every_accepted_dodge_keeps_one_metre_of_swept_tree_clearance(self):
        """The invariant R2 buys. Self-activating: goes 'unexpected success' (red under unittest)
        the moment a nonzero margin lands. 1.0 m is what the 18-tree geometry supports -- see
        TestWhatTheGeometrySupports."""
        self.assertGreaterEqual(min(self.accepted_clearances()), 1.0)

    def test_a_margin_of_one_metre_actually_delivers_it(self):
        """Not an aspiration: run the same sweep with margin 1.0 and confirm the tail is gone and
        the HOLD rate stays sane. The FIX is proven offline; only its FLIGHT behaviour needs a gate."""
        fixed = self.build_sweep(margin_m=1.0)
        clears = self.accepted_clearances(fixed)
        self.assertGreaterEqual(min(clears), 1.0)
        hold_rate_now = self.sweep["n_hold"] / self.sweep["n_case"]
        hold_rate_fix = fixed["n_hold"] / fixed["n_case"]
        self.assertLess(hold_rate_fix - hold_rate_now, 0.15,
                        "a margin that turns dodges into holds near every tree is not free")


# ==================================================================================================
class TestConsequenceIsBoundedByGeometryNotByTheGate(_SweepMixin, unittest.TestCase):
    """The consequence-class verdict, as executable statements. Each of these passes TODAY -- they
    are the reasons the flown 0.846 m tick was not a crash, and each names the world property it
    leans on. If one of them starts failing, the boundary class became a live hazard."""

    @classmethod
    def setUpClass(cls):
        cls.sweep = cls.build_sweep()   # policy default margin, whatever it currently is

    def test_world_constants_are_what_this_verdict_assumes(self):
        geo = self.sweep["geo"]
        self.assertEqual(len(geo), 18)
        for obs in geo.obstacles:
            self.assertEqual(obs.obstacle_radius_m, OBSTACLE_R_M)
            self.assertEqual(obs.canopy_radius_m, CANOPY_R_M)
            self.assertEqual(obs.height_m, TREE_HEIGHT_M)
            self.assertEqual(obs.z_m, 0.0)

    def test_accepted_swept_paths_never_enter_a_tree_exclusion_column(self):
        """The one thing gate 2 does buy even at margin 0: no accepted dodge sweeps INTO a column.
        'Through a tree' is off the table; 'tangent to a tree' is not."""
        for drone_xy, sp, clr, _ in self.sweep["accepted"]:
            if clr < 0.0:
                self.fail(f"accepted dodge sweeps INSIDE a tree column: {drone_xy} -> {sp} ({clr} m)")

    def test_tangent_acceptance_still_clears_the_physical_canopy_by_0_70_m(self):
        """Padding, not a decision: obstacle_radius 2.0 - canopy_radius 1.3. Today the worst
        accepted swept path is exactly 0.700 m from the leaves -- every metre of it donated by the
        obstacle-radius padding, none of it chosen by the vet. Asserted as a FLOOR so a fix that
        raises it stays green and a world change that shrinks the padding goes red."""
        worst = min(self.accepted_clearances())
        self.assertGreaterEqual(worst + OBSTACLE_R_M - CANOPY_R_M, 0.700 - 1e-9)

    def test_at_cruise_a_tree_strike_needs_an_11_metre_altitude_error(self):
        """The second, independent bound: every policy setpoint is at cruise 15.0 m and the tallest
        tree volume tops out at 4.8 m (height 3.8 + vertical_margin 1.0)."""
        band_top = TREE_HEIGHT_M + PolicyParams().vertical_margin_m
        self.assertAlmostEqual(band_top, 4.8, places=6)
        self.assertAlmostEqual(CRUISE_ALT_M - band_top, 10.2, places=6)

    def test_no_accepted_dodge_leaves_the_field_polygon(self):
        """Geofence verdict: bounded. Every accepted setpoint sits >= field_margin_m inside, and
        with a convex polygon that carries the whole swept path."""
        for drone_xy, sp, _, _ in self.sweep["accepted"]:
            for t in (0.0, 0.25, 0.5, 0.75, 1.0):
                px = drone_xy[0] + t * (sp[0] - drone_xy[0])
                py = drone_xy[1] + t * (sp[1] - drone_xy[1])
                self.assertTrue(-1e-9 <= px <= 75.0 + 1e-9 and -1e-9 <= py <= 60.0 + 1e-9,
                                f"swept path left the field: {drone_xy} -> {sp}")

    def test_convexity_is_what_makes_setpoint_containment_imply_path_containment(self):
        """THE unstated dependency, made explicit. The vet checks the SETPOINT against the polygon
        (avoidance_policy.py:390-395); it never checks the swept path. That is only sound because
        the field is convex. This test fails the day the polygon gets a notch -- at which point a
        swept-path containment check is required, not optional."""
        poly = load_field_polygon()
        n = len(poly)
        signs = []
        for i in range(n):
            ax, ay = poly[i]
            bx, by = poly[(i + 1) % n]
            cx, cy = poly[(i + 2) % n]
            signs.append(math.copysign(1.0, (bx - ax) * (cy - by) - (by - ay) * (cx - bx)))
        self.assertEqual(len(set(signs)), 1,
                         "field polygon is no longer convex -- the vet now needs a swept-path "
                         "containment gate (see this test's docstring)")

    def test_the_vet_never_checks_the_vehicles_OWN_position(self):
        """Scope note, pinned: gates 1-4 vet the setpoint and the segment; nothing asserts the drone
        is itself inside the polygon or clear of a column. Harmless while the ownship pose is good;
        it is why the sweep's containment guarantee is about the DODGE, not about the FLIGHT.
        Posed at a WELL-CONDITIONED 5 m range on purpose, so a degenerate-range fix cannot mask it:
        this gap is about ownship containment, not about the away-vector."""
        geo, pol = self.sweep["geo"], self.sweep["policy"]
        outside = (-0.0363, 15.3175, CRUISE_ALT_M)   # flown tick 177 of the 2026-08-23 log
        m = pol.decide(_bird((-0.0363, 10.3175, CRUISE_ALT_M)), _drone(outside), geo)
        self.assertIs(m.decision, Decision.DIVERT,
                      "policy dodges happily from a position outside the field polygon")
        self.assertEqual(m.debug["candidate_angle_deg"], -45.0)

    def test_drone_inside_a_tree_column_yields_HOLD_not_a_dodge(self):
        """The other end of the same gap: with the drone inside a column, every candidate segment
        starts inside it, so all 7 are rejected and the policy HOLDs -- correct for 'boxed in', but
        note that below canopy height this is 'hover inside the tree'. Unreachable at cruise;
        pinned so a future descent feature has to confront it."""
        geo, pol = self.sweep["geo"], self.sweep["policy"]
        m = pol.decide(_bird((45.0, 25.0, 4.0)), _drone((40.5, 25.0, 4.0), hdg=0.0), geo)
        self.assertIs(m.decision, Decision.HOLD)
        self.assertEqual(len(m.debug["candidates_rejected"]), len(_CANDIDATE_ANGLES_DEG))


# ==================================================================================================
class TestIsSafe3dCannotFireInTheFlownConfiguration(unittest.TestCase):
    """VACUOUS-GREEN finding, separate from the degenerate-range one and ranked above it.

    The policy's gate 1 and the executor's ADR-006 safety BACKSTOP are the same call:
    `GeofenceMap.is_safe_3d(setpoint, vertical_margin_m, alt_bounds)`. Every setpoint the v1 policy
    can emit is pinned to `cruise_alt_m` (avoidance_policy.py:333); the flown config sets that to
    15.0 with alt_bounds (2, 30); the tallest tree volume tops out at 4.8 m. So is_safe_3d returns
    True for EVERY XY, including a tree's own trunk. The gate is correct code that cannot reject
    anything in the flown configuration -- and the flight log's '0 gate_reject events' therefore
    means 'could not fire', not 'nothing was wrong'."""

    @classmethod
    def setUpClass(cls):
        cls.geo = GeofenceMap.from_file()
        cls.pol = AvoidancePolicy(field_polygon=load_field_polygon(), cruise_alt_m=CRUISE_ALT_M)

    def test_every_emitted_setpoint_is_pinned_to_cruise_altitude(self):
        n = 0
        for row in ENCOUNTER:
            m = self.pol.decide(_bird(DEMO_BIRD_ENU), _drone(row[1]), self.geo)
            if m.decision is not Decision.DIVERT:
                continue          # a later fix may HOLD some ticks; the altitude claim still holds
            n += 1
            self.assertEqual(m.setpoint_enu[2], CRUISE_ALT_M)
        self.assertGreater(n, 0, "no DIVERT setpoint was emitted -- this test measured nothing")

    def test_CURRENT_is_safe_3d_accepts_the_trunk_of_every_tree_at_cruise(self):
        """R4 must break this test (or make it moot): the backstop's reject branch is dead in the
        flown config. Checked on the strongest possible input -- dead centre of every tree."""
        for obs in self.geo.obstacles:
            with self.subTest(tree=obs.id):
                self.assertTrue(self.geo.is_safe_3d((obs.x_m, obs.y_m, CRUISE_ALT_M),
                                                    PolicyParams().vertical_margin_m, (2.0, 30.0)))

    def test_the_backstop_is_live_code_it_is_just_never_reached_at_cruise(self):
        """Not a bug in is_safe_3d: drop the same setpoint into the canopy band and it rejects.
        The gap is that nothing the v1 policy emits ever gets there."""
        trunk = self.geo.obstacles[0]
        self.assertFalse(self.geo.is_safe_3d((trunk.x_m, trunk.y_m, 4.0),
                                             PolicyParams().vertical_margin_m, (2.0, 30.0)))
        self.assertFalse(self.geo.is_safe_3d((trunk.x_m, trunk.y_m, 31.0),
                                             PolicyParams().vertical_margin_m, (2.0, 30.0)))


# ==================================================================================================
class TestWhatTheGeometrySupports(unittest.TestCase):
    """What margin can the 18-tree world actually carry? Answers R2's 'and what value?' from the
    map itself rather than from taste, and pins the ceiling so a later 'let's just use 3 m' has to
    argue with a number."""

    @classmethod
    def setUpClass(cls):
        cls.geo = GeofenceMap.from_file()

    def test_within_row_corridor_caps_any_margin_at_3_metres(self):
        """Trees are 10.0 m apart within a row with obstacle_radius 2.0 -> a 6.0 m free corridor ->
        a path threading it can never clear more than 3.00 m. A margin >= 3.0 forbids threading a
        row outright; 1.0 m leaves 3x headroom."""
        rows = {}
        for obs in self.geo.obstacles:
            rows.setdefault(obs.row_id, []).append(obs.y_m)
        for row_id, ys in rows.items():
            ys.sort()
            gaps = {round(b - a, 6) for a, b in zip(ys, ys[1:])}
            self.assertEqual(gaps, {10.0}, f"row {row_id} spacing changed")
        self.assertEqual((10.0 - 2 * OBSTACLE_R_M) / 2.0, 3.0)

    def test_inter_row_corridor_is_10_5_metres(self):
        xs = sorted({obs.x_m for obs in self.geo.obstacles})
        self.assertEqual(xs, [15.0, 40.0, 65.0])
        self.assertEqual((25.0 - 2 * OBSTACLE_R_M) / 2.0, 10.5)

    def test_two_mission_lanes_run_5_metres_from_a_tree_row(self):
        """Lane x=45 and lane x=60 sit 5.0 m from rows at 40 and 65 -> 3.0 m of column clearance
        from the lane itself. A 1.0 m margin still leaves those lanes a dodge; a 3.0 m margin does
        not. Lane x=15 flies straight over row 0 (XY clearance -2.0 m), safe only by altitude."""
        lanes = [0.0, 15.0, 30.0, 45.0, 60.0, 75.0]
        rows = [15.0, 40.0, 65.0]
        nearest = {lane: min(abs(lane - r) for r in rows) for lane in lanes}
        self.assertEqual(nearest, {0.0: 15.0, 15.0: 0.0, 30.0: 10.0, 45.0: 5.0, 60.0: 5.0, 75.0: 10.0})
        self.assertEqual(nearest[15.0] - OBSTACLE_R_M, -2.0)


# ==================================================================================================
class TestFlightLogArtifact(unittest.TestCase):
    """Self-activating checks on the committed artifact itself (skip if it is ever pruned). These
    are the numbers no existing gate computes: check_live_flight_log.py validates the coverage
    ledger, not separation. 19/19 'accepted' maneuvers is a statement about SETPOINTS."""

    @classmethod
    def setUpClass(cls):
        if not LIVE_LOG.exists():
            raise unittest.SkipTest(f"{LIVE_LOG.name} absent (eval/results is gitignore-excepted)")
        cls.log = json.loads(LIVE_LOG.read_text())
        cls.path = [tuple(p) for p in cls.log["flown_path_enu"]]
        cls.events = cls.log["events"]

    def test_transcribed_fixture_matches_the_artifact(self):
        """Keeps ENCOUNTER honest: if the log is ever regenerated, this catches the drift instead of
        letting the transcription quietly become fiction."""
        man = {e["tick"]: e for e in self.events if e["kind"] == "maneuver"}
        for tick, pos, rng, away, clr, latch in ENCOUNTER:
            with self.subTest(tick=tick):
                self.assertEqual(tuple(self.path[tick - 1]), pos)
                self.assertEqual(man[tick]["debug"]["trigger_range_m"], rng)
                self.assertEqual(tuple(man[tick]["debug"]["away_unit"]), away)
                self.assertEqual(man[tick]["debug"]["swept_tree_clearance_m"], clr)
                self.assertEqual(man[tick]["latch_action"], latch)

    def test_the_headline_is_one_encounter_not_nineteen(self):
        """A rate needs a denominator. '19/19 maneuvers vetted' counts TICKS of a single encounter
        with a single static virtual bird: 1 takeover, 1 resume, 1 track_id, 0 bird motion."""
        kinds = [e["kind"] for e in self.events]
        self.assertEqual(kinds.count("maneuver"), 19)
        self.assertEqual(kinds.count("takeover"), 1)
        self.assertEqual(kinds.count("resume"), 1)
        self.assertEqual(kinds.count("gate_reject"), 0)
        dets = [e for e in self.events if e["kind"] == "detection"]
        self.assertEqual({e["track_id"] for e in dets}, {"demo_bird_0"})
        self.assertEqual({tuple(e["position_enu"]) for e in dets}, {DEMO_BIRD_ENU},
                         "the threat never moved -- every re-latch was ownship motion")

    def test_CURRENT_closest_point_of_approach_was_5_centimetres(self):
        """SAFETY GAP, pinned. The encounter's CPA is 0.0518 m against a policy whose own
        `min_bird_clearance_m` is 3.0. Nothing in the pipeline computes this number, so nothing
        went red. R5 (a CPA assertion in check_live_flight_log.py) must break this test."""
        cpa = min(math.dist(p[:2], DEMO_BIRD_ENU[:2]) for p in self.path)
        self.assertAlmostEqual(cpa, 0.0518, places=4)
        self.assertLess(cpa, PolicyParams().min_bird_clearance_m)

    def test_CURRENT_the_dodge_bought_45_millimetres_of_lateral_escape(self):
        """From the first accepted DIVERT (tick 323, range 9.272 m, setpoint 10 m BEHIND the
        vehicle) to CPA six ticks later, the vehicle moved 0.045 m across-track and 9.306 m
        along-track -- toward the bird -- while its speed stayed above 6.5 m/s. The maneuver was
        commanded, vetted, logged and flown, and it did not avoid anything."""
        p323, p329 = self.path[322], self.path[328]
        self.assertAlmostEqual(p329[0] - p323[0], 0.0454, places=4)     # across-track (lane x=30)
        self.assertAlmostEqual(p329[1] - p323[1], 9.3063, places=4)     # along-track, toward the bird
        first_sp = (29.98729026619471, 10.727571754630626)
        self.assertAlmostEqual(math.dist(p323[:2], first_sp), 10.0, places=2)
        self.assertAlmostEqual(math.dist(p329[:2], first_sp), 19.31, places=2)
        speed_at_cpa = math.dist(self.path[327][:2], self.path[328][:2]) * 5.0   # CONTROL_HZ
        self.assertGreater(speed_at_cpa, 6.5, "still at cruise speed at closest approach")

    def test_CURRENT_flown_path_leaves_the_field_polygon_on_the_boundary_lanes(self):
        """Separate boundary defect, found while sweeping: mission lanes x=0 and x=75 lie ON the
        field polygon, so ordinary tracking error puts the vehicle outside it -- 118 of 984 logged
        positions, worst 0.073 m. Harmless today (no ArduPilot FENCE is configured, nothing is out
        there) but it means the containment claim is measured 7 cm from false, which is the ADR-015
        'never rest a claim on a boundary' pattern."""
        outside = [(i + 1, p) for i, p in enumerate(self.path)
                   if not (0.0 <= p[0] <= 75.0 and 0.0 <= p[1] <= 60.0)]
        self.assertEqual(len(outside), 118)
        worst = max(max(-p[0], p[0] - 75.0, -p[1], p[1] - 60.0) for _, p in outside)
        self.assertAlmostEqual(worst, 0.073, places=3)

    @unittest.expectedFailure
    def test_WANT_the_encounter_holds_the_policys_own_minimum_bird_clearance(self):
        """The bar the flight missed, stated as the invariant a re-fly must clear: CPA >= 3.0 m
        (`min_bird_clearance_m` -- the policy already refuses to place a SETPOINT closer than this,
        so flying closer than it is inconsistent on its face). Self-activating: goes red-as-passing
        the day a flight clears it."""
        cpa = min(math.dist(p[:2], DEMO_BIRD_ENU[:2]) for p in self.path)
        self.assertGreaterEqual(cpa, PolicyParams().min_bird_clearance_m)


if __name__ == "__main__":
    unittest.main()
