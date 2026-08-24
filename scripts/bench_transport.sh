#!/usr/bin/env bash
# SwathKeeper — one DDS/transport bench ARM. Runs on the macOS HOST.
#
# WHY THIS EXISTS. Round 2's bench was ad-hoc, and its most expensive lesson was environment drift:
# the SAME code measured 17.31 % and 25.60 % red/ci on different host states, and in a 4-run
# interleaved A/B the sign of (A-B) flipped between pairs. A transport lever cannot be judged by one
# run, and it cannot be judged by a `docker stats` snapshot either — sampling caught 267-352 %-of-a-
# core bursts sitting between two quiet snapshots. So: a scripted, interleavable arm, with load
# sampled THROUGHOUT, that costs ~3 minutes instead of a ~5-minute flight.
#
# WHAT IT RUNS: Gazebo + bridge + ndvi_node ONLY — no SITL, no recorder, no birds. The vehicle never
# flies; the question is transport delivery, not coverage. The three payloads are read VERBATIM out
# of scripts/fly_pipeline.sh rather than retyped, so this bench cannot drift from the flight path
# (which is in turn byte-identical to docs/runbooks/FULL_PIPELINE_DEMO.md).
#
# THE ONE ARGUMENT is the in-container path of a Fast DDS XML profile, or empty for the baseline
# arm. When given it is injected as FASTRTPS_DEFAULT_PROFILES_FILE via `docker exec -e` on every
# exec this script makes that creates a DDS participant. `bash -c` is non-interactive and never
# sources .bashrc, so an rc-file export would reach nothing — the flag is the mechanism.
#
# OUTPUT: one line of JSON on stdout (progress goes to stderr, so `> arm.json` is clean):
#   red/ci and nir/ci straight from the fuser's existing 1 Hz sidecar (no node changes), fused_count,
#   the dds_env_snapshot() fields taken from INSIDE the container while the participants are alive,
#   and the load samples.
#
# ADMISSIBILITY, before any number in the output is read (a malformed profile falls back to defaults
# with only a log line): dds.shm_segments.max_bytes must show the profile took effect, and
# dds.shm_segments.min_bytes must show NO participant missed it. Default segment files are 549,408 B.
#
# Usage (host, repo root):
#   scripts/bench_transport.sh                                               # baseline arm
#   scripts/bench_transport.sh /workspace/fieldguard/config/dds/fg_fastdds.xml
set -euo pipefail

CONTAINER="fieldguard-sim"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${1:-}"
DURATION_S="${BENCH_DURATION_S:-180}"
SAMPLE_S="${BENCH_SAMPLE_S:-10}"
SIDECAR="$REPO_ROOT/eval/results/ndvi_fuser_stats.json"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="${TMPDIR:-/tmp}/swathkeeper_bench_$STAMP"
LOAD_LOG="$WORK/load.log"
DDS_JSON="$WORK/dds.json"

mkdir -p "$WORK"
say() { printf '[bench] %s\n' "$*" >&2; }
die() { printf '[bench] ERROR: %s\n' "$*" >&2; exit 1; }

# `docker exec -e` only when a profile is given, so the baseline arm's exec line is exactly what the
# untuned stack runs — no empty env var to argue about later. A function, not an array: macOS ships
# bash 3.2, where expanding an EMPTY array under `set -u` is an "unbound variable" error, and the
# baseline arm's flag list is empty by definition.
dex() {
  if [ -n "$PROFILE" ]; then
    docker exec -e "FASTRTPS_DEFAULT_PROFILES_FILE=$PROFILE" "$@"
  else
    docker exec "$@"
  fi
}
ARM_LABEL="${BENCH_LABEL:-$([ -n "$PROFILE" ] && echo "profile:$(basename "$PROFILE")" || echo baseline)}"

# --- payloads, read verbatim from the launcher (never retyped) -----------------------------------
for v in INNER_GAZEBO INNER_BRIDGE INNER_NDVI; do
  line="$(grep -m1 "^${v}=" "$REPO_ROOT/scripts/fly_pipeline.sh")" \
    || die "could not find $v in scripts/fly_pipeline.sh"
  eval "$line"
