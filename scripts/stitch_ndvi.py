#!/usr/bin/env python3
"""Offline georeferenced NDVI stitch: spike-schema clip -> per-cell heatmap artifact.

THE consumer of `ndvi_georef.NdviHeatmapGrid` (which shipped math-first with zero callers -- this
runner is what makes the Weeks 5-6 exit criterion 1, "a georeferenced NDVI heatmap for a full
flight," producible). Decision (DECISIONS.md, 2026-08-18): the v1 stitch is OFFLINE, post-flight,
over a recorded clip -- NOT a live in-node accumulator. A recorded flight satisfies the exit
criterion identically, keeps the flight-time graph unchanged, and makes the stitch rerunnable/
debuggable against the same evidence artifact it consumes.

Input: a clip directory in the spike schema (`sim/spike/README.md` -- the layout both the
synthetic generator and the future real-render capture emit):
    <clip>/meta.json      camera intrinsics block (fx/fy/cx/cy, image size) + extrinsic offset
    <clip>/poses.jsonl    one line per frame: drone pos_m + quat_wxyz, ndvi_path
    <clip>/frames/ndvi/*.npy   float32 (H,W) NDVI in [-1,1] (AUTHORITATIVE band)

Frame poses use the drone body pose ONLY (`drone.pos_m` / `drone.quat_wxyz`): the fixed nadir
mount extrinsic is already baked into `ndvi_georef.CAMERA_TO_BODY_SIGNS`, so consuming
`camera.quat_wxyz` here would apply the mount twice. quat order: poses.jsonl records (w,x,y,z);
`ndvi_georef` takes geometry_msgs field order (x,y,z,w) -- converted in exactly one place
(`_pose_from_line`), tested in tests/fieldguard_planning/test_stitch_ndvi.py.

Output (default <clip>/heatmap/):
    heatmap.json   per-cell rows on the CANONICAL 2.5 m coverage grid (`coverage.build_grid`, the
                   same 720 cells the avoidance ledger uses -- joinable by cell_id, which is the
                   whole point); mean NDVI is null for a never-imaged cell, EXPLICIT not absent,
                   matching the ledger discipline.
    heatmap.png    false-color render (ndvi_fusion.ndvi_to_preview_rgb ramp; human-only, non-
                   authoritative -- same status as /fg/ndvi/preview under ADR-007).

Exits nonzero if zero frames accumulate or no cell gets a single sample -- a stitch that "ran"
but carries no data is the silent failure mode (cf. the flat-NDVI check in check_ndvi_bands.py)
and must not look like success in a runbook or CI.

Dependency: numpy (requirements-eval.txt) + stdlib; PNG via sim/spike/gen_spike_clip.write_png
(the existing stdlib zlib encoder -- no imageio/opencv).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "spike"))

from fieldguard_planning.coverage import (  # noqa: E402
    DEFAULT_CELL_SIZE_M, CoverageCell, build_grid, load_field_polygon,
)
from fieldguard_planning.ndvi_fusion import ndvi_to_preview_rgb  # noqa: E402
from fieldguard_planning.ndvi_georef import CameraIntrinsics, NdviHeatmapGrid  # noqa: E402
from gen_spike_clip import write_png  # noqa: E402

# Cell-fill colors for the two kinds of "no NDVI value here" in the PNG (heatmap.json is the
# authoritative record; these are display-only): interior-but-never-imaged vs outside-the-polygon.
UNIMAGED_GREY = (170, 170, 170)
OUTSIDE_POLYGON_GREY = (60, 60, 60)
PNG_CELL_PX = 16  # upscale factor: one 2.5 m cell -> 16x16 px, canonical grid -> ~768x256 image


def load_clip_meta(clip_dir: Path) -> dict:
    meta = json.loads((clip_dir / "meta.json").read_text())
    cam = meta["camera"]
    # Fail loudly on the known sample-fixture wart (fx/cx authored for a different image size)
    # rather than stitching every sample out of frame and "succeeding" with an empty map.
    if not (0.0 < cam["cx"] < cam["image_width_px"] and 0.0 < cam["cy"] < cam["image_height_px"]):
        raise ValueError(
            f"meta.json camera block is internally inconsistent: principal point "
            f"({cam['cx']}, {cam['cy']}) lies outside the {cam['image_width_px']}x"
            f"{cam['image_height_px']} image -- intrinsics were authored for a different "
            f"resolution (known issue with sim/spike/sample/); fix the clip's meta.json")
    return meta


def intrinsics_from_meta(meta: dict) -> CameraIntrinsics:
    cam = meta["camera"]
    return CameraIntrinsics(width_px=int(cam["image_width_px"]), height_px=int(cam["image_height_px"]),
                            fx=float(cam["fx"]), fy=float(cam["fy"]),
                            cx=float(cam["cx"]), cy=float(cam["cy"]))


def mount_offset_from_meta(meta: dict) -> Tuple[float, float, float]:
    """Body-frame (FLU) camera offset. The synthetic spike records [0,0,0]; a real-render capture
    records the ADR-007 mount's [0,0,-0.08] (config/ndvi_camera.json)."""
    off = meta.get("camera_extrinsic", {}).get("offset_from_drone_m", [0.0, 0.0, 0.0])
    return (float(off[0]), float(off[1]), float(off[2]))


