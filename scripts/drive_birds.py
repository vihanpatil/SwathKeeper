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

Mechanism: one `gz service /world/<world>/set_pose` call per bird per tick (subprocess, gz CLI —
no gz-transport Python bindings needed in the container). At the default 5 Hz x 3 birds this is
~15 short-lived processes/sec, comfortably within budget, and matches the camera's 5 Hz
update_rate (config/ndvi_camera.json) — the render never sees a stale hop. Loop-restart matches
the old actor <loop>true</loop> semantics (time wraps modulo the last waypoint's t_s).

Timing uses WALL clock, matching the old actor behavior only if Gazebo runs at real-time factor
~1.0 (it does in every runbook; RTF is checked in Gate 3). Slower-than-realtime sim would need
--rate-scale or sim-clock subscription — deliberately NOT built (YAGNI until a runbook needs it).

Dependency: stdlib only.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BIRDS_CONFIG = REPO_ROOT / "config" / "birds" / "farm_world_birds.json"
DEFAULT_WORLD = "farmguard_field"

Pose = Tuple[float, float, float, float]  # (x_m, y_m, z_m, yaw_rad)


def pose_at(t_s: float, waypoints: Sequence[dict], loop: bool = True) -> Pose:
    """Piecewise-linear pose along `waypoints` at time `t_s` — the same interpolation the SDF
    <actor><script> performed. Before the first waypoint: hold the first. After the last:
    wrap (loop=True, modulo the last t_s) or hold the last. Yaw interpolates linearly in
    degrees then converts (the committed trajectories never cross the +/-180 seam; asserting
    that here would be over-engineering a data file this repo owns)."""
    if not waypoints:
        raise ValueError("empty waypoint list")
    t0, tN = waypoints[0]["t_s"], waypoints[-1]["t_s"]
    if loop and tN > 0:
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


def set_pose_request(name: str, pose: Pose) -> str:
    """gz.msgs.Pose text-proto for /world/<w>/set_pose. Yaw-only orientation -> quaternion
    (z = sin(yaw/2), w = cos(yaw/2))."""
    x, y, z, yaw = pose
    return (f'name: "{name}", position: {{x: {x:.4f}, y: {y:.4f}, z: {z:.4f}}}, '
            f'orientation: {{z: {math.sin(yaw / 2):.6f}, w: {math.cos(yaw / 2):.6f}}}')


def gz_set_pose(world: str, name: str, pose: Pose, timeout_ms: int = 500) -> bool:
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", type=Path, default=DEFAULT_BIRDS_CONFIG)
    ap.add_argument("--world", default=DEFAULT_WORLD)
    ap.add_argument("--rate", type=float, default=5.0, help="update rate Hz (default 5, = camera rate)")
    ap.add_argument("--once", type=float, metavar="T_S", default=None,
                    help="place every bird at trajectory time T_S and exit (deterministic Gate-2 shots)")
    args = ap.parse_args(argv)

    birds = json.loads(args.config.read_text())["birds"]
    print(f"[drive_birds] driving {len(birds)} birds in world '{args.world}' "
          f"({'once at t=%.2fs' % args.once if args.once is not None else '%.1f Hz, Ctrl-C to stop' % args.rate})")

    if args.once is not None:
        ok = all(gz_set_pose(args.world, b["bird_id"],
                             pose_at(args.once, b["waypoints"], b.get("loop", True)))
                 for b in birds)
        return 0 if ok else 1

    t_start = time.monotonic()
    period = 1.0 / args.rate
    failures = 0
    try:
        while True:
            tick_begin = time.monotonic()
            t = tick_begin - t_start
            for b in birds:
                if not gz_set_pose(args.world, b["bird_id"],
                                   pose_at(t, b["waypoints"], b.get("loop", True))):
                    failures += 1
                    if failures == 5:
                        print("[drive_birds] 5 failed calls — is Gazebo up and the world name "
                              f"'{args.world}' right?", file=sys.stderr)
            time.sleep(max(0.0, period - (time.monotonic() - tick_begin)))
    except KeyboardInterrupt:
        print(f"\n[drive_birds] stopped after {time.monotonic() - t_start:.1f}s "
              f"({failures} failed calls)")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
