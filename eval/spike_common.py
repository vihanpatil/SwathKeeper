#!/usr/bin/env python3
"""Shared helpers for the ADR-003 NDVI-vs-RGB spike harness (docs/SPIKE_ndvi_vs_rgb.md).

Deliberately dependency-light: numpy + scipy only. A stdlib PNG reader/writer lives here so the
harness stays headless (no Pillow/OpenCV/imageio) and so it keeps working against the future real
Gazebo render, whose PNGs may use any of the standard filter types (the synthetic generator only
emits filter-type 0, but we decode all five so a real render is a drop-in).

Coordinate / camera convention is read from meta.json and applied per sim/spike/README.md
"Camera model": world ENU meters; nadir pinhole; rel = P_world - cam_pos; Xc=rel.x, Yc=-rel.y,
Zc=-rel.z; u=fx*Xc/Zc+cx, v=fy*Yc/Zc+cy; r_px = fx*physical_radius_m/Zc.
"""
from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

import numpy as np

# Minimum pinhole depth (m) for a bird to count as projectable / in front of the nadir camera.
# Matches the generator's `zc > 0.5` frustum gate so GT agrees with how the clip was rendered.
MIN_DEPTH_M = 0.5


# --------------------------------------------------------------------------------------
# Stdlib PNG I/O (8-bit grayscale or RGB, all standard filter types) -- no Pillow/OpenCV.
# --------------------------------------------------------------------------------------
def read_png(path: Path) -> np.ndarray:
    """Decode an 8-bit PNG (grayscale or RGB, non-interlaced) to a uint8 numpy array.
    Supports filter types 0-4 so real-render PNGs decode too, not just the synthetic clip."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    pos = 8
    width = height = bit_depth = color_type = None
    idat = bytearray()
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length  # 4 len + 4 tag + data + 4 crc
        if tag == b"IHDR":
            width, height, bit_depth, color_type, comp, filt, interlace = struct.unpack(
                ">IIBBBBB", chunk)
            if bit_depth != 8:
                raise ValueError(f"only 8-bit PNG supported, got bit_depth={bit_depth}")
            if interlace != 0:
                raise ValueError("interlaced PNG not supported")
        elif tag == b"IDAT":
            idat.extend(chunk)
        elif tag == b"IEND":
            break
    if color_type == 0:
        channels = 1
    elif color_type == 2:
        channels = 3
    else:
        raise ValueError(f"unsupported PNG color_type={color_type} (need 0 grayscale or 2 RGB)")

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = np.zeros((height, width * channels), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    i = 0
    bpp = channels  # bytes per pixel (8-bit)
    for row in range(height):
        ftype = raw[i]
        i += 1
        cur = np.frombuffer(raw[i:i + stride], dtype=np.uint8).astype(np.int32).copy()
        i += stride
        if ftype == 0:  # None
            pass
        elif ftype == 1:  # Sub
            for x in range(bpp, stride):
                cur[x] = (cur[x] + cur[x - bpp]) & 0xFF
        elif ftype == 2:  # Up
            cur = (cur + prev) & 0xFF
        elif ftype == 3:  # Average
            for x in range(stride):
                a = cur[x - bpp] if x >= bpp else 0
                cur[x] = (cur[x] + ((a + prev[x]) >> 1)) & 0xFF
        elif ftype == 4:  # Paeth
            for x in range(stride):
                a = cur[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                cur[x] = (cur[x] + pr) & 0xFF
        else:
            raise ValueError(f"unknown PNG filter type {ftype}")
        out[row] = cur
        prev = cur
    img = out.reshape(height, width, channels)
    return img[:, :, 0] if channels == 1 else img


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def write_png(path: Path, arr: np.ndarray) -> None:
    """Write uint8 (H,W) grayscale or (H,W,3) RGB PNG (filter type 0). For overlay dumps."""
    if arr.dtype != np.uint8:
        raise ValueError(f"write_png expects uint8, got {arr.dtype}")
    if arr.ndim == 2:
        h, w = arr.shape
        color_type = 0
    elif arr.ndim == 3 and arr.shape[2] == 3:
        h, w, _ = arr.shape
        color_type = 2
    else:
        raise ValueError(f"unsupported shape {arr.shape}")
    raw = bytearray()
    for row in range(h):
        raw.append(0)
        raw.extend(arr[row].tobytes())
    ihdr = struct.pack(">IIBBBBB", w, h, 8, color_type, 0, 0, 0)
    Path(path).write_bytes(
        b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + _png_chunk(b"IEND", b""))


# --------------------------------------------------------------------------------------
# Clip loading + projection + geometry
# --------------------------------------------------------------------------------------
def load_meta(clip_dir: Path) -> dict:
    return json.loads((Path(clip_dir) / "meta.json").read_text())


def load_poses(clip_dir: Path) -> list[dict]:
    lines = (Path(clip_dir) / "poses.jsonl").read_text().splitlines()
    return [json.loads(l) for l in lines if l.strip()]


def project_bird(bird_pos, cam_pos, intr):
    """Project a world-ENU bird position to (u, v, r_px, Zc) using the nadir pinhole convention.
    Returns None if the point is behind / above the camera (Zc <= MIN_DEPTH_M).
    intr: dict with fx, fy, cx, cy. bird_pos/cam_pos: (x,y,z) world ENU meters.
    r_px uses physical_radius via caller; here return unit-radius scale fx/Zc for the caller."""
    rel_x = bird_pos[0] - cam_pos[0]
    rel_y = bird_pos[1] - cam_pos[1]
    rel_z = bird_pos[2] - cam_pos[2]
    xc, yc, zc = rel_x, -rel_y, -rel_z
    if zc <= MIN_DEPTH_M:
        return None
    u = intr["fx"] * xc / zc + intr["cx"]
    v = intr["fy"] * yc / zc + intr["cy"]
    return u, v, zc


def clip_box(box, w, h):
    """Clip [x0,y0,x1,y1] to image bounds; return None if it has no area inside the image."""
    x0 = max(0.0, min(box[0], box[2]))
    y0 = max(0.0, min(box[1], box[3]))
    x1 = min(float(w), max(box[0], box[2]))
    y1 = min(float(h), max(box[1], box[3]))
    if x1 <= x0 or y1 <= y0:
        return None
    return [x0, y0, x1, y1]


def iou(a, b) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0
