# FieldGuard 🛸🌾

> Autonomous drone survey system in simulation: **live reactive obstacle avoidance** +
> **NDVI crop-health mapping**, on the ArduPilot + Gazebo + ROS 2 stack.

**Status:** early build (Week 0 — scaffolding complete). This README is owned by the
`gtm-narrative-lead` and is filled in as milestones land. See `CLAUDE.md` for the project summary
and `docs/SPEC.md` for the full spec.

## Why this is interesting
Commercial ag-drone platforms (DJI, DroneDeploy, Sentera/John Deere, Trimble) fly **pre-surveyed
static missions**. FieldGuard adds the thing they don't: **live reactive avoidance of unplanned
dynamic obstacles, with coverage-debt reconciliation** so no part of the field gets silently
skipped when the drone dodges. NDVI health mapping falls out of the same flight/camera pipeline.

## Headline metrics
_Filled in from the `eval/` harness as the build progresses (detection recall, false-negative rate,
avoidance success rate, coverage completeness, single-vs-second-sensor delta)._

## Architecture (short version)
```
Gazebo farm world  ─►  simulated NDVI camera ─►  perception (detect dynamic obstacle)
   (ardupilot_gazebo)          │                          │
ArduPilot SITL ◄─ MAVLink ◄─ flight software: boustrophedon coverage planner
                                   │  + reactive avoidance & coverage-debt replanning  (← the core)
                                   └─► NDVI health map (georeferenced, stitched)  ─►  light dashboard
```
Full detail: `docs/SPEC.md`. Design tradeoffs & rationale: `docs/DECISIONS.md`.

## Run it
_TBD — owned by `robotics-sim-engineer` + `devops-reliability-engineer`. Target: one command to
bring up the sim, one command to run the eval harness, reproducible from a clean clone._

## How this repo is built
Developed with a Claude Code **tiger team** — eight specialized subagents in `.claude/agents/`
(product, tech-lead, perception/ML, sim, flight-software, devops, QA/safety, GTM). See
[`TIGER_TEAM_GUIDE.md`](TIGER_TEAM_GUIDE.md).
