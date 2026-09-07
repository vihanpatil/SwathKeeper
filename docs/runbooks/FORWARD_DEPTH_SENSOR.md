# Forward depth sensor — the commissioning session *(runbook; ADR-019 / Council Ruling 002)*

The forward depth camera exists because nadir cannot buy detection lead time at **any** speed:
ADR-017 amendment 1 measured `speed_at_which_nadir_becomes_safe_mps = None` — bird_0 closes at its
own 6.002 m/s, and nadir's 2.480 m forward horizon would have to be 17.8–38.8 m. So detection moves
to its own aperture while the NDVI survey pair stays exactly where four green gates left it.

**This is a COMMISSIONING session, not a flight.** Nothing here arms, and no dodge take may be
booked until §3 exits 0. One Docker session, ~20 minutes of gates, host quiet.

> **COMMISSIONED 2026-09-06/07 — all six D-gates MEASURED.** D2 **PASS 8/8**; D3 optical prefix
> **58.0 m (a floor)** / **BOOKABLE 46.0 m**, ratified by the user 2026-09-07 (§2); D4 **exit 0 —
> PASS and BOOKABLE at 5.0 m/s, margin 1.780×** on the live six-number intrinsic set (§3,
> artifact [`eval/results/booking_gate_20260907T064136Z.json`](../../eval/results/booking_gate_20260907T064136Z.json));
> D5 **132 / 132 = 1.000** (§4) and D6 **−1.18° median / −12.50° worst attitude** (§5). The
> acquisition rule those inputs feed is **ADR-020 amendments 1-2**.
>
> **STILL OWED, and it is a speed, not a gate: D5 and D6 were both measured in a window whose
> median ground speed was 3.50 m/s, not the booked 5.0 m/s.** Delivery and pitch **at the booked
> speed are UNMEASURED** and come off the dodge flight — the first flight that actually flies it.
> Numbers marked *(host)* are predictions to compare the render against; measured values are
> called out inline with their date.
>
> *First-run history, kept because it is the lesson:* run 1 **FAILED (exit 1) on the harness, not
> the sensor** — it stripped the physics plugin, so every `set_pose` was a silent no-op and the
> gates scored empty sky. See §2 "How the harness moves the bird".

### Where this sits among the runbooks
| runbook | what it does |
|---|---|
| [`FULL_PIPELINE_DEMO.md`](FULL_PIPELINE_DEMO.md) | **canonical for bringup** — the pane one-liners live there and only there, byte-diffed against `scripts/fly_pipeline.sh` |
| **this file** | commissions the ADR-019 forward depth mount: does it render, aim, deliver, and how far does it actually see |
| [`AVOIDANCE_REAL_DETECTION.md`](AVOIDANCE_REAL_DETECTION.md) | the take that consumes what this session measures |

---

## 0. Host-side preconditions — free, and they must all be green before the session

```bash
python3 scripts/gen_farm_world.py                       # must leave the tree byte-identical
git diff --stat sim/worlds/farmguard_field.sdf config/static_obstacles.json   # expect: nothing

python3 scripts/check_depth_mount.py                    # the STATIC geometry gate
python3 scripts/predict_forward_lead.py --sweep 2:10:0.5   # CHOOSE a mission speed (exit 3)
python3 -m pytest tests/fieldguard_planning/test_depth_detect.py \
                  tests/fieldguard_planning/test_predict_forward_lead.py -q
```

Measured on the committed artifacts *(host, 2026-08-26)*: the static gate passes **23/23**; the
sweep passes every mission speed from 2.0 to 9.0 m/s and **FAILs at 10.0 m/s** (ArduCopter's own
`WPNAV_SPD` default), with margin 1.811× and 28.2 % horizon headroom at the recommended **5.0 m/s**.

**The sweep is for CHOOSING a speed, not for authorising a flight.** It runs on
`config/depth_camera.json` numbers, so it exits **3** — PASS but NOT BOOKABLE — exactly like the
single-speed design check. Two pinned properties of the tool, not conventions: **a `--sweep` can
never exit 0**, however live its inputs (it exits **3** when some row passes and **1** when none
does); and **no mode reaches exit 0 without the full live input set** — the six intrinsics *and*
`--acq-range-m`, which is why §3 comes after §2.

**Why the static gate is not enough, stated once so nobody skips §2:** the nadir mount faced the
horizon, upside down, for two weeks and five recorded flights while all four of its gates passed,
because every gate measured VALUES and none measured GEOMETRY (ADR-007 am. 5). `check_depth_mount.py`
proves the arithmetic. Only the render proves Gazebo agrees with it.

### Keep the host quiet
Software rendering in Docker is CPU-starved by construction. Builds, test suites and parallel agents
have cost this project >90 % of a flight's frames, twice. Close them before you start.

---

## 1. Gate D1 — the world advertises the depth topics, under the names the bridge expects

```bash
scripts/fly_pipeline.sh up
```

`up` now gates on **six** camera topics, not four: the ADR-007 `/fg/sensor/*` quartet *and*
`/fg/depth/image` + `/fg/depth/camera_info`, counted separately so a world that lost one mount
cannot be covered by the other.

**The one thing most likely to be wrong, and why:** `/fg/depth/camera_info` is **derived by gz, not
declared in the SDF**. `DepthCameraSensor::Load` never calls `CameraSensor::Load`, so
`<camera_info_topic>` is silently ignored for this sensor type; `AdvertiseInfo()` instead splits
`<topic>` on `/`, **drops the last segment** and appends `/camera_info`
(gz-sensors8 `src/CameraSensor.cc:662-676`). `fg/depth/image` should therefore yield exactly
`/fg/depth/camera_info`. Confirm it by eye:

```bash
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && gz topic -l | grep /fg/'
```

*Expect:* `/fg/depth/image`, `/fg/depth/image/points`, `/fg/depth/camera_info`, and the four
`/fg/sensor/*`.
*If it says `/fg/depth/image/camera_info` instead:* the derivation changed. Fix
`sim/bridge/fg_sensor_bridge.yaml` to match what gz printed — **do not** add a `<camera_info_topic>`
element to the world; this sensor type ignores it, and a config that looks live and does nothing is
the exact failure mode the bridge yaml's own header warns about.

