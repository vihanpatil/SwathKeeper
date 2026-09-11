#!/usr/bin/env python3
"""GATE: does the committed mission enter any tree's 3D exclusion volume? (R8, ADR-022 amendment 2)

Loads a QGC WPL mission (`config/missions/boustrophedon.waypoints`) and the known-static-obstacle
export (`config/static_obstacles.json`), flattens the mission into its ordered (east, north,
altitude) flight path (`fieldguard_planning.mission_waypoints.mission_xyz_path`), and asks the SAME
question the executor asks of every GUIDED setpoint before it is sent, at every sample of every leg:
`GeofenceMap.unsafe_obstacle_3d` -- is this point inside a tree's cylinder (XY within
`obstacle_radius_m` AND z within `[z_m, z_m + height_m + vertical_margin_m]`)? One rule, imported,
never re-derived here: if the flight-side rule moves, this gate moves with it.

Where it samples is SOLVED, not stepped. For each tree it intersects the leg's XY chord window with
the leg's altitude-band window and samples the midpoint of the overlap (`volume_samples`), so the
verdict does not depend on `SAMPLE_STEP_M`. See `volume_samples` for the measured reason. The
uniform sweep is kept as well, because it assumes nothing about obstacle SHAPE and would still cover
the leg if the rule's volume ever stopped being a cylinder while `volume_samples` still solved for one.

It prints two numbers per leg and never confuses them:
  * **XY clearance** -- the 2D overlap. The committed mission's lane at x=15 runs straight down tree
    row 0 and reads **-1.997 m**. That is real, and it is REPORTED on every run.
  * **vertical clearance** where the leg passes over a tree's column -- 15 m of cruise against a
    4.80 m band top is **+10.200 m**. That is *why* the XY overlap is not a violation.
Only the 3D verdict sets the exit code: **0** if no leg enters a tree's volume, **1** if one does,
**2** if a mission/obstacle file cannot be read or carries no legs. Until 2026-09-11 this script
exited 1 on the XY overlap alone, so CI ran it `|| true` -- and an XY geofence that cannot fail is
not one (ADR-022, finding R8).

The mission is NOT re-planned to satisfy this gate: every committed flight log flew it as it stands,
and comparability across those logs outranks a cosmetic lane shift.

Pure-logic / stdlib-only (no Gazebo/ArduPilot/ROS 2 needed): it validates mission-vs-geofence
geometry, not that the mission flies in Gazebo (that needs the human Docker run, see sim/README.md
"Launching the world").

Usage:
    python3 scripts/check_mission_geofence.py
    python3 scripts/check_mission_geofence.py --mission path/to/other.waypoints
"""
import argparse
import json
import math
import sys
from pathlib import Path
from typing import List, NamedTuple, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.avoidance_executor import DEFAULT_VERTICAL_MARGIN_M  # noqa: E402
from fieldguard_planning.geofence import GeofenceMap, Obstacle  # noqa: E402
from fieldguard_planning.mission_waypoints import mission_xyz_path, parse_qgc_wpl  # noqa: E402

DEFAULT_MISSION = REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints"
DEFAULT_STATIC_OBSTACLES = REPO_ROOT / "config" / "static_obstacles.json"
DEFAULT_FIELD_POLYGON = REPO_ROOT / "config" / "field_polygon.json"

# The margin the EXECUTOR vets setpoints with (avoidance_executor.DEFAULT_VERTICAL_MARGIN_M), not a
# second copy of it: the mission and the dodges are judged against the same canopy band.
VERTICAL_MARGIN_M = DEFAULT_VERTICAL_MARGIN_M
# The shape-agnostic sweep. NOT the gate's resolution: `volume_samples` solves each tree's in-volume
# window exactly, so widening this cannot hide a breach -- which is pinned, at 10x and 2e9x, by
# test_a_leg_that_climbs_out_of_the_band_mid_circle_is_not_stepped_over.
SAMPLE_STEP_M = 0.5

Point = Tuple[float, float, float]


