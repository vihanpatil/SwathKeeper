# FieldGuard — Roadmap (living document)

Owner: `product-lead`. Update at each `/standup`. Target: done in ~7-8 weeks, before the Europe trip.
The `product-lead` re-cuts scope rather than moving the deadline. Full detail: `docs/SPEC.md`.

| Weeks | Goal | Primary roles | Exit criteria |
|---|---|---|---|
| **1-2** | Gazebo + ArduPilot SITL running; custom farm world; basic boustrophedon mission flies end-to-end, **no obstacles yet**. Run the NDVI-vs-RGB detection spike. | `robotics-sim-engineer`, `flight-software-engineer`, `perception-ml-engineer` | A mission flies the full field in sim; detection-approach decision recorded in DECISIONS.md with the metric that decided it. |
| **3-4** | Detector + **reactive avoidance + coverage-debt-tracking loop** in the Week-2 farm world (obstacles already built in Week 2). **The core — the differentiator.** | `tech-lead` (ADR-006), `perception-ml-engineer`, `flight-software-engineer`, `qa-safety-reviewer` | Drone detects a bird → avoids (3D-safe, no dodge into a geofenced tree) → returns to next waypoint, **demonstrated in sim** (needs the human Docker run); every detection/takeover/maneuver/resume + any uncovered cell (logged as coverage-**debt**) instrumented; QA's no-silent-skip scenarios green. v1 = return-to-next-waypoint (ADR-002); full requeue/reconciliation = stretch. |
| **5-6** | NDVI rendering pipeline; per-frame vegetation index; georeferenced stitching into a health map. Second-sensor comparison arm quantified. | `robotics-sim-engineer`, `perception-ml-engineer`, `flight-software-engineer` | A georeferenced NDVI heatmap for a full flight; comparison-arm numbers (what a 2nd sensor buys) written up. |
| **7** | Dashboard, demo video, README, resume bullets. | `gtm-narrative-lead`, `flight-software-engineer`, `devops-reliability-engineer` | Light dashboard (replay + avoidance log + NDVI overlay); recorded 60-90s demo; README readable in 90s; metric-backed resume bullets. |
| **8** | Buffer / polish. | all | Green CI from clean clone; tagged demo-ready commit; safety sign-off from `qa-safety-reviewer`. |

## ⚠️ Reality check & brutally honest status (2026-08-05, product-lead — no sweet talk, by request)

**What is actually true right now.** The full sim stack (Gazebo + ArduPilot + ROS 2) has run **exactly
once**, by hand, in Week 1. Every deliverable since — farm world, geofence, AP_DDS contract, detection
decision, CI — is validated **only in pure-Python and on synthetic data.** That is real, disciplined
engineering. It is **not** the same as "it works in sim," and the roadmap must not read as if it were.

**Risk register — ✅ CLEARED 2026-08-05. Runbook + results: `docs/WEEK3_VALIDATION.md`.**
The Week 3 Docker session ran end-to-end; all three gates passed:
1. **Farm world flies** — ✅ armed, took off to 15 m, flew the mission (`Reached command #N`). → Gate 1.
2. **AP_DDS publishes as verified (ADR-005)** — ✅ all 18 `/ap/*` topics match the contract. **ADR-005 confirmed.** → Gate 2.
3. **ADR-006 resume behavior** — ✅ `MIS_RESTART=0`, AUTO→GUIDED→AUTO resumed the interrupted leg. **ADR-006 confirmed.** → Gate 3.
- **ADR-003 real-render re-confirmation remains deferred to Weeks 5-6** — there is **no NDVI camera in the
  sim yet** (the NDVI render is the Weeks 5-6 pipeline). Correctly NOT batchable now.
