#!/usr/bin/env python3
"""Approach (b) RGB-pass detector for the ADR-003 spike (docs/SPIKE_ndvi_vs_rgb.md).

Same-shape classical detector as baseline_ndvi.py, different signal: threshold a per-pixel
"birdness", open/close, connected components, area filter. (a) and (b) differ ONLY in that signal,
which is what makes the comparison apples-to-apples. Emits detections.json, same schema as (a).

THE BIRDNESS IS PER-RENDER, and that is the criterion-2 finding, not a convenience:

  synthetic spike  birdness = min(R,G,B), bird = HIGH, thresh 110
      The spike's birds are white; canopy is green, soil brown, shadow dark, so all three have at
      least one low channel. This is the signal ADR-003 was DECIDED on (precision 1.000) and it is
      untouched -- the synthetic arm reproduces bit-identically.

  real Gazebo render  birdness = GRVI = (G-R)/(G+R), bird = LOW, thresh +0.0322
      "Bright + achromatic" is FALSE on this world and its 1.000 FNR was never RGB's ceiling. In
      sim/worlds/farmguard_field.sdf the birds are dark AND the soil is bright (modal soil pixel
      138/161/115), so min-channel saturates the mask into one whole-image blob that max_area then
      discards -- (b) emitted zero detections for a reason with nothing to do with RGB-vs-NDVI.
      Flipping min-channel's polarity was never the fix either: measured over 1.4027 Gpx it is the
      wrong FEATURE (best operating point FNR 0.0042 at FPR 3.03e-03, 482.3x worse than GRVI's).
      What actually separates bird from world here is CHROMATIC, not tonal: soil (G-R = +23) and
      canopy (+33 to +54) are green-dominant, while all three bird materials are not (bird_0
      0.12/0.12/0.12 and bird_2 0.18/0.18/0.20 render G-R = 0; bird_1 0.30/0.22/0.10 renders -12).
      GRVI is that contrast in NDVI's own algebraic form with G standing in for NIR, so it is
      invariant to the illumination gradient a raw G-R difference is not.
      Provenance of +0.0322: the bird/background GRVI MIDPOINT measured over every pixel of both
      committed real clips -- the same construction that produced the NDVI arm's -0.61 from
      gate2_summary.json. It is recomputed from its evidence by
      tests/fieldguard_planning/test_rgb_pixel_study.py so it cannot drift from it.
      Full study, with every denominator: eval/rgb_pixel_study.py and its results directory
      eval/results/criterion2_rgb_study_*/.

WHAT (b) IS FOR. It is the ADR-003 criterion-2 comparison arm, NOT a detection path: it needs an
RGB camera the real drone does not have (ADR-000 sensor reality), so a win here does not by itself
justify (b) -- see the decision rule in docs/SPIKE_ndvi_vs_rgb.md section 3.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, NamedTuple

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import spike_common as sc  # noqa: E402
# The SAME blob machinery arm (a) runs, from its single home -- that is what makes the ADR-003
# comparison apples-to-apples: (a) and (b) differ only in the birdness signal above.
from fieldguard_planning.ndvi_detect import (  # noqa: E402
    DEFAULT_MAX_AREA,
    DEFAULT_MIN_AREA,
    detect_blobs,
)

SYNTHETIC_MIN_CHANNEL_THRESH = 110      # counts; bird = min(R,G,B) ABOVE this
REAL_RENDER_GRVI_THRESH = 0.0322        # GRVI; bird = (G-R)/(G+R) BELOW this


def birdness_min_channel(rgb: np.ndarray) -> np.ndarray:
    """Bright + achromatic: high only when all three channels are bright (white/gray birds)."""
    return rgb.min(axis=2).astype(np.float32)


def birdness_grvi(rgb: np.ndarray) -> np.ndarray:
    """Green-Red Vegetation Index, (G-R)/(G+R) -- NDVI's algebra with G as the pseudo-NIR band.

    Ratio, not difference, on purpose: a Lambertian surface scales all three channels by the same
    illumination factor, so the ratio is invariant to shading while G-R is not. Measured on this
    world: one bird material spans G-R from -20 (shadowed) to -6 (lit) while its GRVI stays within
    0.02 of its material value.

    The 0/0 pixel (R=G=0) is defined as 0.0, borrowing ndvi_fusion.NDVI_ZERO_DENOM_SENTINEL. Say
    the consequence out loud rather than implying neutrality: 0.0 is BELOW this render's threshold,
    so a pure-black pixel is called bird. That is the fail-SAFE direction on ADR-003's own terms (a
    wasteful dodge is cheap, a missed bird is not), and it cannot arise on this render anyway --
    the darkest pixel either clip contains is R=52. Pinned by test so the reasoning outlives the
    world that made it moot."""
    red = rgb[:, :, 0].astype(np.float32)
    green = rgb[:, :, 1].astype(np.float32)
    denom = green + red
    return np.divide(green - red, denom, out=np.zeros_like(denom), where=denom > 0)


class Birdness(NamedTuple):
    name: str
    feature: Callable[[np.ndarray], np.ndarray]
    thresh: float
    low_is_bird: bool
    provenance: str

    def mask(self, rgb: np.ndarray) -> np.ndarray:
        v = self.feature(rgb)
        return v < self.thresh if self.low_is_bird else v > self.thresh


SYNTHETIC_BIRDNESS = Birdness(
    "min_channel", birdness_min_channel, SYNTHETIC_MIN_CHANNEL_THRESH, False,
    "synthetic-spike default (ADR-003 deciding run)")
REAL_RENDER_BIRDNESS = Birdness(
    "grvi", birdness_grvi, REAL_RENDER_GRVI_THRESH, True,
    "real-render default, PROVISIONAL (bird/background GRVI midpoint, criterion-2 pixel study)")


def resolve_birdness(clip_dir: Path, explicit_thresh: float | None = None) -> Birdness:
    """Which birdness this clip needs. An explicit --thresh overrides the value, never the feature.

    Refuses to guess when the clip does not say which render it is -- exactly as
    baseline_ndvi.resolve_threshold does, and for the same reason: the failure mode of guessing is
    not a crash but a plausible-looking run that detected nothing (ADR-003 am. 1)."""
    meta_path = Path(clip_dir) / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    if "synthetic" not in meta:
        raise ValueError(
            f"{meta_path} does not say whether this clip is `synthetic` -- and (b)'s birdness "
            f"differs in FEATURE and POLARITY between the synthetic spike (min-channel > "
            f"{SYNTHETIC_MIN_CHANNEL_THRESH}) and the real render (GRVI < "
            f"{REAL_RENDER_GRVI_THRESH}). Pass --clip a clip with a meta.json.")
    b = SYNTHETIC_BIRDNESS if meta["synthetic"] else REAL_RENDER_BIRDNESS
    if explicit_thresh is not None:
        b = b._replace(thresh=explicit_thresh, provenance="explicit --thresh")
    return b


def run(clip_dir: Path, birdness: Birdness, min_area: int, max_area: int):
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
        # decision (which denominator is honest?) that belongs with the comparison arm.
        if "rgb_path" not in d:
            skipped.append(d["frame_id"])
            continue
        rgb = sc.read_png(Path(clip_dir) / d["rgb_path"])
        boxes = detect_blobs(birdness.mask(rgb), min_area, max_area)
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
    ap.add_argument("--thresh", type=float, default=None,
                    help=f"override the birdness threshold; the FEATURE still comes from the "
                         f"clip's meta.json (synthetic: min-channel > "
                         f"{SYNTHETIC_MIN_CHANNEL_THRESH}; real render: GRVI < "
                         f"{REAL_RENDER_GRVI_THRESH}, PROVISIONAL)")
    ap.add_argument("--min-area", type=int, default=DEFAULT_MIN_AREA)
    ap.add_argument("--max-area", type=int, default=DEFAULT_MAX_AREA)
    args = ap.parse_args()

    birdness = resolve_birdness(args.clip, args.thresh)
    if "PROVISIONAL" in birdness.provenance:
        print(f"[baseline_rgb] NOTE: birdness {birdness.name} < {birdness.thresh} is PROVISIONAL -- "
              f"a class midpoint over 1.4027 Gpx of the two committed real clips, on 16,686 bird "
              f"pixels from 3 birds at 3 depths (3.9 / 6.9 / 9.0 m). It is the comparison arm's "
              f"signal, not a detection path: the drone has no RGB camera (ADR-000).",
              file=sys.stderr)

    frames, skipped = run(args.clip, birdness, args.min_area, args.max_area)
    n_det = sum(len(f["boxes"]) for f in frames)
    out = {"approach": "b_synthetic_rgb", "clip": str(args.clip),
           "params": {"birdness": birdness.name, "thresh": birdness.thresh,
                      "low_is_bird": birdness.low_is_bird,
                      "thresh_source": birdness.provenance,
                      "thresh_provisional": "PROVISIONAL" in birdness.provenance,
                      "min_area": args.min_area, "max_area": args.max_area},
           "frames_without_rgb": skipped,
           "frames": frames}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n")
    print(f"[baseline_rgb] {birdness.name}{'<' if birdness.low_is_bird else '>'}{birdness.thresh} "
          f"({birdness.provenance}) -> {n_det} detections over {len(frames)} frames -> {args.out}")


if __name__ == "__main__":
    main()
