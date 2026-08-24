# SwathKeeper — System Spec

Autonomous drone survey system, built **entirely in simulation** (ADR-000): live reactive obstacle
avoidance + NDVI crop-health mapping on ArduPilot SITL + Gazebo Harmonic + ROS 2 Humble.
*(Originally written 2026-07-27 under the working title FieldGuard; rewritten 2026-08-18 as the
current-state spec. The original phased plan and resolved open questions moved to
`docs/BUILD_LOG.md` and `docs/DECISIONS.md` — this file describes the system, not the schedule.)*

## Priorities (confirmed, in order — do not reorder)

1. **Flight autonomy + reactive obstacle avoidance** — the differentiator. Commercial ag-drone
   platforms (DJI, DroneDeploy, Sentera/John Deere, Trimble) fly pre-surveyed static missions;
   live reactive avoidance of *unplanned* obstacles, with coverage integrity, is what they don't do.
2. **NDVI health mapping** — real and useful, powered by the same pipeline.
3. **Farmer-facing dashboard** — built last, kept light. It's the proof, not the point.

## The core guarantee

A survey is only valid if every cell was imaged — so a dodge that skips cells must never be
silent. Every canonical grid cell (2.5 m, 720 cells over the field polygon) terminates in exactly
one state: `covered` or `debt`. Absence from the ledger IS the bug, and the partition invariant
(`coverage.check_ledger`) makes it a test failure. A *commanded* position is never recorded as a
*flown* position (regression-pinned after the 2026-08-18 ledger-honesty bug). v1 ships
avoid-then-resume + honest debt (ADR-002); full debt reconciliation (requeue missed cells) is the
documented stretch goal.

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
   v1) is **planned as the Week-6 comparison arm — not built yet** — to measure what a second
   sensor buys against the ADR-009 monocular range estimate.
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
   resume, and debt cell is logged.
6. **Health mapping:** NDVI = (NIR − Red)/(NIR + Red) per frame (`ndvi_fusion.py`), recorded live to
   a spike-schema clip (`record_node.py` / `clip_recorder.py` — each frame pairs to the pose
   nearest its OWN Gazebo-clock stamp; arrival pairing smears a render burst across meters, ADR-007
   amendment, and out-of-bound frames are flagged `pose_pair_stale` and skipped rather than painted
   somewhere wrong), georeferenced from SITL telemetry (`ndvi_georef.py`, hand-fixture-tested incl.
   tilted poses), stitched **offline post-flight** (ADR-010, `scripts/stitch_ndvi.py`) into a
   per-cell heatmap on the SAME canonical grid as the coverage ledger — heatmap cell and ledger
   cell join by `cell_id`.
7. **Dashboard (last, light):** flight replay + avoidance event log + NDVI overlay, joined on the
   shared cell grid.

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
