# Week 1 Bringup — Zero to a No-Obstacle Boustrophedon Mission

Owner: `robotics-sim-engineer`. Gate: **a boustrophedon mission flies end-to-end in Gazebo with
ArduPilot SITL, no obstacles, over ROS 2** — this is the Week 1-2 gate for the whole project. Don't
move on to Week 3-4 (trees/birds/avoidance) until every step below is green.

This doc assumes the dev machine is **macOS (Apple Silicon)**. Native ROS 2 + Gazebo + ArduPilot
SITL is not a practical target on macOS — everything below runs inside a Docker/Ubuntu container.
See `docs/DECISIONS.md` ADR-004 for why, and the "Pinned versions" section of `CLAUDE.md` for the
versions once the human has confirmed them (this doc references them but does not set them).

## 0. Definition of done for this doc

- [ ] `colcon build` succeeds with zero errors inside the container.
- [ ] ArduPilot SITL boots standalone (no Gazebo) and can arm/takeoff/land via MAVProxy.
- [ ] Gazebo (headless) boots with the `ardupilot_gazebo` plugin loaded and the farm-world stand-in
      (empty/runway world is fine for Week 1) renders.
- [ ] SITL ⟷ Gazebo JSON backend connects — actuator commands from SITL move the model in Gazebo.
- [ ] ROS 2 topics for pose/telemetry are visible via `ros2 topic list` / `ros2 topic hz`.
- [ ] A boustrophedon waypoint file flies AUTO end-to-end and lands, no obstacles, with a rosbag
      capturing the run as proof.

Each numbered step below ends with its own explicit verification command — **do not proceed past a
step until its check is green.** This is the single biggest time-saver in this stack: SITL, Gazebo,
and the ROS 2 bridge each fail in different, easily-confused ways, and conflating them costs hours.

---

## 1. Host-side prerequisites (macOS, run locally — no repo files)

- Docker Desktop for Mac, running, with Apple Silicon (arm64) as confirmed on this machine.
  Allocate generously in Docker Desktop → Settings → Resources: **≥6 CPUs, ≥8GB RAM, ≥40GB disk**.
  Gazebo + ROS 2 Humble desktop + ArduPilot build artifacts are heavy.
- Free disk: colcon build + Gazebo + ArduPilot source easily reach 15-20GB before any world assets.
- Optional, only if you want a live Gazebo GUI window instead of pure headless: install XQuartz.
  Not required for Week 1 — see the rendering gotcha below for why headless is the recommended
  default.
- Confirm Docker is actually running before anything else: `docker info` should return cleanly
  (it errored with no daemon response when last checked in this session — start Docker Desktop
  first).

## 2. Build the container image (produces a repo file: `sim/docker/Dockerfile`)

A starter Dockerfile sketch lives at `sim/docker/Dockerfile` in this repo. It is intentionally
minimal — a Week 1 "get it green" image, not a hardened/CI-ready one. `devops-reliability-engineer`
owns turning this into the production image (multi-stage build, non-root user, exact SHA pins
baked in, CI wiring) once the versions below are confirmed and Week 1 is green.

Build it (run locally on the Mac host):

```bash
cd /Users/vihanpatil/personal/projects/auto-drone-sim
docker build -t fieldguard-sim:week1 -f sim/docker/Dockerfile .
```

Run it, mounting the repo in so edits to `sim/`, `config/`, `src/` are visible without rebuilding
the image, and using a **named volume** for the colcon workspace (see gotcha #3 — bind-mounted
`build/`/`install/` on macOS Docker Desktop is painfully slow):

```bash
docker volume create fieldguard_ardu_ws

docker run -it --rm \
  --name fieldguard-sim \
  -v "$(pwd)":/workspace/fieldguard \
  -v fieldguard_ardu_ws:/root/ardu_ws \
  -p 14550:14550/udp \
  -p 14551:14551/udp \
  fieldguard-sim:week1 \
  bash
```

**Verify:** the shell prompt comes up inside the container, and `ls /opt/ros/humble/setup.bash` and
`gz sim --version` both resolve. (Check the setup file with `ls`, not `printenv ROS_DISTRO` — the
Dockerfile sets `ENV ROS_DISTRO=humble`, so `printenv` prints `humble` even on a broken image where
ROS never actually installed. The file existing is the real proof.)

## 3. Import + build the ROS 2 / Gazebo / ArduPilot workspace (inside the container)

> **Before §3 — confirm your shell is _inside the container_, not the macOS host:** run
> `ls /opt/ros/humble/setup.bash` and it must print the path (on the host it says "No such file").
> Your prompt should look like `root@<hash>:~#`. Also, if you edited `sim/docker/Dockerfile` since
> your last build, **rebuild the image (§2) first** — Dockerfile edits (e.g. ROS auto-sourcing in
> `.bashrc`) don't reach a running container until you rebuild. If `ros2` isn't found even though
> `setup.bash` exists, you're on a stale image; rebuild, or `source /opt/ros/humble/setup.bash` to
> unblock the current shell.

