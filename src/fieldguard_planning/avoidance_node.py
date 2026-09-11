"""ROS 2 bringup node that runs the reactive-avoidance loop live against ArduPilot SITL + Gazebo.

Wires the confirmed AP_DDS interface (ADR-005) to the tested loop:

    /ap/pose/filtered ──▶ DroneState ──┐
    detection_source  ──▶ [Detection] ─┼─▶ AvoidancePolicy.decide_multi ─▶ AvoidanceManeuver
                                        │                                          │
                    mission model ──▶ current_wp_index                            ▼
                                                        AvoidanceExecutor.step ─▶ Ros2VehicleSink
                                                                                   │
                                                            /ap/mode_switch + /ap/cmd_gps_pose

DETECTION SOURCE is a seam with three live implementations, chosen at the command line -- and never
more than ONE of them per flight:

    --detect   the REAL NDVI detector (ADR-003 am. 7, ADOPTED), and the DEFAULT of
               `--detection-source`: `/fg/ndvi/image` -> `ndvi_detect` blobs -> world-ENU positions
               ranged by APPARENT SIZE (ADR-009 rule 2).
    --detect --detection-source depth
               the FORWARD DEPTH detector: `/fg/depth/image` -> `depth_segment.DepthSegmenter`
               boxes -> world-ENU positions at the MEASURED depth (ADR-020's seam, no radius prior,
               no ground plane). SHIPS OFF -- a run without the flag is behaviourally unchanged.
    --demo     the scripted stand-in bird at ENU (30,30,15). Kept, not deleted: it is the
               regression-gate exception (ADR-013 am. 2) and the A/B arm against the real
               detector -- a flight where the demo dodges and the detector does not is a
               perception finding, and that comparison needs both sources to still exist.

THE TWO DETECTORS ARE EXCLUSIVE, BY CONSTRUCTION AND NOT BY CARE: this node holds exactly ONE
`detection_source` and subscribes only to THAT source's own image + camera_info pair, so
`--detection-source depth` disarms the NDVI detector for that run (the orchestrator's call on
DESIGN §7 Q2 -- one detection source per flight; running both would cost up to ~50 ms of a 200 ms
tick and give one flight two sources of truth, and a combined mode is a product decision and a
later flag, not a default). Which one ran is read back off the source's own `SOURCE_TAG` into the
flight log -- never inferred from `hasattr(source, "on_frame")`, which is true of both and labelled
a depth flight `ndvi_blob`.

ONE CLOCK: GAZEBO SIM SECONDS (binding, 2026-08-24). Three clocks coexist on this stack -- NDVI
frames carry Gazebo sim time (ADR-007), `/ap/pose/filtered` carries ArduPilot's own clock (SITL runs
`use_sim_time=false`), and a node's `get_clock()` here is wall time. Until this build the policy was
handed t = elapsed-since-node-start and `now_s` was never passed at all, so ADR-009's staleness gate
could not evaluate; had it been passed, an elapsed `now_s` against absolute gz stamps yields
NEGATIVE ages -- every detection reads fresh forever, and the bug is invisible because unstamped
detections already fail OPEN. So this node streams Gazebo's own clock natively (the SAME mechanism
`record_node`/`clip_recorder` already ship -- a `gz topic -e -t /clock` subprocess feeding
`StreamingClockParser`, never a bridged `/clock`: at ~350 msg/s bridging it collapsed the fused
frame rate ~8x, measured live 2026-08-18), tags every pose into a `PoseBuffer` in that domain, pairs
each NDVI frame to the pose nearest its own stamp, and passes that same gz reading as `now_s`.
`_on_tick` additionally TRIPWIRES the inversion: a detection stamped more than
`CLOCK_DOMAIN_BOUND_S` in the future is counted as a clock-domain violation, and the flight-log gate
fails any run with a non-zero count.

rclpy imports lazily inside build_node()/main() so the repo's stdlib test suite can import the
sibling pure modules without a ROS 2 environment; the whole per-tick decision path lives in
`AvoidanceLoop` below, which has no rclpy in it at all and is unit-tested off-sim.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from .avoidance_types import AvoidanceManeuver, Detection, DroneState
from .avoidance_policy import AvoidancePolicy, _params_dict
from .avoidance_executor import AvoidanceExecutor
from .geofence import GeofenceMap
from .coverage import build_grid, derive_swath_half_width_m, load_field_polygon

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# (t_seconds, drone_state_or_None) -> current detections in world-ENU. The real NDVI detector ignores
# both args (it works from camera frames); the demo source uses them for proximity triggering.
DetectionSource = Callable[[float, Optional[DroneState]], List[Detection]]
ENU = Tuple[float, float, float]

# The altitude this node flies and derives its coverage swath at. It MUST equal
# `config/field_polygon.json`'s `mission_altitude_m` (15.0), which is what the mission generator
# planned the lanes at and what `coverage.DEFAULT_SWATH_HALF_WIDTH_M` is derived from -- two
# altitudes would mean the ledger claimed a swath the camera never had at the height actually flown.
# Kept as a literal rather than read from the config (this node's other constants are literals too),
# and cross-pinned by `test_avoidance_node_seam.TestTheNodeFliesTheCameraDerivedSwath`.
CRUISE_ALT_M = 15.0
CONTROL_HZ = 5.0

# NOTE: the swath half-width is NOT declared here either. It is derived from the camera at the
# altitude this node actually cruises at (`coverage.derive_swath_half_width_m(CRUISE_ALT_M)`,
# 6.886 m) -- a literal 7.5 here was the lane-spacing/2 assumption wearing a second home, and it
# over-claimed the ledger by a 1.228 m strip between every lane pair (ADR-016).

# NOTE: the ADR-009 staleness bound is NOT declared here. It is `PolicyParams.max_detection_age_s`
# (1.0 s) and nowhere else -- this node armed it with a local constant while the policy default
# stayed None, which is one knob with two homes and left the flight-log gate's upper bound dead
# code. The flown value still travels in the log's run.policy_params.

# Clock-domain tripwire. A detection cannot legitimately be stamped in the FUTURE by more than the
# jitter between the frame's stamp and the clock reading beside it (measured max 0.156 s, and even
# that is an age, i.e. the other sign). Half a second of "future" therefore means the two numbers
# are not on the same clock at all -- which is what an elapsed `now_s` against absolute gz stamps
# looks like from tick one (elapsed ~0-300 s vs gz absolute), and is otherwise SILENT because a
# negative age passes the staleness gate. Loud beats invisible.
CLOCK_DOMAIN_BOUND_S = 0.5

# How long `--detect` waits for the first Gazebo clock reading before refusing to start. A startup
# check is cheaper than a burnt take: without the clock there is no staleness gate, no stamp-paired
# pose, and no gz-time axis for the flight log to be scored against ground truth.
GZ_CLOCK_WAIT_S = 10.0

# ...and the same refusal for the OTHER input a frame detector cannot work without. Until this was
# added the clock was the node's only startup gate: a take whose `camera_info` never arrived -- the
# camera pipeline started after this shell, a topic name that changed, a bridge that did not come
# up -- flew BLIND for the whole flight, counting and dropping every frame (`dropped_no_intrinsics`)
# while the 2 s heartbeat printed the normal-looking `nearest_bird=none in view`. Nothing else
# catches it: `check_render_alive.py` probes the image topics and not their `camera_info`, and the
# flight-log gate's own DETECTOR NEVER RAN check reads the artifact AFTER the take is burnt.
# Deliberately generous against the 5 Hz render, and it only ever costs time on a flight that was
# already going to produce nothing (measured off-sim: 1200 frames in, 1200 dropped, 0 detections).
CAMERA_INFO_WAIT_S = 20.0

# The fused NDVI band and ITS OWN camera_info pass-through (ndvi_node publishes both). Deliberately
# not the bridge's rgb camera_info: these intrinsics must describe the frames actually consumed, and
# subscribing the rgb band would add a third reader to the hop that has starved twice.
NDVI_IMAGE_TOPIC = "/fg/ndvi/image"
NDVI_INFO_TOPIC = "/fg/ndvi/camera_info"
# 32-bit float, one channel: NDVI in [-1, 1]. The SAME node also publishes `/fg/ndvi/preview` as
# rgb8 off the same fused array (`ndvi_node.NDVI_ENCODING` / `PREVIEW_ENCODING`), which is why the
# encoding is asserted rather than assumed -- the two topics differ by one word in a launch line.
NDVI_IMAGE_ENCODING = "32FC1"

# The forward depth aperture (ADR-019/020). `/fg/depth/camera_info` is DERIVED by gz-sensors from
# `<topic>`, not declared -- `config/depth_camera.json` records why, and the runbook's gate D1
# checks it live. Both names are the ones the live bridge publishes, and the intrinsics are taken
# from the message and never from that config (depth_detect rule 4).
DEPTH_IMAGE_TOPIC = "/fg/depth/image"
DEPTH_INFO_TOPIC = "/fg/depth/camera_info"
# 32-bit float, one channel: pinhole Z-depth in METRES, +inf beyond far clip, -inf inside near.
DEPTH_IMAGE_ENCODING = "32FC1"

# The two frame detectors' own tags, spelled here as literals rather than imported because
# importing either detector module would pull numpy/scipy into a node that must stay importable on
# a bare interpreter (`--demo` has to parse its arguments on an image that cannot run `--detect`).
# Cross-pinned to `ndvi_detect.SOURCE_TAG` / `depth_detect.SOURCE_TAG` by
# tests/fieldguard_planning/test_avoidance_node_depth_seam.py, so the two spellings cannot drift.
NDVI_SOURCE_TAG = "ndvi_blob"
DEPTH_SOURCE_TAG = "depth_blob"

# Which (image, camera_info) pair a frame-consuming source needs, keyed by the source's OWN tag.
# The node subscribes to exactly ONE entry -- the one belonging to the source that was armed --
# which is what makes the two detectors exclusive by construction rather than by care.
FRAME_TOPICS = {
    NDVI_SOURCE_TAG: (NDVI_IMAGE_TOPIC, NDVI_INFO_TOPIC),
    DEPTH_SOURCE_TAG: (DEPTH_IMAGE_TOPIC, DEPTH_INFO_TOPIC),
}

# `--detection-source` choices. The default is the NDVI detector: the depth path ships OFF.
KIND_NDVI = "ndvi"
KIND_DEPTH = "depth"
DETECTION_SOURCE_KINDS = (KIND_NDVI, KIND_DEPTH)

# What `detection_source_name` calls a frame detector that declares no tag. Deliberately NOT
# `DEMO_SOURCE_TAG` and deliberately not a guess: the flight-log gate treats a demo bird's logged
# position as exact ground truth, so mislabelling a real detector that way would score an ESTIMATE
# against itself. An unknown tag is not in the gate's DETECTOR_SOURCES, so such a flight is
# UNSCOREABLE -- which is the fail-safe direction.
UNTAGGED_FRAME_SOURCE = "untagged_frame_source"

# `log["run"]` schema. Version 2 is the first flight-log contract that carries a time axis, the
# clock provenance, the detector provenance and the policy parameters -- i.e. the first that can be
# scored against ground truth. Legacy logs have no `run` key at all and keep exactly the verdict
# they were flown under (scripts/check_live_flight_log.py branches on this).
RUN_SCHEMA_VERSION = 2


def _nearest_upcoming_wp(pos_xy: Tuple[float, float], mission_xy: Sequence[Tuple[float, float]]) -> int:
    """Derive the mission's 'current waypoint' index the way ADR-006 says a real adapter must (AP_DDS
    exposes no mission-current service): the nearest mission waypoint, from the drone's pose + the
    loaded mission. Approximate but sufficient — the executor uses it only for resume bookkeeping;
    ArduPilot's MIS_RESTART=0 owns the actual AUTO resume."""
    best_i, best_d = 0, math.inf
    for i, (wx, wy) in enumerate(mission_xy):
        d = math.hypot(pos_xy[0] - wx, pos_xy[1] - wy)
        if d < best_d:
            best_i, best_d = i, d
    return best_i


