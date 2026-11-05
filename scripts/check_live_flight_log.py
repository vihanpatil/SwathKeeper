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
     and CPA measured against the BIRD GROUND-TRUTH TRACK rather than the drone's own detections);
  7. and, when a BOOKING is bound to it (`--booking`, or a `<log-stem>.booking.json` sidecar), that
     the flight was flown at the mission speed that booking authorised -- see THE BOOKING below.
     Optional, because the NDVI survey needs no booking; mandatory for a dodge take, where its
     absence prints a WARNING that the authorisation is unverified.

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

WHICH LEFT THE OPPOSITE HOLE (QA finding G47, 2026-08-25): sim time restarts near 0 every run, so
the committed 2026-08-23 track overlaps EVERY later take and that guard fired on every new flight --
"AMBIGUOUS TAKE -> INVALID" with no CPA printed at all, and then a wrong complaint that the take's
own SAFETY_FINDING marker was stale. Overlap cannot identify a take; a REVIEWED PIN can, so
`TRUTH_BINDINGS` maps a flight-log stem to its applied log, is consulted first, and bypasses the
scan. Unpinned flights keep the scan and its refusals exactly.

WHY (5) EXISTS -- the 2026-08-23 encounter: every gate was green (19/19 maneuvers vetted, ledger
720 covered / 0 debt, this checker PASS) while the vehicle passed **0.0518 m** from the bird (the
number this gate reported then; segment geometry made it **0.0391 m** on 2026-08-25). The
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
        --truth eval/results/bird_drive_<stamp>_applied.jsonl \
        --booking eval/results/booking_gate_<stamp>.json          # a dodge take
    python3 scripts/check_live_flight_log.py <log> --no-birds     # a bird-less wiring flight

STDLIB ONLY, deliberately: this runs as a CI step that needs nothing but `src/` importable, and the
whole truth-track path (`scripts/drive_birds.py`, `eval/annotate_real_clip.py`) is stdlib too. Do
not let numpy/scipy leak into the gate.
"""
import argparse
import json
import math
import re
import statistics
import sys
from datetime import datetime
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
# geom.py is the ONE point-to-segment primitive and the ONE definition of airborne. It imports
# `math` and nothing else -- no config, no numpy, no sibling -- so importing it costs this gate
# none of its stdlib-only purity.
from fieldguard_planning.geom import (  # noqa: E402
    AIRBORNE_Z_M, point_segment_projection_xy,
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
# The tag every schema-2 CPA-breach message leads with. Named rather than typed twice because the
# real-evidence test (tests/fieldguard_planning/test_check_live_flight_log.py) decides whether a
# committed log needs a written finding beside it from THIS GATE'S OWN VERDICT -- and a message
# literal it string-matched would drift silently the first time the wording changed.
CPA_BREACH_TAG = "CPA BREACH"
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
    # Depths as this gate reports them TODAY, with the value ADR-013 am. 12 cites in brackets: the
    # vertex-only minimum was replaced by segment geometry on 2026-08-25 and both breaches deepened.
    "live_flight_log_20260818T144711Z",   # 0.0393 m [was 0.0597], found retroactively by R1
    "live_flight_log_20260823T004031Z",   # 0.0391 m [was 0.0518], degenerate-range encounter
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

# WHICH TRUTH TRACK BELONGS TO WHICH TAKE -- the third reviewed pin, and the only one that JOINS
# evidence rather than excusing it (QA finding G47, 2026-08-25).
# `truth_candidates` matches applied-pose logs to a flight by SIM-TIME OVERLAP, and Gazebo sim time
# restarts near 0 every run: the committed 2026-08-23 track (sim 110..264 s) therefore overlaps every
# later take. From the second committed track onward EVERY new flight scored "AMBIGUOUS TAKE ->
# INVALID" with no CPA printed at all -- including under an explicit `--truth`, because the
# exactly-one-candidate guard deliberately runs there too (and it is right to: `ls -t | head -1`
# after an aborted takeoff is how the wrong track gets passed). Measured on the 2026-08-25 take: the
# gate could not print gt_cpa_m 0.0067 m, and then told the operator the take's own SAFETY_FINDING
# marker was stale "beside a log that does not breach CPA". A gate that cannot join a flight to its
# bird track cannot reproduce its own breach verdict in CI, and "we could not tell" was landing on
# the same INVALID as "it breached" -- the one distinction this file exists to keep.
# A binding says: THIS flight's bird ground truth is THAT applied log. It is consulted FIRST and it
# BYPASSES the overlap scan entirely -- the pin IS the disambiguation, so re-running a scan that can
# only report ambiguity would be theatre. An UNPINNED flight is unchanged: overlap scan, AMBIGUOUS on
# more than one candidate. Same ratchet doctrine as the two lists above: a binding is a reviewed diff
# on this gate, landed with the evidence commit it describes, one line per take.
# The value is a FILENAME, not a path. The applied log is committed BESIDE the flight log (.gitignore
# re-includes both) and is resolved the same way the marker file is, so a log copied into another
# tree without its truth is UNSCOREABLE rather than silently joined to whatever happens to sit in
# this repo's eval/results. An explicit `--truth` must AGREE with the binding by name: a pin the
# command line can override is not a pin.
TRUTH_BINDINGS = {
    # 2026-08-25 real-detection take: gt_cpa_m 0.0067 m, BREACH. Marker beside it and deliberately
    # NOT in ACKNOWLEDGED_BREACH_STEMS -- a NEW breach is a FAILED flight, not recorded history.
    "live_flight_log_20260825T210402Z": "bird_drive_20260825T210030Z_applied.jsonl",
}

# --- schema-2 contract (written by avoidance_node.py's `run` block) -----------------------------
GATED_SCHEMA_VERSION = 2            # `run.schema_version` >= this -> the per-decision gates below
CLOCK_SOURCE = "gz_clock_stream"    # the ONE clock: native gz /clock, absolute Gazebo sim seconds
DET_NDVI_BLOB = "ndvi_blob"         # the real ADR-003 detector -> CPA measured against truth
DET_DEMO_VIRTUAL = "demo_virtual"   # a bird we invented -> the logged position IS exact truth
DET_NONE = "none"                   # no detector armed -> the log may not claim avoidance at all
# The ADR-020/021 forward depth detector (`avoidance_node --detect --detection-source depth`).
# ADDED TO `DETECTOR_SOURCES` 2026-09-07 (P1 of docs/runbooks/DODGE_TAKE_PREREGISTRATION_20260907.md)
# TOGETHER WITH ITS OWN GATES, AND ONLY TOGETHER WITH THEM. It was deliberately absent until now
# because every schema-2 detector gate was written for the NADIR NDVI camera -- the detect-rate
# floor counts `ndvi_msgs_received`, the estimator check prices an apparent-size ray, and the
# missed-detection note reasons about a downward footprint -- so a depth log landed on "the gate
# cannot know what the logged detections are worth" (UNSCOREABLE, INVALID). The unlock is not the
# name in this tuple; it is the SEVEN PRE-REGISTERED BARS in the depth section below, written before
# any depth take existed and each one red-first against a synthetic log. Adding the name without
# them would have converted a refusal-to-score into a false PASS on the other sensor's evidence,
# which is what the old comment here refused and what `gate_detector_block_matches_source` still
# refuses in both directions.
DET_DEPTH_BLOB = "depth_blob"
DETECTOR_SOURCES = (DET_NDVI_BLOB, DET_DEMO_VIRTUAL, DET_DEPTH_BLOB, DET_NONE)
# Fields only ONE of the two real detectors can write, from `avoidance_node.detector_log_block`.
# A block carrying a field from the other family is MISLABELLED, whichever way round it is.
NDVI_ONLY_DETECTOR_FIELDS = ("thresh", "thresh_provenance", "thresh_provisional",
                             "radius_prior_m", "min_area", "max_area")
DEPTH_ONLY_DETECTOR_FIELDS = ("params", "params_provenance", "params_provisional",
                              "segmenter_counters", "seam_module", "min_range_m", "max_range_m")
NDVI_ONLY_COUNTERS = ("ndvi_msgs_received",)
DEPTH_ONLY_COUNTERS = ("depth_msgs_received", "dropped_non_finite_depth", "dropped_out_of_range",
                       "detections_near_known_obstacle")
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
    """(cpa_m, track_id) -- the smallest HORIZONTAL distance between the flown PATH and any logged
    detection -- or None when the log carries no CPA evidence.

    THE PATH, NOT ITS VERTICES (fixed 2026-08-25). This minimised over sampled points until then,
    so a bird overflown BETWEEN two samples scored the distance to the nearer sample. Measured
    consequence on committed artifacts: `eval/scenarios/cov_bird_at_turnaround` reported **7.0000 m**
    -- the one scenario fixture that cleared the 3 m bar -- for a detection at (22, 58) sitting dead
    centre of the 15 m leg (15, 58) -> (30, 58), i.e. a fly-through with a true CPA of 0. The two
    historical live breaches deepened too (0.0597 -> 0.0393, 0.0518 -> 0.0391): still breaches,
    still acknowledged, just closer than the artifact used to admit. `_point_segment_xy_m` has been
    in this file since G22 (`ground_truth_cpa` uses it) and was simply never back-ported here --
    which is why the ESTIMATE-referenced number was the optimistic one while the truth-referenced
    number was not.

    Segments between SURVIVING vertices: a malformed sample is skipped, joining its neighbours, so
    a corrupt row can only make the measured swept path longer, never shorter.

    Horizontal (XY) on purpose: it is the separation the policy's own `min_bird_clearance_m` is
    expressed in, and ADR-009 is explicit that a bird's z is the estimate we cannot trust, so
    folding altitude in here would let an untrusted number manufacture clearance.

    None, never a number, when there are no detections or no path: 'nothing came close' and 'we
    never looked' are opposite claims and the caller must be able to tell them apart."""
    dets = detection_positions(log)
    path = log.get("flown_path_enu") if isinstance(log, dict) else None
    if not dets or not isinstance(path, list) or not path:
        return None
    pts: List[Tuple[float, float]] = []
    for point in path:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        try:
            pts.append((float(point[0]), float(point[1])))
        except (TypeError, ValueError):
            continue
    if not pts:
        return None
    # A one-sample path is no segment but is still evidence: measure it as a degenerate one.
    segments = list(zip(pts, pts[1:])) or [(pts[0], pts[0])]
    best: Optional[Tuple[float, str]] = None
    for (ax, ay), (bx, by) in segments:
        for track_id, dx, dy in dets:
            d = _point_segment_xy_m(dx, dy, ax, ay, bx, by)
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


