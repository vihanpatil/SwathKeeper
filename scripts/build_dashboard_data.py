#!/usr/bin/env python3
"""Populate `dashboard/data/` from the committed evidence -- every byte copied or derived.

WHY THIS SCRIPT EXISTS. The v1 dashboard (ADR-018) is a static client-side page served straight off
GitHub Pages, so it can only read files that sit beside it. `eval/results/` is gitignored (its
contents are force-added, reviewed artifacts), the clips are 12 GB, and the flight logs live at
paths a Pages URL cannot reach. This script is the ONE seam between the evidence and the page, and
it has exactly two moves:

  * COPY, byte for byte -- flight logs, safety-finding markers, stitched heatmaps, clip meta. The
    page's numbers then come from the same bytes the gates read. `sha256` of every source is
    recorded in `manifest.json` so a reader can verify the copy: `shasum -a 256 <source>`.
  * DERIVE, by calling the gates themselves -- never by re-implementing them. Verdicts come from
    `check_live_flight_log.check_file`, the ground-truth CPA from that module's `ground_truth_cpa`,
    the tree/canopy oracle from `check_tree_positions.analyse`, the canonical grid from
    `fieldguard_planning.coverage.build_grid`, the mission lanes from `mission_waypoints`. If a gate
    changes its mind, the dashboard changes with it on the next rebuild -- it cannot hold a stale
    verdict, because it never had its own.

NO HAND-AUTHORED NUMBERS. Not one figure in `dashboard/` is typed by a human. The headline numbers
(720/720 cells, 18/18 trees, 11/18 canopy-grade, median lift, detector rate, CPA) are recomputed by
the PAGE from the copied artifacts; the derived oracles written here exist so the page can
cross-check itself and shout if the two disagree.

REBUILD, IDEMPOTENCE, FRESHNESS. The build always runs into a temp tree and then syncs, so a file
this script no longer produces cannot linger. Nothing timestamped or machine-specific is written, so
two runs over the same inputs produce byte-identical output; `--check` proves it without touching
the tree, and `tests/test_build_dashboard_data.py` runs `--check` in CI. That pin is not
bureaucracy: the `spike_scores.json` drift (ADR-003 am. 10, 2026-08-26) was a committed COPY of a
derived artifact that silently stopped matching its source, and two internally-consistent stale
files agreed with each other for days. A copy that can go stale needs a freshness pin.

    python3 scripts/build_dashboard_data.py            # rebuild dashboard/data/
    python3 scripts/build_dashboard_data.py --check    # exit 1 if the tree is stale (no writes)

STDLIB ONLY, same reason as the gates it calls: this runs in CI with nothing but `src/` importable.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

import check_live_flight_log as GATE  # noqa: E402
import check_tree_positions as TREES  # noqa: E402
from fieldguard_planning.avoidance_policy import PolicyParams  # noqa: E402
from fieldguard_planning.coverage import (  # noqa: E402
    DEFAULT_CELL_SIZE_M, DEFAULT_SWATH_HALF_WIDTH_M, build_grid, load_field_polygon,
)
from fieldguard_planning.mission_waypoints import mission_xy_path, parse_qgc_wpl  # noqa: E402

RESULTS = REPO_ROOT / "eval" / "results"
CONFIG = REPO_ROOT / "config"
OUT_DIR = REPO_ROOT / "dashboard" / "data"

# The flights the dashboard shows: every live flight log committed as evidence. Listed rather than
# globbed so adding a flight to the dashboard is a reviewed diff -- the same doctrine as the gate's
# own pinned stem lists, and it keeps a stray log dropped into eval/results/ from silently becoming
# published evidence.
FLIGHT_STEMS = (
    "live_flight_log_20260818T144711Z",
    "live_flight_log_20260823T004031Z",
    "live_flight_log_20260825T210402Z",
)

# The stitched clips the NDVI view offers. Both are committed, both PASS check_tree_positions, and
# they are the pair the ROADMAP quotes against each other (the 2026-08-25 take vs the ADR-003-adopted
# 2026-08-23 clip). Clips marked INVALID_DO_NOT_USE.md are deliberately absent.
CLIP_NAMES = (
    "real_flight_20260825T205705Z",
    "real_flight_20260823T073644Z",
)

MISSIONS = ("boustrophedon", "test_2lane")

# --- the airborne window (what the replay should open on) ---------------------------------------
# Every committed flight log opens with a long stretch of a parked vehicle -- 40-52 % of the ticks on
# two of the three -- because the avoidance node starts logging at bringup and the human arms and
# takes off at the MAVProxy prompt some seconds later (ADR-013: demo flights are HUMAN-FLOWN). The
# dashboard trims the DEFAULT VIEW to the airborne window; it never trims the data.
#
# The rule, and why each half of it: a tick is airborne when the telemetry z exceeds
# AIRBORNE_Z_M, and the window opens at the first tick whose next AIRBORNE_SUSTAIN_TICKS samples are
# ALL airborne (and closes at the last tick whose preceding run is).
#   * AIRBORNE_Z_M is 1.0 because that is already this project's definition of airborne: it is the
#     `z_threshold_m` the clip recorder writes into every clip's `meta.airborne` block. Inventing a
#     second threshold here would give the dashboard and the NDVI evidence two different ideas of
#     when the flight started.
#   * the sustain run rejects a single spurious sample. 5 ticks is ~1 s at the node's nominal 5 Hz
#     control rate -- long enough to be a climb, short enough to cost nothing at the real takeoff.
# Measured on the committed logs (see tests/test_build_dashboard_data.py, which re-derives all of
# this): the sustain requirement moves NO boundary on any of the three -- every one climbs cleanly --
# so it is insurance, not a fudge factor, and the test pins that fact.
AIRBORNE_Z_M = 1.0
AIRBORNE_SUSTAIN_TICKS = 5


def airborne_window(path) -> dict:
    """{first_motion_tick, last_motion_tick, ...} -- 1-based ticks, or the whole log when nothing flew."""
    zs = []
    for p in path:
        try:
            zs.append(float(p[2]))
        except (TypeError, ValueError, IndexError):
            zs.append(float("-inf"))       # unreadable sample is not evidence of flight
    n = len(zs)
    up = [z > AIRBORNE_Z_M for z in zs]
    k = AIRBORNE_SUSTAIN_TICKS
    first = next((i for i in range(n) if all(up[i:i + k]) and any(up[i:i + k])), None)
    last = next((i for i in range(n - 1, -1, -1)
                 if all(up[max(0, i - k + 1):i + 1]) and up[i]), None)
    airborne = sum(up)
    if first is None or last is None or last < first:
        return {"first_motion_tick": 1, "last_motion_tick": n, "airborne_ticks": airborne,
                "pre_flight_ticks": 0, "post_flight_ticks": 0, "z_threshold_m": AIRBORNE_Z_M,
                "sustain_ticks": k, "found": False,
                "rule": "no sustained airborne run in this log -- the replay opens on tick 1 and "
                        "claims nothing about when it flew"}
    # The bare first/last crossing, so the artifact shows what the sustain requirement actually cost.
    bare_first = next(i for i in range(n) if up[i])
    bare_last = next(i for i in range(n - 1, -1, -1) if up[i])
    return {
        "first_motion_tick": first + 1, "last_motion_tick": last + 1,
        "bare_first_crossing_tick": bare_first + 1, "bare_last_crossing_tick": bare_last + 1,
        "airborne_ticks": airborne, "pre_flight_ticks": first, "post_flight_ticks": n - 1 - last,
        "z_threshold_m": AIRBORNE_Z_M, "sustain_ticks": k, "found": True,
        "rule": f"first tick whose next {k} telemetry samples all read z > {AIRBORNE_Z_M} m "
                f"(the clip recorder's own airborne threshold), and the last tick whose preceding "
                f"{k} do. Derived from flown_path_enu; the data is never trimmed, only the default "
                f"view.",
    }


# ================================================================================================
# output plumbing -- everything lands in a staging tree first, so a removed output cannot linger
# ================================================================================================
class Build:
    """Accumulates files + their provenance, then syncs the staging tree onto the real one."""

    def __init__(self, stage: Path):
        self.stage = stage
        self.sources: List[dict] = []

    def _dest(self, rel: str) -> Path:
        dest = self.stage / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        return dest

    def copy(self, src: Path, rel: str, role: str) -> None:
        """Byte-for-byte copy of a committed artifact, with its sha256 recorded."""
        data = src.read_bytes()
        self._dest(rel).write_bytes(data)
        self.note_source(src, role, data)

    def derive(self, obj, rel: str) -> None:
        """A derived JSON, written deterministically (sorted keys, fixed indent, trailing newline)."""
        self._dest(rel).write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")

    def note_source(self, src: Path, role: str, data: Optional[bytes] = None) -> None:
        rel = str(src.relative_to(REPO_ROOT))
        if any(s["path"] == rel for s in self.sources):
            return
        blob = src.read_bytes() if data is None else data
        self.sources.append({
            "path": rel,
            "role": role,
            "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
        })


def sync(stage: Path, out: Path) -> List[str]:
    """Make `out` equal `stage`. Returns the sorted list of relative paths that differed."""
    wanted = {str(p.relative_to(stage)): p for p in stage.rglob("*") if p.is_file()}
    have = {str(p.relative_to(out)): p for p in out.rglob("*") if p.is_file()} if out.exists() else {}
    changed: List[str] = []
    for rel, src in sorted(wanted.items()):
        dst = out / rel
        if rel not in have or dst.read_bytes() != src.read_bytes():
            changed.append(rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
    for rel in sorted(set(have) - set(wanted)):
        changed.append(rel)
        (out / rel).unlink()
    for d in sorted((p for p in out.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
        if not any(d.iterdir()):
            d.rmdir()
    return sorted(changed)


def diff(stage: Path, out: Path) -> List[str]:
    """Relative paths where `out` disagrees with a fresh build. Empty == fresh."""
    wanted = {str(p.relative_to(stage)): p.read_bytes() for p in stage.rglob("*") if p.is_file()}
    have = {str(p.relative_to(out)): p.read_bytes()
            for p in out.rglob("*") if p.is_file()} if out.exists() else {}
    return sorted({rel for rel in set(wanted) | set(have) if wanted.get(rel) != have.get(rel)})


# ================================================================================================
# the field: canonical grid, polygon, trees, mission lanes, scripted birds
# ================================================================================================
def build_field(b: Build) -> None:
    poly_path = CONFIG / "field_polygon.json"
    obstacles_path = CONFIG / "static_obstacles.json"
    birds_path = CONFIG / "birds" / "farm_world_birds.json"
    field = json.loads(poly_path.read_text())
    obstacles = json.loads(obstacles_path.read_text())
    birds_cfg = json.loads(birds_path.read_text())

    polygon = load_field_polygon(poly_path)
    grid = build_grid(polygon, DEFAULT_CELL_SIZE_M)

    missions = {}
    for name in MISSIONS:
        path = CONFIG / "missions" / f"{name}.waypoints"
        items = parse_qgc_wpl(path)
        missions[name] = {
            "file": str(path.relative_to(REPO_ROOT)),
            "xy_m": [[x, y] for x, y in mission_xy_path(items, field["home_lat"], field["home_lon"])],
            "alt_m": sorted({it.alt for it in items if it.command == 16}),
        }
        b.note_source(path, "planned mission (QGC WPL 110)")

    b.note_source(poly_path, "field polygon + home")
    b.note_source(obstacles_path, "surveyed static obstacles (ADR-001 geofence export)")
    b.note_source(birds_path, "scripted bird trajectories (the world's dynamic obstacles)")

    b.derive({
        "polygon_m": [[x, y] for x, y in polygon],
        "home_lat": field["home_lat"],
        "home_lon": field["home_lon"],
        "mission_altitude_m": field["mission_altitude_m"],
        "cell_size_m": DEFAULT_CELL_SIZE_M,
        "cells": [{"cell_id": c.cell_id, "i": c.i, "j": c.j, "cx_m": c.cx_m, "cy_m": c.cy_m}
                  for c in grid],
        "swath": {
            "camera_derived_half_width_m": DEFAULT_SWATH_HALF_WIDTH_M,
            "note": "fieldguard_planning.coverage.derive_swath_half_width_m from the committed "
                    "camera intrinsics at the 15 m cruise. The committed flight logs recorded "
                    "swath_half_width_m 7.5 (lane spacing / 2) and their ledgers were computed with "
                    "it; ADR-016 (2026-08-25) measured the true half-swath at 6.886 m, so each 15 m "
                    "lane pair leaves a 1.228 m strip no frame saw. The 720/720 claim survives only "
                    "by quantisation -- a 2.5 m cell CENTRE is at most 6.25 m from a lane.",
        },
        "trees": [{"id": o["id"], "pos_m": o["pos_m"], "obstacle_radius_m": o["obstacle_radius_m"],
                   "canopy_radius_m": o["canopy_radius_m"], "height_m": o["height_m"]}
                  for o in obstacles["obstacles"] if o.get("type") == "tree"],
        "tree_radius_note": obstacles["tree_defaults"]["obstacle_radius_note"],
        "missions": missions,
        "birds": [{"bird_id": bd["bird_id"], "physical_radius_m": bd["physical_radius_m"],
                   "loop": bd.get("loop", True),
                   "waypoints": [[w["t_s"], w["x_m"], w["y_m"], w["z_m"]] for w in bd["waypoints"]]}
                  for bd in birds_cfg["birds"]],
        "policy_params_defaults": dataclasses.asdict(PolicyParams()),
        "policy_params_note": "fieldguard_planning.avoidance_policy.PolicyParams defaults -- what "
                              "the policy would fly TODAY. Each flight logged the params it "
                              "actually flew; the replay reads those from the log, never from here.",
    }, "field.json")


# ================================================================================================
# flights: verbatim log + marker, and the gate's own verdict
# ================================================================================================
def _legacy_cpa_locate(log: dict) -> Optional[dict]:
    """Where on the flown path the LEGACY (detection-referenced) CPA lands.

    The VALUE is the gate's -- `closest_approach` -- and this function asserts it reproduces that
    value exactly before returning anything. It exists only to give the page a path index to draw a
    marker at, using the gate's OWN point-segment primitive so the geometry cannot diverge."""
    reported = GATE.closest_approach(log)
    if reported is None:
        return None
    dets = GATE.detection_positions(log)
    pts: List[Tuple[float, float]] = []
    for p in log.get("flown_path_enu") or []:
        try:
            pts.append((float(p[0]), float(p[1])))
        except (TypeError, ValueError, IndexError):
            continue
    best = None
    for i, ((ax, ay), (bx, by)) in enumerate(zip(pts, pts[1:])):
        for track_id, dx, dy in dets:
            d = GATE._point_segment_xy_m(dx, dy, ax, ay, bx, by)
            if best is None or d < best["cpa_m"]:
                best = {"cpa_m": d, "track_id": track_id, "segment_index": i,
                        "bird_xy_m": [dx, dy]}
    if best is None or best["cpa_m"] != reported[0]:
        raise SystemExit(
            "[build_dashboard_data] REFUSING: the located legacy CPA "
            f"({None if best is None else best['cpa_m']!r}) does not reproduce the gate's "
            f"{reported[0]!r}. The dashboard must never draw a marker the gate did not measure.")
    best["bar_m"] = GATE.min_bird_clearance_m()
    best["basis"] = ("detection-referenced: the drone's OWN logged detections, segment geometry "
                     "(schema-1 legacy path). NOT the bird ground truth.")
    return best


