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

# ros2_gz.repos pulls micro_ros_agent but NOT its runtime dependency micro_ros_msgs. Without it the
# agent BUILDS fine but dies at runtime (Week-3 bringup, docs/WEEK3_VALIDATION.md Gate 2):
#   micro_ros_agent: error while loading shared libraries:
#   libmicro_ros_msgs__rosidl_typesupport_cpp.so: cannot open shared object file: No such file or directory
# Clone it explicitly (branch humble, matching CLAUDE.md's micro-ROS pin) so colcon builds + installs it:
git clone -b humble https://github.com/micro-ROS/micro_ros_msgs.git src/micro_ros_msgs

# Add OSRF's Gazebo rosdep rules so rosdep can resolve the gz-* keys (gz-sim8, gz-msgs10, gz-plugin2,
# gz-cmake3, gz-transport13, sdformat14, ...) against GZ_VERSION. WITHOUT this, rosdep can't map those
# keys and ABORTS, installing nothing. This is ArduPilot's documented approach and is also baked into
# the image Dockerfile — safe to re-run here.
wget -q https://raw.githubusercontent.com/osrf/osrf-rosdep/master/gz/00-gazebo.list \
  -O /etc/ros/rosdep/sources.list.d/00-gazebo.list
rosdep update

rosdep install --from-paths src --ignore-src -y

# ArduPilot's SITL build (AP_DDS / ROS 2 enabled on master) needs the microxrceddsgen code generator
# on PATH, or waf fails with "Could not find the program ['microxrceddsgen']". It's baked into the
# image Dockerfile; if you're on an image without it, install it once (v4.7.0 for firmware 4.7+):
#   apt-get install -y default-jdk
#   git clone --recurse-submodules --branch v4.7.0 https://github.com/ardupilot/Micro-XRCE-DDS-Gen.git /opt/Micro-XRCE-DDS-Gen
#   (cd /opt/Micro-XRCE-DDS-Gen && ./gradlew assemble)
#   export PATH="$PATH:/opt/Micro-XRCE-DDS-Gen/scripts"

# Build up to the Gazebo bringup target. Pulls the ros_gz / ardupilot_gazebo / ardupilot_gz packages
# (and micro_ros_agent, which builds fine once the OSRF rosdep deps above are installed).
#
# MEMORY (macOS Docker Desktop): ros_gz_bridge generates large, template-heavy message-conversion
# files; compiling them in parallel can exhaust Docker's RAM and get the compiler OOM-killed
# ("fatal error: Killed signal terminated program cc1plus"). If that happens, cap parallelism:
#   MAKEFLAGS="-j2" colcon build --packages-up-to ardupilot_gz_bringup --executor sequential
# (drop to -j1 if it still OOMs) and/or raise Docker Desktop memory (Settings > Resources) to ~12 GB.
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

# MAVProxy gives you the SITL command console. This is lighter than the full first-time setup
# (Tools/environment_install/install-prereqs-ubuntu.sh -y), which also works but installs a lot.
python3 -m pip install --upgrade MAVProxy pymavlink future   # 'future' is a MAVProxy runtime dep

# HEADLESS (macOS Docker): do NOT pass --map/--console — those open wxPython GUI windows that need an
# X display the container doesn't have. Plain sim_vehicle.py runs MAVProxy as a text prompt right here.
# (ardupilot_sitl already built arducopter in §3, so this starts fast.)
# sim_vehicle.py lives in Tools/autotest and isn't on PATH unless install-prereqs added it — add it:
export PATH="$PWD/Tools/autotest:$PATH"
sim_vehicle.py -v ArduCopter
```

**Verify:** at the MAVProxy text prompt (`MAV>` / `GUIDED>`), wait for a GPS/EKF-ready message
(`EKF3 IMU0 is using GPS`), then:

```
param set DISARM_DELAY 0   # stop the ~10 s ground auto-disarm from racing your takeoff
mode guided
arm throttle
takeoff 5
```

Expect `NAV_TAKEOFF: ACCEPTED` and the altitude climbing (`status` shows `Alt`), in the pure SITL
physics model (no Gazebo yet). Gotchas: the vehicle auto-disarms ~10 s after arming if it hasn't
taken off, so a late/garbled takeoff then fails on a disarmed vehicle (hence `DISARM_DELAY 0`); and
the periodic `Flight battery 100 percent` lines are just telemetry noise — type your commands over
them. `Ctrl-D`/`exit` to quit. If this fails, the problem is in the ArduPilot build, not the
Gazebo/ROS 2 integration — fix here first.

## 5. Launch Gazebo headless with the ArduPilot plugin

Two prerequisites the image now bakes in, but which are the difference between a loading and a
non-loading world (both cost real debugging time the first time):
- **`libdebuginfod1`** must be installed, or `ardupilot_gazebo`'s `libGstCameraPlugin.so` fails to
  load (`libdebuginfod.so.1: cannot open shared object file`).
- **`GZ_SIM_RESOURCE_PATH` must include `ardupilot_gazebo`'s `share` dir**, or the `package://` URIs
  in the `iris_with_gimbal` model don't resolve and the **entire world fails to load**
  (`Unable to find uri[package://ardupilot_gazebo/models/...]` → `Failed to load a world`). The
  container `.bashrc` sets this; if you build a fresh env, re-add it:

