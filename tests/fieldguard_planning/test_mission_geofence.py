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
      explicitly (`test_vertical_separation_is_the_actual_safety_basis`). That gap CLOSED on
      2026-09-11 (R8, ADR-022 am. 2): the gate is 3D and armed in CI, and `TestMissionGeofence3DGate`
      below is the adversarial half -- the same mission at 3.0 m, at the 4.80 m band edge, and a
      climb that crosses a tree footprint mid-climb all have to come back UNSAFE, and the verdict has
      to come from the executor's own `unsafe_obstacle_3d` (proved by mutation), not a re-derivation.

stdlib unittest only. Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import inspect
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))   # the gate lives in scripts/, not src/

import check_mission_geofence as gate  # noqa: E402
from fieldguard_planning.avoidance_executor import DEFAULT_VERTICAL_MARGIN_M  # noqa: E402
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402
from fieldguard_planning.mission_waypoints import (  # noqa: E402
    M_PER_DEG_LAT, NAV_TAKEOFF, NAV_WAYPOINT, m_per_deg_lon, mission_xy_path, mission_xyz_path,
    parse_qgc_wpl,
)

FIELD_POLYGON = REPO_ROOT / "config" / "field_polygon.json"
MISSION = REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints"
STATIC_OBSTACLES = REPO_ROOT / "config" / "static_obstacles.json"

TREE_HEIGHT_M = 3.8           # config/static_obstacles.json height_m (uniform for all trees)
MIN_VERTICAL_MARGIN_M = 5.0   # required air gap between mission altitude and tallest obstacle

HOME_LAT, HOME_LON = -35.363262, 149.165237
# The top of tree_row0_0's 3D exclusion band, written out LITERALLY on purpose: a boundary pin that
# recomputes itself from the same constants the gate uses cannot catch a change to those constants.
# Provenance (asserted in test_band_edge_is_the_canopy_top_plus_the_policy_margin): pos_m z 0.0 +
# height_m 3.8 + the executor's vertical margin 1.0.
BAND_TOP_M = 4.80


