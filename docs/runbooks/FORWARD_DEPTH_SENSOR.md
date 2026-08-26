# Forward depth sensor — the commissioning session *(runbook; ADR-019 / Council Ruling 002)*

The forward depth camera exists because nadir cannot buy detection lead time at **any** speed:
ADR-017 amendment 1 measured `speed_at_which_nadir_becomes_safe_mps = None` — bird_0 closes at its
own 6.002 m/s, and nadir's 2.480 m forward horizon would have to be 17.8–38.8 m. So detection moves
to its own aperture while the NDVI survey pair stays exactly where four green gates left it.

**This is a COMMISSIONING session, not a flight.** Nothing here arms, and no dodge take may be
booked until §3 exits 0. One Docker session, ~20 minutes of gates, host quiet.

> **Status: NEVER RUN.** Everything below is authored and verified host-side (the static geometry
> gate at 23/23, the booking-gate arithmetic, 80 host tests). Verified offline is not rendered.
> Numbers marked *(host)* are predictions to compare the render against, not results.

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
single-speed design check. Exit 0 is unreachable in every mode until §3's live inputs exist; that
is a pinned property of the tool, not a convention.

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

Run it **alone**, before or instead of a bringup: it launches its own second rendering Gazebo.

```bash
docker exec -it fieldguard-sim bash /workspace/fieldguard/scripts/verify_depth_mount_geometry.sh
```

It parks the vehicle at (60, 30, 15) nose-east — clear of both tree rows, open sky along the optical
axis — and teleports `bird_0` to known ranges dead ahead.

| gate | assertion | *(host)* prediction |
|---|---|---|
| **D2 CLEAR** | no finite depth pixel nearer than 1.0 m | 0 px — the airframe mesh is the one thing host math cannot settle, so this is the real news |
| **D2 RANGE** | nearest finite depth at the 10 m on-axis capture | **9.820 m** (10 − the 0.18 m bird radius), ±0.20 m. A nadir mount from this pose reads **15.000 m** |
| **D2 AIM** | blind near-cluster centroid vs the principal point | (320, 240), ≤ 15 px |
| **D2 OFFAX** | the reading at pixel (560, 120) is **Z-depth, not slant range** | **19.84 m**, not the 22.33 m slant — 2.49 m apart against a 0.20 m tolerance |
| **D2 AXES** | that same target lands where u+=right / v+=down predicts | (560, 120), ≤ 15 px |
| **D2 NEAR** | bird parked 0.25 m ahead → literal pixel values at the principal point | `['-inf']`, **not** `0.1` |
| **D2 FAR** | some of the 10 m frame is `+inf` (sky past the far clip) | ~80 % of pixels |
| **D2 CULL** | greatest finite Z-depth = far ÷ \|ray\| **at its own pixel** | ~57.8 m at \|ray\| 1.038, **not** 60.0 |
| **D3** | greatest range at which the bird survives the adopted morphology | **46.8 m** *(host pinhole bound)* — the measurement is the point |

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
number would promote the booking gate to exit 0 on noise. **Write the printed number down.**

*If D2 CLEAR fails* the aperture is occluded by the airframe: move `mount.mount_pose_xyz_rpy` in
`config/depth_camera.json` forward/up, regenerate the world, re-run §0, re-run this.
*If D2 AIM, RANGE, OFFAX or AXES fails* stop. Do not record anything with this mount, and do not
"fix" it by adjusting the georef — read `config/depth_camera.json`'s `mount_pose_rpy_note` first.
*If the sweep says the bird was still detected at the longest swept range*, that is a floor, not the
horizon: raise `SWEEP_RANGES` in the script and the `clip_far_m` in the config, and re-run.

---

## 3. Gate D4 — the booking gate, on live numbers

Read `fx` off the LIVE `camera_info` (it is `K[0]`), not off the config:

```bash
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && export FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml && ros2 topic echo --once /fg/depth/camera_info'
```

Then, on the host:

