"""Spike-schema clip writer -- the pure, unit-testable core of the real-render recorder.

Writes the EXACT directory layout `sim/spike/README.md` defines and `scripts/stitch_ndvi.py` +
`eval/run_spike.sh` consume, from live-flight data instead of the synthetic generator:

    <out>/meta.json          synthetic: false (the real thing at last), live camera intrinsics
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
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np

Vec3 = Tuple[float, float, float]
QuatXYZW = Tuple[float, float, float, float]

SCHEMA_VERSION = "1.1"

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


class ClipWriter:
    """Accumulates live frames into a spike-schema clip directory. Use: construct, `add_frame` per
    fused NDVI frame, `finalize()` once -> meta.json + summary dict."""

    def __init__(self, out_dir: Path, camera_info: dict,
                 mount_offset_body_m: Vec3 = (0.0, 0.0, -0.08),
                 png_writer: Optional[Callable] = None):
        """`camera_info`: {image_width_px, image_height_px, fx, fy, cx, cy} -- from the LIVE
        /fg/sensor/rgb/camera_info (closes ADR-007 follow-up 5: intrinsics confirmed empirically,
        not assumed from config). `png_writer(path, uint8_array)` or None to skip RGB frames."""
        self.out_dir = Path(out_dir)
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
        self._t0_stamp_s: Optional[float] = None
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

    def finalize(self) -> dict:
        self._poses_fh.close()
        # Convert the raw in-flight RGB dumps to schema PNGs now that no frames are arriving.
        raw_dir = self.out_dir / "frames" / "rgb_raw"
        if self.png_writer is not None and raw_dir.exists():
            for raw in sorted(raw_dir.glob("frame_*.npy")):
                self.png_writer(self.out_dir / "frames" / "rgb" / (raw.stem + ".png"), np.load(raw))
                raw.unlink()
            raw_dir.rmdir()
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
            "clock_note": ("camera stamps are Gazebo sim time; /ap/pose/filtered stamps are "
                           "ArduPilot's clock (use_sim_time=false) -- poses gz-tagged via a "
                           "native gz clock stream and paired to each frame's stamp; residual in "
                           "poses.jsonl pose_pair_residual_s, stale pairs flagged pose_pair_stale"),
            "ndvi_dtype": "float32, numpy.save (.npy), values in [-1, 1]",
        }
        (self.out_dir / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
        return {"out_dir": str(self.out_dir), "n_frames": self.n_frames, "n_rgb": self.n_rgb}
