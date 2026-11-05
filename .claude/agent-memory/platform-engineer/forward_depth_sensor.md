---
name: forward-depth-sensor
description: The ADR-019 forward depth camera — COMMISSIONED IN THE RENDER 2026-09-06/07 (D2 8/8, D3 bookable 46.0 m user-ratified, D4 exit 0 at 5 m/s margin 1.780x, D5 132/132 but at 3.5 m/s not cruise, D6 pitch unmeasured at 5 m/s). Mount pose and the Gazebo +X derivation, the gz-sensors depth_camera facts at the pinned stack, every gate with its measured margin, the two sweep guards, the exit contracts, and the QA rounds that reshaped them.
metadata:
  type: project
---

Built host-side 2026-08-26 under ADR-019 (Council Ruling 002) after ADR-017 am. 1 measured
`speed_at_which_nadir_becomes_safe_mps = None`. **RENDERED AND COMMISSIONED 2026-09-06** — see
"The commissioning session" below for every measured number.
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
| in-render | `bash scripts/verify_depth_mount_geometry.sh` | run 1 **2026-09-06: FAIL exit 1 — HARNESS BUG, not the sensor.** It stripped the physics plugin, so every `set_pose` was a silent no-op and the bird was never in frame (D2 CLEAR/FAR "passed"; RANGE/AIM/OFFAX/AXES/NEAR nan; D3 0.0 m). Camera itself fine: nearest finite depth 32.568 m == the ground at the bottom edge of a level camera at 15 m. Rewritten same day (zero-gravity world, verified teleports, extended ground, stale-server guard, waiting teardown) → **run 2 PASS 8/8** — see [[gz-teleport-and-park]] |

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
**It is now PERMANENT**, as `TestTheScoringBlockOnSyntheticFrames` in
`tests/test_verify_depth_mount_geometry.py`: a 2-station run (10 m + 20 m, one painted `far/|ray|`
pixel so D2 CULL has its ground) driven green / red / missed-station / no-camera_info, ~1 s. At the
live intrinsics it reproduces the render's own D2 CULL **58.01 m at pixel (289,374), |ray| 1.034**
and corner bound **47.56 m** from first principles — an independent model agreeing to the centipixel
is the cheapest confidence in this repo. Requires numpy+scipy, skipped without them.

## The commissioning session — every measured number (2026-09-06/07)
* **D2 PASS 8/8** in the render. RANGE 9.821 m (predicted 9.820), AIM error **0.0 px** (bar 15),
  OFFAX 19.822 m = Z-depth 19.840 and NOT slant 22.326, AXES exact at (560,120), CLEAR **0 px**
  (the airframe does not occlude), NEAR `['-inf']`, FAR 0.796, CULL **57.99 m at |ray| 1.034** vs
  far/|ray| 58.01. Live intrinsics **fx 520.0058046927554, cy 240, fy 520.0058046927553** — config
  agrees to **1 ULP**.
* **D3 is TWO numbers (ADR-020 am. 1):** the bird was detected at EVERY swept range 10->58 m, so the
  **optical prefix 58.0 m is a FLOOR, not a horizon** (footprint PLATEAUS at a 4x4 px patch from
  40 m out — an analytic sphere + hardcoded AA(2) returns finite depth for any pixel a sample
  touches, so the component survives on AREA 16 > min_area 6, not on a 2 px radius). The
  **BOOKABLE** number is the longest prefix range inside the frame-corner Z horizon: **46.0 m**
  (last swept value under 47.56). Feed BOOKABLE to the booking gate, never the prefix.
* **46.0 m RATIFIED BY THE USER 2026-09-07** (options offered: 46.0 / 44.0 / hold-until-segmenter).
  Four independent bounds land in **[46.0, 47.56]**: render prefix 58.0, pinhole x morphology 46.80,
  corner clip 47.56, QA's centre-sampled ideal-disc ladder through `detect_blobs` dies at 48 m.
  **46.0 is a BEST-CASE-SCENE UPPER BOUND** (no clutter, static vehicle, noiseless sensor, sky
  background, on-axis, blind `isfinite` mask, and the depth segmenter does not exist yet) and must
  **never be quoted without that clause**.
