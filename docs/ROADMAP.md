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
- **✅ WEEK 1-2 MILESTONE COMPLETE (2026-08-04): boustrophedon mission flies end-to-end, no obstacles.**
  Full ArduPilot + Gazebo + ROS 2 workspace builds from source (§3); SITL flies standalone (§4); the
  custom-plugin Gazebo world loads (§5); the iris flies in Gazebo via the SITL⟷Gazebo JSON backend
  (§6); firmware SHAs pinned in CLAUDE.md (§7); and a generated boustrophedon coverage mission flew
  **fully autonomously in AUTO — takeoff, 6-lane lawnmower sweep, RTL — confirmed from both MAVProxy
  (`Reached command #N`) and Gazebo model pose (holding 15 m, sweeping the field) (§8)**. Generator:
  `scripts/gen_boustrophedon.py`. All bringup fixes on branch `fix/week1-bringup` (`docs/WEEK1_BRINGUP.md`).
- **Next (Weeks 3-4 — the differentiator):** custom farm world (field polygon, tree rows, scripted
  birds); NDVI-vs-RGB detection spike; detector + **reactive avoidance + coverage-debt replanning loop**.
- **Deferred, non-blocking:** enable AP_DDS (`DDS_ENABLE=1`) for `/ap/*` ROS 2 topics (needed for the
  ROS 2 control path — perception/planner nodes — not for a MAVLink mission); bake the workspace build
  into the image (devops); merge the `fix/week1-bringup` PR.

### Earlier (kickoff)
- **Week:** 1 (planning done; execution is the human's to run). Both lanes scoped in parallel.
- **Lane 1 — sim bringup (`robotics-sim-engineer`):** ✅ toolchain pinned (ADR-004 ACCEPTED: Gazebo
  Harmonic + `ardupilot_gz` on ROS 2 Humble, Ubuntu 22.04 in Docker). Bringup checklist in
  `docs/WEEK1_BRINGUP.md`; starter container in `sim/docker/`. **Human next:** run the checklist to
  get a no-obstacle mission flying, then capture the exact ArduPilot firmware SHA into CLAUDE.md.
- **Lane 2 — detection spike (`perception-ml-engineer`):** ✅ scoped in `docs/SPIKE_ndvi_vs_rgb.md`
  (default NDVI-direct; FNR is the safety-critical metric; 3-day time-box). **Blocked on** a sim clip
  from Lane 1 (short fixed-seed flight rendered as NDVI + co-located RGB with pose logs).
- **CI:** ✅ starter GitHub Actions workflow validates the tiger-team config on every push; the real
  build/test/sim/eval pipeline is stubbed and ready to grow at Week 2+.
- **Blocking human steps:** (1) create the GitHub repo + push so CI runs; (2) install Docker Desktop
  and run `docs/WEEK1_BRINGUP.md`. Interface names off the AP_DDS bridge need locking by `tech-lead`
  once the bridge is up (topic/frame names have moved between versions — verify against the checkout).

## Explicit stretch goals (documented, NOT v1 blockers)
- Full coverage-debt reconciliation (v1 ships "avoid, return to next waypoint" first).
- Scaling from 2-3 birds to a flock / higher obstacle density.
- Second-sensor config promoted from comparison arm to a supported operating mode.

## Cut / deferred log
_(product-lead records anything cut here, with the date and the reason — this is interview material.)_
