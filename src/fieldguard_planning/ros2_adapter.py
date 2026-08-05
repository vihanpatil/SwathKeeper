"""ROS 2 binding for the avoidance loop — implements `avoidance_executor.VehicleCommandSink` against
the AP_DDS interface locked in ADR-005/ADR-006. This is the "thin adapter" the executor was designed
around: the executor stays sim-agnostic and unit-tested; THIS file is the only part that talks rclpy.

Mapping (all verified names from ADR-005, confirmed live at Week-3 Gate 2):
  - set_mode("GUIDED"/"AUTO")   -> service  /ap/mode_switch   (ardupilot_msgs/srv/ModeSwitch)
  - send_setpoint_enu((e,n,u))  -> publish   /ap/cmd_gps_pose  (ardupilot_msgs/msg/GlobalPosition),
                                   world-ENU converted to geodetic against the field home origin.
  - current_waypoint()          -> tracked int the node sets from the mission model (AP_DDS exposes
                                   no mission-current service at the pinned SHA — ADR-006), so the
                                   node derives it from /ap/pose/filtered vs the loaded mission.

IMPORTANT — verify-in-container items (cannot be checked outside the Docker/ROS 2 stack):
  * The exact field names of `ardupilot_msgs/msg/GlobalPosition` and `srv/ModeSwitch` at the pinned
    ArduPilot SHA. The names used below match ArduPilot master's ardupilot_msgs; if a field differs,
    it fails loudly at import/construction in the container, not silently. Do a `ros2 interface show
    ardupilot_msgs/msg/GlobalPosition` before the first live run.
  * ArduCopter flight-mode numbers (AUTO=3, GUIDED=4) — stable, but confirm with `mode` in MAVProxy.

Only `enu_to_geodetic` (pure math) and the mode-number map are import-safe / unit-tested here; the
rclpy pieces import lazily so this module loads on a bare interpreter for those tests.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Tuple

from .mission_waypoints import M_PER_DEG_LAT, m_per_deg_lon

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FIELD_POLYGON = REPO_ROOT / "config" / "field_polygon.json"

# ArduCopter flight-mode numbers (Copter mode enum). Confirm with MAVProxy `mode` if ever in doubt.
AP_COPTER_MODE = {"AUTO": 3, "GUIDED": 4}

# ardupilot_msgs/GlobalPosition.coordinate_frame — MAV_FRAME_GLOBAL_INT (absolute lat/lon, AMSL alt).
# The executor commands a world-ENU point; we convert to absolute geodetic against the field home,
# rather than a relative frame, so the command is unambiguous regardless of EKF-origin drift.
MAV_FRAME_GLOBAL = 5  # MAV_FRAME_GLOBAL_INT


def enu_to_geodetic(
    e_m: float, n_m: float, u_m: float,
    home_lat: float, home_lon: float, home_alt_m: float,
) -> Tuple[float, float, float]:
    """Inverse of `mission_waypoints.latlon_to_enu` (+ altitude): world-ENU metres relative to the
    field home -> (latitude_deg, longitude_deg, altitude_m_AMSL). Pure, deterministic, stdlib."""
    lat = home_lat + n_m / M_PER_DEG_LAT
    lon = home_lon + e_m / m_per_deg_lon(home_lat)
    alt = home_alt_m + u_m
    return lat, lon, alt


def load_home(path: Path = DEFAULT_FIELD_POLYGON) -> Tuple[float, float, float]:
    d = json.loads(Path(path).read_text())
    return float(d["home_lat"]), float(d["home_lon"]), float(d.get("home_elevation_m", 0.0))


class Ros2VehicleSink:
    """`VehicleCommandSink` implementation over AP_DDS. Construct inside a live rclpy node (pass the
    node in so it owns the executor/context). Duck-types the Protocol in avoidance_executor.py — no
    import of that module needed here, keeping the dependency one-directional.
    """

    def __init__(self, node, home: Tuple[float, float, float] | None = None, cmd_topic: str = "/ap/cmd_gps_pose",
                 mode_service: str = "/ap/mode_switch"):
        # Lazy imports: rclpy + ardupilot_msgs only exist inside the container. Importing here (not at
        # module top) lets enu_to_geodetic + the mode map be unit-tested on a bare interpreter.
        from ardupilot_msgs.msg import GlobalPosition  # noqa: F401
        from ardupilot_msgs.srv import ModeSwitch

        self._node = node
        self._GlobalPosition = GlobalPosition
        self.home_lat, self.home_lon, self.home_alt = home if home is not None else load_home()

        self._pub = node.create_publisher(GlobalPosition, cmd_topic, 10)
        self._mode_cli = node.create_client(ModeSwitch, mode_service)
        self.current_wp_index: int = 0  # the node sets this from its mission model each tick

    # -- VehicleCommandSink Protocol -----------------------------------------
    def set_mode(self, mode: str) -> None:
        from ardupilot_msgs.srv import ModeSwitch
        mode_num = AP_COPTER_MODE[mode]  # KeyError on an unexpected mode -> loud, not silent
        if not self._mode_cli.wait_for_service(timeout_sec=2.0):
            raise RuntimeError(f"{self._mode_cli.srv_name} unavailable — is AP_DDS up? (WEEK1 §6b)")
        req = ModeSwitch.Request()
        req.mode = mode_num
        self._mode_cli.call_async(req)  # fire-and-forget; the loop re-asserts mode each maneuver
        self._node.get_logger().info(f"[sink] set_mode {mode} ({mode_num})")

    def send_setpoint_enu(self, point_enu: Tuple[float, float, float]) -> None:
        lat, lon, alt = enu_to_geodetic(*point_enu, self.home_lat, self.home_lon, self.home_alt)
        msg = self._GlobalPosition()
        # frame_id="map" per ADR-006 (world frame); coordinate_frame carries the MAVLink frame enum.
        msg.header.frame_id = "map"
        msg.header.stamp = self._node.get_clock().now().to_msg()
        msg.coordinate_frame = MAV_FRAME_GLOBAL
        msg.latitude = lat
        msg.longitude = lon
        msg.altitude = float(alt)
        self._pub.publish(msg)
        self._node.get_logger().info(
            f"[sink] cmd_gps_pose <- ENU{point_enu} = ({lat:.7f},{lon:.7f},{alt:.1f} AMSL)")

    def current_waypoint(self) -> int:
        return self.current_wp_index
