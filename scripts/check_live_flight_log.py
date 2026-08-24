#!/usr/bin/env python3
"""Evidence gate for flight-log JSONs (eval/results/*flight_log*.json) -- qa-safety-owned.

WHY THIS EXISTS: eval/results/live_flight_log.json -- the only machine artifact of the 2026-08-05
live end-to-end avoidance demo (docs/runbooks/AVOIDANCE_DEMO.md) -- was silently OVERWRITTEN by a
later idle run: `flown_path_enu` = [] and all 720 cells at status "debt". Nothing validated the
file, so nothing noticed. This script is that missing validation; avoidance_node.py now also writes
timestamped filenames (live_flight_log_<UTCstamp>.json) so a new run can never clobber prior
evidence again.

A flight log is VALID iff all of:
  1. it parses as JSON and carries the flight-log contract keys checked here
     (`flown_path_enu`, `coverage_ledger` -- see AvoidanceExecutor.flight_log);
  2. the coverage ledger satisfies the check_ledger partition invariant (P1-P3) against the
     canonical grid (repo field polygon, at the log's own `cell_size_m`);
  3. `flown_path_enu` is non-empty -- an empty path means the node never received a pose: an idle
     bringup, not flight evidence;
  4. NOT every grid cell is "debt" -- an all-debt ledger imaged nothing, which is again an idle
     run wearing a flight log's clothes (that is honest accounting per the ADR-002 v1 bar, but it
     is not evidence of a flight);
  5. CLOSEST POINT OF APPROACH to every logged detection is at least the policy's own
     `min_bird_clearance_m` (ADR-013 amendment 12, R1);
  6. and, for a log carrying a `run` block with `schema_version >= 2`, the per-decision gates in
     the SCHEMA-2 section below (clock domain, R2 swept-tree clearance, R3 degenerate re-latch,
     and CPA measured against the BIRD GROUND-TRUTH TRACK rather than the drone's own detections).

TWO VERSIONS, ON PURPOSE, AND THE OLD ONE IS A CLOSED LIST. Recorded history keeps the verdict it
was flown under: a log with no `run` block takes the legacy path unchanged (5 above), which is what
preserves the ACKNOWLEDGED status of the two historical breach logs and the CI-generated
`eval/scenarios/*/flight_log.json`. But it takes that path ONLY if it is PINNED as pre-seam
(`PRE_SEAM_LEGACY_STEMS` / the scenario-fixture shape) -- because `avoidance_node.py` writes the
`run` block on every flight since the 2026-08-24 seam, so on any other log an absent run block is a
fault or tampering, and `del log["run"]` would otherwise be a one-key downgrade out of every
schema-2 gate. Likewise a log that carries a `run` block whose `schema_version` is unreadable is
INVALID rather than quietly demoted to legacy: a downgrade is a defect, not a default.

WHY GATE-5 CHANGES SHAPE UNDER A REAL DETECTOR. `closest_approach()` measures the flown path
against the LOGGED DETECTIONS. With the demo bird that is exact -- the "bird" is a constant we
chose. With the ADR-003 NDVI blob detector it is self-referential: apparent-size ranging has
metre-scale error (3.27 m estimated vs 3.92 m true on the adopted clip), and a MISS at closest
approach produces no detection there at all, so the flight would score "NO-CPA-EVIDENCE -> VALID"
precisely when the detector failed at the worst moment. Under schema 2 the gated number is
`gt_cpa_m`, computed against `scripts/drive_birds.py`'s applied-pose log (the only thing that moves
a bird in this world, recorded per set_pose call with a sim-time bracket). No truth track = INVALID
("no truth track"), never VALID: "we never looked" and "nothing came close" are opposite claims.
The detection-derived number is still printed, relabelled `detection_cpa_m` and explicitly NOT a
gate -- it is the estimator-error measurement ADR-009's second-sensor comparison arm exists to make.

SEVEN WAYS A SCHEMA-2 PASS COULD STILL MEAN NOTHING (closed 2026-08-24, every one measured on a
probe against this file's own code before it was closed):
  * A FROZEN TIME AXIS. `run.clock` stays `gz_clock_stream`/0 violations when the node's clock
    thread dies or Gazebo pauses -- `_gz_now` just stops advancing -- and the domain tripwire only
    fires on a tick that carries a detection. `ground_truth_cpa` joins every tick by that stamp, so
    a stalled axis scored one flown path at 3.4490 m (VALID) that a live axis scored at 2.0402 m
    (BREACH), both reporting 100 % truth coverage. `gate_clock` requires the axis to MOVE; shorter
    stalls are PRICED (`freeze_debit_m`), because a bound sized against anything but "how far can a
    bird move unseen" is a bound sized against the wrong thing (a 5-tick stall turned a 0.0000 m
    strike into a 3.5000 m pass under the first version of this gate).
  * A DISCRETISED CPA, on either axis. `gt_cpa_m` used to be a minimum over the 5 Hz flown-path
    VERTICES, which is >= the true minimum by construction: a 2.8200 m polyline CPA reported
    3.0008 m PASS at the measured 2.052 m/tick step. It is now a minimum over the flown POLYLINE
    (point-to-SEGMENT). The BIRD half of the same defect survived that fix: sampling the bird at
    tick instants never sees a landed `set_pose` whose whole in-effect window falls between two
    ticks, and the bird is the faster body -- a bird driven through a hovering drone at a 0.70 s
    tick period reported 3.8067 m -> VALID on a 0.0000 m strike, at 24/24 truth coverage. Every
    landed pose is now ALSO scored against the drone polyline over its own window
    (`pose_windows`), with `truth_poses_scored/total` as that axis's own denominator.
  * A DETECTOR THAT NEVER RAN, OR BARELY RAN. `NdviDetectionSource` drops every frame until
    `/fg/ndvi/camera_info` arrives; the node has no startup guard on it. A log with
    `frames_detected_on: 0` and 1200 dropped frames scored VALID and printed nothing about it, and
    1 frame of 1256 was no better. `gate_detector_ran` fails both (`MIN_DETECT_RATE`).
  * A STALENESS GATE THAT ATE THE FLIGHT. All-stale detections produce PROCEED on every tick, and
    PROCEED used to carry no `debug` at all -- so the counter that exists to tell "every detection
    expired" from "no bird was ever seen" read 0 in BOTH cases while avoidance was dead. The
    executor now records the drops on proceed/hold too, and drops > 0 with 0 engagements FAILS.
  * A SETPOINT THE POLICY WOULD REFUSE TO PLACE. Only the geofence was re-checked on the point the
    executor commanded, and the geofence cannot see a bird: an R3 refusal re-commanded a latched
    point 1.000 m from the bird against a 3.00 m bar, logged `accepted`. The executor now rejects
    that point, and `gate_r2_r3` reads BOTH halves: R3.8 reads the `gate_reject` events the
    backstop writes (the live evidence it fired, with its numbers), and R3.7 is the exhaustion
    property -- no `maneuver` event may record a setpoint inside the bar, which on a log the current
    executor produced is unreachable by construction and is therefore a defence against an older or
    edited one. Note what neither covers: a HOLD. A HOLD commands the vehicle's own position, i.e.
    ZERO displacement, so it honours no clearance bar and cannot -- at degenerate range the vehicle
    is inside the bar already. That gap is R4 (escape geometry), open on purpose; the hold's own
    bird clearance is printed as CONTEXT so the artifact shows how close holds got.
  * AN INVENTED BIRD. A bird the truth track never drove used to be pinned at its config spawn pose
    and counted as an observation for the whole flight -- and bird_0, 4 m below cruise, is the only
    bird the vertical scoping ever gates. Unobserved birds are now omitted and named, and the
    spawn-answered rate is reported with a denominator.
  * THE WRONG TAKE'S TRUTH TRACK, waved through by `--truth`. The "exactly one overlapping log"
    guard only ran on auto-discovery, and the runbook's own invocation is
    `ls -t …_applied.jsonl | head -1` -- so one aborted takeoff or one `fly_pipeline.sh birds`
    restart leaves two logs for one take and the newer covers only the tail. `resolve_truth` now
    counts the candidates even when `--truth` is explicit and fails on any OTHER overlapping log.

WHY (5) EXISTS -- the 2026-08-23 encounter: every gate was green (19/19 maneuvers vetted, ledger
720 covered / 0 debt, this checker PASS) while the vehicle passed **0.0518 m** from the bird. The
policy already refuses to place a *setpoint* nearer than `min_bird_clearance_m`, so flying nearer
than it is inconsistent on its face -- but nothing in the pipeline computed the distance actually
FLOWN. "19/19 vetted" is a claim about setpoints, not about separation. The CPA is now printed for
every log, every run, so the number exists whether or not it is in breach: absence of a metric is
how the miss stayed invisible.

ACKNOWLEDGED FINDINGS TAKE TWO HALVES, AND BOTH ARE REVIEWED. Recorded history cannot be re-flown,
and deleting the evidence would be worse than keeping it, so a log in CPA breach can report as
**ACKNOWLEDGED** -- a deliberately different word from VALID, printed to stderr, never green -- and
not fail CI. That takes BOTH: the sibling marker file `<log-stem>.SAFETY_FINDING.md` (the written
finding, beside the evidence, mirroring the clips' INVALID_DO_NOT_USE.md convention) AND the log's
stem pinned in `ACKNOWLEDGED_BREACH_STEMS` below (a reviewed diff on this gate). Either half alone
is a hard INVALID naming the half that is missing -- because until 2026-08-24 the marker alone was
enough, which made the runbook's own remedy for a breach ("keep the log: add the marker") also the
one-file, no-review way to turn a NEW bird strike into green CI, in a gitignored directory. A marker
beside a log that PASSES is itself a defect (a stale acknowledgement silently pre-authorises the
next regression), so it fails too.

Absent paths SKIP with exit 0: eval/results/ is gitignored, so in CI the glob usually matches
nothing (bash passes the literal pattern through unmatched) and this gate only bites when evidence
is deliberately committed/force-added. Exit 0 = every present log valid (or none present);
exit 1 = at least one present log invalid.

Usage:
    python3 scripts/check_live_flight_log.py                          # all eval/results/*flight_log*.json
    python3 scripts/check_live_flight_log.py eval/results/*flight_log*.json
    python3 scripts/check_live_flight_log.py <log> \
        --truth eval/results/bird_drive_<stamp>_applied.jsonl

STDLIB ONLY, deliberately: this runs as a CI step that needs nothing but `src/` importable, and the
whole truth-track path (`scripts/drive_birds.py`, `eval/annotate_real_clip.py`) is stdlib too. Do
not let numpy/scipy leak into the gate.
"""
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
# drive_birds: the truth log's WRITER owns its reader. annotate_real_clip: the same bird-pose
# reconstruction the ADR-003 labels use -- imported, never re-implemented, so a wrong bird pose is
# wrong in BOTH the labels and this gate, never in one of them silently.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

from fieldguard_planning.avoidance_policy import PolicyParams  # noqa: E402
from fieldguard_planning.coverage import (  # noqa: E402
    CELL_COVERED, CELL_DEBT, DEFAULT_CELL_SIZE_M, build_grid, check_ledger, load_field_polygon,
)
from drive_birds import (  # noqa: E402
    DEFAULT_BIRDS_CONFIG, applied_log_path_for, applied_sim_span, pose_at, read_applied_log,
)
from annotate_real_clip import applied_timeline, load_birds, pose_from_applied  # noqa: E402

RESULTS_DIR = REPO_ROOT / "eval" / "results"
# Per-file verdicts (check_file return values). SKIP is deliberately not a failure -- see the
# module docstring's gitignored-glob CI contract. ACKNOWLEDGED is a CPA breach with a marker file:
# loud, on stderr, exit 0 -- never folded into VALID.
SKIP, VALID, INVALID, ACKNOWLEDGED = "SKIP", "VALID", "INVALID", "ACKNOWLEDGED"
MARKER_SUFFIX = ".SAFETY_FINDING.md"
# The log stems whose CPA breach has been REVIEWED and accepted as recorded history. Acknowledging a
# breach takes BOTH halves, deliberately two different kinds of act:
#   1. `<log-stem>.SAFETY_FINDING.md` beside the evidence -- the written finding, readable by
#      whoever finds the log, in the directory the log lives in;
#   2. an entry HERE -- a diff on a qa-safety-owned gate, reviewed like any other change to a gate.
# WHY BOTH (2026-08-24). With the marker alone, the runbook's own remedy for a breach ("keep the
# log: add <log-stem>.SAFETY_FINDING.md") was ALSO the one-file way to turn a NEW bird strike into
# green CI: `touch` a file in a gitignored directory, alone at the MAVProxy prompt, and the gate
# says ACKNOWLEDGED / exit 0. R4 (escape geometry) is open and the next --detect take is
# PRE-REGISTERED as possibly breaching (docs/runbooks/AVOIDANCE_REAL_DETECTION.md §7), so that was
# the expected next event, not a hypothetical. A file nobody reviews may not be the thing that
# clears a safety gate.
# HALF an acknowledgement is INVALID either way and the message names the missing half: a marker
# whose stem is not pinned is a self-service green, and a pinned stem with no marker is an
# acknowledgement with no written finding behind it.
# A STALE PIN NEEDS NO RULE OF ITS OWN: a pin alone silences nothing (both halves are required),
# and the other half -- a marker beside a log that does NOT breach -- is already a hard failure.
ACKNOWLEDGED_BREACH_STEMS = (
    "live_flight_log_20260818T144711Z",   # 0.0597 m, found retroactively by this gate (R1)
    "live_flight_log_20260823T004031Z",   # 0.0518 m, degenerate-range encounter (ADR-013 am. 12)
)

