"""Coverage-grid + coverage-debt ledger invariant (Week 2 safety scaffolding).

This module is the *checkable target* the Week 3-4 reactive-avoidance loop must satisfy. It does
NOT implement avoidance or planning (that is Week 3-4 scope, out of bounds per ADR-002). It defines,
as pure geometry + bookkeeping:

  1. A CANONICAL, deterministic partition of the field polygon into grid cells
     (`build_grid`). Deterministic = same field polygon + cell_size always yields the exact same
     ordered cell set, with no seed and no floating drift, so "cell X" means the same thing in a
     test, in a scenario spec, and in a Week 3-4 flight log.

  2. Which cells a flown XY polyline COVERS (`coverage_from_path`), given a camera swath half-width.
     A "flown polyline" is the nominal mission today and the actual (avoidance-perturbed) flight
     path in Weeks 3-4 -- same function, so the coverage claim is computed identically before and
     after avoidance exists.

  3. The COVERAGE-DEBT LEDGER INVARIANT (`check_ledger`) -- the concrete definition of the core
     safety property in CLAUDE.md: "avoidance never silently drops a coverage cell." See
     `eval/scenarios/README.md` for the prose contract; this is the executable version.

THE SWATH ASSUMPTION (read this -- it is where the coverage guarantee can silently rot):
`DEFAULT_SWATH_HALF_WIDTH_M` = mission lane spacing / 2 = 15 / 2 = 7.5 m. Full coverage HOLDS only
if the real downward NDVI camera's ground swath at `mission_altitude_m` (15 m) is at least the lane
spacing (15 m). That FOV->swath number has NOT been measured against the real Gazebo camera yet.
If the true swath is narrower, uncovered strips open up *between* lanes and no amount of avoidance
logic will fix it -- it is a coverage bug baked into the mission plan. `test_coverage.py` includes
a negative-control test proving this checker actually detects such strips (it is not vacuously
green). Flag for perception-ml-engineer / robotics-sim-engineer: measure the real swath and replace
this assumption with a derived number.

Dependency: stdlib only (math, dataclasses) -- deliberate, so these run without a venv or the
Docker/Gazebo/ROS 2 stack (same reason as geofence.py / mission_waypoints.py).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FIELD_POLYGON = REPO_ROOT / "config" / "field_polygon.json"

# Lane spacing is 15 m (config/field_polygon.json polygon_note); swath half-width = spacing/2 so
# adjacent lanes' swaths meet exactly. SEE MODULE DOCSTRING -- this is an unvalidated assumption.
DEFAULT_SWATH_HALF_WIDTH_M = 7.5
# 2.5 m cells -> 30 x 24 = 720 cells over the 75x60 field. Fine enough to catch a dropped strip,
# coarse enough that the pure-python checks stay instant.
DEFAULT_CELL_SIZE_M = 2.5

# Terminal ledger statuses. REQUEUED is deliberately NOT terminal -- it is an event; a cell that is
# requeued and later imaged terminates COVERED, one that is requeued but never re-imaged terminates
# DEBT. See check_ledger / eval/scenarios/README.md.
CELL_COVERED = "covered"
CELL_DEBT = "debt"
TERMINAL_STATUSES = frozenset({CELL_COVERED, CELL_DEBT})


@dataclass(frozen=True)
class CoverageCell:
    """One field grid cell. `cell_id` is stable and human-readable so it can appear verbatim in a
    flight log and a failing-test message."""
    cell_id: str
    i: int          # column index (east)
    j: int          # row index (north)
    cx_m: float     # center East
    cy_m: float     # center North


def _point_in_polygon(px: float, py: float, poly: Sequence[Tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon (works for the current rectangle and any future concave field).
    Boundary handling is not exact-tie-critical here: cell CENTERS are tested, never edges."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def load_field_polygon(path: Path = DEFAULT_FIELD_POLYGON) -> List[Tuple[float, float]]:
    data = json.loads(Path(path).read_text())
    return [(float(x), float(y)) for x, y in data["polygon_m"]]


def build_grid(polygon: Sequence[Tuple[float, float]],
               cell_size_m: float = DEFAULT_CELL_SIZE_M) -> List[CoverageCell]:
    """Deterministic partition of `polygon`'s bounding box into `cell_size_m` cells, keeping only
    cells whose CENTER falls inside the polygon. Ordered (i, then j) so iteration is stable."""
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    n_i = int(math.ceil((max_x - min_x) / cell_size_m - 1e-9))
    n_j = int(math.ceil((max_y - min_y) / cell_size_m - 1e-9))
    cells: List[CoverageCell] = []
    for i in range(n_i):
        cx = min_x + (i + 0.5) * cell_size_m
        for j in range(n_j):
            cy = min_y + (j + 0.5) * cell_size_m
            if _point_in_polygon(cx, cy, polygon):
                cells.append(CoverageCell(cell_id=f"cell_{i}_{j}", i=i, j=j, cx_m=cx, cy_m=cy))
    return cells


def _point_segment_distance(px: float, py: float,
                            ax: float, ay: float, bx: float, by: float) -> float:
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


def coverage_from_path(cells: Sequence[CoverageCell],
                       path: Sequence[Tuple[float, float]],
                       swath_half_width_m: float = DEFAULT_SWATH_HALF_WIDTH_M) -> Dict[str, bool]:
    """For each cell, True iff its center is within `swath_half_width_m` (perpendicular) of ANY leg
    of the flown polyline `path`. Models the downward camera imaging a swath along the whole flown
    line -- identical for the nominal mission and a Week 3-4 avoidance-perturbed path."""
    covered: Dict[str, bool] = {}
    legs = [(path[k], path[k + 1]) for k in range(len(path) - 1)]
    for cell in cells:
        hit = False
        for (ax, ay), (bx, by) in legs:
            if _point_segment_distance(cell.cx_m, cell.cy_m, ax, ay, bx, by) <= swath_half_width_m:
                hit = True
                break
        covered[cell.cell_id] = hit
    return covered


@dataclass(frozen=True)
class LedgerResult:
    """Outcome of checking a flight log's coverage ledger against the canonical grid."""
    ok: bool
    n_cells: int
    covered: List[str]
    debt: List[str]
    missing: List[str]           # in grid, absent from ledger == SILENT SKIP (the headline bug)
    duplicates: List[str]        # logged twice with a terminal status (ambiguous accounting)
    unknown_cell_ids: List[str]  # logged a cell id that is not in the canonical grid
    bad_status: List[str]        # terminal status not in {covered, debt}
    errors: List[str]

    @property
    def debt_count(self) -> int:
        return len(self.debt)

    @property
    def covered_count(self) -> int:
        return len(self.covered)