Following ArduPilot's own documented workflow (`ardupilot_gz`, see version confirmation below):

```bash
source /opt/ros/humble/setup.bash
export GZ_VERSION=harmonic

mkdir -p /root/ardu_ws/src
cd /root/ardu_ws
vcs import --input https://raw.githubusercontent.com/ArduPilot/ardupilot_gz/main/ros2_gz.repos --recursive src

# Add OSRF's Gazebo rosdep rules so rosdep can resolve the gz-* keys (gz-sim8, gz-msgs10, gz-plugin2,
# gz-cmake3, gz-transport13, sdformat14, ...) against GZ_VERSION. WITHOUT this, rosdep can't map those
# keys and ABORTS, installing nothing. This is ArduPilot's documented approach and is also baked into
# the image Dockerfile — safe to re-run here.
wget -q https://raw.githubusercontent.com/osrf/osrf-rosdep/master/gz/00-gazebo.list \
  -O /etc/ros/rosdep/sources.list.d/00-gazebo.list
rosdep update

rosdep install --from-paths src --ignore-src -y

# Build only what the Gazebo bringup needs. `--packages-up-to ardupilot_gz_bringup` pulls the ros_gz /
# ardupilot_gazebo / ardupilot_gz packages and skips micro_ros_agent — whose upstream micro_ros_msgs
# build is a known-flaky eProsima issue and isn't needed until the DDS bridge (§6). If micro_ros_agent
# still gets pulled in and fails, add: --packages-skip micro_ros_agent
colcon build --packages-up-to ardupilot_gz_bringup
```