* **D4 booking gate, live inputs, 5.0 m/s: exit 0 BOOKABLE, margin 1.780x** (3.832 s available vs
  2.152 s needed), corner headroom 3.4 %, required horizon 33.59 m. Artifact
  `eval/results/booking_gate_20260907T064136Z.json`, schema 1.2 recording
  `acquisition_clamped_from_optical_prefix true` / prefix 58.0 / clamp bound 47.558.
  **Pre-registered invalidation (QA): breakeven acq 33.591 m** — 33.6 still exits 0 at 1.300x, 33.5
  exits 1. At acq 58.0 it exits 1 on `acquisition_within_corner_far_clip` **and nothing else** —
  that check is speed-independent.
* **D5 delivery PASS: 132 / 132 = 1.000** over a 30 s wall window, `32FC1`, sim-clock stamps,
  `8x8413728` SHM segments (eight full-size, none at the 549,408 B default). Artifact
  `eval/results/depth_delivery_d5d6_20260906T195400Z.json` (now un-ignored in `.gitignore`; carries
  `measurement_context` + caveats). **NOT "at cruise":** the window's own ground speed (from the
  clip's `poses.jsonl`, sim 61.6-88.0 s) was **median 3.50 m/s** (n=132, min 2.29, max 4.79) — the
  2-lane mission never reaches cruise in a 30 s window. **Delivery at the 5.0 m/s booking speed is
  UNMEASURED.**
