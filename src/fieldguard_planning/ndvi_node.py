"""ROS 2 bringup node for the NDVI fusion pipeline (Weeks 5-6, ADR-007 downstream).

Wires the locked `/fg/*` contract (ADR-007) to the tested fusion core in `ndvi_fusion.py`:

    /fg/sensor/rgb/image (rgb8)  ──┐
                                    ├─▶ message_filters.ApproximateTimeSynchronizer ─▶ NdviFuser.fuse
    /fg/sensor/nir/image (mono16)──┘         (slop = ndvi_fusion.max_stamp_delta_s)      │
                                                                                          ▼
                                                        /fg/ndvi/image (32FC1, AUTHORITATIVE)
                                                        /fg/ndvi/camera_info (pass-through from rgb)
                                                        /fg/ndvi/preview (rgb8, human-only, published
                                                        ONLY while subscribed -- ADR-013 am. 6)

Alongside the image path, a 1 Hz timer publishes this node's counters to the stats side-channel
(`ndvi_fusion.write_fuser_stats`), which `clip_recorder.finalize()` folds into each clip's
meta.json -- so an under-delivering flight can be root-caused from the artifact instead of from a
console that has scrolled away (ADR-013 amendment 5).

The fusion math is sim-agnostic and unit-tested in `ndvi_fusion.py` (rescale/compute_ndvi/the 0/0
guard, the stale-pair drop path, decode_rgb8/decode_mono16, the preview colormap, and the stats
side-channel's write/read/staleness paths). What is left here is rclpy wiring -- same "thin adapter" discipline as `avoidance_node.py`/`ros2_adapter.py`
(Week 3-4): rclpy imports lazily inside `build_node()`/`main()` so the sibling pure modules stay
importable (and testable) on a bare interpreter with no ROS 2 environment.

The outgoing-message assembly itself (the ADR-007 stamp anchor, the 32FC1/rgb8 `step` arithmetic, the
contiguity of the serialised buffer) is NOT rclpy wiring -- it is arithmetic that is wrong or right
off-sim, so it lives in the module-level pure functions below (`assemble_ndvi_msg_fields`,
`assemble_preview_msg_fields`, `apply_image_fields`) and is unit-tested in
`tests/fieldguard_planning/test_ndvi_node.py`. The callback only constructs `Image()` and publishes.

STATUS: NOT RUN LIVE. The render this node depends on (`/fg/sensor/rgb/image`,
`/fg/sensor/nir/image`) has not rendered yet -- gated on the human Docker session,
`docs/runbooks/NDVI_VALIDATION.md` Gates 0-2. This file is written and ready to run the moment those topics
exist; do not treat anything here as exercised against the real render until Gate 2 is green and
this node has actually been run against it (mirrors how `avoidance_node.py` was written ahead of
its own Week-3 Docker validation).

VERIFY-IN-CONTAINER items (cannot be checked outside Docker/ROS 2, same category as
`ros2_adapter.py`'s note):
  * `message_filters` is a standard ROS 2 Humble package (`ros-humble-message-filters`) but is not
    used anywhere else in this repo yet -- confirm it's on the container's install line
    (`docs/runbooks/SIM_BRINGUP.md` / the Dockerfile) before first run; add it if missing.
  * [ANSWERED 2026-08-21, four flights] the per-band counters ride
    `message_filters.Subscriber.registerCallback` (standard `SimpleFilter` API -- the synchronizer
    itself attaches the same way), which this repo had never used. They climb: red 73/126/113/217,
    nir 404/418/409/411 (ADR-013 am. 6). Nothing left to confirm here.
  * `use_sim_time` is NOT hardcoded here (matches `avoidance_node.py`'s convention) -- launch with
    `--ros-args -p use_sim_time:=true` per ADR-007's "use_sim_time=true" requirement, or the NDVI
    frame's stamp arithmetic (delta vs. the stale-pair guard) will compare wall-clock stamps against
    sim-time stamps.
"""
from __future__ import annotations

from typing import NamedTuple, Optional

import numpy as np

from .ndvi_fusion import (
    FUSER_STATS_PERIOD_S,
    NdviFuser,
    decode_mono16,
    decode_rgb8,
    load_camera_config,
    ndvi_to_preview_rgb,
    write_fuser_stats,
)


