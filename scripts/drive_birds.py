#!/usr/bin/env python3
"""Drive the bird MODELS along their scripted trajectories via Gazebo's set_pose service (ADR-012).

Birds used to be SDF <actor>s with a <script><trajectory>; that never rendered (skinless actor
link-visuals don't enter Harmonic's ogre2 scene — found live 2026-08-18), so
`scripts/gen_farm_world.py` now emits them as static <model>s and THIS script supplies the motion
the <script> used to promise: piecewise-linear interpolation through the exact same
`config/birds/farm_world_birds.json` waypoints (t_s, x_m, y_m, z_m, yaw_deg — the deterministic
committed path; no runtime randomness, so reproducibility is unchanged).

Run INSIDE the fieldguard-sim container, alongside the Gazebo shell, BEFORE any Gate-2 pixel
check or recorded flight that needs visible birds:

    python3 /workspace/fieldguard/scripts/drive_birds.py            # loop at 5 Hz until Ctrl-C
    python3 /workspace/fieldguard/scripts/drive_birds.py --once 12  # place birds at t=12s, exit
                                                                     # (deterministic Gate-2 shots)

Every continuous run drops a run sidecar (`eval/results/bird_drive_<UTCstamp>.json`) recording the
sim-time anchor t0, and an APPLIED-POSE LOG next to it (`bird_drive_<UTCstamp>_applied.jsonl`) —
one line per set_pose call, recording what was asked for, when, and whether it landed. The anchor
alone is NOT enough to label a clip, and that is measured, not feared: on the 2026-08-22 flagship
take the labels reconstructed from t0 sat a mean 198 px (up to 313 px, against a 21-47 px bird)
from where the render actually put the bird, because a pose reaches Gazebo one whole driver tick
plus an unrecorded service latency after the trajectory time it was computed for (am. 6). The applied
log turns that unrecorded latency into a measured bracket, so the annotator can replay what the
renderer was SHOWN instead of modelling what it was asked to show.

THAT LOG IS ALSO THE FLIGHT'S BIRD GROUND TRUTH. Nothing in the ROS 2 graph publishes bird poses,
so this file is the only record of where the birds actually were: `eval/annotate_real_clip.py`
labels clips from it, and `scripts/check_live_flight_log.py --truth <log>` measures closest
approach against it instead of against the detections the drone happened to log (a monocular
estimate cannot referee its own safety margin — and a MISS at closest approach would otherwise
score as no-evidence-of-a-breach). Both consumers replay the same two functions, so a wrong
reconstruction is wrong for the labels and the safety gate together, never quietly for one.

Mechanism: one `gz service /world/<world>/set_pose` call per bird per tick (subprocess, gz CLI —
no gz-transport Python bindings needed in the container). Loop-restart matches the old actor
<loop>true</loop> semantics (time wraps modulo the last waypoint's t_s).

--rate IS A SLEEP FLOOR, NOT AN ACHIEVED RATE, and on this stack the floor does not bind. Measured
on the 2026-08-22 flagship take: `--rate 2` achieved ~1.3 Hz, because one clock poll plus three
`gz service` round-trips (each with its own process spawn and discovery handshake) took ~0.75 s of
wall clock per tick on their own. The birds therefore HOP 2 m between updates rather than gliding,
the hop is one full camera frame wide, and the per-bird lag ordered by position in the loop
(0.12 / 0.38 / 0.42 s). The trajectory stays time-correct — each pose is computed from a fresh
/clock reading — but the earlier claim that this "matches the camera's 5 Hz update_rate, so the
render never sees a stale hop" was wrong and is retracted (ADR-003 amendment 6). The heartbeat now
prints the ACHIEVED rate, and the applied-pose log records the hop instead of hiding it.

Timing uses Gazebo SIM time (polled from the /clock topic each tick) so bird motion stays
trajectory-correct at ANY real-time factor — load-bearing on this stack: software rendering in
Docker-on-Apple-Silicon runs the sim well below realtime (measured RTF << 1 in the 2026-08-18
session), and a wall-clock driver would fly the birds 1/RTF too fast relative to the drone and
camera. --wall-clock restores the old behavior for the rare RTF≈1 case where /clock is
unavailable.

Dependency: stdlib only.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BIRDS_CONFIG = REPO_ROOT / "config" / "birds" / "farm_world_birds.json"
DEFAULT_WORLD = "farmguard_field"
DEFAULT_SIDECAR_DIR = REPO_ROOT / "eval" / "results"  # gitignored, same home as the flight logs

SIDECAR_SCHEMA_VERSION = "1.1"      # 1.1 adds applied_log (ADR-003 am. 6)
# 1.1 adds clock_wall_s: the wall instant the tick's /clock reading was PARSED. Without it the log
# claims tick_sim_s was observed at tick_wall_s, which is false by one `gz topic -e -n 1`
# subprocess -- measured 39 ms median / 146 ms max on the 2026-08-23 take, i.e. up to ~0.8 m of
# bird motion asserted with false precision. Absent (1.0 logs) the bracket math is unchanged.
APPLIED_LOG_SCHEMA_VERSION = "1.1"

Pose = Tuple[float, float, float, float]  # (x_m, y_m, z_m, yaw_rad)


def pose_at(t_s: float, waypoints: Sequence[dict], loop: bool = True) -> Pose:
    """Piecewise-linear pose along `waypoints` at time `t_s` — the same interpolation the SDF
    <actor><script> performed. Before the first waypoint: hold the first — and that is not a
    convention, it is where the bird physically IS: `gen_farm_world.sdf_bird_model` spawns each
    one as a <static> model at waypoints[0] and nothing moves it until this driver's first
    set_pose (ADR-012 amendment 1), so the wrap below is forward-only. After the last: wrap
    (loop=True, modulo the last t_s) or hold the last. Yaw interpolates linearly in degrees then
    converts (the committed trajectories never cross the +/-180 seam; asserting that here would
    be over-engineering a data file this repo owns)."""
    if not waypoints:
        raise ValueError("empty waypoint list")
    t0, tN = waypoints[0]["t_s"], waypoints[-1]["t_s"]
    if loop and tN > 0 and t_s > t0:  # forward-only: -15 % 20 == 5 would teleport a pre-spawn bird
        t_s = t_s % tN
    if t_s <= t0:
        wp = waypoints[0]
        return (wp["x_m"], wp["y_m"], wp["z_m"], math.radians(wp["yaw_deg"]))
    if t_s >= tN:
        wp = waypoints[-1]
        return (wp["x_m"], wp["y_m"], wp["z_m"], math.radians(wp["yaw_deg"]))
    for a, b in zip(waypoints, waypoints[1:]):
        if a["t_s"] <= t_s <= b["t_s"]:
            span = b["t_s"] - a["t_s"]
            f = 0.0 if span <= 0 else (t_s - a["t_s"]) / span
            return (
                a["x_m"] + f * (b["x_m"] - a["x_m"]),
                a["y_m"] + f * (b["y_m"] - a["y_m"]),
                a["z_m"] + f * (b["z_m"] - a["z_m"]),
                math.radians(a["yaw_deg"] + f * (b["yaw_deg"] - a["yaw_deg"])),
            )
    raise AssertionError(f"unreachable: t_s={t_s} not bracketed by waypoints")  # pragma: no cover


def write_run_sidecar(sidecar_dir: Path, t0_sim_s: Optional[float], rate_hz: float,
                      config_path: Path, bird_ids: Sequence[str], world: str) -> Path:
    """Record this run's timing anchor to `<sidecar_dir>/bird_drive_<UTCstamp>.json` and return
    the path.

    A clip recorded while this driver runs has no bird ground truth of its own (nothing in the ROS 2
    graph publishes bird poses), but it is fully recoverable: bird position at a frame =
    `pose_at(frame.stamp_sim_s - t0_sim)`. Without this file that anchor exists ONLY in the console
    scrollback of whichever terminal started the driver -- one closed tab and the clip is unlabelable.
    Written once at startup and flushed immediately, so a Ctrl-C'd or crashed run still leaves it.
    Consumed by `eval/annotate_real_clip.py --sidecar`."""
    sidecar_dir = Path(sidecar_dir)
    sidecar_dir.mkdir(parents=True, exist_ok=True)
    path = sidecar_dir / f"bird_drive_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    payload = {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "driver": "scripts/drive_birds.py",
        "written_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "world": world,
        # "sim" = RTF-proof gz /clock timing; "wall" = wall clock, which leaves NO sim anchor
        # (t0_sim_s null) and therefore no way to label a clip afterwards.
        "clock": "wall" if t0_sim_s is None else "sim",
        "t0_sim_s": t0_sim_s,
        "rate_hz": rate_hz,
        # Recorded as passed: the driver runs at /workspace/fieldguard inside the container while
        # the annotator usually runs from the host checkout, so this path may not resolve there --
        # it is provenance, not a lookup key (the annotator defaults to its own repo's config and
        # cross-checks bird_ids).
        "config": str(config_path),
        "config_name": Path(config_path).name,
        "bird_ids": list(bird_ids),
        # The log is the LABELLING source; t0_sim_s above is only the fallback (and a fallback that
        # is measurably wrong by up to half a metre per 0.1 s of unrecorded latency -- ADR-003 am. 6).
        "applied_log": applied_log_path_for(path).name,
        "applied_log_schema_version": APPLIED_LOG_SCHEMA_VERSION,
        "note": ("label a clip with: python3 eval/annotate_real_clip.py --clip <dir> --sidecar "
                 "<this file> -- which replays applied_log (what the renderer was SHOWN). Without "
                 "that log the annotator can only model pose_at(frame.stamp_sim_s - t0_sim_s), "
                 "which is what the driver ASKED for and lands ~0.4-0.8 s ahead of the render. "
                 "The same applied_log is this flight's bird GROUND TRUTH: "
                 "scripts/check_live_flight_log.py --truth <applied_log> measures closest approach "
                 "against it rather than against the drone's own detections."),
    }
    with path.open("w") as fh:
        json.dump(payload, fh, indent=1)
        fh.write("\n")
        fh.flush()
    return path


def applied_log_path_for(sidecar_path: Path) -> Path:
    """`bird_drive_<stamp>.json` -> `bird_drive_<stamp>_applied.jsonl` (the sidecar names it too, so
    a consumer never has to guess the convention; this function is where the convention lives)."""
    sidecar_path = Path(sidecar_path)
    return sidecar_path.with_name(sidecar_path.stem + "_applied.jsonl")


def applied_record(bird_id: str, t_traj_s: float, pose: Pose, ok: bool,
                   tick_sim_s: Optional[float], tick_wall_s: float,
                   wall_start_s: float, wall_end_s: float,
                   clock_wall_s: Optional[float] = None) -> dict:
    """One set_pose call as EVIDENCE, not as a plan.

    `t_traj_s` is what was asked for; the timestamps are when. Times are recorded raw and in two
    clocks on purpose: `tick_sim_s` is the gz-clock reading this tick's poses were computed from,
    `tick_wall_s`/`clock_wall_s`/`wall_start_s`/`wall_end_s` are `time.monotonic()`. Sim time is
    what a clip's frames are stamped in, but polling it per call would cost another subprocess per
    bird and make the very latency being measured worse -- so the wall times are converted to sim
    OFFLINE by `applied_sim_brackets`, using the RTF measured between consecutive tick anchors.
    Nothing here is interpolated at write time: a crashed run leaves usable evidence.

    `clock_wall_s` (schema 1.1) is when that /clock reading was PARSED, and it exists because the
    reading is not instantaneous: `gz topic -e -t /clock -n 1` is a subprocess that took 39 ms
    median / 146 ms max on the 2026-08-23 take. So `tick_sim_s` was true at some unknown instant in
    [`tick_wall_s`, `clock_wall_s`] -- an interval this driver now MEASURES instead of collapsing to
    its start. Omitted for wall-clock runs (no reading at all) and absent from 1.0 logs, where
    `applied_sim_brackets` falls back to the old zero-width assumption unchanged.

    `ok=False` is as load-bearing as `ok=True`. A failed call means the bird HELD its previous pose,
    and only this record can tell a label that from a pose that landed."""
    x, y, z, yaw = pose
    rec = {
        "bird_id": bird_id,
        "t_traj_s": round(t_traj_s, 6),
        "pos_m": [round(x, 6), round(y, 6), round(z, 6)],
        "yaw_rad": round(yaw, 6),
        "ok": bool(ok),
        "tick_sim_s": None if tick_sim_s is None else round(tick_sim_s, 6),
        "tick_wall_s": round(tick_wall_s, 6),
        "wall_start_s": round(wall_start_s, 6),
        "wall_end_s": round(wall_end_s, 6),
    }
    if clock_wall_s is not None:
        rec["clock_wall_s"] = round(clock_wall_s, 6)
    return rec


def applied_sim_brackets(records: Sequence[dict]) -> List[Optional[Tuple[float, float]]]:
    """Per record, the SIM-time bracket `(start, end)` the pose landed inside — or None if that
    record cannot be placed on the sim clock (a wall-clock run has no anchor at all).

    The bracket, not an instant, is the honest answer: Gazebo applies the pose somewhere between the
    request going out and the reply coming back, and this repo does not record commanded values as
    if they were observed. A frame stamped inside a bracket is genuinely ambiguous and downstream
    says so rather than picking a side.

    Wall->sim uses the RTF MEASURED between this tick's anchor and the next one
    (`(sim[k+1]-sim[k]) / (wall[k+1]-wall[k])`), because RTF is not a constant on this stack: over
    the flagship take it ranged 0.94 (pre-flight) to 0.51 (mid-lane). The last tick reuses the
    previous tick's measured RTF -- the only extrapolation here, and it spans one tick.

    The tick's own anchor is an interval too, for the same reason (schema 1.1): `tick_sim_s` was
    read by a subprocess spanning [`tick_wall_s`, `clock_wall_s`], so the bracket is widened to
    whichever end of that interval makes it WIDER -- latest possible anchor for the start, earliest
    for the end. Uncertainty is not allowed to shrink the ambiguous window, because downstream
    resolves ambiguity conservatively and a falsely-narrow bracket would hand a safety gate a
    precision the driver never had. Schema 1.0 records (no `clock_wall_s`) keep the old zero-width
    anchor exactly, so every label and verdict derived from a committed log stays reproducible."""
    ticks: List[Tuple[float, Optional[float], float]] = []
    for r in records:
        key = (r["tick_wall_s"], r.get("tick_sim_s"), r.get("clock_wall_s", r["tick_wall_s"]))
        if not ticks or ticks[-1] != key:
            ticks.append(key)
    rtf_by_tick_wall = {}
    prev_rtf = None
    for i, (w, s, cw) in enumerate(ticks):
        rtf = None
        if s is not None and i + 1 < len(ticks):
            _w2, s2, cw2 = ticks[i + 1]
            # Anchored on the two READINGS' own instants, so the poll cost cancels instead of
            # biasing the rate (identical to the old tick_wall pairing on 1.0 logs, where cw == w).
            if s2 is not None and cw2 > cw:
                rtf = (s2 - s) / (cw2 - cw)
        if rtf is None:
            rtf = prev_rtf  # last tick (or an unusable neighbour): reuse the last measured RTF
        rtf_by_tick_wall[w] = rtf
        if rtf is not None:
            prev_rtf = rtf
    # A run with a single usable tick has no measured RTF anywhere; fall back to the tick anchor
    # itself (bracket collapses to the poll instant) rather than inventing a rate.
    out: List[Optional[Tuple[float, float]]] = []
    for r in records:
        s0 = r.get("tick_sim_s")
        if s0 is None:
            out.append(None)
            continue
        rtf = rtf_by_tick_wall.get(r["tick_wall_s"])
        if rtf is None:
            out.append((s0, s0))
            continue
        out.append((s0 + (r["wall_start_s"] - r.get("clock_wall_s", r["tick_wall_s"])) * rtf,
                    s0 + (r["wall_end_s"] - r["tick_wall_s"]) * rtf))
    return out


def applied_sim_span(records: Sequence[dict]) -> Optional[Tuple[float, float]]:
    """The sim-time window this truth track actually covers — (earliest landed bracket start,
    latest landed bracket end) — or None if nothing in it can be placed on the sim clock (a
    wall-clock run, or a log whose every call failed).

    Landed calls only, so it describes exactly the records `annotate_real_clip.applied_timeline`
    will answer from: a consumer that SELECTS a truth track by span and then QUERIES it by pose
    must be asking about the same set of records, or it picks a log it cannot answer from.

    This is the association key for a flight: `scripts/check_live_flight_log.py --truth` matches a
    log's `tick_stamp_sim_s` span against this. Necessary but NOT sufficient on its own — Gazebo
    sim time restarts near 0 every run, so two takes overlap trivially and the operator, not the
    overlap, resolves which log belongs to which flight."""
    brackets = [b for r, b in zip(records, applied_sim_brackets(records)) if r.get("ok") and b]
    if not brackets:
        return None
    return (min(b[0] for b in brackets), max(b[1] for b in brackets))


def read_applied_log(path: Path) -> List[dict]:
    """Parse an applied-pose log, skipping trailing garbage from a killed run (the last line of a
    JSONL file written live can be half-flushed; losing it must not cost the other 3,000)."""
    records = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"[drive_birds] WARNING: {path} has a truncated final line — ignoring it",
                  file=sys.stderr)
            break
    return records


class AppliedLogWriter:
    """Append-only writer for the applied-pose log. Never fatal: a read-only mount or a full disk
    must not stop a flight that is otherwise fine, so the first write error disables logging with a
    warning and the driver keeps flying the birds."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh = None
        self._disabled = False
        self.written = 0

    def write(self, record: dict) -> None:
        if self._disabled:
            return
        try:
            if self._fh is None:
                self._fh = self.path.open("a")
            self._fh.write(json.dumps(record) + "\n")
            self._fh.flush()   # per-call flush: a Ctrl-C'd run keeps every pose it applied
            self.written += 1
        except OSError as exc:
            self._disabled = True
            print(f"[drive_birds] WARNING: applied-pose log disabled ({exc}) — a clip recorded now "
                  f"can only be labelled by MODEL, not by measurement", file=sys.stderr)

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:
                pass
            self._fh = None


