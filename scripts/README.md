# Scripts

Bringup, generation, and eval helpers. Owned by devops + sim.

**Sim bringup (run inside the Docker container, see `docs/runbooks/SIM_BRINGUP.md`):**
- `sim_docker_build.sh` — build the `fieldguard-sim` image.
- `sim_docker_run.sh` — start/attach the container (repo bind-mounted, colcon workspace on a volume).
- `run_farm_mission.sh` — start Gazebo (headless) with the custom farm world; prints the SITL + agent
  recipes. The full flight is a multi-shell flow (Gazebo → agent → SITL), not one command — see the
  bringup doc for why (custom world path, agent-before-SITL ordering).

**Full-flight launcher (run on the macOS HOST, not in the container):**
- `fly_pipeline.sh` — one command for the whole `docs/runbooks/FULL_PIPELINE_DEMO.md` bringup: a
  `swathkeeper` tmux session, one window per runbook shell, each running that shell's `docker exec`
  one-liner byte-identical to the runbook, in order, with a timed health gate between steps
  (gz advertisements → ROS 2 topics → the **mandatory** render-alive probe → UDP 2019 before SITL).
  Gates fail fast on a dead pane rather than waiting out their timeout, and `up` refuses to start
  on top of a bringup already live in the container (liveness gates cannot tell whose processes
  they found). `up` never flies — SITL stays interactive with the fly recipe in the pane beside it
  (ADR-013) — and birds are altitude-gated off `/ap/pose/filtered`. The one scripted flight is
  `test-flight` (ADR-013 amendment 2): a pre-demo **regression gate** that reuses `up`, waits for
  DDS + EKF + GPS before touching the keyboard, flies `config/missions/test_2lane.waypoints`, then
  tears down recorder-first, stitches, and writes `eval/results/testflight_gate_<UTC>.json`. Demo
  and recording flights stay human-flown.
  `up | attach | status | birds | down | test-flight`, plus `--dry-run` (prints every docker/tmux command and
  changes nothing; needs neither Docker nor tmux) and `--gate-geometry`. Teardown SIGINTs the
  recorder first and waits for finalize, then prints the stitch command with the real clip dir.
  Needs `tmux` (`brew install tmux`). **Flown live 2026-08-18: `test-flight` PASS in 253 s**
  (`eval/results/testflight_gate_20260818T222031Z.json`) — what that run did and did not prove is
  in the verification note at the top of the runbook.

**Docs site (run on the HOST; needs `python3 -m pip install markdown`):**
- `build_docs_site.py` — renders `README.md`, `TIGER_TEAM_GUIDE.md` and every `docs/**/*.md` into
  `docs-site/` (gitignored, ~0.2 s, idempotent), styled in the **D · Heatmap Neutral** direction
  (ADR-014): monochrome warm-grey chrome, with the NDVI ramp spent only where colour means
  something — status rows, gate markers, callout edges. Markdown sources are never touched; this is
  a rendering layer, so the docs stay diffable on GitHub exactly as they are.
  Exits nonzero on any source that won't read or convert, on a **relative link that resolves to
  nothing**, and on **heading drift** — the render must produce exactly the headings the source
  declares, which is what catches a body line that Markdown quietly reads as a title (ADR-014
  amendment). `python3 scripts/build_docs_site.py && open docs-site/index.html`.

**Generators (stdlib + numpy):**
- `gen_boustrophedon.py` — boustrophedon coverage mission → `config/missions/boustrophedon.waypoints`.
- `gen_farm_world.py` — the farm world SDF **and** the `config/static_obstacles.json` geofence export
  from one tree list (kept in sync). Also emits the ADR-007 dual-band NDVI sensor mount and a
  calibrated `<temperature>` on every visual, from `config/ndvi_camera.json`.

**Checks / regression:**
- `check_mission_geofence.py` — min XY clearance of the mission path vs. the tree geofence (exits 1 on
  the documented, altitude-safe row-0 overlap — expected, not a failure).
- `check_spike_regression.py` — CI gate: fails if the seed-42 per-bird-track FNR regresses, or frame FNR / precision slip past their calibrated floors (ADR-003).
- `check_ndvi_bands.py` — ADR-007 Gate 2 (Weeks 5-6): samples the raw `/fg/sensor/nir/image` band and
  asserts canopy/soil/bird read back materially different, well-separated values (see
  `docs/runbooks/NDVI_VALIDATION.md`, needs a running Docker sim + `--out` for a JSON summary; `--print-calibration`
  works standalone, no ROS 2 needed).
- `validate_agents.py` — validates the tiger-team config + repo structure (the `validate-config` CI job).
