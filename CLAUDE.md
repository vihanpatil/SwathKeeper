# SwathKeeper — Project Context (CLAUDE.md)

This file loads into the main session and every custom subagent. Keep it current, concise, and
authoritative. Full detail lives in `docs/SPEC.md`; this is the always-loaded summary.

## What this is
**SwathKeeper** — an autonomous drone survey system built **entirely in simulation**: live reactive
obstacle avoidance + NDVI mapping, on the **ArduPilot + Gazebo + ROS 2** stack.
It is a **portfolio project** meant to be interview-defensible for robotics / autonomy / applied-ML
roles. The original ~7-8-week hard deadline was **dropped 2026-08-18** (quality over calendar), but
the standing scope guard survives it: nothing added without a cut. Convert relative dates to
absolute when recording them.

**DIRECTION RESET 2026-09-10 (ADR-022, on an end-to-end audit) — this is the current program:**
**(1) portfolio floor first** (reconcile the state docs, delete debris, widen the honesty artifacts,
LICENSE + Pages + video); **(2) then a market test of the METHOD** — ~10 conversations with
ArduPilot/PX4 teams about running pre-registered evidence gates on *their* logs, zero code, kill
criterion **0 of 10 → strong portfolio, no product**; **(3) drone-as-product is DEFERRED** behind
that answer (closing the control loop in sim, ≥20 seeded headless encounters clearing 3.00 m),
hardware behind that. **The ADR-019 wire program is CUT** (am. 1). **NDVI is FROZEN** (ADR-019 §7).
**Claims ceiling everywhere: "sim-demonstrated, evidence-gated."**

**Naming (ADR-011):** renamed from FieldGuard on 2026-08-18; **code identifiers deliberately keep
the old name** — `fieldguard_planning`, `fg_`/`/fg/*`, `farmguard_field.sdf`, the `fieldguard-sim`
image, `/workspace/fieldguard`. Do NOT rename them; `/fg/*` is live-verified (ADR-007 Gate 0).

## Confirmed priorities (do not reorder)
1. **Flight autonomy + reactive obstacle avoidance** — the differentiator, and the least proven
   thing here: three live flights, **three** bird-clearance breaches (see the safety asterisk).
   **Most engineering time lives in the detect → avoid → resume → honest-debt loop.**
2. **NDVI health mapping** — works end to end (720/720 cells, 5.0 Hz) and is **FROZEN** since
   2026-08-26: it is the working demo, not open work. The world authors no health variation.
3. **Farmer-facing dashboard** — **BUILT 2026-08-26** (ADR-018), static and light. The proof, not
   the point.

## Architecture (authoritative summary — see docs/SPEC.md §Architecture)
- **Sim**: Gazebo Harmonic (pinned, ADR-004) + `ardupilot_gazebo` + ROS 2. Custom farm world
  (`sim/worlds/farmguard_field.sdf`, byte-reproducible from config): field polygon, 18 static trees,
  3 birds teleported by `drive_birds.py` (no collision geometry — they cannot hit anything).
- **Sensing**: simulated NDVI camera (dual-band: Red + synthetic NIR), nadir. The NDVI+RGB
  comparison arm was **RETIRED 2026-08-26** (the RGB R channel *is* the Red band). A **forward
  `depth_camera`** (ADR-020/021) is commissioned + scored and has **NEVER FLOWN**.
- **Perception**: lightweight detector on NDVI frames + a **pre-known static-obstacle map** (trees
  geofenced from a pre-flight boundary survey — a legitimate real ag assumption). This separates
  "known static obstacle" from "genuinely unplanned dynamic obstacle" (the real hard problem).
- **Coverage planning**: boustrophedon (lawnmower) over the field polygon. Don't reinvent it.
- **Reactive avoidance (the core)**: on dynamic detection → local avoidance maneuver → reconcile
  against the coverage plan so **no cell is silently skipped**; track **coverage debt**. Measured:
  there is **no replan and no requeue in the code** (ADR-002 scoped them out), and the command path
  is **open-loop** — `send_setpoint_enu` publishes and returns, `verdict="accepted"` is a constant,
  and no live gate compares commanded to achieved displacement.
- **Health mapping**: NDVI = (NIR − Red)/(NIR + Red) per frame, georeferenced (`ndvi_georef.py`),
  stitched **offline post-flight** (ADR-010) onto the SAME canonical 2.5 m grid as the ledger (join
  by `cell_id`). The world authors 4 temperatures: a canopy-vs-soil sign test, not a health gradient.
- **Dashboard (built, ADR-018)**: flight replay, avoidance event log, NDVI overlay.

## Key decisions the spec has already made (don't relitigate without a DECISIONS.md entry)
- v1 replanning = **"avoid, return to next waypoint"**; debt reconciliation is a **stretch goal**.
- MVP obstacle density = **2-3 scripted bird trajectories**, not a flock. Keep the loop debuggable.
- NDVI-vs-RGB detection = **DECIDED (ADR-003): NDVI-direct — CONFIRMED ON THE REAL RENDER
  (criterion 3 CLOSED, ADOPT, 2026-08-23, am. 7)**: per-bird-track FNR 0.000 on measured
  (applied-pose) labels, every bird detected before closest approach, precision 0.708 / recall
  0.850. The −0.61 real-render threshold stays PROVISIONAL (n=20). **Criterion 2 CLOSED 2026-08-26
  — RETIRE-ARM:** the RGB pixel study ran and measured that the RGB R channel *is* the NDVI Red
  band bit-for-bit, so the arm never was a second sensor; its budget moved to the forward sensor.
