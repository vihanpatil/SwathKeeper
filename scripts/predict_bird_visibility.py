#!/usr/bin/env python3
"""Offline PRE-FLIGHT bird-visibility predictor: will any bird enter the nadir NDVI frame on this
mission, and for roughly how many frames? Answers in ~1 s, on the host, with no Docker session.

WHY THIS EXISTS (docs/DECISIONS.md ADR-003 amendment 1, 2026-08-21): the demo take flew the full
boustrophedon with all three birds airborne and produced **0 bird-visible frames out of 454**. A
nadir camera at 15 m sees 18.5 x 13.8 m of GROUND, but at the birds' altitudes as flown (6/8/11 m
AGL, i.e. 9/7/4 m of pinhole depth) the footprint shrinks to 11.1x8.3 / 8.6x6.5 / 4.9x3.7 m --
against a 15 m lane pitch. Nobody could have known before flying, and that flight cost a whole
Docker session.

This tool separates the two reasons a bird stays unseen, which is the thing the flight itself could
not tell anyone (`limited_by` in the report). On the AS-FLOWN geometry it found one of each:
  * STRUCTURAL -- bird_0 patrolled x=20.0, a fixed 5.00 m off lane x=15, where the cross-track
    half-footprint is 3.23 m. It was 1.81 m outside the frame edge at its BEST moment, at every
    driver-start offset. No cadence, speed or luck can ever show that; only geometry can.
  * TIMING -- bird_1 and bird_2 DO cross the lanes, so they were in frame for a median 3 and 11 of
    901 opportunities at the 5 Hz sensor tick (0.3 % / 1.2 %). At the demo take's actual airborne
    frame rate (0.41 Hz, 53 frames in 127.8 s -- ADR-013's throughput problem) that becomes a
    median 0 and 1: the measured zero, reproduced from pure config.
That split is what ADR-015 acted on: the committed geometry now predicts PASS (medians 8 / 6 / 11,
no bird structural) because bird_0's PATROL LINE moved onto the lane -- lowering it was measured to
fix nothing (the miss is cross-track) and to cost the avoidance story. The as-flown numbers above are
still reproduced on every test run, from a frozen copy of that config
(tests/fieldguard_planning/fixtures/farm_world_birds_asflown_20260821.json).

MODEL (deliberately small; every assumption is listed because a predictor nobody trusts is worse
than none):
  * The mission is flown as straight legs at a constant `--speed` (default 3 m/s), instantaneous
    turns, climb and descent at that same speed. Yaw faces the leg (ArduPilot's default
    WP_YAW_BEHAVIOR faces the next waypoint) -- and yaw MATTERS here: the 640-px image axis lies
    along the flight direction and the 480-px axis across it (ADR-007 mount extrinsic), so the
    cross-track half-footprint is the SHORTER one.
  * Frames are sampled at `--fps` (default 5.0 Hz = the sensor tick, config/ndvi_camera.json
    update_rate_hz). That is opportunity, not yield: only ~12 % of sensor ticks currently reach a
    recorded clip (ADR-013 am. 6a), so divide predicted frames by ~8 for expected RECORDED frames.
  * Birds fly the committed `config/birds/farm_world_birds.json` waypoints via the same
    `drive_birds.pose_at` interpolation the live driver uses -- imported, never re-implemented.
  * PHASE SWEEP: `scripts/fly_pipeline.sh` starts the bird driver when the vehicle passes 10 m, so
    trajectory time 0 is anchored there; how that lands relative to LANE timing is uncontrollable
    in practice, so the sweep walks a single offset (one driver, one t0 -- the birds' phases
    relative to EACH OTHER are fixed by the config) across the longest trajectory period. Every
    bird's own period divides that span, so each bird's phase space is covered completely.
  * Projection is `ndvi_georef.project_world_point` -- the SAME transform the heatmap stitch and
    `eval/label_from_sim.py`'s ground truth use, and the same hand-computed fixtures back it. A
    bird counts as in-frame when its apparent-size box overlaps the image, matching
    `eval/spike_common.clip_box` exactly (pinned by test).
  * NOT modelled: acceleration/deceleration (the demo take's own poses show cruise chords up to
    9.2 m/s against a 3.91 m/s median, so `--speed` is a real knob, not a constant), wind, the
    avoidance loop's dodges, occlusion by trees. Each shifts a TIMING bird's count; none can rescue
    a STRUCTURAL miss, which is the verdict this tool exists to deliver.

USE
    python3 scripts/predict_bird_visibility.py                       # the committed mission
    python3 scripts/predict_bird_visibility.py --mission config/missions/test_2lane.waypoints
    python3 scripts/predict_bird_visibility.py --json out.json       # for tooling / CI
    python3 scripts/predict_bird_visibility.py --backtest eval/results/clips/real_flight_...Z
                                                                     # score a FLOWN clip instead

`--backtest` is the honesty check: it replays a recorded clip's own poses.jsonl + birds[] through
the identical geometry and must reproduce what the flight measured. If the predictor cannot
reproduce a measured zero, the predictor is wrong.

Dependency: stdlib only (numpy is never needed -- this reads poses and config, never pixels).
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from fieldguard_planning.mission_waypoints import (  # noqa: E402
    NAV_RTL, NAV_TAKEOFF, NAV_WAYPOINT, latlon_to_enu, parse_qgc_wpl,
)
from fieldguard_planning.ndvi_georef import (  # noqa: E402
    MOUNT_OFFSET_BODY_M, CameraIntrinsics, camera_world_position, project_world_point,
)
from drive_birds import DEFAULT_BIRDS_CONFIG, pose_at  # noqa: E402

Vec3 = Tuple[float, float, float]
Quat = Tuple[float, float, float, float]  # (x, y, z, w)

DEFAULT_MISSION = REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints"
DEFAULT_FIELD_POLYGON = REPO_ROOT / "config" / "field_polygon.json"
DEFAULT_CAMERA_CONFIG = REPO_ROOT / "config" / "ndvi_camera.json"

DEFAULT_SPEED_MPS = 3.0        # WPNAV_SPEED as flown (docs/runbooks/SIM_BRINGUP.md)
DEFAULT_CADENCE_HZ = 5.0       # config/ndvi_camera.json update_rate_hz (sensor tick, not yield)
DEFAULT_PHASE_STEP_S = 0.5
DEFAULT_MIN_FRAMES = 5
BIRD_START_ALT_M = 10.0        # scripts/fly_pipeline.sh altitude gate: birds launch above 10 m

# Minimum pinhole depth for a projection to mean anything -- the same 0.5 m frustum gate
# `eval/spike_common.MIN_DEPTH_M` applies, restated (not imported) so this tool stays stdlib-only.
# Load-bearing on the landing leg, where the drone descends THROUGH the birds' altitude band and a
# near-zero depth would otherwise blow a distant bird up to an "in-frame" projection.
MIN_DEPTH_M = 0.5


# --------------------------------------------------------------------------------------------------
# Mission -> a timed, oriented flight path
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Leg:
    """One straight segment of the modelled flight, with the heading held along it."""
    label: str
    p0: Vec3
    p1: Vec3
    t0_s: float
    duration_s: float
    yaw_rad: float


def _leg_label(p0: Vec3, p1: Vec3) -> str:
    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    if math.hypot(dx, dy) < 1e-6:
        return "climb" if dz > 0 else "descend"
    if abs(dx) < 1e-6:
        return f"lane x={p0[0]:.0f} {'N' if dy > 0 else 'S'}"
    if abs(dy) < 1e-6:
        return f"cross y={p0[1]:.0f} {'E' if dx > 0 else 'W'}"
    return "transit"


def build_legs(mission_path: Path, home_lat: float, home_lon: float,
               speed_mps: float) -> List[Leg]:
    """Parsed QGC WPL -> the ordered legs the vehicle flies, timed at a constant ground speed.

    TAKEOFF/RTL carry placeholder (0,0) lat/lon in this project's generated missions -- the same
    trap `mission_waypoints.mission_xy_path` documents -- so they are mapped to the home position
    (climb in place / return home) rather than taken literally. RTL is modelled as return-at-
    altitude then descend; the descent is kept rather than truncated because a bird could in
    principle be over the home point, and MIN_DEPTH_M keeps the pass-through-bird-altitude moment
    from inventing a projection."""
    items = parse_qgc_wpl(mission_path)
    if not items:
        raise ValueError(f"{mission_path}: no mission items")
    home_e, home_n = latlon_to_enu(items[0].lat, items[0].lon, home_lat, home_lon)

    pts: List[Vec3] = [(home_e, home_n, 0.0)]
    for item in items[1:]:
        cur = pts[-1]
        if item.command == NAV_TAKEOFF:
            pts.append((cur[0], cur[1], item.alt))
        elif item.command == NAV_WAYPOINT:
            e, n = latlon_to_enu(item.lat, item.lon, home_lat, home_lon)
            pts.append((e, n, item.alt if item.alt > 0 else cur[2]))
        elif item.command == NAV_RTL:
            pts.append((home_e, home_n, cur[2]))   # return at altitude
            pts.append((home_e, home_n, 0.0))      # then land
        # any other command: not a position change we model -- skip rather than guess

    legs: List[Leg] = []
    t = 0.0
    for p0, p1 in zip(pts, pts[1:]):
        dist = math.dist(p0, p1)
        if dist < 1e-9:
            continue
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        yaw = math.atan2(dy, dx) if math.hypot(dx, dy) > 1e-6 else float("nan")
        legs.append(Leg(_leg_label(p0, p1), p0, p1, t, dist / speed_mps, yaw))
        t += dist / speed_mps
    if not legs:
        raise ValueError(f"{mission_path}: mission has no travelled distance")

    # A vertical leg has no heading of its own: the vehicle holds what it had (and on the very
    # first climb, it has already yawed to face the first waypoint -- which is what the demo take's
    # frame 0 shows, quat yaw=+90 deg = the first lane's northward heading).
    for i, leg in enumerate(legs):
        if not math.isnan(leg.yaw_rad):
            continue
        prior = next((legs[j].yaw_rad for j in range(i - 1, -1, -1) if not math.isnan(legs[j].yaw_rad)), None)
        following = next((legs[j].yaw_rad for j in range(i + 1, len(legs)) if not math.isnan(legs[j].yaw_rad)),
                         None)
        legs[i] = Leg(leg.label, leg.p0, leg.p1, leg.t0_s, leg.duration_s,
                      prior if prior is not None else (following if following is not None else 0.0))
    return legs


def yaw_to_quat(yaw_rad: float) -> Quat:
    return (0.0, 0.0, math.sin(yaw_rad / 2.0), math.cos(yaw_rad / 2.0))


@dataclass(frozen=True)
class Sample:
    t_s: float
    pos: Vec3
    quat: Quat
    leg_label: str


def sample_path(legs: Sequence[Leg], cadence_hz: float) -> List[Sample]:
    """The modelled flight sampled at the camera cadence: one Sample per frame opportunity."""
    total = legs[-1].t0_s + legs[-1].duration_s
    dt = 1.0 / cadence_hz
    n = int(math.floor(total / dt)) + 1
    out: List[Sample] = []
    li = 0
    for k in range(n):
        t = k * dt
        while li + 1 < len(legs) and t >= legs[li].t0_s + legs[li].duration_s:
            li += 1
        leg = legs[li]
        f = 0.0 if leg.duration_s <= 0 else min(1.0, (t - leg.t0_s) / leg.duration_s)
        pos = (leg.p0[0] + f * (leg.p1[0] - leg.p0[0]),
               leg.p0[1] + f * (leg.p1[1] - leg.p0[1]),
               leg.p0[2] + f * (leg.p1[2] - leg.p0[2]))
        out.append(Sample(t, pos, yaw_to_quat(leg.yaw_rad), leg.label))
    return out


def bird_start_time_s(samples: Sequence[Sample], gate_alt_m: float = BIRD_START_ALT_M) -> float:
    """Mission time at which the vehicle first passes the bird driver's altitude gate. Phase 0 of
    the sweep = 'the driver started exactly here'. If the mission never reaches the gate the birds
    never start under the pipeline's own rule, and 0.0 is returned so the sweep still describes
    a hand-started driver."""
    for s in samples:
        if s.pos[2] > gate_alt_m:
            return s.t_s
    return 0.0


# --------------------------------------------------------------------------------------------------
# Visibility geometry
# --------------------------------------------------------------------------------------------------
def frame_geometry(u: float, v: float, r_px: float, width_px: int,
                   height_px: int) -> Tuple[bool, float]:
    """(in_frame, px_outside_edge) for a projected bird.

    `in_frame` is exactly `spike_common.clip_box([u-r, v-r, u+r, v+r], w, h) is not None` -- the
    apparent-size box overlapping the image with positive area, i.e. the SAME definition
    `eval/label_from_sim.py` marks ground truth `visible` with (pinned by
    tests/fieldguard_planning/test_predict_bird_visibility.py, so the two can never drift).

    `px_outside_edge` is the Chebyshev distance from the bird CENTRE to the image rectangle: 0 once
    the centre is inside, and the number ADR-003 amendment 1 quotes ("~341 px outside the edge").
    Because it is measured to the centre, a value below r_px still counts as in-frame."""
    in_frame = (u - r_px < width_px) and (u + r_px > 0) and (v - r_px < height_px) and (v + r_px > 0)
    return in_frame, max(0.0, -u, u - width_px, -v, v - height_px)


@dataclass
class Sighting:
    """One frame's worth of geometry for one bird."""
    t_s: float
    leg_label: str
    in_frame: bool
    px_outside: Optional[float]   # None when the bird is behind / too close to the camera
    slant_range_m: float
    miss_m: Optional[float] = None  # px_outside converted to metres at THIS frame's depth