# The project's one point-to-segment primitive, re-exported under the names this module's callers
# (and its tests, and build_dashboard_data) already use. `fieldguard_planning.geom` owns the body.
_point_segment_xy = point_segment_projection_xy


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
    denominator -- reported, never gated, because the camera is NADIR (it looks straight down, ADR-007
    am. 5): a bird inside the threat cylinder is routinely outside the downward footprint at its own
    altitude, and one above the drone is never in frame at all, so gating on it would measure
    geometry, not detection quality. It stays a per-TICK count (pass 1 only): its denominator is
    ticks the loop could have engaged on."""
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


def gate_encounter_closure(log, run, adv: dict) -> Tuple[List[str], List[str]]:
    """Assertion: every encounter this flight opened, it also CLOSED -- and it closed for a reason
    the log names.

    Three things no other gate can see (QA C1, 2026-08-25):

    (1) AN UNMATCHED TAKEOVER IS A FAILURE. The executor's threat-clear hysteresis resets on every
        threat tick, so a detection duty cycle denser than 1-in-`resume_clear_ticks` never reaches
        the count: measured on the real executor, 90 ticks of `DIVERT, PROCEED, PROCEED` gave 1
        takeover and 0 resumes -- the mission never came back and every remaining cell booked as
        coverage debt, while the log looked ordinary. A log that ends in GUIDED is not a completed
        survey, so its coverage claim after that takeover means nothing.
    (2) A `guided_ceiling` RESUME IS REPORTED, LOUDLY. It is the executor's backstop firing, not a
        cleared threat; the flight is still scoreable, but something upstream (a duty-cycled
        detector, an all-stale stream) needs fixing and must not pass unread.
    (3) THE HYSTERESIS BUDGET, PRICED ON THIS FLIGHT'S OWN CLOCK. `resume_clear_ticks` x the flown
        mean tick period must stay inside `max_detection_age_s`: waiting longer than the policy
        keeps a detection alive means holding GUIDED on evidence it has already declared ABSENT.
        The static test in tests/ pins the same bound at the NOMINAL tick rate (0.6 s at 5 Hz) as a
        floor; this prices it at what the flight measured (0.160 s median on the 2026-08-25 take,
        i.e. 0.48 s -- the nominal arithmetic overstated the budget by 25 %).

    Silent when there is nothing to say, so a log with matched pairs and no recorded executor params
    reads exactly as it did before this gate existed.

    SCHEMA-2 ONLY, by design: `check_schema2` is the only caller. Legacy (pre-`run`) logs keep the
    verdict they were flown under -- the same rule `PRE_SEAM_LEGACY_STEMS` exists for -- and
    `eval/scenarios/*/flight_log.json` are open-loop CONSTRUCTED fixtures that no automated path
    points this file at (CI's glob is eval/results/ only; run by hand it will score them)."""
    problems: List[str] = []
    notes: List[str] = []
    events = log.get("events") or []
    takeovers = [e for e in events if isinstance(e, dict) and e.get("kind") == "takeover"]
    resumes = [e for e in events if isinstance(e, dict) and e.get("kind") == "resume"]
    if len(takeovers) > len(resumes):
        last = takeovers[-1].get("tick")
        problems.append(
            f"UNCLOSED ENCOUNTER: {len(takeovers)} takeover(s) but {len(resumes)} resume(s) -- the "
            f"flight ended in GUIDED (last takeover tick {last}). The mission never resumed, so "
            f"every cell after that tick is unflown coverage the ledger cannot speak for. TWO known "
            f"causes, and they look identical here: (a) a detection duty cycle denser than "
            f"1-in-resume_clear_ticks resets the threat-clear hysteresis every time (QA C1) -- check "
            f"`resume_pending.ticks_in_guided` climbing and whether a `guided_ceiling` resume ever "
            f"fired; (b) the OPERATOR ended the take mid-dodge (evidence-first teardown: Ctrl-C "
            f"during a hold produces exactly this signature) -- check the last tick's stamp against "
            f"when you stopped the run before hunting a detector fault.")
    for r in resumes:
        if r.get("trigger") == "guided_ceiling":
            notes.append(f"GUIDED-CEILING BACKSTOP FIRED at tick {r.get('tick')} after "
                         f"{r.get('ticks_in_guided')} ticks in GUIDED (ceiling "
                         f"{r.get('ceiling_ticks')}): the encounter was ended by the bound, NOT by a "
                         f"cleared threat. The flight is scoreable; the detection stream is not "
                         f"healthy.")

    ep = log.get("executor_params")
    ticks = _num((ep or {}).get("resume_clear_ticks")) if isinstance(ep, dict) else None
    step_s = _num(adv.get("mean_step_s"))
    age_bound = _num((run.get("policy_params") or {}).get("max_detection_age_s"))
    if ticks is not None and step_s is not None and age_bound is not None:
        budget = ticks * step_s
        verdict = "within" if budget <= age_bound else "EXCEEDS"
        line = (f"hysteresis budget {budget:.3f} s ({ticks:g} clear ticks x {step_s:.3f} s measured "
                f"mean tick) {verdict} max_detection_age_s {age_bound:g}")
        (notes if budget <= age_bound else problems).append(
            line if budget <= age_bound else
            line + " -- the executor can hold GUIDED waiting for clear ticks longer than the policy "
                   "keeps a detection alive, i.e. on evidence already declared ABSENT")
    return problems, notes


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


def gate_detector_block_matches_source(run) -> List[str]:
    """ONE RULE: the name on the detector block and the fields inside it must be the same detector.

    Two apertures now write this block (`ndvi_detect` on the nadir camera, `depth_detect` +
    `depth_segment` on the forward one) and their field sets do not overlap, so a mismatch is
    detectable and is never innocent. It matters in the direction that reads as success: a DEPTH
    take labelled `ndvi_blob` would be routed through the gates below -- the detect-rate floor over
    `ndvi_msgs_received` (a counter it does not have), the apparent-size estimator check, ADR-003's
    adopted-detector verdict -- i.e. one sensor's flight certified with another sensor's evidence.
    The reverse (an NDVI take relabelled `depth_blob`) is the same defect wearing the other hat: it
    would leave the NDVI gates unrun.

    The block's own `counters` are read too, because that is where the two families are most
    obviously distinct (`ndvi_msgs_received` vs `depth_msgs_received`) and where a copy-paste
    between them would land.

    Only the two REAL detector names are checked: `demo_virtual` and `none` carry no detector
    fields at all, and a source this gate does not recognise is already refused as unscoreable."""
    detector = run.get("detector")
    if not isinstance(detector, dict):
        return []                    # absence is gate_detector_ran's / run_block_problem's business
    source = detector.get("source")
    if source not in (DET_NDVI_BLOB, DET_DEPTH_BLOB):
        return []
    counters = detector.get("counters")
    counter_keys = set(counters) if isinstance(counters, dict) else set()
    if source == DET_NDVI_BLOB:
        foreign_fields, foreign_counters, other = (DEPTH_ONLY_DETECTOR_FIELDS,
                                                   DEPTH_ONLY_COUNTERS, DET_DEPTH_BLOB)
    else:
        foreign_fields, foreign_counters, other = (NDVI_ONLY_DETECTOR_FIELDS,
                                                   NDVI_ONLY_COUNTERS, DET_NDVI_BLOB)
    intruders = ([f for f in foreign_fields if f in detector]
                 + [f"counters.{k}" for k in foreign_counters if k in counter_keys])
    if not intruders:
        return []
    return [f"run.detector.source is {source!r} but the block carries {other}'s own field(s) "
            f"{sorted(intruders)} -- the label and the contents are different detectors. One of "
            f"the two is a lie, and this gate cannot tell which, so the flight is not scoreable "
            f"as either: a mislabelled take is certified with the OTHER sensor's gates (the "
            f"detect-rate floor, the range model, the adopted-detector verdict), which is exactly "
            f"the shape of evidence this file exists to refuse. `avoidance_node.detector_log_block` "
            f"writes one branch or the other and never mixes them; a block that mixes them was "
            f"edited or assembled by hand."]


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


# ================================================================================================
# SCHEMA 2, DEPTH FLAVOUR -- the SEVEN PRE-REGISTERED BARS (P1, 2026-09-07)
# ================================================================================================
# WHY A SECOND FAMILY AT ALL. `depth_blob` is a different sensor, not a different threshold: the
# forward aperture MEASURES range where the nadir one INFERS it from an assumed bird radius, and the
# counters, the failure modes and the geometry are all different. Every gate above that reads
# `ndvi_msgs_received`, prices an apparent-size ray, or reasons about a downward footprint is
# therefore N/A here -- and says so IN THOSE WORDS (bar 7), because a gate that passes on a
# measurement it never made is the family this repo already paid for (eval/score.py's ADOPT on
# empty ground truth, 2026-08-21).
#
# WHERE THE BARS COME FROM, AND WHY THEY ARE QUOTED. All seven were written by qa-safety in
# `docs/runbooks/DODGE_TAKE_PREREGISTRATION_20260907.md` §P1 BEFORE any depth take existed, so no
# result can be reinterpreted afterwards (ADR-016 doctrine). Each gate's message quotes its bar
# verbatim from that file, and `tests/fieldguard_planning/test_check_live_flight_log_depth.py` pins
# every quote as a substring of the pre-registration itself -- so the gate cannot be quietly
# re-aimed at an easier bar after a flight fails it.
#
# TWO THINGS THE LOG DOES NOT CARRY, both found by BUILDING this gate rather than by flying into
# them, both named in the messages that need them:
#   * NO ORIENTATION. `flown_path_enu` is positions only; `DroneState.heading_rad` reaches the
#     executor and is never logged. Bar 4's forward axis is therefore the vehicle's COURSE OVER
#     GROUND, measured from the flown path either side of the tick -- exact in a noiseless sim while
#     the vehicle translates the way it points, and wrong by exactly the crab angle when it does not.
#   * NO OUT-OF-CYLINDER DETECTION. `AvoidanceExecutor._log_detection` writes a `detection` event
#     only when the policy attached a triggering detection, which happens only for a threat INSIDE
#     `PolicyParams.threat_radius_m` (12.0 m). So the earliest range any log this executor writes can
#     show is ~13.4 m, and bar 5's 33.591 m acquisition premise is CENSORED by the policy, not
#     measured by the sensor. Bar 5 fails as pre-registered and its message says which of the two it
#     is looking at, because "the sensor acquired late" and "the artifact cannot see the
#     acquisition" rank completely different work.
P1_BARS = {
    1: ("Detect-rate floor over the right denominator. frames_detected_on / depth_msgs_received "
        ">= 0.90 (MIN_DETECT_RATE, :1197 -- same floor, new denominator). frames_detected_on == 0 "
        "is a hard failure, not a vacuous pass."),
    2: ("dropped_frame_shape_mismatch == 0, hard. No NDVI analogue exists. The counter's own note "
        "(depth_detect.counters): a frame whose shape is not the armed camera_info's \"places the "
        "obstacle tens of metres from where it is\"."),
    3: ("Range model. The NDVI gate prices an apparent-size ray; depth must instead assert the "
        "block names depth_pixel_to_enu un-projection, and range_estimate_error_at_cpa_m becomes a "
        "GATED number at <= 0.5 m -- the segmenter's own scored bar (measured p95 0.1076 m over 63 "
        "matches). The monocular ray could never be gated (1.65 m median); this sensor earns it."),
    4: ("Encounter reasoning -- frustum containment. For every accepted maneuver, the triggering "
        "detection's bearing from the paired pose must lie inside the forward frustum (+/-31.6 deg "
        "horizontal, +/-24.775 deg vertical; config/depth_camera.json hfov 1.1033 rad, fy 520.006 "
        "/ cy 240). A threat \"detected\" outside the frustum is a wrong pose pair or a wrong "
        "un-projection."),
    5: ("First-detection range per encounter >= 33.591 m (ADR-020 am. 2), else the take is "
        "INVALID-for-authorisation"),
    6: ("No dodge against the map. Any accepted maneuver whose triggering detection carries a "
        "non-null static_map_hint is a FAIL (confidently-wrong perception). The annotator is "
        "annotate-and-count only (detections_near_known_obstacle); nothing consumes the hint yet"),
    7: ("The NDVI-family gates must print N/A (depth take) in those words, never PASS. A gate that "
        "passes because it measured nothing is the family this repo already paid for (eval/score.py"
        ", 2026-08-21)."),
}


def _bar(n: int) -> str:
    """`P1 bar N, pre-registered verbatim: "..."` -- the tag every depth message leads with."""
    return f'P1 bar {n}, pre-registered verbatim: "{P1_BARS[n]}"'


# The words bar 7 requires, spelled once. A test greps every NDVI-family line for exactly this.
NA_DEPTH = "N/A (depth take)"
# ...and the words a DECLARED bird-less flight requires, for the same reason and spelled the same
# way. See the `--no-birds` section further down for what a declaration is and what falsifies one;
# the constant lives up here because the depth tail below prints it. A test greps for it exactly.
NA_NO_BIRDS = "N/A (no birds driven)"
# The ONE depth bar that needs a bird (P1 bar 3b, the truth-referenced range error). Named once and
# consumed twice -- by the bar's own note and by the DEPTH BARS MEASURED summary -- so the two can
# never disagree about whether it read UNMEASURED or N/A.
DEPTH_BAR_NEEDS_TRUTH = "3b range error"
# `DepthDetectionSource.counters()` -- the whole contract, because a counter that is ABSENT is not a
# counter that is zero, and these are the only evidence the depth detector ran at all.
DEPTH_DETECTOR_COUNTER_KEYS = (
    "depth_msgs_received", "frames_detected_on", "frames_with_detection", "boxes_total",
    "dropped_no_intrinsics", "dropped_no_pose_pair", "dropped_stale_pose_pair",
    "dropped_frame_shape_mismatch", "dropped_non_finite_depth", "dropped_out_of_range",
    "detections_near_known_obstacle", "static_map_annotator_errors",
)
# The node's OWN in-container wall clock, which is the only one that settles the container question
# (host measured 6.708 / 10.786 ms over n = 425; container ~1.2x on comparable work).
DEPTH_WALL_MS_KEYS = ("detect_wall_ms_p95", "detect_wall_ms_max", "detect_wall_ms_n")
DETECT_WALL_MS_P95_BAR = 25.0
DETECT_WALL_MS_MAX_BAR = 100.0
# What `avoidance_node._depth_detector_log_block` must declare, verbatim. Bar 3's first half: the
# NDVI block's `range_model` prices an apparent-size ray off a RADIUS PRIOR, and ADR-009 rule 2's
# fail-dangerous alternative is a ground-plane projection (it puts a flying bird at z=0, outside the
# threat cylinder). A depth block that does not say which model it flew cannot be read as either.
DEPTH_RANGE_MODEL = "measured depth (ADR-020); no radius prior, no ground-plane projection"
# The un-projection module bar 3 names. `depth_pixel_to_enu` lives here; the block records the
# module rather than the function, so this is as close to the pre-registered wording as the artifact
# gets -- and it is checked rather than assumed.
DEPTH_SEAM_MODULE = "fieldguard_planning.depth_detect"
# `_intrinsics_block` writes "live <topic> (not <config>)". The topic half is the load-bearing one:
# intrinsics taken from config/depth_camera.json are what we ASKED for, not what the sensor GOT, and
# every number bar 4 computes is divided by them.
DEPTH_INTRINSICS_PROVENANCE = "live /fg/depth/camera_info"
# ADR-020 am. 2, read forwards: `--acq-range-m 33.6` still exits 0 at exactly 1.300x and `33.5`
# exits 1, so this is the acquisition range below which the 5.0 m/s booking is not authorised.
BREAKEVEN_ACQUISITION_M = 33.591
# The segmenter's own scored bar (eval/results/depth_segmenter_score_20260907T110000Z.json: p95
# 0.1076 m over 63 matches). A monocular ray could never be gated at all -- 1.65 m median error on
# the adopted clip -- which is exactly what this sensor is for.
DEPTH_RANGE_ERROR_BAR_M = 0.5
# The forward mount's translation, body FLU, from `depth_detect.FORWARD_MOUNT_OFFSET_BODY_M` /
# config/depth_camera.json `mount.mount_pose_xyz_rpy`. RESTATED, not imported, for the same reason
# `AIRBORNE_Z_M` is: `depth_detect` imports `clip_recorder`, which imports numpy, and this gate is
# stdlib-only by contract. The copies are pinned equal by test. It is applied rather than ignored
# because ignoring it UNDER-states the off-axis angle (the camera sits 0.15 m nearer the target than
# the body origin), i.e. it fails in the optimistic direction on the one bar that asks whether the
# sensor could have seen the thing at all.
DEPTH_MOUNT_FORWARD_M = 0.15


def depth_detector_counters(run) -> Tuple[Optional[dict], Optional[dict], Optional[str]]:
    """(numeric counters, the raw counters dict, problem). The raw dict comes back too, because the
    wall-ms trio is legitimately `None` before the first frame and must be told apart from absent."""
    detector = run.get("detector") if isinstance(run, dict) else None
    counters = detector.get("counters") if isinstance(detector, dict) else None
    if not isinstance(counters, dict):
        return None, None, (
            "run.detector.counters missing -- `DepthDetectionSource.counters()` writes them on "
            "every flight, so absence means this log did not come from that seam and the detect "
            "half of this flight is unmeasured")
    values = {k: _num(counters.get(k)) for k in DEPTH_DETECTOR_COUNTER_KEYS}
    missing = sorted(k for k, v in values.items() if v is None)
    if missing:
        return None, counters, (
            f"run.detector.counters is missing or non-numeric for {missing} -- a counter that is "
            f"absent is not a counter that is zero, and these are the only evidence the depth "
            f"detector ran at all (`DepthDetectionSource.counters`)")
    return values, counters, None


def depth_counter_contradictions(values) -> List[str]:
    """Relations that CANNOT be false on a log `DepthDetectionSource` wrote -- one line each.

    A counter that is absent is not a counter that is zero (`depth_detector_counters`); the missing
    half, found by mutating this gate rather than reading it (QA 2026-09-07), is that a counter
    LARGER than its own denominator is not a counter at all. `frames_detected_on: 5000` over
    `depth_msgs_received: 1200` is a detect rate of 4.17 and cleared bar 1's 0.90 floor in silence.

    Each relation is read straight off `depth_detect.on_frame`, which is the only writer:
      * every call takes EXACTLY ONE of five paths -- no intrinsics, shape mismatch, no pose pair,
        stale pose pair, or through to the segmenter (`_frame_index += 1`) -- so those five sum to
        `depth_msgs_received` exactly. `dropped_non_finite_depth` / `dropped_out_of_range` are NOT
        in the sum: they are per-BOX, not per-frame (the counters' own note says so);
      * `frames_with_detection` is incremented only inside the segmenter path;
      * `boxes_total += len(dets)`, and that branch adds 1 to `frames_with_detection` only when
        `len(dets) >= 1`.
    A violation is a fabricated, merged or hand-edited counter block, and every bar below divides by
    these numbers."""
    per_frame = ("dropped_no_intrinsics", "dropped_frame_shape_mismatch", "dropped_no_pose_pair",
                 "dropped_stale_pose_pair", "frames_detected_on")
    paths = sum(values[k] for k in per_frame)
    broken = []
    if paths != values["depth_msgs_received"]:
        broken.append(
            f"{' + '.join(per_frame)} = {paths:g}, but depth_msgs_received = "
            f"{values['depth_msgs_received']:g} (every on_frame call takes exactly one of those "
            f"five paths, so they are EQUAL)")
    if values["frames_with_detection"] > values["frames_detected_on"]:
        broken.append(f"frames_with_detection {values['frames_with_detection']:g} > "
                      f"frames_detected_on {values['frames_detected_on']:g} (a frame cannot carry "
                      f"a detection without reaching the segmenter)")
    if values["boxes_total"] < values["frames_with_detection"]:
        broken.append(f"boxes_total {values['boxes_total']:g} < frames_with_detection "
                      f"{values['frames_with_detection']:g} (a frame counts as having a detection "
                      f"only when it contributed at least one box)")
    if not broken:
        return []
    return ["IMPOSSIBLE COUNTERS: " + "; ".join(broken) + ". These relations are "
            f"`DepthDetectionSource.on_frame`'s own arithmetic, so a log that seam wrote cannot "
            f"break them -- and every rate below is computed from these numbers, which means a "
            f"floor could be cleared by arithmetic that never happened. A counter that is absent "
            f"is not a counter that is zero; a counter larger than its own denominator is not a "
            f"counter at all."]


def gate_depth_detector_ran(log, run) -> Tuple[List[str], List[str]]:
    """P1 bars 1 and 2, plus the node's own runtime bars.

    Bar 1 is the SAME floor as the NDVI gate over a DIFFERENT denominator: `frames_detected_on /
    depth_msgs_received`, where `depth_msgs_received` counts every frame handed to `on_frame` BEFORE
    any guard and `frames_detected_on` is the subset that reached the segmenter. A zero denominator
    is a problem in its own right and never a pass -- 0/0 is a shrug, not a rate.

    Bar 2 has no NDVI analogue. A frame whose shape is not the armed `camera_info`'s is un-projected
    with the wrong intrinsics: a 320x240 camera_info against a 640x480 image mis-places a measured
    20 m target by 19.35 m laterally (measured, QA 2026-09-07). The seam counts and drops those
    frames rather than raising, so the count is the only place that fault appears.

    The runtime bars are read from the node's OWN counters, in the container, which is the only
    place that settles the host-vs-container question the segmenter score left open."""
    problems: List[str] = []
    notes: List[str] = []
    values, raw, problem = depth_detector_counters(run)
    if problem is not None:
        return [problem], []
    problems.extend(depth_counter_contradictions(values))
    received, detected_on = values["depth_msgs_received"], values["frames_detected_on"]
    rate = (detected_on / received) if received > 0 else None
    dropped = (f"dropped no_intrinsics={int(values['dropped_no_intrinsics'])} "
               f"frame_shape_mismatch={int(values['dropped_frame_shape_mismatch'])} "
               f"no_pose_pair={int(values['dropped_no_pose_pair'])} "
               f"stale_pose_pair={int(values['dropped_stale_pose_pair'])} "
               f"non_finite_depth={int(values['dropped_non_finite_depth'])} "
               f"out_of_range={int(values['dropped_out_of_range'])}")
    notes.append(
        f"depth detector counters: depth_msgs_received={int(received)} "
        f"frames_detected_on={int(detected_on)} "
        f"frames_with_detection={int(values['frames_with_detection'])} "
        f"boxes_total={int(values['boxes_total'])} "
        f"detections_near_known_obstacle={int(values['detections_near_known_obstacle'])} "
        f"static_map_annotator_errors={int(values['static_map_annotator_errors'])} | {dropped} "
        f"| detect rate "
        + ("UNMEASURED (0 depth messages)" if rate is None else
           f"{_floor_pct(rate)} of {int(received)} (floor {_floor_pct(MIN_DETECT_RATE)}) "
           f"[{_bar(1)}]"))
    if received == 0:
        problems.append(
            f"DEPTH DETECT RATE HAS NO DENOMINATOR: depth_msgs_received = 0, so "
            f"frames_detected_on/depth_msgs_received is 0/0 -- not a rate, and never a PASS. The "
            f"node never received a depth frame at all: `/fg/depth/image` did not arrive, or the "
            f"subscription was never made. {_bar(1)}")
    elif detected_on == 0:
        problems.append(
            f"DEPTH DETECTOR NEVER RAN: 0 of {int(received)} depth message(s) reached the segmenter "
            f"({dropped}). A flight that armed the depth detector and detected on nothing did not "
            f"fly the take it was booked for -- whatever the separation numbers say, there is no "
            f"detect half to quote. Most likely `/fg/depth/camera_info` never arrived (the node "
            f"exits 4 if none is usable within CAMERA_INFO_WAIT_S, so a log that exists at all "
            f"means it did arrive once) or every frame failed the shape check. {_bar(1)}")
    elif rate is not None and rate < MIN_DETECT_RATE:
        problems.append(
            f"DEPTH DETECTOR BARELY RAN: {int(detected_on)} of {int(received)} depth message(s) "
            f"reached the segmenter = {_floor_pct(rate)}, below the "
            f"{_floor_pct(MIN_DETECT_RATE)} floor ({dropped}). The detect half of this take is a "
            f"handful of frames; a bird could cross the whole encounter unlooked-at and the flight "
            f"would still print R2/R3 PASS (vacuous) and a green separation. {_bar(1)}")
    # -- bar 2: the shape mismatch, HARD --------------------------------------------------------
    mismatch = int(values["dropped_frame_shape_mismatch"])
    if mismatch:
        problems.append(
            f"FRAME SHAPE MISMATCH: dropped_frame_shape_mismatch = {mismatch} of "
            f"{int(received)} depth message(s). The decoded frame's shape was not the armed "
            f"camera_info's (height_px, width_px), so the two halves of the geometry disagree and "
            f"the detector was BLIND for that many frames. Un-projecting one of them places the "
            f"obstacle tens of metres from where it is (measured: a 320x240 camera_info against a "
            f"640x480 image moves a 20 m target 19.35 m laterally and 3.96 m vertically). This bar "
            f"is HARD -- there is no acceptable non-zero value. {_bar(2)}")
    else:
        notes.append(f"dropped_frame_shape_mismatch 0 of {int(received)} depth message(s) -- the "
                     f"decoded frames and the armed camera_info agree on the frame size [{_bar(2)}]")
    # -- the node's own runtime bars ------------------------------------------------------------
    wall = {k: (raw.get(k, _ABSENT)) for k in DEPTH_WALL_MS_KEYS}
    absent = sorted(k for k, v in wall.items() if v is _ABSENT)
    if absent:
        problems.append(
            f"run.detector.counters is missing {absent} -- the segmenter score's runtime bars "
            f"(detect_wall_ms_p95 <= {DETECT_WALL_MS_P95_BAR:g} ms, max <= "
            f"{DETECT_WALL_MS_MAX_BAR:g} ms) are measured on the node's OWN in-container clock, and "
            f"a missing counter is not a fast one. The host bench (6.708 / 10.786 ms over n = 425) "
            f"does not settle the container question; this counter does.")
    else:
        n = _num(wall["detect_wall_ms_n"])
        p95, mx = _num(wall["detect_wall_ms_p95"]), _num(wall["detect_wall_ms_max"])
        # THE SKIP THAT USED TO BE FREE. `detect_wall_ms_n = 0` printed UNMEASURED and returned a
        # VALID log -- in a block claiming p95 125 ms and max 300 ms, i.e. 5x and 3x the bars, never
        # read by anything (QA 2026-09-07). On a flown log that combination cannot occur:
        # `on_frame` increments `_wall_ms_n` in a `finally` on EVERY call, so the counter equals
        # `depth_msgs_received` exactly. n = 0 is UNMEASURED only when the denominator is 0 too --
        # and bar 1 has already failed that take for having no denominator.
        if n is not None and n != received:
            problems.append(
                f"IMPOSSIBLE RUNTIME DENOMINATOR: detect_wall_ms_n = {int(n)} over "
                f"depth_msgs_received = {int(received)}, which cannot happen -- "
                f"`DepthDetectionSource.on_frame` times EVERY call in a `finally`, so the two are "
                f"equal on any log that seam wrote. "
                + (f"With n = 0 the {DETECT_WALL_MS_P95_BAR:g} / {DETECT_WALL_MS_MAX_BAR:g} ms bars "
                   f"read as UNMEASURED and are skipped entirely, so this is the exact shape that "
                   f"hides a slow detector behind a zero (this block claims p95 "
                   f"{wall['detect_wall_ms_p95']!r} / max {wall['detect_wall_ms_max']!r}). "
                   if not n else
                   f"A gap of {int(received - n)} frame(s) means these counters did not come from "
                   f"one run of one seam. ")
                + f"The runtime bars are still evaluated below on the numbers as given.")
        if n is None:
            problems.append(
                f"detect_wall_ms_n is {wall['detect_wall_ms_n']!r} -- not a number, so the "
                f"{DETECT_WALL_MS_P95_BAR:g} / {DETECT_WALL_MS_MAX_BAR:g} ms bars have no "
                f"denominator at all and a missing denominator is not a fast detector.")
        elif not n and p95 is None and mx is None:
            notes.append(f"detect wall time UNMEASURED: detect_wall_ms_n = "
                         f"{wall['detect_wall_ms_n']!r}, so the {DETECT_WALL_MS_P95_BAR:g} / "
                         f"{DETECT_WALL_MS_MAX_BAR:g} ms bars have no samples behind them. Never a "
                         f"PASS -- the detector processed no frame it could time.")
        elif p95 is None or mx is None:
            problems.append(
                f"detect_wall_ms_p95 / detect_wall_ms_max are {wall['detect_wall_ms_p95']!r} / "
                f"{wall['detect_wall_ms_max']!r} over n = {int(n)} timed frame(s) -- half a "
                f"runtime statistic is field drift, not a fast detector, and the half that is "
                f"missing is not the one that was inside its bar")
        else:
            notes.append(f"detect wall time p95 {p95:.3f} ms (bar {DETECT_WALL_MS_P95_BAR:g}) max "
                         f"{mx:.3f} ms (bar {DETECT_WALL_MS_MAX_BAR:g}) over n = {int(n)} timed "
                         f"frame(s) -- the node's OWN in-container clock, which is what settles the "
                         f"host-vs-container question")
            for name, got, bar_ms in (("p95", p95, DETECT_WALL_MS_P95_BAR),
                                      ("max", mx, DETECT_WALL_MS_MAX_BAR)):
                if got > bar_ms:
                    problems.append(
                        f"DETECT WALL TIME OVER BAR: detect_wall_ms_{name} {got:.3f} ms exceeds "
                        f"{bar_ms:g} ms over n = {int(n)} timed frame(s). The segmenter is eating "
                        f"the control tick it shares (0.160 s median), which is lead time the "
                        f"booking gate has already spent in its latency budget.")
    # A detector whose output all EXPIRED wears the same clothes as a quiet sky -- the same
    # combination `gate_detector_ran` fails for the nadir camera, and it is sensor-independent.
    n_dets, n_stale = n_detection_events(log), stale_dropped_total(log)
    if n_stale and not n_dets:
        problems.append(
            f"AVOIDANCE WAS DEAD: the ADR-009 staleness gate dropped {n_stale} detection(s) and the "
            f"loop engaged on ZERO ticks -- every detection this flight had expired before the "
            f"policy could act on it, so no bird was ever avoided and no maneuver was ever vetted.")
    elif values["boxes_total"] and not n_dets:
        notes.append(
            f"the depth detector produced {int(values['boxes_total'])} box(es) and the loop engaged "
            f"on 0 tick(s), with 0 stale drops: every box fell OUTSIDE the policy's threat cylinder "
            f"(threat_radius_m {PolicyParams().threat_radius_m:g} m). That is a real flight, not a "
            f"dead gate -- but any R2/R3 vacuous pass below is vacuous for THAT reason.")
    return problems, notes


def gate_depth_range_model(run) -> Tuple[List[str], List[str]]:
    """P1 bar 3, first half: the block must SAY which range model it flew, and its intrinsics must
    have come off the wire.

    Both halves are INVALID rather than a warning, because both are the difference between a number
    that means metres and a number that means nothing: an apparent-size ray inherits a radius
    prior's error linearly, a ground-plane projection puts a flying bird at z=0 (outside the threat
    cylinder -- ADR-009's fail-dangerous case), and intrinsics read from the config are what we
    ASKED the sensor for rather than what it GAVE us."""
    problems: List[str] = []
    notes: List[str] = []
    detector = run.get("detector") if isinstance(run, dict) else None
    if not isinstance(detector, dict):
        return ["run.detector missing -- a depth take must record the block that ranged its "
                "detections"], []
    model = detector.get("range_model")
    if model != DEPTH_RANGE_MODEL:
        problems.append(
            f"RANGE MODEL NOT DECLARED: run.detector.range_model is {model!r}, expected "
            f"{DEPTH_RANGE_MODEL!r}. The whole reason this sensor can be gated at "
            f"{DEPTH_RANGE_ERROR_BAR_M:g} m is that it MEASURES range; a block that does not say so "
            f"could have flown an apparent-size ray (error linear in an assumed bird radius) or a "
            f"ground-plane projection (a flying bird at z=0, outside the threat cylinder -- the "
            f"fail-dangerous case ADR-009 rule 2 exists for). {_bar(3)}")
    seam = detector.get("seam_module")
    if seam != DEPTH_SEAM_MODULE:
        problems.append(
            f"UN-PROJECTION MODULE NOT NAMED: run.detector.seam_module is {seam!r}, expected "
            f"{DEPTH_SEAM_MODULE!r} -- the module `depth_pixel_to_enu` lives in, which is the "
            f"un-projection the pre-registered bar requires the block to name. {_bar(3)}")
    intr = detector.get("intrinsics")
    if not isinstance(intr, dict):
        problems.append(
            f"NO INTRINSICS BLOCK: run.detector.intrinsics is {intr!r}. Before the first "
            f"`/fg/depth/camera_info` the seam drops every frame, so a log with no intrinsics block "
            f"un-projected nothing -- and bar 4's frustum is computed from fx/fy/width/height, "
            f"which are then absent too. {_bar(3)}")
    else:
        prov = intr.get("provenance")
        if not (isinstance(prov, str) and prov.startswith(DEPTH_INTRINSICS_PROVENANCE)):
            problems.append(
                f"INTRINSICS PROVENANCE: run.detector.intrinsics.provenance is {prov!r}, expected a "
                f"string starting {DEPTH_INTRINSICS_PROVENANCE!r}. The config is what we ASKED for; "
                f"the message is what we GOT, and un-projection divides by these numbers. {_bar(3)}")
        else:
            notes.append(
                f"range model {DEPTH_RANGE_MODEL!r} | intrinsics {prov!r} fx="
                f"{_fmt(_num(intr.get('fx')), 3)} fy={_fmt(_num(intr.get('fy')), 3)} cx="
                f"{_fmt(_num(intr.get('cx')), 3)} cy={_fmt(_num(intr.get('cy')), 3)} "
                f"{intr.get('image_width_px')!r}x{intr.get('image_height_px')!r} [{_bar(3)}]")
    return problems, notes


def _flown_point(log, tick) -> Optional[Tuple[float, float, float]]:
    """`flown_path_enu[tick - 1]` -- that tick's recorded position, or None. The index relation is
    the executor's own: `step()` records exactly one position per call, on every branch."""
    path = log.get("flown_path_enu") if isinstance(log, dict) else None
    if not isinstance(path, list) or not isinstance(tick, int) or isinstance(tick, bool):
        return None
    if not (1 <= tick <= len(path)):
        return None
    point = path[tick - 1]
    try:
        return (float(point[0]), float(point[1]), float(point[2]))
    except (TypeError, ValueError, IndexError):
        return None


def accepted_maneuver_ticks(log) -> List[int]:
    """Ticks carrying an ACCEPTED `maneuver` event -- the dodges this flight actually commanded.
    Bars 4 and 6 are scoped to these: a `gate_reject` is the backstop refusing to fly a point, and
    a HOLD commands zero displacement, so neither is a dodge taken on a detection."""
    out = set()
    for ev in log.get("events") or []:
        if not isinstance(ev, dict) or ev.get("kind") != "maneuver":
            continue
        if ev.get("verdict") not in (None, "accepted"):
            continue
        tick = ev.get("tick")
        if isinstance(tick, int) and not isinstance(tick, bool):
            out.add(tick)
    return sorted(out)


def depth_detections(log) -> List[dict]:
    """Every `detection` event, with the range the flight can actually be held to.

    `range_m` is the 3D distance from the detection's estimated world position to the drone's own
    recorded position at that tick -- the same arithmetic the pre-registration's §6 analysis plan
    runs (`math.dist(e["position_enu"], fp[e["tick"]-1][:3])`), so the gate and the runbook cannot
    disagree about what "detection range" means. 3D, not horizontal, because that is what a depth
    camera measures and what the acquisition budget is expressed in.

    `hint` is `_ABSENT` when the event carries no `static_map_hint` KEY at all -- which is what the
    executor writes today -- and that is a different fact from a null hint. Bar 6 depends on the
    distinction."""
    out: List[dict] = []
    for ev in log.get("events") or []:
        if not isinstance(ev, dict) or ev.get("kind") != "detection":
            continue
        tick = ev.get("tick")
        pos = ev.get("position_enu")
        entry = {"tick": tick, "position_enu": None, "range_m": None,
                 "hint": ev.get("static_map_hint", _ABSENT),
                 "track_id": ev.get("track_id"), "drone_enu": None}
        try:
            entry["position_enu"] = (float(pos[0]), float(pos[1]), float(pos[2]))
        except (TypeError, ValueError, IndexError):
            out.append(entry)
            continue
        drone = _flown_point(log, tick)
        if drone is not None:
            entry["drone_enu"] = drone
            entry["range_m"] = math.dist(entry["position_enu"], drone)
        out.append(entry)
    return out


def _declared_range_window(run) -> Tuple[Optional[float], Optional[float]]:
    """`(min_range_m, max_range_m)` as the flight's own block declares them.

    This is the seam's EXCLUSIVE refusal window: `DepthDetectionSource.box_to_detection` returns
    None for `not (min_range_m < d < max_range_m)`, both ends open, because gz stops measuring AT
    the clip planes and exactly-min/exactly-max is what a clamp looks like."""
    detector = run.get("detector") if isinstance(run, dict) else None
    if not isinstance(detector, dict):
        return None, None
    return _num(detector.get("min_range_m")), _num(detector.get("max_range_m"))


def acquisition_plausibility(log, run, det) -> Optional[str]:
    """Is the range bar 5 is about to credit one this sensor could have MEASURED? The problem if
    not, None if it is.

    WHY THIS EXISTS (QA 2026-09-07, on the implementation of the bar rather than its text). Bar 5 is
    the only bar whose failure class is INVALID-for-authorisation, and as pre-registered it compares
    ONE number against 33.591 m and nothing else. So a first detection at 500 m from a block whose
    own `max_range_m` is 60.0 read "at or beyond the breakeven" and the take was VALID -- the bar
    that decides authorisation was the one bar with no plausibility check, in the direction that
    reads as success. The P2 work that ends bar 5's censoring (getting the seam's longest-range
    detection into the artifact) is exactly the work that will start feeding this bar raw
    un-projected ranges, i.e. the one number a wrong un-projection produces.

    THE TWO REFUSALS, both EXACT -- no crab-angle substitution, so neither can fire on a sound log:
      * BEHIND THE CAMERA. Needs a course (the same substitution bar 4 makes and names), and is
        180 deg wide, so a crab angle cannot produce it.
      * OUTSIDE THE DECLARED WINDOW. Needs no course at all. The camera sits
        `DEPTH_MOUNT_FORWARD_M` ahead of the body origin, so the range from the CAMERA is within
        that of the range from the body; and every detection came through a PIXEL, so its off-axis
        angle is at most the frame corner's, i.e. the along-axis depth `d` the seam actually gated
        satisfies `(range - mount) / corner <= d <= range + mount`. If that whole interval lies at
        or outside `(min_range_m, max_range_m)`, no depth the seam would have accepted can be behind
        this position. Strictly tightening: it can only turn a credited range into a refused one."""
    lo, hi = _declared_range_window(run)
    rng, tick = det["range_m"], det["tick"]
    if lo is None or hi is None or not (0.0 < lo < hi):
        detector = run.get("detector") if isinstance(run, dict) else None
        got = (None if not isinstance(detector, dict)
               else (detector.get("min_range_m"), detector.get("max_range_m")))
        return (
            f"ACQUISITION RANGE BOUNDED BY NOTHING at tick {tick}: this bar would credit "
            f"{rng:.3f} m as the range that authorised the flight, and run.detector's "
            f"(min_range_m, max_range_m) are {got!r} -- so the artifact does not say what range "
            f"this sensor can measure, and the number deciding authorisation is bounded by "
            f"nothing. `avoidance_node._depth_detector_log_block` writes both off the seam that "
            f"flew; a block missing them did not come from that writer. {_bar(5)}")
    course = _course_unit(log, tick)
    if (course is not None and det["position_enu"] is not None and det["drone_enu"] is not None
            and depth_bearing_deg(det["position_enu"], det["drone_enu"], course) is None):
        return (
            f"ACQUISITION BEHIND THE CAMERA at tick {tick}: the {rng:.3f} m this bar would credit "
            f"is the distance to a point at or BEHIND the forward camera's image plane, on a "
            f"course of ({course[0]:+.3f}, {course[1]:+.3f}). A forward depth camera cannot "
            f"measure what is behind it, so this is a wrong pose pair or a wrong un-projection, "
            f"not an acquisition. "
            + ("Bar 4 says the same thing about the same detection, from the maneuver side. "
               if tick in accepted_maneuver_ticks(log) else
               "Bar 4 does NOT catch it here: that bar is scoped to ACCEPTED maneuvers, as "
               "pre-registered, and this tick carries none. ")
            + f"NOTE THE ONE SUBSTITUTION: the log records no orientation, so the forward axis is "
            f"the vehicle's COURSE over ground -- at 180 deg off it that substitution cannot be "
            f"what produced this. {_bar(5)}")
    detector = run.get("detector") if isinstance(run, dict) else None
    half = _frustum_half_angles_rad(detector.get("intrinsics") if isinstance(detector, dict)
                                    else None)
    corner = (None if half is None
              else math.sqrt(1.0 + math.tan(half[0]) ** 2 + math.tan(half[1]) ** 2))
    d_hi = rng + DEPTH_MOUNT_FORWARD_M
    d_lo = None if corner is None else max(0.0, rng - DEPTH_MOUNT_FORWARD_M) / corner
    frustum = ("the frame corner is UNKNOWN (bar 3 fails this block's intrinsics), so only the "
               "lower bound on the along-axis depth is checked here"
               if corner is None else
               f"every detection came through a pixel inside +/-{math.degrees(half[0]):.3f} deg h "
               f"/ +/-{math.degrees(half[1]):.3f} deg v, so the along-axis depth behind it is at "
               f"least {d_lo:.3f} m")
    end = ("NEARER than min_range_m" if d_hi <= lo
           else "FURTHER than max_range_m" if d_lo is not None and d_lo >= hi else None)
    if end is not None:
        return (
            f"ACQUISITION RANGE THIS SENSOR CANNOT MEASURE at tick {tick}: {rng:.3f} m is "
            f"{end}, against the block's OWN declared window (min_range_m {lo:g}, max_range_m "
            f"{hi:g}, exclusive both ends -- `box_to_detection` returns None outside it). The "
            f"camera sits {DEPTH_MOUNT_FORWARD_M:g} m ahead of the body origin and {frustum}, so "
            f"no depth the seam would have accepted can sit behind this position. A range this "
            f"sensor cannot measure is not an acquisition, it is a bad un-projection -- and this "
            f"is the bar that decides authorisation. {_bar(5)}")
    return None


def gate_depth_acquisition(log, run) -> Tuple[List[str], List[str], bool]:
    """P1 bar 5: the first detection of each encounter, against the 33.591 m breakeven.

    THE NUMBER THIS CAN SEE, STATED BEFORE IT IS READ. A `detection` event exists only where the
    policy attached a triggering detection, and it only does that for a threat already INSIDE
    `PolicyParams.threat_radius_m` (12.0 m horizontal, +/-6 m vertical -- 13.42 m at the corner of
    that cylinder). No log this executor writes can therefore report a first detection beyond
    ~13.4 m,
    whatever the sensor saw at 46 m. The bar fails as pre-registered either way -- it is a bar about
    authorisation, and an unevidenced authorisation is not a verified one -- but the message
    distinguishes the two readings, because they rank completely different work:
      * range ABOVE the cylinder and BELOW the breakeven -> the sensor really did acquire late, and
        the horizon lever is what that ranks;
      * range AT OR BELOW the cylinder -> the artifact cannot see the acquisition at all, and what
        that ranks is one field on `_log_detection` (or a max-range counter on the seam).

    The third element is whether this bar READ its evidence (a range it could hold to the bar), so
    the tail can count how many of the four event-dependent bars measured anything at all."""
    problems: List[str] = []
    notes: List[str] = []
    measured = False
    pp = PolicyParams()
    cylinder_m = math.hypot(pp.threat_radius_m, pp.vertical_threat_m)
    windows = encounter_windows(log, len(log.get("flown_path_enu") or []))
    dets = [d for d in depth_detections(log) if d["range_m"] is not None]
    if not windows:
        notes.append(
            f"ACQUISITION RANGE UNMEASURED: this take logged no encounter window (no takeover "
            f"event), so there is no first-detection range to hold to the "
            f"{BREAKEVEN_ACQUISITION_M:.3f} m breakeven. Never a PASS -- an encounter that did not "
            f"happen proves nothing about the horizon that authorised the flight. [{_bar(5)}]")
        return problems, notes, measured
    for lo, hi, label in windows:
        inside = sorted((d for d in dets if isinstance(d["tick"], int) and lo <= d["tick"] <= hi),
                        key=lambda d: d["tick"])
        if not inside:
            problems.append(
                f"ACQUISITION RANGE UNMEASURED on {label}: the window carries no `detection` event "
                f"with a usable position and a recorded drone pose, so the range at which this "
                f"encounter was acquired cannot be read at all. An encounter the artifact cannot "
                f"date is not an encounter this booking was verified on. {_bar(5)}")
            continue
        first = inside[0]
        rng = first["range_m"]
        measured = True
        line = (f"{label}: first detection at tick {first['tick']}, range {rng:.3f} m "
                f"(bar {BREAKEVEN_ACQUISITION_M:.3f} m, {len(inside)} detection(s) in window)")
        # THE SANITY CHECK BEFORE THE COMPARISON. A range the sensor cannot have measured is
        # refused rather than credited -- and it is refused BEFORE the breakeven comparison, so an
        # implausible number can never earn the "at or beyond the breakeven" note.
        implausible = acquisition_plausibility(log, run, first)
        if implausible is not None:
            problems.append(implausible)
        if rng >= BREAKEVEN_ACQUISITION_M:
            if implausible is None:
                notes.append(f"acquisition {line} -- at or beyond the breakeven [{_bar(5)}]")
            continue
        censored = rng <= cylinder_m
        problems.append(
            f"ACQUISITION BELOW BREAKEVEN -- {line}. Restated verbatim from ADR-020 am. 2: "
            f"\"Breakeven acquisition is 33.591 m: `--acq-range-m 33.6` still exits 0 at exactly "
            f"1.300x, and `33.5` exits 1. So the booked 46.0 m is not marginal -- but if the "
            f"segmenter's real, cluttered acquisition range comes in under 33.6 m, this gate goes "
            f"red and the dodge take is not bookable at 5 m/s.\" "
            + (f"AND THIS NUMBER IS CENSORED, NOT MEASURED: {rng:.3f} m is at or inside the "
               f"policy's own threat cylinder ({cylinder_m:.3f} m at the corner of "
               f"threat_radius_m {pp.threat_radius_m:g} / vertical_threat_m "
               f"{pp.vertical_threat_m:g}), and `AvoidanceExecutor._log_detection` writes a "
               f"`detection` event ONLY for an in-cylinder threat. So no log this executor "
               f"produces can evidence acquisition at 33.591 m, whatever the sensor saw. What "
               f"this ranks is therefore the LOGGING gap -- the seam's own longest-range "
               f"detection per frame has to reach the artifact -- NOT the horizon lever. "
               if censored else
               f"The detection is beyond the {cylinder_m:.3f} m threat cylinder, so this IS a "
               f"sensor reading: the encounter was acquired later than the booking's lead budget "
               f"assumes. THE HORIZON LEVER is what that ranks -- re-derive the corner bound from "
               f"the THREAT BAND's own worst pixel rather than the frame's (50.8 m at R = 47.6, "
               f"about +4 m; ADR-020 am. 2 open item 7). Raising `clip_far_m` is refused: it walks "
               f"finite ground into the band. ")
            + f"{_bar(5)}")
    return problems, notes, measured


def _frustum_half_angles_rad(intr) -> Optional[Tuple[float, float]]:
    """(horizontal, vertical) half-angles of the frustum, FROM THE LOG'S OWN INTRINSICS.

    `atan((W/2)/fx)` and `atan((H/2)/fy)` -- the pre-registered +/-31.6 deg / +/-24.775 deg at this
    sensor's live fx = fy = 520.006 in a 640x480 frame, and whatever the flight really flew if the
    camera_info ever changes. Derived, never a constant: a gate that carries its own copy of the
    optics is a gate that keeps passing after the optics move."""
    if not isinstance(intr, dict):
        return None
    fx, fy = _num(intr.get("fx")), _num(intr.get("fy"))
    w, h = _num(intr.get("image_width_px")), _num(intr.get("image_height_px"))
    if None in (fx, fy, w, h) or fx <= 0.0 or fy <= 0.0 or w < 2.0 or h < 2.0:
        return None
    return (math.atan((w / 2.0) / fx), math.atan((h / 2.0) / fy))


def _course_unit(log, tick) -> Optional[Tuple[float, float]]:
    """The vehicle's horizontal COURSE at `tick`, as a unit (E, N), or None if it did not move.

    THE SUBSTITUTION THIS GATE MAKES, IN ONE PLACE. Bar 4 needs the body-forward axis at the paired
    pose and the flight log records no orientation at all -- `DroneState.heading_rad` reaches the
    executor and is never written down. Course over ground is the only heading evidence the artifact
    carries: exact in a noiseless sim while the vehicle translates the way it points, and wrong by
    exactly the crab angle when it does not (a GUIDED dodge can translate sideways while holding
    yaw). Measured over the WIDEST bracket the tick has -- the previous vertex to the next -- so the
    baseline is a whole tick period rather than half of one."""
    before, here, after = (_flown_point(log, tick - 1), _flown_point(log, tick),
                           _flown_point(log, tick + 1))
    for a, b in ((before, after), (here, after), (before, here)):
        if a is None or b is None:
            continue
        de, dn = b[0] - a[0], b[1] - a[1]
        norm = math.hypot(de, dn)
        if norm > 1e-9:
            return (de / norm, dn / norm)
    return None


def depth_bearing_deg(det_enu, drone_enu, course, mount_forward_m: float = DEPTH_MOUNT_FORWARD_M
                      ) -> Optional[Tuple[float, float, float]]:
    """(azimuth deg, elevation deg, along-axis depth m) of a world point in the FORWARD camera's
    optical frame, or None when it sits at or behind the image plane.

    THE INVERSE OF `depth_detect.depth_pixel_to_enu`, and deliberately a separate implementation:
    this gate is stdlib-only (`depth_detect` imports `clip_recorder`, which imports numpy), and a
    gate that re-uses the very code it audits cannot catch that code being wrong. The two are pinned
    to agree by a round-trip test rather than by shared source.

    Level flight is assumed with the course as yaw (see `_course_unit`), so the optical frame is
    Gazebo's: optical z = body +X (forward), optical x (u+) = body -Y (the vehicle's right), optical
    y (v+) = body -Z (down). `atan(x/z)` and `atan(y/z)` are then exactly the angles the half-angles
    from `_frustum_half_angles_rad` bound, i.e. the pixel lands in the frame iff both are inside."""
    cam = (drone_enu[0] + mount_forward_m * course[0],
           drone_enu[1] + mount_forward_m * course[1],
           drone_enu[2])
    de, dn, du = det_enu[0] - cam[0], det_enu[1] - cam[1], det_enu[2] - cam[2]
    forward = de * course[0] + dn * course[1]          # body +X
    left = -de * course[1] + dn * course[0]            # body +Y
    if forward <= 1e-9:
        return None
    return (math.degrees(math.atan2(-left, forward)),   # optical x = -left
            math.degrees(math.atan2(-du, forward)),     # optical y = -up
            forward)


def gate_depth_frustum(log, run) -> Tuple[List[str], List[str], bool]:
    """P1 bar 4: every detection that fed an ACCEPTED maneuver has to be somewhere the sensor could
    have seen it.

    A detection outside the forward frustum was not made by this sensor at this pose: it is a wrong
    pose pair (the seam pairs a frame to the pose at its own gz stamp, and a stale pair at cruise is
    metres of position error), a wrong un-projection, or a detection carried over from a frame that
    is no longer the latest. The failure modes it catches are tens of metres wide; the substitution
    it makes (course for yaw) is degrees wide, and every checked detection prints its own margin so
    a marginal failure is diagnosable rather than mysterious."""
    problems: List[str] = []
    notes: List[str] = []
    detector = run.get("detector") if isinstance(run, dict) else None
    intr = detector.get("intrinsics") if isinstance(detector, dict) else None
    half = _frustum_half_angles_rad(intr)
    accepted = set(accepted_maneuver_ticks(log))
    feeding = [d for d in depth_detections(log)
               if isinstance(d["tick"], int) and d["tick"] in accepted]
    if not feeding:
        notes.append(
            f"FRUSTUM CONTAINMENT UNMEASURED: {len(accepted)} accepted maneuver(s) and 0 of them "
            f"carry a `detection` event on the same tick, so no detection can be placed in the "
            f"sensor's frustum. Never a PASS -- vacuous here means the artifact lost the join "
            f"between a dodge and the thing it dodged. [{_bar(4)}]")
        return problems, notes, False
    if half is None:
        problems.append(
            f"FRUSTUM NOT COMPUTABLE: run.detector.intrinsics carries no usable fx/fy/"
            f"image_width_px/image_height_px ({intr!r}), so the frustum this flight's own camera "
            f"had cannot be derived and {len(feeding)} detection(s) behind accepted maneuver(s) "
            f"cannot be placed inside or outside it. The half-angles are DERIVED from the flight's "
            f"intrinsics on purpose -- a constant here would keep passing after the optics moved. "
            f"{_bar(4)}")
        return problems, notes, False
    h_deg, v_deg = math.degrees(half[0]), math.degrees(half[1])
    checked: List[str] = []
    no_course: List[int] = []
    for d in feeding:
        course = _course_unit(log, d["tick"])
        if course is None or d["position_enu"] is None or d["drone_enu"] is None:
            no_course.append(d["tick"])
            continue
        bearing = depth_bearing_deg(d["position_enu"], d["drone_enu"], course)
        if bearing is None:
            problems.append(
                f"DETECTION BEHIND THE CAMERA at tick {d['tick']}: the detection un-projects to a "
                f"point at or behind the forward camera's image plane, on a course of "
                f"({course[0]:+.3f}, {course[1]:+.3f}). A forward depth camera cannot measure "
                f"something behind it, so this detection was not made by this sensor at this pose "
                f"-- a wrong pose pair or a wrong un-projection. {_bar(4)}")
            continue
        az, el, depth = bearing
        checked.append(f"tick {d['tick']} az {az:+.2f} deg el {el:+.2f} deg depth {depth:.3f} m")
        if abs(az) > h_deg or abs(el) > v_deg:
            problems.append(
                f"DETECTION OUTSIDE THE FRUSTUM at tick {d['tick']}: bearing az {az:+.3f} deg / el "
                f"{el:+.3f} deg against the flight's own half-angles +/-{h_deg:.3f} deg h / "
                f"+/-{v_deg:.3f} deg v (derived from intrinsics fx={_num(intr.get('fx'))!r} "
                f"fy={_num(intr.get('fy'))!r} {intr.get('image_width_px')!r}x"
                f"{intr.get('image_height_px')!r}). The sensor could not have made this detection "
                f"at this pose, and an accepted maneuver was flown on it. NOTE THE ONE "
                f"SUBSTITUTION before hunting the seam: the log records no orientation, so the "
                f"forward axis here is the vehicle's COURSE over ground "
                f"({course[0]:+.3f}, {course[1]:+.3f}) -- if this failure is marginal it may be a "
                f"crab angle, and the fix for THAT is to log the tick's yaw "
                f"(`DroneState.heading_rad` reaches the executor and is never written down). "
                f"{_bar(4)}")
    if checked:
        notes.append(
            f"frustum containment: {len(checked)} of {len(feeding)} detection(s) behind accepted "
            f"maneuver(s) checked against +/-{h_deg:.3f} deg h / +/-{v_deg:.3f} deg v [" +
            "; ".join(checked) + f"]. Forward axis = COURSE over ground (the log records no "
            f"orientation), camera origin offset {DEPTH_MOUNT_FORWARD_M:g} m forward of the body "
            f"origin. [{_bar(4)}]")
    if no_course:
        line = (f"FRUSTUM CONTAINMENT UNMEASURED on {len(no_course)} of {len(feeding)} detection(s) "
                f"behind accepted maneuver(s) (first tick {no_course[0]}): the vehicle's own path "
                f"records no movement either side of that tick, so there is no course to use as the "
                f"forward axis and no orientation was logged. Never a PASS. [{_bar(4)}]")
        if len(no_course) == len(feeding):
            # NOTHING was checked. A partly-unmeasured bar is reported; a wholly-unmeasured one is a
            # problem, or a take that hovered through its encounter would skip bar 4 in silence.
            problems.append(line + " EVERY detection behind an accepted maneuver is in this state, "
                                   "so bar 4 measured nothing at all on this take.")
        else:
            notes.append(line)
    return problems, notes, bool(checked)


def gate_depth_static_map(log, run) -> Tuple[List[str], List[str], bool]:
    """P1 bar 6: no dodge against the map.

    The annotator is ANNOTATE-AND-COUNT ONLY by design (`depth_detect` rule 9): filtering mapped
    detections would delete the bird-beside-a-tree case, and a missed obstacle is a safety bug where
    a wasted dodge is not. So the policy MAY act on a hinted detection -- and if it did, that is a
    dodge taken against a tree the mission already knew about, and it is recorded as a failure.

    WHAT THIS BAR CANNOT SEE TODAY, said out loud rather than passed over: the hint is on
    `Detection.static_map_hint`, and `AvoidanceExecutor._log_detection` writes track_id, frame_id,
    confidence, position_enu, source and decision -- not the hint. So on a log this executor
    produced the field is ABSENT, the bar is UNMEASURED, and it is never a PASS. The seam's own
    `detections_near_known_obstacle` counter is reported beside it as the denominator that exists,
    because the negatives measured 14.375 mapped false positives per frame: a take with a non-zero
    count and no hint in the artifact is a take where this bar had something to find."""
    problems: List[str] = []
    notes: List[str] = []
    accepted = set(accepted_maneuver_ticks(log))
    feeding = [d for d in depth_detections(log)
               if isinstance(d["tick"], int) and d["tick"] in accepted]
    values, _raw, _problem = depth_detector_counters(run)
    annotated = None if values is None else int(values["detections_near_known_obstacle"])
    hinted = [d for d in feeding if d["hint"] is not _ABSENT and d["hint"] is not None]
    absent = [d for d in feeding if d["hint"] is _ABSENT]
    for d in hinted:
        problems.append(
            f"DODGE AGAINST THE MAP at tick {d['tick']}: an ACCEPTED maneuver was flown on a "
            f"detection whose static_map_hint is {d['hint']!r} -- the detection's own estimated "
            f"position falls inside a MAPPED obstacle's 3D geofence, i.e. the vehicle dodged a tree "
            f"the mission already knows about. The annotator is annotate-and-count only, so nothing "
            f"suppressed it and the policy was free to act; that it did is the finding. {_bar(6)}")
    if absent:
        notes.append(
            f"STATIC-MAP BAR UNMEASURED on {len(absent)} of {len(feeding)} detection(s) behind "
            f"accepted maneuver(s): the events carry no `static_map_hint` key at all. "
            f"`AvoidanceExecutor._log_detection` does not write it (checked 2026-09-07), so the "
            f"seam annotates and the artifact loses it. NOT A PASS -- the bar had nothing to read. "
            f"The seam's own denominator: detections_near_known_obstacle = "
            + ("UNREADABLE (counters problem above)" if annotated is None else str(annotated))
            + (f", so this take DID annotate detections near mapped obstacles and this artifact "
               f"cannot say whether any of them drove a dodge. One field on that event closes it."
               if annotated else ". Nothing was annotated on this take either.")
            + f" [{_bar(6)}]")
    if feeding and not absent and not hinted:
        notes.append(
            f"no dodge against the map: {len(feeding)} detection(s) behind accepted maneuver(s), "
            f"every one carrying an explicit null static_map_hint (seam counter "
            f"detections_near_known_obstacle = "
            + ("UNREADABLE" if annotated is None else str(annotated)) + f") [{_bar(6)}]")
    if not feeding:
        notes.append(
            f"STATIC-MAP BAR UNMEASURED: {len(accepted)} accepted maneuver(s) and no `detection` "
            f"event on any of their ticks, so no triggering detection can be read for a hint at "
            f"all. Never a PASS. [{_bar(6)}]")
    # Measured means the hint KEY was there to read on every detection behind an accepted dodge --
    # null or not. A partly-absent hint is a partly-unmeasured bar, and this count is not the place
    # to round that up.
    return problems, notes, bool(feeding) and not absent


def depth_range_error(log, truth, report) -> Tuple[List[str], List[str], bool]:
    """P1 bar 3, second half: the range error this sensor is allowed to have, GATED at 0.5 m.

    THE COMPARISON, stated because it is the whole content of the bar. Each `detection` event gives
    a MEASURED range (its estimated world position against the drone's own recorded position at that
    tick). The applied-pose truth track gives, at the same instant, where the birds really were; the
    detection is associated to the NEAREST truth bird (depth detections carry no `track_id` -- the
    seam has no tracker, rule 6) and the association distance is printed, so a detection matched to
    the wrong bird shows up as a large error rather than as a quiet pass. The gated statistic is
    `range_estimate_error_at_cpa_m` -- the error at the detection nearest in time to the gt-CPA
    instant, i.e. at the moment that decides the flight -- plus the p95 over every matched
    detection, because the segmenter's own scored bar (0.1076 m) is a p95 and a single sample has no
    denominator.

    NO TRUTH, NO NUMBER. The monocular estimator was never gated because it could not be (1.65 m
    median error); this sensor earns the gate by MEASURING range, and the measurement still needs
    something to be measured against. With no truth the bar prints UNMEASURED and never PASS."""
    problems: List[str] = []
    notes: List[str] = []
    dets = [d for d in depth_detections(log) if d["range_m"] is not None]
    if not dets:
        notes.append(f"RANGE ERROR UNMEASURED: this take logged no `detection` event with a usable "
                     f"position and drone pose, so the {DEPTH_RANGE_ERROR_BAR_M:g} m range bar has "
                     f"nothing to score. Never a PASS. [{_bar(3)}]")
        return problems, notes, False
    if truth is None:
        notes.append(f"RANGE ERROR UNMEASURED: no bird ground truth is bound to this flight, so the "
                     f"{DEPTH_RANGE_ERROR_BAR_M:g} m bar on {len(dets)} detection(s) has nothing to "
                     f"compare against. Never a PASS -- pass --truth <applied log>. [{_bar(3)}]")
        return problems, notes, False
    stamps = (log.get("run") or {}).get("tick_stamp_sim_s") or []
    matches: List[dict] = []
    for d in dets:
        tick = d["tick"]
        t = _num(stamps[tick - 1]) if isinstance(tick, int) and 1 <= tick <= len(stamps) else None
        cands = truth.candidates_at(t)
        if not cands:
            continue
        best = None
        for bird_id, answer in cands.items():
            for pos in answer.positions:
                assoc = math.dist(d["position_enu"], pos)
                if best is None or assoc < best["assoc_m"]:
                    best = {"bird_id": bird_id, "assoc_m": assoc,
                            "truth_range_m": math.dist(pos, d["drone_enu"])}
        if best is None:
            continue
        best.update({"tick": tick, "t_sim_s": t, "range_m": d["range_m"],
                     "err_m": abs(d["range_m"] - best["truth_range_m"])})
        matches.append(best)
    if not matches:
        notes.append(
            f"RANGE ERROR UNMEASURED: none of this take's {len(dets)} detection(s) falls inside "
            f"what the truth track {truth.path.name} observed, so no measured range has a true "
            f"range to be compared with. Never a PASS. [{_bar(3)}]")
        return problems, notes, False
    errs = sorted(m["err_m"] for m in matches)
    # Nearest rank, so the printed p95 is an error this flight really made -- and with n < 20 that
    # is the MAX, which is the honest reading of a p95 on a handful of samples rather than a
    # smaller number invented by interpolation.
    p95 = _nearest_rank(errs, 0.95)
    cpa_tick = (report or {}).get("tick")
    at_cpa = (min(matches, key=lambda m: abs(m["tick"] - cpa_tick))
              if isinstance(cpa_tick, int) else None)
    notes.append(
        f"range_estimate_error_m over {len(matches)} of {len(dets)} detection(s) with truth: p95 "
        f"{p95:.4f} m, max {errs[-1]:.4f} m, min {errs[0]:.4f} m (bar "
        f"{DEPTH_RANGE_ERROR_BAR_M:g} m; the segmenter's own scored p95 was 0.1076 m over 63 "
        f"matches). Each detection is associated to the NEAREST truth bird at its own instant -- "
        f"the seam has no tracker, so there is no id to join on -- and the worst association "
        f"distance here is {max(m['assoc_m'] for m in matches):.3f} m. [{_bar(3)}]")
    if at_cpa is not None:
        notes.append(
            f"range_estimate_error_at_cpa_m {at_cpa['err_m']:.4f} m (bar "
            f"{DEPTH_RANGE_ERROR_BAR_M:g} m): detection at tick {at_cpa['tick']} measured "
            f"{at_cpa['range_m']:.3f} m against {at_cpa['truth_range_m']:.3f} m true to "
            f"{at_cpa['bird_id']} (association {at_cpa['assoc_m']:.3f} m), the detection nearest "
            f"the gt-CPA tick {cpa_tick}. GATED -- unlike the monocular estimator, which could "
            f"never be. [{_bar(3)}]")
        if at_cpa["err_m"] > DEPTH_RANGE_ERROR_BAR_M:
            problems.append(
                f"RANGE ERROR OVER BAR AT CPA: {at_cpa['err_m']:.4f} m at tick {at_cpa['tick']} "
                f"(measured {at_cpa['range_m']:.3f} m vs {at_cpa['truth_range_m']:.3f} m true to "
                f"{at_cpa['bird_id']}, association {at_cpa['assoc_m']:.3f} m) against the "
                f"{DEPTH_RANGE_ERROR_BAR_M:g} m bar. This is the range the dodge geometry was "
                f"computed from at the moment that decided the flight. A large association "
                f"distance here means the detection was matched to a bird it is not, which is the "
                f"same finding wearing a different hat: the artifact cannot say what was ranged. "
                f"{_bar(3)}")
    else:
        notes.append(f"range_estimate_error_at_cpa_m UNMEASURED: this flight has no gt-CPA tick to "
                     f"anchor the at-CPA sample to. Never a PASS. [{_bar(3)}]")
    if p95 is not None and p95 > DEPTH_RANGE_ERROR_BAR_M:
        problems.append(
            f"RANGE ERROR OVER BAR: p95 {p95:.4f} m over {len(matches)} matched detection(s) "
            f"exceeds the {DEPTH_RANGE_ERROR_BAR_M:g} m bar -- the statistic the segmenter's score "
            f"was written in (0.1076 m over 63 matches). A depth camera that cannot hold half a "
            f"metre is being read as a measurement when it is an estimate. {_bar(3)}")
    return problems, notes, True


def no_birds_range_error() -> Tuple[List[str], List[str], bool]:
    """P1 bar 3b under `--no-birds` -- the ONE depth bar that needs a bird.

    Bars 1, 2, 3a and 7 read counters and declarations; bars 4, 5 and 6 read the flight's own
    events; only 3b joins to the truth track, so only 3b changes here. It keeps its pre-registered
    quote and its "never a PASS", and it does NOT tell the operator to pass `--truth`: there is no
    applied log to pass, which is the whole reason the flag exists."""
    return [], [f"RANGE ERROR {NA_NO_BIRDS}: no bird was driven on this flight (declared "
                f"--no-birds), so the {DEPTH_RANGE_ERROR_BAR_M:g} m range bar has nothing to "
                f"compare a measured range against. Never a PASS. [{_bar(3)}]"], False


def depth_na_notes(report: Optional[dict], seen: Sequence[int]) -> List[str]:
    """P1 bar 7: every NDVI-family gate prints `N/A (depth take)` IN THOSE WORDS, never PASS.

    Four families, and each one is a real gate above that would otherwise read as green on a
    measurement it never made: the detect-rate floor over `ndvi_msgs_received` (a counter this
    detector does not have), the apparent-size estimator check and its
    `range_estimate_error_at_cpa_m` (there is no ray and no radius prior here -- the depth bar
    replaces it), the nadir-footprint reasoning behind the missed-detection signal (this camera
    looks FORWARD, so the scoping argument is the opposite one), and ADR-003's adopted-detector
    verdict (criterion 3 is about the NDVI-direct detector, which `--detection-source depth`
    DISARMS)."""
    notes = [
        f"NDVI detect-rate floor (frames_detected_on / ndvi_msgs_received): {NA_DEPTH} -- this "
        f"detector has no `ndvi_msgs_received` counter at all; the depth denominator is "
        f"`depth_msgs_received` and it is gated above. {_bar(7)}",
        f"apparent-size estimator check (detection_cpa_m, range_estimate_error_at_cpa_m as the "
        f"monocular ray's error): {NA_DEPTH} -- there is no radius prior and no ray here (ADR-020: "
        f"the sensor MEASURES range), so the number that replaces it is the truth-referenced range "
        f"error, GATED at {DEPTH_RANGE_ERROR_BAR_M:g} m above. {_bar(7)}",
        f"nadir-footprint reasoning (why the missed-detection signal is not gated): {NA_DEPTH} -- "
        f"the NDVI camera looks straight DOWN, so a bird inside the threat cylinder is routinely "
        f"outside its footprint. This aperture looks FORWARD: the equivalent scoping is bar 4's "
        f"frustum, which is gated. {_bar(7)}",
        f"ADR-003 evidence (criterion 3, the adopted NDVI-direct detector): {NA_DEPTH} -- "
        f"`--detection-source depth` DISARMS the NDVI detector, so this flight says nothing about "
        f"the nadir detector's FNR, threshold or comparison arm. One flight, one detection source. "
        f"{_bar(7)}",
    ]
    if report is not None:
        n_cyl = len(report.get("cylinder_ticks") or [])
        hit = len(set(report.get("cylinder_ticks") or []) & set(seen))
        notes.append(
            f"bird truly inside the threat cylinder on {n_cyl} tick(s); the loop engaged on {hit} "
            f"of them (missed-detection signal, NOT gated -- but for the OPPOSITE reason to the "
            f"nadir camera's: a forward aperture can see a bird at cylinder range, and what it "
            f"cannot see is one above or beside it outside the frustum. Bar 4 gates the direction "
            f"that matters: no accepted dodge on a detection the sensor could not have made)")
    return notes


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


# ================================================================================================
# THE BOOKING -- was this take flown at the speed it was AUTHORISED at? (QA finding G128)
# ================================================================================================
# WHY THIS EXISTS. `scripts/predict_forward_lead.py` writes `eval/results/booking_gate_<UTC>.json`,
# and the committed 2026-09-07 one says PASS and BOOKABLE at **5.0 m/s**. Nothing in the repo made
# the vehicle fly at 5.0: until 2026-09-07 no waypoint-speed parameter was set anywhere in this
# repo, so ArduCopter's ~10 m/s default flew every mission -- the 2026-09-06 scripted test-flight
# peaked at 10.576 m/s, a speed at which that same booking gate exits 1 (margin 1.216x against a
# 1.30x bar). `fly_pipeline.sh --booking` now injects the speed into the fly recipe, but only when
# it is given one, and nothing it does can be verified from the recipe: the vehicle is what has to
# have flown it. A dodge take flown faster than it was booked is NOT the authorised take, and until
# this gate existed the evidence gate could not tell the difference -- it printed a GT-CPA and a
# green verdict either way.
#
# The flown speed is computed from the LOG'S OWN POSES -- the same `flown_path_enu` +
# `run.tick_stamp_sim_s` pair the GT-CPA join already walks -- so it needs no new instrumentation,
# no new field on the node, and it cannot be written by whatever was supposed to set the parameter.
#
# TWO GATED STATISTICS, ONE BAR. `WP_SPD` (the waypoint speed at ADR-004's pinned SHA -- in m/s;
# `WPNAV_SPEED` is retired there) is a CAP, not a setpoint, so the gated number is a MEDIAN in both
# cases and p90/max ride along as context:
#   * the WHOLE-FLIGHT median -- the speed the mission was flown at; catches the headline failure,
#     an unbooked take at ArduCopter's 10 m/s default against a 5.0 m/s booking;
#   * each ENCOUNTER-WINDOW median (`encounter_windows`) -- the speed the vehicle was doing WHEN it
#     met a bird, which is where the booking's lead margin is actually spent. Added 2026-09-07 after
#     QA finding G138 measured that the whole-flight median CANNOT see the failure it exists for: on
#     the 2026-08-25 take it reads 3.417 m/s (0.68x a 5.0 booking, a comfortable pass) while the
#     encounter itself ran at a median 9.012 m/s = 1.80x booked, a speed at which the booking gate
#     exits 1. That flip -- whole flight passes, encounter fails -- is regression-pinned.
# THE TOLERANCE IS 1.10: far tighter than the failure this exists to catch (a 2x default-vs-booked
# gap) and far looser than a leg-entry transient or the sampling noise of a 5 Hz numerical
# derivative. A booking flown at 5.0 admits a 5.5 m/s median; the unbooked default is 10.
BOOKED_SPEED_TOLERANCE = 1.10
# Altitude above which a tick counts as AIRBORNE: `fieldguard_planning.geom.AIRBORNE_Z_M`, imported
# at the top of this file. It used to be restated here (and in `clip_recorder`, and in
# `build_dashboard_data`) because `clip_recorder` imports numpy and this gate is stdlib-only by
# contract; `geom.py` is the stdlib-only home that ends the restating.
#
# WHY THE PROLOGUE HAS TO COME OUT AT ALL: every committed flight log opens with a long stretch of a
# parked vehicle -- 40-52 % of the ticks on two of the three -- because the node starts logging at
# bringup and the human arms and takes off at the MAVProxy prompt some seconds later (ADR-013).
# A median over ALL ticks on those logs is ~0 m/s, i.e. every flight would clear every booking.
# The sidecar: `<log-stem>.booking.json` beside the flight log, resolved exactly the way
# `marker_path_for` resolves the SAFETY_FINDING marker. `--booking` is the contract and this is the
# convenience -- a copy of the authorising artifact, laid down beside the evidence by whoever
# assembles the take. Named off the LOG'S STEM rather than its own UTC stamp because the stem is the
# only join key that exists between a flight and its sidecars, and because `with_name(stem + suffix)`
# survives the log being copied into a tmp tree with its siblings, which CI's evidence step does.
BOOKING_SUFFIX = ".booking.json"


def booking_path_for(log_path: Path) -> Path:
    """`<...>/live_flight_log_X.json` -> `<...>/live_flight_log_X.booking.json`."""
    return Path(log_path).with_name(Path(log_path).stem + BOOKING_SUFFIX)


def _nearest_rank(values: Sequence[float], q: float) -> float:
    """The q-quantile by NEAREST RANK -- an actual observed sample, never an interpolation between
    two. `values` must be sorted and non-empty. Interpolating would invent a speed the vehicle never
    flew, which is the wrong thing to print beside a measured median."""
    k = max(1, math.ceil(q * len(values)))
    return values[min(k, len(values)) - 1]


def airborne_ground_speed(flown_path: Sequence, tick_stamps: Sequence,
                          tick_range: Optional[Tuple[int, int]] = None) -> dict:
    """How fast this flight actually flew, from its own telemetry: HORIZONTAL ground speed over the
    airborne steps, as {median, p90, max} plus every denominator.

    HORIZONTAL, because that is what the waypoint speed parameter caps and what a booking's
    `mission_speed_mps` means; a climb is not mission speed. Per consecutive tick pair, both ends
    must have a usable position, a usable stamp, a positive sim-time step, and BOTH ends above
    `AIRBORNE_Z_M` -- a step that starts or ends parked is not flight, and one that straddles the
    takeoff would divide a real displacement by a real time and report a speed nobody flew.

    A per-STEP predicate rather than a contiguous window (the shape `build_dashboard_data`'s replay
    trim needs): a take with two airborne runs -- an aborted first attempt, a touch-and-go -- has a
    parked gap in the middle, and a window spanning it would fold zero-speed samples into the median
    in the OPTIMISTIC direction.

    `tick_range` is an INCLUSIVE 1-based (first, last) tick bound -- a step counts only when BOTH of
    its ticks are inside it. That is what makes ONE function serve both gated statistics: the whole
    flight (no range) and one encounter window (`encounter_windows`). `flown_path_enu[tick - 1]` is
    that tick's position by construction -- the executor records exactly one position per `step()`.

    Sim seconds throughout: `run.tick_stamp_sim_s` is the vehicle's own clock, and `gate_clock`
    already refuses a frozen or backwards one. Returns `median_mps` None when nothing was scoreable
    -- 'we could not measure it' is not 'it flew slowly'."""
    pts: List[Optional[Tuple[float, float, float]]] = []
    for point in flown_path or []:
        try:
            pts.append((float(point[0]), float(point[1]), float(point[2])))
        except (TypeError, ValueError, IndexError):
            pts.append(None)
    stamps: List[Optional[float]] = [_num(tick_stamps[i]) if i < len(tick_stamps) else None
                                     for i in range(len(pts))]
    airborne = [p is not None and p[2] > AIRBORNE_Z_M for p in pts]
    lo_tick, hi_tick = tick_range if tick_range is not None else (1, len(pts))
    window = [i for i in range(len(pts)) if lo_tick <= i + 1 <= hi_tick]
    speeds: List[float] = []
    span_s = 0.0
    for i in range(len(pts) - 1):
        if not (lo_tick <= i + 1 and i + 2 <= hi_tick):
            continue                       # a step half outside the window is not in the window
        a, b = pts[i], pts[i + 1]
        ta, tb = stamps[i], stamps[i + 1]
        if a is None or b is None or ta is None or tb is None:
            continue
        if not (airborne[i] and airborne[i + 1]):
            continue
        dt = tb - ta
        if dt <= 0.0:
            continue                       # a frozen or backwards pair measures no speed at all
        speeds.append(math.hypot(b[0] - a[0], b[1] - a[1]) / dt)
        span_s += dt
    speeds.sort()
    return {
        "tick_range": None if tick_range is None else [lo_tick, hi_tick],
        "ticks_total": len(window),
        "airborne_ticks": sum(1 for i in window if airborne[i]),
        "steps_scored": len(speeds),
        "steps_total": max(0, len(window) - 1),
        "airborne_span_s": round(span_s, 3) if speeds else None,
        "median_mps": statistics.median(speeds) if speeds else None,
        "p90_mps": _nearest_rank(speeds, 0.90) if speeds else None,
        "max_mps": speeds[-1] if speeds else None,
        "z_threshold_m": AIRBORNE_Z_M,
        "rule": (f"horizontal |dp|/dt over consecutive ticks with BOTH ends above "
                 f"{AIRBORNE_Z_M} m and a positive sim-time step; p90 by nearest rank (a real "
                 f"sample, not an interpolation)"),
    }


def encounter_windows(log, n_ticks: int) -> List[Tuple[int, int, str]]:
    """The tick spans the EXECUTOR ITSELF delimited: (first_tick, last_tick, label) per
    takeover -> resume pair, inclusive, 1-based.

    No +/-N padding around anything. A window nobody logged is a window somebody chose, and the
    number this feeds is gated -- so the bound has to come out of the flight rather than out of a
    tuning constant. `gate_encounter_closure` pairs the same two event kinds for its unclosed-
    encounter check; this pairs them positionally so each window has an end.

    A second `takeover` before a `resume` does NOT open a second window (the executor re-latches
    inside an encounter that never closed): the window runs from the FIRST takeover to the resume
    that closes it. An UNCLOSED trailing takeover runs to the last tick of the flight -- that log is
    already INVALID for the unclosed encounter, and the speed it flew into the dodge is still the
    honest thing to measure."""
    evs: List[Tuple[int, str]] = []
    for ev in log.get("events") or []:
        if isinstance(ev, dict) and ev.get("kind") in ("takeover", "resume"):
            tick = ev.get("tick")
            if isinstance(tick, int) and not isinstance(tick, bool):
                evs.append((tick, ev["kind"]))
    # A takeover and a resume stamped on the SAME tick: the takeover opens first, or the pair would
    # be read as a resume with nothing open followed by an encounter that never ends.
    evs.sort(key=lambda pair: (pair[0], pair[1] != "takeover"))
    out: List[Tuple[int, int, str]] = []
    opened: Optional[int] = None
    for tick, kind in evs:
        if kind == "takeover":
            if opened is None:
                opened = tick
        elif opened is not None:
            out.append((opened, tick, f"takeover {opened} -> resume {tick}"))
            opened = None
    if opened is not None:
        out.append((opened, max(opened, n_ticks),
                    f"takeover {opened} -> UNCLOSED (to last tick {n_ticks})"))
    return out

# ------------------------------------------------------------------------------------------------
# ACHIEVED DISPLACEMENT -- REPORTED, NEVER GATED (G1/G2, 2026-09-10)
# ------------------------------------------------------------------------------------------------
# WHAT THIS IS. `maneuver.verdict` is the string "accepted", written by the executor on the tick it
# PUBLISHES a setpoint (`avoidance_executor.py`); nothing anywhere reads back whether the vehicle
# accepted the mode switch, and no gate compares what was commanded with what the aircraft did. So
# the flight log's own answer to "did the dodge move the aircraft" has always been a constant. These
# notes put the measurement in the artifact every flight prints.
#
# WHY IT IS A NOTE AND NOT A BAR. The offline point-mass replay measured exactly this on all three
# committed flights (`eval/replay_point_mass.py`, 2026-08-26, ADR-016 am. 2) and found the naive
# reading is wrong-axis: on 2 of 3 flights the along-command figure is NEGATIVE (the vehicle went the
# other way), and on the third the window is 0.434 s -- so short that a working command path and a
# dead one differ by half a telemetry quantum. A bar over a number that cannot discriminate would be
# a gate that passes for the wrong reason. Sizing one is R4/B-track work; measuring it is not, and
# an unmeasured number is how the 0.018 m dodge survived a green gate for a fortnight.
#
# THE DECOMPOSITION IS THE POINT (the replay's M6 finding, reproduced here so the two agree). The
# displacement projected on the commanded direction splits EXACTLY into two orthogonal terms:
#     d . cmd = (d . track)(track . cmd) + (d . cross)(cross . cmd)
# The second is the dodge. The first is ORDINARY FORWARD FLIGHT leaking in through the small angle
# between the commanded direction and the track normal. On 2026-08-25: +0.0541 m along command is
# +0.0182 m of real cross-course dodge plus +0.0359 m of the 3.95 m cruise leg seen through 0.52
# deg. Two thirds of the headline is forward flight, so the along-command figure is never quoted
# alone -- and the raw delta-ENU is printed beside both, because that vector is the fact and every
# projection of it is a reading.
DISPLACEMENT_SETTLE_S = 2.0


def _entry_course_unit(log, tick, max_back: int = 5) -> Optional[Tuple[float, float]]:
    """The vehicle's horizontal course ARRIVING at `tick`, as a unit (E, N), or None.

    STRICTLY BEFORE the tick, unlike `_course_unit` (which straddles it): that one answers "where
    was the camera pointing AT this instant" and wants the widest bracket; this one answers "what
    was the vehicle doing when authority changed hands", and a bracket that reaches forward would
    mix the maneuver's own response into the baseline the response is measured against. Walks back
    up to `max_back` ticks so a repeated pose (a parked or hovering vehicle, which the telemetry
    produces by the hundred) yields the last real motion instead of a zero vector."""
    here = _flown_point(log, tick)
    if here is None:
        return None
    for back in range(1, max_back + 1):
        prev = _flown_point(log, tick - back)
        if prev is None:
            continue
        de, dn = here[0] - prev[0], here[1] - prev[1]
        norm = math.hypot(de, dn)
        if norm > 1e-9:
            return (de / norm, dn / norm)
    return None


def commanded_dodge(log, first_tick: int, last_tick: int
                    ) -> Optional[Tuple[int, str, Tuple[float, float, float]]]:
    """(tick, what named it, setpoint_enu) -- the dodge point the executor commanded when it took
    authority in this window, or None if the window carries no setpoint at all.

    The EARLIEST setpoint in the window, because displacement is measured from the position at
    takeover and the only command in force there is the one latched then. A `latch` wins a tie with
    a `maneuver` on the same tick (the latch is the point actually re-commanded until it clears);
    the 2026-08-18 log predates latch events entirely, so the accepted `maneuver` is the fallback.
    Re-latches later in the window are reported as a count, not folded in: a displacement measured
    against a command that changed mid-window is not a measurement of either command."""
    best: Optional[Tuple[Tuple[int, int], int, str, Tuple[float, float, float]]] = None
    for ev in log.get("events") or []:
        if not isinstance(ev, dict):
            continue
        kind = ev.get("kind")
        if kind not in ("latch", "maneuver"):
            continue
        if kind == "maneuver" and ev.get("verdict") not in (None, "accepted"):
            continue
        tick = ev.get("tick")
        if not isinstance(tick, int) or isinstance(tick, bool):
            continue
        if not (first_tick <= tick <= last_tick):
            continue
        sp = ev.get("setpoint_enu")
        try:
            point = (float(sp[0]), float(sp[1]), float(sp[2]))
        except (TypeError, ValueError, IndexError):
            continue
        key = (tick, 0 if kind == "latch" else 1)
        if best is None or key < best[0]:
            best = (key, tick, kind, point)
    return None if best is None else (best[1], best[2], best[3])


def _displacement_split(p0: Tuple[float, float, float], p1: Tuple[float, float, float],
                        cmd_unit: Tuple[float, float],
                        course: Optional[Tuple[float, float]]) -> dict:
    """The one arithmetic both note blocks use: the raw delta, its 3D length, its projection on the
    commanded axis, and (when a course exists) that projection's dodge/cruise-leak split."""
    d = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    out = {"d": d,
           "d3": math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]),
           "along": d[0] * cmd_unit[0] + d[1] * cmd_unit[1],
           "cross": None, "leak": None, "misalign_deg": None}
    if course is None:
        return out
    cross = (-course[1], course[0])
    if cross[0] * cmd_unit[0] + cross[1] * cmd_unit[1] < 0.0:
        cross = (-cross[0], -cross[1])              # point it the way the command went
    d_track = d[0] * course[0] + d[1] * course[1]
    d_cross = d[0] * cross[0] + d[1] * cross[1]
    out["cross"] = d_cross * (cross[0] * cmd_unit[0] + cross[1] * cmd_unit[1])
    out["leak"] = d_track * (course[0] * cmd_unit[0] + course[1] * cmd_unit[1])
    out["track"] = d_track
    out["misalign_deg"] = math.degrees(math.acos(max(-1.0, min(1.0, abs(
        cross[0] * cmd_unit[0] + cross[1] * cmd_unit[1])))))
    return out


