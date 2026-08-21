#!/usr/bin/env bash
# SwathKeeper — one-command bringup for the full pipeline demo. Runs on the macOS HOST.
#
# Replaces the seven hand-typed terminal tabs of docs/runbooks/FULL_PIPELINE_DEMO.md with one
# tmux session (`swathkeeper`), one window per runbook shell. Each pane runs that shell's
# docker-exec one-liner **byte-identical to the runbook** (the payload strings below are copied
# from it verbatim) — the runbook stays the reference, this script stays auditable against it.
#
# What it adds over copy-paste: the ORDER and the GATES. Each gate is here because skipping it has
# already cost this project a flight:
#   * `up` REFUSES to run on top of a bringup that is already live in the container. Every gate
#     here is a liveness gate, so a stale Gazebo/bridge/agent makes all of them pass instantly
#     while the second micro-ROS agent silently loses the bind on 2019 and SITL talks to the old
#     one. Green lights, two worlds, nothing reproducible (QA review 2026-08-18).
#   * bridge only once Gazebo advertises the 4 /fg/sensor topics (a missing-library bridge crash
#     means the Shell-0 apt step was skipped — preflight now installs those deps).
#   * the render-alive probe is MANDATORY: a long-lived Gazebo silently degrades to sky-flat while
#     its topics stay alive, and the flight records plausible-looking nothing (2026-08-18). On
#     DEGRADED this restarts Gazebo + the bridge and re-probes, twice, then refuses to continue.
#   * micro_ros_agent BEFORE SITL — the golden rule; otherwise no /ap/* topic ever appears.
#   * birds NEVER start before arming: set_pose traffic is jitter the EKF cannot tolerate while
#     aligning (ADR-012 context), so the birds pane altitude-gates itself.
#   * teardown SIGINTs the RECORDER first and waits for finalize — the step that converts the raw
#     in-flight dumps to schema PNGs and writes meta.json.
#
# What `up` deliberately does NOT do: fly. No arming, no mode change, no `wp load` is ever sent from
# here. SITL stays interactive with a human at the MAVProxy prompt (see scripts/run_farm_mission.sh's
# header; ADR-013) — the sitl window just carries a second pane with the exact recipe beside it.
# The ONE exception is `test-flight` (ADR-013 amendment 2): a scripted regression gate that flies the
# short test mission unattended, and only ever after the same DDS/EKF/GPS readiness lines a human is
# told to wait for. Demo and recording flights stay human-flown. Its last gate is on the EVIDENCE,
# not the flight: a mission that completes while recording almost nothing is a FAIL (amendment 4).
#
# ADR-011: the `fieldguard` identifiers (container, /workspace path, /fg topics) are intentional.
#
# Usage (host, repo root):
#   scripts/fly_pipeline.sh [up|attach|status|birds|down|test-flight] [--dry-run] [--gate-geometry]
set -euo pipefail

SESSION="swathkeeper"
CONTAINER="fieldguard-sim"
CTR_REPO="/workspace/fieldguard"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMPBASE="${TMPDIR:-/tmp}"
RECIPE_FILE="${TMPBASE%/}/swathkeeper_fly_recipe.txt"

DRY_RUN=0
GATE_GEOMETRY=0
TESTFLIGHT=0
CMD="up"

GATE_GAZEBO_S=180      # world load = 18 thermal-authored trees + ogre2 warmup, software rendered
GATE_BRIDGE_S=90
GATE_AGENT_S=60
GATE_GEOMETRY_S=600
GATE_STOP_S=45         # how long a SIGINTed Gazebo gets to stop advertising before we refuse
FINALIZE_S=120         # recorder finalize: raw dumps -> schema PNGs -> meta.json
RENDER_RETRIES=2
POLL_S=3

# --- the runbook one-liners, payload-verbatim (docs/runbooks/FULL_PIPELINE_DEMO.md) --------------
# NB: none of these may contain a single quote — exec_line wraps them in one pair of them so the
# emitted command is character-for-character the runbook's. $PWD/$PYTHONPATH/$(date) stay literal
# on purpose: they are evaluated inside the container, at pane start — hence the SC2016 disables,
# which mark "not expanding here is the requirement", not an oversight.
# shellcheck disable=SC2016
INNER_GAZEBO='source /root/ardu_ws/install/setup.bash && export GZ_SIM_RESOURCE_PATH="${GZ_SIM_RESOURCE_PATH:-}:/root/ardu_ws/install/ardupilot_gazebo/share" && gz sim -v4 -s -r --headless-rendering /workspace/fieldguard/sim/worlds/farmguard_field.sdf'
INNER_BRIDGE='source /root/ardu_ws/install/setup.bash && ros2 run ros_gz_bridge parameter_bridge --ros-args -p config_file:=/workspace/fieldguard/sim/bridge/fg_sensor_bridge.yaml'
# shellcheck disable=SC2016
INNER_PROBE='source /root/ardu_ws/install/setup.bash && PYTHONPATH=/workspace/fieldguard/src:$PYTHONPATH python3 /workspace/fieldguard/scripts/check_render_alive.py'
INNER_AGENT='source /root/ardu_ws/install/setup.bash && ros2 run micro_ros_agent micro_ros_agent udp4 --port 2019'
# shellcheck disable=SC2016
INNER_SITL='cd /root/ardu_ws/src/ardupilot && export PATH="$PWD/Tools/autotest:$PATH" && sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --enable-DDS --add-param-file=/workspace/fieldguard/config/sitl_params/dds_udp.parm'
# shellcheck disable=SC2016
INNER_NDVI='source /root/ardu_ws/install/setup.bash && cd /workspace/fieldguard && PYTHONPATH=src:$PYTHONPATH python3 -m fieldguard_planning.ndvi_node'
# shellcheck disable=SC2016
INNER_RECORD='source /root/ardu_ws/install/setup.bash && cd /workspace/fieldguard && PYTHONPATH=src:$PYTHONPATH python3 -m fieldguard_planning.record_node --out /workspace/fieldguard/eval/results/clips/real_flight_$(date -u +%Y%m%dT%H%M%SZ)'
INNER_BIRDS='python3 /workspace/fieldguard/scripts/drive_birds.py --rate 2'
INNER_APT='apt-get update -qq && apt-get install -y -qq ros-humble-actuator-msgs ros-humble-gps-msgs ros-humble-vision-msgs'
# The three the bridge needs at RUNTIME. dpkg-checked in preflight, installed by INNER_APT (which
# keeps its own literal copy: that string is diffed against the runbook character for character).
DEPS=(ros-humble-actuator-msgs ros-humble-gps-msgs ros-humble-vision-msgs)

# The birds pane: the runbook's Shell-5 command, altitude-gated (see header / ADR-012 context).
# The 5 s poll (not 1 s) is deliberate: each pass spawns a `ros2 topic echo` python process, and
# the runbook's own performance rule is that CPU contention is what starves the camera pipeline.
# The last line is $INNER_BIRDS itself, not a copy: the altitude-gated path and the `birds` manual
# override then cannot drift from each other or from the runbook.
# shellcheck disable=SC2016
INNER_BIRDS_WATCH='source /root/ardu_ws/install/setup.bash
zget() { timeout 10 ros2 topic echo --once "$@" /ap/pose/filtered 2>/dev/null | sed -n "/position:/,/orientation:/ s/^ *z: *//p" | head -n 1; }
echo "[birds] altitude gate: drive_birds.py --rate 2 starts by itself once /ap/pose/filtered z > 10 m."
echo "[birds] Birds never start before arming on purpose: set_pose traffic is jitter the EKF cannot"
echo "[birds] tolerate while aligning. Arm and take off in the sitl window; this pane fires itself."
while true; do
  Z=$(zget --qos-reliability best_effort)
  [ -n "$Z" ] || Z=$(zget)
  if [ -z "$Z" ]; then
    echo "[birds] waiting: no /ap/pose/filtered yet (micro-ROS agent + SITL must be up)"
  elif python3 -c "import sys; sys.exit(0 if float(sys.argv[1]) > 10.0 else 1)" "$Z" 2>/dev/null; then
    echo "[birds] altitude $Z m > 10 m -- launching drive_birds.py --rate 2"
    break
  else
    echo "[birds] waiting for takeoff: altitude $Z m (need > 10 m)"
  fi
  sleep 5
