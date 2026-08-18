#!/usr/bin/env python3
"""Week 2 sanity cross-check: does the boustrophedon mission clip any tree's geofence in XY?

Loads `config/missions/boustrophedon.waypoints` and `config/static_obstacles.json`, flattens the
mission into its ordered XY flight path (`fieldguard_planning.mission_waypoints`), and runs every
leg through the geofence exclusion check (`fieldguard_planning.geofence`). Reports the min
clearance per leg and overall -- "no 'it works' without a number" (CLAUDE.md working conventions).

This is a pure-logic / stdlib-only check (no Gazebo/ArduPilot/ROS 2 needed) -- see
docs/runbooks/SIM_BRINGUP.md and this task's Week 2 hand-off note on environment honesty: it validates
mission-vs-geofence geometry, not that the mission actually flies in Gazebo (that needs the human
Docker run, see sim/README.md "Launching the world").

Usage:
    python3 scripts/check_mission_geofence.py
    python3 scripts/check_mission_geofence.py --mission path/to/other.waypoints
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.geofence import GeofenceMap  # noqa: E402
from fieldguard_planning.mission_waypoints import mission_xy_path, parse_qgc_wpl  # noqa: E402

DEFAULT_MISSION = REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints"
DEFAULT_STATIC_OBSTACLES = REPO_ROOT / "config" / "static_obstacles.json"
DEFAULT_FIELD_POLYGON = REPO_ROOT / "config" / "field_polygon.json"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mission", type=Path, default=DEFAULT_MISSION)
    ap.add_argument("--static-obstacles", type=Path, default=DEFAULT_STATIC_OBSTACLES)
    ap.add_argument("--field-polygon", type=Path, default=DEFAULT_FIELD_POLYGON)
    args = ap.parse_args()

    field_cfg = json.loads(args.field_polygon.read_text())
    home_lat, home_lon = field_cfg["home_lat"], field_cfg["home_lon"]
    mission_alt_m = field_cfg["mission_altitude_m"]

    items = parse_qgc_wpl(args.mission)
    path = mission_xy_path(items, home_lat, home_lon)
    geofence = GeofenceMap.from_file(args.static_obstacles)

    print(f"[check_mission_geofence] mission: {args.mission}")
    print(f"[check_mission_geofence] {len(path)} flight-path points, {len(path) - 1} legs, "
          f"{len(geofence)} known static obstacles (trees)")
    print(f"[check_mission_geofence] mission altitude: {mission_alt_m} m "
          f"(vertical clearance vs. tree height is a separate, already-documented check -- "
          f"see sim/README.md; this script checks XY only)\n")

    leg_results = geofence.check_path(path)
    overall_min = None
    violations = []
    for i, result in leg_results:
        p1, p2 = path[i], path[i + 1]
        tag = f"{result.obstacle.id}" if result.obstacle else "n/a"
        flag = ""
        if result.clearance_m <= 0.0:
            flag = "  *** VIOLATION -- inside obstacle_radius_m ***"
            violations.append((i, result))
        print(f"  leg {i:2d}  ({p1[0]:6.2f},{p1[1]:6.2f}) -> ({p2[0]:6.2f},{p2[1]:6.2f})  "
              f"nearest={tag:16s}  clearance={result.clearance_m:7.3f} m{flag}")
        if overall_min is None or result.clearance_m < overall_min.clearance_m:
            overall_min = result
            overall_min_leg = i

    print()
    print(f"[check_mission_geofence] MIN XY CLEARANCE: {overall_min.clearance_m:.3f} m "
          f"(leg {overall_min_leg}, nearest obstacle {overall_min.obstacle.id})")
    if violations:
        print(f"[check_mission_geofence] {len(violations)} leg(s) VIOLATE the XY geofence "
              f"(clearance <= 0). This is EXPECTED at this project's current altitude/tree-height "
              f"ratio -- see sim/README.md: mission_altitude_m={mission_alt_m} vs tree height "
              f"3.5m gives >11m of vertical separation, so a 2D/XY overlap here does not mean an "
              f"unsafe flight. Flag for Week 3-4: if avoidance work later needs the mission to "
              f"force a real XY dodge (e.g. by lowering altitude or raising tree height), this is "
              f"exactly where that would first show up.")
        return 1
    else:
        print("[check_mission_geofence] no XY geofence violations.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