# The --demo bird: a stand-in threat on lane x=30 at cruise altitude. It is NOT the NDVI detector's
# understudy any more (that shipped) -- it is the deterministic regression arm (ADR-013 am. 2).
DEMO_BIRD_ENU: ENU = (30.0, 30.0, 15.0)
# Provenance tag both demo sources stamp onto their detections. It used to be the `Detection` default
# "ndvi_blob", i.e. a virtual bird claiming to be an NDVI blob in every log ever flown. The flight-log
# gate now BRANCHES on this: a demo bird's logged position IS exact ground truth (it is a constant we
# chose), so detection-CPA is the correct safety gate for it, while a real detection's position is an
# estimate that may not referee itself.
DEMO_SOURCE_TAG = "demo_virtual"


def scripted_bird_source(birds) -> DetectionSource:
    """Time-windowed detections: list of (track_id, position_enu, t0_s, t1_s). Ignores drone position.
    Pure/stdlib, unit-tested. Useful for deterministic tests; the --demo uses proximity instead."""
    def src(t: float, drone: Optional[DroneState] = None) -> List[Detection]:
        return [Detection(pos, frame_id=int(t * CONTROL_HZ), track_id=tid, source=DEMO_SOURCE_TAG)
                for tid, pos, t0, t1 in birds if t0 <= t <= t1]
    return src


def proximity_bird_source(bird_enu: ENU, trigger_radius_m: float = 10.0,
                          linger_s: float = 12.0) -> DetectionSource:
    """A demo bird that appears when the drone FIRST comes within `trigger_radius_m` of `bird_enu`,
    lingers `linger_s`, then 'flies off'. Position-triggered, not wall-clock-timed, so the demo shows
    dodge -> hold -> resume regardless of when (or how long after node start) the drone reaches the
    spot. Uses only DIFFERENCES of `t`, so it behaves identically on the gz sim clock and on the
    node-elapsed fallback. Stateful closure; pure/stdlib, unit-tested."""
    bx, by, _ = bird_enu
    state = {"trigger_t": None}

    def src(t: float, drone: Optional[DroneState]) -> List[Detection]:
        if drone is None:
            return []
        if state["trigger_t"] is None:
            if math.hypot(drone.position_enu[0] - bx, drone.position_enu[1] - by) <= trigger_radius_m:
                state["trigger_t"] = t
        if state["trigger_t"] is not None and (t - state["trigger_t"]) <= linger_s:
            return [Detection(bird_enu, frame_id=int(t * CONTROL_HZ), track_id="demo_bird_0",
                              source=DEMO_SOURCE_TAG)]
        return []
    return src


