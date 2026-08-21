#!/usr/bin/env python3
"""Scoring core for the eval harness -- the reusable seed every later 'does it work' claim routes
through (docs/SPIKE_ndvi_vs_rgb.md section 4; eval/README.md metric contract).

Inputs: ground_truth.json (from label_from_sim.py) + one or more detections.json (from the
baselines). Matching: greedy IoU, a detection is a true positive if IoU >= iou_thresh (default 0.3,
loose on purpose -- for avoidance we care 'a bird is roughly there', not pixel-tight boxes). Only
visible GT boxes are scored, so the detector isn't penalized for birds it cannot see.

Metrics (per approach):
  precision = TP / (TP + FP)          -- how much we cry wolf
  recall    = TP / (TP + FN)          -- how many bird-frames we catch
  FNR       = FN / (TP + FN) = 1-recall  -- SAFETY-CRITICAL, reported separately, never averaged
  per-bird-track FNR = fraction of birds NOT detected on >=1 frame BEFORE closest approach
                       (a bird first seen only at/after closest approach is a near-miss)

If both spike approaches (a_ndvi_direct + b_synthetic_rgb) are scored together, applies the
ADR-003 decision rule and prints a recommendation. FN (missed bird) is a safety bug and is reported
apart from FP (wasteful dodge) -- they are not blended into one score.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import spike_common as sc

PER_BIRD_FNR_BAR = 0.10   # (a) must clear this (docs/SPIKE_ndvi_vs_rgb.md section 3)
FNR_GAP_BAR = 0.10        # (a) must be within this of (b) on frame FNR
# Evidence floor for the decision rule (NOT a detector bar). Deliberately the smallest number that
# is not zero: the failure this exists to stop is a decision on an EMPTY ground truth, and nobody
# has yet measured how many bird-frames a trustworthy verdict needs. Raise it when someone has.
MIN_VISIBLE_BIRD_FRAMES = 1


def load_gt(path):
    gt = json.loads(Path(path).read_text())
    by_fid = {}
    for f in gt["frames"]:
        by_fid[f["frame_id"]] = f
    return gt, by_fid


def match_frame(gt_boxes, det_boxes, iou_thresh):
    """gt_boxes: list of (bird_id, bbox) for VISIBLE birds. det_boxes: list of bbox.
    Greedy highest-IoU matching. Returns (matched_bird_ids set, tp, fp, fn)."""
    pairs = []
    for gi, (_, gb) in enumerate(gt_boxes):
        for di, db in enumerate(det_boxes):
            i = sc.iou(gb, db)
            if i >= iou_thresh:
                pairs.append((i, gi, di))
    pairs.sort(reverse=True)
    used_g, used_d = set(), set()
    matched_ids = set()
    for i, gi, di in pairs:
        if gi in used_g or di in used_d:
            continue
        used_g.add(gi)
        used_d.add(di)
        matched_ids.add(gt_boxes[gi][0])
    tp = len(used_g)
    fn = len(gt_boxes) - tp
    fp = len(det_boxes) - len(used_d)
    return matched_ids, tp, fp, fn


def score(gt_by_fid, det_frames, iou_thresh):
    det_by_fid = {f["frame_id"]: f["boxes"] for f in det_frames}
    TP = FP = FN = 0
    # per-bird tracking: closest-approach frame (min range while visible), and frames matched
    bird_frames = {}  # bird_id -> list of (frame_id, t_s, range_m, matched_bool)
    for fid, gf in gt_by_fid.items():
        vis = [(b["bird_id"], b["bbox"]) for b in gf["birds"] if b["visible"]]
        dets = det_by_fid.get(fid, [])
        matched_ids, tp, fp, fn = match_frame(vis, dets, iou_thresh)
        TP += tp
        FP += fp
        FN += fn
        for b in gf["birds"]:
            if not b["visible"]:
                continue
            bird_frames.setdefault(b["bird_id"], []).append(
                (fid, gf["t_s"], b["range_m"], b["bird_id"] in matched_ids))

    precision = TP / (TP + FP) if (TP + FP) else 0.0
    recall = TP / (TP + FN) if (TP + FN) else 0.0
    fnr = FN / (TP + FN) if (TP + FN) else 0.0

    per_bird = []
    n_missed_pre = 0
    for bird_id, recs in sorted(bird_frames.items()):
        # closest approach = frame with min range among visible frames
        closest = min(recs, key=lambda r: (r[2] if r[2] is not None else 1e9))
        t_closest = closest[1]
        pre = [r for r in recs if r[1] <= t_closest]
        detected_pre = any(r[3] for r in pre)
        n_hit = sum(1 for r in recs if r[3])
        if not detected_pre:
            n_missed_pre += 1
        per_bird.append({
            "bird_id": bird_id,
            "visible_frames": len(recs),
            "matched_frames": n_hit,
            "closest_range_m": round(closest[2], 2) if closest[2] is not None else None,
            "t_closest_s": t_closest,
            "detected_before_closest": detected_pre,
        })
    per_bird_fnr = n_missed_pre / len(per_bird) if per_bird else 0.0

    return {
        "TP": TP, "FP": FP, "FN": FN,
        "precision": precision, "recall": recall, "fnr": fnr,
        "per_bird_track_fnr": per_bird_fnr,
        # Evidence counts, reported next to the rates because every rate above is 0.0 when there is
        # nothing to score and 0.0 reads as "perfect". `decide()` refuses on these, not on the rates.
        "birds_with_visible_frames": len(per_bird),
        "visible_bird_frames": sum(b["visible_frames"] for b in per_bird),
        "per_bird": per_bird,
    }


def print_report(label, m):
    print(f"\n=== {label} ===")
    print(f"  TP={m['TP']}  FP={m['FP']}  FN={m['FN']}   (frame-level, IoU>=thresh)")
    print(f"  precision = {m['precision']:.3f}")
    print(f"  recall    = {m['recall']:.3f}")
    print(f"  FNR       = {m['fnr']:.3f}   <-- SAFETY-CRITICAL (missed bird-frames)")
    print(f"  per-bird-track FNR = {m['per_bird_track_fnr']:.3f} "
          f"(birds not seen before closest approach)")
    print(f"  evidence  = {m['visible_bird_frames']} visible bird-frames over "
          f"{m['birds_with_visible_frames']} birds   <-- the denominator every rate above divides by")
    print("  per-bird:")
    print(f"    {'bird':8} {'vis':>4} {'hit':>4} {'closest_m':>9} {'det_before_closest':>18}")
    for b in m["per_bird"]:
        print(f"    {b['bird_id']:8} {b['visible_frames']:>4} {b['matched_frames']:>4} "
              f"{str(b['closest_range_m']):>9} {str(b['detected_before_closest']):>18}")


def evidence_shortfall(m, birds_in_clip):
    """Why this scoring run cannot decide ADR-003, or None if it can.

    Found 2026-08-21 on the first real-render re-run: the demo clip put NO bird in the nadir FOV, so
    TP=FP=FN=0, every guard above yielded 0.000, and the decision rule read four zeros as a clean
    sweep and printed ADOPT. A vacuous PASS on an empty ground truth is worse than a crash -- it
    writes a confirmation into the record on zero evidence. The bars are rates; rates need a
    denominator, so the denominator is now checked before the rates are consulted."""
    if m["visible_bird_frames"] < MIN_VISIBLE_BIRD_FRAMES:
        return (f"only {m['visible_bird_frames']} visible bird-frames scored "
                f"(need >= {MIN_VISIBLE_BIRD_FRAMES})")
    if m["birds_with_visible_frames"] < birds_in_clip:
        return (f"only {m['birds_with_visible_frames']} of {birds_in_clip} birds were ever visible "
                f"-- per-bird-track FNR is undefined for the rest")
    return None


def decide(ma, mb, birds_in_clip):
    """Apply the ADR-003 decision rule. ma=(a) NDVI-direct, mb=(b) synthetic RGB.

    `birds_in_clip` is REQUIRED, not defaulted: a default of 0 would silently switch off the
    roster half of the evidence check for any future caller who forgot it, which is the same class
    of quiet-wrong-answer this guard exists to prevent."""
    a_fnr, b_fnr = ma["fnr"], mb["fnr"]
    a_pbf = ma["per_bird_track_fnr"]
    gap = a_fnr - b_fnr
    lines = []
    shortfall = evidence_shortfall(ma, birds_in_clip)
    if shortfall is not None:
        lines.append(f"evidence check FAILED: {shortfall}")
        return lines, ("EVIDENCE INSUFFICIENT -- no ADR-003 verdict from this clip. This is neither "
                       "a confirmation nor a refutation; the clip contains nothing to score. Fly a "
                       "clip that actually puts each bird in frame, then re-run.")
    lines.append(f"evidence: {ma['visible_bird_frames']} visible bird-frames, "
                 f"{ma['birds_with_visible_frames']}/{birds_in_clip} birds seen")
    lines.append(f"(a) per-bird FNR = {a_pbf:.3f} (bar <= {PER_BIRD_FNR_BAR})")
    lines.append(f"(a) frame FNR = {a_fnr:.3f} vs (b) frame FNR = {b_fnr:.3f} "
                 f"(gap {gap:+.3f}, must be <= {FNR_GAP_BAR})")
    if a_pbf <= PER_BIRD_FNR_BAR and gap <= FNR_GAP_BAR:
        verdict = ("ADOPT (a) NDVI-direct. It clears the per-bird FNR bar and is within "
                   f"{FNR_GAP_BAR} FNR of RGB -- fidelity wins the tiebreak.")
    elif a_pbf > PER_BIRD_FNR_BAR and gap > FNR_GAP_BAR:
        verdict = ("ESCALATE to product-lead: (a) misses the FNR bar AND (b) is materially better "
                   "(gap > 0.10) -- fidelity-vs-safety tradeoff, likely adopt (b) or (a)+RGB-assist.")
    else:
        verdict = ("AMBIGUOUS -> default to (a) + scoped follow-up ticket (do NOT extend the "
                   "spike), per docs/SPIKE_ndvi_vs_rgb.md section 5.")
    return lines, verdict


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ground-truth", type=Path, required=True)
    ap.add_argument("--detections", type=Path, nargs="+", required=True,
                    help="one or more detections.json files")
    ap.add_argument("--iou", type=float, default=0.3)
    ap.add_argument("--out", type=Path, default=Path("eval/results/spike_scores.json"))
    args = ap.parse_args()

    gt, gt_by_fid = load_gt(args.ground_truth)
    results = {"ground_truth": str(args.ground_truth), "iou_thresh": args.iou,
               "synthetic": gt.get("synthetic"), "approaches": {}}
    scored = {}
    for det_path in args.detections:
        det = json.loads(det_path.read_text())
        approach = det.get("approach", det_path.stem)
        m = score(gt_by_fid, det["frames"], args.iou)
        m["params"] = det.get("params")
        scored[approach] = m
        results["approaches"][approach] = m
        print_report(approach, m)

    # The clip's bird roster, not the visible subset: a bird that is never visible must still count
    # against `birds_with_visible_frames`, or "we saw one of three" scores as a full sweep.
    birds_in_clip = len({b["bird_id"] for f in gt_by_fid.values() for b in f["birds"]})
    results["birds_in_clip"] = birds_in_clip

    if "a_ndvi_direct" in scored and "b_synthetic_rgb" in scored:
        lines, verdict = decide(scored["a_ndvi_direct"], scored["b_synthetic_rgb"], birds_in_clip)
        print("\n=== ADR-003 decision rule ===")
        for l in lines:
            print("  " + l)
        print("  ->", verdict)
        results["decision"] = {"criteria": lines, "verdict": verdict}
        if gt.get("synthetic"):
            caveat = ("SYNTHETIC clip -- validates the HARNESS and gives a first signal; confirm "
                      "against the real Gazebo render before closing ADR-003 as final.")
            print("  CAVEAT:", caveat)
            results["decision"]["caveat"] = caveat

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, indent=1) + "\n")
    print(f"\n[score] wrote {args.out}")


if __name__ == "__main__":
    main()
