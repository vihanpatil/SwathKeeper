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
  * CLOCK DOMAINS (the honesty extras): camera stamps are Gazebo sim time; `/ap/pose/filtered`
    stamps are ArduPilot's own clock (SITL runs `use_sim_time=false` -- its DDS log literally says
    "Skipping subscription to /clock"). The two cannot be compared, so the recorder pairs each
    frame with the LATEST pose by ARRIVAL and records `pose_age_wall_s` (wall seconds between pose
    arrival and frame arrival) per frame -- at ~3 m/s sim ground speed and the measured RTF~0.17,
    a 0.2 s-wall-stale pose is ~0.1 m of georef error: acceptable for 2.5 m cells, and QUANTIFIED
    in the artifact rather than hidden. `meta.json` carries the same caveat for future readers.

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

SCHEMA_VERSION = "1.0"


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
        self._poses_fh = (self.out_dir / "poses.jsonl").open("w")
        self.n_frames = 0
        self.n_rgb = 0
        self._t0_stamp_s: Optional[float] = None
        self.origin: Optional[dict] = None  # /ap/gps_global_origin/filtered, set once by the node

    def add_frame(self, stamp_s: float, ndvi: np.ndarray,
                  drone_pos_enu: Vec3, drone_quat_xyzw: QuatXYZW,
                  pose_age_wall_s: float,
                  rgb: Optional[np.ndarray] = None) -> str:
        """One fused NDVI frame + the latest pose. `stamp_s` is the frame's own (gz sim) stamp;
        t_s in poses.jsonl is made relative to the first frame, spike-style. Returns ndvi_path."""
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
            "pose_age_wall_s": round(pose_age_wall_s, 4),
        }
        if rgb is not None and self.png_writer is not None:
            rgb_rel = f"frames/rgb/frame_{fid:06d}.png"
            self.png_writer(self.out_dir / rgb_rel, np.asarray(rgb, dtype=np.uint8))
            line["rgb_path"] = rgb_rel
            self.n_rgb += 1
        self._poses_fh.write(json.dumps(line) + "\n")
        self._poses_fh.flush()  # a crash mid-flight must not lose the recorded prefix
        self.n_frames += 1
        return ndvi_rel

    def finalize(self) -> dict:
        self._poses_fh.close()
        meta = {
            "schema_version": SCHEMA_VERSION,
            "synthetic": False,
            "pending_gazebo_replacement": False,
            "generator": "src/fieldguard_planning/record_node.py (live real-render recorder)",
            "seed": None,
            "num_frames": self.n_frames,
            "num_rgb_frames": self.n_rgb,
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
                           "ArduPilot's clock (use_sim_time=false) -- poses paired by ARRIVAL, "
                           "per-frame staleness in poses.jsonl pose_age_wall_s"),
            "ndvi_dtype": "float32, numpy.save (.npy), values in [-1, 1]",
        }
        (self.out_dir / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
        return {"out_dir": str(self.out_dir), "n_frames": self.n_frames, "n_rgb": self.n_rgb}
