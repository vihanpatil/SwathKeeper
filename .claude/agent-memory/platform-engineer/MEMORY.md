Consolidated 2026-11-05 from robotics-sim-engineer, devops-reliability-engineer (team v2); entries below keep their original dates and role names.

# platform-engineer — memory index

## From robotics-sim-engineer
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
- [Forward depth sensor (ADR-019)](forward_depth_sensor.md) — COMMISSIONED 2026-09-06/07: D2 8/8, D3 46.0 m ratified, D4 exit 0 @1.780×, D5 132/132 (at 3.5 m/s, not cruise); corner bound now ONE copy; the two sweep guards.
- [gz teleport + park (set_pose/Physics)](gz_teleport_and_park.md) — set_pose applies ONLY via Physics (`data: true` = queued); park with zero gravity, never `<static>`; pgrep/zombie/scene-edge traps.
- [Unfinalized clip / skipped teardown](teardown_unfinalized_clip.md) — 2026-08-25: `down` skipped, recorder + drive_birds ran on for 22 min; recover via the shipped send_ctrl_c, never rebuild meta offline.

## From devops-reliability-engineer
- [CI pipeline structure & verified commands](project_ci_pipeline.md) — job map incl. the if-always + KNOWN_RED rework and pages.yml, local repro commands, install-free root (2026-09-10)
- [Owner's 2026-09-10 direction call](project_portfolio_decision_20260910.md) — portfolio first, market-test the METHOD, wire program cut, delete aggressively, honesty artifacts widened
- [Mission-geofence gate is ARMED](mission_geofence_gate_is_armed.md) — a real CI gate since 2026-09-11 (3D verdict, exit 0 on the committed mission); never re-add `|| true`
- [Where pinned versions live](reference_pinned_versions.md) — CLAUDE.md vs requirements-eval.txt vs validate-config's unpinned pyyaml
- [Bug-hunter-not-YAML-author working style](feedback_bug_hunter_not_yaml_author.md) — always run locally in a matching venv before writing CI steps; never claim green without proof
- [Doc claims get measured too](feedback_docs_claims_get_measured.md) — reproduce the reader's env, quote real stdout, re-check handed-down facts against DECISIONS.md
- [sim image + container state](project_sim_image_state.md) — scipy rebuild DONE (verified 2026-08-25), shm 1 G; what still gates a booked take
- [Weeks 5-6 headless Docker/Gazebo CI job](project_week5_ci_gazebo.md) — feasibility verdict (no hosted-runner precedent even upstream), what's built vs unverified, manual-dispatch-gated until a human confirms green (2026-08-05)
- [Booked speed → the air](project_booking_speed_enforcement.md) — `--booking` injects `param set WP_SPD <m/s>` (NOT WPNAV_SPEED); why there are TWO booking sidecars (2026-09-07)
- [The tuning scanner blocks flight params](project_tuning_scanner_blocks_flight_params.md) — any WPNAV_/PSC_/GUID_ token, even in prose, fails the point-mass validity test; no placement avoids it
