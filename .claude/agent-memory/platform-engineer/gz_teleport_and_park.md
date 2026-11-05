---
name: gz-teleport-and-park
description: How to move and park models in a headless gz-sim8 check world — set_pose is applied ONLY by the Physics system (its `data: true` means QUEUED), a nested-include vehicle ignores <static>, so zero gravity is the park trick; plus the stale-server and pgrep traps.
metadata:
  type: project
---

Learned the hard way on 2026-09-06, when `scripts/verify_depth_mount_geometry.sh` ran for the first
time and **scored a bird that had never moved** (D2 CLEAR + D2 FAR "PASS", everything needing the
bird nan, D3 = 0.0 m). Applies to ANY future teleport/park harness on this stack, not just depth.
Related: [[forward-depth-sensor]], [[farm-world-layout]], [[adr007-ndvi-sensor-mount]].

## The rule: a teleport is not a teleport until you read the pose back
* `/world/<w>/set_pose` is served by **UserCommands**: `PoseCommand::Execute` -> `updatePose()` only
  creates/updates a `components::WorldPoseCmd` (gz-sim8 `src/systems/user_commands/UserCommands.cc`).
* The **ONLY** consumer is `PhysicsPrivate::UpdatePhysics` (`src/systems/physics/Physics.cc`,
  ~L2873-2946): it applies the pose through `entityModelMap` and removes the component next
  iteration. **No Physics system => set_pose is a silent no-op.**
* The service replies `data: true` as soon as the command is **QUEUED** (ServiceHandler), so the
  Boolean says nothing about motion. Verify with `gz topic -e -t /world/<w>/pose/info -n 1`:
  split the text on `"\npose {"`, take the block containing `name: "<model>"`, regex
  `position { x: .. y: .. z: .. }` (proto text OMITS components that are exactly 0.0 — default them,
  do not require all three). Top-level names in the farm world: `bird_0`, `iris_with_gimbal_ndvi`.

## The park trick: keep physics, zero gravity
* The old `verify_mount_geometry.sh` (NADIR, ADR-007, live-verified 2.2 px) strips the physics
  plugin so the vehicle will not free-fall. That is fine THERE — it never teleports anything — and
  ADR-019 forbids reopening it. It is fatal in any harness that moves a model.
* `<static>true</static>` on the wrapper model does NOT work: `iris_with_gimbal_ndvi` is a
  **nested include** and does not inherit it (2026-08-18 finding, reconfirmed 2026-09-06 — the
  vehicle still fell 15.0 -> 0.19 m).
* **`<gravity>0 0 0</gravity>` as the first child of `<world>`** does: a free body with no forces
  stays exactly where it is. Measured: `iris_with_gimbal_ndvi` held EXACTLY (60, 30, 15) from t0
  through a >25 s run, and every set_pose applied.

## Scene-extent trap (why a "clip" reading may be the map edge)
`field_ground` is a 125.00 x 110.00 m plane at (37.5, 30) => east edge x = 100, only **39.85 m**
ahead of the depth park pose at x = 60.15. A far-clip check from there measured 39.70 m — the
scene's EDGE, not the 60 m clip. Fix in the CHECK COPY only (`sed` the plane to 425.00 x 110.00):
the 10 m frame then reads max finite Z 57.99 m at |ray| 1.034 = far/|ray|, +inf fraction 0.796, and
the finite/inf boundary stays a clean curve (24 partially-finite rows, 0 fragment components).
Never edit the committed world or `gen_farm_world.py` for a harness's convenience.

## Server lifecycle
* `gz sim -s` is ONE process (ruby, in-process server). `kill <pid>` (SIGTERM) -> gone in ~1 s, its
  topics off `gz topic -l` within ~3 s. Orphans only happen when the killer mis-targets.
* **Never `pgrep -f "gz sim"`**: `-f` matches the whole command line, so any `bash -c '... gz sim
  ...'` wrapper — including the gate itself — matches and kills itself (that is exactly what
  happened on 2026-09-06). `pgrep -x gz` is vacuous instead: `/usr/bin/gz` is a ruby script, so the
  server's comm is `ruby`. Match argv positionally: `ps -eo pid=,args=` + awk on argv[0] == gz (or
  ruby .../gz) and the next arg == `sim`.
* Teardown must WAIT on `kill -0` (and treat a **zombie** — `ps -o stat=` starting with Z — as dead,
  or the loop burns its timeout and SIGKILLs a corpse), then wait for the topics to disappear.
