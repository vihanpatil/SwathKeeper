#!/usr/bin/env python3
"""Reconstruct per-frame bird ground truth for a REAL recorded clip (unblocks the ADR-003 re-run).

The synthetic spike clips ship `birds[]` on every `poses.jsonl` line because the generator knew
where the birds were. The live recorder (`src/fieldguard_planning/clip_recorder.py`) cannot --
nothing in the ROS 2 graph publishes bird poses -- so a real clip arrives with no bird labels at
all. It does not need them: the birds are DETERMINISTIC. `scripts/drive_birds.py` flies the
committed `config/birds/farm_world_birds.json` waypoints on the GAZEBO SIM clock, and every real
pose line records that frame's own gz stamp, so

    bird position in frame F  =  pose_at(F.stamp_sim_s - t0_sim, waypoints)

with `t0_sim` the driver's startup anchor (printed at startup AND written to its run sidecar,
`eval/results/bird_drive_<UTCstamp>.json`). This script replays the SAME `drive_birds.pose_at`
interpolation -- imported, never re-implemented: a second copy of that interpolation would drift
from the driver silently, and both sides are supposed to describe one physical bird.

2026-08-20: frames stamped BEFORE the driver started are now labelled at the spawn pose instead of
being flagged unshippable -- `pose_at`'s wrap is forward-only, and a static bird sitting at
waypoints[0] until the first set_pose is ground truth, not a guess (ADR-012 amendment 1).

    python3 eval/annotate_real_clip.py --clip eval/results/clips/<clip> \
        --sidecar eval/results/bird_drive_20260818T161200Z.json
    python3 eval/annotate_real_clip.py --clip <clip> --bird-t0 152.44 --in-place

Default output is `<clip>/poses_annotated.jsonl` and the recording is left untouched; `--in-place`
rewrites `poses.jsonl` (atomically) once you have eyeballed a line.

Two honesty notes, both load-bearing before anyone scores against these labels:
  * They are COMMANDED bird poses -- what the driver asked for at that sim stamp -- not observed
    Gazebo poses (same rule the coverage ledger lives by: commanded is never recorded as flown).
    The rendered bird sits at the last successfully applied set_pose, i.e. one driver tick of SIM
    time stale: period x RTF, ~1 cm at the RTF<<1 this software-rendered stack actually runs at,
    but ~1.2 m at RTF~1 (bird_0 flies 6 m/s). Read the driver's failure counter before trusting
    sub-metre labels.
  * `eval/label_from_sim.py` still cannot turn an annotated real clip into boxes -- it needs a
    per-frame `camera` block and an orientation-aware projection. See eval/README.md
    "Ground truth for real clips". This script writes the bird half of that contract only.

Dependency: stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from drive_birds import DEFAULT_BIRDS_CONFIG, pose_at  # noqa: E402


def load_birds(config_path: Path) -> List[dict]:
    birds = json.loads(Path(config_path).read_text())["birds"]
    if not birds:
        raise ValueError(f"{config_path} defines no birds -- nothing to annotate with")
    return birds


def t0_from_sidecar(sidecar: dict, source: str = "sidecar") -> float:
    """Startup sim-time anchor out of a `drive_birds` run sidecar. Refuses a wall-clock run: that
    mode has no sim anchor at all, so a clip's gz stamps cannot be mapped back onto trajectories
    (guessing one would produce plausible, wrong, unfalsifiable labels)."""
    t0 = sidecar.get("t0_sim_s")
    if t0 is None:
        raise ValueError(
            f"{source} records clock={sidecar.get('clock')!r} with t0_sim_s=null -- that run timed "
            f"the birds on the WALL clock, so no sim anchor exists and a recorded clip's stamps "
            f"cannot be mapped onto the trajectories. Re-fly with the default sim-time driver.")
    return float(t0)


def bird_entry(bird: dict, t_traj_s: float) -> dict:
    """One `birds[]` entry in the sim/spike/README.md schema.

    Only `bird_id`, `pos_m` and `physical_radius_m` are emitted: the README's own "only ... are
    required to independently reproduce ground truth" list, confirmed against the consumer --
    `eval/label_from_sim.py` reads exactly those three (plus an OPTIONAL `range_m`, used only to
    pick overlay frames). The synthetic generator's `ndvi_value`/`rgb_color` describe how IT painted
    a bird and have no meaning for a real Gazebo render, so they are deliberately not fabricated
    here. `traj_t_s` is provenance: it makes "is this label right?" checkable by hand against the
    waypoint file, which a bare position is not."""
    x, y, z, _yaw = pose_at(t_traj_s, bird["waypoints"], bird.get("loop", True))
    return {
        "bird_id": bird["bird_id"],
        "pos_m": [round(x, 6), round(y, 6), round(z, 6)],
        "physical_radius_m": bird["physical_radius_m"],
        "traj_t_s": round(t_traj_s, 6),
    }


def annotate_lines(lines: Sequence[dict], birds: Sequence[dict],
                   t0_sim_s: float) -> Tuple[List[dict], dict]:
    """Add `birds[]` to every pose line, keyed on that frame's own `stamp_sim_s`. Every existing
    key is preserved untouched; a pre-existing `birds[]` is REPLACED, not appended to, so
    re-annotating with a corrected t0 is idempotent. Returns (annotated_lines, stats)."""
    out: List[dict] = []
    replaced = 0
    t_traj: List[float] = []
    for i, line in enumerate(lines):
        if "stamp_sim_s" not in line:
            raise ValueError(
                f"poses.jsonl line {i} (frame_id={line.get('frame_id')}) has no stamp_sim_s. Only "
                f"clip_recorder schema >= 1.1 records the frame's Gazebo stamp, and `t_s` is "
                f"relative to the clip's first frame, NOT the sim clock the birds fly on -- "
                f"refusing to guess an offset.")
        t = float(line["stamp_sim_s"]) - t0_sim_s
        annotated = dict(line)
        if "birds" in line:
            replaced += 1
        annotated["birds"] = [bird_entry(b, t) for b in birds]
        out.append(annotated)
        t_traj.append(t)
    stats = {
        "n_frames": len(out),
        "n_birds": len(birds),
        "n_replaced": replaced,
        # A negative trajectory time means the frame predates the driver -- routine, since the
        # recorder starts before the birds. Those frames are labelled at the spawn pose, which is
        # where the static models physically sat until the first set_pose (ADR-012 amendment 1).
        # Still counted: a count far larger than the gap actually left is what a WRONG sidecar
        # looks like, and only the operator knows that gap.
        "n_pre_driver_start": sum(1 for t in t_traj if t < 0.0),
        "t_traj_min_s": min(t_traj) if t_traj else None,
        "t_traj_max_s": max(t_traj) if t_traj else None,
    }
    return out, stats


def read_poses(path: Path) -> List[dict]:
    return [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]


def write_poses(path: Path, lines: Sequence[dict]) -> None:
    """Write JSONL via tmp file + os.replace: `--in-place` targets the one copy of a flight that
    cost a Docker session, so a crash mid-write must not leave a truncated recording."""
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")
        fh.flush()
    os.replace(tmp, path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clip", type=Path, required=True,
                    help="recorded clip directory (the one holding poses.jsonl)")
    anchor = ap.add_mutually_exclusive_group(required=True)
    anchor.add_argument("--sidecar", type=Path,
                        help="drive_birds run sidecar (eval/results/bird_drive_<UTCstamp>.json)")
    anchor.add_argument("--bird-t0", type=float, metavar="T0_SIM_S",
                        help="driver startup sim time, for runs that predate the sidecar (the "
                             "'[drive_birds] sim-time mode, t0=...' console line)")
    ap.add_argument("--config", type=Path, default=DEFAULT_BIRDS_CONFIG,
                    help="bird waypoint config the driver flew (default: this repo's "
                         "config/birds/farm_world_birds.json)")
    ap.add_argument("--in-place", action="store_true",
                    help="rewrite <clip>/poses.jsonl (default: write poses_annotated.jsonl next to "
                         "it and leave the recording untouched)")
    args = ap.parse_args(argv)

    if args.sidecar is not None:
        sidecar = json.loads(args.sidecar.read_text())
        t0 = t0_from_sidecar(sidecar, str(args.sidecar))
    else:
        sidecar, t0 = None, float(args.bird_t0)

    birds = load_birds(args.config)
    if sidecar is not None:
        flown = sidecar.get("bird_ids")
        if flown is not None and list(flown) != [b["bird_id"] for b in birds]:
            print(f"[annotate_real_clip] WARNING: the run flew {list(flown)} but --config defines "
                  f"{[b['bird_id'] for b in birds]} (sidecar config: {sidecar.get('config')}) -- "
                  f"labels will describe a different set of birds than the render",
                  file=sys.stderr)

    meta_path = args.clip / "meta.json"
    if meta_path.exists() and json.loads(meta_path.read_text()).get("synthetic"):
        print("[annotate_real_clip] WARNING: this clip's meta.json says synthetic:true -- the "
              "generator already wrote authoritative birds[]; overwriting it with farm-world "
              "trajectories the clip was never rendered with", file=sys.stderr)

    lines = read_poses(args.clip / "poses.jsonl")
    if not lines:
        raise SystemExit(f"[annotate_real_clip] {args.clip}/poses.jsonl has no frames")
    annotated, stats = annotate_lines(lines, birds, t0)

    if stats["n_pre_driver_start"]:
        print(f"[annotate_real_clip] NOTE: {stats['n_pre_driver_start']}/{stats['n_frames']} frames "
              f"predate the driver (earliest {-stats['t_traj_min_s']:.2f}s before t0_sim={t0:.3f}s) "
              f"and are labelled at the SPAWN pose -- where the static bird models sat until the "
              f"first set_pose, so those labels are ground truth. Expected when the recorder starts "
              f"before the birds; if that lead-in is longer than the gap you actually left, you are "
              f"holding the wrong sidecar.", file=sys.stderr)

    out_path = (args.clip / "poses.jsonl") if args.in_place else (args.clip / "poses_annotated.jsonl")
    write_poses(out_path, annotated)
    print(f"[annotate_real_clip] {stats['n_frames']} frames x {stats['n_birds']} birds "
          f"(t0_sim={t0:.3f}s, trajectory t {stats['t_traj_min_s']:.2f}..{stats['t_traj_max_s']:.2f}s"
          f"{', %d pre-existing birds[] replaced' % stats['n_replaced'] if stats['n_replaced'] else ''})"
          f" -> {out_path}")
    if not args.in_place:
        print("[annotate_real_clip] next:")
        print(f"  1. spot-check one line   head -1 {out_path}")
        print(f"     (a bird's pos_m must match config/birds/*.json at its traj_t_s)")
        print(f"  2. adopt it              re-run the same command with --in-place")
        print(f"  3. GT boxes              eval/label_from_sim.py cannot read a real clip yet; see")
        print(f"                           eval/README.md 'Ground truth for real clips'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
