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
    -v "$REPO_ROOT":/workspace/fieldguard \
    -v "$VOLUME_NAME":/root/ardu_ws \
    -p 14550:14550/udp \
    -p 14551:14551/udp \
    "$IMAGE_TAG" \
    bash
fi
