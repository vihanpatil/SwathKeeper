# SwathKeeper — Build Log

Chronological record of what shipped, what broke, and what each phase taught. Newest first.
This is the *narrative* companion to `docs/DECISIONS.md` (the why) and `docs/ROADMAP.md` (the now).
Full session records live in `docs/archive/` and the runbooks in `docs/runbooks/`.

---

## 2026-08-18 (late night) — `fly_pipeline.sh` replaces the 7-shell bringup, and the first scripted test-flight gate PASSES

The seven copy-pasted terminal tabs of `docs/runbooks/FULL_PIPELINE_DEMO.md` collapsed into one
host-side tmux session (ADR-013): `scripts/fly_pipeline.sh`, one window per runbook shell, each pane
running that shell's `docker exec` one-liner **byte-identical** to the runbook (mechanically diffed,
all nine lines) — the only thing added is ordering and a **gate between every stage** (Gazebo's four
`/fg/sensor` advertisements, the ROS 2 crossover, the render-alive probe, UDP 2019 bound before SITL
boots). A qa-safety-reviewer adversarial pass refused to accept that the gates prove anything, on
the grounds that every one of them is a *liveness* gate — it cannot tell whose process it found —
and proved the point live: running `status` against an already-running manual bringup returned
three green gates and no tmux session, the exact stale-bringup clash the happy path would never
have surfaced. `up` now refuses to start on any surviving sim process instead of double-publishing
into it.
Then the one scripted flight mode this ADR allows — `fly_pipeline.sh test-flight` (ADR-013
amendment 2), a regression gate, not a flight path — ran for real and **PASSED on its first attempt**:
`eval/results/testflight_gate_20260818T222031Z.json` — 253 s unattended, every gate green, the
birds pane self-started at its altitude gate (15.0 m), teardown went recorder-first, the host-side
stitch exited 0 over a 48-frame clip with 0 stale-pose pairs. Suite 246 → 270 green (the 24 launcher
tests in `tests/test_fly_pipeline.py`) — and CI was not running any of them: `discover -s
tests/fieldguard_planning` never walks `tests/`, so a second discover was added. The ROADMAP's
test-count line said **131**, a number last true on 2026-08-05 and carried unchanged through the
sessions that tripled it; corrected to 270 in the same pass, and worth naming rather than quietly
overwriting — a stale metric in a living doc is the failure mode this repo claims not to have.
Docs decision: against a four-direction options artifact, the user picked **D · Heatmap Neutral**,
built by an in-repo generator rather than an external tool (ADR-014). An adversarial QA pass on the
generator found four defects the exit code could not: a wrapped body line beginning `#5→#8)` parsed
as a page-title `<h1>` mid-ADR (python-markdown allows `#` with no space; GitHub does not — the
renderer now follows GitHub and a heading-parity gate fails the build on any future divergence),
broken intra-repo `.md` links passing silently, the print stylesheet losing to the dark rule on
specificity so an Auto + dark-OS reader printed a black page, and one unbreakable
`eval/results/...json` path widening every page at 375 px.

### 2026-08-19 02:07Z — the recording-throughput lever, measured and **disproven**

ROADMAP item 1's first lever was `camera.update_rate_hz` 5 → 2: halve the render+transport load and
the starved software-rendered pipeline should *deliver* a larger fraction of frames (at 3 m/s and a
13.8 m footprint, 2 Hz still over-samples). It was a good hypothesis. It is wrong — and the run that
killed it took under four minutes.

| | 5 Hz baseline (22:16Z) | 2 Hz (02:07Z) |
|---|---|---|
| fused frames recorded | **48** (42 with rgb) | **3** (3 with rgb) |
| recorder exposure window, sim time | 133.2 s (sim 11.4 → 144.6) | ~128.9 s (sim ~10.6 → 139.5) |
| frames expected at the configured rate | 666 | ~258 |
| **delivered fraction** | **7.2 %** | **1.2 %** |
| delivered per sim-second | 0.360 | 0.023 |
| **cells imaged** | **291 / 720** | **1 / 720** |
| stale-pose pairs | 0 | 0 |
| soil cells (mean NDVI) | 281 at −0.438 | 1 at −0.438 |
| canopy-like cells (> +0.3) | 6 (max +0.478) | 0 |
| mission flown | 12 "Reached command" | 12 "Reached command" |
| flight wall time (arm → disarm) | 192 s | 177 s |
| gate wall time | 253 s | 233 s |
| RTF (bird anchor → last frame) | 0.561 | 0.585 |

