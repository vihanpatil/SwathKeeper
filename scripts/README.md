# Scripts

Bringup, generation, and eval helpers. Owned by devops + sim.

**Sim bringup (run inside the Docker container, see `docs/WEEK1_BRINGUP.md`):**
- `sim_docker_build.sh` — build the `fieldguard-sim` image.
- `sim_docker_run.sh` — start/attach the container (repo bind-mounted, colcon workspace on a volume).
- `run_farm_mission.sh` — start Gazebo (headless) with the custom farm world; prints the SITL + agent
  recipes. The full flight is a multi-shell flow (Gazebo → agent → SITL), not one command — see the
  bringup doc for why (custom world path, agent-before-SITL ordering).

**Generators (stdlib + numpy):**
- `gen_boustrophedon.py` — boustrophedon coverage mission → `config/missions/boustrophedon.waypoints`.
- `gen_farm_world.py` — the farm world SDF **and** the `config/static_obstacles.json` geofence export
  from one tree list (kept in sync).

**Checks / regression:**
- `check_mission_geofence.py` — min XY clearance of the mission path vs. the tree geofence (exits 1 on
  the documented, altitude-safe row-0 overlap — expected, not a failure).
- `check_spike_regression.py` — CI gate: fails if the seed-42 per-bird-track FNR regresses (ADR-003).
- `validate_agents.py` — validates the tiger-team config + repo structure (the `validate-config` CI job).