# --------------------------------------------------------------------------------------------------
# The per-tick decision path -- pure, stdlib, no rclpy. Lives here rather than inside the Node class
# for the same reason `ndvi_node`'s message assembly does: it is arithmetic that is right or wrong
# off-sim, and the clock-domain bug this build exists to kill is invisible unless it can be driven
# from a test with a deliberately WRONG clock.
# --------------------------------------------------------------------------------------------------
class AvoidanceLoop:
    """detection source -> policy -> executor, once per control tick, plus the clock accounting the
    flight log is scored on.

    THE TWO TIME ARGUMENTS ARE NOT THE SAME NUMBER and must not be merged:
      * `now_s` is the ONE clock the policy and the artifact use -- absolute Gazebo sim seconds off
        the native clock stream, the same domain `Detection.stamp_s` is in. None means no reading
        yet, in which case the staleness gate correctly cannot fire (it fails OPEN on missing data)
        and the tick's stamp is recorded as null rather than invented.
      * `source_t` is what the pluggable detection source is handed. It equals `now_s` whenever
        there is one; without a clock it is the node's elapsed seconds, purely so the legacy
        `--demo` bird still triggers on a stack with no `gz` CLI. It never reaches the policy and
        never reaches the flight log.
    """

    def __init__(self, policy: AvoidancePolicy, geofence: GeofenceMap, executor: AvoidanceExecutor,
                 detection_source: Optional[DetectionSource] = None,
                 warn: Optional[Callable[[str], None]] = None,
                 clock_domain_bound_s: float = CLOCK_DOMAIN_BOUND_S):
        self.policy = policy
        self.geofence = geofence
        self.executor = executor
        self.detection_source: DetectionSource = detection_source or (lambda t, d: [])
        self.warn = warn or (lambda msg: None)
        self.clock_domain_bound_s = float(clock_domain_bound_s)

        # One entry per completed `executor.step()`. `step` records exactly one flown-path position
        # on every branch (proceed/hold/divert/gate_reject), so `index == tick - 1` holds by
        # construction and the flight-log gate can assert the two lengths match -- a consistency
        # check the artifact cannot fake.
        self.tick_stamp_sim_s: List[Optional[float]] = []
        self.clock_domain_violations = 0
        self.ticks_without_clock = 0
        self.last_detections: List[Detection] = []

    def tick(self, drone: DroneState, now_s: Optional[float], source_t: float) -> AvoidanceManeuver:
        dets = list(self.detection_source(source_t, drone))
        self.last_detections = dets
        if now_s is None:
            self.ticks_without_clock += 1
        else:
            self._check_clock_domain(dets, now_s)
        maneuver = self.policy.decide_multi(dets, drone, self.geofence, now_s=now_s)
        self.executor.step(drone, maneuver)
        self.tick_stamp_sim_s.append(now_s)
        return maneuver

    def _check_clock_domain(self, dets: Sequence[Detection], now_s: float) -> None:
        for det in dets:
            if det.stamp_s is None or (det.stamp_s - now_s) <= self.clock_domain_bound_s:
                continue
            self.clock_domain_violations += 1
            if self.clock_domain_violations in (1, 10):
                self.warn(
                    f"CLOCK DOMAIN VIOLATION x{self.clock_domain_violations}: detection stamped "
                    f"{det.stamp_s - now_s:.3f} s in the FUTURE (stamp={det.stamp_s:.3f}, "
                    f"now={now_s:.3f}). These are not the same clock -- the staleness gate is "
                    f"scoring negative ages as fresh. Expected: both are absolute Gazebo sim "
                    f"seconds.")

    def clock_block(self, readings: int) -> dict:
        """The flight log's `run.clock`. `source` is what the gate keys on: only a run that actually
        read Gazebo's clock has comparable detection ages or a sim-time axis to score ground-truth
        CPA against."""
        streamed = readings > 0
        return {
            "source": "gz_clock_stream" if streamed else "node_elapsed_fallback",
            "domain": "absolute Gazebo sim seconds (/clock via native gz-transport, ADR-007)",
            "readings": int(readings),
            "violations": int(self.clock_domain_violations),
            "violation_bound_s": self.clock_domain_bound_s,
            "ticks_without_clock": int(self.ticks_without_clock),
            "ticks_total": len(self.tick_stamp_sim_s),
            "note": ("Detection.stamp_s (the /fg/ndvi/image header) and the now_s passed to "
                     "decide_multi are both absolute Gazebo sim seconds, so age = now_s - stamp_s "
                     "is a true sim-time age. violations counts detections stamped further than "
                     "violation_bound_s in the future -- the signature of an elapsed clock being "
                     "compared against absolute stamps."),
        }


# --------------------------------------------------------------------------------------------------
# Command line -> detector configuration -> flight-log provenance. Pure; tested off-sim.
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DetectorConfig:
    """What `--detect` was armed with, and WHERE EVERY NUMBER IN IT CAME FROM.

    The threshold is the NDVI detector (`mask = ndvi < thresh`), it differs by half a unit between
    the synthetic and real renders, and -0.61 is still PROVISIONAL -- so the value alone is not
    evidence. A flight log that records the number without its provenance cannot answer "was this
    the adopted default or something someone tried?", which is the question every re-reading of the
    artifact starts with.

    ONE OBJECT, TWO HALVES, and exactly one of them is filled: `detector_config_from_args` resolves
    the half belonging to the `--detection-source` that was armed and leaves the other at its
    defaults, so a depth flight's config cannot record an NDVI threshold it never used.

    The depth half is the WHOLE `depth_segment.DepthSegmenterParams` as one frozen object rather
    than seven scalars copied out of it: the constants have one home (the module that was scored),
    a copy here would be a second, and the log's reader can then see there is nothing else. Typed
    `object` only because naming the class would import numpy + scipy at module scope, which
    `--demo` must not need."""
    # -- the NDVI half (`--detection-source ndvi`, the default) -----------------------------------
    thresh: Optional[float] = None
    thresh_provenance: str = ""
    thresh_provisional: bool = True
    min_area: Optional[int] = None
    max_area: Optional[int] = None
    # -- the depth half (`--detection-source depth`) ----------------------------------------------
    depth_params: Optional[object] = None          # a depth_segment.DepthSegmenterParams
    depth_params_provenance: str = ""
    # Provisional until something says otherwise, on BOTH halves: an unprovenanced number is a
    # number someone typed. The adopted defaults set it explicitly -- True for the NDVI threshold
    # (ADR-003 am. 7 adopted the detector, not the threshold's position), False for the depth
    # params (every one of them is the output of the recorded sweep named in their provenance).
    depth_params_provisional: bool = True


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """CLI for `python3 -m fieldguard_planning.avoidance_node`.

    A CLI argument and not a ROS 2 parameter, deliberately: there is not one `declare_parameter`
    anywhere in `src/` -- every node here is configured by CLI args plus `config/*.json` -- and the
    number that matters is the one RECORDED IN THE ARTIFACT, not the one queryable at runtime. The
    knobs stop at the detector: every safety bar the policy vets against (the swept-path tree
    margin, the degenerate-range flag, the bird-clearance minimum) has exactly one home in
    `PolicyParams` and is deliberately NOT reachable from this command line -- the flight-log gate
    reads those bars from that same dataclass, so a flag here could let gate and control law
    disagree silently.

    The detector defaults are `None` here and resolved in `detector_config_from_args`, for two
    reasons that are really one: `ndvi_detect` owns those constants (a second copy in an argparse
    default is a second source of truth), and importing it pulls numpy + scipy -- which would make
    `--demo` fail to even parse its arguments on an image that cannot run `--detect`."""
    ap = argparse.ArgumentParser(prog="fieldguard_planning.avoidance_node",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--detect", action="store_true",
                    help="arm the real NDVI blob detector on the detection_source seam "
                         "(ADR-003 am. 7 / ADR-009). Mutually exclusive with --demo.")
    ap.add_argument("--demo", action="store_true",
                    help=f"inject the scripted stand-in bird at ENU {DEMO_BIRD_ENU} "
                         f"(ADR-013 am. 2 regression arm). Mutually exclusive with --detect.")
    ap.add_argument("--ndvi-thresh", type=float, default=None, dest="ndvi_thresh",
                    help="detector threshold, mask = ndvi < thresh (default: "
                         "ndvi_detect.REAL_RENDER_THRESH, the ADR-003 am. 7 real-render value "
                         "-- PROVISIONAL)")
    ap.add_argument("--min-area", type=int, default=None, dest="min_area",
                    help="minimum blob area in post-morphology pixels "
                         "(default: ndvi_detect.DEFAULT_MIN_AREA)")
    ap.add_argument("--max-area", type=int, default=None, dest="max_area",
                    help="maximum blob area in post-morphology pixels "
                         "(default: ndvi_detect.DEFAULT_MAX_AREA)")
    ap.add_argument("--detection-source", choices=list(DETECTION_SOURCE_KINDS), default=KIND_NDVI,
                    dest="detection_source",
                    help=f"WHICH real detector --detect arms (default: {KIND_NDVI}). "
                         f"'{KIND_DEPTH}' flies the forward depth aperture instead and DISARMS the "
                         f"NDVI detector for that run -- one detection source per flight. The "
                         f"depth segmenter's constants are not reachable from this command line: "
                         f"they are the adopted set in depth_segment.DEFAULT_PARAMS, and a knob "
                         f"here would be a second home for numbers a scored dataset chose.")
    args = ap.parse_args(list(argv) if argv is not None else None)
    if args.detect and args.demo:
        ap.error("--detect and --demo are mutually exclusive: a flight has ONE detection source, "
                 "and a log that mixed a virtual bird with real detections could not be scored "
                 "against either kind of ground truth")
    if args.detection_source != KIND_NDVI and not args.detect:
        ap.error(f"--detection-source {args.detection_source} selects WHICH real detector --detect "
                 f"arms; on its own it arms nothing. A run that asked for the depth detector and "
                 f"silently flew with none would be an observation run wearing a dodge take's "
                 f"command line. Pass --detect --detection-source {args.detection_source}.")
    return args