Sources: `eval/results/testflight_gate_20260818T222031Z.json` and
`eval/results/testflight_gate_20260819T021136Z.json`, their clips' `meta.json` / `poses.jsonl` /
`heatmap/heatmap.json`, and the two `bird_drive_*.json` sidecars (the sim↔wall anchors the RTF and
the 2 Hz window estimate are computed from — that one window start is *derived*, from a recorder
that started 29 s before arming in **both** runs, not measured; every other number is read straight
off an artifact).

Read it honestly: this is not a marginal miss, it is a **16× regression**, and the quality arm
became unevaluable (one cell, at home, during the landing descent — all three frames arrived at sim
130.0 / 131.0 / 139.5 s, i.e. nothing at all was delivered during the traverse). Two controls say the
host was not the culprit: the mission flew identically (12 reached commands, birds self-started at
14.99 m vs 15.0 m, pose-call failures 10/522 vs 6/531) and the sim ran *marginally faster* in sim
time per wall second (RTF 0.585 vs 0.561) — so the render load did drop, exactly as the lever
predicted, and delivery fell anyway. The load relief was real; the throughput gain was imaginary.
The best available explanation is that delivery on this stack is **bursty, not steadily
rate-limited**: 9 of the baseline's 47 inter-frame gaps are ≤ 0.4 s and 4 are exactly 0.2 s, so the
pipeline does briefly run at the 5 Hz ceiling and harvests whole bursts — and a 2 Hz ceiling
(0.5 s) cannot harvest a burst at all. That accounts for part of the drop, not for a 16×, and the
honest position is that the mechanism is **unproven on n=1**. The verdict does not depend on it:
under the project's own rule (keep the change only if the delivered fraction improves materially
with no quality regression), nothing in this data keeps 2 Hz. Config and world are back at 5.0 —
the SDF regenerated byte-identical to its committed state — with the measured basis now recorded in
`config/ndvi_camera.json`'s own `update_rate_note`, so the next person cannot re-derive this
hypothesis for free.

One instrumentation gap this exposed, worth fixing before the next throughput attempt: **no
artifact distinguishes "the fusion node never fused" from "the recorder dropped what it fused."**
`fused_count` / `dropped_pair_count` live only in the ndvi node's console, and `pane_tails["ndvi"]`
comes back empty in *both* gate records — so the one number that would have root-caused this run was
never captured. Persist the fuser's counters into the gate record (or the clip `meta.json`) and the
next lever gets diagnosed instead of guessed.

## 2026-08-18 (night) — Gates 1-3 green, five bugs deep, and the first honest heatmap

The batched session ran to the end — and became the project's best story. Gates 1-3 all passed
live (bridge; canopy 0.854 > soil 0.212 > bird 0.040 across 996 frames with the ADR-012 birds
moving; clean avoidance takeover/resume on the NDVI model, ledger valid at 513/207). Then six
recorded flights peeled five real bugs off the pipeline, each invisible to the value-gates:
1. **Arrival-paired poses** mislabeled frames under render bursts (0/18 trees despite a
   plausible map) → gz-clock stamp pairing + per-frame residuals + stitch skipping flagged frames.
2. **Bridging the sim clock** (~350 msg/s) starved image serialization ~8× → native gz-transport
   clock stream.
3. A **shallow fusion pairing queue** (10) flushed stamps before partners arrived under load →
   queue 60 + the host-quiet rule (parallel agent workloads on the host were eating the sim).
4. A **long-lived render instance silently degraded** to sky-flat frames in both bands →
   `scripts/check_render_alive.py` pre-flight probe + restart-Gazebo-per-flight rule.
5. **The sensor mount had faced the horizon, upside-down, since ADR-007 was authored** — Gazebo
   cameras look along sensor +X; the rpy was derived Z-forward. Found by the tree-position check;
   root-caused with a landmark-oracle world (after learning `<static>` doesn't propagate into
   nested includes — crash-tumbling test vehicles produced hours of contradictions);
   fixed and now GATED: `scripts/verify_mount_geometry.sh`, canopy centroid within 2.2 px of the
   georef prediction.