done
exec '"$INNER_BIRDS"

# --- plumbing -----------------------------------------------------------------------------------
say()  { printf '[fly_pipeline] %s\n' "$*"; }
warn() { printf '[fly_pipeline] WARNING: %s\n' "$*" >&2; }
die()  { printf '[fly_pipeline] ERROR: %s\n' "$*" >&2; exit 1; }
now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# One timestamped line per PROVEN fact, for the test-flight gate record. No file set (every path
# except test-flight) = no-op, so the gates below can call it unconditionally.
EVIDENCE_FILE=""
evidence() {
  [ -n "$EVIDENCE_FILE" ] && printf '%s  %s\n' "$(now_utc)" "$*" >>"$EVIDENCE_FILE"
  return 0
}

usage() {
  cat <<EOF
scripts/fly_pipeline.sh [SUBCOMMAND] [FLAGS]      (host side, macOS; needs tmux + Docker Desktop)

  up        (default) preflight, then bring the 7 runbook shells up in order, gated
  attach    attach to the running '$SESSION' session (sitl window selected)
  status    session/window state + a read-only re-run of the live gates + the fly recipe
  birds     start drive_birds.py NOW, bypassing the altitude gate (drone must be airborne)
  down      SIGINT the recorder first, wait for finalize, stop the rest, print the stitch command
  test-flight  REGRESSION GATE, not the demo path: 'up', then fly the short test mission
               unattended (only after DDS+EKF+GPS ready), tear down, stitch, judge the flight's
               evidence yield against the floor, write a gate record under eval/results/.
               Demo/recording flights stay human-flown.

  --dry-run         print every docker/tmux command instead of running it (works with no Docker)
  --gate-geometry   also run scripts/verify_mount_geometry.sh after the bridge (one-time gate
                    after mount/world/georef changes; off by default — it launches its own world)
EOF
}

# Print args instead of running them under --dry-run. Outer tmux quoting is elided in the printout;
# the pane one-liner itself is printed verbatim so it can be diffed against the runbook.
run() {
  if (( DRY_RUN )); then printf '  DRY  %s\n' "$*"; return 0; fi
  "$@"
}

# The exact runbook one-liner for a payload.
exec_line() {
  case $1 in *\'*) die "internal: pane payload must not contain a single quote";; esac
  printf "docker exec -it %s bash -c '%s'" "$CONTAINER" "$1"
}

# Non-interactive docker exec used by the gates (stdout is consumed by the caller).
ctr() { docker exec "$CONTAINER" bash -c "$1"; }

# -J joins wrapped lines: without it the recorder's stitch line is cut at the pane width and the
# recovered clip path comes back truncated (caught in the tmux smoke test, not live).
pane_text() { tmux capture-pane -p -J -S -400 -t "$SESSION:$1" 2>/dev/null || true; }

# `capture-pane` renders the whole pane GRID, so every row below the cursor comes back as an empty
# line. A pane that talks constantly (birds) has its output at the bottom and tails fine; a QUIET
# pane — the ndvi node heartbeats once per 25 fused frames, the recorder every ~30 s — has its
# output at the TOP of an 80x24 grid, and a plain `tail -n 15` returns nothing but the padding
# underneath it. That, not capture timing, is why pane_tails["ndvi"] is 15 empty strings in BOTH
# committed gate records, and why the record pane's 3 real lines came back with 12 blanks after
# them. (Reproduced by hand against tmux 3.7c, 2026-08-19.) So: drop the padding, then tail.
# `|| true` because grep exits 1 on a pane that really is empty, and this script runs -o pipefail.
meaningful() { grep -v '^[[:space:]]*$' || true; }
pane_tail()  { pane_text "$1" | meaningful | tail -n "$2"; }

session_exists() {
  if (( DRY_RUN )); then return 1; fi
  tmux has-session -t "$SESSION" 2>/dev/null
}

# remain-on-exit keeps a crashed pane's output on screen instead of letting the window vanish.
# It cannot be set before the window exists, so a command that dies INSTANTLY takes its window with
# it and this set-option fails ("no such window") — verified in a throwaway tmux session. Under
# `set -e` that used to abort the script with a raw tmux error; now it is a named failure.
keep_output() {
  if (( DRY_RUN )); then run tmux set-option -w -t "$SESSION:$1" remain-on-exit on; return 0; fi
  tmux set-option -w -t "$SESSION:$1" remain-on-exit on 2>/dev/null && return 0
  die "the '$1' pane exited instantly and its window is already gone, so its output is lost.
  That is almost always the docker exec itself failing — container stopped mid-bringup, or the
  command missing from the image. Check:  docker ps --filter name=$CONTAINER
  Then tear down what did start:  scripts/fly_pipeline.sh down"
}

new_window() {
  run tmux new-window -d -t "$SESSION" -n "$1" "$2"
  keep_output "$1"
}

# True when the window is gone, or its pane has exited (remain-on-exit is holding the corpse).
# Lets a gate fail in seconds with the pane's tail instead of burning its whole timeout.
window_failed() {
  local dead
  dead=$(tmux display-message -p -t "$SESSION:$1" '#{pane_dead}' 2>/dev/null) || return 0
  [ "$dead" = "1" ]
}

# SIGINT every pane of a window, not just the active one: the sitl window has the recipe pane
# beside SITL, and whichever pane the user last clicked is the one `send-keys -t <window>` would
# have hit. Returns 1 if the window does not exist.
send_ctrl_c() {
  local p ids
  ids=$(tmux list-panes -t "$SESSION:$1" -F '#{pane_id}' 2>/dev/null) || return 1
  [ -n "$ids" ] || return 1
  while IFS= read -r p; do
    [ -n "$p" ] && tmux send-keys -t "$p" C-c 2>/dev/null || true
  done <<<"$ids"
}

# --- gate probes --------------------------------------------------------------------------------
probe_gz_topics() {
  local n
  n=$(ctr "source /root/ardu_ws/install/setup.bash >/dev/null 2>&1; timeout 10 gz topic -l" 2>/dev/null |
      grep -c '^/fg/sensor/' || true)
  [ "$n" -ge 4 ]
}

probe_ros_topics() {
  local n
  n=$(ctr "source /root/ardu_ws/install/setup.bash >/dev/null 2>&1; timeout 15 ros2 topic list" 2>/dev/null |
      grep -c '^/fg/sensor/' || true)
  [ "$n" -ge 4 ]
}

# 2019 == 0x07E3 in /proc/net/udp's local_address column. No ss/netstat dependency.
probe_agent_port() { ctr "grep -qiE ':07E3[[:space:]]' /proc/net/udp /proc/net/udp6" >/dev/null 2>&1; }