def look_at_bird(sample: Sample, bird_pos: Vec3, radius_m: float, intr: CameraIntrinsics,
                 mount_offset_body_m: Vec3 = MOUNT_OFFSET_BODY_M) -> Sighting:
    cam_pos = camera_world_position(sample.pos, sample.quat, mount_offset_body_m)
    slant = math.dist(bird_pos, cam_pos)
    proj = project_world_point(bird_pos, sample.pos, sample.quat, intr, mount_offset_body_m)
    if proj is None or proj[2] <= MIN_DEPTH_M:
        return Sighting(sample.t_s, sample.leg_label, False, None, slant)
    u, v, depth = proj
    in_frame, px_out = frame_geometry(u, v, intr.fx * radius_m / depth, intr.width_px, intr.height_px)
    # px -> metres AT BIRD ALTITUDE: the actionable form of the miss ("this bird would have to pass
    # 1.8 m nearer the lane, or fly low enough that the footprint grows by 1.8 m").
    return Sighting(sample.t_s, sample.leg_label, in_frame, px_out, slant, px_out * depth / intr.fx)


def windows_from(sightings: Sequence[Sighting]) -> List[dict]:
    """Contiguous in-frame runs -> the 'which lane, when' answer."""
    out: List[dict] = []
    run: List[Sighting] = []
    for s in list(sightings) + [Sighting(0.0, "", False, None, 0.0)]:
        if s.in_frame:
            run.append(s)
            continue
        if run:
            out.append({"t_start_s": round(run[0].t_s, 2), "t_end_s": round(run[-1].t_s, 2),
                        "n_frames": len(run), "leg": run[0].leg_label,
                        "min_slant_range_m": round(min(r.slant_range_m for r in run), 2)})
            run = []
    return out


