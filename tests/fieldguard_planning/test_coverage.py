"""Coverage-grid + coverage-debt ledger tests (Week 2 safety scaffolding).

These are RUNNABLE NOW: they are pure geometry / bookkeeping over the CURRENT mission path, field
polygon, and static-obstacle map -- no Gazebo/ROS 2, no not-yet-built avoidance loop. They pin the
baseline the Week 3-4 avoidance loop must never regress below:

  * the NOMINAL boustrophedon plan already covers every field cell (if it didn't, coverage would be
    broken before avoidance is even in the picture);
  * the coverage checker actually has teeth (a narrower swath opens detectable gaps -- negative
    control, so a passing coverage test is not vacuously green);
  * the coverage-debt ledger invariant catches a silently-skipped cell, a double-logged cell, and a
    lie about coverage.

stdlib unittest only (see test_geofence.py header for why).
Run:  python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.coverage import (  # noqa: E402
    CELL_COVERED, CELL_DEBT, DEFAULT_SWATH_HALF_WIDTH_M,
    build_grid, check_ledger, coverage_from_path, derive_swath_half_width_m,
    ledger_from_covered_map, load_field_polygon,
)
from fieldguard_planning.mission_waypoints import mission_xy_path, parse_qgc_wpl  # noqa: E402

FIELD_POLYGON = REPO_ROOT / "config" / "field_polygon.json"
MISSION = REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints"


def _nominal_path():
    import json
    field = json.loads(FIELD_POLYGON.read_text())
    items = parse_qgc_wpl(MISSION)
    return mission_xy_path(items, field["home_lat"], field["home_lon"])


class TestGrid(unittest.TestCase):
    def test_grid_is_deterministic_and_covers_field(self):
        poly = load_field_polygon(FIELD_POLYGON)
        g1 = build_grid(poly)
        g2 = build_grid(poly)
        self.assertEqual([c.cell_id for c in g1], [c.cell_id for c in g2])
        # 75x60 field at 2.5 m cells, rectangle -> exactly 30 x 24 = 720 cells, all centers inside.
        self.assertEqual(len(g1), 720)

    def test_cell_ids_unique(self):
        cells = build_grid(load_field_polygon(FIELD_POLYGON))
        ids = [c.cell_id for c in cells]
        self.assertEqual(len(ids), len(set(ids)))


class TestNominalCoverage(unittest.TestCase):
    """The core baseline: the nominal boustrophedon plan (no avoidance) leaves ZERO cells uncovered.
    This is the bar the Week 3-4 avoidance loop must not silently drop below."""

    def setUp(self):
        self.cells = build_grid(load_field_polygon(FIELD_POLYGON))
        self.path = _nominal_path()

    def test_nominal_mission_covers_every_cell(self):
        covered = coverage_from_path(self.cells, self.path, DEFAULT_SWATH_HALF_WIDTH_M)
        uncovered = [cid for cid, hit in covered.items() if not hit]
        self.assertEqual(uncovered, [],
                         msg=f"{len(uncovered)} field cell(s) NOT covered by the nominal plan at "
                             f"swath +/-{DEFAULT_SWATH_HALF_WIDTH_M} m: {uncovered[:8]}")

    def test_negative_control_narrow_swath_opens_gaps(self):
        # If the camera swath is narrower still, strips between lanes go uncovered. Proves the
        # coverage check can FAIL -- a passing coverage test is therefore meaningful. 5.0 m is
        # narrow enough that a 2.5 m cell CENTRE lands in the gap (the true 6.886 m swath leaves a
        # 1.23 m strip, which no cell centre falls in -- see TestSwathComesFromTheCamera).
        narrow = 5.0
        covered = coverage_from_path(self.cells, self.path, narrow)
        uncovered = [cid for cid, hit in covered.items() if not hit]
        self.assertGreater(len(uncovered), 0,
                           msg="coverage checker failed to detect gaps with a sub-spacing swath -- "
                               "the checker would be vacuous")


class TestSwathComesFromTheCamera(unittest.TestCase):
    """The swath half-width is DERIVED from the sensor, never from lane-spacing/2 prose (ADR-016).

    Until 2026-08-25 it was 7.5 m = half the 15 m lane pitch -- an assumption the module docstring
    itself flagged as unmeasured, and it over-claimed: the camera images 13.772 m across track, so
    every 15 m lane pair leaves a 1.228 m strip no frame ever saw. `coverage_from_path` was booking
    that strip as COVERED."""

    def _config(self):
        import json
        cam = json.loads((REPO_ROOT / "config" / "ndvi_camera.json").read_text())
        alt = json.loads(FIELD_POLYGON.read_text())["mission_altitude_m"]
        return cam, alt

    def test_default_is_the_camera_derived_cross_track_half_swath(self):
        """Recomputed here from the raw config, deliberately WITHOUT calling the derivation -- a
        test that reuses the code under test could only prove it is self-consistent."""
        import math
        cam, alt = self._config()
        c = cam["camera"]
        fx = (c["image_width_px"] / 2.0) / math.tan(c["horizontal_fov_rad"] / 2.0)
        depth = alt + cam["mount"]["mount_pose_xyz_rpy"][2]      # camera hangs 0.08 m under the body
        self.assertAlmostEqual(DEFAULT_SWATH_HALF_WIDTH_M, depth * (c["image_height_px"] / 2.0) / fx,
                               places=9)
        self.assertAlmostEqual(DEFAULT_SWATH_HALF_WIDTH_M, 6.886077, places=5)  # today's number

    def test_it_agrees_with_the_projects_one_intrinsics_primitive(self):
        """`ndvi_georef.CameraIntrinsics.from_config` owns the fx/fy formula for the whole project;
        coverage.py restates it (stdlib, and ndvi_georef imports coverage). Pinned equal so the
        restatement cannot drift into a second camera model."""
        from fieldguard_planning.ndvi_georef import CameraIntrinsics
        cam, alt = self._config()
        c = cam["camera"]
        intr = CameraIntrinsics.from_config(c["image_width_px"], c["image_height_px"],
                                            c["horizontal_fov_rad"])
        depth = alt + cam["mount"]["mount_pose_xyz_rpy"][2]
        self.assertAlmostEqual(derive_swath_half_width_m(alt), depth * intr.cy / intr.fy, places=9)

    def test_cross_track_is_the_short_image_axis(self):
        """The ADR-007 mount extrinsic puts image u+ along body +X (the flight direction), so lanes
        are separated across the 480 px axis. Taking the swath off the 640 px axis would over-claim
        by a third and re-open exactly the strip this fix closes."""
        cam, alt = self._config()
        c = cam["camera"]
        along = derive_swath_half_width_m(alt) * c["image_width_px"] / c["image_height_px"]
        self.assertLess(derive_swath_half_width_m(alt), along)
        self.assertAlmostEqual(along, 9.181436, places=5)

    def test_it_scales_with_altitude_through_the_mount_offset(self):
        # Twice the DEPTH is twice the swath -- and the mount offset lives in the depth, so doubling
        # the ALTITUDE gives slightly MORE than double (the fixed 0.08 m is a smaller share of 30 m).
        mount_z = self._config()[0]["mount"]["mount_pose_xyz_rpy"][2]      # -0.08 m
        self.assertAlmostEqual(derive_swath_half_width_m(2 * (15.0 + mount_z) - mount_z),
                               2 * derive_swath_half_width_m(15.0), places=9)
        self.assertGreater(derive_swath_half_width_m(30.0), 2 * derive_swath_half_width_m(15.0))

    def test_the_720_cell_guarantee_survives_the_true_swath_but_only_just(self):
        """The honest state of the coverage guarantee: at 15 m lane pitch the true swath does NOT
        meet between lanes, and 720/720 holds only because 2.5 m cell CENTRES sit at most 6.25 m
        from a lane -- 0.636 m of quantization margin. Narrow the swath (lower cruise, tighter FOV)
        or refine the grid and this test is the one that says so before a flight does."""
        cells = build_grid(load_field_polygon(FIELD_POLYGON))
        covered = coverage_from_path(cells, _nominal_path(), DEFAULT_SWATH_HALF_WIDTH_M)
        self.assertEqual([cid for cid, hit in covered.items() if not hit], [])
        worst = max(min(abs(cell.cx_m - lane) for lane in (0, 15, 30, 45, 60, 75)) for cell in cells)
        self.assertAlmostEqual(worst, 6.25, places=9)
        self.assertLess(worst, DEFAULT_SWATH_HALF_WIDTH_M)
        self.assertLess(DEFAULT_SWATH_HALF_WIDTH_M, 7.5,      # the strip that used to be over-claimed
                        msg="the derivation drifted back onto the lane-spacing/2 assumption")


class TestCoverageDebtLedger(unittest.TestCase):
    """The executable coverage-debt invariant (eval/scenarios/README.md). These prove the invariant
    catches exactly the failure modes it exists for."""

    def setUp(self):
        self.cells = build_grid(load_field_polygon(FIELD_POLYGON))
        self.grid_ids = [c.cell_id for c in self.cells]

    def test_perfect_nominal_ledger_passes_with_zero_debt(self):
        covered = coverage_from_path(self.cells, _nominal_path(), DEFAULT_SWATH_HALF_WIDTH_M)
        ledger = ledger_from_covered_map(covered)
        result = check_ledger(self.grid_ids, ledger)
        self.assertTrue(result.ok, msg="; ".join(result.errors))
        self.assertEqual(result.debt_count, 0)
        self.assertEqual(result.covered_count, len(self.grid_ids))

    def test_explicit_debt_is_allowed_v1(self):
        # ADR-002 v1 bar: dropping a cell is allowed IF it is explicitly logged as debt, not absent.
        ledger = ledger_from_covered_map(
            coverage_from_path(self.cells, _nominal_path(), DEFAULT_SWATH_HALF_WIDTH_M))
        ledger[0]["status"] = CELL_DEBT  # loop chose to drop one cell but LOGGED it
        result = check_ledger(self.grid_ids, ledger)
        self.assertTrue(result.ok, msg="explicit debt must satisfy the v1 invariant")
        self.assertEqual(result.debt_count, 1)

    def test_silently_skipped_cell_is_caught(self):
        # THE headline bug: a cell simply missing from the ledger (dropped, not logged) must fail.
        ledger = ledger_from_covered_map(
            coverage_from_path(self.cells, _nominal_path(), DEFAULT_SWATH_HALF_WIDTH_M))
        dropped = ledger.pop()  # cell vanishes from the plan with no record at all
        result = check_ledger(self.grid_ids, ledger)
        self.assertFalse(result.ok)
        self.assertIn(dropped["cell_id"], result.missing)

    def test_double_logged_cell_is_caught(self):
        ledger = ledger_from_covered_map(
            coverage_from_path(self.cells, _nominal_path(), DEFAULT_SWATH_HALF_WIDTH_M))
        ledger.append(dict(ledger[0]))  # same cell logged twice -> ambiguous accounting
        result = check_ledger(self.grid_ids, ledger)
        self.assertFalse(result.ok)
        self.assertTrue(result.duplicates)

    def test_unknown_status_is_caught(self):
        ledger = ledger_from_covered_map(
            coverage_from_path(self.cells, _nominal_path(), DEFAULT_SWATH_HALF_WIDTH_M))
        ledger[0]["status"] = "requeued"  # requeued is an EVENT, never a terminal status
        result = check_ledger(self.grid_ids, ledger)
        self.assertFalse(result.ok)
        self.assertTrue(result.bad_status)


if __name__ == "__main__":
    unittest.main()
