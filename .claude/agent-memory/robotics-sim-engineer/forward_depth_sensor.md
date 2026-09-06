---
name: forward-depth-sensor
description: The ADR-019 forward depth camera (built host-side 2026-08-26, NOT YET RENDERED) — mount pose and the generalized Gazebo +X derivation, the gz-sensors depth_camera facts verified at the pinned stack, the gates with their measured host-side margins, the booking-gate and in-render exit contracts, and the two adversarial-QA rounds that reshaped them.
metadata:
  type: project
---

Built host-side 2026-08-26 under ADR-019 (Council Ruling 002) after ADR-017 am. 1 measured
`speed_at_which_nadir_becomes_safe_mps = None`. **Authored and host-gated; NEVER RENDERED.**
Related: [[adr007-ndvi-sensor-mount]] (the nadir pair this must not disturb),
[[recording-throughput-levers]] (the bus it joins), [[farm-world-layout]].

## The mount
`config/depth_camera.json` -> `scripts/gen_farm_world.py` -> a SECOND link `fg_depth_mount` +
`fg_depth_mount_joint` on the same `iris_with_gimbal_ndvi` wrapper, parent
`iris_with_gimbal::base_link` (identical scoped name to the NDVI mount, and for the identical
`<include merge="true">` reason). Pose **(0.15, 0, 0) xyz, (0, 0, 0) rpy**. Sensors only, no
visual/collision.

**rpy (0,0,0) IS forward** — Gazebo cameras look along the SENSOR frame's +X, so identity gives
optical z = body +X, u+ = body -Y (right), v+ = body -Z (down). **The trap:** the ROS/pinhole
instinct `rpy (-pi/2, 0, -pi/2)` aims the optical axis at body **-Y**, out of the right flank —
the ADR-007 am. 5 bug class. `depth_detect.optical_to_body_matrix(roll,pitch,yaw)` is the general
form (`Rz*Ry*Rx @ OPTICAL_TO_SENSOR`), and its licence is that at the NADIR mount's
`(-pi/2, +pi/2, 0)` it returns exactly `diag(1,-1,-1)` == `ndvi_georef.CAMERA_TO_BODY_SIGNS`, the
extrinsic verified in the real render to 2.2 px. Use that cross-check for ANY future mount.

## gz-sensors `depth_camera` facts — verified against pinned-branch source, not memory
Re-verify by re-fetching these files at the branches `CLAUDE.md` pins if they seem to have drifted.
* **`<camera_info_topic>` IS IGNORED for `depth_camera`.** `DepthCameraSensor::Load` calls the base
  `Sensor::Load`, never `CameraSensor::Load` (which is where line 389 reads the element), then calls
  `AdvertiseInfo()` with an empty infoTopic. `CameraSensor::AdvertiseInfo` (src/CameraSensor.cc:
  662-676) then DERIVES the name: split `<topic>` on '/', **pop the last segment**, append
  `/camera_info`. So `fg/depth/image` -> `/fg/depth/camera_info`. Emitting the element would be dead
  config that looks live.
* Depth value = **pinhole Z-depth in metres** (`point.x = -viewSpacePos.z`, gz-rendering8 ogre2
  `depth_camera_fs.glsl`), so `ndvi_georef.pixel_at_depth_to_enu`'s `depth_m` semantics apply
  verbatim. **THE TWO CULLS ARE ASYMMETRIC and quoting only one overstates headroom by an order of
  magnitude:** NEAR culls on the stored Z-depth (`point.x < near + tolerance`), FAR culls on the
  **Euclidean** length (`length(point) > far - tolerance`). So the effective Z horizon is far/|ray|
  — 51.10 m at the horizontal frame edge, **47.56 m at the corner**, against a 46.80 m acquisition
  bound: **1.6 % of headroom, not 28 %**. On-axis the two are equal by construction, which is why an
  on-axis-only render check cannot catch a sensor that reports slant range (up to 1.26x error).
* **+inf beyond far clip, -inf inside near clip** (`dataMaxVal`/`dataMinVal` default to
  `±gz::math::INF_D`). A non-finite pixel is a refusal, never clampable to the clip plane.