def displacement_notes(log) -> List[str]:
    """One block per takeover -> resume window: what was commanded, what the aircraft did, on which
    ticks. REPORTED, NEVER GATED -- nothing here can change a verdict or an exit code.

    A legacy (pre-`run`) log has no time axis at all, so its seconds and its +2 s figures read
    `n/a`: the same refusal `check_file` already makes for a booking's flown speed. The tick
    displacements are still facts and are still printed."""
    path = log.get("flown_path_enu") if isinstance(log, dict) else None
    if not isinstance(path, list) or not path:
        return []
    windows = encounter_windows(log, len(path))
    if not windows:
        return []
    run = log.get("run")
    stamps = run.get("tick_stamp_sim_s") if isinstance(run, dict) else None
    if not isinstance(stamps, list):
        stamps = []

    def stamp(tick) -> Optional[float]:
        if isinstance(tick, int) and 1 <= tick <= len(stamps):
            return _num(stamps[tick - 1])
        return None

    notes: List[str] = []
    for n, (t0, t1, _label) in enumerate(windows, 1):
        p0, p1 = _flown_point(log, t0), _flown_point(log, t1)
        s0, s1 = stamp(t0), stamp(t1)
        span = "n/a (no `run` block: this log has no time axis)" if None in (s0, s1) else \
            f"{s1 - s0:.3f} s sim ({s0:.3f} -> {s1:.3f} s)"
        head = (f"achieved displacement, encounter {n} [REPORTED, NOT GATED -- no bar is applied to "
                f"this number, and `maneuver.verdict` is a constant, not a readback]: GUIDED "
                f"authority ticks {t0} -> {t1} (takeover -> resume), {t1 - t0} tick step(s), {span}")
        cmd = commanded_dodge(log, t0, t1)
        if p0 is None or p1 is None or cmd is None:
            notes.append(head + " -- NOT MEASURED: the window carries no commanded setpoint or no "
                                "position at its ends, so there is nothing to compare")
            continue
        cmd_tick, cmd_kind, sp = cmd
        vec = (sp[0] - p0[0], sp[1] - p0[1], sp[2] - p0[2])
        horiz = math.hypot(vec[0], vec[1])
        if horiz <= 1e-9:
            notes.append(head + " -- NOT MEASURED: the commanded point is directly above/below the "
                                "position at takeover, so it defines no horizontal axis")
            continue
        cmd_unit = (vec[0] / horiz, vec[1] / horiz)
        course = _entry_course_unit(log, t0)
        n_relatch = sum(1 for ev in log.get("events") or []
                        if isinstance(ev, dict) and ev.get("kind") == "relatch"
                        and isinstance(ev.get("tick"), int) and t0 <= ev["tick"] <= t1)
        notes.append(head)
        notes.append(
            f"  commanded {horiz:.4f} m (3D {math.sqrt(sum(v * v for v in vec)):.4f} m) from the "
            f"tick-{cmd_tick} {cmd_kind}: setpoint ({sp[0]:.4f}, {sp[1]:.4f}, {sp[2]:.4f}) minus "
            f"the tick-{t0} position ({p0[0]:.4f}, {p0[1]:.4f}, {p0[2]:.4f}); commanded axis "
            f"(E {cmd_unit[0]:+.4f}, N {cmd_unit[1]:+.4f}); {n_relatch} re-latch(es) inside the "
            f"window (the axis is the command in force at takeover, not a later one)")
        win = _displacement_split(p0, p1, cmd_unit, course)
        notes.append(f"  achieved ON THE COMMANDED AXIS {win['along']:+.4f} m over ticks {t0} -> "
                     f"{t1} = {100.0 * win['along'] / horiz:.2f} % of the {horiz:.4f} m commanded"
                     + (" [no entry course: the vehicle was not moving before takeover, so the "
                        "dodge/cruise split cannot be taken]" if win["cross"] is None else
                        f", of which cross-course dodge {win['cross']:+.4f} m and cruise leak "
                        f"{win['leak']:+.4f} m ({win['track']:+.4f} m of ordinary forward flight "
                        f"seen through {win['misalign_deg']:.2f} deg between the commanded axis and "
                        f"the track normal) -- the along-command figure is NOT a dodge measurement"))
        notes.append(f"  achieved 3D straight line {win['d3']:.4f} m over the same ticks; raw "
                     f"delta-ENU ({win['d'][0]:+.4f}, {win['d'][1]:+.4f}, {win['d'][2]:+.4f}) m "
                     f"-- the vector is the fact, every projection above is a reading of it")
        t2, s2 = _settle_tick(stamps, t1, len(path))
        if t2 is None or s0 is None:
            notes.append(f"  +{DISPLACEMENT_SETTLE_S:.1f} s past resume: n/a -- no tick stamps, so "
                         f"this log cannot say which tick is 2 seconds later")
        else:
            settle = _displacement_split(p0, _flown_point(log, t2) or p0, cmd_unit, course)
            notes.append(
                f"  +{DISPLACEMENT_SETTLE_S:.1f} s past resume (ticks {t0} -> {t2}, "
                f"{s2 - s0:.3f} s from takeover, AUTO for the tail): on the commanded axis "
                f"{settle['along']:+.4f} m"
                + ("" if settle["cross"] is None else
                   f" (cross-course {settle['cross']:+.4f} m)")
                + f", 3D straight line {settle['d3']:.4f} m")
        notes.append(
            f"  course axis from the last telemetry secant strictly before takeover, so the entry "
            f"course carries none of the maneuver's own response; the split is ill-conditioned when "
            f"the two axes are near-parallel, which is why the raw vector is printed with it")
    return notes