# Anything from a previous (or manual-runbook) bringup still alive in the container. Read-only.
# `ps` runs in the container; the grep runs on the host, so it cannot match itself.
running_sim_procs() {
  local all
  all=$(docker exec "$CONTAINER" ps -eo args= 2>/dev/null) || return 0
  [ -n "$all" ] || { warn "could not read the container process list — the already-running check
  below is inconclusive. If a bringup is already live, stop it before continuing."; return 0; }
  printf '%s\n' "$all" | grep -F -e 'gz sim ' -e 'parameter_bridge' -e 'micro_ros_agent ' \
    -e 'sim_vehicle.py' -e 'fieldguard_planning.ndvi_node' \
    -e 'fieldguard_planning.record_node' -e 'drive_birds.py' || true
}

# --- gates --------------------------------------------------------------------------------------
# gate <desc> <timeout_s> <probe_fn> <failure_hint> <window>
# Polls until the probe passes; a gate never silently gives up — it dies with the hint. The window
# is watched while polling: a dead pane fails the gate in seconds rather than burning the whole
# timeout in silence (a bridge that crashes on a missing library used to cost 90 s of nothing).
gate() {
  local desc=$1 timeout_s=$2 probe=$3 hint=$4 win=$5 waited=0
  if (( DRY_RUN )); then printf '  DRY  gate: %s (timeout %ss)\n' "$desc" "$timeout_s"; return 0; fi
  say "gate: $desc (up to ${timeout_s}s) ..."
  while (( waited < timeout_s )); do
    if pane_text "$win" | grep -q 'Failed to load a world'; then
      die "Gazebo printed 'Failed to load a world' — the world never loaded, so nothing downstream
  can work. Read the '$win' window (tmux attach -t $SESSION); the usual cause is
  GZ_SIM_RESOURCE_PATH or a moved model/world path."
    fi
    # Checked BEFORE the probe on purpose: every probe here is a liveness probe on a shared
    # resource, so a dead pane whose port/topic is held by something else would otherwise PASS.
    if window_failed "$win"; then
      printf '%s\n' "--- tail of the '$win' window ---" >&2
      pane_tail "$win" 20 >&2
      die "the '$win' pane exited before its gate passed (tail above): $desc. $hint"
    fi
    if "$probe"; then say "gate PASSED: $desc"; evidence "gate PASSED: $desc"; return 0; fi
    sleep "$POLL_S"; waited=$(( waited + POLL_S ))
  done
  die "gate FAILED after ${timeout_s}s: $desc. $hint"
}

gate_gazebo() {
  gate "Gazebo advertises the 4 /fg/sensor topics (gz topic -l)" "$GATE_GAZEBO_S" probe_gz_topics \
    "The world may be up while the ADR-007 camera pair is not advertising — read the gazebo window." \
    gazebo
}

gate_bridge() {
  gate "the 4 /fg/sensor topics cross into ROS 2 (ros2 topic list)" "$GATE_BRIDGE_S" probe_ros_topics \
    "A missing-library crash in the bridge window means the three runtime deps are absent (they are
  container-ephemeral until the image is rebuilt) — re-run 'up': preflight installs them." bridge
}

gate_agent() {
  gate "micro-ROS agent listening on UDP 2019" "$GATE_AGENT_S" probe_agent_port \
    "SITL must NOT boot before the agent (the golden rule) or no /ap/* topic ever appears." agent
}

# verify_mount_geometry.sh launches its OWN physics-free copy of the world alongside the flying
# one. It already isolates itself by NAME — its sed rewrites the world to `mountcheck` and the topic
# namespace to `mountcheck/sensor/*` — so there is no /fg/sensor collision to guard against and this
# runs the runbook's line verbatim, no extra env. (An earlier draft exported GZ_PARTITION here for a
# collision that does not exist; removed 2026-08-18 QA review.) What it genuinely costs is CPU: a
# second rendering Gazebo on the machine the runbook tells you to keep quiet. Hence off by default,
# and better run standalone before the bringup than during it.
gate_geometry_run() {
  local sh="$CTR_REPO/scripts/verify_mount_geometry.sh"
  local line="docker exec -it $CONTAINER bash $sh"
  if (( DRY_RUN )); then printf '  DRY  %s\n' "$line"; return 0; fi
  say "gate (--gate-geometry): camera aim vs the georef transform, up to ${GATE_GEOMETRY_S}s ..."
  if ! docker exec "$CONTAINER" timeout "$GATE_GEOMETRY_S" bash "$sh"; then
    die "geometry gate FAILED — do NOT trust any imagery recorded with this mount (ADR-007
  amendment 5: five flights were lost to a horizon-facing camera that every values-only gate
  passed). Re-run it alone with:  $line"
  fi
  say "gate PASSED: mount geometry agrees with the georef transform"
  evidence "gate PASSED: mount geometry vs the georef transform (verify_mount_geometry.sh exit 0)"
}

# Restart the world (and the bridge with it — it re-discovers a fresh gz-transport publisher, but
# restarting both is the reliable order) and re-gate. Used by the render-alive retry loop.
#
# The wait for the OLD world to disappear is load-bearing, not politeness. `respawn-window -k` kills
# the pane's `docker exec` CLIENT; the process it started lives in the container and is only killed
# indirectly (SIGINT through the pty, then SIGHUP when the pty closes). Respawning before that
# lands leaves TWO gz sim servers publishing /fg/sensor/* — and every gate downstream is a liveness
# gate, so all of them would go green on the corpse we were trying to replace.
restart_world() {
  if (( DRY_RUN )); then
    printf '  DRY  tmux send-keys C-c -> bridge, gazebo; wait <=%ss for /fg/sensor to clear\n' "$GATE_STOP_S"
  else
    send_ctrl_c bridge || true
    send_ctrl_c gazebo || true
    local waited=0
    while probe_gz_topics; do
      if (( waited >= GATE_STOP_S )); then
        die "the old Gazebo is still advertising /fg/sensor/* ${GATE_STOP_S}s after SIGINT, so a
  restart would leave two worlds publishing the same topics and every gate below would pass on the
  wrong one. Stop it by hand (attach: tmux attach -t $SESSION, gazebo window) or restart the
  container:  docker restart $CONTAINER   — then re-run: scripts/fly_pipeline.sh up"
      fi
      sleep "$POLL_S"; waited=$(( waited + POLL_S ))
    done
    sleep 3
  fi
  run tmux respawn-window -k -t "$SESSION:gazebo" "$(exec_line "$INNER_GAZEBO")"
  keep_output gazebo
  gate_gazebo
  run tmux respawn-window -k -t "$SESSION:bridge" "$(exec_line "$INNER_BRIDGE")"
  keep_output bridge
  gate_bridge
  if ! (( DRY_RUN )); then sleep 5; fi
}

# MANDATORY every flight. exit 0 = alive, 1 = degraded/suspect, 2 = no frame at all.
gate_render_alive() {
  if (( DRY_RUN )); then printf '  DRY  %s\n' "$(exec_line "$INNER_PROBE")"; return 0; fi
  local attempt=0 rc=0
  while true; do
    say "gate: render-alive probe (MANDATORY — pixels, not topics)"
    rc=0; docker exec "$CONTAINER" bash -c "$INNER_PROBE" || rc=$?
    if (( rc == 0 )); then
      say "gate PASSED: render alive"
      evidence "gate PASSED: render alive (check_render_alive.py exit 0, attempt $((attempt + 1)))"
      return 0
    fi
    if (( attempt >= RENDER_RETRIES )); then
      die "render probe still failing after $RENDER_RETRIES Gazebo restarts (last exit $rc).
  exit 1 = degraded/suspect pixels, exit 2 = no frame arrived at all. Do not fly: the flight would
  record plausible-looking nothing. Investigate the gazebo and bridge windows before retrying."
    fi
    attempt=$(( attempt + 1 ))
    warn "render probe exit $rc — restarting Gazebo + bridge (attempt $attempt/$RENDER_RETRIES)"
    restart_world
  done
}