def _run_gate(*argv):
    """Run the gate in-process and return (exit_code, combined stdout+stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = gate.main(list(argv))
    return code, out.getvalue() + err.getvalue()


def _to_ll(east_m, north_m):
    """ENU metres -> lat/lon, the inverse the mission generator writes (module constants, not a
    second projection)."""
    return HOME_LAT + north_m / M_PER_DEG_LAT, HOME_LON + east_m / m_per_deg_lon(HOME_LAT)


def _wpl_line(seq, command, lat, lon, alt, frame=3, current=0):
    return "\t".join([str(seq), str(current), str(frame), str(command), "0", "0", "0", "0",
                      f"{lat:.7f}", f"{lon:.7f}", f"{alt:.6f}", "1"])


def _mission_at_altitude(alt_m, tmpdir):
    """The COMMITTED mission with every airborne item's altitude rewritten, nothing else touched.

    Leg numbering, lane geometry and the tree map are therefore identical to the committed mission's,
    so "leg 4 now fails" is attributable to altitude and to nothing else."""
    lines = MISSION.read_text().splitlines()
    out = [lines[0]]
    for line in lines[1:]:
        if not line.strip():
            continue
        f = line.split("\t")
        if int(f[0]) != 0 and int(f[3]) in (NAV_TAKEOFF, NAV_WAYPOINT):
            f[10] = f"{alt_m:.6f}"
        out.append("\t".join(f))
    path = Path(tmpdir) / f"mission_alt_{alt_m:.2f}.waypoints"
    path.write_text("\n".join(out) + "\n")
    return path


def _write_mission(tmpdir, name, rows):
    """rows: (command, east_m, north_m, alt_m) after the home placeholder row."""
    lines = ["QGC WPL 110", _wpl_line(0, NAV_WAYPOINT, HOME_LAT, HOME_LON, 0.0, frame=0, current=1)]
    for i, (command, east, north, alt) in enumerate(rows, start=1):
        lat, lon = _to_ll(east, north)
        lines.append(_wpl_line(i, command, lat, lon, alt))
    path = Path(tmpdir) / name
    path.write_text("\n".join(lines) + "\n")
    return path


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


class TestMissionGeofence3DGate(unittest.TestCase):
    """R8 (ADR-022 am. 2): `scripts/check_mission_geofence.py` as a GATE, not a printout.

    Until 2026-09-11 the script exited 1 on the committed mission -- the XY overlap on leg 4 -- so CI
    ran it `|| true` and it could not fail. These tests hold the new contract: the committed mission
    (XY overlap, cleared by 10.2 m of altitude) PASSES, and a mission that actually enters a tree's
    3D volume FAILS -- by the executor's own rule, at a pinned boundary, and with the intermediate
    samples that a climb leg needs.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    @staticmethod
    def _leg_line(out, i):
        for line in out.splitlines():
            if line.strip().startswith(f"leg {i:2d} "):
                return line
        raise AssertionError(f"no 'leg {i:2d}' line in the gate's output:\n{out}")

    def test_committed_mission_passes_with_leg4_cleared_by_altitude(self):
        """(a) The mission every committed flight log flew: leg 4's -1.997 m XY overlap is REPORTED,
        the 15 m cruise clears the 4.80 m band by 10.2 m, and the gate exits 0."""
        code, out = _run_gate()
        self.assertEqual(code, 0, msg=f"the committed mission must PASS the 3D gate:\n{out}")
        leg4 = self._leg_line(out, 4)
        self.assertIn("-1.997", leg4, msg=f"the XY overlap must stay REPORTED, not hidden: {leg4}")
        self.assertIn("+10.200", leg4, msg=f"vertical clearance 15.0 - 4.80 must be printed: {leg4}")
        self.assertIn("tree_row0_0", leg4)
        self.assertIn("CLEAR-BY-ALTITUDE", leg4)
        self.assertIn("PASS", out)
        self.assertNotIn("UNSAFE", out)

    def test_same_mission_at_3m_fails_naming_the_leg_and_the_tree(self):
        """(b) The identical mission flown at 3.0 m -- inside the band -- must FAIL, and must say
        WHICH leg and WHICH tree. One leg, not fourteen: only lane x=15 overlaps row 0."""
        mission = _mission_at_altitude(3.0, self.tmp.name)
        code, out = _run_gate("--mission", str(mission))
        self.assertEqual(code, 1, msg=f"a 3.0 m cruise straight down row 0 must FAIL:\n{out}")
        self.assertIn("FAIL", out)
        # Southbound down row 0, so tree_row0_5 (y=55) is entered first -- and all SIX are named:
        # a leg that flies down a whole orchard row breaches six volumes, and naming one would lie.
        self.assertIn("leg 4 (tree_row0_5, tree_row0_4, tree_row0_3, tree_row0_2, tree_row0_1, "
                      "tree_row0_0)", out,
                      msg=f"the failure must name the leg and every obstacle it enters:\n{out}")
        self.assertIn("UNSAFE", self._leg_line(out, 4))
        self.assertEqual(out.count("*** UNSAFE"), 1,
                         msg=f"exactly one leg enters a tree volume at 3.0 m:\n{out}")

    def test_band_edge_is_the_canopy_top_plus_the_policy_margin(self):
        """(c) The boundary, both sides: 4.80 m FAILS (the rule's band is inclusive) and 4.81 m
        PASSES -- plus the provenance of 4.80, so changing height_m or the margin cannot move the
        boundary silently past a test that recomputes itself."""
        tree = json.loads(STATIC_OBSTACLES.read_text())["obstacles"][0]
        self.assertEqual(tree["id"], "tree_row0_0")
        self.assertEqual(tree["pos_m"][2], 0.0)
        self.assertEqual(tree["height_m"], TREE_HEIGHT_M)         # 3.8
        self.assertEqual(DEFAULT_VERTICAL_MARGIN_M, 1.0)
        self.assertAlmostEqual(tree["pos_m"][2] + tree["height_m"] + DEFAULT_VERTICAL_MARGIN_M,
                               BAND_TOP_M, places=9)
        at_edge, out_edge = _run_gate("--mission", str(_mission_at_altitude(BAND_TOP_M, self.tmp.name)))
        self.assertEqual(at_edge, 1, msg=f"{BAND_TOP_M} m is INSIDE the band and must fail:\n{out_edge}")
        above, out_above = _run_gate("--mission", str(_mission_at_altitude(4.81, self.tmp.name)))
        self.assertEqual(above, 0, msg=f"4.81 m is 1 cm above the band and must pass:\n{out_above}")

    def test_a_climb_that_crosses_a_tree_footprint_is_caught_between_the_endpoints(self):
        """(d) The case endpoints cannot see: a leg that starts clear on the ground at (0,5) and ends
        clear at 15 m over (60,5), but crosses tree_row0_0's column at ~3.7 m mid-climb. BOTH
        endpoints pass the policy rule -- asserted, so the fixture cannot rot into one that would be
        caught anyway -- and the leg must still FAIL."""
        mission = _write_mission(self.tmp.name, "climb.waypoints",
                                 [(NAV_WAYPOINT, 0.0, 5.0, 0.0), (NAV_WAYPOINT, 60.0, 5.0, 15.0)])
        code, out = _run_gate("--mission", str(mission))
        self.assertEqual(code, 1, msg=f"a climb through row 0's footprint must FAIL:\n{out}")
        self.assertIn("leg 1 (tree_row0_0)", out)

        g = GeofenceMap.from_file(STATIC_OBSTACLES)
        p1, p2 = (0.0, 5.0, 0.0), (60.0, 5.0, 15.0)
        for endpoint in (p1, p2):
            self.assertIsNone(g.unsafe_obstacle_3d(endpoint, DEFAULT_VERTICAL_MARGIN_M),
                              msg=f"{endpoint} is not a clear endpoint, so this fixture proves nothing")
        report = gate.leg_report(g, 1, p1, p2)
        self.assertGreater(report.n_samples, 2)
        self.assertEqual(report.unsafe_obstacle.id, "tree_row0_0")
        self.assertLess(report.unsafe_point[2], BAND_TOP_M)

    def test_a_graze_shorter_than_the_sample_step_is_still_caught(self):
        """(d2) The adversarial version: a level leg at 4.0 m that clips tree_row0_0's column for
        0.40 m -- SHORTER than the 0.5 m step. Every uniform sample misses it (asserted); the gate
        catches it anyway because it SOLVES each tree's in-volume window and samples its midpoint.
        A gate whose resolution is a step size can be walked between."""
        g = GeofenceMap.from_file(STATIC_OBSTACLES)
        p1, p2 = (0.25, 6.99, 4.0), (29.75, 6.99, 4.0)    # 1.99 m off tree_row0_0 (15, 5), r = 2.0
        missed_by_the_grid = [gate.lerp(p1, p2, t) for t in gate.uniform_samples(p1, p2, gate.SAMPLE_STEP_M)]
        self.assertTrue(all(g.unsafe_obstacle_3d(s, DEFAULT_VERTICAL_MARGIN_M) is None
                            for s in missed_by_the_grid),
                        msg="the uniform grid already catches this one -- re-tune the fixture's "
                            "offset, or the chord sampling below is not what is being tested")
        report = gate.leg_report(g, 0, p1, p2)
        self.assertEqual(report.unsafe_obstacle.id, "tree_row0_0")

    def test_the_verdict_comes_from_the_executors_own_3d_rule(self):
        """(e) Mutation: neuter `GeofenceMap.unsafe_obstacle_3d` (the function the executor vets every
        GUIDED setpoint with) and the 3.0 m mission must go green. If it stays red, this gate is
        re-deriving the band on its own and the two can drift apart -- which is the whole bug class
        ADR-022 am. 2 is closing."""
        mission = _mission_at_altitude(3.0, self.tmp.name)
        self.assertEqual(_run_gate("--mission", str(mission))[0], 1, msg="baseline must be RED")
        with mock.patch.object(GeofenceMap, "unsafe_obstacle_3d",
                               lambda self, point_enu, vertical_margin_m=1.0: None):
            code, out = _run_gate("--mission", str(mission))
        self.assertEqual(code, 0, msg=f"with the policy rule neutered the gate must go green -- it "
                                      f"did not, so it is not calling it:\n{out}")

    def test_malformed_inputs_exit_2_rather_than_passing(self):
        """(f) A mission or obstacle map the gate cannot read is exit 2 -- never a silent 0. The
        frame case is the fail-DANGEROUS one: frame 0 altitudes are MSL (~584 m here), which read as
        relative would put every leg hundreds of metres above the trees and pass anything."""
        bad = Path(self.tmp.name) / "not_a_mission.waypoints"
        bad.write_text("this is not a mission\n")
        self.assertEqual(_run_gate("--mission", str(bad))[0], 2)

        msl = Path(self.tmp.name) / "msl.waypoints"
        msl.write_text("\n".join([
            "QGC WPL 110",
            _wpl_line(0, NAV_WAYPOINT, HOME_LAT, HOME_LON, 0.0, frame=0, current=1),
            _wpl_line(1, NAV_WAYPOINT, *_to_ll(15.0, 5.0), alt=584.0, frame=0),
        ]) + "\n")
        code, out = _run_gate("--mission", str(msl))
        self.assertEqual(code, 2, msg=f"an un-interpretable altitude frame must not be flown blind:\n{out}")

        self.assertEqual(_run_gate("--static-obstacles", str(Path(self.tmp.name) / "nope.json"))[0], 2)

        # An export with no height_m used to default every tree to 0.0 m tall -- a margin-high stub
        # a 3 m mission flies clean through, printed with the band formula and a PASS. "We could not
        # tell how tall the trees are" is not a clearance.
        cfg = json.loads(STATIC_OBSTACLES.read_text())
        for tree in cfg["obstacles"]:
            tree.pop("height_m")
        heightless = Path(self.tmp.name) / "no_height.json"
        heightless.write_text(json.dumps(cfg))
        code, out = _run_gate("--mission", str(_mission_at_altitude(3.0, self.tmp.name)),
                              "--static-obstacles", str(heightless))
        self.assertEqual(code, 2, msg=f"trees with no height_m must not be flown through:\n{out}")

    def test_the_vertical_margin_has_exactly_one_home(self):
        """One margin, one home -- and the whole chain, not one link of it. The gate, the executor,
        the policy's planning-side default and the rule's own signature all read
        `geofence.DEFAULT_VERTICAL_MARGIN_M`. They used to be four independent `1.0` literals that
        happened to agree, so moving the flight-side margin would have left the planner behind."""
        from fieldguard_planning import geofence as geofence_mod
        from fieldguard_planning.avoidance_policy import PolicyParams
        one = geofence_mod.DEFAULT_VERTICAL_MARGIN_M
        self.assertIs(gate.VERTICAL_MARGIN_M, one)
        self.assertIs(DEFAULT_VERTICAL_MARGIN_M, one)          # re-exported by avoidance_executor
        self.assertIs(PolicyParams().vertical_margin_m, one)
        for fn in (GeofenceMap.unsafe_obstacle_3d, GeofenceMap.is_safe_3d):
            self.assertIs(inspect.signature(fn).parameters["vertical_margin_m"].default, one,
                          msg=f"{fn.__name__} carries its own margin default")
        self.assertEqual(one, 1.0)

    # The worst false pass the 2026-09-11 QA sweep measured: 57 of 2,500 genuinely-unsafe SLOPED legs
    # were passed by a 0.5 m grid plus circle entry/exit samples (level legs: 0). Kept as the measured
    # lat/lon rather than re-derived from metres, so this is that leg and not a near neighbour.
    SLOPED_LEG = ((-35.3629729, 149.1657321, 2.788477),      # ENU (44.946, 32.183, 2.788)
                  (-35.3629547, 149.1656155, 7.188564))      # ENU (34.361, 34.209, 7.189)

    def test_a_leg_that_climbs_out_of_the_band_mid_circle_is_not_stepped_over(self):
        """(g) THE resolution case. On a leg that CHANGES ALTITUDE the in-volume window is bounded by
        a band crossing rather than by the circle, so it can be shorter than any step -- and its other
        end sits exactly ON the circle, where the rule's `<=` is decided by float rounding. This leg
        crosses tree_row1_3 climbing, is inside for ~0.36 m of path, and used to print
        `CLEAR-BY-ALTITUDE`, `+0.005 m` of vertical clearance and `PASS -- 0 of 2 legs`, exit 0.

        Ground truth comes from the POLICY RULE first, so the fixture cannot rot into a safe leg the
        gate then "correctly" passes. Then the step is widened 10x and 2e9x: the verdict must not
        move, because the window is solved rather than stepped."""
        mission = Path(self.tmp.name) / "sloped.waypoints"
        mission.write_text("\n".join(
            ["QGC WPL 110", _wpl_line(0, NAV_WAYPOINT, HOME_LAT, HOME_LON, 0.0, frame=0, current=1)]
            + [_wpl_line(i, NAV_WAYPOINT, lat, lon, alt)
               for i, (lat, lon, alt) in enumerate(self.SLOPED_LEG, start=1)]) + "\n")
        field = json.loads(FIELD_POLYGON.read_text())
        _, p1, p2 = mission_xyz_path(parse_qgc_wpl(mission), field["home_lat"], field["home_lon"])

        g = GeofenceMap.from_file(STATIC_OBSTACLES)
        n = 20000
        inside = sum(1 for i in range(n + 1)
                     if g.unsafe_obstacle_3d(gate.lerp(p1, p2, i / n), DEFAULT_VERTICAL_MARGIN_M))
        self.assertGreater(inside, 0, msg="the fixture no longer enters a tree: it proves nothing")

        code, out = _run_gate("--mission", str(mission))
        self.assertEqual(code, 1, msg=f"a leg the policy rule says is INSIDE tree_row1_3 for {inside} "
                                      f"of {n + 1} sampled points was passed by the gate -- the "
                                      f"sampling, not the rule, decided that:\n{out}")
        self.assertIn("leg 1 (tree_row1_3)", out)
        # The clearance printed as the REASON it was safe was itself read off the blind samples.
        self.assertIn("MIN VERTICAL CLEARANCE OVER A TREE COLUMN: -0.135 m", out)

        coarse = [gate.lerp(p1, p2, t) for t in gate.uniform_samples(p1, p2, 5.0)]
        self.assertTrue(all(g.unsafe_obstacle_3d(s, DEFAULT_VERTICAL_MARGIN_M) is None for s in coarse),
                        msg="a 5 m grid already catches this leg -- the step is not what is on test")
        for step_m in (gate.SAMPLE_STEP_M, 5.0, 1e9):
            self.assertEqual(
                [o.id for o in gate.leg_report(g, 1, p1, p2, step_m=step_m).unsafe_obstacles],
                ["tree_row1_3"], msg=f"the verdict moved at step_m={step_m}: the gate's resolution "
                                     f"is its step size again, and a step can be walked between")

    def test_an_unmodelled_nav_command_is_refused_not_silently_dropped(self):
        """(h) Same point, same altitude, one field changed. A waypoint inside tree_row0_0 at 3.0 m
        FAILS as NAV_WAYPOINT. As NAV_SPLINE_WAYPOINT the flattening used to DROP the item, join its
        neighbours with a line the vehicle never flies, and print PASS -- and the drop is also how an
        item slips past the MAV_FRAME check. Absence from the path IS the bug, so it is exit 2 now.
        DO_* commands move nothing and must still be skipped in silence."""
        def rows(command):
            return [(NAV_WAYPOINT, 5.0, 5.0, 3.0), (command, 15.0, 5.0, 3.0),
                    (NAV_WAYPOINT, 25.0, 5.0, 3.0)]

        ctrl = _write_mission(self.tmp.name, "nav_ctrl.waypoints", rows(NAV_WAYPOINT))
        self.assertEqual(_run_gate("--mission", str(ctrl))[0], 1,
                         msg="the control mission must FAIL -- otherwise the pair proves nothing")
        for command, name in ((82, "NAV_SPLINE_WAYPOINT"), (21, "NAV_LAND"), (31, "NAV_LOITER_TO_ALT")):
            mission = _write_mission(self.tmp.name, f"nav_{command}.waypoints", rows(command))
            code, out = _run_gate("--mission", str(mission))
            self.assertEqual(code, 2, msg=f"{name} ({command}) was dropped from the flight path "
                                          f"rather than refused:\n{out}")
        do_jump = _write_mission(self.tmp.name, "nav_do.waypoints",
                                 [(NAV_WAYPOINT, 5.0, 5.0, 3.0), (177, 0.0, 0.0, 0.0),
                                  (NAV_WAYPOINT, 25.0, 5.0, 3.0)])
        self.assertEqual(_run_gate("--mission", str(do_jump))[0], 1,
                         msg="DO_JUMP changes no position: refusing it would fail readable missions")


if __name__ == "__main__":
    unittest.main()
