---
name: bringup-file-layout
description: Where the Week 1 sim bringup artifacts live and the ownership split with devops-reliability-engineer for hardening them later.
metadata:
  type: project
---

Week 1 bringup artifacts and their locations, established 2026-07-27:
- `docs/runbooks/SIM_BRINGUP.md` — the ordered, macOS-friendly setup + bringup checklist, owned by
  `robotics-sim-engineer`. Each step has an explicit verification command; don't skip a step's
  check to "move faster" — this stack fails in different, easily-confused ways at each layer
  (SITL-only vs Gazebo-plugin vs ROS 2/DDS bridge), and the doc is structured to isolate which
  layer broke.
- `sim/docker/Dockerfile` — a deliberately minimal "get it green" starter image (ROS 2 Humble +
  Gazebo Harmonic + ArduPilot build deps installed, but the actual `vcs import`/`colcon build`/
  `./waf build` steps are done interactively per the bringup doc, not baked in). Explicitly labeled
  as a starting sketch for `devops-reliability-engineer` to harden (multi-stage build, non-root
  user, baked-in resolved SHAs, CI wiring) once Week 1 goes green — don't mistake it for the
  production container.
- `scripts/sim_docker_build.sh`, `scripts/sim_docker_run.sh` — thin wrappers around `docker build`/
  `docker run` with the named-volume + published-port conventions from
  [[macos_arm64_bringup_gotchas]] already baked in.

How to apply: when asked to iterate on the container or bringup scripts, treat the Dockerfile as
pre-hardening — don't over-engineer it (no multi-stage, no CI-specific caching) until devops takes
it over; that's an explicit scope boundary agreed at Week 1, not an oversight.