def _settle_tick(stamps: Sequence, resume_tick: int, n_ticks: int
                 ) -> Tuple[Optional[int], Optional[float]]:
    """(the last tick whose stamp is within DISPLACEMENT_SETTLE_S of the resume tick's, its stamp).
    The vehicle is back in AUTO over that tail -- the point is how much of the shortfall is window
    LENGTH rather than a dead command path, which is the same counterfactual the point-mass replay
    prices with its SETTLE_S."""
    if not isinstance(resume_tick, int) or not (1 <= resume_tick <= len(stamps)):
        return None, None
    s1 = _num(stamps[resume_tick - 1])
    if s1 is None:
        return None, None
    best_tick, best_stamp = resume_tick, s1
    for tick in range(resume_tick + 1, min(len(stamps), n_ticks) + 1):
        s = _num(stamps[tick - 1])
        if s is None or s > s1 + DISPLACEMENT_SETTLE_S:
            break
        best_tick, best_stamp = tick, s
    return best_tick, best_stamp



def load_booking(path: Path) -> Tuple[Optional[dict], Optional[str]]:
    """(booking-gate artifact, problem). None + a reason unless `path` is a report that AUTHORISES a
    flight at one speed.

    Validated by `predict_forward_lead.validate_report` -- the SAME function the tool runs before it
    writes the file -- rather than by a second opinion here. Imported lazily because
    `predict_forward_lead` imports `max_bird_speed_m_s` from this module at import time; by the time
    anything calls this, this module is fully loaded, so the cycle cannot bite in either order.

    Three separate refusals, because they mean different things:
      * unreadable / malformed  -> the artifact is not evidence of anything;
      * `bookable` false        -> a SWEEP, or a config-sourced exit-3 design check. Those authorise
        NOTHING by construction (the tool's whole docstring is about that), so binding one to a
        flight is a claim of authorisation that never existed;
      * no `encounter.mission_speed_mps` -> nothing to compare the flight against."""
    path = Path(path)
    if not path.exists():
        return None, (f"--booking {path} does not exist. A booking that cannot be read cannot "
                      f"authorise a flight.")
    try:
        rep = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        return None, f"booking {path.name} is unreadable / not valid JSON: {e}"
    # The LAUNCHER'S RECORD IS A POINTER, NOT AN AUTHORISATION. `fly_pipeline.sh --booking` writes
    # `eval/results/live_flight_booking_<UTC>.json` at bringup ({"kind": "live_flight_booking"}) --
    # the artifact's path, the booked speed and the recipe line it injected. It is stamped with the
    # BRINGUP time, sits beside the flight logs, and is the obvious thing to reach for on flight
    # day. It carries none of the gate's checks, so reading it as an authorisation would let a
    # two-field JSON book a flight. Refused BY NAME, pointing at the file it names, because
    # `validate_report`'s "missing top-level key(s)" is a dead end at the MAVProxy prompt.
    if isinstance(rep, dict) and rep.get("kind") == "live_flight_booking":
        named = ((rep.get("booking") or {}).get("path") if isinstance(rep.get("booking"), dict)
                 else None)
        return None, (
            f"{path.name} is the LAUNCHER'S bringup record (kind 'live_flight_booking'), not a "
            f"booking-gate artifact: it says which speed the fly recipe booked, and carries none "
            f"of the checks that authorised it. Pass the artifact it names instead"
            + (f": --booking {named}" if named else " (its `booking.path` field)")
            + ". Reading this file as an authorisation would let a two-field JSON book a flight.")
    try:
        from predict_forward_lead import validate_report      # noqa: E402  (see the docstring)
        validate_report(rep)
    except (ImportError, ValueError) as e:
        return None, (f"booking {path.name} is not a well-formed booking-gate artifact: {e}. It is "
                      f"read with `predict_forward_lead.validate_report`, the same function the "
                      f"tool runs before it writes one.")
    verdict = rep.get("verdict") or {}
    if not verdict.get("bookable"):
        return None, (f"booking {path.name} does not AUTHORISE anything: verdict.bookable is "
                      f"{verdict.get('bookable')!r} (exit code {verdict.get('exit_code')!r}, "
                      f"{verdict.get('why_not_bookable')!r}). A --sweep chooses a mission speed and "
                      f"a config-sourced run is a design check; only a single --speed run on the "
                      f"full live input set books a flight (FORWARD_DEPTH_SENSOR.md gate D4). "
                      f"Binding this file to a take claims an authorisation that was never issued.")
    speed = _num((rep.get("encounter") or {}).get("mission_speed_mps"))
    if speed is None or speed <= 0.0:
        return None, (f"booking {path.name} carries no usable encounter.mission_speed_mps (got "
                      f"{(rep.get('encounter') or {}).get('mission_speed_mps')!r}) -- there is no "
                      f"speed to hold the flight to.")
    return rep, None


