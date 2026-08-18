# NDVI Validation — the Batched Docker Gate Session *(runbook; ADR-007 gates, born Week 5)*

Owner: **human** (you), with `robotics-sim-engineer` on standby for failures.

## ✅ GATE 0 PASSED GREEN (2026-08-05) — Gates 1–3 still to run

**Gate 0 (the thermal-system kill-switch) executed live 2026-08-05 and passed**: the thermal
system loads on the pinned Harmonic+ogre2 stack, the world loads with the sensor mount (after the
joint-parent fix recorded below — see "The fixed-joint parent name"), and all four `/fg/sensor/*`
topics are present on the gz side. **Do NOT re-run Gate 0; the batched session resumes at
Gate 1.** Everything below about Gates 1–3 remains source-verified only.

## ⚠️ Session log 2026-08-18 — Gate 1 attempted; read this before resuming

**What happened:** Shell 1 (Gazebo) came up healthy — thermal systems on all 36 visuals, all four
`/fg/sensor/*` topics advertised gz-side (Gate 0 behavior re-confirmed incidentally). Shell 2's
`parameter_bridge` failed to start: `error while loading shared libraries:
libactuator_msgs__rosidl_typesupport_cpp.so`.

**Root cause + fix (APPLIED LIVE in container `dafb3e095140`, and pinned in
`sim/docker/Dockerfile` for future image rebuilds):** `ros_gz_bridge` was compiled with three
*optional* deps present (rosdep installed them at workspace-build time), which makes them hard
runtime deps — but apt state is **container-ephemeral** while `/root/ardu_ws` persists, so a
recreated container loses them. Fix, verified working (bridge starts, creates all 4 GZ→ROS
bridges):
```bash
apt-get update && apt-get install -y ros-humble-actuator-msgs ros-humble-gps-msgs ros-humble-vision-msgs
```

**✅ RESOLVED (ADR-012, verified live 2026-08-18): the bird-render bug is fixed.** The actors
(which never rendered — skinless `<actor>` link-visuals don't enter Harmonic's ogre2 scene; 0 bird
entities in `scene/info` all along) are now static **models** (same sphere/material/authored 273 K
per-visual thermal), moved along the unchanged `config/birds/*.json` trajectories by
`scripts/drive_birds.py`. Verified in-container on a renamed-world copy: 3 birds in the render
scene, no actor warnings, and `--once 12` placed bird_0 at the trajectory-exact (20, 32.998, 8).

**Session procedure change:** for Gate 2's bird check and ANY recorded flight, start the driver in
its own shell first:
```bash
python3 /workspace/fieldguard/scripts/drive_birds.py            # 5 Hz until Ctrl-C
python3 /workspace/fieldguard/scripts/drive_birds.py --once 12  # or: park birds at t=12s for a still shot
```
⚠️ **Restart Gazebo (Shell 1) before resuming** — the running instance predates the world change;
the regenerated `farmguard_field.sdf` (birds as models) only takes effect on a fresh `gz sim` launch.

## Gates 1–3 are source/doc-verified only, not run

