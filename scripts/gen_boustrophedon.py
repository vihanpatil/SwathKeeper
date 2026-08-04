#!/usr/bin/env python3
"""Generate a boustrophedon (lawnmower) coverage mission for ArduPilot AUTO mode.

FieldGuard Week-1 MVP coverage planner: a standalone .waypoints generator over a rectangular field.
The production planner (arbitrary field polygon, coverage-debt tracking, a ROS 2 node in
fieldguard_planning) is future work; this proves the end-to-end AUTO mission loop for §8 of
docs/WEEK1_BRINGUP.md. Output is QGC WPL 110, loadable with MAVProxy `wp load`.

Example:
    python3 scripts/gen_boustrophedon.py --width 80 --height 60 --spacing 15 --alt 15
"""
import argparse
import math

# iris_runway world origin (== SITL home): see sim world spherical_coordinates.
DEFAULT_HOME_LAT = -35.363262
DEFAULT_HOME_LON = 149.165237


def boustrophedon_latlon(home_lat, home_lon, width_m, height_m, spacing_m):
    """Lanes run north (0->height), stepping east by spacing, alternating direction (lawnmower).

    Returns a list of (lat, lon) coverage waypoints. Meter offsets are converted to lat/lon with a
    local flat-earth approximation, which is plenty accurate over a field of this size.
    """
    m_per_deg_lat = 111320.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(home_lat))

    def to_ll(north_m, east_m):
        return (home_lat + north_m / m_per_deg_lat,
                home_lon + east_m / m_per_deg_lon)

    n_lanes = int(width_m / spacing_m) + 1
    pts = []  # (north_m, east_m)
    for i in range(n_lanes):
        east = i * spacing_m
        lane = [(0.0, east), (height_m, east)]
        if i % 2 == 1:          # every other lane runs the opposite direction
            lane.reverse()
        pts.extend(lane)
    return [to_ll(n, e) for (n, e) in pts], n_lanes


def write_qgc_wpl(path, home_lat, home_lon, waypoints, alt_m):
    """Write a QGC WPL 110 mission: home, NAV_TAKEOFF, coverage NAV_WAYPOINTs, then RTL."""
    NAV_WAYPOINT, NAV_TAKEOFF, NAV_RTL = 16, 22, 20
    FRAME_GLOBAL, FRAME_REL_ALT = 0, 3  # 3 = MAV_FRAME_GLOBAL_RELATIVE_ALT
    rows, seq = ["QGC WPL 110"], 0

    def row(cur, frame, cmd, lat, lon, alt):
        nonlocal seq
        rows.append(f"{seq}\t{cur}\t{frame}\t{cmd}\t0\t0\t0\t0\t"
                    f"{lat:.7f}\t{lon:.7f}\t{alt:.6f}\t1")
        seq += 1

    row(1, FRAME_GLOBAL, NAV_WAYPOINT, home_lat, home_lon, 0.0)   # 0: home (placeholder)
    row(0, FRAME_REL_ALT, NAV_TAKEOFF, 0.0, 0.0, alt_m)           # 1: climb to alt
    for lat, lon in waypoints:                                    # 2..N: sweep the field
        row(0, FRAME_REL_ALT, NAV_WAYPOINT, lat, lon, alt_m)
    row(0, FRAME_REL_ALT, NAV_RTL, 0.0, 0.0, 0.0)                 # N+1: return + land
    with open(path, "w") as f:
        f.write("\n".join(rows) + "\n")
    return seq


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home-lat", type=float, default=DEFAULT_HOME_LAT)
    ap.add_argument("--home-lon", type=float, default=DEFAULT_HOME_LON)
    ap.add_argument("--width", type=float, default=80.0, help="field east-west extent, m")
    ap.add_argument("--height", type=float, default=60.0, help="field north-south extent, m")
    ap.add_argument("--spacing", type=float, default=15.0, help="lane spacing, m")
    ap.add_argument("--alt", type=float, default=15.0, help="mission altitude (relative), m")
    ap.add_argument("-o", "--out", default="config/missions/boustrophedon.waypoints")
    args = ap.parse_args()

    wps, n_lanes = boustrophedon_latlon(args.home_lat, args.home_lon,
                                        args.width, args.height, args.spacing)
    n_items = write_qgc_wpl(args.out, args.home_lat, args.home_lon, wps, args.alt)
    print(f"Wrote {n_items} mission items ({len(wps)} coverage waypoints across {n_lanes} lanes, "
          f"{args.width:.0f}x{args.height:.0f} m field @ {args.alt:.0f} m) -> {args.out}")


if __name__ == "__main__":
    main()