def gate_booked_speed(log, run, log_path: Path,
                      booking_arg: Optional[Path] = None) -> Tuple[List[str], List[str]]:
    """Assertion G128: this take was flown at the speed it was AUTHORISED at.

    Optional by design, and asymmetrically so. The NDVI survey needs no booking -- it carries no
    dodge and nothing about it is authorised by the forward-sensor gate -- so a log with no booking
    is not a failure. But an AVOIDANCE take (a log whose `run.detector` names a detector, the same
    criterion `check_schema2` branches on) with no booking gets a WARNING saying in those words that
    its authorisation cannot be verified: silence would read as verified.

    With a booking present the flown median is a HARD gate. Failing it means the flight in front of
    you is not the flight that was booked, which is not a CPA finding and is therefore not something
    a SAFETY_FINDING marker can acknowledge -- it lands in `problems`, i.e. INVALID.

    `depth_blob` IS an avoidance take here, even though `check_schema2` refuses to SCORE one
    (DETECTOR_SOURCES). Authorisation and scoring are different questions and this gate answers the
    first: the forward depth aperture is the sensor the ADR-019/020 booking gate was built to
    authorise in the first place, so exempting it would tell the one take that needs a booking that
    it needs none -- and the exemption would turn from a false LINE into a false PASS on the day a
    reviewed diff adds `depth_blob` to DETECTOR_SOURCES (QA, 2026-09-07; the same family as G137
    "printed, not gated" and G138 "the procedure never binds one")."""
    problems: List[str] = []
    notes: List[str] = []
    detector = run.get("detector") if isinstance(run, dict) else None
    source = detector.get("source") if isinstance(detector, dict) else None
    is_avoidance = source in (DET_NDVI_BLOB, DET_DEMO_VIRTUAL, DET_DEPTH_BLOB)

    sidecar = booking_path_for(log_path)
    chosen = Path(booking_arg) if booking_arg is not None else (sidecar if sidecar.exists()
                                                                else None)
    if chosen is None:
        notes.append(
            (f"NO BOOKING BOUND -- WARNING: this is an AVOIDANCE take (detector source {source!r}) "
             f"and nothing here can verify it was flown at the speed the ADR-019 booking gate "
             f"authorised. The fly recipe only carries a `param set WP_SPD` line when the launcher "
             f"was given `--booking`; without one ArduCopter's 10 m/s default flies the mission, and "
             f"the committed booking is for 5.0 m/s -- a speed at which that gate exits 1. Pass "
             f"--booking eval/results/booking_gate_<UTC>.json (or drop a copy at {sidecar.name} "
             f"beside the log). Flown speed measured anyway, below, so the number exists either way."
             if is_avoidance else
             f"no booking bound (detector source {source!r} -- not an avoidance take; the NDVI "
             f"survey is not authorised by the forward-sensor booking gate and needs none)"))

    rep: Optional[dict] = None
    if chosen is not None:
        rep, problem = load_booking(chosen)
        if problem is not None:
            problems.append(problem)
        # TWO BOOKINGS FOR ONE TAKE is the `AMBIGUOUS TAKE` shape this file already refuses for
        # truth tracks: a flag that quietly overrides a sidecar lets the strictest authorisation on
        # disk be the one nobody reads. They may both be present; they may not disagree.
        if booking_arg is not None and sidecar.exists() and sidecar.resolve() != chosen.resolve():
            other, other_problem = load_booking(sidecar)
            here = None if rep is None else _num((rep.get("encounter") or {}).get(
                "mission_speed_mps"))
            there = None if other is None else _num((other.get("encounter") or {}).get(
                "mission_speed_mps"))
            if other_problem is not None or here != there:
                problems.append(
                    f"TWO BOOKINGS FOR ONE TAKE: --booking {Path(chosen).name} was given and "
                    f"{sidecar.name} also sits beside the log, and they do not agree "
                    f"({here!r} m/s vs {there!r} m/s"
                    + (f"; the sidecar is also unusable: {other_problem}" if other_problem else "")
                    + "). One take has ONE authorisation. Remove the one that does not belong to "
                      "this flight rather than letting the command line pick.")

    path_enu = log.get("flown_path_enu") or []
    stamps = (run.get("tick_stamp_sim_s") or []) if isinstance(run, dict) else []
    speed = airborne_ground_speed(path_enu, stamps)
    flown = speed["median_mps"]

    def denom_of(stat) -> str:
        return (f"{stat['steps_scored']} of {stat['steps_total']} tick step(s) scored, "
                f"{stat['airborne_ticks']}/{stat['ticks_total']} ticks airborne above "
                f"{stat['z_threshold_m']:g} m, {_fmt(stat['airborne_span_s'], 3)} s of sim time")

    denom = denom_of(speed)
    if flown is None:
        line = (f"flown_ground_speed_mps NOT MEASURABLE ({denom}) -- no airborne tick pair carried "
                f"two positions, two stamps and a positive sim step")
        (problems if rep is not None else notes).append(
            line + (". A booking is bound to this log and nothing here can check it was honoured: "
                    "an unverifiable authorisation is not a verified one." if rep is not None
                    else ""))
        return problems, notes

    line = (f"flown_ground_speed_mps median {flown:.3f} p90 {speed['p90_mps']:.3f} max "
            f"{speed['max_mps']:.3f} ({denom})")

    # THE SECOND GATED STATISTIC, and the one the failure actually lives in (QA finding G138).
    # The whole-flight median is a MISSION statistic: on a boustrophedon most ticks are turnarounds
    # and accel/decel, so the 2026-08-25 take reads median 3.417 m/s -- 0.68x a 5.0 m/s booking,
    # PASSING with 32 % to spare -- while its one encounter (takeover 991 -> resume 995) was flown
    # at a median 9.012 m/s, i.e. 1.80x booked. Re-running the booking gate at that speed FAILS it.
    # So a take whose encounter the booking gate would refuse was being certified as flown at the
    # booking. The lead margin is spent at the speed flown WHEN the bird appears, not at the mission
    # median, and that is exactly what an encounter window measures.
    windows = encounter_windows(log, len(path_enu))
    window_stats = [(label, airborne_ground_speed(path_enu, stamps, (lo, hi)))
                    for lo, hi, label in windows]
    scoreable = [(label, s) for label, s in window_stats if s["median_mps"] is not None]

    if rep is None:
        notes.append(line + (" -- no booking bound, so this is context, not a check"
                             if chosen is None else
                             f" -- the bound booking ({Path(chosen).name}) is unusable (the problem "
                             f"is above), so this is context, not a check"))
        if scoreable:
            notes.append(
                "...and the ENCOUNTER window(s), which is where a booking's lead margin is spent: "
                + "; ".join(f"{label} median {s['median_mps']:.3f} m/s ({s['steps_scored']} step(s))"
                            for label, s in scoreable)
                + ". CONTEXT here -- with no booking there is nothing to hold it to.")
        return problems, notes

    booked = float(rep["encounter"]["mission_speed_mps"])
    ratio = flown / booked
    bar = booked * BOOKED_SPEED_TOLERANCE
    notes.append(
        f"booking {Path(chosen).name}: booked_speed_mps {booked:.3f} | {line} | ratio "
        f"{ratio:.3f} (bar {BOOKED_SPEED_TOLERANCE:.2f}x = {bar:.3f} m/s, applied to the MEDIAN of "
        f"the whole flight AND to the median of each encounter window; p90 and max are context -- "
        f"the waypoint speed is a cap and transients cross it)")
    # THE TAIL, NAMED RATHER THAN LEFT TO THE READER. Still not gated: a p90 on a mission with
    # turnarounds is mission geometry, not a violated cap, and gating it would fail honest takes.
    # It is what pointed at the encounter-window gate above, so it stays printed.
    over = [name for name, v in (("p90", speed["p90_mps"]), ("max", speed["max_mps"])) if v > bar]
    if over:
        notes.append(
            f"...and the TAIL of that distribution is above the bar: "
            + ", ".join(f"{n} {speed[n + '_mps']:.3f} m/s = "
                        f"{speed[n + '_mps'] / booked:.3f}x booked" for n in over)
            + f". NOT GATED (the medians are), and said out loud because a mission median hides the "
              f"speed the vehicle was doing when a bird appeared. The encounter windows below are "
              f"the gated version of this concern.")
    if flown > bar:
        problems.append(
            f"FLOWN FASTER THAN BOOKED: median airborne ground speed {flown:.3f} m/s against a "
            f"booking for {booked:.3f} m/s ({Path(chosen).name}) = {ratio:.3f}x, past the "
            f"{BOOKED_SPEED_TOLERANCE:.2f}x tolerance ({bar:.3f} m/s). THIS IS NOT THE AUTHORISED "
            f"TAKE. The booking gate's lead margin is computed at the booked speed and falls with "
            f"it -- re-run scripts/predict_forward_lead.py at {flown:.3f} m/s before quoting any "
            f"separation number from this flight; the 2026-09-07 booking exits 1 by ~10 m/s. The "
            f"cause is almost always that the launcher was not given `--booking`, so no waypoint "
            f"speed was set and ArduCopter's 10 m/s default flew the mission (see "
            f"docs/runbooks/AVOIDANCE_REAL_DETECTION.md section 0g).")

    if not windows:
        notes.append("no encounter window on this take (no takeover event), so the whole-flight "
                     "median is the only booked-speed statistic there is to check")
        return problems, notes
    # EVERY window is owed a verdict, not just the ones that happened to be scoreable: a booking
    # bound to an encounter nobody can measure is an authorisation nobody can verify, which is the
    # same rule the whole-flight NOT MEASURABLE case above already follows. Reported for the subset,
    # so a take with one good window and one dead one loses neither half.
    unscoreable = [(label, s) for label, s in window_stats if s["median_mps"] is None]
    if unscoreable:
        problems.append(
            f"ENCOUNTER SPEED NOT MEASURABLE on {len(unscoreable)} of {len(windows)} encounter "
            f"window(s) ("
            + "; ".join(f"{label}, {denom_of(s)}" for label, s in unscoreable)
            + f"): no airborne tick step there carried two positions, two stamps and a positive sim "
              f"step, so the speed the vehicle was flying WHEN it met a bird -- the speed the "
              f"{booked:.3f} m/s booking's lead margin is computed at -- cannot be checked. An "
              f"unverifiable authorisation is not a verified one.")
    if not scoreable:
        return problems, notes

    notes.append(
        f"ENCOUNTER window speed (GATED, same {BOOKED_SPEED_TOLERANCE:.2f}x bar = {bar:.3f} m/s): "
        + "; ".join(f"{label} median {s['median_mps']:.3f} m/s = {s['median_mps'] / booked:.3f}x "
                    f"booked ({denom_of(s)})" for label, s in scoreable)
        + ". This is the speed the booking's lead margin is actually spent at.")
    for label, s in scoreable:
        if s["median_mps"] > bar:
            problems.append(
                f"ENCOUNTER FLOWN FASTER THAN BOOKED: {label} was flown at a median "
                f"{s['median_mps']:.3f} m/s against a booking for {booked:.3f} m/s "
                f"({Path(chosen).name}) = {s['median_mps'] / booked:.3f}x, past the "
                f"{BOOKED_SPEED_TOLERANCE:.2f}x tolerance ({bar:.3f} m/s) -- while the whole-flight "
                f"median is {flown:.3f} m/s ({ratio:.3f}x). THIS IS NOT THE AUTHORISED TAKE: the "
                f"booking authorises a lead time computed at {booked:.3f} m/s of closing speed, and "
                f"the vehicle spent the encounter at {s['median_mps'] / booked:.3f}x that. Re-run "
                f"scripts/predict_forward_lead.py --speed {s['median_mps']:.3f} before quoting any "
                f"separation number from this encounter.")
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


