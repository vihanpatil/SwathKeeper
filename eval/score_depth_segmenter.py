#!/usr/bin/env python3
"""Label and SCORE the forward depth segmenter on the cluttered 85-frame dataset.

    python3 eval/score_depth_segmenter.py                     # full run: sweep, score, write
    python3 eval/score_depth_segmenter.py --no-write          # everything, no artifact on disk

Runs the pre-registered protocol of `docs/design/DEPTH_SEGMENTER_DESIGN.md` §4 against
`eval/results/depth_dataset_20260907` and writes
`eval/results/depth_segmenter_score_<UTC>.json` + the dataset's `REPORT.md`. Host-side, ~3 min,
numpy + scipy only.

--------------------------------------------------------------------------------------------------
THE LABELLER, AND WHY IT IS NOT THE STATION FILE
--------------------------------------------------------------------------------------------------
`docs/design/depth_segmenter_stations.json` carries `expected_px` / `expected_depth_m`, and they are
PREDICTIONS: they were computed with the camera at `cam_enu`, i.e. WITHOUT the 0.15 m
`fg_depth_mount` link offset. Every label here is recomputed from the RENDER's own readbacks --
camera world pose = vehicle model pose composed with the link pose, both as gz reported them -- and
the run STOPS if a rendered bird pixel disagrees with the recomputed prediction by more than
`TAU_PX`. A station file that disagrees with the render is a harness bug, not a relabel.

Three checks this scorer cannot fake, deliberately, because a gate that measures VALUES cannot catch
GEOMETRY (ADR-007 am. 5: every band gate passed while the camera faced the horizon):

  1. THE BIRD IS LOCATED BY DIFFING THE FRAME AGAINST ITS OWN GROUP'S NEGATIVE CONTROL, not by
     looking for whatever the detector found. Every camera pose in the dataset was rendered twice --
     once per station and once with all three birds parked at (-200, -190/-180/-200, 50) -- so the
     pixels that CHANGED are exactly the bird's rendered footprint, established with no detector in
     the loop. It also proves the occlusion stations: S058/S059/S060 change ZERO pixels, which is
     the assertion an occlusion test must make BEFORE it asserts a miss (an occlusion test that
     skips it passes for a detector that never detects anything).
  2. THE FORWARD AND INVERSE PROJECTIONS ARE DIFFERENT CODE. Labels come from this file's
     `project_to_pixel`; the un-projection that turns a box into a world point for the mapped-FP
     test is the FLIGHT primitive `depth_detect.depth_pixel_to_enu`, exercised on the render's own
     poses. `check_projection_roundtrip` requires them to agree, so a sign error in either shows up
     as a residual instead of as a consistent lie.
  3. THE WORLD MODEL IS CHECKED AGAINST THE RENDER. `raycast_world` computes what should be behind
     each bird pixel from the SDF's geometry (ground plane, 18 canopy spheres, 18 trunk cylinders);
     the negative control says what actually IS. The residual between them is reported, and a big
     one means the background CLASS labels are wrong even though every depth value is fine.

The negatives pull the other way from the FNR bar on the same eight frames: a segmenter that
hallucinated birds to pass the range ladder scores its own FP bar red on the same run.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import math
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from scipy import ndimage

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning import depth_detect                      # noqa: E402
from fieldguard_planning.depth_segment import (                   # noqa: E402
    DEFAULT_PARAMS, DEFAULT_PARAMS_PROVENANCE, MASK_TERMS, DepthSegmenter, DepthSegmenterParams,
    analytic_ground_ramp, border_residual_m, params_with,
)
from fieldguard_planning.geofence import GeofenceMap              # noqa: E402
from fieldguard_planning.ndvi_georef import CameraIntrinsics      # noqa: E402

SCHEMA_VERSION = "1.0"
DATASET_DIR = REPO_ROOT / "eval" / "results" / "depth_dataset_20260907"
STATION_FILE = REPO_ROOT / "docs" / "design" / "depth_segmenter_stations.json"
RESULTS_DIR = REPO_ROOT / "eval" / "results"

# --- the matcher's two constants, DESIGN §4.2, fixed before any frame was scored ----------------
TAU_PX = 5.0        # box midpoint vs expected pixel. The NDVI mount's live-verified geometry
                    # residual is 2.2 px; 5 px is that with headroom, and small enough that a
                    # canopy 20 px away cannot claim the match.
EPS_M = 0.5         # |median depth - expected NEAR-SURFACE depth|. PROBE B measured the plateau's
                    # own depths to 0.02-0.16 m of true, so this is ~3x the observed error. NOT
                    # decoration: the merge failure is a centroid hit carrying the BACKGROUND's
                    # depth, and a one-clause matcher would score it as a success.

BIRD_RADIUS_M = 0.18          # config/birds/farm_world_birds.json; the world's own value
FAR_CLIP_M = 60.0
NEAR_CLIP_M = 0.1
MISSION_ALT_M = 15.0
BOOKED_ACQ_M = 46.0           # ADR-020 am. 2, the number this run can only LOWER
BREAKEVEN_5MPS_M = 33.591     # ADR-020 am. 2's pre-registered invalidation at 5 m/s
GEOFENCE_TOP_M = 4.8          # tree height 3.8 + the annotator's 1.0 m vertical margin

# --- the pre-registered sweep ladders (DESIGN §3.2) ---------------------------------------------
K_LADDER = (15, 17, 21, 25)
MARGIN_LADDER = (0.5, 0.75, 1.0, 1.2, 1.5, 1.75, 2.0, 2.5, 3.0)
MIN_AREA_LADDER = (4, 6, 8, 10, 12, 14, 16, 20)
OPEN_ITER_LADDER = (0, 1)
SWEEP_MAX_BOXES = 512         # effectively uncapped while the OTHER constants are being chosen,
                              # so a truncation can never be mistaken for a detector miss

# --- the world, from sim/worlds/farmguard_field.sdf ---------------------------------------------
GROUND_EXTENT_M = (125.0, 110.0)
GROUND_CENTRE_M = (37.5, 30.0)
TREE_X_M = (15.0, 40.0, 65.0)
TREE_Y_M = (5.0, 15.0, 25.0, 35.0, 45.0, 55.0)
CANOPY_CENTRE_Z_M, CANOPY_R_M = 2.5, 1.3
TRUNK_R_M, TRUNK_TOP_Z_M = 0.15, 1.5

FIXTURE_STATIONS = ("S015", "S026", "S036", "S040", "S061", "S080")
FIXTURE_WHY = {
    "S015": "sky, 46 m, down the worst-clutter lane -- the far end of the FNR bar",
    "S026": "ground_band MERGE: bird 5 m below cruise at 14 m, projected into the ground band",
    "S036": "trunk_edge MERGE: the bird's footprint straddles a trunk base and the ground behind it",
    "S040": "canopy-backed threat bird at 26 m",
    "S061": "NEGATIVE CONTROL, P1 worst-clutter lane -- no bird in the world at all",
    "S080": "PITCHED arm: -12.5 deg nose-down, the level-camera transfer gap made a measurement",
}


# ==================================================================================================
# Geometry. Every function here takes a READBACK, never a command.
# ==================================================================================================

def quat_to_matrix(qx: float, qy: float, qz: float, qw: float) -> np.ndarray:
    """(x, y, z, w) -> 3x3 rotation, child frame into parent. Normalised first: gz's readbacks come
    back at 1e-16 of unit and a silently un-normalised quaternion scales every range."""
    n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if n <= 0.0:
        raise ValueError("zero quaternion in a readback")
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    return np.array([
        [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
        [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
        [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
    ], dtype=float)


def parse_readback(s: str) -> Tuple[np.ndarray, np.ndarray, Tuple[float, float, float, float]]:
    """"x y z yaw_deg qx qy qz qw" -> (position, rotation matrix, quaternion xyzw)."""
    p = [float(x) for x in s.split()]
    if len(p) != 8:
        raise ValueError(f"readback must have 8 fields, got {len(p)}: {s!r}")
    return np.array(p[0:3]), quat_to_matrix(p[4], p[5], p[6], p[7]), (p[4], p[5], p[6], p[7])


def camera_world_pose(row: dict) -> Tuple[np.ndarray, np.ndarray]:
    """Camera world pose = MODEL pose composed with the LINK pose, both from readbacks.

    The design note is explicit about why the model pose alone will not do: the wrapper's base_link
    sits above the model origin and the depth link sits 0.15 m ahead of it, so labelling with the
    commanded pose bakes that bias into every expected pixel -- the ADR-007 am. 5 family of defect,
    a value that is correct under a geometry nobody checked."""
    vp, vR, _ = parse_readback(row["vehicle_readback"])
    lp, lR, _ = parse_readback(row["depth_link_readback_parent_relative"])
    return vp + vR @ lp, vR @ lR


def project_to_pixel(cam_p: np.ndarray, cam_R: np.ndarray, point: Sequence[float],
                     intr: CameraIntrinsics) -> Optional[Tuple[float, float, float]]:
    """World point -> (u, v, pinhole Z-depth), or None if it is behind the camera.

    Gazebo's camera convention, and this is the whole derivation: the optical axis is the LINK's
    +X, image right is link -Y and image down is link -Z. So with `d` the point in link axes,
    `u = cx + fx * (-d_y)/d_x` and `v = cy + fy * (-d_z)/d_x`, and the stored depth is `d_x`
    itself. Verified on the render: S001 lands at (320.00, 240.00) with a near-surface depth of
    13.82 m against a measured `min_finite_m` of 13.8210."""
    d = cam_R.T @ (np.asarray(point, dtype=float) - cam_p)
    if d[0] <= 0.0:
        return None
    return (intr.cx + intr.fx * (-d[1]) / d[0],
            intr.cy + intr.fy * (-d[2]) / d[0],
            float(d[0]))


def pixel_ray_world(u: np.ndarray, v: np.ndarray, cam_R: np.ndarray,
                    intr: CameraIntrinsics) -> np.ndarray:
    """Pixels -> world ray directions scaled so the ray PARAMETER IS THE PINHOLE Z-DEPTH.

    Same ray `depth_detect.depth_pixel_to_enu` builds (`pixel_to_camera_ray` then
    `DEPTH_OPTICAL_TO_BODY`), written here in array form for the ray-cast; the round-trip check
    pins the two together."""
    ray = np.stack([np.ones_like(np.asarray(u, dtype=float)),
                    -(np.asarray(u, dtype=float) - intr.cx) / intr.fx,
                    -(np.asarray(v, dtype=float) - intr.cy) / intr.fy], axis=-1)
    return ray @ cam_R.T


def raycast_world(cam_p: np.ndarray, dirs: np.ndarray) -> Tuple[np.ndarray, List[str]]:
    """Ray-cast the COMMITTED world: ground plane + 18 canopy spheres + 18 trunk cylinders.

    Returns (pinhole Z-depth per ray, class per ray) with `+inf`/`sky` for a ray that hits nothing
    or whose hit is beyond the EUCLIDEAN far cull -- gz culls on `|point|` while it stores `point.x`,
    which is why the cull test multiplies by `|dir|` (dir is scaled to unit Z-depth)."""
    n = dirs.shape[0]
    best = np.full(n, np.inf)
    cls = ["sky"] * n

    def take(t: np.ndarray, ok: np.ndarray, name: str) -> None:
        sel = ok & (t > 0.0) & (t < best)
        best[sel] = t[sel]
        for i in np.nonzero(sel)[0]:
            cls[i] = name

    dz = dirs[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(dz < 0.0, -cam_p[2] / dz, np.inf)
    hit = cam_p[None, :] + t[:, None] * dirs
    ok = (np.isfinite(t) & (np.abs(hit[:, 0] - GROUND_CENTRE_M[0]) <= GROUND_EXTENT_M[0] / 2.0)
          & (np.abs(hit[:, 1] - GROUND_CENTRE_M[1]) <= GROUND_EXTENT_M[1] / 2.0))
    take(np.where(np.isfinite(t), t, np.inf), ok, "ground_band")

    for tx in TREE_X_M:
        for ty in TREE_Y_M:
            c = np.array([tx, ty, CANOPY_CENTRE_Z_M])
            e = cam_p - c
            a = (dirs * dirs).sum(axis=1)
            b = 2.0 * (dirs @ e)
            cc = float(e @ e) - CANOPY_R_M ** 2
            disc = b * b - 4 * a * cc
            with np.errstate(invalid="ignore"):
                sq = np.sqrt(np.where(disc >= 0.0, disc, 0.0))
                t = (-b - sq) / (2 * a)
            take(np.where(disc >= 0.0, t, np.inf), disc >= 0.0, "canopy")

            exy = cam_p[:2] - np.array([tx, ty])
            a2 = (dirs[:, :2] ** 2).sum(axis=1)
            b2 = 2.0 * (dirs[:, :2] @ exy)
            c2 = float(exy @ exy) - TRUNK_R_M ** 2
            disc2 = b2 * b2 - 4 * a2 * c2
            with np.errstate(invalid="ignore", divide="ignore"):
                sq2 = np.sqrt(np.where(disc2 >= 0.0, disc2, 0.0))
                t2 = np.where(a2 > 0.0, (-b2 - sq2) / (2 * a2), np.inf)
            zh = cam_p[2] + t2 * dirs[:, 2]
            take(np.where(disc2 >= 0.0, t2, np.inf),
                 (disc2 >= 0.0) & (zh >= 0.0) & (zh <= TRUNK_TOP_Z_M), "trunk")

    slant = best * np.linalg.norm(dirs, axis=1)
    culled = slant > FAR_CLIP_M
    best[culled] = np.inf
    for i in np.nonzero(culled)[0]:
        cls[i] = "sky"
    return best, cls


# ==================================================================================================
# Dataset + labels
# ==================================================================================================

@dataclass
class Station:
    sid: str
    group: int
    station: dict
    row: dict
    frame: np.ndarray
    neg_id: str
    cam_p: np.ndarray
    cam_R: np.ndarray
    veh_pos: Tuple[float, float, float]
    veh_quat: Tuple[float, float, float, float]
    intr: CameraIntrinsics
    # label, recomputed
    in_frame: bool
    expected_px: Optional[Tuple[float, float]]
    bird_centre_depth_m: Optional[float]
    expected_depth_m: Optional[float]        # NEAR SURFACE: centre - 0.18
    expected_r_px: Optional[float]
    rendered_px: Optional[Tuple[float, float]]
    rendered_area_px: int
    bird_mask: np.ndarray                    # the negative-control diff itself: WHICH pixels are the
                                             # bird. `rendered_area_px` is its sum; the mask is what
                                             # `flip_block` needs to say how much of a matched
                                             # component is actually the bird.
    rendered_min_depth_m: Optional[float]
    label_residual_px: Optional[float]
    background: str
    background_render_depth_m: Optional[float]
    background_raycast_depth_m: Optional[float]
    standoff_m: Optional[float]
    occluded: bool
    pass_bar: str
    range_m: Optional[float]

    @property
    def is_negative(self) -> bool:
        return self.pass_bar == "FP_zero_unmapped" or self.sid == "S085"

    @property
    def is_pitched(self) -> bool:
        return self.group == 9


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_dataset(ddir: Path) -> Tuple[List[Station], dict]:
    rows = [json.loads(l) for l in (ddir / "labels.jsonl").read_text().splitlines() if l.strip()]
    groups = {g["group"]: g for g in
              (json.loads(l) for l in (ddir / "groups.jsonl").read_text().splitlines() if l.strip())}
    intrs = {}
    for gid, g in groups.items():
        ci = json.loads((ddir / g["camera_info"]).read_text())
        k = ci["intrinsics"]["k"]
        intrs[gid] = CameraIntrinsics(width_px=int(ci["width"]), height_px=int(ci["height"]),
                                      fx=float(k[0]), fy=float(k[4]),
                                      cx=float(k[2]), cy=float(k[5]))
    negs = {}
    for r in rows:
        if str(r["station"].get("background", "")).startswith("none_target"):
            negs[r["group"]] = r["id"]
    missing = [g for g in groups if g not in negs]
    if missing:
        raise RuntimeError(f"groups {missing} have no negative-control frame; the labeller locates "
                           f"the rendered bird by DIFFING against one, so it cannot label them")

    frames: Dict[str, np.ndarray] = {}
    for r in rows:
        f = np.load(ddir / r["frame"]["file"])
        if f.dtype != np.float32 or f.shape != tuple(r["frame"]["shape"]):
            raise RuntimeError(f"{r['id']}: frame is {f.dtype} {f.shape}, labels say "
                               f"{r['frame']['dtype']} {tuple(r['frame']['shape'])}")
        got = hashlib.sha1(f.tobytes()).hexdigest()
        if got != r["frame"]["sha1"]:
            raise RuntimeError(f"{r['id']}: frame sha1 {got} != labels' {r['frame']['sha1']} -- the "
                               f"frames on disk are not the frames that were labelled")
        frames[r["id"]] = f

    stations = [label_station(r, groups, intrs, negs, frames) for r in rows]
    meta = {
        "dataset_dir": str(ddir.relative_to(REPO_ROOT)),
        "n_frames": len(rows),
        "labels_sha256": sha256_of(ddir / "labels.jsonl"),
        "groups_sha256": sha256_of(ddir / "groups.jsonl"),
        "stations_file": str(STATION_FILE.relative_to(REPO_ROOT)),
        "stations_file_sha256": sha256_of(STATION_FILE),
        "n_distinct_frame_sha1": len({r["frame"]["sha1"] for r in rows}),
        "negative_control_per_group": {str(k): v for k, v in sorted(negs.items())},
    }
    return stations, meta


def label_station(row: dict, groups: dict, intrs: dict, negs: dict,
                  frames: Dict[str, np.ndarray]) -> Station:
    st = row["station"]
    gid = row["group"]
    intr = intrs[gid]
    cam_p, cam_R = camera_world_pose(row)
    vp, _, vq = parse_readback(row["vehicle_readback"])
    frame = frames[row["id"]]
    neg_id = negs[gid]
    neg = frames[neg_id]

    bird = row["bird_0_readback"]["enu"]
    proj = project_to_pixel(cam_p, cam_R, bird, intr)
    in_frame = bool(proj is not None and 0.0 <= proj[0] < intr.width_px
                    and 0.0 <= proj[1] < intr.height_px)
    exp_px = (proj[0], proj[1]) if proj is not None else None
    zc = proj[2] if proj is not None else None
    zsurf = (zc - BIRD_RADIUS_M) if zc is not None else None
    r_px = (intr.fx * BIRD_RADIUS_M / zc) if zc else None

    # THE RENDERED BIRD, located with no detector in the loop: the pixels that changed against this
    # group's negative control, restricted to the ones that got NEARER (a bird can only occlude).
    if row["id"] == neg_id:
        diff = np.zeros(frame.shape, dtype=bool)
    else:
        with np.errstate(invalid="ignore"):
            diff = np.isfinite(frame) & (~np.isfinite(neg) | (frame < neg - 1e-3))
    area = int(diff.sum())
    rend_px = None
    rend_min = None
    resid = None
    if area:
        ys, xs = np.nonzero(diff)
        rend_px = (0.5 * (float(xs.min()) + float(xs.max()) + 1.0),
                   0.5 * (float(ys.min()) + float(ys.max()) + 1.0))
        rend_min = float(frame[diff].min())
        if exp_px is not None:
            resid = math.hypot(rend_px[0] - exp_px[0], rend_px[1] - exp_px[1])

    # BACKGROUND: what the render says is behind the bird's own footprint (the negative control),
    # classified by ray-casting the SDF geometry at the same pixels. Depth from the render, class
    # from the model, and the disagreement between them is reported rather than assumed away.
    bg_class, bg_render, bg_ray = "none", None, None
    if area:
        ys, xs = np.nonzero(diff)
        sel = slice(None) if len(ys) <= 400 else slice(0, 400)
        uu = xs[sel].astype(float) + 0.5
        vv = ys[sel].astype(float) + 0.5
        dirs = pixel_ray_world(uu, vv, cam_R, intr)
        rz, rc = raycast_world(cam_p, dirs)
        vals = neg[ys[sel], xs[sel]]
        finite = np.isfinite(vals)
        bg_render = float(np.median(vals[finite])) if finite.any() else float("inf")
        bg_ray = float(np.median(rz[np.isfinite(rz)])) if np.isfinite(rz).any() else float("inf")
        counts: Dict[str, int] = {}
        for c in rc:
            counts[c] = counts.get(c, 0) + 1
        dom = max(counts, key=lambda k: counts[k])
        bg_class = dom if len(counts) == 1 else f"{dom}_edge"
    elif st.get("background", "").startswith("none_target"):
        bg_class = "none_target_parked_out_of_world"
    else:
        bg_class = "occluded"

    standoff = None
    if bg_render is not None and zc is not None and math.isfinite(bg_render):
        standoff = bg_render - zc
    occluded = bool(in_frame and area == 0 and row["id"] != neg_id)

    return Station(
        sid=row["id"], group=gid, station=st, row=row, frame=frame, neg_id=neg_id,
        cam_p=cam_p, cam_R=cam_R, veh_pos=(vp[0], vp[1], vp[2]), veh_quat=vq, intr=intr,
        in_frame=in_frame, expected_px=exp_px, bird_centre_depth_m=zc, expected_depth_m=zsurf,
        expected_r_px=r_px, rendered_px=rend_px, rendered_area_px=area, bird_mask=diff,
        rendered_min_depth_m=rend_min, label_residual_px=resid, background=bg_class,
        background_render_depth_m=bg_render, background_raycast_depth_m=bg_ray,
        standoff_m=standoff, occluded=occluded, pass_bar=st.get("pass_bar", "diagnostic"),
        range_m=(round(zc, 2) if zc is not None else None))


def check_labeller(stations: Sequence[Station]) -> dict:
    """The run STOPS if a rendered bird pixel disagrees with the recomputed prediction by more than
    TAU_PX, and if a station file prediction disagrees with the recompute by more than TAU_PX."""
    worst_render, worst_render_id = 0.0, None
    worst_file, worst_file_id = 0.0, None
    worst_ray, worst_ray_id = 0.0, None
    bad: List[str] = []
    for s in stations:
        if s.label_residual_px is not None:
            if s.label_residual_px > worst_render:
                worst_render, worst_render_id = s.label_residual_px, s.sid
            if s.label_residual_px > TAU_PX:
                bad.append(f"{s.sid}: rendered bird {s.rendered_px} vs recomputed {s.expected_px} "
                           f"= {s.label_residual_px:.2f} px > tau {TAU_PX}")
        fp = s.station.get("expected_px")
        if fp and s.expected_px is not None:
            d = math.hypot(fp[0] - s.expected_px[0], fp[1] - s.expected_px[1])
            if d > worst_file:
                worst_file, worst_file_id = d, s.sid
        if (s.background_render_depth_m is not None and s.background_raycast_depth_m is not None
                and math.isfinite(s.background_render_depth_m)
                and math.isfinite(s.background_raycast_depth_m)):
            d = abs(s.background_render_depth_m - s.background_raycast_depth_m)
            if d > worst_ray:
                worst_ray, worst_ray_id = d, s.sid
    if bad:
        raise RuntimeError("LABELLER DISAGREES WITH THE RENDER -- harness bug, not a relabel:\n  "
                           + "\n  ".join(bad))
    return {
        "tau_px": TAU_PX,
        "max_rendered_vs_recomputed_px": round(worst_render, 4), "at_station": worst_render_id,
        "max_stationfile_vs_recomputed_px": round(worst_file, 4), "stationfile_worst": worst_file_id,
        "max_raycast_vs_render_background_m": round(worst_ray, 4), "raycast_worst": worst_ray_id,
        "note": ("the rendered bird is located by DIFFING each frame against its own group's "
                 "negative control, so no detector is in the labelling loop; the ray-cast column "
                 "is the SDF world model checked against what the renderer actually drew"),
    }


def check_projection_roundtrip(stations: Sequence[Station]) -> dict:
    """Forward (this file) vs inverse (`depth_detect.depth_pixel_to_enu`, the FLIGHT primitive).
    Two different code paths, and they must agree on every visible station or one of them is wrong
    in a way no value-only gate can see."""
    worst, worst_id = 0.0, None
    for s in stations:
        if s.expected_px is None or s.bird_centre_depth_m is None:
            continue
        back = depth_detect.depth_pixel_to_enu(
            s.expected_px[0], s.expected_px[1], s.bird_centre_depth_m, s.intr,
            s.veh_pos, s.veh_quat)
        truth = np.asarray(s.row["bird_0_readback"]["enu"], dtype=float)
        d = float(np.linalg.norm(np.asarray(back) - truth))
        if d > worst:
            worst, worst_id = d, s.sid
    if worst > 1e-3:
        raise RuntimeError(f"forward/inverse projection disagree by {worst:.6f} m at {worst_id}")
    return {"max_roundtrip_error_m": round(worst, 9), "at_station": worst_id,
            "inverse_primitive": "fieldguard_planning.depth_detect.depth_pixel_to_enu"}


# ==================================================================================================
# Scoring
# ==================================================================================================

def unproject_box(s: Station, box: Sequence[float], depth_m: float) -> Tuple[float, float, float]:
    return depth_detect.depth_pixel_to_enu(0.5 * (box[0] + box[2]), 0.5 * (box[1] + box[3]),
                                           depth_m, s.intr, s.veh_pos, s.veh_quat)


def classify_fp(s: Station, box: Sequence[float], depth_m: float, gmap: GeofenceMap) -> dict:
    """A false positive is MAPPED if it is real, known clutter: inside a tree's 3D geofence (1.0 m
    vertical margin -- the same `unsafe_obstacle_3d` volume the executor's setpoint backstop runs)
    or at or below the geofence top. Mapped FPs are REPORTED, NOT BARRED: they are real near
    objects, the policy's +/-6 m vertical band around a 15 m cruise already excludes them, and
    suppressing them in pixel space is what DESIGN §1.2 forbids."""
    pos = unproject_box(s, box, depth_m)
    obs = gmap.unsafe_obstacle_3d(pos, 1.0)
    below = bool(pos[2] <= GEOFENCE_TOP_M)
    return {"box": [round(float(c), 1) for c in box], "depth_m": round(float(depth_m), 3),
            "enu": [round(float(c), 2) for c in pos],
            "mapped_obstacle": (None if obs is None else obs.id),
            "below_geofence_top": below,
            "mapped_by": ("tree_geofence" if obs is not None else
                          ("below_geofence_top" if below else None)),
            "mapped": bool(obs is not None or below)}


def score_station(s: Station, boxes: Sequence[Tuple[Sequence[float], float]],
                  gmap: GeofenceMap, margin_m: float) -> dict:
    """One station's row.

    MATCHING IS DESIGN §4.2's STRICT TWO-CLAUSE RULE, DELIBERATELY, AND ALGORITHM §7.2's one-to-many
    amendment is NOT applied to `matched`: a component only matches when its box midpoint is within
    TAU_PX of the expected pixel AND its median depth is within EPS_M of the bird's near surface.
    The amendment exists for the rim-arc regime -- a bird nearer than the ~12.5 m crossover comes
    back as four arcs, none of them centred on the bird -- and NO station in this dataset is in it
    (the nearest is 14 m). Loosening the matcher to a footprint disc would only make it easier to
    call something a hit, on a range the data does not cover, so the strict rule stands and the
    `fragments` counter records how many components fell inside the footprint disc without matching.

    MERGE MISLABEL, corrected: a box at the bird's PIXEL carrying the BACKGROUND's depth is only the
    failure-that-looks-like-success when the bird was not ALSO returned as its own component. The
    first scoring pass flagged it unconditionally, which scored a correct SPLIT (bird component +
    canopy component, both right) as the merge it is the fix for -- and that miscount was the stated
    reason for adopting `link_break=False`. The neighbour is still recorded, under its own name, so
    the information is kept without being scored as a failure."""
    row = {
        "id": s.sid, "group": s.group, "pass_bar": s.pass_bar, "background": s.background,
        "background_declared": s.station.get("background"),
        "range_m": s.range_m, "expected_px": (None if s.expected_px is None else
                                              [round(s.expected_px[0], 2), round(s.expected_px[1], 2)]),
        "expected_depth_m": (None if s.expected_depth_m is None else round(s.expected_depth_m, 3)),
        "expected_r_px": (None if s.expected_r_px is None else round(s.expected_r_px, 2)),
        "rendered_area_px": s.rendered_area_px,
        "label_residual_px": (None if s.label_residual_px is None else round(s.label_residual_px, 3)),
        "background_depth_m": (None if s.background_render_depth_m is None
                               else (None if math.isinf(s.background_render_depth_m)
                                     else round(s.background_render_depth_m, 3))),
        "standoff_m": (None if s.standoff_m is None else round(s.standoff_m, 3)),
        "sub_margin": (s.standoff_m is not None and s.standoff_m <= margin_m),
        "occluded": s.occluded, "in_frame": s.in_frame, "n_boxes": len(boxes),
    }
    matched = False
    best = None
    fragments = 0
    merge = None
    if s.expected_px is not None and s.expected_depth_m is not None and not s.is_negative:
        eu, ev = s.expected_px
        rpx = s.expected_r_px or 0.0
        for box, dm in boxes:
            mid = (0.5 * (box[0] + box[2]), 0.5 * (box[1] + box[3]))
            dist = math.hypot(mid[0] - eu, mid[1] - ev)
            depth_err = float(dm) - s.expected_depth_m
            if dist <= TAU_PX and abs(depth_err) <= EPS_M:
                if best is None or dist < best["centroid_err_px"]:
                    best = {"centroid_err_px": dist, "depth_err_m": depth_err,
                            "depth_m": float(dm), "box": [float(c) for c in box]}
                matched = True
            elif dist <= rpx + TAU_PX:
                fragments += 1
            if (dist <= TAU_PX and s.background_render_depth_m is not None
                    and math.isfinite(s.background_render_depth_m)
                    and abs(float(dm) - s.background_render_depth_m) <= EPS_M
                    and abs(depth_err) > EPS_M):
                merge = {"depth_m": float(dm), "background_depth_m": s.background_render_depth_m}
    row["matched"] = matched
    row["centroid_err_px"] = None if best is None else round(best["centroid_err_px"], 3)
    row["depth_err_m"] = None if best is None else round(best["depth_err_m"], 4)
    row["matched_depth_m"] = None if best is None else round(best["depth_m"], 3)
    row["matched_box"] = None if best is None else [float(x) for x in best["box"]]
    row["fragments"] = fragments
    # THE CORRECTION: a box at the bird's pixel carrying the background's depth is a MISLABEL only
    # if the bird was not separately matched. If it was, this is a correct SPLIT and gets its own,
    # unbarred name -- reported because it is exactly the geometry the median-flip metric watches.
    row["merge_mislabel"] = merge if (merge is not None and not matched) else None
    row["separated_neighbour_at_background_depth"] = (merge if (merge is not None and matched)
                                                      else None)

    # False positives are only scored where the world contains no target: the negatives.
    if s.is_negative:
        det = [classify_fp(s, b, d, gmap) for b, d in boxes]
        row["fp_total"] = len(det)
        row["fp_mapped"] = sum(1 for d in det if d["mapped"])
        row["fp_unmapped"] = sum(1 for d in det if not d["mapped"])
        row["fp_mapped_by_tree_geofence"] = sum(1 for d in det if d["mapped_by"] == "tree_geofence")
        row["fp_mapped_by_ground"] = sum(1 for d in det if d["mapped_by"] == "below_geofence_top")
        row["fp_unmapped_detail"] = [d for d in det if not d["mapped"]][:12]
    return row


def run(stations: Sequence[Station], params: DepthSegmenterParams, gmap: GeofenceMap,
        seg: Optional[DepthSegmenter] = None) -> Tuple[List[dict], DepthSegmenter]:
    seg = seg or DepthSegmenter(params)
    return [score_station(s, seg(s.frame), gmap, params.margin_m) for s in stations], seg


def fnr_block(rows: Sequence[dict], margin_m: float) -> dict:
    """FNR over the FNR_zero stations, per background class x range bin, CONDITIONED on
    `standoff_m > margin_m` (ALGORITHM §7.2: a bird inside the resolving standoff is a known
    physical limit, not a detector miss). Every rate carries its denominator."""
    bar = [r for r in rows if r["pass_bar"] == "FNR_zero"]
    detectable = [r for r in bar if not r["occluded"] and not r["sub_margin"]]
    excluded = [r["id"] for r in bar if r["sub_margin"]]
    misses = [r["id"] for r in detectable if not r["matched"]]
    cells: Dict[str, dict] = {}
    for r in detectable:
        rng = r["range_m"] or 0.0
        b = f"{int(rng // 10) * 10}-{int(rng // 10) * 10 + 10}m"
        key = f"{r['background']} | {b}"
        c = cells.setdefault(key, {"n": 0, "missed": 0, "ids": []})
        c["n"] += 1
        if not r["matched"]:
            c["missed"] += 1
            c["ids"].append(r["id"])
    for c in cells.values():
        c["fnr"] = round(c["missed"] / c["n"], 4) if c["n"] else None
    return {
        "denominator_all_FNR_zero_stations": len(bar),
        "denominator_detectable": len(detectable),
        "conditioned_on": f"standoff_m > margin_m ({margin_m} m), unoccluded",
        "excluded_by_condition": excluded,
        "misses": misses,
        "fnr": (round(len(misses) / len(detectable), 4) if detectable else None),
        "per_background_x_range": cells,
        "bar": "0 misses",
        "pass": (len(misses) == 0 and len(detectable) > 0),
    }


def fp_block(rows: Sequence[dict], pitched: bool = False) -> dict:
    negs = [r for r in rows if "fp_total" in r and ((r["group"] == 9) == pitched)]
    n = len(negs)
    unmapped = sum(r["fp_unmapped"] for r in negs)
    mapped = sum(r["fp_mapped"] for r in negs)
    return {
        "denominator_frames": n,
        "unmapped_fp_total": unmapped,
        "unmapped_fp_per_frame": (round(unmapped / n, 4) if n else None),
        "mapped_fp_total": mapped,
        "mapped_fp_per_frame": (round(mapped / n, 4) if n else None),
        "mapped_by_tree_geofence": sum(r.get("fp_mapped_by_tree_geofence", 0) for r in negs),
        "mapped_by_ground_or_below_geofence_top": sum(r.get("fp_mapped_by_ground", 0)
                                                      for r in negs),
        "per_frame": {r["id"]: {"total": r["fp_total"], "mapped": r["fp_mapped"],
                                "unmapped": r["fp_unmapped"]} for r in negs},
        "unmapped_examples": [d for r in negs for d in r.get("fp_unmapped_detail", [])][:12],
        "bar": "unmapped <= 0.05 /frame",
        "pass": (n > 0 and unmapped / n <= 0.05),
        "mapped_note": ("mapped FPs are REPORTED, NOT BARRED: a cluttered lane pose is nothing but "
                        "real near canopies, the policy's +/-6 m band around a 15 m cruise already "
                        "excludes them, and depth_detect rule 9 forbids suppressing them here"),
    }


def _p(vals: Sequence[float], q: float) -> Optional[float]:
    if not vals:
        return None
    v = sorted(vals)
    return float(v[min(len(v) - 1, max(0, math.ceil(q * len(v)) - 1))])


def accuracy_block(rows: Sequence[dict]) -> dict:
    errs = [abs(r["depth_err_m"]) for r in rows if r.get("depth_err_m") is not None]
    cent = [r["centroid_err_px"] for r in rows if r.get("centroid_err_px") is not None]
    signed = [r["depth_err_m"] for r in rows if r.get("depth_err_m") is not None]
    with_c = [r for r in rows if r.get("centroid_err_px") is not None]
    worst_c = max(with_c, key=lambda r: r["centroid_err_px"]) if with_c else None
    return {
        "worst_centroid_station": (None if worst_c is None else worst_c["id"]),
        "worst_centroid_tau_headroom_px": (None if worst_c is None
                                           else round(TAU_PX - worst_c["centroid_err_px"], 3)),
        "denominator_matches": len(errs),
        "range_error_median_m": (round(float(np.median(errs)), 4) if errs else None),
        "range_error_p95_m": (None if not errs else round(_p(errs, 0.95), 4)),
        "range_error_max_m": (round(max(errs), 4) if errs else None),
        "range_error_signed_min_m": (round(min(signed), 4) if signed else None),
        "range_error_signed_max_m": (round(max(signed), 4) if signed else None),
        "centroid_error_p95_px": (None if not cent else round(_p(cent, 0.95), 4)),
        "centroid_error_max_px": (round(max(cent), 4) if cent else None),
        "bar": "range error p95 <= 0.5 m",
        "pass": (bool(errs) and _p(errs, 0.95) <= 0.5),
        "context": ("the monocular apparent-size ray this replaces measured 1.65 m MEDIAN range "
                    "error on the adopted NDVI clip"),
    }


def merge_block(rows: Sequence[dict]) -> dict:
    hits = [r["id"] for r in rows if r.get("merge_mislabel")]
    split = [r["id"] for r in rows if r.get("separated_neighbour_at_background_depth")]
    scored = [r for r in rows if r["expected_depth_m"] is not None and not r["occluded"]]
    return {"denominator_visible_bird_stations": len(scored), "merge_mislabels": hits,
            "count": len(hits), "bar": "0", "pass": (len(hits) == 0),
            "separated_neighbour_at_background_depth": split,
            "separated_neighbour_count": len(split),
            "definition": ("a box whose midpoint is within tau of the bird, whose median depth is "
                           "within eps of the BACKGROUND and not of the bird, AND where the bird "
                           "was not separately matched -- the failure that looks like success"),
            "separated_neighbour_note": (
                "the same pixel/depth geometry WITH the bird also returned as its own component is "
                "a correct SPLIT, not a mislabel, and is counted here instead of in the bar. The "
                "first scoring pass conflated the two, which made a strictly better detector score "
                "the 0-merge bar red and became the stated reason for an adopted constant")}


def component_pixels(params: DepthSegmenterParams,
                     frame: np.ndarray) -> List[Tuple[Tuple[float, float, float, float],
                                                      float, np.ndarray]]:
    """The PIXELS behind each returned box: (box, median depth, boolean mask), nearest-first.

    Rebuilt from the segmenter's OWN `_mask`/`_link_break` on a THROWAWAY instance -- so the scored
    segmenter's counters stay clean, and so this is not a second implementation of the operator that
    could agree with the artifact while disagreeing with the flight module. The only steps written
    out here are the two scipy one-liners `__call__` uses (`binary_opening`, `label`), and the
    caller asserts the rebuilt (box, depth) list is EXACTLY what `__call__` returned, which is what
    makes that faithfulness a measurement rather than a claim."""
    seg = DepthSegmenter(params)
    cand, zb = seg._mask(frame)                                          # noqa: SLF001 -- see above
    if params.link_break:
        cand = seg._link_break(cand, zb)                                 # noqa: SLF001
    if params.open_iter > 0:
        cand = ndimage.binary_opening(cand, structure=ndimage.generate_binary_structure(2, 1),
                                      iterations=int(params.open_iter))
    labels, _ = ndimage.label(cand, structure=ndimage.generate_binary_structure(2, 2))
    out: List[Tuple[Tuple[float, float, float, float], float, np.ndarray]] = []
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None:
            continue
        sub = labels[sl] == i
        if int(sub.sum()) < params.min_area_px:
            continue
        m = np.zeros(frame.shape, dtype=bool)
        m[sl] = sub
        out.append(((float(sl[1].start), float(sl[0].start),
                     float(sl[1].stop), float(sl[0].stop)),
                    float(np.median(frame[sl][sub])), m))
    out.sort(key=lambda r: (r[1], r[0][1], r[0][0]))
    return out[:params.max_boxes]


def flip_block(stations: Sequence[Station], rows: Sequence[dict],
               params: DepthSegmenterParams) -> dict:
    """HOW MUCH OF EACH MATCHED COMPONENT IS ACTUALLY THE BIRD -- reported, not barred.

    The returned depth is the component's MEDIAN, so a component that is part bird and part
    background reports the bird's depth only while the bird holds a majority of its pixels. That is
    a CLIFF, not a drift: lose the majority and the same detection reports the background's depth
    instead -- at S042 a bird at 29.96 m would be published at 54.5 m, 24.7 m too far, i.e. no
    threat. `range_error_p95` cannot see it, because until the flip happens the range is right to
    within 0.14 m.

    So the margin is measured in PIXELS and reported per station. Bird pixels come from the
    negative-control diff the labeller already has -- no detector in that loop.

      * `bird_pixel_fraction` = bird px / component px.
      * `px_to_median_flip`   = bird_px - (component_px//2 + 1): how many of the component's pixels
        could change ownership (a sub-pixel shift, antialiasing, a moving bird) at CONSTANT component
        size before the median stops being the bird's. Only meaningful when `other_px > 0` -- a
        component that is all bird has no farther population to flip to, and is reported as null.
      * `flipped_depth_m` is what the detection would say after the flip: the number that makes this
        a safety metric rather than a curiosity.

    NOT A BAR. It is measured for the first time in this fix round, and inventing a threshold in the
    same pass that first sees the number is how a bar gets fitted to its own data. It is on the
    record so the next round can pre-register one."""
    by_id = {s.sid: s for s in stations}
    per: List[dict] = []
    for r in rows:
        if not r.get("matched") or r.get("matched_box") is None:
            continue
        s = by_id[r["id"]]
        if s.rendered_area_px == 0:
            continue
        comps = component_pixels(params, s.frame)
        rebuilt = [([b[0], b[1], b[2], b[3]], d) for b, d, _ in comps]
        got = DepthSegmenter(params)(s.frame)
        if rebuilt != got:
            raise RuntimeError(f"{s.sid}: the component rebuild disagrees with the segmenter's own "
                               f"output ({len(rebuilt)} vs {len(got)} boxes) -- the pixel-level "
                               f"numbers below would be about a different detector")
        want = tuple(r["matched_box"])
        hit = [(b, d, m) for b, d, m in comps if b == want]
        if not hit:
            raise RuntimeError(f"{s.sid}: matched box {want} is not among the rebuilt components")
        _, depth, mask = hit[0]
        comp_px = int(mask.sum())
        bird_px = int((mask & s.bird_mask).sum())
        other = mask & ~s.bird_mask
        other_px = int(other.sum())
        rec = {
            "id": s.sid, "range_m": r["range_m"], "background": r["background"],
            "component_px": comp_px, "bird_px": bird_px, "other_px": other_px,
            "bird_pixel_fraction": round(bird_px / comp_px, 4) if comp_px else None,
            "reported_depth_m": round(depth, 3),
            "px_to_median_flip": (None if other_px == 0 else bird_px - (comp_px // 2 + 1)),
            "flipped_depth_m": (None if other_px == 0
                                else round(float(np.median(s.frame[other])), 3)),
            "bird_px_are_nearest": (True if other_px == 0 or bird_px == 0 else
                                    bool(float(s.frame[mask & s.bird_mask].max())
                                         < float(s.frame[other].min()))),
        }
        per.append(rec)
        r["bird_pixel_fraction"] = rec["bird_pixel_fraction"]
        r["px_to_median_flip"] = rec["px_to_median_flip"]
        r["component_px"] = comp_px
        r["bird_px"] = bird_px
        r["flipped_depth_m"] = rec["flipped_depth_m"]
    mixed = [x for x in per if x["other_px"] > 0]
    worst = sorted(per, key=lambda x: (x["bird_pixel_fraction"], x["id"]))[:5]
    return {
        "denominator_matched_stations": len(per),
        "mixed_components": len(mixed),
        "pure_bird_components": len(per) - len(mixed),
        "min_bird_pixel_fraction": (min(x["bird_pixel_fraction"] for x in per) if per else None),
        "min_px_to_median_flip": (min(x["px_to_median_flip"] for x in mixed) if mixed else None),
        "stations_within_3_px_of_a_flip": [x["id"] for x in mixed if x["px_to_median_flip"] <= 3],
        "stations_below_75pct_bird": [x["id"] for x in per if x["bird_pixel_fraction"] < 0.75],
        "all_bird_pixels_are_nearest": all(x["bird_px_are_nearest"] for x in per),
        "worst_five": worst,
        "per_station": per,
        "bar": "REPORTED, NOT BARRED -- first measured in the 2026-09-07 fix round",
        "note": ("the reported range is the component MEDIAN, so a mixed component tells the truth "
                 "only while the bird holds the majority. This is the distance to the cliff, in "
                 "pixels, and `flipped_depth_m` is what the detection would say on the far side of "
                 "it. It is why the corrected link-break arm is recorded as an open item rather "
                 "than dismissed: link_break=True separates exactly these components"),
    }


def occlusion_block(rows: Sequence[dict], stations: Sequence[Station]) -> dict:
    by_id = {s.sid: s for s in stations}
    out = {}
    for r in rows:
        if r["pass_bar"] != "occlusion_label":
            continue
        s = by_id[r["id"]]
        out[r["id"]] = {
            "rendered_bird_pixels": s.rendered_area_px,
            "occluder_proved_first": s.rendered_area_px == 0,
            "detected_at_expected_pixel": r["matched"],
            "outcome": ("expected non-detection (occluded)" if not r["matched"]
                        else "DETECTED -- not scored as an FP, but investigate"),
        }
    return {"denominator_stations": len(out), "stations": out,
            "rule": ("a miss here is the EXPECTED outcome and a detection is not an FP; the "
                     "zero-rendered-pixel assertion comes FIRST, because an occlusion test that "
                     "skips it passes for a detector that never detects anything")}


# ==================================================================================================
# Acquisition (DESIGN §4.4)
# ==================================================================================================

def acquisition_block(rows: Sequence[dict], stations: Sequence[Station],
                      intr: CameraIntrinsics) -> dict:
    by_id = {s.sid: s for s in stations}

    def prefix(sel: Sequence[dict]) -> Tuple[Optional[float], Optional[float], List[dict]]:
        ladder: Dict[float, List[dict]] = {}
        for r in sel:
            ladder.setdefault(round(r["range_m"], 1), []).append(r)

        table, good, first_fail = [], None, None
        for rng in sorted(ladder):
            at = ladder[rng]
            ok = all(r["matched"] for r in at)
            table.append({"range_m": rng, "n": len(at), "matched": sum(1 for r in at if r["matched"]),
                          "worst_background": sorted({r["background"] for r in at})[-1],
                          "backgrounds": sorted({r["background"] for r in at}),
                          "all_matched": ok})
            if ok and first_fail is None:
                good = rng
            elif not ok and first_fail is None:
                first_fail = rng
        return good, first_fail, table

    cluttered_sel = [r for r in rows if r["pass_bar"] == "FNR_zero" and not r["occluded"]
                     and not r["sub_margin"] and r["range_m"]]
    measured, fail_at, table = prefix(cluttered_sel)

    optical_sel = [r for r in rows if r["range_m"] and not r["occluded"] and not r["sub_margin"]
                   and r["group"] != 9 and by_id[r["id"]].background == "sky"
                   and not by_id[r["id"]].is_negative]
    optical, opt_fail, opt_table = prefix(optical_sel)

    # HOW FAR IS THE LADDER ACTUALLY CLUTTER-BACKED. Above ~30 m every rung in this world is
    # sky-backed, and that is geometrically forced rather than a sampling gap: an in-band bird at
    # 46 m, 6 m below the optical axis, has its ground background at ~86 m -- past the 60 m
    # Euclidean cull, so there is nothing behind it to be clutter. Stated because "cluttered
    # acquisition 46.0 m" reads as a clutter measurement at 46 m and it is not one.
    clutter = [r for r in cluttered_sel if not str(r["background"]).startswith("sky")]
    by_class: Dict[str, float] = {}
    for r in clutter:
        by_class[r["background"]] = max(by_class.get(r["background"], 0.0), float(r["range_m"]))
    max_clutter = max(by_class.values()) if by_class else None
    sky_only_from = next((row["range_m"] for row in table
                          if max_clutter is not None and row["range_m"] > max_clutter), None)

    ratio = depth_detect.corner_ray_ratio(intr.width_px, intr.height_px,
                                          intr.fx, intr.fy, intr.cx, intr.cy)
    clamp = FAR_CLIP_M / ratio
    clamped = None if measured is None else min(measured, clamp)
    booked = None if clamped is None else min(BOOKED_ACQ_M, clamped)
    if booked is None:
        verdict = "NO ACQUISITION RANGE MEASURED -- no station ladder was scoreable"
    elif booked < BREAKEVEN_5MPS_M:
        verdict = (f"NOT BOOKABLE AT 5 M/S: cluttered acquisition {booked:.2f} m is below the "
                   f"{BREAKEVEN_5MPS_M} m breakeven (ADR-020 am. 2 pre-registered invalidation)")
    elif clamped is not None and clamped < BOOKED_ACQ_M:
        verdict = (f"MEASURED {clamped:.2f} M IS BELOW THE BOOKED 46.0 M AND REPLACES IT "
                   f"(min(current, measured), no exceptions)")
    else:
        verdict = (f"measured {measured:.2f} m QUALIFIES the booked 46.0 m and does not raise it; "
                   f"the best-case-scene clause loses 'no clutter' and 'blind isfinite mask' and "
                   f"KEEPS static vehicle, noiseless sensor and level attitude")
    if max_clutter is not None:
        verdict += (f". READ THE CLUTTER CLAIM TO {max_clutter:.0f} M, NOT TO "
                    f"{(measured or 0.0):.0f}: clutter-backed FNR_zero stations exist to "
                    + ", ".join(f"{v:.0f} m ({k})" for k, v in sorted(by_class.items(),
                                                                      key=lambda kv: -kv[1]))
                    + (f", and every rung from {sky_only_from:.0f} m up is sky-backed"
                       if sky_only_from is not None else "")
                    + ". That is geometrically forced in this world rather than a sampling gap: an "
                      "in-band bird at 46 m and 6 m below the optical axis has its ground "
                      "background at ~86 m, past the 60 m Euclidean cull, so there is nothing "
                      "behind it to be clutter. The booked number does not change")
    return {
        "cluttered_acquisition_m": measured,
        "clutter_backed_max_range_m": max_clutter,
        "clutter_backed_max_range_by_background": {k: round(v, 1)
                                                   for k, v in sorted(by_class.items())},
        "sky_backed_only_from_range_m": sky_only_from,
        "clutter_qualifier_note": (
            "the acquisition ladder's upper rungs are 100% sky-backed. The FNR cell table shows it "
            "(canopy and ground_band cells stop in the 20-30 m bin) but no sentence said it, and "
            "'cluttered acquisition 46.0 m' reads as a clutter measurement at 46 m. It is not one"),
        "first_failing_range_m": fail_at,
        "ladder": table,
        "optical_prefix_m": optical, "optical_first_failing_range_m": opt_fail,
        "optical_ladder": opt_table,
        "optical_note": ("sky-backed, unoccluded, level stations only -- the clutter-free arm, "
                         "reported beside the cluttered number and NEVER booked"),
        "corner_ray_ratio": round(ratio, 6),
        "clamp_bound_m": round(clamp, 3),
        "clamped_from_optical_prefix": bool(measured is not None and measured > clamp),
        "limited_by_ladder": bool(fail_at is None),
        "limited_by_ladder_note": (
            "NO station in the scored set failed, so the measured prefix is the LAST RUNG OF THE "
            "LADDER and not a detector horizon: read it as '>= this range', which is exactly why "
            "the §4.4 rule lets it QUALIFY the booked number and never raise it. Raising a booked "
            "horizon needs its own gate, on a flown take."),
        "acquisition_after_clamp_m": (None if clamped is None else round(clamped, 3)),
        "previously_booked_m": BOOKED_ACQ_M,
        "booked_m": (None if booked is None else round(booked, 3)),
        "breakeven_5mps_m": BREAKEVEN_5MPS_M,
        "bookable_at_5mps": (booked is not None and booked >= BREAKEVEN_5MPS_M),
        "verdict": verdict,
    }


def group_d_block(rows: Sequence[dict], stations: Sequence[Station]) -> dict:
    by_id = {s.sid: s for s in stations}
    out = {}
    for r in rows:
        s = by_id[r["id"]]
        if s.station.get("group") != "D_small_step":
            continue
        out[r["id"]] = {
            "declared_step_m": s.station.get("depth_step_m"),
            "measured_standoff_m": r["standoff_m"],
            "range_m": r["range_m"], "v_px": (None if not r["expected_px"] else r["expected_px"][1]),
            "detected": r["matched"], "sub_margin": r["sub_margin"],
        }
    return {"denominator_stations": len(out), "stations": out,
            "purpose": ("group D is the margin's OWN boundary: the smallest bird-to-background "
                        "stand-off that is still separable. It is diagnostic, not a bar -- in this "
                        "world a sub-margin stand-off can only happen OUTSIDE the +/-6 m threat "
                        "band, because trees top out at 3.8 m and the band starts at 9 m")}


# ==================================================================================================
# The sweep (DESIGN §3.2), run as a recorded measurement rather than a choice
# ==================================================================================================

def measure_border_residuals(intr: CameraIntrinsics) -> Dict[int, float]:
    ramp = analytic_ground_ramp(intr.height_px, intr.width_px, intr.fy, intr.cy,
                                MISSION_ALT_M, FAR_CLIP_M, intr.fx, intr.cx)
    return {k: round(border_residual_m(ramp, k), 4) for k in K_LADDER}


def multi_object_probe(params: DepthSegmenterParams) -> dict:
    """TWO near objects that touch in image space -- the case the 85-frame dataset never contains,
    and the case CLAUDE.md's own MVP obstacle density (2-3 scripted birds) is made of.

    It answers two questions with one construction, which is why it is one function:

      1. WITHOUT the link break, two touching objects at different depths return ONE component whose
         median belongs to NEITHER of them. 20.0 m beside 30.0 m reports 25.0 m -- and 25 m is not a
         conservative rounding of 20 m, it is a threat pushed 5 m out.
      2. WITH the link break, the seam cut can push BOTH halves below `min_area_px`, so the pair
         returns NOTHING. That falsifies the design note's "splits and tags, NEVER withholds a
         component", which was the stated CONDITION for keeping the rule -- and it is the reason
         `link_break=False` survives the corrected merge metric.

    The large pair is here so 2 is read as the interaction with `min_area_px` that it is, and not as
    "the link break deletes things": give both halves enough pixels to clear the floor and it does
    exactly what it promises."""
    out: Dict[str, dict] = {}
    for name, half_w in (("small_pair_3x4_px", 4), ("large_pair_3x20_px", 20)):
        z = np.full((480, 640), np.inf, dtype=np.float32)
        z[240:243, 320:320 + half_w] = np.float32(20.0)
        z[240:243, 320 + half_w:320 + 2 * half_w] = np.float32(30.0)
        case = {}
        for lb in (False, True):
            seg = DepthSegmenter(params_with(params, link_break=lb))
            boxes = seg(z)
            c = seg.counters()
            case[f"link_break_{lb}"] = {
                "n_boxes": len(boxes),
                "depths_m": [round(d, 3) for _, d in boxes],
                "components_below_min_area": c["components_below_min_area"],
                "link_cut_px": c["link_cut_px"],
            }
        out[name] = case
    return {
        "kind": "SYNTHETIC two-object construction -- not a render measurement",
        "cases": out,
        "finding_1_merge_median_belongs_to_neither": (
            "two touching near objects at 20.0 m and 30.0 m return ONE component reporting "
            f"{out['small_pair_3x4_px']['link_break_False']['depths_m']} m. The dataset's nearest "
            "analogue is the partial fusion at S042/S046 (bird plus canopy rim), which reports the "
            "bird's depth ONLY because the bird holds 53% of the pixels -- see metrics."
            "median_flip_margin. Every one of the 85 stations has exactly one bird in the world "
            "(birds 1 and 2 are parked at (-200, -190/-180, 50)), so multi-object merging is "
            "UNMEASURED on the render and this is the direction it fails in."),
        "finding_2_link_break_can_withhold": (
            "with the rule ON the small pair returns "
            f"{out['small_pair_3x4_px']['link_break_True']['n_boxes']} boxes: the seam cut drops "
            "both halves below min_area_px. The large pair returns "
            f"{out['large_pair_3x20_px']['link_break_True']['depths_m']} m, i.e. the rule does what "
            "it promises whenever both sides clear the floor -- so this is an INTERACTION with "
            "min_area_px, not a defect of the cut, and the honest statement of the guarantee is "
            "'withholds no component still larger than min_area_px after the cut'."),
    }


def sweep(stations: Sequence[Station], gmap: GeofenceMap, intr: CameraIntrinsics,
          log=print) -> dict:
    fnr_stations = [s for s in stations if s.pass_bar == "FNR_zero"]
    neg_stations = [s for s in stations if s.pass_bar == "FP_zero_unmapped"]
    resid = measure_border_residuals(intr)
    log(f"  border residual (analytic 15 m ramp): {resid}")

    base = DepthSegmenterParams(bg_window_px=15, margin_m=1.5, min_area_px=6, open_iter=0,
                                max_boxes=SWEEP_MAX_BOXES, near_m=NEAR_CLIP_M, far_m=FAR_CLIP_M)

    # --- margin: smallest with ZERO unmapped FP on the 8 negatives, floored at 1.5x the residual
    margin_rows = []
    chosen_margin: Dict[int, Optional[float]] = {}
    for k in K_LADDER:
        floor = 1.5 * resid[k]
        pick = None
        for m in MARGIN_LADDER:
            p = params_with(base, bg_window_px=k, margin_m=m)
            rows, _ = run(neg_stations, p, gmap)
            unmapped = sum(r["fp_unmapped"] for r in rows)
            mapped = sum(r["fp_mapped"] for r in rows)
            comps = max(r["n_boxes"] for r in rows)
            margin_rows.append({"k": k, "margin_m": m, "unmapped_fp": unmapped,
                               "unmapped_fp_per_frame": round(unmapped / len(rows), 4),
                                "mapped_fp": mapped, "max_components": comps,
                                "at_or_above_floor": m >= floor})
            if pick is None and unmapped == 0 and m >= floor:
                pick = m
        chosen_margin[k] = pick
        log(f"  K={k}: floor {floor:.3f} m -> margin {pick}")

    # --- K: smallest with FNR 0 on the FNR_zero stations, at its own chosen margin
    k_rows = []
    adopted_k = None
    for k in K_LADDER:
        m = chosen_margin[k]
        if m is None:
            k_rows.append({"k": k, "margin_m": None, "skipped": "no margin gives zero unmapped FP"})
            continue
        p = params_with(base, bg_window_px=k, margin_m=m)
        rows, _ = run(fnr_stations, p, gmap)
        blk = fnr_block(rows, m)
        k_rows.append({"k": k, "margin_m": m, "denominator": blk["denominator_detectable"],
                       "misses": blk["misses"], "fnr": blk["fnr"],
                       "merge_mislabels": merge_block(rows)["merge_mislabels"]})
        if adopted_k is None and not blk["misses"]:
            adopted_k = k
        log(f"  K={k} margin={m}: FNR {blk['fnr']} over {blk['denominator_detectable']} "
            f"misses {blk['misses']}")
    if adopted_k is None:
        raise RuntimeError("no K in the ladder gives FNR 0 -- the gate is RED and no constant is "
                           "adoptable; see the sweep table")
    adopted_margin = chosen_margin[adopted_k]
    base = params_with(base, bg_window_px=adopted_k, margin_m=adopted_margin)

    # --- min_area: largest keeping FNR 0, MINUS one ladder step
    area_rows, largest_ok = [], None
    for a in MIN_AREA_LADDER:
        rows, _ = run(fnr_stations, params_with(base, min_area_px=a), gmap)
        blk = fnr_block(rows, adopted_margin)
        area_rows.append({"min_area_px": a, "misses": blk["misses"], "fnr": blk["fnr"],
                          "denominator": blk["denominator_detectable"]})
        if not blk["misses"]:
            largest_ok = a
    idx = MIN_AREA_LADDER.index(largest_ok)
    adopted_area = MIN_AREA_LADDER[max(0, idx - 1)]
    first_bad = next((x["min_area_px"] for x in area_rows if x["misses"]), None)
    smallest_footprint = min(s.rendered_area_px for s in fnr_stations if s.rendered_area_px)
    base = params_with(base, min_area_px=adopted_area)
    log(f"  min_area: largest with FNR 0 = {largest_ok} -> adopt one step down = {adopted_area}")

    # --- open_iter: both scored, the loser's numbers recorded
    open_rows, adopted_open = [], None
    for o in OPEN_ITER_LADDER:
        rows, _ = run(fnr_stations, params_with(base, open_iter=o), gmap)
        blk = fnr_block(rows, adopted_margin)
        nrows, _ = run(neg_stations, params_with(base, open_iter=o), gmap)
        open_rows.append({"open_iter": o, "misses": blk["misses"], "fnr": blk["fnr"],
                          "denominator": blk["denominator_detectable"],
                          "unmapped_fp": sum(r["fp_unmapped"] for r in nrows)})
        if adopted_open is None and not blk["misses"]:
            adopted_open = o
    base = params_with(base, open_iter=adopted_open)
    log(f"  open_iter: adopt {adopted_open} ({open_rows})")

    # --- max_boxes: from the worst-case component count over ALL stations, not the negatives alone
    rows, _ = run(stations, base, gmap)
    worst_all = max(r["n_boxes"] for r in rows)
    worst_all_id = max(rows, key=lambda r: r["n_boxes"])["id"]
    worst_neg = max(r["n_boxes"] for r in rows if "fp_total" in r)
    adopted_boxes = int(2 ** math.ceil(math.log2(max(8, 2 * worst_all))))
    base = params_with(base, max_boxes=adopted_boxes)
    log(f"  max_boxes: worst-case components all-stations {worst_all} ({worst_all_id}), "
        f"negatives {worst_neg} -> adopt {adopted_boxes}")

    # --- link break: kept ONLY if it strictly improves a bar, worsens none, AND satisfies the
    #     design note's own precondition (it never withholds a component). All three are now
    #     MEASURED; the first pass measured only a broken version of the second.
    link_rows = []
    for lb in (False, True):
        p = params_with(base, link_break=lb)
        rows, seg = run(stations, p, gmap)
        blk = fnr_block(rows, adopted_margin)
        mb = merge_block(rows)
        acc = accuracy_block(rows)
        flp = flip_block(stations, rows, p)
        link_rows.append({"link_break": lb, "misses": blk["misses"],
                          "unmapped_fp": sum(r["fp_unmapped"] for r in rows if "fp_total" in r),
                          "merge_mislabels": mb["count"],
                          "merge_mislabel_ids": mb["merge_mislabels"],
                          "separated_neighbour_ids": mb["separated_neighbour_at_background_depth"],
                          "range_error_p95_m": acc["range_error_p95_m"],
                          "range_error_max_m": acc["range_error_max_m"],
                          "centroid_error_max_px": acc["centroid_error_max_px"],
                          "worst_centroid_station": acc["worst_centroid_station"],
                          "min_bird_pixel_fraction": flp["min_bird_pixel_fraction"],
                          "min_px_to_median_flip": flp["min_px_to_median_flip"],
                          "stations_within_3_px_of_a_flip": flp["stations_within_3_px_of_a_flip"],
                          "link_cut_px": seg.counters()["link_cut_px"]})
    off, on = link_rows[0], link_rows[1]
    keys = ("misses", "unmapped_fp", "merge_mislabels")
    better = any(len(on[k]) < len(off[k]) if k == "misses" else on[k] < off[k] for k in keys)
    worse = any(len(on[k]) > len(off[k]) if k == "misses" else on[k] > off[k] for k in keys)
    probe = multi_object_probe(base)
    withholds = probe["cases"]["small_pair_3x4_px"]["link_break_True"]["n_boxes"] == 0
    adopted_link = bool(better and not worse and not withholds)
    base = params_with(base, link_break=adopted_link)
    log(f"  link_break: adopt {adopted_link} (better={better}, worse={worse}, "
        f"withholds={withholds})")

    return {
        "adopted": base,
        "record": {
            "border_residual_m_by_k": resid,
            "border_residual_source": ("max closing(D,K)-D over a 15 m analytic ground ramp at the "
                                       "live intrinsics; it is a frame-BORDER effect, zero over the "
                                       "interior, and it is what floors margin_m"),
            "margin": {"ladder": list(MARGIN_LADDER), "rows": margin_rows,
                       "rule": "smallest with ZERO unmapped FP on the 8 negatives, floored at "
                               "1.5x the measured border residual",
                       "chosen_per_k": chosen_margin},
            "k": {"ladder": list(K_LADDER), "rows": k_rows,
                  "rule": "smallest K with FNR 0 over the FNR_zero stations", "adopted": adopted_k,
                  "design_expected_at_least": 17,
                  "note": ("DESIGN §3.2 argued K >= 17 from the fill requirement "
                           "(2*fx*0.18/13.05 = 14.3 px). The dataset is what settles it.")},
            "min_area": {"ladder": list(MIN_AREA_LADDER), "rows": area_rows,
                         "largest_with_fnr_zero": largest_ok, "adopted": adopted_area,
                         "first_failing_min_area_px": first_bad,
                         "measured_min_accepted_component_px": [largest_ok, first_bad],
                         "smallest_rendered_bird_footprint_px": int(smallest_footprint),
                         "rule": "largest keeping FNR 0, minus one ladder step",
                         "headroom_note": (
                             "the smallest rendered bird footprint anywhere in the FNR_zero set is "
                             "the render's own antialiasing floor, and it is the number the "
                             "adopted min_area has headroom against -- the ladder BRACKETS the "
                             "smallest accepted component between the largest passing step and "
                             "the first failing one")},
            "open_iter": {"rows": open_rows, "adopted": adopted_open},
            "max_boxes": {"worst_case_components_all_stations": worst_all,
                          "at_station": worst_all_id,
                          "worst_case_components_negatives": worst_neg,
                          "adopted": adopted_boxes,
                          "rule": ("2x the worst-case component count over ALL stations, rounded "
                                   "up to a power of two. NOT the negatives alone: nearest-first "
                                   "truncation drops the FARTHEST candidate, so a cap below the "
                                   "count of near canopies in a cluttered lane deletes the far "
                                   "bird and nothing else")},
            "link_break": {
                "rows": link_rows, "adopted": adopted_link,
                "rule": ("keep only if (a) it strictly improves one of the three bar quantities "
                         "and worsens none, AND (b) it satisfies the design note's precondition "
                         "that it never withholds a component"),
                "moves_a_bar": bool(better and not worse),
                "withholds_a_component": withholds,
                "withholding_probe": probe["cases"]["small_pair_3x4_px"],
                "decision": (
                    "OFF. Under the CORRECTED merge rule the ON arm moves no bar -- 0 misses, 0 "
                    "unmapped FP and 0 merge mislabels on both arms -- so clause (a) is not met, "
                    "and clause (b) fails outright: the seam cut drops a pair of adjacent 12 px "
                    "objects below min_area_px and returns nothing (multi_object_probe). Either "
                    "clause alone keeps it off."),
                "correction_to_the_first_pass": (
                    "the first scoring pass recorded 'ON introduced 2 merge mislabels (S042, S046) "
                    "and fixed nothing'. BOTH halves were wrong. The 2 were correct SPLITS "
                    "mis-counted by a merge rule that did not require the bird to be unmatched, "
                    "and ON does fix something: it separates exactly the two components whose "
                    "medians sit 1 px from a flip."),
                "open_item_for_a_pre_registered_round": (
                    "ON is measurably better on two REPORTED (unbarred) quantities -- range error "
                    "p95/max and worst centroid -- and it removes the median-flip fragility at "
                    "S042/S046 by giving the bird its own component. It is NOT adopted here "
                    "because choosing it now would mean widening the adoption rule after seeing "
                    "which way the numbers fell, on the same data. The pre-registerable next step "
                    "is 'link_break=True with cut components exempt from min_area_px', which would "
                    "satisfy clause (b) by construction; it needs its own round and its own "
                    "dataset arm (a two-bird station), not a flip in a fix round."),
            },
        },
    }


# ==================================================================================================
# The three checks the artifact cannot fake
# ==================================================================================================

def mutation_canned_frame(intr: CameraIntrinsics) -> Tuple[np.ndarray, dict]:
    """THE canned frame the mutation check runs on -- one home, imported by the test file so the
    artifact and the suite cannot drift apart.

    It carries one instance of everything each conjunct is supposed to reject or keep:
      * a 15 m analytic ground ramp (what `step > margin` must NOT flag);
      * one bird-sized disc 20 m over the ramp at v=400 (the one true positive);
      * a 12x12 patch at EXACTLY 60.0 m against sky (the far CLAMP SIGNATURE -- finite, so
        `isfinite` keeps it, and only the exclusive clip window rejects it);
      * a 10x10 `-inf` blob (inside near clip).
    """
    z = analytic_ground_ramp(intr.height_px, intr.width_px, intr.fy, intr.cy,
                             MISSION_ALT_M, FAR_CLIP_M, intr.fx, intr.cx).copy()
    u = np.arange(intr.width_px, dtype=np.float64)[None, :] + 0.5
    v = np.arange(intr.height_px, dtype=np.float64)[:, None] + 0.5
    r_px = intr.fx * BIRD_RADIUS_M / 20.0
    disc = ((u - 320.0) ** 2 + (v - 400.0) ** 2) <= r_px * r_px
    z[disc] = np.float32(20.0)
    z[100:112, 100:112] = np.float32(FAR_CLIP_M)      # the clamp signature, against sky
    z[40:50, 500:510] = np.float32(-np.inf)           # inside the near clip
    return z, {"bird_px": [320.0, 400.0], "bird_depth_m": 20.0, "bird_radius_px": round(r_px, 3),
               "clamp_patch_px": [100, 100, 112, 112], "clamp_patch_depth_m": FAR_CLIP_M,
               "neg_inf_patch_px": [500, 40, 510, 50]}


def mutation_check(stations: Sequence[Station], params: DepthSegmenterParams,
                   gmap: GeofenceMap, intr: CameraIntrinsics) -> dict:
    """Delete each conjunct of the mask expression in turn (DESIGN §4.5 item 3).

    Run twice: on the canned frame (what the unit suite asserts) and on all 85 dataset frames (what
    the bars are actually computed from). The pre-registered expectation was three reds; the
    measurement returned TWO, and the third is a finding rather than a hole -- see
    `isfinite_redundant_with_clip_window`. The pair deletion is scored because that is the mutation
    that actually exercises the non-finite rejection."""
    canned, canned_meta = mutation_canned_frame(intr)
    variants: List[Tuple[str, Tuple[str, ...]]] = [(t, tuple(x for x in MASK_TERMS if x != t))
                                                   for t in MASK_TERMS]
    variants.append(("isfinite+clip_window",
                     tuple(x for x in MASK_TERMS if x not in ("isfinite", "clip_window"))))

    base_seg = DepthSegmenter(params)
    canned_intact = base_seg(canned)
    intact_rows, _ = run(stations, params, gmap)
    intact = {"fnr_misses": len(fnr_block(intact_rows, params.margin_m)["misses"]),
              "unmapped_fp_per_frame": fp_block(intact_rows)["unmapped_fp_per_frame"],
              "boxes_total": sum(r["n_boxes"] for r in intact_rows),
              "canned_boxes": len(canned_intact),
              "canned_depths_m": [round(d, 3) for _, d in canned_intact]}
    out = {"canned_frame": canned_meta, "intact": intact, "mutants": {}}
    for name, kept in variants:
        cseg = DepthSegmenter(params, _mask_terms=kept)
        cboxes = cseg(canned)
        seg = DepthSegmenter(params, _mask_terms=kept)
        rows = [score_station(s, seg(s.frame), gmap, params.margin_m) for s in stations]
        blk = fnr_block(rows, params.margin_m)
        fpb = fp_block(rows)
        canned_changed = repr(cboxes) != repr(canned_intact)
        dataset_changed = (len(blk["misses"]) != intact["fnr_misses"]
                           or fpb["unmapped_fp_per_frame"] != intact["unmapped_fp_per_frame"]
                           or sum(r["n_boxes"] for r in rows) != intact["boxes_total"])
        out["mutants"][name] = {
            "removed": name, "canned_boxes": len(cboxes),
            "canned_depths_m": [round(d, 3) for _, d in cboxes][:6],
            "canned_result_changed": bool(canned_changed),
            "dataset_fnr_misses": len(blk["misses"]),
            "dataset_unmapped_fp_per_frame": fpb["unmapped_fp_per_frame"],
            "dataset_mapped_fp_per_frame": fpb["mapped_fp_per_frame"],
            "dataset_boxes_total": sum(r["n_boxes"] for r in rows),
            "dataset_result_changed": bool(dataset_changed),
            "fnr_bar_pass": blk["pass"], "fp_bar_pass": fpb["pass"],
            "suite_goes_red": bool(canned_changed or dataset_changed),
        }
    red = {k: v["suite_goes_red"] for k, v in out["mutants"].items()}
    out["reds"] = red
    out["all_three_red"] = bool(red["step_over_margin"] and red["clip_window"]
                                and red["isfinite+clip_window"])
    out["isfinite_redundant_with_clip_window"] = not red["isfinite"]
    out["redundancy_finding"] = (
        "MEASURED, and it is the mutation check doing its job rather than failing it: deleting "
        "`isfinite` ALONE changes nothing, on the canned frame or on all 85 dataset frames, because "
        "the exclusive clip window already rejects every non-finite value -- `-inf > near_m`, "
        "`+inf < far_m` and every NaN comparison are all False. The three pre-registered conjuncts "
        "are therefore only TWO independent terms. Deleting the PAIR is red (the -inf blob returns "
        "as a candidate with an infinite step), which is the mutation that actually exercises "
        "non-finite rejection. `isfinite` is kept in the source because it states the intent the "
        "clip window only implies, and because a future window that is not exclusive at both ends "
        "would make it load-bearing again -- but it is documented here as redundant so nobody "
        "counts it as a second, independent safeguard.")
    return out


def analytic_sphere(intr: CameraIntrinsics, cu: float, cv: float, radius_m: float,
                    depth_m: float, background: Optional[np.ndarray] = None) -> np.ndarray:
    """A SPHERE's near surface (not a flat disc), so the target carries its own relief -- which is
    what decides whether the closing can reproduce it. Nearer surface wins, so an occluder occludes.
    """
    z = (np.full((intr.height_px, intr.width_px), np.inf, dtype=np.float32)
         if background is None else background.astype(np.float32).copy())
    u = np.arange(intr.width_px, dtype=np.float64)[None, :] + 0.5
    v = np.arange(intr.height_px, dtype=np.float64)[:, None] + 0.5
    x = (u - cu) / intr.fx * depth_m
    y = (v - cv) / intr.fy * depth_m
    rr = x * x + y * y
    m = rr <= radius_m * radius_m
    d = depth_m - np.sqrt(np.maximum(radius_m * radius_m - rr, 0.0))
    z[m] = np.minimum(z[m], d[m].astype(np.float32))
    return z.astype(np.float32)


def resolving_floor_px(intr: CameraIntrinsics, params: DepthSegmenterParams,
                       depth_m: float = 30.0, offsets: Sequence[float] = (0.0, 0.25, 0.5),
                       lo: float = 0.5, hi: float = 4.0, step: float = 0.05) -> float:
    """Smallest apparent radius a sky-backed filled disc can have and still be detected, at the
    WORST sub-pixel placement over `offsets` in both axes.

    This is the re-measurement `config/depth_camera.json:min_resolving_radius_source` BOOKS for the
    segmenter session and `depth_detect.MIN_RESOLVING_RADIUS_PX` currently answers with 2.0 px --
    a number measured through the NDVI detector's morphology (3x3 open, close, min_area 6), which
    this segmenter does not use. Same protocol as
    `tests/fieldguard_planning/test_depth_detect.py`'s, so the two numbers are comparable."""
    r = lo
    while r <= hi + 1e-9:
        ok = True
        for du in offsets:
            for dv in offsets:
                u = np.arange(intr.width_px, dtype=np.float64)[None, :] + 0.5
                v = np.arange(intr.height_px, dtype=np.float64)[:, None] + 0.5
                z = np.full((intr.height_px, intr.width_px), np.inf, dtype=np.float32)
                z[((u - (intr.cx + du)) ** 2 + (v - (intr.cy + dv)) ** 2) <= r * r] = depth_m
                if not DepthSegmenter(params)(z):
                    ok = False
                    break
            if not ok:
                break
        if ok:
            return round(r, 4)
        r += step
    return float("nan")


def size_and_near_field_sweep(intr: CameraIntrinsics, params: DepthSegmenterParams) -> dict:
    """SYNTHETIC, and labelled as such -- the dataset's nearest station is 14 m and its only object
    radius is 0.18 m, so the near field and the large-object case are unmeasured by it.

    THE FINDING THIS EXISTS TO RECORD, because both design notes state it the other way round:
    DESIGN §2.5 says an object wider than K "returns as a RING of its own silhouette carrying its
    own depth, not as nothing", and ALGORITHM §2.4 says the same in different words. **That is
    wrong, and this measures it.** A grey CLOSING by definition PRESERVES a pit wider than the
    structuring element -- `closing(D) = D` there -- so `closing(D) - D = 0` and a sufficiently
    large near object produces NO CANDIDATES AT ALL. Not a ring: nothing.

    What saves the mission case is that this world's large objects are the mapped, geofenced trees
    (ADR-001) and its unplanned obstacle is a 0.18 m bird, which stays detectable to ~2 m. The gap
    is named rather than papered over: an unplanned LARGE obstacle -- another airframe, a flock, a
    wall -- inside the range where it fills more than ~3K pixels is invisible to this operator."""
    bird = []
    for r in (46.0, 30.0, 20.0, 16.0, 14.0, 12.5, 12.0, 10.0, 8.0, 6.0, 4.0, 3.0, 2.0):
        boxes = DepthSegmenter(params)(analytic_sphere(intr, intr.cx, intr.cy, BIRD_RADIUS_M, r))
        bird.append({"range_m": r, "apparent_diameter_px": round(2 * intr.fx * BIRD_RADIUS_M / r, 1),
                     "components": len(boxes),
                     "nearest_depth_m": (None if not boxes else round(min(d for _, d in boxes), 3))})
    sizes = {}
    for radius_m in (0.18, 1.3, 5.0):
        rows = []
        for r in (60.0, 50.0, 40.0, 30.0, 25.0, 20.0, 15.0, 10.0, 5.0):
            boxes = DepthSegmenter(params)(analytic_sphere(intr, intr.cx, intr.cy, radius_m, r))
            rows.append({"range_m": r,
                         "apparent_diameter_px": round(2 * intr.fx * radius_m / r, 1),
                         "components": len(boxes)})
        blind = [x["range_m"] for x in rows if x["components"] == 0]
        sizes[f"radius_{radius_m}m"] = {
            "rows": rows,
            "blind_ranges_m": blind,
            "blind_from_diameter_px": (None if not blind else
                                       min(x["apparent_diameter_px"] for x in rows
                                           if x["components"] == 0))}
    floor = resolving_floor_px(intr, params)
    implied = intr.fx * BIRD_RADIUS_M / floor if floor == floor else None
    floor6 = resolving_floor_px(intr, params_with(params, min_area_px=6))
    implied6 = intr.fx * BIRD_RADIUS_M / floor6 if floor6 == floor6 else None
    ratio = depth_detect.corner_ray_ratio(intr.width_px, intr.height_px,
                                          intr.fx, intr.fy, intr.cx, intr.cy)
    clamp = FAR_CLIP_M / ratio
    return {
        "kind": "SYNTHETIC analytic spheres against sky -- not a render measurement",
        "resolving_floor_px": floor,
        "resolving_floor_implied_range_m": (None if implied is None else round(implied, 2)),
        "resolving_floor_px_at_min_area_6": floor6,
        "resolving_floor_implied_range_m_at_min_area_6": (None if implied6 is None
                                                          else round(implied6, 2)),
        "corner_clamp_m": round(clamp, 3),
        "morphology_is_the_binding_horizon": bool(implied is not None and implied < clamp),
        "resolving_floor_note": (
            "Closes the re-measurement config/depth_camera.json:min_resolving_radius_source BOOKED "
            "for the segmenter session, and ADR-020 am. 1 open item 3 with it. "
            f"depth_detect.MIN_RESOLVING_RADIUS_PX = {depth_detect.MIN_RESOLVING_RADIUS_PX} px was "
            f"measured through the NDVI detector's morphology, which this segmenter does NOT use. "
            f"Re-measured against the adopted operator at the worst sub-pixel placement it is "
            f"{floor} px -> {'n/a' if implied is None else round(implied, 2)} m for a 0.18 m "
            f"target, i.e. the booked geometric bound is REPRODUCED rather than moved -- and that "
            f"is arithmetic coincidence, not inheritance: it comes from min_area_px, where the NDVI "
            f"number came from a 3x3 cross opening. It sits just BELOW the "
            f"{round(clamp, 3)} m corner clamp, so on this sensor the morphology binds the horizon "
            f"by {'' if implied is None else round(clamp - implied, 2)} m rather than the far cull. "
            f"The pre-registered min_area rule cost horizon here and the number is on the record: "
            f"at min_area_px=6 the floor is {floor6} px -> "
            f"{'n/a' if implied6 is None else round(implied6, 2)} m. Both are above the 46.0 m "
            f"booked range, so the booked number does not move either way."),
        "bird_ladder_radius_0.18m": bird,
        "whole_object_crossover_note": (
            "one component down to 10 m, then 4 rim arcs from 8 m in; the pinhole prediction "
            f"2*fx*R/K = {2 * intr.fx * BIRD_RADIUS_M / params.bg_window_px:.2f} m brackets it"),
        "object_size_sweep": sizes,
        "large_object_blind_zone": (
            "MEASURED CORRECTION to DESIGN §2.5 and ALGORITHM §2.4: a near object wide enough that "
            "the closing's erosion can recover its own depth across the whole silhouette produces "
            "ZERO candidates -- not a ring. A 1.3 m canopy sphere is invisible inside ~25 m and a "
            "flat 300 px wall at 8 m is invisible entirely. In THIS world the large objects are the "
            "mapped, geofenced trees and the unplanned obstacle is a 0.18 m bird detectable to "
            "~2 m, so the mission case holds -- but an unplanned LARGE obstacle at close range is a "
            "named blind spot of this operator, and no bar on this dataset can see it."),
    }


def determinism_check(stations: Sequence[Station], params: DepthSegmenterParams) -> dict:
    """Shuffle the station order, re-run, require byte-identical per-station output."""
    a = {s.sid: repr(DepthSegmenter(params)(s.frame)) for s in stations}
    shuffled = list(stations)
    random.Random(20260907).shuffle(shuffled)
    seg = DepthSegmenter(params)
    b = {s.sid: repr(seg(s.frame)) for s in shuffled}
    diff = sorted(k for k in a if a[k] != b[k])
    return {"denominator_stations": len(a), "mismatched": diff, "pass": not diff,
            "note": ("one fresh segmenter per station vs ONE segmenter walking a shuffled order: "
                     "identical output proves there is no frame-to-frame state as well as no RNG")}


def runtime_check(stations: Sequence[Station], params: DepthSegmenterParams,
                  reps: int = 5) -> dict:
    seg = DepthSegmenter(params)
    per: Dict[str, List[float]] = {}
    by_rep: List[List[float]] = []
    for _ in range(reps):
        rep: List[float] = []
        for s in stations:
            t0 = time.perf_counter()
            seg(s.frame)
            ms = (time.perf_counter() - t0) * 1000.0
            per.setdefault(s.sid, []).append(ms)
            rep.append(ms)
        by_rep.append(rep)
    c = seg.counters()
    worst = max(per, key=lambda k: max(per[k]))
    flat = [x for r in by_rep for x in r]
    return {
        "reps_per_station": reps, "n": c["seg_wall_ms_n"],
        "seg_wall_ms_p95": c["seg_wall_ms_p95"], "seg_wall_ms_max": c["seg_wall_ms_max"],
        "seg_wall_ms_median": round(float(np.median(flat)), 3),
        "per_rep_p95_ms": [round(_p(r, 0.95), 3) for r in by_rep],
        "per_rep_note": ("rep 1 is COLD (85 x 1.2 MB of frames first-touched from the page cache); "
                         "it is included in the p95 rather than discarded, and the per-rep column "
                         "is here so a reader can see the difference instead of taking it on trust"),
        "slowest_station": worst, "slowest_station_max_ms": round(max(per[worst]), 3),
        "bar_p95_ms": 25.0, "bar_max_ms": 100.0,
        "pass": bool(c["seg_wall_ms_p95"] is not None and c["seg_wall_ms_p95"] <= 25.0
                     and c["seg_wall_ms_max"] <= 100.0),
        "host_note": ("HOST numbers (macOS arm64). The container measured ~1.2x this host on the "
                      "same class of numpy/scipy work (NDVI detector: 6.94 ms host median vs "
                      "8.211 ms in-container p95 over n=1302, "
                      "eval/results/live_flight_log_20260825T210402Z.json). The number that "
                      "SETTLES it is DepthDetectionSource.counters()['detect_wall_ms_p95'] on the "
                      "first flight, not this bench."),
    }


# ==================================================================================================
# Outputs
# ==================================================================================================

def write_fixtures(stations: Sequence[Station], ddir: Path,
                   params: DepthSegmenterParams) -> List[dict]:
    out_dir = ddir / "fixtures"
    out_dir.mkdir(exist_ok=True)
    by_id = {s.sid: s for s in stations}
    recs = []
    for sid in FIXTURE_STATIONS:
        s = by_id[sid]
        meta = {
            "station_id": sid, "group": s.group, "why": FIXTURE_WHY[sid],
            "background": s.background, "pass_bar": s.pass_bar,
            "expected_px": s.expected_px, "expected_depth_m": s.expected_depth_m,
            "expected_r_px": s.expected_r_px, "bird_centre_depth_m": s.bird_centre_depth_m,
            "bird_enu": s.row["bird_0_readback"]["enu"],
            "vehicle_pos_enu": list(s.veh_pos), "vehicle_quat_xyzw": list(s.veh_quat),
            "camera_pos_enu": [float(c) for c in s.cam_p],
            "intrinsics": {"fx": s.intr.fx, "fy": s.intr.fy, "cx": s.intr.cx, "cy": s.intr.cy,
                           "width_px": s.intr.width_px, "height_px": s.intr.height_px},
            "frame_sha1": s.row["frame"]["sha1"],
            "source": f"{ddir.name}/{sid}.npy",
        }
        p = out_dir / f"{sid}.npz"
        np.savez_compressed(p, depth=s.frame, meta=np.array(json.dumps(meta)))
        kb = p.stat().st_size / 1024.0
        recs.append({"station_id": sid, "path": str(p.relative_to(REPO_ROOT)),
                     "size_kb": round(kb, 1), "under_500kb": kb < 500.0, "why": FIXTURE_WHY[sid]})
    return recs


def write_report(path: Path, art: dict) -> None:
    a = art
    c = a["constants"]
    L: List[str] = []
    L.append("# Depth segmenter — score report")
    L.append("")
    L.append(f"**Artifact:** `{a['artifact']}` · schema {a['schema_version']} · "
             f"generated {a['generated_utc']}")
    L.append(f"**Verdict:** {a['verdict']}")
    L.append("")
    L.append("Claims ceiling: **sim-demonstrated, evidence-gated**. Every rate below carries its "
             "denominator. This is a HOST score on a rendered dataset; nothing here is a flight "
             "measurement, and the runtime bar is settled in the air, not on this bench.")
    L.append("")
    L.append("## The dataset, and what the capture already proved")
    d = a["dataset"]
    L.append("")
    L.append(f"- `{d['dataset_dir']}` — **{d['n_frames']} frames**, float32 (480, 640), pinhole "
             f"Z-depth in m; `+inf` beyond the 60 m far clip (culled on Euclidean slant), `-inf` "
             f"inside the 0.1 m near clip.")
    L.append(f"- `labels.jsonl` sha256 `{d['labels_sha256'][:16]}…`; station file "
             f"`{d['stations_file']}` sha256 `{d['stations_file_sha256'][:16]}…`.")
    L.append(f"- **{d['n_distinct_frame_sha1']} distinct frame sha1** over {d['n_frames']} frames. "
             f"The repeats are the occlusion stations against their pose's negative control: a "
             f"hidden bird leaves the scene pixel-identical to the empty one, which is both the "
             f"expected outcome AND the occlusion proof.")
    L.append("- Capture facts, verified fail-closed by the render harness: every vehicle pose "
             "within 0.05 m / 0.5° of command, every bird teleport within 0.05 m, the committed "
             "125×110 m `field_ground` (NOT the 425 m check-world extension), birds 1 and 2 parked "
             "out of every frustum, zero gravity so nothing drifts.")
    L.append("- Each frame was re-hashed on load; a mismatch stops the run.")
    L.append("")
    lb = a["labeller"]
    L.append("### The labeller, and the three things it cannot fake")
    L.append("")
    L.append(f"1. **The bird is located by diffing each frame against its own group's negative "
             f"control** — no detector in the labelling loop. Max |rendered − recomputed| = "
             f"**{lb['max_rendered_vs_recomputed_px']} px** (at {lb['at_station']}), against "
             f"τ = {lb['tau_px']} px, over every visible station.")
    L.append(f"2. **Forward and inverse projections are different code.** Round-trip through the "
             f"flight primitive `{a['roundtrip']['inverse_primitive']}` closes to "
             f"**{a['roundtrip']['max_roundtrip_error_m']} m**.")
    L.append(f"3. **The world model is checked against the render.** Max |ray-cast − rendered| "
             f"background depth = **{lb['max_raycast_vs_render_background_m']} m** "
             f"(at {lb['raycast_worst']}).")
    L.append(f"")
    L.append(f"The station file's own `expected_px` differs from the readback recompute by at most "
             f"**{lb['max_stationfile_vs_recomputed_px']} px** ({lb['stationfile_worst']}) — the "
             f"predictions hold, but every label used here is the recompute.")
    L.append("")
    L.append("## Adopted constants")
    L.append("")
    L.append("| constant | adopted | rule (pre-registered, DESIGN §3.2) |")
    L.append("|---|---|---|")
    r = a["constants_sweep"]
    L.append(f"| `bg_window_px` (K) | **{c['bg_window_px']}** | smallest K in "
             f"{list(K_LADDER)} with FNR 0 |")
    L.append(f"| `margin_m` | **{c['margin_m']}** | smallest with zero unmapped FP on the 8 "
             f"negatives, floored at 1.5× the border residual |")
    L.append(f"| `min_area_px` | **{c['min_area_px']}** | largest keeping FNR 0, minus one step |")
    L.append(f"| `open_iter` | **{c['open_iter']}** | both scored |")
    L.append(f"| `max_boxes` | **{c['max_boxes']}** | 2× worst-case component count over ALL "
             f"stations |")
    L.append(f"| `link_break` | **{c['link_break']}** | kept only if it moves a bar |")
    L.append(f"| `near_m` / `far_m` | {c['near_m']} / {c['far_m']} | the seam's own exclusive "
             f"window, pinned equal by test |")
    L.append("")
    L.append("### The sweeps, as run")
    L.append("")
    L.append("**Border residual** (max `closing(D,K) − D` on a 15 m analytic ground ramp — a frame-"
             "border effect, exactly zero over the interior). It is what floors the margin, so the "
             "chain reads *border artifact → margin → smallest visible stand-off*:")
    L.append("")
    res_by_k = {int(k): v for k, v in r["border_residual_m_by_k"].items()}
    L.append("| K | " + " | ".join(str(k) for k in K_LADDER) + " |")
    L.append("|---|" + "---|" * len(K_LADDER))
    L.append("| residual (m) | " + " | ".join(f"{res_by_k[k]:.3f}" for k in K_LADDER) + " |")
    L.append("| 1.5x floor on margin (m) | "
             + " | ".join(f"{1.5 * res_by_k[k]:.3f}" for k in K_LADDER) + " |")
    L.append("")
    L.append("**margin × K on the 8 negatives** (unmapped FP / frame; `*` = at or above that K's "
             "floor):")
    L.append("")
    L.append("| K \\ margin | " + " | ".join(f"{m}" for m in MARGIN_LADDER) + " |")
    L.append("|---|" + "---|" * len(MARGIN_LADDER))
    for k in K_LADDER:
        cells = []
        for m in MARGIN_LADDER:
            row = next((x for x in r["margin"]["rows"] if x["k"] == k and x["margin_m"] == m), None)
            cells.append("—" if row is None else
                         f"{row['unmapped_fp_per_frame']}{'*' if row['at_or_above_floor'] else ''}")
        L.append(f"| {k} | " + " | ".join(cells) + " |")
    L.append("")
    L.append("**The FP term never bound.** Every cell above is 0.0 unmapped FP per frame — at every "
             "K and every margin down to 0.5 m — so `margin_m` was chosen entirely by its FLOOR. "
             "That is a real limit of this measurement, and naming it is the point: the ground "
             "band's border artifact un-projects to z ≈ 0, i.e. to *mapped* clutter, so the "
             "unmapped-FP metric is structurally blind to the very artifact the floor exists to "
             "clear. The prediction that would falsify the floor's sufficiency is foliage with "
             "self-depth structure containing pits narrower than K; this world's canopies are "
             "smooth spheres.")
    L.append("")
    L.append("**K ladder** at each K's own chosen margin:")
    L.append("")
    L.append("| K | margin (m) | denominator | misses | FNR | merge mislabels |")
    L.append("|---|---|---|---|---|---|")
    for row in r["k"]["rows"]:
        L.append(f"| {row['k']} | {row.get('margin_m')} | {row.get('denominator', '—')} | "
                 f"{row.get('misses', row.get('skipped'))} | {row.get('fnr', '—')} | "
                 f"{row.get('merge_mislabels', '—')} |")
    L.append("")
    L.append(f"DESIGN §3.2 argued **K ≥ 17** from the fill requirement (2·fx·0.18/13.05 = 14.3 px). "
             f"The dataset adopted **K = {r['k']['adopted']}**"
             + (" — so that argument was conservative, and it is recorded as such rather than "
                "quietly overridden." if r["k"]["adopted"] < 17 else "."))
    L.append("")
    L.append("**How the large-K arms fail is the interesting part.** K = 21 and K = 25 do not "
             "merely lose the canopy-backed birds — the merge-mislabel column shows they lose some "
             "of them *by merging the bird into a ~53.9 m canopy component*, which is the failure "
             "DESIGN §2.4 calls *worse than a miss, because it looks like success*. A one-clause "
             "matcher (pixel only, no depth) would have scored those stations as HITS and adopted "
             "K = 21. Clause 2 is what makes the K sweep mean anything.")
    L.append("")
    L.append("**min_area ladder** and **open_iter**:")
    L.append("")
    L.append("| min_area_px | " + " | ".join(str(x["min_area_px"]) for x in r["min_area"]["rows"])
             + " |")
    L.append("|---|" + "---|" * len(r["min_area"]["rows"]))
    L.append("| misses | " + " | ".join(str(len(x["misses"])) for x in r["min_area"]["rows"]) + " |")
    L.append("")
    ma = r["min_area"]
    L.append(f"The ladder BRACKETS the smallest accepted component in "
             f"[{ma['largest_with_fnr_zero']}, {ma['first_failing_min_area_px']}) px, and the "
             f"smallest rendered bird footprint anywhere in the FNR_zero set is "
             f"**{ma['smallest_rendered_bird_footprint_px']} px** (three 46 m stations — the "
             f"render's antialiasing floor, and the same 12 px PROBE B measured on the "
             f"commissioning frames). Adopted **{ma['adopted']}**, i.e. "
             f"{ma['smallest_rendered_bird_footprint_px'] / ma['adopted']:.1f}× headroom.")
    L.append("")
    for row in r["open_iter"]["rows"]:
        L.append(f"- `open_iter={row['open_iter']}`: {len(row['misses'])} misses "
                 f"over {row['denominator']} detectable, unmapped FP {row['unmapped_fp']}"
                 + (f" — misses {row['misses']}" if row["misses"] else ""))
    L.append("")
    L.append("**link_break**, scored on both arms under the CORRECTED merge rule:")
    L.append("")
    L.append("| arm | misses | unmapped FP | merge mislabels | correct splits | range p95 / max (m) "
             "| worst centroid (px) | min bird-pixel fraction | link_cut_px |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for row in r["link_break"]["rows"]:
        L.append(f"| `link_break={row['link_break']}` | {len(row['misses'])} | "
                 f"{row['unmapped_fp']} | {row['merge_mislabels']} | "
                 f"{len(row.get('separated_neighbour_ids', []))} | "
                 f"{row['range_error_p95_m']} / {row['range_error_max_m']} | "
                 f"{row['centroid_error_max_px']} ({row['worst_centroid_station']}) | "
                 f"{row['min_bird_pixel_fraction']} | {row['link_cut_px']} |")
    L.append("")
    lbk = r["link_break"]
    L.append(f"> **{lbk['decision']}**")
    L.append("")
    L.append(f"*Correction to the first pass:* {lbk['correction_to_the_first_pass']}")
    L.append("")
    L.append(f"*Open item, not acted on here:* {lbk['open_item_for_a_pre_registered_round']}")
    L.append("")
    L.append("## Bars")
    L.append("")
    L.append("| metric | value | denominator | bar | result |")
    L.append("|---|---|---|---|---|")
    m = a["metrics"]
    f = m["fnr"]
    L.append(f"| FNR (per background × range bin) | {f['fnr']} | {f['denominator_detectable']} "
             f"detectable of {f['denominator_all_FNR_zero_stations']} FNR_zero | 0 misses | "
             f"**{'PASS' if f['pass'] else 'FAIL'}** |")
    mg = m["merge"]
    L.append(f"| merge mislabels (bird NOT separately matched) | {mg['count']} | "
             f"{mg['denominator_visible_bird_stations']} visible bird stations | 0 | "
             f"**{'PASS' if mg['pass'] else 'FAIL'}** |")
    fp = m["false_positives"]
    L.append(f"| unmapped FP / frame | {fp['unmapped_fp_per_frame']} | {fp['denominator_frames']} "
             f"negative frames | ≤ 0.05 | **{'PASS' if fp['pass'] else 'FAIL'}** |")
    ac = m["accuracy"]
    L.append(f"| range error p95 | {ac['range_error_p95_m']} m | {ac['denominator_matches']} "
             f"matches | ≤ 0.5 m | **{'PASS' if ac['pass'] else 'FAIL'}** |")
    rt = m["runtime"]
    L.append(f"| runtime p95 / max | {rt['seg_wall_ms_p95']} / {rt['seg_wall_ms_max']} ms | "
             f"n={rt['n']} ({rt['reps_per_station']}× per station) | 25 / 100 ms | "
             f"**{'PASS' if rt['pass'] else 'FAIL'}** |")
    dt = m["determinism"]
    L.append(f"| determinism | {len(dt['mismatched'])} mismatched | {dt['denominator_stations']} "
             f"stations | 0 | **{'PASS' if dt['pass'] else 'FAIL'}** |")
    mu = a["mutation"]
    n_red = sum(1 for x in mu["mutants"].values() if x["suite_goes_red"])
    L.append(f"| mutation (mask conjuncts) | {n_red}/{len(mu['mutants'])} red | "
             f"1 canned frame + {a['dataset']['n_frames']} dataset frames | the 2 independent "
             f"terms + the pair | **{'PASS' if mu['all_three_red'] else 'FAIL'}** |")
    L.append("")
    L.append(f"**Quote the runtime row, not the counters.** `metrics.runtime` is the bench: "
             f"p95 **{rt['seg_wall_ms_p95']} ms**, max **{rt['seg_wall_ms_max']} ms**, "
             f"**n = {rt['n']}** ({rt['reps_per_station']}× per station, host). The separate "
             f"`segmenter_counters` block carries a wall-ms trio too, but over the single scoring "
             f"pass (n = {a['segmenter_counters']['seg_wall_ms_n']}); its numbers are smaller and "
             f"they are the ones a reader reaches for by accident. Note the max is "
             f"{rt['seg_wall_ms_max'] / rt['seg_wall_ms_p95']:.1f}× the p95 — both clear the "
             f"25 / 100 ms bars, and that ratio is the part not to lose.")
    L.append("")
    L.append(f"**Merge mislabels are counted only where the bird was NOT also returned as its own "
             f"component.** {mg['separated_neighbour_note']}. On this run the corrected column is "
             f"{mg['count']} and the correct-split column is {mg['separated_neighbour_count']} "
             f"({mg['separated_neighbour_at_background_depth'] or 'none'}).")
    L.append("")
    L.append(f"Mapped FP — **reported, not barred** — {fp['mapped_fp_per_frame']} per frame over "
             f"{fp['denominator_frames']} negative frames "
             f"({fp['mapped_by_tree_geofence']} inside a tree's 3D geofence, "
             f"{fp['mapped_by_ground_or_below_geofence_top']} at or below the 4.8 m geofence top). "
             f"{fp['mapped_note']}")
    L.append("")
    L.append("**Read the FP bar with its mechanism in view.** Nearly every detection on a negative "
             "frame un-projects to a real near object — a canopy or the ground — so the *mapped* "
             "column is where the volume is and the *unmapped* bar is a check that nothing was "
             "detected in EMPTY SPACE. The two bars pull in opposite directions on the same eight "
             "frames: a segmenter that hallucinated a bird to pass the range ladder would score its "
             "own FP bar red on the same run.")
    L.append("")
    L.append(f"Centroid error (reported, not barred — it is what decides whether the box-midpoint "
             f"decision of DESIGN §1.3 stays): p95 **{ac['centroid_error_p95_px']} px**, max "
             f"**{ac['centroid_error_max_px']} px** at `{ac['worst_centroid_station']}` — "
             f"**{ac['worst_centroid_tau_headroom_px']} px of headroom** against the matcher's "
             f"τ = {TAU_PX} px. Range error is **signed positive at every match** "
             f"({ac['range_error_signed_min_m']} to {ac['range_error_signed_max_m']} m): the median "
             f"places the bird slightly FARTHER than its nearest surface, which is the "
             f"fail-dangerous direction and is bounded here by the object's own 0.18 m radius.")
    L.append("")
    fl = m["median_flip_margin"]
    L.append("### Median-flip margin — REPORTED, NOT BARRED, and the number `range_error_p95` "
             "cannot see")
    L.append("")
    L.append(f"The depth that ships with a box is the component's MEDIAN, so a component that is "
             f"part bird and part background tells the truth **only while the bird holds a "
             f"majority of its pixels**. That is a cliff, not a drift. Over "
             f"**{fl['denominator_matched_stations']} matched stations** "
             f"({fl['mixed_components']} of them mixed, {fl['pure_bird_components']} pure bird), "
             f"the minimum bird-pixel fraction is **{fl['min_bird_pixel_fraction']}** and the "
             f"closest approach to a flip is **{fl['min_px_to_median_flip']} px** "
             f"({fl['stations_within_3_px_of_a_flip']} are within 3 px). Bird pixels come from the "
             f"negative-control diff, so no detector is in this loop either.")
    L.append("")
    L.append("| station | range (m) | background | component px | bird px | fraction | px to flip "
             "| reports (m) | would report after a flip (m) |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for x in fl["worst_five"]:
        L.append(f"| {x['id']} | {x['range_m']} | {x['background']} | {x['component_px']} | "
                 f"{x['bird_px']} | {x['bird_pixel_fraction']} | "
                 f"{'—' if x['px_to_median_flip'] is None else x['px_to_median_flip']} | "
                 f"{x['reported_depth_m']} | {x['flipped_depth_m'] or '—'} |")
    L.append("")
    L.append(f"Read the worst row as the safety statement it is: lose "
             f"{fl['min_px_to_median_flip']} pixel(s) of the bird's silhouette to a different "
             f"sub-pixel placement, to antialiasing, or to the motion this static dataset does not "
             f"contain, and the SAME detection reports the canopy's depth instead — a bird at "
             f"~30 m published at ~54 m, which is no threat at all. **The published "
             f"`range_error_p95` of {ac['range_error_p95_m']} m cannot see this**: until the flip "
             f"the range is right to within {ac['range_error_max_m']} m. It is not a bar because "
             f"this fix round is the first run that measures it, and a threshold invented in the "
             f"same pass that first sees the number is a threshold fitted to its own data.")
    L.append("")
    L.append("### FNR cells (background × range)")
    L.append("")
    L.append("| cell | n | missed | FNR |")
    L.append("|---|---|---|---|")
    for k in sorted(f["per_background_x_range"]):
        cell = f["per_background_x_range"][k]
        L.append(f"| {k} | {cell['n']} | {cell['missed']} | {cell['fnr']} |")
    L.append("")
    L.append(f"FNR is conditioned on `{f['conditioned_on']}`. **That condition is vacuous for the "
             f"{f['denominator_all_FNR_zero_stations']} FNR_zero stations** — it excludes "
             f"{len(f['excluded_by_condition'])} of them ({f['excluded_by_condition'] or 'none'}) "
             f"— which is the geometry DESIGN §2.3 predicted: in this world a sub-margin stand-off "
             f"can only occur outside the ±6 m threat band. The stations it does exclude are "
             f"diagnostics: {a['sub_margin_diagnostics']}.")
    L.append("")
    L.append("### Occlusion (group E) — expected non-detections, never misses, never FPs")
    L.append("")
    for sid, o in a["metrics"]["occlusion"]["stations"].items():
        L.append(f"- **{sid}**: rendered bird pixels {o['rendered_bird_pixels']} "
                 f"(occluder proved first: {o['occluder_proved_first']}) → {o['outcome']}")
    L.append("")
    L.append("## Acquisition range (DESIGN §4.4)")
    L.append("")
    aq = a["acquisition"]
    L.append(f"- **cluttered acquisition: {aq['cluttered_acquisition_m']} m** — longest contiguous "
             f"prefix of the range ladder, worst background class per range, every FNR_zero "
             f"station matched. First failing range: {aq['first_failing_range_m']}.")
    L.append(f"- **clutter-backed only to {aq['clutter_backed_max_range_m']} m** — "
             + ", ".join(f"{v} m ({k})"
                         for k, v in sorted(aq["clutter_backed_max_range_by_background"].items(),
                                            key=lambda kv: -kv[1]))
             + (f"; every rung from {aq['sky_backed_only_from_range_m']} m up is sky-backed. "
                if aq["sky_backed_only_from_range_m"] is not None else ". ")
             + "Geometrically forced in this world, not a sampling gap: an in-band bird at 46 m "
               "and 6 m below the optical axis has its ground background at ~86 m, past the 60 m "
               "Euclidean cull, so there is nothing behind it to BE clutter. The booked number "
               "does not change; the claim's reach does.")
    L.append(f"- optical prefix (sky-backed arm, never booked): **{aq['optical_prefix_m']} m**.")
    L.append(f"- clamp = far_clip / `corner_ray_ratio` = 60.0 / {aq['corner_ray_ratio']} = "
             f"**{aq['clamp_bound_m']} m** on the group's live intrinsics.")
    L.append(f"- **booked = min(46.0, measured) = {aq['booked_m']} m**; breakeven at 5 m/s is "
             f"{aq['breakeven_5mps_m']} m → bookable: **{aq['bookable_at_5mps']}**.")
    L.append("")
    L.append(f"> {aq['verdict']}")
    L.append("")
    if aq["limited_by_ladder"]:
        L.append(f"**Read the number as `≥`, not `=`.** {aq['limited_by_ladder_note']}")
    L.append("")
    L.append("| range (m) | n | matched | worst background | all matched |")
    L.append("|---|---|---|---|---|")
    for row in aq["ladder"]:
        L.append(f"| {row['range_m']} | {row['n']} | {row['matched']} | {row['worst_background']} | "
                 f"{row['all_matched']} |")
    L.append("")
    L.append("## Near field and object size — a SYNTHETIC arm, and the one correction it forces")
    L.append("")
    sz = a["size_and_near_field"]
    L.append(f"*{sz['kind']}.* The dataset's nearest station is 14 m and its only object radius is "
             f"0.18 m, so the near field and the large-object case are unmeasured by it.")
    L.append("")
    L.append(f"**Resolving floor, re-measured against THIS operator: "
             f"{sz['resolving_floor_px']} px → {sz['resolving_floor_implied_range_m']} m for a "
             f"0.18 m target.** {sz['resolving_floor_note']}")
    L.append("")
    L.append("| bird range (m) | " + " | ".join(str(x["range_m"])
                                                for x in sz["bird_ladder_radius_0.18m"]) + " |")
    L.append("|---|" + "---|" * len(sz["bird_ladder_radius_0.18m"]))
    L.append("| apparent diameter (px) | " + " | ".join(str(x["apparent_diameter_px"])
                                                        for x in sz["bird_ladder_radius_0.18m"])
             + " |")
    L.append("| components | " + " | ".join(str(x["components"])
                                            for x in sz["bird_ladder_radius_0.18m"]) + " |")
    L.append("")
    L.append(f"{sz['whole_object_crossover_note']} — a 0.18 m bird is never invisible over "
             f"46 → 2 m; below the crossover it returns as rim arcs at its own correct depth, which "
             f"is what the one-to-many clause of the matcher exists for.")
    L.append("")
    L.append("| object radius | blind ranges (m) | blind from apparent diameter (px) |")
    L.append("|---|---|---|")
    for k in sorted(sz["object_size_sweep"]):
        row = sz["object_size_sweep"][k]
        L.append(f"| `{k}` | {row['blind_ranges_m'] or 'none'} | "
                 f"{row['blind_from_diameter_px'] or '—'} |")
    L.append("")
    L.append(f"> **{sz['large_object_blind_zone']}**")
    L.append("")
    L.append("## Two objects at once — the mission's own obstacle density, unmeasured by the render")
    L.append("")
    mo = a["multi_object_probe"]
    L.append(f"*{mo['kind']}.*")
    L.append("")
    L.append("| construction | `link_break=False` | `link_break=True` |")
    L.append("|---|---|---|")
    for name, case in mo["cases"].items():
        off_c, on_c = case["link_break_False"], case["link_break_True"]
        L.append(f"| `{name}` | {off_c['n_boxes']} box(es) at {off_c['depths_m']} m | "
                 f"{on_c['n_boxes']} box(es) at {on_c['depths_m']} m "
                 f"(cut {on_c['link_cut_px']} px, {on_c['components_below_min_area']} below "
                 f"min_area) |")
    L.append("")
    L.append(f"1. **{mo['finding_1_merge_median_belongs_to_neither']}**")
    L.append("")
    L.append(f"2. {mo['finding_2_link_break_can_withhold']}")
    L.append("")
    L.append("## Group D — where the margin's own boundary falls")
    L.append("")
    L.append("| station | declared step (m) | measured stand-off (m) | range (m) | v px | detected |")
    L.append("|---|---|---|---|---|---|")
    for sid, g in a["group_d"]["stations"].items():
        L.append(f"| {sid} | {g['declared_step_m']} | {g['measured_standoff_m']} | "
                 f"{g['range_m']} | {g['v_px']} | {'**yes**' if g['detected'] else 'no'} |")
    L.append("")
    L.append("## Pitched arm (group I, S080–S085) — its own block, never folded into a bar")
    L.append("")
    pt = a["pitched"]
    L.append(f"The dataset's only non-level stations: −12.5° nose-down, the flight's worst observed "
             f"attitude (ADR-020 am. 2). DESIGN §2.6 failure mode 3 called the level-camera "
             f"derivation a named transfer gap; this measures it, on {pt['denominator_birds']} "
             f"bird stations and {pt['fp']['denominator_frames']} negative.")
    L.append("")
    L.append(f"- detected: **{pt['detected']}/{pt['denominator_birds']}** "
             f"(FNR {pt['fnr']}), misses {pt['misses'] or 'none'}")
    L.append(f"- range error median / p95: {pt['accuracy']['range_error_median_m']} / "
             f"{pt['accuracy']['range_error_p95_m']} m over {pt['accuracy']['denominator_matches']} "
             f"matches")
    L.append(f"- unmapped FP: {pt['fp']['unmapped_fp_per_frame']} /frame over "
             f"{pt['fp']['denominator_frames']} frame(s); mapped {pt['fp']['mapped_fp_per_frame']}")
    L.append("")
    L.append("| station | range (m) | background | matched | centroid err (px) | depth err (m) |")
    L.append("|---|---|---|---|---|---|")
    for row in pt["rows"]:
        L.append(f"| {row['id']} | {row['range_m']} | {row['background']} | {row['matched']} | "
                 f"{row['centroid_err_px']} | {row['depth_err_m']} |")
    L.append("")
    L.append("## Mutation check — each mask conjunct deleted in turn (DESIGN §4.5.3)")
    L.append("")
    L.append("| removed term | canned boxes | dataset boxes | dataset FNR misses | unmapped "
             "FP/frame | suite |")
    L.append("|---|---|---|---|---|---|")
    L.append(f"| *(none — intact)* | {mu['intact']['canned_boxes']} | "
             f"{mu['intact']['boxes_total']} | {mu['intact']['fnr_misses']} | "
             f"{mu['intact']['unmapped_fp_per_frame']} | — |")
    for term, x in mu["mutants"].items():
        state = "**RED**" if x["suite_goes_red"] else "GREEN — term not load-bearing"
        L.append(f"| `{term}` | {x['canned_boxes']} | {x['dataset_boxes_total']} | "
                 f"{x['dataset_fnr_misses']} | {x['dataset_unmapped_fp_per_frame']} | {state} |")
    L.append("")
    L.append(f"**Finding.** {mu['redundancy_finding']}")
    L.append("")
    L.append("## Per-group results")
    L.append("")
    L.append("| group | world | stations | visible birds | sub-margin (diag) | matched / "
             "scoreable | unmapped FP |")
    L.append("|---|---|---|---|---|---|---|")
    for g in a["per_group"]:
        L.append(f"| {g['group']} | {g['world']} | {g['n']} | {g['visible_birds']} | "
                 f"{g['sub_margin']} | {g['matched']}/{g['scoreable']} | {g['unmapped_fp']} |")
    L.append("")
    L.append("Sub-margin stations are group D and group H diagnostics — a bird 0.3–0.6 m in front "
             "of a canopy at 33–43 m, which is a **known physical limit of a discontinuity test**, "
             "not a detector miss, and is ~11.8 m below cruise in every case (outside the ±6 m "
             "threat band). They are excluded from the FNR bar by the pre-registered condition and "
             "listed by name above.")
    L.append("")
    L.append("## Fixtures committed as the regression set")
    L.append("")
    L.append("| station | size (KB) | < 500 KB | why |")
    L.append("|---|---|---|---|")
    for fx in a["fixtures"]:
        L.append(f"| `{fx['station_id']}` | {fx['size_kb']} | {fx['under_500kb']} | {fx['why']} |")
    L.append("")
    L.append("## What this run does NOT measure")
    L.append("")
    ev = a["environment"]
    L.append(f"Computed on python {ev['python']} / numpy {ev['numpy']} / scipy {ev['scipy']} "
             f"({ev['platform']}). CI pins {ev['ci_pins']}; the flight container is "
             f"{ev['flight_container_pins']} — three different stacks, and the 3-decimal fixture "
             f"assertions have only ever run on this one.")
    L.append("")
    for gap in a["transfer_gaps"]:
        L.append(f"- {gap}")
    L.append("")
    path.write_text("\n".join(L) + "\n")


# ==================================================================================================

def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dataset", default=str(DATASET_DIR))
    ap.add_argument("--out-dir", default=str(RESULTS_DIR))
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--reps", type=int, default=5, help="timing repeats per station (n >= 5)")
    ap.add_argument("--stamp", default=None,
                    help=("force the artifact's UTC stamp. Exists for exactly one reason: "
                          "DEFAULT_PARAMS_PROVENANCE in src/ names the artifact that chose the "
                          "constants, and without a fixed stamp that reference and the file can "
                          "never be made to agree in one pass."))
    a = ap.parse_args(argv)
    ddir = Path(a.dataset)

    print(f"[1/8] loading + labelling {ddir} ...")
    stations, dmeta = load_dataset(ddir)
    lab = check_labeller(stations)
    rt = check_projection_roundtrip(stations)
    print(f"      max |rendered - recomputed| = {lab['max_rendered_vs_recomputed_px']} px "
          f"({lab['at_station']}); round-trip {rt['max_roundtrip_error_m']} m")

    gmap = GeofenceMap.from_file()
    intr = stations[0].intr
    level = [s for s in stations if not s.is_pitched]
    pitched = [s for s in stations if s.is_pitched]

    print(f"[2/8] constant sweep over {len(level)} level stations ...")
    sw = sweep(level, gmap, intr)
    params = sw["adopted"]
    print(f"      adopted: {params}")

    print("[3/8] scoring at the adopted constants ...")
    rows, seg = run(level, params, gmap)
    prows, pseg = run(pitched, params, gmap)

    print("[4/8] mutation check ...")
    mut = mutation_check(level, params, gmap, intr)
    print("[5/8] determinism + synthetic size/near-field sweep ...")
    det = determinism_check(level, params)
    sizes = size_and_near_field_sweep(intr, params)
    print(f"[6/8] runtime ({a.reps} reps/station) ...")
    run_t = runtime_check(stations, params, a.reps)
    print("[7/8] acquisition + blocks ...")

    fnr = fnr_block(rows, params.margin_m)
    fps = fp_block(rows)
    acc = accuracy_block(rows)
    mrg = merge_block(rows)
    occ = occlusion_block(rows, level)
    acq = acquisition_block(rows, level, intr)
    gd = group_d_block(rows, level)
    flip = flip_block(level, rows, params)
    flip_block(pitched, prows, params)          # injects the same per-station fields into the arm
    multi = multi_object_probe(params)

    pit_bird = [r for r in prows if r["expected_depth_m"] is not None and not r["occluded"]
                and r["in_frame"]]
    pit = {
        "denominator_birds": len(pit_bird),
        "detected": sum(1 for r in pit_bird if r["matched"]),
        "misses": [r["id"] for r in pit_bird if not r["matched"]],
        "fnr": (round(1 - sum(1 for r in pit_bird if r["matched"]) / len(pit_bird), 4)
                if pit_bird else None),
        "accuracy": accuracy_block(prows), "fp": fp_block(prows, pitched=True),
        "rows": prows,
        "pitch_deg": -12.5,
        "note": ("SCORED AND REPORTED AS ITS OWN DIAGNOSTIC BLOCK, never folded into the bars: the "
                 "49-station FNR bar, the 8-frame FP bar and the acquisition ladder are all level-"
                 "camera measurements and stay that way."),
    }

    per_group = []
    gmeta = {g["group"]: g for g in (json.loads(l) for l in
                                     (ddir / "groups.jsonl").read_text().splitlines() if l.strip())}
    for gid in sorted(gmeta):
        gr = [r for r in (rows + prows) if r["group"] == gid]
        vis = [r for r in gr if r["expected_depth_m"] is not None and not r["occluded"]
               and r["in_frame"]]
        sc = [r for r in vis if not r["sub_margin"]]
        per_group.append({"group": gid, "world": gmeta[gid]["world"], "n": len(gr),
                          "visible_birds": len(vis), "sub_margin": len(vis) - len(sc),
                          "scoreable": len(sc), "matched": sum(1 for r in sc if r["matched"]),
                          "unmapped_fp": sum(r.get("fp_unmapped", 0) for r in gr)})

    fixtures = ([] if a.no_write else write_fixtures(stations, ddir, params))

    bars = {"fnr_zero": fnr["pass"], "merge_zero": mrg["pass"], "unmapped_fp": fps["pass"],
            "range_error_p95": acc["pass"], "runtime": run_t["pass"],
            "determinism": det["pass"], "mutation_all_red": mut["all_three_red"]}
    all_pass = all(bars.values())
    verdict = (f"{'ADOPT' if all_pass else 'DO NOT ADOPT'}: "
               f"K={params.bg_window_px} margin={params.margin_m} m min_area={params.min_area_px} "
               f"open_iter={params.open_iter} max_boxes={params.max_boxes} -- FNR "
               f"{fnr['fnr']} over {fnr['denominator_detectable']} detectable stations, unmapped FP "
               f"{fps['unmapped_fp_per_frame']}/frame over {fps['denominator_frames']}, range p95 "
               f"{acc['range_error_p95_m']} m over {acc['denominator_matches']} matches, "
               f"seg p95 {run_t['seg_wall_ms_p95']} ms host; cluttered acquisition "
               f"{acq['cluttered_acquisition_m']} m -> booked {acq['booked_m']} m. "
               f"{'ALL BARS PASS' if all_pass else 'FAILED BARS: ' + str([k for k, v in bars.items() if not v])}")

    stamp = a.stamp or _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"depth_segmenter_score_{stamp}.json"
    art = {
        "schema_version": SCHEMA_VERSION,
        "artifact": name,
        "tool": "eval/score_depth_segmenter.py",
        "generated_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "claims_ceiling": "sim-demonstrated, evidence-gated",
        "dataset": dmeta,
        "labeller": lab,
        "roundtrip": rt,
        "constants": {"bg_window_px": params.bg_window_px, "margin_m": params.margin_m,
                      "min_area_px": params.min_area_px, "open_iter": params.open_iter,
                      "max_boxes": params.max_boxes, "near_m": params.near_m,
                      "far_m": params.far_m, "link_break": params.link_break},
        "constants_sweep": sw["record"],
        "constants_match_module_default": (
            {"bg_window_px": DEFAULT_PARAMS.bg_window_px, "margin_m": DEFAULT_PARAMS.margin_m,
             "min_area_px": DEFAULT_PARAMS.min_area_px, "open_iter": DEFAULT_PARAMS.open_iter,
             "max_boxes": DEFAULT_PARAMS.max_boxes, "near_m": DEFAULT_PARAMS.near_m,
             "far_m": DEFAULT_PARAMS.far_m, "link_break": DEFAULT_PARAMS.link_break}
            == {"bg_window_px": params.bg_window_px, "margin_m": params.margin_m,
                "min_area_px": params.min_area_px, "open_iter": params.open_iter,
                "max_boxes": params.max_boxes, "near_m": params.near_m,
                "far_m": params.far_m, "link_break": params.link_break}),
        "module_default_provenance": DEFAULT_PARAMS_PROVENANCE,
        "metrics": {"fnr": fnr, "merge": mrg, "false_positives": fps, "accuracy": acc,
                    "median_flip_margin": flip, "occlusion": occ, "runtime": run_t,
                    "determinism": det},
        "sub_margin_diagnostics": [r["id"] for r in rows if r["sub_margin"]],
        "acquisition": acq,
        "size_and_near_field": sizes,
        "multi_object_probe": multi,
        "group_d": gd,
        "pitched": pit,
        "mutation": mut,
        "per_group": per_group,
        "fixtures": fixtures,
        "environment": {
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "scipy": __import__("scipy").__version__,
            "platform": sys.platform,
            "ci_pins": "requirements-eval.txt: numpy==2.5.1, scipy==1.18.0 (python 3.12)",
            "flight_container_pins": ("sim/docker/Dockerfile python3-numpy/python3-scipy, jammy: "
                                      "numpy 1.21.5, scipy 1.8.0 (python 3.10)"),
            "note": ("the stack these numbers were computed on. It is NEITHER of the two stacks "
                     "that will re-run them, which is why the version spread is a named transfer "
                     "gap rather than a footnote"),
        },
        "segmenter_counters": seg.counters(),
        "segmenter_counters_note": (
            "CUMULATIVE over the ONE scoring pass across the 79 level stations (seg_wall_ms_n=79). "
            "Its wall-ms trio is NOT the runtime measurement -- quote metrics.runtime, which is the "
            "5-rep bench over n=425 and whose max is ~1.8x its own p95. Two different denominators, "
            "and the smaller one is the one a reader reaches for first by accident."),
        "stations": rows + prows,
        "bars": bars,
        "all_bars_pass": all_pass,
        "transfer_gaps": [
            "STATIC VEHICLE. Every frame is a parked teleport; motion blur, rolling shutter and "
            "pose/frame pairing error are not in this measurement.",
            "NOISELESS SENSOR (proposed TG-6). gz writes no depth noise. Noise enters the "
            "maximum_filter as a max over K^2 samples, which is biased UPWARD -- it inflates the "
            "background and pushes FP up rather than FN, the safer direction, but it is unquantified.",
            "ONE TARGET RADIUS. Every station uses the world's 0.18 m bird; the resolving floor's "
            "sensitivity to target size is unbounded by this run.",
            "ONE TARGET PER FRAME. Every one of the 85 stations has exactly one bird in the world "
            "(birds 1 and 2 are parked out of every frustum), while CLAUDE.md's MVP obstacle "
            "density is 2-3 scripted birds. Multi-object merging is therefore UNMEASURED on the "
            "render, and `multi_object_probe` shows the direction it fails in: two touching near "
            "objects return ONE component at a median belonging to NEITHER (20 m beside 30 m reads "
            "25 m). The cheap close is one extra teleport per camera pose in whatever renders next.",
            "VERSION SPREAD. The constants and every 3-decimal number here were computed on the "
            "`environment` block's stack. CI runs the pinned numpy 2.5.1 / scipy 1.18.0 on python "
            "3.12 and the flight container runs jammy's numpy 1.21.5 / scipy 1.8.0 on python 3.10 "
            "-- and the artifact test asserts box counts and depths out of a scipy morphology, "
            "while DESIGN §1.4 claims byte-identical output on any machine with the pinned scipy, "
            "which has never been executed on either target. BOOKED, 60 seconds on the next "
            "container session: `python3 -m pytest tests/fieldguard_planning/test_depth_segment.py "
            "-q` inside the sim image. If scipy 1.8.0 moves one pixel on one fixture, the 3-dp "
            "assertions in test_depth_segmenter_score_artifact.py are where it surfaces.",
            "LEVEL ATTITUDE for every bar. The pitched arm is 5 bird stations at one attitude, "
            "reported separately; roll is not sampled at all.",
            "HOST TIMING. The runtime numbers are macOS; the container measured ~1.2x on comparable "
            "work and the number that settles it is the first flight's own counter.",
            "ONE WORLD. Eight camera poses in one orchard; foliage here is a smooth sphere, and "
            "real foliage has self-depth structure with pits narrower than K.",
        ],
        "verdict": verdict,
    }

    print(f"[8/8] {verdict}")
    if not a.no_write:
        out = Path(a.out_dir) / name
        out.write_text(json.dumps(art, indent=1, default=str) + "\n")
        write_report(ddir / "REPORT.md", art)
        print(f"      wrote {out}")
        print(f"      wrote {ddir / 'REPORT.md'}")
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(main())