Flights 6-7 on the corrected mount produced the first heatmaps that survive cross-examination:
every imaged tree at its true position, +0.87 typical NDVI lift, soil dead on the physics
prediction. Evidence committed past the gitignore (level-by-level exceptions). Remaining:
fused-frame recording THROUGHPUT (truth proven; coverage per flight still partial — first lever:
camera 5→2 Hz), then the ADR-003 real-render re-run (annotator needs a pre-driver-start clamp).
The meta-lesson, now everywhere in the docs: gates that measure values cannot catch geometry;
every artifact needs a check against ground truth it cannot fake.

## 2026-08-18 (evening) — First Gate-1 attempt: one blocker fixed live, one real bug found

The batched Docker session started. Gazebo came up healthy (thermal on all 36 visuals, four
`/fg/sensor/*` topics advertised), but the `ros_gz` bridge crashed on missing
`libactuator_msgs...so`: the bridge's *optional* build-time deps are hard runtime deps, rosdep had
installed them at workspace-build time, and apt state is container-ephemeral while the workspace
volume persists. Fixed live (3 apt packages), verified (bridge creates all 4 GZ→ROS bridges),
pinned into the Dockerfile. Then a live scene-graph query exposed a latent Week-2 bug: **the bird
actors have never rendered** — skinless `<actor>` link-visuals don't enter Harmonic's ogre2 scene
(0 bird entities in `scene/info`). Never noticed because the avoidance demo injects bird
positions, not pixels. Gate 2's bird check + real-render detection were blocked on the fix,
which landed the same night (ADR-012): birds → static models (per-visual thermal works there,
unlike actor skins) + `scripts/drive_birds.py` interpolating the unchanged trajectory JSON through
`set_pose` at the camera rate. Verified in-container on a renamed-world copy: 3 birds in the
render scene (was 0), driver placed bird_0 trajectory-exact. Gazebo must be relaunched to pick up
the regenerated world. Full details: `docs/runbooks/NDVI_VALIDATION.md` session log.

## 2026-08-18 — The audit, the rename, and Phase A1 hardening

A 5-auditor sweep (docs / code / sim / eval-CI / state-vs-claims) after a 13-day pause found the
foundation solid but the process rusting: **CI had been silently red for 12 days** (tests ran before
the numpy install, so the seed-42 FNR safety gate never executed on the branch), the **coverage
ledger had an honesty bug** (commanded dodge setpoints recorded as flown — a never-visited cell
could finalize COVERED; scenario logs understated debt by up to 32 cells), and the **2026-08-05
live-demo flight log had been silently clobbered** by a later idle run. One session repaired
committed scope, nothing added without a cut:

- CI un-redded + 2 new gates (scenario-log drift, flight-log evidence validity). The drift gate
  caught two real regressions on its first day: a stale-params drift and a **cross-platform libm
  ulp divergence** (macOS vs glibc disagree in the last bit of the bearing-sweep trig — logs now
  round floats to 1e-9 so byte-identity is platform-independent).
- Ledger honesty restored: fix + regression test (proven to fail against the old code) + honestly
  regenerated logs (`cov_bird_at_turnaround` 118→144 debt, `geo_avoid_into_tree` 112→144).
