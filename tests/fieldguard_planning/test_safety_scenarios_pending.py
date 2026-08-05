"""PENDING safety-scenario assertions -- the Week 3-4 avoidance loop's acceptance tests, written NOW.

Every test here states, as a real executable assertion, a safety property that cannot be checked
until the reactive-avoidance loop exists and can emit a FLIGHT LOG. They are not stubs: the assertion
body is complete. They are SELF-ACTIVATING -- each skips only because its scenario's flight log does
not exist yet (`eval/scenarios/<name>/flight_log.json`). The moment the Week 3-4 loop is run on a
scenario and drops its log there, the matching test goes live with ZERO edits. That is deliberate:
Week 3 turns these on by producing artifacts, not by inventing assertions.

Flight-log contract (also in eval/scenarios/README.md -- keep the two in sync):
  {
    "scenario": "<name>",
    "seed": <int>,
    "cell_size_m": 2.5,               # must match coverage.DEFAULT_CELL_SIZE_M or override consciously
    "swath_half_width_m": 7.5,        # must match the validated camera swath (see coverage.py caveat)
    "flown_path_enu": [[e,n,u], ...], # ACTUAL flown path incl. every avoidance deviation
    "coverage_ledger": [{"cell_id": str, "status": "covered"|"debt"}, ...],  # terminal, one per cell
    "requeue_events": [{"cell_id": str, "t_s": float}, ...],                 # audit trail (optional)
    "detection": {                    # for the "no missed bird" family; feeds eval/score.py verbatim
      "ground_truth": "<path to ground_truth.json>",
      "detections":  "<path to detections.json>"
    }
  }

Property families and where their truth comes from:
  * coverage-debt ledger    -> fieldguard_planning.coverage.check_ledger  (no silently-skipped cell)
  * geofence (3D)           -> fieldguard_planning.geofence + altitude band (no breach on avoid path)
  * missed-bird / FNR       -> eval/score.py per_bird_track_fnr == 0        (the SAFETY-CRITICAL one)

stdlib unittest only. Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

from fieldguard_planning.coverage import (  # noqa: E402
    build_grid, check_ledger, coverage_from_path, load_field_polygon,
)
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402

SCENARIOS_DIR = REPO_ROOT / "eval" / "scenarios"
STATIC_OBSTACLES = REPO_ROOT / "config" / "static_obstacles.json"
FIELD_POLYGON = REPO_ROOT / "config" / "field_polygon.json"

TREE_HEIGHT_M = 3.5
# A flown point is "in the tree danger band" if it is at or below tree height + a vertical buffer.
# Below this altitude an XY geofence breach is a real collision, not a benign over-flight.
TREE_DANGER_BAND_TOP_M = TREE_HEIGHT_M + 2.0


def _load_flight_log(name: str) -> dict:
    """Load a scenario's flight log, or skip the test if the avoidance loop hasn't produced one."""
    log_path = SCENARIOS_DIR / name / "flight_log.json"
    if not log_path.exists():
        raise unittest.SkipTest(
            f"PENDING avoidance loop (Week 3-4): no flight log at {log_path}. This assertion goes "
            f"live automatically once the loop runs scenario '{name}' and writes that file.")
    return json.loads(log_path.read_text())


def _grid_ids():
    return [c.cell_id for c in build_grid(load_field_polygon(FIELD_POLYGON))]


class TestNoSilentlySkippedCell(unittest.TestCase):
    """CORE property (CLAUDE.md): an avoidance manoeuvre must never make a coverage cell vanish."""

    def _assert_ledger_honest(self, name: str):
        log = _load_flight_log(name)
        result = check_ledger(_grid_ids(), log["coverage_ledger"])
        self.assertTrue(result.ok,
                        msg=f"[{name}] coverage-debt ledger dishonest: {'; '.join(result.errors)}")
        # v1 bar (ADR-002): debt may be > 0 but must be EXPLICIT (guaranteed by result.ok above).
        # Cross-check the ledger does not LIE: a cell claimed covered must actually be within swath
        # of the flown path. This catches a loop that marks cells covered to zero out its debt.
        cells = build_grid(load_field_polygon(FIELD_POLYGON))
        flown_xy = [(p[0], p[1]) for p in log["flown_path_enu"]]
        geo_covered = coverage_from_path(cells, flown_xy, log["swath_half_width_m"])
        lied = [r["cell_id"] for r in log["coverage_ledger"]
                if r["status"] == "covered" and not geo_covered.get(r["cell_id"], False)]
        self.assertEqual(lied, [],
                         msg=f"[{name}] {len(lied)} cell(s) marked COVERED but the flown path never "
                             f"imaged them: {lied[:8]}")

    def test_bird_forces_avoid_over_cell(self):
        """Scenario cov_bird_over_cell: a bird forces a dodge directly over a coverage cell; that
        cell must end up covered OR explicitly logged as debt -- never silently absent."""
        self._assert_ledger_honest("cov_bird_over_cell")

    def test_bird_at_lane_turnaround(self):
        """Scenario cov_bird_at_turnaround (ADVERSARIAL): the dodge happens during a lane reversal,
        the moment the plan's 'next waypoint' is itself changing -- the likeliest place a cell falls
        between the old and new lane and is dropped by both."""
        self._assert_ledger_honest("cov_bird_at_turnaround")

    def test_two_birds_near_simultaneous(self):
        """Scenario cov_two_birds_simultaneous (ADVERSARIAL): two dodges back-to-back; the second
        avoidance must not clobber the first's requeued/debt bookkeeping."""
        self._assert_ledger_honest("cov_two_birds_simultaneous")


