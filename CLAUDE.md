# SwathKeeper — Project Context (CLAUDE.md)

This file loads into the main session and every custom subagent. Keep it current, concise, and
authoritative. Full detail lives in `docs/SPEC.md`; this is the always-loaded summary.

## What this is
**SwathKeeper** — an autonomous drone survey system built **entirely in simulation**: live reactive
obstacle avoidance + NDVI-based crop-health mapping, on the **ArduPilot + Gazebo + ROS 2** stack.
It is a **portfolio project** meant to be interview-defensible for robotics / autonomy / applied-ML
roles. The original ~7-8-week hard deadline was **dropped 2026-08-18** (quality over calendar), but
the standing scope guard survives it: nothing added without a cut. Convert relative dates to
absolute when recording them.

**Naming (ADR-011):** renamed from the working title FieldGuard on 2026-08-18. Docs and branding
say SwathKeeper; **code identifiers deliberately keep the old name** — `fieldguard_planning`,
`fg_`/`/fg/*` topics, `farmguard_field.sdf`, the `fieldguard-sim` image, `/workspace/fieldguard`
paths. Do NOT "helpfully" rename them; the `/fg/*` contract is live-verified (ADR-007 Gate 0).

## Confirmed priorities (do not reorder)
1. **Flight autonomy + reactive obstacle avoidance** — the differentiator and the depth. Commercial
   ag-drone platforms fly pre-surveyed static missions; live reactive avoidance is what sets this
   apart. **Most engineering time lives in the detect → avoid → replan → requeue-missed-cells loop.**
2. **NDVI health mapping** — real and useful, powered by the same pipeline. Second priority.
3. **Farmer-facing dashboard** — deferred, built last, kept light. It's the proof, not the point.

## Architecture (authoritative summary — see docs/SPEC.md §Architecture)
- **Sim**: Gazebo Harmonic (pinned, ADR-004) + `ardupilot_gazebo` + ROS 2. Custom farm world
  (`sim/worlds/farmguard_field.sdf`): bounded field polygon, tree rows (static obstacles), scripted
  bird actors (dynamic obstacles).
- **Sensing**: simulated NDVI camera (dual-band: Red + synthetic NIR). A second-sensor config
  (NDVI+depth or NDVI+RGB) runs in parallel as a **comparison arm** to quantify a second sensor's value.
- **Perception**: lightweight detector on NDVI frames + a **pre-known static-obstacle map** (trees
  geofenced from a pre-flight boundary survey — a legitimate real ag assumption). This separates
  "known static obstacle" from "genuinely unplanned dynamic obstacle" (the real hard problem).
- **Coverage planning**: boustrophedon (lawnmower) over the field polygon. Don't reinvent it.
- **Reactive avoidance + replanning (the core)**: on dynamic detection → local avoidance maneuver →
  reconcile against the coverage plan so **no cell is silently skipped**; track **coverage debt**,
  requeue missed cells.
- **Health mapping**: NDVI = (NIR − Red)/(NIR + Red) per frame, georeferenced from SITL telemetry
  (`ndvi_georef.py`), stitched **offline post-flight** (ADR-010, `scripts/stitch_ndvi.py`) onto the
  SAME canonical 2.5 m cell grid as the coverage ledger — heatmap and ledger join by `cell_id`.
- **Dashboard (last, light)**: flight replay, avoidance event log, NDVI overlay.

## Key decisions the spec has already made (don't relitigate without a DECISIONS.md entry)
- v1 replanning = **"avoid, return to next waypoint"** first; full coverage-debt reconciliation is a
  documented **stretch goal**, not a v1 blocker.
- MVP obstacle density = **2-3 scripted bird trajectories**, not a flock. Keep the loop debuggable.
- NDVI-vs-RGB detection = **DECIDED (ADR-003): NDVI-direct — CONFIRMED ON THE REAL RENDER
  (criterion 3 CLOSED, ADOPT, 2026-08-23, am. 7)**: per-bird-track FNR 0.000 on measured
  (applied-pose) labels, every bird detected before closest approach, precision 0.708 / recall
  0.850. The −0.61 real-render threshold stays PROVISIONAL (n=20); criterion 2's comparison arm
  still needs an independent RGB pixel study (birdness is INVERTED on this world).
