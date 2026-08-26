#!/usr/bin/env python3
"""ADR-003 criterion 2: the independent RGB pixel study on the real Gazebo render.

THE QUESTION. Criterion 2 asks what a second sensor buys. Its arm was `baseline_rgb.py`, whose
"bright + achromatic" birdness is inverted on this world, so its 1.000 FNR measured the wrong
signal and was never RGB's ceiling. This script answers the question the arm could not: given the
pixels the real render actually produces, what is the BEST an RGB rule could do here -- and does
that reach the adopted NDVI detector's per-bird-track FNR 0.000 / precision 0.708 / recall 0.850?

HOW A BIRD PIXEL IS DEFINED (and why it is not circular). Ground truth for "which pixels are bird"
comes from the NDVI ORACLE `ndvi < -0.50`, validated here rather than assumed: across every frame
of both committed real clips the darkest NON-bird pixel is -0.4406, so the oracle sits in a wide
empty band, and the 22 frames it fires on are the same frames the independently-derived
applied-pose ground truth calls bird-visible (plus one, at the known label lag). Two caveats are
reported, not hidden:
  * NDVI's Red band IS the RGB camera's R channel (ADR-007), so the oracle is not fully independent
    of the RGB being studied. The bias is toward selecting HIGH-R pixels, which makes birds look
    MORE separable on a red-vs-green feature -- i.e. it flatters RGB, the arm under test.
  * The thermal band is hard-edged while the visible render is antialiased, so a few oracle-labelled
    pixels are RGB mixtures of bird and background. Those land in the feature tails and are counted,
    never trimmed.

WHAT IT MEASURES. (1) exact joint (R,G,B) histograms per pixel class over the FULL pixel budget --
no sampling, so every rate below has a real denominator; (2) per-feature separability, including
the current min-channel birdness in both polarities; (3) the Bayes-optimal per-pixel RGB limit
(a colour-cube lookup: the ceiling over EVERY feature, learned or hand-made, that sees one pixel),
in-sample and held out by bird and by clip; (4) the same blob detector run end to end on the best
principled feature and scored by score.py against the same ground truth the NDVI arm was scored on;
(5) what the resulting false positives actually are, checked against the ADR-001 static-obstacle map.

Run:  python3 eval/rgb_pixel_study.py --out eval/results/criterion2_rgb_study_<UTC>
~3 min on the host over 4,566 frames / 1.40 Gpx (most of it the --sweep re-runs). No Docker.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import ndimage

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "src"))

import baseline_rgb  # noqa: E402
import score as scoring  # noqa: E402
import spike_common as sc  # noqa: E402
from fieldguard_planning.ndvi_georef import CameraIntrinsics, pixel_to_ground_enu  # noqa: E402
from label_from_sim import project_bird_oriented  # noqa: E402

# The bird-pixel oracle. ADR-003 am. 9 measured that no non-bird pixel on the 2026-08-25 clip falls
# below -0.50; `validate_oracle` re-measures that here on BOTH clips instead of trusting it.
ORACLE_THRESH = -0.50
# ADR-009's apparent-size ray, used only to cross-check the per-bird attribution below.
BIRD_RADIUS_M = 0.18
MISSION_ALT_M = 15.0
ATTRIB_CONFIDENT_PX = 25.0   # projected-centre distance under which positional attribution is trusted

# The two committed real clips and the ground truth each was scored on.
CLIPS = [
    {"tag": "real_flight_20260823T073644Z",
     "clip": REPO / "eval/results/clips/real_flight_20260823T073644Z",
     "gt": REPO / "eval/results/adr003_20260823/ground_truth.json",
     "ndvi_det": REPO / "eval/results/adr003_20260823/detections_ndvi.json"},
    {"tag": "real_flight_20260825T205705Z",
     "clip": REPO / "eval/results/clips/real_flight_20260825T205705Z",
     "gt": REPO / "eval/results/adr003_20260825/ground_truth.json",
     "ndvi_det": REPO / "eval/results/adr003_20260825/detections_ndvi.json"},
]

NBINS = 1 << 24   # the whole 8-bit colour cube, so no feature has to be chosen before the sweep

# AUTHORED, not generated -- perception-ml-engineer's reading of the numbers this script produces.
# Update it when the numbers move; it is written into results.json so the evidence directory is
# self-describing (the same role score.py's `decision.verdict` plays in spike_scores.json).
VERDICT = {
    "authored_by": "perception-ml-engineer, 2026-08-26",
    "recommendation": "RETIRE-ARM",
    "answer": (
        "baseline_rgb's 1.000 FNR measured a wrong FEATURE, not a wrong sign: min-channel cannot "
        "beat FNR 0.99994 in the shipped polarity and costs 482.3x GRVI's false-positive rate when "
        "flipped. The real signal on this world is chromatic -- soil and canopy are green-dominant, "
        "all three bird materials are not -- and GRVI < +0.0322 drives the SAME blob detector to "
        "EXACTLY the NDVI arm's safety numbers (identical TP/FN/recall/frame-FNR, per-bird-track "
        "FNR 0.000 on both clips) while losing precision 0.227 vs 0.708 (n=20 bird-frames, 3 birds) "
        "and 0.037 vs 1.000 (n=2, 1 bird). All 103 false positives the RGB arm adds land inside the "
        "2 m ADR-001 tree geofence: the trunk material 0.35/0.22/0.10 and bird_1's 0.30/0.22/0.10 "
        "are the same brown to 0.05 in red, and the trunk is the MORE bird-like of the two, so "
        "per-bird fnr_at_zero_fpr is 1.000 for every bird -- no threshold catches a bird pixel "
        "without also catching trunk. The thermal band resolves them (ADR-007 gate 2: trunk -0.026 "
        "vs bird -0.789); the visible bands cannot."),
    "reasoning": (
        "RETIRE as an OPEN criterion-2 item, not because the arm failed -- it works now and its "
        "result is banked -- but because `band_independence` above MEASURES that it is not a second "
        "sensor: inverting NDVI with rho_red = R/255 collapses dozens of distinct 8-bit red levels onto "
        "3 rho_nir values (gate2's MEASURED means, not config's authored ones -- the collapse is "
        "the proof, not the value match), so the arm shares a band, a sensor, its optics, its mount and its frame "
        "clock with the primary instrument. It contributes G and B and nothing geometric, while the "
        "measured bottleneck is geometric (2.48 m sensor horizon, 0.175 s of lead at the flown "
        "9.4 m/s; 5 of 7 in-cylinder frames 1.4-7.8 m outside the image edge). Criterion 2's "
        "remaining budget belongs to ADR-017's forward-facing sensor, priced in geometry."),
    "closes": [
        "baseline_rgb's 1.000 FNR is retired as a claim about RGB's ceiling",
        "'could RGB have matched the adopted detector?' -- on safety yes exactly, on precision no",
        "'should min-channel's polarity be flipped?' -- no, it is the wrong feature either way",
        "'why not the feature that tops the pixel table?' -- because it loses a bird. G-B beats GRVI "
        "on pixel FNR (0.00082 vs 0.00306) and by 3 orders of magnitude on fpr_at_zero_fnr, and at "
        "its own midpoint it scores per-bird-track FNR 0.333: bird_1, 0 of 5 frames, never detected "
        "before closest approach -- its brown G-B of 24 sits on the background minimum of 23. GRVI, "
        "ExG and G-R all hold 0.000 at precision 0.227 / 0.230 / 0.218, statistically the same. "
        "The DETECTOR decides; the pixel table only shortlists (see rival_features).",
        "ADR-003's ADOPT now rests on a WORKING comparison arm; decision rule unchanged, gap 0.000",
    ],
    "does_not_close": [
        "the -0.61 NDVI threshold's PROVISIONAL flag. Its RANGE half is NARROWED, not closed: this "
        "study measures bird cores at 3.9 / 6.9 / 9.0 m depth all reading <= -0.8276, so the "
        "'only ever exercised at ~4 m' line in ADR-003 am. 9 / ROADMAP item 3 is true of the 08-25 "
        "clip and understates the adopted 08-23 one. Still unmeasured beyond ~11 m; the r_px ~ 2.2 "
        "-> ~40 m bound stays DERIVED; n=20 with 8 label-ambiguous stands.",
        "anything needing a different mount or sensor (ADR-017's forward-facing camera) -- that is "
        "a geometry question for predict_bird_visibility.py over a new extrinsic, then a flight. "
        "Not closable offline on the committed clips, at all.",
        "generalisation past this world: one lighting condition and four authored material "
        "constants. NDVI's empty band is a property of the authored scene as much as of NDVI.",
    ],
    "carry_forward": (
        "tree trunks and bird_1 are the same colour to a visible-band sensor. Harmless only while "
        "every brown object is in config/static_obstacles.json -- a fence post, a bale or a second "
        "vehicle would be dodged by the RGB arm and invisible to the NDVI arm. **v1 flies NDVI-only, so the LIVE failure mode is the invisible brown object, not the cry-wolf dodge** "
        "-- an unsurveyed warm-signature-less obstacle reads as background to the shipped "
        "detector, and a missed obstacle is a safety bug where a wasted dodge is not."),
}


# ---------------------------------------------------------------------------------------------
# Features. Everything is a function of (R,G,B) arrays of the DISTINCT colours in a histogram, so
# each is evaluated exactly once per colour and weighted by that colour's pixel count.
# ---------------------------------------------------------------------------------------------
def _mn(R, G, B):
    return np.minimum(np.minimum(R, G), B)


def _mx(R, G, B):
    return np.maximum(np.maximum(R, G), B)


FEATURES = {
    "R": lambda R, G, B: R,
    "G": lambda R, G, B: G,
    "B": lambda R, G, B: B,
    "min_channel": _mn,                       # <- the birdness baseline_rgb used to use everywhere
    "max_channel": _mx,
    "luminance": lambda R, G, B: 0.299 * R + 0.587 * G + 0.114 * B,
    "chroma_max_minus_min": lambda R, G, B: _mx(R, G, B) - _mn(R, G, B),
    "G_minus_R": lambda R, G, B: G - R,
    "G_minus_B": lambda R, G, B: G - B,
    "ExG_2G_minus_R_minus_B": lambda R, G, B: 2 * G - R - B,
    "GRVI": lambda R, G, B: np.divide(G - R, G + R, out=np.zeros_like(R), where=(G + R) > 0),
    "norm_green": lambda R, G, B: np.divide(G, R + G + B, out=np.zeros_like(R),
                                            where=(R + G + B) > 0),
}


def unpack(hist):
    """(R, G, B, weight) float arrays over the colours a histogram actually contains."""
    nz = np.nonzero(hist)[0]
    return (((nz >> 16) & 255).astype(np.float64), ((nz >> 8) & 255).astype(np.float64),
            (nz & 255).astype(np.float64), hist[nz].astype(np.float64))


def pack_index(rgb):
    return ((rgb[:, :, 0].astype(np.uint32) << 16) | (rgb[:, :, 1].astype(np.uint32) << 8)
            | rgb[:, :, 2].astype(np.uint32))


def accumulate(hist, idx_values):
    v, c = np.unique(idx_values, return_counts=True)
    hist[v] += c.astype(np.uint64)


# ---------------------------------------------------------------------------------------------
# Pass 1: one sweep over every frame -> oracle validation + histograms + component records
# ---------------------------------------------------------------------------------------------
def sweep(entry):
    clip = entry["clip"]
    if not (clip / "frames" / "rgb").is_dir():
        raise SystemExit(
            f"{clip}/frames/rgb is not on disk. This study needs the raw recorded frames, which are "
            f"gitignored (only meta.json / poses.jsonl / heatmap are committed) -- it is a manual "
            f"evidence generator, not a CI step. Its OUTPUT is committed instead: "
            f"eval/results/criterion2_rgb_study_*/results.json.")
    meta = sc.load_meta(clip)
    intr = meta["camera"]
    mount = tuple(meta.get("camera_extrinsic", {}).get("offset_from_drone_m", (0.0, 0.0, 0.0)))
    # Real clips are annotated in place (`--in-place`) or through a view dir; either way the bird
    # labels live beside the poses. Prefer the annotated file when both exist.
    ann = clip / "poses_annotated.jsonl"
    poses = ([json.loads(l) for l in ann.read_text().splitlines() if l.strip()]
             if ann.exists() else sc.load_poses(clip))
    if not any(p.get("birds") for p in poses):
        raise SystemExit(f"{clip} carries no bird labels -- run eval/annotate_real_clip.py first")

    hists = {"bird": np.zeros(NBINS, dtype=np.uint64), "bg": np.zeros(NBINS, dtype=np.uint64)}
    per_bird = {}
    comps = []
    n_px = 0
    n_bird_px = 0
    oracle_frames = []
    floor_no_bird = 1.0        # min NDVI over frames the oracle does NOT fire on
    darkest_bird = 1.0
    # On a bird frame, the smallest NDVI the oracle did NOT claim. If that equals the background
    # floor, nothing lies between the two classes -- no mixed band, so the partition is exhaustive.
    floor_above_oracle = 1.0

    for d in poses:
        ndvi = np.load(clip / d["ndvi_path"])
        n_px += ndvi.size
        bird_m = ndvi < ORACLE_THRESH
        rgb = sc.read_png(clip / d["rgb_path"])
        idx = pack_index(rgb)
        if not bird_m.any():
            floor_no_bird = min(floor_no_bird, float(ndvi.min()))
            accumulate(hists["bg"], idx.ravel())
            continue
        oracle_frames.append(d["frame_id"])
        darkest_bird = min(darkest_bird, float(ndvi.min()))
        n_bird_px += int(bird_m.sum())
        accumulate(hists["bird"], idx[bird_m])
        accumulate(hists["bg"], idx[~bird_m])
        floor_above_oracle = min(floor_above_oracle, float(ndvi[~bird_m].min()))

        # ---- attribute each oracle component to a bird, by GEOMETRY only (never by colour) ----
        wq, xq, yq, zq = d["drone"]["quat_wxyz"]
        quat = (xq, yq, zq, wq)
        proj = {}
        for b in d["birds"]:
            p = project_bird_oriented(b["pos_m"], d["drone"]["pos_m"], quat, mount, intr)
            if p is not None:
                proj[b["bird_id"]] = p
        nominal_depth = {b["bird_id"]: MISSION_ALT_M - b["pos_m"][2] for b in d["birds"]}
        lab, n = ndimage.label(bird_m)
        for ci in range(1, n + 1):
            cm = lab == ci
            ys, xs = np.nonzero(cm)
            cy, cx = float(ys.mean()), float(xs.mean())
            pos_id, pos_dist = None, None
            for bid, (u, v, _zc) in proj.items():
                dd = math.hypot(u - cx, v - cy)
                if pos_dist is None or dd < pos_dist:
                    pos_id, pos_dist = bid, dd
            # ADR-009's apparent-size ray as the independent second opinion: each bird flies a
            # different altitude on a constant-altitude mission, so blob area alone names it.
            r_px = math.sqrt(int(cm.sum()) / math.pi)
            depth = intr["fx"] * BIRD_RADIUS_M / r_px if r_px > 0 else float("inf")
            size_id = min(nominal_depth, key=lambda b: abs(nominal_depth[b] - depth))
            confident = pos_dist is not None and pos_dist <= ATTRIB_CONFIDENT_PX
            bird_id = pos_id if confident else size_id
            hh = per_bird.setdefault(bird_id, np.zeros(NBINS, dtype=np.uint64))
            accumulate(hh, idx[cm])
            comps.append({"frame_id": d["frame_id"], "n_px": int(cm.sum()),
                          "positional_bird": pos_id,
                          "positional_dist_px": round(pos_dist, 1) if pos_dist else None,
                          "size_bird": size_id, "depth_from_size_m": round(depth, 2),
                          "attributed": bird_id, "attribution": "positional" if confident
                          else "apparent-size (positional label was lagged)"})

    return {"meta": meta, "poses": poses, "hists": hists, "per_bird": per_bird, "comps": comps,
            "n_px": n_px, "n_bird_px": n_bird_px, "oracle_frames": oracle_frames,
            "background_floor_ndvi": floor_no_bird, "darkest_bird_ndvi": darkest_bird,
            "floor_above_oracle_on_bird_frames": floor_above_oracle}


# ---------------------------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------------------------
def band_independence(entry, frame_ids):
    """Is the RGB arm actually a SECOND sensor?  Measured, not read off ADR-007's prose.

    ADR-007 states the NDVI Red band is the R channel of this same RGB camera. If that is true then
    rho_red = R/255 exactly (`ndvi_fusion.rescale_red`, lines 85-87), and NDVI = (n-r)/(n+r) inverts
    for the NIR band: n = r(1+NDVI)/(1-NDVI).

    THE PROOF IS THE COLLAPSE, NOT THE VALUES. Shading spreads each frame's red channel over dozens
    of distinct 8-bit levels; the inversion folds all of them onto a HANDFUL of rho_nir values. That
    can only happen if the red used to invert is bit-for-bit the red the NDVI was computed from -- a
    reconstruction from any other red source smears across hundreds of values. `red_levels` vs
    `distinct_reconstructed_rho_nir` below is that ratio, and it is what the claim rests on.

    WHAT THIS IS NOT (adversarial-QA correction, 2026-08-26). The recovered values match
    `eval/results/gate2_summary.json`'s **measured** `mean_rho_nir` (bird 0.040333 / soil 0.211666 /
    canopy 0.854167), NOT `config/ndvi_camera.json`'s **authored** `calibrated_rho_nir`
    (0.05 / 0.20 / 0.85 -- off by -19.3 % / +5.8 % / +0.5 %). gate2 was produced by this same render
    pipeline, so the value agreement is SELF-CONSISTENCY against a same-pipeline artifact plus code
    identity, not cross-validation against config. The inference survives on the collapse alone.

    Why it decides criterion 2: if the two arms share a band, a sensor, its optics, its mount and
    its frame clock, the arm cannot answer 'what does a SECOND sensor buy in range and lead time' --
    it adds G and B, and nothing geometric."""
    clip = entry["clip"]
    poses = {d["frame_id"]: d for d in sc.load_poses(clip)}
    out = []
    for fid in frame_ids:
        d = poses[fid]
        ndvi = np.load(clip / d["ndvi_path"]).astype(np.float64)
        red_u8 = sc.read_png(clip / d["rgb_path"])[:, :, 0]
        red = red_u8.astype(np.float64) / 255.0
        nir = red * (1.0 + ndvi) / (1.0 - ndvi)
        vals = np.unique(np.round(nir, 6))
        levels = int(len(np.unique(red_u8)))
        out.append({"frame_id": fid, "pixels": int(ndvi.size),
                    "red_levels": levels,
                    "distinct_reconstructed_rho_nir": len(vals),
                    "collapse_ratio": round(levels / len(vals), 1),
                    "values": [float(v) for v in vals[:8]],
                    "all_within_unit_interval": bool((nir >= -1e-9).all() and (nir <= 1 + 1e-9).all())})
    return out


def separability(name, fn, hb, hg):
    """Exact bird-vs-background separability of one feature over the FULL pixel budget."""
    bR, bG, bB, bW = unpack(hb)
    gR, gG, gB, gW = unpack(hg)
    NB, NG = bW.sum(), gW.sum()
    vb, vg = fn(bR, bG, bB), fn(gR, gG, gB)
    out = {"feature": name,
           "bird": {"n_px": int(NB), "min": float(vb.min()), "max": float(vb.max()),
                    "mean": float((vb * bW).sum() / NB)},
           "background": {"n_px": int(NG), "min": float(vg.min()), "max": float(vg.max()),
                          "mean": float((vg * gW).sum() / NG)}}
    for pol, low in (("bird_is_LOW", True), ("bird_is_HIGH", False)):
        if low:
            fpr0 = float(gW[vg <= vb.max()].sum() / NG)      # loosest threshold that misses no bird
            fnr0 = float(1 - bW[vb < vg.min()].sum() / NB)   # tightest that admits no background
        else:
            fpr0 = float(gW[vg >= vb.min()].sum() / NG)
            fnr0 = float(1 - bW[vb > vg.max()].sum() / NB)
        # best single threshold, exact, over every value either class takes
        vals = np.unique(np.concatenate([vb, vg]))
        ob, og = np.argsort(vb), np.argsort(vg)
        sb, cb = vb[ob], np.cumsum(bW[ob])
        sg, cg = vg[og], np.cumsum(gW[og])
        best = None
        for t in vals:
            if low:
                i, j = np.searchsorted(sb, t, "right"), np.searchsorted(sg, t, "right")
                tp = cb[i - 1] if i else 0.0
                fp = cg[j - 1] if j else 0.0
            else:
                i, j = np.searchsorted(sb, t, "left"), np.searchsorted(sg, t, "left")
                tp = cb[-1] - (cb[i - 1] if i else 0.0)
                fp = cg[-1] - (cg[j - 1] if j else 0.0)
            fnr, fpr = 1 - tp / NB, fp / NG
            if best is None or (fnr + fpr) < best[0]:
                best = (fnr + fpr, float(t), float(fnr), float(fpr))
        out[pol] = {"fpr_at_zero_fnr": fpr0, "fnr_at_zero_fpr": fnr0,
                    "best_threshold": best[1], "best_fnr": best[2], "best_fpr": best[3]}
    # a positive gap means an EMPTY band separates the classes, as NDVI has between -0.6697/-0.4406
    out["empty_band_width_bird_low"] = float(vg.min() - vb.max())
    out["empty_band_width_bird_high"] = float(vb.min() - vg.max())
    return out


def bayes_limit(hb, hg):
    """Best (FNR, FPR) over EVERY per-pixel RGB rule: a rule is a subset of the colour cube."""
    nz = np.nonzero(hb | hg)[0]
    cb, cg = hb[nz].astype(np.float64), hg[nz].astype(np.float64)
    NB, NG = cb.sum(), cg.sum()
    if NB == 0:
        return {"bird_px": 0, "note": "no bird pixels in this split"}
    shared = (cb > 0) & (cg > 0)
    return {"bird_px": int(NB), "background_px": int(NG),
            "colours_bird_only": int(((cb > 0) & (cg == 0)).sum()),
            "colours_background_only": int(((cb == 0) & (cg > 0)).sum()),
            "colours_in_both": int(shared.sum()),
            "fnr_at_zero_fpr": float(cb[shared].sum() / NB),
            "fpr_at_zero_fnr": float(cg[shared].sum() / NG)}


def apply_rule(hb, hg, accept):
    """(FNR, FPR) of an explicit colour set `accept` on a held-out split."""
    nzb, nzg = np.nonzero(hb)[0], np.nonzero(hg)[0]
    NB, NG = hb[nzb].sum(), hg[nzg].sum()
    tp = hb[nzb][np.isin(nzb, accept)].sum()
    fp = hg[nzg][np.isin(nzg, accept)].sum()
    return {"bird_px": int(NB), "background_px": int(NG),
            "fnr": float(1 - tp / NB) if NB else None,
            "fpr": float(fp / NG) if NG else None}


def threshold_rule(hb, hg, fn, thresh, low=True):
    bR, bG, bB, bW = unpack(hb)
    gR, gG, gB, gW = unpack(hg)
    vb, vg = fn(bR, bG, bB), fn(gR, gG, gB)
    hit_b = (vb < thresh) if low else (vb > thresh)
    hit_g = (vg < thresh) if low else (vg > thresh)
    return {"bird_px": int(bW.sum()), "background_px": int(gW.sum()),
            "fnr": float(1 - bW[hit_b].sum() / bW.sum()) if bW.sum() else None,
            "fpr": float(gW[hit_g].sum() / gW.sum()) if gW.sum() else None}


# ---------------------------------------------------------------------------------------------
# Detector-level arm: the SAME blob detector, scored by the SAME scorer, on the SAME ground truth
# ---------------------------------------------------------------------------------------------
def detector_arm(entry, birdness, trees, geofence_r, sweep_threshs=()):
    clip = entry["clip"]
    meta = sc.load_meta(clip)
    intr_obj = CameraIntrinsics.from_meta(meta["camera"])
    mount = tuple(meta.get("camera_extrinsic", {}).get("offset_from_drone_m", (0.0, 0.0, 0.0)))
    poses = {d["frame_id"]: d for d in sc.load_poses(clip)}
    _gt, gt_by_fid = scoring.load_gt(entry["gt"])
    birds_in_clip = len({b["bird_id"] for f in gt_by_fid.values() for b in f["birds"]})

    out = {}
    frames_rgb, _skipped = baseline_rgb.run(clip, birdness, 6, 5000)
    frames_ndvi = json.loads(Path(entry["ndvi_det"]).read_text())["frames"]
    for name, frames in (("a_ndvi_direct", frames_ndvi), ("b_rgb_grvi", frames_rgb)):
        # `per_bird` is kept, not summarised away: per-bird-track FNR is the safety metric, and an
        # artifact that reports the rate without the table it divides is the shape of defect this
        # project keeps finding.
        m = scoring.score(gt_by_fid, frames, 0.3)
        m["n_detections"] = sum(len(f["boxes"]) for f in frames)
        m["fp_vs_static_map"] = classify_fps(frames, gt_by_fid, poses, intr_obj, mount,
                                             trees, geofence_r)
        out[name] = m
    out["birds_in_clip"] = birds_in_clip
    # How wide is the threshold window in which the DETECTOR's verdict does not move? The pixel
    # band above bounds a pixel rule; this bounds the thing that actually flies.
    if sweep_threshs:
        out["threshold_sweep"] = {}
        for t in sweep_threshs:
            fr, _ = baseline_rgb.run(clip, birdness._replace(thresh=t), 6, 5000)
            m = scoring.score(gt_by_fid, fr, 0.3)
            out["threshold_sweep"][f"{t:g}"] = {
                "TP": m["TP"], "FP": m["FP"], "FN": m["FN"], "precision": m["precision"],
                "recall": m["recall"], "per_bird_track_fnr": m["per_bird_track_fnr"],
                "n_detections": sum(len(f["boxes"]) for f in fr)}
    return out


def rival_features(entry, hb, hg, names, trees, geofence_r):
    """Why the DETECTOR decides which feature ships, and not the pixel table.

    The pixel table's top rows are not GRVI: ExG (best FNR 0.00033) and G-B (0.00082) beat it
    (0.00306, 8th of 12), and on `fpr_at_zero_fnr` G-B is 0.00082 against GRVI's 0.99705. A reviewer
    reading only that table would ask why the worse feature shipped. So run the rivals end to end,
    each at ITS OWN class-mean midpoint -- the same construction GRVI's +0.0322 comes from, so no
    feature is handicapped by being given someone else's threshold.

    Only the 08-23 clip is swept: per-bird-track FNR is the discriminating metric here and it needs
    the 3-bird denominator. The 08-25 clip has 1 of 3 birds visible and score.py refuses it, so it
    cannot separate these candidates at all."""
    clip = entry["clip"]
    _gt, gt_by_fid = scoring.load_gt(entry["gt"])
    out = {}
    for name in names:
        fn = FEATURES[name]
        bR, bG, bB, bW = unpack(hb)
        gR, gG, gB, gW = unpack(hg)
        bird_mean = float((fn(bR, bG, bB) * bW).sum() / bW.sum())
        bg_mean = float((fn(gR, gG, gB) * gW).sum() / gW.sum())
        mid = (bird_mean + bg_mean) / 2.0

        def image_feature(rgb, fn=fn):
            return fn(rgb[:, :, 0].astype(np.float32), rgb[:, :, 1].astype(np.float32),
                      rgb[:, :, 2].astype(np.float32))

        birdness = baseline_rgb.Birdness(name, image_feature, mid, True, "own class-mean midpoint")
        frames, _sk = baseline_rgb.run(clip, birdness, 6, 5000)
        m = scoring.score(gt_by_fid, frames, 0.3)
        out[name] = {
            "own_midpoint": mid, "bird_mean": bird_mean, "background_mean": bg_mean,
            "pixel": threshold_rule(hb, hg, fn, mid),
            "TP": m["TP"], "FP": m["FP"], "FN": m["FN"], "precision": m["precision"],
            "recall": m["recall"], "fnr": m["fnr"],
            "per_bird_track_fnr": m["per_bird_track_fnr"],
            "per_bird": [{k: b[k] for k in ("bird_id", "visible_frames", "matched_frames",
                                            "detected_before_closest")} for b in m["per_bird"]],
            "n_detections": sum(len(f["boxes"]) for f in frames)}
        print(f"        rival {name:24s} @ {mid:+.4f} -> per-bird-track FNR "
              f"{m['per_bird_track_fnr']:.3f}, precision {m['precision']:.3f}", flush=True)
    return out


def classify_fps(frames, gt_by_fid, poses, intr, mount, trees, geofence_r):
    """Every FP box, projected onto the tree column and measured against the surveyed tree map.

    Ground-plane projection is the WRONG model for a bird (ADR-009: z=0 puts a flying bird outside
    the threat cylinder) and the RIGHT one for a tree, which is the point of the check: an FP that
    lands on a surveyed tree is the ADR-001 known-static class the geofence already owns, not a
    cry-wolf dodge. Distance is taken to the tree AXIS by testing several heights along it rather
    than guessing which part of the tree the ray hit."""
    inside = between = beyond = unprojectable = 0
    examples = []
    for fr in frames:
        fid = fr["frame_id"]
        gf = gt_by_fid.get(fid)
        vis = [b["bbox"] for b in (gf["birds"] if gf else []) if b["visible"]]
        for box in fr["boxes"]:
            if max((sc.iou(gb, box) for gb in vis), default=0.0) >= 0.3:
                continue    # matched a real bird -> a TP, not an FP
            d = poses[fid]
            w, x, y, z = d["drone"]["quat_wxyz"]
            best = None
            for zp in (0.0, 0.75, 1.5, 2.5, 3.8):   # trunk base .. canopy top
                g = pixel_to_ground_enu((box[0] + box[2]) / 2, (box[1] + box[3]) / 2, intr,
                                        tuple(d["drone"]["pos_m"]), (x, y, z, w), zp, mount)
                if g is None:
                    continue
                dd = min(math.dist(g, t) for t in trees)
                if best is None or dd < best[0]:
                    best = (dd, g, zp)
            if best is None:
                unprojectable += 1
                continue
            if best[0] <= geofence_r:
                inside += 1
            elif best[0] <= 2 * geofence_r:
                between += 1
            else:
                beyond += 1
                examples.append({"frame_id": fid, "nearest_tree_m": round(best[0], 2),
                                 "enu_m": [round(best[1][0], 2), round(best[1][1], 2)]})
    total = inside + between + beyond + unprojectable
    return {"fp_boxes": total, "inside_tree_geofence": inside,
            "one_to_two_geofence_radii": between, "beyond_two_radii": beyond,
            "unprojectable": unprojectable, "geofence_radius_m": geofence_r,
            "beyond_examples": examples[:10]}


# ---------------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ap.add_argument("--out", type=Path,
                    default=REPO / f"eval/results/criterion2_rgb_study_{stamp}")
    ap.add_argument("--sweep", type=float, nargs="*",
                    default=[0.0, 0.005, 0.0322, 0.07, 0.077],
                    help="thresholds to re-run the DETECTOR at, to measure the window in which "
                         "its verdict does not move (the two outer values are the predicted "
                         "failure points: bird materials render GRVI 0.0000, soil renders 0.0769). "
                         "Pass --sweep with no values to skip; costs ~25 s per value.")
    args = ap.parse_args()
    t0 = time.time()

    obstacles = json.loads((REPO / "config/static_obstacles.json").read_text())
    trees = [(o["pos_m"][0], o["pos_m"][1]) for o in obstacles["obstacles"]]
    geofence_r = obstacles["tree_defaults"]["obstacle_radius_m"]

    swept = {}
    for entry in CLIPS:
        print(f"[study] sweeping {entry['tag']} ...", flush=True)
        swept[entry["tag"]] = sweep(entry)
        s = swept[entry["tag"]]
        print(f"        {len(s['poses'])} frames, {s['n_px'] / 1e6:.2f} Mpx, "
              f"{s['n_bird_px']} bird px on {len(s['oracle_frames'])} frames, "
              f"background floor {s['background_floor_ndvi']:.4f} ({time.time() - t0:.0f}s)")

    # ---- oracle validation, per clip and pooled ------------------------------------------------
    oracle = {}
    for entry in CLIPS:
        s = swept[entry["tag"]]
        gt = json.loads(Path(entry["gt"]).read_text())
        gt_frames = sorted({f["frame_id"] for f in gt["frames"]
                            if any(b["visible"] for b in f["birds"])})
        oracle[entry["tag"]] = {
            "frames": len(s["poses"]), "pixels": s["n_px"],
            "background_floor_ndvi": s["background_floor_ndvi"],
            "darkest_bird_frame_ndvi": s["darkest_bird_ndvi"],
            "oracle_threshold": ORACLE_THRESH,
            "bird_pixels": s["n_bird_px"],
            "floor_above_oracle_on_bird_frames": s["floor_above_oracle_on_bird_frames"],
            "empty_band": [s["darkest_bird_ndvi"], s["background_floor_ndvi"]],
            "oracle_frames": s["oracle_frames"],
            "gt_visible_frames": gt_frames,
            "oracle_not_in_gt": sorted(set(s["oracle_frames"]) - set(gt_frames)),
            "gt_not_in_oracle": sorted(set(gt_frames) - set(s["oracle_frames"]))}

    hb = sum((s["hists"]["bird"] for s in swept.values()), np.zeros(NBINS, dtype=np.uint64))
    hg = sum((s["hists"]["bg"] for s in swept.values()), np.zeros(NBINS, dtype=np.uint64))

    # ---- feature table -------------------------------------------------------------------------
    print(f"[study] feature separability ({time.time() - t0:.0f}s)", flush=True)
    features = {name: separability(name, fn, hb, hg) for name, fn in FEATURES.items()}

    # ---- the derived threshold, and its provenance ---------------------------------------------
    grvi = FEATURES["GRVI"]
    bird_mean = features["GRVI"]["bird"]["mean"]
    bg_mean = features["GRVI"]["background"]["mean"]
    midpoint = (bird_mean + bg_mean) / 2
    derived = {
        "feature": "GRVI", "polarity": "bird is LOW",
        "bird_mean_grvi": bird_mean, "bird_px": features["GRVI"]["bird"]["n_px"],
        "background_mean_grvi": bg_mean, "background_px": features["GRVI"]["background"]["n_px"],
        "midpoint": midpoint, "rounded_4dp": round(midpoint, 4),
        "constant_in_baseline_rgb": baseline_rgb.REAL_RENDER_GRVI_THRESH,
        "construction": "class-mean midpoint -- the same construction that produced the NDVI arm's "
                        "-0.61 from eval/results/gate2_summary.json",
        # Every rate the summary quotes is at the threshold that SHIPS, not at the ROC optimum the
        # feature table reports (that one is fitted to these very pixels and flatters the arm).
        "at_shipped_threshold": threshold_rule(hb, hg, grvi,
                                               baseline_rgb.REAL_RENDER_GRVI_THRESH),
        "pixel_rates_by_threshold": {
            f"{t:g}": threshold_rule(hb, hg, grvi, t)
            for t in (0.0, 0.005, 0.01, 0.02, 0.0322, 0.05, 0.07, 0.0765, 0.077, 0.08)}}

    # ---- Bayes-optimal pixel ceiling, in-sample and held out -----------------------------------
    print(f"[study] Bayes ceiling + held-out splits ({time.time() - t0:.0f}s)", flush=True)
    per_bird = {}
    for s in swept.values():
        for bid, h in s["per_bird"].items():
            per_bird[bid] = per_bird.get(bid, np.zeros(NBINS, dtype=np.uint64)) + h
    ceiling = {"in_sample": bayes_limit(hb, hg), "holdout": {}}
    for bid in sorted(per_bird):
        train = sum((h for b, h in per_bird.items() if b != bid),
                    np.zeros(NBINS, dtype=np.uint64))
        accept = np.nonzero(train)[0]          # the zero-FNR-in-sample rule, fit WITHOUT this bird
        ceiling["holdout"][f"leave_out_{bid}"] = {
            "lut_learned_on_other_birds": apply_rule(per_bird[bid], hg, accept),
            "grvi_threshold_rule": threshold_rule(per_bird[bid], hg, grvi,
                                                  baseline_rgb.REAL_RENDER_GRVI_THRESH)}
    tags = [e["tag"] for e in CLIPS]
    train_h = swept[tags[0]]["hists"]["bird"]
    accept = np.nonzero(train_h)[0]
    ceiling["holdout"][f"train_{tags[0]}_test_{tags[1]}"] = {
        "lut_learned_on_the_other_clip": apply_rule(swept[tags[1]]["hists"]["bird"],
                                                    swept[tags[1]]["hists"]["bg"], accept),
        "grvi_threshold_rule": threshold_rule(swept[tags[1]]["hists"]["bird"],
                                              swept[tags[1]]["hists"]["bg"], grvi,
                                              baseline_rgb.REAL_RENDER_GRVI_THRESH)}

    # ---- per-bird separability + the attribution cross-check -----------------------------------
    comps = [dict(c, clip=t) for t in tags for c in swept[t]["comps"]]
    confident = [c for c in comps if c["attribution"] == "positional"]
    per_bird_sep = {bid: {"bird_px": int(per_bird[bid].sum()),
                          "GRVI": separability("GRVI", grvi, per_bird[bid], hg)}
                    for bid in sorted(per_bird)}
    attribution = {
        "components": len(comps),
        "positionally_confident": len(confident),
        "apparent_size_agrees_on_confident": sum(1 for c in confident
                                                 if c["size_bird"] == c["positional_bird"]),
        "resolved_by_apparent_size": [c for c in comps if c["attribution"] != "positional"],
        "note": "the apparent-size rule is only used where the projected label was lagged; it is "
                "cross-checked against every positionally-confident component first, and it never "
                "looks at colour, so it cannot be circular with the study it feeds"}

    # ---- detector arm ---------------------------------------------------------------------------
    detector = {}
    for entry in CLIPS:
        print(f"[study] detector arm on {entry['tag']} ({time.time() - t0:.0f}s)", flush=True)
        detector[entry["tag"]] = detector_arm(entry, baseline_rgb.REAL_RENDER_BIRDNESS,
                                              trees, geofence_r, args.sweep)

    # ---- the rivals the pixel table would have picked --------------------------------------------
    print(f"[study] rival features on the 3-bird clip ({time.time() - t0:.0f}s)", flush=True)
    rivals = rival_features(CLIPS[0], hb, hg,
                            ("GRVI", "ExG_2G_minus_R_minus_B", "G_minus_B", "G_minus_R"),
                            trees, geofence_r)

    results = {
        "study": "ADR-003 criterion 2 -- independent RGB pixel study on the real render",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": "eval/rgb_pixel_study.py",
        "clips": [{"tag": e["tag"], "clip": str(e["clip"]), "ground_truth": str(e["gt"])}
                  for e in CLIPS],
        "denominators": {
            "frames": sum(o["frames"] for o in oracle.values()),
            "pixels": sum(o["pixels"] for o in oracle.values()),
            "bird_pixels": int(hb.sum()), "background_pixels": int(hg.sum()),
            "bird_visible_frames": sum(len(o["oracle_frames"]) for o in oracle.values()),
            "birds": sorted(per_bird)},
        "oracle_validation": oracle,
        "band_independence": {
            "claim": "ADR-007: the NDVI Red band IS this RGB camera's R channel, so the criterion-2 "
                     "'second sensor' shares a band, a sensor, its optics, its mount and its frame "
                     "clock with the primary one",
            "method": "invert NDVI with rho_red = R/255 (ndvi_fusion.rescale_red:85-87) and report "
                      "how many distinct rho_nir values the frame's red_levels collapse onto. THE "
                      "COLLAPSE RATIO IS THE PROOF: only bit-for-bit band identity folds dozens of "
                      "8-bit red levels onto a handful of reflectances.",
            "value_check": "the recovered values are gate2_summary.json's MEASURED mean_rho_nir "
                           "(bird 0.040333 / soil 0.211666 / canopy 0.854167), NOT "
                           "config/ndvi_camera.json's AUTHORED calibrated_rho_nir "
                           "(0.05 / 0.20 / 0.85; -19.3 % / +5.8 % / +0.5 % apart). gate2 came from "
                           "this same pipeline, so this is self-consistency against a same-pipeline "
                           "artifact plus code identity -- NOT cross-validation against config.",
            "frames": {e["tag"]: band_independence(e, swept[e["tag"]]["oracle_frames"][:2])
                       for e in CLIPS}},
        "features": features,
        "derived_threshold": derived,
        "pixel_ceiling": ceiling,
        "per_bird": per_bird_sep,
        "attribution": attribution,
        "detector_arm": detector,
        "rival_features": {
            "why": "the pixel table's best rows are NOT the feature that shipped -- ExG and G-B beat "
                   "GRVI on pixel FNR, and G-B beats it by three orders of magnitude on "
                   "fpr_at_zero_fnr. Each rival is therefore run END TO END at its OWN class-mean "
                   "midpoint (the identical construction GRVI's +0.0322 comes from) on the only clip "
                   "whose 3-bird denominator can separate them. The pixel-dominant feature loses a "
                   "whole bird; that is why the DETECTOR decides and the pixel table only shortlists.",
            "clip": CLIPS[0]["tag"], "shipped": "GRVI", "results": rivals},
        "elapsed_s": round(time.time() - t0, 1),
        # Everything above is generated. This block is the analyst's reading of it, kept in the
        # artifact for the same reason score.py writes `decision.verdict` into spike_scores.json:
        # a directory of numbers with no recorded conclusion gets re-litigated from scratch.
        "verdict": VERDICT,
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=1) + "\n")
    print(f"\n[study] {results['denominators']['frames']} frames / "
          f"{results['denominators']['pixels'] / 1e9:.3f} Gpx, "
          f"{results['denominators']['bird_pixels']} bird px -> {args.out / 'results.json'} "
          f"({results['elapsed_s']}s)")
    return results


if __name__ == "__main__":
    main()