- **6 real bringup bugs** found + fixed en route (PR #6): bash-3.2 array, colcon `set -u`, MAVProxy,
  `future`, `micro_ros_msgs`, and AP_DDS `--enable-DDS` (SITL builds DDS OUT by default).

The foundation is **confirmed live, no longer provisional.** **The Week 3 loop build is now UNBLOCKED**
(the product-lead gate on Gates 1-3 is cleared).

**Reality check on the ambition (you asked for zero sweet-talk):** this is a **simulation-only,
single-developer, ~7-8-week portfolio project** (ADR-000, CLAUDE.md). Stated plainly: in its current
form it is **not a company and will not be "bought for billions."** Saying otherwise would be the exact
flattery you told me to cut. What it genuinely can be — and what actually moves careers, and only *later*
companies — is a **rigorous, honest, interview-defensible demonstration of the hardest
practically-unsolved problem in ag-drone autonomy: live reactive avoidance that never silently drops
coverage.** Commercial ag drones fly pre-surveyed static missions; a defensible
reactive-avoidance-with-coverage-integrity demo is a genuine differentiator.

Becoming something commercially real would require what is explicitly **out of scope** and impossible
solo in 7-8 weeks: real flight hardware, real field trials, paying customers, BVLOS/regulatory work, and
a defensible moat. The honest path to "the next big thing" does **not** run through inflating a sim demo
— it runs through making the core loop so rigorous and well-measured that it earns the credibility to
attempt those steps. **Priority is therefore unchanged and correct: make the reactive-avoidance loop
excellent, measured, and honest. That is the bet. Everything else is narrative dressing on top of it.**

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

## Weeks 3-4 plan — the core loop (2026-08-05 — set at Week 3 standup; product-lead owns)
**Goal:** the detect → avoid → return-to-next-waypoint loop, built as **sim-agnostic, unit-tested Python**
proven against QA's adversarial scenarios, then demonstrated in sim. **Sequencing (product-lead, 2026-08-05):
the loop build is GATED on the human Docker validation (Gates 1-3) passing** — confirm the foundation
first, then build on it.
**Failure condition:** building the loop on an unconfirmed sim foundation and discovering at demo time that
the interface assumptions were wrong. The portfolio lives or dies on this loop existing **and being real.**

| # | Workstream | Lead | Support | Exit criterion |
|---|---|---|---|---|
| 0 | ✅ **ADR-006** — avoidance command interface, verified vs pinned SHA | `tech-lead` | `flight-software-engineer` | **DONE.** Our executor owns the maneuver: AUTO→GUIDED→one **3D-vetted `/ap/cmd_gps_pose`** setpoint (world-ENU, `frame_id="map"`)→GUIDED→AUTO. `MIS_RESTART=0` makes AUTO deterministically resume the interrupted leg to the same next waypoint (no index juggling). Rejected ArduPilot built-in OA (would move the reactive decision into the autopilot — deletes the differentiator). Source-verified @ pinned SHA; ACCEPTED (confirmation-pending: live resume needs the Docker run). Bonus: AP_DDS exposes **no mission-current service** → a source-verified reason requeue/reconciliation (ADR-002 stretch) is genuinely harder, not just deferred. |
| 1 | ✅ **Human Docker validation (THE GATE)** — Gates 1-3 in `docs/WEEK3_VALIDATION.md` | human | `robotics-sim-engineer`, `flight-software-engineer` | **DONE 2026-08-05** — all 3 gates passed; ADR-005 + ADR-006 confirmed live |
| 2 | 🔨 IN PROGRESS — Avoidance **decision policy**: given a detection + geofence + coverage state, when/where to dodge | `perception-ml-engineer` | `qa-safety-reviewer` | Emits a **3D-safe** maneuver for every QA scenario (never steers into a geofenced tree) |
| 3 | 🔨 IN PROGRESS — Avoidance **executor + coverage-debt bookkeeping**: take control, execute, resume, log every event, mark uncovered cells as debt | `flight-software-engineer` | `qa-safety-reviewer` | QA's pending scenarios go green: no silently-skipped cell, no missed bird, no geofence breach |
| 4 | 🔨 IN PROGRESS — Extend `geofence.py` to **3D** (altitude-aware safety gate) | `flight-software-engineer` | — | `geo_avoid_into_tree` scenario passes |

- _Forcing-scenario already in place:_ tree row 0 (x=15) sits exactly on a boustrophedon lane centerline
  (min XY clearance **−2.0 m** — overlaps in plane, safe today only via the 11.5 m vertical margin at 15 m
  alt vs 3.5 m trees). A scenario that forces a genuine dodge already exists — lower altitude or raise that
  tree; rows 1/2 sit 5-10 m off-lane and won't. Deliberate, documented.
- **CI (2026-08-04):** a no-Docker `planning-and-eval` job now runs on every push/PR — the stdlib
  `tests/fieldguard_planning` suite + the eval spike harness end-to-end + a seed-42 per-bird-track-FNR
  regression gate (`.github/workflows/ci.yml`, `requirements-eval.txt`, `scripts/check_spike_regression.py`).
  Verified locally in a clean py3.12 venv; deterministic across reruns. The Docker/Gazebo `build-test-sim`
  job stays deferred until the container image exists.
- **Deferred, non-blocking:** bake the workspace build into the image + stand up the Docker/Gazebo CI
  job (devops); merge the `fix/week1-bringup` PR. _(AP_DDS moved into Week 2 as goal D — the ROS 2
  control path needs it.)_

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