def resolve_truth(log_path: Path, run, truth_arg: Optional[Path] = None,
                  results_dir: Path = RESULTS_DIR) -> Tuple[Optional[TruthTrack], List[str]]:
    """(TruthTrack, problems) for the flight log at `log_path`. Every failure here is a HARD problem,
    never a skip: a flight flown with the real detector and no bird ground truth has measured nothing
    about separation, and "we could not tell" must not score green.

    TWO WAYS A FLIGHT REACHES ITS TRUTH TRACK, and the pinned one comes first.
      * PINNED (`TRUTH_BINDINGS`, keyed by this log's stem): the binding names the applied log, and
        the overlap scan is SKIPPED -- the reviewed pin IS the disambiguation. Sim time restarts near
        0 every run, so the scan can only report ambiguity once two takes are committed.
      * UNPINNED: unchanged -- discover by sim-span overlap and refuse on 0 or >1, and refuse on any
        OTHER overlapping log even when `--truth` was explicit.
    `log_path` is a required positional, not an option: a signature that let a caller omit the log
    would let a PINNED flight silently fall back to the very scan the pin exists to replace."""
    span = tick_stamp_span(run)
    bound = TRUTH_BINDINGS.get(Path(log_path).stem)
    path: Optional[Path] = None
    if truth_arg is not None:
        path = Path(truth_arg)
        if not path.exists():
            return None, [f"no truth track: --truth {path} does not exist"]
        if bound is not None and path.name != bound:
            return None, [
                f"--truth {path.name} CONTRADICTS the reviewed binding for this flight: "
                f"{Path(log_path).stem!r} is pinned to {bound} in TRUTH_BINDINGS in "
                f"scripts/{Path(__file__).name}. A pin the command line can override is not a pin, "
                f"and the wrong take's track is exactly what `ls -t …_applied.jsonl | head -1` "
                f"hands you after an aborted takeoff: every tick outside it is answered from the "
                f"birds' SPAWN poses -- confidently wrong, not unmeasured. Pass the bound log, or "
                f"change the binding in a reviewed diff."]
    if bound is not None:
        if path is None:
            path = Path(log_path).with_name(bound)
            if not path.exists():
                return None, [
                    f"no truth track: {Path(log_path).stem!r} is pinned to {bound} in "
                    f"TRUTH_BINDINGS in scripts/{Path(__file__).name}, but that file is not beside "
                    f"the log ({path}). A binding is not a hint to fall back from -- falling back "
                    f"to the overlap scan would score this flight against whatever ELSE overlaps "
                    f"it, which is the failure the pin exists to prevent. Restore the applied log "
                    f"beside the flight log, or pass it with --truth (same filename)."]
    else:
        cands = truth_candidates(span, results_dir)
        if truth_arg is not None:
            # `--truth` says WHICH log to score against; it does not get to say that the others do
            # not exist. The runbook's own invocation is `ls -t … | head -1`, and one aborted
            # takeoff (the runbook warns about `Arm: Accels inconsistent` + retry) or one
            # `fly_pipeline.sh birds` override leaves two applied logs for a single take. `head -1`
            # then picks the one covering the TAIL, every earlier tick is answered from the birds'
            # config SPAWN poses, and bird_0's spawn sits 4 m below cruise directly under mission
            # lane x=15 -- so the wrong pick either fabricates a ~0 m breach or hides a real one.
            # The only signal was a note nobody must read.
            others = [p for p in cands if p.resolve() != path.resolve()]
            if others:
                names = ", ".join(p.name for p in others)
                return None, [
                    f"AMBIGUOUS TAKE: --truth {path.name} was given, but {len(others)} OTHER "
                    f"applied log(s) also overlap this flight's sim-time window ({names}). One "
                    f"take has ONE bird ground truth; two mean an aborted takeoff, a "
                    f"`fly_pipeline.sh birds` restart, or a stale log from a previous run. Every "
                    f"tick outside the log you passed is answered from the birds' SPAWN poses -- "
                    f"confidently wrong, not unmeasured. Move the log(s) that do not belong to "
                    f"this take out of {results_dir.name}/ and re-run, or bind this take in "
                    f"TRUTH_BINDINGS (a reviewed diff) if the log is being committed as evidence."]
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
                    f"ambiguous truth track: {len(cands)} applied logs overlap this flight's "
                    f"sim-time window ({names}). Gazebo sim time restarts near 0 every run, so "
                    f"overlap alone cannot pick the take -- pass --truth explicitly, or bind this "
                    f"take in TRUTH_BINDINGS (a reviewed diff) if the log is being committed as "
                    f"evidence."]
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


