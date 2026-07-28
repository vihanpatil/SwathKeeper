#!/usr/bin/env bash
# Build the Week 1 sim container image. Run from anywhere; resolves the repo root itself.
#
# Usage:
#   scripts/sim_docker_build.sh            # native platform
#   scripts/sim_docker_build.sh --amd64    # force linux/amd64 (fallback if arm64 apt/build breaks,
#                                           # see docs/WEEK1_BRINGUP.md gotcha #2)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="fieldguard-sim:week1"
PLATFORM_ARGS=()

if [[ "${1:-}" == "--amd64" ]]; then
  PLATFORM_ARGS=(--platform linux/amd64)
fi

docker build "${PLATFORM_ARGS[@]}" -t "$IMAGE_TAG" -f "$REPO_ROOT/sim/docker/Dockerfile" "$REPO_ROOT"
