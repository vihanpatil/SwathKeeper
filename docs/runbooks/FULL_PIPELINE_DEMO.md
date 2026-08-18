# Full Pipeline Demo — the SwathKeeper showpiece *(runbook)*

One flight, end to end: an autonomous boustrophedon survey over the farm world, scripted birds
flying their committed trajectories, the dual-band NDVI camera fusing in real time, every frame
recorded with a stamp-paired pose, and — after landing — the offline stitch that turns the flight
into a georeferenced crop-health heatmap on the same cell grid the coverage ledger uses.

Every command below is a **host-side one-liner** (each runs `docker exec` into the running
`fieldguard-sim` container) — one terminal tab per shell, in this order. Total wall time:
**~35-45 min**, dominated by the mission itself (the software-rendered sim runs at RTF ≈ 0.2;
the flight is ~5 sim-minutes).

**Shell 0 — is the container up?**
```bash
docker ps --filter name=fieldguard-sim
```
If it's not listed: `bash scripts/sim_docker_run.sh` first. If the container was *recreated* (not
just re-entered), re-install the three bridge runtime deps (container-ephemeral until the image is
rebuilt — see `NDVI_VALIDATION.md` session log):
```bash
docker exec fieldguard-sim bash -c 'apt-get update -qq && apt-get install -y -qq ros-humble-actuator-msgs ros-humble-gps-msgs ros-humble-vision-msgs'
```

---

## Shell 1 — Gazebo (the world)

```bash
docker exec -it fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && export GZ_SIM_RESOURCE_PATH="${GZ_SIM_RESOURCE_PATH:-}:/root/ardu_ws/install/ardupilot_gazebo/share" && gz sim -v4 -s -r --headless-rendering /workspace/fieldguard/sim/worlds/farmguard_field.sdf'
```
*What's happening:* the farm world loads headless — 18 calibrated-temperature trees, 3 bird
models, the drone with its ADR-007 dual-band camera pair (RGB Red + thermal-as-synthetic-NIR).
*Look for:* ~40 `Loaded system … Thermal` lines (the per-visual temperature authoring), all four
`fg/sensor/*` advertisements, **no** `Actor skin mesh` warnings (the pre-ADR-012 bug), no
`Failed to load a world`.

## Shell 2 — the sensor bridge (Gazebo → ROS 2)

```bash
docker exec -it fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && ros2 run ros_gz_bridge parameter_bridge --ros-args -p config_file:=/workspace/fieldguard/sim/bridge/fg_sensor_bridge.yaml'
```
*What's happening:* the locked `/fg/*` contract crosses into ROS 2.
*Look for:* **four** `Creating GZ->ROS Bridge` lines (the sensor topics only — the recorder reads
the sim clock natively via gz-transport, deliberately NOT through this bridge: Gazebo's /clock is
~350 msgs/s and bridging it starved the image pipeline, measured live). A missing-library crash
here means the Shell-0 apt step was skipped.

## Shell 3 — the micro-ROS agent (start BEFORE SITL — the golden rule)

```bash
docker exec -it fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && ros2 run micro_ros_agent micro_ros_agent udp4 --port 2019'
```
*What's happening:* the DDS doorway ArduPilot's ROS 2 interface walks through. It must be
listening before SITL boots or the `/ap/*` topics never appear.
*Look for:* `running... port: 2019`, then a burst of `create_*` lines once SITL starts.

## Shell 4 — ArduPilot SITL + MAVProxy

```bash
docker exec -it fieldguard-sim bash -c 'cd /root/ardu_ws/src/ardupilot && export PATH="$PWD/Tools/autotest:$PATH" && sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --enable-DDS --add-param-file=/workspace/fieldguard/config/sitl_params/dds_udp.parm'
```
*What's happening:* the real ArduPilot flight stack boots against Gazebo physics (`--enable-DDS`
and the param file are load-bearing — without them, zero `/ap/*` topics, silently).
*Look for:* `DDS: Initialization passed`, `EKF3 IMU0/IMU1 tilt alignment complete`,
`GPS 1: detected u-blox`. **Wait for all of those before flying** — arming during the post-boot
CPU spike earns `Arm: Accels inconsistent` (if you get it anyway: wait 30 s, retry).

