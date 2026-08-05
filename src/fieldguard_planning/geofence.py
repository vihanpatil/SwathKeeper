"""Static-obstacle geofence consumer (ADR-001).

Loads `config/static_obstacles.json` -- the contract `robotics-sim-engineer` generates alongside
`sim/worlds/farmguard_field.sdf` (see `sim/README.md` "Static-obstacle geofence contract" and
`docs/DECISIONS.md` ADR-001) -- and exposes exclusion queries against it: given a point or a
mission leg (line segment), is it inside any known tree's `obstacle_radius_m`?

Per ADR-001, trees are KNOWN static obstacles from a (synthetic, for now) pre-flight boundary
survey, geofenced directly rather than runtime-detected. This module is that geofence. It is what
lets the Week 3-4 avoidance loop distinguish "known tree, already excluded from the plan" from
"unplanned dynamic obstacle, needs a reactive avoid" -- it does NOT itself do any avoidance or
replanning (that's Week 3-4 scope, out of bounds here per ADR-002).

Exclusion is checked in the XY (east/north) plane only. Z is deliberately not part of the geofence
query: `sim/README.md` documents that tree canopy height (3.5 m) sits well below
`config/field_polygon.json`'s `mission_altitude_m` (15 m) by design, so vertical separation is a
separate, already-satisfied constraint -- see `scripts/check_mission_geofence.py` for where that
gets confirmed numerically for the current mission, rather than baked as an assumption in here.

Dependency: stdlib only (json, math, dataclasses) -- deliberate, so tests run without a venv/ROS 2
environment (see this project's Week 2 environment-honesty note: only pure-logic modules like this
one can be validated outside the Docker/Gazebo/ROS 2 stack).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_STATIC_OBSTACLES = REPO_ROOT / "config" / "static_obstacles.json"


@dataclass(frozen=True)
class Obstacle:
    """One known static obstacle (currently always a tree; `type` is kept for future obstacle
    kinds, e.g. a fixed structure, without changing the schema)."""
    id: str
    type: str
    row_id: int
    x_m: float          # East
    y_m: float           # North
    z_m: float            # Up (ground-level for trees today; kept for completeness)
    obstacle_radius_m: float  # USE THIS for exclusion -- already includes a safety margin.
    canopy_radius_m: float     # Gazebo collision/visual geometry only -- do not geofence on this.
    height_m: float

    @classmethod
    def from_json(cls, d: dict) -> "Obstacle":
        x, y, z = d["pos_m"]
        return cls(
            id=d["id"],
            type=d.get("type", "unknown"),
            row_id=d.get("row_id", -1),
            x_m=float(x),
            y_m=float(y),
            z_m=float(z),
            obstacle_radius_m=float(d["obstacle_radius_m"]),
            canopy_radius_m=float(d.get("canopy_radius_m", d["obstacle_radius_m"])),
            height_m=float(d.get("height_m", 0.0)),
        )


class ClearanceResult(NamedTuple):
    """Signed clearance to the single nearest-in-margin obstacle: distance from the query
    point/segment to that obstacle's center, MINUS its obstacle_radius_m. Negative means the
    query is inside the exclusion radius (a violation); zero or positive means clear, and the
    value is exactly how many meters of margin remain."""
    obstacle: Optional[Obstacle]
    clearance_m: float


def _point_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Exact (not sampled) distance from point (px,py) to segment [(ax,ay),(bx,by)]."""
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


class GeofenceMap:
    """Exclusion-radius query over a set of known static obstacles (trees)."""

    def __init__(self, obstacles: Sequence[Obstacle]):
        self._obstacles: List[Obstacle] = list(obstacles)

    @classmethod
    def from_file(cls, path: Path = DEFAULT_STATIC_OBSTACLES) -> "GeofenceMap":
        data = json.loads(Path(path).read_text())
        obstacles = [Obstacle.from_json(o) for o in data["obstacles"]]
        return cls(obstacles)

    def __len__(self) -> int:
        return len(self._obstacles)

    @property
    def obstacles(self) -> Tuple[Obstacle, ...]:
        return tuple(self._obstacles)

    def point_clearance(self, x_m: float, y_m: float) -> ClearanceResult:
        """Worst-case (smallest / most-negative) signed clearance from (x_m, y_m) to any
        obstacle's exclusion boundary. Empty map => (None, +inf)."""
        best: Optional[Obstacle] = None
        best_clearance = math.inf
        for obs in self._obstacles:
            d = math.hypot(x_m - obs.x_m, y_m - obs.y_m) - obs.obstacle_radius_m
            if d < best_clearance:
                best_clearance = d
                best = obs
        return ClearanceResult(best, best_clearance)

    def is_point_excluded(self, x_m: float, y_m: float) -> bool:
        """True iff (x_m, y_m) falls inside (or exactly on) any obstacle's obstacle_radius_m."""
        return self.point_clearance(x_m, y_m).clearance_m <= 0.0

    def excluding_obstacle(self, x_m: float, y_m: float) -> Optional[Obstacle]:
        """The obstacle excluding this point, or None if the point is clear of all of them."""
        obstacle, clearance = self.point_clearance(x_m, y_m)
        return obstacle if clearance <= 0.0 else None

    def segment_clearance(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> ClearanceResult:
        """Worst-case signed clearance between the line segment p1->p2 and any obstacle. This is
        what a mission leg (waypoint_i -> waypoint_i+1) should be checked against, not just the
        endpoints -- a leg can clip a tree's exclusion radius while both endpoints stay clear."""
        ax, ay = p1
        bx, by = p2
        best: Optional[Obstacle] = None
        best_clearance = math.inf
        for obs in self._obstacles:
            d = _point_segment_distance(obs.x_m, obs.y_m, ax, ay, bx, by) - obs.obstacle_radius_m
            if d < best_clearance:
                best_clearance = d
                best = obs
        return ClearanceResult(best, best_clearance)

    def is_segment_clear(self, p1: Tuple[float, float], p2: Tuple[float, float]) -> bool:
        return self.segment_clearance(p1, p2).clearance_m > 0.0

    def check_path(self, points: Sequence[Tuple[float, float]]) -> List[Tuple[int, ClearanceResult]]:
        """Run `segment_clearance` over every consecutive leg of an ordered XY path (e.g. a
        flattened mission: home -> takeoff -> waypoints... -> RTL). Returns a list of
        (leg_index, ClearanceResult) for every leg -- callers can filter for the min / any
        violation (see `scripts/check_mission_geofence.py`)."""
        results = []
        for i in range(len(points) - 1):
            results.append((i, self.segment_clearance(points[i], points[i + 1])))
        return results
