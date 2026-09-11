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

# The MAV_CMD NAV block: 16 (NAV_WAYPOINT) .. 95 (NAV_LAST). EVERY command in it moves the vehicle,
# so one this module cannot place is a hole in the flight path, not a detail. DO_* / CONDITION_*
# commands are >= 112, change no position, and are correctly skipped. See `_flatten`.
NAV_COMMAND_RANGE = range(16, 96)

# MAV_FRAME 3 = GLOBAL_RELATIVE_ALT: `alt` is metres ABOVE HOME, which is the same z the geofence
# map, the Gazebo world and the executor's setpoints use. It is the only altitude frame
# `mission_xyz_path` can convert, and reading any other one as if it were this one is
# fail-DANGEROUS (a frame-0 waypoint carries AMSL -- ~584 m at this home -- which would float the
# whole mission far above every obstacle and pass anything), so it raises instead.
FRAME_GLOBAL_RELATIVE_ALT = 3


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

    This is `mission_xyz_path` with the altitude dropped -- one flattening, so a caller that only
    needs XY (the dashboard's lane overlay, `avoidance_node`'s mission path) cannot disagree with
    the 3D geofence gate about where the vehicle goes. It never raises -- neither on an altitude
    frame it cannot read (it never reads one) nor on an unmodelled NAV command (it draws an overlay;
    `mission_xyz_path` feeds a safety gate, and only the gate's input has to refuse).
    """
    return [(east, north)
            for east, north, _alt in _flatten(items, home_lat, home_lon, check_alt_frame=False)]


def mission_xyz_path(items: List[MissionItem], home_lat: float, home_lon: float
                     ) -> List[Tuple[float, float, float]]:
    """`mission_xy_path` plus the altitude each point is flown at: (east_m, north_m, alt_m_above_home).

    Altitudes are the mission's own `alt` fields, which is what makes a 3D geofence check honest on
    the legs that are NOT at cruise altitude -- the takeoff climb and the RTL descent. Two readings
    are deliberate:

      * The **home placeholder row** (item 0) is forced to **0.0 m**: its `alt` field is not a flight
        altitude (this project's generator writes 0.0; other GCSs write the home AMSL elevation), and
        the vehicle is on the ground there. Ground is the reading that cannot hide an obstacle.
      * Every other item keeps its own `alt`, so NAV_TAKEOFF is the climb target and this project's
        NAV_RTL (alt 0.0) is modelled as returning and landing. A leg is therefore a straight line in
        3D between consecutive points, and a caller that samples it sees the real climb/descent
        profile rather than a cruise-altitude fiction.

    It REFUSES what it cannot place, rather than dropping it: ValueError if any non-home item uses
    an altitude frame other than FRAME_GLOBAL_RELATIVE_ALT (see that constant), or carries a NAV
    command this module does not model (see NAV_COMMAND_RANGE). Both would otherwise hand a safety
    check a path with a hole in it, and the gate downstream turns a ValueError into exit 2 -- which
    is the point: "I could not read this mission" must never come out as PASS.
    """
    return _flatten(items, home_lat, home_lon, check_alt_frame=True)


def _flatten(items: List[MissionItem], home_lat: float, home_lon: float, check_alt_frame: bool
             ) -> List[Tuple[float, float, float]]:
    """The one mission-flattening. `check_alt_frame` is False for the XY-only view, which does not
    read `alt` at all and so must not reject a mission over how `alt` is expressed."""
    if not items:
        return []

    # Item 0 is always the home placeholder row (current=1, cmd=NAV_WAYPOINT, real home lat/lon).
    home_item = items[0]
    home_xy = latlon_to_enu(home_item.lat, home_item.lon, home_lat, home_lon)

    path: List[Tuple[float, float, float]] = [(home_xy[0], home_xy[1], 0.0)]
    for item in items[1:]:
        if item.command in (NAV_TAKEOFF, NAV_RTL):
            xy = home_xy  # climbs/returns in place over the home position (ADR: see docstring)
        elif item.command == NAV_WAYPOINT:
            xy = latlon_to_enu(item.lat, item.lon, home_lat, home_lon)
        elif check_alt_frame and item.command in NAV_COMMAND_RANGE:
            # A NAV command this module cannot place is DELETED from the path if we `continue`, and
            # its two neighbours get joined by a straight line the vehicle never flies -- so a
            # NAV_SPLINE_WAYPOINT sitting in a tree reads as PASS. Absence from the path IS the bug.
            # (It is also how an item slips past the MAV_FRAME check below.) Refuse, like the frame.
            raise ValueError(
                f"mission item seq={item.seq} uses NAV command {item.command}, which this module "
                f"cannot place: it moves the vehicle somewhere the flattened path would not go. "
                f"Model it here or the path is a fiction")
        else:
            continue  # DO_*/CONDITION_* and friends: they change no position, so nothing is lost
        if check_alt_frame and item.frame != FRAME_GLOBAL_RELATIVE_ALT:
            raise ValueError(
                f"mission item seq={item.seq} (command {item.command}) uses MAV_FRAME "
                f"{item.frame}, not {FRAME_GLOBAL_RELATIVE_ALT} (GLOBAL_RELATIVE_ALT): its alt "
                f"{item.alt} is not metres above home and must not be read as if it were")
        path.append((xy[0], xy[1], float(item.alt)))
    return path