## Shell 6 — the NDVI fusion node

```bash
docker exec -it fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && cd /workspace/fieldguard && PYTHONPATH=src:$PYTHONPATH python3 -m fieldguard_planning.ndvi_node'
```
*What's happening:* Red + synthetic-NIR frames pair by stamp and fuse into the authoritative
`/fg/ndvi/image` (NDVI = (NIR−Red)/(NIR+Red), per pixel, live).
*Look for:* `fieldguard_ndvi up`, then `fused_count=…` heartbeats once the camera renders.
`dropped_pair_count` should stay ~0.

## Shell 7 — the clip recorder (the evidence)

```bash
docker exec -it fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && cd /workspace/fieldguard && PYTHONPATH=src:$PYTHONPATH python3 -m fieldguard_planning.record_node --out /workspace/fieldguard/eval/results/clips/real_flight_$(date -u +%Y%m%dT%H%M%SZ)'
```
*What's happening:* every fused frame is written in the spike schema with a pose selected by
**gz-clock stamp pairing** — the recorder streams Gazebo's clock natively (a `gz topic`
subprocess, zero bridge load) and matches each frame's own stamp against gz-tagged poses, so
render bursts can't mislabel frames (the lesson of the first recorded flight, whose canopy landed
meters down-track and put 0/18 trees at their true spots).
*Look for:* `live intrinsics locked` (that line is ADR-007 follow-up-5 evidence) and the
**absence** of the arrival-fallback warning. Heartbeats:
`recorded N frames (M with rgb, K stale-pose flagged)` — K near zero.

## Fly it — Shell 4's MAVProxy prompt

```
wp load /workspace/fieldguard/config/missions/boustrophedon.waypoints
param set MIS_RESTART 0
param set AUTO_OPTIONS 3
wp set 1
mode guided
mode auto
arm throttle
```
*What's happening:* the generated lawnmower mission loads; the guided→auto bounce forces a fresh
AUTO entry at item 1 (re-entering AUTO after a finished mission is otherwise a no-op — learned
live); `AUTO_OPTIONS 3` lets AUTO take off armed.
*Look for:* `ARMED`, `height 15`, then `Reached command #N` marching through the lanes.

## Shell 5 — the birds (start AFTER `height 15`)

```bash
docker exec -it fieldguard-sim bash -c 'python3 /workspace/fieldguard/scripts/drive_birds.py --rate 2'
```
*What's happening:* the three bird models fly their committed JSON trajectories on **sim time**
(ADR-012) — correct at any real-time factor.
*Look for:* `sim-time mode … (RTF-proof)`, heartbeats `poses ok=N failed=0-ish`. Started after
arming on purpose: its service traffic adds jitter the EKF can't tolerate while aligning.

## After RTL + disarm

1. **Ctrl-C Shell 7 first.** Finalize converts the in-flight raw RGB dumps to schema PNGs
   (give it a minute), writes `meta.json` (`synthetic: false`), and prints the stitch command.
2. Ctrl-C the rest at leisure. Don't idle for ages first — parked frames add nothing.
3. **On the host** (repo root, no container needed):
```bash
python3 scripts/stitch_ndvi.py --clip eval/results/clips/<the dir Shell 7 printed>
```
*Look for:* `~700/720 cells imaged`, few stale-pose skips — and open `heatmap/heatmap.png`.

## The proof standard (what makes this demo honest)

A pretty heatmap is not the bar. The bar: **the 18 trees appear at their 18 known positions**
(`config/static_obstacles.json`) as high-NDVI cells against the negative-NDVI soil, and the birds'
committed patrol zones show as low-NDVI track marks. The first recorded flight LOOKED right and
failed exactly this check — which is the whole SwathKeeper story: a survey artifact is only
trusted when it can be cross-examined against ground truth, whether that's coverage debt in the
ledger or trees in the heatmap.
