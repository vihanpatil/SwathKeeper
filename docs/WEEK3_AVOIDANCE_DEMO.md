# Week 3-4 — Live Avoidance-Loop Demo (ROS 2 adapter)

Run the tested reactive-avoidance loop **live** against ArduPilot SITL + Gazebo: a scripted bird
forces the drone to leave its lane, dodge (3D-safe), and resume the survey — with coverage-debt
logged. This is the differentiator moving on the real stack, not just in unit tests.

The loop logic (`avoidance_policy`, `avoidance_executor`, `geofence`) is sim-agnostic and unit-tested
(54 tests). Only two files touch ROS 2: `ros2_adapter.py` (the `VehicleCommandSink` → AP_DDS) and
`avoidance_node.py` (this node). Their pure parts (ENU↔geodetic, scripted source, waypoint pick) are
unit-tested; the rclpy parts are verified here, live.

## Prerequisites
All three validation gates must be green first (`docs/WEEK3_VALIDATION.md`): **Shell A** Gazebo,
**Shell B** SITL built `--enable-DDS`, **Shell C** the micro-ROS agent — all up, with `/ap/*` topics
publishing (`ros2 topic list | grep ^/ap` shows the 18 topics).

## One-time pre-flight check (do this before the first live run)
The adapter constructs `ardupilot_msgs/msg/GlobalPosition` and calls `ardupilot_msgs/srv/ModeSwitch`.
Confirm the field names + mode numbers match this build (they were not verifiable off-sim):
```bash
ros2 interface show ardupilot_msgs/msg/GlobalPosition   # expect: header, coordinate_frame, latitude, longitude, altitude, ...
ros2 interface show ardupilot_msgs/srv/ModeSwitch        # expect a request 'mode' (uint8)
```
If a field name differs, update `src/fieldguard_planning/ros2_adapter.py` accordingly (it fails loudly
at construction, never silently). ArduCopter modes: AUTO=3, GUIDED=4 (confirm with `mode` in MAVProxy).

## Run it (Shell D — 4th shell into the container)
```bash
docker exec -it fieldguard-sim bash
source /root/ardu_ws/install/setup.bash
cd /workspace/fieldguard
PYTHONPATH=src python3 -m fieldguard_planning.avoidance_node --demo
```
`--demo` injects a scripted bird parked on lane **x=30** at cruise altitude (a stand-in until the NDVI
detector lands in Weeks 5-6). Omit `--demo` to run with no detections (nominal pass-through).

Then in **Shell B (MAVProxy)** start the survey so the drone sweeps toward the bird:
```
param set MIS_RESTART 0
wp load /workspace/fieldguard/config/missions/boustrophedon.waypoints
param set AUTO_OPTIONS 3
mode auto
arm throttle
```

## What you should see (the money shot)
- **Shell D logs**: `set_mode GUIDED` → `cmd_gps_pose <- ENU(...)` → `set_mode AUTO` as the drone
  reaches lane x=30 near the bird — a takeover, a vetted dodge setpoint, and a resume.
- **Gazebo**: the drone leaves the straight lane, sidesteps away from the bird, then returns and
  continues the lawnmower pattern (MIS_RESTART=0 resumes the same waypoint — ADR-006).
- **On `Ctrl-C` (Shell D)**: writes `eval/results/live_flight_log.json` — the same flight-log contract
  the QA scenarios consume, so you can score/validate the real run afterward.

## Honest caveats
- **Message field names + mode numbers** are verify-in-container (above) — I could not check them off-sim.
- **The bird is scripted**, not detected: the real NDVI blob detector on the gimbal camera is the
  Weeks 5-6 pipeline (ADR-003 on the real render). The demo proves the *control + avoidance* path;
  perception plugs into the same `detection_source` seam later.
- **`current_waypoint` is derived** from pose + the loaded mission (nearest waypoint), because AP_DDS
  exposes no mission-current service (ADR-006). Fine for resume bookkeeping; ArduPilot owns the actual resume.
- Not yet a colcon package (`ros2 run`): run via `python3 -m` as above. Packaging is a small follow-up.