# The logs allowed to take the LEGACY (detection-referenced) path at all -- the artifacts that
# PREDATE the schema-2 `run` block. Same ratchet doctrine as ACKNOWLEDGED_BREACH_STEMS above, and
# closed 2026-08-24 for the same shape of hole: the legacy path scores CPA against the drone's OWN
# detections, so `del log["run"]` was a ONE-KEY DOWNGRADE out of every schema-2 gate -- a flight the
# bird ground truth fails came back "NO-CPA-EVIDENCE -> VALID" precisely when the detector missed
# the bird at closest approach. `avoidance_node.py` fills the run block on EVERY take since the
# 2026-08-24 seam, so an absent one is a fault or tampering unless the log predates the seam, and
# those are a finite, reviewed list -- pinned two different ways for two different reasons:
#   * the two historical live logs, by STEM rather than by directory, because CI and
#     tests/test_ci_evidence_gate.py copy them into a tmp tree to run this gate hermetically;
#   * the CI scenario fixtures, by SHAPE (`eval/scenarios/<name>/flight_log.json`), because
#     `eval/scenarios/generate_flight_logs.py` drives the policy + executor OFF-ROS -- no clock, no
#     detector, no bird driver -- so there is nothing for a run block to record, and because the
#     scenario SET is meant to grow (each fixture arrives as a reviewed committed diff, and the
#     regenerate-and-diff CI step already pins their bytes), whereas this stem list is not.
# That the two stems below repeat ACKNOWLEDGED_BREACH_STEMS is a coincidence of history -- both
# pre-seam live logs happened to breach. The lists answer different questions ("may this log be
# scored on the old gate?" vs "is this breach reviewed?") and are deliberately kept apart.
PRE_SEAM_LEGACY_STEMS = (
    "live_flight_log_20260818T144711Z",   # flown 2026-08-18, before the run block existed
    "live_flight_log_20260823T004031Z",   # flown 2026-08-23, likewise
)
SCENARIO_FIXTURE_DIR = REPO_ROOT / "eval" / "scenarios"
SCENARIO_FIXTURE_NAME = "flight_log.json"

# --- schema-2 contract (written by avoidance_node.py's `run` block) -----------------------------
GATED_SCHEMA_VERSION = 2            # `run.schema_version` >= this -> the per-decision gates below
CLOCK_SOURCE = "gz_clock_stream"    # the ONE clock: native gz /clock, absolute Gazebo sim seconds
DET_NDVI_BLOB = "ndvi_blob"         # the real ADR-003 detector -> CPA measured against truth
DET_DEMO_VIRTUAL = "demo_virtual"   # a bird we invented -> the logged position IS exact truth
DET_NONE = "none"                   # no detector armed -> the log may not claim avoidance at all
DETECTOR_SOURCES = (DET_NDVI_BLOB, DET_DEMO_VIRTUAL, DET_NONE)
# Event kinds that only ever occur while the avoidance loop is engaged. Every tick carrying one of
# these MUST have bird ground truth: a flight cannot certify the encounter it cannot see.
ENCOUNTER_KINDS = ("detection", "maneuver", "hold", "takeover", "gate_reject")
# A FROZEN time axis is the second consumer of `now_s` the clock gate used to miss. `run.clock`
# stays `gz_clock_stream` with 0 violations when the node's `gz topic -e -t /clock` thread dies or
# Gazebo pauses -- `_gz_now` simply stops advancing -- and the domain tripwire can only fire on a
# tick that carries a detection (8 frames in 1256 on the adopted clip), so the freeze is silent for
# ~99 % of a flight. `ground_truth_cpa` joins EVERY tick to the truth track by that stamp, so a
# stalled axis scores the whole flown path against a bird nailed to one instant -- and reports 100 %
# truth coverage while doing it (measured: 2.0402 m breach -> 3.4490 m pass on one flown path).
#
# HOW MUCH A FREEZE CAN HIDE -- the derivation, because the first bound was sized against the wrong
# denominator (it borrowed the 1.0 s ADR-009 staleness bound, which is about detection freshness and
# has nothing to do with the truth JOIN; QA round 2, 2026-08-24, measured a 5-tick freeze turning a
# 0.0000 m strike into a 3.5000 m PASS):
#   * A frozen stamp does not misplace the DRONE. `flown_path_enu[i]` is telemetry recorded when tick
#     i ran, and `ground_truth_cpa` walks the polyline between those points -- both independent of
#     what the clock said. It misplaces the BIRD: every tick in a frozen run is answered with the
#     truth track's pose at the frozen instant t_f while the bird really was at pose(t_i). So the
#     join error is bounded by the bird's own top speed:  err <= v_bird_max * |t_i - t_f|.
#   * |t_i - t_f| is MEASURED FROM THE FLIGHT'S OWN STAMPS, never converted from a nominal tick rate
#     (QA round 3, 2026-08-24, finding 5). The first version priced a run of N identical stamps at
#     (N-1)/CONTROL_HZ WALL seconds and leaned on RTF <= 1 -- but wall seconds per tick is
#     1/CONTROL_HZ only if the ROS timer actually fires at 5 Hz, and `avoidance_node` runs that timer
#     on a wall clock on a box this project has twice documented starving. A starved callback makes
#     the nominal bound an UNDER-count, and the two faults are correlated: a node whose `/clock`
#     reader thread stalled for 3 ticks is a node that may also be starved. Measured under-pricing:
#     1.75x at 0.35 s/tick, 2.5x at 0.50, 5.0x at 1.00.
#     The stamps bound it exactly. A run of ticks all reading sim second `v` is bracketed by two
#     honest readings: `v` itself (a clock reading never runs AHEAD of sim time, so every tick in the
#     run happened at or after `v`) and the first stamp AFTER the run that advanced, `v_next` (the
#     reader was alive again, so that tick is where the run's last tick can no longer be). Joining
#     every frozen tick at `v` therefore costs at most `v_next - v` seconds -- assumption-free, no
#     rate anywhere in it, and looser than the truth by at most one tick period.
#     A run with NO advancing stamp after it (the clock died and never came back) has no such
#     bracket, so it is priced at the flight's OWN measured mean sim-step (`span_s / advanced`) times
#     the run length -- a number the flight produced, not a nominal one. A flight that never advanced
#     at all is a hard failure before any of this is read.
#   * The WORST run is priced, not the longest: a 2-tick freeze can hide more sim time than a 5-tick
#     one, and the bound is about seconds hidden, not ticks repeated.
#   * v_bird_max is read from the birds config, not hard-coded (`max_bird_speed_m_s`): 7.00 m/s
#     today (bird_1, 65 m in 9.29 s). Re-scripting a faster bird tightens this gate automatically.
# Two consequences of that ONE inequality, and no free constants:
#   1. `freeze_debit_m` is subtracted from `gt_cpa_m` BEFORE it meets the bar, so the gated number is
#      a true worst case over the unseen window. With no freeze the window is 0.0 s and so is the
#      debit.
#   2. When the debit reaches `min_bird_clearance_m` the join could hide a strike outright, i.e. the
#      flight measured nothing about separation -- that is a broken clock, not a close pass, so it is
#      a hard `gate_clock` problem (never acknowledgeable by a SAFETY_FINDING marker) rather than a
#      debited breach. Today: 3.00 / 7.00 = 0.4286 s of hidden sim time is the line.
# The detect half of "detect -> avoid at a measured separation" (NdviDetectionSource.counters()).
# Written by the node since the seam landed and read by NOTHING until now.
DETECTOR_COUNTER_KEYS = ("ndvi_msgs_received", "frames_detected_on", "frames_with_detection",
                         "boxes_total", "dropped_no_intrinsics", "dropped_no_pose_pair",
                         "dropped_stale_pose_pair")


def min_bird_clearance_m() -> float:
    """The CPA bar, read from the POLICY that owns it (`PolicyParams.min_bird_clearance_m`) rather
    than duplicated here. A second literal 3.0 in this file would let the gate and the control law
    drift apart silently -- and the gate would go on passing flights the policy would refuse to
    command. Read per call, not captured at import, so the two can never disagree."""
    return float(PolicyParams().min_bird_clearance_m)


def max_bird_speed_m_s(birds_config: Path = DEFAULT_BIRDS_CONFIG) -> float:
    """Fastest speed any bird in the config is scripted to fly: max |dp|/dt over consecutive
    waypoints. Read from the file the world was GENERATED from (`gen_farm_world.py` and
    `drive_birds.py` read the same one), never duplicated as a literal here -- a faster bird must
    tighten this gate by itself. 7.00 m/s today (bird_1: 65 m in 9.29 s)."""
    best = 0.0
    for bird in load_birds(Path(birds_config)):
        wps = bird.get("waypoints") or []
        for a, b in zip(wps, wps[1:]):
            dt = float(b["t_s"]) - float(a["t_s"])
            if dt <= 0.0:
                continue
            d = math.dist((a["x_m"], a["y_m"], a["z_m"]), (b["x_m"], b["y_m"], b["z_m"]))
            best = max(best, d / dt)
    return best


def freeze_debit_m(frozen_window_s: float) -> float:
    """How far the fastest bird could have moved inside the sim-time window a frozen stamp hides:
    the amount by which a frozen-stamp truth join can OVER-report separation, and therefore the
    amount `gt_cpa_m` is debited by before it is compared to `min_bird_clearance_m`.

    Takes SECONDS, measured by `stamp_advance` from the flight's own stamps (`frozen_window_s`), not
    a tick count converted at a nominal rate -- see the derivation above."""
    return max(0.0, float(frozen_window_s)) * max_bird_speed_m_s()


def marker_path_for(log_path: Path) -> Path:
    """`<...>/live_flight_log_X.json` -> `<...>/live_flight_log_X.SAFETY_FINDING.md`."""
    return log_path.with_name(log_path.stem + MARKER_SUFFIX)


def acknowledgement_problem(log_path: Path) -> Optional[str]:
    """None when a CPA breach on this log is FULLY acknowledged -- marker file AND pinned stem (see
    `ACKNOWLEDGED_BREACH_STEMS`) -- otherwise the reason, NAMING THE MISSING HALF.

    Call only on a log that breaches. A marker beside a log that does NOT breach is a stale
    acknowledgement, which is a different defect and stays with the callers."""
    marker = marker_path_for(log_path)
    has_marker, pinned = marker.exists(), log_path.stem in ACKNOWLEDGED_BREACH_STEMS
    tool = Path(__file__).name
    if has_marker and pinned:
        return None
    if has_marker:
        return (f"{marker.name} is present but the log stem {log_path.stem!r} is NOT pinned in "
                f"ACKNOWLEDGED_BREACH_STEMS in scripts/{tool}: that is HALF an acknowledgement, and "
                f"half acknowledges nothing. A marker file alone is a drive-by file in a gitignored "
                f"directory -- it would turn a NEW breach green with nobody reviewing it. Both "
                f"halves or neither: the marker (the written finding, beside the evidence) AND the "
                f"pinned stem (a reviewed diff on this safety gate). If this is a new flight, THE "
                f"FLIGHT FAILED -- the pre-registered answer while R4 is open.")
    if pinned:
        return (f"the log stem {log_path.stem!r} is pinned in ACKNOWLEDGED_BREACH_STEMS in "
                f"scripts/{tool}, but {marker.name} is MISSING. The pin is the reviewed half; the "
                f"marker is the context half and it is equally mandatory -- an acknowledged breach "
                f"with no written finding beside the evidence is an unexplained one, and the next "
                f"reader of this log would have the verdict without the reason. Restore the marker "
                f"(or drop the pin, if this log is no longer acknowledged history).")
    return (f"no acknowledgement. A CPA breach is acknowledged by BOTH {marker.name} (the written "
            f"finding, beside the evidence) AND the log stem {log_path.stem!r} pinned in "
            f"ACKNOWLEDGED_BREACH_STEMS in scripts/{tool} (a reviewed diff on this safety gate) -- "
            f"neither half alone, so that no file dropped beside a log can clear this gate by "
            f"itself. If this is recorded history that cannot be re-flown, add both, citing the "
            f"finding, exactly as the two historical logs did; if it is a new flight, the flight "
            f"failed.")


def detection_positions(log) -> List[Tuple[str, float, float]]:
    """Every logged detection as (track_id, x, y). Ignores malformed entries rather than raising --
    a truncated event must not crash the gate, it must fail to provide CPA evidence."""
    out: List[Tuple[str, float, float]] = []
    if not isinstance(log, dict):
        return out
    for ev in log.get("events") or []:
        if not isinstance(ev, dict) or ev.get("kind") != "detection":
            continue
        pos = ev.get("position_enu")
        if not isinstance(pos, (list, tuple)) or len(pos) < 2:
            continue
        try:
            out.append((str(ev.get("track_id") or ev.get("frame_id") or "?"),
                        float(pos[0]), float(pos[1])))
        except (TypeError, ValueError):
            continue
    return out


