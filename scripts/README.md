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
  from one tree list (kept in sync). Also emits BOTH sensor mounts — the ADR-007 dual-band nadir
  NDVI pair with a calibrated `<temperature>` on every visual (`config/ndvi_camera.json`) and the
  ADR-019 forward depth camera (`config/depth_camera.json`).

**Checks / regression:**
- `predict_bird_visibility.py` — **run this before spending a Docker session on a detection flight,
  at the speed the mission will actually fly** (`--speed` is REQUIRED and has no default: the 3 m/s
  it used to assume PASSed a geometry the 2026-08-25 take then flew at ~9 m/s for 2 bird-visible
  frames — ADR-016). Mission file × bird config × the same `ndvi_georef` projection → "will any bird
  be in frame, and for how many frames", host-only in 0.8 s, exit 1 when a bird is below the frame
  floor, exit 2 when it refuses (no speed, or an unannotated clip). Sweeps the
  bird driver's start offset and reports each bird as `STRUCTURAL` (never in frame at any offset —
  only geometry can fix it) or `TIMING` (does cross, just rarely). `--backtest <clip>` replays a
  flown clip's own poses through the identical geometry, and reproducing the demo take's measured
  0/454 is what makes the prediction trustworthy (ADR-003 amendment 2).
- `predict_forward_lead.py` — **THE ADR-019 BOOKING GATE**: does the forward depth camera buy enough
  lead to clear the 3.00 m bar at a given mission speed? `--speed` is REQUIRED (same doctrine, same
  reason). Every number is imported from its owner — the bar from `PolicyParams`, the plant from
  `eval/point_mass.GUIDED_DEFAULT`, the bird speed from the birds config, the frame period from
  `config/depth_camera.json` — so the gate cannot drift from the control law. Four exit codes:
  **0** PASS *and bookable* (live-measured intrinsics + `--acq-range-m`), **1** FAIL, **2** refusal
  (no speed, or any unusable/partial input), **3** PASS but NOT bookable — config-sourced inputs,
  live intrinsics with no `--acq-range-m`, or a `--sweep` in which some row passes (ADR-019 item 6
  wants the horizon from the sensor, not from prose). A `--sweep` where nothing passes exits **1**;
  the unconditional property is that a sweep can never exit **0**. The live intrinsics are a **set
  of six off ONE `camera_info`** — `--fx --fy --cx --cy --width --height` — because the frame-corner
  far-clip bound needs the FARTHEST corner (`max(cx, W−1−cx)/fx`, `max(cy, H−1−cy)/fy`) and not the
  principal point; part of a set is a refusal, and live `W×H` that disagrees with the config (which
  *generates* the world SDF) is a refusal too. `--acq-optical-prefix-m` records the prefix D3's
  bookable range was clamped from, so the schema-1.3 artifact says whether the horizon it authorised
  was a clamped one (ADR-020 am. 1) — 1.3 adds a repo-relative config path beside the absolute one
  and the four intrinsics at full precision beside the 4-dp ones, purely additively, so the
  committed 1.2 artifact still validates untouched. The **mission-speed cap is a check**, not a
  printed note: `escape_survives_mission_speed_cap` re-runs the 1.3× bar against the plant a
  `WP_SPD` of `--speed` implies, so below **0.788 m/s** on the live set the run exits 1 where it
  used to print PASS/BOOKABLE beside "Re-derive before booking" (QA G127; 5.0 m/s is unaffected).
  `--sweep LO:HI:STEP` picks a mission speed. Measured on the
  committed config: PASS 2.0–9.0 m/s, **FAIL at 10.0** (ArduCopter's `WP_SPD` default), 1.811× at
  5.0; on 2026-09-06's live numbers at 5.0 m/s, **1.780× and exit 0** at `--acq-range-m 46.0` — a
  **best-case-scene upper bound** (no clutter, sky background, static vehicle, and no depth
  segmenter yet; ADR-020 am. 2, where the 33.591 m breakeven is pre-registered beside it). The
  margin is monotone in speed and in horizon; the **verdict is not** — past the 47.56 m
  frame-corner bound a *longer* horizon FAILs (47.5 → 0, 47.6 → 1), so sweep rather than assume.
- `check_depth_mount.py` — the HOST-side geometry gate for the ADR-019 forward mount, ~50 ms, no
  container: the SDF really carries the sensor and no dead `<camera_info_topic>`, the SDF pose ==
  the config == `depth_detect`'s importable mirror, the optical axis derived from the SDF rpy is
  body +X — and, the check that licenses the rest, the SAME general formula fed the NADIR mount's
  rpy reproduces `ndvi_georef.CAMERA_TO_BODY_SIGNS`, the extrinsic verified in the real render to
  2.2 px. Run in the suite too, so nobody has to remember it.
- `verify_depth_mount_geometry.sh` — the IN-RENDER half of the above, and the only place the
  acquisition range can honestly be measured: one **zero-gravity** world copy — physics KEPT,
  because `set_pose` is applied only by the Physics system and stripping it made every teleport a
  silent no-op — vehicle parked nose-east in clear sky, `bird_0` teleported to known ranges and
  **verified by a pose readback** (≤ 0.05 m, else exit 4: a gate that cannot place its target does
  not score pixels). Gates aim/range/self-occlusion at 10 m, then sweeps for the range at which the
  bird stops surviving the adopted morphology. **The sweep is asserted to be a sweep, twice**: no
  two captured frames may be byte-identical, *and* every detected station's blob must carry its own
  range — median finite depth within `TOL_M` of the bird's true Z (measured 0.02–0.16 m on the
  2026-09-07 frames, against a 0.20 m bound). Distinctness alone cannot catch a mis-teleport, and
  apparent size cannot either: the footprint plateaus at 4×4 px past 40 m, exactly where the booked
  number is read. Either failure is exit 4, the harness class, and the booking line is refused. It
  prints **two** ranges (ADR-020 am. 1): the
  *optical prefix*, which in a sky-backed scene is clip-limited and is a resolvability FLOOR, and
  the **BOOKABLE** range — the longest prefix range inside the frame-corner Z-depth horizon
  `far/|ray_corner|`, since gz culls on Euclidean slant — computed by the **one** copy of that
  formula, `depth_detect.corner_ray_ratio`, imported here as it is by the other two gates. It prints
  the whole `predict_forward_lead.py` command with the six live `camera_info` values already
  substituted, so the operator copies a set instead of retyping one. Feed the **bookable** one to
  `predict_forward_lead.py --acq-range-m` — **only from a run that exited 0**: a run that failed a
  mount gate labels the sweep *not a measurement* and refuses to print that command line, because
  the range was read through geometry the same run disproved. Exit 0 and 1 are the only codes that
  say anything about the mount; 4 (and 124/130/143) mean the run was never scored. See
  `docs/runbooks/FORWARD_DEPTH_SENSOR.md`.
