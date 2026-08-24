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
  * [NOT YET RUN LIVE, added 2026-08-21] `nir_camera_info_frames` subscribes
    `/fg/sensor/nir/camera_info`, which is bridged (`sim/bridge/fg_sensor_bridge.yaml`) but has had
    ZERO subscribers until now -- so the first instrumented flight must confirm it climbs rather
    than sitting at 0. A 0 here means "nothing is publishing that topic", NOT "the NIR sensor never
    ticked", and the two must not be confused when reading the artifact.
  * `use_sim_time` is NOT hardcoded here (matches `avoidance_node.py`'s convention) -- launch with
    `--ros-args -p use_sim_time:=true` per ADR-007's "use_sim_time=true" requirement, or the NDVI
    frame's stamp arithmetic (delta vs. the stale-pair guard) will compare wall-clock stamps against
    sim-time stamps.
"""
from __future__ import annotations

from collections import deque
from typing import Dict, NamedTuple, Optional

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

# How long (in FRAME-STAMP seconds) a red frame is held before the histogram below decides it never
# paired. Both bands render on one 5 Hz tick grid and arrive bursty, so a red's partner can lag it
# by many messages; 2 s is 10 ticks of slack, ~40x the observed max frame age (0.190 s).
UNPAIRED_SETTLE_S = 2.0
# Bounded, tiny, and deliberately generous: 512 stamps is ~170 s of NIR at its measured ~3 Hz and
# ~5 min of red at its measured ~1.6 Hz, against a 2 s settle window. Anything evicted before it
# could be classified is COUNTED (`evicted_undrained`), never silently dropped.
UNPAIRED_STAMP_WINDOW = 512
# Bucket boundaries are compared with a 1 us tolerance. Not cosmetic: a real 0.2 s tick difference
# between two `sec + nanosec*1e-9` floats lands at 0.2 +/- ~2e-13, so a bare `< tick_s` would sort
# identical physical situations into DIFFERENT buckets at random -- and the tick bucket is the whole
# answer this diagnostic exists to produce. 1 us is ~5e6x the float noise and 2e5x under the tick.
BUCKET_EPS_S = 1e-6


def unpaired_red_count(red_frames: int, fused_count: int, dropped_pair_count: int) -> int:
    """Red frames that ARRIVED at this node and never became a fused frame (ADR-013 am. 6a).

    `_on_pair` has exactly two outcomes, so this subtraction is an identity, not an estimate: it is
    precisely the red frames `ApproximateTimeSynchronizer` never handed over at all. It gets a NAME
    in the schema because the alternative -- leaving it as a subtraction -- is how
    `dropped_pair_count: 0` came to be misread as "pairing was healthy" for four flights. Plain
    `int` at the write boundary on purpose (`json.dumps(np.int64)` raises TypeError inside the 1 Hz
    stats timer, which would kill the fusion node mid-flight). Clamped at 0: the counters are
    sampled from one thread but `fused_count` can legitimately be one ahead of `red_frames` for the
    duration of a single `_on_pair`, and a negative count would read as a bug that isn't one."""
    return max(0, int(red_frames) - int(fused_count) - int(dropped_pair_count))


class UnpairedNirDeltaHistogram:
    """ONE-OFF DIAGNOSTIC (2026-08-21): for every red frame that arrived and never fused, how far
    away was the nearest NIR frame that DID arrive?

    It exists to settle one question offline, on evidence, instead of spending a flight on it:
    **could widening the synchronizer slop ever pair anything?** Both sensors sit on one rigid link
    at one `update_rate`, so every render tick stamps an RGB and a NIR onto the same 0.2 s grid,
    while the slop is only 25 % of that period (ADR-007). The hypothesis is therefore that an
    unpaired red's nearest surviving NIR is a FULL TICK away -- i.e. its own-tick partner died in
    transport and no slop short of 200 ms (which would pair bands from different ticks, ~0.6 m of
    flight) can recover it. Three buckets, boundaries taken from the live constants rather than
    hardcoded, so the answer is readable without knowing the config:

        <= slop      the pair was reachable and something else lost it -- the model is WRONG
        slop..tick   arrival skew is real; widening slop is a live lever
        >= tick      the own-tick partner never arrived; the slop lever is DEAD

    Pure and bounded: two small stamp deques and a handful of ints, no allocation per frame beyond
    a deque append, and the classification runs on the 1 Hz stats timer -- never on the image path.
    Rides the existing sidecar (ADR-013 am. 5); it adds no topic and no file."""

    def __init__(self, slop_s: float, tick_s: float, settle_s: float = UNPAIRED_SETTLE_S,
                 window: int = UNPAIRED_STAMP_WINDOW):
        self.slop_s = float(slop_s)
        self.tick_s = float(tick_s)
        self.settle_s = float(settle_s)
        self.window = int(window)
        self._red: deque = deque()            # pending red stamps, arrival order
        self._nir: deque = deque(maxlen=self.window)
        self._paired: deque = deque()         # rgb stamp keys handed to _on_pair
        self._paired_keys: set = set()
        self._newest_stamp_s: Optional[float] = None
        self._counts: Dict[str, int] = {"le_slop": 0, "slop_to_tick": 0, "ge_tick": 0}
        self._no_nir_in_window = 0
        self._evicted_undrained = 0

    @staticmethod
    def _key(stamp_s: float) -> int:
        """Microsecond key. Both sides derive the stamp from the same `sec`/`nanosec` fields so the
        floats are already identical; keying on an int removes the question."""
        return int(round(float(stamp_s) * 1e6))

    def _note_stamp(self, stamp_s: float) -> None:
        s = float(stamp_s)
        if self._newest_stamp_s is None or s > self._newest_stamp_s:
            self._newest_stamp_s = s

    def on_red(self, stamp_s: float) -> None:
        self._red.append(float(stamp_s))
        while len(self._red) > self.window:
            self._red.popleft()
            self._evicted_undrained += 1
        self._note_stamp(stamp_s)

    def on_nir(self, stamp_s: float) -> None:
        self._nir.append(float(stamp_s))
        self._note_stamp(stamp_s)

    def on_pair(self, rgb_stamp_s: float) -> None:
        key = self._key(rgb_stamp_s)
        self._paired.append(key)
        self._paired_keys.add(key)
        while len(self._paired) > self.window:
            self._paired_keys.discard(self._paired.popleft())

    def drain(self) -> None:
        """Classify every pending red older than the settle window. Called from the stats timer."""
        if self._newest_stamp_s is None:
            return
        cutoff = self._newest_stamp_s - self.settle_s
        while self._red and self._red[0] <= cutoff:
            stamp = self._red.popleft()
            if self._key(stamp) in self._paired_keys:
                continue                                   # it fused; not this histogram's business
            if not self._nir:
                self._no_nir_in_window += 1
                continue
            delta = min(abs(n - stamp) for n in self._nir)
            if delta <= self.slop_s + BUCKET_EPS_S:
                self._counts["le_slop"] += 1
            elif delta < self.tick_s - BUCKET_EPS_S:
                self._counts["slop_to_tick"] += 1
            else:
                self._counts["ge_tick"] += 1

    def snapshot(self) -> dict:
        """Plain ints/floats only -- this dict goes straight into `json.dumps` on a 1 Hz timer."""
        classified = sum(self._counts.values()) + self._no_nir_in_window
        return {"classified": int(classified),
                "le_slop": int(self._counts["le_slop"]),
                "slop_to_tick": int(self._counts["slop_to_tick"]),
                "ge_tick": int(self._counts["ge_tick"]),
                "no_nir_in_window": int(self._no_nir_in_window),
                "pending": int(len(self._red)),
                "evicted_undrained": int(self._evicted_undrained),
                "slop_s": float(self.slop_s),
                "tick_s": float(self.tick_s),
                "settle_s": float(self.settle_s)}


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
            # The NIR band's MISSING DENOMINATOR (2026-08-21). `camera_info_frames` counts only the
            # RGB sensor's camera_info, so every statement anyone has made about NIR delivery has
            # rested on ASSUMING the thermal sensor ticked at the same 5 Hz the RGB sensor's
            # camera_info proves the RGB sensor ticked. This topic is already bridged and had ZERO
            # subscribers; camera_info is deliberately left RELIABLE at the bridge (the control),
            # so it measures the SENSOR TICK, not image transport. ~= camera_info_frames means the
            # NIR band loses in transport and a transport lever applies; ~= nir_frames means the
            # thermal sensor is under-rendering and no transport lever can help.
            self._nir_camera_info_frames = 0
            self._last_fused_stamp_sim_s: Optional[float] = None
            self._unpaired_hist = UnpairedNirDeltaHistogram(
                slop_s=self.fuser.max_delta_s, tick_s=1.0 / self.fuser.update_rate_hz)
            self.create_subscription(CameraInfo, topics["rgb_camera_info"], self._on_rgb_info,
                                     qos_profile_sensor_data)
            # Same QoS as the RGB camera_info above, deliberately: the two counters are only
            # comparable if they are subscribed identically.
            self.create_subscription(CameraInfo, topics["nir_camera_info"], self._on_nir_info,
                                     qos_profile_sensor_data)

            rgb_sub = message_filters.Subscriber(self, Image, topics["rgb_image"],
                                                 qos_profile=qos_profile_sensor_data)
            nir_sub = message_filters.Subscriber(self, Image, topics["nir_image"],
                                                 qos_profile=qos_profile_sensor_data)
            rgb_sub.registerCallback(self._count_red)
            nir_sub.registerCallback(self._count_nir)
            # ADR-007 amendment: message_filters' own slop is the SAME 25%-of-period bound
            # ndvi_fusion.NdviFuser re-enforces per-pair below. CORRECTED 2026-08-21 (this comment
            # used to call that "belt-and-suspenders"): because slop IS max_delta_s, the
            # synchronizer can never hand `_on_pair` a pair the guard would reject, so
            # `dropped_pair_count` is STRUCTURALLY UNREACHABLE in the live node and 0 is the only
            # value it can take. The guard is still the right thing to keep -- `NdviFuser.fuse()`
            # is also called from the offline `pair_and_fuse_stream` path, which has no
            # synchronizer -- but nobody may read `dropped_pair_count: 0` as evidence that pairing
            # was lossless. The number that says that is `unpaired_red_count`, below.
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
            self.create_timer(FUSER_STATS_PERIOD_S, self._publish_stats)

            self.get_logger().info(
                f"fieldguard_ndvi up: rgb={topics['rgb_image']} nir={topics['nir_image']} "
                f"update_rate={self.fuser.update_rate_hz}Hz slop={self.fuser.max_delta_s * 1000:.1f}ms")

        @staticmethod
        def _stamp_s(msg) -> float:
            return msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9

        def _count_red(self, msg) -> None:
            self._red_frames += 1
            self._unpaired_hist.on_red(self._stamp_s(msg))

        def _count_nir(self, msg) -> None:
            self._nir_frames += 1
            self._unpaired_hist.on_nir(self._stamp_s(msg))

        def _on_rgb_info(self, msg: "CameraInfo") -> None:
            self._rgb_info = msg
            self._camera_info_frames += 1

        def _on_nir_info(self, _msg: "CameraInfo") -> None:
            self._nir_camera_info_frames += 1

        def _publish_stats(self) -> None:
            """The 1 Hz stats timer. Classification of settled unpaired reds happens HERE, off the
            image path, so the diagnostic costs the fused frame nothing."""
            self._unpaired_hist.drain()
            write_fuser_stats(self.counters())

        def _on_pair(self, rgb_msg, nir_msg) -> None:
            rgb_stamp = rgb_msg.header.stamp.sec + rgb_msg.header.stamp.nanosec * 1e-9
            nir_stamp = nir_msg.header.stamp.sec + nir_msg.header.stamp.nanosec * 1e-9
            red_u8 = decode_rgb8(rgb_msg.height, rgb_msg.width, rgb_msg.data)[:, :, 0]
            nir_u16 = decode_mono16(nir_msg.height, nir_msg.width, nir_msg.data)

            self._unpaired_hist.on_pair(rgb_stamp)

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
            pair, so a second counter would be a second source of truth for one number.

            Both bands now have a DENOMINATOR: `camera_info_frames` for red, `nir_camera_info_frames`
            for NIR (both left RELIABLE at the bridge, so both measure sensor ticks). Every value
            here is a plain Python int/float -- this dict is `json.dumps`d on a 1 Hz rclpy timer,
            where a numpy scalar raises TypeError and would take the fusion node down mid-flight."""
            return {"fused_count": int(self.fuser.fused_count),
                    "dropped_pair_count": int(self.fuser.dropped_pair_count),
                    "unpaired_red_count": unpaired_red_count(
                        self._red_frames, self.fuser.fused_count, self.fuser.dropped_pair_count),
                    "red_frames": int(self._red_frames),
                    "nir_frames": int(self._nir_frames),
                    "camera_info_frames": int(self._camera_info_frames),
                    "nir_camera_info_frames": int(self._nir_camera_info_frames),
                    "unpaired_red_nearest_nir": self._unpaired_hist.snapshot(),
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
        # Final drain + write before the timer stops, so the sidecar the recorder reads at finalize
        # carries the exact terminal counts rather than the last periodic sample. Reds still inside
        # the settle window stay `pending` rather than being force-classified -- an unsettled red is
        # not evidence about pairing, and reporting it as one would be the fabrication this whole
        # side-channel exists to prevent.
        node._publish_stats()
        node.get_logger().info(f"fieldguard_ndvi shutting down: {node.counters()}")
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
