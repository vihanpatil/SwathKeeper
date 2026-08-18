#!/usr/bin/env python3
"""Generate a fixed-seed synthetic NDVI+RGB spike clip for ADR-003 (docs/SPIKE_ndvi_vs_rgb.md).

*** SYNTHETIC STAND-IN -- NOT A GAZEBO RENDER. ***
The real Gazebo + ArduPilot + ROS 2 stack only runs inside the human-operated Docker/Ubuntu
container (see docs/runbooks/SIM_BRINGUP.md), which is not available in this environment. This script
produces a reproducible, code-generated clip that emits data in the EXACT file/schema shape the
future Gazebo NDVI-camera render will emit, so `eval/label_from_sim.py` and the classical-CV
baselines can be built and tested against it now. When the real render lands, it must write the
same directory layout described in sim/spike/README.md so it's a drop-in replacement -- swap the
input directory, nothing downstream should need to change. Every output file/field that is
synthetic-only is called out in README "Assumptions the future Gazebo render must honor".

Coordinate frame: world is ENU (x=East, y=North, z=Up), meters, matching REP-103 / what the AP_DDS
ROS 2 bridge publishes -- NOT ArduPilot's internal NED. Camera is a fixed nadir mount (no gimbal),
constant heading (east) for the whole clip -- see README "Camera model" for the exact convention.

Usage:
    python3 sim/spike/gen_spike_clip.py
    python3 sim/spike/gen_spike_clip.py --seed 42 --out sim/spike/out/spike_seed42
    python3 sim/spike/gen_spike_clip.py --scenario sim/spike/scenario_default.json --no-previews

Dependencies: numpy only (stdlib zlib/struct used for a minimal PNG writer -- no imageio/opencv
required, so the eval harness stays headless-friendly per the workstream constraint).
"""
import argparse
import json
import math
import struct
import zlib
from pathlib import Path

import numpy as np

SCHEMA_VERSION = "1.0"
DEFAULT_SCENARIO = Path(__file__).parent / "scenario_default.json"

# Fixed camera extrinsic (nadir mount, no gimbal, constant drone heading for the whole clip):
# camera X (image right, u+)  = world +X (East)
# camera Y (image down,  v+)  = world -Y (South)
# camera Z (optical/depth)    = world -Z (Down)
# This is a proper right-handed rotation (180 deg about the world X axis) -> quaternion (w,x,y,z)
# = (0, 1, 0, 0). See README "Camera model" for the derivation.
CAMERA_QUAT_WXYZ = (0.0, 1.0, 0.0, 0.0)
DRONE_QUAT_WXYZ = (1.0, 0.0, 0.0, 0.0)  # constant heading east, math yaw=0 about world Z


# --------------------------------------------------------------------------------------
# Minimal stdlib PNG writer (uint8 grayscale or RGB, no interlace) -- avoids an imageio/
# opencv dependency so this stays runnable in a bare numpy environment.
# --------------------------------------------------------------------------------------
def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def write_png(path: Path, arr: np.ndarray) -> None:
    """arr: uint8, shape (H,W) for grayscale or (H,W,3) for RGB."""
    if arr.dtype != np.uint8:
        raise ValueError(f"write_png expects uint8, got {arr.dtype}")
    if arr.ndim == 2:
        h, w = arr.shape
        color_type, channels = 0, 1
    elif arr.ndim == 3 and arr.shape[2] == 3:
        h, w, _ = arr.shape
        color_type, channels = 2, 3
    else:
        raise ValueError(f"unsupported array shape for PNG: {arr.shape}")

    raw = bytearray()
    row_bytes = w * channels
    for row in range(h):
        raw.append(0)  # filter type: None
        raw.extend(arr[row].tobytes())
    compressed = zlib.compress(bytes(raw), 6)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0)
    sig = b"\x89PNG\r\n\x1a\n"
    data = (sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", compressed)
            + _png_chunk(b"IEND", b""))
    path.write_bytes(data)