**Verify:** `colcon build` finishes with `Summary: N packages finished [..]` and **0 packages
failed**. If arm64 apt/rosdep resolution breaks here (see gotcha #1), that's the first thing to
chase before touching anything else.

Record whatever the actual checked-out commit SHAs end up being once this succeeds (see §7) — that
snapshot is the real reproducibility pin, not just the branch names.

## 4. Sanity-check ArduPilot SITL alone, no Gazebo (isolates SITL issues from Gazebo issues)

```bash
cd /root/ardu_ws/src/ardupilot
Tools/environment_install/install-prereqs-ubuntu.sh -y   # first time only
./waf configure --board sitl
./waf copter

sim_vehicle.py -v ArduCopter --map --console
```

**Verify:** MAVProxy console connects, `mode guided`, `arm throttle`, `takeoff 5` climbs the
simulated vehicle in the pure dronekit-less SITL physics model (no Gazebo yet). Land, exit. If this
step fails, the problem is in the ArduPilot build, not the Gazebo/ROS 2 integration — fix here
first.

## 5. Launch Gazebo headless with the ArduPilot plugin

```bash
source /root/ardu_ws/install/setup.bash
gz sim -s -r --headless-rendering iris_runway.sdf   # or via the ardupilot_gz_bringup launch, see below
```

In practice, prefer the packaged launch file over a bare `gz sim` invocation — it wires the SDF
world, the plugin, and the ros_gz bridge in one shot:

```bash
ros2 launch ardupilot_gz_bringup iris_runway.launch.py rviz:=false use_gz_tf:=true
```

**Verify:** `gz topic -l` (or `ros2 topic list`, once the bridge is up) shows the world/clock/model
topics; no plugin-load errors in the console output. This is running gzserver headless (no gzclient
window) — correct default for a macOS host, see rendering gotcha below.

## 6. Confirm SITL ⟷ Gazebo JSON backend + ROS 2 bridge together

`ardupilot_gz_bringup`'s launch file starts SITL for you with the `gazebo-iris` frame already; if
running it manually:

```bash
sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --map --console
```

**Verify, in order:**
1. MAVProxy connects and `arm throttle` + `takeoff 5` visibly moves the model in Gazebo (rotors
   spin, altitude changes) — this confirms the SITL→Gazebo actuator path.
2. `ros2 topic list` shows ArduPilot's DDS topics (pose, battery, nav status, clock) — confirms the
   AP_DDS→ROS 2 bridge is alive.
3. `ros2 topic hz /ap/pose/filtered` (or the equivalent pose topic name — confirm exact name
   against your checked-out `ardupilot_gz`/AP_DDS version, names have moved before) reports a
   steady rate, not zero.

If (1) works but (2)/(3) don't: the DDS bridge or micro-ROS agent isn't running — check
`micro_ros_agent` came up as part of the launch file.

## 7. Record the exact versions that worked (produces edits to `CLAUDE.md`, human does this)

Once §3-6 are green, capture the actual resolved commit SHAs:

```bash
cd /root/ardu_ws/src
for d in ardupilot ardupilot_gazebo ardupilot_gz ros_gz sdformat_urdf; do
  echo "$d: $(git -C $d rev-parse HEAD)"
done
```

Paste these SHAs (plus the branch names from §8 below) into `CLAUDE.md`'s "Pinned versions"
section. **This is the human's call to accept, not mine to write** — see the summary at the end of
this task for the exact values to paste.

## 8. Fly a boustrophedon mission end-to-end, no obstacles

For Week 1, the boustrophedon path itself can be a **static waypoint file**, not yet generated by
`fieldguard_planning` (that package doesn't need to exist yet — see the layout recommendation).
Hand-author a small lawnmower `.waypoints` file over a placeholder field polygon (a flat, obstacle-
free rectangle is fine; the real farm world/tree rows are Week 3-4 scope) and load it:

```bash
mavproxy.py --master udp:127.0.0.1:14550
# in MAVProxy:
wp load /workspace/fieldguard/config/missions/week1_boustrophedon.waypoints
mode auto
arm throttle
```

**Verify:** the vehicle flies the full lawnmower pattern in Gazebo and lands (RTL or the mission's
own land waypoint), with no manual intervention after `mode auto`. Capture proof:

```bash
ros2 bag record -o /workspace/fieldguard/eval/week1_smoke_run /ap/pose/filtered /ap/battery /clock
```

That bag is the artifact that proves the gate is green — keep it (or a trimmed version) as the
Week 1 reference recording for `devops-reliability-engineer`'s demo-readiness work later.

---

## Known macOS gotchas

1. **No GPU passthrough into Docker Desktop, on Intel or Apple Silicon.** Gazebo's sensor rendering
   (ogre2) falls back to software rendering (llvmpipe) inside the container regardless of X11/
   XQuartz setup — there is no path to real GPU acceleration in-container on macOS today. This is
   fine for correctness (camera topics still publish, physics is unaffected) but expect the camera
   render pipeline (needed later for the NDVI camera) to run well under real-time. Don't burn time
   chasing GPU passthrough; budget wall-clock accordingly and keep camera resolution modest.
2. **arm64 package availability is the least-tested part of this stack.** ROS 2 Humble on Ubuntu
   22.04 arm64 is Tier 1 (should just work). Gazebo Harmonic's OSRF apt repo publishes arm64
   packages for Jammy, but this combination (Humble + Harmonic + `ardupilot_gazebo`'s C++ plugin,
   which is built from source and links `libgz-sim8-dev`) is far more commonly run/tested on amd64
   by the community. If `rosdep install` or the plugin build fails on arm64 with missing packages,
   fall back to `--platform linux/amd64` on `docker build`/`docker run` (Docker Desktop emulates via
   Rosetta) — slower, but a known-working escape hatch. Confirm arm64 works on Day 1, don't discover
   this mid-Week-2.
3. **Don't try to reach SITL/Gazebo from a native macOS GCS by default.** Docker Desktop on Mac runs
   containers inside a Linux VM; there's no `--network host` equivalent that behaves like native
   Linux. Run MAVProxy, Gazebo, and the ROS 2 nodes **all inside the same container** for Week 1 —
   simplest, and sidesteps host-networking confusion entirely. Only bother exposing UDP ports
   (`-p 14550:14550/udp`, already in the run command above) if you specifically want a host-side
   QGroundControl for visualization; Docker Desktop does transparently proxy published ports to
   `127.0.0.1` on the Mac host, so that path works when you need it.
4. **X11/XQuartz forwarding to see a live Gazebo GUI window is flaky on macOS** (wrong OpenGL
   version negotiated, XQuartz connection drops are a known community complaint). Default to
   headless (`gz sim -s -r --headless-rendering`, no `gzclient`/`-g`) for all of Week 1. If you want
   to *see* the drone fly, dump artifacts to the mounted `/workspace/fieldguard` volume (rosbag,
   or periodic PNG frame grabs from the camera topic) and view them with native macOS tools instead
   of running a GUI inside the container — much less setup risk than getting XQuartz working.
5. **macOS Docker Desktop bind-mount I/O is slow for heavy write workloads.** `colcon build`'s
   `build/`/`install/` directories churn a lot of small files — bind-mounting them from the repo
   (rather than a named volume, as done above) will make builds noticeably slower and is worth
   avoiding from the start.

## What runs where

| Step | Runs on | Produces |
|---|---|---|
| §1 Docker Desktop install/config | macOS host, human | nothing tracked |
| §2 Dockerfile | repo file (`sim/docker/Dockerfile`) | tracked |
| §2 `docker build` / `docker run` | macOS host, human (or a `scripts/` wrapper) | local image/container only |
| §3-8 | inside the container | workspace under a named volume (not tracked); rosbag/mission files under `config/`, `eval/` (tracked if kept) |
| §7 pasting SHAs into `CLAUDE.md` | human, in the repo | tracked |

## Next (out of scope for this doc)

Week 3-4: swap the placeholder runway world for the real farm world (field polygon, tree rows,
scripted bird actors) under `sim/worlds/`, and wire the reactive avoidance loop. Not blocked on
anything above except this gate being green.