* **D6 pitch in that window: median -1.175 deg nose-down** (n=388 from `/ap/pose/filtered`; the
  clip's 133 quaternions give the identical median), mean -0.60, extremes -7.71/+8.56 — at
  **3.5 m/s, not 5**. **THE 5 m/s PITCH IS UNMEASURED**; the earlier reading that -1.18 deg
  "bounds the 5 m/s pitch from above" was **WRONG — do not repeat it**. It is bounded only by the
  flight's own worst attitude: **whole flight (sim 34.2-138.8 s, up to 10.58 m/s) -12.498 / +11.240
  deg** (n=524). Band arithmetic at that worst case: R*tan(24.775-12.5 deg) = 0.218R = **7.3 m**
  above the axis at the 33.59 m horizon vs a +/-6 m band — still in frame, **1.3 m spare**.
  **The mount stays level.**

### Two measurement traps from that session, both worth reusing
* **Do NOT count frames on the gz side.** `timeout 30 gz topic -e ... | grep -c "^header"` measured
  **0** depth and **68** camera_info while ROS was taking 132 of each: `timeout` kills `gz topic -e`
  before its stdout buffer flushes. The metric is the ROS-side PAIR (depth frames / camera_info
  frames over the SAME window) — the `red_frames/camera_info_frames` rule again.
* **The launcher prints no ARMED cue.** Trigger in-flight measurements on `/ap/pose/filtered`
  (BEST_EFFORT, container-only) `z > 8 m` plus a settle — 2026-09-06 fired at z 14.67 m, +12 s.

### The corner-bound formula — ONE COPY as of 2026-09-07, after three were wrong two ways
Under ADR-020 am. 1 the frame-corner Z horizon CLAMPS the acquisition range a flight is booked on,
so it must be `sqrt(1 + (max(cx, W-1-cx)/fx)^2 + (max(cy, H-1-cy)/fy)^2)`: the **FARTHEST** corner
(an off-centre cy=120 in a 480-row frame gives an honest 44.05 m where cy-alone says 50.14 m), the
**W-1/H-1** extents, and the vertical term over **fy**, not fx. Every error is optimistic in the
same direction, and today's centred 640x480 config hides all three.
**It now lives in exactly one place: `fieldguard_planning.depth_detect.corner_ray_ratio(W, H, fx,
fy, cx, cy)`**, imported by all three gates on their three different input sources —
`check_depth_mount.py` (config, the STATIC gate), `predict_forward_lead.py` (live camera_info) and
the in-render scoring block (the frame's own camera_info, inside the container off
`/workspace/fieldguard/src`, which is why it must live in `src/` and not `scripts/`). It had been
three hand-written copies; two were measured wrong at once. The in-render one was the worst — `w/2`
and `cy` for the principal point, **both** terms over fx, and it never read `K[2]` or `K[4]` at all.
Numerically 47.56 m either way on today's centred sensor, which is exactly why it survived.
*It raises `ValueError` on a degenerate set, so the in-render block calls it INSIDE the camera_info
`try` — uncaught 200 lines later it would abort python at exit 1, the code that means MOUNT FAIL.*

### The sweep is asserted to BE a sweep — TWO independent guards
* **G105 DISTINCTNESS.** All 15 sweep captures are hashed (sha1 over the base64 `data` field);
  `harness_fail` (exit 4) on any two identical — a wedged renderer repeating one frame would give
  D3 a long, entirely false contiguous prefix. Its heredoc delimiter is **PYHASH, not PYEOF**,
  because the host test indexes the PYEOF blocks positionally (0 = pose_check, 1 = scoring).
* **PER-STATION DEPTH EVIDENCE (added 2026-09-07, QA).** Distinctness is necessary and NOT
  sufficient: noise alone makes two captures of one scene distinct, so 15 different frames can
  still be 15 frames of a mis-teleported bird. Each DETECTED station's blob must carry its range —
  median finite depth inside its half-open box within `TOL_M` (0.20 m) of `R - 0.18`. **Measured on
  the retained run-2 frames: member depths track true Z to 0.02-0.16 m at every station 10..58 m**
  (10 m: 9.821-9.985; 46 m: 45.832-45.887; 58 m: 57.839-57.964), so the medians sit ~0.04-0.08 m
  out and 0.20 is a real bound. A MISSED station is never checked — a miss is the horizon, i.e. the
  thing being measured. Any mismatch = **exit 4, the harness class**, printed table and all, and
  the booking line is unreachable by construction (the check runs before the prefix is computed).
  **Why `r_apparent` cannot substitute:** the footprint PLATEAUS at 4x4 px from 40 m out, exactly
  the band the booked number is read from, so apparent size stops discriminating range there.

### The booking command line is now printed with the six live values substituted
`verify_depth_mount_geometry.sh` prints `--fx/--fy/--cx/--cy/--width/--height` at full `repr` off
this run's camera_info (fx and fy differ in the LAST ULP — rounding them would read as "square
pixels, confirmed"), plus `--acq-range-m <bookable> --acq-optical-prefix-m <prefix>`. Only
`--speed` stays a placeholder: it is a decision, not a measurement. **If camera_info did not parse
the whole line is REFUSED, not printed from the config fallback** — six config numbers wearing the
live flags would pass the booking gate's own set check and answer ADR-019 item 6 with prose.

## Still open
1. Whether `predict_bird_visibility.py` (the nadir gate) is still a precondition for a DODGE take
   now that detection is on the forward sensor. It still gates the NDVI map. Do not silently retire.
2. **The segmenter does not exist**, and `MIN_RESOLVING_RADIUS_PX = 2.0` was calibrated on
   `ndvi_detect.detect_blobs` — which the render just showed is not what the sweep actually keys on
   (area, not radius). Re-measure the floor against the real segmenter, in a CLUTTERED scene:
   canopies enter the frame from ~24.4 m and ground from ~32.5 m, both inside the 33.6 m horizon,
   and an `isfinite` mask merges a low bird into the ground band where `max_area` then deletes it.