def closest_approach(log) -> Optional[Tuple[float, str]]:
    """(cpa_m, track_id) -- the smallest HORIZONTAL distance between any flown path point and any
    logged detection -- or None when the log carries no CPA evidence.

    Horizontal (XY) on purpose: it is the separation the policy's own `min_bird_clearance_m` is
    expressed in, and ADR-009 is explicit that a bird's z is the estimate we cannot trust, so
    folding altitude in here would let an untrusted number manufacture clearance.

    None, never a number, when there are no detections or no path: 'nothing came close' and 'we
    never looked' are opposite claims and the caller must be able to tell them apart."""
    dets = detection_positions(log)
    path = log.get("flown_path_enu") if isinstance(log, dict) else None
    if not dets or not isinstance(path, list) or not path:
        return None
    best: Optional[Tuple[float, str]] = None
    for point in path:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            px, py = float(point[0]), float(point[1])
        except (TypeError, ValueError):
            continue
        for track_id, dx, dy in dets:
            d = math.hypot(px - dx, py - dy)
            if best is None or d < best[0]:
                best = (d, track_id)
    return best


# ================================================================================================
# SCHEMA 2 -- the gates a flight flown with the REAL detector has to pass (2026-08-24)
# ================================================================================================
def schema_version(log) -> Optional[int]:
    """`run.schema_version`, or None when the log carries no `run` block at all (legacy).

    Raises nothing: a `run` block whose version is unreadable is reported by `run_block_problem`
    as INVALID rather than silently falling back to the legacy path -- the legacy path measures CPA
    against the drone's own detections, so a demotion is a downgrade attack, not a default."""
    run = log.get("run") if isinstance(log, dict) else None
    if not isinstance(run, dict):
        return None
    v = run.get("schema_version")
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def legacy_pinned(path: Path) -> bool:
    """True iff `path` is one of the artifacts that predate the schema-2 `run` block and may
    therefore be scored on the legacy (detection-referenced) CPA path: a stem in
    `PRE_SEAM_LEGACY_STEMS`, or a scenario fixture at `eval/scenarios/<name>/flight_log.json`.

    Anchored at this repo for the fixtures (a `flight_log.json` two directories deep somewhere else
    is not one of ours) and NOT anchored for the stems, because the historical logs are copied into
    tmp trees by CI's own evidence step. See the constants for why the list is closed."""
    path = Path(path)
    if path.stem in PRE_SEAM_LEGACY_STEMS:
        return True
    return (path.name == SCENARIO_FIXTURE_NAME
            and path.resolve().parent.parent == SCENARIO_FIXTURE_DIR.resolve())


def run_block_problem(log, path: Path) -> Optional[str]:
    """Why this log may not be dispatched on its `run` block, or None.

    Both reasons are DOWNGRADES rather than parse errors, and both land on the same rule: the only
    way onto the weaker legacy path is to be pinned as pre-seam. A run block that is present but
    unreadable is a defect; a run block that is ABSENT on a log nothing pins is a fault or tampering
    (`del log["run"]` would otherwise convert a ground-truth-gated INVALID into a legacy VALID)."""
    run = log.get("run") if isinstance(log, dict) else None
    if run is None:
        if legacy_pinned(path):
            return None
        return (f"NO 'run' BLOCK, and {Path(path).name} is not pinned as a pre-seam log. Every "
                f"flight since the 2026-08-24 seam writes one (avoidance_node.py fills it on every "
                f"take), so an absent run block here is a fault or tampering -- "
                f"and not a harmless one: deleting that ONE key drops the log onto the legacy "
                f"path, where CPA is measured against the drone's own detections instead of the "
                f"bird ground truth, so a flight the truth track FAILS comes back "
                f"'NO-CPA-EVIDENCE -> VALID' exactly when the detector missed the bird at closest "
                f"approach. The logs that may take that path are pinned: the stems in "
                f"PRE_SEAM_LEGACY_STEMS in scripts/{Path(__file__).name} (a reviewed diff on this "
                f"gate) and the eval/scenarios/*/flight_log.json fixtures. If this is a real take, "
                f"the log the node wrote is the evidence -- recover it or re-fly; this file is not "
                f"scoreable as it stands.")
    if not isinstance(run, dict):
        return ("'run' is present but is not an object -- a flight log either carries the "
                "schema-2 run block or none at all")
    if schema_version(log) is None:
        return (f"run.schema_version is {run.get('schema_version')!r}, not an integer. A log with "
                f"a run block is a schema-{GATED_SCHEMA_VERSION} log; it does not get to fall back "
                f"to the legacy (detection-referenced) CPA path by making its version unreadable.")
    return None


# "the key was not there at all", which is a different fact from a key whose value is None: the
# executor writes None to mean "this hold named no threat", and absence to mean nothing at all.
_ABSENT = object()