def detector_config_from_args(args: argparse.Namespace) -> DetectorConfig:
    """Freeze the CLI intent against the armed detector's own defaults. Whether a number is still
    PROVISIONAL is decided by whether the operator passed one at all -- not by comparing floats to
    the default, which would silently re-label an explicit `--ndvi-thresh -0.61` as a default.

    The DEPTH half takes `depth_segment.DEFAULT_PARAMS` whole, with `DEFAULT_PARAMS_PROVENANCE` as
    its provenance string: every one of those five constants is the output of the recorded sweep
    that string names, so the depth config is NOT provisional -- and there is no CLI override for
    them, which is what keeps that true."""
    if getattr(args, "detection_source", KIND_NDVI) == KIND_DEPTH:
        from .depth_segment import DEFAULT_PARAMS, DEFAULT_PARAMS_PROVENANCE
        return DetectorConfig(depth_params=DEFAULT_PARAMS,
                              depth_params_provenance=DEFAULT_PARAMS_PROVENANCE,
                              depth_params_provisional=False)
    from .ndvi_detect import DEFAULT_MAX_AREA, DEFAULT_MIN_AREA, REAL_RENDER_THRESH
    explicit = args.ndvi_thresh is not None
    return DetectorConfig(
        thresh=float(args.ndvi_thresh) if explicit else float(REAL_RENDER_THRESH),
        thresh_provenance=("operator-supplied --ndvi-thresh" if explicit else
                           "node default REAL_RENDER_THRESH (ADR-003 am. 7, gate2 bird/soil "
                           "midpoint of the committed real-render evidence)"),
        thresh_provisional=not explicit,
        min_area=int(args.min_area) if args.min_area is not None else int(DEFAULT_MIN_AREA),
        max_area=int(args.max_area) if args.max_area is not None else int(DEFAULT_MAX_AREA),
    )


def detection_source_name(source) -> str:
    """Provenance tag for the flight log, read off the source's OWN `SOURCE_TAG` rather than
    inferred -- which is this function's stated principle and was, until the depth wiring landed,
    not what it did: `hasattr(source, "on_frame")` is true of BOTH frame detectors, so a depth
    flight would have been logged as `ndvi_blob` (DESIGN §6 item 2).

    Three answers, and the fallback is the interesting one. A frame detector that declares no tag
    is NOT called a demo bird -- the flight-log gate treats a demo bird's logged position as exact
    ground truth, and a real estimate scored against itself is the failure schema 2 exists to stop.
    It gets a name the gate does not know, which makes the flight unscoreable rather than
    mislabelled. A plain callable is a scripted stand-in; None is an observation run."""
    if source is None:
        return "none"
    tag = getattr(source, "SOURCE_TAG", None)
    if isinstance(tag, str) and tag:
        return tag
    return UNTAGGED_FRAME_SOURCE if hasattr(source, "on_frame") else DEMO_SOURCE_TAG


def _intrinsics_block(intr, info_topic: str, config_name: str) -> Optional[dict]:
    """The live intrinsics as the log records them, or None before the first `camera_info`.

    Never the config file: the config is what we ASKED for, the message is what we GOT (the rule
    `clip_recorder` set and `depth_detect` rule 4 repeats), and the provenance string says so on
    the artifact's face so a reader does not have to trust that it happened."""
    if intr is None:
        return None
    return {"image_width_px": int(intr.width_px), "image_height_px": int(intr.height_px),
            "fx": float(intr.fx), "fy": float(intr.fy),
            "cx": float(intr.cx), "cy": float(intr.cy),
            "provenance": f"live {info_topic} (not {config_name})"}


def detector_log_block(source, cfg: Optional[DetectorConfig]) -> dict:
    """`log["run"]["detector"]`. Every number is read back from the SOURCE that actually ran, not
    from the CLI intent -- the only provenance the config contributes is where a constant came from
    and whether it is still provisional, which the source has no way to know."""
    name = detection_source_name(source)
    if name == DEPTH_SOURCE_TAG:
        return _depth_detector_log_block(source, cfg)
    if name != NDVI_SOURCE_TAG:
        return {
            "source": name,
            "module": "fieldguard_planning.avoidance_node",
            # The two unknown cases are DIFFERENT and the note must not say the wrong one: a source
            # that declares a tag this node has no branch for is not a source that declares none,
            # and a note describing the opposite of what happened is worse than no note.
            "note": ("scripted stand-in bird: its logged position IS exact ground truth (a constant "
                     "we chose), so detection-CPA is the correct safety gate for this flight"
                     if name == DEMO_SOURCE_TAG else
                     "no detection source armed -- observation run, no avoidance claimed"
                     if name == "none" else
                     "a frame-consuming detector that declares no SOURCE_TAG: this flight cannot "
                     "be scored, because nothing here can say what its detections are worth"
                     if name == UNTAGGED_FRAME_SOURCE else
                     f"a detection source declaring SOURCE_TAG {name!r}, which this node has no "
                     f"log branch for: the tag was read off the source that ran, but nothing here "
                     f"can say what its detections are worth, so the flight is unscoreable"),
        }
    return {
        "source": name,
        "module": "fieldguard_planning.ndvi_detect",
        "thresh": float(source.thresh),
        "thresh_provenance": (cfg.thresh_provenance if cfg and cfg.thresh_provenance
                              else "unknown (no DetectorConfig)"),
        "thresh_provisional": bool(cfg.thresh_provisional) if cfg else True,
        "min_area": int(source.min_area),
        "max_area": int(source.max_area),
        "radius_prior_m": float(source.radius_prior_m),
        "range_model": ("apparent_size_ray (ADR-009 rule 2); ground-plane projection is never used "
                        "-- it places a flying bird at z=0, outside the threat cylinder"),
        "intrinsics": _intrinsics_block(getattr(source, "intr", None), NDVI_INFO_TOPIC,
                                        "config/ndvi_camera.json"),
        "counters": source.counters(),
    }


def _depth_detector_log_block(source, cfg: Optional[DetectorConfig]) -> dict:
    """The depth branch of `detector_log_block` (DESIGN §6 item 3).

    Two modules ran, so both are named and both are read off the objects that ran rather than
    written down: the SEGMENTER (image space, where the params live) and the SEAM (un-projection,
    where the range refusals live). Two `counters()` dicts for the same reason -- they measure
    different things and summing them would hide which half dropped a frame.

    Plain ints and floats only: this dict crosses a `json.dumps` into the flight log, where a numpy
    scalar raises TypeError."""
    from dataclasses import asdict, is_dataclass

    seg = getattr(source, "segmenter", None)
    params = getattr(seg, "params", None)
    if params is None and cfg is not None:
        params = cfg.depth_params            # a segmenter that keeps none: fall back to the intent
    seg_counters = getattr(seg, "counters", None)
    return {
        "source": detection_source_name(source),
        "module": (type(seg).__module__ if seg is not None else "unknown"),
        "seam_module": type(source).__module__,
        # The WHOLE frozen configuration as one object -- see DetectorConfig's docstring for why it
        # is not seven scalars.
        "params": (asdict(params) if is_dataclass(params) else None),
        "params_provenance": (cfg.depth_params_provenance if cfg and cfg.depth_params_provenance
                              else "unknown (no DetectorConfig)"),
        "params_provisional": bool(cfg.depth_params_provisional) if cfg else True,
        # The seam's own EXCLUSIVE refusal window, recorded beside the segmenter's clip window so
        # the artifact itself shows the two agreed rather than leaving it to a test.
        "min_range_m": float(source.min_range_m),
        "max_range_m": float(source.max_range_m),
        "range_model": ("measured depth (ADR-020); no radius prior, no ground-plane projection"),
        "static_map_annotator": (None if getattr(source, "static_map_annotator", None) is None else
                                 "geofence 3D volume test -- ANNOTATE + COUNT ONLY, never suppress "
                                 "(depth_detect rule 9): detections_near_known_obstacle is a "
                                 "clutter denominator, not a drop count"),
        "intrinsics": _intrinsics_block(getattr(source, "intr", None), DEPTH_INFO_TOPIC,
                                        "config/depth_camera.json"),
        "counters": source.counters(),
        "segmenter_counters": (seg_counters() if callable(seg_counters) else None),
    }


