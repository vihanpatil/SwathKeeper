"""Spike-schema clip writer -- the pure, unit-testable core of the real-render recorder.

Writes the EXACT directory layout `sim/spike/README.md` defines and `scripts/stitch_ndvi.py` +
`eval/run_spike.sh` consume, from live-flight data instead of the synthetic generator:

    <out>/meta.json          synthetic: false (the real thing at last), live camera intrinsics,
                             `fuser`: the NDVI node's own counters at finalize -- red/nir frames in,
                             pairs dropped, frames fused, plus the age of that reading, so a thin
                             clip says WHERE it thinned instead of only that it did;
                             `recorder`: THIS node's counters (schema 1.3) -- messages received vs
                             rows written, and how long the callback took, which is what separates
                             "the middleware dropped it" from "the callback dropped it";
                             `airborne`: frames and cadence over the flying window, the basis the
                             ADR-015 predictor's --fps expects.
                             `present: false` + a reason for any block whose source never published.
    <out>/poses.jsonl        one line per frame: drone pose + ndvi_path (+ honesty extras, below)
    <out>/frames/ndvi/*.npy  float32 (H,W) NDVI in [-1,1]  (AUTHORITATIVE band)
    <out>/frames/rgb/*.png   uint8 (H,W,3)                  (the ADR-003 RGB comparison arm)

Two contract details that MUST NOT drift (both regression-tested against the actual consumers):
  * poses.jsonl records quaternions in **wxyz** order (spike schema); ROS geometry_msgs delivers
    **xyzw**. The conversion lives HERE, in exactly one place (`add_frame`), mirroring how
    `stitch_ndvi._pose_from_line` owns the reverse conversion.
  * CLOCK DOMAINS + PAIRING: camera stamps are Gazebo sim time; `/ap/pose/filtered` stamps are
    ArduPilot's own clock (SITL runs `use_sim_time=false` -- its DDS log literally says "Skipping
    subscription to /clock"). The first recorder version therefore paired each frame with the pose
    at ARRIVAL -- which the 2026-08-18 real flight proved wrong: the software render STALLS AND
    BURSTS (instantaneous RTF 0.0016..0.48), so a burst delivers frames rendered sim-seconds apart
    within wall-milliseconds, and arrival-pairing stamped canopy frames with poses meters
    down-track (0/18 trees showed in the first heatmap; the canopy blobs sat over empty soil).
    The fix is `PoseBuffer`: the node streams Gazebo's own clock natively (a `gz topic` subprocess — NOT
    bridged: at ~350 msgs/s the bridged clock starved the image pipeline), TAGS every
    arriving pose with gz-now, and each frame selects the pose whose gz tag is nearest the frame's
    own gz stamp -- one clock domain, burst-proof. Per-frame `pose_pair_residual_s` (tag minus
    stamp) and `frame_age_sim_s` (gz-now at arrival minus stamp) are recorded so mislabeling is
    MEASURABLE, and `pose_pair_stale` flags any frame whose best residual exceeds the bound --
    `stitch_ndvi.py` skips flagged frames rather than painting them somewhere plausible-but-wrong.

The rclpy wiring lives in `record_node.py` (same thin-adapter split as ndvi_node/avoidance_node).
Dependency: numpy (same scoped exception as the other ndvi_* modules); PNG writing is INJECTED as
a callable (the node passes sim/spike's stdlib `write_png`; tests pass a stub) so this module adds
no new dependency edge.
"""
from __future__ import annotations

import json
import math
from collections import deque
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np

from .dds_env import dds_env_snapshot
from .ndvi_fusion import FUSER_STATS_PATH, read_fuser_stats

Vec3 = Tuple[float, float, float]
QuatXYZW = Tuple[float, float, float, float]

