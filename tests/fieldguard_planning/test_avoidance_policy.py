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


if __name__ == "__main__":
    unittest.main()