def parse_sim_time_s(clock_text: str) -> Optional[float]:
    """Extract sim seconds from gz.msgs.Clock text output: the `sim { sec: N nsec: M }` block.
    Returns None if no sim block is present (e.g. truncated read) — caller decides the fallback."""
    m = re.search(r"sim\s*\{([^}]*)\}", clock_text)
    if not m:
        return None
    body = m.group(1)
    sec = re.search(r"sec:\s*(\d+)", body)
    nsec = re.search(r"nsec:\s*(\d+)", body)
    if not sec:
        return None
    return int(sec.group(1)) + (int(nsec.group(1)) / 1e9 if nsec else 0.0)


def gz_sim_now_s(timeout_s: float = 3.0) -> Optional[float]:
    """Latest sim time via one `gz topic -e -t /clock -n 1` call (publishes fast; returns quickly).
    None on any failure — the driver loop treats that as 'hold this tick', never crashes."""
    try:
        out = subprocess.run(["gz", "topic", "-e", "-t", "/clock", "-n", "1"],
                             capture_output=True, text=True, timeout=timeout_s)
        return parse_sim_time_s(out.stdout) if out.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def set_pose_request(name: str, pose: Pose) -> str:
    """gz.msgs.Pose text-proto for /world/<w>/set_pose. Yaw-only orientation -> quaternion
    (z = sin(yaw/2), w = cos(yaw/2))."""
    x, y, z, yaw = pose
    return (f'name: "{name}", position: {{x: {x:.4f}, y: {y:.4f}, z: {z:.4f}}}, '
            f'orientation: {{z: {math.sin(yaw / 2):.6f}, w: {math.cos(yaw / 2):.6f}}}')