# 1.2 adds meta["fuser"] -- the fusion node's own counters, so a clip records WHERE the pipeline
# starved and not just how little arrived (ADR-013 amendment 5). Additive: every 1.1 key is
# unchanged, and no consumer reads this field yet.
# 1.3 (2026-08-21) adds meta["recorder"] -- the RECORDER's own counters, which have never existed:
# every frame that died between `/fg/ndvi/image` being published and a row landing in poses.jsonl
# was a single unattributed black box (ADR-013 am. 6a names this as "the next counter to add, not
# the next lever"). Also meta["airborne"], so the round's target metric -- painting cadence over the
# window the vehicle was actually flying -- stops having to be re-derived by hand from poses.jsonl.
# Additive: every 1.2 key is unchanged.
# 1.4 (2026-08-22) adds meta["dds"] -- the transport stack this clip was actually recorded on
# (see dds_env.py). Round 3 traced the large-sample loss to Fast DDS SHM segment exhaustion, whose
# fix is an XML profile whose FAILURE mode is silent (malformed XML falls back to defaults with only
# a log line). Without this block a lever flight that reads 20 % delivery is unattributable between
# "the lever did nothing" and "the lever never loaded". Additive: every 1.3 key is unchanged.
SCHEMA_VERSION = "1.4"

# Altitude above which a recorded frame is counted AIRBORNE. This is a DESCRIPTIVE threshold, not a
# recording gate: nothing here skips a frame (that is a separate, deliberately-deferred decision --
# it would change what `TF_MIN_FRAMES` means and restate published ADR-003 denominators). 1.0 m
# separates the 2026-08-21 demo take perfectly -- 53 airborne / 401 parked at (0,0,-0.0), zero
# straddlers -- and sits well under the lowest frame that ever painted a cell there (z = 2.87 m).
AIRBORNE_Z_M = 1.0

# A frame whose best pose-pair residual exceeds this (in SIM seconds) is recorded but flagged
# pose_pair_stale -- at ~3 m/s sim ground speed, 0.35 s is ~1 m of georef error, under half a cell.
STALE_PAIR_BOUND_S = 0.35


class StreamingClockParser:
    """Incremental parser for `gz topic -e -t /clock` text output. Feed it lines; it returns the
    sim time (seconds) each time a `sim { sec: N nsec: M }` block completes, else None.

    Why a subprocess text stream and not a bridged ROS topic: Gazebo publishes /clock at ~350
    msgs/s, and routing that through ros_gz_bridge starved the image serialization on the
    CPU-saturated stack (measured live 2026-08-18: the fused frame rate collapsed ~8x with the
    clock bridged, recovering when removed). Native gz-transport via the CLI costs the bridge
    nothing and the recorder a line parse."""

    def __init__(self):
        self._in_sim = False
        self._sec: Optional[int] = None
        self._nsec: int = 0

    def feed(self, line: str) -> Optional[float]:
        s = line.strip()
        if s.startswith("sim {"):
            self._in_sim, self._sec, self._nsec = True, None, 0
            return None
        if not self._in_sim:
            return None
        if s.startswith("sec:"):
            self._sec = int(s.split(":", 1)[1])
            return None
        if s.startswith("nsec:"):
            self._nsec = int(s.split(":", 1)[1])
            return None
        if s.startswith("}"):
            self._in_sim = False
            if self._sec is None:
                return None
            return self._sec + self._nsec * 1e-9
        return None


class PoseBuffer:
    """Ring buffer of poses tagged with GAZEBO-clock arrival times. `nearest(stamp)` returns the
    pose whose gz tag is closest to a frame's gz stamp -- pairing in ONE clock domain, immune to
    render bursts (see module docstring). Pure and unit-tested; the node feeds it."""

    def __init__(self, maxlen: int = 4000):
        self._buf: list = []  # (gz_tag_s, pos, quat_xyzw) -- appended in arrival order
        self._maxlen = maxlen

    def tag(self, gz_now_s: float, pos: Vec3, quat_xyzw: QuatXYZW) -> None:
        self._buf.append((gz_now_s, tuple(pos), tuple(quat_xyzw)))
        if len(self._buf) > self._maxlen:
            del self._buf[: len(self._buf) - self._maxlen]

    def __len__(self) -> int:
        return len(self._buf)

    def nearest(self, stamp_s: float):
        """(pos, quat_xyzw, residual_s) for the buffered pose gz-tagged closest to `stamp_s`,
        or None if the buffer is empty. residual = tag - stamp (signed; positive = pose is from
        after the frame)."""
        if not self._buf:
            return None
        tag, pos, quat = min(self._buf, key=lambda e: abs(e[0] - stamp_s))
        return pos, quat, tag - stamp_s