# --------------------------------------------------------------------------------------------------
# The prediction
# --------------------------------------------------------------------------------------------------
def predict(mission_path: Path, birds_config: Path, intr: CameraIntrinsics, speed_mps: float,
            cadence_hz: float, phase_step_s: float, min_frames: int,
            home: Tuple[float, float]) -> dict:
    birds = json.loads(Path(birds_config).read_text())["birds"]
    if not birds:
        raise ValueError(f"{birds_config} defines no birds")
    legs = build_legs(mission_path, home[0], home[1], speed_mps)
    samples = sample_path(legs, cadence_hz)
    t_gate = bird_start_time_s(samples)

    # One sweep span covers every bird's own period (each divides into it), so per-bird phase
    # coverage is complete even though the birds' JOINT pattern does not repeat.
    span_s = max(b["waypoints"][-1]["t_s"] for b in birds)
    phases = [k * phase_step_s for k in range(max(1, int(math.ceil(span_s / phase_step_s))))]

    mission_alt_m = max(s.pos[2] for s in samples)
    bird_reports = []
    for bird in birds:
        wps = bird["waypoints"]
        loop = bird.get("loop", True)
        radius = bird["physical_radius_m"]
        counts: List[int] = []
        best: Tuple[int, float, List[dict]] = (-1, 0.0, [])
        closest: Optional[Sighting] = None
        min_slant = None
        for phase in phases:
            sightings = []
            for s in samples:
                bx, by, bz, _yaw = pose_at(s.t_s - t_gate + phase, wps, loop)
                sightings.append(look_at_bird(s, (bx, by, bz), radius, intr))
            n = sum(1 for x in sightings if x.in_frame)
            counts.append(n)
            for x in sightings:
                if x.px_outside is not None and (closest is None or x.px_outside < closest.px_outside):
                    closest = x
                if min_slant is None or x.slant_range_m < min_slant:
                    min_slant = x.slant_range_m
            if n > best[0]:
                best = (n, phase, windows_from(sightings))

        alt_m = statistics.median(w["z_m"] for w in wps)
        depth_m = mission_alt_m - alt_m
        bird_reports.append({
            "bird_id": bird["bird_id"],
            "altitude_m": round(alt_m, 2),
            "depth_at_survey_alt_m": round(depth_m, 2),
            # along-track is the 640-px axis, cross-track the 480-px axis (ADR-007 mount extrinsic)
            "footprint_at_bird_alt_m": [round(2 * depth_m * intr.cx / intr.fx, 2),
                                        round(2 * depth_m * intr.cy / intr.fy, 2)],
            "frames_in_view": {"min": min(counts), "median": int(statistics.median(counts)),
                               "max": max(counts)},
            # What the pipeline itself will hand you: driver started AT the 10 m gate, phase 0.
            "frames_at_nominal_phase": counts[0],
            "phases_with_any_view": sum(1 for c in counts if c > 0),
            "n_phases": len(counts),
            # "structural" = no driver-start offset can ever put this bird in frame; the miss is
            # geometry (lane pitch vs footprint at bird altitude) and only geometry can fix it.
            # "timing" = it does enter the frame at some phases, so it is a coincidence problem.
            "limited_by": "structural" if max(counts) == 0 else "timing",
            "closest_px_outside_edge": None if closest is None else round(closest.px_outside, 1),
            "closest_miss_m": None if closest is None else round(closest.miss_m, 2),
            "closest_slant_range_m": round(min_slant, 2),
            "best_phase_s": best[1],
            "best_phase_windows": best[2],
        })

    failing = [b["bird_id"] for b in bird_reports if b["frames_in_view"]["median"] < min_frames]
    return {
        "schema_version": "1.0",
        "tool": "scripts/predict_bird_visibility.py",
        "mission": str(mission_path),
        "birds_config": str(birds_config),
        "model": {
            "speed_mps": speed_mps,
            "cadence_hz": cadence_hz,
            "frames": len(samples),
            "mission_duration_s": round(samples[-1].t_s, 1),
            "survey_altitude_m": round(mission_alt_m, 1),
            "bird_start_gate_alt_m": BIRD_START_ALT_M,
            "bird_start_t_s": round(t_gate, 1),
            "phase_sweep": {"n": len(phases), "step_s": phase_step_s, "span_s": span_s},
            "min_depth_m": MIN_DEPTH_M,
            "legs": [{"label": lg.label, "t0_s": round(lg.t0_s, 1)} for lg in legs],
        },
        "camera": {"width_px": intr.width_px, "height_px": intr.height_px, "fx": intr.fx,
                   "fy": intr.fy,
                   "ground_footprint_m": [round(2 * mission_alt_m * intr.cx / intr.fx, 2),
                                          round(2 * mission_alt_m * intr.cy / intr.fy, 2)]},
        "birds": bird_reports,
        "verdict": {
            "pass": not failing,
            "statistic": "median frames in view over the phase sweep",
            "min_frames": min_frames,
            "failing_birds": failing,
        },
    }