# ------------------------------------------------- the DECLARED bird-less flight (`--no-birds`)
# A WIRING FLIGHT HAS NO TRUTH TRACK, AND THAT IS NOT THE SAME AS A MISSING ONE. The P2 step-0 depth
# flight of 2026-09-11 drove NO birds by design -- they were parked off-field and `drive_birds.py`
# never ran -- so no `bird_drive_*_applied.jsonl` was written for it. Gazebo sim time restarts near
# 0 every run, so two OLD applied logs overlapped its window anyway, `resolve_truth` reported
# "ambiguous truth track", and the take came out INVALID with no way to say "there was nothing to
# track". That is a CHECKER GAP, booked as such in ADR-020 amendment 6: the gate could not tell
# "we did not look" from "there was nothing to look at", and those are not the same claim either.
#
# `--no-birds` is a DECLARATION, not a measurement. Under it truth resolution is SKIPPED (no
# candidate search, no ambiguity, no binding), and every gate that needs a bird prints
# `N/A (no birds driven)` -- never PASS, never a number. EVERYTHING ELSE STAYS LIVE: ledger, clock,
# stamps, detector-ran, the depth counter/runtime bars, the booked speed, R2/R3, the schema. That is
# the whole design constraint -- the 2026-09-11 log is still INVALID under this flag, on its own
# `detect_wall_ms_max` bar, and a mode that turns an INVALID log green would be a laundering mode
# rather than a scoring one.
#
# SIX THINGS THE DECLARATION CANNOT SURVIVE, because a FALSE declaration is the only way this flag
# could hide a breach. The first four are evidence, in the log itself, that something WAS in front
# of the vehicle:
#   1. an avoidance event the loop only writes for a threat (takeover / latch / relatch / maneuver /
#      resume) -- the executor cannot reach any of them without a policy maneuver;
#   2. a `detection` event inside the policy's OWN threat cylinder, tested with the same inequality
#      `AvoidancePolicy._threats` uses, on the cylinder THIS flight recorded. A detection outside it
#      is allowed on purpose: the depth seam boxes mapped canopies all flight long (33,029 of them
#      on 2026-09-11) and a wiring flight is largely a record of exactly that;
#   3. a `bird_drive_*[_applied].jsonl` filename the log ITSELF names anywhere in its JSON -- a
#      flight that recorded its own bird track did not fly without birds;
#   4. a stem pinned in `TRUTH_BINDINGS` -- a reviewed diff already says which bird track belongs to
#      this take, and a command-line declaration may not overrule a reviewed pin (the same doctrine
#      that makes `--truth` unable to override a binding).
# ...and the last two do NOT read the flight log at all, which is the whole point of them:
#   5. THE WALL CLOCK -- a `bird_drive_*` artifact written within +/-30 min of this flight's own UTC
#      stamp (`no_birds_wall_clock_reasons`). Gazebo restarts SIM time near 0 every run, which is
#      what made the truth scan ambiguous in the first place; the wall clock does not restart, so
#      "the driver ran minutes from this take" is checkable without the detector's help.
#   6. THE BRINGUP RECORD -- `eval/results/live_flight_booking_<UTC>.json`, written by
#      `fly_pipeline.sh up` BEFORE the flight, which since 2026-09-11 records whether the birds pane
#      was armed. A declaration typed at scoring time does not overrule the machine-written record
#      of the bringup (`launcher_birds_reason`).
# None of the six is a measurement of separation, and they are not claimed to be: they are the
# falsifiers of the declaration. What the flag GIVES UP is the gt-CPA gate, which is why the verdict
# block says the N/A lines came from a declaration and names it.
#
# THE BLIND SPOT, STATED ONCE HERE AND PRINTED ON EVERY RUN (QA, 2026-09-11). Falsifiers 1-4 are all
# DETECTOR-SIDE: `AvoidanceExecutor._log_detection` writes a `detection` event only for a detection
# the policy already classified as an in-cylinder THREAT, so a bird the detector NEVER SAW leaves no
# trace in the artifact at all -- a total false negative writes exactly the log a bird-less flight
# writes. That is the direction the gt-CPA bar exists for, and the applied-pose truth track is the
# ONLY evidence of a bird the log itself does not carry. Falsifiers 5 and 6 are the answer available
# without one, and they are proximity/paperwork tests rather than measurements: they can say "a bird
# driver ran next to this take", never "nothing was in the air".
# (`NA_NO_BIRDS`, the words every one of those lines prints, lives beside `NA_DEPTH` above -- the
# depth tail needs it, and one constant may not have two homes.)
#
# Event kinds `AvoidanceExecutor` can only reach through a policy maneuver against a threat.
# `proceed`, `hold`, `gate_reject`, `debt` and `divert_audit_summary` are deliberately NOT here:
# a proceed is the no-threat tick, and a hold/gate_reject without a triggering detection is the
# geofence backstop, which a bird-less flight can legitimately hit.
TARGET_EVIDENCE_KINDS = ("takeover", "latch", "relatch", "maneuver", "resume")
# `bird_drive_<stamp>.json` / `bird_drive_<stamp>_applied.jsonl`, as `drive_birds.py` names them.
TRUTH_FILE_RE = re.compile(r"bird_drive_[0-9A-Za-z]+(?:_applied)?\.jsonl?")


def named_truth_files(log) -> List[str]:
    """Every `bird_drive_*[_applied].jsonl` filename this log names, anywhere in its own JSON.

    Walked iteratively over keys AND values: a flight log is a few MB of nested lists and the
    filename could arrive in a field nobody has written yet (a future `run.truth_track`, a
    hand-added note). The question is "does this artifact name a bird track", and the honest way to
    ask it is of the whole document rather than of one key."""
    found = set()
    stack = [log]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            stack.extend(node.keys())
            stack.extend(node.values())
        elif isinstance(node, (list, tuple)):
            stack.extend(node)
        elif isinstance(node, str):
            found.update(TRUTH_FILE_RE.findall(node))
    return sorted(found)


# +/-30 min, on the WALL clock. Measured on the real artifacts (2026-09-11): the take that DROVE
# birds sits 3.5 min from its own track, the bird-less wiring take 23,802 min (16.5 days) from the
# nearest one, and the two demo takes 228.8 / 164.4 min. Three orders of magnitude of separation, so
# the window is chosen wide enough to cover a bringup-to-log gap (21.5 min on 2026-09-11) and small
# enough that it has never had to be argued about.
BIRD_TRACK_WALL_WINDOW_S = 1800.0
# A bringup precedes the flight log it produces by minutes to hours (2026-09-11: 21.5 min). A record
# stamped AFTER the log belongs to a later take and is not read at all.
LAUNCHER_RECORD_WINDOW_S = 6 * 3600.0
# The two values `fly_pipeline.sh write_booking_sidecar` writes into `birds`. A record with NO
# `birds` key was written by a launcher older than 2026-09-11 and reconciles NOTHING -- absence is
# not a declaration, and the gate says so rather than reading it either way.
LAUNCHER_BIRDS_DECLARED = "none (declared --no-birds)"
LAUNCHER_BIRDS_ARMED = "armed (altitude-gated drive_birds.py pane)"
UTC_STAMP_RE = re.compile(r"\d{8}T\d{6}Z")


def utc_of(text) -> Optional[datetime]:
    """The UTC instant in `text`, from a `<...>_20260911T094235Z.json` stem or a
    `2026-09-11T09:21:05Z` field. `None` when there is none to read -- never "now", never the file's
    mtime: a copied file carries a new mtime and the same claim."""
    if not isinstance(text, str):
        return None
    m = UTC_STAMP_RE.search(text.replace("-", "").replace(":", ""))
    if m is None:
        return None
    try:
        return datetime.strptime(m.group(0), "%Y%m%dT%H%M%SZ")
    except ValueError:
        return None


def evidence_dirs(path: Path, results_dir: Path) -> List[Path]:
    """Where a take's sibling artifacts live: the results dir the gate scans AND the log's own
    directory. The 2026-09-11 wiring log sits in `eval/results/step0_wiring_20260911/` while the
    bird tracks sit in `eval/results/`, so looking in one place only would scan the wrong half."""
    dirs: List[Path] = []
    seen = set()
    for d in (Path(results_dir), Path(path).parent):
        try:
            key = d.resolve()
        except OSError:                                        # pragma: no cover - unreadable path
            continue
        if d.is_dir() and key not in seen:
            seen.add(key)
            dirs.append(d)
    return dirs


def bird_track_artifacts(dirs: Sequence[Path]) -> List[Tuple[str, Optional[datetime]]]:
    """Every `bird_drive_*` file in `dirs` as (name, wall-clock stamp).

    The stamp comes from the sidecar's own `written_utc` when the file is a readable JSON sidecar
    (that is what `drive_birds.py` records) and from the filename otherwise -- the applied logs are
    half a megabyte of JSONL and are not read for a timestamp their name already carries."""
    out: List[Tuple[str, Optional[datetime]]] = []
    for d in dirs:
        for p in sorted(d.glob("bird_drive_*")):
            stamp = None
            if p.suffix == ".json":
                try:
                    doc = json.loads(p.read_text())
                    stamp = utc_of(doc.get("written_utc")) if isinstance(doc, dict) else None
                except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                    stamp = None
            out.append((p.name, stamp if stamp is not None else utc_of(p.name)))
    return out


def no_birds_wall_clock_reasons(path: Path, results_dir: Path) -> List[str]:
    """FALSIFIER 5: a bird driver that ran next to this take, on the one clock Gazebo does not
    restart. `[]` = no bird-track artifact is close enough in wall-clock time to contradict the
    declaration.

    Three ways to be refused, and they are different facts. A track INSIDE the window is evidence
    birds were driven on this flight. A track whose stamp cannot be read is a track that cannot be
    excluded -- and "we could not tell" may not clear a declaration, the same rule the truth join
    and the unplaceable detection live by. A FLIGHT LOG whose name carries no UTC stamp puts every
    track in that second class at once (`avoidance_node` always writes `live_flight_log_<UTC>.json`,
    so an unstamped one has been renamed)."""
    dirs = evidence_dirs(path, results_dir)
    tracks = bird_track_artifacts(dirs)
    if not tracks:
        return []
    flight = utc_of(Path(path).name)
    where = ", ".join(str(d) for d in dirs)
    if flight is None:
        return [f"{len(tracks)} bird-track artifact(s) sit in {where} and this log's NAME carries no "
                f"UTC stamp ({Path(path).name}), so none of them can be excluded in WALL-CLOCK time "
                f"-- `avoidance_node` writes `live_flight_log_<UTC>.json`, so a log without one has "
                f"been renamed. Score it under its own name, or bind the track with --truth"]
    reasons = []
    unstamped = sorted(name for name, stamp in tracks if stamp is None)
    if unstamped:
        reasons.append(f"bird-track artifact(s) in {where} whose wall-clock stamp cannot be read "
                       f"({', '.join(unstamped[:3])}{'...' if len(unstamped) > 3 else ''}) -- an "
                       f"artifact that cannot be placed in time cannot be excluded from this take")
    near = sorted(((abs((stamp - flight).total_seconds()), name, stamp)
                   for name, stamp in tracks if stamp is not None
                   and abs((stamp - flight).total_seconds()) <= BIRD_TRACK_WALL_WINDOW_S))
    for dt_s, name, stamp in near[:3]:
        reasons.append(
            f"a bird-track artifact written {dt_s / 60.0:.1f} min from this flight's own wall-clock "
            f"stamp ({name}, {stamp:%Y-%m-%dT%H:%M:%SZ} vs {flight:%Y-%m-%dT%H:%M:%SZ}; window "
            f"+/-{BIRD_TRACK_WALL_WINDOW_S / 60.0:.0f} min) -- Gazebo restarts SIM time near 0 every "
            f"run, which is why the truth scan cannot tell these apart, but the WALL clock does not "
            f"restart: a driver that ran that close to this take drove birds on it")
    if len(near) > 3:
        reasons.append(f"...and {len(near) - 3} further bird-track artifact(s) inside the window")
    return reasons


def launcher_record(path: Path, results_dir: Path) -> Tuple[Optional[str], Optional[str],
                                                            Optional[datetime]]:
    """FALSIFIER 6's input: (record name, its `birds` field, its stamp) for the newest
    `live_flight_booking_*.json` written at or before this flight's stamp and within
    `LAUNCHER_RECORD_WINDOW_S` of it -- the bringup this take was flown out of.

    The launcher writes that file only when the bringup was given `--booking`, so its ABSENCE means
    nothing at all and is reported as "unreconciled" rather than read either way. Same for a record
    with no `birds` key: those were written before 2026-09-11 and carry no statement to reconcile."""
    flight = utc_of(Path(path).name)
    if flight is None:
        return None, None, None
    best: Optional[Tuple[datetime, str, Optional[str]]] = None
    for d in evidence_dirs(path, results_dir):
        for p in sorted(d.glob("live_flight_booking_*.json")):
            try:
                doc = json.loads(p.read_text())
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                continue
            if not isinstance(doc, dict) or doc.get("kind") != "live_flight_booking":
                continue
            stamp = utc_of(doc.get("written_utc")) or utc_of(p.name)
            if stamp is None:
                continue
            delta = (flight - stamp).total_seconds()
            if not (0.0 <= delta <= LAUNCHER_RECORD_WINDOW_S):
                continue
            birds = doc.get("birds")
            if best is None or stamp > best[0]:
                best = (stamp, p.name, birds if isinstance(birds, str) else None)
    if best is None:
        return None, None, None
    return best[1], best[2], best[0]


def launcher_birds_reason(path: Path, results_dir: Path) -> Optional[str]:
    """FALSIFIER 6: the bringup record says the birds pane was ARMED. `None` = nothing to contradict
    (no record in the window, or one that carries no statement about birds)."""
    name, birds, stamp = launcher_record(path, results_dir)
    if name is None or birds is None or birds == LAUNCHER_BIRDS_DECLARED:
        return None
    return (f"the launcher's own bringup record for this take ({name}, written "
            f"{stamp:%Y-%m-%dT%H:%M:%SZ}) records `birds: {birds!r}` -- the bringup that produced "
            f"this flight ARMED the birds pane, and a declaration typed at SCORING time does not "
            f"overrule the machine-written record of the BRINGUP. One of the two is wrong; the gate "
            f"does not get to choose which")


def launcher_birds_note(path: Path, results_dir: Path, no_birds: bool) -> Optional[str]:
    """The bringup record read the OTHER way: what the two declarations say to each other.

    Under `--no-birds` it reports whether the bringup agrees, is silent, or was never written --
    because a declaration that reconciles against a machine-written record is worth more than one
    that does not, and a reader must be able to tell those apart. WITHOUT the flag it fires only
    when a record explicitly declared the take bird-less: that take's truth resolution just ran
    anyway, which is either a missing flag or a wrong record."""
    name, birds, stamp = launcher_record(path, results_dir)
    if not no_birds:
        if name is not None and birds == LAUNCHER_BIRDS_DECLARED:
            return (f"BRINGUP DECLARED BIRD-LESS, SCORED WITHOUT THE FLAG: {name} records `birds: "
                    f"{birds!r}` at {stamp:%Y-%m-%dT%H:%M:%SZ}, but --no-birds was not passed, so "
                    f"truth resolution ran against whatever tracks overlap this flight's sim "
                    f"window. If the bringup record is right, score this take with --no-birds; if "
                    f"it is wrong, the take's paperwork is wrong.")
        return None
    if name is None:
        return ("bringup record: NONE within "
                f"{LAUNCHER_RECORD_WINDOW_S / 3600.0:.0f} h before this flight's stamp, so the "
                f"declaration is UNRECONCILED -- `fly_pipeline.sh up` writes "
                f"`live_flight_booking_<UTC>.json` only when the bringup was given --booking.")
    if birds is None:
        return (f"bringup record: {name} ({stamp:%Y-%m-%dT%H:%M:%SZ}) carries no `birds` field -- "
                f"written by a launcher older than 2026-09-11, so it says nothing about whether the "
                f"pane was armed and the declaration stays UNRECONCILED.")
    return (f"bringup record RECONCILES: {name} ({stamp:%Y-%m-%dT%H:%M:%SZ}) already recorded "
            f"`birds: {birds!r}` at bringup, minutes before the flight -- the same declaration, "
            f"made by the launcher rather than at scoring time.")


def no_birds_denominators(log, path: Path, results_dir: Path) -> str:
    """WHAT THE SIX FALSIFIERS SCANNED -- with denominators, because a clean scan and an EMPTY scan
    print the same word otherwise (CLAUDE.md: a rate with no denominator is EVIDENCE INSUFFICIENT).

    On the real 2026-09-11 wiring take the in-cylinder falsifier scanned ZERO detection events while
    the segmenter produced 33,029 boxes, and the first cut of this note said only "all four ran and
    found nothing"."""
    events = log.get("events") if isinstance(log, dict) else None
    events = events if isinstance(events, list) else []
    run = log.get("run") if isinstance(log, dict) else None
    detector = run.get("detector") if isinstance(run, dict) else None
    counters = detector.get("counters") if isinstance(detector, dict) else None
    boxes = _num(counters.get("boxes_total")) if isinstance(counters, dict) else None
    dirs = evidence_dirs(path, results_dir)
    tracks = bird_track_artifacts(dirs)
    flight = utc_of(Path(path).name)
    deltas = [abs((stamp - flight).total_seconds()) for _, stamp in tracks
              if stamp is not None and flight is not None]
    nearest = (f"nearest {min(deltas) / 60.0:,.1f} min away"
               if deltas else "none of them placeable in time")
    return (f"falsifiers scanned: {len(events)} event(s), {len(depth_detections(log))} of them "
            f"`detection` event(s); "
            + ("no boxes_total counter in this log" if boxes is None else
               f"{int(boxes)} detector box(es) that never reached the event log (a `detection` is "
               f"written only for a detection the policy classified as an in-cylinder THREAT)")
            + f"; {len(named_truth_files(log))} bird-track filename(s) named by the log; "
              f"{len(TRUTH_BINDINGS)} reviewed TRUTH_BINDINGS pin(s); {len(tracks)} bird-track "
              f"artifact(s) in {', '.join(str(d) for d in dirs) or '(no readable directory)'} "
              f"({nearest}, refusal window "
              f"+/-{BIRD_TRACK_WALL_WINDOW_S / 60.0:.0f} min).")


def threat_cylinder(run) -> Tuple[float, float, str]:
    """`(threat_radius_m, vertical_threat_m, provenance)` -- the cylinder the refusal tests, which
    is the LARGER of the one this take flew and today's default.

    Read from `run.policy_params`, because a take flown with a WIDER cylinder must be judged against
    the one it flew. FLOORED at `PolicyParams()`, because a falsifier may not shrink with the knobs
    it falsifies: the same run writes both the knobs and the detections, so a log recording
    `threat_radius_m 0.1` would push a detection 0.21 m from the vehicle "outside" a cylinder 30x
    smaller than the 3.00 m clearance bar the declaration protects, and the declaration would stand
    (QA, 2026-09-11 -- measured on the 2026-08-25 breach log). The widening lives HERE rather than in
    `gate_knob_floors` because only the refusal may use it: the two ACKNOWLEDGED demo logs record
    NEITHER knob, and flooring them there would add a new problem to a committed verdict. A log with
    no usable block falls back to `PolicyParams()` and SAYS SO, because a silent fallback is how a
    refusal ends up measured against the wrong cylinder."""
    defaults = PolicyParams()
    floor_r, floor_v = float(defaults.threat_radius_m), float(defaults.vertical_threat_m)
    pp = run.get("policy_params") if isinstance(run, dict) else None
    if isinstance(pp, dict):
        radius, vertical = _num(pp.get("threat_radius_m")), _num(pp.get("vertical_threat_m"))
        if radius is not None and vertical is not None:
            wide, tall = max(radius, floor_r), max(vertical, floor_v)
            if (wide, tall) == (radius, vertical):
                return wide, tall, "run.policy_params"
            return wide, tall, (
                f"run.policy_params WIDENED to today's floor -- this log records threat_radius_m "
                f"{radius:g} m / vertical_threat_m {vertical:g} m, below the {floor_r:g} m / "
                f"{floor_v:g} m PolicyParams() default, and a falsifier does not shrink with the "
                f"knobs it is falsifying")
    return (floor_r, floor_v,
            "PolicyParams() defaults -- this log records no usable run.policy_params")


def in_cylinder_detections(log, run) -> List[str]:
    """Reasons, one per `detection` event that a bird-less flight cannot explain.

    Two of them. INSIDE THE CYLINDER: the same inequality `AvoidancePolicy._threats` applies
    (horizontal range <= `threat_radius_m` AND |dz| <= `vertical_threat_m`), so the refusal and the
    policy cannot disagree about what a threat is. UNPLACEABLE: an event with no position, or none
    on its tick's flown point, cannot be shown to be outside -- and "we could not tell" may not
    clear a declaration, which is the same rule the truth join lives by.

    `depth_detections` is the reader for every `detection` event whatever the detector wrote it
    (its name is where it was first needed, not what it reads): position, the drone's own recorded
    point on that tick, and the 3D range between them."""
    radius, vertical, prov = threat_cylinder(run)
    reasons: List[str] = []
    for det in depth_detections(log):
        pos, drone, tick = det["position_enu"], det["drone_enu"], det["tick"]
        if pos is None or drone is None:
            reasons.append(
                f"a `detection` event at tick {tick} this gate cannot PLACE (no position_enu, or no "
                f"flown point on that tick), so it cannot be shown to be outside the threat "
                f"cylinder -- an unplaceable detection does not clear a declaration")
            continue
        hrange = math.hypot(pos[0] - drone[0], pos[1] - drone[1])
        dz = abs(pos[2] - drone[2])
        if hrange <= radius and dz <= vertical:
            reasons.append(
                f"a `detection` event at tick {tick} sitting {hrange:.3f} m horizontally and "
                f"{dz:.3f} m vertically from the drone -- INSIDE the policy's own threat cylinder "
                f"(threat_radius_m {radius:g} m, vertical_threat_m {vertical:g} m, from {prov})")
    return reasons