- NDVI render mechanism = **ADR-007: RGB camera Red channel + Gazebo thermal sensor repurposed as
  synthetic NIR**, fused in a ROS 2 node. **All four gates GREEN live** (Gate 0 2026-08-05;
  Gates 1-3 2026-08-18: bridge, bands canopy 0.854 > soil 0.212 > bird 0.040, avoidance
  regression). Sensor mount corrected same day (was horizon-facing since authoring — Gazebo
  cameras look along +X; ADR-007 amendment 5) and geometry is now GATED:
  `scripts/verify_mount_geometry.sh` (2.2 px). First tree-verified real-render heatmaps committed.
  Recording throughput **SOLVED 2026-08-22 (ADR-013 am. 6-9)**: the Fast DDS SHM segment was the
  root cause (silent fragment discard); `config/dds/fg_fastdds.xml` + `--shm-size=1g` took
  delivery to 100 % both bands, painting cadence 0.41 → **5.0 Hz flat**, full 720/720 maps.
  Safety asterisk from the avoidance QA (am. 12): both historical avoidance flights breached
  bird clearance (CPA ~5 cm) under green gates — CPA is now a gated metric; control-law fixes
  R2/R3 await their live gate on the next avoidance flight.
- Real-detector contract = **ADR-009**: detections carry `stamp_s` (policy staleness gate); bird
  position from apparent-size ray, **never** ground-plane projection (fail-dangerous at altitude).
- Coverage-ledger honesty = commanded setpoints are **never** recorded as flown
  (regression-pinned after the 2026-08-18 audit found debt understated by up to 32 cells/scenario).

## Reference to read before building
**`aerial-autonomy-stack`** (Feb 2026): autopilot-agnostic ROS 2 framework wiring Gazebo +
ArduPilot/PX4 + a simulated camera through YOLOv8 + simulated LiDAR avoidance. Close to this use
case — mine it for setup time; adapt, don't adopt wholesale.

## Pinned versions (ADR-004, confirmed by robotics-sim-engineer 2026-07-27; owned by robotics-sim-engineer + devops)
Rationale: ArduPilot's own documented/CI-tested stack, corroborated by the `aerial-autonomy-stack` ref.
Run in Docker on Ubuntu 22.04 — this stack is not practically supported natively on macOS.
- **Base OS**: Ubuntu 22.04 (jammy), in Docker Desktop
- **ROS 2 distro**: Humble (Tier 1; EOL 2027-05)
- **Gazebo**: Harmonic — `GZ_VERSION=harmonic` (LTS; EOL 2028-09)
- **`ardupilot_gz`**: branch `main`
- **`ardupilot_gazebo`**: branch `ros2`  ← note: not `main`
- **`ros_gz`, `sdformat_urdf`, `micro-ROS-Agent`**: branch `humble`
- **`SITL_Models`**: branch `main`
- **ArduPilot firmware**: branch `master` (not a stable Copter tag) is intentional: the AP_DDS/ROS 2
  bridge surface tracks master, so a stable tag risks DDS topic mismatches.
- Setup + bringup checklist: `docs/runbooks/SIM_BRINGUP.md`. Container: `sim/docker/Dockerfile` +
  `scripts/sim_docker_build.sh` / `sim_docker_run.sh`.

### Pinned commit SHAs (captured 2026-08-04 — first green Gazebo flight; the real reproducibility anchor)
- `ardupilot`        `9895756d874ec9128d50918f6747a83706f4e221`  (V4.8.0-dev)
- `ardupilot_gazebo` `cc0290d964dfa373531963a8fc39093a0836af0a`
- `ardupilot_gz`     `8df4dc1726e37504e6fc8b952d02e554cfa3176f`
- `ros_gz`           `9d7f8c721c233a9ac8b43950129d51e67905523e`

## Repo layout
```
.claude/agents/     8 tiger-team subagents        docs/README.md      docs map: living/runbooks/history
.claude/commands/   /standup session opener       docs/SPEC.md        system spec (living)
src/                Python planning core           docs/ROADMAP.md     current truth + what's next
sim/                Gazebo worlds & models         docs/DECISIONS.md   ADR / tradeoff log
config/             field polygon, missions, birds docs/BUILD_LOG.md   chronological narrative
scripts/            bringup / run / stitch helpers docs/runbooks/      operational Docker-session docs
eval/               evaluation harness + metrics   docs/archive/       frozen historical records
tests/              regression + safety scenarios  TIGER_TEAM_GUIDE.md how to run the team
```

## The tiger team (see TIGER_TEAM_GUIDE.md)
Eight subagents in `.claude/agents/`: `product-lead`, `tech-lead`, `perception-ml-engineer`,
`robotics-sim-engineer`, `flight-software-engineer`, `devops-reliability-engineer`,
`qa-safety-reviewer`, `gtm-narrative-lead`. Start a work session with `/standup`.
**Escalation rule:** if two roles disagree, `product-lead` wins for v1 — and the disagreement is
recorded in `docs/DECISIONS.md` as a tradeoff (that log is interview material).

## Working conventions
- No "it works" without a metric or a reproducible scenario (perception-ml-engineer / qa-safety enforce).
- Every non-trivial architecture choice gets a one-line justification in `docs/DECISIONS.md`.
- Instrument the avoidance loop: log every detection, avoidance event, replan, and requeued cell.
- Keep sim runs reproducible (pinned versions, fixed seeds where possible) so eval numbers mean something.
