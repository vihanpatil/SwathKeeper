# FieldGuard — Project Spec (working title, rename freely)

Autonomous drone survey system: reactive obstacle avoidance + NDVI-based crop health
mapping, built in simulation on the ArduPilot stack.

---

## Priorities (confirmed)

1. **Flight autonomy + reactive obstacle avoidance** — primary engineering depth. This is
   the software-skill differentiator; nobody in the commercial ag-drone space
   (DJI, DroneDeploy, Sentera/John Deere, Trimble) does live reactive avoidance —
   they fly pre-surveyed static missions.
2. **NDVI-based health mapping** — real, useful, powered by the same flight/camera
   pipeline. Not the headline, but not an afterthought either.
3. **Farmer-facing dashboard** — deferred. Build last, keep it light. It's an easy add-on
   once the pipeline produces real data to display.

## Sensor strategy

- **Real hardware today:** single NDVI camera. Hardware team temporarily unavailable to
  add sensors.
- **Simulation approach:** don't let the hardware constraint limit the sim. Build the
  primary pipeline around the single-NDVI-camera configuration (matches reality), but
  also simulate a second-sensor configuration (NDVI + depth, or NDVI + RGB) as a
  comparison arm. This quantifies what a second sensor would actually buy you —
  genuinely useful output for the hardware engineer when they're back, not just an
  academic exercise.
- **Open technical question, solve early (Weeks 1–2):** NDVI cameras capture red + NIR,
  not RGB. Off-the-shelf detectors (YOLO, etc.) assume RGB. Two paths:
  - (a) Build detection directly on NDVI-rendered frames — vegetation-index contrast
    becomes the detection signal (low-vegetation anomalies = birds/objects against
    high-vegetation canopy). Matches real hardware. Recommended starting point.
  - (b) Render a separate synthetic RGB pass in sim purely for perception, keep NDVI
    for health only. Easier to prototype, less faithful to the real constraint.
  - Decide after a short Week 1–2 spike, not before — don't over-plan this one.

## Architecture

1. **Simulation environment:** Gazebo Harmonic (pinned, ADR-004) + `ardupilot_gazebo` plugin +
   ROS 2. Custom "farm world": bounded field polygon, rows of trees as static obstacles,
   scripted bird actors as dynamic obstacles (Gazebo actor plugins).
2. **Sensing:** simulated NDVI camera (dual-band render: red + synthetic NIR pass).
   Second sensor configuration simulated in parallel for comparison (see above).
3. **Perception:** lightweight object/anomaly detector on NDVI-rendered frames, plus a
   pre-known static-obstacle map. Trees are geofenced from a pre-flight boundary survey
   — a legitimate real-world assumption (ag operators map field boundaries in advance
   anyway) that also cleanly separates "known static obstacle" from "genuinely
   unplanned dynamic obstacle," which is the actual hard problem.
4. **Coverage planning:** boustrophedon (lawnmower) path generator over the field
   polygon — standard, well-understood, don't reinvent it.
5. **Reactive avoidance + replanning:** on dynamic-obstacle detection, trigger a local
   avoidance maneuver, then reconcile against the coverage plan so no field cells get
   silently skipped. Track "coverage debt" and requeue missed cells. This loop is the
   core of the whole project — most of your engineering time should live here.
6. **Health mapping:** NDVI = (NIR − Red) / (NIR + Red), computed per frame,
   georeferenced from SITL telemetry (pose/GPS), stitched post-flight into a simple
   heatmap grid.
7. **Dashboard (last):** flight path replay, avoidance event log, NDVI heatmap overlay.
   Simple. It's the proof, not the point.

**Reference implementation worth reading before you start:** a Feb 2026 paper released
an autopilot-agnostic ROS2 framework ("aerial-autonomy-stack") that already wires
together Gazebo, ArduPilot/PX4, a simulated camera through YOLOv8, and simulated LiDAR
for obstacle avoidance — close enough to your use case to save you real setup time.

## Phased plan (~7–8 weeks, targeting done before your Europe trip)

| Weeks | Goal |
|---|---|
| 1–2 | Gazebo + ArduPilot SITL running; custom farm world; basic boustrophedon mission flying end-to-end, no obstacles yet. Spike the NDVI-vs-RGB detection question here. |
| 3–4 | Static tree obstacles (geofence) + scripted dynamic bird obstacles; detector + reactive avoidance + coverage-debt replanning loop. |
| 5–6 | NDVI rendering pipeline; per-frame vegetation index; georeferenced stitching into a health map. |
| 7 | Dashboard, demo video, README, resume bullets (this is where the GTM/Narrative Lead role from the playbook earns its keep). |
| 8 | Buffer / polish. |

## Open questions to pin down as you build (not before)

_All three are now RESOLVED (2026-08-05) — kept here as the original framing; see `docs/DECISIONS.md`
and `docs/ROADMAP.md` for outcomes._

- **Obstacle density for the MVP demo:** start with 2–3 scripted bird trajectories, not
  a flock. Keep the avoidance loop debuggable before you scale complexity. — **Resolved:** the farm
  world ships 3 scripted bird actors; the live demo uses a single scripted bird (MVP scope).
- **Replanning sophistication for v1:** ship "avoid, return to next waypoint" first.
  Document full coverage-debt reconciliation as an explicit stretch goal — good
  interview material either way, and you don't want to block v1 on it. — **Resolved (ADR-002):** v1
  ships avoid-then-resume + honest coverage-debt tracking; full reconciliation is the stretch goal.
- **NDVI-only detection viability:** decide after the Week 1–2 spike whether the
  vegetation-index signal alone is enough for reliable dynamic-obstacle detection, or
  whether a synthetic RGB pass earns its complexity. — **Resolved (ADR-003):** NDVI-direct — the blob
  baseline hit per-bird-track FNR 0.000 on the spike; re-confirm on the real render in Weeks 5–6.