def ndvi_to_preview_rgb(ndvi: np.ndarray) -> np.ndarray:
    """Hand-rolled 3-stop colormap for human eyeballing only -- NOT authoritative data.
    -1 -> red, 0 -> yellow, +1 -> green (rough RdYlGn analog, no matplotlib dependency)."""
    v = np.clip(ndvi, -1.0, 1.0)
    red = np.array([200, 30, 30], dtype=np.float32)
    yellow = np.array([230, 210, 40], dtype=np.float32)
    green = np.array([20, 140, 40], dtype=np.float32)
    low_mix = np.clip((v + 1.0), 0.0, 1.0)[..., None]      # 0 at v=-1, 1 at v=0
    high_mix = np.clip(v, 0.0, 1.0)[..., None]              # 0 at v=0,  1 at v=+1
    lower_half = red * (1 - low_mix) + yellow * low_mix
    out = lower_half * (1 - high_mix) + green * high_mix
    return np.clip(out, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------------------
# Scenario loading
# --------------------------------------------------------------------------------------
def load_scenario(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


# --------------------------------------------------------------------------------------
# Field texture (ground truth NDVI/RGB map in WORLD coordinates, independent of camera)
# --------------------------------------------------------------------------------------
def build_field_texture(scenario: dict, rng: np.random.Generator):
    field = scenario["field"]
    bg = scenario["ndvi_background"]
    gsd = field["gsd_m_per_px"]
    w_m, h_m = field["width_m"], field["height_m"]
    w_px = int(round(w_m / gsd))
    h_px = int(round(h_m / gsd))

    ndvi = (bg["canopy_base"] + rng.normal(0.0, bg["canopy_noise_std"], size=(h_px, w_px))
            ).astype(np.float32)
    ndvi = np.clip(ndvi, -1.0, 1.0)

    # Simple ndvi-correlated greenness for the RGB base render (not physically calibrated --
    # this is a synthetic stand-in, see README).
    norm = np.clip((ndvi + 1.0) / 2.0, 0.0, 1.0)
    rgb = np.stack([
        (50 + 30 * (1 - norm)),
        (60 + 150 * norm),
        (40 + 15 * (1 - norm)),
    ], axis=-1).astype(np.float32)
    rgb += rng.normal(0.0, 4.0, size=rgb.shape).astype(np.float32)

    # World coordinate of each texel: col -> X (east), row -> Y (north).
    xs = (np.arange(w_px) + 0.5) * gsd
    ys = (np.arange(h_px) + 0.5) * gsd
    grid_x, grid_y = np.meshgrid(xs, ys)  # shape (h_px, w_px)

    feather = bg.get("feather_m", 0.4)

    def blend_circular_patch(cx, cy, r, ndvi_target=None, ndvi_delta=None, rgb_target=None,
                              rgb_delta=None):
        dist = np.sqrt((grid_x - cx) ** 2 + (grid_y - cy) ** 2)
        alpha = np.clip((r - dist) / max(feather, 1e-6), 0.0, 1.0)[..., None]
        nonlocal ndvi, rgb
        if ndvi_target is not None:
            ndvi = ndvi * (1 - alpha[..., 0]) + ndvi_target * alpha[..., 0]
        elif ndvi_delta is not None:
            ndvi = ndvi + ndvi_delta * alpha[..., 0]
        if rgb_target is not None:
            rgb = rgb * (1 - alpha) + np.array(rgb_target, dtype=np.float32) * alpha
        elif rgb_delta is not None:
            rgb = rgb + np.array(rgb_delta, dtype=np.float32) * alpha

    for p in bg.get("soil_patches", []):
        blend_circular_patch(p["cx_m"], p["cy_m"], p["r_m"], ndvi_target=p["ndvi"],
                              rgb_target=p["rgb"])
    for p in bg.get("shadow_patches", []):
        blend_circular_patch(p["cx_m"], p["cy_m"], p["r_m"], ndvi_delta=p["ndvi_delta"],
                              rgb_delta=p.get("rgb_delta"))
    for p in bg.get("clutter_blobs", []):
        blend_circular_patch(p["cx_m"], p["cy_m"], p["r_m"], ndvi_target=p["ndvi"],
                              rgb_target=p["rgb"])

    ndvi = np.clip(ndvi, -1.0, 1.0).astype(np.float32)
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    return ndvi, rgb, gsd


def sample_field(field_ndvi, field_rgb, gsd, world_x, world_y):
    """Nearest-neighbor sample of the world-space field texture at arbitrary (world_x, world_y)
    arrays (same shape as the output image). Out-of-bounds samples clamp to the field edge."""
    h_px, w_px = field_ndvi.shape
    col = np.clip((world_x / gsd).astype(np.int32), 0, w_px - 1)
    row = np.clip((world_y / gsd).astype(np.int32), 0, h_px - 1)
    return field_ndvi[row, col], field_rgb[row, col]


# --------------------------------------------------------------------------------------
# Camera model (pinhole, fixed nadir extrinsic -- see module docstring for the convention)
# --------------------------------------------------------------------------------------
def world_to_camera(rel_x, rel_y, rel_z):
    """rel_* = world point minus camera world position. Returns (Xc, Yc, Zc)."""
    return rel_x, -rel_y, -rel_z


def camera_to_pixel(xc, yc, zc, fx, fy, cx, cy):
    u = fx * xc / zc + cx
    v = fy * yc / zc + cy
    return u, v


def pixel_grid_world_ground(cam_x, cam_y, cam_z, fx, fy, cx, cy, width_px, height_px):
    """For every output pixel, the world (X,Y) ground point (Z=0) it looks at, given the fixed
    nadir camera model. Vectorized -- used to sample the field texture per frame."""
    us = np.arange(width_px) + 0.5
    vs = np.arange(height_px) + 0.5
    grid_u, grid_v = np.meshgrid(us, vs)  # shape (height_px, width_px)
    xc = (grid_u - cx) / fx * cam_z
    yc = (grid_v - cy) / fy * cam_z
    world_x = cam_x + xc
    world_y = cam_y - yc
    return world_x, world_y


# --------------------------------------------------------------------------------------
# Bird trajectory (piecewise-linear between scripted waypoints)
# --------------------------------------------------------------------------------------
def bird_position_at(bird_cfg, t):
    """Returns (x,y,z) or None if t is outside the bird's scripted waypoint window (bird has not
    yet appeared / has already left the clip -- scripted actors are not present the whole clip)."""
    wps = bird_cfg["waypoints"]
    t0, tN = wps[0]["t_s"], wps[-1]["t_s"]
    if t < t0 or t > tN:
        return None
    for i in range(len(wps) - 1):
        a, b = wps[i], wps[i + 1]
        if a["t_s"] <= t <= b["t_s"]:
            span = max(b["t_s"] - a["t_s"], 1e-9)
            frac = (t - a["t_s"]) / span
            x = a["x_m"] + frac * (b["x_m"] - a["x_m"])
            y = a["y_m"] + frac * (b["y_m"] - a["y_m"])
            z = a["z_m"] + frac * (b["z_m"] - a["z_m"])
            return x, y, z
    return None


def composite_blob(ndvi_frame, rgb_frame, u, v, r_px, ndvi_value, rgb_color, width_px, height_px):
    """Soft-edged circular blob compositing, restricted to the blob's bounding box for speed."""
    r_draw = max(r_px * 1.2, 1.0)
    x0 = max(int(math.floor(u - r_draw - 1)), 0)
    x1 = min(int(math.ceil(u + r_draw + 1)), width_px)
    y0 = max(int(math.floor(v - r_draw - 1)), 0)
    y1 = min(int(math.ceil(v + r_draw + 1)), height_px)
    if x1 <= x0 or y1 <= y0:
        return
    xs = np.arange(x0, x1) + 0.5
    ys = np.arange(y0, y1) + 0.5
    gx, gy = np.meshgrid(xs, ys)
    dist = np.sqrt((gx - u) ** 2 + (gy - v) ** 2)
    alpha = np.clip((r_draw - dist) / max(0.35 * r_draw, 0.5), 0.0, 1.0)

    ndvi_frame[y0:y1, x0:x1] = (ndvi_frame[y0:y1, x0:x1] * (1 - alpha)
                                 + ndvi_value * alpha).astype(np.float32)
    rgb_col = np.array(rgb_color, dtype=np.float32)
    rgb_frame[y0:y1, x0:x1] = np.clip(
        rgb_frame[y0:y1, x0:x1].astype(np.float32) * (1 - alpha[..., None])
        + rgb_col * alpha[..., None], 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------------------
# Main generation loop
# --------------------------------------------------------------------------------------
def generate(scenario: dict, out_dir: Path, width_px: int, height_px: int,
             duration_s: float, fps: float, write_previews: bool, write_npy: bool) -> None:
    seed = scenario["seed"]
    rng = np.random.default_rng(seed)

    cam_cfg = dict(scenario["camera"])
    cam_cfg["image_width_px"] = width_px
    cam_cfg["image_height_px"] = height_px
    fx, fy, cx, cy = cam_cfg["fx"], cam_cfg["fy"], cam_cfg["cx"], cam_cfg["cy"]

    flight = scenario["flight"]
    alt = flight["altitude_m"]
    start_x, start_y = flight["start_xy_m"]
    speed = flight["speed_mps"]
    jitter_std = flight.get("pos_jitter_std_m", 0.0)

    field_ndvi, field_rgb, gsd = build_field_texture(scenario, rng)

    num_frames = int(round(duration_s * fps))
    (out_dir / "frames" / "ndvi").mkdir(parents=True, exist_ok=True)
    (out_dir / "frames" / "rgb").mkdir(parents=True, exist_ok=True)
    if write_previews:
        (out_dir / "frames" / "ndvi_preview").mkdir(parents=True, exist_ok=True)

    poses_path = out_dir / "poses.jsonl"
    frames_csv_path = out_dir / "frames.csv"
    poses_lines = []
    csv_lines = ["frame_id,t_s,cam_x_m,cam_y_m,cam_z_m,ndvi_path,rgb_path"]

    for frame_id in range(num_frames):
        t = frame_id / fps

        jitter = rng.normal(0.0, jitter_std, size=3) if jitter_std > 0 else np.zeros(3)
        cam_x = start_x + speed * t + jitter[0]
        cam_y = start_y + jitter[1]
        cam_z = alt + jitter[2]

        world_x, world_y = pixel_grid_world_ground(cam_x, cam_y, cam_z, fx, fy, cx, cy,
                                                     width_px, height_px)
        ndvi_frame, rgb_frame = sample_field(field_ndvi, field_rgb, gsd, world_x, world_y)
        ndvi_frame = ndvi_frame.copy()
        rgb_frame = rgb_frame.copy()

        birds_out = []
        for bird_cfg in scenario["birds"]:
            pos = bird_position_at(bird_cfg, t)
            if pos is None:
                continue  # not spawned / already despawned this frame
            bx, by, bz = pos
            rel = (bx - cam_x, by - cam_y, bz - cam_z)
            xc, yc, zc = world_to_camera(*rel)
            range_m = cam_z - bz  # vertical range from camera to bird (nadir camera, matches Zc)
            entry = {
                "bird_id": bird_cfg["bird_id"],
                "pos_m": [round(bx, 4), round(by, 4), round(bz, 4)],
                "physical_radius_m": bird_cfg["physical_radius_m"],
                "ndvi_value": bird_cfg["ndvi_value"],
                "rgb_color": bird_cfg["rgb_color"],
                "range_m": round(float(range_m), 4),
                "in_frustum_hint": False,
                "generator_bbox_px": None,
            }
            if zc > 0.5:  # in front of / below the downward camera
                u, v = camera_to_pixel(xc, yc, zc, fx, fy, cx, cy)
                r_px = fx * bird_cfg["physical_radius_m"] / zc
                bx0, by0 = u - r_px, v - r_px
                bx1, by1 = u + r_px, v + r_px
                cx0, cy0 = max(0.0, bx0), max(0.0, by0)
                cx1, cy1 = min(float(width_px), bx1), min(float(height_px), by1)
                if cx1 > cx0 and cy1 > cy0:
                    entry["in_frustum_hint"] = True
                    entry["generator_bbox_px"] = [round(cx0, 2), round(cy0, 2),
                                                   round(cx1, 2), round(cy1, 2)]
                    composite_blob(ndvi_frame, rgb_frame, u, v, r_px,
                                    bird_cfg["ndvi_value"], bird_cfg["rgb_color"],
                                    width_px, height_px)
            birds_out.append(entry)

        ndvi_name = f"frame_{frame_id:06d}.npy"
        rgb_name = f"frame_{frame_id:06d}.png"
        if write_npy:
            np.save(out_dir / "frames" / "ndvi" / ndvi_name, ndvi_frame.astype(np.float32))
        write_png(out_dir / "frames" / "rgb" / rgb_name, rgb_frame)
        if write_previews:
            write_png(out_dir / "frames" / "ndvi_preview" / rgb_name,
                      ndvi_to_preview_rgb(ndvi_frame))

        poses_lines.append(json.dumps({
            "frame_id": frame_id,
            "t_s": round(t, 4),
            "drone": {
                "pos_m": [round(cam_x, 4), round(cam_y, 4), round(cam_z, 4)],
                "quat_wxyz": list(DRONE_QUAT_WXYZ),
            },
            "camera": {
                "pos_m": [round(cam_x, 4), round(cam_y, 4), round(cam_z, 4)],
                "quat_wxyz": list(CAMERA_QUAT_WXYZ),
                "note": "rigid nadir mount, zero offset from drone origin in this spike",
            },
            "birds": birds_out,
            "ndvi_path": f"frames/ndvi/{ndvi_name}" if write_npy else None,
            "rgb_path": f"frames/rgb/{rgb_name}",
        }))
        csv_lines.append(f"{frame_id},{t:.4f},{cam_x:.4f},{cam_y:.4f},{cam_z:.4f},"
                          f"frames/ndvi/{ndvi_name},frames/rgb/{rgb_name}")

    poses_path.write_text("\n".join(poses_lines) + "\n")
    frames_csv_path.write_text("\n".join(csv_lines) + "\n")

    meta = {
        "schema_version": SCHEMA_VERSION,
        "synthetic": True,
        "pending_gazebo_replacement": True,
        "generator": "sim/spike/gen_spike_clip.py",
        "seed": seed,
        "duration_s": duration_s,
        "fps": fps,
        "num_frames": num_frames,
        "image_width_px": width_px,
        "image_height_px": height_px,
        "coordinate_frame": "world ENU meters (x=East, y=North, z=Up), REP-103 convention",
        "camera": cam_cfg,
        "camera_extrinsic": {
            "mount": "rigid nadir, no gimbal, fixed for entire clip",
            "convention": "camera X=world East, camera Y=world South (down-image), "
                           "camera Z(depth)=world Down (i.e. pinhole optical convention, "
                           "X right / Y down / Z forward)",
            "quat_wxyz": list(CAMERA_QUAT_WXYZ),
            "offset_from_drone_m": [0.0, 0.0, 0.0],
        },
        "flight": flight,
        "field": scenario["field"],
        "ndvi_dtype": "float32, saved via numpy.save (.npy), values clipped to [-1, 1]",
        "ndvi_preview_note": "frames/ndvi_preview/*.png is a false-color visualization for humans "
                              "only -- NOT authoritative, do not label/eval against it.",
        "bbox_convenience_note": "poses.jsonl birds[].generator_bbox_px is a convenience "
                                  "cross-check computed by this generator, NOT the authoritative "
                                  "ground truth. eval/label_from_sim.py should independently "
                                  "project birds[].pos_m through camera + drone pose to produce "
                                  "ground_truth.json, per docs/SPIKE_ndvi_vs_rgb.md section 3.",
        "occlusion_note": "no static obstacles in this spike (ADR-001 scope: no trees needed) -- "
                           "in_frustum_hint/generator_bbox_px only account for the camera frustum, "
                           "not true 3D occlusion. Out of scope per docs/SPIKE_ndvi_vs_rgb.md.",
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (out_dir / "scenario.json").write_text(json.dumps(scenario, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO,
                     help="scenario JSON (default: sim/spike/scenario_default.json)")
    ap.add_argument("--out", type=Path, default=None,
                     help="output dir (default: sim/spike/out/spike_seed<seed>)")
    ap.add_argument("--seed", type=int, default=None, help="override scenario seed")
    ap.add_argument("--duration", type=float, default=None, help="override duration_s")
    ap.add_argument("--fps", type=float, default=None, help="override fps")
    ap.add_argument("--width", type=int, default=None, help="override image_width_px")
    ap.add_argument("--height", type=int, default=None, help="override image_height_px")
    ap.add_argument("--no-previews", action="store_true",
                     help="skip false-color NDVI preview PNGs (raw .npy is always written)")
    ap.add_argument("--no-npy", action="store_true",
                     help="skip raw float32 NDVI .npy (for a quick RGB-only smoke test)")
    args = ap.parse_args()

    scenario = load_scenario(args.scenario)
    if args.seed is not None:
        scenario["seed"] = args.seed
    duration_s = args.duration if args.duration is not None else scenario["duration_s"]
    fps = args.fps if args.fps is not None else scenario["fps"]
    width_px = args.width if args.width is not None else scenario["camera"]["image_width_px"]
    height_px = args.height if args.height is not None else scenario["camera"]["image_height_px"]

    out_dir = args.out or (Path(__file__).parent / "out" / f"spike_seed{scenario['seed']}")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[gen_spike_clip] SYNTHETIC STAND-IN clip (not a Gazebo render) -- seed={scenario['seed']} "
          f"duration={duration_s}s fps={fps} -> {out_dir}")
    generate(scenario, out_dir, width_px, height_px, duration_s, fps,
              write_previews=not args.no_previews, write_npy=not args.no_npy)
    n = int(round(duration_s * fps))
    print(f"[gen_spike_clip] wrote {n} frames to {out_dir}")


if __name__ == "__main__":
    main()