def _num(x) -> Optional[float]:
    """float(x) for real numbers only -- bools and strings are NOT numbers here. A gate that reads
    `True` as 1.0 is a gate that can be passed with the wrong type."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x)


def encounter_ticks(log) -> List[int]:
    """Sorted 1-based ticks carrying any ENCOUNTER_KINDS event. `flown_path_enu[tick - 1]` is that
    tick's position: `AvoidanceExecutor.step()` records exactly one position per call on every
    branch, so the index relation holds by construction."""
    ticks = set()
    for ev in log.get("events") or []:
        if isinstance(ev, dict) and ev.get("kind") in ENCOUNTER_KINDS:
            t = ev.get("tick")
            if isinstance(t, int) and not isinstance(t, bool):
                ticks.add(t)
    return sorted(ticks)


# ------------------------------------------------------------------ bird ground truth (the gate)
class BirdTruth(NamedTuple):
    """One bird's answer at one instant: every position it COULD have had, plus whether that answer
    came from the SPAWN pose (the track has not yet observed a landed call for this bird).

    The flag is not decoration. A spawn answer is a legitimate observation only while the track
    really is this flight's -- it is also what a WRONG track produces for a whole flight, so the
    rate of spawn answers is reported with a denominator instead of blending into truth coverage."""
    positions: List[tuple]
    from_spawn: bool


class TruthTrack:
    """The flight's bird ground truth: `scripts/drive_birds.py`'s applied-pose log, read through
    the SAME functions `eval/annotate_real_clip.py` labels the ADR-003 clips with.

    That import direction is deliberate. Nothing in the ROS 2 graph publishes bird poses, so the
    driver's per-`set_pose` record is the only observation of where a bird was; if that
    reconstruction is ever wrong, the detection labels and this safety gate must be wrong TOGETHER,
    never one silently right."""

    def __init__(self, path: Path, records: Sequence[dict], birds: Sequence[dict]):
        self.path = Path(path)
        self.records = list(records)
        self.timeline = applied_timeline(self.records)   # bird_id -> [(sim_start, sim_end, pos, t)]
        self.birds = {b["bird_id"]: b for b in birds}
        self.span = applied_sim_span(self.records)       # landed calls only -- what we can answer
        # Landed calls per bird, and the set difference in BOTH directions.
        # `unknown_bird_ids` (timeline minus config): the track drove a bird this world does not
        # define, so the track and the flown world disagree and clearance measured across that
        # mismatch would be confident nonsense.
        # `unobserved_bird_ids` (config minus timeline): the inverse, and the more dangerous half --
        # a bird the track NEVER drove used to be pinned at its config spawn pose for the entire
        # flight and counted as an observation. bird_0 spawns 4 m below cruise and is the only bird
        # the vertical scoping ever gates, so inventing it either fabricates a breach (a path
        # through the spawn point scores 0.0000 m) or hides a real one (a static bird parked far
        # from a path that actually flew through the real one).
        self.landed_counts = {b: len(self.timeline.get(b, ())) for b in self.birds}
        self.unknown_bird_ids = sorted(set(self.timeline) - set(self.birds))
        self.unobserved_bird_ids = sorted(b for b, n in self.landed_counts.items() if n == 0)

    @classmethod
    def load(cls, path: Path, birds_config: Path = DEFAULT_BIRDS_CONFIG) -> "TruthTrack":
        return cls(path, read_applied_log(Path(path)), load_birds(Path(birds_config)))

    def _spawn_pos(self, bird_id: str) -> Tuple[float, float, float]:
        """Where a bird sits before its first landed call: `waypoints[0]`, EXACT, not modelled --
        gen_farm_world spawns it as a <static> model and nothing moves it until set_pose lands
        (ADR-012 amendment 1). Routed through the driver's own `pose_at` so the convention has one
        home."""
        bird = self.birds[bird_id]
        wps = bird["waypoints"]
        x, y, z, _yaw = pose_at(wps[0]["t_s"], wps, bird.get("loop", True))
        return (x, y, z)

    def candidates_at(self, t_sim_s: Optional[float]) -> Optional[Dict[str, BirdTruth]]:
        """{bird_id: BirdTruth} -- every position each OBSERVED bird could have had at absolute
        Gazebo sim second `t_sim_s`. None when this instant is outside what the track observed.

        A list of positions, not one position, because `pose_from_applied` reports frames that fall
        inside a `set_pose` bracket as ambiguous: Gazebo applied the pose somewhere between the
        request and the reply. Both candidates are returned and the caller takes the NEARER one --
        uncertainty must not buy clearance.

        None (no coverage) for: an unstamped tick, any instant AFTER the track's last landed call,
        and a track with no observed bird at all. Past the last landed call "the bird held its last
        pose" is an extrapolation nothing observed -- the driver may have been killed, or a later
        run may have re-driven the birds.

        A bird with ZERO landed calls is OMITTED, never answered for. Before a bird's FIRST landed
        call the spawn pose is a real observation (the model is <static> until set_pose lands,
        ADR-012 am. 1) -- but only if this track drove that bird at all. A bird the track never
        touched is a bird nobody watched, and `from_spawn` counts the rest so the difference between
        "observed at spawn" and "never observed" survives into the artifact."""
        if self.span is None or t_sim_s is None or t_sim_s > self.span[1]:
            return None
        out: Dict[str, BirdTruth] = {}
        for bird_id in self.birds:
            entries = self.timeline.get(bird_id)
            if not entries:
                continue                                # never driven -> not an observation at all
            found = pose_from_applied(entries, t_sim_s)
            from_spawn = found is None or found[0] is None
            cands = [self._spawn_pos(bird_id)] if from_spawn else [tuple(found[0])]
            if found is not None and found[2]:          # ambiguous: every bracket spanning t counts
                for start, end, pos, _t in entries:
                    if start <= t_sim_s < end:
                        cands.append(tuple(pos))
            out[bird_id] = BirdTruth(cands, from_spawn)
        return out or None


def truth_candidates(tick_span: Optional[Tuple[float, float]],
                     results_dir: Path = RESULTS_DIR) -> List[Path]:
    """Applied-pose logs whose sim span overlaps this flight's tick-stamp span, sidecar-first.

    Sidecar-first because the sidecar is what screens out the runs that cannot answer: a
    `--wall-clock` driver run records `clock: "wall"` with no sim anchor at all, and its poses can
    never be placed on the clock the flight is stamped in.

    Overlap is NECESSARY, NOT SUFFICIENT -- Gazebo sim time restarts near 0 every run, so two takes
    overlap trivially. The caller requires EXACTLY ONE candidate and otherwise tells the operator to
    pass `--truth`; picking the wrong log yields a full flight of confident spawn-pose truth."""
    if tick_span is None:
        return []
    lo, hi = tick_span
    out: List[Path] = []
    for sidecar_path in sorted(Path(results_dir).glob("bird_drive_*.json")):
        try:
            sidecar = json.loads(sidecar_path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        if not isinstance(sidecar, dict) or sidecar.get("clock") != "sim":
            continue
        named = sidecar.get("applied_log")
        applied = (sidecar_path.with_name(named) if isinstance(named, str) and named
                   else applied_log_path_for(sidecar_path))
        if not applied.exists():
            continue
        span = applied_sim_span(read_applied_log(applied))
        if span is not None and span[0] <= hi and lo <= span[1]:
            out.append(applied)
    return out


def _point_segment_xy(px: float, py: float, ax: float, ay: float,
                      bx: float, by: float) -> Tuple[float, float]:
    """(horizontal distance from (px,py) to the SEGMENT (ax,ay)-(bx,by), the fraction along that
    segment where the closest point sits). Degenerate segment (a == b) collapses to the point
    distance at fraction 0."""
    dx, dy = bx - ax, by - ay
    seg = dx * dx + dy * dy
    t = 0.0 if seg == 0.0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def _point_segment_xy_m(px: float, py: float, ax: float, ay: float,
                        bx: float, by: float) -> float:
    """Distance only -- the per-tick pass does not care where on the segment the minimum landed."""
    return _point_segment_xy(px, py, ax, ay, bx, by)[0]


def _lerp3(a: Tuple[float, float, float], b: Tuple[float, float, float],
           s: float) -> Tuple[float, float, float]:
    """The point a fraction `s` of the way from `a` to `b`. The drone's telemetry is a polyline, so
    this is the same constant-velocity-between-samples assumption the polyline itself already makes
    -- no new modelling, just the existing one evaluated between two vertices."""
    return (a[0] + s * (b[0] - a[0]), a[1] + s * (b[1] - a[1]), a[2] + s * (b[2] - a[2]))


def pose_windows(truth: TruthTrack) -> List[Tuple[str, Tuple[float, float, float], float, float]]:
    """[(bird_id, position, window_start_s, window_end_s)] -- one entry per LANDED `set_pose` call,
    with the sim-time window over which that pose could have been what Gazebo was rendering. Sorted
    by window start.

    THE BIRD AXIS OF THE JOIN, and the reason it exists (QA round 3, 2026-08-24, finding 1): the
    per-tick pass asks `candidates_at(t_i)` at the flight's TICK instants, so a landed call whose
    whole in-effect window falls strictly BETWEEN two ticks is never returned and never scored. The
    bird is the faster body (7.00 m/s scripted vs the drone's measured p50 0.747 m/tick), so that was
    the larger half of the discretisation. Measured on the committed 839-pose applied log, the
    fraction of poses no tick ever saw: 0.0 % at 0.121 s/tick (today's healthy rate), 3.2 % at 0.50,
    9.3 % at 0.60, 29.6 % at 0.80, 41.6 % at 1.00 -- and the artifact printed `truth coverage
    191/191 ticks` throughout, because tick coverage is the OTHER denominator. A hover with a bird
    driven through it at a 0.70 s tick period reported 3.8067 m -> VALID on a 0.0000 m strike.

    The window is the widest the truth log can defend, because uncertainty must not buy clearance:
    it OPENS when the call's request went out (`sim_start` -- from there the render may already show
    it) and CLOSES when the NEXT landed call's reply came back (`sim_end` -- from there the render
    certainly shows that one). That is exactly the interval over which `pose_from_applied` can
    return this pose, ambiguous bracket included, so the two agree by construction. The last call
    holds until the end of what the track observed (`TruthTrack.span[1]`), which is where
    `candidates_at` also stops answering.

    THE FREEZE INTERACTION, stated so it is not re-derived later: these timestamps come from the
    truth log and are gz-native sim seconds recorded by the driver itself -- they do not depend on
    `run.tick_stamp_sim_s` at all. The DRONE side of the join still does (a segment is located in
    time by the stamps of the ticks that bound it), so a frozen axis still mis-times the drone and
    `freeze_debit_m` still prices exactly that, unchanged."""
    out: List[Tuple[str, Tuple[float, float, float], float, float]] = []
    if truth.span is None:
        return out
    for bird_id, entries in truth.timeline.items():
        if bird_id not in truth.birds:
            continue                       # driven but not defined -- `unknown_bird_ids` refuses it
        for i, (start, _end, pos, _t) in enumerate(entries):
            closes = entries[i + 1][1] if i + 1 < len(entries) else truth.span[1]
            out.append((bird_id, tuple(pos), float(start), float(closes)))
    out.sort(key=lambda w: w[2])
    return out


def ground_truth_cpa(flown_path: Sequence, tick_stamps: Sequence, truth: TruthTrack,
                     vertical_threat_m: float, threat_radius_m: float) -> dict:
    """Closest point of approach between the FLOWN PATH -- the polyline, not its vertices -- and the
    TRUE bird positions.

    TWO PASSES, one per axis of the discretisation, and `gt_cpa_m` is the minimum over both.

    PASS 1, over the TICKS. Each tick's bird candidate set is scored against BOTH segments bounding
    that tick's vertex, so a minimum sampled at 5 Hz vertices -- always >= the true minimum, i.e.
    biased the one direction a safety gate may not (QA round 2, 2026-08-24) -- becomes a true lower
    bound over the flown polyline. Measured drone step on the 2026-08-23 log is p50 0.747 / p95
    1.892 / max 2.052 m per tick, and the birds TELEPORT 3.16 m per `set_pose` at ~1.9 Hz, so both
    discretisations are metre-scale against a 3.00 m bar. Two probes, both from those measured
    numbers: a true 2.8200 m polyline CPA reported as 3.0008 m PASS, and a bird teleport whose true
    continuous minimum of 2.6332 m reported as 3.0500 m PASS. This pass is also the ONLY one that
    can answer before a bird's first landed call, where the truth is its exact spawn pose.

    PASS 2, over the BIRD POSES (QA round 3, finding 1). Pass 1 samples the bird at tick instants,
    so a landed pose whose entire in-effect window falls between two ticks is invisible to it -- and
    the bird is the faster body. Every landed `set_pose` call is therefore ALSO scored directly:
    `pose_windows` gives the window over which that pose could have been rendered, and it is scored
    point-to-segment against exactly the piece of drone polyline that window covers (endpoints
    interpolated along the bounding ticks, so the sub-segment is the travel that really happened
    inside the window and not a whole step of it). The tick grid stops mattering: with a 0.70 s tick
    period and a bird driven through a hovering drone between two ticks, pass 1 alone reported
    3.8067 m -> VALID on a 0.0000 m strike. `truth_poses_scored/total` is that pass's own
    denominator, which `truth coverage K/N ticks` never had.

    The vertical band test uses the drone z at the point the minimum landed on (a tick's own z in
    pass 1, the interpolated z in pass 2): the gated axis is horizontal, and the vehicle flies level
    at cruise, so this is a centimetre-scale distinction either way.

    Horizontal (XY) against `min_bird_clearance_m`, for the reason `closest_approach` gives: 3D
    distance is always >= XY, so folding altitude in can only manufacture clearance. The 3D
    distance and the vertical separation AT the CPA tick are reported as non-gating context, so
    "but it was 4 m below" is answered inside the artifact instead of in an argument.

    VERTICALLY SCOPED, and this is not optional: bird_1 and bird_2 patrol 7 m and 9 m below cruise
    and pass horizontally under the lanes constantly, so an unscoped horizontal bar would fail every
    flight forever and mean nothing. The band is `PolicyParams.vertical_threat_m` -- the policy's
    OWN definition of what counts as a threat -- so the gate and the control law cannot drift.

    `ticks_from_spawn` counts the ticks answered from a bird's SPAWN pose (before its first landed
    call). That is a real observation -- the model is <static> until set_pose lands -- but it is
    also exactly what the WRONG take's truth track produces for a whole flight, so it is reported
    with a denominator rather than folded into truth coverage.

    Returns a report dict; `gt_cpa_m` is None when no bird was ever inside the vertical band (a
    measurement with a denominator, not an absence -- `min_horizontal_any_band_m` is reported so
    the number exists either way). `cpa_from` names which pass produced it.

    `cylinder_ticks` is the ticks on which a bird was TRULY inside the policy's threat cylinder.
    Crossed against the ticks that logged a detection it gives the missed-detection signal with a
    denominator -- reported, never gated, because a bird BEHIND the drone is invisible to a
    forward-facing camera and gating on it would measure geometry, not detection quality. It stays a
    per-TICK count (pass 1 only): its denominator is ticks the loop could have engaged on."""
    best: Optional[dict] = None
    unscoped: Optional[float] = None
    ticks_total = 0
    ticks_with_truth = 0
    ticks_from_spawn = 0
    uncovered: List[int] = []
    pairs_in_band = 0
    cylinder_ticks: List[int] = []

    def consider(bird_id: str, pos, drone_z: float, horiz: float, tick: Optional[int],
                 t: Optional[float], source: str, cylinder_tick: Optional[int] = None) -> None:
        """One (bird pose, drone point) pair, from either pass, against every number this reports."""
        nonlocal best, unscoped, pairs_in_band
        if unscoped is None or horiz < unscoped:
            unscoped = horiz
        vsep = abs(drone_z - pos[2])
        if vsep > vertical_threat_m:
            return                              # not a threat by the policy's own definition
        pairs_in_band += 1
        if (cylinder_tick is not None and horiz <= threat_radius_m
                and (not cylinder_ticks or cylinder_ticks[-1] != cylinder_tick)):
            cylinder_ticks.append(cylinder_tick)
        if best is None or horiz < best["gt_cpa_m"]:
            best = {"gt_cpa_m": horiz, "bird_id": bird_id, "tick": tick, "t_sim_s": t,
                    "drone_z_m": drone_z, "bird_z_m": pos[2], "vertical_sep_m": vsep,
                    "dist_3d_m": math.sqrt(horiz * horiz + vsep * vsep), "cpa_from": source}

    # Parse every vertex once, so a tick can reach its neighbours: a malformed point is None and
    # simply contributes no segment (it is already counted as uncovered below).
    pts: List[Optional[Tuple[float, float, float]]] = []
    for point in flown_path:
        try:
            pts.append((float(point[0]), float(point[1]), float(point[2])))
        except (TypeError, ValueError, IndexError):
            pts.append(None)
    stamps: List[Optional[float]] = [_num(tick_stamps[i]) if i < len(tick_stamps) else None
                                     for i in range(len(pts))]

    # --- PASS 1: every tick, against the bird poses in effect at that tick's instant --------------
    for i, parsed in enumerate(pts):
        tick = i + 1
        ticks_total += 1
        t = stamps[i]
        if parsed is None:
            uncovered.append(tick)
            continue
        dx, dy, dz = parsed
        cands = truth.candidates_at(t)
        if cands is None:
            uncovered.append(tick)
            continue
        # The two segments this vertex bounds -- the drone's ACTUAL travel either side of the instant
        # this tick's bird poses are known for.
        segments = [(a, b) for a, b in ((pts[i - 1] if i else None, parsed),
                                        (parsed, pts[i + 1] if i + 1 < len(pts) else None))
                    if a is not None and b is not None]
        ticks_with_truth += 1
        if any(answer.from_spawn for answer in cands.values()):
            ticks_from_spawn += 1
        for bird_id, answer in cands.items():
            for pos in answer.positions:
                horiz = math.hypot(dx - pos[0], dy - pos[1])
                for a, b in segments:
                    horiz = min(horiz, _point_segment_xy_m(pos[0], pos[1], a[0], a[1], b[0], b[1]))
                consider(bird_id, pos, dz, horiz, tick, t, "tick_sample", cylinder_tick=tick)

    # --- PASS 2: every landed bird pose, against the drone polyline over ITS OWN window -----------
    # Time-located drone segments: (start tick, A, B, t_A, t_B). Only ADJACENT ticks that both have a
    # position and a stamp -- a gap must not be bridged into a segment the drone never flew. The
    # `j` pointer below assumes stamps are non-decreasing, which `gate_clock` enforces outright: a
    # backwards axis is a hard INVALID, so it can never reach a verdict off a mis-walked pointer.
    segs = [(i, pts[i], pts[i + 1], stamps[i], stamps[i + 1]) for i in range(len(pts) - 1)
            if pts[i] is not None and pts[i + 1] is not None
            and stamps[i] is not None and stamps[i + 1] is not None]
    flown = [s for s in stamps if s is not None]
    poses_total = poses_scored = 0
    # The DENOMINATOR is counted even with no usable segments at all (a one-tick flight, or every
    # stamp missing): "0 of 12 bird poses scored" is a rate, "0/0" is a shrug.
    if flown:
        lo, hi = min(flown), max(flown)
        j = 0
        for bird_id, pos, w0, w1 in pose_windows(truth):
            if w0 > hi or w1 < lo:
                continue                        # this pose was never in effect during the flight
            poses_total += 1
            while j < len(segs) and segs[j][4] < w0:
                j += 1                          # windows are sorted, so this pointer only moves on
            scored = False
            for k in range(j, len(segs)):
                si, a, b, ta, tb = segs[k]
                if ta > w1:
                    break
                dur = tb - ta
                # Clip the step to the part of it that happened inside the pose's window. A frozen
                # pair (dur == 0) cannot be clipped and is scored whole -- conservative, and the
                # freeze that produced it is priced separately.
                s0, s1 = ((max(0.0, (w0 - ta) / dur), min(1.0, (w1 - ta) / dur)) if dur > 0.0
                          else (0.0, 1.0))
                p, q = _lerp3(a, b, s0), _lerp3(a, b, s1)
                horiz, frac = _point_segment_xy(pos[0], pos[1], p[0], p[1], q[0], q[1])
                scored = True
                consider(bird_id, pos, p[2] + frac * (q[2] - p[2]), horiz, si + 1,
                         ta + (s0 + frac * (s1 - s0)) * dur, "pose_window")
            poses_scored += 1 if scored else 0

    report = {"gt_cpa_m": None, "bird_id": None, "tick": None, "t_sim_s": None,
              "drone_z_m": None, "bird_z_m": None, "vertical_sep_m": None, "dist_3d_m": None,
              "cpa_from": None,
              "ticks_total": ticks_total, "ticks_with_truth": ticks_with_truth,
              "ticks_from_spawn": ticks_from_spawn,
              "ticks_without_truth": uncovered, "pairs_in_band": pairs_in_band,
              "truth_poses_total": poses_total, "truth_poses_scored": poses_scored,
              "min_horizontal_any_band_m": unscoped, "cylinder_ticks": cylinder_ticks,
              "vertical_threat_m": vertical_threat_m, "threat_radius_m": threat_radius_m}
    if best is not None:
        report.update(best)
    return report


# ------------------------------------------------------------------------ per-decision assertions
def stamp_advance(stamps) -> dict:
    """How far, and how monotonically, the flight's time axis actually MOVED.

    Null entries are SKIPPED rather than counted as freezes: an unstamped tick is a tick with no
    clock reading (already reported as missing truth coverage), not a clock that stopped.

    Returns: `advanced`/`pairs` (strictly-increasing steps out of consecutive stamped pairs),
    `span_s`, `longest_frozen_run`, the first backwards step, and -- the number the freeze debit is
    actually priced from -- `frozen_window_s`: the WORST sim-time window any run of identical stamps
    hides, measured from the stamps themselves (`frozen_at` names that run: (start tick, length,
    value)). See the derivation at the top of this file; nothing here converts ticks to seconds at a
    nominal rate."""
    usable: List[Tuple[int, float]] = []
    for i, s in enumerate(stamps or []):
        v = _num(s)
        if v is not None:
            usable.append((i + 1, v))                # 1-based ticks, same index base as the events
    advanced = 0
    backwards: Optional[Tuple[int, float, float]] = None
    for (_prev_tick, prev), (tick, cur) in zip(usable, usable[1:]):
        if cur > prev:
            advanced += 1
        elif cur < prev and backwards is None:
            backwards = (tick, prev, cur)
    # Consecutive ticks sharing one stamp value, as [start index, length, value].
    runs: List[list] = []
    for i, (_tick, val) in enumerate(usable):
        if runs and val == runs[-1][2]:
            runs[-1][1] += 1
        else:
            runs.append([i, 1, val])
    values = [v for _t, v in usable]
    span_s = (max(values) - min(values)) if values else None
    mean_step_s = (span_s / advanced) if (advanced and span_s) else None
    window_s = 0.0
    frozen_at: Optional[Tuple[int, int, float]] = None
    for start_i, length, val in runs:
        if length < 2:
            continue                                 # one tick, one honest stamp: nothing hidden
        # The first stamp after the run that ADVANCED past it closes the window exactly. Without one
        # the clock never came back, so the flight's own measured mean sim-step prices it instead.
        after = next((v for _t, v in usable[start_i + length:] if v > val), None)
        w = (after - val) if after is not None else (mean_step_s * length if mean_step_s else 0.0)
        if frozen_at is None or w > window_s:
            window_s, frozen_at = w, (usable[start_i][0], length, val)
    return {"usable": len(usable), "pairs": max(0, len(usable) - 1), "advanced": advanced,
            "span_s": span_s, "mean_step_s": mean_step_s,
            "longest_frozen_run": max((r[1] for r in runs), default=0),
            "frozen_window_s": window_s, "frozen_at": frozen_at, "backwards": backwards}


def gate_clock(log, run, adv: dict) -> Tuple[List[str], List[str]]:
    """Assertion 7: ONE clock domain, AND a time axis that actually moves.

    Without one domain the ages the staleness gate computed are not comparable, the truth track
    cannot be joined to the flown path, and the whole GT-CPA number is a coincidence. `violations`
    is the node's own tripwire (a stamp more than 0.5 s in the FUTURE of `now_s` -- what an elapsed
    clock against absolute gz stamps produces on every tick).

    The advance check is the SECOND consumer of `now_s`, and the one the domain tripwire cannot
    cover: a clock that stopped is still the right clock. `adv` (`stamp_advance`) supplies the
    numbers and they are reported whatever the verdict, because a stalled axis reads as perfect
    truth coverage. A freeze that could hide the whole `min_bird_clearance_m` bar fails HERE, as a
    clock fault: shorter freezes are priced into `gt_cpa_m` by `freeze_debit_m` instead (see the
    derivation at the top of this file)."""
    problems: List[str] = []
    notes: List[str] = []
    clock = run.get("clock")
    if not isinstance(clock, dict):
        problems.append("run.clock missing -- a schema-2 log must record which clock it flew on")
    else:
        src = clock.get("source")
        if src != CLOCK_SOURCE:
            problems.append(f"run.clock.source is {src!r}, expected {CLOCK_SOURCE!r}: the "
                            f"detection stamps and the truth track are only comparable on the "
                            f"native Gazebo /clock stream")
        viol = clock.get("violations")
        if not isinstance(viol, int) or isinstance(viol, bool):
            problems.append("run.clock.violations missing or not an integer -- absence of the "
                            "clock-domain tripwire is a defect, not a zero")
        elif viol != 0:
            problems.append(f"run.clock.violations = {viol}: detections arrived stamped in a "
                            f"DIFFERENT clock domain than `now_s`, so every staleness age this "
                            f"flight computed is meaningless (and negative ages read as fresh)")
        else:
            notes.append("clock gz_clock_stream, 0 domain violations")
    stamps = run.get("tick_stamp_sim_s")
    path = log.get("flown_path_enu")
    if not isinstance(stamps, list):
        problems.append("run.tick_stamp_sim_s missing or not a list -- the flown path has no time "
                        "axis, so it cannot be joined to the bird ground truth")
        return problems, notes
    if isinstance(path, list) and len(stamps) != len(path):
        problems.append(f"run.tick_stamp_sim_s has {len(stamps)} entries but flown_path_enu has "
                        f"{len(path)} -- one stamp per recorded position or the join is guesswork")
    # The axis must MOVE. A clock that reads the same second forever passes source/violations/length
    # untouched and quietly re-dates the whole flight onto one instant of the truth track.
    debit = freeze_debit_m(adv["frozen_window_s"])
    notes.append(f"stamps_advanced {adv['advanced']}/{adv['pairs']} "
                 f"(span {_fmt(adv['span_s'], 3)} s, mean sim step "
                 f"{_fmt(adv['mean_step_s'], 3)} s/tick, longest frozen run "
                 f"{adv['longest_frozen_run']} tick(s), worst hidden window "
                 f"{adv['frozen_window_s']:.3f} s -> gt_cpa_m freeze debit {debit:.4f} m)")
    if adv["backwards"] is not None:
        tick, prev, cur = adv["backwards"]
        problems.append(f"run.tick_stamp_sim_s goes BACKWARDS at tick {tick} ({prev} -> {cur}): "
                        f"Gazebo sim seconds do not run backwards within a take, so this is not "
                        f"one clock and every truth-track join made on it is arbitrary")
    if adv["usable"] >= 2 and adv["span_s"] == 0.0:
        problems.append(f"run.tick_stamp_sim_s NEVER ADVANCED: all {adv['usable']} stamped ticks "
                        f"read sim {adv['frozen_at'][2]:.3f} s. The clock stream died or Gazebo "
                        f"paused, and the whole flown path would be scored against bird positions "
                        f"frozen at one instant -- at 100 % reported truth coverage.")
    elif debit >= min_bird_clearance_m():
        start, length, value = adv["frozen_at"]
        problems.append(f"run.tick_stamp_sim_s FROZE: {length} consecutive ticks from tick {start} "
                        f"all read sim {value:.3f} s, and the next stamp that advanced puts "
                        f"{adv['frozen_window_s']:.3f} s of sim time inside that run where the "
                        f"truth join cannot see. The fastest scripted bird covers {debit:.3f} m in "
                        f"that window at {max_bird_speed_m_s():.2f} m/s -- at or beyond the "
                        f"{min_bird_clearance_m():.2f} m min_bird_clearance_m bar, so this join "
                        f"could hide a strike outright. Every tick in the run is scored against a "
                        f"bird nailed to one instant, and truth coverage still reads 100 %.")
    return problems, notes


def gate_knob_floors(run) -> List[str]:
    """Assertions R2.2 / R3.6 (plus the CPA bar itself): the flight was flown at or above today's
    safety knobs. Same shape, three knobs, one loop -- bigger is safer for all three. A log flown
    with an edited or older policy fails rather than being scored as current behaviour.

    Every bar is read from `PolicyParams()` at call time: a second literal in this file is exactly
    how a knob gets raised in one place and flown from the other."""
    problems: List[str] = []
    pp = run.get("policy_params")
    if not isinstance(pp, dict):
        return ["run.policy_params missing -- the log does not say what control law it flew"]
    defaults = PolicyParams()
    for knob in ("lateral_tree_margin_m", "min_bird_clearance_m", "degenerate_range_m"):
        bar = _num(getattr(defaults, knob, None))
        flown = _num(pp.get(knob))
        if bar is None:
            continue                      # the policy does not define it; nothing to compare to
        if flown is None:
            problems.append(f"run.policy_params.{knob} missing or not a number -- the flight does "
                            f"not record the safety knob it flew (bar: {bar})")
        elif flown < bar:
            problems.append(f"run.policy_params.{knob} = {flown} is BELOW today's policy default "
                            f"{bar}: this log was flown with a weaker control law than the one the "
                            f"gate is written for and must not be read as current behaviour")
    return problems


def gate_staleness(run) -> List[str]:
    """The staleness gate must have been ARMED for a real-detector flight. ADR-009 makes
    `stamp_s` a contract term and `max_detection_age_s` the policy that enforces it; flown as
    None the gate cannot fire at all, and a stale frame is then treated as live evidence about the
    world now -- the phantom-dodge / masked-threat failure the parameter exists to prevent."""
    pp = run.get("policy_params")
    if not isinstance(pp, dict):
        return []                                   # already reported by gate_knob_floors
    flown = _num(pp.get("max_detection_age_s"))
    if flown is None:
        return ["run.policy_params.max_detection_age_s is null/missing while a real detector was "
                "armed -- the ADR-009 staleness gate was OFF, so no detection this flight acted on "
                "was ever checked for age"]
    bar = _num(PolicyParams().max_detection_age_s)
    if bar is not None and flown > bar:
        return [f"run.policy_params.max_detection_age_s = {flown} s exceeds today's policy default "
                f"{bar} s -- this flight tolerated staler detections than the current control law"]
    return []


# FLOOR on the detect half, chosen the way ADR-013 am. 4 chose 12 frames / 40 cells -- a number with
# a measurement behind it, not a zero-check. `frames_detected_on / ndvi_msgs_received` is 1256/1256 =
# 100.0 % on the adopted clip's offline dry run: in a healthy take EVERY published NDVI message
# reaches the detector, because intrinsics arrive with the first fused frame and the PoseBuffer keeps
# up. The only legitimate loss is startup ordering (frames published before `/fg/ndvi/camera_info`
# lands); at 5 Hz, losing the first ten seconds of a ~5 minute take is ~3 %. 0.90 is ~3x that worst
# plausible transient and far above any real defect -- the failure mode this catches
# (camera_info late by minutes, or a starved PoseBuffer) loses 90-100 %. REVISABLE after the first
# real `--detect` flight measures the number in the air; revise it there, not by widening it here.
MIN_DETECT_RATE = 0.90


def _floor_pct(rate: float, places: int = 2) -> str:
    """A rate as a percentage, TRUNCATED rather than rounded, so a number below the floor can never
    print as the floor. `1130/1256 = 0.899681` failed the gate while `:.1%` printed "90.0%", which
    reads as a gate bug in a scrollback and invites someone to widen the floor after a failure (QA
    round 3, 2026-08-24, finding 7). Truncation makes the printed digits a true statement about the
    comparison: anything that prints "90.00%" really is >= 0.9000."""
    scale = 10 ** places
    return f"{math.floor(rate * 100.0 * scale) / scale:.{places}f}%"


def gate_detector_ran(log, run) -> Tuple[List[str], List[str]]:
    """The DETECT half of "detect -> avoid, at a measured separation" -- did the detector ever see
    a frame at all, did it see enough of them, and did anything survive the staleness gate?

    `NdviDetectionSource.on_frame` drops every frame while it has no intrinsics, and the node
    refuses to start without a Gazebo clock reading but has NO equivalent guard on
    `/fg/ndvi/camera_info`. So a take whose `ndvi_node` came up after the avoidance shell -- or
    whose BEST_EFFORT camera_info publication was missed -- flies to completion, writes a clean
    schema-2 log, and would be certified on a detector that processed nothing. The counters have
    been written since the seam landed and read by nothing.

    Zero frames is a hard failure, not a vacuous pass. R2/R3 can legitimately have nothing to check
    (a flight where no bird came close is a real flight); a detector armed and fed no frames is a
    broken bringup wearing a flight log's clothes, and the take's headline claim has no detect half.
    This is the family that produced ADOPT on empty ground truth (eval/score.py, 2026-08-21).

    A RATE, not a zero-check (`MIN_DETECT_RATE`): 1 frame of 1256 used to pass with no comment, and
    the same broken bringup one tick later looks exactly like that.

    A DETECTOR WHOSE OUTPUT ALL EXPIRED is the third failure here, and it wears the same clothes as
    a quiet sky: `boxes_total` climbing while the loop never engages. If the staleness gate dropped
    anything at all and the loop engaged on NOTHING, avoidance was dead for the whole flight (a
    systematic sub-second clock offset does exactly this, and the domain tripwire only fires on
    stamps in the FUTURE). If nothing was dropped, boxes with no engagement is the honest reading --
    every box fell outside the threat cylinder -- and it is said in those words rather than left to
    an absent number."""
    detector = run.get("detector")
    counters = detector.get("counters") if isinstance(detector, dict) else None
    if not isinstance(counters, dict):
        return (["run.detector.counters missing -- the real detector always reports them "
                 "(NdviDetectionSource.counters), so absence means this log did not come from that "
                 "detector, and the detect half of this flight is unmeasured"], [])
    values = {k: _num(counters.get(k)) for k in DETECTOR_COUNTER_KEYS}
    missing = sorted(k for k, v in values.items() if v is None)
    if missing:
        return ([f"run.detector.counters is missing or non-numeric for {missing} -- a counter that "
                 f"is absent is not a counter that is zero, and these are the only evidence the "
                 f"detector ran at all"], [])
    received, detected_on = values["ndvi_msgs_received"], values["frames_detected_on"]
    rate = (detected_on / received) if received > 0 else None
    note = ("detector counters: ndvi_msgs_received={ndvi_msgs_received} "
            "frames_detected_on={frames_detected_on} frames_with_detection={frames_with_detection} "
            "boxes_total={boxes_total} | dropped no_intrinsics={dropped_no_intrinsics} "
            "no_pose_pair={dropped_no_pose_pair} stale_pose_pair={dropped_stale_pose_pair}"
            ).format(**{k: int(v) for k, v in values.items()})
    note += (" | detect rate " + ("n/a (0 NDVI messages)" if rate is None else
                                  f"{_floor_pct(rate)} (floor {_floor_pct(MIN_DETECT_RATE)})"))
    dropped = (f"dropped no_intrinsics={int(values['dropped_no_intrinsics'])} "
               f"no_pose_pair={int(values['dropped_no_pose_pair'])} "
               f"stale_pose_pair={int(values['dropped_stale_pose_pair'])}")
    problems: List[str] = []
    if detected_on == 0:
        problems.append(
            f"DETECTOR NEVER RAN: 0 of {int(received)} NDVI message(s) reached "
            f"the detector ({dropped}). A flight that armed the "
            f"real detector and detected on nothing did not fly the take it was booked for -- "
            f"whatever the separation numbers say, there is no detect half to quote. Most likely "
            f"`/fg/ndvi/camera_info` never arrived (ndvi_node started after the avoidance shell).")
    elif rate is not None and rate < MIN_DETECT_RATE:
        problems.append(
            f"DETECTOR BARELY RAN: {int(detected_on)} of {int(received)} NDVI message(s) reached "
            f"the detector = {_floor_pct(rate)}, below the {_floor_pct(MIN_DETECT_RATE)} floor "
            f"({dropped}). The "
            f"detect half of this take is a handful of frames; a bird could pass through the whole "
            f"encounter unlooked-at and the flight would still print R2/R3 PASS (vacuous) and a "
            f"green separation. Same cause as the zero case, one tick later.")
    n_dets = n_detection_events(log)
    n_stale = stale_dropped_total(log)
    if n_stale and not n_dets:
        problems.append(
            f"AVOIDANCE WAS DEAD: the ADR-009 staleness gate dropped {n_stale} detection(s) and the "
            f"loop engaged on ZERO ticks -- every detection this flight had expired before the "
            f"policy could act on it, so no bird was ever avoided and no maneuver was ever vetted. "
            f"A sub-second clock offset does this silently (the domain tripwire only fires on "
            f"stamps in the FUTURE), and it reads identically to a quiet sky unless this is gated.")
    elif values["boxes_total"] and not n_dets:
        note += (f" || the detector produced {int(values['boxes_total'])} box(es) and the loop "
                 f"engaged on 0 tick(s), with 0 stale drops: every box fell OUTSIDE the policy's "
                 f"threat cylinder. That is a real flight, not a dead gate -- but any R2/R3 "
                 f"vacuous pass below is vacuous for THAT reason, and the number says so.")
    return problems, [note]


def _min_setpoint_bird_gap_m(setpoint, threat_positions) -> Optional[Tuple[float, int]]:
    """(horizontal distance from `setpoint` to the nearest threat, that threat's index), or None
    when either side is missing/malformed. Horizontal, the axis `min_bird_clearance_m` is stated
    in -- the policy's own gate 4 uses exactly this distance."""
    if not isinstance(setpoint, (list, tuple)) or len(setpoint) < 2:
        return None
    if not isinstance(threat_positions, (list, tuple)) or not threat_positions:
        return None
    try:
        sx, sy = float(setpoint[0]), float(setpoint[1])
    except (TypeError, ValueError):
        return None
    best: Optional[Tuple[float, int]] = None
    for i, pos in enumerate(threat_positions):
        if not isinstance(pos, (list, tuple)) or len(pos) < 2:
            continue
        try:
            d = math.hypot(sx - float(pos[0]), sy - float(pos[1]))
        except (TypeError, ValueError):
            continue
        if best is None or d < best[0]:
            best = (d, i)
    return best


def gate_r2_r3(log, run) -> Tuple[List[str], List[str]]:
    """The per-decision assertions R2 and R3 actually control (ADR-013 am. 12).

    R2 gates the clearance the POLICY vetted on each accepted dodge. Stated honestly, because the
    scope is narrower than the words "tree clearance" suggest: the LATCHED point's swept path is
    NOT re-vetted as ownship moves (the executor re-vets the point, via is_safe_3d, not the
    segment). That is a named, deliberately-deferred control-law gap, not a claim this gate makes.

    R3 gates on the NUMBER, not the flag: a lying `range_degenerate` cannot buy a re-latch, and the
    flag/number consistency check catches a policy and executor at different versions.

    R3.7 (QA round 2, 2026-08-24) is the EXHAUSTION half of the executor's bird backstop, and its
    scope is exactly this: no `maneuver` event may record a `setpoint_enu` inside the flown
    `min_bird_clearance_m` of the birds logged with that decision. On a log the current executor
    produced that assertion should be vacuously true -- the executor writes a `gate_reject` instead
    of a `maneuver` precisely so it cannot happen -- so a BREACH here means the backstop failed (or
    the log was hand-edited, or it predates the backstop). Round 3 finding 3: this branch used to be
    presented as the artifact half of the executor catch, which it is not; the artifact half is the
    `gate_reject` events, and they are read below.

    R3.8 reads those rejects. A `gate_reject` carrying `bird_clearance_m` below the bar is the
    backstop WORKING and is reported with its numbers. A reject that names neither an obstacle nor a
    sub-bar bird clearance is a refusal the log cannot explain, and that is a problem: the executor
    only rejects for one of those two reasons, so an unexplained one means the fields drifted.

    HOLD clearance is CONTEXT, never gated, and the note pre-registers why (round 3, finding 2): a
    HOLD commands the vehicle's own current position -- zero displacement -- so it chooses no point
    and can honour no clearance bar. At degenerate range the vehicle is inside the bar BY
    CONSTRUCTION, so holds inside the bar there are the known signature of R4 (escape geometry)
    being open, not a new finding. The number is printed so the artifact shows how close holds got --
    ALWAYS, and with its denominator (`N of M hold(s)`, round 4): the note used to appear only when
    some hold carried a number, so a take with holds that named no threat and a take whose hold
    events had lost the field printed the same nothing. The second of those is FIELD DRIFT and is now
    a problem in its own right, on the same rule R3.8 applies to a gate_reject. Drift is the KEY
    being absent OR the value being unusable -- a string, a dict, a bool -- and NOT an explicit None,
    which is what `_handle_hold` writes when the decision names no threat. The unusable value was the
    quieter half (round 5): `_num` returned None for it, so the tick fell into the "named no threat"
    bucket and a hold whose clearance had turned into `"n/a"` read exactly like a hold with no bird
    near it, while the hold COUNT went on rising with nothing behind it.
    """
    problems: List[str] = []
    notes: List[str] = []
    pp = run.get("policy_params")
    if not isinstance(pp, dict):
        return problems, notes                      # already reported by gate_knob_floors
    margin = _num(pp.get("lateral_tree_margin_m"))
    degen = _num(pp.get("degenerate_range_m"))
    bird_bar = _num(pp.get("min_bird_clearance_m"))
    n_refused = 0
    n_maneuvers = 0
    n_rejects = 0
    n_holds = 0
    reject_bird_gaps: List[float] = []
    hold_gaps: List[float] = []
    holds_no_field: List[object] = []               # hold ticks with no USABLE bird_clearance_m
    for ev in log.get("events") or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("latch_action") == "relatch_refused_degenerate":
            n_refused += 1
        kind = ev.get("kind")
        if kind == "hold":
            n_holds += 1
            # THREE cases, not two. `_handle_hold` writes `bird_clearance_m` on EVERY hold and sets
            # it None only when the decision names no threat, so:
            #   * absent KEY            -> field drift (the executor and this gate have parted);
            #   * present but NOT a number ("n/a", {}, True) -> field drift TOO, and it used to be
            #     the quieter half of the same defect: `_num` returned None, the tick fell into the
            #     "named no threat" bucket, and a hold whose clearance had turned into a string read
            #     exactly like a hold with no bird near it -- while `holds with a threat=N of M`
            #     kept counting M. An unusable value is not an absent threat;
            #   * an explicit None      -> a legitimate hold that named no threat.
            raw = ev.get("bird_clearance_m", _ABSENT)
            gap = _num(raw)
            if raw is _ABSENT or (raw is not None and gap is None):
                holds_no_field.append(ev.get("tick"))
            elif gap is not None:
                hold_gaps.append(gap)
        elif kind == "gate_reject":
            # -- R3.8: the backstop firing IS the evidence; read the numbers it wrote --------------
            n_rejects += 1
            gap = _num(ev.get("bird_clearance_m"))
            flown_bar = _num(ev.get("min_bird_clearance_m"))
            bar_here = flown_bar if flown_bar is not None else bird_bar
            if gap is not None and bar_here is not None and gap < bar_here:
                reject_bird_gaps.append(gap)
            elif ev.get("obstacle_id") is None:
                problems.append(
                    f"tick {ev.get('tick')}: gate_reject explains itself with neither an "
                    f"obstacle_id nor a bird_clearance_m below min_bird_clearance_m (got "
                    f"{ev.get('bird_clearance_m')!r} vs {ev.get('min_bird_clearance_m')!r}). The "
                    f"executor rejects for exactly those two reasons, so a reject that records "
                    f"neither means the fields it writes and the fields read here have drifted -- "
                    f"and the only live evidence that the bird backstop fires is these numbers")
        if kind != "maneuver":
            continue
        n_maneuvers += 1
        tick = ev.get("tick")
        debug = ev.get("debug")
        if not isinstance(debug, dict):
            problems.append(f"tick {tick}: maneuver event has no debug dict -- the policy always "
                            f"writes one, so absence means this log did not come from this policy")
            continue
        # -- R2.1: the policy did what its own params say ---------------------------------------
        clearance = _num(debug.get("swept_tree_clearance_m"))
        if clearance is None:
            problems.append(f"tick {tick}: accepted maneuver has no debug.swept_tree_clearance_m "
                            f"-- an accepted dodge with no recorded tree clearance is unvetted "
                            f"evidence, not a passing decision")
        elif margin is not None and clearance < margin:
            problems.append(f"R2 BREACH tick {tick}: accepted dodge swept within {clearance:.3f} m "
                            f"of a tree, below the flown lateral_tree_margin_m {margin:.3f} m")
        # -- R3.7: the COMMANDED point kept the policy's own bird bar ----------------------------
        gap = _min_setpoint_bird_gap_m(ev.get("setpoint_enu"), debug.get("threat_positions_enu"))
        if gap is None:
            problems.append(f"tick {tick}: accepted maneuver records no usable setpoint_enu / "
                            f"debug.threat_positions_enu pair -- the point this flight COMMANDED "
                            f"cannot be checked against the bird it was dodging, which is exactly "
                            f"how a re-commanded latch flew 1.000 m from one")
        elif bird_bar is not None and gap[0] < bird_bar:
            ids = debug.get("threat_ids") or []
            who = ids[gap[1]] if isinstance(ids, list) and gap[1] < len(ids) else f"#{gap[1]}"
            problems.append(f"R3.7 BREACH tick {tick}: COMMANDED a setpoint {gap[0]:.3f} m from "
                            f"bird {who}, inside the flown min_bird_clearance_m {bird_bar:.3f} m. "
                            f"The policy refuses to PLACE a setpoint that near a threat AND the "
                            f"executor's backstop refuses to command one -- it writes a "
                            f"gate_reject instead -- so a maneuver event carrying this point means "
                            f"the backstop did not fire on a log that should have made it "
                            f"impossible (a stale latch re-commanded against birds that have since "
                            f"moved, an older executor, or an edited log).")
        # -- R3.5: the flag and the number agree, by construction --------------------------------
        trig = _num(debug.get("trigger_range_m"))
        flag = debug.get("range_degenerate")
        if trig is None or not isinstance(flag, bool):
            problems.append(f"tick {tick}: maneuver debug is missing trigger_range_m and/or "
                            f"range_degenerate (got {debug.get('trigger_range_m')!r} / "
                            f"{debug.get('range_degenerate')!r}). Both travel together or R3 is "
                            f"unauditable")
        elif degen is not None and flag != (trig < degen):
            problems.append(f"tick {tick}: debug.range_degenerate is {flag} but trigger_range_m "
                            f"{trig} vs degenerate_range_m {degen} says {trig < degen} -- policy "
                            f"and executor are at different versions")
        # -- R3.4: no re-latch on a degenerate tick, gated on the NUMBER -------------------------
        if (ev.get("latch_action") == "relatch" and trig is not None and degen is not None
                and trig < degen):
            problems.append(f"R3 BREACH tick {tick}: RE-LATCHED at trigger range {trig} m, below "
                            f"degenerate_range_m {degen} m -- the away-vector's direction there is "
                            f"noise, and the executor chased it instead of keeping the vetted "
                            f"point")
    # A gate that checked nothing says so, in those words. R2 and R3 constrain ACCEPTED DODGES; a
    # flight with none has not exercised them, and "no maneuver breached the margin" is a true
    # sentence about an empty set. The vacuous-pass family is how a green gate stops meaning
    # anything (eval/score.py's ADOPT on empty ground truth, 2026-08-21).
    notes.append(f"maneuvers={n_maneuvers} relatch_refused_degenerate={n_refused}"
                 + ("" if n_maneuvers else " -- R2/R3 PASS (vacuous): 0 accepted dodges to check"))
    # R3.8: the backstop's own artifact. `n_maneuvers` counts points that PASSED it; this counts the
    # ones it stopped, which is the only place a working backstop shows up in a log.
    notes.append(
        f"gate_rejects={n_rejects} (bird-bar rejects={len(reject_bird_gaps)}"
        + ("" if not reject_bird_gaps
           else f", closest refused point {min(reject_bird_gaps):.3f} m from a bird")
        + ") -- a reject inside the bar is the executor backstop WORKING; R3.7 above is the "
          "exhaustion half (no accepted maneuver may command inside the bar)")
    # HOLD context, printed for EVERY schema-2 log and always WITH ITS DENOMINATOR. This used to
    # print only when some hold carried a number, so "no hold ever named a threat" and "the hold
    # events stopped carrying the field" both printed NOTHING -- and the second is the field drift
    # below. R4 (escape geometry) is open on exactly this number, so a take that measured none of it
    # has to say so rather than fall silent.
    hold_note = (f"holds with a threat={len(hold_gaps)} of {n_holds} hold(s) "
                 f"[CONTEXT, NEVER GATED]")
    if hold_gaps:
        hold_note += (
            f": min hold-tick bird clearance {min(hold_gaps):.3f} m. A HOLD commands the vehicle's "
            f"own current position -- ZERO displacement -- so it chooses no point and cannot honour "
            f"any clearance bar; guarantee 1 covers commanded DISPLACEMENT only. Below "
            f"degenerate_range_m the vehicle is inside the "
            + (f"{bird_bar:.2f} m " if bird_bar is not None else "")
            + "bar by construction, so holds inside it there are the pre-registered signature of "
              "R4 (escape geometry) being open -- expected, printed, and not a new finding.")
    else:
        hold_note += (". No hold event named a threat, so this take measured nothing about how "
                      "close a zero-displacement hold got to a bird -- unmeasured, not clean; R4 "
                      "(escape geometry) is open on exactly that number.")
    notes.append(hold_note)
    if holds_no_field:
        problems.append(
            f"{len(holds_no_field)} of {n_holds} hold event(s) carry no USABLE bird_clearance_m -- "
            f"the key is absent, or present with a value that is not a number (first at tick "
            f"{holds_no_field[0]}). `AvoidanceExecutor._handle_hold` writes a number or None on "
            f"every hold -- None when the decision names no threat -- so either shape is FIELD "
            f"DRIFT, the same defect R3.8 fails a gate_reject for: the hold COUNT would keep rising "
            f"while the number behind it went blank, and an unusable value would read as 'no bird "
            f"was near this hold'. That number is the only evidence a log carries about how close a "
            f"hold got to a bird, and R4 (escape geometry) is open on it.")
    return problems, notes


def stale_dropped_total(log) -> int:
    """How many detections the ADR-009 staleness gate threw away, summed over every event that
    carries the policy's debug -- maneuvers, and (since QA round 2, 2026-08-24) proceeds and holds.

    That last part is the whole point. "Every detection expired" and "no bird was ever seen" are
    opposite diagnoses, and ALL-STALE is precisely the case that produces PROCEED: the executor used
    to attach `debug` only on an accepted DIVERT, so a flight whose every detection aged out logged
    0 detections, 0 maneuvers, and a stale count of 0 -- byte-identical to a flight that saw
    nothing, with avoidance completely dead. `AvoidanceExecutor._stale_detail` now writes the count
    on the proceed/hold events too, and `gate_detector_ran` fails the combination."""
    total = 0
    for ev in log.get("events") or []:
        if isinstance(ev, dict) and isinstance(ev.get("debug"), dict):
            n = ev["debug"].get("n_stale_dropped")
            if isinstance(n, int) and not isinstance(n, bool):
                total += n
    return total


def n_detection_events(log) -> int:
    """Ticks on which the loop actually ENGAGED: `AvoidanceExecutor._log_detection` writes one only
    when the policy returned a maneuver with a triggering detection, i.e. an in-cylinder threat."""
    return sum(1 for ev in (log.get("events") or [])
               if isinstance(ev, dict) and ev.get("kind") == "detection")


def tick_stamp_span(run) -> Optional[Tuple[float, float]]:
    """(first, last) usable Gazebo sim second in `run.tick_stamp_sim_s`, or None."""
    stamps = [s for s in (_num(x) for x in (run.get("tick_stamp_sim_s") or [])) if s is not None]
    return (min(stamps), max(stamps)) if stamps else None


def resolve_truth(run, truth_arg: Optional[Path],
                  results_dir: Path = RESULTS_DIR) -> Tuple[Optional[TruthTrack], List[str]]:
    """(TruthTrack, problems). Every failure here is a HARD problem, never a skip: a flight flown
    with the real detector and no bird ground truth has measured nothing about separation, and
    "we could not tell" must not score green."""
    span = tick_stamp_span(run)
    cands = truth_candidates(span, results_dir)
    if truth_arg is not None:
        path = Path(truth_arg)
        if not path.exists():
            return None, [f"no truth track: --truth {path} does not exist"]
        # `--truth` says WHICH log to score against; it does not get to say that the others do not
        # exist. The runbook's own invocation is `ls -t … | head -1`, and one aborted takeoff (the
        # runbook warns about `Arm: Accels inconsistent` + retry) or one `fly_pipeline.sh birds`
        # override leaves two applied logs for a single take. `head -1` then picks the one covering
        # the TAIL, every earlier tick is answered from the birds' config SPAWN poses, and bird_0's
        # spawn sits 4 m below cruise directly under mission lane x=15 -- so the wrong pick either
        # fabricates a ~0 m breach or hides a real one. The only signal was a note nobody must read.
        others = [p for p in cands if p.resolve() != path.resolve()]
        if others:
            names = ", ".join(p.name for p in others)
            return None, [
                f"AMBIGUOUS TAKE: --truth {path.name} was given, but {len(others)} OTHER applied "
                f"log(s) also overlap this flight's sim-time window ({names}). One take has ONE "
                f"bird ground truth; two mean an aborted takeoff, a `fly_pipeline.sh birds` "
                f"restart, or a stale log from a previous run. Every tick outside the log you "
                f"passed is answered from the birds' SPAWN poses -- confidently wrong, not "
                f"unmeasured. Move the log(s) that do not belong to this take out of "
                f"{results_dir.name}/ and re-run."]
    else:
        if not cands:
            return None, [
                "no truth track: no eval/results/bird_drive_*_applied.jsonl overlaps this "
                "flight's sim-time window. Pass --truth <applied log> explicitly (the driver "
                "prints the exact command on Ctrl-C). Without it this flight measured nothing "
                "about separation from a real bird."]
        if len(cands) > 1:
            names = ", ".join(p.name for p in cands)
            return None, [
                f"ambiguous truth track: {len(cands)} applied logs overlap this flight's sim-time "
                f"window ({names}). Gazebo sim time restarts near 0 every run, so overlap alone "
                f"cannot pick the take -- pass --truth explicitly."]
        path = cands[0]
    try:
        truth = TruthTrack.load(path)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as e:
        return None, [f"no truth track: {path.name} is unreadable ({e})"]
    if truth.span is None:
        return None, [f"no truth track: {path.name} places nothing on the sim clock (a wall-clock "
                      f"driver run, or every set_pose call failed) -- it cannot answer where a "
                      f"bird was at any instant of this flight"]
    if truth.unknown_bird_ids:
        return None, [f"truth track {path.name} drives bird(s) {truth.unknown_bird_ids} that "
                      f"{DEFAULT_BIRDS_CONFIG.name} does not define -- the truth track and the "
                      f"flown world disagree; clearance measured across that is confident nonsense"]
    if span is None:
        return None, ["no usable run.tick_stamp_sim_s -- the flown path has no time axis to join "
                      "the truth track to"]
    if not (truth.span[0] <= span[1] and span[0] <= truth.span[1]):
        return None, [f"truth track {path.name} covers sim {truth.span[0]:.3f}..{truth.span[1]:.3f}"
                      f" s but this flight's ticks span {span[0]:.3f}..{span[1]:.3f} s -- no "
                      f"overlap, so this is a DIFFERENT take. Every tick would be scored against "
                      f"birds frozen at their spawn poses: confidently wrong, not unmeasured."]
    return truth, []


def check_schema2(path: Path, log: dict, truth_arg: Optional[Path] = None,
                  results_dir: Path = RESULTS_DIR) -> Tuple[str, List[str]]:
    """The gates a schema-2 (real-flight) log must pass. Returns (verdict, messages).

    `problems` is what makes a log INVALID and is NEVER acknowledgeable by a marker file: a marker
    acknowledges a recorded CPA finding, not a clock-domain fault or an R2 breach. The measured
    numbers are printed first, whatever the verdict -- absence of a metric is how the last two
    breaches stayed invisible."""
    run = log["run"]
    problems: List[str] = []
    notes: List[str] = []

    stamps = run.get("tick_stamp_sim_s")
    adv = stamp_advance(stamps if isinstance(stamps, list) else [])
    clock_problems, clock_notes = gate_clock(log, run, adv)
    problems.extend(clock_problems)
    notes.extend(clock_notes)
    problems.extend(gate_knob_floors(run))
    r_problems, r_notes = gate_r2_r3(log, run)
    problems.extend(r_problems)
    notes.extend(r_notes)

    bar = min_bird_clearance_m()
    freeze_debit = freeze_debit_m(adv["frozen_window_s"])      # 0.0 unless the axis stalled
    detector = run.get("detector")
    source = detector.get("source") if isinstance(detector, dict) else None
    det_cpa = closest_approach(log)              # the monocular ESTIMATE -- never a gate under v2
    cpa_m: Optional[float] = None                # the gated number, whatever it is measured against
    seen = encounter_ticks(log)

    if source not in DETECTOR_SOURCES:
        problems.append(f"run.detector.source is {source!r}; expected one of {DETECTOR_SOURCES}. "
                        f"The gate cannot know what the logged detections are worth, so it refuses "
                        f"to score the flight.")
    elif source == DET_NONE:
        if seen:
            problems.append(f"run.detector.source is 'none' but the log carries {len(seen)} "
                            f"tick(s) of avoidance events -- a log claiming no detector cannot "
                            f"also claim avoidance evidence")
        else:
            notes.append("no avoidance claimed (detector source 'none', 0 avoidance events)")
    elif source == DET_DEMO_VIRTUAL:
        # The demo bird's logged position IS exact truth -- it is a constant we chose -- so R1's
        # detection-referenced CPA is the correct gate here and runs unchanged.
        if det_cpa is None:
            notes.append("CPA NO-CPA-EVIDENCE (demo source, no detections with a position)")
        else:
            cpa_m = det_cpa[0]
            notes.append(f"CPA {cpa_m:.4f} m to {det_cpa[1]} [demo_virtual: the logged bird IS "
                         f"truth] (bar {bar:.2f} m)")
    else:                                        # DET_NDVI_BLOB -- the real detector
        problems.extend(gate_staleness(run))
        det_problems, det_notes = gate_detector_ran(log, run)
        problems.extend(det_problems)
        notes.extend(det_notes)
        truth, truth_problems = resolve_truth(run, truth_arg, results_dir)
        problems.extend(truth_problems)
        if truth is not None:
            pp = PolicyParams()
            report = ground_truth_cpa(log.get("flown_path_enu") or [],
                                      run.get("tick_stamp_sim_s") or [], truth,
                                      pp.vertical_threat_m, pp.threat_radius_m)
            notes.append(f"truth {truth.path.name} sim {truth.span[0]:.3f}..{truth.span[1]:.3f} s "
                         f"| truth coverage {report['ticks_with_truth']}/{report['ticks_total']} "
                         f"ticks | answered_from_spawn {report['ticks_from_spawn']}/"
                         f"{report['ticks_total']} ticks")
            # The BIRD-axis denominator. Tick coverage reads 100 % whether or not a landed bird pose
            # was ever looked at, so it is not the same measurement and never was (QA round 3, F1).
            notes.append(f"truth poses scored {report['truth_poses_scored']}/"
                         f"{report['truth_poses_total']} landed set_pose call(s) in flight window "
                         f"-- the BIRD axis of the join, scored over each pose's own in-effect "
                         f"window rather than at tick instants; unscored means no stamped drone "
                         f"segment covered that window")
            notes.append("truth landed set_pose calls per bird: "
                         + " ".join(f"{b}={n}" for b, n in sorted(truth.landed_counts.items())))
            if truth.unobserved_bird_ids:
                problems.append(
                    f"truth track {truth.path.name} has NO landed set_pose call for "
                    f"{truth.unobserved_bird_ids} -- {DEFAULT_BIRDS_CONFIG.name} defines those "
                    f"birds, so this flight flew with them and measured nothing about them. They "
                    f"are NOT scored at their spawn pose: an invented static bird either "
                    f"fabricates a breach or hides one, and bird_0 (4 m below cruise) is the only "
                    f"bird the "
                    f"vertical scoping ever gates. Wrong take's truth log, or the driver never "
                    f"reached them.")
            # Off-path ticks count as blind too: an event whose tick has no recorded POSITION is
            # not merely untruthed, it is unlocatable, and silently skipping it would let a
            # corrupt log hide its encounter outside the range the gate walks.
            uncovered = set(report["ticks_without_truth"])
            n_path = len(log.get("flown_path_enu") or [])
            blind = [t for t in seen if t in uncovered or not (1 <= t <= n_path)]
            if blind:
                problems.append(
                    f"{len(blind)} tick(s) carrying avoidance events have NO bird ground truth "
                    f"(first: tick {blind[0]}) -- the flight cannot certify its own encounter. "
                    f"Wrong truth log, or the driver stopped before the flight did.")
            if report["ticks_with_truth"] == 0:
                problems.append("the truth track answers for 0 of this flight's ticks -- present "
                                "but useless, which is not the same as clean")
            cpa_m = report["gt_cpa_m"]
            if cpa_m is None:
                notes.append(
                    f"gt_cpa_m NONE-IN-BAND: no bird was ever within |dz| <= "
                    f"{report['vertical_threat_m']:.1f} m of the drone, so nothing was a threat by "
                    f"the policy's own definition. Nearest bird in ANY band: "
                    f"{_fmt(report['min_horizontal_any_band_m'])} m horizontal.")
            else:
                notes.append(
                    f"gt_cpa_m {cpa_m:.4f} m to {report['bird_id']} at tick {report['tick']} "
                    f"(t_sim {_fmt(report['t_sim_s'], 3)} s, drone z {_fmt(report['drone_z_m'])} "
                    f"m, bird z {_fmt(report['bird_z_m'])} m, vertical sep "
                    f"{_fmt(report['vertical_sep_m'])} m, 3D {_fmt(report['dist_3d_m'])} m) "
                    f"[bar {bar:.2f} m, joined via {report['cpa_from']}]")
                # A frozen stamp misplaces the BIRD, so the join can only over-report separation.
                # Debit the worst case before the bar sees the number (derivation at the top).
                if freeze_debit >= bar:
                    # The window swallows the whole bar: `gate_clock` has already failed this as a
                    # CLOCK fault ("nothing was measured"), and subtracting it here would print a
                    # NEGATIVE separation and a CPA BREACH -- dressing an unmeasured flight up as a
                    # close pass, on top of the fault that says it is neither.
                    notes.append(
                        f"gt_cpa_gated_m NOT COMPUTED: the {freeze_debit:.4f} m freeze debit is at "
                        f"or beyond the whole {bar:.2f} m bar, so this flight measured nothing "
                        f"about separation. That is the CLOCK failure above, not a close pass.")
                elif freeze_debit > 0.0:
                    cpa_m -= freeze_debit
                    notes.append(
                        f"gt_cpa_gated_m {cpa_m:.4f} m = gt_cpa_m minus a {freeze_debit:.4f} m freeze "
                        f"debit ({adv['frozen_at'][1]} identically-stamped ticks from tick "
                        f"{adv['frozen_at'][0]} hiding {adv['frozen_window_s']:.3f} s of sim time x "
                        f"the fastest scripted bird at {max_bird_speed_m_s():.2f} m/s). THIS is the "
                        f"number gated: a frozen truth join can only over-report separation, never "
                        f"under-report it.")
            if det_cpa is None:
                notes.append("detection_cpa_m NONE -- the detector logged no positioned detection. "
                             "ESTIMATOR CHECK, NOT A SAFETY GATE.")
            else:
                # The estimator error is measured against the MEASURED join, never the debited one:
                # the debit prices a clock fault, not the detector's range error.
                gt_measured = report["gt_cpa_m"]
                notes.append(
                    f"detection_cpa_m {det_cpa[0]:.4f} m to {det_cpa[1]} -- monocular "
                    f"apparent-size estimate; ESTIMATOR CHECK, NOT A SAFETY GATE"
                    + ("" if gt_measured is None else
                       f" | range_estimate_error_at_cpa_m {gt_measured - det_cpa[0]:+.4f} "
                       f"(gt_cpa_m minus detection_cpa_m: the two MINIMA, not one instant)"))
            n_cyl = len(report["cylinder_ticks"])
            hit = len(set(report["cylinder_ticks"]) & set(seen))
            notes.append(f"bird truly inside the threat cylinder on {n_cyl} tick(s); the loop "
                         f"engaged on {hit} of them (missed-detection signal, NOT gated -- a bird "
                         f"behind the drone is invisible to a forward-facing camera)")
    notes.append(f"n_stale_dropped={stale_dropped_total(log)} over "
                 f"{n_detection_events(log)} detection event(s) -- reported for every flight, and "
                 f"FAILED by gate_detector_ran in exactly one combination: drops > 0 with 0 "
                 f"engagements, which is avoidance dead for the whole take")

    # --- verdict: a marker acknowledges a CPA FINDING, never a failed gate ------------------------
    marker = marker_path_for(path)
    breach = cpa_m is not None and cpa_m < bar
    if breach:
        problems.append(f"CPA BREACH: flew within {cpa_m:.4f} m of a bird, closer than the "
                        f"policy's own min_bird_clearance_m {bar:.2f} m -- the policy refuses to "
                        f"place a SETPOINT that near a threat (ADR-013 amendment 12, S1)."
                        + ("" if freeze_debit <= 0.0 or source != DET_NDVI_BLOB else
                           f" (worst case: the measured join reads "
                           f"{cpa_m + freeze_debit:.4f} m and is debited {freeze_debit:.4f} m for "
                           f"the {adv['frozen_window_s']:.3f} s clock freeze above)"))
        ack = acknowledgement_problem(path)
        if ack is None and len(problems) == 1:
            return ACKNOWLEDGED, notes + problems + [
                f"acknowledged by {marker.name} -- recorded history, kept as evidence, NOT a "
                f"passing flight"]
        if ack is not None:
            problems.append(ack)
        else:
            problems.append(f"{marker.name} and the pinned stem acknowledge the CPA finding, but "
                            f"the gate failures above are NOT acknowledgeable -- an "
                            f"acknowledgement covers a recorded separation finding, not a broken "
                            f"flight log.")
    elif marker.exists():
        problems.append(f"a stale acknowledgement marker {marker.name} is present beside a log "
                        f"that does not breach CPA. An acknowledgement beside a passing log "
                        f"pre-authorises the next regression on this file; delete the marker.")
    if problems:
        return INVALID, notes + problems
    return VALID, notes


def _fmt(x: Optional[float], places: int = 4) -> str:
    return "n/a" if x is None else f"{x:.{places}f}"


def validate_flight_log(log) -> List[str]:
    """Pure validation of one parsed flight-log dict; returns a list of problems ([] == valid).
    Importable and unit-tested (tests/fieldguard_planning/test_check_live_flight_log.py)."""
    if not isinstance(log, dict):
        return ["top-level JSON is not an object (expected the AvoidanceExecutor.flight_log dict)"]
    problems: List[str] = []

    path_enu = log.get("flown_path_enu")
    if not isinstance(path_enu, list):
        problems.append("'flown_path_enu' missing or not a list")
    elif not path_enu:
        problems.append("flown_path_enu is EMPTY -- the node never received a pose; this is an "
                        "idle run, not flight evidence")

    ledger = log.get("coverage_ledger")
    if not isinstance(ledger, list):
        problems.append("'coverage_ledger' missing or not a list")
        return problems

    cell_size = log.get("cell_size_m", DEFAULT_CELL_SIZE_M)
    try:
        grid = build_grid(load_field_polygon(), cell_size_m=float(cell_size))
    except Exception as e:  # unparseable cell_size_m, or field-polygon config trouble
        problems.append(f"cannot build canonical grid (cell_size_m={cell_size!r}): {e}")
        return problems

    result = check_ledger([c.cell_id for c in grid], ledger)
    problems.extend(f"ledger invariant: {e}" for e in result.errors)
    # All-debt = zero cells imaged. Distinct from the invariant above: an all-debt ledger is
    # perfectly HONEST accounting (P1-P3 pass) of a run that surveyed nothing -- i.e. not a flight.
    if result.n_cells > 0 and result.debt_count == result.n_cells:
        problems.append(f"ALL {result.n_cells} cells have status 'debt' (covered=0) -- an idle "
                        "run's ledger, not survey evidence")
    return problems


def check_file(path: Path, truth: Optional[Path] = None,
               results_dir: Path = RESULTS_DIR) -> Tuple[str, List[str]]:
    """Validate one path -> (SKIP|VALID|INVALID|ACKNOWLEDGED, messages). For VALID the messages are
    the headline numbers (CLAUDE.md: no 'it works' without a metric); for INVALID the numbers come
    first and the problems after -- the metric is printed whatever the verdict."""
    if not path.exists():
        return SKIP, [f"{path} absent -- nothing to validate"]
    try:
        log = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        return INVALID, [f"unreadable / not valid JSON: {e}"]
    problems = validate_flight_log(log)
    if problems:
        return INVALID, problems
    ledger = log["coverage_ledger"]
    n_cov = sum(1 for r in ledger if r.get("status") == CELL_COVERED)
    n_debt = sum(1 for r in ledger if r.get("status") == CELL_DEBT)
    headline = f"covered={n_cov} debt={n_debt} path_points={len(log['flown_path_enu'])}"

    # --- schema-2 logs take the gated path; legacy logs keep the verdict they were flown under ---
    rb_problem = run_block_problem(log, path)
    if rb_problem:
        return INVALID, [headline, rb_problem]
    version = schema_version(log)
    if version is not None:
        if version < GATED_SCHEMA_VERSION:
            return INVALID, [headline,
                             f"run.schema_version is {version}, below the gated schema "
                             f"{GATED_SCHEMA_VERSION}. There is no schema-1 flight log: a run "
                             f"block claiming an older version is a downgrade out of the "
                             f"R2/R3/clock/ground-truth-CPA gates, not a legacy artifact."]
        status, messages = check_schema2(path, log, truth, results_dir)
        return status, [f"{headline} | {messages[0]}"] + messages[1:]

    # --- CPA (ADR-013 am. 12 R1). Printed ALWAYS, whatever the verdict. -------------------------
    bar = min_bird_clearance_m()
    cpa = closest_approach(log)
    marker = marker_path_for(path)
    if cpa is None:
        return VALID, [f"{headline} | CPA NO-CPA-EVIDENCE (no logged detections with a position, "
                       f"or no flown path) -- this log says nothing about separation"]
    cpa_m, track_id = cpa
    cpa_note = f"CPA {cpa_m:.4f} m to {track_id} (bar: min_bird_clearance_m {bar:.2f} m)"

    if cpa_m < bar:
        breach = (f"{cpa_note} -- FLEW CLOSER THAN THE POLICY WILL COMMAND. The policy refuses to "
                  f"place a setpoint within {bar:.2f} m of a threat; this path came within "
                  f"{cpa_m:.4f} m of one (ADR-013 amendment 12, S1).")
        ack = acknowledgement_problem(path)
        if ack is None:
            return ACKNOWLEDGED, [f"{headline} | {breach}",
                                  f"acknowledged by {marker.name} -- recorded history, kept as "
                                  f"evidence, NOT a passing flight"]
        return INVALID, [breach, ack]

    if marker.exists():
        return INVALID, [f"{headline} | {cpa_note} -- PASSES",
                         f"but a stale acknowledgement marker {marker.name} is present. An "
                         f"acknowledgement beside a passing log pre-authorises the next regression "
                         f"on this file; delete the marker."]
    return VALID, [f"{headline} | {cpa_note}"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", type=Path, nargs="*",
                    help="flight-log JSONs to validate (default: eval/results/*flight_log*.json)")
    ap.add_argument("--truth", type=Path, default=None,
                    help="bird ground-truth track (eval/results/bird_drive_<stamp>_applied.jsonl) "
                         "for schema-2 logs flown with the real detector. Applies to EVERY log "
                         "named on this command line -- pass one flight at a time. Omitted: the "
                         "gate auto-discovers by sim-time overlap and refuses on 0 or >1 matches.")
    args = ap.parse_args(argv)

    paths = args.logs or sorted(RESULTS_DIR.glob("*flight_log*.json"))
    if not paths:
        print("[check_live_flight_log] SKIP: no eval/results/*flight_log*.json present -- "
              "nothing to validate (eval/results/ is gitignored; exit 0).")
        return 0

    n_invalid = n_acknowledged = 0
    for path in paths:
        status, messages = check_file(path, truth=args.truth)
        if status == INVALID:
            n_invalid += 1
            print(f"[check_live_flight_log] INVALID: {path}", file=sys.stderr)
            for m in messages:
                print(f"    - {m}", file=sys.stderr)
        elif status == ACKNOWLEDGED:
            # stderr, own word, own counter: an acknowledged safety finding must never read like a
            # pass in a scrollback or a CI log.
            n_acknowledged += 1
            print(f"[check_live_flight_log] ACKNOWLEDGED SAFETY FINDING: {path}", file=sys.stderr)
            for m in messages:
                print(f"    - {m}", file=sys.stderr)
        elif status == SKIP:
            print(f"[check_live_flight_log] SKIP: {messages[0]}")
        else:
            print(f"[check_live_flight_log] VALID: {path} ({messages[0]})")
            # Every measured number, not just the headline: a schema-2 log's GT-CPA, truth
            # coverage rate and estimator error are the point of the flight, and a metric nobody
            # prints is a metric nobody reads.
            for m in messages[1:]:
                print(f"    - {m}")

    if n_invalid:
        print(f"[check_live_flight_log] FAIL: {n_invalid} of {len(paths)} flight log(s) invalid -- "
              "this file is not evidence of a real flight (idle-run clobber, corrupt ledger, or a "
              "closest-approach breach); do not keep/commit it as the demo artifact.",
              file=sys.stderr)
        return 1
    if n_acknowledged:
        print(f"[check_live_flight_log] PASS WITH {n_acknowledged} ACKNOWLEDGED SAFETY FINDING(S): "
              f"{len(paths) - n_acknowledged} of {len(paths)} log(s) clean. The acknowledged log(s) "
              f"above are kept as recorded history and are NOT evidence of a safe flight.",
              file=sys.stderr)
        return 0
    print("[check_live_flight_log] PASS: all present flight logs valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