def serialise_flight_log(log: dict) -> str:
    """`json.dumps` the flight log, and NEVER lose a flight to a formatting error.

    `dump_flight_log` runs in `main`'s `finally`, so a `TypeError` raised while encoding (a numpy
    scalar in a counters dict is the live shape of this: `Object of type int64 is not JSON
    serializable`) writes NO FILE AT ALL and replaces whatever actually ended the flight. Unreachable
    with the shipped detectors -- both `counters()` methods coerce to plain ints, and that is
    pinned by test on the real path -- but the cost of being wrong about it is the whole take's
    evidence, which is not a trade worth taking for three lines.

    The degraded log is deliberately WORSE-LOOKING than a clean one, not quietly equivalent: the
    offending values become `repr` STRINGS (so any gate reading them as numbers says 'non-numeric'
    rather than scoring them) and a top-level key says so on the artifact's face."""
    import json

    try:
        return json.dumps(log, indent=2)
    except TypeError as exc:
        degraded = dict(log)
        degraded["log_serialisation_degraded"] = (
            f"json.dumps refused a value in this log ({exc}); it was re-encoded with repr() so the "
            f"flight's evidence survived. Every value that took that path is now a STRING and is "
            f"not numeric data -- find it and fix the writer (a numpy scalar in a counters dict is "
            f"the usual cause) rather than reading through it.")
        return json.dumps(degraded, indent=2, default=repr)


def build_run_block(*, policy_params: dict, clock: dict, tick_stamp_sim_s: Sequence[Optional[float]],
                    detector: dict) -> dict:
    """`log["run"]` -- the half of the flight log that says under what contract the flight was
    flown. Written by the NODE, not the executor: `AvoidanceExecutor.flight_log` keeps its exact
    shape, so every legacy log (and every CI-generated scenario log) still validates on the path it
    was written for."""
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "policy_params": policy_params,
        "clock": clock,
        "tick_stamp_sim_s": list(tick_stamp_sim_s),
        "detector": detector,
    }


