#!/usr/bin/env python3
"""Approach (b) synthetic-RGB detector for the ADR-003 spike (docs/SPIKE_ndvi_vs_rgb.md).

Same-shape classical detector as baseline_ndvi.py, different signal: on the co-located RGB pass a
bird is a bright, achromatic (gray/white) blob, whereas canopy is green (low R,B), soil is brown,
and shadow is dark. "birdness" = per-pixel min-channel min(R,G,B): high only when all three
channels are bright, i.e. white/gray birds; canopy/soil/shadow all have at least one low channel.
mask = min_channel > thresh -> open/close -> connected components -> area filter.

This is the FALLBACK arm and the comparison-arm ceiling: it needs an RGB camera the real drone
does not have (ADR-000 sensor reality), so a win here does not by itself justify (b) -- see the
decision rule in docs/SPIKE_ndvi_vs_rgb.md section 3. Emits detections.json, same schema as (a).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import spike_common as sc
from blob import detect_blobs


def run(clip_dir: Path, thresh: int, min_area: int, max_area: int):
    poses = sc.load_poses(clip_dir)
    frames = []
    for d in poses:
        rgb = sc.read_png(Path(clip_dir) / d["rgb_path"])
        birdness = rgb.min(axis=2)  # bright + achromatic -> high min channel
        mask = birdness > thresh
        boxes = detect_blobs(mask, min_area, max_area)
        frames.append({"frame_id": d["frame_id"], "boxes": boxes})
    return frames


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clip", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--thresh", type=int, default=110,
                    help="min-channel above this = bright/achromatic bird candidate (default 110)")
    ap.add_argument("--min-area", type=int, default=6)
    ap.add_argument("--max-area", type=int, default=5000)
    args = ap.parse_args()

    frames = run(args.clip, args.thresh, args.min_area, args.max_area)
    n_det = sum(len(f["boxes"]) for f in frames)
    out = {"approach": "b_synthetic_rgb", "clip": str(args.clip),
           "params": {"thresh": args.thresh, "min_area": args.min_area,
                      "max_area": args.max_area},
           "frames": frames}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    print(f"[baseline_rgb] thresh={args.thresh} -> {n_det} detections over {len(frames)} frames "
          f"-> {args.out}")


if __name__ == "__main__":
    main()