done
[ -n "${INNER_GAZEBO:-}" ] && [ -n "${INNER_BRIDGE:-}" ] && [ -n "${INNER_NDVI:-}" ] \
  || die "one of the INNER_* payloads came back empty"

# --- refuse to run on top of somebody else's bringup ---------------------------------------------
docker inspect "$CONTAINER" >/dev/null 2>&1 || die "container '$CONTAINER' does not exist"
[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" = "true" ] \
  || die "container '$CONTAINER' is not running (scripts/sim_docker_run.sh)"
if docker exec "$CONTAINER" ps -eo args= 2>/dev/null \
     | grep -qE 'gz sim|parameter_bridge|ndvi_node|sim_vehicle|record_node'; then
  die "a bringup is already live in '$CONTAINER' — refusing to bench on top of it"
fi

# Orphaned segments would silently void the admissibility check. A participant killed hard leaves its
# /dev/shm files behind, and `min_bytes` then reports a DEAD 549,408 B segment as if some live
# participant had missed the profile — measured: the first B1 arm read min=549,408 / max=8,413,728
# purely because of a leftover from an aborted run 20 minutes earlier. Safe to clear here and only
# here: the guard above has already established that no bringup is live.
say "clearing stale /dev/shm segments (no bringup is live -- checked above)"
docker exec "$CONTAINER" bash -c 'rm -f /dev/shm/fastrtps_* /dev/shm/sem.fastrtps_* 2>/dev/null; true' \
  >/dev/null 2>&1 || true

cleanup() {
  say "tearing down bench processes"
  docker exec "$CONTAINER" bash -c \
    'pkill -INT -f "gz sim" >/dev/null 2>&1; pkill -INT -f parameter_bridge >/dev/null 2>&1;
     pkill -INT -f ndvi_node >/dev/null 2>&1; sleep 3;
     pkill -f "gz sim" >/dev/null 2>&1; pkill -f parameter_bridge >/dev/null 2>&1;
     pkill -f ndvi_node >/dev/null 2>&1; true' >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

say "arm=$ARM_LABEL duration=${DURATION_S}s work=$WORK"

# --- 1/3 Gazebo ----------------------------------------------------------------------------------
say "starting Gazebo"
docker exec -d "$CONTAINER" bash -c "$INNER_GAZEBO"
deadline=$((SECONDS + 240))
until [ "$(docker exec "$CONTAINER" bash -c \
        'source /root/ardu_ws/install/setup.bash && gz topic -l 2>/dev/null' \
        | grep -c '/fg/sensor')" -ge 4 ]; do
  [ $SECONDS -lt $deadline ] || die "Gazebo never advertised the 4 /fg/sensor topics"
  sleep 5
done
say "Gazebo up (4 /fg/sensor gz topics)"

# --- 2/3 bridge ----------------------------------------------------------------------------------
say "starting bridge"
dex -d "$CONTAINER" bash -c "$INNER_BRIDGE"
deadline=$((SECONDS + 120))
until [ "$(dex "$CONTAINER" bash -c \
        'source /root/ardu_ws/install/setup.bash && ros2 topic list 2>/dev/null' \
        | grep -c '/fg/sensor')" -ge 4 ]; do
  [ $SECONDS -lt $deadline ] || die "the 4 /fg/sensor topics never crossed into ROS 2"
  sleep 5
done
say "bridge up (4 /fg/sensor ROS topics)"

# The render probe doubles as this bench's discovery check: under an SHM-only profile a participant
# that cannot reach the bridge fails HERE, cheaply, instead of producing a plausible-looking zero.
# $PYTHONPATH must stay literal here: it is expanded IN the container, not on the host.
# shellcheck disable=SC2016
if dex "$CONTAINER" bash -c \
     'source /root/ardu_ws/install/setup.bash && PYTHONPATH=/workspace/fieldguard/src:$PYTHONPATH python3 /workspace/fieldguard/scripts/check_render_alive.py' >&2; then
  RENDER_OK=true
else
  RENDER_OK=false
  say "WARNING: render-alive probe did NOT pass — the arm continues so the failure is recorded, but"
  say "         treat every number below as suspect (this is the SHM-only blackout tell)."
fi

# --- 3/3 the measured arm ------------------------------------------------------------------------
rm -f "$SIDECAR"
say "running ndvi_node for ${DURATION_S}s, sampling load every ${SAMPLE_S}s"
: >"$LOAD_LOG"
( dex "$CONTAINER" \
    bash -c "timeout -s INT $DURATION_S bash -c '$INNER_NDVI'" >/dev/null 2>&1 || true ) &
NDVI_PID=$!

DDS_TAKEN=0
while kill -0 "$NDVI_PID" 2>/dev/null; do
  sleep "$SAMPLE_S"
  printf '%s %s\n' "$(date -u +%H:%M:%S)" \
    "$(docker stats --no-stream --format '{{.Name}} {{.CPUPerc}}' 2>/dev/null \
       | grep -v "$CONTAINER" \
       | awk '{gsub(/%/,"",$2); s+=$2; if($2>m)m=$2} END{printf "other_sum=%.1f%% other_max=%.1f%% n=%d", s+0, m+0, NR}')" \
    >>"$LOAD_LOG"
  # Snapshot the transport stack once, mid-arm, while every participant is alive and its segment
  # exists. At teardown the segments are gone and min_bytes could not see a partial injection.
  if [ "$DDS_TAKEN" -eq 0 ]; then
    # Same: expanded in the container, not here.
    # shellcheck disable=SC2016
    dex "$CONTAINER" bash -c \
      'PYTHONPATH=/workspace/fieldguard/src:$PYTHONPATH python3 -c "import json,sys; sys.path.insert(0,\"/workspace/fieldguard/src\"); from fieldguard_planning.dds_env import dds_env_snapshot; print(json.dumps(dds_env_snapshot()))"' \
      >"$DDS_JSON" 2>/dev/null && DDS_TAKEN=1 || true
  fi
done
wait "$NDVI_PID" 2>/dev/null || true
say "arm complete"

# --- emit ----------------------------------------------------------------------------------------
ARM_LABEL="$ARM_LABEL" PROFILE="$PROFILE" DURATION_S="$DURATION_S" RENDER_OK="$RENDER_OK" \
STAMP="$STAMP" SIDECAR="$SIDECAR" DDS_JSON="$DDS_JSON" LOAD_LOG="$LOAD_LOG" \
python3 - <<'PY'
import json, os

def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"

fuser, fuser_err = read_json(os.environ["SIDECAR"])
dds, dds_err = read_json(os.environ["DDS_JSON"])
try:
    load = [l.strip() for l in open(os.environ["LOAD_LOG"]) if l.strip()]
except Exception:
    load = []

def ratio(num, den):
    """None, never 0.0, when there is no denominator — a rate without one is EVIDENCE INSUFFICIENT."""
    if not fuser or not den:
        return None
    return round(100.0 * fuser.get(num, 0) / den, 2)

ci = (fuser or {}).get("camera_info_frames") or 0
nci = (fuser or {}).get("nir_camera_info_frames") or 0

out = {
    "arm": os.environ["ARM_LABEL"],
    "profile": os.environ["PROFILE"] or None,
    "stamp_utc": os.environ["STAMP"],
    "duration_s": int(os.environ["DURATION_S"]),
    "render_alive": os.environ["RENDER_OK"] == "true",
    "camera_info_frames": ci or None,
    "nir_camera_info_frames": nci or None,
    "red_frames": (fuser or {}).get("red_frames"),
    "nir_frames": (fuser or {}).get("nir_frames"),
    "fused_count": (fuser or {}).get("fused_count"),
    "red_over_ci_pct": ratio("red_frames", ci),
    "nir_over_nirci_pct": ratio("nir_frames", nci),
    "fuser_present": fuser is not None,
    "dds": dds if dds is not None else {"present": False, "reason": dds_err},
    "load_samples": load,
    "load_log": os.environ["LOAD_LOG"],
}
if fuser is None:
    out["fuser_reason"] = fuser_err
print(json.dumps(out))
PY