* **The depth render is LAZY.** `Update()` returns early when nothing is subscribed to either the
  image or the `<topic>/points` cloud. "No frames" can mean "no subscriber". The point cloud is
  likewise only *built* when subscribed (`HasPointConnections()`), so leaving it unbridged is free.
* `SetAntiAliasing(2)` is **hardcoded** in DepthCameraSensor.cc with a `\todo ... via sdf` — the
  SDF `<image><anti_aliasing>` element does not reach it. This is why the acquisition range must be
  measured in the render rather than trusted from pinhole arithmetic.
* `R_FLOAT32` is a documented `<image><format>` value in sdformat 1.9 camera.sdf, and ros_gz at the
  pinned SHA maps it to ROS encoding **`32FC1`** (convert/sensor_msgs.cpp:158-159).
* Frame size 640x480x4 = 1,228,800 B = **19 SHM fragments**, same class as `/fg/ndvi/image`. Bridge
  QoS `best_effort` for it is a per-topic ROS **parameter** on the bridge command line, never a
  yaml key (same as the two /fg/sensor images).

## Gates and their measured host-side margins (2026-08-26)
| gate | command | measured |
|---|---|---|
| static geometry | `python3 scripts/check_depth_mount.py` | **PASS 23/23**, ~50 ms, no container |
| booking gate | `python3 scripts/predict_forward_lead.py --speed 5.0` | **PASS, margin 1.811x** (bar 1.30x), exit **3** = not bookable on config inputs (exit 0 is UNREACHABLE without live inputs in every mode, sweep included) |
| booking sweep | `--sweep 2:10:0.5` | PASS 2.0-9.0 m/s, **FAIL at 10.0** (ArduCopter's own WPNAV_SPD default) |
| in-render | `bash scripts/verify_depth_mount_geometry.sh` | first run **2026-09-06: FAIL exit 1 — HARNESS BUG, not the sensor.** It stripped the physics plugin, so every `set_pose` was a silent no-op and the bird was never in frame (D2 CLEAR/FAR "passed"; RANGE/AIM/OFFAX/AXES/NEAR nan; D3 0.0 m). Camera itself fine: nearest finite depth 32.568 m == the ground at the bottom edge of a level camera at 15 m. Rewritten same day (zero-gravity world, verified teleports, extended ground, stale-server guard, waiting teardown) and **still owes a real pass** — see [[gz-teleport-and-park]] |

Booking-gate arithmetic, conservative reading: `margin = (acq_range / (v_mission + v_bird)) /
(t_req + latency) >= 1.3`, with `t_req = 1.7925 s` (`time_to_displace_s(3.00, GUIDED_DEFAULT)`),
`latency = 0.200 (frame) + 0.160 (measured control tick)`, `v_bird = 7.004` (fastest bird in the
config, not today's threat). The lenient reading (`(lead - latency) / t_req`) passes 10 m/s —
do not switch conventions without saying so.

Host-side geometry numbers to compare the render against: **acquisition 46.80 m** (a 0.18 m bird at
the measured 2.0 px radius floor, fx 520.006), **threat band in frame from 13.00 m** (±6 m at
cy/fy), required horizon **33.59 m at 5 m/s**, headroom **28.2 %** (only **4.3 %** at 9 m/s — which
is why 5.0 m/s is the recommendation, not a preference).

**MIN_RESOLVING_RADIUS_PX = 2.0** is MEASURED against `ndvi_detect.detect_blobs` at the worst
sub-pixel offset (1.9 px / 9 raw px is erased by the 3x3 open; 2.0 px / 13 raw px survives), and
re-measured on every test run.

## What the adversarial QA round changed (2026-08-26, same day)
The physics and every source citation survived independent re-derivation; the **exit contract and
the gate holes** did not. Keep these, they are the reusable lessons:
* **One exit code, one meaning — check EVERY mode.** `--sweep` returned 0 whenever any speed passed,
  on config-only inputs, while two runbooks published "exit 0 = book the flight". The property to
  test is "exit 0 is unreachable without live inputs", parametrized over modes — not "the four exit
  codes are distinct integers".
* **A cross-check between a function and its own inverse is not a cross-check.**
  `time_to_displace_s` IS bisection on `max_displacement_m`; a 3x-optimistic mutant moved t_req
  1.79 -> 1.00 s with the "two plant functions agree" test still green. Pin to the ANALYTIC closed
  forms instead (j*t^3/6; the three-phase accel form; the quadratic root for t_req).
* **Validate input or it launders.** `--acq-range-m inf` produced exit 0 BOOKABLE; `--speed nan`
  exited 1, i.e. a typo read as a conclusion about the hardware. Garbage is always a REFUSAL.
* **Half a live intrinsic set is a 2x-optimistic answer.** fx drives acquisition range, cy drives
  band coverage: they must come from the same `camera_info` or neither.
* **`max()` is the wrong aggregator for a horizon sweep** — one lucky far hit after a miss promotes
  the gate. Use the longest contiguous prefix.
* **Inclusive clip bounds accept the exact value the "refuse, never clamp" rule exists to reject.**
* **A new sensor needs adding to the MANDATORY liveness probe.** `check_render_alive.py` sampled
  RGB only, so `up` went all-green with depth dead — the 2026-08-18 failure on the newer sensor.

## The gate's exit contract, hardened 2026-09-06 (QA round 2, host-only)
Two MUST-FIX findings, both reproduced on the host with no renderer, both about the same thing:
**an unscoreable or failing run must not read as a verdict, and must not hand over a number.**
* **Only exit 0 and exit 1 say anything about the mount.** 2/3/4 and 124/130/143 mean NOT SCORED.
  Two paths used to bypass the published table: an unguarded `gz topic -l | grep "^/<w>/depth"`
  aborted at **exit 1** (the gate-fail code) before the D1 diagnostic printed, and `capture()`'s bare
  `timeout 30 gz topic -e` aborted at **124** with no banner and a 0-byte frame. Both now route
  through `harness_fail` -> 4. Generalisable: under `set -euo pipefail`, **grep and timeout are the
  two commands that fail as a matter of course** — the test that pins this scans logical lines (with
  continuations joined) for unconditional uses of either, and it is worth copying to other gates.
* **D3's number and its `predict_forward_lead.py` command line now print ONLY inside `if ok:`.**
  They used to print ABOVE the verdict loop, so a run that FAILED D2 still handed the operator a
  plausible acquisition range and the exact command that authorises a flight (runbook §2 "write the
  number down" and §6 item 1 were unconditioned too — both now say "only if this run exited 0").
* **The near-miss worth remembering:** moving the `ok = all(...)` fold above the sweep collided with
  the sweep's own `for r, ok in zip(ranges, detected)` — a `for` target leaks in python. A sweep that
  detected at EVERY range left `ok = True`, so a mount failing D2 OFFAX + D2 CULL printed **PASS,
  exit 0, and the booking command**. Reproduced, then fixed by renaming to `seen`. This is the
  ADR-007 am. 5 shape exactly: a green tick over geometry the same run had already disproven.
  **Reordering a verdict fold is a scope change, not a move — re-run the block, do not eyeball it.**

**Host-only rehearsal technique that caught all of it** (no Docker, ~2 s): extract the script's
python heredoc (`TEXT.split("<<'PYEOF'\n")[2]`) and drive it with synthetic frames from an
INDEPENDENT pinhole model (sphere + ground plane, near/far cull on Euclidean slant, value stored as
Z-depth or — to force a failure — slant range). numpy and `ndvi_detect.detect_blobs` both import on
the host. The synth agreed with the live probe on the two numbers that matter: D2 FAR 0.796 vs 0.80,
D2 CULL 57.78 m @ |ray| 1.038 vs the live 57.99 @ 1.034. Use it before spending any session.

## Two open questions this session deliberately did not decide
1. Whether `predict_bird_visibility.py` (the nadir gate) is still a precondition for a DODGE take
   now that detection is on the forward sensor. It still gates the NDVI map. Do not silently retire.
2. Cruise nose-down pitch rotates this camera; the level mount's band coverage is unverified against
   it. Measure it live (FORWARD_DEPTH_SENSOR.md gate D6) — do NOT pre-compensate with an invented
   tilt. The tilt rejection is quantified in `config/depth_camera.json` `tilt_rejected_note`.