`/fg/depth/image/points` appearing in that list is **expected and harmless**: gz-sensors advertises
the point cloud unconditionally but only *builds* it when something subscribes
(`HasPointConnections()`), and nothing does. It is deliberately not bridged.

**The mandatory render probe now covers BOTH apertures.** `scripts/check_render_alive.py` — the
probe `fly_pipeline.sh` refuses to continue without — used to sample `/fg/sensor/rgb/image` only,
so `up` went all-green with the depth camera dead: the 2026-08-18 failure this project already paid
for, on the newer sensor. It now also requires a `/fg/depth/image` frame whenever the world being
flown declares one (derived from the SDF, so a camera-stripped world is not failed for a sensor it
does not carry), and reports the worse of the two verdicts.

---

## 2. Gate D2 + D3 — the mount aims where it claims, and how far it actually sees

Run it **alone**, before or instead of a bringup: it launches its own second rendering Gazebo, and
it **refuses (exit 4)** if one is already up — a leftover `/depthcheck/` server would answer its
probes with another run's scene, and a bringup's Gazebo starves the software renderer they would
share. `scripts/fly_pipeline.sh down` first if §1 left one running.

```bash
docker exec -it fieldguard-sim bash /workspace/fieldguard/scripts/verify_depth_mount_geometry.sh
```

It parks the vehicle at (60, 30, 15) nose-east — clear of both tree rows, open sky along the optical
axis — and teleports `bird_0` to known ranges dead ahead.

**How the harness moves the bird** *(rewritten 2026-09-06, after the gate's first run scored a bird
that never moved).* The script edits its own `/tmp` copy of the world in exactly two places, and
asserts both landed before it launches anything:

* **Physics is KEPT; gravity is zeroed** (`<gravity>0 0 0</gravity>` as the first child of
  `<world>`). `/world/<w>/set_pose` is served by `UserCommands`, whose `PoseCommand::Execute` only
  creates a `components::WorldPoseCmd`; the **only** consumer of that component is the Physics
  system (`PhysicsPrivate::UpdatePhysics`). Strip physics — as the first version of this script did,
  to stop the nested-include vehicle free-falling — and every teleport is a silent no-op while the
  service still replies `data: true`, because that Boolean means **queued, not moved**. Making the
  wrapper `<static>` is not the fix either: a nested include does not inherit it (measured again on
  2026-09-06 — the vehicle fell 15.0 → 0.19 m). With gravity zeroed, a free body with no forces on
  it stays parked: the vehicle held **exactly** (60, 30, 15) over a >25 s probe.