- `check_mission_geofence.py` — CI gate (R8, ADR-022 am. 2): the mission path vs. the tree geofence in
  **3D**, using the executor's own `unsafe_obstacle_3d`. Reports min XY clearance per leg (the
  documented row-0 overlap, -1.997 m, still prints) and the vertical clearance over each tree column;
  exit 1 only if a leg actually enters a tree's volume, exit 2 on unreadable inputs.
- `check_spike_regression.py` — CI gate: fails if the seed-42 per-bird-track FNR regresses, or frame FNR / precision slip past their calibrated floors (ADR-003).
- `check_ndvi_bands.py` — ADR-007 Gate 2: samples the raw `/fg/sensor/nir/image` band and asserts
  canopy/soil/bird read back materially different, well-separated values (see
  `docs/archive/NDVI_VALIDATION.md`, needs a running Docker sim + `--out` for a JSON summary; `--print-calibration`
  works standalone, no ROS 2 needed). **Passed live 2026-08-18** (canopy 0.854 > soil 0.212 > bird
  0.040 over 996 frames); it is a regression check now, not a pending experiment.
- `check_render_alive.py` — the render-sanity probe `fly_pipeline.sh` runs before every flight
  (`--gate-geometry` wires in `verify_mount_geometry.sh` below); a degraded long-lived Gazebo
  instance previously cost a whole recorded flight before this existed.
