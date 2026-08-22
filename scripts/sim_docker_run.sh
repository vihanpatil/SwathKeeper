#!/usr/bin/env bash
# Start (or attach to) the Week 1 sim container: repo mounted read/write, colcon workspace on a
# named volume (bind-mounting build/install on macOS Docker Desktop is slow — see
# docs/runbooks/SIM_BRINGUP.md gotcha #5), and MAVLink UDP ports published for an optional host-side GCS.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="fieldguard-sim:week1"
VOLUME_NAME="fieldguard_ardu_ws"
CONTAINER_NAME="fieldguard-sim"

docker volume create "$VOLUME_NAME" >/dev/null

if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  echo "Attaching to existing container '$CONTAINER_NAME'..."
  docker start -ai "$CONTAINER_NAME"
else
  docker run -it \
    --name "$CONTAINER_NAME" \
    --shm-size=1g \
    -v "$REPO_ROOT":/workspace/fieldguard \
    -v "$VOLUME_NAME":/root/ardu_ws \
    -p 14550:14550/udp \
    -p 14551:14551/udp \
    "$IMAGE_TAG" \
    bash
fi

# --shm-size=1g (2026-08-22, round 3): Fast DDS carries every /fg/* image over SHARED MEMORY, and
# each participant allocates -- and memsets -- its own segment out of /dev/shm. Docker's default is
# 64 MB, which fits the stock 512 KiB segments but NOT the enlarged ones that fix the large-sample
# fragment loss (config/dds/fg_fastdds.xml: 8 MiB x ~6 participants = ~48 MB, before phase 2's
# 64 MiB). Raising the ceiling is a capacity enabler and provably changes NOTHING on its own --
# nothing allocates more unless segment_size does -- so it cannot confound the lever it enables.
# It is creation-time only: there is no `docker update` for it, hence the container re-create.
# KEEP IN SYNC with the duplicated docker run block in docs/runbooks/SIM_BRINGUP.md -- unlike the
# nine pane payloads, NO test asserts those two agree, so this flag can silently drift.