```bash
python3 scripts/predict_forward_lead.py --speed <the speed the mission will actually fly> \
        --fx <K[0] from above> --cy <K[5] from the SAME message> --acq-range-m <D3> \
        --json eval/results/booking_gate_$(date -u +%Y%m%dT%H%M%SZ).json
```

**`--fx` and `--cy` are a SET.** `fx` sets the acquisition range and `cy` sets the threat-band
coverage, so a live `fx` against a config `cy` is a 2×-optimistic answer assembled from two
different cameras — the tool refuses (exit 2) rather than mixing them. Anything unusable is a
refusal too: an `--acq-range-m` beyond the 60 m far clip (or `inf`), a non-finite or non-positive
speed, an insane focal length. **Exit 2 is never a statement about the sensor.**

**Exit codes are the whole gate:**

| exit | meaning | what to do |
|---|---|---|
| **0** | PASS **and BOOKABLE** — margin ≥ 1.3× on live-measured inputs | book the dodge flight |
| **1** | FAIL | **do not book.** Slow the mission or lengthen the horizon; the failing check names which |
| **2** | REFUSAL — no `--speed` | measure the speed; the tool will not guess one (ADR-016) |
| **3** | PASS but **NOT BOOKABLE** — config-sourced inputs | you skipped D3. The design is sound; the sensor is unmeasured |

**Do not book on exit 3.** ADR-019 tripwire (a) exists to end failure theater: the next take is
*designed to pass*, and "if it books under this gate and still fails, that is a plant-model finding
→ Ruling 003, not another re-fly."

The gate's speed response is **monotone** (slower is never worse, a longer horizon is never worse) —
unlike the nadir bird-visibility predictor, whose response ADR-016 am. 1 measured NON-monotone. So
`predict_bird_visibility.py` still has to be re-run at whatever speed you pick; the two gates do not
substitute for each other.

---

## 4. Gate D5 — the depth stream reaches ROS 2 **under flight load**, on one clock

The depth frame is 640×480×4 = **1,228,800 B** = **19 SHM fragments**, the same size class as the
fused `/fg/ndvi/image` the ADR-013 am. 9 Fast DDS fix was sized for. That fix gave the 8 MiB segment
**128 fragment slots**. The BRIDGE participant's per-tick load was **27 fragments** when that was
sized — rgb 15 + nir 10 + two single-fragment `camera_info` — i.e. **4.74 ticks** of burst headroom
(128 ÷ 27). Depth adds **19**, taking it to **46 fragments/tick** and **2.78 ticks** (128 ÷ 46) — a
**41 % cut in burst headroom**. (The `ndvi_node`'s own 19-fragment fused frame is a *separate*
participant with its own segment and is not in that 46; each participant costs its full 8 MiB in
`/dev/shm`, which is why the container runs `--shm-size=1g`.) Still positive, **and unmeasured**:
depth is the first stream added to that bus since it was sized.

**Measure it under load, not at idle.** An idle bringup has nothing else competing for the render or
the segment; the failure mode is a starved bus mid-flight. Run the survey (or `test-flight`), and
capture a **ratio with a denominator** — a raw count is not a rate and a rate is not a delivery
fraction:

```bash
# 1. gz-side production vs ROS-side delivery over the SAME window, both as COUNTS.
#    `--no-arr` keeps gz from dumping 1.2 MB of pixels per message onto your terminal.
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && \
  timeout 30 gz topic -e -t /fg/depth/image --no-arr 2>/dev/null | grep -c "^header"' \
  > /tmp/gz_depth_count &
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && \
  export FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml && \
  timeout 30 ros2 topic echo --once=false --field header.stamp.sec /fg/depth/image 2>/dev/null \
  | grep -c .' > /tmp/ros_depth_count &
wait; echo "gz=$(cat /tmp/gz_depth_count)  ros=$(cat /tmp/ros_depth_count)"

# 2. the camera_info control: small, RELIABLE, one fragment. It is the denominator that says
#    "the sensor ticked N times", exactly as red_frames/camera_info_frames does for NDVI.
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && \
  export FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml && \
  timeout 30 ros2 topic echo --once=false --field width /fg/depth/camera_info 2>/dev/null \
  | grep -c .'

# 3. encoding + ONE CLOCK DOMAIN: 32FC1, and a header stamp in Gazebo SIM seconds.
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && \
  export FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml && \
  ros2 topic echo --once --field encoding /fg/depth/image && \
  ros2 topic echo --once --field header.stamp /fg/depth/image'

# 4. the SHM segments must all be ~8.4 MB; a 549,408 B one means a participant missed the profile.
docker exec fieldguard-sim bash -c 'ls -l /dev/shm/fastrtps_* | grep -v port'
```