Nothing about Gates 1–3 has executed against the real Gazebo/ogre2 render yet. Every claim about the
thermal sensor, the bridge, and the sensor-mount attachment was checked against the pinned-branch
**source** (gz-sim8 == Harmonic, ros_gz `ros2` branch, ArduPilot/ardupilot_gazebo `main`), not
memory or guesswork — but source-reading is not the same as a live render. This session is what
converts "source-verified" into "confirmed." **Do the remaining gates in order, starting at
Gate 1** (Gate 0, the hard kill-switch, already passed — banner above). (Gate 3, added by
flight-software-engineer 2026-08-05, is a regression check — the NDVI sensor mount changed the
vehicle model the already-proven Week-3 avoidance loop flies with, not a new ADR-007 render claim —
but it belongs in the same session since it reuses Gates 0-2's running Gazebo instance.)

## Why this exists

ADR-007 (`docs/DECISIONS.md`) picked a specific, slightly unusual mechanism: Gazebo's `type="thermal"`
sensor, repurposed as a synthetic NIR band via a per-visual `<temperature>` plugin, fused with a
plain RGB camera's Red channel. The external review that accepted ADR-007 flagged two real risks
before any NDVI number can be trusted:
1. Does `gz-sim-thermal-system` even load cleanly on this project's pinned Harmonic + ogre2 build?
   If not, everything downstream (calibration, the smoke test, the future `ndvi_node`) is dead.
2. Is the per-visual temperature authoring actually complete? Miss one visual and it silently
   renders ambient temperature — flat, meaningless NDVI, with no error to flag it.

Gates 0 and 2 below exist specifically to answer those two questions before any stitch work starts.

---

## Prerequisites (macOS host)

Same as `docs/archive/WEEK3_VALIDATION.md`: Docker Desktop running, the `fieldguard-sim` image built
(`scripts/sim_docker_build.sh`), the container up (`scripts/sim_docker_run.sh`). All commands below
run **inside the container** at `/workspace/fieldguard`.

If `sim/worlds/farmguard_field.sdf` was regenerated since your last container session, nothing new
needs rebuilding on the Gazebo side — it's a plain SDF file, no colcon package involved. Just make
sure the checked-out repo inside the container (bind-mounted, per `docs/runbooks/SIM_BRINGUP.md` §2) has
the current version.

---

## Gate 0 — KILL SWITCH: does `gz-sim-thermal-system` load on this pinned Harmonic + ogre2 build?

**Run this before touching anything else.** If it fails, stop and report back — there is no point
authoring/debugging NDVI calibration against a thermal sensor that doesn't load.

This world already runs `gz-sim-sensors-system` with `<render_engine>ogre2</render_engine>`
(`sim/worlds/farmguard_field.sdf` lines ~13-15, unchanged since Week 2) — the same render path the
official `gz-sim8` (Harmonic) example `examples/worlds/thermal_camera.sdf` uses for its own thermal
camera demo (fetched and diffed against the pinned branch this session; not guessed). That's the
basis for expecting Gate 0 to pass, but it is **not** the same as having run it.

```bash
source /root/ardu_ws/install/setup.bash
export GZ_SIM_RESOURCE_PATH="${GZ_SIM_RESOURCE_PATH:-}:/root/ardu_ws/install/ardupilot_gazebo/share"
gz sim -v4 -s -r --headless-rendering /workspace/fieldguard/sim/worlds/farmguard_field.sdf
```

- ✅ PASS: the world loads with no `Failed to load a world`, no `Unable to find uri`, and — the
  thermal-specific check — no error naming `gz-sim-thermal-system`, `gz-sim-thermal-sensor-system`,
  or `ThermalCamera`/`ThermalSensor` (e.g. "Failed to load system plugin", "unable to create
  sensor"). Cosmetic `gz_frame_id` warnings are expected and fine (same as every prior Week's runs).
- Also confirm the two new sensors actually instantiate (not just that the world parses):
  ```bash
  gz topic -l | grep fg/sensor
  # expect: /fg/sensor/rgb/image  /fg/sensor/rgb/camera_info
  #         /fg/sensor/nir/image  /fg/sensor/nir/camera_info
  ```
  If the world loads but these four are **missing**, the sensors themselves failed to instantiate
  (different failure mode than the world failing to parse) — check the full `-v4` log around
  `fg_rgb_camera`/`fg_nir_camera` for the actual error before going further.
- ❌ FAIL: capture the full `-v4` output and report back immediately — per the review, this is the
  single highest-leverage failure this whole ADR could have.

### The fixed-joint parent name — RESOLVED live 2026-08-05 (Gate 0 passed)

This was a **second, self-identified risk** beyond the review's own kill-switch, and it **did fire on
the first live run**: `gz sim` rejected the world with
`Error Code 21: parent frame [iris_with_gimbal::iris_with_standoffs::base_link] specified by joint
[fg_sensor_mount_joint] not found in model [iris_with_gimbal_ndvi]`. The originally-authored
fully-nested name (and the fallback first suggested here, `iris_with_standoffs::base_link`) were
**both wrong**. Confirmed correct value: **`iris_with_gimbal::base_link`**.

Why: `iris_with_gimbal` pulls in `model://iris_with_standoffs` with `<include merge="true">`, which
flattens `base_link` directly into `iris_with_gimbal` rather than keeping it under an
`iris_with_standoffs::` sub-scope — proven by the fact that the fully-nested path did NOT resolve
while the merged path does. From the non-merge wrapper `iris_with_gimbal_ndvi`, the airframe link is
therefore `iris_with_gimbal::base_link` (drop the middle segment, keep the wrapper prefix). This is
now the value in `config/ndvi_camera.json` → `mount.parent_link_scoped_from_wrapper`; regenerate with
`python3 scripts/gen_farm_world.py` if you ever change it. Gate 0 then loaded cleanly with the thermal
system and all four `/fg/sensor/*` topics present.

This is a separate concern from Gate 0's thermal-system question — the world could fail to load for
this reason with the thermal system working perfectly fine, or vice versa. Diagnose which one it is
from the actual error text before changing anything.

---

## Gate 1 — the four `/fg/sensor/*` topics publish, correctly encoded, at rate

With Gate 0's Gazebo instance still running:

**Shell B** — start the ros_gz bridge:
```bash
source /root/ardu_ws/install/setup.bash
ros2 run ros_gz_bridge parameter_bridge --ros-args \
  -p config_file:=/workspace/fieldguard/sim/bridge/fg_sensor_bridge.yaml
```

**Shell C** — from any ROS 2-sourced shell:
```bash
ros2 topic list | grep '^/fg/sensor'
# expect exactly 4: /fg/sensor/rgb/image  /fg/sensor/rgb/camera_info
#                    /fg/sensor/nir/image  /fg/sensor/nir/camera_info

ros2 topic hz /fg/sensor/rgb/image     # WALL rate ≈ 5 Hz × RTF, not zero. Measured 2026-08-18:
                                        # RTF ≈ 0.17 on this software-rendered ARM stack → ~0.8 Hz
                                        # wall is CORRECT for the 5 Hz sim-time camera
                                        # (config/ndvi_camera.json update_rate_hz). Confirm the
                                        # SIM rate via header stamps: consecutive frames must be
                                        # ~0.2 s of sim time apart. Budget note: recordings take
                                        # ~1/RTF wall time (a 5-min mission ≈ 30 min wall).
ros2 topic hz /fg/sensor/nir/image     # same rate, same cadence as rgb

ros2 topic echo --field encoding /fg/sensor/rgb/image --once   # expect: rgb8
ros2 topic echo --field encoding /fg/sensor/nir/image --once   # expect: mono16

ros2 topic echo --field width  /fg/sensor/rgb/camera_info --once  # expect: 640
ros2 topic echo --field width  /fg/sensor/nir/camera_info --once  # expect: 640 (IDENTICAL to rgb --
                                                                    # ADR-007's hard requirement)
```

- ✅ PASS: all four topics present, encodings exactly `rgb8` / `mono16`, both at the same non-zero
  rate, and `rgb`/`nir` `camera_info` report identical `width`/`height`/`K` (intrinsics) — they're
  declared with literally the same `horizontal_fov`/`width`/`height` in
  `sim/worlds/farmguard_field.sdf` (generated from one `config/ndvi_camera.json`), so any mismatch
  here means the generator or the SDF drifted, not that this was expected.
- If topics are missing: confirm Shell B (the bridge) is actually running and didn't error on
  startup (a bad `gz_type_name` string would print an unsupported-type error immediately); confirm
  Gate 0's `gz topic -l | grep fg/sensor` still shows the underlying Gazebo-side topics.
- If rate is zero but topics list: the sensors likely aren't being updated because nothing is
  driving simulation time forward — confirm `gz sim` is running with `-r` (not paused).

---

## Gate 2 — the canopy/soil/bird pixel smoke test (the actual proof)

This is the gate the review asked for by name, and the one that has to pass before any stitch/fusion
work starts. Script: `scripts/check_ndvi_bands.py` (see its module docstring for the full design
rationale — samples the **raw NIR band directly**, deliberately does not build the NDVI-fusion math,
which is flight-software's downstream scope).

**Shell D** — fly the existing, already-proven boustrophedon mission exactly as in
`docs/archive/WEEK3_VALIDATION.md` Gate 1 (`scripts/run_farm_mission.sh` prints the recipe). No mission or
world regeneration needed — reusing the proven flight is deliberate, see the script's docstring for
why lane x=15m is expected to put bird_0 in frame.

**Shell E** — once the mission is armed and flying:
```bash
source /root/ardu_ws/install/setup.bash
python3 /workspace/fieldguard/scripts/check_ndvi_bands.py --out /workspace/fieldguard/gate2_summary.json
```

Expected signature (from `config/ndvi_camera.json`'s calibration table): mean raw-NIR reflectance
proxy (`rho_nir`) roughly **canopy ≈0.85 > soil ≈0.20 > bird ≈0.05**, each pair separated by
**≥0.08** (the script's default `--min-rho-gap`; calibration guarantees ≥0.15 for both gaps, 0.08
leaves slack for antialiasing/edge blending). The script prints a running per-class report every 15s
and a final PASS/FAIL verdict; exit code 0 = PASS.

- ✅ PASS: script prints `PASS: canopy(...) > soil(...) > bird(...)` and exits 0. This is the direct
  proof the NIR band is genuinely independent of the RGB/Red band (the thing ADR-007's rejected
  option (c), NIR-derived-from-RGB, could never produce) — canopy vs. soil differ, so the
  temperature authoring isn't flat/ambient, and the bird registering a *third*, most-extreme value
  confirms even the dynamic actors are calibrated correctly.
- ⚠️ INCONCLUSIVE (`bird` pixel count stayed 0): the bird likely never crossed the frame this run.
  Rerun with a longer `--duration-s`, or fly a second full mission — do **not** treat this as a pass
  by just dropping the bird check; the whole point is proving the calibration reaches the dynamic
  actors too, not just the static world.
- ❌ FAIL (classes observed but gap too small): this is the review's named failure mode —
  some visual(s) fell back to ambient temperature instead of their calibrated value. Cross-check
  `sim/worlds/farmguard_field.sdf` — every `<visual>` must have its own
  `<plugin filename="gz-sim-thermal-system" ...><temperature>...</temperature></plugin>` (**40**
  per-visual: 1 ground + 18×2 tree trunk/canopy + 3 birds).
  **Correction (verified 2026-08-05, was previously misstated as 40):**
  `grep -c 'gz::sim::systems::Thermal' sim/worlds/farmguard_field.sdf` should print **41**, not 40 —
  the raw (unanchored) grep pattern also matches the single world-level
  `name="gz::sim::systems::ThermalSensor"` system-loader plugin (the one that enables the thermal
  camera sensor itself, distinct from the 40 per-visual temperature-authoring plugins), because
  `"ThermalSensor"` contains `"Thermal"` as a substring. To count ONLY the per-visual authoring
  plugins (the number that must be exactly 40), anchor the pattern:
  `grep -c 'name="gz::sim::systems::Thermal"' sim/worlds/farmguard_field.sdf` (should print 40); use
  `grep -c 'name="gz::sim::systems::ThermalSensor"' sim/worlds/farmguard_field.sdf` to confirm
  exactly 1 sensor-system loader separately. If the anchored per-visual count is off from 40, the
  generator has a bug — report back, don't hand-patch the generated SDF.

---

## Gate 3 — the Week-3 avoidance loop still flies with the NDVI sensor model

**Why this gate exists:** the vehicle model changed `iris_with_gimbal` -> `iris_with_gimbal_ndvi`
(config/ndvi_camera.json's "mount" block) — two new rendering sensors (RGB + thermal cameras) and
40 per-visual thermal plugins added on top of the world Weeks 1-4 already proved out. Added render
load can drop the real-time factor or perturb FDM/sensor timing; the Week-3 avoidance loop
(`docs/runbooks/AVOIDANCE_DEMO.md`) was specifically sensitive to this class of problem (a stalled or
delayed `/ap/pose/filtered` stream reads as a frozen drone to the control loop). This gate exists to
catch a regression **before** trusting any NDVI number gathered on top of a maybe-broken avoidance
loop — same "previous work must keep working" discipline as every other regression gate in this
project.

Run this AFTER Gates 0-2 pass (so the NDVI sensors are confirmed instantiating and publishing) —
it reuses that same running Gazebo instance, model, and world.

**Shell A** (Gazebo, already up from Gate 0) + **Shell B** (micro-ROS agent, started BEFORE SITL —
see `docs/runbooks/AVOIDANCE_DEMO.md`'s "Agent BEFORE SITL" warning, it applies identically here) +
**Shell C** (SITL, `--enable-DDS`) + **Shell D** (the avoidance node):

```bash
# Shell D, inside the container:
source /root/ardu_ws/install/setup.bash
cd /workspace/fieldguard
PYTHONPATH=src:$PYTHONPATH python3 -m fieldguard_planning.avoidance_node --demo
```

Then in Shell C's MAVProxy prompt, exactly as in `docs/runbooks/AVOIDANCE_DEMO.md`:
```
param set MIS_RESTART 0
wp load /workspace/fieldguard/config/missions/boustrophedon.waypoints
param set AUTO_OPTIONS 3
mode auto
arm throttle
```

While the mission flies, in a spare shell watch the real-time factor Gazebo is achieving (the
`gz sim` GUI stats panel, or `gz stats` if available) — note it before/during the dodge, since a
collapsed RTF is the actual regression signal, not just "did it eventually finish":
```bash
gz topic -e -t /world/farmguard_field/stats -n 1   # one-shot sample of the world stats message
```

- ✅ PASS, ALL of the following:
  1. Shell D's log shows the same `takeover` -> `maneuver` -> `resume` sequence as
     `docs/runbooks/AVOIDANCE_DEMO.md` documents (`set_mode GUIDED` -> `cmd_gps_pose <- ENU(...)` ->
     `set_mode AUTO`) as the drone reaches the demo bird near lane x=30 — dodge -> hold -> resume
     completes cleanly, same as the pre-NDVI-model Week-3 run.
  2. The mission continues and completes its remaining lanes after the resume (not just the one
     dodge) — confirms the render load isn't causing a LATER stall once the two extra cameras are a
     few tens of seconds into continuous operation, not just at t=0.
  3. Real-time factor stays in a broadly comparable range to the Week-3 baseline (`docs/
     docs/archive/WEEK3_VALIDATION.md`'s recorded number, if captured there — otherwise treat any RTF that stays
     bounded and non-collapsing, e.g. doesn't trend toward 0, as passing) for the duration of the
     dodge. A software-rendering (`llvmpipe`, no GPU passthrough — `docs/runbooks/SIM_BRINGUP.md` gotcha
     #1) machine is already slow; the question is whether the TWO NEW CAMERAS make it categorically
     worse, not whether it's fast in absolute terms.
  4. `eval/results/live_flight_log_<UTCstamp>.json` (written on Shell D's `Ctrl-C`; timestamped since 2026-08-18 so runs can never clobber prior evidence) shows the same shape as a
     Week-3 flight log: a `takeover`/`maneuver`/`resume` triplet in `events`, and `finalize()`'s
     coverage ledger has no cell missing (per `coverage.check_ledger`'s P1 partition invariant) —
     i.e. the coverage-debt guarantee still holds with the heavier vehicle model, not just the
     avoidance mechanics.
- ⚠️ DEGRADED (dodge completes but RTF visibly collapses / pose updates visibly stutter): capture
  the RTF numbers and the flight log, but this is not an automatic FAIL — note it and consider
  lowering `config/ndvi_camera.json`'s `camera.update_rate_hz` (already conservative at 5 Hz,
  documented as the first lever to pull in that file's own `update_rate_note`) before concluding
  the sensor mount itself is the problem.
- ❌ FAIL (dodge doesn't trigger, doesn't complete, or the flight log shows a missing/duplicate
  cell that Week-3's equivalent run didn't have): this is a real regression — report back with the
  Shell D log tail and the flight log; do not silently attribute it to "the sim is just slow" without
  the RTF evidence from step 3 above.

---

## On any gate failure

**STOP.** Capture the failing shell's full output (`-v4` Gazebo log for Gate 0, `ros2 topic echo`
output for Gate 1, the script's final report line + `--out` JSON for Gate 2, the Shell D log tail +
flight log for Gate 3). Report back to `robotics-sim-engineer` (Gates 0-2) or
`flight-software-engineer` (Gate 3, the avoidance-loop regression) — per the review, a Weeks 5-6
stall here is the #1 project risk, so a fast, well-captured failure report matters more than trying
to patch it live.

## When all four gates pass

Flip ADR-007 in `docs/DECISIONS.md` from "confirmation-pending" to confirmed, with the date and a
one-line pointer to this doc's results (mirroring how ADR-005/ADR-006 were closed out in Week 3).
Then run **the recorded flight** — the artifact every remaining exit criterion consumes.

### The recorded flight (same session, gates green)

Shell order (1-5 as the gates already have them): Gazebo, bridge, agent, SITL, birds
(`drive_birds.py --rate 2`, started AFTER arming — its service traffic adds jitter the EKF can't
tolerate while aligning). Then:

**Shell 6 — the fusion node** (must be up before the recorder; its `/fg/ndvi/image` stamp is the
georef anchor):
```bash
source /root/ardu_ws/install/setup.bash
PYTHONPATH=/workspace/fieldguard/src:$PYTHONPATH python3 -m fieldguard_planning.ndvi_node
```

**Shell 7 — the recorder** (writes the spike-schema clip live; Ctrl-C AFTER the mission RTLs):
```bash
source /root/ardu_ws/install/setup.bash
PYTHONPATH=/workspace/fieldguard/src:$PYTHONPATH python3 -m fieldguard_planning.record_node \
  --out /workspace/fieldguard/eval/results/clips/real_flight_$(date -u +%Y%m%dT%H%M%SZ)
```
Watch for "live intrinsics locked" (that line IS the ADR-007 follow-up-5 evidence) and the
`recorded N frames` heartbeats. On Ctrl-C it finalizes `meta.json` (`synthetic: false`) and prints
the exact stitch command. Budget ~1/RTF wall time for the full boustrophedon.

**Afterwards, on the host** (no container needed): `python3 scripts/stitch_ndvi.py --clip <dir>`
→ the georeferenced heatmap (exit criterion 1); `eval/run_spike.sh` pointed at the same clip → the
ADR-003 real-render re-confirmation (criterion 3). COMMIT the clip's `meta.json` + `poses.jsonl` +
`heatmap.*` + a handful of sample frames (not all ~GBs of `.npy`) — evidence, per the 2026-08-18
clobber lesson.
