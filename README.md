# SwathKeeper 🛸🌾

> Autonomous drone survey system in simulation: **live reactive obstacle avoidance** +
> **NDVI crop-health mapping**, on the ArduPilot + Gazebo + ROS 2 stack. A *swath* is one pass of
> a coverage survey; SwathKeeper's thesis is **keeping the swath** — the survey stays provably
> complete even when the flight plan doesn't survive contact with the world.
> *(Renamed from the working title FieldGuard, 2026-08-18.)*

**Status (2026-08-18, end of a very long day):** Weeks 1-4 complete; Week 5's validation is
DONE — all four ADR-007 gates passed live on the pinned stack, and the day's real-render work
caught and fixed five deep bugs the value-gates couldn't see (poses mislabeled under render
bursts; a bridged sim-clock starving the image pipeline; a degraded long-lived render instance;
a fusion pairing queue too shallow for bursty delivery; and the sensor mount itself, which had
faced the horizon upside-down since authoring — Gazebo cameras look along +X). Each fix shipped
with the gate that makes its bug class impossible to repeat, ending with
`scripts/verify_mount_geometry.sh`: the camera's view now provably agrees with the georef
transform to 2.2 px. The first **tree-verified** heatmaps are committed evidence: everywhere the
recording looked, the 18 known trees appear at their true positions (+0.87 NDVI lift over soil).
Open: fused-frame recording throughput (limits per-flight coverage), then the ADR-003
real-render re-run and the dashboard. Docs map: [`docs/README.md`](docs/README.md).

## Why this is interesting
Commercial ag-drone platforms (DJI, DroneDeploy, Sentera/John Deere, Trimble) fly **pre-surveyed
static missions**. SwathKeeper adds the thing they don't: **live reactive avoidance of unplanned
dynamic obstacles, with coverage integrity** — every cell the dodge disturbs is either still covered
or explicitly logged as coverage *debt*, never silently skipped. NDVI health mapping falls out of the
same flight/camera pipeline. (Full coverage-debt *reconciliation* — requeue and re-fly every missed
cell — is a documented stretch goal, ADR-002; v1 ships "avoid, return to next waypoint" + honest debt.)

## Headline metrics (from the `eval/` harness)
- **Detection:** per-bird-track FNR **0.000** (every bird seen before closest approach) on the fixed-seed
  spike clip; the classical-CV blob baseline clears the safety bar, so no trained model is justified yet
  (ADR-003). _Caveat: the deciding clip is a **synthetic** stand-in; the real-render re-run is next
  (ground-truth tooling ready, waiting on a full-coverage recording)._
- **Avoidance loop:** demonstrated live — one clean AUTO→GUIDED→AUTO takeover/resume per encounter, the
  dodge setpoint 3D-vetted against the tree geofence, coverage-debt ledger honest by construction.
- **Coverage integrity:** the ledger partition invariant (`coverage.check_ledger`) makes a
  silently-skipped cell a **test failure**; 5 previously-pending safety assertions (coverage-integrity +
  avoid-into-tree, across 4 scenarios) now pass against real flight logs the loop produced. When a
  2026-08-18 audit found the ledger itself understating debt (commanded dodge setpoints recorded as
  flown — up to 32 cells falsely COVERED per scenario), the fix + regression test + honestly-regenerated
  logs shipped the same day; the decision log records it. **The honesty is the product.**
- **Automated tests:** 248 (`tests/fieldguard_planning`, via `python3 -m unittest discover -s
  tests/fieldguard_planning` or `pytest tests/`), green in CI, which also gates on: the seed-42
  per-bird-track-FNR regression, scenario-log drift (regenerate + byte-diff), and committed
  flight-log evidence validity. The avoidance/coverage/geofence core is stdlib-only; the NDVI
  fusion/georef/stitch tests use numpy (pinned in `requirements-eval.txt`) — a scoped, documented
  exception, not a project-wide dependency change.

## Architecture (short version)
```
Gazebo farm world  ─►  NDVI camera (RGB Red + thermal-as-NIR, ADR-007) ─►  perception: detect
   (ardupilot_gazebo)          │                          │  dynamic obstacle (blob, ADR-003/009)
ArduPilot SITL  ◄── AP_DDS ──  ROS 2 avoidance node:  policy (when/where to dodge, 3D-safe)
   /ap/mode_switch, /ap/cmd_gps_pose          │      + executor (take over, resume, book coverage-debt)
                                              └─►  recorded flight ─► offline georeferenced stitch
                                                   (scripts/stitch_ndvi.py, ADR-010) ─► NDVI heatmap
                                                   on the SAME cell grid as the coverage ledger
                                                   ─► light dashboard (Week 7)
```
The boustrophedon coverage mission flies over MAVLink; the reactive avoidance loop commands ArduPilot
over the **AP_DDS `/ap/*` bridge** (ADR-005/006). Full detail: `docs/SPEC.md`. Design tradeoffs &
rationale: `docs/DECISIONS.md`.

## Run it
Runs in Docker (the stack isn't practically supported natively on macOS, ADR-004).
1. **Bring up the sim** — `docs/runbooks/SIM_BRINGUP.md` (build the image, then Gazebo → micro-ROS agent →
   SITL, *in that order* — the agent must be listening before SITL's DDS client starts).
2. **Reproduce the live avoidance demo** — `docs/runbooks/AVOIDANCE_DEMO.md` (runs the loop against a
   scripted bird; writes a flight log to `eval/results/live_flight_log_<UTCstamp>.json`).
3. **Stitch a heatmap (no Docker needed)** — generate the synthetic clip, then stitch:
   `python3 sim/spike/gen_spike_clip.py --seed 42 --out /tmp/clip && python3 scripts/stitch_ndvi.py
   --clip /tmp/clip` → `heatmap.json` + false-color `heatmap.png` on the canonical coverage grid.
   The real-render clip from the batched validation session feeds the same runner.
4. **Run the tests / eval harness (no Docker needed)** —
   `python3 -m unittest discover -s tests/fieldguard_planning` and `bash eval/run_spike.sh` (needs the
   pinned deps in `requirements-eval.txt`). Both run in CI (`.github/workflows/ci.yml`).

## How this repo is built
Developed with a Claude Code **tiger team** — eight specialized subagents in `.claude/agents/`
(product, tech-lead, perception/ML, sim, flight-software, devops, QA/safety, GTM). See
[`TIGER_TEAM_GUIDE.md`](TIGER_TEAM_GUIDE.md). Start a work session with `/standup`.
