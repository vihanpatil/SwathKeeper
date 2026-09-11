# SwathKeeper — System Spec

Autonomous drone survey system, built **entirely in simulation** (ADR-000): live reactive obstacle
avoidance + NDVI mapping on ArduPilot SITL + Gazebo Harmonic + ROS 2 Humble. ("Crop-health" is the
*shape* of the NDVI half; this world authors no health variation — see *What this system is NOT*.)
*(Originally written 2026-07-27 under the working title FieldGuard; rewritten 2026-08-18 as the
current-state spec. The original phased plan and resolved open questions moved to
`docs/BUILD_LOG.md` and `docs/DECISIONS.md` — this file describes the system, not the schedule.)*

**Direction (ADR-022, 2026-09-10):** SwathKeeper is a **portfolio project** — the floor is a
reconciled, licensed, hosted repo whose every claim checks out; a market test of the *evidence
method* follows it; drone-as-product (closing the control loop in sim, ≥20 seeded headless
encounters clearing 3.00 m) is deferred behind that answer, and hardware behind that. The
**claims ceiling is "sim-demonstrated, evidence-gated"** (ADR-019 §1) and it applies to every
sentence below.

## Priorities (order confirmed; annotated with the measured state, 2026-09-10)

1. **Flight autonomy + reactive obstacle avoidance** — still the differentiator: commercial ag-drone
   platforms fly pre-surveyed static missions, and live reactive avoidance of *unplanned* obstacles
   with coverage integrity is what they don't do. It is also the **least proven** thing here: three
   live flights, three bird-clearance breaches against the 3.00 m bar (0.0393 / 0.0391 / 0.0067 m,
   gate-recomputed — `eval/results/live_flight_log_*.json`).
2. **NDVI health mapping** — **FROZEN since 2026-08-26** (ADR-019 §7, re-affirmed ADR-022 8(d)). It
   works end to end (720/720 cells, 5.0 Hz flat) and is kept as the **working demo**, not open work.
3. **Farmer-facing dashboard** — **BUILT 2026-08-26** (ADR-018): a static client-side page over the
   committed artifacts — replay, avoidance event log, NDVI overlay on the shared grid.

## The core guarantee

