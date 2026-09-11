"""Safety-scenario assertions -- the avoidance loop's acceptance tests.

Every test here states, as a real executable assertion, a safety property of the reactive-avoidance
loop. They are not stubs: the assertion body is complete, and each is SELF-ACTIVATING -- it skips
only while the artifact it scores does not exist.

THE SAFETY-CRITICAL FAMILY WAS WIRED ON 2026-09-10, 37 days after it was written. `TestNoMissedBird`
was the one class here labelled SAFETY-CRITICAL and it had executed ZERO times, because it waited on
`eval/scenarios/det_bird_crosses_path/flight_log.json` -- a synthetic scenario nobody ever generated,
and which by now would be WEAKER evidence than what the repo holds: two real-render clips, labelled
from the bird driver's own applied poses, scored by this same `eval/score.py`. So the FNR arm now
scores the committed real-render evidence (`eval/results/adr003_20260823/`, the ADR-003 am. 7 ADOPT
clip) and the synthetic scenario is retired rather than waited on. Its adversarial sibling (a bird
over bare, low-NDVI soil) stays skipped and says exactly what it is missing -- see that test.

Flight-log contract (also in eval/scenarios/README.md -- keep the two in sync):
  {
    "scenario": "<name>",
    "seed": <int>,
    "cell_size_m": 2.5,               # must match coverage.DEFAULT_CELL_SIZE_M or override consciously
    "swath_half_width_m": 7.5,        # these open-loop FIXTURES were cut at 7.5; the camera-derived
                                      # swath is 6.886 m (coverage.derive_swath_half_width_m,
                                      # ADR-016) -- a log states the swath it was computed with
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
  * missed-bird / FNR       -> eval/score.py per_bird_track_fnr == 0        (the SAFETY-CRITICAL one),
                               scored on the COMMITTED real-render labels, with its denominators
                               asserted beside it -- a rate over no bird-frames is 0.0 and reads
                               as perfect

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

# The real-render evidence the missed-bird family is scored on: the ADR-003 am. 7 ADOPT clip
# (2026-08-23), the only committed label set with every bird of the world visible on some frame.
# Its sibling `adr003_20260825/` is deliberately NOT used: 1 of 3 birds ever visible, 2 bird-frames,
# and its own `spike_scores.json` calls itself EVIDENCE INSUFFICIENT -- a per-bird FNR of 0.0 over
# one bird is 0.0 because the denominator is one, which is precisely the vacuous green this
# project's rules forbid.
ADR003_EVIDENCE = REPO_ROOT / "eval" / "results" / "adr003_20260823"

TREE_HEIGHT_M = 3.5
# A flown point is "in the tree danger band" if it is at or below tree height + a vertical buffer.
# Below this altitude an XY geofence breach is a real collision, not a benign over-flight.
TREE_DANGER_BAND_TOP_M = TREE_HEIGHT_M + 2.0


def _load_flight_log(name: str) -> dict:
    """Load a scenario's flight log, or skip the test if nobody has generated one."""
    log_path = SCENARIOS_DIR / name / "flight_log.json"
    if not log_path.exists():
        raise unittest.SkipTest(
            f"no flight log at {log_path}: `eval/scenarios/generate_flight_logs.py` does not "
            f"produce scenario '{name}'. This assertion goes live with zero edits the moment that "
            f"file exists.")
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
    """SAFETY-CRITICAL, and LIVE since 2026-09-10. Reuses eval/score.py so the safety bar is the
    SAME metric family as ADR-003: per-bird-track FNR == 0 (every bird detected on >=1 frame BEFORE
    its closest approach; a bird first seen at/after closest approach is a near-miss the loop could
    not have avoided).

    Scored on the committed real-render artifacts rather than on a synthetic scenario: the labels
    are the bird driver's own APPLIED poses (`label_src: applied`), the detector is the adopted one
    at the adopted threshold, and the frames are the ones the live camera actually rendered --
    which produced this committed artifact. This test RE-SCORES that artifact, so it catches scorer
    regressions and artifact drift, NOT a live detector regression: that is CI's seed-42
    `check_spike_regression.py` step, which re-runs `fieldguard_planning.ndvi_detect` on a
    regenerated clip."""

    IOU_THRESH = json.loads((ADR003_EVIDENCE / "spike_scores.json").read_text())["iou_thresh"] \
        if (ADR003_EVIDENCE / "spike_scores.json").exists() else 0.3

    def _evidence(self, gt_path: Path, det_path: Path) -> dict:
        for p in (gt_path, det_path):
            if not p.exists():
                raise unittest.SkipTest(f"{p} absent (eval/results is gitignore-excepted)")
        import score  # eval/score.py; imported lazily so the module isn't required until activated
        _, gt_by_fid = score.load_gt(gt_path)
        det = json.loads(det_path.read_text())
        return score.score(gt_by_fid, det["frames"], iou_thresh=self.IOU_THRESH)

    def _assert_no_missed_bird(self, m: dict, label: str):
        self.assertEqual(m["per_bird_track_fnr"], 0.0,
                         msg=f"[{label}] per-bird-track FNR = {m['per_bird_track_fnr']:.3f} -- a "
                             f"bird was first seen only at/after closest approach (a near-miss). "
                             f"per-bird: {m['per_bird']}")

    def test_no_bird_was_missed_before_closest_approach(self):
        """THE SAFETY ASSERTION. Every bird that the camera ever saw was detected on at least one
        frame before it was closest to the vehicle."""
        m = self._evidence(ADR003_EVIDENCE / "ground_truth.json",
                           ADR003_EVIDENCE / "detections_ndvi.json")
        self._assert_no_missed_bird(m, ADR003_EVIDENCE.name)
        for bird in m["per_bird"]:
            self.assertTrue(bird["detected_before_closest"], msg=f"{bird}")

    def test_the_zero_has_denominators(self):
        """A per-bird FNR of 0.0 is also what an EMPTY label set returns. So the evidence behind the
        green is asserted beside it: every bird the world defines was visible on some frame, there
        are bird-frames to score, and every scored label's POSITION came from a measured source
        (`applied`) rather than a model."""
        m = self._evidence(ADR003_EVIDENCE / "ground_truth.json",
                           ADR003_EVIDENCE / "detections_ndvi.json")
        birds_in_world = len(json.loads(
            (REPO_ROOT / "config" / "birds" / "farm_world_birds.json").read_text())["birds"])
        self.assertEqual(m["birds_with_visible_frames"], birds_in_world,
                         msg="a bird the world defines was never visible: its per-bird FNR is "
                             "undefined, not zero")
        self.assertGreaterEqual(m["visible_bird_frames"], birds_in_world)
        self.assertEqual(m["unscoreable_label_frames"], 0,
                         msg=f"labels from an unmeasured source: {m['label_srcs']}")

    def test_the_recompute_agrees_with_the_committed_score(self):
        """The artifact and the recomputation must not drift: `spike_scores.json` is what the ADRs
        quote, and this test is what CI runs. Same inputs, same function, same numbers."""
        committed = json.loads((ADR003_EVIDENCE / "spike_scores.json").read_text())
        m = self._evidence(ADR003_EVIDENCE / "ground_truth.json",
                           ADR003_EVIDENCE / "detections_ndvi.json")
        a = committed["approaches"]["a_ndvi_direct"]
        for key in ("TP", "FP", "FN", "per_bird_track_fnr", "birds_with_visible_frames",
                    "visible_bird_frames", "ambiguous_label_frames"):
            self.assertEqual(m[key], a[key], msg=f"{key} drifted from the committed artifact")

    def test_the_assertion_fails_on_a_near_miss(self):
        """NOT VACUOUS, proven by construction: a bird whose only detection lands AFTER its closest
        approach must fail this assertion. Without this, "FNR == 0" is a test that a detector which
        never fires also passes on an empty label set."""
        import score
        gt_by_fid = {
            1: {"frame_id": 1, "t_s": 10.0,
                "birds": [{"bird_id": "bird_0", "bbox": [10, 10, 20, 20], "visible": True,
                           "range_m": 5.0, "label_src": "applied"}]},
            2: {"frame_id": 2, "t_s": 11.0,
                "birds": [{"bird_id": "bird_0", "bbox": [10, 10, 20, 20], "visible": True,
                           "range_m": 9.0, "label_src": "applied"}]},
        }
        # Frame 1 is closest approach (5.0 m) and is NOT detected; frame 2, afterwards, is.
        det_frames = [{"frame_id": 1, "boxes": []},
                      {"frame_id": 2, "boxes": [[10, 10, 20, 20]]}]
        m = score.score(gt_by_fid, det_frames, iou_thresh=self.IOU_THRESH)
        self.assertEqual(m["per_bird_track_fnr"], 1.0)
        with self.assertRaises(AssertionError):
            self._assert_no_missed_bird(m, "synthetic near-miss")

    def test_bird_over_low_ndvi_ground(self):
        """STILL PENDING, and this is the honest reason (2026-09-10).

        The adversarial arm asks a different question from the one above: is a bird over BARE,
        low-NDVI soil -- where the bird/background contrast the -0.61 threshold lives on is at its
        narrowest -- detected before closest approach? Nothing committed can answer it. The label
        schema (`eval/label_from_sim.py`) records `bbox`, `visible`, `range_m` and `label_src`; it
        records NOTHING about what the bird was in front of, and the raw frames that would let a
        reader classify it are gitignored (ADR-013: clips are 12 GB and stay out of the tree).

        It goes live when a label carries the terrain under the bird -- either a `background` field
        on the GT box, or a committed per-frame NDVI sample of the bbox. Until then this skips, and
        it does NOT borrow the test above's green: the two are different questions and the repo has
        evidence for only one of them."""
        raise unittest.SkipTest(
            "no committed artifact records what a labelled bird was in front of: the ground-truth "
            "schema carries bbox/visible/range_m/label_src and no terrain, and the raw frames are "
            "gitignored. Goes live when a GT box carries the background class (noted 2026-09-10; "
            "written 2026-08-04, never run).")


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
