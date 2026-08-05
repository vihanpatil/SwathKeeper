"""Unit tests for src/fieldguard_planning/geofence.py.

stdlib unittest only (no pytest dependency assumed -- see the Week 2 environment-honesty note:
these are pure-logic tests and must run without a venv or the Docker/Gazebo/ROS 2 stack).

Run:
    python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.geofence import GeofenceMap, Obstacle, DEFAULT_STATIC_OBSTACLES  # noqa: E402


def make_tree(id_, x, y, radius=2.0):
    return Obstacle(id=id_, type="tree", row_id=0, x_m=x, y_m=y, z_m=0.0,
                     obstacle_radius_m=radius, canopy_radius_m=1.3, height_m=3.5)


class TestGeofenceMapSynthetic(unittest.TestCase):
    """Hand-checked cases on a small synthetic obstacle set (independent of the real
    config/static_obstacles.json contents, so these keep testing the *logic* even if the field
    layout changes)."""

    def setUp(self):
        # One tree at (15, 5), obstacle_radius_m=2.0 -- matches tree_row0_0 in the real contract.
        self.map = GeofenceMap([make_tree("tree_row0_0", 15.0, 5.0, radius=2.0)])

    def test_point_inside_tree_radius_is_excluded(self):
        # 1m from tree center, radius 2.0m -> inside.
        excluded = self.map.excluding_obstacle(15.0 + 1.0, 5.0)
        self.assertIsNotNone(excluded)
        self.assertEqual(excluded.id, "tree_row0_0")
        self.assertTrue(self.map.is_point_excluded(16.0, 5.0))

    def test_point_on_exact_boundary_is_excluded(self):
        # Exactly obstacle_radius_m away -> clearance == 0 -> excluded (boundary is inclusive by
        # design: "clearance_m <= 0.0 => excluded", see geofence.py).
        self.assertTrue(self.map.is_point_excluded(15.0 + 2.0, 5.0))

    def test_point_far_from_tree_is_clear(self):
        far_x, far_y = 15.0, 40.0  # 35m north of the tree, radius only 2m
        self.assertFalse(self.map.is_point_excluded(far_x, far_y))
        obstacle, clearance = self.map.point_clearance(far_x, far_y)
        self.assertAlmostEqual(clearance, 35.0 - 2.0, places=6)

    def test_segment_clipping_tree_is_flagged_even_with_clear_endpoints(self):
        # A north-south leg at x=15 running from y=0 to y=10 passes directly through the tree at
        # (15, 5) even though neither endpoint is within 2m of it in the y-direction alone.
        result = self.map.segment_clearance((15.0, 0.0), (15.0, 10.0))
        self.assertLess(result.clearance_m, 0.0)
        self.assertEqual(result.obstacle.id, "tree_row0_0")
        # closest point on the segment is (15,5), exactly the tree center -> clearance = -radius
        self.assertAlmostEqual(result.clearance_m, -2.0, places=6)

    def test_segment_well_clear_of_tree(self):
        # A leg entirely on the other side of the field, 20m+ east of the tree.
        result = self.map.segment_clearance((40.0, 0.0), (40.0, 60.0))
        self.assertGreater(result.clearance_m, 0.0)
        self.assertAlmostEqual(result.clearance_m, 25.0 - 2.0, places=6)


class TestGeofenceMapFromRealContract(unittest.TestCase):
    """Cases against the real config/static_obstacles.json contract file, so a regression in
    that file's schema (or a bad edit) fails a test, not just a runtime surprise."""

    def setUp(self):
        self.map = GeofenceMap.from_file(DEFAULT_STATIC_OBSTACLES)

    def test_loads_18_trees(self):
        self.assertEqual(len(self.map), 18)

    def test_known_tree_center_is_excluded(self):
        # tree_row1_2 per config/static_obstacles.json: pos_m [40.0, 25.0, 0.0], radius 2.0.
        self.assertTrue(self.map.is_point_excluded(40.0, 25.0))
        excluded = self.map.excluding_obstacle(40.0, 25.0)
        self.assertEqual(excluded.id, "tree_row1_2")

    def test_point_on_mission_path_between_lanes_is_clear(self):
        # Mission lane x=30 (a boustrophedon turn lane, see config/missions/boustrophedon.waypoints)
        # sits between tree rows at x=15 and x=40. At y=25 the nearest tree is tree_row1_2 at
        # (40, 25): distance 10m, radius 2.0m -> 8m clearance, hand-checked.
        self.assertFalse(self.map.is_point_excluded(30.0, 25.0))
        obstacle, clearance = self.map.point_clearance(30.0, 25.0)
        self.assertEqual(obstacle.id, "tree_row1_2")
        self.assertGreater(clearance, 0.0)
        self.assertAlmostEqual(clearance, 10.0 - 2.0, places=6)


if __name__ == "__main__":
    unittest.main()