def _schema2_cpa(path: Path, log: dict) -> Optional[dict]:
    """The gate's ground-truth CPA report for a schema-2 log, verbatim, plus the freeze debit."""
    run = log["run"]
    truth, problems = GATE.resolve_truth(path, run)
    if truth is None:
        return {"unavailable": problems}
    pp = PolicyParams()
    report = GATE.ground_truth_cpa(log.get("flown_path_enu") or [],
                                   run.get("tick_stamp_sim_s") or [], truth,
                                   pp.vertical_threat_m, pp.threat_radius_m)
    adv = GATE.stamp_advance(run.get("tick_stamp_sim_s") or [])
    debit = GATE.freeze_debit_m(adv["frozen_window_s"])
    report["freeze_debit_m"] = debit
    report["gt_cpa_gated_m"] = (None if report["gt_cpa_m"] is None
                                else report["gt_cpa_m"] - debit)
    report["bar_m"] = GATE.min_bird_clearance_m()
    report["truth_track"] = truth.path.name
    report["truth_span_sim_s"] = list(truth.span) if truth.span else None
    report["stamp_advance"] = adv
    report["basis"] = ("ground truth: the birds' applied set_pose poses, read through the same "
                       "functions the ADR-003 labels use. Horizontal (XY), scoped to the policy's "
                       "own vertical_threat_m band, measured against the flown POLYLINE.")
    return report