- `scripts/stitch_ndvi.py` (ADR-010): the offline georeferenced stitch — exit criterion 1 became
  producible in a single Docker session. Georef pitch/roll proven correct by new hand-derived
  tilted-pose fixtures (no bug found — the math was right, now it's pinned).
- ADR-009 detector contract locked before the Week-6 detector: `Detection.stamp_s` + staleness
  gate; bird position from apparent-size ray, never ground-plane projection (which would place a
  flying bird at z=0, *outside* the threat cylinder — fail-dangerous).
- Flight logs timestamped + CI-validated; evidence can no longer be silently destroyed.
- Test suite 94 → 131; pytest un-broken repo-wide (a tests `__init__.py` shadowed the source package).
- PR #13 merged (10 commits) — public main current again.
- **Project renamed FieldGuard → SwathKeeper** (ADR-011): docs/branding renamed; code identifiers
  (`fieldguard_planning`, `fg_`/`/fg/*`, `farmguard_field.sdf`, `fieldguard-sim` image) deliberately
  kept. Docs restructured reader-first: `docs/runbooks/` (by function, not week number),
  `docs/archive/` (historical records), this build log, `docs/README.md` index.

## 2026-08-05 — Week 5 kickoff: ADR-007 lands, Gate 0 GREEN

The NDVI phase's one architecture risk — *can the pinned Gazebo Harmonic + ogre2 stack render a
second band at all?* — was retired the right way: ADR-007 (RGB camera Red channel + **Gazebo
thermal sensor repurposed as synthetic NIR**, fused in a ROS 2 node) passed external review, and
the kill-switch gate ran FIRST in Docker before any temperature authoring: `gz-sim-thermal-system`
loads, the world loads with the two-sensor mount, all four `/fg/sensor/*` topics present. One real
failure en route: the mount joint's parent-link name was wrong twice before
`iris_with_gimbal::base_link` resolved (the `<include merge="true">` flattening — full record in
`docs/runbooks/NDVI_VALIDATION.md`). NDVI fusion + georef stitch math shipped sim-agnostic and
unit-tested. Scope guards recorded: no YOLOv8 keyword-chasing, no startup cosplay
(`docs/ROADMAP.md` cut log). Remaining live-verification debt batched into ONE session: Gates 1-3 +
ADR-003 real-render re-run.

## 2026-08-05 — Weeks 3-4: the core loop, live

The differentiator ran end-to-end on the real stack: during a boustrophedon survey the drone
detected the scripted bird, took over (`/ap/mode_switch`→GUIDED), flew a 3D-vetted dodge
(`/ap/cmd_gps_pose`), held clear, resumed AUTO at the same waypoint (`MIS_RESTART=0`), finished the
survey — one clean takeover/resume, no thrash. Built sim-agnostic first (policy + executor +
coverage-debt ledger, pure stdlib Python, QA's adversarial scenarios green), then bound to ROS 2
by a thin adapter. ADR-005 (the `/ap/*` topic contract) and ADR-006 (we own the maneuver;
AUTO→GUIDED→AUTO) both **confirmed live**. The three Docker gates (farm world flies, AP_DDS
publishes per contract, resume behavior) passed in one session — record archived at
`docs/archive/WEEK3_VALIDATION.md`. Six real bringup bugs found + fixed en route (bash-3.2 array,
colcon `set -u`, MAVProxy, `future`, `micro_ros_msgs`, and the big one — SITL builds DDS OUT
unless `--enable-DDS`).

## 2026-08-04 — Weeks 1-2: foundation + the detection decision

Full ArduPilot + Gazebo + ROS 2 workspace built from source in Docker (pinned SHAs in `CLAUDE.md`
— captured at the first green Gazebo flight, the real reproducibility anchor). A generated
boustrophedon mission flew fully autonomously (takeoff, 6-lane sweep, RTL). The farm world shipped
(18 static trees, 3 scripted birds) with the mission unchanged byte-for-byte. AP_DDS enabled
explicitly with the non-obvious catches documented (frame_id lies on `/ap/pose|twist/filtered`;
`eeprom.bin` persists params). The NDVI-vs-RGB question was closed by measurement, not opinion:
ADR-003 — detect NDVI-direct; the classical blob baseline hit per-bird-track FNR 0.000 on the
fixed-seed synthetic clip, so no trained model was justified. The permanent `eval/` harness was
born from that spike. QA defined the coverage-debt invariant (720-cell canonical grid; every cell
terminates `covered`|`debt`; absence IS the bug) — the invariant everything since is measured against.

## 2026-07-27 — Kickoff

Scope confirmed (avoidance-with-coverage-integrity first, NDVI second, dashboard last-and-light);
sim-only decided (ADR-000); toolchain pinned (ADR-004: Ubuntu 22.04 in Docker, ROS 2 Humble,
Gazebo Harmonic, `ardupilot_gazebo` `ros2` branch); tiger team of 8 subagents stood up
(`TIGER_TEAM_GUIDE.md`); original playbook archived at `docs/archive/tiger_team_playbook.md`.
