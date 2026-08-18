#!/usr/bin/env bash
# Build the Week 1 sim container image. Run from anywhere; resolves the repo root itself.
#
# Usage:
#   scripts/sim_docker_build.sh            # native platform
#   scripts/sim_docker_build.sh --amd64    # force linux/amd64 (fallback if arm64 apt/build breaks,
#                                           # see docs/runbooks/SIM_BRINGUP.md gotcha #2)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="fieldguard-sim:week1"
PLATFORM_ARGS=()

if [[ "${1:-}" == "--amd64" ]]; then
  PLATFORM_ARGS=(--platform linux/amd64)
fi

# Note: ${PLATFORM_ARGS[@]+"${PLATFORM_ARGS[@]}"} (not a bare "${PLATFORM_ARGS[@]}") so an EMPTY
# array doesn't trip `set -u` on bash 3.2 — the version macOS ships, which treats an empty array as
# unset ("unbound variable"). This idiom expands to nothing when empty, and to the quoted elements
# otherwise. Do not "simplify" it back.
docker build ${PLATFORM_ARGS[@]+"${PLATFORM_ARGS[@]}"} -t "$IMAGE_TAG" -f "$REPO_ROOT/sim/docker/Dockerfile" "$REPO_ROOT"
