"""Tests for the import-safe parts of the ROS 2 adapter (ros2_adapter.py).

The rclpy pieces (Ros2VehicleSink's publisher/client construction) import ardupilot_msgs lazily and
are verified live in the container. Testable off-sim, and tested here:

  * the ENU<->geodetic conversion — the one piece that MUST be exactly right, because a wrong
    ENU->lat/lon transform sends the drone to the wrong place: a safety issue, not cosmetic.
  * the mode-number map.
  * the mode-switch response reader (`format_mode_switch_outcome` + `_log_mode_switch_result`). The
    set_mode call is fire-and-forget by design, and ADR-006 asserts the mode exactly once per
    takeover, so nothing retries a rejection — the log line IS the failure signal, which makes its
    wording and its log level load-bearing rather than cosmetic.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fieldguard_planning.ros2_adapter import (  # noqa: E402
    enu_to_geodetic, load_home, AP_COPTER_MODE, Ros2VehicleSink, format_mode_switch_outcome,
)
from fieldguard_planning.mission_waypoints import latlon_to_enu  # noqa: E402


class TestEnuGeodetic(unittest.TestCase):
    def setUp(self):
        self.home_lat, self.home_lon, self.home_alt = load_home()

    def test_home_maps_to_itself(self):
        lat, lon, alt = enu_to_geodetic(0.0, 0.0, 0.0, self.home_lat, self.home_lon, self.home_alt)
        self.assertAlmostEqual(lat, self.home_lat, places=9)
        self.assertAlmostEqual(lon, self.home_lon, places=9)
        self.assertAlmostEqual(alt, self.home_alt, places=6)

    def test_altitude_is_home_plus_up(self):
        _, _, alt = enu_to_geodetic(0.0, 0.0, 15.0, self.home_lat, self.home_lon, self.home_alt)
        self.assertAlmostEqual(alt, self.home_alt + 15.0, places=6)

    def test_roundtrip_against_latlon_to_enu(self):
        """enu_to_geodetic must be the exact inverse of mission_waypoints.latlon_to_enu (the transform
        used to BUILD the mission), so a setpoint round-trips to the same ENU point sub-millimetre."""
        for e, n, u in [(10.0, 5.0, 15.0), (-20.0, 40.0, 12.0), (75.0, 60.0, 20.0), (0.0, 0.0, 0.0)]:
            lat, lon, _ = enu_to_geodetic(e, n, u, self.home_lat, self.home_lon, self.home_alt)
            e2, n2 = latlon_to_enu(lat, lon, self.home_lat, self.home_lon)
            self.assertAlmostEqual(e2, e, places=6, msg=f"east round-trip off for ENU=({e},{n},{u})")
            self.assertAlmostEqual(n2, n, places=6, msg=f"north round-trip off for ENU=({e},{n},{u})")

    def test_mode_numbers(self):
        self.assertEqual(AP_COPTER_MODE["AUTO"], 3)
        self.assertEqual(AP_COPTER_MODE["GUIDED"], 4)


class TestFormatModeSwitchOutcome(unittest.TestCase):
    """The message logic behind the /ap/mode_switch done-callback."""

    def test_accepted_switch_is_ok(self):
        out = format_mode_switch_outcome("GUIDED", 4, status=True, curr_mode=4)
        self.assertTrue(out.ok)
        self.assertIn("GUIDED", out.message)
        self.assertIn("accepted", out.message)

    def test_accepted_without_curr_mode_is_still_ok(self):
        self.assertTrue(format_mode_switch_outcome("AUTO", 3, status=True).ok)

    def test_rejected_guided_takeover_names_the_dropped_setpoint(self):
        """A refused GUIDED takeover is the dangerous one: the executor goes on streaming setpoints
        that ArduPilot silently drops outside GUIDED+armed, so the dodge never flies. The log line
        has to say that, not just 'mode switch failed'."""
        out = format_mode_switch_outcome("GUIDED", 4, status=False, curr_mode=3)
        self.assertFalse(out.ok)
        self.assertIn("REJECTED", out.message)
        self.assertIn("/ap/cmd_gps_pose", out.message)
        self.assertIn("dodge is NOT flying", out.message)
        self.assertIn("mode 3", out.message)          # reports where the vehicle actually is

    def test_rejected_auto_handback_names_its_own_consequence(self):
        """The AUTO hand-back fails differently: the drone hovers at the dodge point instead."""
        out = format_mode_switch_outcome("AUTO", 3, status=False, curr_mode=4)
        self.assertFalse(out.ok)
        self.assertIn("coverage is stalling", out.message)

    def test_every_supported_mode_has_a_specific_consequence(self):
        generic = "the vehicle is not in the commanded mode"
        for mode, num in AP_COPTER_MODE.items():
            out = format_mode_switch_outcome(mode, num, status=False)
            self.assertFalse(out.ok)
            self.assertNotIn(generic, out.message,
                             msg=f"{mode} fell through to the generic consequence text")

    def test_success_with_a_different_curr_mode_is_a_failure(self):
        """AP_DDS reports curr_mode AFTER the attempt; status=True but a different mode means
        something else moved it. Not a warning — the setpoints are still being dropped."""
        out = format_mode_switch_outcome("GUIDED", 4, status=True, curr_mode=3)
        self.assertFalse(out.ok)
        self.assertIn("reported success", out.message)

    def test_missing_status_field_cannot_confirm_rather_than_reject(self):
        """A ModeSwitch.Response shape mismatch at the pinned SHA is a different failure from a
        refusal, and must not be laundered into one."""
        out = format_mode_switch_outcome("GUIDED", 4, status=None)
        self.assertFalse(out.ok)
        self.assertIn("CANNOT CONFIRM", out.message)
        self.assertNotIn("REJECTED", out.message)

    def test_no_response_reports_the_underlying_error(self):
        out = format_mode_switch_outcome("GUIDED", 4, error=RuntimeError("service went away"))
        self.assertFalse(out.ok)
        self.assertIn("no response", out.message)
        self.assertIn("service went away", out.message)


class _FakeLogger:
    def __init__(self):
        self.info_lines = []
        self.error_lines = []

    def info(self, line):
        self.info_lines.append(line)

    def error(self, line):
        self.error_lines.append(line)


class _FakeNode:
    def __init__(self):
        self._logger = _FakeLogger()

    def get_logger(self):
        return self._logger


class _FakeSink:
    """Minimal stand-in for Ros2VehicleSink: `_log_mode_switch_result` touches only `self._node`, so
    the method can be exercised unbound without constructing the real sink (whose __init__ imports
    ardupilot_msgs, which exists only in the container)."""

    def __init__(self):
        self._node = _FakeNode()


class _DoneFuture:
    """A completed rclpy-style future: either a response object or a raised exception."""

    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc

    def result(self):
        if self._exc is not None:
            raise self._exc
        return self._response


class _Response:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class TestModeSwitchDoneCallback(unittest.TestCase):
    """The done-callback runs on the rclpy executor thread, where a raised exception is swallowed or
    takes the spin down with it — so every path must end in a log line and none may throw."""

    def _run(self, future, mode="GUIDED", mode_num=4):
        sink = _FakeSink()
        Ros2VehicleSink._log_mode_switch_result(sink, future, mode, mode_num)
        return sink._node.get_logger()

    def test_accepted_response_logs_info_only(self):
        log = self._run(_DoneFuture(_Response(status=True, curr_mode=4)))
        self.assertEqual(len(log.info_lines), 1)
        self.assertEqual(log.error_lines, [])

    def test_rejected_response_logs_error_only(self):
        log = self._run(_DoneFuture(_Response(status=False, curr_mode=3)))
        self.assertEqual(log.info_lines, [])
        self.assertEqual(len(log.error_lines), 1)
        self.assertIn("REJECTED", log.error_lines[0])

    def test_service_exception_is_logged_not_raised(self):
        log = self._run(_DoneFuture(exc=RuntimeError("call cancelled")))
        self.assertEqual(len(log.error_lines), 1)
        self.assertIn("call cancelled", log.error_lines[0])

    def test_empty_response_is_reported(self):
        log = self._run(_DoneFuture(response=None))
        self.assertEqual(len(log.error_lines), 1)
        self.assertIn("no response", log.error_lines[0])

    def test_response_without_status_field_is_reported_as_unconfirmed(self):
        log = self._run(_DoneFuture(_Response(curr_mode=4)))
        self.assertEqual(len(log.error_lines), 1)
        self.assertIn("CANNOT CONFIRM", log.error_lines[0])

    def test_auto_handback_rejection_logs_the_auto_consequence(self):
        log = self._run(_DoneFuture(_Response(status=False, curr_mode=4)), mode="AUTO", mode_num=3)
        self.assertIn("coverage is stalling", log.error_lines[0])


if __name__ == "__main__":
    unittest.main()