def build_flights(b: Build) -> None:
    verdicts = {}
    for stem in FLIGHT_STEMS:
        log_path = RESULTS / f"{stem}.json"
        marker_path = GATE.marker_path_for(log_path)
        b.copy(log_path, f"flights/{stem}.json", "live flight log")
        entry: Dict[str, object] = {"stem": stem, "log": f"flights/{stem}.json"}
        if marker_path.exists():
            b.copy(marker_path, f"flights/{marker_path.name}", "written safety finding (marker)")
            entry["marker"] = f"flights/{marker_path.name}"

        status, messages = GATE.check_file(log_path)
        entry["verdict"] = status
        entry["gate_messages"] = list(messages)
        entry["gate"] = "scripts/check_live_flight_log.py"
        entry["acknowledged_pin"] = stem in GATE.ACKNOWLEDGED_BREACH_STEMS

        log = json.loads(log_path.read_text())
        version = GATE.schema_version(log)
        entry["schema_version"] = version
        entry["airborne"] = airborne_window(log.get("flown_path_enu") or [])
        entry["time_axis"] = ("sim_seconds" if version and version >= 2 else "tick_index")
        entry["cpa"] = (_schema2_cpa(log_path, log) if version and version >= 2
                        else _legacy_cpa_locate(log))
        verdicts[stem] = entry

        if version and version >= 2:
            build_truth(b, stem, log_path, log)

    b.derive({
        "flights": verdicts,
        "verdict_legend": {
            "VALID": "every gate green -- evidence of a flight that met its bars",
            "ACKNOWLEDGED": "a REVIEWED, recorded closest-approach breach: marker file beside the "
                            "log AND the stem pinned in ACKNOWLEDGED_BREACH_STEMS. Kept as "
                            "history, deliberately never the word VALID.",
            "INVALID": "the gate refuses this log as evidence of a safe flight",
        },
    }, "verdicts.json")