class TestNoMissedBird(unittest.TestCase):
    """SAFETY-CRITICAL. Reuses eval/score.py so the safety bar is the SAME metric family as ADR-003:
    per-bird-track FNR == 0 (every bird detected on >=1 frame BEFORE closest approach)."""

    def _assert_no_missed_bird(self, name: str):
        log = _load_flight_log(name)
        import score  # eval/score.py; imported lazily so the module isn't required until activated
        det_cfg = log["detection"]
        _, gt_by_fid = score.load_gt(REPO_ROOT / det_cfg["ground_truth"])
        det = json.loads((REPO_ROOT / det_cfg["detections"]).read_text())
        m = score.score(gt_by_fid, det["frames"], iou_thresh=0.3)
        self.assertEqual(m["per_bird_track_fnr"], 0.0,
                         msg=f"[{name}] per-bird-track FNR = {m['per_bird_track_fnr']:.3f} -- a bird "
                             f"was first seen only at/after closest approach (a near-miss). "
                             f"per-bird: {m['per_bird']}")

    def test_bird_crosses_path(self):
        """Scenario det_bird_crosses_path: a bird crosses the flight line; detection must fire pre
        closest-approach."""
        self._assert_no_missed_bird("det_bird_crosses_path")

    def test_bird_over_low_ndvi_ground(self):
        """Scenario det_bird_over_low_ndvi (ADVERSARIAL): bird over bare/low-NDVI soil -- the exact
        FN risk ADR-003 flagged. The spike did not trip it on synthetic frames; this re-checks it on
        the real render, where low NDVI contrast is hardest."""
        self._assert_no_missed_bird("det_bird_over_low_ndvi")


class TestAvoidanceDoesNotBreachGeofence(unittest.TestCase):
    """An avoidance manoeuvre must not create a NEW collision. The nominal mission's benign XY
    overlap with row 0 is safe only by altitude (see test_mission_geofence.py); an avoid path that
    both breaches a tree's XY radius AND descends into the tree band is a real strike."""

    def test_avoid_path_never_enters_tree_band_and_radius(self):
        """Scenario geo_avoid_into_tree (ADVERSARIAL): a bird positioned so the natural dodge points
        the drone at a geofenced tree. The flown path must never be simultaneously inside a tree's
        obstacle_radius_m AND at/below the tree danger band."""
        log = _load_flight_log("geo_avoid_into_tree")
        geo = GeofenceMap.from_file(STATIC_OBSTACLES)
        strikes = []
        for e, n, u in log["flown_path_enu"]:
            if u <= TREE_DANGER_BAND_TOP_M and geo.is_point_excluded(e, n):
                obs = geo.excluding_obstacle(e, n)
                strikes.append((round(e, 2), round(n, 2), round(u, 2), obs.id if obs else "?"))
        self.assertEqual(strikes, [],
                         msg=f"[geo_avoid_into_tree] avoidance drove the drone into a tree "
                             f"(inside radius AND in the <= {TREE_DANGER_BAND_TOP_M} m band): {strikes[:5]}")

    def test_avoid_path_stays_inside_field_polygon(self):
        """A dodge must not push the drone outside the field boundary (a geofence breach of a
        different kind). Uses the same scenario's flown path."""
        from fieldguard_planning.coverage import _point_in_polygon  # noqa
        log = _load_flight_log("geo_avoid_into_tree")
        poly = load_field_polygon(FIELD_POLYGON)
        outside = [(round(e, 2), round(n, 2)) for e, n, u in log["flown_path_enu"]
                   if not _point_in_polygon(e, n, poly)]
        self.assertEqual(outside, [],
                         msg=f"[geo_avoid_into_tree] avoidance left the field polygon at: {outside[:5]}")


if __name__ == "__main__":
    unittest.main()
