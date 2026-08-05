"""QGC WPL 110 mission-file parsing + lat/lon -> local ENU meters conversion.

Reads the `.waypoints` files `scripts/gen_boustrophedon.py` writes (e.g.
`config/missions/boustrophedon.waypoints`) and converts them into the same local ENU frame
`config/static_obstacles.json` and `config/field_polygon.json` use, so a mission and the geofence
map can be checked against each other directly (see `geofence.py` and
`scripts/check_mission_geofence.py`).

The lat/lon -> ENU conversion is the exact inverse of `scripts/gen_boustrophedon.py`'s
`boustrophedon_latlon()` (same flat-earth approximation, same constants) -- deliberately not
reimplemented differently, so round-tripping a generated mission through this module reproduces
the original meter offsets to float precision, not just approximately.

Dependency: stdlib only (math, pathlib) -- see `geofence.py` module docstring for why.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

M_PER_DEG_LAT = 111320.0  # matches scripts/gen_boustrophedon.py

# QGC WPL 110 MAV_CMD ids relevant to this project's missions.
NAV_WAYPOINT = 16
NAV_TAKEOFF = 22
NAV_RTL = 20


@dataclass(frozen=True)
class MissionItem:
    seq: int
    current: int
    frame: int
    command: int
    lat: float
    lon: float
    alt: float


def m_per_deg_lon(home_lat_deg: float) -> float:
    return M_PER_DEG_LAT * math.cos(math.radians(home_lat_deg))


def latlon_to_enu(lat: float, lon: float, home_lat: float, home_lon: float) -> Tuple[float, float]:
    """(lat, lon) -> (east_m, north_m) relative to (home_lat, home_lon). Inverse of
    scripts/gen_boustrophedon.py's to_ll()."""
    north_m = (lat - home_lat) * M_PER_DEG_LAT
    east_m = (lon - home_lon) * m_per_deg_lon(home_lat)
    return east_m, north_m


def parse_qgc_wpl(path: Path) -> List[MissionItem]:
    """Parse a QGC WPL 110 file into an ordered list of MissionItem. Raises ValueError on a
    missing/mismatched header, since a silently-misparsed mission is worse than a loud failure
    here (this feeds a safety cross-check, not just a display)."""
    lines = Path(path).read_text().splitlines()
    if not lines or not lines[0].strip().startswith("QGC WPL 110"):
        raise ValueError(f"{path}: missing/unexpected 'QGC WPL 110' header (got: {lines[:1]!r})")

    items = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) != 12:
            raise ValueError(f"{path}: expected 12 tab-separated fields, got {len(fields)}: {line!r}")
        seq, current, frame, command = (int(fields[0]), int(fields[1]), int(fields[2]), int(fields[3]))
        lat, lon, alt = float(fields[8]), float(fields[9]), float(fields[10])
        items.append(MissionItem(seq=seq, current=current, frame=frame, command=command,
                                  lat=lat, lon=lon, alt=alt))
    return items


def mission_xy_path(items: List[MissionItem], home_lat: float, home_lon: float) -> List[Tuple[float, float]]:
    """Flatten a parsed mission into the ordered (east_m, north_m) polyline the vehicle actually
    flies in the XY plane -- what a geofence/clearance check should run against.

    NAV_TAKEOFF and NAV_RTL items carry placeholder (0,0) lat/lon in this project's generated
    missions (see scripts/gen_boustrophedon.py write_qgc_wpl): TAKEOFF climbs straight up from
    wherever the vehicle currently is (home, at mission start) and RTL flies straight back to
    home. Both are therefore mapped to the running "current position" rather than taken literally
    as (0,0) lat/lon, which would otherwise put a bogus point at (home_lat, home_lon) offset by
    the full home lat/lon itself (a real, non-obvious parsing trap if you don't special-case it).
    """
    if not items:
        return []

    # Item 0 is always the home placeholder row (current=1, cmd=NAV_WAYPOINT, real home lat/lon).
    home_item = items[0]
    home_xy = latlon_to_enu(home_item.lat, home_item.lon, home_lat, home_lon)

    path: List[Tuple[float, float]] = [home_xy]
    for item in items[1:]:
        if item.command in (NAV_TAKEOFF, NAV_RTL):
            xy = home_xy  # climbs/returns in place over the home position (ADR: see docstring)
        elif item.command == NAV_WAYPOINT:
            xy = latlon_to_enu(item.lat, item.lon, home_lat, home_lon)
        else:
            continue  # unhandled command type; skip rather than guess
        path.append(xy)
    return path