# --------------------------------------------------------------------------------------------------
# Backtest: the same geometry against a clip that was actually flown
# --------------------------------------------------------------------------------------------------
def backtest(clip_dir: Path) -> dict:
    """Replay a recorded clip's own poses + annotated birds[] through the identical projection.

    This is the predictor's validation, not a feature: a clip carries what the flight MEASURED
    (`eval/label_from_sim.py`'s visible-box count), so reproducing it is the only evidence that a
    prediction of zero means anything. Requires a clip annotated by `eval/annotate_real_clip.py`
    (birds[] present); refuses loudly rather than reporting a confident zero off missing labels."""
    clip_dir = Path(clip_dir)
    meta = json.loads((clip_dir / "meta.json").read_text())
    intr = CameraIntrinsics.from_meta(meta["camera"])
    mount = tuple(meta.get("camera_extrinsic", {}).get("offset_from_drone_m", (0.0, 0.0, 0.0)))
    lines = [json.loads(l) for l in (clip_dir / "poses.jsonl").read_text().splitlines() if l.strip()]
    if not lines:
        raise ValueError(f"{clip_dir}/poses.jsonl has no frames")
    if not any(line.get("birds") for line in lines):
        raise ValueError(
            f"{clip_dir}/poses.jsonl carries no birds[] -- annotate it first "
            f"(eval/annotate_real_clip.py --clip {clip_dir} --sidecar <bird_drive_*.json>); "
            f"scoring an unannotated clip would report a zero that means 'no labels', not 'no birds'")

    per_bird: Dict[str, dict] = {}
    for line in lines:
        w, x, y, z = line["drone"]["quat_wxyz"]
        sample = Sample(line.get("t_s", 0.0), tuple(line["drone"]["pos_m"]), (x, y, z, w),
                        f"frame {line['frame_id']}")
        for b in line.get("birds", []):
            s = look_at_bird(sample, tuple(b["pos_m"]), b["physical_radius_m"], intr, mount)
            rec = per_bird.setdefault(b["bird_id"], {"bird_id": b["bird_id"], "frames_in_view": 0,
                                                     "closest_px_outside_edge": None,
                                                     "closest_px_frame": None,
                                                     "closest_slant_range_m": None,
                                                     "closest_slant_frame": None})
            rec["frames_in_view"] += int(s.in_frame)
            if s.px_outside is not None and (rec["closest_px_outside_edge"] is None
                                             or s.px_outside < rec["closest_px_outside_edge"]):
                rec["closest_px_outside_edge"] = round(s.px_outside, 1)
                rec["closest_px_frame"] = line["frame_id"]
            if rec["closest_slant_range_m"] is None or s.slant_range_m < rec["closest_slant_range_m"]:
                rec["closest_slant_range_m"] = round(s.slant_range_m, 3)
                rec["closest_slant_frame"] = line["frame_id"]

    birds = [per_bird[k] for k in sorted(per_bird)]
    closest = min(birds, key=lambda b: b["closest_slant_range_m"])
    nearest_px = min((b for b in birds if b["closest_px_outside_edge"] is not None),
                     key=lambda b: b["closest_px_outside_edge"], default=None)
    return {
        "schema_version": "1.0",
        "tool": "scripts/predict_bird_visibility.py --backtest",
        "clip": str(clip_dir),
        "frames": len(lines),
        "camera": {"width_px": intr.width_px, "height_px": intr.height_px, "fx": intr.fx},
        "birds": birds,
        "total_frames_in_view": sum(b["frames_in_view"] for b in birds),
        "closest_approach": {"bird_id": closest["bird_id"],
                             "slant_range_m": closest["closest_slant_range_m"],
                             "frame_id": closest["closest_slant_frame"]},
        "nearest_miss": None if nearest_px is None else {
            "bird_id": nearest_px["bird_id"],
            "px_outside_edge": nearest_px["closest_px_outside_edge"],
            "frame_id": nearest_px["closest_px_frame"]},
    }


