# Week 3 — Human Docker Validation Session (the gating run)

> ## ✅ RESULT (2026-08-05): all three gates PASSED — foundation confirmed live, core-loop build unblocked.
> - **Gate 1** ✅ farm world flies — armed, took off to 15 m, `Reached command #N` through the lanes.
> - **Gate 2** ✅ AP_DDS — all **18 `/ap/*` topics** present, exactly matching the ADR-005 contract. **ADR-005 confirmed.**
> - **Gate 3** ✅ resume — `MIS_RESTART=0`, AUTO→GUIDED→AUTO resumed at the interrupted leg, no restart. **ADR-006 confirmed.**
> - **6 real bringup bugs** found + fixed en route (bash-3.2 array, colcon `set -u`, MAVProxy, `future`, `micro_ros_msgs`, `--enable-DDS`).
> - **Still pending (correctly deferred):** ADR-003 real-render — no NDVI camera in sim yet (Weeks 5-6).

Owner: **human** (you), with `robotics-sim-engineer` + `flight-software-engineer` on standby for failures.
Created 2026-08-05 at the Week 3 standup. **This was the gate:** the Week 3 core-loop build was HELD until
Gates 1-3 passed (product-lead decision, 2026-08-05 — "gate on Docker first"). **Now cleared.**

## Why this exists

Everything built since Week 1 is validated only in pure-Python / synthetic data. This session runs the
real Gazebo + ArduPilot + ROS 2 stack once, end-to-end, to convert three "provisional" claims into
"confirmed" — or to surface breakage now, while there's still schedule to absorb it (Week 1 proved this
stack is fragile). **Do all three gates in ONE session; they share the same running sim.**

### Honest scope correction (read before you start)
Earlier notes (including ADR-003/005/006 and the standup) said "batch **all three** confirmation-pending
ADRs here." That was wrong. **ADR-003's real-render re-confirmation is NOT possible in this session** —
there is no NDVI camera in the sim yet (`sim/worlds/farmguard_field.sdf` has only the generic sensors
plugin; the NDVI dual-band render is the **Weeks 5-6** pipeline). This session proves **two** pending
items (ADR-005, ADR-006) + the Week-2 farm-world flight-check. ADR-003 stays gated on Weeks 5-6. Do not
attempt it now — there is nothing to render from.

## Prerequisites (macOS host)
1. Docker Desktop running.
2. Image built: `scripts/sim_docker_build.sh` (first time, or after Dockerfile changes).
3. Container up: `scripts/sim_docker_run.sh` — gives you a shell inside `fieldguard-sim` at
   `/workspace/fieldguard`. Open **three** shells into it as needed: `docker exec -it fieldguard-sim bash`.

All commands below run **inside the container**, not on the macOS host.

---

## Gate 1 — Farm world flies (confirms Week 2 workstream C)

**Shell A** — start Gazebo with the custom world:
```bash
scripts/run_farm_mission.sh
```
- ✅ PASS: no `Unable to find uri` / `Failed to load a world` in the output.
- Confirm a tree loaded: `gz topic -l | grep model/tree_row0_0`
- Confirm birds move (dynamic actors): `gz model -m bird_0 -p` run twice — pose should change.

**Shell B** — fly the unchanged boustrophedon mission (recipe is printed by the script; verbatim):
```bash
cd /root/ardu_ws/src/ardupilot && export PATH="$PWD/Tools/autotest:$PATH"
sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON \
  --add-param-file=/workspace/fieldguard/config/sitl_params/dds_udp.parm
# wait for the EKF-ready message (docs/runbooks/SIM_BRINGUP.md §6), THEN:
mode rtl                  # land any hover; wait for DISARMED
wp load /workspace/fieldguard/config/missions/boustrophedon.waypoints
wp list                   # confirm 15 items
param set DISARM_DELAY 0
param set AUTO_OPTIONS 3
mode auto
arm throttle
```
- ✅ PASS: MAVProxy reports `Reached command #N` through all lanes + RTL; Gazebo model sweeps the field
  holding ~15 m. **Keep `mav.tlog`** as the farm-world reference run.

---

## Gate 2 — AP_DDS publishes as verified (confirms ADR-005)

**Shell C** — start the micro-ROS agent (needed for `/ap/*`):
```bash
source /root/ardu_ws/install/setup.bash
ros2 run micro_ros_agent micro_ros_agent udp4 --port 2019
```
With Shells A (Gazebo), B (SITL, armed/flying), and C (agent) all up, from any ROS 2-sourced shell:
```bash
ros2 topic list   | grep '^/ap'            # expect 18 topics (ADR-005 locked contract)
ros2 service list | grep '^/ap'            # expect 6 services
ros2 topic hz   /ap/pose/filtered          # steady rate, not zero
ros2 topic echo /ap/pose/filtered --once   # sanity-check values
```
- ✅ PASS: the topic + service set **matches the ADR-005 contract** in `docs/DECISIONS.md`
  (spot-check `/ap/pose/filtered`, `/ap/navsat`, `/ap/cmd_gps_pose` subscriber, the 6 services).
- Sanity on frame reality (ADR-005): `/ap/pose/filtered` content is **world-ENU** (near the field
  origin in `config/field_polygon.json`) even though `frame_id` says `base_link`. Confirm the *values*
  look ENU-world, not body-frame.
- If a topic is missing, check in order: Shell C running; `param show DDS_ENABLE` == 1 (WEEK1 §6b).

---

## Gate 3 — ADR-006 resume behavior (the executor's core assumption)

This proves the AUTO→GUIDED→AUTO **resume** mechanism ADR-006 depends on, **before** the executor is
built — so the whole executor design rests on confirmed behavior, not a source-read assumption.

```bash
param set MIS_RESTART 0 ; param show MIS_RESTART      # must read 0 (deterministic resume, not restart)
# with the mission running (Gate 1), let it reach a mid-lane waypoint, then:
mode guided                                            # take control mid-mission
# (optional deeper test — command a setpoint via the ADR-006 primitive, world-ENU frame_id="map":)
#   ros2 topic pub --once /ap/cmd_gps_pose ardupilot_msgs/msg/GlobalPosition '{...safe point...}'
#   -> vehicle should move to it (honored only while armed + GUIDED)
mode auto                                              # hand back
```
- ✅ PASS: on re-entering AUTO the mission **RESUMES toward the same next waypoint** — it does **not**
  restart at waypoint 1. Confirm via MAVProxy `wp num` / the continuing `Reached command #N` sequence.
- ✅ PASS (optional): a `/ap/cmd_gps_pose` setpoint in GUIDED moves the vehicle; the same command is
  silently ignored outside GUIDED/disarmed (ADR-006 gating).

---

## On any gate failure
**STOP.** Capture the failing shell's output + `mav.tlog` + the `ros2 topic list`. This is the
fragile-stack risk materializing — report it back so `robotics-sim-engineer` / `flight-software-engineer`
can triage while there's still schedule. Do **not** proceed to the loop build on a red gate.

## When all three gates pass
Record the results in `docs/DECISIONS.md` (flip ADR-005 and ADR-006 from "confirmation-pending" to
confirmed, with the date). Then the Week 3 core-loop build is unblocked. ADR-003 remains pending until
the Weeks 5-6 NDVI render exists — that's the correct, honest state.