# --- preflight (runbook Shell 0) ----------------------------------------------------------------
preflight() {
  if (( DRY_RUN )); then
    printf '  DRY  docker info                                   # is the daemon up?\n'
    printf '  DRY  docker ps -a --format {{.Names}} | grep -qx %s\n' "$CONTAINER"
    printf '  DRY  docker start %s                    # only if stopped; NOT -ai (that attaches)\n' "$CONTAINER"
    printf '  DRY  docker exec %s ps -eo args=          # refuse if a bringup is already live\n' "$CONTAINER"
    printf '  DRY  docker exec %s dpkg -s %s\n' "$CONTAINER" "${DEPS[*]}"
    printf '  DRY  %s\n' "$(exec_line "$INNER_APT")"
    return 0
  fi
  command -v docker >/dev/null 2>&1 || die "docker is not on PATH — install / start Docker Desktop."
  docker info >/dev/null 2>&1 || die "the Docker daemon is not responding — start Docker Desktop and retry."
  if ! docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    die "container '$CONTAINER' does not exist. Create it first:  bash scripts/sim_docker_run.sh
  (that one attaches you to a shell in it — detach/exit, then re-run this script)."
  fi
  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    say "container '$CONTAINER' exists but is stopped — starting it (docker start, NOT -ai)"
    docker start "$CONTAINER" >/dev/null
  fi
  say "container '$CONTAINER': running"

  # The one check no gate below can make for itself. Every gate here is a LIVENESS gate, so a
  # bringup already running in the container (a manual runbook session in other tabs, or a tmux
  # session killed without `down`) makes all of them pass instantly against the wrong processes:
  # the second Gazebo publishes /fg/sensor/* alongside the first, the second micro-ROS agent loses
  # the bind on UDP 2019 without the gate noticing, and SITL talks to whichever agent got there
  # first. All green, nothing reproducible. Refuse instead. (QA review 2026-08-18 — found this way:
  # `status` reported three green gates with no tmux session at all.)
  local live
  live=$(running_sim_procs)
  if [ -n "$live" ]; then
    die "a SwathKeeper bringup is already running inside '$CONTAINER':

$(printf '%s\n' "$live" | cut -c1-110 | sed 's/^/      /')

  Starting a second one would double-publish /fg/sensor/*, lose the UDP 2019 bind silently, and
  every gate below would still go green. Refusing.
    - if that is a manual FULL_PIPELINE_DEMO session, finish or Ctrl-C those tabs first;
    - if it is a leftover from a tmux session that was killed without 'down', clear it with
      docker restart $CONTAINER      (kills everything inside the container — nothing else is in it)
  Then re-run: scripts/fly_pipeline.sh up"
  fi

  # `dpkg -s` alone exits 0 for a package that is removed-but-config-files, which would skip the
  # install and hand you a missing-library bridge crash 90 s later. Demand all of them INSTALLED.
  local n_installed
  n_installed=$(docker exec "$CONTAINER" dpkg -s "${DEPS[@]}" 2>/dev/null |
                  grep -c '^Status: install ok installed' || true)
  if [ "${n_installed:-0}" -eq "${#DEPS[@]}" ]; then
    say "bridge runtime deps present"
  else
    say "bridge runtime deps missing (container-ephemeral until the image is rebuilt) — installing ..."
    docker exec "$CONTAINER" bash -c "$INNER_APT" ||
      die "apt install of ros-humble-{actuator-msgs,gps-msgs,vision-msgs} failed — see output above."
    say "bridge runtime deps installed"
  fi
}

# --- the fly recipe ------------------------------------------------------------------------------
# ONE source for the MAVProxy sequence: the recipe pane displays it (mission $1 = boustrophedon),
# `test-flight` types it (mission $1 = test_2lane). Nothing else may spell these lines out.
fly_lines() {
  cat <<EOF
wp load $CTR_REPO/config/missions/$1.waypoints
param set MIS_RESTART 0
param set AUTO_OPTIONS 3
wp set 1
mode guided
mode auto
arm throttle
EOF
}

print_fly_recipe() {
  cat <<'EOF'
======== SwathKeeper — FLY IT (you type these; 'up' never does) ========
WAIT for all three in the sitl pane before arming:
    DDS: Initialization passed
    EKF3 IMU0/IMU1 tilt alignment complete
    GPS 1: detected u-blox
  Arming during the post-boot CPU spike earns "Arm: Accels inconsistent" — wait 30 s, retry.

Then, at the MAVProxy prompt:
EOF
  fly_lines boustrophedon | sed 's/^/    /'
  cat <<'EOF'
  Look for: ARMED, height 15, then "Reached command #N" marching through the lanes.

BIRDS: the birds window fires drive_birds.py by itself once altitude > 10 m — nothing to do.
  Manual override, only when airborne:  scripts/fly_pipeline.sh birds

KEEP THIS MAC QUIET while recording. Proven twice: with builds / test suites / parallel agents
  running, the bands drop frames independently, fusion pairing starves, and the recorder can lose
  >90% of the flight. Symptoms: ndvi fused_count crawling, birds' failed count past ~20%, record
  heartbeats minutes apart.

AFTER RTL + disarm:  scripts/fly_pipeline.sh down
  (SIGINTs the recorder FIRST, waits for finalize, then prints the host-side stitch command.)
===============================================================================
EOF
}

# --- teardown helpers ---------------------------------------------------------------------------
# The clip dir out of any stream that carries a `--clip <dir>` (the recorder's own next-step line,
# or this script's stitch hint). Last one wins: the newest line is the current clip.
parse_clip() { sed -n 's#.*--clip \([^[:space:]]*\).*#\1#p' | tail -n 1; }

# The altitude the birds pane fired its OWN gate at:
#   "[birds] altitude 12.34 m > 10 m -- launching drive_birds.py --rate 2"
# ONE anchor, on "launching", and deliberately so: the pane's "waiting for takeoff: altitude 3.2 m"
# lines must NOT read as a launch, or a flight where the birds never fired would score itself green.
# (A second pattern for a raw `z: 12.34` was removed in the 2026-08-18 QA pass: that pane never
# prints one — zget consumes it — so it could only ever have matched something that was not a launch.)
parse_alt_m() { sed -n -E 's/.*altitude (-?[0-9.]+) m > .*launching.*/\1/p' | tail -n 1; }

# Where that altitude comes from. FG_ALT_SOURCE_CMD is a test seam (canned text instead of a pane);
# nothing in a real run sets it.
birds_gate_alt() {
  if [ -n "${FG_ALT_SOURCE_CMD:-}" ]; then eval "$FG_ALT_SOURCE_CMD"; else pane_text birds; fi |
    parse_alt_m
}

# Clip dirs are UTC-stamped, so lexicographic order == chronological.
newest_clip() {
  local d last=""
  for d in "$REPO_ROOT"/eval/results/clips/*/; do
    if [ -d "$d" ]; then last="$d"; fi
  done
  [ -n "$last" ] || return 1
  last=${last%/}
  printf 'eval/results/clips/%s\n' "${last##*/}"
}