*Expect:* `depth_frames / camera_info_frames` at or near **1.00** over the flight window, `32FC1`,
a stamp that matches the `gazebo` pane's sim time, and four ~8,413,728 B segments. **Record the
ratio and the window length as an artifact beside the booking-gate JSON** — a delivery claim with no
denominator is the `cells_imaged` mistake in a new place.

*If the ROS-side count is a fraction of the gz-side count:* the segment is saturating, and this is
the first new stream on that bus since it was sized. Raising `segment_size` in
`config/dds/fg_fastdds.xml` is the lever, and it is a **pinned-config change**: it needs a
`docs/DECISIONS.md` entry and a re-run of the ADR-007 delivery gates, not a quiet edit.
*If `ros2 topic echo` reports nothing at all:* remember that `DepthCameraSensor::Update` returns
early when **nothing is subscribed** on the gz side. "No frames" can mean "no subscriber", not only
"broken sensor" — check the bridge pane printed six `Creating GZ->ROS Bridge` lines. (The same
laziness is why this camera costs the CI smoke job nothing but is **not** free in flight: the bridge
subscribes, so every flight pays the render.)

## 5. Gate D6 — cruise pitch vs the threat band *(measurement, no pass/fail yet)*

The mount is **level** (rpy 0,0,0) because at fy 520.006 / cy 240 the vertical half-FOV is 24.775°,
so a level camera contains the whole ±6 m threat band at every range beyond **13.00 m** — well
inside the 17.8–38.8 m horizon the replay requires, and a down-tilt would push the band's *upper*
edge out to 22.74 m for 10° of tilt. What host math cannot know is that **a copter pitches nose-down
to cruise, and this camera pitches with it.**

With the vehicle flying a lane at the booked speed, record the pitch:

```bash
docker exec fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && export FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml && timeout 30 ros2 topic echo --qos-reliability best_effort /ap/pose/filtered --field pose.orientation'
```

Convert to pitch and check the band still fits: a nose-down pitch θ moves the covered band to
`[R·tan(24.775° − θ)` above, `R·tan(24.775° + θ)` below`]`. At the 5 m/s recommendation the pitch
should be small; **measure it, do not pre-compensate with an invented tilt.** If the upper half of
the band is pushed outside the required horizon, that is an ADR-020 amendment with a number in it,
not a config tweak.

---

## 6. What this session owes the record

1. The D3 number, in a `docs/DECISIONS.md` ADR-020 amendment — it is the first *measured* property
   of this sensor and it supersedes the host-side 46.80 m bound.
2. The booking-gate JSON (`eval/results/booking_gate_<UTC>.json`) — the artifact that authorises
   the dodge flight. It carries a top-level `verdict` with `pass`, `bookable` and `exit_code`;
   `scripts/predict_forward_lead.validate_report` refuses to write a malformed one and the host test
   reads it back.
3. The §4 delivery **ratio with its denominator and window length** (depth frames ÷ camera_info
   frames, under flight load) — the first measurement of this bus since a third image stream joined
   it.
4. The measured cruise pitch from §5.
5. Anything gz did differently from the source-verified expectations in
   `config/depth_camera.json` — those citations are checkable, and a correction is worth more than
   a green tick.

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
* **Whether the nadir bird-visibility gate is still a precondition for a dodge take** is an open
  question for the ADR, not for this runbook: with detection on the forward sensor,
  `predict_bird_visibility.py` gates the NDVI *map*, not the dodge. It is still a real gate for the
  survey half; do not silently retire it.