def gz_set_pose(world: str, name: str, pose: Pose, timeout_ms: int = 2000) -> bool:
    # 2000ms, not 500: with SITL + MAVProxy + software rendering sharing the CPU, service
    # round-trips beyond 500ms are routine (learned live 2026-08-18 — the first in-mission run
    # failed every call while the idle-world test had passed).
    """One set_pose service call via the gz CLI. Returns True on success; a failed call is
    reported but never raises — one dropped tick must not kill the driver mid-flight."""
    cmd = ["gz", "service", "-s", f"/world/{world}/set_pose",
           "--reqtype", "gz.msgs.Pose", "--reptype", "gz.msgs.Boolean",
           "--timeout", str(timeout_ms), "--req", set_pose_request(name, pose)]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_ms / 1000 + 2)
        return out.returncode == 0 and "true" in out.stdout
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"[drive_birds] set_pose {name} failed: {exc}", file=sys.stderr)
        return False


def drive_tick(birds: Sequence[dict], t_traj_s: float, set_pose, log: Optional[AppliedLogWriter],
               *, tick_sim_s: Optional[float], tick_wall_s: float,
               clock_wall_s: Optional[float], now=None) -> Tuple[int, int]:
    """Apply every bird's pose for ONE tick and record what happened. Returns (n_ok, n_failed).

    `set_pose(bird_id, pose) -> bool` is injected rather than called directly, which is the whole
    reason this is a function: the loop that WRITES the ground truth a safety gate is scored
    against is then testable without Gazebo, with a fake clock and a fake service, and the
    per-call timestamps become exactly checkable instead of merely plausible.

    Each bird is timed individually because the birds do not land together: on the flagship take
    the three lagged 0.12 / 0.38 / 0.42 s by their position in this loop. One record per call, in
    call order, whether or not it landed."""
    now = now or time.monotonic   # resolved here, not at import: one clock for the whole tick
    n_ok = 0
    n_failed = 0
    for b in birds:
        pose = pose_at(t_traj_s, b["waypoints"], b.get("loop", True))
        call_start = now()
        ok = set_pose(b["bird_id"], pose)
        call_end = now()
        if log is not None:
            log.write(applied_record(b["bird_id"], t_traj_s, pose, ok, tick_sim_s, tick_wall_s,
                                     call_start, call_end, clock_wall_s))
        if ok:
            n_ok += 1
        else:
            n_failed += 1
    return n_ok, n_failed


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, default=DEFAULT_BIRDS_CONFIG)
    ap.add_argument("--world", default=DEFAULT_WORLD)
    ap.add_argument("--rate", type=float, default=5.0, help="update rate Hz (default 5, = camera rate)")
    ap.add_argument("--once", type=float, metavar="T_S", default=None,
                    help="place every bird at trajectory time T_S and exit (deterministic Gate-2 shots)")
    ap.add_argument("--wall-clock", action="store_true",
                    help="time trajectories on wall clock instead of Gazebo /clock sim time "
                         "(only correct at RTF~1; sim time is the default because software "
                         "rendering runs this stack well below realtime)")
    ap.add_argument("--sidecar-dir", type=Path, default=DEFAULT_SIDECAR_DIR,
                    help="where to write the run sidecar recording t0_sim (default eval/results/) "
                         "— it is what lets eval/annotate_real_clip.py label a clip recorded "
                         "during this run")
    ap.add_argument("--no-sidecar", action="store_true",
                    help="skip the run sidecar (any clip recorded during this run then depends on "
                         "console scrollback for its bird ground truth)")
    args = ap.parse_args(argv)

    birds = json.loads(args.config.read_text())["birds"]
    print(f"[drive_birds] driving {len(birds)} birds in world '{args.world}' "
          f"({'once at t=%.2fs' % args.once if args.once is not None else '%.1f Hz, Ctrl-C to stop' % args.rate})")

    if args.once is not None:
        ok = all(gz_set_pose(args.world, b["bird_id"],
                             pose_at(args.once, b["waypoints"], b.get("loop", True)))
                 for b in birds)
        return 0 if ok else 1

    t0_sim: Optional[float] = None
    if not args.wall_clock:
        t0_sim = gz_sim_now_s()
        if t0_sim is None:
            print("[drive_birds] WARNING: no /clock reading — falling back to wall clock "
                  "(trajectory timing only correct at RTF~1)", file=sys.stderr)
        else:
            print(f"[drive_birds] sim-time mode, t0={t0_sim:.2f}s (RTF-proof)")

    applied_log = None
    if not args.no_sidecar:
        # Never fatal: a read-only mount must not stop a flight that is otherwise fine.
        try:
            sidecar = write_run_sidecar(args.sidecar_dir, t0_sim, args.rate, args.config,
                                        [b["bird_id"] for b in birds], args.world)
            applied_log = AppliedLogWriter(applied_log_path_for(sidecar))
            print(f"[drive_birds] run sidecar -> {sidecar}  "
                  f"(label a clip: eval/annotate_real_clip.py --sidecar <that file>)")
            print(f"[drive_birds] applied-pose log -> {applied_log.path}  "
                  f"(what the render was SHOWN; the labels come from here)")
        except OSError as exc:
            print(f"[drive_birds] WARNING: could not write run sidecar ({exc}) — note t0 by hand "
                  f"or a clip recorded now cannot be labelled later", file=sys.stderr)

    def set_pose(name: str, pose: Pose) -> bool:
        return gz_set_pose(args.world, name, pose)

    t_start = time.monotonic()
    period = 1.0 / args.rate
    failures = 0
    successes = 0
    ticks = 0
    next_failure_report = 1
    last_report = t_start
    try:
        while True:
            tick_begin = time.monotonic()
            if t0_sim is not None:
                # tick_sim is the /clock reading THESE poses were computed from; the poses land
                # later, by the service round-trip recorded per call. The reading itself is not
                # instantaneous, so [tick_begin, clock_wall] brackets when it was true.
                tick_sim = gz_sim_now_s()
                clock_wall = time.monotonic()
                if tick_sim is None:
                    time.sleep(period)  # hold this tick; transient /clock hiccup must not kill the run
                    continue
                t = tick_sim - t0_sim
            else:
                tick_sim, clock_wall = None, None   # wall-clock run: no reading, no sim anchor
                t = tick_begin - t_start
            n_ok, n_failed = drive_tick(birds, t, set_pose, applied_log, tick_sim_s=tick_sim,
                                        tick_wall_s=tick_begin, clock_wall_s=clock_wall)
            successes += n_ok
            failures += n_failed
            if failures >= next_failure_report:
                # First failure, then geometric backoff: an all-failing driver says so within one
                # tick, and a merely loaded one does not fill the console with the same line.
                next_failure_report = max(5, failures * 5)
                print(f"[drive_birds] {failures} failed set_pose calls so far "
                      f"({successes} ok) — heavy load slows service round-trips; the birds "
                      f"still track sim time, just at fewer updates", file=sys.stderr)
            ticks += 1
            # Heartbeat every 30s wall so 'working' is visibly different from 'silently failing'.
            # ACHIEVED cadence, not the requested one: --rate is a sleep floor, and on the flagship
            # take the gz-CLI round-trips overran it so far that --rate 2 ran at ~1.3 Hz (measured,
            # ADR-003 am. 6). A rate knob that silently does not apply is exactly what a heartbeat
            # is for.
            if time.monotonic() - last_report >= 30.0:
                last_report = time.monotonic()
                achieved = ticks / max(1e-9, time.monotonic() - t_start)
                print(f"[drive_birds] t_sim={t:7.1f}s  poses ok={successes}  failed={failures}  "
                      f"achieved {achieved:.2f} Hz of the {args.rate:.2f} Hz requested")
            time.sleep(max(0.0, period - (time.monotonic() - tick_begin)))
    except KeyboardInterrupt:
        elapsed = time.monotonic() - t_start
        print(f"\n[drive_birds] stopped after {elapsed:.1f}s ({successes} ok, {failures} failed "
              f"calls, {ticks / max(1e-9, elapsed):.2f} Hz achieved of {args.rate:.2f} Hz requested)")
        if applied_log is not None:
            applied_log.close()
            print(f"[drive_birds] applied-pose log: {applied_log.written} records -> "
                  f"{applied_log.path}")
            # The window this take's bird ground truth covers, printed where the operator needs it:
            # the post-flight gate has to be handed the log that overlaps the FLIGHT's sim stamps,
            # and sim time restarts near 0 every run, so two takes' filenames look alike.
            try:
                span = applied_sim_span(read_applied_log(applied_log.path))
            except OSError:
                span = None
            if span is not None:
                print(f"[drive_birds] bird ground truth covers sim {span[0]:.1f}..{span[1]:.1f}s — "
                      f"pass it to: python3 scripts/check_live_flight_log.py <flight log> "
                      f"--truth {applied_log.path}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
