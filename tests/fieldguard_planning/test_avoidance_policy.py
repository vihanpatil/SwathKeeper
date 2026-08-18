"""Tests for the reactive-avoidance decision policy (avoidance_policy.py).

Load-bearing invariant under test: **whenever the policy returns DIVERT, its setpoint passes
`geofence.is_safe_3d`** — the policy never hands the executor a point it cannot prove safe. When no
safe divert exists it returns HOLD, never an unsafe DIVERT. Stdlib unittest, runs on bare python.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fieldguard_planning.avoidance_types import Detection, DroneState, Decision  # noqa: E402
from fieldguard_planning.avoidance_policy import AvoidancePolicy  # noqa: E402
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402


def _drone(x, y, z=15.0, wp=3, hdg=0.0):
    return DroneState(position_enu=(x, y, z), heading_rad=hdg, current_wp_index=wp)


def _bird(x, y, z=15.0, fid=10, tid="bird_0"):
    return Detection(position_enu=(x, y, z), frame_id=fid, track_id=tid)


class TestAvoidancePolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.geo = GeofenceMap.from_file()  # the real farm geofence (18 trees)

    def setUp(self):
        self.pol = AvoidancePolicy()

    # -- PROCEED --------------------------------------------------------------
    def test_no_detection_proceeds(self):
        m = self.pol.decide(None, _drone(30, 30), self.geo)
        self.assertIs(m.decision, Decision.PROCEED)
        self.assertIsNone(m.setpoint_enu)

    def test_bird_outside_threat_cylinder_proceeds(self):
        # bird 30 m away horizontally -- well outside the 12 m threat radius
        m = self.pol.decide(_bird(30 + 30, 30), _drone(30, 30), self.geo)
        self.assertIs(m.decision, Decision.PROCEED)

    def test_bird_far_below_proceeds(self):
        # bird within horizontal radius but 10 m below cruise (> 6 m vertical threat) -> not a threat
        m = self.pol.decide(_bird(33, 30, z=5.0), _drone(30, 30, z=15.0), self.geo)
        self.assertIs(m.decision, Decision.PROCEED)

    # -- clean DIVERT in open field ------------------------------------------
    def test_bird_crossing_open_field_diverts_safely(self):
        # drone at (30,30) between tree rows x=15 and x=40; bird just east -> dodge west, clear ground
        m = self.pol.decide(_bird(33, 30), _drone(30, 30), self.geo)
        self.assertIs(m.decision, Decision.DIVERT)
        self.assertIsNotNone(m.setpoint_enu)
        self.assertTrue(self.geo.is_safe_3d(m.setpoint_enu))
        # setpoint must increase separation from the bird
        sx, sy, _ = m.setpoint_enu
        self.assertGreater(((sx - 33) ** 2 + (sy - 30) ** 2) ** 0.5,
                           ((30 - 33) ** 2 + (30 - 30) ** 2) ** 0.5)

    # -- THE invariant: DIVERT is ALWAYS 3D-safe -----------------------------
    def test_divert_setpoint_is_always_3d_safe_across_a_sweep(self):
        """Sweep the bird around the drone at many bearings; every DIVERT that comes back must carry a
        setpoint that passes is_safe_3d, and HOLD must never carry a setpoint. This is the property
        the executor's backstop assumes."""
        import math
        drone = _drone(30, 30)
        for deg in range(0, 360, 15):
            bx = 30 + 5.0 * math.cos(math.radians(deg))
            by = 30 + 5.0 * math.sin(math.radians(deg))
            m = self.pol.decide(_bird(bx, by), drone, self.geo)
            if m.decision is Decision.DIVERT:
                self.assertIsNotNone(m.setpoint_enu, f"DIVERT w/o setpoint at bearing {deg}")
                self.assertTrue(self.geo.is_safe_3d(m.setpoint_enu),
                                f"DIVERT setpoint unsafe at bearing {deg}: {m.setpoint_enu}")
            else:
                self.assertIsNone(m.setpoint_enu, f"{m.decision} carried a setpoint at bearing {deg}")

    # -- avoid-into-tree: never steer the dodge through a tree column --------
    def test_does_not_dodge_into_a_tree(self):
        """Drone just west of tree row 2 (x=65), bird to the west so the naive 'straight away' (east)
        dodge would sweep through the tree at (65,25). The policy must reject that candidate and pick a
        genuinely clear one (or HOLD) -- never a setpoint whose swept path clips a tree."""
        drone = _drone(57, 25)
        bird = _bird(54, 25)                      # west of the drone -> away-vector points east, at the tree
        m = self.pol.decide(bird, drone, self.geo)
        if m.decision is Decision.DIVERT:
            self.assertTrue(self.geo.is_safe_3d(m.setpoint_enu))
            sp_xy = (m.setpoint_enu[0], m.setpoint_enu[1])
            clr = self.geo.segment_clearance((57.0, 25.0), sp_xy).clearance_m
            self.assertGreaterEqual(clr, 0.0,
                                    f"dodge swept path clips a tree (clearance {clr:.2f} m): {m.setpoint_enu}")
        else:
            self.assertIs(m.decision, Decision.HOLD)

    # -- boxed in -> HOLD, never an unsafe DIVERT ----------------------------
    def test_boxed_in_holds(self):
        """Constrain the field polygon to a tiny box around the drone: any 10 m dodge leaves the field,
        so every candidate is rejected on containment -> HOLD (not an out-of-field DIVERT)."""
        tiny_field = [(28.0, 28.0), (32.0, 28.0), (32.0, 32.0), (28.0, 32.0)]
        pol = AvoidancePolicy(field_polygon=tiny_field)
        m = pol.decide(_bird(33, 30), _drone(30, 30), self.geo)
        self.assertIs(m.decision, Decision.HOLD)
        self.assertIsNone(m.setpoint_enu)

    # -- two simultaneous birds ----------------------------------------------
    def test_two_birds_still_safe(self):
        drone = _drone(30, 30)
        birds = [_bird(33, 30, tid="bird_a", fid=1), _bird(30, 33, tid="bird_b", fid=1)]
        m = self.pol.decide_multi(birds, drone, self.geo)
        self.assertIn(m.decision, (Decision.DIVERT, Decision.HOLD))
        if m.decision is Decision.DIVERT:
            self.assertTrue(self.geo.is_safe_3d(m.setpoint_enu))
            # keep min clearance from BOTH birds
            for b in birds:
                d = ((m.setpoint_enu[0] - b.position_enu[0]) ** 2
                     + (m.setpoint_enu[1] - b.position_enu[1]) ** 2) ** 0.5
                self.assertGreaterEqual(d, 3.0)