class LegReport(NamedTuple):
    """One mission leg, judged. `unsafe_obstacle` is the verdict; the clearances are the evidence."""
    index: int
    p1: Point
    p2: Point
    xy_clearance_m: float                     # signed, to the nearest obstacle over the whole leg
    xy_nearest: Optional[Obstacle]
    vertical_clearance_m: Optional[float]     # None unless the leg passes over a tree's column
    vertical_obstacle: Optional[Obstacle]
    unsafe_obstacles: Tuple[Obstacle, ...]    # every tree whose volume this leg enters, in order
    unsafe_point: Optional[Point]             # where it enters the FIRST of them
    n_samples: int

    @property
    def unsafe_obstacle(self) -> Optional[Obstacle]:
        """The first tree the leg enters, or None -- this is the verdict."""
        return self.unsafe_obstacles[0] if self.unsafe_obstacles else None

    @property
    def verdict(self) -> str:
        if self.unsafe_obstacles:
            return "UNSAFE"
        return "CLEAR-BY-ALTITUDE" if self.vertical_obstacle is not None else "CLEAR"


def lerp(p1: Point, p2: Point, t: float) -> Point:
    return (p1[0] + (p2[0] - p1[0]) * t,
            p1[1] + (p2[1] - p1[1]) * t,
            p1[2] + (p2[2] - p1[2]) * t)


def uniform_samples(p1: Point, p2: Point, step_m: float) -> List[float]:
    """Sample parameters t in [0,1] spaced at most `step_m` apart along the leg's 3D length.

    3D length, not XY: a takeoff climbs 15 m over zero XY distance, and an unsampled climb is an
    unchecked one. Always includes both endpoints."""
    length = math.dist(p1, p2)
    n = max(1, int(math.ceil(length / step_m))) if step_m > 0 else 1
    return [i / n for i in range(n + 1)]