A survey is only valid if every cell was imaged — so a dodge that skips cells must never be
silent. Every canonical grid cell (2.5 m, 720 cells over the field polygon) terminates in exactly
one state: `covered` or `debt`. Absence from the ledger IS the bug, and the partition invariant
(`coverage.check_ledger`) makes it a test failure. A *commanded* position is never recorded as a
*flown* position (regression-pinned after the 2026-08-18 ledger-honesty bug). v1 ships
avoid-then-resume + honest debt (ADR-002); full debt reconciliation (requeue missed cells) is the
documented stretch goal. **Measured, so nothing outside this file may say otherwise: there is no
replan and no requeue in the code** — `grep -rni replan src/` returns one prose hit, `MIS_RESTART=0`
resumes the *same* waypoint index, and the executor says so at `avoidance_executor.py:741` ("not a
v1 requeue mechanism").

## Architecture (as built)

1. **Simulation:** Gazebo Harmonic + `ardupilot_gazebo` + ROS 2 Humble, pinned to SHAs (ADR-004,
   `CLAUDE.md`), in Docker on Ubuntu 22.04. Custom farm world generated from config
   (`scripts/gen_farm_world.py` → `sim/worlds/farmguard_field.sdf`, byte-reproducible): bounded
   field polygon, 18 static trees in rows, 3 birds as static models teleported along their
   committed trajectories by `scripts/drive_birds.py` on the sim clock (ADR-012 — skinless SDF
   actors never entered the ogre2 render scene).
2. **Sensing (ADR-007):** dual-band NDVI camera = RGB camera (Red channel) + Gazebo **thermal
   sensor repurposed as synthetic NIR** (per-visual `<temperature>` authoring from the calibration
   table in `config/ndvi_camera.json`), co-located on one rigid nadir mount so fusion needs no
   resampling. Topics `/fg/sensor/*` → `ros_gz` bridge (four topics, live-verified 2026-08-18). Sun
   shadows are OFF in the world: the thermal band ignores illumination but Red does not, so a cast
   shadow darkens Red alone and reads as false vegetation (ADR-007 amendment — found via the
   drone's own shadow reading NDVI-positive). A second-sensor configuration (NDVI+RGB, reusing the
   RGB camera already needed for the Red band — ADR-007; NDVI+depth is a documented stretch, not
   v1) was **RETIRED as a comparison arm 2026-08-26** — the study measured that the RGB R channel
   *is* the NDVI Red band bit-for-bit, so it never was a second sensor (ADR-003 closure,
   criterion 2 = RETIRE-ARM). **The second sensor that does exist is a forward-facing gz-sim
   `depth_camera`** on its own level (ADR-020): commissioned live 2026-09-06/07 (all six D-gates
   measured, booked to 46.0 m at 5.0 m/s) with a black-top-hat segmenter scored 7/7 on an
   85-station cluttered render (ADR-021) — and it has **NEVER FLOWN**: no committed flight log
   contains a `depth_blob` detection. Built, scored, unflown, and frozen there until a take exists.
3. **Perception:** classical blob detector directly on NDVI frames (ADR-003 — NDVI-direct beat the
   bar: per-bird-track FNR 0.000 on the fixed-seed clip; any learned model must beat the same
   harness before it earns a place). Trees are a **pre-known static-obstacle map** (ADR-001,
   geofenced from a pre-flight boundary survey — a legitimate real-ag assumption), which isolates
   the genuinely hard problem: the unplanned dynamic obstacle. Detector evidence contract:
   ADR-009 (stamped detections + staleness gate; position via apparent-size ray, never
   ground-plane projection).
4. **Coverage planning:** boustrophedon (lawnmower) over the field polygon
   (`scripts/gen_boustrophedon.py`) — standard, not reinvented.
5. **Reactive avoidance + replanning (the core):** sim-agnostic policy + executor
   (`src/fieldguard_planning/`), bound to ArduPilot through a thin ROS 2 adapter over the AP_DDS
   `/ap/*` contract (ADR-005). Maneuver shape fixed by ADR-006: `AUTO → GUIDED → one 3D-vetted
   setpoint → GUIDED → AUTO`, latching (one takeover/resume per encounter), `MIS_RESTART=0` resumes
   the interrupted leg. Every DIVERT setpoint is re-vetted 3D against the geofence at the executor
   (the safety backstop); rejection falls back to HOLD. Every detection, takeover, maneuver,
   resume, and debt cell is logged. **The loop is OPEN, and the log records belief, not achievement:**
   `ros2_adapter.send_setpoint_enu` publishes and returns, `set_mode` is a non-blocking `call_async`
   whose outcome reaches only a log line, and `verdict="accepted"` is a constant written on the
   publish tick (`avoidance_executor.py:687`). No live gate compares commanded displacement to
   achieved — on 2026-08-25 that was 10 m commanded against 0.018 m flown in a 0.434 s GUIDED window.
6. **Health mapping:** NDVI = (NIR − Red)/(NIR + Red) per frame (`ndvi_fusion.py`), recorded live to
   a spike-schema clip (`record_node.py` / `clip_recorder.py` — each frame pairs to the pose
   nearest its OWN Gazebo-clock stamp; arrival pairing smears a render burst across meters, ADR-007
   amendment, and out-of-bound frames are flagged `pose_pair_stale` and skipped rather than painted
   somewhere wrong), georeferenced from SITL telemetry (`ndvi_georef.py`, hand-fixture-tested incl.
   tilted poses), stitched **offline post-flight** (ADR-010, `scripts/stitch_ndvi.py`) into a
   per-cell heatmap on the SAME canonical grid as the coverage ledger — heatmap cell and ledger
   cell join by `cell_id`.
7. **Dashboard (built 2026-08-26, ADR-018):** a static, self-contained client-side page over the
   committed artifacts — flight replay + avoidance event log + NDVI overlay, joined on the shared
   cell grid. No server, no CDN; verdicts are derived by importing the same gate CI runs.

## What this system is NOT — measured limits that travel with every number

These are facts about the tree, each with its source. If a doc, a README line or an agent says
otherwise, this section wins (ADR-022).

- **The NDVI map carries no crop-health variation.** The world authors exactly **four**
  `<temperature>` values (273 / 282 / 291 / 321 K, `sim/worlds/farmguard_field.sdf`) and one canopy
  colour, so the heatmap is a **canopy-vs-soil sign test**, not a health gradient.
- **The birds cannot collide with anything.** All three have **zero `<collision>` geometry** and are
  teleported by `gz service set_pose`, which bypasses physics — a strike is physically impossible in
  this world, so the **offline CPA gate is the entire safety system**.
- **The flying image is not SHA-pinned.** `sim/docker/Dockerfile` contains **no commit SHAs** and
  deliberately does not bake the workspace; no flight log records firmware or image identity. The
  pins in `CLAUDE.md` are a document, not an artifact — a flight is not reproducible on a second
  machine today.
- **Replan and requeue do not exist** (see *The core guarantee*) — scoped out by ADR-002, not built.
- **The control loop is open** (see Architecture §5): fire-and-forget commands, belief-based events,
  no live achieved-displacement gate.
- **The depth sensor has never flown** (see Architecture §2): every depth number comes from parked,
  noiseless renders.
- **Three live avoidance flights, three breaches** (see Priorities): two ACKNOWLEDGED exit 0, one
  **INVALID exit 1**, and the INVALID one stands.

## Evaluation discipline

No "it works" without a metric or a reproducible scenario. The `eval/` harness is deterministic
(fixed seeds, pinned numpy); CI gates on the seed-42 per-bird-track FNR, scenario-log byte-drift,
and flight-log evidence validity. Adversarial safety scenarios (`eval/scenarios/`) encode the
no-silent-skip invariant; live-run evidence is timestamped and validated so it cannot be silently
overwritten. Sim-side claims are verified in batched human Docker sessions with written gate
records (`docs/runbooks/`, `docs/archive/`).

## Reference

**`aerial-autonomy-stack`** (Feb 2026): autopilot-agnostic ROS 2 framework wiring Gazebo +
ArduPilot/PX4 + simulated camera (YOLOv8) + simulated LiDAR avoidance. Mined for setup time;
adapted, not adopted wholesale.
