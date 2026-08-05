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
- **✅ WEEK 1-2 GATE CLOSED (2026-08-04): both exit criteria met.**
  Criterion 1 (a mission flies the full field in sim) ✅; criterion 2 (detection-approach decision
  recorded in DECISIONS.md with the metric that decided it) ✅ — **ADR-003 now ACCEPTED
  (confirmation-pending): adopt NDVI-direct detection**, decided on FNR (per-bird-track FNR 0.000, blob
  baseline clears the safety bar, no trained model justified yet). One open follow-up rides on it:
  re-confirm ADR-003 on the real Gazebo NDVI render (the deciding clip was a synthetic stand-in).
  _(Corrected 2026-08-04: an earlier revision prematurely marked the milestone "COMPLETE" on the
  strength of the flight alone, before the detection decision existed.)_
  - **Criterion 1 ✅ — boustrophedon mission flies end-to-end, no obstacles.** Full ArduPilot + Gazebo +
    ROS 2 workspace builds from source (§3); SITL flies standalone (§4); the custom-plugin Gazebo world
    loads (§5); the iris flies in Gazebo via the SITL⟷Gazebo JSON backend (§6); firmware SHAs pinned in
    CLAUDE.md (§7); and a generated boustrophedon coverage mission flew **fully autonomously in AUTO —
    takeoff, 6-lane lawnmower sweep, RTL — confirmed from both MAVProxy (`Reached command #N`) and Gazebo
    model pose (holding 15 m, sweeping the field) (§8)**. Generator: `scripts/gen_boustrophedon.py`. All
    bringup fixes on branch `fix/week1-bringup` (`docs/WEEK1_BRINGUP.md`).
  - **Criterion 2 ❌ — detection decision outstanding.** Spike scoped in `docs/SPIKE_ndvi_vs_rgb.md`;
    was blocked on a sim clip from Lane 1, which is now done → **unblocked.** This is Week 2 goal A→B.

## Week 2 goals (2026-08-04 — set at standup; product-lead owns)
**Session goal:** close the one unmet Week 1-2 exit criterion (metric-backed ADR-003) and stand up the
obstacle-populated farm world, so the Weeks 3-4 avoidance core starts on day one with nothing behind it.
**Failure condition:** end Week 2 with a green mission but ADR-003 still PROPOSED — the differentiator slips.

| # | Workstream | Lead | Support | Exit criterion |
|---|---|---|---|---|
| A | ✅ Render the spike clip (fixed-seed flight → NDVI + co-located RGB + pose log) | `robotics-sim-engineer` | `perception-ml-engineer` | **DONE** — synthetic stand-in clip `sim/spike/gen_spike_clip.py` (seed 42), schema is a drop-in for the future Gazebo render; formats match |
| B | ✅ Close the detection decision (run `docs/SPIKE_ndvi_vs_rgb.md`; FNR is the safety metric) | `perception-ml-engineer` | `tech-lead` | **DONE** — ADR-003 ACCEPTED (confirmation-pending): adopt (a) NDVI-direct; per-bird-track FNR 0.000 for both arms, blob baseline clears the bar → no trained model justified. Permanent `eval/` harness born. Must re-confirm on real Gazebo render. |
| C | ✅ Build the farm world (field polygon, tree rows geofenced-static per ADR-001, 2-3 scripted birds) | `robotics-sim-engineer` | `flight-software-engineer` | **DONE (pending human Docker flight-check).** World `sim/worlds/farmguard_field.sdf` (18 static trees + 3 dynamic birds); obstacle-export contract `config/static_obstacles.json`; mission flies **unchanged** (waypoints diff byte-for-byte); tested stdlib geofence consumer `src/fieldguard_planning/` (15/15 tests). Statically validated; live flight-through-world still needs the human Docker run. |
| D | ✅ Enable AP_DDS + lock interface names | `flight-software-engineer` | `tech-lead`, `devops-reliability-engineer` | **DONE (pending human `ros2 topic list` confirm).** Explicit enablement `config/sitl_params/dds_udp.parm` (`DDS_ENABLE=1`); full `/ap/*` topic/service/frame contract verified from AP_DDS source @ pinned SHA and pinned in **ADR-005**. Non-obvious catches: `/ap/pose|twist/filtered` are frame-mislabeled (content is world-ENU, not `base_link`); subscriber is bare `/clock` not `/ap/clock`; compiled `DDS_ENABLE` default is untrustworthy (SITL `eeprom.bin` persists the saved value) → hence explicit param file. |
| E | ✅ Scenario scaffolding (skeletons that can't let a cell be silently skipped) | `qa-safety-reviewer` | — | **DONE** — coverage-debt invariant defined (720-cell canonical grid; every cell terminal-status `covered`\|`debt`, absence = the silently-skipped bug); `src/fieldguard_planning/coverage.py` + 8 `eval/scenarios/*` specs; test suite 15→34 (27 pass now, 7 self-activate when a flight log exists). Two safety findings flagged: (i) the geofence is XY-only — the avoidance gate must be 3D; (ii) coverage rests on an unvalidated 7.5 m camera swath. |

- **Next (Weeks 3-4 — the differentiator):** detector + **reactive avoidance + coverage-debt replanning
  loop** running in the Week-2 farm world.
  - _Setup already in place for Weeks 3-4:_ tree row 0 (x=15) sits exactly on a boustrophedon lane
    centerline (min XY clearance **−2.0 m** — overlaps in plane, safe today only via the 11.5 m vertical
    margin at 15 m alt vs 3.5 m trees). So a scenario that forces a genuine XY dodge already exists —
    lower altitude or raise that tree; rows 1/2 sit 5-10 m off-lane and won't. Deliberate, documented.
- **Deferred, non-blocking:** bake the workspace build into the image (devops); merge the
  `fix/week1-bringup` PR. _(AP_DDS moved into Week 2 as goal D — the ROS 2 control path needs it.)_

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