```bash
source /root/ardu_ws/install/setup.bash
export GZ_SIM_RESOURCE_PATH="$GZ_SIM_RESOURCE_PATH:/root/ardu_ws/install/ardupilot_gazebo/share"
```

**Recommended — run Gazebo and SITL as two separate processes** so each one's health is visible.
Shell A: start the world and leave it running:

```bash
gz sim -v4 -s -r --headless-rendering iris_runway.sdf
```
It should keep running with only cosmetic `gz_frame_id` warnings — no `Unable to find uri` and no
`Failed to load a world`. (This continues straight into §6.)

**The all-in-one launch** wires world + plugin + ros_gz bridge + micro_ros_agent + SITL together, but
is flakier about startup ordering (SITL can race Gazebo's plugin, then exit) and needs the same env
above. Prefer it *after* the two-piece flow is proven, and always `pkill -9 -f 'arducopter|mavproxy|gz sim'`
first:

```bash
ros2 launch ardupilot_gz_bringup iris_runway.launch.py rviz:=false use_gz_tf:=true
```

**Verify:** the world stays up with no `Unable to find uri` / `Failed to load a world`. Running
gzserver headless (no gzclient window) is the correct default on a macOS host.

## 6. Confirm SITL ⟷ Gazebo JSON backend + ROS 2 bridge together

With the world from §5 running in shell A, start SITL wired to Gazebo in shell B (headless: no
`--map`/`--console`, which need an X display):

```bash
cd /root/ardu_ws/src/ardupilot
export PATH="$PWD/Tools/autotest:$PATH"
sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON
```

**Verify, in order:**
1. First boot often shows `AP: Frame: UNSUPPORTED` and repeated `PreArm: Motors: Check frame class
   and type`. The gazebo-iris `FRAME_CLASS 1` / `FRAME_TYPE 1` params load but only apply to the motor
   mixer after a reboot. Fix once at the `MAV>` prompt: `param set FRAME_CLASS 1` →
   `param set FRAME_TYPE 1` → `reboot`; wait ~15 s for reconnect (now `Frame: QUAD/X`). Then
   `param set DISARM_DELAY 0` → `mode guided` → `arm throttle` → `takeoff 5` climbs, and the model
   moves in Gazebo — confirming the SITL ⟷ Gazebo JSON actuator path.
2. **AP_DDS → ROS 2 (`/ap/*` topics) is a separate follow-up**, not automatic: the default
   gazebo-iris params do **not** set `DDS_ENABLE`, so `ros2 topic list | grep '^/ap'` is empty until
   DDS is enabled (a param / DDS-enabled param file). Not required to fly a mission (that uses
   MAVLink); see §6b below to enable it and confirm the `/ap/*` topics live.

## 6b. Enable AP_DDS (the ROS 2 `/ap/*` bridge)

(Week 2 workstream D, `flight-software-engineer`; **corrected 2026-08-05 at Week-3 Gate 2**.)
**AP_DDS is compiled OUT of SITL by default.** A plain `sim_vehicle.py` / `./waf configure --board sitl`
builds with `-DAP_DDS_ENABLED=0`, so the `DDS_ENABLE` parameter **does not exist** (`param show
DDS_ENABLE` is blank, `param set DDS_ENABLE 1` → "Unable to find parameter") and **no `/ap/*` topics
ever appear** no matter how the agent or param file are set. You MUST build SITL with `--enable-DDS`:

```bash
cd /root/ardu_ws/src/ardupilot
export PATH="$PWD/Tools/autotest:$PATH"
sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --enable-DDS \
  --add-param-file=/workspace/fieldguard/config/sitl_params/dds_udp.parm
```
(The first `--enable-DDS` build triggers a full waf reconfigure + recompile — expect a few minutes.
Re-running `sim_vehicle.py` **without** `--enable-DDS` reconfigures it back OFF, so always pass it.)

_Earlier this section wrongly claimed "DDS_ENABLE compiles in as on-by-default." That conflated two
things: the compile gate `AP_DDS_ENABLED` (OFF for SITL unless `--enable-DDS`) vs. the param's default
**value** once compiled._ Once AP_DDS is compiled in, `DDS_ENABLE` exists and defaults to 1
(`libraries/AP_DDS/AP_DDS_Client.cpp`, `ENABLED_BY_DEFAULT = 1` @ SHA `9895756d...`). The
`--add-param-file` above still sets `DDS_ENABLE 1` / `DDS_UDP_PORT 2019` explicitly, because a SITL
instance's `eeprom.bin` (persisted on the named volume, §2) keeps whatever value was saved the *first*
time DDS existed for that instance — so don't trust the compiled default value either.

`config/sitl_params/dds_udp.parm` sets `DDS_ENABLE 1` and `DDS_UDP_PORT 2019` — mirroring
ArduPilot's own `Tools/ros2/ardupilot_sitl/config/default_params/dds_udp.parm` at the pinned SHA
(what `ardupilot_gz_bringup`'s launch file loads by default). We load it via `--add-param-file`
rather than the launch file because this project's bringup deliberately bypasses that launch file
(custom world path, see §5-6 above) — see the param file's own header comment for why we do **not**
also load `dds_use_ns.parm` (keeps topic names as plain `/ap/<name>`, not `/ap/v1/<name>`).

DDS needs a **third shell**: the micro-ROS-DDS-XRCE agent, which the `ardupilot_gz_bringup` launch
file would normally spawn for you (`use_dds_agent:=True` → `ardupilot_sitl`'s
`sitl_dds_udp.launch.py` → a `micro_ros_agent` node, confirmed by reading that package's launch
source at the pinned ArduPilot SHA). Since we're not using that launch file, start it ourselves —
same container, localhost only, no new Docker port mapping needed (AP_DDS's default UDP peer is
`127.0.0.1` for non-ChibiOS boards, `libraries/AP_DDS/AP_DDS_config.h`):

```bash
# Shell C:
source /root/ardu_ws/install/setup.bash
ros2 run micro_ros_agent micro_ros_agent udp4 --port 2019
```

**Verify:** with shells A (Gazebo), B (SITL, `--add-param-file` above), and C (agent) all up:

```bash
ros2 topic list | grep '^/ap'      # expect ~19 topics, see docs/DECISIONS.md for the locked list
ros2 topic hz /ap/pose/filtered    # steady rate, not zero
ros2 service list | grep '^/ap'    # expect 6 services (arm_motors, mode_switch, ...)
```

The exact `/ap/*` topic names, message types, and frame_ids are **locked against our pinned
ArduPilot SHA** (not guessed) in `docs/DECISIONS.md` — that's the contract the Week 3-4
perception/planner ROS 2 nodes code against. If a topic is missing from `ros2 topic list`, check
(in order): shell C actually running, `DDS_ENABLE` really got set (`param show DDS_ENABLE` at the
`MAV>` prompt), and shell A/B connected (§6 point 1).

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

For Week 1 the boustrophedon path is generated by a standalone script — the MVP of the coverage
planner that becomes a `fieldguard_planning` ROS 2 node later. It writes a QGC WPL `.waypoints` file
over a flat, obstacle-free rectangle centered on the SITL home (the real farm world / tree rows are
Week 3-4 scope):

```bash
python3 /workspace/fieldguard/scripts/gen_boustrophedon.py \
  --width 80 --height 60 --spacing 15 --alt 15 \
  -o /workspace/fieldguard/config/missions/boustrophedon.waypoints
```

Then at the MAVProxy prompt of the running gazebo-iris SITL (§6): land any current hover, load the
mission, and fly it in AUTO. Copter starts an AUTO mission on throttle-up:

```
mode rtl                 # land the §6 hover first; wait for DISARMED
wp load /workspace/fieldguard/config/missions/boustrophedon.waypoints
wp list                  # confirm 15 items loaded
param set DISARM_DELAY 0
param set AUTO_OPTIONS 3  # Copter blocks arming in AUTO by default; bit0=allow arm, bit1=auto-takeoff
mode auto
arm throttle             # arms AND auto-starts the mission: NAV_TAKEOFF, the lanes, then RTL
```

**Verify:** the vehicle flies the full lawnmower in Gazebo and returns/lands (the mission's RTL) with
no manual input after `rc 3 1500`. MAVProxy prints `Reached command #N` as it hits each waypoint, and
the Gazebo model pose sweeps the field.

Proof capture (no ROS 2 bridge/DDS needed for v1): MAVProxy already writes a telemetry log
(`mav.tlog`) — keep it as the Week 1 reference run. Once AP_DDS is enabled (deferred), a
`ros2 bag record` of `/ap/pose/filtered` + `/clock` becomes the cleaner artifact for
`devops-reliability-engineer`'s demo-readiness work.

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