def _pose_from_line(line: dict) -> Tuple[Tuple[float, float, float], Tuple[float, float, float, float]]:
    """poses.jsonl drone pose -> (pos_enu, quat_xyzw). THE wxyz->xyzw conversion point (see module
    docstring) -- keep it the only one."""
    pos = tuple(float(v) for v in line["drone"]["pos_m"])
    w, x, y, z = (float(v) for v in line["drone"]["quat_wxyz"])
    return pos, (x, y, z, w)


def stitch_clip(clip_dir: Path, cells: Sequence[CoverageCell]) -> Tuple[NdviHeatmapGrid, dict]:
    """Accumulate every frame of `clip_dir` into a heatmap grid. Returns (grid, stats). Raises
    ValueError on an empty/self-inconsistent clip -- never returns a silently-empty result."""
    meta = load_clip_meta(clip_dir)
    intr = intrinsics_from_meta(meta)
    grid = NdviHeatmapGrid(cells, intr, mount_offset_body_m=mount_offset_from_meta(meta))

    zero_update_frames: List[int] = []
    stale_pose_frames: List[int] = []
    n_frames = 0
    with (clip_dir / "poses.jsonl").open() as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            line = json.loads(raw)
            if line.get("pose_pair_stale"):
                # The recorder flagged this frame's pose pairing as beyond bound (render-burst
                # mislabeling, the 2026-08-18 lesson) — skipping is honest; painting it somewhere
                # plausible-but-wrong is exactly what this pipeline exists to prevent.
                stale_pose_frames.append(int(line["frame_id"]))
                continue
            ndvi = np.load(clip_dir / line["ndvi_path"])
            if ndvi.shape != (intr.height_px, intr.width_px):
                raise ValueError(f"frame {line['frame_id']}: NDVI shape {ndvi.shape} != meta.json "
                                 f"({intr.height_px}, {intr.width_px})")
            pos, quat_xyzw = _pose_from_line(line)
            if grid.accumulate_frame(ndvi, pos, quat_xyzw) == 0:
                zero_update_frames.append(int(line["frame_id"]))  # bad pose / out of field -- log, don't hide
            n_frames += 1

    if n_frames == 0:
        raise ValueError(f"{clip_dir}/poses.jsonl contains no frames -- nothing to stitch")
    n_imaged = sum(1 for v in grid.mean_grid().values() if v is not None)
    if n_imaged == 0:
        raise ValueError(f"stitched {n_frames} frames but not one cell got a sample -- the clip's "
                         f"poses/intrinsics do not image the field (silent-empty stitch forbidden)")

    stats = {
        "frames_total": n_frames,
        "frames_stale_pose_skipped": stale_pose_frames,
        "frames_zero_update": zero_update_frames,
        "cells_total": len(cells),
        "cells_imaged": n_imaged,
        "cells_unimaged": len(cells) - n_imaged,
        "clip_synthetic": bool(meta.get("synthetic", False)),
        "clip_seed": meta.get("seed"),
    }
    return grid, stats