* **`field_ground`'s plane grows 125.00 → 425.00 m east-west, in the copy only.** The real ground
  ends at x = 100, i.e. **39.85 m** ahead of the parked camera, so nothing in the committed world
  reaches the 60 m far clip from this pose and **D2 CULL has nothing to measure** (the first run
  read 39.70 m — the scene's edge, not the clip). The extension touches nothing else: the boundary
  it creates is a clean curve, 0 fragment components through the morphology.

**Every teleport is verified.** After each `set_pose` the script reads the model back off
`/world/depthcheck/pose/info` and requires ≤ 0.05 m on each axis, printing the readback beside every
capture; the vehicle's park pose is checked the same way at world-up **and** after the last capture.
Any mismatch is **exit 4** and the run stops — a gate that cannot place its target does not get to
score pixels. `sim/worlds/farmguard_field.sdf` and `scripts/gen_farm_world.py` are untouched by all
of this (`tests/test_verify_depth_mount_geometry.py` pins that, and re-runs the sed on the host).

**And every sweep frame is asserted to be a different frame** *(added 2026-09-07)*. After the sweep
the script hashes all 15 captures (sha1 over each frame's base64 image data) and **exit 4**s if any
two are byte-identical, printing `sweep frames: 15 distinct of 15 captured`. A wedged renderer that
republishes one frame would have every range scored off **one** capture and D3 would report a long,
entirely false contiguous prefix. Before this the protection was only *incidental* — the offaxis and
near captures come after the sweep, so a stuck frame would have failed **D2 OFFAX** / **D2 NEAR**
— and incidental is not gated. It is the pose-readback lesson pointed at the sensor instead of the
bird: the *service reply* is not the move, and the *capture* is not a new frame.

| gate | assertion | *(host)* prediction → **measured 2026-09-06, run 2** |
|---|---|---|
| **D2 CLEAR** | no finite depth pixel nearer than 1.0 m | 0 px — the airframe mesh is the one thing host math cannot settle, so this is the real news → **0 px, PASS** |
| **D2 RANGE** | nearest finite depth at the 10 m on-axis capture | **9.820 m** (10 − the 0.18 m bird radius), ±0.20 m. A nadir mount from this pose reads **15.000 m** → **9.821 m** |
| **D2 AIM** | blind near-cluster centroid vs the principal point | (320, 240), ≤ 15 px → **(320, 240), error 0.0 px** |
| **D2 OFFAX** | the reading at pixel (560, 120) is **Z-depth, not slant range** | **19.84 m**, not the 22.33 m slant — 2.49 m apart against a 0.20 m tolerance → **19.822 m**, i.e. Z 19.840 and **not** slant 22.326 |
| **D2 AXES** | that same target lands where u+=right / v+=down predicts | (560, 120), ≤ 15 px → **(560, 120) exact** |
| **D2 NEAR** | bird parked 0.25 m ahead → literal pixel values at the principal point | `['-inf']`, **not** `0.1` → **`['-inf']`** |
| **D2 FAR** | some of the 10 m frame is `+inf` (sky past the far clip) | ~80 % of pixels — the reasoning assumes ground *all the way to the clip*, which is what the harness's plane extension buys → **0.796** |
| **D2 CULL** | greatest finite Z-depth = far ÷ \|ray\| **at its own pixel** | ~57.8 m at \|ray\| 1.038, **not** 60.0 → **57.99 m at (289, 374), \|ray\| 1.034, far ÷ \|ray\| = 58.01** |
| **D3** | greatest range at which the bird survives the adopted morphology | **46.8 m** *(host pinhole bound)* — the measurement is the point → **optical prefix 58.0 m (a FLOOR); BOOKABLE 46.0 m** (see below) |
| **D3 depth** *(harness, exit 4)* | every DETECTED station's blob carries **its own** range: median finite depth within `TOL_M` = 0.20 m of the bird's true Z (`R − 0.18`) | a frame from the wrong station is otherwise invisible → **0.02–0.16 m at every station, 10 → 58 m** (PROBE B, 2026-09-07) |

**Live intrinsics, 2026-09-06:** `fx` **520.0058046927554**, `cy` **240.0**, read in the check-world
copy. The config-derived focal length is `(640/2)/tan(1.1033/2)` = **520.0058046927555** — they agree
to **1 ULP**, which is a float's last bit and not a discrepancy. The booking gate takes its `fx`/`cy` from
the **real bringup's** `/fg/depth/camera_info` (§3): this world is a copy, and "the copy agreed" is
evidence, not the source.

**Why D2 alone is not enough (M3).** On the optical axis Z-depth and slant range are *identical by
construction*, so a mount that reported slant range would pass AIM, RANGE and CLEAR perfectly and
then place every off-axis obstacle up to **1.17×** too far at the frame edge (1.26× at the corner —
about **8 m of error at 46 m**, straight through `depth_pixel_to_enu`). **D2 OFFAX** is the capture
that can see that, and **D2 AXES** pins u+/v+ in the render rather than only in the matrix.

**Why the clip probes exist (M6).** `DepthDetectionSource` refuses a depth at or past a clip plane
rather than clamping it — a clamp at 60.0 m reads as a confident obstacle. Until now that rested on
reading gz-rendering source. **D2 NEAR** and **D2 FAR** put literal pixel values on the record, and
**D2 CULL** measures the asymmetry the config documents: the **near** cull is on Z-depth, the
**far** cull is on **Euclidean slant range** while the value stored is Z-depth.

**D3 is the number ADR-019 item 6 means by "from the sensor's own `camera_info`, never from config
prose"** — and it is a **BEST-CASE-SCENE RESOLVABILITY** figure, which is how it must be quoted. The
scene is the friendliest that exists: no clutter, a static vehicle, a noiseless sensor, a sky
background. That discharges the anti-aliasing unknown the host bound could not (gz hardcodes
`SetAntiAliasing(2)` past the SDF), and it stays an **upper bound on the mission horizon**, where the
bird crosses tree canopies and the ground band. The aggregator reports the longest **contiguous
prefix** of detected ranges, never `max()`: a hit after a miss is aliasing, and letting it set the
number would promote the booking gate to exit 0 on noise. **Write the printed number down — only if
this run exited 0.** A run that failed a mount gate still prints the sweep (it is the diagnostic
that says whether the target resolved at all), but the script labels the number *NOT A MEASUREMENT
OF THIS MOUNT* and refuses to print the `predict_forward_lead.py` line, because that number was read
through geometry the same run just disproved.

**D3 prints TWO numbers, and only one of them books a flight** *(the rule is ADR-020 amendment 1,
2026-09-06)*:

* the **OPTICAL PREFIX** — the contiguous prefix itself. On 2026-09-06 the bird was **DETECTED at
  every swept range, 10 → 58 m**, so the prefix is a **FLOOR**: the sweep ran out of clip, not out
  of target. Apparent radius tracked the pinhole prediction to ~40 m (9.00 px measured vs 9.36 at
  10 m; 3.00 vs 3.12 at 30 m) and then **PLATEAUED at a 4×4 px patch (r 2.00 px) from 40 to 58 m**
  while pinhole predicts 2.34 → 1.61 px. In a noiseless sky-backed scene an analytic sphere plus
  gz's hardcoded AA(2) returns a finite depth for **any** pixel a sample touches, so the footprint
  stops shrinking. **In this scene the optics out-resolve any far clip** — which makes the prefix a
  statement about the scene, not a horizon.
* the **BOOKABLE** range — the longest prefix range that also sits inside the **frame-corner
  Z-depth horizon** `far ÷ |ray_corner|` = **47.56 m** on the live `fx`/`cy`. Past that bound the
  *same* target away from the optical axis is culled to `+inf` — the asymmetry **D2 CULL** measures
  two gates up — and `predict_forward_lead.py` refuses it (`acquisition_within_corner_far_clip`).
  A horizon has to hold at the **worst** pixel, not the best one. On 2026-09-06: **46.0 m.**

**THE RULE — what `verify_depth_mount_geometry.sh` actually computes** *(ADR-020 am. 1)*:

> **D3-bookable = the longest contiguous-prefix swept range that also sits inside
> `far_clip ÷ |ray_corner|`, with `|ray_corner|` computed from the LIVE intrinsics.** Two bounds,
> and the result is always a station the sweep observed. That last part is what keeps it a
> measurement: a computed bound is a range at which **nothing was ever seen**, and the booking
> input has to be something the sensor did.

That is the rule in the amendment and the rule in the code — one expression,
`scripts/verify_depth_mount_geometry.sh`: `max(r for r in swept if detected and r <= prefix and
r <= far_corner)`. On 2026-09-06: prefix **58.0**, corner bound **47.56** → the last swept station
under both is **46.0 m**. The sweep quantum is 2 m in this band, so **46.0 is the last SWEPT value,
not the bound**; the true horizon lies in **[46.0, 47.56] m** and the gate books the low end, which
costs lead time — the safe direction to be wrong in. **The user ratified 46.0 m on 2026-09-07**,
against the alternatives of 44.0 m (one station further back) and holding the number until the
segmenter can be measured against it.

*The host pinhole × morphology bound (**46.80 m**) is NOT a term in that expression* — it is one of
the four independent bounds ADR-020 am. 2 tabulates as **corroboration**, and it happens to land
between 46.0 and 47.56 today, so a min-of-three rule would give the same answer. It would stop
giving the same answer the moment the morphology bound binds (a smaller bird, a lower `fx`, a
re-measured `MIN_RESOLVING_RADIUS_PX`) — which is why this section states the two-bound rule the
script runs, and not a three-bound one nobody implemented. Changing that is a rule change and needs
its own dated amendment plus the `.sh` edit, in that order.

**And the plateau is COVERAGE, not blur — two probes, 2026-09-07.** Amendment 1 could only label the
anti-aliasing story an interpretation. It is now evidence:

* **PROBE B, on run 2's retained frames.** The member **depths** of the plateau patch match the true
  Z (`R − 0.18` m) at **every** station within **0.02–0.16 m** — 10 m → 9.821-9.985; 30 m →
  29.825-29.936; 46 m → 45.832-45.887; 58 m → 57.839-57.964. A blended anti-aliased edge would be
  pulled toward the background, and this background is `+inf`. It is not: the plateau is a real
  12-raw-pixel patch of the bird's own surface carrying the bird's own range, a plus-shape that
  survives `detect_blobs`' 3 × 3 CROSS opening. It also **retro-proves the frames were distinct**
  (the depths advance with R) — the run predates the G105 hash check above, and probe B settles it
  better than a hash would.
* **PROBE 5** (a separate zero-g check-world run, every pose readback max |d| = 0.0000 m, exit 0):
  **QA probe A passed 5/5** — at Z 46 m the target still resolves at five sub-pixel offsets beside
  the on-axis baseline (r_app 2.00 on-axis, 2.00 at u+0.25, **1.75 at u+0.50** — QA's floor, and it
  holds — 2.00 at v+0.25, 2.00 and 2.50 on the diagonals; depths 45.82-45.95), so the plateau is not
  an artifact of the target landing on a sample centre. The **cull law was measured OFF-AXIS**: at
  pixel (580, 60), |ray| 1.1704, Z 46 → finite 45.83, Z 50 → finite 49.83, **Z 52 → `inf`** —
  bracketing the boundary in (50, 52) m against a predicted 51.26. And a bird **6 m below the axis**
  was detected at 30 m (row 344, predicted 344), 40 m (318) and 46 m (308), **all sky-backed**:
  finite ground starts at row 374 at the 60 m clip, so **the whole ±6 m band is sky-backed at the
  33.6 m required horizon** and shares rows with ground only below **~23 m**.

*If it exits 1* one of the mount gates failed and the script names it. The sweep below it is not a
property of this mount; nothing from that run reaches ADR-020 or the booking gate.
*If it exits 2* the depth topic never appeared — the world did not load, or it does not carry the
sensor. Go back to §1.
*If it exits 3* **D1 failed**: `/<world>/depth/camera_info` is not the name gz derived from
`<topic>`, so the bridge is bridging a topic that does not exist and will advertise silence. **This
script's exit 3 has nothing to do with the booking gate's exit 3 in §3** — same number, unrelated
meanings, in two tools one runbook section apart. Read the banner, not the code.
*If it exits 124, 130 or 143* the run was aborted, not scored — a capture timed out, or something
killed it. Same standing as exit 4, but without a banner, so read the code. **Only exit 0 and exit 1
say anything about the mount.**
*If it exits 4* nothing it printed is a measurement — the harness itself failed. It names which:
a gz server was already up (tear it down), the world copy did not get its two edits (the committed
world changed shape under the sed), a teleport did not apply (check the copy still carries
`gz-sim-physics-system`), **two sweep frames came back byte-identical** (the renderer wedged — check
`/tmp/depthcheck/gz.log`), **a sweep station's blob carried the WRONG DEPTH** (its median finite
depth is further than `TOL_M` from the bird's true Z — a frame from another station, or a bird that
did not go where it was told), a probe the run depends on did not answer, or the vehicle is not
parked at (60, 30, 15). Fix that and re-run; do not read the numbers above the failure.
*If D2 CLEAR fails* the aperture is occluded by the airframe: move `mount.mount_pose_xyz_rpy` in
`config/depth_camera.json` forward/up, regenerate the world, re-run §0, re-run this.
*If D2 AIM, RANGE, OFFAX or AXES fails* stop. Do not record anything with this mount, and do not
"fix" it by adjusting the georef — read `config/depth_camera.json`'s `mount_pose_rpy_note` first.
*If the sweep says the bird was still detected at the longest swept range*, that is a floor, not the
horizon — and on 2026-09-06 it did. **Do not chase it by raising `clip_far_m`.** The bookable number
is bounded by the frame corner, not by the prefix, so a longer clip buys the booking gate nothing;
what it does buy is clutter, measured from this render's own geometry: at far 60 m the ground
returns finite from row ~374 and the ±6 m threat band's lower edge shares rows with it only below
**23.2 m**, but at far 100 m the ground goes finite from row ~319 and that overlap grows to
**39.6 m** — i.e. across essentially the whole 33.59 m horizon the booking gate needs at 5 m/s.
Raising the clip walks mapped ground into exactly the band the (unbuilt) segmenter has to key on.
The clip stays **60 m**. If a later mission speed genuinely needs more horizon, the cheaper lever is
a **tighter bound, not a longer clip**: re-derive the corner from the threat band's own worst pixel
rather than the frame's (**50.8 m** at R = 47.6) — a `predict_forward_lead.py` change with its own
ADR entry, worth ~4 m.

---

## 3. Gate D4 — the booking gate, on live numbers

Read the intrinsics off the LIVE `camera_info` — **six numbers, one message**: `K[0]`=fx, `K[4]`=fy,
`K[2]`=cx, `K[5]`=cy, plus `width` and `height`:

```bash
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && export FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml && ros2 topic echo --once /fg/depth/camera_info'
```

Then, on the host:

```bash
python3 scripts/predict_forward_lead.py --speed <the speed the mission will actually fly> \
        --fx <K[0]> --fy <K[4]> --cx <K[2]> --cy <K[5]> \
        --width <width> --height <height> \
        --acq-range-m <D3 BOOKABLE> --acq-optical-prefix-m <D3 OPTICAL PREFIX> \
        --json eval/results/booking_gate_$(date -u +%Y%m%dT%H%M%SZ).json
```

**`--acq-range-m` takes D3's BOOKABLE number, never the optical prefix** (ADR-020 am. 1);
`--acq-optical-prefix-m` records the prefix it was clamped *from*, so the artifact says on its face
that the horizon it authorised was clamped and against which bound (schema **1.2**). It is
informational — it cannot make a failing gate pass — but a `--acq-range-m` *longer* than its prefix
is a refusal, because a clamp cannot run in that direction. **All six intrinsics come from the
command above — the REAL bringup's `/fg/depth/camera_info`.** §2's check-world copy printed the same
`fx`/`cy` and the config agrees to every digit, but that world is a copy with two edits in it; "the
copy agreed" is corroboration, not the source.

**Measured 2026-09-06, at 5.0 m/s on the live intrinsics** (`fx` 520.0058046927554,
`fy` 520.0058046927553, `cx` 320, `cy` 240, 640×480 — re-verified against the new six-number CLI
2026-09-07, every number unchanged):

| `--acq-range-m` | exit | verdict |
|---|---|---|
| **46.0** (D3 bookable) | **0** | **PASS and BOOKABLE** — margin **1.780×** (3.832 s available vs 2.152 s needed), corner headroom **3.4 %**, required horizon **33.59 m** → 27.0 % headroom |
| 58.0 (optical prefix) | 1 | FAIL on `acquisition_within_corner_far_clip` **and nothing else** — 58.0 > 47.56 m, headroom −18.0 %; the lead margin was 2.245× |

That contrast is the whole reason the bookable number is clamped: hand the gate the prefix and it
refuses a sensor that is fine, at **every** speed, because the corner check does not depend on speed.

**The six intrinsics are a SET, and the frame size is part of it.** `fx` sets the acquisition range,
`fy`+`cy` set the threat-band coverage, and all six set the frame-corner far-clip bound
`far ÷ |ray|`, whose ray runs to the **farthest** corner: `max(cx, W−1−cx)/fx` and
`max(cy, H−1−cy)/fy`. So a live number beside a config number is an answer assembled from two
cameras, and any part of the set is a refusal. The bound formula matters more than it looks — until
2026-09-07 it used `cy/fx` with `cx` from config, and at a live `cy` of 120 it published a **50.14 m**
horizon where the true one is **44.05 m**, i.e. exit **0 BOOKABLE** on a 50 m acquisition range
(QA probe C). Live `width`/`height` are also cross-checked against `config/depth_camera.json`: the
world SDF is *generated* from that config, so a mismatch means the wrong camera is being read, and
that is a refusal too — not something to reconcile by preferring one.

Everything unusable is a refusal, never a verdict: an `--acq-range-m` beyond the 60 m far clip (or
`inf`), a non-finite or non-positive speed, an insane focal length, a non-integral `width`, a
principal point outside the frame. **Exit 2 is never a statement about the sensor.**

**Exit codes are the whole gate:**

| exit | meaning | what to do |
|---|---|---|
| **0** | PASS **and BOOKABLE** — margin ≥ 1.3× on live-measured inputs | book the dodge flight |
| **1** | FAIL | **do not book.** Slow the mission or lengthen the horizon; the failing check names which |
| **2** | REFUSAL — no `--speed`, part of the six-number live set, live `W×H` ≠ config, or any unusable number | fix the input; **nothing was decided about the sensor** |
| **3** | PASS but **NOT BOOKABLE** — config-sourced inputs, live intrinsics **without** `--acq-range-m`, or a `--sweep` in which some row passes | you skipped D3. The design is sound; the sensor is unmeasured |

A `--sweep` in which **no** row passes exits **1**, not 3 — "PASS but not bookable" printed beside
"no mission speed in this range passes" would be one code with two meanings. The unconditional
property is the other one: **a sweep can never exit 0.**

**Do not book on exit 3.** ADR-019 tripwire (a) exists to end failure theater: the next take is
*designed to pass*, and "if it books under this gate and still fails, that is a plant-model finding
→ Ruling 003, not another re-fly."

**The MARGIN is monotone in both knobs. The VERDICT is not — sweep, do not assume.** *(corrected
2026-09-07; the sentence here used to read "slower is never worse, a longer horizon is never worse"
and was used to justify passing "the safe end" when unsure, where the safe end is in fact the
failing one.)*

* **Margin falls monotonically with mission speed** on the uncapped plant — verified 0.2–14.0 m/s
  at 0.05 steps on the live set, **zero inversions**. But **below ~3.5 m/s the mission-speed cap
  lengthens `t_req`, and the verdict does not include that**: at 0.6 m/s the tool prints its own
  `NOTE: flying at 0.6 m/s caps the plant's speed and MOVES t_req to 5.326 s — the verdict above
  uses the uncapped 1.792 s. Re-derive before booking.` Slower is not automatically safer.
* **A longer `--acq-range-m` is NOT monotone in the verdict.** Margin rises with it, and then the
  frame-corner check fails: on the live set **47.5 → exit 0, 47.6 → exit 1** (headroom −0.1 %), and
  **58.0 → exit 1** at −18.0 %, which is the contrast the table above prints. Past **47.56 m**
  today, a longer horizon is a FAIL.

And `predict_bird_visibility.py` still has to be re-run at whatever speed you pick — its response
ADR-016 am. 1 measured non-monotone in a third way. The two gates do not substitute for each other.

---

## 4. Gate D5 — the depth stream reaches ROS 2 **under flight load**, on one clock

The depth frame is 640×480×4 = **1,228,800 B** = **19 SHM fragments**, the same size class as the
fused `/fg/ndvi/image` the ADR-013 am. 9 Fast DDS fix was sized for. That fix gave the 8 MiB segment
**128 fragment slots**. The BRIDGE participant's per-tick load was **27 fragments** when that was
sized — rgb 15 + nir 10 + two single-fragment `camera_info` — i.e. **4.74 ticks** of burst headroom
(128 ÷ 27). Depth adds **19**, taking it to **46 fragments/tick** and **2.78 ticks** (128 ÷ 46) — a
**41 % cut in burst headroom**. (The `ndvi_node`'s own 19-fragment fused frame is a *separate*
participant with its own segment and is not in that 46; each participant costs its full 8 MiB in
`/dev/shm`, which is why the container runs `--shm-size=1g`.) Still positive, and until 2026-09-06
**unmeasured**: depth was the first stream added to that bus since it was sized.

> **MEASURED 2026-09-06 — D5 PASS: 132 / 132 = 1.000** over a **30 s wall window**
> (`test-flight` #2, scripted, started 19:54:00Z), encoding `32FC1`, header stamp on the **gz sim
> clock** (sec 61.6), SHM segments all 8,413,728 B. *(132 frames in 30 **wall** seconds is ~4.4 Hz
> against a 5.0 Hz sensor that ticks on **sim** time — which is exactly why the claim is the ratio
> and not the rate: `camera_info`, counted over the same window, came back at the same 132.)*
> Artifact:
> [`eval/results/depth_delivery_d5d6_20260906T195400Z.json`](../../eval/results/depth_delivery_d5d6_20260906T195400Z.json),
> flight record `eval/results/testflight_gate_20260906T195708Z.json`. **The third image stream cost
> this bus nothing measurable.** One flight, one window — it is a reading, not a distribution.
>
> **THE WINDOW WAS NOT FLOWN AT THE BOOKED SPEED.** Ground speed inside it, from the clip's own
> `poses.jsonl` (`eval/results/clips/real_flight_20260906T195307Z`, sim 61.6-88.0 s): **median
> 3.50 m/s** (n = 132, mean 3.53, min 2.29, max 4.79) — the 2-lane test mission never reaches cruise
> in a 30 s window. **Delivery at the 5.0 m/s booking speed is UNMEASURED**, and is owed by the
> dodge flight. Do not quote 1.000 as a delivery figure for the booked mission.

**THE METRIC IS A ROS-SIDE PAIR: `depth frames ÷ camera_info frames`, counted over the SAME window.**
Numerator and denominator both cross the bridge and the DDS transport; `camera_info` is one
fragment and the depth frame is nineteen, so the ratio isolates *fragment loss* from *the sensor
not ticking* — exactly what `red_frames / camera_info_frames` does for NDVI, and for the same
reason: a raw count is not a rate, and a rate is not a delivery fraction.

**Do not count on the gz side.** The 2026-09-06 run measured `timeout 30 gz topic -e … | grep -c` at
**0** frames on `/fg/depth/image` and **68** on `/fg/depth/camera_info` while the ROS side was
taking 132 of each: `timeout` kills `gz topic -e` before its stdout buffer flushes, so the gz-side
number is an artifact of the pipe, not of the renderer. Those commands used to be step 1 of this
section; they are **deleted**, not merely warned about, because a "production" figure that reads
0/132 invites exactly the wrong conclusion about a bus that is in fact delivering everything. The
gz-side stream is still worth an eyeball (`gz topic -e -t /fg/depth/image --no-arr | head`), just
never a denominator.

**Measure it under load, not at idle.** An idle bringup has nothing else competing for the render or
the segment; the failure mode is a starved bus mid-flight.

**Getting the window in the air — the launcher prints no ARMED cue** *(2026-09-06 lesson: there is
no line to grep for and no pane that announces takeoff).* Trigger on altitude instead, from inside
the container, and only then start the counters:

```bash
# 0. watch the altitude; /ap/pose/filtered is BEST_EFFORT, and it only exists inside the container.
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && \
  export FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml && \
  timeout 180 ros2 topic echo --qos-reliability best_effort --field pose.position.z /ap/pose/filtered'
```

Start the 30 s window once **z > 8 m** and the vehicle has settled onto a lane. *(2026-09-06: fired
at z = 14.67 m, 19:53:48Z, plus a 12 s settle — window 19:54:00Z.)*

```bash
# 1. THE METRIC: both counts over the SAME window, started together and waited on together.
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && \
  export FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml && \
  timeout 30 ros2 topic echo --once=false --field header.stamp.sec /fg/depth/image 2>/dev/null \
  | grep -c .' > /tmp/ros_depth_count &
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && \
  export FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml && \
  timeout 30 ros2 topic echo --once=false --field width /fg/depth/camera_info 2>/dev/null \
  | grep -c .' > /tmp/ros_info_count &
wait; echo "depth=$(cat /tmp/ros_depth_count)  info=$(cat /tmp/ros_info_count)"

# 2. encoding + ONE CLOCK DOMAIN: 32FC1, and a header stamp in Gazebo SIM seconds.
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && \
  export FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml && \
  ros2 topic echo --once --field encoding /fg/depth/image && \
  ros2 topic echo --once --field header.stamp /fg/depth/image'

# 3. the SHM segments must all be ~8.4 MB; a 549,408 B one means a participant missed the profile.
docker exec fieldguard-sim bash -c 'ls -l /dev/shm/fastrtps_* | grep -v port'
```

*Expect:* `depth = info`, i.e. a ratio at or near **1.00** over the window; `32FC1`; a stamp that
matches the `gazebo` pane's sim time; and every sized segment at **8,413,728 B**. **Record the
ratio, the window length and the trigger as an artifact beside the booking-gate JSON** — a delivery
claim with no denominator is the `cells_imaged` mistake in a new place.

*Two things the 2026-09-06 run corrects in the expectations above:* `/clock` is **not bridged**, so
there is nothing to `ros2 topic echo /clock` — the evidence that the stream is on the sim clock is
the header stamp itself (sec 61.6 at a 30 s wall window). And `ls -l /dev/shm/fastrtps_*` printed
**`8x0 8x8413728`**: eight full-size segments, not the four this section predicted, beside eight
zero-length companions that `grep -v port` does not filter. The count is not the assertion — **no
segment at the 549,408 B default** is, and none was.

*If depth frames are a fraction of `camera_info` frames:* the segment is saturating, and this is
the first new stream on that bus since it was sized. Raising `segment_size` in
`config/dds/fg_fastdds.xml` is the lever, and it is a **pinned-config change**: it needs a
`docs/DECISIONS.md` entry and a re-run of the ADR-007 delivery gates, not a quiet edit.
*If `ros2 topic echo` reports nothing at all:* remember that `DepthCameraSensor::Update` returns
early when **nothing is subscribed** on the gz side. "No frames" can mean "no subscriber", not only
"broken sensor" — check the bridge pane printed six `Creating GZ->ROS Bridge` lines. (The same
laziness is why this camera costs the CI smoke job nothing but is **not** free in flight: the bridge
subscribes, so every flight pays the render.)

## 5. Gate D6 — flight pitch vs the threat band *(measured 2026-09-06 at 3.50 m/s, NOT at the booked 5.0; no coded pass/fail)*

The mount is **level** (rpy 0,0,0) because at fy 520.006 / cy 240 the vertical half-FOV is 24.775°,
so a level camera contains the whole ±6 m threat band at every range beyond **13.05 m** — well
inside the 17.8–38.8 m horizon the replay requires, and a down-tilt would push the band's *upper*
edge out to 22.74 m for 10° of tilt. *(13.05, not the 13.00 this section used to print: the band
fits only when its **smaller** half-extent fits, and `min(cy, H−1−cy)` is 239 rows below the axis,
not 240 — `band_covered_from_m` takes the `min()` as of 2026-09-07. Five centimetres, changing no
verdict, fixed because it is the same optimistic off-by-one as the frame-corner rule.)* What host
math cannot know is that **a copter pitches nose-down to cruise, and this camera pitches with it.**

With the vehicle flying a lane at the booked speed, record the pitch — **and record the ground
speed the window was actually flown at, from the clip's own `poses.jsonl`.** A pitch without its
speed is a number you cannot reason from; that is the 2026-09-06 lesson below.

```bash
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && export FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml && timeout 30 ros2 topic echo --qos-reliability best_effort /ap/pose/filtered --field pose.orientation'
```

Convert to pitch and check the band still fits: a nose-down pitch θ moves the covered band to
`[R·tan(24.775° − θ)` above, `R·tan(24.775° + θ)` below`]`. At the 5 m/s recommendation the pitch
should be small; **measure it, do not pre-compensate with an invented tilt.** If the upper half of
the band is pushed outside the required horizon, that is an ADR-020 amendment with a number in it,
not a config tweak.

**MEASURED 2026-09-06 — the level mount survives the worst attitude this airframe was seen to fly.**
Convention `pitch = asin(2(w·y − z·x))`, **negative = nose-down**. Same artifact as §4
([`depth_delivery_d5d6_20260906T195400Z.json`](../../eval/results/depth_delivery_d5d6_20260906T195400Z.json)):

| | pitch | flown at |
|---|---|---|
| **WHOLE FLIGHT — the load-bearing pair** | **−12.498° / +11.240°** (n = 524, sim 34.2-138.8 s) | ground speed up to **10.58 m/s** |
| the D5 window: median | −1.175° (n = 388 from `/ap/pose/filtered`; the clip's own quaternions, n = 133, give the identical −1.175 median) | **3.50 m/s** median |
| the D5 window: mean / extremes | −0.60° / −7.71° / +8.56° | **3.50 m/s** median |

**Read the whole-flight pair, not the window's.** At **−12.5°** the ±6 m band's upper edge sits at
`R·tan(24.775° − 12.5°)` = **0.218·R** = **7.3 m** above the optical axis at the 33.59 m horizon the
booking gate needs at 5 m/s — **still in frame, with 1.3 m to spare.** That is the claim this gate
supports: the level mount holds through the worst attitude on record. Nothing here reopens
`mount.tilt_rejected_note` — **the mount stays level.** *(The artifact flags the axis convention as
unconfirmed; only the magnitudes are load-bearing, and the band stays in frame in either direction.)*

**THE PITCH AT 5.0 m/s IS UNMEASURED.** The window was flown at **3.50 m/s median ground speed —
slower than the booked 5.0**, so its −1.18° median is a lower bound on the booked pitch
**MAGNITUDE**: the vehicle pitches *at least* that far nose-down at 5 m/s, and possibly much
further. It is not a ceiling. *(Say MAGNITUDE. On a signed quantity where more nose-down is more
negative, "a lower bound on the pitch" reads as pitch ≥ −1.18°, i.e. no more nose-down than −1.18°
— which is the retracted claim word for word.)* The only thing bounding the booked pitch today is
the flight's own worst attitude, −12.50°, and the 1.3 m of spare frame that leaves. Get the real number off the dodge flight —
the first flight that flies the booked speed — and record it beside its **measured ground speed**,
never beside the word "cruise".

---

## 6. What this session owes the record

1. The D3 number **from a run that exited 0**, in a `docs/DECISIONS.md` ADR-020 amendment — it is
   the first *measured* property of this sensor and it supersedes the host-side 46.80 m bound. A
   number from any other exit code is not a property of this mount and does not go in the record.
   **DONE 2026-09-06 → ADR-020 amendment 1: optical prefix 58.0 m (a FLOOR), BOOKABLE 46.0 m.** The
   rule stays standing: re-run this gate after any mount or config change, and the record takes the
   *bookable* number.
2. The booking-gate JSON (`eval/results/booking_gate_<UTC>.json`) — the artifact that authorises
   the dodge flight. It carries a top-level `verdict` with `pass`, `bookable` and `exit_code`;
   `scripts/predict_forward_lead.validate_report` refuses to write a malformed one and the host test
   reads it back. **DONE 2026-09-07 →
   [`eval/results/booking_gate_20260907T064136Z.json`](../../eval/results/booking_gate_20260907T064136Z.json):
   exit 0, PASS and BOOKABLE at 5.0 m/s, margin 1.780×, schema 1.2 with the clamp recorded.** It is
   written from the real bringup's `camera_info`, so it belongs to the flight session, not the §2
   run. **It is an authorisation with an expiry: it authorises 5.0 m/s on 46.0 m and nothing else.**
3. **DONE (D5) 2026-09-06 → `132 depth ÷ 132 camera_info = 1.000` over a 30 s wall window**, 32FC1,
   gz sim clock, all SHM segments 8,413,728 B —
   [`eval/results/depth_delivery_d5d6_20260906T195400Z.json`](../../eval/results/depth_delivery_d5d6_20260906T195400Z.json),
   flight record `eval/results/testflight_gate_20260906T195708Z.json`. **Still owed: the same ratio
   at the booked 5.0 m/s** — this window's median ground speed was 3.50 m/s (§4).
4. **DONE (D6) 2026-09-06 → −1.175° median in the 3.5 m/s window; −12.498° / +11.240° over the whole
   flight (n = 524, up to 10.58 m/s)**, same artifact, band still in frame with 1.3 m to spare.
   **Still owed: the pitch at the booked 5.0 m/s** (§5).
   *(Both test-flights that produced these passed their own gate:
   `eval/results/testflight_gate_20260906T195115Z.json` — 256 s / 681 frames / 415 cells — and
   `..._20260906T195708Z.json` — 673 frames / 415 cells. Their `bird_drive_*_applied.jsonl` tracks
   were **deleted** from `eval/results/`: they are test-flight artefacts, not takes, and the CPA
   gate auto-discovers applied tracks, so leaving them turns `check_live_flight_log`'s `TestCli` red
   and makes the next real take's CPA binding ambiguous by default.)*
5. **STILL OPEN.** Anything gz did differently from the source-verified expectations in
   `config/depth_camera.json` — those citations are checkable, and a correction is worth more than
   a green tick. **After two render sessions the answer is: nothing about the sensor.** Every
   source-read claim gz was asked about held — the derived `camera_info` topic name, the 32FC1
   encoding, `-inf`/`+inf` outside the clips, and the far cull on Euclidean slant against a stored
   Z-depth (now measured twice: on-axis at D2 CULL, off-axis by probe 5's bracket). **What was
   wrong both times was ours:** the harness (run 1's teleport into a physics-less world) and this
   runbook's own gz-side counters (`timeout` killing `gz topic -e` before its buffer flushed, §4).
   Keep the item open anyway — it is the only line here that asks the question in the direction that
   can still surprise us.

## 7. Known gaps — deliberate, named, not blind spots

* **The segmenter does not exist.** `DepthDetectionSource` carries the contract (guards, counters,
  stamp passthrough, un-projection, the range refusal) and takes the segmenter as a constructor
  argument; the detector lands next session with perception. Nothing on this list flies a detection.
* **`avoidance_node` is not wired to it.** Deliberate: that node is flight-software's, and wiring a
  detection source before its detector exists would be a seam nobody can test.
* **The depth camera is NOISELESS** — gz-sensors' own default, kept rather than guessed at, and
  recorded as a transfer gap (proposed TG-6) beside `eval/point_mass.py`'s unmodelled dynamics. It
  makes the sensor optimistic in the same direction the plant model already is.
* **NO MATERIAL DISCRIMINATOR, AND CLUTTER MERGING — the segmenter session owns both.** A depth
  camera cannot tell a tree from a bird; it only knows *near*. Tree canopies enter this frame from
  about **24.4 m** and the ground from about **32.5 m**, both **inside** the 33.6 m horizon the
  booking gate needs at 5 m/s, so the forward frame is full of mapped clutter for exactly the range
  band that matters. Two distinct problems live here:
  - *Coincidence.* A detection whose ray lands inside a surveyed tree's geofence is ANNOTATED
    (`Detection.static_map_hint`, plus a counter) and **never suppressed** — hiding a bird hovering
    beside a known tree is the failure mode, and a missed obstacle is a safety bug where a wasted
    dodge is not. Nothing consumes the annotation yet; the policy still decides alone.
  - *Merging, which annotation does NOT solve.* QA's scenario: a bird 6 m below cruise at 20 m
    projects into the ground band, an `isfinite` mask joins it to the ground component, and the
    `max_area` filter then deletes the merged blob entirely — the bird disappears, silently. The D3
    sweep cannot see this because its scene is deliberately clutter-free and sky-backed. **The
    segmenter must key on depth DISCONTINUITY against the local background, not on `isfinite`**, and
    must be scored against a cluttered scene before any dodge is booked on it.
* **`MIN_RESOLVING_RADIUS_PX = 2.0` was calibrated on `ndvi_detect.detect_blobs`** — the *NDVI*
  detector's morphology — because that is the only scored morphology this repo has. The depth
  segmenter is TBD and may not use it. **Re-measuring the floor against whatever the segmenter
  actually runs is booked for the segmenter session**, and until then the 46.80 m host bound
  inherits an assumption from a different detector. (D3 measures the render, so it is unaffected —
  but D3 also runs `detect_blobs`, so the same re-measure applies to the sweep's criterion.)
  **2026-09-06 sharpens this: the re-measure is now mandatory, because the render does not do what
  the floor was calibrated on.** The footprint plateaus at a 4×4 px patch instead of shrinking with
  range, and at that plateau the component survives on **area** (16 px vs `DEFAULT_MIN_AREA` 6),
  not on a 2 px radius — the printed `r_apparent 2.00 px` coincides with `MIN_RESOLVING_RADIUS_PX`
  arithmetically, not causally. A floor measured on synthetic discs describes the discs; the
  segmenter's floor must be measured **against this render**, and against a *cluttered* one, where
  the bird is finite-against-finite rather than finite-against-`+inf`.
* **Whether the nadir bird-visibility gate is still a precondition for a dodge take** is an open
  question for the ADR, not for this runbook: with detection on the forward sensor,
  `predict_bird_visibility.py` gates the NDVI *map*, not the dodge. It is still a real gate for the
  survey half; do not silently retire it.