def no_birds_refusal(log, path: Path, results_dir: Path = RESULTS_DIR) -> List[str]:
    """Why this log may NOT be declared bird-less. `[]` = the declaration stands.

    ONE message, naming every falsifier found, because an operator who mis-declared a take wants the
    whole list rather than the first item of it. The verdict is INVALID and the log is NOT scored
    further: gates run under a declaration this log contradicts would be a verdict on a fiction.

    Falsifiers 5 and 6 need `results_dir` -- they read the take's SIBLING artifacts (the bird tracks
    and the launcher's bringup record) rather than the log, which is what makes them the only two
    that a detector blind spot cannot silence."""
    run = log.get("run") if isinstance(log, dict) else None
    run = run if isinstance(run, dict) else {}
    reasons: List[str] = []

    counts: Dict[str, int] = {}
    first: Optional[dict] = None
    for ev in (log.get("events") or []):
        if isinstance(ev, dict) and ev.get("kind") in TARGET_EVIDENCE_KINDS:
            counts[ev["kind"]] = counts.get(ev["kind"], 0) + 1
            if first is None:
                first = ev
    if first is not None:
        reasons.append(
            f"{sum(counts.values())} avoidance event(s) the loop can only write for a THREAT "
            f"({', '.join(f'{k} x{n}' for k, n in sorted(counts.items()))}) -- first: `"
            f"{first.get('kind')}` at tick {first.get('tick')}")

    hits = in_cylinder_detections(log, run)
    reasons.extend(hits[:3])
    if len(hits) > 3:
        reasons.append(f"...and {len(hits) - 3} further detection event(s) of the same kind")

    named = named_truth_files(log)
    if named:
        reasons.append(f"the log itself names bird ground-truth file(s) ({', '.join(named)}) -- a "
                       f"flight that recorded its own bird track drove birds")

    stem = Path(path).stem
    if stem in TRUTH_BINDINGS:
        reasons.append(f"{stem!r} is pinned to {TRUTH_BINDINGS[stem]} in TRUTH_BINDINGS in "
                       f"scripts/{Path(__file__).name} -- a reviewed diff already says which bird "
                       f"track belongs to this take, and a command-line declaration does not "
                       f"overrule a reviewed pin")

    reasons.extend(no_birds_wall_clock_reasons(Path(path), results_dir))
    launcher = launcher_birds_reason(Path(path), results_dir)
    if launcher is not None:
        reasons.append(launcher)

    if not reasons:
        return []
    return ["--no-birds REFUSED: this log carries evidence that something WAS in front of the "
            "vehicle, so it cannot be declared a bird-less flight -- " + "; ".join(reasons)
            + ". Nothing below was scored: gates run under a declaration the artifact contradicts "
              "would be a verdict on a fiction. Re-run WITHOUT --no-birds (with --truth <applied "
              "log> if this take had one) to score it properly."]


def no_birds_notes(depth: bool, scanned: str) -> List[str]:
    """The CPA/truth family, under a declaration that there was nothing to measure it against.

    Every line says `N/A (no birds driven)` in those words -- never PASS, never a number -- and the
    first one says WHY: a declaration produced them, what its falsifiers scanned (`scanned`, from
    `no_birds_denominators`), and what none of them can see."""
    notes = [
        f"truth: none (declared --no-birds) -- truth resolution was SKIPPED for this flight: no "
        f"candidate search, no ambiguity, no bound applied log. The {NA_NO_BIRDS} lines below come "
        f"from a DECLARATION, not from a measurement, and are worth exactly what the declaration "
        f"is. Its six falsifiers all ran and found nothing (an avoidance event, a detection inside "
        f"the threat cylinder, a bird-track filename this log names, a reviewed TRUTH_BINDINGS pin, "
        f"a bird track written within "
        f"{BIRD_TRACK_WALL_WINDOW_S / 60.0:.0f} min of this flight on the WALL clock, a bringup "
        f"record that armed the birds pane); none of them measures separation. "
        f"BLIND SPOT, stated: a bird the detector NEVER SAW leaves no trace here -- the first four "
        f"read this flight's own log, where a `detection` appears only for a policy-classified "
        f"threat, so a total false negative writes the same log a bird-less flight writes. The "
        f"applied-pose truth track is the only evidence of a bird the log itself does not carry; "
        f"the last two falsifiers are proximity and paperwork, not separation. {scanned}",
        f"gt_cpa_m -- THE safety bar, the flown path against the birds' applied-pose truth: "
        f"{NA_NO_BIRDS}. Never a PASS and never a number: a flight with no bird in the world "
        f"measured nothing about separation from one, so this take does not clear the "
        f"{min_bird_clearance_m():.2f} m bar and is not claimed to.",
        f"truth coverage / truth poses scored / answered_from_spawn: {NA_NO_BIRDS} -- no "
        f"applied-pose track covers this flight's ticks, so the join has no denominators to report.",
    ]
    if not depth:
        notes.append(
            f"detection_cpa_m (the monocular estimator check) and the bird-inside-the-cylinder "
            f"missed-detection signal: {NA_NO_BIRDS} -- both are measured AGAINST the truth track, "
            f"and the estimator was never a gate in the first place.")
    return notes


def check_schema2(path: Path, log: dict, truth_arg: Optional[Path] = None,
                  results_dir: Path = RESULTS_DIR,
                  booking_arg: Optional[Path] = None,
                  no_birds: bool = False) -> Tuple[str, List[str]]:
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
    e_problems, e_notes = gate_encounter_closure(log, run, adv)
    problems.extend(e_problems)
    notes.extend(e_notes)
    r_problems, r_notes = gate_r2_r3(log, run)
    problems.extend(r_problems)
    notes.extend(r_notes)
    b_problems, b_notes = gate_booked_speed(log, run, path, booking_arg)
    problems.extend(b_problems)
    notes.extend(b_notes)
    # THE OTHER DECLARATION ABOUT THIS TAKE, written by the launcher at bringup minutes before the
    # flight. Read whether or not `--no-birds` was passed: two declarations of the same fact that
    # are never reconciled are one declaration typed twice (QA, 2026-09-11).
    launcher_note = launcher_birds_note(path, results_dir, no_birds)
    if launcher_note is not None:
        notes.append(launcher_note)

    bar = min_bird_clearance_m()
    freeze_debit = freeze_debit_m(adv["frozen_window_s"])      # 0.0 unless the axis stalled
    detector = run.get("detector")
    source = detector.get("source") if isinstance(detector, dict) else None
    det_cpa = closest_approach(log)              # the monocular ESTIMATE -- never a gate under v2
    cpa_m: Optional[float] = None                # the gated number, whatever it is measured against
    seen = encounter_ticks(log)

    # The label and the fields must be the same detector -- checked BEFORE the dispatch below, so a
    # mislabelled block is named as such whether or not its claimed source is one this gate scores.
    problems.extend(gate_detector_block_matches_source(run))

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
    else:                    # DET_NDVI_BLOB / DET_DEPTH_BLOB -- a real detector, on real evidence
        depth = source == DET_DEPTH_BLOB
        problems.extend(gate_staleness(run))          # ADR-009 rule 1 is sensor-independent
        if depth:
            for gate in (gate_depth_detector_ran(log, run),          # P1 bars 1, 2 + runtime
                         gate_depth_range_model(run)):               # P1 bar 3, first half
                problems.extend(gate[0])
                notes.extend(gate[1])
        else:
            det_problems, det_notes = gate_detector_ran(log, run)
            problems.extend(det_problems)
            notes.extend(det_notes)
        # THE TRUTH JOIN IS THE SAME MEASUREMENT FOR BOTH APERTURES, and deliberately so: `gt_cpa_m`
        # is the flown path against the bird's own applied-pose track, which knows nothing about
        # which camera saw it. What differs is everything DOWNSTREAM of it -- the estimator check
        # (an apparent-size ray vs a measured range) and the missed-detection scoping (a downward
        # footprint vs a forward frustum) -- so those live in the two tails below, not in here.
        truth: Optional[TruthTrack] = None
        report: Optional[dict] = None
        if no_birds:
            # DECLARED bird-less: skip the resolution entirely rather than resolve-and-forgive. A
            # candidate scan that ran and was ignored would still print its ambiguity, which is the
            # exact noise this mode exists to remove. The falsifiers already ran in `check_file`;
            # what they SCANNED is printed here, because an empty scan and a clean one otherwise
            # print the same sentence.
            notes.extend(no_birds_notes(depth, no_birds_denominators(log, path, results_dir)))
        else:
            truth, truth_problems = resolve_truth(path, run, truth_arg, results_dir)
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
            if not depth:
                if det_cpa is None:
                    notes.append("detection_cpa_m NONE -- the detector logged no positioned "
                                 "detection. ESTIMATOR CHECK, NOT A SAFETY GATE.")
                else:
                    # The estimator error is measured against the MEASURED join, never the debited
                    # one: the debit prices a clock fault, not the detector's range error.
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
                             f"engaged on {hit} of them (missed-detection signal, NOT gated -- the "
                             f"camera is NADIR, so a bird inside the cylinder can sit outside the "
                             f"downward footprint at its own altitude, and one above the drone is "
                             f"never in frame at all)")
        if depth:
            # THE DEPTH TAIL -- the four bars that need the flight's own events and, for bar 3's
            # second half, the truth join above (`truth`/`report` are None when it failed, and the
            # bar then prints UNMEASURED rather than passing on nothing).
            scored: List[Tuple[str, bool]] = []
            range_gate = (no_birds_range_error() if no_birds
                          else depth_range_error(log, truth, report))
            for label, gate in ((DEPTH_BAR_NEEDS_TRUTH, range_gate),
                                ("5 acquisition", gate_depth_acquisition(log, run)),
                                ("4 frustum", gate_depth_frustum(log, run)),
                                ("6 static map", gate_depth_static_map(log, run))):
                problems.extend(gate[0])
                notes.extend(gate[1])
                scored.append((label, gate[2]))
            # HOW MUCH OF THIS TAKE WAS ACTUALLY LOOKED AT, in the artifact whatever the verdict.
            # Each of those four says "Never a PASS" when it measures nothing, but the VERDICT WORD
            # and the exit code -- which is what CI and the runbook's step 1 read -- do not: a depth
            # take that logged no encounter at all comes out VALID with all four UNMEASURED. This
            # count is the honest half of that (QA 2026-09-07). Whether a take flown under a BOOKING
            # with no encounter in it should be AMBIGUOUS rather than VALID is a safety-vs-scope
            # call and belongs to product-lead, not to a gate written overnight.
            def bar_status(label: str, ok: bool) -> str:
                if ok:
                    return "measured"
                # UNMEASURED means the evidence could have been there and was not. Under a bird-less
                # declaration bar 3b's evidence could NOT have been there, so it says so in the
                # summary too -- one word for one fact, wherever it is printed.
                return NA_NO_BIRDS if (no_birds and label == DEPTH_BAR_NEEDS_TRUTH) else "UNMEASURED"

            notes.append(
                f"DEPTH BARS MEASURED: {sum(1 for _, ok in scored if ok)} of {len(scored)} -- "
                + "; ".join(f"bar {label}: {bar_status(label, ok)}" for label, ok in scored)
                + ". Measured = the bar had the evidence it needs and reached a verdict on it; "
                  "UNMEASURED is never a PASS. These four need the flight's own encounter events "
                  "(and, for 3b, a truth track); bars 1, 2, 3a and 7 read counters and "
                  "declarations, so they always measure.")
            notes.extend(depth_na_notes(report, seen))               # P1 bar 7
    notes.append(f"n_stale_dropped={stale_dropped_total(log)} over "
                 f"{n_detection_events(log)} detection event(s) -- reported for every flight, and "
                 f"FAILED by gate_detector_ran in exactly one combination: drops > 0 with 0 "
                 f"engagements, which is avoidance dead for the whole take")

    notes.extend(displacement_notes(log))        # REPORTED, NEVER GATED (G1/G2)

    # --- verdict: a marker acknowledges a CPA FINDING, never a failed gate ------------------------
    marker = marker_path_for(path)
    breach = cpa_m is not None and cpa_m < bar
    if breach:
        problems.append(f"{CPA_BREACH_TAG}: flew within {cpa_m:.4f} m of a bird, closer than the "
                        f"policy's own min_bird_clearance_m {bar:.2f} m -- the policy refuses to "
                        f"place a SETPOINT that near a threat (ADR-013 amendment 12, S1)."
                        + ("" if freeze_debit <= 0.0
                                  or source not in (DET_NDVI_BLOB, DET_DEPTH_BLOB) else
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
               results_dir: Path = RESULTS_DIR,
               booking: Optional[Path] = None,
               no_birds: bool = False) -> Tuple[str, List[str]]:
    """Validate one path -> (SKIP|VALID|INVALID|ACKNOWLEDGED, messages). For VALID the messages are
    the headline numbers (CLAUDE.md: no 'it works' without a metric); for INVALID the numbers come
    first and the problems after -- the metric is printed whatever the verdict.

    `no_birds` is the operator's DECLARATION that this flight drove no birds (see the `--no-birds`
    section above). It is checked HERE, once, for every log on every path -- schema-2 and legacy --
    because a declaration is about the artifact, not about which gate happens to read it."""
    if not path.exists():
        return SKIP, [f"{path} absent -- nothing to validate"]
    if no_birds and truth is not None:
        return INVALID, [
            "--no-birds declares this flight drove no birds and --truth binds it to a bird track: "
            "the two cannot both be true. `main` refuses the combination at the command line "
            "(argparse, exit 2); this is the same refusal for an in-process caller."]
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
    # THE DECLARATION IS CHECKED BEFORE THE DISPATCH, so it covers the legacy path too: a pre-seam
    # log's CPA is measured against its own detections, and declaring one of those bird-less while
    # it carries an in-cylinder detection would be the same lie on a different gate.
    if no_birds:
        refusal = no_birds_refusal(log, path, results_dir)
        if refusal:
            return INVALID, [headline] + refusal
    version = schema_version(log)
    if version is not None:
        if version < GATED_SCHEMA_VERSION:
            return INVALID, [headline,
                             f"run.schema_version is {version}, below the gated schema "
                             f"{GATED_SCHEMA_VERSION}. There is no schema-1 flight log: a run "
                             f"block claiming an older version is a downgrade out of the "
                             f"R2/R3/clock/ground-truth-CPA gates, not a legacy artifact."]
        status, messages = check_schema2(path, log, truth, results_dir, booking, no_birds)
        return status, [f"{headline} | {messages[0]}"] + messages[1:]

    # A BOOKING CANNOT BE BOUND TO A LEGACY LOG. Pre-seam logs carry no `run` block, so they have no
    # time axis at all -- their only axis is the tick index, and 5 Hz is the node's NOMINAL rate,
    # not something those flights measured. There is no honest flown speed to hold an authorisation
    # to, and "we could not check" must not read as "checked". (Nothing automated does this: CI's
    # glob passes no --booking and lays down no sidecar. It is the hand-run case.)
    sidecar = booking_path_for(path)
    bound = booking if booking is not None else (sidecar if sidecar.exists() else None)
    if bound is not None:
        return INVALID, [
            headline,
            f"a booking ({Path(bound).name}) is bound to a PRE-SEAM log with no `run` block. Those "
            f"logs carry no `tick_stamp_sim_s`, so their flown ground speed cannot be measured at "
            f"all and the authorisation cannot be verified -- which is not the same as honoured. "
            f"Bookings apply to schema-2 takes; drop the flag (or the sidecar) to score this log on "
            f"the legacy path it was flown under."]

    # --- CPA (ADR-013 am. 12 R1). Printed ALWAYS, whatever the verdict. -------------------------
    bar = min_bird_clearance_m()
    cpa = closest_approach(log)
    marker = marker_path_for(path)
    disp = displacement_notes(log)               # REPORTED, NEVER GATED (G1/G2)
    if cpa is None:
        return VALID, [f"{headline} | CPA NO-CPA-EVIDENCE (no logged detections with a position, "
                       f"or no flown path) -- this log says nothing about separation"] + disp
    cpa_m, track_id = cpa
    cpa_note = f"CPA {cpa_m:.4f} m to {track_id} (bar: min_bird_clearance_m {bar:.2f} m)"

    if cpa_m < bar:
        breach = (f"{cpa_note} -- FLEW CLOSER THAN THE POLICY WILL COMMAND. The policy refuses to "
                  f"place a setpoint within {bar:.2f} m of a threat; this path came within "
                  f"{cpa_m:.4f} m of one (ADR-013 amendment 12, S1).")
        ack = acknowledgement_problem(path)
        if ack is None:
            return ACKNOWLEDGED, [f"{headline} | {breach}"] + disp + [
                f"acknowledged by {marker.name} -- recorded history, kept as evidence, NOT a "
                f"passing flight"]
        return INVALID, [breach] + disp + [ack]

    if marker.exists():
        return INVALID, [f"{headline} | {cpa_note} -- PASSES"] + disp + [
            f"but a stale acknowledgement marker {marker.name} is present. An acknowledgement "
            f"beside a passing log pre-authorises the next regression on this file; delete the "
            f"marker."]
    return VALID, [f"{headline} | {cpa_note}"] + disp


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("logs", type=Path, nargs="*",
                    help="flight-log JSONs to validate (default: eval/results/*flight_log*.json)")
    # WHICH BIRD TRACK, or NONE AT ALL -- and never both. `--truth` names the track; `--no-birds`
    # declares there was none to name. A command line that said both would be asking the gate to
    # score a flight against a bird the same command line says did not exist.
    truth_group = ap.add_mutually_exclusive_group()
    truth_group.add_argument("--truth", type=Path, default=None,
                    help="bird ground-truth track (eval/results/bird_drive_<stamp>_applied.jsonl) "
                         "for schema-2 logs flown with the real detector. Applies to EVERY log "
                         "named on this command line -- pass one flight at a time. Omitted: a "
                         "flight pinned in TRUTH_BINDINGS uses its bound track; any other "
                         "auto-discovers by sim-time overlap and refuses on 0 or >1 matches.")
    truth_group.add_argument("--no-birds", action="store_true",
                    help="DECLARE that no bird was driven on this flight (a wiring or sensor "
                         "shake-out take, birds parked). Truth resolution is skipped entirely and "
                         "the CPA/truth family prints '" + NA_NO_BIRDS + "' -- never PASS, never a "
                         "number, and the verdict line SAYS SO. Every other gate stays live and "
                         "unchanged, so a bird-less take is still judged on its own bars. REFUSED "
                         "(INVALID) if the log carries any avoidance event, a detection inside the "
                         "threat cylinder, a bird-track filename or a TRUTH_BINDINGS pin -- or if a "
                         "bird track was written within 30 min of this flight on the WALL clock, or "
                         "the launcher's bringup record says the birds pane was armed. A bird the "
                         "DETECTOR never saw leaves no trace in the log: only the truth track can "
                         "show that one. Applies to EVERY log on this command line.")
    ap.add_argument("--booking", type=Path, default=None,
                    help="the booking-gate artifact that AUTHORISED this take "
                         "(eval/results/booking_gate_<UTC>.json, from scripts/"
                         "predict_forward_lead.py exiting 0). The flight's own poses are then "
                         "measured against the speed it books: a take flown faster is not the "
                         "authorised take (INVALID). MANDATORY for a dodge take, unnecessary for "
                         "the NDVI survey. Omitted: a `<log-stem>.booking.json` sidecar beside the "
                         "log is used if present, otherwise an avoidance log gets a WARNING that "
                         "its authorisation is unverified. Applies to EVERY log on this command "
                         "line -- pass one flight at a time.")
    args = ap.parse_args(argv)

    paths = args.logs or sorted(RESULTS_DIR.glob("*flight_log*.json"))
    if not paths:
        print("[check_live_flight_log] SKIP: no eval/results/*flight_log*.json present -- "
              "nothing to validate (eval/results/ is gitignored; exit 0).")
        return 0

    # THE DECLARATION RIDES IN THE VERDICT WORD, not only in the notes. `VALID` and `PASS` are the
    # two strings CI, the dashboard and a scrollback reader consume, and a take whose safety bar was
    # never measured may not print the same word as one that cleared it -- the same doctrine as
    # `check_tree_positions`' "PASS (vacuous)" and this file's own "R2/R3 PASS (vacuous)" notes.
    declared = f" (DECLARED BIRD-LESS -- gt_cpa_m {NA_NO_BIRDS})" if args.no_birds else ""
    n_invalid = n_acknowledged = n_declared = 0
    for path in paths:
        status, messages = check_file(path, truth=args.truth, booking=args.booking,
                                      no_birds=args.no_birds)
        if args.no_birds and status in (VALID, ACKNOWLEDGED):
            n_declared += 1
        if status == INVALID:
            n_invalid += 1
            print(f"[check_live_flight_log] INVALID: {path}", file=sys.stderr)
            for m in messages:
                print(f"    - {m}", file=sys.stderr)
        elif status == ACKNOWLEDGED:
            # stderr, own word, own counter: an acknowledged safety finding must never read like a
            # pass in a scrollback or a CI log.
            n_acknowledged += 1
            print(f"[check_live_flight_log] ACKNOWLEDGED SAFETY FINDING{declared}: {path}",
                  file=sys.stderr)
            for m in messages:
                print(f"    - {m}", file=sys.stderr)
        elif status == SKIP:
            print(f"[check_live_flight_log] SKIP: {messages[0]}")
        else:
            print(f"[check_live_flight_log] VALID{declared}: {path} ({messages[0]})")
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
    unmeasured = (f" ({n_declared} of {len(paths)} DECLARED BIRD-LESS: the "
                  f"{min_bird_clearance_m():.2f} m clearance bar was NOT measured on those)"
                  if n_declared else "")
    if n_acknowledged:
        print(f"[check_live_flight_log] PASS WITH {n_acknowledged} ACKNOWLEDGED SAFETY "
              f"FINDING(S){unmeasured}: {len(paths) - n_acknowledged} of {len(paths)} log(s) clean. "
              f"The acknowledged log(s) above are kept as recorded history and are NOT evidence of "
              f"a safe flight.", file=sys.stderr)
        return 0
    print(f"[check_live_flight_log] PASS{unmeasured}: all present flight logs valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