def write_heatmap_json(path: Path, grid: NdviHeatmapGrid, stats: dict, clip_dir: Path,
                       cell_size_m: float) -> None:
    means, counts = grid.mean_grid(), grid.sample_counts()
    doc = {
        "schema_version": "1.0",
        "generated_by": "scripts/stitch_ndvi.py",
        "clip_dir": str(clip_dir),
        "cell_size_m": cell_size_m,
        **stats,
        "cells": [
            {"cell_id": c.cell_id, "i": c.i, "j": c.j, "cx_m": c.cx_m, "cy_m": c.cy_m,
             "mean_ndvi": (round(means[c.cell_id], 6) if means[c.cell_id] is not None else None),
             "n_samples": counts[c.cell_id]}
            for c in grid.cells
        ],
    }
    path.write_text(json.dumps(doc, indent=1) + "\n")


def render_heatmap_png(path: Path, grid: NdviHeatmapGrid) -> None:
    means = grid.mean_grid()
    n_i = max(c.i for c in grid.cells) + 1
    n_j = max(c.j for c in grid.cells) + 1
    img = np.empty((n_j, n_i, 3), dtype=np.uint8)
    img[:] = OUTSIDE_POLYGON_GREY
    for c in grid.cells:
        v = means[c.cell_id]
        if v is None:
            img[c.j, c.i] = UNIMAGED_GREY
        else:
            img[c.j, c.i] = ndvi_to_preview_rgb(np.array([[v]], dtype=np.float32))[0, 0]
    img = np.flipud(img)  # row 0 at top of image = max northing (ENU y-up -> image y-down)
    img = np.repeat(np.repeat(img, PNG_CELL_PX, axis=0), PNG_CELL_PX, axis=1)
    write_png(path, img)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clip", required=True, type=Path, help="clip directory (spike schema)")
    ap.add_argument("--out", type=Path, default=None, help="output dir (default <clip>/heatmap)")
    ap.add_argument("--cell-size", type=float, default=DEFAULT_CELL_SIZE_M,
                    help="grid cell size in m (default: canonical %(default)s)")
    # No --ground-z: the flat-field z=0 plane is baked into NdviHeatmapGrid/ndvi_georef (the
    # documented v1 assumption, config/field_polygon.json) -- a flag here would pretend otherwise.
    args = ap.parse_args(argv)

    cells = build_grid(load_field_polygon(), cell_size_m=args.cell_size)
    try:
        grid, stats = stitch_clip(args.clip, cells)
    except (ValueError, FileNotFoundError, KeyError) as exc:
        print(f"STITCH FAILED: {exc}", file=sys.stderr)
        return 1

    out_dir = args.out if args.out is not None else args.clip / "heatmap"
    out_dir.mkdir(parents=True, exist_ok=True)
    write_heatmap_json(out_dir / "heatmap.json", grid, stats, args.clip, args.cell_size)
    render_heatmap_png(out_dir / "heatmap.png", grid)

    src_kind = "SYNTHETIC" if stats["clip_synthetic"] else "real render"
    print(f"stitched {stats['frames_total']} frames ({src_kind}, seed={stats['clip_seed']}) -> "
          f"{stats['cells_imaged']}/{stats['cells_total']} cells imaged "
          f"({stats['cells_unimaged']} unimaged, {len(stats['frames_zero_update'])} zero-update, "
          f"{len(stats['frames_stale_pose_skipped'])} stale-pose skipped) -> "
          f"{out_dir}/heatmap.json + heatmap.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
