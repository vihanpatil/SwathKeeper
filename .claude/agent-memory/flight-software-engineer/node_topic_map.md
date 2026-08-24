---
name: node-topic-map
description: FieldGuard ROS 2 node/topic map, package layout, locked AP_DDS /ap/* contract (Weeks 3-4 live) + Weeks 5-6 NDVI nodes, the avoidance control parameters incl. R2/R3 as landed 2026-08-24, the two-half CPA-breach acknowledgement contract, and the test-flight gate's evidence-yield floor parameters
metadata:
  type: project
---

Current as of 2026-08-05 (Weeks 3-4 avoidance loop demonstrated live; Weeks 5-6 NDVI fusion/georef
built and unit-tested, render still pending a human Docker session). Supersedes the old Week-2-only
version of this memory (kept the still-true parts, corrected/extended the rest).

## Package layout (`src/fieldguard_planning/`)
Still **not a real colcon/ament package** (no `package.xml`/`setup.py`) as of Weeks 5-6 —
`docs/runbooks/AVOIDANCE_DEMO.md` flags this as "a small follow-up." Everything runs via
`PYTHONPATH=src:$PYTHONPATH python3 -m fieldguard_planning.<node>` (note: **prepend**, don't
replace — a bare `PYTHONPATH=src` inside the container wipes out ROS 2's own Python path and gives
`ModuleNotFoundError: No module named 'rclpy'`). If this ever gets promoted to a colcon package,
that prepend gotcha becomes moot but is worth remembering for now.

Two dependency tiers inside the package (a project-blessed, documented split, not an accident):
- **stdlib-only**: `geofence.py`, `coverage.py`, `mission_waypoints.py`, `avoidance_types.py`,
  `avoidance_policy.py`, `avoidance_executor.py`, `ros2_adapter.py`'s pure `enu_to_geodetic`, and
  `ndvi_georef.py`'s single-point transform functions (`pixel_to_latlon`, `world_enu_to_pixel`,
  etc. — no numpy needed for one point/ray). Runs on a bare interpreter, zero installs.
- **numpy-dependent** (a deliberate, scoped exception, documented in each module's own docstring):
  `ndvi_fusion.py` (per-pixel image math) and `ndvi_georef.py`'s `NdviHeatmapGrid` (accumulates
  numpy NDVI arrays). Already-blessed dependency (`requirements-eval.txt`, `eval/baseline_ndvi.py`,
  `scripts/check_ndvi_bands.py` all use it) — just newly extended into `src/fieldguard_planning/`
  for this one image-processing slice. If this pattern grows, it's worth a DECISIONS.md entry
  formalizing the dependency boundary; flagged for tech-lead, not decided unilaterally.
- Every rclpy-touching file (`avoidance_node.py`, `ros2_adapter.py`'s `Ros2VehicleSink`,
  `ndvi_node.py`) imports rclpy **lazily inside `build_node()`/`main()`**, never at module top —
  this is what lets the whole test suite run without a sourced ROS 2 environment. Follow this
  pattern for any future node.

## Reactive-avoidance loop (Weeks 3-4) — CONFIRMED LIVE 2026-08-05
- Interface boundary: `avoidance_types.py` (`Detection`, `DroneState`, `AvoidanceManeuver`,
  `Decision` enum: PROCEED/DIVERT/HOLD).
- Decision policy (perception-ml-engineer's `avoidance_policy.py`) decides *when/where*; executor
  (`avoidance_executor.py`, mine) takes control, flies it, resumes, books coverage-debt.
- ADR-006 maneuver shape, CONFIRMED live: `AUTO -> GUIDED -> one 3D-vetted setpoint -> GUIDED ->
  AUTO`, `MIS_RESTART=0` makes AUTO resume the SAME next waypoint (verified: reached #3, took
  control heading to #4, resumed at #4, continued #5-#8, no restart at #1).
- Safety backstop: every point the executor is about to command is re-vetted on the tick it is
  commanded, **both halves** — `GeofenceMap.is_safe_3d` (trees/altitude) AND the policy's own
  `min_bird_clearance_m` against `debug["threat_positions_enu"]`. Reject -> HOLD, never fly an
  unvetted point. The bird half landed 2026-08-24 (QA round 2): the geofence cannot see a bird, and
  a LATCHED point is bird-vetted only for the tick it was latched, so an R3 refusal re-commanded a
  latch the bird had walked to 1.000 m of, `verdict: accepted`, no gate_reject. The bar is read from
  the maneuver's OWN `debug["params"]` (no second literal in the executor); a maneuver with no
  params fails OPEN, same doctrine as a missing `range_degenerate` flag.
- `AvoidanceExecutor.finalize()` builds the terminal coverage ledger from the ACTUAL flown path via
  `coverage.coverage_from_path` — every canonical grid cell is visited exactly once by
  construction, so a cell can never be silently absent from the ledger (worst case: explicit
  `debt`, the allowed ADR-002 v1 outcome).
- Live bringup order that matters (real gotcha, cost real debugging time): **start the micro-ROS
  agent BEFORE SITL.** AP_DDS pings the agent at startup; if the agent isn't listening on UDP 2019
  yet, SITL prints `AP: DDS: No ping response, exiting` and NO `/ap/*` data ever flows (the
  avoidance loop then sees a permanently frozen pose). Order: Gazebo -> micro-ROS agent -> SITL
  (`--enable-DDS`) -> the avoidance node.
- **RE-FLOWN LIVE 2026-08-23** (`eval/results/live_flight_log_20260823T004031Z.json`, first run since
  2026-08-05): full boustrophedon, one encounter, **coverage ledger closed 720 covered / 0 debt**
  (the 2026-08-18 run was 513/207). Chain: 19 `detection` -> 1 `takeover` (AUTO->GUIDED at wp 6) ->
  1 `latch` + 7 `relatch` -> 19 `maneuver` all `accepted`, 0 rejected -> 1 `resume` -> 545
  `requeue_events`. `check_live_flight_log.py` PASS. The commanded-never-flown invariant verified
  directly: 19 distinct commanded setpoints, **0 overlap** with the 984 flown-path points.
- **BUT IT WAS A DE-FACTO BIRD STRIKE (ADR-013 am. 12, S1).** CPA to the bird was **0.0518 m**
  against the policy's own `min_bird_clearance_m` 3.0 — with every gate green, because nothing
  computed the distance FLOWN. "19/19 maneuvers vetted" is a claim about SETPOINTS. R1 (shipped
  2026-08-23) adds CPA to `check_live_flight_log.py`, sourced from `PolicyParams`, printed for every
  log every run. **The 2026-08-18 log breaches too, at 0.0597 m** — found by R1's first run over the
  committed evidence; that log predates the latch/relatch machinery entirely, so the gap is in the
  control law's escape geometry, not in the later logging. ACKNOWLEDGED takes **TWO halves since
  2026-08-24**: the sibling `<log-stem>.SAFETY_FINDING.md` marker AND the stem pinned in
  `ACKNOWLEDGED_BREACH_STEMS` inside `check_live_flight_log.py` (a reviewed diff on the gate).
  Either half alone = INVALID naming the missing half; a marker beside a PASSING log = stale
  acknowledgement = also a hard fail. **Why two:** the marker alone made the runbook's own remedy
  for a breach ("keep the log, add the marker") the one-`touch`, no-review way to turn the NEXT
  bird strike into green CI, in a gitignored directory — with R4 open and the next `--detect` take
  pre-registered as possibly breaching. The list is meant to stay two long; a breaching NEW take
  stays INVALID / exit 1 — the operator writes the marker (context) and does NOT add the pin.
  Markers still need their own `.gitignore` allowlist or CI reds out on committed history. The same
  file-not-contents doctrine now also guards the gate's LEGACY branch (`PRE_SEAM_LEGACY_STEMS` —
  see [[detection-seam-live]]).
- TWO THINGS WORTH KNOWING from that run, both self-reported by the executor rather than hidden:
  (1) `resume` recorded `resumed_same_waypoint: false` (took over at wp 6, resumed at wp 7) — the
  drone passed the waypoint during the dodge; ADR-006's "same waypoint" claim is about
  `MIS_RESTART=0` not restarting the mission, and the log does not overstate it.
  (2) At `trigger_range_m: 0.052` (drone essentially on top of the bird) the away-vector flipped to
  [0.758, 0.652] and the accepted setpoint had **swept_tree_clearance_m 0.846** against 7-8 m on
  every other tick, and the executor re-latched onto that 20.9 m jump. Both are now fixed in code —
  see the control-parameter block below.

## Avoidance control parameters (the numbers a flight is flown at; one home = `PolicyParams`)
`AvoidancePolicy.__init__` no longer re-declares any of them: it is `(*, field_polygon=None,
**params)` forwarding straight to `PolicyParams`, so a constructor default cannot drift from the
dataclass default that `check_live_flight_log.py` reads as its bar. Unknown knob = TypeError.
- `lateral_tree_margin_m` **0.0 -> 1.0** (R2, landed 2026-08-24). Measured price on the dense
  degenerate-range sweep (11 856 cases around three trees): HOLD rate 5.64 % -> 15.66 % (+10.0 pp,
  a worst-case neighbourhood, not a flight-wide rate), min accepted swept clearance 0.000 ->
  1.000 m, sub-metre tail 28.1 % -> 0 %. On the flown 19-tick encounter: still 19/19 DIVERT, the
  degenerate tick rotates +0 -> +45 deg at 7.563 m.
- `degenerate_range_m` **1.0, new** (R3). A FLAG, not a floor: `decide` still dodges, but publishes
  `debug["range_degenerate"]`, computed from the ROUNDED `trigger_range_m` that goes into the log so
  the gate's consistency check holds at the boundary by construction.
- Executor consequence: a re-latch is REFUSED on a flagged tick and logged as the fourth
  `latch_action` value, **`relatch_refused_degenerate`** (the other three: `latch`, `relatch`,
  `recommand_latched`). No latch event is emitted and latch state is untouched — UNLESS the kept
  latch is now inside `min_bird_clearance_m` of a threat, in which case the refusal falls through to
  HOLD, drops the dead latch (so the next tick can latch a fresh vetted point) and logs a
  `gate_reject` carrying `bird_clearance_m` / `bird_track_id` and still labelled
  `relatch_refused_degenerate`.
- Policy consequence: every threat-branch maneuver now also carries
  `debug["threat_positions_enu"]`, parallel to `threat_ids` — the executor's bird backstop and the
  flight-log gate's R3.7 assertion both read it, so an id with no position would be a threat neither
  can check.
- What R3 actually buys, measured, and NOT more: the flown noise-driven setpoint (37.6, 36.6, 15) is
  never commanded; the re-latch lands one tick later (0.2 s) at 1.192 m where the away-vector is
  geometry again. Relatches over the encounter 7 -> 6 + 1 refusal. **R2/R3 do NOT fix S1** (CPA
  0.0518 m); that is R4, the reversal-preferring candidate order `(0, +45, -45, ...)`, still open.
- `max_detection_age_s` **1.0, a `PolicyParams` DEFAULT** (2026-08-24, follow-up CLOSED same day).
  It was briefly armed from an `avoidance_node.MAX_DETECTION_AGE_S` constant while the dataclass
  default stayed None — one knob, two homes — and QA proved the consequence: the flight-log gate's
  upper-bound branch was dead code, so a log flown at 3600 s scored VALID. The node no longer
  declares or passes it (a test asserts the node source contains no `MAX_DETECTION_AGE_S =` and no
  `max_detection_age_s=`). Evidence for 1.0: the adopted clip's `frame_age_sim_s` is p50 0.143 /
  max 0.156 s (n=1256), ~6x headroom. Unstamped detections still fail OPEN, so the scripted sources
  are untouched; turning the gate OFF is now an explicit `max_detection_age_s=None`.
- Two detection sources, mutually exclusive at the CLI: `--demo` (scripted bird at ENU (30,30,15),
  `proximity_bird_source`, triggers within 10 m, lingers 12 s — tight enough not to fire on adjacent
  lanes) and `--detect` (the real ADR-003 am. 7 NDVI blob detector — see [[detection-seam-live]]).
  Demo recipe: `docs/runbooks/AVOIDANCE_DEMO.md`. Both now tag their detections `demo_virtual` /
  `ndvi_blob` honestly, and the node writes a `run` block (schema 2) into every flight log.
- `current_waypoint()` is DERIVED (nearest mission waypoint to current pose), not read from AP_DDS —
  no mission-current service exists at the pinned SHA (ADR-006 "why no waypoint-index juggling").
  Fine for resume bookkeeping since ArduPilot's own `MIS_RESTART=0` owns the actual resume.

## Locked AP_DDS `/ap/*` interface (ADR-005, CONFIRMED live — all 18 topics enumerated, matched exactly)
- `/ap/pose/filtered` (`geometry_msgs/PoseStamped`) — **frame_id says "base_link" but LIES**; the
  message *content* is world-ENU position relative to the EKF/home origin. Trust content, ignore
  frame_id, for this topic specifically. Same REP-105 mislabeling on `/ap/twist/filtered.linear`
  (world ENU) vs `.angular` (body-frame) — two frames under one message, don't cross them.
- `/ap/gps_global_origin/filtered` (`geographic_msgs/GeoPointStamped`) — WGS-84 EKF origin, the
  correct RUNTIME anchor for `/ap/pose/filtered`'s ENU frame (as opposed to
  `config/field_polygon.json`'s `home_lat`/`home_lon`, which is only the offline/test default and
  *should* match but isn't guaranteed to bit-for-bit).
- Command topics work OPPOSITE to telemetry: for `/ap/cmd_gps_pose` /
  `/ap/cmd_vel`, `frame_id` **is honored** as a real switch (`"map"` = world-ENU, transformed to NED
  internally; `"base_link"` = body-frame via `ahrs.body_to_earth()`). Command `"map"`, always —
  sending `base_link` by mistake flies a body-frame dodge.
- `/ap/cmd_gps_pose`/`/ap/cmd_vel` are ONLY honored in GUIDED + armed
  (`ready_for_external_control()`); ArduPilot silently drops them otherwise. This is why the
  executor must switch mode BEFORE sending a setpoint, every time.
- DDS_ENABLE is **not** on by default at the param-storage level even though the compiled default
  is `ENABLED_BY_DEFAULT=1` — the SITL instance's persisted `eeprom.bin` (named Docker volume) keeps
  whatever was saved the first time that param existed. Always load the explicit param file
  (`config/sitl_params/dds_udp.parm`), don't trust "the code says it defaults on."
- `ardupilot_msgs/msg/GlobalPosition` fields (verified against the pinned build): `header,
  coordinate_frame, type_mask, latitude, longitude, altitude, velocity, acceleration_or_force, yaw`.
  `ardupilot_msgs/srv/ModeSwitch.Request` has `mode` (uint8). ArduCopter mode numbers: AUTO=3,
  GUIDED=4.

## NDVI fusion + georef stitch (Weeks 5-6) — UNIT-TESTED ONLY, render pending Docker Gates 0-2
- ADR-007 locked contract: IN `/fg/sensor/rgb/image` (rgb8) + `/fg/sensor/nir/image` (mono16) +
  their camera_info; OUT `/fg/ndvi/image` (32FC1 ∈[-1,1], AUTHORITATIVE), `/fg/ndvi/camera_info`,
  `/fg/ndvi/preview` (rgb8, human-only, non-authoritative).
- `/fg/ndvi/image` now has TWO consumers with deliberately OPPOSITE QoS: `record_node` subscribes
  RELIABLE depth 10 (it wants every frame) and `avoidance_node --detect` subscribes **BEST_EFFORT
  depth 1** (a control loop wants the newest frame; a queued backlog is what the staleness gate
  would throw away one tick late). Do not "unify" them.
- Files: `ndvi_fusion.py` (pure fusion math + stale-pair guard, numpy), `ndvi_georef.py` (the
  pixel->lat/lon transform + `NdviHeatmapGrid` stitch accumulator, stdlib math for the transform
  itself), `ndvi_node.py` (thin rclpy adapter, `message_filters.ApproximateTimeSynchronizer`).
- Stale-pair guard (ADR-007 amendment): max stamp delta = `0.25 / update_rate_hz` (50ms at this
  project's configured 5Hz). Exceeding it DROPS the pair (never emits a mispaired NDVI) and
  increments a logged `dropped_pair_count` — same "instrument every event" discipline as the
  avoidance executor's `_log`.
- NDVI 0/0 guard: sentinel is `0.0` (neutral — a 0/0 pixel carries no vegetation signal either way),
  never a silent NaN; every occurrence is counted (`zero_denom_count`).
- Georef body-frame convention: FLU (X-forward,Y-left,Z-up), world ENU — matches
  `avoidance_node.py`'s existing yaw-extraction assumption, not a new/second convention. Mount
  extrinsic (ADR-007 nadir mount, quat_wxyz=(0,1,0,0)): camera<->body axis map is a diagonal
  `(+1,-1,-1)` sign flip (self-inverse, same tuple works both directions).
- The transform reuses `ros2_adapter.enu_to_geodetic` for the final ENU->lat/lon step rather than
  reimplementing it — one ENU<->geodetic transform for the whole project (mission planner +
  avoidance executor + georef stitch all share it).
- `NdviHeatmapGrid` reuses `coverage.py`'s canonical 720-cell grid (same `cell_id`s as the
  coverage-debt ledger) rather than inventing a second grid — a cell never imaged is `None` in
  `mean_grid()`, the NDVI-mapping analog of an explicit coverage-debt cell.
- **SUPERSEDED 2026-08-18/22 — this HAS run against the real render.** All four ADR-007 gates went
  green live, the sensor mount was corrected (it faced the horizon from the day it was authored),
  and multiple real clips + tree-verified heatmaps are committed. The open problem is no longer
  "does it render" but **recording throughput** — see [[throughput-instrumentation-results]].
- `/fg/sensor/nir/camera_info` was bridged but had ZERO subscribers until 2026-08-22; `ndvi_node`
  now counts it as `nir_camera_info_frames`, which is what gave the NIR band a denominator.
- Added **Gate 3** to `docs/runbooks/NDVI_VALIDATION.md`: re-fly the Week-3 avoidance demo against the new
  `iris_with_gimbal_ndvi` vehicle model (2 new cameras + 40 thermal plugins added render load) and
  confirm dodge->hold->resume still completes + RTF doesn't collapse — a regression check, not a
  new ADR-007 claim.

## `test-flight` gate parameters (as of 2026-08-19 — verify against `scripts/fly_pipeline.sh` before quoting)
- The gate's LAST check is an **evidence-yield floor**: `TF_MIN_FRAMES=12`, `TF_MIN_CELLS=40`,
  read from the clip's `meta.json` (`num_frames`) and `heatmap/heatmap.json` (`cells_imaged`).
  Both are **floors derived from n=2** (the 48-frame/291-cell baseline and the 3-frame/1-cell 2 Hz
  collapse) and tied to the `test_2lane` mission — a different mission needs different numbers.
  **Never state the floor has been live-exercised until a real `test-flight` has run against it**
  (as of 2026-08-19 it has not; it is pinned offline against the two committed gate records).
- **SUPERSEDED:** many test-flights have now run (four one-variable throughput flights on
  2026-08-21 plus the instrumented baseline on 2026-08-22), all committed under
  `eval/results/testflight_gate_*.json`. The floor itself is still 12/40 and still n=2-derived.
- The floor has now been live-exercised, and it FAILED a flight (2026-08-22, 7 frames / 37 cells) —
  correctly, but the cause was host load, not the pipeline. Always read the counters before
  believing the floor's suggested diagnosis; see [[host-quiet-is-a-flight-gate]].

## Field/geofence/mission constants (still true, Week 2 origin)
- Field: `config/field_polygon.json` — 75m(E) x 60m(N) rectangle, home = (-35.363262, 149.165237,
  584m elev), mission altitude 15m, ground plane assumed flat at local-ENU z=0 (also the georef
  stitch's flat-field assumption).
- Trees: `config/static_obstacles.json` — 18 trees, 3 rows at x=15,40,65 (y=5..55, spacing 10m).
  `obstacle_radius_m=2.0` is the geofence field (not `canopy_radius_m=1.3`). Tree row 0 (x=15) sits
  exactly on mission lane x=15 — -2.0m XY clearance, safe only because of the 11.5m vertical margin
  (canopy top 3.5m vs cruise 15m). This is the row already primed for forcing a real XY-plane dodge
  scenario if one is ever needed (rows 1/2 are offset from their lanes and aren't).

## ArduPilot/MAVLink gotchas (running list)
- `GZ_SIM_RESOURCE_PATH` must include `ardupilot_gazebo`'s `share` dir or the world fails to load.
- First SITL boot after a fresh build shows `Frame: UNSUPPORTED` — `FRAME_CLASS`/`FRAME_TYPE` only
  apply after a `reboot`, not just `param set`.
- `DISARM_DELAY 0` needed or the vehicle auto-disarms ~10s after arming before a mission starts.
- `AUTO_OPTIONS 3` needed to allow arming + auto-takeoff directly into AUTO mode.
- `MIS_RESTART 0` required for the avoidance executor's resume assumption to hold (ADR-006).
- **Agent BEFORE SITL** (see above) — the single most time-costly ordering gotcha found in Week 3-4
  live validation.
