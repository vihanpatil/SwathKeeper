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

KNOWN-WRONG FOR THE GAZEBO WORLD (found 2026-08-21, deliberately NOT patched here). "bright +
achromatic" is a property of the SYNTHETIC clip's white birds. In sim/worlds/farmguard_field.sdf the
birds are DARK (config/birds/farm_world_birds.json color_rgba 0.12 / 0.30 / 0.18) against BRIGHT
soil (R138 G161 B115), so min-channel birdness is inverted: on the demo take every real-render frame
saturates the mask into one whole-image blob that max_area then discards, and this arm emits zero
detections for a reason that has nothing to do with RGB-vs-NDVI. Flipping the polarity is a
one-character change and a wrong one to make blind -- the threshold also has to be recalibrated to
this render's absolute scale, and both belong to the Week-6 comparison arm with a clip that actually
contains a visible bird to calibrate against. Until then, (b)'s numbers on a real clip mean nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import spike_common as sc  # noqa: E402
# The SAME blob machinery arm (a) runs, from its single home -- that is what makes the ADR-003
# comparison apples-to-apples: (a) and (b) differ only in the birdness signal above.
from fieldguard_planning.ndvi_detect import detect_blobs  # noqa: E402


def run(clip_dir: Path, thresh: int, min_area: int, max_area: int):
    poses = sc.load_poses(clip_dir)
    frames = []
    skipped = []
    for d in poses:
        # The synthetic spike clip carries RGB on every frame; a real recorded clip carries it on a
        # SUBSET (the 2026-08-21 demo take: 243 of 454), because the RGB and NDVI bands arrive on
        # separate topics and only NDVI is required. Unconditional d["rgb_path"] used to KeyError
        # here, killing run_spike.sh on any real clip.
        #
        # LIMITATION, not fixed here: score.py iterates the GROUND TRUTH's frames and treats a frame
        # absent from this list exactly as it treats one with zero boxes, so these frames still land
        # as FN against (b) if a bird was visible in them. Skipping vs emitting empty is therefore
        # the same number today; the ids are recorded below so the shortfall is visible in the
        # artifact rather than inferred. Making (b)'s FNR comparable to (a)'s on a partial-RGB clip
        # means scoring each arm over the frames it could actually see -- a score.py change, and a
        # decision (which denominator is honest?) that belongs with the Week-6 comparison arm.
        if "rgb_path" not in d:
            skipped.append(d["frame_id"])
            continue
        rgb = sc.read_png(Path(clip_dir) / d["rgb_path"])
        birdness = rgb.min(axis=2)  # bright + achromatic -> high min channel
        mask = birdness > thresh
        boxes = detect_blobs(mask, min_area, max_area)
        frames.append({"frame_id": d["frame_id"], "boxes": boxes})
    if skipped:
        print(f"[baseline_rgb] {len(skipped)} of {len(poses)} frames carry no rgb_path -- this arm "
              f"cannot see them; see run()'s LIMITATION note before comparing (b)'s FNR to (a)'s")
    return frames, skipped


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

    frames, skipped = run(args.clip, args.thresh, args.min_area, args.max_area)
    n_det = sum(len(f["boxes"]) for f in frames)
    out = {"approach": "b_synthetic_rgb", "clip": str(args.clip),
           "params": {"thresh": args.thresh, "min_area": args.min_area,
                      "max_area": args.max_area},
           "frames_without_rgb": skipped,
           "frames": frames}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    print(f"[baseline_rgb] thresh={args.thresh} -> {n_det} detections over {len(frames)} frames "
          f"-> {args.out}")


if __name__ == "__main__":
    main()
