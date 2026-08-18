"""Mission-vs-geofence safety pins (Week 2 scaffolding), RUNNABLE NOW.

`scripts/check_mission_geofence.py` PRINTS clearances; this file turns the safety-relevant facts into
ASSERTIONS so a future edit to the mission, the field, or the tree map cannot silently change them.

The non-obvious fact these tests pin (found while building this scaffolding):
  The nominal boustrophedon lane at x=15 (leg 4) flies STRAIGHT THROUGH orchard row 0 in XY --
  min XY clearance -1.997 m. That is a real 2D geofence breach. It is deemed safe TODAY *only*
  because the mission flies at 15 m and the trees are 3.8 m tall (11.2 m vertical separation). So:

    - The XY breach is EXPECTED and localised (row 0 lane only). A NEW XY breach appearing on any
      OTHER leg is a regression and must fail (`test_only_row0_lane_breaches_xy`).
    - The safety of that breach rests ENTIRELY on vertical separation, which these tests assert
      explicitly (`test_vertical_separation_is_the_actual_safety_basis`). SAFETY GAP for Week 3-4:
      geofence.py is XY-only, and any avoidance/imaging manoeuvre that DESCENDS into the 3.8 m tree
      band turns this benign 2D overlap into a collision. The avoidance-path geofence assertion must
      therefore be 3D-aware (or must assert the manoeuvre holds altitude) -- see the pending tests
      in test_safety_scenarios_pending.py.

stdlib unittest only. Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.geofence import GeofenceMap  # noqa: E402
from fieldguard_planning.mission_waypoints import mission_xy_path, parse_qgc_wpl  # noqa: E402

FIELD_POLYGON = REPO_ROOT / "config" / "field_polygon.json"
MISSION = REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints"
STATIC_OBSTACLES = REPO_ROOT / "config" / "static_obstacles.json"

TREE_HEIGHT_M = 3.8           # config/static_obstacles.json height_m (uniform for all trees)
MIN_VERTICAL_MARGIN_M = 5.0   # required air gap between mission altitude and tallest obstacle


class TestNominalMissionGeofence(unittest.TestCase):
    def setUp(self):
        field = json.loads(FIELD_POLYGON.read_text())
        self.mission_alt_m = field["mission_altitude_m"]
        items = parse_qgc_wpl(MISSION)
        self.path = mission_xy_path(items, field["home_lat"], field["home_lon"])
        self.geofence = GeofenceMap.from_file(STATIC_OBSTACLES)
        self.leg_results = self.geofence.check_path(self.path)

    def test_only_row0_lane_breaches_xy(self):
        """Exactly the by-design row-0 overlap breaches XY; nothing else does. A breach anywhere
        else means a lane started clipping a tree it used to clear -- a regression to surface."""
        breaches = [(i, r) for i, r in self.leg_results if r.clearance_m <= 0.0]
        self.assertEqual(len(breaches), 1,
                         msg=f"expected exactly 1 known XY breach (row-0 lane), got {len(breaches)}: "
                             f"{[(i, r.obstacle.id, round(r.clearance_m, 3)) for i, r in breaches]}")
        i, r = breaches[0]
        self.assertEqual(r.obstacle.row_id, 0,
                         msg=f"the one known XY breach must be an orchard-row-0 tree, got {r.obstacle.id}")
        # The breaching leg is the vertical lane at x=15 (both endpoints at x=15). Tolerance is
        # loose because the lat/lon round-trip lands the lane at 14.997 m, not exactly 15.
        p1, p2 = self.path[i], self.path[i + 1]
        self.assertAlmostEqual(p1[0], 15.0, delta=0.05)
        self.assertAlmostEqual(p2[0], 15.0, delta=0.05)

    def test_vertical_separation_is_the_actual_safety_basis(self):
        """The row-0 XY breach is only safe because of altitude. Pin that so lowering the mission
        altitude (or growing the trees) toward the danger band fails loudly here."""
        vertical_sep = self.mission_alt_m - TREE_HEIGHT_M
        self.assertGreaterEqual(
            vertical_sep, MIN_VERTICAL_MARGIN_M,
            msg=f"mission altitude {self.mission_alt_m} m vs tree height {TREE_HEIGHT_M} m leaves "
                f"only {vertical_sep} m -- below the {MIN_VERTICAL_MARGIN_M} m margin the XY breach "
                f"relies on. The nominal mission is no longer safe by altitude alone.")

    def test_geofence_map_matches_world_contract(self):
        """18 trees, all with a nonzero exclusion radius -- guards against a truncated/edited map
        silently disabling exclusion for some trees."""
        self.assertEqual(len(self.geofence), 18)
        for obs in self.geofence.obstacles:
            self.assertGreater(obs.obstacle_radius_m, 0.0, msg=f"{obs.id} has non-positive radius")


if __name__ == "__main__":
    unittest.main()