def build_truth(b: Build, stem: str, log_path: Path, log: dict) -> None:
    """The bound bird ground-truth track, projected to what a replay needs.

    Read through the gate's own `resolve_truth` (so the reviewed TRUTH_BINDINGS pin decides which
    track belongs to which flight) and its `applied_timeline` (so the poses are reconstructed by the
    same code the safety gate and the ADR-003 labels use). Each entry is
    `[sim_end_s, x, y, z]` -- `sim_end_s` is the instant the pose is CERTAINLY applied, which is
    exactly the rule `pose_from_applied` uses to say what the render was showing. The page steps
    between poses and never interpolates a bird."""
    truth, problems = GATE.resolve_truth(log_path, log["run"])
    if truth is None:
        b.derive({"unavailable": problems}, f"truth/{stem}.json")
        return
    b.note_source(truth.path, "bird ground truth (applied set_pose poses)")
    b.derive({
        "track": truth.path.name,
        "bound_by": "TRUTH_BINDINGS in scripts/check_live_flight_log.py (a reviewed pin)",
        "span_sim_s": list(truth.span) if truth.span else None,
        "landed_calls": truth.landed_counts,
        "spawn_m": {bid: list(truth._spawn_pos(bid)) for bid in sorted(truth.birds)},
        "poses": {bid: [[end, pos[0], pos[1], pos[2]]
                        for _start, end, pos, _t in truth.timeline.get(bid, ())]
                  for bid in sorted(truth.birds)},
        "note": "Outside span_sim_s the track observed nothing and the page draws no bird: "
                "'the bird held its last pose' is an extrapolation nothing measured.",
    }, f"truth/{stem}.json")


