---
name: adr006-avoidance-executor
description: ADR-006 — reactive avoidance = AUTO->GUIDED->AUTO, our code owns the maneuver; CONFIRMED live 2026-08-05. STILL OPEN: MIS_RESTART=0 is typed at flight time, not pinned in any param file
metadata:
  type: project
---

ADR-006 (reactive-avoidance executor) is **ACCEPTED, confirmation-pending** as of 2026-08-05. This is
the core-loop contract that unblocked perception + flight-software for Week 3. Decision: on a dynamic
bird detection during AUTO boustrophedon, our ROS 2 executor switches AUTO->GUIDED (via `/ap/mode_switch`
service), commands ONE pre-vetted avoidance setpoint, then switches GUIDED->AUTO to resume.

**Verified mechanisms @ pinned ArduPilot SHA 9895756d874ec9128d50918f6747a83706f4e221 (interview gold):**
- `/ap/cmd_vel` AND `/ap/cmd_gps_pose` are honored ONLY in GUIDED + armed — both route through
  `AP_ExternalControl_Copter::ready_for_external_control()` = `in_guided_mode() && motors->armed()`
  (ArduCopter/AP_ExternalControl_Copter.cpp). v1 primitive = `/ap/cmd_gps_pose` (GlobalPosition, a
  discrete point the safety gate can vet); cmd_vel is a valid alternative but is a velocity you'd have
  to integrate to safety-check.
- **Command frame = world-ENU with `frame_id="map"`.** For these COMMAND topics frame_id IS honored
  (real switch): `handle_velocity_control` maps "map" ENU->NED as {y,x,-z}, "base_link" = body frame.
  This is the OPPOSITE of [[adr005-apdds-contract]]'s /ap/pose/filtered where frame_id lies and content
  is authoritative. Sending base_link by mistake flies a body-frame dodge.
- **Resume = `MIS_RESTART=0`** (pinned in param file): AUTO re-entry runs `mission.start_or_resume()`
  -> `resume()` -> continues to the SAME next waypoint it was flying. No index manipulation needed for
  v1 (matches ADR-002 "return to next waypoint").
- **AP_DDS at this SHA has NO mission-current service** (only mode_switch/arm/prearm/takeoff/params).
  Skip/requeue would need MAVLink MAV_CMD_DO_SET_MISSION_CURRENT (`AP_Mission::set_current_cmd`) — a
  second control channel. This is the verified reason the ADR-002 STRETCH coverage-debt reconciliation
  is genuinely harder, not just deferred.

**Rejected:** (a) pure MAVLink/DO_REPOSITION — adds a 2nd control channel for no v1 benefit (it IS the
home for the stretch requeue though). (b) ArduPilot built-in OA (BendyRuler/Dijkstra/OA_*) — moves the
reactive decision INTO the autopilot, deleting priority #1 differentiator.

**Requirement handed to flight-software (their build):** a 3D safety gate must vet the avoidance setpoint
BEFORE GUIDED execution — target outside all geofenced-tree volumes AND within altitude bounds.
`geofence.py` is currently XY-only; must become altitude-aware. QA regression = `geo_avoid_into_tree`.
Reject-and-hover fallback; never execute an unvetted maneuver. Log takeover/maneuver/resume.

**How to apply:** treat AUTO->GUIDED->AUTO + cmd_gps_pose(map/ENU) + MIS_RESTART=0 as the locked core-loop
contract — don't relitigate. Open follow-up: live behavior (GUIDED accepts setpoint mid-mission; AUTO
resumes to intended waypoint) must be confirmed in the human Docker run. Now THREE confirmation-pending
items are all gated on that Docker run (ADR-003 real render, ADR-005 live topics, ADR-006 live resume)
— batch them into one session.
