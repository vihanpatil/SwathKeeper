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
  * `ModeSwitch.Response`'s fields specifically: `status` (did the mode actually change) and
    `curr_mode` (the mode the vehicle is in AFTER the attempt). Only `Request.mode` has been read off
    the pinned source so far, so the response reader below treats a missing `status` as "cannot
    confirm" and says so in the log, rather than reading it as a failure. Confirm with `ros2
    interface show ardupilot_msgs/srv/ModeSwitch`.
  * ArduCopter flight-mode numbers (AUTO=3, GUIDED=4) — stable, but confirm with `mode` in MAVProxy.

Import-safe / unit-tested here: `enu_to_geodetic` (pure math), `load_home`, the mode-number map, and
`format_mode_switch_outcome` (the mode-switch response reader's message logic). The rclpy pieces
import lazily so this module loads on a bare interpreter for those tests.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import NamedTuple, Optional, Tuple

from .mission_waypoints import M_PER_DEG_LAT, m_per_deg_lon

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FIELD_POLYGON = REPO_ROOT / "config" / "field_polygon.json"

# ArduCopter flight-mode numbers (Copter mode enum). Confirm with MAVProxy `mode` if ever in doubt.
AP_COPTER_MODE = {"AUTO": 3, "GUIDED": 4}

# ardupilot_msgs/GlobalPosition.coordinate_frame — MAV_FRAME_GLOBAL_INT (absolute lat/lon, AMSL alt).
# The executor commands a world-ENU point; we convert to absolute geodetic against the field home,
# rather than a relative frame, so the command is unambiguous regardless of EKF-origin drift.
MAV_FRAME_GLOBAL = 5  # MAV_FRAME_GLOBAL_INT


# --------------------------------------------------------------------------------------------------
# Mode-switch outcome reporting (pure — unit-tested off-sim)
# --------------------------------------------------------------------------------------------------
# What a failed mode switch actually COSTS, per commanded mode. Spelled out in the log line because
# "mode switch failed" on its own doesn't tell whoever reads the flight log that the dodge silently
# never flew — which is the whole reason a rejection must not stay unread.
_MODE_SWITCH_FAILURE_COST = {
    "GUIDED": ("the vehicle is still in AUTO — /ap/cmd_gps_pose is honored ONLY in GUIDED+armed "
               "(ADR-006 ready_for_external_control), so the avoidance setpoint is being dropped "
               "and the dodge is NOT flying"),
    "AUTO": ("the vehicle is still in GUIDED — the mission never resumed, so the drone is holding at "
             "the dodge point and coverage is stalling"),
}


class ModeSwitchOutcome(NamedTuple):
    """One `/ap/mode_switch` response, read: `ok` picks the log level, `message` is the line. A plain
    tuple so the formatter stays pure and testable on a bare interpreter."""
    ok: bool
    message: str


def format_mode_switch_outcome(mode: str, mode_num: int, *, status: Optional[bool] = None,
                               curr_mode: Optional[int] = None,
                               error: Optional[BaseException] = None) -> ModeSwitchOutcome:
    """Turn an `ardupilot_msgs/srv/ModeSwitch` response — or the failure to get one — into the line
    the node logs. The information was always there (AP_DDS answers with `status` and `curr_mode`);
    it was simply never read, because the call was fire-and-forget with no done-callback.

    `status=None` means the response carried no `status` field at all (a shape mismatch at the pinned
    SHA). That is reported as "cannot confirm", NOT silently read as a rejection — an unverifiable
    switch and a refused switch are different failures and deserve different log lines."""
    prefix = f"[sink] set_mode {mode} ({mode_num})"
    cost = _MODE_SWITCH_FAILURE_COST.get(mode, "the vehicle is not in the commanded mode")
    reported = "" if curr_mode is None else f" (vehicle reports mode {curr_mode})"

    if error is not None:
        return ModeSwitchOutcome(
            False, f"{prefix} FAILED: no response from the mode service ({error!r}) — assume {cost}")
    if status is None:
        return ModeSwitchOutcome(
            False, f"{prefix}: ModeSwitch response carried no 'status' field — CANNOT CONFIRM the "
                   f"switch{reported}; run `ros2 interface show ardupilot_msgs/srv/ModeSwitch` "
                   f"(module docstring, verify-in-container)")
    if not status:
        return ModeSwitchOutcome(False, f"{prefix} REJECTED by the mode service{reported} — {cost}")
    if curr_mode is not None and int(curr_mode) != mode_num:
        # Accepted-but-elsewhere: AP_DDS reports curr_mode AFTER the attempt, so status=True with a
        # different curr_mode means something else moved the mode. Treat as a failure, not a warning.
        return ModeSwitchOutcome(
            False, f"{prefix} reported success but the vehicle is in mode {curr_mode}, not "
                   f"{mode_num} — {cost}")
    return ModeSwitchOutcome(True, f"{prefix} accepted{reported}")


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
        # NON-BLOCKING on purpose: this runs inside the 5 Hz control-loop timer callback, and the
        # response is delivered by the SAME single-threaded executor — so spinning/waiting on the
        # future here would deadlock, not merely stall. It is NOT, however, self-healing. (The
        # comment that used to sit here
        # said "the loop re-asserts mode each maneuver" — it does not: ADR-006's maneuver shape is
        # "take over once, hold, resume once", so AvoidanceExecutor asserts the mode exactly ONCE per
        # takeover and once per hand-back and nothing re-sends a rejected switch.) That contradiction
        # is what let a FAILED GUIDED takeover pass silently while the executor went on streaming
        # setpoints ArduPilot was dropping. The done-callback below makes the outcome visible —
        # still without blocking the caller, which returns immediately as before.
        self._mode_cli.call_async(req).add_done_callback(
            lambda future: self._log_mode_switch_result(future, mode, mode_num))
        self._node.get_logger().info(f"[sink] set_mode {mode} ({mode_num}) requested")

    def _log_mode_switch_result(self, future, mode: str, mode_num: int) -> None:
        """Done-callback for the non-blocking `set_mode`: read the ModeSwitch response and log
        whether ArduPilot actually took the mode. Deliberately total — this runs on the rclpy
        executor thread, where a raised exception is swallowed (or takes the spin down with it), so
        every path ends in a log line and none of them throw. Message text comes from the pure
        `format_mode_switch_outcome` so the wording is unit-tested off-sim."""
        try:
            resp = future.result()
            if resp is None:
                raise RuntimeError("ModeSwitch future completed with no response object")
        except Exception as exc:  # noqa: BLE001 — call failed/cancelled: report it, never re-raise
            outcome = format_mode_switch_outcome(mode, mode_num, error=exc)
        else:
            outcome = format_mode_switch_outcome(
                mode, mode_num,
                status=getattr(resp, "status", None), curr_mode=getattr(resp, "curr_mode", None))
        logger = self._node.get_logger()
        (logger.info if outcome.ok else logger.error)(outcome.message)

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