# ================================================================================================
# clips: the offline stitch (ADR-010) + the tree-placement oracle
# ================================================================================================
def build_clips(b: Build) -> None:
    index = {}
    for name in CLIP_NAMES:
        clip_dir = RESULTS / "clips" / name
        b.copy(clip_dir / "heatmap" / "heatmap.json", f"clips/{name}/heatmap.json",
               "offline NDVI stitch (ADR-010)")
        b.copy(clip_dir / "meta.json", f"clips/{name}/meta.json", "clip recorder metadata")
        oracle = TREES.analyse(clip_dir)
        oracle["clip_dir"] = str(clip_dir.relative_to(REPO_ROOT))
        oracle["gate"] = "scripts/check_tree_positions.py"
        b.derive(oracle, f"clips/{name}/tree_check.json")
        index[name] = {
            "heatmap": f"clips/{name}/heatmap.json",
            "meta": f"clips/{name}/meta.json",
            "tree_check": f"clips/{name}/tree_check.json",
        }
    b.derive({
        "clips": index,
        "note": "The page recomputes cells imaged, trees imaged, canopy-grade and median lift from "
                "heatmap.json + the surveyed tree positions, then cross-checks itself against "
                "tree_check.json (this gate's own output) and says so loudly if they disagree.",
    }, "clips/index.json")


