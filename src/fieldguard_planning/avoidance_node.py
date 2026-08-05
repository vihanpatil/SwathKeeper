"""ROS 2 bringup node that runs the reactive-avoidance loop live against ArduPilot SITL + Gazebo.

Wires the confirmed AP_DDS interface (ADR-005) to the tested loop:

    /ap/pose/filtered ──▶ DroneState ──┐
    detection_source  ──▶ [Detection] ─┼─▶ AvoidancePolicy.decide_multi ─▶ AvoidanceManeuver
                                        │                                          │
                    mission model ──▶ current_wp_index                            ▼
                                                        AvoidanceExecutor.step ─▶ Ros2VehicleSink
                                                                                   │
                                                            /ap/mode_switch + /ap/cmd_gps_pose

Everything except THIS node and `ros2_adapter.py` is sim-agnostic and unit-tested. This is the thin,
verify-in-container layer. Run it inside the fieldguard-sim container with ROS 2 sourced and AP_DDS
up (WEEK1_BRINGUP §6b), as the 4th shell alongside Gazebo + SITL + the micro-ROS agent — see
docs/WEEK3_AVOIDANCE_DEMO.md.

DETECTION SOURCE is intentionally pluggable and defaults to "none": the real NDVI blob detector on
the gimbal camera is the Weeks 5-6 pipeline (ADR-003 on the real render). Until then, pass a
`detection_source` callable (e.g. a scripted-bird injector) to exercise the avoidance path. This
keeps the control loop demonstrable now without blocking on the perception pipeline.

rclpy imports lazily inside main()/the class so the repo's stdlib test suite can import the sibling
pure modules without a ROS 2 environment.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from .avoidance_types import Detection, DroneState
from .avoidance_policy import AvoidancePolicy
from .avoidance_executor import AvoidanceExecutor
from .geofence import GeofenceMap
from .coverage import build_grid, load_field_polygon

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DetectionSource = Callable[[float], List[Detection]]  # t_seconds -> current detections (world-ENU)

CRUISE_ALT_M = 15.0
SWATH_HALF_M = 7.5
CONTROL_HZ = 5.0


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


# A scripted bird for the live demo before the NDVI detector exists (Weeks 5-6). Each entry:
# (track_id, position_enu, t_start_s, t_end_s). A TRANSIENT threat on lane x=30 at cruise altitude,
# present for the first 40 s then "flown off" -- so the loop dodges + holds while it's there and then
# cleanly RESUMES the survey once it clears (a persistent bird would just hold at a safe standoff
# forever, which is safe but doesn't show the resume). Tune the window to your machine's flight
# timing: the drone must reach lane x=30 while the bird is still present. A crossing bird is the real
# case; this static-with-window stand-in is enough until the NDVI detector plugs into this same seam.
DEMO_BIRDS = [("demo_bird_0", (30.0, 30.0, 15.0), 0.0, 60.0)]


def scripted_bird_source(birds) -> DetectionSource:
    """Turn a list of (track_id, position_enu, t0, t1) into a DetectionSource — a stand-in for the
    real NDVI detector so the live control loop is demonstrable now. Pure/stdlib (unit-tested)."""
    def src(t: float) -> List[Detection]:
        return [Detection(pos, frame_id=int(t * CONTROL_HZ), track_id=tid)
                for tid, pos, t0, t1 in birds if t0 <= t <= t1]
    return src


def default_mission_xy() -> List[Tuple[float, float]]:
    """Load the boustrophedon mission as world-ENU waypoints (for current-waypoint derivation)."""
    from .mission_waypoints import parse_qgc_wpl, mission_xy_path
    from .ros2_adapter import load_home
    home_lat, home_lon, _ = load_home()
    items = parse_qgc_wpl(REPO_ROOT / "config" / "missions" / "boustrophedon.waypoints")
    return mission_xy_path(items, home_lat, home_lon)


def build_node(detection_source: Optional[DetectionSource] = None,
               mission_xy: Optional[Sequence[Tuple[float, float]]] = None):
    """Construct the rclpy node. Kept as a factory so the (untestable-off-sim) rclpy import is lazy."""
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import qos_profile_sensor_data  # BEST_EFFORT — matches AP_DDS publisher QoS (ADR-005)
    from geometry_msgs.msg import PoseStamped

    from .ros2_adapter import Ros2VehicleSink

    class AvoidanceNode(Node):
        def __init__(self):
            super().__init__("fieldguard_avoidance")
            self.geofence = GeofenceMap.from_file()
            self.cells = build_grid(load_field_polygon())
            self.policy = AvoidancePolicy(field_polygon=load_field_polygon(),
                                          cruise_alt_m=CRUISE_ALT_M)
            self.sink = Ros2VehicleSink(self)
            self.avoidance_executor = AvoidanceExecutor(self.geofence, self.cells, self.sink,
                                              swath_half_width_m=SWATH_HALF_M, alt_bounds=(2.0, 30.0))
            self.detection_source = detection_source or (lambda t: [])
            self.mission_xy = list(mission_xy) if mission_xy else []
            self._drone: Optional[DroneState] = None
            self._t0 = self.get_clock().now()

            # ADR-005: /ap/pose/filtered is PoseStamped whose CONTENT is world-ENU relative to the
            # EKF/home origin (frame_id says base_link but the content, not the label, is authoritative).
            self.create_subscription(PoseStamped, "/ap/pose/filtered", self._on_pose,
                                     qos_profile_sensor_data)
            self.create_timer(1.0 / CONTROL_HZ, self._on_tick)
            self.get_logger().info("fieldguard_avoidance up: subscribing /ap/pose/filtered @ "
                                   f"{CONTROL_HZ} Hz")

        def _on_pose(self, msg):
            p = msg.pose.position
            wp = _nearest_upcoming_wp((p.x, p.y), self.mission_xy) if self.mission_xy else 0
            self.sink.current_wp_index = wp
            # heading from orientation quaternion (yaw), ENU
            q = msg.pose.orientation
            yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))
            self._drone = DroneState(position_enu=(p.x, p.y, p.z), heading_rad=yaw, current_wp_index=wp)

        def _on_tick(self):
            if self._drone is None:
                return  # no pose yet
            t = (self.get_clock().now() - self._t0).nanoseconds * 1e-9
            dets = self.detection_source(t)
            maneuver = self.policy.decide_multi(dets, self._drone, self.geofence)
            self.avoidance_executor.step(self._drone, maneuver)

        def dump_flight_log(self, out_path: Path) -> None:
            import json
            self.avoidance_executor.finalize()
            log = self.avoidance_executor.flight_log("live_run", seed=0, cell_size_m=2.5)
            out_path.write_text(json.dumps(log, indent=2))
            self.get_logger().info(f"wrote flight log -> {out_path}")

    if not rclpy.ok():          # rclpy.init() must run before any Node is constructed
        rclpy.init()
    return rclpy, AvoidanceNode()


def main(argv=None):
    import sys
    args = argv if argv is not None else sys.argv[1:]
    demo = "--demo" in args
    src = scripted_bird_source(DEMO_BIRDS) if demo else None
    try:
        mission_xy = default_mission_xy()
    except Exception:
        mission_xy = None
    rclpy, node = build_node(detection_source=src, mission_xy=mission_xy)
    node.get_logger().info(f"demo bird injection: {'ON' if demo else 'off'}")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.dump_flight_log(REPO_ROOT / "eval" / "results" / "live_flight_log.json")
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
