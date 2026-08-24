#!/usr/bin/env python3
"""Project scripted-bird world poses -> per-frame ground-truth boxes for the ADR-003 spike.

Reads a spike clip (sim/spike/README.md schema): drone/camera poses + bird world positions from
poses.jsonl, intrinsics from meta.json. INDEPENDENTLY projects each bird through the documented
nadir-pinhole camera model (spike_common.project_bird) into an image-space GT box -- we do NOT
trust poses.jsonl's `generator_bbox_px` (that is the generator's own number, exposed only as a
cross-check). See docs/SPIKE_ndvi_vs_rgb.md section 3.

Visibility gate: a bird gets visible=True only if it is in front of the camera (Zc > MIN_DEPTH_M)
AND its projected box has area inside the image. Birds absent from a frame's birds[] list (not yet
spawned / already despawned) produce no GT entry. Occlusion is out of scope for this spike (no
static obstacles -- ADR-001), so the gate is frustum-only, matching the clip.

Outputs ground_truth.json: {clip, frames:[{frame_id, t_s, birds:[{bird_id, bbox, visible,
range_m}]}]}. --verify cross-checks our projection against generator_bbox_px and prints the
disagreement (a wrong projection silently corrupts every downstream metric -- this is Day-1 work).
--overlay writes a few NDVI/RGB frames with GT boxes drawn, for human eyeballing.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

import spike_common as sc

# Real recorded clips (clip_recorder schema) carry only the DRONE pose, and the drone yaws along
# lanes -- the spike's fixed-extrinsic projection (spike_common.project_bird, camera X = world East
# always) is wrong the moment the vehicle turns. The oriented path below reuses the SAME rotation
# primitives the stitch georef is built on (ndvi_georef, hand-fixture-tested incl. tilted poses),
# so GT labels and the heatmap share one camera model.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from fieldguard_planning.ndvi_georef import (  # noqa: E402
    CameraIntrinsics, camera_world_position, project_world_point,
)


def project_bird_oriented(bird_pos, drone_pos, quat_xyzw, mount_offset_body_m, intr):
    """(u_px, v_px, zc_m) for a bird world position seen from a fully-oriented drone pose, or None
    if the bird is behind/beside the camera. Same pinhole convention as spike_common.project_bird.

    A thin dict-intrinsics adapter over `ndvi_georef.project_world_point` -- the ONE projection this
    project owns (heatmap stitch, these GT labels and `scripts/predict_bird_visibility.py` all call
    it), kept as a named function here because that is the name the harness and its tests import."""
    intr_obj = CameraIntrinsics(width_px=int(intr.get("image_width_px", 0)),
                                height_px=int(intr.get("image_height_px", 0)),
                                fx=intr["fx"], fy=intr["fy"], cx=intr["cx"], cy=intr["cy"])
    return project_world_point(tuple(bird_pos), tuple(drone_pos), tuple(quat_xyzw), intr_obj,
                               tuple(mount_offset_body_m))


def bird_range_m(bird, cam_pos):
    """Camera-to-bird slant range, metres. The synthetic generator writes `range_m` into poses.jsonl
    and that number wins when present; real clips (annotate_real_clip.py) carry only positions, so
    it is derived here from the same camera position the projection uses.

    Not cosmetic: `score.py` defines per-bird-track FNR as "detected before CLOSEST APPROACH", and
    picks that frame by `min(range_m)`. With every range None its `or 1e9` fallback makes `min` pick
    the first visible frame instead, silently weakening the project's safety-critical metric to
    "detected on first sight" -- on exactly the real clips it was built to score."""
    recorded = bird.get("range_m")
    if recorded is not None:
        return recorded
    return round(math.dist(bird["pos_m"], cam_pos), 6)


def build_ground_truth(clip_dir: Path):
    meta = sc.load_meta(clip_dir)
    intr = meta["camera"]
    w, h = meta["image_width_px"], meta["image_height_px"]
    poses = sc.load_poses(clip_dir)
    mount_offset = tuple(meta.get("camera_extrinsic", {}).get("offset_from_drone_m",
                                                              (0.0, 0.0, 0.0)))

    frames = []
    disagreements = []  # (frame_id, bird_id, max_corner_px_diff) vs generator_bbox_px
    for d in poses:
        # Synthetic spike lines carry an explicit fixed-extrinsic camera pose; real recorded lines
        # (clip_recorder schema, annotated by eval/annotate_real_clip.py) carry only the oriented
        # drone pose -- each gets the projection model that matches how its frames were rendered.
        legacy_cam = d.get("camera", {}).get("pos_m")
        if legacy_cam is None:
            wq, xq, yq, zq = d["drone"]["quat_wxyz"]
            quat_xyzw = (xq, yq, zq, wq)
            cam_pos = camera_world_position(tuple(d["drone"]["pos_m"]), quat_xyzw, mount_offset)
        else:
            cam_pos = tuple(legacy_cam)
        birds_gt = []
        for b in d["birds"]:
            if legacy_cam is not None:
                proj = sc.project_bird(b["pos_m"], legacy_cam, intr)
            else:
                proj = project_bird_oriented(b["pos_m"], d["drone"]["pos_m"], quat_xyzw,
                                             mount_offset, intr)
            entry = {"bird_id": b["bird_id"], "bbox": None, "visible": False,
                     "range_m": bird_range_m(b, cam_pos),
                     # How well this label's POSITION is known, carried through untouched from
                     # annotate_real_clip. "generator" is the synthetic clips' default: their
                     # birds[] is where the generator drew the bird, exact by construction. A real
                     # clip that arrives without the key was labelled by a pre-2026-08-22 annotator
                     # and its timing is unknown, which scores the same as modeled -- unscoreable.
                     "label_src": b.get("label_src", "generator" if meta.get("synthetic")
                                        else "unknown")}
            if b.get("label_ambiguous"):
                entry["label_ambiguous"] = True
            if proj is not None:
                u, v, zc = proj
                r_px = intr["fx"] * b["physical_radius_m"] / zc
                box = sc.clip_box([u - r_px, v - r_px, u + r_px, v + r_px], w, h)
                if box is not None:
                    entry["bbox"] = [round(c, 3) for c in box]
                    entry["visible"] = True
                    gen = b.get("generator_bbox_px")
                    if gen is not None:
                        diff = max(abs(box[i] - gen[i]) for i in range(4))
                        disagreements.append((d["frame_id"], b["bird_id"], diff))
            birds_gt.append(entry)
        frames.append({"frame_id": d["frame_id"], "t_s": d["t_s"], "birds": birds_gt})

    gt = {"clip": str(clip_dir), "seed": meta.get("seed"), "synthetic": meta.get("synthetic"),
          "image_width_px": w, "image_height_px": h, "frames": frames}
    return gt, disagreements


def draw_box(img, box, color):
    x0, y0, x1, y1 = [int(round(c)) for c in box]
    x0, x1 = max(0, x0), min(img.shape[1] - 1, x1)
    y0, y1 = max(0, y0), min(img.shape[0] - 1, y1)
    for t in range(2):  # 2px thick
        img[np.clip([y0 + t, y1 - t], 0, img.shape[0] - 1), x0:x1 + 1] = color
        img[y0:y1 + 1, np.clip([x0 + t, x1 - t], 0, img.shape[1] - 1)] = color


def ndvi_to_gray(ndvi):
    g = np.clip((ndvi + 1.0) / 2.0 * 255.0, 0, 255).astype(np.uint8)
    return np.stack([g, g, g], axis=-1)


def write_overlays(clip_dir: Path, gt, out_dir: Path, frame_ids):
    out_dir.mkdir(parents=True, exist_ok=True)
    poses = {d["frame_id"]: d for d in sc.load_poses(clip_dir)}
    gt_by_fid = {f["frame_id"]: f for f in gt["frames"]}
    for fid in frame_ids:
        d = poses[fid]
        ndvi = np.load(Path(clip_dir) / d["ndvi_path"])
        rgb = sc.read_png(Path(clip_dir) / d["rgb_path"])
        ndvi_img = ndvi_to_gray(ndvi)
        for b in gt_by_fid[fid]["birds"]:
            if b["visible"]:
                draw_box(ndvi_img, b["bbox"], [255, 40, 40])
                draw_box(rgb, b["bbox"], [255, 40, 40])
        sc.write_png(out_dir / f"gt_ndvi_frame_{fid:06d}.png", ndvi_img)
        sc.write_png(out_dir / f"gt_rgb_frame_{fid:06d}.png", rgb)
    print(f"[label_from_sim] wrote {len(frame_ids)} GT overlay pairs -> {out_dir}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clip", type=Path, required=True, help="spike clip dir (has meta.json etc.)")
    ap.add_argument("--out", type=Path, default=None, help="ground_truth.json path")
    ap.add_argument("--verify", action="store_true",
                    help="cross-check projection vs generator_bbox_px and print disagreement")
    ap.add_argument("--overlay", type=Path, default=None,
                    help="dir to write GT-box overlay PNGs (closest-approach frame per bird)")
    args = ap.parse_args()

    gt, disagreements = build_ground_truth(args.clip)
    out = args.out or (args.clip / "ground_truth.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(gt, indent=1) + "\n")

    n_vis = sum(1 for f in gt["frames"] for b in f["birds"] if b["visible"])
    print(f"[label_from_sim] {len(gt['frames'])} frames, {n_vis} visible bird-boxes -> {out}")
    srcs = {}
    for f in gt["frames"]:
        for b in f["birds"]:
            if b["visible"]:
                srcs[b["label_src"]] = srcs.get(b["label_src"], 0) + 1
    if srcs:
        print(f"[label_from_sim] visible-box label provenance: "
              f"{', '.join(f'{v} {k}' for k, v in sorted(srcs.items()))}")

    if args.verify:
        if disagreements:
            diffs = [d[2] for d in disagreements]
            worst = max(disagreements, key=lambda x: x[2])
            print(f"[verify] independent projection vs generator_bbox_px over "
                  f"{len(disagreements)} in-frustum boxes:")
            print(f"[verify]   max corner disagreement = {max(diffs):.4f} px "
                  f"(frame {worst[0]}, {worst[1]}); mean = {np.mean(diffs):.4f} px")
            if max(diffs) < 1.0:
                print("[verify]   PASS: projection agrees with generator to sub-pixel -> GT trusted.")
            else:
                print("[verify]   WARN: >1px disagreement -- investigate before trusting metrics.")
        else:
            print("[verify] no in-frustum boxes to cross-check (unexpected).")

    if args.overlay is not None:
        # closest-approach frame per bird (min range while visible), for human inspection
        closest = {}
        for f in gt["frames"]:
            for b in f["birds"]:
                if b["visible"] and b["range_m"] is not None:
                    cur = closest.get(b["bird_id"])
                    if cur is None or b["range_m"] < cur[1]:
                        closest[b["bird_id"]] = (f["frame_id"], b["range_m"])
        write_overlays(args.clip, gt, args.overlay,
                       sorted({fid for fid, _ in closest.values()}))


if __name__ == "__main__":
    main()
