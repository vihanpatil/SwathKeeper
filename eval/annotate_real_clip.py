#!/usr/bin/env python3
"""Reconstruct per-frame bird ground truth for a REAL recorded clip (unblocks the ADR-003 re-run).

The synthetic spike clips ship `birds[]` on every `poses.jsonl` line because the generator knew
where the birds were. The live recorder (`src/fieldguard_planning/clip_recorder.py`) cannot --
nothing in the ROS 2 graph publishes bird poses -- so a real clip arrives with no bird labels at
all. `scripts/drive_birds.py` is the only thing that moves them, so this script reconstructs the
labels from what that driver did.

TWO SOURCES, AND THEY ARE NOT EQUALS (ADR-003 amendment 6):

  1. **`--applied-log` -- MEASUREMENT, the default whenever it exists.** The driver records every
     set_pose call it made: the pose, the trajectory time it was computed for, a sim-time bracket
     around the call, and whether it landed. A frame then shows the last pose that had definitely
     ARRIVED before its stamp -- which is what the renderer actually painted. Failed calls hold the
     previous pose, exactly as the render did.

  2. **`--sidecar` t0 alone -- MODEL, and a measurably wrong one on a real render.** Without the
     log all that is left is `pose_at(F.stamp_sim_s - t0_sim)`: where the driver would have asked
     the bird to be at that instant. That is NOT where the render put it. Measured on the
     2026-08-22 flagship take: the driver's poses arrive one whole tick (0.43 s of sim) plus an
     unrecorded per-call service latency late, so the modelled labels sat a mean 198 px -- up to
     313 px, against boxes 21-47 px wide -- from the bird the detector actually saw, on every one
     of the 22 detections. IoU can never match across that. Such labels are emitted (they still say "a bird
     was roughly here") but marked `label_src: "modeled"`, and `eval/score.py` refuses to decide
     ADR-003 on them rather than scoring a detector against a bird that was never there.

Both paths replay the SAME `drive_birds.pose_at` / applied-log readers -- imported, never
re-implemented: a second copy would drift from the driver silently, and both sides are supposed to
describe one physical bird.

Frames stamped before the driver's first successful set_pose are labelled at the SPAWN pose
(`label_src: "spawn"`) -- exact, not modelled: `gen_farm_world.sdf_bird_model` spawns each bird as
a <static> model at waypoints[0] and nothing moves it until that call lands (ADR-012 amendment 1).

    python3 eval/annotate_real_clip.py --clip eval/results/clips/<clip> \
        --sidecar eval/results/bird_drive_20260818T161200Z.json      # log auto-discovered
    python3 eval/annotate_real_clip.py --clip <clip> --bird-t0 152.44 --in-place

Default output is `<clip>/poses_annotated.jsonl` and the recording is left untouched; `--in-place`
rewrites `poses.jsonl` (atomically) once you have eyeballed a line.

Honesty note that survives both paths: these are still COMMANDED poses -- what the driver asked
Gazebo for -- not poses observed back out of the running world (the rule the coverage ledger lives
by: commanded is never recorded as flown). The applied log closes the timing half of that gap by
measuring when each command landed; a frame that falls INSIDE a call's bracket is genuinely
undecidable and is marked `label_ambiguous`, not silently rounded to one side.

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

from drive_birds import (  # noqa: E402
    DEFAULT_BIRDS_CONFIG, applied_log_path_for, applied_sim_brackets, pose_at, read_applied_log,
)

# Label provenance, worst-first. Only the first two are evidence; "modeled" is an estimate whose
# error is bounded by nothing the run recorded, which is why score.py treats it as unscoreable.
SRC_SPAWN = "spawn"        # exact: the static model has not been moved yet
SRC_APPLIED = "applied"    # measured: the last set_pose that had landed by this frame's stamp
SRC_MODELED = "modeled"    # estimated: what the driver WOULD have asked for at this stamp


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


def bird_entry(bird: dict, t_traj_s: float, pos_m: Optional[Sequence[float]] = None,
               label_src: str = SRC_MODELED, ambiguous: bool = False) -> dict:
    """One `birds[]` entry in the sim/spike/README.md schema.

    Only `bird_id`, `pos_m` and `physical_radius_m` are required: the README's own "only ... are
    required to independently reproduce ground truth" list, confirmed against the consumer --
    `eval/label_from_sim.py` reads exactly those three (plus an OPTIONAL `range_m`, used only to
    pick overlay frames). The synthetic generator's `ndvi_value`/`rgb_color` describe how IT painted
    a bird and have no meaning for a real Gazebo render, so they are deliberately not fabricated
    here. `traj_t_s` is provenance: it makes "is this label right?" checkable by hand against the
    waypoint file, which a bare position is not.

    `label_src` travels WITH the position all the way into ground_truth.json, because "where the
    bird was" and "how well we know that" are one fact, not two, and separating them is how a
    modelled guess gets scored as if it were a measurement."""
    if pos_m is None:
        x, y, z, _yaw = pose_at(t_traj_s, bird["waypoints"], bird.get("loop", True))
        pos_m = (x, y, z)
    entry = {
        "bird_id": bird["bird_id"],
        "pos_m": [round(c, 6) for c in pos_m],
        "physical_radius_m": bird["physical_radius_m"],
        "traj_t_s": round(t_traj_s, 6),
        "label_src": label_src,
    }
    if ambiguous:
        entry["label_ambiguous"] = True
    return entry


def applied_timeline(records: Sequence[dict]) -> dict:
    """bird_id -> [(sim_start, sim_end, pos_m, t_traj_s)] for the calls that LANDED, in order.

    Failed calls are dropped on purpose and that IS the fix for them: a call that failed never
    changed the render, so the bird held whatever the previous successful call left it at -- which
    is exactly what a lookup over successful calls only returns. Records that cannot be placed on
    the sim clock (a wall-clock driver run) are dropped too; the caller sees a shorter timeline and
    the `--sidecar` refusal for wall-clock runs already covers that case."""
    brackets = applied_sim_brackets(records)
    by_bird: dict = {}
    for rec, bracket in zip(records, brackets):
        if not rec.get("ok") or bracket is None:
            continue
        by_bird.setdefault(rec["bird_id"], []).append(
            (bracket[0], bracket[1], tuple(rec["pos_m"]), rec.get("t_traj_s")))
    for entries in by_bird.values():
        entries.sort(key=lambda e: e[1])
    return by_bird


def pose_from_applied(entries: Sequence[tuple], t_sim_s: float):
    """(pos_m, t_traj_s, ambiguous) the render was showing at `t_sim_s`, or None before the first
    landed call.

    "Showing" = the last call whose reply had come back by then (`sim_end <= t`): the pose is
    certainly applied by the time Gazebo answers, and not certainly before the request went out.
    A frame inside a call's bracket falls in the gap between those two certainties, so it is
    reported `ambiguous` rather than rounded to whichever side flatters the score."""
    chosen = None
    for start, end, pos, t_traj in entries:
        if end <= t_sim_s:
            chosen = (pos, t_traj)
        else:
            break
    ambiguous = any(start <= t_sim_s < end and (chosen is None or pos != chosen[0])
                    for start, end, pos, _t in entries)
    if chosen is None:
        return None if not ambiguous else (None, None, True)
    return (chosen[0], chosen[1], ambiguous)


def annotate_lines(lines: Sequence[dict], birds: Sequence[dict], t0_sim_s: float,
                   applied: Optional[dict] = None) -> Tuple[List[dict], dict]:
    """Add `birds[]` to every pose line, keyed on that frame's own `stamp_sim_s`. Every existing
    key is preserved untouched; a pre-existing `birds[]` is REPLACED, not appended to, so
    re-annotating with a corrected t0 (or with a log the first pass lacked) is idempotent.

    `applied` is `applied_timeline(...)` -- when present it decides every label it can, and t0 is
    used only for the `traj_t_s` provenance of the frames it cannot (those before the first landed
    call, which are the spawn pose regardless). Returns (annotated_lines, stats)."""
    out: List[dict] = []
    replaced = 0
    t_traj: List[float] = []
    src_counts = {SRC_SPAWN: 0, SRC_APPLIED: 0, SRC_MODELED: 0}
    n_ambiguous = 0
    for i, line in enumerate(lines):
        if "stamp_sim_s" not in line:
            raise ValueError(
                f"poses.jsonl line {i} (frame_id={line.get('frame_id')}) has no stamp_sim_s. Only "
                f"clip_recorder schema >= 1.1 records the frame's Gazebo stamp, and `t_s` is "
                f"relative to the clip's first frame, NOT the sim clock the birds fly on -- "
                f"refusing to guess an offset.")
        stamp = float(line["stamp_sim_s"])
        t = stamp - t0_sim_s
        entries = []
        for b in birds:
            found = None if applied is None else pose_from_applied(
                applied.get(b["bird_id"], ()), stamp)
            if found is not None and found[0] is not None:
                pos, t_traj_s, ambiguous = found
                entries.append(bird_entry(b, t_traj_s if t_traj_s is not None else t, pos,
                                          SRC_APPLIED, ambiguous))
            elif applied is not None or t <= 0.0:
                # No landed call yet (or the frame predates the driver entirely): the <static> model
                # is still sitting at waypoints[0]. Exact, not modelled -- ADR-012 amendment 1.
                ambiguous = bool(found is not None and found[2])
                entries.append(bird_entry(b, min(t, 0.0), None, SRC_SPAWN, ambiguous))
            else:
                entries.append(bird_entry(b, t, None, SRC_MODELED))
            src_counts[entries[-1]["label_src"]] += 1
            n_ambiguous += 1 if entries[-1].get("label_ambiguous") else 0
        annotated = dict(line)
        if "birds" in line:
            replaced += 1
        annotated["birds"] = entries
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
        "label_src_counts": src_counts,
        "n_label_ambiguous": n_ambiguous,
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
    ap.add_argument("--applied-log", type=Path, default=None,
                    help="drive_birds applied-pose log (bird_drive_<UTCstamp>_applied.jsonl). "
                         "Auto-discovered next to --sidecar; pass it explicitly for a run whose "
                         "sidecar moved. Labels from this log are MEASURED; without it they are "
                         "modelled and eval/score.py will refuse to decide ADR-003 on them.")
    ap.add_argument("--no-applied-log", action="store_true",
                    help="ignore the applied-pose log even if one exists (for reproducing a "
                         "pre-2026-08-22 modelled labelling; not for scoring)")
    args = ap.parse_args(argv)

    if args.sidecar is not None:
        sidecar = json.loads(args.sidecar.read_text())
        t0 = t0_from_sidecar(sidecar, str(args.sidecar))
    else:
        sidecar, t0 = None, float(args.bird_t0)

    log_path = args.applied_log
    if log_path is None and args.sidecar is not None and not args.no_applied_log:
        # The sidecar NAMES its log (schema >= 1.1); older sidecars get the same convention tried
        # anyway, which costs one stat() and rescues a run whose sidecar predates the field.
        named = (sidecar.get("applied_log") or applied_log_path_for(args.sidecar).name)
        candidate = args.sidecar.parent / named
        log_path = candidate if candidate.exists() else None
    applied = None
    if log_path is not None and not args.no_applied_log:
        records = read_applied_log(log_path)
        applied = applied_timeline(records)
        n_ok = sum(1 for r in records if r.get("ok"))
        print(f"[annotate_real_clip] applied-pose log {log_path}: {len(records)} calls, {n_ok} "
              f"landed, {len(records) - n_ok} failed (a failed call means the bird HELD -- the "
              f"labels hold with it)")

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

    if applied is not None:
        # Two ways to hold the WRONG log, both of which would otherwise produce a full set of
        # confident spawn-pose labels: a bird the log never moved, and a log from another run.
        missing = [b["bird_id"] for b in birds if not applied.get(b["bird_id"])]
        if missing:
            print(f"[annotate_real_clip] WARNING: {missing} have no landed set_pose in this log -- "
                  f"they will be labelled at the spawn pose for the WHOLE clip. Correct if the "
                  f"driver never reached them; a wrong log looks exactly like this.",
                  file=sys.stderr)
        spans = [e for entries in applied.values() for e in entries]
        if spans:
            log_lo, log_hi = min(e[0] for e in spans), max(e[1] for e in spans)
            clip_lo = min(float(l["stamp_sim_s"]) for l in lines if "stamp_sim_s" in l)
            clip_hi = max(float(l["stamp_sim_s"]) for l in lines if "stamp_sim_s" in l)
            if log_hi < clip_lo or log_lo > clip_hi:
                print(f"[annotate_real_clip] WARNING: the log covers sim {log_lo:.1f}..{log_hi:.1f}s "
                      f"and this clip covers {clip_lo:.1f}..{clip_hi:.1f}s -- they do not overlap "
                      f"at all, so this log is almost certainly from a different run.",
                      file=sys.stderr)

    annotated, stats = annotate_lines(lines, birds, t0, applied)

    n_modeled = stats["label_src_counts"][SRC_MODELED]
    if n_modeled:
        print(f"[annotate_real_clip] WARNING: {n_modeled} bird-labels are MODELED "
              f"(pose_at(stamp - t0)) because this run left no applied-pose log. That is what the "
              f"driver ASKED for at each stamp, not what the render showed: measured on the "
              f"2026-08-22 flagship take, the render lagged by one driver tick plus an unrecorded "
              f"service latency, putting these labels a mean 198 px (max 313 px) off the bird. "
              f"They are marked label_src=\"modeled\" and eval/score.py will refuse to decide "
              f"ADR-003 on them (ADR-003 amendment 6).", file=sys.stderr)
    if stats["n_label_ambiguous"]:
        print(f"[annotate_real_clip] NOTE: {stats['n_label_ambiguous']} bird-labels fall inside a "
              f"set_pose call's own sim-time bracket -- the pose may or may not have landed by that "
              f"frame. Marked label_ambiguous rather than rounded.", file=sys.stderr)

    if stats["n_pre_driver_start"]:
        print(f"[annotate_real_clip] NOTE: {stats['n_pre_driver_start']}/{stats['n_frames']} frames "
              f"predate the driver (earliest {-stats['t_traj_min_s']:.2f}s before t0_sim={t0:.3f}s) "
              f"and are labelled at the SPAWN pose -- where the static bird models sat until the "
              f"first set_pose, so those labels are ground truth. Expected when the recorder starts "
              f"before the birds; if that lead-in is longer than the gap you actually left, you are "
              f"holding the wrong sidecar.", file=sys.stderr)

    out_path = (args.clip / "poses.jsonl") if args.in_place else (args.clip / "poses_annotated.jsonl")
    write_poses(out_path, annotated)
    counts = stats["label_src_counts"]
    print(f"[annotate_real_clip] {stats['n_frames']} frames x {stats['n_birds']} birds "
          f"(t0_sim={t0:.3f}s, trajectory t {stats['t_traj_min_s']:.2f}..{stats['t_traj_max_s']:.2f}s"
          f"{', %d pre-existing birds[] replaced' % stats['n_replaced'] if stats['n_replaced'] else ''})"
          f" -> {out_path}")
    print(f"[annotate_real_clip] label provenance: {counts[SRC_APPLIED]} applied (measured), "
          f"{counts[SRC_SPAWN]} spawn (exact), {counts[SRC_MODELED]} modeled (unscoreable)")
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