print_stitch_hint() {
  local clip=${1:-}
  case $clip in "$CTR_REPO"/*) clip=${clip#"$CTR_REPO"/} ;; esac
  if [ -z "$clip" ]; then clip=$(newest_clip || true); fi
  if [ -z "$clip" ]; then clip="eval/results/clips/<the dir the record window printed>"; fi
  printf '\n[fly_pipeline] stitch it on the host (repo root, no container needed):\n\n'
  printf '    python3 scripts/stitch_ndvi.py --clip %s\n\n' "$clip"
  # The bar names its preconditions on purpose. 697/720 has been reached exactly once, off a full
  # boustrophedon that delivered 1781 frames; every other real clip to date ran 48-116 frames and
  # stitched to 228-586. Quoting the good number alone reads a short mission or a starved recorder
  # as a bad flight.
  cat <<'EOF'
[fly_pipeline] bar: the 18 trees at their 18 known positions in heatmap/heatmap.png, few stale-pose
[fly_pipeline] skips, and cells_imaged near 720 — but read frames_total AND which mission flew,
[fly_pipeline] first. 697/720 has been hit once, on a full boustrophedon with 1781 frames; the
[fly_pipeline] 2-lane test-flight gate stitches ~291/720 off 48 frames, and a busy machine starves
[fly_pipeline] a full mission to ~100. Low cells with low frames is a short mission or a starved
[fly_pipeline] recorder, not a bad flight.
EOF
}

# --- subcommands --------------------------------------------------------------------------------
cmd_up() {
  if session_exists; then
    die "tmux session '$SESSION' already exists — refusing to start a second bringup on the same
  container. Attach:  scripts/fly_pipeline.sh attach     Tear down:  scripts/fly_pipeline.sh down"
  fi
  preflight
  # Under --dry-run this is the ONLY thing that would touch the host, so it is guarded too:
  # a dry run must leave the machine exactly as it found it.
  if ! (( DRY_RUN )); then print_fly_recipe >"$RECIPE_FILE"; fi

  say "1/7 Gazebo (the world)"
  run tmux new-session -d -s "$SESSION" -n gazebo "$(exec_line "$INNER_GAZEBO")"
  keep_output gazebo
  gate_gazebo
  say "2/7 sensor bridge (Gazebo -> ROS 2)"
  new_window bridge "$(exec_line "$INNER_BRIDGE")"
  gate_bridge
  if (( GATE_GEOMETRY )); then gate_geometry_run; fi
  gate_render_alive
  say "3/7 micro-ROS agent (BEFORE SITL — the golden rule)"
  new_window agent "$(exec_line "$INNER_AGENT")"
  gate_agent
  say "4/7 ArduPilot SITL + MAVProxy (the prompt the flight is flown from), recipe in the pane beside it"
  new_window sitl "$(exec_line "$INNER_SITL")"
  # -d keeps SITL the active pane without naming a pane index: `sitl.0` is only pane 0 when the
  # user's .tmux.conf leaves pane-base-index at 0, and being wrong there would abort the bringup
  # with SITL already booted. Teardown no longer depends on which pane is active either.
  run tmux split-window -d -h -l 45% -t "$SESSION:sitl" "cat \"$RECIPE_FILE\"; exec bash"
  say "5/7 NDVI fusion node"
  new_window ndvi "$(exec_line "$INNER_NDVI")"
  say "6/7 clip recorder (the evidence)"
  new_window record "$(exec_line "$INNER_RECORD")"
  say "7/7 birds — altitude-gated, will not start before you arm and climb past 10 m"
  new_window birds "$(exec_line "$INNER_BIRDS_WATCH")"
  run tmux select-window -t "$SESSION:sitl"
  say "all panes up. Windows: gazebo bridge agent sitl(+recipe pane) ndvi record birds"
  say "fly from the sitl window (recipe is in the pane beside it); tear down with: scripts/fly_pipeline.sh down"
  # test-flight drives the panes from here instead of handing them to a human, so it must not attach.
  if (( DRY_RUN || TESTFLIGHT )); then return 0; fi
  if [ -t 1 ]; then cmd_attach; else say "not a tty — attach with: scripts/fly_pipeline.sh attach"; fi
}

cmd_attach() {
  if (( DRY_RUN )); then printf '  DRY  tmux attach -t %s\n' "$SESSION"; return 0; fi
  session_exists || die "no tmux session '$SESSION' — start it with: scripts/fly_pipeline.sh up"
  tmux select-window -t "$SESSION:sitl" 2>/dev/null || true
  if [ -n "${TMUX:-}" ]; then exec tmux switch-client -t "$SESSION"; fi
  exec tmux attach -t "$SESSION"
}

cmd_status() {
  if (( DRY_RUN )); then
    printf '  DRY  tmux list-windows -t %s\n' "$SESSION"
    printf '  DRY  docker ps --filter name=%s\n' "$CONTAINER"
    printf '  DRY  gate re-checks: gz topic -l | ros2 topic list | /proc/net/udp :07E3\n'
    print_fly_recipe
    return 0
  fi
  local up=0
  if session_exists; then
    up=1
    say "session '$SESSION' is UP:"
    tmux list-windows -t "$SESSION" -F '    #{window_index}  #{window_name}  (#{?pane_dead,DEAD,running})'
  else
    say "session '$SESSION' is DOWN — start it with: scripts/fly_pipeline.sh up"
  fi
  if docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER"; then
    say "container '$CONTAINER': running"
    if probe_gz_topics;   then say "  gz   4 /fg/sensor advertisements: yes"; else warn "  gz   4 /fg/sensor advertisements: NO"; fi
    if probe_ros_topics;  then say "  ros2 4 /fg/sensor topics: yes";         else warn "  ros2 4 /fg/sensor topics: NO"; fi
    if probe_agent_port;  then say "  udp  micro-ROS agent on 2019: yes";     else warn "  udp  micro-ROS agent on 2019: NO"; fi
    # Those three are liveness checks on shared resources — they cannot tell WHOSE processes they
    # found. Green gates with no session means something else is flying: say so, loudly.
    if (( ! up )) && [ -n "$(running_sim_procs)" ]; then
      warn "sim processes are running in the container with NO '$SESSION' session — a manual
  FULL_PIPELINE_DEMO bringup, or a session killed without 'down'. The green lines above belong to
  THAT bringup, not to this launcher, and 'up' will refuse to start on top of it."
    fi
  else
    warn "container '$CONTAINER' is not running"
  fi
  print_fly_recipe
}

cmd_birds() {
  local line
  line=$(exec_line "$INNER_BIRDS")
  if (( DRY_RUN )); then printf '  DRY  tmux respawn-window -k -t %s:birds %s\n' "$SESSION" "$line"; return 0; fi
  session_exists || die "no tmux session '$SESSION' — nothing to drive birds in."
  say "manual bird start — this BYPASSES the altitude gate; only do it once the drone is airborne."
  if ! tmux respawn-window -k -t "$SESSION:birds" "$line" 2>/dev/null; then
    die "no 'birds' window in session '$SESSION' to respawn. Run the runbook's Shell 5 by hand:
  $line"
  fi
  keep_output birds
  say "birds window respawned (watch it: scripts/fly_pipeline.sh attach, then select the birds window)"
}

cmd_down() {
  if (( DRY_RUN )); then
    printf '  DRY  tmux send-keys -t %s:record C-c        # RECORDER FIRST — finalize writes meta.json\n' "$SESSION"
    printf '  DRY  poll the record pane up to %ss for "clip finalized"\n' "$FINALIZE_S"
    printf '  DRY  tmux send-keys C-c -> birds ndvi sitl agent bridge gazebo\n'
    printf '  DRY  tmux kill-session -t %s\n' "$SESSION"
    print_stitch_hint ""
    return 0
  fi
  # Teardown must be idempotent: a session that is already gone is not an error, it is the goal.
  # It IS worth saying out loud, because a session that vanished on its own never finalized a clip.
  if ! session_exists; then
    say "no tmux session '$SESSION' — nothing to tear down."
    if [ -n "$(running_sim_procs 2>/dev/null)" ]; then
      warn "but sim processes ARE still running inside '$CONTAINER' (a session killed without
  'down', or a manual runbook bringup). The recorder was never SIGINTed there, so its clip is
  probably unfinalized. Stop them by hand, or:  docker restart $CONTAINER"
    fi
    return 0
  fi

  say "SIGINT -> record window FIRST: finalize converts the raw in-flight dumps to schema PNGs and"
  say "writes meta.json. Everything else can wait; this cannot."
  local waited=0 clip="" have_record=1 tail_txt=""
  if ! send_ctrl_c record; then
    have_record=0
    warn "no 'record' window in this session — nothing to finalize; stopping the rest."
  fi
  while (( have_record && waited < FINALIZE_S )); do
    # ONE capture per pass, read twice: two captures raced each other for no benefit, and this way
    # both verdicts are read off the same snapshot of the pane.
    tail_txt=$(pane_text record)
    if grep -q 'clip finalized' <<<"$tail_txt"; then
      clip=$(parse_clip <<<"$tail_txt"); say "recorder finalized after ${waited}s"; break
    fi
    if grep -q 'NOTHING RECORDED' <<<"$tail_txt"; then
      warn "recorder reports NOTHING RECORDED — no camera_info ever arrived. There is no clip to stitch."
      break
    fi
    # The recorder has exited without printing either line: waiting out the full timeout would
    # only delay the bad news. Show the tail instead.
    if window_failed record; then
      warn "the record pane exited without printing a finalize line — the clip may be incomplete."
      printf '%s\n' "--- tail of the 'record' window ---" >&2
      meaningful <<<"$tail_txt" | tail -n 15 >&2
      break
    fi
    sleep "$POLL_S"; waited=$(( waited + POLL_S ))
    if (( waited % 15 == 0 )); then say "  ... still finalizing (${waited}s of ${FINALIZE_S}s)"; fi
  done
  if (( have_record )) && [ -z "$clip" ] && (( waited >= FINALIZE_S )); then
    warn "recorder finalize did not report within ${FINALIZE_S}s — the clip may be incomplete.
  Read the record window's tail before trusting it; the PNG conversion may still have been running."
  fi

  local w
  for w in birds ndvi sitl agent bridge gazebo; do
    send_ctrl_c "$w" || true
  done
  sleep 5
  tmux kill-session -t "$SESSION" 2>/dev/null || true
  say "tmux session '$SESSION' killed (the container itself is left running)."
  # Killing a pane kills the `docker exec` CLIENT; whether the process inside died with it is a
  # question, not a given. Answer it now, while the answer is cheap — a survivor makes the NEXT
  # `up` refuse to start, and it is much easier to understand here than there.
  local survivors
  survivors=$(running_sim_procs)
  if [ -n "$survivors" ]; then
    warn "these sim processes survived the teardown inside '$CONTAINER':

$(printf '%s\n' "$survivors" | cut -c1-110 | sed 's/^/      /')

  'up' will refuse to start on top of them. Clear with:  docker restart $CONTAINER"
  fi
  print_stitch_hint "$clip"
}

# --- test-flight: the scripted pre-demo regression gate (ADR-013 amendment 2) --------------------
# NOT the demo path. Demo/recording flights stay human-flown at the MAVProxy prompt; this exists so
# the whole stack — bringup gates, AUTO mission, the altitude-gated birds firing THEMSELVES, the
# recorder's finalize, the host-side stitch — can be regression-tested in one unattended command
# before a demo. It types the same recipe a human does, on the short test mission, and only ever
# AFTER the three readiness lines the runbook says to wait for: scripting past those is the exact
# historical failure this project keeps paying for, so the wait is the feature, not the overhead.
TF_MISSION_NAME="test_2lane"
TF_READY_S=240        # DDS init + EKF alignment + GPS lock, after SITL boots
TF_ARM_S=90           # ARMED after `arm throttle`
TF_ARM_RETRY_S=30     # the runbook's rule for "Arm: Accels inconsistent" (post-boot CPU spike)
TF_TAKEOFF_S=300      # first "Reached command" (mission item 1 is NAV_TAKEOFF)
TF_FLIGHT_S=1500      # arm -> disarm budget, REAL seconds: ~2 sim-min at RTF ~0.2, with slack
TF_RE_DDS='DDS.*[Ii]nitialization passed'
TF_RE_EKF='EKF3 IMU. (tilt alignment complete|is using GPS)'
TF_RE_GPS='GPS 1: detected'
TF_RE_ARMED='(^|[^A-Z])ARMED'   # the leading class is what keeps DISARMED from matching
TF_RE_DISARM='DISARM|Disarmed'
TF_RE_REACHED='Reached command'
TF_RE_ACCELS='Accels inconsistent'
# Everything this launcher can start inside the container; the abort path force-kills exactly this.
# It must cover every pattern running_sim_procs refuses on, `sim_vehicle` included — kill only the
# arducopter/mavproxy children it spawned and the launcher itself survives, and the NEXT `up`
# refuses to start on the corpse this abort was supposed to clear (2026-08-18 QA pass).
TF_PROCS='arducopter|mavproxy|sim_vehicle|gz sim|parameter_bridge|micro_ros_agent|fieldguard_planning|drive_birds'

TF_WORK=""; TF_LOG=""; TF_PANE=""; TF_RECORD=""; TF_PHASE="startup"; TF_FAIL=""
TF_CLIP=""; TF_BIRDS_ALT=""; TF_STITCH_EXIT=""; TF_TEARDOWN=""; TF_START=""; TF_T0=0
TF_FRAMES=""; TF_CELLS=""

# --- the evidence-yield floor ---
# Booting, arming, flying the mission and disarming is not the same as RECORDING one. On
# 2026-08-19 the 2 Hz throughput measurement flew a byte-identical mission, recorded 3 frames,
# imaged 1 of 720 cells — and this gate said PASS. A pre-demo regression gate that cannot fail on a
# 16x throughput collapse is not gating the thing it exists for, so the LAST gate is on the
# evidence yield, read off the artifacts themselves.
#
# The numbers below are FLOORS DERIVED FROM n=2 — the only two test-flights that have ever run,
# both on $TF_MISSION_NAME (a different mission needs different numbers):
#   2026-08-18  5 Hz baseline, healthy:   48 frames / 291 cells  -> clears by 4.0x / 7.3x
#   2026-08-19  2 Hz collapse, unusable:   3 frames /   1 cell   -> fails both, decisively
# Set at roughly a quarter of the healthy frame count and a seventh of its cell count: far enough
# below the one healthy run that ordinary variance on a busy laptop cannot flake them, far enough
# above the one bad run to catch any collapse within 4x of the measured one. They are floors, not
# targets — a flight that merely clears them is still a poor flight, just not a regression. Raise
# them once more healthy runs exist; do not raise them off a single good number.
TF_MIN_FRAMES=12
TF_MIN_CELLS=40

# One integer out of a JSON artifact; empty when the file, the key, or the type is not there.
# Python, not grep: these files have nested keys a regex would eventually read the wrong one of.
tf_json_int() {
  python3 -c 'import json, sys
try:
    v = json.load(open(sys.argv[1]))[sys.argv[2]]
except Exception:
    sys.exit(0)
if isinstance(v, int) and not isinstance(v, bool):
    print(v)' "$1" "$2" 2>/dev/null
}

# The floor itself: echoes the failure text when the yield is under it, nothing when it clears.
# Kept pure and argument-driven so it can be exercised against the two committed gate records
# without flying (tests/test_fly_pipeline.py). An UNREADABLE yield is a failure, never a pass —
# "we could not tell" reading as green is the exact shape of bug this gate was missing.
tf_floor_failure() {
  local frames=${1:-} cells=${2:-}
  if ! [[ $frames =~ ^[0-9]+$ ]] || ! [[ $cells =~ ^[0-9]+$ ]]; then
    printf 'evidence-yield floor: cannot read the yield (frames_recorded=%s, cells_imaged=%s) from the clip meta.json / heatmap.json, so the floor cannot be judged — that is a FAIL, not a pass\n' \
      "${frames:-<none>}" "${cells:-<none>}"
    return 0
  fi
  if (( frames < TF_MIN_FRAMES || cells < TF_MIN_CELLS )); then
    printf 'evidence-yield floor: frames_recorded=%s (min %s), cells_imaged=%s (min %s) — the mission flew but the flight recorded almost nothing (throughput collapse). Read this record pane_tails["ndvi"]: a fused_count that kept climbing means the RECORDER dropped what fusion produced; one that stalled means fusion never paired the bands.\n' \
      "$frames" "$TF_MIN_FRAMES" "$cells" "$TF_MIN_CELLS"
  fi
}

tf_has()  { grep -Eq -- "$1" "$TF_LOG"; }
tf_line() { grep -Em1 -- "$1" "$TF_LOG" || true; }
tf_die()  { TF_FAIL=$1; exit 1; }   # the EXIT trap does the teardown and writes the record

# Bounded poll of the SITL log for a regex, from line $3 on. Echoes the line that matched — that
# string is the gate record's evidence, so it is never paraphrased.
tf_wait() {
  local re=$1 timeout_s=$2 from=${3:-1} waited=0 hit
  while (( waited < timeout_s )); do
    hit=$(tail -n "+$from" "$TF_LOG" | grep -Em1 -- "$re" || true)
    if [ -n "$hit" ]; then printf '%s\n' "$hit"; return 0; fi
    sleep "$POLL_S"; waited=$(( waited + POLL_S ))
  done
  return 1
}

# SITL itself, not the recipe pane beside it (pane order depends on the user's pane-base-index).
tf_sitl_pane() {
  tmux list-panes -t "$SESSION:sitl" -F '#{pane_id} #{pane_start_command}' 2>/dev/null |
    awk '/sim_vehicle/ { print $1; exit }'
}

# All three, or nothing. This is the gate a human is told to watch and a script must not skip.
tf_ready() {
  local waited=0 re
  while (( waited < TF_READY_S )); do
    if tf_has "$TF_RE_DDS" && tf_has "$TF_RE_EKF" && tf_has "$TF_RE_GPS"; then
      for re in "$TF_RE_DDS" "$TF_RE_EKF" "$TF_RE_GPS"; do evidence "sitl: $(tf_line "$re")"; done
      say "SITL ready: DDS initialized, EKF3 aligned, GPS detected"
      return 0
    fi
    if window_failed sitl; then return 1; fi
    sleep "$POLL_S"; waited=$(( waited + POLL_S ))
  done
  return 1
}

# `arm throttle` has already gone in with the rest of the recipe. One retry, on the one documented
# cause (the post-boot CPU spike) — anything else is a real failure and stays one.
tf_arm() {
  local hit
  if hit=$(tf_wait "$TF_RE_ARMED" "$TF_ARM_S"); then evidence "armed: $hit"; return 0; fi
  tf_has "$TF_RE_ACCELS" || return 1
  warn "'Arm: Accels inconsistent' — waiting ${TF_ARM_RETRY_S}s and retrying arm throttle once."
  evidence "arm rejected: $(tf_line "$TF_RE_ACCELS")"
  sleep "$TF_ARM_RETRY_S"
  tmux send-keys -t "$TF_PANE" "arm throttle" Enter
  hit=$(tf_wait "$TF_RE_ARMED" "$TF_ARM_S") || return 1
  evidence "armed after retry: $hit"
}

tf_dry_plan() {
  say "test-flight = 'up' (below), then the runbook recipe typed for you. Regression gate only."
  cmd_up
  printf '  DRY  tmux capture-pane + pipe-pane: the SITL pane -> %s/sitl.log\n' '<tmpdir>/swathkeeper_testflight_<UTC>'
  printf '  DRY  wait <=%ss for ALL of: /%s/  /%s/  /%s/\n' "$TF_READY_S" "$TF_RE_DDS" "$TF_RE_EKF" "$TF_RE_GPS"
  printf '  DRY  then send-keys to that pane, one line at a time, 2s apart:\n'
  fly_lines "$TF_MISSION_NAME" | sed 's/^/  DRY      /'
  printf '  DRY  on /%s/: wait %ss, retry "arm throttle" ONCE\n' "$TF_RE_ACCELS" "$TF_ARM_RETRY_S"
  printf '  DRY  supervise: ARMED <=%ss, first "%s" <=%ss, disarm within a %ss flight budget\n' \
    "$TF_ARM_S" "$TF_RE_REACHED" "$TF_TAKEOFF_S" "$TF_FLIGHT_S"
  printf '  DRY  the birds pane must fire ITSELF (altitude gate) — never started by this path\n'
  printf '  DRY  on disarm: down (recorder first) -> stitch the clip -> gate record\n'
  printf '  DRY  evidence-yield floor (LAST gate, read from the clip meta.json + heatmap.json):\n'
  printf '  DRY    frames_recorded >= %s AND cells_imaged >= %s, else FAIL with the full record still written\n' \
    "$TF_MIN_FRAMES" "$TF_MIN_CELLS"
  printf '  DRY  gate record: eval/results/testflight_gate_<UTC>.json\n'
  printf '  DRY  on abort: same teardown, then docker exec %s pkill -9 -f %s\n' "$CONTAINER" "$TF_PROCS"
}

# One teardown for both outcomes, and the reason the trap can be trusted: pane evidence comes out
# FIRST (killing the session loses it), then the recorder-first `down`, then a force-kill of
# anything that outlived its `docker exec` client, then the stitch and the record.
tf_cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  # Deeper tails on any abort. Keyed on the PHASE, not on TF_FAIL: most causes (a bringup gate that
  # died, birds that never fired) are only named further down, after the panes are already read.
  local w n=15
  if [ -n "$TF_FAIL" ] || [ "$TF_PHASE" != "teardown" ]; then n=60; fi
  if session_exists; then
    for w in gazebo bridge agent sitl ndvi record birds; do
      pane_tail "$w" "$n" >"$TF_WORK/tails/$w.log"
    done
    TF_BIRDS_ALT=$(birds_gate_alt)
    cmd_down >"$TF_WORK/down.log" 2>&1 || warn "teardown reported a problem (see the log below)"
    cat "$TF_WORK/down.log"
    TF_CLIP=$(parse_clip <"$TF_WORK/down.log")
    if [ -n "$TF_CLIP" ] && [ ! -d "$REPO_ROOT/$TF_CLIP" ]; then TF_CLIP=""; fi
    if grep -q 'recorder finalized' "$TF_WORK/down.log"; then
      TF_TEARDOWN="recorder SIGINTed first; finalize confirmed; session killed; survivors force-killed"
    else
      TF_TEARDOWN="recorder SIGINTed first; NO finalize line — the clip may be incomplete"
    fi
    tmux kill-session -t "$SESSION" 2>/dev/null || true
    docker exec "$CONTAINER" pkill -9 -f "$TF_PROCS" >/dev/null 2>&1 || true
  fi

  # An abort anywhere before teardown already printed its own ERROR line; name the phase so the
  # record does not blame whichever downstream artifact is missing as a consequence.
  if [ -z "$TF_FAIL" ] && [ "$TF_PHASE" != "teardown" ]; then
    TF_FAIL="aborted during $TF_PHASE — see the ERROR line above and the pane tails in this record"
  fi
  if [ -z "$TF_FAIL" ] && [ -z "$TF_BIRDS_ALT" ]; then
    TF_FAIL="the birds pane never fired its own altitude gate — drive_birds.py never launched"
  fi
  if [ -z "$TF_FAIL" ] && [ -z "$TF_CLIP" ]; then
    TF_FAIL="no clip directory survived the recorder's finalize — nothing to stitch"
  fi
  if [ -z "$TF_FAIL" ]; then
    say "stitching $TF_CLIP on the host ..."
    TF_STITCH_EXIT=0
    python3 "$REPO_ROOT/scripts/stitch_ndvi.py" --clip "$REPO_ROOT/$TF_CLIP" \
      >"$TF_WORK/stitch.log" 2>&1 || TF_STITCH_EXIT=$?
    tail -n 20 "$TF_WORK/stitch.log"
    if (( TF_STITCH_EXIT != 0 )); then
      TF_FAIL="host-side stitch exited $TF_STITCH_EXIT (see $TF_WORK/stitch.log)"
    fi
  fi

  # The yield, straight off the two artifacts (the recorder's finalize wrote meta.json, the stitch
  # above wrote heatmap.json) — never off a counter this script kept. Read whenever a clip exists,
  # so a FAILING record still carries the numbers; judged only when nothing else already failed,
  # because a starved clip is a consequence of an earlier abort, not a second cause.
  if [ -n "$TF_CLIP" ]; then
    TF_FRAMES=$(tf_json_int "$REPO_ROOT/$TF_CLIP/meta.json" num_frames)
    TF_CELLS=$(tf_json_int "$REPO_ROOT/$TF_CLIP/heatmap/heatmap.json" cells_imaged)
    evidence "evidence yield: frames_recorded=${TF_FRAMES:-<none>} (min $TF_MIN_FRAMES), cells_imaged=${TF_CELLS:-<none>} (min $TF_MIN_CELLS)"
  fi
  if [ -z "$TF_FAIL" ]; then
    TF_FAIL=$(tf_floor_failure "$TF_FRAMES" "$TF_CELLS")
    # Teardown already finished above, so a floor failure still gets the full record; naming its
    # own phase keeps the record from blaming the teardown that actually worked.
    [ -z "$TF_FAIL" ] || TF_PHASE="evidence-yield"
  fi

  tf_write_record
  if [ -n "$TF_FAIL" ]; then
    printf '[fly_pipeline] TEST-FLIGHT FAILED in %s: %s\n' "$TF_PHASE" "$TF_FAIL" >&2
    say "gate record: $TF_RECORD   full logs: $TF_WORK"
    exit 1
  fi
  say "TEST-FLIGHT PASSED — gate record: $TF_RECORD"
  exit "$rc"
}

# Evidence out as JSON. Python does the escaping; the yield numbers were read from the clip's own
# meta.json / heatmap.json above, so the record can never disagree with the artifacts it describes.
tf_write_record() {
  TF_RECORD="$REPO_ROOT/eval/results/testflight_gate_$(date -u +%Y%m%dT%H%M%SZ).json"
  mkdir -p "$REPO_ROOT/eval/results"
  TF_RESULT=PASS
  if [ -n "$TF_FAIL" ]; then TF_RESULT=FAIL; fi
  TF_FINISHED=$(now_utc)
  TF_DURATION=$(( SECONDS - TF_T0 ))
  export TF_WORK TF_FAIL TF_PHASE TF_CLIP TF_BIRDS_ALT TF_STITCH_EXIT TF_TEARDOWN
  export TF_RESULT TF_START TF_FINISHED TF_DURATION TF_MISSION_NAME
  export TF_FRAMES TF_CELLS TF_MIN_FRAMES TF_MIN_CELLS
  python3 - "$TF_RECORD" <<'PY' || warn "could not write the gate record to $TF_RECORD"
import json, os, pathlib, sys

work = pathlib.Path(os.environ["TF_WORK"])
clip = os.environ.get("TF_CLIP", "").strip()
failed = os.environ["TF_RESULT"] == "FAIL"


def lines(path):
    try:
        return path.read_text(errors="replace").splitlines()
    except OSError:
        return []


def opt(key, cast=str):
    value = os.environ.get(key, "").strip()
    try:
        return cast(value) if value else None
    except ValueError:
        return value


record = {
    # 1.1 added cells_imaged + evidence_floor (2026-08-19); the two committed 1.0 records predate
    # the floor and carry neither.
    "schema_version": "1.1",
    "gate": "scripts/fly_pipeline.sh test-flight (scripted pre-demo regression gate, ADR-013 am. 2)",
    "written_utc": os.environ["TF_FINISHED"],
    "started_utc": os.environ["TF_START"],
    "duration_s": int(os.environ["TF_DURATION"]),
    "result": os.environ["TF_RESULT"],
    "failed_phase": os.environ["TF_PHASE"] if failed else None,
    "failure": opt("TF_FAIL"),
    "mission": "config/missions/%s.waypoints" % os.environ["TF_MISSION_NAME"],
    "evidence": lines(work / "evidence.txt"),
    "frames_recorded": opt("TF_FRAMES", int),
    "cells_imaged": opt("TF_CELLS", int),
    # The floor this run was judged against, in the record, so a future reader can see which bar
    # a PASS cleared instead of having to date the script (floors from n=2 — see fly_pipeline.sh).
    "evidence_floor": {"frames_recorded_min": opt("TF_MIN_FRAMES", int),
                       "cells_imaged_min": opt("TF_MIN_CELLS", int)},
    "birds_started_alt_m": opt("TF_BIRDS_ALT", float),
    "clip": clip or None,
    "teardown": opt("TF_TEARDOWN"),
    "stitch_exit": opt("TF_STITCH_EXIT", int),
    "sitl_log": str(work / "sitl.log"),
    "pane_tails": {p.stem: lines(p) for p in sorted((work / "tails").glob("*.log"))},
}
pathlib.Path(sys.argv[1]).write_text(json.dumps(record, indent=1) + "\n")
PY
}

cmd_test_flight() {
  if (( DRY_RUN )); then tf_dry_plan; return 0; fi
  if session_exists; then
    die "tmux session '$SESSION' already exists — refusing to script a flight on top of a session
  this run does not own (its teardown would kill yours). Tear it down first:
    scripts/fly_pipeline.sh down"
  fi
  TESTFLIGHT=1
  TF_START=$(now_utc); TF_T0=$SECONDS
  TF_WORK="${TMPBASE%/}/swathkeeper_testflight_$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$TF_WORK/tails"
  TF_LOG="$TF_WORK/sitl.log";        : >"$TF_LOG"
  EVIDENCE_FILE="$TF_WORK/evidence.txt"; : >"$EVIDENCE_FILE"
  say "TEST-FLIGHT: scripted regression gate, NOT the demo path. Logs: $TF_WORK"
  evidence "test-flight started (mission $TF_MISSION_NAME)"
  # Armed only now: before this point a failure means we do NOT own the container, and tearing down
  # would kill someone else's manual bringup.
  trap tf_cleanup EXIT INT TERM

  TF_PHASE="bringup"
  cmd_up

  TF_PHASE="sitl-readiness"
  TF_PANE=$(tf_sitl_pane)
  [ -n "$TF_PANE" ] || tf_die "could not identify the SITL pane in the sitl window"
  # Scrollback first, then the live pipe: SITL prints its DDS line while the later panes are still
  # coming up, and a pipe alone would start after it.
  tmux capture-pane -p -J -S - -t "$TF_PANE" >>"$TF_LOG" 2>/dev/null || true
  tmux pipe-pane -o -t "$TF_PANE" "cat >>\"$TF_LOG\""
  say "waiting up to ${TF_READY_S}s for DDS init + EKF alignment + GPS — never scripted past"
  tf_ready || tf_die "SITL did not report all three readiness lines within ${TF_READY_S}s
  (DDS initialization / EKF3 alignment / GPS 1 detected) — see the sitl tail in the gate record"

  TF_PHASE="mission"
  say "typing the fly recipe into SITL, one line at a time, on $TF_MISSION_NAME"
  local line
  while IFS= read -r line; do
    tmux send-keys -t "$TF_PANE" "$line" Enter
    sleep 2
  done < <(fly_lines "$TF_MISSION_NAME")
  evidence "sent the fly recipe: $(fly_lines "$TF_MISSION_NAME" | paste -sd';' -)"

  TF_PHASE="arm"
  tf_arm || tf_die "never saw ARMED within ${TF_ARM_S}s (one accels-inconsistent retry included)"

  TF_PHASE="flight"
  local armed_from hit
  armed_from=$(( $(wc -l <"$TF_LOG") + 1 ))
  hit=$(tf_wait "$TF_RE_REACHED" "$TF_TAKEOFF_S" "$armed_from") ||
    tf_die "no '$TF_RE_REACHED' within ${TF_TAKEOFF_S}s of arming — takeoff or AUTO entry failed"
  evidence "takeoff / AUTO progress: $hit"
  hit=$(tf_wait "$TF_RE_DISARM" $(( TF_FLIGHT_S - (SECONDS - TF_T0) )) "$armed_from") ||
    tf_die "no disarm within the ${TF_FLIGHT_S}s flight budget — the mission or RTL never finished"
  evidence "mission progress: $(grep -Ec -- "$TF_RE_REACHED" "$TF_LOG" || true) '$TF_RE_REACHED' lines"
  evidence "disarmed: $hit"

  TF_PHASE="teardown"
  say "disarmed — tearing down recorder-first, then stitching. (trap does the rest)"
}

# --- main ---------------------------------------------------------------------------------------
main() {
  while (( $# )); do
    case $1 in
      --dry-run)       DRY_RUN=1 ;;
      --gate-geometry) GATE_GEOMETRY=1 ;;
      -h|--help)       usage; exit 0 ;;
      up|attach|status|birds|down|test-flight) CMD=$1 ;;
      *) usage >&2; die "unknown argument: $1" ;;
    esac
    shift
  done

  # --dry-run is a paper exercise — it must run anywhere, so tmux is only required for real work.
  if ! command -v tmux >/dev/null 2>&1; then
    (( DRY_RUN )) || die "tmux is required for this launcher: brew install tmux"
    warn "tmux is not installed — fine for --dry-run, required before a real 'up'."
  fi

  case $CMD in
    up)          cmd_up ;;
    attach)      cmd_attach ;;
    status)      cmd_status ;;
    birds)       cmd_birds ;;
    down)        cmd_down ;;
    test-flight) cmd_test_flight ;;
    *)           usage >&2; die "unknown subcommand: $CMD" ;;
  esac
}

# Sourcing this file exercises one function in isolation (tests/test_fly_pipeline.py does exactly
# that); only executing it runs a subcommand.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; fi