class TestDetectionStaleness(unittest.TestCase):
    """Staleness gate (`Detection.stamp_s` + `max_detection_age_s`): once the real detector replaces
    the --demo bird behind the detection_source seam, an old frame must not be able to trigger a
    phantom dodge or sit in the threat set masking a live threat. Gate is OFF by default so all
    pre-existing behavior (and every unstamped source) is untouched."""

    @classmethod
    def setUpClass(cls):
        cls.geo = GeofenceMap.from_file()  # the real farm geofence (18 trees)

    def setUp(self):
        # gate ON at 0.5 s for these tests; drone/bird geometry mirrors the clean-DIVERT case above
        self.pol = AvoidancePolicy(max_detection_age_s=0.5)

    def test_fresh_detection_still_triggers(self):
        # stamped 0.1 s ago -- inside the 0.5 s budget -> normal threat handling (a DIVERT here)
        det = Detection(position_enu=(33.0, 30.0, 15.0), frame_id=10, track_id="bird_0",
                        stamp_s=100.0)
        m = self.pol.decide(det, _drone(30, 30), self.geo, now_s=100.1)
        self.assertIs(m.decision, Decision.DIVERT)

    def test_stale_detection_treated_as_absent(self):
        # stamped 1.0 s ago (> 0.5 s) -> ABSENT: PROCEED, no setpoint, and the drop is OBSERVABLE
        # in both the reason and the debug dict (event-log instrumentation rule)
        det = Detection(position_enu=(33.0, 30.0, 15.0), frame_id=10, track_id="bird_0",
                        stamp_s=100.0)
        m = self.pol.decide(det, _drone(30, 30), self.geo, now_s=101.0)
        self.assertIs(m.decision, Decision.PROCEED)
        self.assertIsNone(m.setpoint_enu)
        self.assertIn("stale", m.reason)
        self.assertEqual(m.debug.get("n_stale_dropped"), 1)
        self.assertIn("bird_0", m.debug.get("stale_ids", []))

    def test_unstamped_detection_with_gate_on_keeps_current_behavior(self):
        """UNSTAMPED detection + gate ON -> gate fails OPEN (detection still triggers). Why: the
        --demo bird and scripted sources do not stamp detections yet (`stamp_s` stays None), so
        dropping unstamped input would silently disable avoidance for every current source -- the
        exact opposite of the gate's safety intent. Once those sources stamp, the gate tightens
        naturally with no code change here."""
        det = _bird(33, 30)  # the shared helper builds an unstamped Detection
        m = self.pol.decide(det, _drone(30, 30), self.geo, now_s=1000.0)
        self.assertIs(m.decision, Decision.DIVERT)

    def test_gate_off_by_default_ignores_stamps(self):
        # default policy (max_detection_age_s=None): even an ancient stamp changes nothing
        pol = AvoidancePolicy()
        det = Detection(position_enu=(33.0, 30.0, 15.0), frame_id=10, track_id="bird_0",
                        stamp_s=0.0)
        m = pol.decide(det, _drone(30, 30), self.geo, now_s=1.0e6)
        self.assertIs(m.decision, Decision.DIVERT)

    def test_gate_on_without_now_s_keeps_current_behavior(self):
        # gate configured but the caller supplied no clock -> age is uncomputable -> fail open
        det = Detection(position_enu=(33.0, 30.0, 15.0), frame_id=10, track_id="bird_0",
                        stamp_s=0.0)
        m = self.pol.decide(det, _drone(30, 30), self.geo)
        self.assertIs(m.decision, Decision.DIVERT)

    def test_stale_bird_does_not_mask_fresh_bird(self):
        # one stale + one fresh in-cylinder bird: the fresh one still triggers; the stale one is
        # dropped from the threat set entirely (not just demoted) and shows up in the drop log
        stale = Detection(position_enu=(33.0, 30.0, 15.0), frame_id=1, track_id="stale_bird",
                          stamp_s=90.0)
        fresh = Detection(position_enu=(30.0, 33.0, 15.0), frame_id=2, track_id="fresh_bird",
                          stamp_s=99.9)
        m = self.pol.decide_multi([stale, fresh], _drone(30, 30), self.geo, now_s=100.0)
        self.assertIn(m.decision, (Decision.DIVERT, Decision.HOLD))
        self.assertEqual(m.triggering_detection.track_id, "fresh_bird")
        self.assertNotIn("stale_bird", m.debug.get("threat_ids", []))
        self.assertEqual(m.debug.get("n_stale_dropped"), 1)
        self.assertIn("stale_bird", m.debug.get("stale_ids", []))


if __name__ == "__main__":
    unittest.main()