# --------------------------------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------------------------------
def format_prediction(rep: dict) -> str:
    m, cam = rep["model"], rep["camera"]
    L = [
        "SwathKeeper pre-flight bird-visibility prediction",
        f"  mission  {rep['mission']}",
        f"  birds    {rep['birds_config']}  ({len(rep['birds'])} birds)",
        f"  model    {m['speed_mps']:.1f} m/s, {m['cadence_hz']:.1f} Hz -> {m['frames']} frame "
        f"opportunities over {m['mission_duration_s']:.0f} s at {m['survey_altitude_m']:.0f} m; "
        f"birds start at t={m['bird_start_t_s']:.0f} s (>{m['bird_start_gate_alt_m']:.0f} m gate)",
        f"  sweep    {m['phase_sweep']['n']} phases x {m['phase_sweep']['step_s']} s "
        f"(covers the {m['phase_sweep']['span_s']:.1f} s trajectory period)",
        f"  camera   {cam['width_px']}x{cam['height_px']} fx={cam['fx']:.0f} -> ground footprint "
        f"{cam['ground_footprint_m'][0]:.1f} x {cam['ground_footprint_m'][1]:.1f} m "
        f"(along-track x cross-track)",
        "",
        f"  {'bird':8} {'alt':>5} {'depth':>6} {'footprint@bird_alt':>19}  "
        f"{'frames in view':>17} {'at gate':>8} {'phases':>8}  limited by",
        f"  {'':8} {'m':>5} {'m':>6} {'along x cross (m)':>19}  {'min/med/max':>17} "
        f"{'phase 0':>8} {'seen':>8}",
    ]
    for b in rep["birds"]:
        f = b["frames_in_view"]
        fp = b["footprint_at_bird_alt_m"]
        L.append(f"  {b['bird_id']:8} {b['altitude_m']:5.1f} {b['depth_at_survey_alt_m']:6.1f} "
                 f"{fp[0]:8.1f} x {fp[1]:6.1f}  "
                 f"{f['min']:4d} /{f['median']:5d} /{f['max']:5d} "
                 f"{b['frames_at_nominal_phase']:8d} "
                 f"{str(b['phases_with_any_view']) + '/' + str(b['n_phases']):>8}  "
                 f"{b['limited_by'].upper()}")
    L.append("")
    for b in rep["birds"]:
        if b["closest_px_outside_edge"] is not None:
            L.append(f"  {b['bird_id']}: nearest it ever comes to the frame is "
                     f"{b['closest_px_outside_edge']:.0f} px = {b['closest_miss_m']:.2f} m outside the "
                     f"edge (closest slant {b['closest_slant_range_m']:.1f} m)"
                     if b["limited_by"] == "structural" else
                     f"  {b['bird_id']}: enters the frame at {b['phases_with_any_view']}/"
                     f"{b['n_phases']} driver-start offsets; best phase {b['best_phase_s']:.1f} s "
                     f"gives {b['frames_in_view']['max']} frame"
                     f"{'' if b['frames_in_view']['max'] == 1 else 's'}")
        for w in b["best_phase_windows"]:
            L.append(f"      window  t={w['t_start_s']:.1f}-{w['t_end_s']:.1f} s "
                     f"on {w['leg']}  {w['n_frames']} frame{'' if w['n_frames'] == 1 else 's'}, "
                     f"closest {w['min_slant_range_m']:.1f} m")
    v = rep["verdict"]
    if v["pass"]:
        L.append(f"  VERDICT: PASS -- every bird clears the {v['min_frames']}-frame floor "
                 f"({v['statistic']}).")
    else:
        L.append(f"  VERDICT: FAIL -- {len(v['failing_birds'])} of {len(rep['birds'])} birds below "
                 f"the {v['min_frames']}-frame floor ({v['statistic']}): "
                 f"{', '.join(v['failing_birds'])}.")
        structural = [b["bird_id"] for b in rep["birds"]
                      if b["limited_by"] == "structural" and b["bird_id"] in v["failing_birds"]]
        timing = [bid for bid in v["failing_birds"] if bid not in structural]
        if structural:
            L.append(f"           {', '.join(structural)}: STRUCTURAL -- never in frame at ANY "
                     f"driver-start offset. More frames cannot fix this; only mission or world "
                     f"geometry can. Read `closest_miss_m` before reaching for altitude: if the "
                     f"miss is CROSS-TRACK (a patrol line offset from every lane) lowering the bird "
                     f"buys only 0.46 m of half-footprint per metre of depth and costs the "
                     f"avoidance threat cylinder long before it closes -- move the line onto a lane "
                     f"instead (ADR-015).")
        if timing:
            L.append(f"           {', '.join(timing)}: TIMING -- does cross the frame, just rarely. "
                     f"Cadence, ground speed and bird speed all move this number; geometry does "
                     f"not have to change.")
    L.append("  NOTE: cadence is frame OPPORTUNITY, not recorded yield -- only ~12 % of the "
             "sensor's ticks currently reach a clip (ADR-013 am. 6a). The demo take's airborne "
             "frames arrived at 0.41 Hz, not 5 Hz.")
    return "\n".join(L)


