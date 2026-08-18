---
name: macos-arm64-bringup-gotchas
description: Known macOS (Apple Silicon) gotchas for running the Gazebo/ArduPilot/ROS 2 stack in Docker Desktop — rendering, arm64 package risk, and networking.
metadata:
  type: project
---

The developer's machine is confirmed Apple Silicon (arm64) macOS, using Docker Desktop. Full detail
lives in `docs/runbooks/SIM_BRINGUP.md` "Known macOS gotchas" — this memory is the condensed version worth
recalling before debugging a fresh setup failure.

1. **No GPU passthrough into Docker Desktop on macOS at all (Intel or Apple Silicon).** Gazebo's
   sensor rendering falls back to software rendering (llvmpipe). Camera topics (including the
   NDVI camera, Weeks 5-6) will still publish correctly but slower than real-time — don't spend
   time chasing GPU passthrough, it doesn't exist for this setup.
2. **arm64 is the least-tested path in this stack.** ROS 2 Humble on Ubuntu 22.04 arm64 is Tier 1
   and should be fine. Gazebo Harmonic's OSRF apt repo does publish arm64 debs, but the combination
   with `ardupilot_gazebo`'s from-source C++ plugin (needs `libgz-sim8-dev`) is far more commonly
   run on amd64 by the community — this is unconfirmed-by-testing risk, not a known failure.
   Fallback if arm64 breaks: `docker build/run --platform linux/amd64` (Rosetta emulation under
   Docker Desktop) — slower but functional. `scripts/sim_docker_build.sh --amd64` already wires
   this fallback.
3. **Don't try to split SITL/Gazebo/ROS 2 across host and container networking on Mac.** Docker
   Desktop on macOS has no real `--network host`; run SITL + Gazebo + ROS 2 all inside one
   container. Only publish UDP ports (14550/14551) if you specifically want a host-side GCS like
   QGroundControl — Docker Desktop does proxy published ports to `127.0.0.1` on the Mac host fine.
4. **XQuartz/X11 forwarding to see a live Gazebo GUI is flaky on macOS** (OpenGL version
   negotiation issues are a known community complaint). Default to headless
   (`gz sim -s -r --headless-rendering`); dump rosbags/PNG frames to the mounted volume and view
   with native macOS tools instead of fighting X11.
5. **Bind-mount the repo, but use a named Docker volume for the colcon workspace** (`build/`,
   `install/`, `log/`). macOS Docker Desktop bind-mount I/O is slow for the many small files a
   colcon build churns through; a named volume avoids that entirely.

How to apply: check gotcha #2 (arm64 package risk) first if a rosdep/colcon/plugin build fails on
this machine — it's the single most likely macOS-Apple-Silicon-specific failure mode, distinct from
generic ArduPilot/Gazebo setup issues that'd also hit an amd64 Linux dev.