def default_mission_xy() -> List[Tuple[float, float]]:
    """Load the boustrophedon mission as world-ENU waypoints (for current-waypoint derivation)."""
    from .mission_waypoints import parse_qgc_wpl, mission_xy_path
    from .ros2_adapter import load_home
    home_lat, home_lon, _ = load_home()
    items = parse_qgc_wpl(REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints")
    return mission_xy_path(items, home_lat, home_lon)


def build_detection_source(cfg: DetectorConfig, kind: str = KIND_NDVI):
    """Construct THE ONE real detector this flight will fly. Imported HERE and nowhere else at
    module scope: both detector cores pull numpy + scipy, and a missing scipy must fail with the
    rebuild instruction rather than at the top of a module the stdlib test suite imports.

    Returns exactly one object, which is the whole of the exclusion: there is no arrangement of
    flags that leaves two detectors armed, because there is one variable to put one in.

    The depth arm wires three things the NDVI arm has no equivalent of:
      * the segmenter, constructed from the ADOPTED `DEFAULT_PARAMS` the config carries (never
        field-by-field: the frozen object IS the configuration);
      * the seam's refusal window taken FROM those same params, so the segmenter's clip window and
        the seam's exclusive (min, max) are one number and not two;
      * the geofence annotator (DESIGN §6 item 5) -- ANNOTATE + COUNT, never suppress. The forward
        frame is full of mapped canopy from ~24.4 m, and this is what gives the flight log a
        clutter denominator without a filter that could also delete a bird beside a tree."""
    if kind == KIND_DEPTH:
        from .depth_detect import DepthDetectionSource, geofence_annotator
        from .depth_segment import DEFAULT_PARAMS, DepthSegmenter
        params = cfg.depth_params if cfg is not None and cfg.depth_params is not None \
            else DEFAULT_PARAMS
        return DepthDetectionSource(
            DepthSegmenter(params),
            min_range_m=params.near_m, max_range_m=params.far_m,
            static_map_annotator=geofence_annotator(GeofenceMap.from_file()))
    if kind != KIND_NDVI:
        raise ValueError(f"unknown detection source kind {kind!r}; expected one of "
                         f"{list(DETECTION_SOURCE_KINDS)}")
    from .ndvi_detect import NdviDetectionSource
    return NdviDetectionSource(cfg.thresh, min_area=cfg.min_area, max_area=cfg.max_area)


# --------------------------------------------------------------------------------------------------
# The ROS-facing half of the depth path, as PURE FUNCTIONS. `build_node` cannot be called off-sim
# (rclpy, ros messages), so decode + pose pairing + the call into the seam live out here where a
# test can drive them with a duck-typed message and no ROS at all. They are the only place this node
# touches a depth wire format.
# --------------------------------------------------------------------------------------------------
def decode_depth_frame(msg):
    """A `sensor_msgs/Image` on `/fg/depth/image` -> a float32 (H, W) array of pinhole Z-depth.

    EVERY NUMBER IS DERIVED FROM THE MESSAGE and then asserted, rather than copied from the sensor
    config: `step` must be exactly 4 bytes per column and the payload must be exactly `height *
    step` long. A frame that fails either is REFUSED (ValueError) and not reshaped -- a
    mis-strided buffer reshapes without complaint into a plausible-looking depth image, and the
    obstacle it invents would be at the wrong pixel, which is the failure family ADR-007 am. 5
    (a value correct under a geometry nobody checked) cost this project two weeks.

    `is_bigendian` is READ, not assumed. gz publishes little-endian on this host, so the byte order
    is the one term here that no live test has ever exercised in the other state -- which is
    precisely why it is taken from the message and converted to native float32 (the segmenter
    requires `dtype == float32` exactly, and a big-endian '>f4' array is not that).

    NOT caught by the node: a decode failure here is a bringup fault that is true of frame 1 and
    every frame after it (a fixed sensor does not change its stride mid-flight), so it must stop
    the take loudly at the start -- the same doctrine as refusing to start without a gz clock. The
    flight log is still written by `main`'s finally."""
    import numpy as np

    encoding = getattr(msg, "encoding", None)
    if encoding != DEPTH_IMAGE_ENCODING:
        raise ValueError(f"{DEPTH_IMAGE_TOPIC} carried encoding {encoding!r}, expected "
                         f"{DEPTH_IMAGE_ENCODING!r} (32-bit float metres). Refusing rather than "
                         f"reinterpreting: a uint16 millimetre encoding read as float32 metres is "
                         f"a confident obstacle at a fictional range.")
    height, width, step = int(msg.height), int(msg.width), int(msg.step)
    itemsize = 4                                    # 32FC1: one float32 channel per pixel
    if width <= 0 or height <= 0:
        raise ValueError(f"{DEPTH_IMAGE_TOPIC} carried a degenerate frame {width}x{height}")
    if step != width * itemsize:
        raise ValueError(f"{DEPTH_IMAGE_TOPIC} step {step} != width {width} * {itemsize} bytes "
                         f"({width * itemsize}) -- a padded or mis-strided row would reshape "
                         f"silently into a plausible depth image with every pixel in the wrong "
                         f"place")
    buf = np.frombuffer(msg.data, dtype=np.uint8)
    if buf.size != height * step:
        raise ValueError(f"{DEPTH_IMAGE_TOPIC} payload is {buf.size} bytes, expected height "
                         f"{height} * step {step} = {height * step}")
    dtype = np.dtype(">f4" if getattr(msg, "is_bigendian", 0) else "<f4")
    return buf.view(dtype).reshape(height, width).astype(np.float32, copy=False)


def decode_ndvi_frame(msg):
    """A `sensor_msgs/Image` on `/fg/ndvi/image` -> a float32 (H, W) array of NDVI in [-1, 1].

    THE SAME FOUR CHECKS `decode_depth_frame` MAKES, on the band that has actually flown (G10,
    2026-09-10). Until now this decoder was `np.frombuffer(msg.data, float32).reshape(h, w)` with
    nothing asserted, and the three failure modes are not equally loud:

      * `is_bigendian` was IGNORED, and that one is SILENT. A byte-swapped float32 buffer reshapes
        perfectly into an array of plausible-looking numbers; NDVI would be denormal noise, the
        -0.61 threshold would find nothing, and the flight would log a clean detector that saw no
        birds. Exactly the shape of the failures this project keeps finding after the fact.
      * `encoding` was ASSUMED. `/fg/ndvi/preview` is rgb8 off the same fused array, one word away
        in a launch line; any 4-byte-per-pixel encoding pointed at this topic decodes without
        complaint into confident NDVI.
      * `step` and payload length were UNASSERTED. Those two do raise today -- but as a bare
        `cannot reshape array of size N into shape (H,W)` out of a subscription callback, which
        names neither the topic nor the cause. A padded row that DID divide evenly would place
        every pixel at the wrong coordinate, and `ndvi_georef.project_world_point` would then
        georeference a real detection to the wrong cell: the ADR-007 am. 5 family (a value correct
        under a geometry nobody checked), which cost this project two weeks.

    NOT caught by the node, same doctrine as the depth decoder: a wire-format fault is true of frame
    1 and of every frame after it, so it stops the take loudly at the start rather than degrading a
    flight nobody re-flies. `main`'s `finally` still writes the flight log.

    A VALID frame decodes byte-identically to what this node has always produced -- pinned in
    `tests/fieldguard_planning/test_detection_seam.py`, because the point is the refusals, and a
    refactor that also moved a pixel would be a silent change to the adopted detector."""
    import numpy as np

    encoding = getattr(msg, "encoding", None)
    if encoding != NDVI_IMAGE_ENCODING:
        raise ValueError(f"{NDVI_IMAGE_TOPIC} carried encoding {encoding!r}, expected "
                         f"{NDVI_IMAGE_ENCODING!r} (32-bit float NDVI). Refusing rather than "
                         f"reinterpreting: the rgb8 preview of this very band read as float32 is "
                         f"a confident NDVI value per 4 bytes of colour.")
    height, width, step = int(msg.height), int(msg.width), int(msg.step)
    itemsize = 4                                    # 32FC1: one float32 channel per pixel
    if width <= 0 or height <= 0:
        raise ValueError(f"{NDVI_IMAGE_TOPIC} carried a degenerate frame {width}x{height}")
    if step != width * itemsize:
        raise ValueError(f"{NDVI_IMAGE_TOPIC} step {step} != width {width} * {itemsize} bytes "
                         f"({width * itemsize}) -- a padded or mis-strided row shifts every pixel, "
                         f"and a detection's centroid then georeferences to the wrong cell")
    buf = np.frombuffer(msg.data, dtype=np.uint8)
    if buf.size != height * step:
        raise ValueError(f"{NDVI_IMAGE_TOPIC} payload is {buf.size} bytes, expected height "
                         f"{height} * step {step} = {height * step}")
    dtype = np.dtype(">f4" if getattr(msg, "is_bigendian", 0) else "<f4")
    return buf.view(dtype).reshape(height, width).astype(np.float32, copy=False)


def feed_depth_frame(source, pose_buf, msg):
    """One depth message -> the seam, paired to the pose nearest the frame's OWN gz stamp.

    Identical pairing policy to the NDVI path and on the same clock (`PoseBuffer.nearest`, the
    residual handed on so the seam can refuse a stale pair): the render stalls and bursts, so
    pairing on ARRIVAL would put an obstacle metres down-track. Frames arriving before the first
    `camera_info` are not special-cased here -- the seam counts and drops them (rule 5), because a
    silently discarded pre-`camera_info` window is exactly how the recorder lost most of a flight."""
    stamp_s = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
    depth = decode_depth_frame(msg)
    paired = pose_buf.nearest(stamp_s)
    if paired is None:
        return source.on_frame(stamp_s, depth, None, None)
    pos, quat_xyzw, residual = paired
    return source.on_frame(stamp_s, depth, pos, quat_xyzw, pose_pair_residual_s=residual)


def wait_for_live_intrinsics(node, spin_once, timeout_s: float = CAMERA_INFO_WAIT_S,
                             now=None) -> bool:
    """Block until the armed frame detector has its LIVE intrinsics, or the window runs out.

    The gz-clock refusal's sibling, for the second input a frame detector cannot work without --
    and it must SPIN, not sleep: the clock arrives on its own subprocess thread, `camera_info`
    arrives on a subscription, and a subscription that is never spun delivers nothing. Spinning
    here means the loop is live during the wait, which is what it would be anyway; with no
    detections the policy PROCEEDs and the executor commands nothing.

    True when there is nothing to wait for (a scripted `--demo` source, or an observation run):
    this gate is about a detector that consumes frames, and inventing a requirement for a source
    that reads none would refuse the regression arm."""
    import time

    now = time.monotonic if now is None else now
    detector = getattr(node, "_frame_detector", None)
    if detector is None:
        return True
    deadline = now() + float(timeout_s)
    while getattr(detector, "intr", None) is None and now() < deadline:
        spin_once(node, timeout_sec=0.1)
    return getattr(detector, "intr", None) is not None


def build_node(detection_source: Optional[DetectionSource] = None,
               mission_xy: Optional[Sequence[Tuple[float, float]]] = None,
               detector_cfg: Optional[DetectorConfig] = None):
    """Construct the rclpy node. Kept as a factory so the (untestable-off-sim) rclpy import is lazy.

    A `detection_source` exposing `on_frame` is a real detector: the node then subscribes to THAT
    detector's own image + camera_info pair, chosen by its `SOURCE_TAG` through `FRAME_TOPICS` --
    one pair, never both, which is where the two detectors' exclusivity is enforced. Any other
    callable is used as-is and gets no subscriptions."""
    import subprocess
    import threading

    import rclpy
    from rclpy.node import Node
    from rclpy.qos import (HistoryPolicy, QoSProfile, ReliabilityPolicy,
                           qos_profile_sensor_data)  # BEST_EFFORT — matches AP_DDS publisher QoS (ADR-005)
    from geometry_msgs.msg import PoseStamped
    from sensor_msgs.msg import CameraInfo, Image

    from .clip_recorder import PoseBuffer, StreamingClockParser
    from .ndvi_georef import CameraIntrinsics
    from .ros2_adapter import Ros2VehicleSink

    class AvoidanceNode(Node):
        def __init__(self):
            super().__init__("fieldguard_avoidance")
            self.geofence = GeofenceMap.from_file()
            self.cells = build_grid(load_field_polygon())
            # The ADR-009 staleness bound is NOT passed here: it is a PolicyParams default, so the
            # gate that reads `PolicyParams()` as its bar and the flight that flies it cannot be
            # different numbers. The flown value travels in run.policy_params either way.
            self.policy = AvoidancePolicy(field_polygon=load_field_polygon(),
                                          cruise_alt_m=CRUISE_ALT_M)
            self.sink = Ros2VehicleSink(self)
            swath_half_m = derive_swath_half_width_m(CRUISE_ALT_M)
            self.avoidance_executor = AvoidanceExecutor(self.geofence, self.cells, self.sink,
                                              swath_half_width_m=swath_half_m, alt_bounds=(2.0, 30.0))
            self.detection_source = detection_source
            self.detector_cfg = detector_cfg
            self.loop = AvoidanceLoop(self.policy, self.geofence, self.avoidance_executor,
                                      detection_source, warn=self.get_logger().warn)
            # A detection source that consumes FRAMES gets frames; anything else is a scripted
            # source and the node stays out of the image path entirely. WHICH frames is decided by
            # the source's own tag, so arming the depth detector cannot leave the NDVI band
            # subscribed (or vice versa) -- there is one pair, and no flag can select two.
            self._frame_detector = (detection_source
                                    if hasattr(detection_source, "on_frame") else None)
            self._source_name = detection_source_name(detection_source)
            self._frame_topics = (FRAME_TOPICS.get(self._source_name)
                                  if self._frame_detector is not None else None)
            self._intrinsics_refused = False
            self.mission_xy = list(mission_xy) if mission_xy else []
            self._drone: Optional[DroneState] = None
            self._t0 = self.get_clock().now()
            self._got_pose = False
            self._last_status_t = -1e9

            # ONE clock (see module docstring): Gazebo sim seconds, streamed natively.
            self._pose_buf = PoseBuffer()
            self._gz_now: Optional[float] = None
            self._gz_readings = 0
            self._start_clock_stream()

            # ADR-005: /ap/pose/filtered is PoseStamped whose CONTENT is world-ENU relative to the
            # EKF/home origin (frame_id says base_link but the content, not the label, is authoritative).
            self.create_subscription(PoseStamped, "/ap/pose/filtered", self._on_pose,
                                     qos_profile_sensor_data)
            if self._frame_detector is not None:
                # A frame detector needs BOTH a topic pair and its own decoder, and the two are
                # looked up by the same key. A third detector that added one and not the other
                # would otherwise be handed the wrong decoder in silence -- so this refuses to come
                # up instead, which is cheaper than a flight decoded as the wrong wire format.
                decoders = {NDVI_SOURCE_TAG: self._on_ndvi, DEPTH_SOURCE_TAG: self._on_depth}
                if self._frame_topics is None or self._source_name not in decoders:
                    raise ValueError(
                        f"detection source '{self._source_name}' consumes frames but has no "
                        f"topic pair in FRAME_TOPICS {sorted(FRAME_TOPICS)} and/or no decoder "
                        f"{sorted(decoders)}. Refusing to come up: a frame detector with nothing "
                        f"subscribed detects nothing, silently, for a whole flight.")
                image_topic, info_topic = self._frame_topics
                # BEST_EFFORT, DEPTH 1 -- deliberately NOT the recorder's RELIABLE depth 10. A
                # control loop wants the NEWEST frame, not every frame: a queued backlog of stale
                # frames is exactly what the staleness gate would then throw away, one tick late. It
                # also keeps this third subscriber off the RELIABLE NACK-repair path ADR-013 am. 8
                # priced on the band that has starved twice.
                self.create_subscription(
                    Image, image_topic, decoders[self._source_name],
                    QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                               reliability=ReliabilityPolicy.BEST_EFFORT))
                self.create_subscription(CameraInfo, info_topic, self._on_camera_info,
                                         qos_profile_sensor_data)
            self.create_timer(1.0 / CONTROL_HZ, self._on_tick)
            self.get_logger().info(
                f"fieldguard_avoidance up: /ap/pose/filtered @ {CONTROL_HZ} Hz, coverage swath "
                f"+/-{swath_half_m:.3f} m (derived from config/ndvi_camera.json at {CRUISE_ALT_M:.0f} m "
                f"cruise), detection source '{self._source_name}'"
                + (f", subscribing {self._frame_topics[0]} + {self._frame_topics[1]}"
                   if self._frame_topics is not None else ""))

        # -- clock ------------------------------------------------------------------------------
        def _start_clock_stream(self) -> None:
            """Native gz-transport clock via a `gz topic -e` subprocess + reader thread — NOT
            bridged through ros_gz (Gazebo's /clock is ~350 msgs/s; bridging it starved the image
            pipeline, measured live 2026-08-18). Identical in shape to record_node's, and it feeds
            the SAME `StreamingClockParser`: one mechanism, reused, not a second clock path.

            If the stream dies mid-flight, `_gz_now` simply stops advancing: detection ages grow,
            the staleness gate expires them, and the loop PROCEEDs with `n_stale_dropped` in the
            maneuver debug. Never a sign flip, never a silently-fresh stale frame."""
            def _reader():
                parser = StreamingClockParser()
                try:
                    proc = subprocess.Popen(["gz", "topic", "-e", "-t", "/clock"],
                                            stdout=subprocess.PIPE, text=True, bufsize=1)
                    for line in proc.stdout:
                        t = parser.feed(line)
                        if t is not None:
                            self._gz_now = t
                            self._gz_readings += 1
                except Exception as exc:  # pragma: no cover -- environment-dependent
                    self.get_logger().warn(f"gz clock stream died: {exc}")

            threading.Thread(target=_reader, daemon=True).start()

        # -- subscriptions ----------------------------------------------------------------------
        def _on_pose(self, msg):
            p = msg.pose.position
            wp = _nearest_upcoming_wp((p.x, p.y), self.mission_xy) if self.mission_xy else 0
            self.sink.current_wp_index = wp
            # heading from orientation quaternion (yaw), ENU
            q = msg.pose.orientation
            yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
            self._drone = DroneState(position_enu=(p.x, p.y, p.z), heading_rad=yaw, current_wp_index=wp)
            if self._gz_now is not None:
                # gz-domain tag: the burst-proof pairing key each NDVI frame selects against. The
                # POLICY keeps using the latest pose (it wants where the drone is NOW); the DETECTOR
                # wants the pose that was true when its frame was rendered. Different questions,
                # both correct -- and at 7.7 m/s a 0.4 s pairing error is 3 m of bird-position
                # error, which is what destabilises the away-vector.
                self._pose_buf.tag(self._gz_now, (p.x, p.y, p.z), (q.x, q.y, q.z, q.w))
            if not self._got_pose:
                self._got_pose = True
                self.get_logger().info(f"first /ap/pose/filtered received: ENU("
                                       f"{p.x:.1f}, {p.y:.1f}, {p.z:.1f}) — loop is live")

        def _on_camera_info(self, msg) -> None:
            """LIVE intrinsics for whichever detector is armed -- from the message, never from a
            config file (depth_detect rule 4 / clip_recorder's rule: the config is what we ASKED
            for). One handler for both bands because the subscription already carries which topic
            it came from, and a second copy of `k[0]/k[4]/k[2]/k[5]` is a second place to index the
            wrong element of a 9-vector.

            A `camera_info` the seam REFUSES (ROS publishes an all-zero K for an uncalibrated
            camera, and un-projection divides by fx) leaves the detector unarmed and is logged
            ONCE, not per message. The startup wait in `main` then refuses the take by name --
            the same outcome as no message at all, and the correct one: an unarmed detector
            cannot fly, and finding that out at arming is cheaper than a ZeroDivisionError out of
            a subscription callback after takeoff."""
            if self._frame_detector is None or self._frame_detector.intr is not None:
                return
            try:
                self._frame_detector.set_intrinsics(CameraIntrinsics(
                    width_px=msg.width, height_px=msg.height,
                    fx=msg.k[0], fy=msg.k[4], cx=msg.k[2], cy=msg.k[5]))
            except ValueError as exc:
                if not self._intrinsics_refused:
                    self._intrinsics_refused = True
                    self.get_logger().error(
                        f"REFUSED the camera_info on {self._frame_topics[1]}: {exc}")
                return
            self.get_logger().info(
                f"detector armed with LIVE intrinsics: {msg.width}x{msg.height} fx={msg.k[0]:.1f} "
                f"cx={msg.k[2]:.1f} cy={msg.k[5]:.1f} (from {self._frame_topics[1]})")

        def _on_ndvi(self, msg) -> None:
            """Fused NDVI frame -> detections, paired to the pose nearest the frame's OWN gz stamp.
            Every drop is counted inside the source; nothing here returns silently. The decode is
            `decode_ndvi_frame`'s, out at module scope where a test can drive it with a duck-typed
            message and no ROS -- a malformed frame raises there rather than being reshaped into a
            plausible NDVI image."""
            stamp_s = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            ndvi = decode_ndvi_frame(msg)
            paired = self._pose_buf.nearest(stamp_s)
            if paired is None:
                self._frame_detector.on_frame(stamp_s, ndvi, None, None)
                return
            pos, quat_xyzw, residual = paired
            self._frame_detector.on_frame(stamp_s, ndvi, pos, quat_xyzw,
                                          pose_pair_residual_s=residual)

        def _on_depth(self, msg) -> None:
            """Forward depth frame -> detections. The decode, the pose pairing and the call are
            `feed_depth_frame`'s, out at module scope where they are unit-testable without ROS; a
            malformed frame raises there rather than being reshaped into a plausible obstacle."""
            feed_depth_frame(self._frame_detector, self._pose_buf, msg)

        # -- control tick -----------------------------------------------------------------------
        def _on_tick(self):
            if self._drone is None:
                return  # no pose yet
            now_s = self._gz_now
            elapsed_s = (self.get_clock().now() - self._t0).nanoseconds * 1e-9
            maneuver = self.loop.tick(self._drone, now_s,
                                      now_s if now_s is not None else elapsed_s)
            # Heartbeat every ~2 s so the node isn't a black box: position, decision, nearest bird.
            # Elapsed wall seconds, and ONLY here -- this number never reaches the policy or the log.
            if elapsed_s - self._last_status_t >= 2.0:
                self._last_status_t = elapsed_s
                x, y, z = self._drone.position_enu
                dets = self.loop.last_detections
                nb = min((math.hypot(x - d.position_enu[0], y - d.position_enu[1]) for d in dets),
                         default=None)
                nb_s = f"{nb:.1f} m" if nb is not None else "none in view"
                sim_s = "NO CLOCK" if now_s is None else f"{now_s:.1f}"
                self.get_logger().info(f"[status t={elapsed_s:5.1f}s sim={sim_s}] "
                                       f"pos=({x:5.1f},{y:5.1f},{z:4.1f}) "
                                       f"wp={self._drone.current_wp_index} "
                                       f"decision={maneuver.decision.value} nearest_bird={nb_s}")

        # -- evidence ---------------------------------------------------------------------------
        def run_block(self) -> dict:
            return build_run_block(
                policy_params=_params_dict(self.policy.params),
                clock=self.loop.clock_block(self._gz_readings),
                tick_stamp_sim_s=self.loop.tick_stamp_sim_s,
                detector=detector_log_block(self.detection_source, self.detector_cfg))

        def dump_flight_log(self, out_path: Path) -> None:
            self.avoidance_executor.finalize()
            log = self.avoidance_executor.flight_log("live_run", seed=0, cell_size_m=2.5)
            log["run"] = self.run_block()
            out_path.parent.mkdir(parents=True, exist_ok=True)  # eval/results/ is gitignored -- may not exist
            out_path.write_text(serialise_flight_log(log))
            self.get_logger().info(f"wrote flight log -> {out_path}")

    if not rclpy.ok():          # rclpy.init() must run before any Node is constructed
        rclpy.init()
    return rclpy, AvoidanceNode()


