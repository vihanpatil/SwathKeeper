#!/usr/bin/env bash
# Fly N scripted encounters back to back and tabulate them (the ADR-022 kill-criterion shape: >= 20 seeded
# encounters, each scored on its own bird track). Runs on the macOS HOST like fly_pipeline.sh.
#
#   scripts/encounter_batch.sh [N=20] [--birds config/birds/headon_lane15.json] [--mission headon_lane15]
#                              [--speeds "4.0 5.0 6.0"] [--detection-source depth]
#
# Each run is `scripts/fly_pipeline.sh encounter ...` with the speed cycling through --speeds (the seed of
# the batch: the bird track is identical, the drone's speed and therefore the meeting point and lead time
# vary). A run that fails to score is counted, not skipped; the batch never stops on one bad run (the
# container is left clean by the encounter's own teardown). At the end scripts/summarize_encounters.py
# writes eval/results/encounters/BATCH_<UTC>.md + .json over exactly this batch's run folders.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "$REPO_ROOT/.venv/bin/python3" ] && ! python3 -c "import numpy" >/dev/null 2>&1; then
  export PATH="$REPO_ROOT/.venv/bin:$PATH"
fi
N=20; BIRDS="config/birds/headon_lane15.json"; MISSION="headon_lane15"; SPEEDS="4.0 5.0 6.0"; SRC="depth"
while (( $# )); do
  case $1 in
    --birds) BIRDS=$2; shift ;;
    --mission) MISSION=$2; shift ;;
    --speeds) SPEEDS=$2; shift ;;
    --detection-source) SRC=$2; shift ;;
    -h|--help) sed -n 2,12p "$0"; exit 0 ;;
    *) N=$1 ;;
  esac
  shift
done
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
read -r -a SPEED_LIST <<<"$SPEEDS"
echo "[batch] $N encounters, birds $BIRDS, mission $MISSION, speeds ${SPEED_LIST[*]}, detector $SRC — started $STAMP"
ok=0; bad=0
for (( i = 0; i < N; i++ )); do
  speed=${SPEED_LIST[$(( i % ${#SPEED_LIST[@]} ))]}
  echo "[batch] run $(( i + 1 ))/$N at $speed m/s — $(date -u +%H:%M:%SZ)"
  if bash "$REPO_ROOT/scripts/fly_pipeline.sh" encounter --detection-source "$SRC" --speed "$speed" \
       --mission "$MISSION" --birds "$BIRDS" >"${TMPDIR:-/tmp}/encounter_batch_${STAMP}_$(( i + 1 )).log" 2>&1; then
    ok=$(( ok + 1 )); echo "[batch]   scored, checker exit 0"
  else
    rc=$?; bad=$(( bad + 1 )); echo "[batch]   exit $rc (1 = checker INVALID/FAIL, the usual; see the log)"
    # a tmux session left behind would make the next `encounter` refuse: clear it
    tmux kill-session -t swathkeeper 2>/dev/null || true
    docker exec fieldguard-sim pkill -9 -f 'arducopter|mavproxy|sim_vehicle|gz sim|parameter_bridge|micro_ros_agent|fieldguard_planning|drive_birds' >/dev/null 2>&1 || true
    sleep 5
  fi
done
echo "[batch] done: $ok exit-0, $bad non-zero. Summary:"
python3 "$REPO_ROOT/scripts/summarize_encounters.py" --since "$STAMP" --birds "$(basename "$BIRDS")" \
  --out "$REPO_ROOT/eval/results/encounters/BATCH_${STAMP}.md"
