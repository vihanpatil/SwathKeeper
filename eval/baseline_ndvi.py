#!/usr/bin/env python3
"""Approach (a) NDVI-direct detector for the ADR-003 spike (docs/SPIKE_ndvi_vs_rgb.md).

Signal hypothesis: a bird is a low/negative-NDVI blob against a high-NDVI canopy. Birds are
non-vegetation (NDVI ~<= 0), distinctly below both the canopy (~0.78) AND bare soil (~0.15), which
is what lets a single threshold survive the bird-over-soil hard case (bird_1): the soil reads 0.15
but the bird core reads negative, so `ndvi < thresh` isolates the bird even sitting on bare ground.

Pipeline (`fieldguard_planning.ndvi_detect.detect_ndvi`): mask = ndvi < thresh -> open/close ->
connected components -> area filter. Emits detections.json: {frame_id, boxes:[[x0,y0,x1,y1], ...]}.

THE DETECTOR ITSELF DOES NOT LIVE HERE. It lives in `src/fieldguard_planning/ndvi_detect.py` so the
live avoidance node and this offline harness run the SAME code (ADR-003 amendment 7 adopted what
this file measured; a second implementation in the flight path would be a different detector
wearing the same verdict). What stays here is the part that is genuinely an eval concern: turning a
recorded CLIP into detections, and resolving which render's threshold that clip needs.

THE THRESHOLD IS PER-RENDER, and that is not a convenience -- it is the ADR-003 amendment-1
finding. `ndvi < thresh` only isolates a bird if `thresh` sits BELOW the background it is seen
against; the synthetic spike's soil reads +0.15 and the real Gazebo render's reads -0.4377, half a
unit apart. Carrying the synthetic 0.05 onto a real clip makes the mask pass 100 % of pixels on 438
of 454 frames (one whole-image component, then discarded by max_area) -- a detector that returns
zero detections while looking like it ran. So the default is resolved from the clip's own
`meta.json` `synthetic` flag rather than being one number for both worlds; `--thresh` still
overrides, and whichever value was used is written into the output next to WHERE it came from.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import spike_common as sc  # noqa: E402
# The detector and its two per-render thresholds, from their single home. Re-exported into this
# module's namespace because they are part of its surface (--thresh help text, resolve_threshold,
# the regression tests) -- re-exported, not re-declared: a second copy of `-0.61` is exactly the
# drift this move exists to make impossible.
from fieldguard_planning.ndvi_detect import (  # noqa: E402
    DEFAULT_MAX_AREA,
    DEFAULT_MIN_AREA,
    REAL_RENDER_THRESH,
    SYNTHETIC_THRESH,
    detect_ndvi,
)


def resolve_threshold(clip_dir: Path, explicit: float | None):
    """(threshold, provenance) for this clip. An explicit --thresh always wins.

    Refuses to guess when the clip does not say which render it is: silently defaulting would pick
    a value that is either half a unit too high or too low, and the failure mode is not a crash but
    a plausible-looking run that detected nothing (ADR-003 am. 1, defect class 'would have written
    a WRONG number into the record rather than failing')."""
    if explicit is not None:
        return explicit, "explicit --thresh"
    meta_path = Path(clip_dir) / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    if "synthetic" not in meta:
        raise ValueError(
            f"{meta_path} does not say whether this clip is `synthetic` -- and the right NDVI "
            f"threshold differs by half a unit between the synthetic spike ({SYNTHETIC_THRESH}) and "
            f"the real render ({REAL_RENDER_THRESH}, gate2-derived). Pass --thresh explicitly.")
    if meta["synthetic"]:
        return SYNTHETIC_THRESH, "synthetic-spike default (ADR-003 deciding run)"
    return REAL_RENDER_THRESH, "real-render default, PROVISIONAL (gate2 bird/soil midpoint)"


def run(clip_dir: Path, thresh: float, min_area: int, max_area: int):
    poses = sc.load_poses(clip_dir)
    frames = []
    for d in poses:
        ndvi = np.load(Path(clip_dir) / d["ndvi_path"])
        boxes = detect_ndvi(ndvi, thresh, min_area, max_area)
        frames.append({"frame_id": d["frame_id"], "boxes": boxes})
    return frames


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clip", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--thresh", type=float, default=None,
                    help=f"NDVI below this = bird candidate. Default is resolved from the clip's "
                         f"meta.json: {SYNTHETIC_THRESH} synthetic, {REAL_RENDER_THRESH} real "
                         f"render (gate2 bird/soil midpoint, PROVISIONAL)")
    ap.add_argument("--min-area", type=int, default=DEFAULT_MIN_AREA)
    ap.add_argument("--max-area", type=int, default=DEFAULT_MAX_AREA)
    args = ap.parse_args()

    thresh, source = resolve_threshold(args.clip, args.thresh)
    if "PROVISIONAL" in source:
        print(f"[baseline_ndvi] NOTE: threshold {thresh} is PROVISIONAL -- derived from per-class "
              f"pixel means (eval/results/gate2_summary.json), not from a detection score. ADR-003 "
              f"amendment 7 ADOPTED the detector at this value, which says it WORKS (n=20 visible "
              f"bird-frames, 7 FP / 3 FN, 8 of 20 labels ambiguous) -- not that it is where the "
              f"threshold belongs. Lifting PROVISIONAL needs the false-positive characterisation, "
              f"not another passing run.", file=sys.stderr)

    frames = run(args.clip, thresh, args.min_area, args.max_area)
    n_det = sum(len(f["boxes"]) for f in frames)
    out = {"approach": "a_ndvi_direct", "clip": str(args.clip),
           "params": {"thresh": thresh, "thresh_source": source,
                      "thresh_provisional": "PROVISIONAL" in source,
                      "min_area": args.min_area, "max_area": args.max_area},
           "frames": frames}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    print(f"[baseline_ndvi] thresh={thresh} ({source}) -> {n_det} detections over {len(frames)} "
          f"frames -> {args.out}")


if __name__ == "__main__":
    main()