- `verify_mount_geometry.sh` — the geometry gate ADR-007 amendment 5 added: parks the vehicle 1 m
  from a known tree in a physics-free world copy and checks the canopy centroid lands within 15 px
  of `ndvi_georef`'s prediction (measured 2.2 px). Run after any change to the mount, the vehicle
  SDF, or the georef extrinsics.
- `check_tree_positions.py` — the post-flight companion to `verify_mount_geometry.sh`: reads a
  clip's stitched `heatmap/heatmap.json`, prints the per-tree table (imaged / canopy-grade / NDVI
  lift), and **exits 1 on the georef-displacement signature** — a positive-NDVI cell more than 2 m
  from every tree centre. Post-mount-fix clips sit at 1.7678 m, the horizon-mount ones at
  6.4-11.9 m. Host-only, no container. The runbook's proof standard points here, because
  `cells_imaged` will not catch a map that is full and misplaced.
- `check_live_flight_log.py` — evidence gate for `eval/results/*flight_log*.json`: parses the log,
  runs the `check_ledger` partition invariant against the canonical grid, and rejects an empty
  `flown_path_enu`. Exists because the 2026-08-05 demo log was silently clobbered by a later idle
  run and nothing noticed. **`--booking eval/results/booking_gate_<UTC>.json`** (or a
  `<log-stem>.booking.json` sidecar beside the log) binds the take to the speed the ADR-019 booking
  gate authorised: the flown **median / p90 / max** airborne ground speed is measured from the log's
  own poses, and a median more than **10 %** past the booked speed is INVALID — *not the authorised
  take* (QA G128; before 2026-09-07 nothing set a waypoint speed, so ArduCopter's 10 m/s `WP_SPD`
  default flew a 5.0 m/s booking). **Two** medians are gated: the whole flight's and each
  **encounter window's** (takeover → resume, QA G138) — the mission median cannot see the failure
  (2026-08-25: whole-flight 3.417 m/s passes, encounter 9.012 m/s = 1.80× booked fails). Optional for the NDVI survey, which needs no booking; on an avoidance take its absence
  prints a WARNING that the authorisation is unverified. Only an artifact that exited **0** may be
  bound — a `--sweep` or a config-sourced design check authorises nothing.
- `check_sim_smoke.py` / `ci_sim_smoke.py` / `ci_sim_smoke.sh` — the headless CI smoke flight and
  its regression gate (ADR-008). **Unverified live** — the job stays `workflow_dispatch` until one
  green run (`docs/archive/SIM_CI.md`).
- `validate_agents.py` — validates the tiger-team config + repo structure (the `validate-config` CI job).

**Flight-session helpers (run alongside a live sim):**
- `drive_birds.py` — supplies the bird motion the removed `<actor>` scripts used to promise
  (ADR-012): interpolates `config/birds/farm_world_birds.json` and teleports each bird via
  `set_pose` at 5 Hz on the **Gazebo sim clock**. Must be running for any Gate-2 bird check or
  recorded flight; `--once <t>` parks the birds for a deterministic still.
- `stitch_ndvi.py` — the offline post-flight stitch (ADR-010): a spike-schema clip → per-cell mean
  NDVI on the same canonical 2.5 m / 720-cell grid as the coverage ledger, joinable by `cell_id` →
  `heatmap.json` + `heatmap.png`. Exits nonzero on an empty stitch.
- `build_dashboard_data.py` — populates `dashboard/data/` for the static v1 dashboard (ADR-018).
  Copies flight logs / safety markers / stitched heatmaps byte-for-byte and derives the rest by
  CALLING the gates (`check_live_flight_log`, `check_tree_positions`, `coverage.build_grid`), so the
  page can never hold a verdict the gate does not. Idempotent; `--check` exits 1 when the committed
  tree is stale and is pinned by `tests/test_build_dashboard_data.py`.