# --------------------------------------------------------------------------------------------------
# Outgoing sensor_msgs/Image assembly -- pure, no rclpy (tested in test_ndvi_node.py)
# --------------------------------------------------------------------------------------------------
NDVI_ENCODING = "32FC1"          # float32, 1 channel -> 4 bytes per pixel
NDVI_BYTES_PER_PIXEL = 4
PREVIEW_ENCODING = "rgb8"        # uint8, 3 channels -> 3 bytes per pixel
PREVIEW_BYTES_PER_PIXEL = 3

# Arrival-skew tolerance of the pairing queue (see the live finding at its use site). Named here
# because it is also reported in the persisted counters -- a fused_count far below the per-band
# counts is read against this number.
SYNC_QUEUE_SIZE = 60


class ImageMsgFields(NamedTuple):
    """The sensor_msgs/Image field values for one outgoing frame. Deliberately a plain tuple and NOT
    a ROS message: it is built by the pure functions below (importable on a bare interpreter) and
    copied onto a real `Image()` by `apply_image_fields` at the last possible moment."""
    header: object   # the RGB header object, passed through untouched -- see georef_anchor_header
    height: int
    width: int
    encoding: str
    is_bigendian: int
    step: int
    data: bytes


def georef_anchor_header(rgb_header, nir_header):
    """ADR-007: the fused NDVI frame inherits the RGB frame's header. The RGB stamp is the georef
    anchor `ndvi_georef.py` interpolates the vehicle pose against, so the NIR header must never be
    the one that ships. Returning `rgb_header` is the whole rule -- it lives in a named, tested
    function rather than a comment inside the rclpy callback precisely because "use the NIR stamp
    instead" is a plausible-sounding edit that would silently mis-georeference every stitched cell
    (by up to one stale-pair tolerance, 50 ms at 5 Hz, of flight)."""
    return rgb_header


def assemble_ndvi_msg_fields(ndvi: np.ndarray, rgb_header, nir_header) -> ImageMsgFields:
    """Field values for `/fg/ndvi/image` (32FC1, AUTHORITATIVE -- ADR-007).

    Takes BOTH headers on purpose so the stamp-anchor choice happens inside a testable function
    (see `georef_anchor_header`) instead of at an untestable call site.

    `ascontiguousarray(..., float32)` is load-bearing, not decoration: `FusionResult.ndvi` may be a
    view (a slice or transpose of the fused array), and `.tobytes()` on a non-contiguous -- or
    non-float32 -- view would serialise the wrong bytes for the `step` this function declares."""
    if ndvi.ndim != 2:
        raise ValueError(f"NDVI array must be 2D (height, width), got shape {ndvi.shape}")
    height, width = int(ndvi.shape[0]), int(ndvi.shape[1])
    buf = np.ascontiguousarray(ndvi, dtype=np.float32)
    return ImageMsgFields(
        header=georef_anchor_header(rgb_header, nir_header),
        height=height,
        width=width,
        encoding=NDVI_ENCODING,
        is_bigendian=0,
        step=width * NDVI_BYTES_PER_PIXEL,
        data=buf.tobytes(),
    )


def assemble_preview_msg_fields(ndvi: np.ndarray, rgb_header, nir_header) -> ImageMsgFields:
    """Field values for `/fg/ndvi/preview` (rgb8, human-only, non-authoritative -- ADR-007). Applies
    the false-color colormap here so the preview cannot drift out of shape-agreement with the
    authoritative frame, and carries the SAME georef anchor so the two line up frame-for-frame in
    rviz/rosbag."""
    if ndvi.ndim != 2:
        raise ValueError(f"NDVI array must be 2D (height, width), got shape {ndvi.shape}")
    buf = np.ascontiguousarray(ndvi_to_preview_rgb(ndvi), dtype=np.uint8)
    height, width = int(buf.shape[0]), int(buf.shape[1])
    return ImageMsgFields(
        header=georef_anchor_header(rgb_header, nir_header),
        height=height,
        width=width,
        encoding=PREVIEW_ENCODING,
        is_bigendian=0,
        step=width * PREVIEW_BYTES_PER_PIXEL,
        data=buf.tobytes(),
    )


def apply_image_fields(msg, fields: ImageMsgFields):
    """Copy an `ImageMsgFields` onto a sensor_msgs/Image (duck-typed -- any object with these
    attributes works, which is what makes it testable) and return it. Split out from the callback
    because a field silently dropped here (`step`, `is_bigendian`) yields a subtly corrupt image
    that only shows up as garbage in rviz, long after the flight."""
    msg.header = fields.header
    msg.height = fields.height
    msg.width = fields.width
    msg.encoding = fields.encoding
    msg.is_bigendian = fields.is_bigendian
    msg.step = fields.step
    msg.data = fields.data
    return msg