def format_backtest(rep: dict) -> str:
    L = [f"Backtest: {rep['clip']}",
         f"  {rep['frames']} frames, {len(rep['birds'])} birds, "
         f"{rep['camera']['width_px']}x{rep['camera']['height_px']} fx={rep['camera']['fx']:.1f}",
         f"  {'bird':8} {'frames in view':>14} {'nearest miss (px)':>19} {'closest slant (m)':>19}"]
    for b in rep["birds"]:
        px = "n/a" if b["closest_px_outside_edge"] is None else f"{b['closest_px_outside_edge']:.1f}"
        L.append(f"  {b['bird_id']:8} {b['frames_in_view']:14d} "
                 f"{px:>13} @f{b['closest_px_frame']:<4} "
                 f"{b['closest_slant_range_m']:13.2f} @f{b['closest_slant_frame']:<4}")
    c, n = rep["closest_approach"], rep["nearest_miss"]
    L.append(f"  measured: {rep['total_frames_in_view']} bird-visible frames of {rep['frames']}; "
             f"closest approach {c['slant_range_m']:.2f} m slant ({c['bird_id']}, frame "
             f"{c['frame_id']})" + ("" if n is None else
             f"; nearest miss {n['px_outside_edge']:.0f} px outside the edge ({n['bird_id']}, "
             f"frame {n['frame_id']})"))
    return "\n".join(L)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mission", type=Path, default=DEFAULT_MISSION)
    ap.add_argument("--birds", type=Path, default=DEFAULT_BIRDS_CONFIG)
    ap.add_argument("--speed", type=float, default=DEFAULT_SPEED_MPS,
                    help=f"ground speed m/s (default {DEFAULT_SPEED_MPS})")
    ap.add_argument("--fps", type=float, default=DEFAULT_CADENCE_HZ,
                    help=f"effective frame cadence Hz (default {DEFAULT_CADENCE_HZ} = the sensor "
                         f"tick; recorded yield is ~12%% of it, ADR-013 am. 6a)")
    ap.add_argument("--phase-step", type=float, default=DEFAULT_PHASE_STEP_S,
                    help=f"bird-phase sweep resolution, s (default {DEFAULT_PHASE_STEP_S})")
    ap.add_argument("--min-frames", type=int, default=DEFAULT_MIN_FRAMES,
                    help=f"PASS floor: median frames in view per bird (default {DEFAULT_MIN_FRAMES})")
    ap.add_argument("--backtest", type=Path, default=None,
                    help="score a FLOWN clip's own poses.jsonl instead of predicting a mission")
    ap.add_argument("--json", type=Path, default=None, help="also write the full report as JSON")
    args = ap.parse_args(argv)

    if args.backtest is not None:
        try:
            rep = backtest(args.backtest)
        except ValueError as exc:
            # Most commonly "this clip was never annotated" -- an operator answer, not a bug, so it
            # gets a message and exit 2 rather than a traceback. Still nonzero: refusing to score is
            # never the same as scoring zero.
            print(f"[predict_bird_visibility] {exc}", file=sys.stderr)
            return 2
        print(format_backtest(rep))
    else:
        cfg = json.loads(DEFAULT_CAMERA_CONFIG.read_text())["camera"]
        intr = CameraIntrinsics.from_config(cfg["image_width_px"], cfg["image_height_px"],
                                            cfg["horizontal_fov_rad"])
        poly = json.loads(DEFAULT_FIELD_POLYGON.read_text())
        rep = predict(args.mission, args.birds, intr, args.speed, args.fps, args.phase_step,
                      args.min_frames, (poly["home_lat"], poly["home_lon"]))
        print(format_prediction(rep))

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rep, indent=1) + "\n")
        print(f"  json -> {args.json}")
    return 0 if rep.get("verdict", {}).get("pass", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
