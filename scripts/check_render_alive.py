#!/usr/bin/env python3
"""Pre-flight render sanity probe: is the camera actually seeing the WORLD, or degraded sky-flat?

Born 2026-08-18: a long-lived Gazebo instance (hours of software rendering, several ArduPilot
reconnects, thousands of set_pose calls) silently degraded until both bands rendered a uniform
sky-like nothing — RGB near-white (238,238,235) everywhere, NIR flat at ambient — and a full
recorded flight produced a plausible-looking but content-free clip. Gate 2 had proven the SAME
instance healthy hours earlier, so liveness of the topics proves nothing; the PIXELS must be
checked before every recording flight.

Discriminator (works with the drone PARKED — no flight needed): the authored world is
green-dominant from above (soil material (0.30, 0.42, 0.20): G exceeds R by ~40%), while the
degraded-render signature is a bright, channel-balanced near-white. One RGB frame decides:

    healthy parked/flying:  G notably > R, frame not near-saturated
    degraded (sky-flat):    R ≈ G ≈ B at high brightness

Run inside the container (ROS 2 sourced, bridge up), any time before a flight:

    PYTHONPATH=/workspace/fieldguard/src:$PYTHONPATH python3 /workspace/fieldguard/scripts/check_render_alive.py

Exit 0 = render alive; exit 1 = degraded (restart Gazebo — Shell 1 — and re-probe); exit 2 = no
frame arrived at all (camera/bridge down). Stdlib + rclpy + numpy (in-container only, like the
nodes it guards).
"""
from __future__ import annotations

import sys

import numpy as np

TIMEOUT_S = 30.0
NEAR_WHITE_FLOOR = 200.0     # mean brightness above this in ALL channels -> sky-like
GREEN_DOMINANCE_MIN = 1.10   # healthy world from above: G/R well above this (authored ~1.4)


def verdict(rgb_mean) -> tuple:
    """(exit_code, message) for a frame's per-channel means. Pure — unit-testable."""
    r, g, b = (float(v) for v in rgb_mean)
    if min(r, g, b) > NEAR_WHITE_FLOOR and max(r, g, b) - min(r, g, b) < 15.0:
        return 1, (f"DEGRADED: frame is channel-balanced near-white ({r:.0f},{g:.0f},{b:.0f}) — "
                   f"the sky-flat render-degradation signature. Restart Gazebo (Shell 1) and re-probe.")
    if g / max(r, 1e-6) >= GREEN_DOMINANCE_MIN:
        return 0, f"ALIVE: green-dominant world in view ({r:.0f},{g:.0f},{b:.0f}), G/R={g / r:.2f}."
    return 1, (f"SUSPECT: neither green-dominant nor sky-white ({r:.0f},{g:.0f},{b:.0f}) — eyeball "
               f"a frame before trusting a recording (unexpected scene or lighting).")


def main() -> int:
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from sensor_msgs.msg import Image

    rclpy.init()
    node = rclpy.create_node("render_alive_probe")
    got: list = []

    def _on_img(msg):
        arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
        got.append(arr.reshape(-1, 3).mean(axis=0))

    node.create_subscription(Image, "/fg/sensor/rgb/image", _on_img, qos_profile_sensor_data)
    end = node.get_clock().now().nanoseconds + int(TIMEOUT_S * 1e9)
    while not got and node.get_clock().now().nanoseconds < end:
        rclpy.spin_once(node, timeout_sec=0.5)
    node.destroy_node()
    rclpy.shutdown()

    if not got:
        print(f"[check_render_alive] NO FRAME in {TIMEOUT_S:.0f}s — camera or bridge down (exit 2)")
        return 2
    code, msg = verdict(got[0])
    print(f"[check_render_alive] {msg}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