def build_node():
    """Construct the rclpy node. Factory pattern (matches avoidance_node.build_node) so the
    (untestable-off-sim) rclpy/message_filters import stays lazy."""
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data  # BEST_EFFORT -- matches the Gazebo camera
    # sensor bridge's publisher QoS (same gotcha flagged in avoidance_node.py for /ap/pose/filtered).
    from sensor_msgs.msg import CameraInfo, Image
    import message_filters

    class NdviNode(Node):
        def __init__(self):
            super().__init__("fieldguard_ndvi")
            cfg = load_camera_config()
            self.fuser = NdviFuser.from_config(cfg)
            topics = cfg["camera"]["topics"]

            self.ndvi_pub = self.create_publisher(Image, "/fg/ndvi/image", 10)
            self.ndvi_info_pub = self.create_publisher(CameraInfo, "/fg/ndvi/camera_info", 10)
            self.preview_pub = self.create_publisher(Image, "/fg/ndvi/preview", 10)

            self._rgb_info: Optional[CameraInfo] = None
            # Per-band arrival counters: the pair (red_frames, nir_frames) vs fused_count is what
            # separates "a band never arrived" from "both arrived but never paired" -- the question
            # the 2 Hz flight could not answer (ADR-013 amendment 4). Counted on the filter
            # subscribers that already deserialise these messages, so no second subscription and no
            # second copy of a 640x480 frame.
            self._red_frames = 0
            self._nir_frames = 0
            self._camera_info_frames = 0
            self._last_fused_stamp_sim_s: Optional[float] = None
            self.create_subscription(CameraInfo, topics["rgb_camera_info"], self._on_rgb_info,
                                     qos_profile_sensor_data)

            rgb_sub = message_filters.Subscriber(self, Image, topics["rgb_image"],
                                                 qos_profile=qos_profile_sensor_data)
            nir_sub = message_filters.Subscriber(self, Image, topics["nir_image"],
                                                 qos_profile=qos_profile_sensor_data)
            rgb_sub.registerCallback(self._count_red)
            nir_sub.registerCallback(self._count_nir)
            # ADR-007 amendment: message_filters' own slop is set to the SAME 25%-of-period bound
            # ndvi_fusion.NdviFuser re-enforces per-pair below -- belt-and-suspenders, not redundant:
            # this slop only decides which NIR message gets HANDED to the callback as "nearest";
            # NdviFuser.fuse() independently re-checks the actual delta and is what increments
            # dropped_pair_count if the nearest available match still isn't close enough (e.g. a
            # dropped NIR frame widened the true nearest gap beyond tolerance).
            self._sync = message_filters.ApproximateTimeSynchronizer(
                [rgb_sub, nir_sub], queue_size=SYNC_QUEUE_SIZE, slop=self.fuser.max_delta_s)
            # queue_size 60, not 10 (2026-08-18 live finding): under host CPU contention each band
            # drops frames independently and arrives bursty, so a stamp's partner may lag many
            # messages behind — with queue 10 the match was flushed before it could pair and fused
            # output STARVED to ~zero while both raw bands looked alive (the 18-frame flight).
            # A deeper queue only tolerates ARRIVAL skew; the stamp-accuracy bound (slop = 25% of
            # the frame period, ADR-007) is untouched.
            self._sync.registerCallback(self._on_pair)

            # Persist the counters on a TIMER, not on the image path: one small atomic file write
            # per second, which `clip_recorder.finalize()` folds into the clip's meta.json (see
            # ndvi_fusion's side-channel section). Written once here at startup too, so "fuser up,
            # nothing arriving" is distinguishable from "fuser never ran" from the first second.
            write_fuser_stats(self.counters())
            self.create_timer(FUSER_STATS_PERIOD_S, lambda: write_fuser_stats(self.counters()))

            self.get_logger().info(
                f"fieldguard_ndvi up: rgb={topics['rgb_image']} nir={topics['nir_image']} "
                f"update_rate={self.fuser.update_rate_hz}Hz slop={self.fuser.max_delta_s * 1000:.1f}ms")

        def _count_red(self, _msg) -> None:
            self._red_frames += 1

        def _count_nir(self, _msg) -> None:
            self._nir_frames += 1

        def _on_rgb_info(self, msg: "CameraInfo") -> None:
            self._rgb_info = msg
            self._camera_info_frames += 1

        def _on_pair(self, rgb_msg, nir_msg) -> None:
            rgb_stamp = rgb_msg.header.stamp.sec + rgb_msg.header.stamp.nanosec * 1e-9
            nir_stamp = nir_msg.header.stamp.sec + nir_msg.header.stamp.nanosec * 1e-9
            red_u8 = decode_rgb8(rgb_msg.height, rgb_msg.width, rgb_msg.data)[:, :, 0]
            nir_u16 = decode_mono16(nir_msg.height, nir_msg.width, nir_msg.data)

            result = self.fuser.fuse(rgb_stamp, red_u8, nir_stamp, nir_u16)
            if not result.accepted:
                self.get_logger().warn(
                    f"[ndvi] dropped stale pair: delta={result.stamp_delta_s * 1000:.1f}ms > "
                    f"{self.fuser.max_delta_s * 1000:.1f}ms "
                    f"(dropped_pair_count={self.fuser.dropped_pair_count})")
                return

            # The sim-time marker: WHEN the fusion last produced, in the same clock the recorded
            # frames are stamped in -- so a fuser that stopped mid-flight is locatable in the clip,
            # not merely known to be stale in wall time.
            self._last_fused_stamp_sim_s = rgb_stamp

            # NDVI inherits the RGB stamp -- the georef anchor (ADR-007). Both headers go in; the
            # tested `georef_anchor_header` inside picks the RGB one.
            self.ndvi_pub.publish(apply_image_fields(
                Image(), assemble_ndvi_msg_fields(result.ndvi, rgb_msg.header, nir_msg.header)))

            if self._rgb_info is not None:
                info = self._rgb_info
                info.header = rgb_msg.header
                self.ndvi_info_pub.publish(info)

            # The preview is HUMAN-ONLY (ADR-007): nothing in this repo subscribes to it, so on every
            # unattended flight it cost a colormap over 307k px plus two 921,600 B copies plus a
            # serialize-and-write of a message with no reader -- on the very executor whose next job
            # is to drain the 921,600 B RGB subscription that the counters name as the starving stage
            # (red_frames 73 of 692 camera_info ticks, baseline 2026-08-21). Asking the publisher
            # whether anyone is listening is the whole fix; rviz still gets its preview the moment it
            # subscribes, so this removes work rather than removing the feature.
            if self.preview_pub.get_subscription_count() > 0:
                self.preview_pub.publish(apply_image_fields(
                    Image(), assemble_preview_msg_fields(result.ndvi, rgb_msg.header, nir_msg.header)))

            if self.fuser.fused_count % 25 == 1:  # heartbeat, not every frame (avoid log spam)
                self.get_logger().info(
                    f"[ndvi] fused_count={self.fuser.fused_count} "
                    f"dropped_pair_count={self.fuser.dropped_pair_count} "
                    f"zero_denom_count={result.zero_denom_count}")

        def counters(self) -> dict:
            """The whole where-did-it-starve chain in one payload: bands in (`red_frames`,
            `nir_frames`), pairs rejected by the stale-pair guard (`dropped_pair_count`), frames
            out (`fused_count`), and the config the first three are read against. `fused_count` is
            also the `/fg/ndvi/image` publish count -- publishing is unconditional on an accepted
            pair, so a second counter would be a second source of truth for one number."""
            return {"fused_count": self.fuser.fused_count,
                    "dropped_pair_count": self.fuser.dropped_pair_count,
                    "red_frames": self._red_frames,
                    "nir_frames": self._nir_frames,
                    "camera_info_frames": self._camera_info_frames,
                    "last_fused_stamp_sim_s": self._last_fused_stamp_sim_s,
                    "update_rate_hz": self.fuser.update_rate_hz,
                    "max_delta_s": self.fuser.max_delta_s,
                    "sync_queue_size": SYNC_QUEUE_SIZE}

    if not rclpy.ok():
        rclpy.init()
    return rclpy, NdviNode()


def main(argv=None):
    rclpy, node = build_node()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # Final write before the timer stops, so the sidecar the recorder reads at finalize carries
        # the exact terminal counts rather than the last periodic sample.
        write_fuser_stats(node.counters())
        node.get_logger().info(f"fieldguard_ndvi shutting down: {node.counters()}")
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