def xy_window(obs: Obstacle, p1: Point, p2: Point) -> Optional[Tuple[float, float]]:
    """The parameter window [t0, t1] within [0, 1] over which the leg is inside `obs`'s exclusion
    circle in XY -- None if it never is. Exact (the segment/circle quadratic), clamped to the leg.

    This is the ONE place leg-vs-tree geometry is solved; both callers below use it and neither
    re-derives it."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    fx, fy = p1[0] - obs.x_m, p1[1] - obs.y_m
    c = fx * fx + fy * fy - obs.obstacle_radius_m ** 2
    a = dx * dx + dy * dy
    if a <= 0.0:                                 # vertical leg (a takeoff climb): XY never changes
        return (0.0, 1.0) if c <= 0.0 else None
    b = 2.0 * (fx * dx + fy * dy)
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return None                              # the leg never reaches this obstacle's circle
    root = math.sqrt(disc)
    t0 = max(0.0, (-b - root) / (2.0 * a))
    t1 = min(1.0, (-b + root) / (2.0 * a))
    return (t0, t1) if t0 <= t1 else None


def volume_samples(obs: Obstacle, p1: Point, p2: Point, margin_m: float) -> List[float]:
    """One parameter at which the leg is INSIDE `obs`'s 3D volume, or [] if it never is.

    Stepping cannot answer this, at any step. Both constraints are linear/convex in t, so the
    in-volume window is the XY window intersected with the altitude-band window -- and on a leg that
    CHANGES ALTITUDE that window is bounded by a band crossing and can be arbitrarily short. A
    2026-09-11 QA sweep measured **57 false passes in 2,500 genuinely-unsafe sloped legs (2.28 %)**
    against a 0.5 m grid plus circle entry/exit samples -- the deepest 18.6 cm inside the trunk
    cylinder over 43 cm of flight path, printed as `CLEAR-BY-ALTITUDE ... PASS`. Re-measured on this
    implementation: **16 of 1420 sloped legs false-passed before, 0 after, 0 false alarms**; LEVEL
    legs, where the window can only end at the circle, scored **0 of 2107 both before and after** --
    which is why the level-leg graze test never caught this.

    The sample returned is the window's MIDPOINT: strictly interior, so the answer does not hang on
    whether a point sitting exactly on the circle or exactly on the band top survives float rounding
    in the rule's `<=`.

    This decides WHERE to look and never WHETHER the point is unsafe -- `leg_report` still asks
    `GeofenceMap.unsafe_obstacle_3d`, which stays the only verdict in this file."""
    window = xy_window(obs, p1, p2)
    if window is None:
        return []
    t0, t1 = window
    z_lo, z_hi = obs.z_m, obs.z_m + obs.height_m + margin_m
    dz = p2[2] - p1[2]
    if dz == 0.0:                                # level leg: the band constraint is all-or-nothing
        if not (z_lo <= p1[2] <= z_hi):
            return []
        s0, s1 = 0.0, 1.0
    else:
        s0, s1 = sorted(((z_lo - p1[2]) / dz, (z_hi - p1[2]) / dz))
    u0, u1 = max(t0, s0), min(t1, s1)
    return [(u0 + u1) / 2.0] if u0 <= u1 else []


def column_clearance(obs: Obstacle, p1: Point, p2: Point, margin_m: float
                     ) -> Optional[Tuple[float, float]]:
    """(lowest altitude above `obs`'s band top, the parameter it occurs at) over the stretch of leg
    that is inside `obs`'s XY column -- None if the leg never flies over that column.

    Exact, not sampled: altitude is linear in t, so its minimum over the XY window is at one end of
    that window. This is the number printed as the REASON an XY overlap is not a violation, so a
    sampled estimate of it -- which is what this was, and which could only report clearance at the
    parameters the grid happened to land on -- would be evidence, quoted in an ADR, that nothing
    computed."""
    window = xy_window(obs, p1, p2)
    if window is None:
        return None
    band_top = obs.z_m + obs.height_m + margin_m
    return min((lerp(p1, p2, t)[2] - band_top, t) for t in window)


def leg_report(geofence: GeofenceMap, index: int, p1: Point, p2: Point,
               margin_m: float = VERTICAL_MARGIN_M, step_m: float = SAMPLE_STEP_M) -> LegReport:
    """Judge one leg: XY clearance (whole-segment, exact), vertical clearance over each tree column
    (exact), and the 3D verdict -- which comes from `GeofenceMap.unsafe_obstacle_3d` and from nothing
    else, so this gate and the executor's setpoint backstop cannot drift apart.

    Two sample sources, deliberately: the exact in-volume window of every tree, which is what makes
    the verdict independent of `step_m`; and a uniform sweep, which assumes nothing about obstacle
    SHAPE and so still covers the leg if the rule's volume ever stops being a cylinder while
    `volume_samples` still solves for one."""
    xy = geofence.segment_clearance((p1[0], p1[1]), (p2[0], p2[1]))

    ts = set(uniform_samples(p1, p2, step_m))
    vertical: Optional[Tuple[float, float, Obstacle]] = None   # (clearance, t, obstacle)
    for obs in geofence.obstacles:
        ts.update(volume_samples(obs, p1, p2, margin_m))
        column = column_clearance(obs, p1, p2, margin_m)
        if column is not None and (vertical is None or column < vertical[:2]):
            vertical = (column[0], column[1], obs)   # ties go to the column entered FIRST

    unsafe: List[Obstacle] = []          # every tree entered, not just the first: a leg down a row
    unsafe_point: Optional[Point] = None  # enters six of them, and a report that names one lies
    for t in sorted(ts):
        sample = lerp(p1, p2, t)
        inside = geofence.unsafe_obstacle_3d(sample, margin_m)     # THE verdict, the policy's rule
        if inside is not None:
            if not unsafe:
                unsafe_point = sample
            if inside not in unsafe:
                unsafe.append(inside)

    return LegReport(index=index, p1=p1, p2=p2,
                     xy_clearance_m=xy.clearance_m, xy_nearest=xy.obstacle,
                     vertical_clearance_m=vertical[0] if vertical else None,
                     vertical_obstacle=vertical[2] if vertical else None,
                     unsafe_obstacles=tuple(unsafe), unsafe_point=unsafe_point,
                     n_samples=len(ts))


def check_path(geofence: GeofenceMap, path: Sequence[Point],
               margin_m: float = VERTICAL_MARGIN_M, step_m: float = SAMPLE_STEP_M) -> List[LegReport]:
    return [leg_report(geofence, i, path[i], path[i + 1], margin_m, step_m)
            for i in range(len(path) - 1)]


def _fmt_point(p: Point) -> str:
    return f"({p[0]:6.2f},{p[1]:6.2f},{p[2]:6.2f})"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mission", type=Path, default=DEFAULT_MISSION)
    ap.add_argument("--static-obstacles", type=Path, default=DEFAULT_STATIC_OBSTACLES)
    ap.add_argument("--field-polygon", type=Path, default=DEFAULT_FIELD_POLYGON)
    args = ap.parse_args(argv)

    # Anything unreadable is exit 2, never a PASS: a gate that cannot see the mission has not
    # cleared it. An empty/1-point path is in the same class -- zero legs would "pass" vacuously.
    try:
        field_cfg = json.loads(args.field_polygon.read_text())
        home_lat, home_lon = field_cfg["home_lat"], field_cfg["home_lon"]
        path = mission_xyz_path(parse_qgc_wpl(args.mission), home_lat, home_lon)
        geofence = GeofenceMap.from_file(args.static_obstacles)
        if len(path) < 2:
            raise ValueError(f"{args.mission}: flattened to {len(path)} point(s) -- no legs to check")
        if len(geofence) == 0:
            raise ValueError(f"{args.static_obstacles}: no obstacles -- nothing to check against")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"[check_mission_geofence] ERROR: {exc}", file=sys.stderr)
        print("[check_mission_geofence] exit 2 -- unreadable inputs are not a PASS", file=sys.stderr)
        return 2

    print(f"[check_mission_geofence] mission: {args.mission}")
    print(f"[check_mission_geofence] {len(path)} flight-path points, {len(path) - 1} legs, "
          f"{len(geofence)} known static obstacles (trees)")
    print(f"[check_mission_geofence] rule: geofence.unsafe_obstacle_3d -- XY inside "
          f"obstacle_radius_m AND z in [z_m, z_m + height_m + {VERTICAL_MARGIN_M:.2f} m], the same "
          f"call the executor vets every GUIDED setpoint with")
    print(f"[check_mission_geofence] altitudes are the mission's own, linear along each leg "
          f"(takeoff climb and RTL descent included); sampled every {SAMPLE_STEP_M} m AND at the "
          f"solved midpoint of every tree's in-volume window\n")

    reports = check_path(geofence, path)
    for r in reports:
        nearest = r.xy_nearest.id if r.xy_nearest else "n/a"
        vert = (f"{r.vertical_clearance_m:+8.3f} m over {r.vertical_obstacle.id}"
                if r.vertical_clearance_m is not None else "     n/a")
        print(f"  leg {r.index:2d}  {_fmt_point(r.p1)} -> {_fmt_point(r.p2)}  "
              f"nearest={nearest:16s} xy={r.xy_clearance_m:7.3f} m  vert={vert}  {r.verdict}")
        if r.unsafe_obstacles:
            o = r.unsafe_obstacle
            print(f"          *** UNSAFE -- enters {len(r.unsafe_obstacles)} tree volume(s) "
                  f"[{', '.join(x.id for x in r.unsafe_obstacles)}], first at "
                  f"{_fmt_point(r.unsafe_point)}; band {o.z_m:.2f} to "
                  f"{o.z_m + o.height_m + VERTICAL_MARGIN_M:.2f} m, "
                  f"radius {o.obstacle_radius_m:.2f} m ***")

    worst_xy = min(reports, key=lambda r: r.xy_clearance_m)
    over = [r for r in reports if r.vertical_clearance_m is not None]
    unsafe = [r for r in reports if r.unsafe_obstacles]
    print()
    print(f"[check_mission_geofence] MIN XY CLEARANCE: {worst_xy.xy_clearance_m:.3f} m "
          f"(leg {worst_xy.index}, nearest obstacle "
          f"{worst_xy.xy_nearest.id if worst_xy.xy_nearest else 'n/a'}) -- an XY overlap is not by "
          f"itself a violation; the 3D verdict is")
    if over:
        w = min(over, key=lambda r: r.vertical_clearance_m)
        o = w.vertical_obstacle
        print(f"[check_mission_geofence] MIN VERTICAL CLEARANCE OVER A TREE COLUMN: "
              f"{w.vertical_clearance_m:+.3f} m (leg {w.index}, over {o.id}; band top = "
              f"{o.z_m:.2f} + {o.height_m:.2f} + {VERTICAL_MARGIN_M:.2f} = "
              f"{o.z_m + o.height_m + VERTICAL_MARGIN_M:.2f} m)")
    else:
        print("[check_mission_geofence] MIN VERTICAL CLEARANCE OVER A TREE COLUMN: n/a -- no leg "
              "passes over a tree's column at all")
    n_clear = sum(1 for r in reports if r.verdict == "CLEAR")
    print(f"[check_mission_geofence] legs: {n_clear} CLEAR, {len(over) - len(unsafe)} "
          f"CLEAR-BY-ALTITUDE, {len(unsafe)} in-volume "
          f"({sum(r.n_samples for r in reports)} samples, step {SAMPLE_STEP_M} m, "
          f"margin {VERTICAL_MARGIN_M} m)")

    if unsafe:
        named = "; ".join(f"leg {r.index} ({', '.join(o.id for o in r.unsafe_obstacles)})"
                          for r in unsafe)
        print(f"[check_mission_geofence] FAIL -- {len(unsafe)} of {len(reports)} legs enter a "
              f"tree's 3D volume: {named}")
        return 1
    print(f"[check_mission_geofence] PASS -- 0 of {len(reports)} legs enter a tree's 3D volume")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