# ================================================================================================
def build(stage: Path) -> Build:
    b = Build(stage)
    build_field(b)
    build_flights(b)
    build_clips(b)
    b.derive({
        "generated_by": "scripts/build_dashboard_data.py",
        "what": "Every file under dashboard/data/ is either a byte-for-byte copy of a committed "
                "artifact or is derived by calling the project's own gates. Nothing here is typed "
                "by hand, and nothing here carries a timestamp -- two runs over the same inputs "
                "produce identical bytes, which is what tests/test_build_dashboard_data.py pins.",
        "verify_a_copy": "shasum -a 256 <path> and compare with the sha256 below",
        "sources": sorted(b.sources, key=lambda s: s["path"]),
        "flights": list(FLIGHT_STEMS),
        "clips": list(CLIP_NAMES),
    }, "manifest.json")
    return b


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=OUT_DIR, help="output directory")
    ap.add_argument("--check", action="store_true",
                    help="do not write: exit 1 if the output tree differs from a fresh build")
    args = ap.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "data"
        stage.mkdir()
        build(stage)
        if args.check:
            stale = diff(stage, args.out)
            if stale:
                print(f"[build_dashboard_data] STALE: {len(stale)} file(s) in {args.out} disagree "
                      f"with a fresh build -- rerun scripts/build_dashboard_data.py and commit:",
                      file=sys.stderr)
                for rel in stale:
                    print(f"    - {rel}", file=sys.stderr)
                return 1
            n = sum(1 for _ in stage.rglob("*") if _.is_file())
            print(f"[build_dashboard_data] FRESH: all {n} file(s) match a fresh build.")
            return 0
        args.out.mkdir(parents=True, exist_ok=True)
        changed = sync(stage, args.out)
    total = sum(p.stat().st_size for p in args.out.rglob("*") if p.is_file())
    print(f"[build_dashboard_data] {args.out}: "
          f"{sum(1 for p in args.out.rglob('*') if p.is_file())} file(s), "
          f"{total / 1e6:.2f} MB, {len(changed)} changed")
    for rel in changed:
        print(f"    ~ {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
