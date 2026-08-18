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
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from .clip_recorder import ClipWriter
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
    from rclpy.qos import qos_profile_sensor_data
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
            self._latest_pose = None           # (pos, quat_xyzw, arrival_wall_s)
            self._rgb_by_stamp: dict = {}       # (sec, nanosec) -> np rgb array (bounded, see below)
            self._dropped_no_pose = 0

            self.create_subscription(CameraInfo, topics["rgb_camera_info"], self._on_info,
                                     qos_profile_sensor_data)
            self.create_subscription(Image, topics["rgb_image"], self._on_rgb,
                                     qos_profile_sensor_data)
            self.create_subscription(Image, "/fg/ndvi/image", self._on_ndvi,
                                     qos_profile_sensor_data)
            self.create_subscription(PoseStamped, "/ap/pose/filtered", self._on_pose,
                                     qos_profile_sensor_data)
            self.create_subscription(PoseStamped, "/ap/gps_global_origin/filtered", self._on_origin,
                                     qos_profile_sensor_data)
            self.get_logger().info(f"recording to {out_dir} (waiting for camera_info + frames; "
                                   f"ndvi_node must be running)")

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
            self._latest_pose = ((p.x, p.y, p.z), (o.x, o.y, o.z, o.w), time.monotonic())

        def _on_origin(self, msg) -> None:
            if self.writer is not None and self.writer.origin is None:
                p = msg.pose.position
                self.writer.origin = {"lat_deg?": None, "note": "PoseStamped passthrough",
                                      "x": p.x, "y": p.y, "z": p.z}

        def _on_rgb(self, msg) -> None:
            key = (msg.header.stamp.sec, msg.header.stamp.nanosec)
            arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.width, 3)
            self._rgb_by_stamp[key] = arr.copy()
            if len(self._rgb_by_stamp) > 20:  # bound the buffer; NDVI trails rgb by <1 frame
                self._rgb_by_stamp.pop(next(iter(self._rgb_by_stamp)))

        def _on_ndvi(self, msg) -> None:
            if self.writer is None:
                return  # no intrinsics yet
            if self._latest_pose is None:
                self._dropped_no_pose += 1
                if self._dropped_no_pose in (1, 10):
                    self.get_logger().warn(
                        f"NDVI frame with no /ap/pose/filtered yet (x{self._dropped_no_pose}) -- "
                        f"is SITL up with DDS enabled?")
                return
            stamp_s = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            ndvi = np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width)
            pos, quat_xyzw, pose_arrival = self._latest_pose
            rgb = self._rgb_by_stamp.pop((msg.header.stamp.sec, msg.header.stamp.nanosec), None)
            self.writer.add_frame(stamp_s, ndvi, pos, quat_xyzw,
                                  pose_age_wall_s=time.monotonic() - pose_arrival, rgb=rgb)
            if self.writer.n_frames % 25 == 1:
                self.get_logger().info(f"recorded {self.writer.n_frames} frames "
                                       f"({self.writer.n_rgb} with rgb)")

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
            summary = node.writer.finalize()
            print(f"\n[record_node] clip finalized: {summary}")
            print(f"[record_node] next: python3 scripts/stitch_ndvi.py --clip {summary['out_dir']}")
        else:
            print("\n[record_node] NOTHING RECORDED — no camera_info ever arrived "
                  "(bridge or ndvi_node down?)", file=sys.stderr)
        node.destroy_node()
        rclpy.shutdown()
    return 0 if node.writer is not None and node.writer.n_frames > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
