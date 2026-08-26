"""ROS 2 bringup node that runs the reactive-avoidance loop live against ArduPilot SITL + Gazebo.

Wires the confirmed AP_DDS interface (ADR-005) to the tested loop:

    /ap/pose/filtered ──▶ DroneState ──┐
    detection_source  ──▶ [Detection] ─┼─▶ AvoidancePolicy.decide_multi ─▶ AvoidanceManeuver
                                        │                                          │
                    mission model ──▶ current_wp_index                            ▼
                                                        AvoidanceExecutor.step ─▶ Ros2VehicleSink
                                                                                   │
                                                            /ap/mode_switch + /ap/cmd_gps_pose

DETECTION SOURCE is a seam with exactly two live implementations, chosen at the command line:

    --detect   the REAL detector (ADR-003 am. 7, ADOPTED): `/fg/ndvi/image` -> `ndvi_detect`
               blobs -> world-ENU positions ranged by APPARENT SIZE (ADR-009 rule 2).
    --demo     the scripted stand-in bird at ENU (30,30,15). Kept, not deleted: it is the
               regression-gate exception (ADR-013 am. 2) and the A/B arm against the real
               detector -- a flight where the demo dodges and the detector does not is a
               perception finding, and that comparison needs both sources to still exist.

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

# The fused NDVI band and ITS OWN camera_info pass-through (ndvi_node publishes both). Deliberately
# not the bridge's rgb camera_info: these intrinsics must describe the frames actually consumed, and
# subscribing the rgb band would add a third reader to the hop that has starved twice.
NDVI_IMAGE_TOPIC = "/fg/ndvi/image"
NDVI_INFO_TOPIC = "/fg/ndvi/camera_info"

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
    """What `--detect` was armed with, and WHERE THE THRESHOLD CAME FROM.

    The threshold is the detector (`mask = ndvi < thresh`), it differs by half a unit between the
    synthetic and real renders, and -0.61 is still PROVISIONAL -- so the value alone is not evidence.
    A flight log that records the number without its provenance cannot answer "was this the adopted
    default or something someone tried?", which is the question every re-reading of the artifact
    starts with."""
    thresh: float
    thresh_provenance: str
    thresh_provisional: bool
    min_area: int
    max_area: int


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
    args = ap.parse_args(list(argv) if argv is not None else None)
    if args.detect and args.demo:
        ap.error("--detect and --demo are mutually exclusive: a flight has ONE detection source, "
                 "and a log that mixed a virtual bird with real detections could not be scored "
                 "against either kind of ground truth")
    return args


def detector_config_from_args(args: argparse.Namespace) -> DetectorConfig:
    """Freeze the CLI intent against `ndvi_detect`'s own defaults. Whether the threshold is still
    PROVISIONAL is decided by whether the operator passed one at all -- not by comparing floats to
    the default, which would silently re-label an explicit `--ndvi-thresh -0.61` as a default."""
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
    """Provenance tag for the flight log, derived from what the source IS rather than from a flag
    the node could forget to pass. A frame-consuming source (`on_frame`) is the real detector; any
    other callable is a scripted stand-in; none is an idle/observation run."""
    if source is None:
        return "none"
    return "ndvi_blob" if hasattr(source, "on_frame") else DEMO_SOURCE_TAG


def detector_log_block(source, cfg: Optional[DetectorConfig]) -> dict:
    """`log["run"]["detector"]`. Every number is read back from the SOURCE that actually ran, not
    from the CLI intent -- the only provenance the config contributes is where the threshold came
    from and whether it is still provisional, which the source has no way to know."""
    name = detection_source_name(source)
    if name != "ndvi_blob":
        return {
            "source": name,
            "module": "fieldguard_planning.avoidance_node",
            "note": ("scripted stand-in bird: its logged position IS exact ground truth (a constant "
                     "we chose), so detection-CPA is the correct safety gate for this flight"
                     if name == DEMO_SOURCE_TAG else
                     "no detection source armed -- observation run, no avoidance claimed"),
        }
    intr = getattr(source, "intr", None)
    return {
        "source": name,
        "module": "fieldguard_planning.ndvi_detect",
        "thresh": float(source.thresh),
        "thresh_provenance": cfg.thresh_provenance if cfg else "unknown (no DetectorConfig)",
        "thresh_provisional": bool(cfg.thresh_provisional) if cfg else True,
        "min_area": int(source.min_area),
        "max_area": int(source.max_area),
        "radius_prior_m": float(source.radius_prior_m),
        "range_model": ("apparent_size_ray (ADR-009 rule 2); ground-plane projection is never used "
                        "-- it places a flying bird at z=0, outside the threat cylinder"),
        "intrinsics": (None if intr is None else
                       {"image_width_px": int(intr.width_px), "image_height_px": int(intr.height_px),
                        "fx": float(intr.fx), "fy": float(intr.fy),
                        "cx": float(intr.cx), "cy": float(intr.cy),
                        "provenance": f"live {NDVI_INFO_TOPIC} (not config/ndvi_camera.json)"}),
        "counters": source.counters(),
    }


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


def build_detection_source(cfg: DetectorConfig):
    """Construct the real detector. Imported HERE and nowhere else at module scope: `ndvi_detect`
    pulls numpy + scipy, and a missing scipy must fail with the rebuild instruction rather than at
    the top of a module the stdlib test suite imports."""
    from .ndvi_detect import NdviDetectionSource
    return NdviDetectionSource(cfg.thresh, min_area=cfg.min_area, max_area=cfg.max_area)


def build_node(detection_source: Optional[DetectionSource] = None,
               mission_xy: Optional[Sequence[Tuple[float, float]]] = None,
               detector_cfg: Optional[DetectorConfig] = None):
    """Construct the rclpy node. Kept as a factory so the (untestable-off-sim) rclpy import is lazy.

    A `detection_source` exposing `on_frame` is the real detector: the node then subscribes to the
    fused NDVI band and feeds it. Any other callable is used as-is and gets no subscriptions."""
    import subprocess
    import threading

    import numpy as np
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
            # source and the node stays out of the image path entirely.
            self._frame_detector = (detection_source
                                    if hasattr(detection_source, "on_frame") else None)
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
                # BEST_EFFORT, DEPTH 1 -- deliberately NOT the recorder's RELIABLE depth 10. A
                # control loop wants the NEWEST frame, not every frame: a queued backlog of stale
                # NDVI is exactly what the staleness gate would then throw away, one tick late. It
                # also keeps this third subscriber off the RELIABLE NACK-repair path ADR-013 am. 8
                # priced on the band that has starved twice.
                self.create_subscription(Image, NDVI_IMAGE_TOPIC, self._on_ndvi,
                                         QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                                                    reliability=ReliabilityPolicy.BEST_EFFORT))
                self.create_subscription(CameraInfo, NDVI_INFO_TOPIC, self._on_ndvi_info,
                                         qos_profile_sensor_data)
            self.create_timer(1.0 / CONTROL_HZ, self._on_tick)
            self.get_logger().info(
                f"fieldguard_avoidance up: /ap/pose/filtered @ {CONTROL_HZ} Hz, coverage swath "
                f"+/-{swath_half_m:.3f} m (derived from config/ndvi_camera.json at {CRUISE_ALT_M:.0f} m "
                f"cruise), detection source '{detection_source_name(detection_source)}'"
                + (f", subscribing {NDVI_IMAGE_TOPIC} + {NDVI_INFO_TOPIC}"
                   if self._frame_detector is not None else ""))

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

        def _on_ndvi_info(self, msg) -> None:
            if self._frame_detector is None or self._frame_detector.intr is not None:
                return
            self._frame_detector.set_intrinsics(CameraIntrinsics(
                width_px=msg.width, height_px=msg.height,
                fx=msg.k[0], fy=msg.k[4], cx=msg.k[2], cy=msg.k[5]))
            self.get_logger().info(
                f"detector armed with LIVE intrinsics: {msg.width}x{msg.height} fx={msg.k[0]:.1f} "
                f"cx={msg.k[2]:.1f} cy={msg.k[5]:.1f} (from {NDVI_INFO_TOPIC})")

        def _on_ndvi(self, msg) -> None:
            """Fused NDVI frame -> detections, paired to the pose nearest the frame's OWN gz stamp.
            Every drop is counted inside the source; nothing here returns silently."""
            stamp_s = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            ndvi = np.frombuffer(msg.data, dtype=np.float32).reshape(msg.height, msg.width)
            paired = self._pose_buf.nearest(stamp_s)
            if paired is None:
                self._frame_detector.on_frame(stamp_s, ndvi, None, None)
                return
            pos, quat_xyzw, residual = paired
            self._frame_detector.on_frame(stamp_s, ndvi, pos, quat_xyzw,
                                          pose_pair_residual_s=residual)

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
            import json
            self.avoidance_executor.finalize()
            log = self.avoidance_executor.flight_log("live_run", seed=0, cell_size_m=2.5)
            log["run"] = self.run_block()
            out_path.parent.mkdir(parents=True, exist_ok=True)  # eval/results/ is gitignored -- may not exist
            out_path.write_text(json.dumps(log, indent=2))
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
            src = build_detection_source(cfg)
        except ImportError as exc:
            print(f"[avoidance_node] --detect needs the ADOPTED detector core and its scipy "
                  f"morphology, which this image cannot import ({exc}). Rebuild the image "
                  f"(sim/docker/Dockerfile installs python3-scipy): bash scripts/sim_docker_build.sh "
                  f"&& bash scripts/sim_docker_run.sh. There is deliberately NO numpy fallback -- a "
                  f"reimplementation would be a different detector wearing ADR-003 am. 7's verdict.",
                  file=sys.stderr)
            return 2
        if cfg.thresh_provisional:
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
