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
**Re-sequenced 2026-11-05 (ADR-022 am. 4): the owner ruled C — build the method as a tool, then ten public posts of it;
step 2 was BUILT and SCORED 2026-11-05 (ADR-023: `src/swathkeeper_gates/`, three public logs, PX4 cut); step 5 BUILT the same day
(ADR-023 am. 1: the composite Action `.github/actions/swathkeeper-gates/`, the README badge, and CI job `gates-tool` on py3.10 + py3.12
re-fetching the three logs by sha256 and diffing every committed verdict). Next: step 6, the ten posts; G257 is flagged, undecided.**
**Claims ceiling everywhere: "sim-demonstrated, evidence-gated."**

**Naming (ADR-011):** renamed from FieldGuard on 2026-08-18; **code identifiers deliberately keep
the old name** — `fieldguard_planning`, `fg_`/`/fg/*`, `farmguard_field.sdf`, the `fieldguard-sim`
image, `/workspace/fieldguard`. Do NOT rename them; `/fg/*` is live-verified (ADR-007 Gate 0).

## Confirmed priorities (do not reorder)
1. **Flight autonomy + reactive obstacle avoidance** — the differentiator, and the least proven
   thing here: three live flights, **three** bird-clearance breaches (see the safety asterisk).
   **Most engineering time lives in the detect → avoid → resume → honest-debt loop.** **2026-11-10: the owner
   reopened this loop (ADR-022 am. 5); four scripted depth-camera encounters flew in one day under ADR-013 am. 20,
   gt_cpa 0.021 → 0.839 → 0.039 m on the lane-patrol bird (its last strikes had zero detections: a lane-end U-turn and an astern overtake, outside a forward camera's view), then **9.568 m on the owner's head-on scenario** (ADR-013 am. 21), then **20 of 20 head-on encounters cleared 3.00 m** (min 5.42 / median 9.52 / max 9.82 m; `docs/encounters/BATCH_20261110T194048Z.md`) — unbooked EXPERIMENTS, not evidence. **2026-11-11: the first VALID avoidance take** — booked at 5.0 m/s on the 2026-09-07 artifact, head-on, gt_cpa_m 9.6138 m (7.9898 m gated), every depth bar measured, VALID under the flight-log gate and committed as evidence (`eval/results/live_flight_log_20261111T202709Z.json`, ADR-020 am. 8) — the third of three attempts with gate rules changed between them; the booking's own preconditions were OPEN at flight time and were closed on 2026-11-12 (the am. 5 tall-obstacle re-score run and PASSED, ADR-021 am. 2; §0b ruled REPORTED, ADR-020 am. 9). ONE take; the asterisk below still comes first.**
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
  `depth_camera`** (ADR-020/021) is commissioned + scored and **has flown against a bird since 2026-11-10** (24 head-on
  encounters; the 2026-11-11 booked take 3 is committed VALID under the flight-log gate, ADR-020 am. 8; the 2026-09-11 wiring
  flight was no-target and INVALID on its runtime max bar).
- **Perception**: lightweight detector on NDVI frames + a **pre-known static-obstacle map** (trees
  geofenced from a pre-flight boundary survey — a legitimate real ag assumption). This separates
  "known static obstacle" from "genuinely unplanned dynamic obstacle" (the real hard problem).
- **Coverage planning**: boustrophedon (lawnmower) over the field polygon. Don't reinvent it.
- **Reactive avoidance (the core)**: on dynamic detection → local avoidance maneuver → reconcile
  against the coverage plan so **no cell is silently skipped**; track **coverage debt**. Still **no replan
  and no requeue in the code** (ADR-002). **Measured 2026-11-10 (ADR-013 am. 20):** the GUIDED command path WORKS
  (`scripts/probe_actuation.py`: 3 m lateral in ≈2.2–2.5 s sim from hover), the executor flies a latched dodge to
  completion (`DODGE_ARRIVAL_RADIUS_M`, one commitment per encounter), R4 sidesteps an on-track bird, the depth
  source triggers at 45 m, and **one command flies + scores an encounter**:
  `scripts/fly_pipeline.sh encounter --detection-source depth --speed 5.0` (≈5 min; artifacts in
  `eval/results/encounters/<UTC>/`, gitignored). `verdict="accepted"` is still a constant (no mode readback).
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
  entire safety system. **Since 2026-11-11 there is also ONE booked clearance VALID under the flight-log gate — 9.6138 m
  (7.99 m gated), head-on, forward depth camera, every depth bar measured; its am. 5 booking precondition measured and closed 2026-11-12 (ADR-021 am. 2), §0b ruled REPORTED the same day (ADR-020 am. 9). Say
  both: three breaches on the nadir-era flights, one gate-VALID clearance on the forward camera; not a batch, not a product.**
- **Forward depth camera (ADR-020/021): built, commissioned, scored 7/7 — and FLOWN AGAINST A BIRD since 2026-11-10** (the
  2026-09-11 wiring flight was no-target, INVALID on its 141.16 ms runtime max): over the 24 head-on encounters since (the pilot,
  the 20-run batch, the 3 booked takes) it acquired the 0.18 m bird at 39.8–45.2 m on 23 and 32.2 m on one. The committed
  2026-11-11 take 3: 18 depth frames (29 consumption events), frame-joined range error p95 0.1687 m over the 7 frames the truth
  places unambiguously, detect rate 99.64 %, runtime p95 10.701 / max 20.702 ms. D5/D6 at a 5.0 m/s CRUISE remain UNMEASURED
  (encounter windows run at ~2.9 m/s because the dodge brakes). Booked to 46.0 m at 5.0 m/s on parked renders — clutter robustness
  demonstrated to 46 m against a smooth 18 m box face since the 2026-11-12 am. 5 re-score (ADR-021 am. 2; foliage with self-depth
  structure untested), in-flight acquisition sits below 46.0, and **the am. 5 re-score that gates any depth-camera booking PASSED on
  the shipped constants — all seven bars, nine FNR_zero stations structure-backed at 34–46 m**.
- Real-detector contract = **ADR-009**: detections carry `stamp_s` (policy staleness gate); bird
  position from apparent-size ray, **never** ground-plane projection (fail-dangerous at altitude).
- Coverage-ledger honesty = commanded setpoints are **never** recorded as flown (regression-pinned
  after the 2026-08-18 audit found debt understated by up to 32 cells/scenario).

## Reference to read before building
**`aerial-autonomy-stack`** (Feb 2026): autopilot-agnostic ROS 2 framework wiring Gazebo +
ArduPilot/PX4 + a simulated camera (YOLOv8) + simulated LiDAR avoidance. Mine it for setup time;
adapt, don't adopt wholesale.

## Pinned versions (ADR-004; owned by platform-engineer)
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
.claude/agents/     5 team subagents              docs/README.md      docs map: living/runbooks/history
.claude/skills/     5 skills (TIGER_TEAM_GUIDE §1) docs/SPEC.md        system spec (living)
src/                Python planning core           docs/ROADMAP.md     current truth + what's next
src/swathkeeper_gates/ the evidence-gate tool (ADR-023; pip package `swathkeeper-gates`, never imported by the core)
examples/           the tool's 3 scored public logs: SOURCE.json (url+sha256), bars, prereg sidecar, verdict.json
sim/                Gazebo worlds & models         docs/DECISIONS.md   ADR / tradeoff log
config/             field polygon, missions, birds docs/BUILD_LOG.md   chronological narrative
scripts/            bringup / run / stitch helpers docs/runbooks/      operational Docker-session docs
eval/               evaluation harness + metrics   docs/archive/       frozen historical records
tests/              regression + safety scenarios  TIGER_TEAM_GUIDE.md how to run the team
```

## The tiger team (see TIGER_TEAM_GUIDE.md)
Five subagents (`.claude/agents/`): `lead`, `software-engineer`, `platform-engineer`,
`qa-safety-reviewer`, `narrative-lead`, all preloading the `evidence-discipline` skill. Open with
`/standup`; run `/gates` before any claim. **Escalation:** `lead` wins build-level calls (logged in
`docs/DECISIONS.md`); critical calls go to the user.

## Working conventions
- No "it works" without a metric or a reproducible scenario (software-engineer / qa-safety enforce).
- Every non-trivial architecture choice gets a one-line justification in `docs/DECISIONS.md`.
- Host Python: `.venv/bin/python` (uv, 3.12); `/usr/bin/python3` runs but is 3.9.6 (measured 2026-11-09), below the gates
  tool's 3.10 floor. Tests need `.venv/bin` first on PATH.
- Instrument the avoidance loop: log every detection, takeover, maneuver, resume and debt cell.
- Keep sim runs reproducible (pinned versions, fixed seeds where possible) so eval numbers mean something.
- **Standing freezes (ADR-022):** the **NDVI pipeline** is frozen (ADR-019 §7) and the **depth
  segmenter** is frozen until a depth flight exists — no more bars, no more design notes.
- **`docs/DECISIONS.md` amendments are ≤ 10 lines, and no new ADR ships without a cut.**
- **tests:src is capped at 3.70:1** (ADR-022 am. 1; baseline 2026-09-10: `src/fieldguard_planning/*.py`
  6,771 vs `tests/**.{py,sh}` 25,049; the src side is `src/**/*.py` since ADR-022 am. 4, 2026-11-05).
  **UNDER since 2026-11-05: 3.42** (27,929 / 8,173 after step 5 + its three QA rounds; 3.33 after step 2), **by dilution, not by retiring a test** — the new
  `src/swathkeeper_gates/` joined the src side (ADR-023); over `src/fieldguard_planning/*.py` alone it is
  27,189 / 6,854 = **3.97** (it was OVER at 3.84 from 2026-09-11). Every new test file still retires one while the
  ratio is over the cap; the cap is not re-baselined.
