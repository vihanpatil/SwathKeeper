"""`fieldguard_planning.geom` -- the ONE point-to-segment primitive, proven equal to the three it
replaced (D5, 2026-09-10).

The three copies this consolidates were `geofence._point_segment_distance`,
`coverage._point_segment_distance` and `check_live_flight_log._point_segment_xy`. Two of them fed
SAFETY numbers -- the tree-clearance geofence and the CPA the flight gate breaches on -- so
"behaviour-identical" cannot be a claim in a commit message. The three original bodies are copied
in below VERBATIM as reference functions (frozen; they are what the repo did before the change) and
re-run against the shared primitive over 10k randomised points, with the degenerate and
near-degenerate segments a flown path actually produces deliberately over-represented.

EXACT equality, not almostEqual: the consolidation is supposed to be the same arithmetic in the
same order, so any float difference at all is a real change and this test says so. The seed is
fixed, so a failure is reproducible.

stdlib unittest only. Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import math
import random
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from fieldguard_planning import coverage, geofence, geom  # noqa: E402

import check_live_flight_log as checker  # noqa: E402


# --- the three ORIGINAL implementations, copied verbatim at 6bb1371 ---------------------------
# Do not "simplify" these. They exist to be a frozen record of the behaviour being preserved.

def _ref_geofence(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Exact (not sampled) distance from point (px,py) to segment [(ax,ay),(bx,by)]."""
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def _ref_coverage(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Distance from a point to a segment (same math as geofence._point_segment_distance; kept
    local so coverage.py has no import dependency on geofence.py)."""
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def _ref_checker(px: float, py: float, ax: float, ay: float, bx: float, by: float):
    """(horizontal distance from (px,py) to the SEGMENT (ax,ay)-(bx,by), the fraction along that
    segment where the closest point sits). Degenerate segment (a == b) collapses to the point
    distance at fraction 0."""
    dx, dy = bx - ax, by - ay
    seg = dx * dx + dy * dy
    t = 0.0 if seg == 0.0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def _cases(n: int = 10000):
    """Random point/segment pairs over the field's coordinate range, with the pathologies that
    actually occur in this project's data mixed in at a rate no uniform sample would give them:

      * DEGENERATE segments (a == b): a flown path repeats a pose every time the vehicle holds
        station, and `coverage_from_path` / the CPA pass both walk consecutive-pose legs.
      * NEAR-degenerate segments (sub-millimetre): the telemetry quantum is ~9 mm, so a parked
        vehicle produces legs this short by the hundred.
      * Points EXACTLY on the segment, on its endpoints, and on its infinite line beyond both ends
        (where the t-clamp is the entire behaviour).
    """
    rng = random.Random(20260910)
    for i in range(n):
        ax, ay = rng.uniform(-100.0, 100.0), rng.uniform(-100.0, 100.0)
        flavour = i % 10
        if flavour == 0:                                    # degenerate
            bx, by = ax, ay
        elif flavour == 1:                                  # near-degenerate
            bx, by = ax + rng.uniform(-1e-4, 1e-4), ay + rng.uniform(-1e-4, 1e-4)
        elif flavour == 2:                                  # axis-aligned (a survey lane)
            bx, by = ax, ay + rng.uniform(-30.0, 30.0)
        else:
            bx, by = rng.uniform(-100.0, 100.0), rng.uniform(-100.0, 100.0)
        if flavour in (3, 4, 5):                            # on the infinite line, t swept wide
            t = rng.uniform(-2.0, 3.0)
            px, py = ax + t * (bx - ax), ay + t * (by - ay)
        elif flavour == 6:                                  # exactly an endpoint
            px, py = (ax, ay) if rng.random() < 0.5 else (bx, by)
        else:
            px, py = rng.uniform(-120.0, 120.0), rng.uniform(-120.0, 120.0)
        yield px, py, ax, ay, bx, by


class TestGeomIsTheOldMathExactly(unittest.TestCase):

    def test_distance_matches_all_three_originals_bit_for_bit(self):
        n = 0
        for px, py, ax, ay, bx, by in _cases():
            n += 1
            got = geom.point_segment_distance_xy(px, py, ax, ay, bx, by)
            args = (px, py, ax, ay, bx, by)
            self.assertEqual(got, _ref_geofence(*args), msg=f"geofence body differs at {args}")
            self.assertEqual(got, _ref_coverage(*args), msg=f"coverage body differs at {args}")
            self.assertEqual(got, _ref_checker(*args)[0], msg=f"checker body differs at {args}")
        self.assertEqual(n, 10000)

    def test_fraction_matches_the_checker_original(self):
        """The checker is the only caller that reads the fraction (the CPA pass interpolates the
        bird's pose at it), so it is the only one whose t-convention is load-bearing."""
        for px, py, ax, ay, bx, by in _cases():
            args = (px, py, ax, ay, bx, by)
            self.assertEqual(geom.point_segment_projection_xy(*args), _ref_checker(*args),
                             msg=f"(distance, fraction) differs at {args}")

    def test_degenerate_segment_is_the_point_distance_at_fraction_zero(self):
        d, t = geom.point_segment_projection_xy(3.0, 4.0, 1.0, 1.0, 1.0, 1.0)
        self.assertEqual(t, 0.0)
        self.assertAlmostEqual(d, math.hypot(2.0, 3.0))

    def test_fraction_is_clamped_to_the_segment(self):
        self.assertEqual(geom.point_segment_projection_xy(-5.0, 0.0, 0.0, 0.0, 10.0, 0.0), (5.0, 0.0))
        self.assertEqual(geom.point_segment_projection_xy(15.0, 0.0, 0.0, 0.0, 10.0, 0.0), (5.0, 1.0))


class TestEveryCallerUsesTheOnePrimitive(unittest.TestCase):
    """A shared primitive that a caller quietly stops calling is worse than three copies: the
    equivalence test above would still pass while the caller drifted. These pin the wiring."""

    def test_no_module_still_defines_its_own_copy(self):
        for mod in (geofence, coverage):
            self.assertFalse(hasattr(mod, "_point_segment_distance"),
                             f"{mod.__name__} still defines a private point-segment copy")

    def test_the_three_callers_resolve_to_the_geom_body(self):
        self.assertIs(geofence.point_segment_distance_xy, geom.point_segment_distance_xy)
        self.assertIs(coverage.point_segment_distance_xy, geom.point_segment_distance_xy)
        self.assertIs(checker._point_segment_xy, geom.point_segment_projection_xy)
        # `_point_segment_xy_m` stays a named function: build_dashboard_data.py reaches for it.
        self.assertAlmostEqual(checker._point_segment_xy_m(4.5, 2.0, 3.0, 0.0, 6.0, 0.0), 2.0)


class TestAirborneHasOneHome(unittest.TestCase):
    """`AIRBORNE_Z_M` is the altitude that decides which ticks a flown SPEED is measured over, and
    the booking gate holds that speed to a bar. Two homes drifting apart would move the denominator
    of a safety check silently, which is why the pre-existing test in
    test_check_live_flight_log_booking.py pins the copies EQUAL. This pins the stronger property
    the copies could never have: the gate reads the shared constant itself."""

    def test_the_gate_reads_geoms_constant(self):
        self.assertIs(checker.AIRBORNE_Z_M, geom.AIRBORNE_Z_M)
        self.assertEqual(geom.AIRBORNE_Z_M, 1.0)

    def test_geom_is_importable_with_no_numpy_and_no_config(self):
        """The whole reason the constant can live here: `geom` imports `math` and nothing else, so
        the stdlib-only gate can take it. A sibling import creeping in would re-break that."""
        src = (REPO_ROOT / "src" / "fieldguard_planning" / "geom.py").read_text()
        imports = [ln.strip() for ln in src.splitlines()
                   if ln.startswith("import ") or ln.startswith("from ")]
        self.assertEqual(imports, ["from __future__ import annotations",
                                   "import math",
                                   "from typing import Tuple"], f"geom.py grew an import: {imports}")


if __name__ == "__main__":
    unittest.main()
