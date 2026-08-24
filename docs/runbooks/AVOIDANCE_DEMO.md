# Avoidance Demo — the Live Reactive-Avoidance Loop *(runbook; born Weeks 3-4)*

> ## PARTLY SUPERSEDED (2026-08-24) — read this first
> **What still stands:** the `--demo` scripted-bird procedure below. It is the deterministic
> regression arm and the A/B against perception (ADR-013 am. 2), and `avoidance_node --demo` is
> live code.
>
> **What is superseded — do not follow it:** everything here about *bringup and gates*. Use
> **[AVOIDANCE_REAL_DETECTION.md](AVOIDANCE_REAL_DETECTION.md)** for the detect→avoid flight
> (`--detect`, the ADOPTED ADR-003 am. 7 detector on the ADR-009 seam, with the full recording
> pipeline in the same take), and **[FULL_PIPELINE_DEMO.md](FULL_PIPELINE_DEMO.md)** +
> `scripts/fly_pipeline.sh up` for bringup. Three specific drifts, found live and reported rather
> than adapted around (ADR-013 am. 11):
> 1. the Prerequisites below delegate bringup to `docs/archive/WEEK3_VALIDATION.md`, whose SITL line
>    **lacks `--enable-DDS`** — it produces zero `/ap/*` topics, and the loop then watches a frozen
>    pose;
> 2. that archived doc's tree check (`gz topic -l | grep model/tree_row0_0`) is **structurally
>    stale**: trees and birds are `<static>` models (ADR-012) and advertise no pose topics, so it can
>    only ever prove a name exists. The current tree gate is `scripts/check_tree_positions.py`, run
>    post-flight on the stitched heatmap;
> 3. Shells A-D predate the launcher — the current path is one `fly_pipeline.sh up` plus one
>    `docker exec`.
>
> The Weeks-5-6 future tense in "Honest caveats" is also closed: the real detector landed and is
> ADOPTED (ADR-003 am. 7).

Run the tested reactive-avoidance loop **live** against ArduPilot SITL + Gazebo: a scripted bird
forces the drone to leave its lane, dodge (3D-safe), and resume the survey — with coverage-debt
logged. This is the differentiator moving on the real stack, not just in unit tests.

The loop logic (`avoidance_policy`, `avoidance_executor`, `geofence`) is sim-agnostic and unit-tested
(33 tests across those three modules; repo-wide totals live in `docs/ROADMAP.md`). Only two files touch ROS 2: `ros2_adapter.py` (the `VehicleCommandSink` → AP_DDS) and
`avoidance_node.py` (this node). Their pure parts (ENU↔geodetic, scripted source, waypoint pick) are
unit-tested; the rclpy parts are verified here, live.

## Prerequisites
All three validation gates must be green first (`docs/archive/WEEK3_VALIDATION.md`), brought up in THIS ORDER:
**Shell A** Gazebo, **Shell B** the micro-ROS agent (`ros2 run micro_ros_agent micro_ros_agent udp4
--port 2019`), **Shell C** SITL built `--enable-DDS`.

> **Agent BEFORE SITL.** AP_DDS's client pings the agent at startup; if the agent isn't already
> listening on port 2019, SITL prints `AP: DDS: No ping response, exiting` and **no `/ap/*` data ever
> flows** (the loop then sees a frozen pose). If you started SITL first and see that message, start the
> agent, and if the spam doesn't stop within ~15 s, restart SITL with the agent already running.

Confirm the bridge is live before flying: `ros2 topic hz /ap/pose/filtered` must show a **steady rate**
(and `ros2 topic list | grep ^/ap` shows the 18 topics).

## One-time pre-flight check (do this before the first live run)
The adapter constructs `ardupilot_msgs/msg/GlobalPosition` and calls `ardupilot_msgs/srv/ModeSwitch`.
**Verified 2026-08-05 against the pinned build**: `GlobalPosition` has `header, coordinate_frame,
type_mask, latitude, longitude, altitude, velocity, acceleration_or_force, yaw`; `ModeSwitch.Request`
has `mode` — the adapter's field usage matches. Re-confirm if the ArduPilot SHA is ever bumped:
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
PYTHONPATH=src:$PYTHONPATH python3 -m fieldguard_planning.avoidance_node --demo
```
> **`PYTHONPATH=src:$PYTHONPATH`, not `PYTHONPATH=src`** — a bare `PYTHONPATH=src` *replaces* ROS 2's
> Python path and you get `ModuleNotFoundError: No module named 'rclpy'`. Prepend, don't overwrite.
`--demo` injects a scripted bird parked on lane **x=30** at cruise altitude (a stand-in until the NDVI
detector lands in Weeks 5-6). Omit `--demo` to run with no detections (nominal pass-through).

Then at **Shell C's MAVProxy prompt** (the SITL shell — Shell B is the micro-ROS agent) start the
survey so the drone sweeps toward the bird:
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
- **On `Ctrl-C` (Shell D)**: writes `eval/results/live_flight_log_<UTCstamp>.json` (timestamped since 2026-08-18 — a new run can never clobber prior evidence; validate with `scripts/check_live_flight_log.py`) — the same flight-log contract
  the QA scenarios consume, so you can score/validate the real run afterward.

## Honest caveats
- **Message field names + mode numbers** are verify-in-container (above) — I could not check them off-sim.
- **The bird is scripted**, not detected: the real NDVI blob detector on the gimbal camera is the
  Weeks 5-6 pipeline (ADR-003 on the real render). The demo proves the *control + avoidance* path;
  perception plugs into the same `detection_source` seam later.
- **`current_waypoint` is derived** from pose + the loaded mission (nearest waypoint), because AP_DDS
  exposes no mission-current service (ADR-006). Fine for resume bookkeeping; ArduPilot owns the actual resume.
- Not yet a colcon package (`ros2 run`): run via `python3 -m` as above. Packaging is a small follow-up.
