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

BOTH APERTURES, not just the survey one (ADR-019, added 2026-08-26). This probe subscribed to
`/fg/sensor/rgb/image` alone, so `fly_pipeline.sh up` — which gates on it, mandatorily — went
all-green with the forward depth camera dead. That is the 2026-08-18 failure this file exists to
prevent, wearing the newer sensor. The depth requirement is DERIVED from the world being flown
(`depth_expected`: does the SDF declare the depth topic) rather than asserted, so a camera-stripped
or older world is not failed for a sensor it does not carry. Its discriminator is deliberately
weaker than the RGB one — a forward frustum always contains ground somewhere, so an entirely
non-finite frame means the depth pass produced nothing.

Run inside the container (ROS 2 sourced, bridge up), any time before a flight:

    PYTHONPATH=/workspace/fieldguard/src:$PYTHONPATH python3 /workspace/fieldguard/scripts/check_render_alive.py

Exit 0 = both bands alive; exit 1 = degraded (restart Gazebo — Shell 1 — and re-probe); exit 2 = a
required frame never arrived (camera/bridge down). Stdlib + rclpy + numpy (in-container only, like
the nodes it guards).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORLD = REPO_ROOT / "sim" / "worlds" / "farmguard_field.sdf"
DEPTH_TOPIC = "/fg/depth/image"

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


def depth_expected(world_path: Path = DEFAULT_WORLD) -> bool:
    """Does the world being flown actually carry the ADR-019 forward depth camera?

    Substring on the generated SDF's `<topic>` value. Derived, not assumed: `fly_pipeline.sh` gates
    on this probe, and failing a stripped or pre-ADR-019 world for a missing sensor would make the
    launcher unusable against it. A missing world file reads as 'no depth mount' — this probe's job
    is the render, and a missing world is the launcher's gate to catch."""
    try:
        return DEPTH_TOPIC.lstrip("/") in world_path.read_text()
    except OSError:
        return False


def depth_verdict(stats: Optional[dict]) -> tuple:
    """(exit_code, message) for one depth frame's summary, or None if none arrived. Pure.

    `stats` = {"finite_frac", "min_m", "max_m"}. The bar is deliberately low — liveness, not
    content: gz writes +inf past the far clip and -inf inside the near clip, and a forward frustum
    over this field always contains SOME ground, so an entirely non-finite frame means the depth
    pass produced nothing rather than that the world is empty."""
    if stats is None:
        return 2, (f"NO DEPTH FRAME in {TIMEOUT_S:.0f}s on {DEPTH_TOPIC} — the forward depth camera "
                   f"or its bridge is down. Note gz renders depth LAZILY: with no subscriber there "
                   f"are no frames AND no cost, so check the bridge printed six "
                   f"'Creating GZ->ROS Bridge' lines before blaming the sensor.")
    if stats["finite_frac"] <= 0.0:
        return 1, ("DEGRADED: every depth pixel is non-finite (+/-inf) — the depth pass rendered "
                   "nothing. Restart Gazebo (Shell 1) and re-probe.")
    return 0, (f"ALIVE: depth returns on {100.0 * stats['finite_frac']:.0f}% of pixels "
               f"({stats['min_m']:.1f}-{stats['max_m']:.1f} m).")


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

    depth: list = []
    want_depth = depth_expected()

    def _on_depth(msg):
        d = np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width)
        finite = np.isfinite(d)
        depth.append({"finite_frac": float(finite.mean()),
                      "min_m": float(d[finite].min()) if finite.any() else None,
                      "max_m": float(d[finite].max()) if finite.any() else None})

    node.create_subscription(Image, "/fg/sensor/rgb/image", _on_img, qos_profile_sensor_data)
    if want_depth:
        node.create_subscription(Image, DEPTH_TOPIC, _on_depth, qos_profile_sensor_data)
    end = node.get_clock().now().nanoseconds + int(TIMEOUT_S * 1e9)
    while node.get_clock().now().nanoseconds < end:
        if got and (depth or not want_depth):
            break
        rclpy.spin_once(node, timeout_sec=0.5)
    node.destroy_node()
    rclpy.shutdown()

    if not got:
        print(f"[check_render_alive] NO RGB FRAME in {TIMEOUT_S:.0f}s — camera or bridge down "
              f"(exit 2)")
        return 2
    code, msg = verdict(got[0])
    print(f"[check_render_alive] rgb: {msg}")
    if not want_depth:
        print("[check_render_alive] depth: SKIPPED — this world declares no forward depth camera")
        return code
    dcode, dmsg = depth_verdict(depth[0] if depth else None)
    print(f"[check_render_alive] depth: {dmsg}")
    # The worse of the two decides: a live RGB band is not evidence that the aperture the dodge
    # depends on is rendering. 2 (nothing arrived) outranks 1 (arrived, degraded).
    return max(code, dcode) if 2 not in (code, dcode) else 2


if __name__ == "__main__":
    raise SystemExit(main())