def nearest_rank_p95(samples) -> Optional[float]:
    """p95 by NEAREST RANK (the value at ceil(0.95*n) in sorted order), or None for no samples.

    Nearest rank, not interpolation, on purpose: with the handful of samples a short flight
    produces, an interpolated percentile invents a number that no callback ever took. None (not
    0.0) for an empty sample -- "the callback never ran" and "the callback always returned
    instantly" are opposite diagnoses."""
    vals = sorted(float(s) for s in samples)
    if not vals:
        return None
    return vals[min(len(vals) - 1, max(0, math.ceil(0.95 * len(vals)) - 1))]


class RecorderCounters:
    """The recorder's own frame accounting -- the stage that had NO counter at all until 2026-08-21.

    `meta.json` used to record exactly one recorder-side number, `num_frames`, so the gap between
    the fuser's `fused_count` and the clip's row count was a single black box covering at least
    four different mechanisms. These split it:

        fused_count - ndvi_msgs_received     frames that died in TRANSPORT (never reached a callback)
        ndvi_msgs_received - num_frames      frames the callback itself dropped, of which
          dropped_no_writer                    ...arrived before the first camera_info (silent until now)
          dropped_no_pose                      ...arrived before any /ap/pose/filtered (counted since
                                               the beginning, never once persisted)
        on_ndvi_wall_ms p95 vs the 200 ms tick   whether the executor was BLOCKED when frames died

    `rgb_msgs_received` is the same topic `ndvi_node` counts as `red_frames`, read by a second,
    independent subscriber in a different process -- so one flight prices what being the second
    reader on the starving band actually costs, at zero config change.

    Pure: the node only increments. Every value crosses the JSON boundary as a plain Python
    int/float (a numpy scalar there raises TypeError and has already been shown to be able to take
    a node down mid-flight)."""

    # ~6 hours of frames at the best rate this stack has ever recorded. The percentile is over the
    # most recent `wall_ms_window` samples; `on_ndvi_wall_ms_n` reports the TOTAL observed so a
    # truncated window is visible rather than implied.
    DEFAULT_WALL_MS_WINDOW = 20000

    def __init__(self, wall_ms_window: int = DEFAULT_WALL_MS_WINDOW):
        self.ndvi_msgs_received = 0
        self.rgb_msgs_received = 0
        self.dropped_no_writer = 0
        self.dropped_no_pose = 0
        self._wall_ms: deque = deque(maxlen=int(wall_ms_window))
        self._wall_ms_window = int(wall_ms_window)
        self._wall_ms_n = 0
        self._wall_ms_max: Optional[float] = None

    def observe_on_ndvi_wall_ms(self, ms: float) -> None:
        """One `_on_ndvi` body, wall-clock. Recorded for EVERY invocation including the early
        returns -- a callback that returns in 0.01 ms is as much evidence as one that blocks for
        180 ms."""
        v = float(ms)
        self._wall_ms.append(v)
        self._wall_ms_n += 1
        if self._wall_ms_max is None or v > self._wall_ms_max:
            self._wall_ms_max = v

    def to_meta(self) -> dict:
        p95 = nearest_rank_p95(self._wall_ms)
        return {
            "present": True,
            "ndvi_msgs_received": int(self.ndvi_msgs_received),
            "rgb_msgs_received": int(self.rgb_msgs_received),
            "dropped_no_writer": int(self.dropped_no_writer),
            "dropped_no_pose": int(self.dropped_no_pose),
            "on_ndvi_wall_ms_p95": (None if p95 is None else round(p95, 3)),
            "on_ndvi_wall_ms_max": (None if self._wall_ms_max is None
                                    else round(float(self._wall_ms_max), 3)),
            "on_ndvi_wall_ms_n": int(self._wall_ms_n),
            "on_ndvi_wall_ms_window": int(self._wall_ms_window),
            "note": ("ndvi_msgs_received counts every /fg/ndvi/image message this process's "
                     "callback was handed, BEFORE any guard; fused_count minus it is the transport "
                     "loss on that hop. wall_ms times the whole _on_ndvi body including the "
                     "synchronous .npy/.jsonl writes; null means no sample, never zero."),
        }


