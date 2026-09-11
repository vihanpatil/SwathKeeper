#!/usr/bin/env python3
"""D5/D6 at the BOOKED speed — in-container, self-triggering measurer for the depth step-0 flight.

Waits for the vehicle to climb past TRIGGER_Z_M on /ap/pose/filtered, then for WINDOW_S seconds counts
ROS depth frames vs ROS camera_info messages (D5 delivery = image / camera_info, the ADR-020 metric)
and records pitch and ground speed from /ap/pose/filtered (D6). Writes one JSON to /tmp/d5d6_depth_<UTC>.json
and prints a one-line summary. Runs inside fieldguard-sim after `source /root/ardu_ws/install/setup.bash`:

    python3 /tmp/d5d6_depth_measure.py            # blocks until triggered, then ~WINDOW_S + 5 s

Nothing here commands the vehicle; it only listens. Exit 0 = measured; 3 = never triggered (timeout).
"""
import json, math, os, sys, time, statistics
from datetime import datetime, timezone

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import Image, CameraInfo
from geometry_msgs.msg import PoseStamped

TRIGGER_Z_M = float(os.environ.get("TRIGGER_Z_M", "8.0"))
WINDOW_S = float(os.environ.get("WINDOW_S", "60.0"))
TIMEOUT_S = float(os.environ.get("TIMEOUT_S", "1500.0"))
DEPTH_IMG = os.environ.get("DEPTH_IMG", "/fg/depth/image")
DEPTH_INFO = os.environ.get("DEPTH_INFO", "/fg/depth/camera_info")
POSE = os.environ.get("POSE_TOPIC", "/ap/pose/filtered")


def pitch_deg(q):
    # ArduPilot AP_DDS pose is ENU/FLU-ish; pitch about body Y. Report both sign conventions honestly.
    x, y, z, w = q.x, q.y, q.z, q.w
    s = 2.0 * (w * y - z * x)
    s = max(-1.0, min(1.0, s))
    return math.degrees(math.asin(s))


class Meas(Node):
    def __init__(self):
        super().__init__("d5d6_depth_measure")
        sensor_qos = QoSProfile(depth=50, reliability=ReliabilityPolicy.BEST_EFFORT, history=HistoryPolicy.KEEP_LAST)
        self.create_subscription(Image, DEPTH_IMG, self._img, sensor_qos)
        self.create_subscription(CameraInfo, DEPTH_INFO, self._info, sensor_qos)
        self.create_subscription(PoseStamped, POSE, self._pose, sensor_qos)
        self.triggered = None
        self.n_img = 0
        self.n_info = 0
        self.img_stamps = []
        self.poses = []          # (t_ros, x, y, z, pitch_deg)
        self.last_z = None
        self.t0 = time.monotonic()

    def _in_window(self):
        return self.triggered is not None and (time.monotonic() - self.triggered) <= WINDOW_S

    def _img(self, m):
        if self._in_window():
            self.n_img += 1
            self.img_stamps.append(m.header.stamp.sec + m.header.stamp.nanosec * 1e-9)

    def _info(self, m):
        if self._in_window():
            self.n_info += 1

    def _pose(self, m):
        z = m.pose.position.z
        self.last_z = z
        if self.triggered is None and z > TRIGGER_Z_M:
            self.triggered = time.monotonic()
            print(f"[d5d6] TRIGGERED at z={z:.2f} m; measuring {WINDOW_S:.0f} s", flush=True)
        if self._in_window():
            t = m.header.stamp.sec + m.header.stamp.nanosec * 1e-9
            self.poses.append((t, m.pose.position.x, m.pose.position.y, z, pitch_deg(m.pose.orientation)))


def main():
    rclpy.init()
    n = Meas()
    print(f"[d5d6] waiting for z > {TRIGGER_Z_M} m on {POSE} (timeout {TIMEOUT_S:.0f} s) ...", flush=True)
    while rclpy.ok():
        rclpy.spin_once(n, timeout_sec=0.5)
        if n.triggered is not None and (time.monotonic() - n.triggered) > WINDOW_S + 2.0:
            break
        if n.triggered is None and (time.monotonic() - n.t0) > TIMEOUT_S:
            print("[d5d6] never triggered — no climb past trigger altitude", flush=True)
            rclpy.shutdown(); sys.exit(3)
    speeds = []
    for (t1, x1, y1, _, _), (t2, x2, y2, _, _) in zip(n.poses, n.poses[1:]):
        dt = t2 - t1
        if dt > 0:
            speeds.append(math.hypot(x2 - x1, y2 - y1) / dt)
    pitches = [p[4] for p in n.poses]
    zs = [p[3] for p in n.poses]
    img_dt = [b - a for a, b in zip(n.img_stamps, n.img_stamps[1:]) if b > a]
    out = {
        "kind": "d5d6_depth_at_booked_speed", "written_utc": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "trigger_z_m": TRIGGER_Z_M, "window_s": WINDOW_S, "topics": {"image": DEPTH_IMG, "camera_info": DEPTH_INFO, "pose": POSE},
        "D5": {"depth_frames": n.n_img, "camera_info_msgs": n.n_info,
               "delivery_ratio": (n.n_img / n.n_info) if n.n_info else None,
               "frame_rate_hz_from_stamps": (1.0 / statistics.median(img_dt)) if img_dt else None},
        "D6": {"pitch_deg_median": statistics.median(pitches) if pitches else None,
               "pitch_deg_min": min(pitches) if pitches else None, "pitch_deg_max": max(pitches) if pitches else None,
               "pitch_sign_note": "asin(2(wy - zx)); positive = nose up in this convention — check against a known climb",
               "pose_samples": len(n.poses)},
        "speed": {"ground_speed_mps_median": statistics.median(speeds) if speeds else None,
                  "ground_speed_mps_p90": (sorted(speeds)[int(0.9 * (len(speeds) - 1))] if speeds else None),
                  "ground_speed_mps_max": max(speeds) if speeds else None, "z_m_median": statistics.median(zs) if zs else None},
        "caveat": "one window on one flight; the booked speed is a CAP (WP_SPD), not a guarantee the window median reaches 5.0 m/s",
    }
    path = f"/tmp/d5d6_depth_{out['written_utc']}.json"
    json.dump(out, open(path, "w"), indent=1)
    print(f"[d5d6] D5 {n.n_img}/{n.n_info} = {out['D5']['delivery_ratio']}  | D6 pitch median {out['D6']['pitch_deg_median']} deg "
          f"(min {out['D6']['pitch_deg_min']}, max {out['D6']['pitch_deg_max']}) | speed median {out['speed']['ground_speed_mps_median']} m/s "
          f"p90 {out['speed']['ground_speed_mps_p90']} | -> {path}", flush=True)
    rclpy.shutdown()


if __name__ == "__main__":
    main()
