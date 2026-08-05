#!/usr/bin/env python3
"""Approach (a) NDVI-direct detector for the ADR-003 spike (docs/SPIKE_ndvi_vs_rgb.md).

Signal hypothesis: a bird is a low/negative-NDVI blob against a high-NDVI canopy. Birds are
non-vegetation (NDVI ~<= 0), distinctly below both the canopy (~0.78) AND bare soil (~0.15), which
is what lets a single threshold survive the bird-over-soil hard case (bird_1): the soil reads 0.15
but the bird core reads negative, so `ndvi < thresh` isolates the bird even sitting on bare ground.

Pipeline (blob.py): mask = ndvi < thresh -> open/close -> connected components -> area filter.
Emits detections.json: {frame_id, boxes:[[x0,y0,x1,y1], ...]}.

Threshold default (0.05) is data-driven, not tuned to the metric: it sits below soil (0.15) and
well below canopy, above the bird core (~-0.08). Reported in the output so the choice is auditable.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import spike_common as sc
from blob import detect_blobs


def run(clip_dir: Path, thresh: float, min_area: int, max_area: int):
    poses = sc.load_poses(clip_dir)
    frames = []
    for d in poses:
        ndvi = np.load(Path(clip_dir) / d["ndvi_path"])
        mask = ndvi < thresh
        boxes = detect_blobs(mask, min_area, max_area)
        frames.append({"frame_id": d["frame_id"], "boxes": boxes})
    return frames


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clip", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--thresh", type=float, default=0.05,
                    help="NDVI below this = bird candidate (default 0.05, below soil ~0.15)")
    ap.add_argument("--min-area", type=int, default=6)
    ap.add_argument("--max-area", type=int, default=5000)
    args = ap.parse_args()

    frames = run(args.clip, args.thresh, args.min_area, args.max_area)
    n_det = sum(len(f["boxes"]) for f in frames)
    out = {"approach": "a_ndvi_direct", "clip": str(args.clip),
           "params": {"thresh": args.thresh, "min_area": args.min_area,
                      "max_area": args.max_area},
           "frames": frames}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    print(f"[baseline_ndvi] thresh={args.thresh} -> {n_det} detections over {len(frames)} frames "
          f"-> {args.out}")


if __name__ == "__main__":
    main()
