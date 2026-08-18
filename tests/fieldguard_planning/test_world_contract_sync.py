"""The Gazebo world and the geofence contract must describe the SAME trees (ADR-001).

`config/static_obstacles.json`'s 'obstacles' array is what flight-software's geofence actually
consumes; `sim/worlds/farmguard_field.sdf` is what Gazebo actually draws. Both come out of one
`scripts/gen_farm_world.py` run, but only the WORLD carried the real canopy geometry -- the export
computed `height_m` as trunk_height_m + canopy_height_m (3.5 m) while the world drew a canopy
SPHERE of canopy_radius_m centred at trunk_height_m + canopy_height_m/2, topping out at 3.8 m.
That 0.3 m gap is fail-dangerous, not cosmetic: geofence.py's vertical band is
`z_m .. z_m + height_m + margin`, so a manoeuvre at 3.6 m cleared as "above the tree" would have
been inside the canopy (2026-08-18 audit item 14).

These tests read the two COMMITTED artifacts and cross-check them against each other, so the fix
can't silently regress and neither artifact can be regenerated alone.

stdlib unittest. Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import filecmp
import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.geofence import GeofenceMap  # noqa: E402
from gen_farm_world import canopy_center_z_m, tree_height_m  # noqa: E402

WORLD = REPO_ROOT / "sim" / "worlds" / "farmguard_field.sdf"
STATIC_OBSTACLES = REPO_ROOT / "config" / "static_obstacles.json"
GENERATOR = REPO_ROOT / "scripts" / "gen_farm_world.py"

EXPECTED_TREE_HEIGHT_M = 3.8  # canopy sphere top with today's tree_defaults


def world_tree_tops_m():
    """{model name -> world-frame z of the top of the canopy sphere} parsed out of the SDF."""
    root = ET.parse(WORLD).getroot()
    tops = {}
    for model in root.find("world").findall("model"):
        name = model.get("name")
        if not name.startswith("tree_"):
            continue
        model_z = float(model.find("pose").text.split()[2])
        canopy = next(l for l in model.findall("link") if l.get("name") == "canopy")
        canopy_z = float(canopy.find("pose").text.split()[2])
        radii = {float(s.find("radius").text) for s in canopy.iter("sphere")}
        assert len(radii) == 1, f"{name}: collision/visual canopy radii disagree: {radii}"
        tops[name] = model_z + canopy_z + radii.pop()
    return tops


class TestTreeHeightContract(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(STATIC_OBSTACLES.read_text())
        self.obstacles = {o["id"]: o for o in self.cfg["obstacles"]}
        self.tops = world_tree_tops_m()

    def test_same_trees_in_world_and_contract(self):
        self.assertEqual(set(self.tops), set(self.obstacles))
        self.assertEqual(len(self.tops), 18)

    def test_contract_height_equals_what_the_world_draws(self):
        """The whole point of ADR-001: the export describes exactly what is physically in the world.
        An export that under-reports height is worse than no export -- it reads as authoritative."""
        for tree_id, top_m in sorted(self.tops.items()):
            self.assertAlmostEqual(
                self.obstacles[tree_id]["height_m"], top_m, places=6,
                msg=f"{tree_id}: contract says height_m={self.obstacles[tree_id]['height_m']} m but "
                    f"the world draws its canopy top at {top_m} m")

    def test_height_is_the_canopy_sphere_top_not_trunk_plus_canopy_height(self):
        """Pins the actual number AND the wrong-but-plausible formula that produced 3.5 m."""
        defaults = self.cfg["tree_defaults"]
        naive = defaults["trunk_height_m"] + defaults["canopy_height_m"]
        self.assertAlmostEqual(naive, 3.5, places=6)
        self.assertAlmostEqual(tree_height_m(defaults), EXPECTED_TREE_HEIGHT_M, places=6)
        self.assertAlmostEqual(
            tree_height_m(defaults),
            canopy_center_z_m(defaults) + defaults["canopy_radius_m"], places=9)
        for tree_id, obs in sorted(self.obstacles.items()):
            self.assertAlmostEqual(obs["height_m"], EXPECTED_TREE_HEIGHT_M, places=6,
                                   msg=f"{tree_id} height_m regressed")

    def test_vertical_exclusion_band_now_covers_the_whole_canopy(self):
        """The consequence that matters: geofence.py bands z in [z_m, z_m + height_m + margin], so
        a point just under the real canopy top must no longer read as clear at zero margin."""
        gmap = GeofenceMap.from_file(STATIC_OBSTACLES)
        x, y, _ = self.cfg["obstacles"][0]["pos_m"]
        just_under_canopy_top = EXPECTED_TREE_HEIGHT_M - 0.05
        self.assertFalse(gmap.is_safe_3d((x, y, just_under_canopy_top), vertical_margin_m=0.0))
        self.assertTrue(gmap.is_safe_3d((x, y, EXPECTED_TREE_HEIGHT_M + 0.05),
                                        vertical_margin_m=0.0))


class TestGeneratorOutputsAreCurrentAndDeterministic(unittest.TestCase):
    """Regenerating must reproduce the committed artifacts byte-for-byte, twice. Catches both a
    hand-edited 'obstacles' array and a generator whose output depends on run order/dict ordering."""

    def _run(self, out_dir: Path):
        out_dir.mkdir(parents=True, exist_ok=True)
        obstacles_out = out_dir / "static_obstacles.json"
        world_out = out_dir / "farmguard_field.sdf"
        subprocess.run(
            [sys.executable, str(GENERATOR),
             "--obstacles-out", str(obstacles_out), "--world-out", str(world_out)],
            check=True, capture_output=True, cwd=REPO_ROOT)
        return obstacles_out, world_out

    def test_regen_matches_committed_artifacts_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            a_obs, a_world = self._run(Path(td) / "a")
            b_obs, b_world = self._run(Path(td) / "b")
            self.assertEqual(a_obs.read_bytes(), b_obs.read_bytes(), "obstacles regen not stable")
            self.assertEqual(a_world.read_bytes(), b_world.read_bytes(), "world regen not stable")
            self.assertTrue(filecmp.cmp(a_obs, STATIC_OBSTACLES, shallow=False),
                            "config/static_obstacles.json is stale -- rerun scripts/gen_farm_world.py")
            self.assertTrue(filecmp.cmp(a_world, WORLD, shallow=False),
                            "sim/worlds/farmguard_field.sdf is stale -- rerun scripts/gen_farm_world.py")


if __name__ == "__main__":
    unittest.main()
