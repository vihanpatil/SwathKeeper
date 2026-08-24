"""ROS 2 recorder node: live real-render flight -> spike-schema clip (Weeks 5-6 recording step).

The last missing link of the pipeline: after this records a flight,
`scripts/stitch_ndvi.py --clip <out>` produces the georeferenced heatmap (exit criterion 1) and
`eval/run_spike.sh` re-runs ADR-003 on real frames (criterion 3). Subscribes:

    /fg/ndvi/image (32FC1)          the AUTHORITATIVE fused band -- ndvi_node must be running;
                                     its stamp == the rgb stamp (the ADR-007 georef anchor)
    /fg/sensor/rgb/image (rgb8)      matched to the NDVI frame by EXACT stamp equality (the NDVI
                                     header is copied from the rgb message, so equality is the
                                     contract, not a tolerance) -> the ADR-003 RGB comparison arm
    /ap/pose/filtered                latest-by-arrival (clock domains differ -- see clip_recorder
                                     docstring); content is world-ENU per ADR-005 (frame_id lies)
    /ap/gps_global_origin/filtered   captured once into meta.json (the ADR-005 georef anchor rule)

Run INSIDE the container (ROS 2 sourced), typically as the 7th shell of the recording flight
(gazebo, bridge, agent, SITL, birds, ndvi_node, THIS):

    python3 -m fieldguard_planning.record_node --out /workspace/fieldguard/eval/results/clips/real_flight_$(date -u +%Y%m%dT%H%M%SZ)

Ctrl-C to stop; it finalizes meta.json and prints the summary + the exact stitch command to run
next. Same thin-adapter discipline as ndvi_node.py: rclpy imports stay inside build_node(), the
recording logic lives in the unit-tested clip_recorder.ClipWriter.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from .clip_recorder import ClipWriter, PoseBuffer, RecorderCounters, StreamingClockParser
from .ndvi_fusion import load_camera_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def _spike_png_writer():
    """sim/spike's stdlib PNG encoder, imported the same way scripts/stitch_ndvi.py does. Returns
    None (RGB frames skipped, recording still valid) if unavailable -- the NDVI band is the
    authoritative product; the RGB arm is a comparison nicety."""
    try:
        sys.path.insert(0, str(REPO_ROOT / "sim" / "spike"))
        from gen_spike_clip import write_png
        return write_png
    except Exception:  # pragma: no cover -- environment-dependent
        return None


def build_node(out_dir: Path):
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
    from geometry_msgs.msg import PoseStamped
    from sensor_msgs.msg import CameraInfo, Image

    class RecordNode(Node):
        def __init__(self):
            super().__init__("fieldguard_clip_recorder")
            cfg = load_camera_config()
            topics = cfg["camera"]["topics"]
            self.mount_offset = tuple(cfg["mount"]["mount_pose_xyz_rpy"][:3])

            self.writer: Optional[ClipWriter] = None  # created on first camera_info (live intrinsics)
            self._out_dir = out_dir
            self._png_writer = _spike_png_writer()
            self._pose_buf = PoseBuffer()
            self._gz_now: Optional[float] = None   # latest gz sim seconds (native clock stream)
            self._latest_pose = None               # arrival-fallback only (no clock stream)
            self._rgb_by_stamp: dict = {}          # (sec, nanosec) -> np rgb array (bounded)
            # Every recorder-side count lives in one pure object (clip_recorder.RecorderCounters)
            # and is folded into meta.json at finalize. Before this, the ONLY recorder-side number
            # in any artifact was num_frames, so 180 of the demo take's fused frames vanished with
            # no way to tell transport loss from an early return (ADR-013 am. 6a).
            self.counters = RecorderCounters()
            self._warned_no_clock = False
            self._start_clock_stream()

            self.create_subscription(CameraInfo, topics["rgb_camera_info"], self._on_info,
                                     qos_profile_sensor_data)
            self.create_subscription(Image, topics["rgb_image"], self._on_rgb,
                                     qos_profile_sensor_data)
            # LEVER L1 -- KEPT (F6 vs F5c, 2026-08-22, ADR-013 am. 8). Reliability ONLY; every
            # other field copied from qos_profile_sensor_data so it stayed a one-variable change.
            # The publisher at ndvi_node.py is already RELIABLE depth 10, so NACK repair became
            # available on the 1,228,800 B samples (the largest in the system) and CLOSED this hop:
            # 62.5% loss (F5c: 96 fused -> 36 received) -> 0.0% (F6: 72 -> 72). The predicted
            # backpressure was real and is the measured cost: red/ci 25.60% -> 20.46%. Net still
            # 1.69x painting cadence (0.2823 -> 0.4767 Hz) because the downstream leak was bigger.
            # RE-CHECK THIS TRADE if NIR transport is ever fixed -- with more fused frames arriving,
            # the upstream cost could outgrow the hop it closes.
            # L1 RE-CHECK CLOSED (2026-08-22, F9 vs F10, ADR-013 am. 8's standing clause): with L2
            # in place the hop is a DEAD HEAT -- RELIABLE lost 1.56 % of fused frames, BEST_EFFORT
            # 1.71 %, both at an identical 5.0 Hz painting cadence with 502 painting frames each.
            # KEPT, on two grounds: the 0.15-point margin favours RELIABLE, and L1's previously
            # MEASURED cost is gone -- the upstream backpressure that took red/ci 25.60 % -> 20.46 %
            # in round 2 does not appear at all now (both flights sit at 100 % red/ci), because L2
            # removed the drops that the retransmission was repairing. So L1 is now free insurance
            # for the case L2 cannot cover: a segment under pressure again (more participants, a
            # longer mission, a busier host).
            self.create_subscription(Image, "/fg/ndvi/image", self._on_ndvi,
                                     QoSProfile(depth=qos_profile_sensor_data.depth,
                                                history=qos_profile_sensor_data.history,
                                                durability=qos_profile_sensor_data.durability,
                                                reliability=ReliabilityPolicy.RELIABLE))
            self.create_subscription(PoseStamped, "/ap/pose/filtered", self._on_pose,
                                     qos_profile_sensor_data)
            self.create_subscription(PoseStamped, "/ap/gps_global_origin/filtered", self._on_origin,
                                     qos_profile_sensor_data)
            self.get_logger().info(f"recording to {out_dir} (waiting for camera_info + frames; "
                                   f"ndvi_node must be running; gz clock streamed natively for "
                                   f"stamp-paired poses)")

        def _start_clock_stream(self) -> None:
            """Native gz-transport clock via a `gz topic -e` subprocess + reader thread — NOT
            bridged through ros_gz (Gazebo's /clock is ~350 msgs/s; bridging it starved the image
            pipeline, measured live 2026-08-18). Failure here degrades to arrival pairing, loudly."""
            import threading

            def _reader():
                parser = StreamingClockParser()
                try:
                    proc = subprocess.Popen(["gz", "topic", "-e", "-t", "/clock"],
                                            stdout=subprocess.PIPE, text=True, bufsize=1)
                    for line in proc.stdout:
                        t = parser.feed(line)
                        if t is not None:
                            self._gz_now = t
                except Exception as exc:  # pragma: no cover -- environment-dependent
                    self.get_logger().warn(f"gz clock stream died: {exc} — arrival fallback")

            threading.Thread(target=_reader, daemon=True).start()

        def _on_info(self, msg) -> None:
            if self.writer is not None:
                return
            self.writer = ClipWriter(
                self._out_dir,
                camera_info={"image_width_px": msg.width, "image_height_px": msg.height,
                             "fx": msg.k[0], "fy": msg.k[4], "cx": msg.k[2], "cy": msg.k[5]},
                mount_offset_body_m=self.mount_offset,
                png_writer=self._png_writer)
            self.get_logger().info(
                f"live intrinsics locked: {msg.width}x{msg.height} fx={msg.k[0]:.1f} "
                f"cx={msg.k[2]:.1f} cy={msg.k[5]:.1f} (ADR-007 follow-up 5 evidence)")

        def _on_pose(self, msg) -> None:
            p, o = msg.pose.position, msg.pose.orientation
            pos, quat = (p.x, p.y, p.z), (o.x, o.y, o.z, o.w)
            if self._gz_now is not None:
                self._pose_buf.tag(self._gz_now, pos, quat)  # gz-domain tag: the burst-proof pairing key
            self._latest_pose = (pos, quat, time.monotonic())

        def _on_origin(self, msg) -> None:
            if self.writer is not None and self.writer.origin is None:
                p = msg.pose.position
                self.writer.origin = {"lat_deg?": None, "note": "PoseStamped passthrough",
                                      "x": p.x, "y": p.y, "z": p.z}

        def _on_rgb(self, msg) -> None:
            # This process is the SECOND independent subscriber to /fg/sensor/rgb/image (ndvi_node
            # is the first, where the same arrivals are counted as red_frames). Comparing the two
            # counters from one flight prices the fan-out hypothesis without changing any config.
            self.counters.rgb_msgs_received += 1
            key = (msg.header.stamp.sec, msg.header.stamp.nanosec)
            arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
            self._rgb_by_stamp[key] = arr.copy()
            if len(self._rgb_by_stamp) > 20:  # bound the buffer; NDVI trails rgb by <1 frame
                self._rgb_by_stamp.pop(next(iter(self._rgb_by_stamp)))

        def _on_ndvi(self, msg) -> None:
            """Arrival accounting + timing; the work is in `_record_ndvi_frame`.

            The counter increments BEFORE any guard, so `fused_count - ndvi_msgs_received` is
            exactly the frames that died in transport on this hop and never reached Python at all.
            The wall-clock measurement spans the WHOLE body -- including the ~2.15 MB of synchronous
            .npy writes and the flushed JSON row that `ClipWriter.add_frame` does on this same
            single-threaded executor -- because that is the one measurement that separates "the
            executor was blocked when frames died" from "the executor was idle and the middleware
            dropped them". `finally`, so a raising callback still records its cost."""
            t0 = time.monotonic()
            self.counters.ndvi_msgs_received += 1
            try:
                self._record_ndvi_frame(msg)
            finally:
                self.counters.observe_on_ndvi_wall_ms((time.monotonic() - t0) * 1000.0)

        def _record_ndvi_frame(self, msg) -> None:
            if self.writer is None:
                # Silent until 2026-08-21: every fused frame arriving before the first camera_info
                # was discarded with a bare return. On the F1 gate flight that window was >= 0.92 s
                # and nothing recorded it.
                self.counters.dropped_no_writer += 1
                return  # no intrinsics yet
            stamp_s = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            ndvi = np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width)
            rgb = self._rgb_by_stamp.pop((msg.header.stamp.sec, msg.header.stamp.nanosec), None)
            frame_age = None if self._gz_now is None else self._gz_now - stamp_s

            paired = self._pose_buf.nearest(stamp_s)
            if paired is not None:
                pos, quat_xyzw, residual = paired
            elif self._latest_pose is not None:
                # Arrival fallback — only reachable if the native gz clock stream never produced. Loudly
                # degraded: this is the mode that mislabeled the 2026-08-18 flight.
                if not self._warned_no_clock:
                    self._warned_no_clock = True
                    self.writer.pairing_mode = "arrival_fallback"
                    self.get_logger().warn(
                        "no gz clock reading yet — falling back to ARRIVAL pose pairing (render "
                        "bursts will mislabel frames; is the gz CLI on PATH inside the "
                        "container?)")
                pos, quat_xyzw, _ = self._latest_pose
                residual = float("nan")
            else:
                self.counters.dropped_no_pose += 1
                if self.counters.dropped_no_pose in (1, 10):
                    self.get_logger().warn(
                        f"NDVI frame with no /ap/pose/filtered yet "
                        f"(x{self.counters.dropped_no_pose}) -- is SITL up with DDS enabled?")
                return

            self.writer.add_frame(stamp_s, ndvi, pos, quat_xyzw,
                                  pose_pair_residual_s=residual, frame_age_sim_s=frame_age,
                                  rgb=rgb)
            if self.writer.n_frames % 25 == 1:
                self.get_logger().info(
                    f"recorded {self.writer.n_frames} frames ({self.writer.n_rgb} with rgb, "
                    f"{self.writer.n_stale} stale-pose flagged)")

    if not rclpy.ok():
        rclpy.init()
    return rclpy, RecordNode()


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True, help="clip output directory (created)")
    args = ap.parse_args(argv)

    rclpy, node = build_node(args.out)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node.writer is not None:
            summary = node.writer.finalize(recorder_counters=node.counters.to_meta())
            print(f"\n[record_node] clip finalized: {summary}")
            print(f"[record_node] next: python3 scripts/stitch_ndvi.py --clip {summary['out_dir']}")
        else:
            # The counters are the diagnosis here, not a footnote: ndvi_msgs_received > 0 with no
            # writer means fusion was publishing and camera_info never arrived, which is a very
            # different failure from ndvi_msgs_received == 0.
            print(f"\n[record_node] NOTHING RECORDED — no camera_info ever arrived "
                  f"(bridge or ndvi_node down?) counters={node.counters.to_meta()}", file=sys.stderr)
        node.destroy_node()
        if rclpy.ok():  # Ctrl-C may have already shut the context down; a second call raises
            rclpy.shutdown()
    return 0 if node.writer is not None and node.writer.n_frames > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
