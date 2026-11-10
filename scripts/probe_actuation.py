#!/usr/bin/env python3
"""Measure whether — and how fast — the vehicle flies a commanded avoidance setpoint.

Runs INSIDE the sim container against a vehicle that is already airborne (any mode). It uses the
SAME command path the avoidance executor flies — `ros2_adapter.Ros2VehicleSink.send_setpoint_enu`
→ `/ap/cmd_gps_pose` — after switching to GUIDED through `/ap/mode_switch`, re-commanding the
setpoint at the executor's 5 Hz for a fixed hold, and recording `/ap/pose/filtered` the whole time.
The output is the number every live flight so far has lacked: commanded vs ACHIEVED displacement
as a function of time, plus the ModeSwitch response ArduPilot actually returned.

    PYTHONPATH=src python3 scripts/probe_actuation.py --east 10 --hold-s 12

Writes eval/results/actuation_probe_<UTC>.json and prints a table. Leaves the vehicle in GUIDED,
hovering wherever it got to; hand it back from MAVProxy (`mode rtl` / `mode land`).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.ros2_adapter import AP_COPTER_MODE, Ros2VehicleSink  # noqa: E402

SAMPLE_TIMES_S = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0)


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v) if n > 0 else (0.0, 0.0, 0.0)


def summarize(series, p0, target, t_cmd_wall):
    """series: list of (t_wall, (x,y,z)). Everything is measured from the FIRST setpoint publish."""
    cmd = tuple(t - p for t, p in zip(target, p0))
    u = _unit(cmd)
    cmd_len = math.sqrt(sum(c * c for c in cmd))
    rows = []
    for t_s in SAMPLE_TIMES_S:
        # the last pose at or before t_cmd_wall + t_s
        cand = [s for s in series if s[0] <= t_cmd_wall + t_s]
        if not cand:
            continue
        t, p = cand[-1]
        d = tuple(pi - p0i for pi, p0i in zip(p, p0))
        along = sum(di * ui for di, ui in zip(d, u))
        cross = math.sqrt(max(0.0, sum(di * di for di in d) - along * along))
        rows.append({"t_s": t_s, "along_m": round(along, 3), "cross_m": round(cross, 3),
                     "dz_m": round(d[2], 3), "dist_to_target_m":
                     round(math.sqrt(sum((ti - pi) ** 2 for ti, pi in zip(target, p))), 3)})
    # first motion: along-command displacement first exceeds 0.30 m
    t_first = None
    for t, p in series:
        if t < t_cmd_wall:
            continue
        along = sum((pi - p0i) * ui for pi, p0i, ui in zip(p, p0, u))
        if along > 0.30:
            t_first = round(t - t_cmd_wall, 3)
            break
    # time to within 1 m / 3 m of target
    def t_within(r):
        for t, p in series:
            if t < t_cmd_wall:
                continue
            if math.sqrt(sum((ti - pi) ** 2 for ti, pi in zip(target, p))) <= r:
                return round(t - t_cmd_wall, 3)
        return None
    # peak speed along the command (finite difference over >= 0.4 s windows)
    vmax = 0.0
    post = [(t, p) for t, p in series if t >= t_cmd_wall]
    for i in range(len(post)):
        for j in range(i + 1, len(post)):
            dt = post[j][0] - post[i][0]
            if dt < 0.4:
                continue
            a1 = sum((pi - p0i) * ui for pi, p0i, ui in zip(post[j][1], p0, u))
            a0 = sum((pi - p0i) * ui for pi, p0i, ui in zip(post[i][1], p0, u))
            vmax = max(vmax, (a1 - a0) / dt)
            break
    return {"command_vector_enu_m": [round(c, 3) for c in cmd], "command_length_m": round(cmd_len, 3),
            "samples": rows, "t_first_motion_s": t_first, "t_within_3m_s": t_within(3.0),
            "t_within_1m_s": t_within(1.0), "peak_along_speed_mps": round(vmax, 3),
            "poses_recorded": len(series)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--east", type=float, default=10.0)
    ap.add_argument("--north", type=float, default=0.0)
    ap.add_argument("--up", type=float, default=0.0)
    ap.add_argument("--hold-s", type=float, default=12.0, help="how long to keep re-commanding")
    ap.add_argument("--rate-hz", type=float, default=5.0, help="re-command rate (executor: 5 Hz)")
    ap.add_argument("--no-mode-switch", action="store_true",
                    help="skip the GUIDED request (vehicle already in GUIDED)")
    ap.add_argument("--no-bounce", action="store_true",
                    help="do not bounce through LOITER before GUIDED (see the comment in main)")
    ap.add_argument("--settle-s", type=float, default=2.0,
                    help="wait after the mode switch before the first setpoint")
    ap.add_argument("--out-dir", type=Path, default=REPO_ROOT / "eval" / "results")
    args = ap.parse_args(argv)

    import rclpy
    from geometry_msgs.msg import PoseStamped
    from rclpy.qos import qos_profile_sensor_data
    from ardupilot_msgs.srv import ModeSwitch

    rclpy.init()
    node = rclpy.create_node("fg_actuation_probe")
    series = []
    stamps = []  # (wall, header stamp) pairs: the stamp is SITL time, i.e. sim time
    latest = {"p": None}

    def on_pose(msg):
        p = msg.pose.position
        latest["p"] = (p.x, p.y, p.z)
        st = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
        series.append((time.time(), (p.x, p.y, p.z)))
        stamps.append((time.time(), st))

    node.create_subscription(PoseStamped, "/ap/pose/filtered", on_pose, qos_profile_sensor_data)

    # optional mode/armed readback if this AP_DDS build publishes /ap/status
    status = {"seen": False, "last": None}
    try:
        from ardupilot_msgs.msg import Status

        def on_status(msg):
            status["seen"] = True
            status["last"] = {"armed": bool(msg.armed), "flying": bool(msg.flying),
                              "mode": int(msg.mode), "external_control": bool(msg.external_control)}
        node.create_subscription(Status, "/ap/status", on_status, qos_profile_sensor_data)
    except Exception as exc:  # noqa: BLE001
        status["last"] = f"no ardupilot_msgs/Status in this build: {exc}"

    print("[probe] waiting for /ap/pose/filtered ...", flush=True)
    t_end = time.time() + 20.0
    while rclpy.ok() and latest["p"] is None and time.time() < t_end:
        rclpy.spin_once(node, timeout_sec=0.1)
    if latest["p"] is None:
        print("[probe] no pose in 20 s — is SITL + the micro-ROS agent up?", file=sys.stderr)
        return 2
    p0 = latest["p"]
    print(f"[probe] pose live: ENU({p0[0]:.2f}, {p0[1]:.2f}, {p0[2]:.2f})  status={status['last']}", flush=True)

    sink = Ros2VehicleSink(node)
    mode_resp = None
    t_mode_req = None
    if not args.no_mode_switch:
        cli = node.create_client(ModeSwitch, "/ap/mode_switch")
        if not cli.wait_for_service(timeout_sec=10.0):
            print("[probe] /ap/mode_switch service not available", file=sys.stderr)
            return 3
        # BOUNCE through LOITER first. ArduCopter's WP controller reads WP_JERK / WP_ACC / WP_SPD
        # only in wp_and_spline_init, which runs when GUIDED enters its WP sub-mode -- a vehicle
        # that is ALREADY in GUIDED-WP keeps the limits it started with, and a same-mode request
        # is a no-op. The executor always arrives from AUTO, so a flight re-inits; this probe
        # must force it. (Measured 2026-11-10: three param sets with no bounce, three identical
        # curves.)
        if not args.no_bounce:
            req0 = ModeSwitch.Request()
            req0.mode = AP_COPTER_MODE["LOITER"]
            fut0 = cli.call_async(req0)
            rclpy.spin_until_future_complete(node, fut0, timeout_sec=10.0)
            r0 = fut0.result()
            print(f"[probe] bounce: ModeSwitch(LOITER=5) -> status={getattr(r0, 'status', None)} "
                  f"curr_mode={getattr(r0, 'curr_mode', None)}", flush=True)
            t_b = time.time() + 1.5
            while time.time() < t_b:
                rclpy.spin_once(node, timeout_sec=0.05)
        req = ModeSwitch.Request()
        req.mode = AP_COPTER_MODE["GUIDED"]
        t_mode_req = time.time()
        fut = cli.call_async(req)
        rclpy.spin_until_future_complete(node, fut, timeout_sec=10.0)
        r = fut.result()
        mode_resp = (None if r is None else
                     {"status": bool(getattr(r, "status", False)),
                      "curr_mode": int(getattr(r, "curr_mode", -1)),
                      "latency_s": round(time.time() - t_mode_req, 3)})
        print(f"[probe] ModeSwitch(GUIDED=4) -> {mode_resp}", flush=True)
        t_settle = time.time() + args.settle_s
        while time.time() < t_settle:
            rclpy.spin_once(node, timeout_sec=0.05)

    p0 = latest["p"]  # re-read: the vehicle may have drifted during the settle
    target = (p0[0] + args.east, p0[1] + args.north, p0[2] + args.up)
    print(f"[probe] commanding ENU{tuple(round(c, 2) for c in target)} from ENU{tuple(round(c, 2) for c in p0)} "
          f"at {args.rate_hz:.1f} Hz for {args.hold_s:.1f} s", flush=True)
    t_cmd = time.time()
    period = 1.0 / args.rate_hz
    next_pub = t_cmd
    n_pub = 0
    while time.time() < t_cmd + args.hold_s:
        now = time.time()
        if now >= next_pub:
            sink.send_setpoint_enu(target)
            n_pub += 1
            next_pub += period
        rclpy.spin_once(node, timeout_sec=0.02)
        if n_pub % 10 == 0 and latest["p"] is not None and abs(now - next_pub + period) < 0.03:
            p = latest["p"]
            print(f"[probe] t={now - t_cmd:5.1f}s  ENU({p[0]:.2f}, {p[1]:.2f}, {p[2]:.2f})", flush=True)

    summary = summarize(series, p0, target, t_cmd)
    # Real-time factor over the command window from the poses' own stamps: every t(s) above is WALL
    # time, and only this ratio says how much SIM time that was. RTF ~1 -> the two axes agree.
    win = [(w, st) for w, st in stamps if w >= t_cmd]
    rtf = None
    if len(win) >= 2 and win[-1][0] > win[0][0]:
        rtf = round((win[-1][1] - win[0][1]) / (win[-1][0] - win[0][0]), 3)
    for r in summary["samples"]:
        r["t_sim_s"] = (round(r["t_s"] * rtf, 2) if rtf else None)
    summary["rtf_over_command_window"] = rtf
    summary.update({
        "schema_version": "1.0",
        "written_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "inputs": vars(args) | {"out_dir": str(args.out_dir)},
        "p0_enu": [round(c, 3) for c in p0], "target_enu": [round(c, 3) for c in target],
        "setpoints_published": n_pub,
        "mode_switch": mode_resp, "status_topic": status["last"],
        "home_used_by_adapter": {"lat": sink.home_lat, "lon": sink.home_lon, "alt_amsl": sink.home_alt},
        "series_decimated": [{"t_s": round(t - t_cmd, 3), "enu": [round(c, 3) for c in p]}
                             for i, (t, p) in enumerate(series) if i % 3 == 0],
    })
    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"actuation_probe_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(summary, indent=1) + "\n")

    print("\n[probe] commanded-vs-achieved (along the command axis):")
    print("   t(s)   along(m)  cross(m)  dz(m)   to-target(m)")
    for r in summary["samples"]:
        print(f"  {r['t_s']:5.1f}  {r['along_m']:8.3f}  {r['cross_m']:8.3f}  {r['dz_m']:6.3f}  {r['dist_to_target_m']:10.3f}")
    print(f"[probe] real-time factor over the command window: {summary['rtf_over_command_window']} "
          f"(multiply the t(s) column by this for SIM seconds)")
    print(f"[probe] first motion (>0.30 m along): {summary['t_first_motion_s']} s; "
          f"within 3 m: {summary['t_within_3m_s']} s; within 1 m: {summary['t_within_1m_s']} s; "
          f"peak along-speed {summary['peak_along_speed_mps']} m/s; poses {summary['poses_recorded']}")
    print(f"[probe] wrote {out}")
    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
