# Week 5 — Human Docker Validation Session (ADR-007 NDVI sensor gate)

Owner: **human** (you), with `robotics-sim-engineer` on standby for failures.

## Everything below is source/doc-verified only, not run

Nothing in this doc has executed against the real Gazebo/ogre2 render yet. Every claim about the
thermal sensor, the bridge, and the sensor-mount attachment was checked against the pinned-branch
**source** (gz-sim8 == Harmonic, ros_gz `ros2` branch, ArduPilot/ardupilot_gazebo `main`), not
memory or guesswork — but source-reading is not the same as a live render. This session is what
converts "source-verified" into "confirmed." **Do the three gates below in order — Gate 0 is a
hard kill-switch, do it FIRST, before looking at anything else.**

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

Same as `docs/WEEK3_VALIDATION.md`: Docker Desktop running, the `fieldguard-sim` image built
(`scripts/sim_docker_build.sh`), the container up (`scripts/sim_docker_run.sh`). All commands below
run **inside the container** at `/workspace/fieldguard`.

If `sim/worlds/farmguard_field.sdf` was regenerated since your last container session, nothing new
needs rebuilding on the Gazebo side — it's a plain SDF file, no colcon package involved. Just make
sure the checked-out repo inside the container (bind-mounted, per `docs/WEEK1_BRINGUP.md` §2) has
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

### If the world fails to load specifically at `iris_with_gimbal_ndvi` / the fixed joint

This is a **second, self-identified risk** beyond the review's own kill-switch, worth calling out
explicitly: the sensor mount is attached via a `<joint type="fixed">` whose `<parent>` is the scoped
name `iris_with_gimbal::iris_with_standoffs::base_link` (see `config/ndvi_camera.json`'s `"mount"`
block for the full derivation — traced from ArduPilot's own `models/iris_with_gimbal/model.sdf` at
the pinned branch, not guessed). If `gz sim` reports it can't resolve that parent link (something
like "unable to find parent link" naming `fg_sensor_mount_joint` or `iris_with_gimbal_ndvi`):
1. First fallback to try: shorten the parent name to `iris_with_standoffs::base_link` (drop the
   `iris_with_gimbal::` prefix) in `config/ndvi_camera.json` → `mount.parent_link_scoped_from_wrapper`,
   then `python3 scripts/gen_farm_world.py` to regenerate, then retry Gate 0.
2. If neither resolves, report back — this needs `robotics-sim-engineer` to either find the correct
   scoped name (`gz model -m iris_with_gimbal_ndvi -l` or the Entity Tree GUI panel would show the
   actual link names Gazebo resolved) or fall back to the (more heavily reviewed, plugin-based)
   `gz-sim-detachable-joint-system` mechanism instead of a plain `<joint>`.

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

ros2 topic hz /fg/sensor/rgb/image     # steady ~5 Hz (config/ndvi_camera.json update_rate_hz), not zero
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
`docs/WEEK3_VALIDATION.md` Gate 1 (`scripts/run_farm_mission.sh` prints the recipe). No mission or
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
  `<plugin filename="gz-sim-thermal-system" ...><temperature>...</temperature></plugin>` (40 total:
  1 ground + 18×2 tree trunk/canopy + 3 birds — `grep -c 'gz::sim::systems::Thermal'
  sim/worlds/farmguard_field.sdf` should print 40). If one is missing, the generator has a bug —
  report back, don't hand-patch the generated SDF.

---

## On any gate failure

**STOP.** Capture the failing shell's full output (`-v4` Gazebo log for Gate 0, `ros2 topic echo`
output for Gate 1, the script's final report line + `--out` JSON for Gate 2). Report back to
`robotics-sim-engineer` — per the review, a Weeks 5-6 stall here is the #1 project risk, so a fast,
well-captured failure report matters more than trying to patch it live.

## When all three gates pass

Flip ADR-007 in `docs/DECISIONS.md` from "confirmation-pending" to confirmed, with the date and a
one-line pointer to this doc's results (mirroring how ADR-005/ADR-006 were closed out in Week 3).
Then Weeks 5-6's remaining scope — the `ndvi_node` fusion (`/fg/ndvi/image` etc.) and the ADR-003
real-render re-confirmation — is unblocked. Both are explicitly **out of scope for this session and
this doc** (flight-software-engineer / perception-ml-engineer, downstream of a green Gate 2).