- NDVI render mechanism = **ADR-007: RGB camera Red channel + Gazebo thermal sensor repurposed as
  synthetic NIR**, fused in a ROS 2 node. **All four gates GREEN live** (Gate 0 2026-08-05;
  Gates 1-3 2026-08-18). Mount geometry is GATED (`scripts/verify_mount_geometry.sh`, 2.2 px) after
  it flew horizon-facing under four green value gates. Throughput **SOLVED 2026-08-22** (ADR-013
  am. 6-9: the Fast DDS SHM segment discarded fragments silently; `config/dds/fg_fastdds.xml` +
  `--shm-size=1g` → 100 % delivery, **5.0 Hz flat**, 720/720 maps).
- **SAFETY ASTERISK — say this before any avoidance claim.** Three live avoidance flights, **three**
  bird-clearance breaches against a 3.00 m bar: gate-recomputed CPA **0.0393 / 0.0391 / 0.0067 m**.
  The two 2026-08 `--demo` takes are ACKNOWLEDGED (exit 0); the 2026-08-25 real-detection take is
  **INVALID, exit 1, and it stands** — which is why `main`'s CI carries **one declared red**
  (`tests/test_ci_evidence_gate.py`'s committed-evidence step). R2 passed live 2026-08-25 (min swept
  clearance 1.340 m, 8 candidate rejections); **R3 shipped and has never fired live** (missed by
  15 mm). Birds have no `<collision>` geometry and are teleported, so the offline gate is the
  entire safety system.
- **Forward depth camera (ADR-020/021): built, commissioned, scored 7/7 — NEVER FLOWN.** Booked to
  46.0 m at 5.0 m/s on parked, noiseless renders; no committed log carries a `depth_blob` detection.
- Real-detector contract = **ADR-009**: detections carry `stamp_s` (policy staleness gate); bird
  position from apparent-size ray, **never** ground-plane projection (fail-dangerous at altitude).
- Coverage-ledger honesty = commanded setpoints are **never** recorded as flown (regression-pinned
  after the 2026-08-18 audit found debt understated by up to 32 cells/scenario).

## Reference to read before building
**`aerial-autonomy-stack`** (Feb 2026): autopilot-agnostic ROS 2 framework wiring Gazebo +
ArduPilot/PX4 + a simulated camera (YOLOv8) + simulated LiDAR avoidance. Mine it for setup time;
adapt, don't adopt wholesale.

## Pinned versions (ADR-004; owned by robotics-sim-engineer + devops)
ArduPilot's own documented/CI-tested stack; Docker on Ubuntu 22.04 (not supported natively on macOS).
**The flying image is NOT SHA-pinned** (`sim/docker/Dockerfile` has none) — a document, not an artifact.
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
.claude/agents/     9 tiger-team subagents        docs/README.md      docs map: living/runbooks/history
.claude/commands/   /standup session opener       docs/SPEC.md        system spec (living)
src/                Python planning core           docs/ROADMAP.md     current truth + what's next
sim/                Gazebo worlds & models         docs/DECISIONS.md   ADR / tradeoff log
config/             field polygon, missions, birds docs/BUILD_LOG.md   chronological narrative
scripts/            bringup / run / stitch helpers docs/runbooks/      operational Docker-session docs
eval/               evaluation harness + metrics   docs/archive/       frozen historical records
tests/              regression + safety scenarios  TIGER_TEAM_GUIDE.md how to run the team
```

## The tiger team (see TIGER_TEAM_GUIDE.md)
Nine subagents in `.claude/agents/`: `product-lead`, `tech-lead`, `perception-ml-engineer`,
`robotics-sim-engineer`, `flight-software-engineer`, `devops-reliability-engineer`,
`qa-safety-reviewer`, `gtm-narrative-lead`, `exec-council`. Start a work session with `/standup`.
**Escalation rule:** if two roles disagree, `product-lead` wins for v1 — and the disagreement is
recorded in `docs/DECISIONS.md` as a tradeoff (that log is interview material).

## Working conventions
- No "it works" without a metric or a reproducible scenario (perception-ml-engineer / qa-safety enforce).
- Every non-trivial architecture choice gets a one-line justification in `docs/DECISIONS.md`.
- Instrument the avoidance loop: log every detection, takeover, maneuver, resume and debt cell.
- Keep sim runs reproducible (pinned versions, fixed seeds where possible) so eval numbers mean something.
- **Standing freezes (ADR-022):** the **NDVI pipeline** is frozen (ADR-019 §7) and the **depth
  segmenter** is frozen until a depth flight exists — no more bars, no more design notes.
- **`docs/DECISIONS.md` amendments are ≤ 10 lines, and no new ADR ships without a cut.**
- **tests:src is capped at 3.70:1** (measured 2026-09-10 after the floor round: `src/fieldguard_planning/*.py`
  6,771 lines vs `tests/**.{py,sh}` 25,049 — the round itself took it from 3.45; ADR-022 am. 1):
  every new test file retires one until it falls.