class ClipWriter:
    """Accumulates live frames into a spike-schema clip directory. Use: construct, `add_frame` per
    fused NDVI frame, `finalize()` once -> meta.json + summary dict."""

    def __init__(self, out_dir: Path, camera_info: dict,
                 mount_offset_body_m: Vec3 = (0.0, 0.0, -0.08),
                 png_writer: Optional[Callable] = None,
                 fuser_stats_path: Path = FUSER_STATS_PATH):
        """`camera_info`: {image_width_px, image_height_px, fx, fy, cx, cy} -- from the LIVE
        /fg/sensor/rgb/camera_info (closes ADR-007 follow-up 5: intrinsics confirmed empirically,
        not assumed from config). `png_writer(path, uint8_array)` or None to skip RGB frames.
        `fuser_stats_path`: the ndvi_node counters sidecar, read once at finalize (parameterised so
        tests never touch the live one)."""
        self.out_dir = Path(out_dir)
        self.fuser_stats_path = Path(fuser_stats_path)
        self.camera_info = dict(camera_info)
        self.mount_offset_body_m = tuple(mount_offset_body_m)
        self.png_writer = png_writer
        (self.out_dir / "frames" / "ndvi").mkdir(parents=True, exist_ok=True)
        if png_writer is not None:
            (self.out_dir / "frames" / "rgb").mkdir(parents=True, exist_ok=True)
        if png_writer is not None:
            (self.out_dir / "frames" / "rgb_raw").mkdir(parents=True, exist_ok=True)
        self._poses_fh = (self.out_dir / "poses.jsonl").open("w")
        self.n_frames = 0
        self.n_rgb = 0
        self.n_stale = 0
        self.n_airborne = 0
        self._first_airborne_stamp_s: Optional[float] = None
        self._last_airborne_stamp_s: Optional[float] = None
        self._t0_stamp_s: Optional[float] = None
        # Captured HERE, at recorder construction, and not at finalize: by the time this node starts
        # the whole stack is already up (bridge, fuser and agent all precede it in fly_pipeline.sh),
        # so every participant's SHM segment already exists and `min_bytes` can see a process that
        # missed the profile. At finalize the other panes may already be torn down.
        self.dds = dds_env_snapshot()
        self.origin: Optional[dict] = None  # /ap/gps_global_origin/filtered, set once by the node
        self.pairing_mode = "gz_clock_stamp"  # node overrides to 'arrival_fallback' if no clock stream

    def add_frame(self, stamp_s: float, ndvi: np.ndarray,
                  drone_pos_enu: Vec3, drone_quat_xyzw: QuatXYZW,
                  pose_pair_residual_s: float,
                  frame_age_sim_s: Optional[float] = None,
                  rgb: Optional[np.ndarray] = None) -> str:
        """One fused NDVI frame + its stamp-paired pose. `stamp_s` is the frame's own (gz sim)
        stamp; t_s in poses.jsonl is made relative to the first frame, spike-style. A residual
        beyond STALE_PAIR_BOUND_S flags the line pose_pair_stale (stitch skips it). Returns
        ndvi_path."""
        if self._t0_stamp_s is None:
            self._t0_stamp_s = stamp_s
        if abs(float(drone_pos_enu[2])) > AIRBORNE_Z_M:
            self.n_airborne += 1
            if self._first_airborne_stamp_s is None:
                self._first_airborne_stamp_s = stamp_s
            self._last_airborne_stamp_s = stamp_s
        fid = self.n_frames
        ndvi_rel = f"frames/ndvi/frame_{fid:06d}.npy"
        np.save(self.out_dir / ndvi_rel, np.asarray(ndvi, dtype=np.float32))

        line = {
            "frame_id": fid,
            "t_s": round(stamp_s - self._t0_stamp_s, 6),
            "drone": {
                "pos_m": [round(float(v), 6) for v in drone_pos_enu],
                # xyzw (ROS) -> wxyz (spike schema); the ONE conversion point.
                "quat_wxyz": [round(float(drone_quat_xyzw[3]), 9),
                              round(float(drone_quat_xyzw[0]), 9),
                              round(float(drone_quat_xyzw[1]), 9),
                              round(float(drone_quat_xyzw[2]), 9)],
            },
            "ndvi_path": ndvi_rel,
            # honesty extras (consumers ignore unknown keys; humans/QA read them):
            "stamp_sim_s": round(stamp_s, 6),
            # NaN residual = arrival-fallback pairing (no gz clock) -> null in JSON, whole-clip
            # degradation already recorded in meta.pose_pairing.
            "pose_pair_residual_s": (None if pose_pair_residual_s != pose_pair_residual_s
                                     else round(pose_pair_residual_s, 4)),
        }
        if frame_age_sim_s is not None:
            line["frame_age_sim_s"] = round(frame_age_sim_s, 4)
        if pose_pair_residual_s == pose_pair_residual_s and \
                abs(pose_pair_residual_s) > STALE_PAIR_BOUND_S:
            line["pose_pair_stale"] = True
            self.n_stale += 1
        if rgb is not None and self.png_writer is not None:
            # Raw .npy during flight (~ms); PNG conversion happens in finalize() -- per-frame PNG
            # encoding in the callback path is load we don't spend while frames are arriving.
            raw_rel = f"frames/rgb_raw/frame_{fid:06d}.npy"
            np.save(self.out_dir / raw_rel, np.asarray(rgb, dtype=np.uint8))
            line["rgb_path"] = f"frames/rgb/frame_{fid:06d}.png"  # the finalize()-produced path
            self.n_rgb += 1
        self._poses_fh.write(json.dumps(line) + "\n")
        self._poses_fh.flush()  # a crash mid-flight must not lose the recorded prefix
        self.n_frames += 1
        return ndvi_rel

    def airborne_summary(self) -> dict:
        """The recorded frames that were taken while the vehicle was FLYING, and their cadence.

        Why this belongs in the artifact: on the 2026-08-21 demo take only 53 of 454 recorded
        frames were airborne and only 51 painted a cell, so "454 frames" reads five times better
        than the map it produced. The cadence quoted against the ADR-015 predictor is this one --
        (n-1) / (last - first), which reproduces that take's published 0.407 Hz from 53 frames over
        127.8 s. `None`, never 0.0, when there is nothing to divide: a cadence with no denominator
        is EVIDENCE INSUFFICIENT, not a slow flight."""
        n = int(self.n_airborne)
        first, last = self._first_airborne_stamp_s, self._last_airborne_stamp_s
        span = None if (first is None or last is None) else round(float(last - first), 3)
        cadence = None if (n < 2 or not span) else round((n - 1) / span, 4)
        return {"z_threshold_m": float(AIRBORNE_Z_M),
                "frames": n,
                "frames_total": int(self.n_frames),
                "first_stamp_sim_s": (None if first is None else round(float(first), 6)),
                "last_stamp_sim_s": (None if last is None else round(float(last), 6)),
                "span_s": span,
                "cadence_hz": cadence,
                "note": ("cadence_hz = (frames-1)/span_s over the airborne window only -- the basis "
                         "the ADR-015 predictor's --fps expects. It is frame OPPORTUNITY along the "
                         "lanes, not painting yield: the frames that PAINTED a cell are counted by "
                         "scripts/stitch_ndvi.py into heatmap.json (frames_painting), because "
                         "whether a frame paints depends on the projection, which is an offline "
                         "post-flight question (ADR-010).")}

    def finalize(self, recorder_counters: Optional[dict] = None) -> dict:
        """`recorder_counters`: `RecorderCounters.to_meta()` from the node. Omitted (None) means
        nobody supplied them -- recorded as `present: false` with a reason, never as zeros, for the
        same reason the fuser block is (a fabricated `ndvi_msgs_received: 0` is indistinguishable
        from a recorder whose subscription never fired)."""
        self._poses_fh.close()
        # Convert the raw in-flight RGB dumps to schema PNGs now that no frames are arriving.
        raw_dir = self.out_dir / "frames" / "rgb_raw"
        if self.png_writer is not None and raw_dir.exists():
            for raw in sorted(raw_dir.glob("frame_*.npy")):
                self.png_writer(self.out_dir / "frames" / "rgb" / (raw.stem + ".png"), np.load(raw))
                raw.unlink()
            raw_dir.rmdir()
        # The fusion node's own counters, read from its side-channel at the one moment they are
        # final. `num_frames` alone can only say the clip is thin; this says which stage thinned it
        # (bands in vs pairs fused vs frames recorded), and `stats_stale` says whether the fuser was
        # still alive when the recorder stopped. Absent/unreadable -> an explicit present:false with
        # a reason, never zeros.
        fuser = read_fuser_stats(self.fuser_stats_path)
        meta = {
            "schema_version": SCHEMA_VERSION,
            "synthetic": False,
            "pending_gazebo_replacement": False,
            "generator": "src/fieldguard_planning/record_node.py (live real-render recorder)",
            "seed": None,
            "num_frames": self.n_frames,
            "num_rgb_frames": self.n_rgb,
            "num_stale_pose_pairs": self.n_stale,
            "pose_pairing": self.pairing_mode,
            "stale_pair_bound_s": STALE_PAIR_BOUND_S,
            "image_width_px": self.camera_info["image_width_px"],
            "image_height_px": self.camera_info["image_height_px"],
            "coordinate_frame": "world ENU meters (x=East, y=North, z=Up), REP-103 convention",
            "camera": self.camera_info,
            "camera_extrinsic": {
                "mount": "rigid nadir (ADR-007 fg_sensor_mount), fixed for entire clip",
                "offset_from_drone_m": list(self.mount_offset_body_m),
            },
            "gps_global_origin": self.origin,
            "fuser": fuser,
            "recorder": (recorder_counters if recorder_counters is not None else
                         {"present": False,
                          "reason": ("no recorder counters supplied to finalize() -- this clip was "
                                     "written by a caller that does not track them (pre-1.3 "
                                     "record_node, or a test harness)")}),
            "airborne": self.airborne_summary(),
            "dds": self.dds,
            "clock_note": ("camera stamps are Gazebo sim time; /ap/pose/filtered stamps are "
                           "ArduPilot's clock (use_sim_time=false) -- poses gz-tagged via a "
                           "native gz clock stream and paired to each frame's stamp; residual in "
                           "poses.jsonl pose_pair_residual_s, stale pairs flagged pose_pair_stale"),
            "ndvi_dtype": "float32, numpy.save (.npy), values in [-1, 1]",
        }
        (self.out_dir / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
        return {"out_dir": str(self.out_dir), "n_frames": self.n_frames, "n_rgb": self.n_rgb,
                "n_airborne": self.n_airborne,
                # The number the round is actually trying to move, printed where a human sees it
                # rather than derived from poses.jsonl three days later.
                "airborne_cadence_hz": meta["airborne"]["cadence_hz"],
                # Printed by record_node at Ctrl-C -- the one moment a human is watching, and the
                # cheapest place to learn the fuser died an hour ago.
                "fuser": (f"fused_count={fuser.get('fused_count')} "
                          f"({fuser['stats_age_s']}s old"
                          f"{', STALE' if fuser['stats_stale'] else ''})"
                          if fuser["present"] else fuser["reason"])}