def check_ledger(grid_cell_ids: Sequence[str],
                 records: Sequence[dict]) -> LedgerResult:
    """THE coverage-debt invariant, executable form. `records` is the terminal per-cell ledger from
    a flight log: a list of {"cell_id": str, "status": "covered"|"debt"} (list, not dict, so double
    -logging a cell is detectable). Prose contract: eval/scenarios/README.md.

    A ledger is OK iff:
      (P1 PARTITION)   every canonical grid cell appears exactly once  -> no `missing`, no `duplicates`.
                       A cell MISSING from the ledger is a SILENTLY-SKIPPED cell -- the exact failure
                       CLAUDE.md forbids -- and is the loudest possible fail here.
      (P2 STATUS)      every terminal status is `covered` or `debt`    -> no `bad_status`.
      (P3 KNOWN CELLS) no ledger cell id is outside the canonical grid -> no `unknown_cell_ids`.

    NOTE ON THE v1 BAR (ADR-002): a nonzero `debt` count is NOT a failure of this invariant --
    "avoid, return to next waypoint" is allowed to leave debt, as long as that debt is EXPLICIT
    (i.e. every dropped cell is present with status `debt`, never simply absent). The stretch goal
    (full reconciliation) is the stricter, separate assertion debt_count == 0; callers assert that
    only when testing the stretch behavior. This function proves the loop is HONEST, not that it is
    complete."""
    grid_set = set(grid_cell_ids)
    seen: Dict[str, str] = {}
    duplicates: List[str] = []
    unknown_cell_ids: List[str] = []
    bad_status: List[str] = []
    for r in records:
        cid = r.get("cell_id")
        st = r.get("status")
        if st not in TERMINAL_STATUSES:
            bad_status.append(f"{cid}:{st!r}")
        if cid in seen:
            duplicates.append(cid)
        seen[cid] = st
        if cid not in grid_set:
            unknown_cell_ids.append(cid)
    missing = [c for c in grid_cell_ids if c not in seen]
    covered = sorted(c for c, s in seen.items() if s == CELL_COVERED and c in grid_set)
    debt = sorted(c for c, s in seen.items() if s == CELL_DEBT and c in grid_set)

    errors: List[str] = []
    if missing:
        errors.append(f"{len(missing)} cell(s) SILENTLY SKIPPED (absent from ledger): "
                      f"{missing[:5]}{'...' if len(missing) > 5 else ''}")
    if duplicates:
        errors.append(f"{len(duplicates)} cell(s) logged twice (ambiguous accounting): "
                      f"{duplicates[:5]}")
    if unknown_cell_ids:
        errors.append(f"{len(unknown_cell_ids)} ledger cell id(s) not in canonical grid: "
                      f"{unknown_cell_ids[:5]}")
    if bad_status:
        errors.append(f"{len(bad_status)} cell(s) with non-terminal/unknown status: {bad_status[:5]}")

    ok = not (missing or duplicates or unknown_cell_ids or bad_status)
    return LedgerResult(ok=ok, n_cells=len(grid_cell_ids), covered=covered, debt=debt,
                        missing=missing, duplicates=duplicates,
                        unknown_cell_ids=unknown_cell_ids, bad_status=bad_status, errors=errors)


def ledger_from_covered_map(covered_map: Dict[str, bool]) -> List[dict]:
    """Convenience: turn a coverage_from_path() result into a terminal ledger (covered->covered,
    uncovered->debt). This is what a *perfect-instrumentation, no-requeue* flight would log; the
    Week 3-4 loop will instead build the ledger from real detections/avoidance/requeue events."""
    return [{"cell_id": cid, "status": CELL_COVERED if hit else CELL_DEBT}
            for cid, hit in covered_map.items()]
