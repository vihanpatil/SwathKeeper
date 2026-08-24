# robotics-sim-engineer memory index

- [Toolchain version pins](toolchain_version_pins.md) — ADR-004 confirmed (Humble+Harmonic); exact component branches + why ArduPilot pins to a master SHA, not a stable tag.
- [macOS/arm64 bringup gotchas](macos_arm64_bringup_gotchas.md) — no GPU passthrough, arm64 package risk, Docker networking, X11 flakiness, bind-mount slowness.
- [Bringup file layout](bringup_file_layout.md) — where docs/runbooks/SIM_BRINGUP.md / sim/docker/Dockerfile / scripts live, and the devops handoff boundary.
- [User context](user_context.md) — solo dev, Apple Silicon Mac, 7-8 week deadline, container-first by default.
- [Spike clip generator](spike_clip_generator.md) — sim/spike/ layout, schema decisions, camera-footprint-dwell waypoint gotcha, no-numpy dev env note.
- [Farm world layout](farm_world_layout.md) — sim/worlds/farmguard_field.sdf generator pattern, tree-height-vs-mission-altitude design decision, SDF comment/actor gotchas.
- [ADR-007 NDVI sensor mount](adr007_ndvi_sensor_mount.md) — thermal-sensor SDF mechanics (per-visual plugin, L16 packing formula), nested-model+fixed-joint attachment to iris_with_gimbal, Gate 0/1/2 structure.
- [Recording-throughput levers](recording_throughput_levers.md) — CLOSED 2026-08-22 (Fast DDS SHM segment, 5.0 Hz flat); plus the disproven 5→2 Hz lever and the two kept ones.
- [Bird ground-truth track](bird_ground_truth_track.md) — the applied-pose log is the only bird truth (labels + safety CPA); clock-anchor numbers, schema 1.0 vs 1.1, offline flight rehearsal.
- [Avoidance-with-real-detection take](avoidance_real_detection_take.md) — the Week-6 runbook: precheck gates + margins, 7 panes + the unlaunched 8th shell, post-flight gate sequence and verdict meanings.
