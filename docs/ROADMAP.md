# FieldGuard — Roadmap (living document)

Owner: `product-lead`. Update at each `/standup`. Target: done in ~7-8 weeks, before the Europe trip.
The `product-lead` re-cuts scope rather than moving the deadline. Full detail: `docs/SPEC.md`.

| Weeks | Goal | Primary roles | Exit criteria |
|---|---|---|---|
| **1-2** | Gazebo + ArduPilot SITL running; custom farm world; basic boustrophedon mission flies end-to-end, **no obstacles yet**. Run the NDVI-vs-RGB detection spike. | `robotics-sim-engineer`, `flight-software-engineer`, `perception-ml-engineer` | A mission flies the full field in sim; detection-approach decision recorded in DECISIONS.md with the metric that decided it. |
| **3-4** | Static tree obstacles (geofence) + scripted dynamic bird obstacles; detector + reactive avoidance + coverage-debt replanning loop. **The core.** | `perception-ml-engineer`, `flight-software-engineer`, `qa-safety-reviewer` | Drone detects a bird, avoids, returns to next waypoint; avoidance events + requeued cells logged; QA has scenarios that can't silently skip a cell. |
| **5-6** | NDVI rendering pipeline; per-frame vegetation index; georeferenced stitching into a health map. Second-sensor comparison arm quantified. | `robotics-sim-engineer`, `perception-ml-engineer`, `flight-software-engineer` | A georeferenced NDVI heatmap for a full flight; comparison-arm numbers (what a 2nd sensor buys) written up. |
| **7** | Dashboard, demo video, README, resume bullets. | `gtm-narrative-lead`, `flight-software-engineer`, `devops-reliability-engineer` | Light dashboard (replay + avoidance log + NDVI overlay); recorded 60-90s demo; README readable in 90s; metric-backed resume bullets. |
| **8** | Buffer / polish. | all | Green CI from clean clone; tagged demo-ready commit; safety sign-off from `qa-safety-reviewer`. |

## Current status
- **Week:** 0 (setup complete — tiger team scaffolded, repo initialized).
- **Next action:** run `/standup`, then have `robotics-sim-engineer` pin versions and stand up the
  Gazebo + ArduPilot SITL bringup; in parallel `perception-ml-engineer` scopes the Week 1-2 spike.

## Explicit stretch goals (documented, NOT v1 blockers)
- Full coverage-debt reconciliation (v1 ships "avoid, return to next waypoint" first).
- Scaling from 2-3 birds to a flock / higher obstacle density.
- Second-sensor config promoted from comparison arm to a supported operating mode.

## Cut / deferred log
_(product-lead records anything cut here, with the date and the reason — this is interview material.)_
