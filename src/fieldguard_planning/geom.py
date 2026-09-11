"""The shared 2-D flight-geometry primitives -- one implementation, several callers.

WHY THIS MODULE EXISTS. Point-to-segment distance in the XY plane was written out three times
(`geofence.py`, `coverage.py`, `scripts/check_live_flight_log.py`), each copy with its own
docstring explaining why it was a copy: importing the neighbour would have dragged in config reads
or numpy. That reason is real, so the fix is not "import the neighbour" but "put the primitive
somewhere that has no dependencies at all". This module imports `math` and nothing else -- no
config, no numpy, no sibling -- so every one of those callers can use it and keep its own purity
promise:

  * `geofence.py` / `coverage.py`  -- stdlib-only, so they run with no venv, no ROS 2, no Docker.
  * `scripts/check_live_flight_log.py` -- stdlib-only on purpose: the evidence gate must run in
    CI (and on a bare host) without the sim stack installed.
  * `scripts/build_dashboard_data.py` -- reaches the same primitive through the gate module.

THE DEGENERATE SEGMENT IS THE WHOLE REASON A SHARED COPY IS SAFE. All three copies agreed that a
zero-length segment collapses to the point distance at fraction 0.0; a flown path repeats poses
whenever the vehicle holds station, so that case is not theoretical -- it is most of a hover.
`tests/fieldguard_planning/test_geom.py` re-runs the three ORIGINAL bodies (copied in verbatim as
reference functions) against this one over 10k randomised points including degenerate segments, so
"behaviour-identical" is measured rather than asserted in prose.
"""
from __future__ import annotations

import math
from typing import Tuple

# The altitude above which this project calls the vehicle AIRBORNE, and the one home for it.
#
# 1.0 m because that is already the project's definition: `clip_recorder` writes it into every
# clip's `meta.json` as `z_threshold_m` (a frame recorded below it is ground, not survey), and both
# the flight-log gate (airborne ground-speed window) and the dashboard's flight-window finder have
# to mean the SAME thing by "the flight" or a speed measured over one window gets held to a bar
# measured over another. It sits above pad-level pose noise and far below the 15 m cruise, so no
# real flight is ever ambiguous about it.
#
# It lives HERE rather than in `clip_recorder` (its original home) because the gate cannot import
# `clip_recorder`: that module imports numpy, and the gate is stdlib-only by design.
AIRBORNE_Z_M = 1.0


def point_segment_projection_xy(px: float, py: float, ax: float, ay: float,
                                bx: float, by: float) -> Tuple[float, float]:
    """(horizontal distance from (px,py) to the SEGMENT (ax,ay)-(bx,by), the fraction along that
    segment where the closest point sits).

    Exact, not sampled. The fraction is clamped to [0, 1], so the answer is the distance to the
    segment and never to its infinite line. A degenerate segment (a == b) collapses to the point
    distance at fraction 0.0.
    """
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return math.hypot(px - ax, py - ay), 0.0
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def point_segment_distance_xy(px: float, py: float, ax: float, ay: float,
                              bx: float, by: float) -> float:
    """Distance only -- most callers do not care where on the segment the minimum landed."""
    return point_segment_projection_xy(px, py, ax, ay, bx, by)[0]