def main(argv=None) -> int:
    import sys
    import time

    args = parse_args(argv)
    cfg: Optional[DetectorConfig] = None
    src: Optional[DetectionSource] = None
    if args.detect:
        try:
            cfg = detector_config_from_args(args)
            src = build_detection_source(cfg, args.detection_source)
        except ImportError as exc:
            # Name the source that was ASKED for and cite the verdict that belongs to IT: the depth
            # arm imports `depth_segment`, whose constants are ADR-020's scored set, and printing
            # ADR-003 am. 7 (the NDVI adoption) at it is provenance pointing at the wrong sensor.
            core = ("fieldguard_planning.depth_segment (the ADR-020 scored segmenter)"
                    if args.detection_source == KIND_DEPTH else
                    "fieldguard_planning.ndvi_detect (the ADR-003 am. 7 ADOPTED detector)")
            print(f"[avoidance_node] --detect --detection-source {args.detection_source} needs "
                  f"{core} and its scipy morphology, which this image cannot import ({exc}). "
                  f"Rebuild the image (sim/docker/Dockerfile installs python3-scipy): "
                  f"bash scripts/sim_docker_build.sh && bash scripts/sim_docker_run.sh. There is "
                  f"deliberately NO numpy fallback -- a reimplementation would be a different "
                  f"detector wearing the adopted one's verdict.", file=sys.stderr)
            return 2
        if args.detection_source == KIND_DEPTH:
            print(f"[avoidance_node] the NDVI detector is DISARMED for this run: "
                  f"--detection-source {KIND_DEPTH} flies the forward aperture "
                  f"({DEPTH_IMAGE_TOPIC}) and one flight carries ONE detection source. This take "
                  f"therefore produces no ADR-003 in-air detection evidence. Segmenter params: "
                  f"{cfg.depth_params}.", file=sys.stderr)
        elif cfg.thresh_provisional:
            print(f"[avoidance_node] WARNING: --ndvi-thresh {cfg.thresh} is the PROVISIONAL "
                  f"ADR-003 am. 7 default. It was derived from per-class PIXEL means "
                  f"(eval/results/gate2_summary.json); the detection evidence behind ADOPT is "
                  f"n=20 visible bird-frames with 7 FP / 3 FN and 8 of 20 labels ambiguous. That "
                  f"is a confirmation it WORKS, not a characterisation of where the threshold "
                  f"belongs. Lifting PROVISIONAL needs the false-positive study.", file=sys.stderr)
    elif args.demo:
        src = proximity_bird_source(DEMO_BIRD_ENU)

    try:
        mission_xy = default_mission_xy()
    except Exception:
        mission_xy = None
    rclpy, node = build_node(detection_source=src, mission_xy=mission_xy, detector_cfg=cfg)
    node.get_logger().info(f"detection source: {detection_source_name(src)}")

    if args.detect:
        # REFUSE TO START without a clock reading. Without it there is no staleness gate, no
        # stamp-paired pose and no sim-time axis to score the flight against ground truth -- and all
        # three failures are silent in the air. A startup check is cheaper than a burnt take.
        deadline = time.monotonic() + GZ_CLOCK_WAIT_S
        while node._gz_now is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if node._gz_now is None:
            node.get_logger().error(
                f"no Gazebo /clock reading after {GZ_CLOCK_WAIT_S:.0f} s — is the `gz` CLI on PATH "
                f"inside the container and is Gazebo up? --detect refuses to fly without one "
                f"clock (see the module docstring).")
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
            return 3
        node.get_logger().info(f"gz clock live at sim t={node._gz_now:.3f} s — detector armed")

        # REFUSE TO FLY BLIND. The clock was this node's only startup gate, and a frame detector
        # with no `camera_info` is just as silent: it counts and drops every frame for the whole
        # take while the heartbeat prints `nearest_bird=none in view`. Same shape as the refusal
        # above, and it names the topic because that name is the thing most likely to be wrong --
        # `/fg/depth/camera_info` is DERIVED by gz-sensors, not declared.
        if not wait_for_live_intrinsics(node, rclpy.spin_once):
            info_topic = (node._frame_topics[1] if node._frame_topics else "the camera_info topic")
            node.get_logger().error(
                f"no usable {info_topic} in {CAMERA_INFO_WAIT_S:.0f} s — the detector is UNARMED "
                f"and would drop every frame of this flight (dropped_no_intrinsics), silently. "
                f"Bring the camera pipeline up BEFORE this shell and check the topic really "
                f"publishes: `ros2 topic echo --once {info_topic}`. Refusing to fly a detector "
                f"that detects nothing.")
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
            return 4
        node.get_logger().info("live intrinsics present — the detector consumes frames from here")

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # EVIDENCE PROTECTION: timestamped filename so a later run can NEVER clobber a prior run's
        # log -- the 2026-08-05 live demo's unsuffixed live_flight_log.json was silently overwritten
        # by an idle run (empty path, all-cells-debt) and nothing noticed. No code reads the
        # unsuffixed path (docs reference it for humans only), so we write ONLY timestamped files;
        # scripts/check_live_flight_log.py validates eval/results/*flight_log*.json.
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        node.dump_flight_log(REPO_ROOT / "eval" / "results" / f"live_flight_log_{stamp}.json")
        node.destroy_node()
        if rclpy.ok():  # Ctrl-C may have already shut the context down; a second call raises
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
