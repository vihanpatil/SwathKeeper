# SwathKeeper — Decision Log (ADR-lite)

*(Project renamed FieldGuard → SwathKeeper 2026-08-18, ADR-011. Entries below keep their original
wording — "FieldGuard" in an older ADR is historically accurate, not stale.)*

Owner: `tech-lead` (with `product-lead` for scope calls). **Every non-trivial choice goes here** with
the alternative rejected and a one-sentence reason. Per the playbook's escalation rule, when two
roles disagree the `product-lead` wins for v1 **and the disagreement is recorded here as a tradeoff.**
This log is the engineer's interview script for "why did you build it this way?"

Format per entry:

```
## ADR-NNN: <title>   (YYYY-MM-DD, status: accepted | superseded | proposed)
#   An accepted decision that still depends on unproven live behaviour reads
#   `ACCEPTED — confirmation-pending`, and flips to `ACCEPTED — CONFIRMED live <date>`
#   the day a gate proves it. Decision bodies are APPEND-ONLY: corrections and
#   gate results land as a dated `### ADR-NNN amendment (<date>, <what>)` block at
#   the end of this file — never as an edit to the decision text above.
Decision: <what we're doing>
Alternative(s) rejected: <what we didn't do>
Why: <one to two sentences the engineer can say out loud in an interview>
Owner / roles involved:
```

---

## ADR-000: Build FieldGuard entirely in simulation (2026-07-27, accepted)
Decision: Develop the whole system in sim (Gazebo + ArduPilot SITL + ROS 2); no live hardware in v1.
Alternative(s) rejected: Fly on the single real NDVI-camera drone. Rejected — hardware team is
temporarily unavailable to add sensors, and sim lets us iterate on the hard autonomy problem safely
and reproducibly.
Why: Simulation is the honest, correct choice for iterating on safety-critical reactive avoidance —
and it lets us also simulate a second-sensor config to quantify sensor ROI, which hardware can't.
Owner / roles: product-lead, tech-lead, robotics-sim-engineer.

## ADR-001: Geofence trees as known static obstacles from a pre-flight boundary survey (2026-07-27, accepted)
Decision: Treat tree rows as known static obstacles from a pre-flight boundary survey; reserve the
perception/avoidance loop for genuinely unplanned dynamic obstacles (birds).
Alternative(s) rejected: Detect trees at runtime too. Rejected — ag operators already map field
boundaries in advance, so this is a legitimate real-world assumption, and it cleanly isolates the
actual hard problem (unplanned dynamic obstacles) instead of blurring it with static-map building.
Why: It mirrors how real ag operations work and focuses engineering effort on the differentiator.
Owner / roles: tech-lead, flight-software-engineer.

## ADR-002: v1 replanning = "avoid, return to next waypoint"; full coverage-debt reconciliation is a stretch goal (2026-07-27, accepted)
Decision: Ship the simplest correct avoidance-then-resume for v1; document full coverage-debt
reconciliation (requeue every missed cell) as an explicit stretch goal.
Alternative(s) rejected: Build full reconciliation up front. Rejected — it risks blocking v1 on the
hardest sub-problem; shipping the simple version first keeps the core loop demoable on schedule.
Why: Protects the deadline while keeping the harder version as documented, defensible interview material.
Owner / roles: product-lead, tech-lead, flight-software-engineer.

---

## ADR-003: NDVI-vs-RGB detection approach  (2026-08-04, status: ACCEPTED — **criterion 3 CLOSED 2026-08-23, verdict ADOPT on the real render** (amendment 7): per-bird-track FNR 0.000 on measured labels, precision 0.708 / recall 0.850, every bird detected before closest approach. The 2026-08-21 attempt that returned EVIDENCE INSUFFICIENT is amendments 1-3 and is superseded, not deleted. Still open: criterion 2's independent RGB pixel study, and the −0.61 real-render threshold stays PROVISIONAL at n=20)
Decision: Detect directly on the **NDVI-rendered frame itself** (approach (a), NDVI-direct), faithful
to the single-NDVI-camera hardware (ADR-000). The synthetic-RGB pass (b) is **retained but not as the
detection path** — it becomes the NDVI+RGB comparison arm that quantifies what a second sensor buys.
No trained model is justified yet: the classical-CV blob baseline already clears the safety bar, so
any future model must beat it on the same `eval/` harness to earn its place (pre-empts scope creep).
Deciding numbers (spike clip `sim/spike/out/spike_seed42`, seed 42, 30s@10fps, 3 birds, blob baseline):
  - (a) NDVI-direct: precision 0.445, recall 0.981, **FNR 0.019, per-bird-track FNR 0.000**
  - (b) synthetic RGB: precision 1.000, recall 0.981, **FNR 0.019, per-bird-track FNR 0.000**
  Decision rule (spike §3) fires for (a): per-bird FNR 0.000 ≤ 0.10 AND frame FNR within 0.10 of (b)
  (gap 0.000) → fidelity wins the precision tiebreak. The feared failure mode (bird over bare low-NDVI
  soil → false negative) did NOT occur: caught 12/12 visible frames, birds read negative NDVI cleanly
  below soil (~0.15). (a)'s precision gap is explained, not mysterious: 66/66 false positives are ONE
  static clutter feature (zero random-noise FPs), suppressible later by the static-obstacle-map
  sanity-check + blob motion-tracking — a wasteful dodge is cheap, a missed bird is not.
Alternative(s) rejected: (b) detect on a synthetic RGB pass. Rejected as the detection path — it would
make the headline demo depend on a sensor the real drone doesn't have (an interview liability), and it
was no safer here (identical FNR), so there is no safety reason to pay the fidelity cost.
Why: We detect on the exact frame the real NDVI camera produces, so nothing about the perception demo
has to be walked back — and the numbers show the NDVI-only signal catches every bird as reliably as
RGB does, so fidelity costs us nothing but easily-suppressible extra dodges.
Open follow-up (do not silently forget): the spike clip is a **SYNTHETIC stand-in, not a real Gazebo
render** (`meta.json synthetic:true`) — the numbers validate the eval harness and give a strong first
signal but do NOT yet validate against the real render. The framing call is made **now** (default (a)
was never in real danger of falsification), but ADR-003 must be **re-confirmed by re-running
`eval/run_spike.sh` on the real Gazebo NDVI render** before it is treated as fully validated.
Owner / roles: perception-ml-engineer (decided on metric), tech-lead (recorded).
Amendment 1 (2026-08-21, criterion 3 — the real-render re-run, on the demo take
`eval/results/clips/real_flight_20260821T045848Z`): **the re-run EXECUTED cleanly end to end and
produced NOTHING TO SCORE. Criterion 3 is NOT met. This is neither a confirmation nor a refutation
— it is an empty measurement, and it is recorded as one.**
  * **The number: 0 visible bird-boxes over 454 frames.** `eval/annotate_real_clip.py` labelled
    454/454 with 0 refusals (ADR-012 amendment 1 doing its job — 280 frames predate the driver and
    label at the spawn pose rather than being flagged unshippable), and `eval/label_from_sim.py`
    then projected every bird through the oriented camera model: `454 frames, 0 visible bird-boxes`.
    So precision, recall, FNR and per-bird-track FNR are all **undefined** on this clip against the
    synthetic bars (0.445 precision, 0.000 per-bird-track FNR). Both baselines emitted 0 detections;
    both would have been unscoreable anyway.
  * **Why, and it is not throughput.** Nadir camera at 15 m over birds at 6 / 8 / 11 m AGL leaves
    depths of 9 / 7 / 4 m, so the FOV footprint *at bird altitude* is only 11.1×8.3 / 8.6×6.5 /
    4.9×3.7 m — against a **15 m boustrophedon lane pitch**. The footprint tiles the *ground* plane
    (18.5×13.8 m) and does **not** tile the bird-altitude plane. bird_0 patrols x=20, a fixed 5.0 m
    from lane x=15, i.e. systematically just outside frame on every pass. Closest any bird came:
    **14.15 m** slant range, ≈341 px outside the image edge (bird_2, frame 279). More frames cannot
    fix this; only mission or world geometry can. Verified twice independently (a from-scratch
    projection, and the harness's own `label_from_sim.py`), both returning in-frame counts 0/0/0.
  * **What the clip DOES establish — the separability premise survives, with a wider margin than the
    spike.** The real render reproduces ADR-007's Gate-2 band arithmetic to three decimals: soil
    ρ_nir 0.212 with ρ_red 138/255 predicts NDVI −0.437, and the clip's modal soil cell is
    **−0.437687** (311 of 410 imaged cells); canopy ρ_nir 0.854 with ρ_red 52/255 predicts +0.614
    and the clip's **raw NDVI pixel maximum is +0.6145**. `eval/results/gate2_summary.json` (996
    frames, 3,646 bird pixels, real render) keeps ADR-003's class ordering intact — canopy +0.531 >
    trunk −0.026 > soil −0.429 > **bird −0.789** — with a bird-vs-soil gap of **0.360** on the real
    render against ~0.23 synthetic. **What broke is the threshold VALUE, not the hypothesis.** The
    0.05 default was chosen below the *synthetic* soil (0.15); against real soil at −0.4377 the
    `ndvi < thresh` mask passes **100 % of pixels on 438 of 454 frames** (307,200 px → one component
    → discarded by `max_area=5000`), which is why (a) returned zero detections. On this render the
    threshold belongs near the bird/soil midpoint, ≈ **−0.55 to −0.61**. That is a recalibration,
    and it stays **unverified** until a clip exists with a bird actually in frame.
  * **Three harness defects found, all of which would have written a WRONG number into the record
    rather than failing** (all three fixed in this change, with `tests/fieldguard_planning/
    test_score_evidence.py` pinning them):
    1. **`eval/score.py` decided ADR-003 on an EMPTY ground truth.** With TP=FP=FN=0 every rate
       guard yields 0.000, the decision rule reads four zeros as a clean sweep, and it printed
       `-> ADOPT (a) NDVI-direct`. Reproduced live on this clip's real artifacts against the pre-fix
       file: same inputs, `ADOPT` before, `EVIDENCE INSUFFICIENT` after. A rate needs a denominator,
       so `evidence_shortfall()` now checks the denominator (≥1 visible bird-frame, and every bird
       in the clip seen at least once) *before* the rates are consulted, and refuses rather than
       deciding. This is the defect that matters most: it is the one that would have closed ADR-003
       on zero evidence, silently, for anyone who read the last line of `run_spike.sh`.
    2. **`eval/label_from_sim.py` never derived `range_m` on real clips**, so `score.py`'s
       closest-approach lookup hit its `1e9` fallback for every record and `min()` returned the
       *first* visible frame. That silently redefines the project's safety-critical **per-bird-track
       FNR** from "detected before closest approach" to "detected on first sight" — on exactly the
       real clips it exists to score. Now derived from the same camera position the projection uses.
    3. **`eval/baseline_rgb.py` KeyError-ed on real clips** (unconditional `d["rgb_path"]`; real
       clips carry RGB on a subset — 243 of 454 here), killing `run_spike.sh` outright.
  * **Not fixed, deliberately, and now flagged in the file: `baseline_rgb.py`'s birdness hypothesis
    is inverted for this world.** "Bright + achromatic" is a property of the *synthetic* clip's
    white birds. In `farmguard_field.sdf` the birds are **dark** (`color_rgba` 0.12 / 0.30 / 0.18)
    against **bright** soil — measured modal soil pixel (138, 161, 115), min-channel **115 > the
    110 threshold**, so every real frame saturates into one whole-image blob. Flipping the polarity
    is one character and a wrong thing to do blind: the threshold must also be recalibrated to this
    render's absolute scale, and there is no visible bird to calibrate against yet. Criterion 2's
    comparison arm is therefore **also** blocked on the same missing clip, not on code.
  * **Status unchanged: ACCEPTED — confirmation-pending.** The default was never in danger of
    falsification here; it simply was not tested. Cheapest unblocks, in order: (1) **lower the birds
    in `config/birds/farm_world_birds.json`** — at 2-3 m AGL the nadir footprint is 14.8-16.0 m, i.e.
    ≈ the lane pitch, giving near-continuous cross-track opportunity; their altitudes are pure
    config and nothing in ADR-001/ADR-003 requires 6/8/11 m; (2) **an offline pre-flight predictor**
    — commanded waypoints × bird waypoints × the same `ndvi_georef` projection answers "will any bird
    be in frame, and for how many frames?" with no Docker session, and would have called this flight
    dead before it was flown; (3) recalibrate both thresholds against the first clip that has one.

Amendment 2 (2026-08-21, perception-ml-engineer — unblock (2) BUILT, unblock (3) done for the NDVI
arm): **`scripts/predict_bird_visibility.py`.** Mission file × bird config × the same `ndvi_georef`
projection → "will any bird be in frame, and for how many frames", in **0.8 s on the host, no
container**. It backtests against the flown clip, and it **sharpens amendment 1's diagnosis into two
different problems that need two different fixes.**
  * **Validated by reproduction, not by inspection.** Replaying the demo take's own `poses.jsonl`
    through this tool returns that flight's measured numbers exactly: **0 bird-visible frames of
    454**, closest approach **14.15 m** slant (bird_2, frame 275), nearest miss **341.2 px** outside
    the image edge (bird_2, frame 279) — the three figures amendment 1 quotes, which were produced
    by a different implementation (the pre-refactor `label_from_sim.project_bird_oriented`, before it
    became a view of the shared primitive). That reproduction is the cross-check. It also agrees with
    today's `label_from_sim.py` `visible` flag on **all 1,362 frame×bird decisions** (test
    `test_agrees_with_the_ground_truth_labeller_frame_by_frame`) — worth pinning, but scoped
    honestly: since the refactor both call the same `project_world_point`, so what that test pins is
    the apparent-size and in-frame predicate on real poses, not the projection underneath it. (The
    refactor itself was verified behaviour-preserving on those same 1,362 decisions: no decision
    flips, max deviation 2.9e-11 px from float reassociation.) Predicting the same mission from
    **pure config, no clip**, at the rate that take actually sampled (0.407 Hz — 53 airborne frames
    in 127.8 s) gives per-bird medians **0 / 0 / 1**, i.e. **under one expected bird-visible frame in
    the whole flight**. The measured zero was the most likely single outcome, not bad luck.
  * **Correction to amendment 1's arithmetic (verdict unchanged, the miss is BIGGER).** bird_0's 5.0 m
    off-lane distance was compared against 4.31 m, the half-footprint of the **640-px** image axis.
    Per ADR-007's mount extrinsic that axis lies **along** the flight direction; the cross-track half
    is the 480-px axis, **3.23 m** at bird_0's 7 m depth. Measured miss at its best moment: **136 px
    = 1.81 m** outside the frame edge, not ~0.7 m.
  * **"More frames cannot fix this" is true of bird_0 and ONLY bird_0.** Swept across all 55
    driver-start offsets (the bird driver's t0 is anchored to `fly_pipeline.sh`'s 10 m altitude gate,
    but where that lands relative to lane timing is uncontrollable), at the 5 Hz sensor tick:

    | bird | alt | depth | footprint at bird alt | frames in view min/med/max | offsets seen | limited by |
    |---|---|---|---|---|---|---|
    | bird_0 | 8 m | 7 m | 8.6 × 6.5 m | **0 / 0 / 0** | **0/55** | **STRUCTURAL** |
    | bird_1 | 11 m | 4 m | 4.9 × 3.7 m | 0 / 3 / 5 | 37/55 | timing |
    | bird_2 | 6 m | 9 m | 11.1 × 8.3 m | 0 / 11 / 26 | 46/55 | timing |

    bird_1 and bird_2 **do** cross the lanes — rarely (0.3 % / 1.2 % of ~900 opportunities), but at
    every-cadence-dependent rates, so **throughput moves them and geometry does not have to**. Only
    bird_0 is unreachable at any rate. The tool reports this as `limited_by`, because "lower the
    birds" and "fix the recording pipeline" are different work and amendment 1 read as though only
    the first could help. (bird_2's median is high for a reason worth knowing: its north component is
    2.94 m/s against a 3 m/s lane speed, so on a northbound lane it nearly *surfs* the frame.)
  * **One projection, now literally.** `ndvi_georef.project_world_point` is the single
    world-point→(u, v, depth) primitive; the heatmap stitch (`world_enu_to_pixel`), the GT labeller
    (`label_from_sim.project_bird_oriented`) and this predictor are all thin views of it, so a
    projection bug cannot disagree between the map, the labels and the prediction. The in-frame
    predicate is likewise pinned equal to `spike_common.clip_box`, by test.
  * **Alternatives rejected:** a Monte-Carlo sampler over random bird phases (a deterministic sweep
    over one offset is complete here — the birds share one driver, so their phases relative to each
    other are fixed by the config, and each period divides the swept span); simulating the ROS 2
    stack offline (the question is geometry, and geometry does not need a container).
  * **Honest limits.** Constant speed, instant turns, no wind, no avoidance dodges, no occlusion, and
    frames spread uniformly — whereas real frames are bursty and cluster where the vehicle is slow
    (only 29 of the take's 53 airborne frames were at survey altitude off the takeoff point, with
    gaps to 18.4 s). Every one of those makes the model **optimistic**, which is the safe direction
    for a check whose job is to say "don't bother". `--speed` is a real knob, not a constant: the
    take's own poses show cruise chords to 9.2 m/s against a 3.91 m/s median.

Amendment 3 (2026-08-21, perception-ml-engineer — the NDVI threshold, unblock (3) half-done):
**`eval/baseline_ndvi.py`'s threshold is now resolved per render from the clip's `meta.json`, and
the real-render value is `-0.61`, PROVISIONAL.**
  * **Value:** the midpoint of the two classes the mask must separate, from the committed 996-frame
    real-render evidence in `eval/results/gate2_summary.json` — bird **−0.7888**, soil **−0.4285**,
    midpoint **−0.6087**. Pinned to that file by `test_baseline_ndvi_threshold.py`, which recomputes
    the midpoint rather than trusting the constant.
  * **What it fixes, measured on the demo take's 454 real frames:** at the synthetic `0.05`, `ndvi <
    thresh` masks **≥99.9 % of pixels on 438 of 454 frames** (mean masked fraction 0.9986) —
    independently reproducing amendment 1's figure — so every frame collapses to one whole-image
    component that `max_area=5000` discards: **0 detections from saturation**. At `-0.61` the mask is
    **empty on all 454** (soil at −0.4377 sits above it), so the same 0 detections now means *there
    was nothing there*, which is the truth for this clip.
  * **PROVISIONAL, and it stays that way until a bird-visible clip exists.** It is calibrated on
    per-class pixel means, never against precision/recall, because criterion 3's blocker is still
    open. The tool prints that caveat on every real-render run and writes `thresh_provisional: true`
    into its output; a test fails if the word ever leaves the module.
  * **Synthetic stays at 0.05, untouched** — that is the number ADR-003 was decided on and
    `check_spike_regression.py` re-checks; a per-clip resolution (not a flag) keeps `run_spike.sh`
    byte-identical in behaviour while making the real-render default correct by default.
  * **`baseline_rgb.py`'s inverted birdness is deliberately NOT touched** (amendment 1's reasoning
    stands: flipping polarity blind, with no visible bird to calibrate the absolute scale against,
    would replace a known-wrong number with an unknown-wrong one). Week 6.

---

## ADR-004: Pin the simulation toolchain versions  (2026-07-27, status: ACCEPTED)
Confirmed by `robotics-sim-engineer` against ArduPilot's `ardupilot_gz` docs and the
`aerial-autonomy-stack` reference (both pin the same stack); no landscape shift as of mid-2026.
Exact pins live in `CLAUDE.md` "Pinned versions" and the bringup steps in `docs/runbooks/SIM_BRINGUP.md`.
Note: `ardupilot_gazebo` uses the `ros2` branch (not `main`), and ArduPilot firmware tracks `master`
(not a stable Copter tag) because the AP_DDS/ROS 2 bridge surface tracks master — the one remaining
open item is capturing the exact firmware commit SHA once the Week 1 build is green.
Decision: pin **Gazebo Harmonic (LTS)** + ArduPilot's **`ardupilot_gz`** ROS 2
integration on **ROS 2 Humble** (Ubuntu 22.04), matching ArduPilot's officially documented and
CI-tested stack, run inside a **Docker/Ubuntu container** (the dev machine is macOS, where this
stack is not practically supported natively).
Alternative(s) rejected:
  (a) **ROS 2 Jazzy + Harmonic** — newer LTS, longer support horizon, but ArduPilot's docs and CI
      primarily exercise Humble, so it carries more first-run setup risk. Kept as the fallback.
  (b) **Native macOS install** — rejected; Gazebo + ArduPilot SITL + ROS 2 aren't practically
      supported on macOS, and fighting that would burn the Week 1-2 gate.
  (c) **Gazebo Garden** — rejected; Harmonic is the current LTS and the release ArduPilot targets.
Why: the Week 1-2 gate is "get a mission flying," so following ArduPilot's most-documented,
most-tested combination minimizes setup risk on the critical path; longevity is secondary for a
time-boxed portfolio build.
Owner / roles: robotics-sim-engineer (research + confirm exact branch/tags), devops-reliability-engineer
(container image), tech-lead (recorded). Promote to `accepted` with exact pins written into
`CLAUDE.md` once robotics-sim-engineer confirms compatibility.

## ADR-005: Enable AP_DDS explicitly + lock the /ap/* topic/service/frame contract to the pinned ArduPilot SHA   (2026-08-04, status: ACCEPTED — CONFIRMED live 2026-08-05)
**CONFIRMED 2026-08-05 (Week-3 Gate 2, `docs/archive/WEEK3_VALIDATION.md`):** all 18 `/ap/*` topics enumerated
below appeared on the running bridge, exactly matching this source-verified list (14 publishers + 4 `/ap`
subscribers; the 5th subscriber is the bare `/clock`). **Correction to the original enablement claim:**
AP_DDS is **compiled OUT of SITL by default** (`-DAP_DDS_ENABLED=0`) — SITL must be built with
`sim_vehicle.py --enable-DDS` first, or the `DDS_ENABLE` param does not even exist and no `/ap/*` topics
appear. The param file alone is NOT sufficient. (An earlier draft implied DDS was compiled-in by default;
that conflated the `AP_DDS_ENABLED` compile gate with the `DDS_ENABLE` param value — see docs/runbooks/SIM_BRINGUP.md §6b.)
Decision: Build SITL with `--enable-DDS`, **then** enable the bridge via an explicit param file
(`config/sitl_params/dds_udp.parm`: DDS_ENABLE=1, DDS_UDP_PORT=2019), loaded through
`sim_vehicle.py --add-param-file` rather than relying on `ardupilot_gz_bringup`'s launch file. Keep DDS_USE_NS=0 (compiled default) so
names stay a flat `/ap/<name>`. Lock the following `/ap/*` interface — verified directly from source at
ArduPilot commit `9895756d874ec9128d50918f6747a83706f4e221` (V4.8.0-dev, CLAUDE.md "Pinned commit
SHAs"), every `#if AP_DDS_*_ENABLED` gate checked, not guessed — as the contract Week 3-4
perception/planner ROS 2 nodes code against:
  Publishers: /ap/time (builtin_interfaces/Time), /ap/navsat (sensor_msgs/NavSatFix, frame_id=GPS
  instance index as string), /ap/tf_static (tf2_msgs/TFMessage, base_link->GPS_<i>), /ap/battery
  (sensor_msgs/BatteryState, frame_id=battery instance index), /ap/imu/experimental/data
  (sensor_msgs/Imu, frame_id=base_link_ned), /ap/pose/filtered (geometry_msgs/PoseStamped,
  frame_id=base_link **but content is ENU position relative to EKF/home origin — REP-105 mislabeling,
  treat content not frame_id as authoritative**), /ap/twist/filtered (geometry_msgs/TwistStamped,
  frame_id=base_link; linear=world ENU, angular=body-frame — two frames under one label), /ap/airspeed
  (ardupilot_msgs/Airspeed), /ap/rc (ardupilot_msgs/Rc), /ap/geopose/filtered
  (geographic_msgs/GeoPoseStamped), /ap/goal_lla (geographic_msgs/GeoPointStamped), /ap/clock
  (rosgraph_msgs/Clock), /ap/gps_global_origin/filtered (geographic_msgs/GeoPointStamped, WGS-84 EKF
  origin — the anchor for pose/filtered's ENU frame), /ap/status (ardupilot_msgs/Status).
  Subscribers: **/clock** (rosgraph_msgs/Clock — note: **NOT /ap/clock**, an absolute-path special
  case in the topic table), /ap/joy (sensor_msgs/Joy), /ap/tf (tf2_msgs/TFMessage), /ap/cmd_vel
  (geometry_msgs/TwistStamped), /ap/cmd_gps_pose (ardupilot_msgs/GlobalPosition).
  Services (ArduPilot=server): /ap/arm_motors, /ap/mode_switch, /ap/prearm_check,
  /ap/experimental/takeoff, /ap/set_parameters, /ap/get_parameters.
  Source: libraries/AP_DDS/{AP_DDS_Topic_Table.h, AP_DDS_Service_Table.h, AP_DDS_Client.h,
  AP_DDS_Client.cpp, AP_DDS_config.h, AP_DDS_Frames.h} @ ardupilot commit
  9895756d874ec9128d50918f6747a83706f4e221.
Alternative(s) rejected:
  (a) Use `ardupilot_gz_bringup`'s default DDS enablement (auto-loads dds_udp.parm + dds_use_ns.parm,
      auto-spawns micro_ros_agent). Rejected — that launch file hardcodes its own world path (already
      rejected project-wide, sim/README.md / docs/runbooks/SIM_BRINGUP.md), and its default DDS_USE_NS=1 would
      namespace every topic under /v<sysid>/ for no benefit in a single-vehicle project.
  (b) Trust the compiled-in ENABLED_BY_DEFAULT=1 and skip explicit enablement. Rejected — a SITL
      instance's eeprom.bin (persisted on our named Docker volume) keeps whatever DDS_ENABLE value was
      saved the first time that param existed; a later compiled-default change does not retroactively
      re-enable an existing instance. Explicit + reproducible beats implicit.
  (c) Take topic/frame names from ArduPilot's ROS 2 wiki/docs. Rejected — ROADMAP already flags these
      names have moved between versions; the reproducibility anchor is the pinned commit SHA, not a
      version-unspecified doc page.
Why: The Week 3-4 avoidance loop is a ROS 2 control path that consumes ArduPilot telemetry and issues
guided commands over these exact names/types/frames, so I locked the contract by reading AP_DDS source
at the exact commit we build — that way perception and planner nodes can be written in parallel against
names that won't silently drift, with a concrete re-verification target the day we bump the SHA.
Open follow-up (do not silently forget): this contract is verified from **source at the pinned SHA**,
but the live bridge only comes up in the human Docker run — so the actual `ros2 topic list` /
`ros2 topic hz` confirmation against a running SITL+micro-ROS-agent is still owed. Confirm the topics
appear with these names/types before treating ADR-005 as fully validated (same pattern as ADR-003's
"re-confirm on the real Gazebo render").
Owner / roles: flight-software-engineer (verified source + drafted), tech-lead (records).

## ADR-006: Reactive-avoidance executor = AUTO->GUIDED->AUTO, we own the maneuver policy   (2026-08-05, status: ACCEPTED — CONFIRMED live 2026-08-05)
**CONFIRMED 2026-08-05 (Week-3 Gate 3, `docs/archive/WEEK3_VALIDATION.md`):** with `MIS_RESTART=0`, AUTO→GUIDED→AUTO
resumed the interrupted leg (reached #3, took control heading to #4, handed back → resumed at #4, continued
#5→#8), no restart at #1. The resume mechanism the executor depends on works on the real stack.
Decision: On a dynamic bird detection during the AUTO boustrophedon mission, **our** executor node
takes control by switching AUTO -> GUIDED (via the `/ap/mode_switch` service, ardupilot_msgs/ModeSwitch,
locked in ADR-005), commands a **single pre-vetted avoidance setpoint** in GUIDED, then switches
GUIDED -> AUTO to resume coverage. Verified mechanism, all cited @ pinned ArduPilot commit
`9895756d874ec9128d50918f6747a83706f4e221`:
  - **Maneuver command (primary):** a discrete guided position setpoint on `/ap/cmd_gps_pose`
    (ardupilot_msgs/GlobalPosition, WGS-84, anchored to `/ap/gps_global_origin/filtered` from ADR-005).
    Alternative primitive `/ap/cmd_vel` (geometry_msgs/TwistStamped, world-ENU) is also valid but is a
    velocity we'd have to integrate to safety-check; a position target is the thing the safety gate
    actually evaluates, so it is the v1 primitive. **Both are honored only in GUIDED + armed:**
    `AP_DDS_ExternalControl.cpp::handle_velocity_control` / `handle_global_position_control` ->
    `AP_ExternalControl_Copter::set_linear_velocity_and_yaw_rate` / `set_global_position`, each gated by
    `ready_for_external_control()` = `copter.flightmode->in_guided_mode() && copter.motors->armed()`
    (ArduCopter/AP_ExternalControl_Copter.cpp @ SHA). This reconciles the ADR-005 note that `/ap/cmd_vel`
    is a subscriber: it is a live input, but ArduPilot silently drops it unless we are in GUIDED.
  - **Frame the executor MUST command in:** world-**ENU** with `header.frame_id = "map"`. Unlike
    `/ap/pose/filtered` (ADR-005: content authoritative, frame_id lies), for these command topics the
    `frame_id` **is honored** as a real switch: `handle_velocity_control` transforms `"map"` ENU -> NED
    as `{linear.y, linear.x, -linear.z}`, whereas `"base_link"` is treated as body frame via
    `ahrs.body_to_earth()` (AP_DDS_ExternalControl.cpp @ SHA). Sending `base_link` by mistake would fly a
    body-frame dodge. Command `"map"`/ENU.
  - **Resume mechanism:** re-entering AUTO runs `ModeAuto::run()` -> `mission.start_or_resume()`
    (ArduCopter/mode_auto.cpp @ SHA), which calls `resume()` unless `MIS_RESTART==1`
    (AP_Mission.cpp::start_or_resume @ SHA). We **pin `MIS_RESTART=0`** in the param file (same explicit
    discipline as ADR-005) so AUTO deterministically resumes the leg it was flying and continues to the
    **same next waypoint** it was navigating to when interrupted — exactly the ADR-002 v1 behavior, no
    index manipulation required.
  - **Why no waypoint-index juggling:** AP_DDS at this SHA exposes **no mission-current service** (ADR-005
    table: mode_switch/arm/prearm/takeoff/get+set_parameters only). Skipping/requeuing cells would need
    `AP_Mission::set_current_cmd` reachable only via MAVLink `MAV_CMD_DO_SET_MISSION_CURRENT` — a second
    control channel. v1 doesn't need it (natural resume suffices), which is a verified concrete reason the
    full coverage-debt reconciliation (ADR-002 stretch) is genuinely harder, not just deferred.
Safety requirement handed to flight-software (build, not decided here): the executor MUST pass the
candidate avoidance setpoint (and ideally the swept path to it) through a **3D safety gate BEFORE**
switching to GUIDED — the target must lie outside every geofenced-tree obstacle volume AND within
altitude bounds. `config`/`geofence.py` is currently **XY-only**; extend it to altitude-aware so a dodge
cannot climb/descend into a canopy or breach the ceiling (QA's `geo_avoid_into_tree` is the regression).
If the gate rejects the primary dodge, fall back to hover-in-GUIDED; never execute an unvetted maneuver.
Log every takeover (trigger detection id + AUTO->GUIDED), the maneuver target + gate verdict, and the
resume (GUIDED->AUTO + resumed waypoint) per the CLAUDE.md instrumentation rule.
Alternative(s) rejected:
  (a) Pure MAVLink mission manipulation / `DO_REPOSITION`. Rejected for v1 — it adds a second control
      channel alongside the AP_DDS bridge we already locked (ADR-005) for no v1 benefit; keep one bus.
      (It's the natural home for the ADR-002 *stretch* requeue, which genuinely needs it — noted above.)
  (b) Lean on ArduPilot's built-in object avoidance (BendyRuler/Dijkstra + `OA_*`/proximity). Rejected —
      that path is built for known-obstacle/proximity avoidance and would move the reactive decision
      **into the autopilot**, deleting the exact thing this project exists to show (priority #1); our
      differentiator is that *our* code sees, decides, and acts, and we can log and defend every step.
Why: We keep the avoidance brain in our own ROS 2 code — detect, safety-gate, switch to GUIDED, command
one vetted setpoint, then hand control back to AUTO which resumes the mission on its own — because that
is the whole point of the project (priority #1), and every takeover, maneuver, and resume is a line in a
log I can walk an interviewer through.
Open follow-up (do not silently forget): the interface is verified from **source @ the pinned SHA**, but
the live behavior — that GUIDED accepts our setpoint mid-mission and AUTO with `MIS_RESTART=0` actually
resumes to the intended waypoint — must be **confirmed in the human Docker run** before ADR-006 is fully
validated (same pattern as ADR-003 real-render and ADR-005 live-topic checks; batch all three).
Owner / roles: tech-lead (decided + verified source@SHA), flight-software-engineer (builds executor +
3D geofence), perception-ml-engineer (detection trigger), qa-safety-reviewer (`geo_avoid_into_tree`).

## ADR-007: Produce the dual-band NDVI frame with an RGB camera (Red) + Gazebo's thermal sensor repurposed as synthetic NIR; NDVI computed in a ROS 2 node   (2026-08-05, status: ACCEPTED — CONFIRMED live 2026-08-18; see the ADR-007 amendments below)
Decision: Render the two NDVI bands as **two co-located Gazebo Harmonic sensors on one rigid nadir
mount**, and compute the index in ROS 2, not in the render:
  - **Red band** = the **R channel of a standard `type="camera"` (R8G8B8) sensor**. That same RGB
    image is *also* the ADR-003 comparison arm (NDVI+RGB), so the Red-band source doubles as the
    second-sensor arm — zero extra cameras for the comparison.
  - **NIR band** = a **`type="thermal"` sensor (L16) repurposed as synthetic NIR**. Gazebo's thermal
    camera reads a *per-object scalar signature you author in SDF* (via `gz-sim-thermal-system`'s
    `<temperature>` / `<heat_signature>` on each visual), **independent of visible color and
    lighting** — which is exactly the "per-model reflectance property so vegetation reads high-NIR,
    soil/water/birds low" that option (a) calls for, delivered by a **first-class documented sensor
    instead of a hand-written shader**. Each world material carries a `<temperature>` that encodes its
    NIR reflectance, calibrated into the sensor's `[min_temp,max_temp]` so the bridged `mono16` maps
    **linearly to NIR reflectance ρ_nir∈[0,1]** (the one calibration knob; lives in the camera pkg,
    not this ADR).
  - **NDVI** is computed in a dedicated ROS 2 node (`ndvi_node`), **not** baked into the render:
    it pairs the two bridged images by nearest sim-time stamp
    (`message_filters` ApproximateTime), rescales R/255→ρ_red∈[0,1] and mono16→ρ_nir∈[0,1], and
    publishes **NDVI=(NIR−Red)/(NIR+Red)** per pixel as `32FC1`∈[−1,1]. Rationale: Gazebo keeps
    emitting raw bands (honest), the index math stays unit-tested and offline-reproducible (the eval
    harness already consumes `float32` NDVI `.npy`), and the ROS contract is stable per ADR-005
    discipline. **Hard build requirement:** the RGB and thermal sensors MUST share identical
    intrinsics (width/height/hfov), pose (co-located nadir, matching the spike extrinsic
    `quat_wxyz=(0,1,0,0)`) and `update_rate`, so the node combines pixel-wise with no resampling.
    `use_sim_time=true`; the NDVI frame inherits the **RGB image stamp** (the georef anchor).
  - **Stale-pair guard (amendment 2026-08-05):** the node MUST enforce a **max stamp-delta of 25%
    of one frame period** when pairing Red↔NIR (default **25 ms** at the spike's 10 Hz anchor;
    scales as `0.25/update_rate`). Since both sensors share `update_rate` by construction, a correct
    pair is stamp-aligned to within render jitter and only a *dropped frame* pushes the nearest match
    toward a full period; 25% sits well above jitter yet well below the half-period point where the
    match flips to the wrong neighbor. On exceed: **drop the frame and increment a logged
    `dropped_pair` counter** (instrumentation per CLAUDE.md) rather than emit a mispaired NDVI — a
    persistently rising count is itself the signal that band rates are drifting under load.
**Locked topic/message contract** (perception + stitch code against these names, same as ADR-005):
  - `/fg/sensor/rgb/image` — `sensor_msgs/Image` (`rgb8`)  [Red band = ch0; also the NDVI+RGB arm]
  - `/fg/sensor/rgb/camera_info` — `sensor_msgs/CameraInfo`
  - `/fg/sensor/nir/image` — `sensor_msgs/Image` (`mono16`, thermal→NIR proxy)
  - `/fg/sensor/nir/camera_info` — `sensor_msgs/CameraInfo`
  - `/fg/ndvi/image` — `sensor_msgs/Image` (`32FC1`, values ∈[−1,1]) ← **authoritative frame ADR-003
    detects on and the stitch georeferences** (via ADR-005 `/ap/pose/filtered` +
    `/ap/gps_global_origin/filtered` + this stamp + `camera_info`)
  - `/fg/ndvi/camera_info` — `sensor_msgs/CameraInfo` (pass-through intrinsics for the stitch)
  - `/fg/ndvi/preview` — `sensor_msgs/Image` (`rgb8`, false-color, HUMAN-ONLY, non-authoritative)
Second-sensor comparison arm (concrete): **NDVI+RGB, reusing the RGB camera already needed for the
Red band.** A `type="depth"` camera (NDVI+depth) is a documented **stretch**, not v1 — we get the RGB
arm for free, depth costs a third sensor for no v1 detection benefit (ADR-003 already chose NDVI-direct).
Alternative(s) rejected:
  (b) Single camera + a **shader/material-encoded** synthetic NIR band. Rejected — it means writing and
      maintaining custom OGRE2 render passes/materials: clever but hard to explain and fragile against
      Gazebo rendering-engine updates, and the thermal sensor already gives the identical
      per-model-reflectance capability as a supported, documented sensor. Boring-but-explainable wins.
  (c) **Post-process synthetic NIR derived from RGB + a vegetation mask.** Rejected — the NIR would be a
      *function of the visible render*, so NDVI carries **no independent second-band information**; this
      is essentially what the Week-2 synthetic spike clip already did (`meta.json synthetic:true`), so
      choosing it would make the ADR-003 "re-confirm on the REAL render" step **circular and meaningless**
      — you'd re-validate the detector on a frame whose NIR is manufactured from its own RGB. The whole
      point of a real render is a genuinely independent NIR band; (c) throws that away.
Why: One normal RGB camera gives me the Red band and doubles as the comparison arm; I repurpose Gazebo's
thermal sensor — which reads an author-controlled per-object signature, not visible color — as an
**independent** synthetic NIR band; a small ROS 2 node combines them into a georeferenced NDVI frame.
It's a two-camera render (option (a)) built entirely from documented, first-class Gazebo sensors on the
already-proven `ogre2` Sensors system, so nothing about it is exotic to explain — and because the NIR
band is genuinely independent of the visible render, the ADR-003 real-render re-confirmation actually
tests something.
Known-honest caveat (say it out loud): this is a **synthetic sim NDVI**, not radiometric truth — Red
comes from a lit visible render while NIR is an illumination-independent scalar, so shadowed canopy can
spuriously raise NDVI. Mitigation: render with a fixed high sun + dominantly diffuse sky to suppress
shadows; if the ADR-003 re-run shows lighting artifacts break detection, fall back to authoring the
**Red band as a second thermal-style reflectance scalar** (both bands illumination-independent, matching
the spike's material-property NDVI model) — documented fallback, not built up front.
Open follow-up (do not silently forget): the render only comes up in the **human Docker run**, so the
whole mechanism is unproven live. Concrete re-verification targets (batch with the ADR-003 real-render
spike re-run + ADR-005 live-topic + ADR-006 live-resume checks — one Docker session):
  1. `ros2 topic list` shows the six `/fg/*` topics; `ros2 topic hz /fg/ndvi/image` at camera rate;
     `ros2 topic echo --field encoding` returns `rgb8`, `mono16`, `32FC1` respectively.
  2. Sample a canopy pixel vs. bare-soil vs. bird pixel on `/fg/ndvi/image`: canopy high-positive, soil
     near-zero/low, bird negative — this is the direct proof the NIR band is **independent** of RGB
     (the thing (c) cannot produce); if soil and canopy NDVI are indistinguishable the temperature
     authoring is wrong (every object returning ambient = flat NDVI).
  3. Point `eval/run_spike.sh` at the real render's output dir (drop-in per `sim/spike/README.md` schema)
     → re-confirm ADR-003 numbers hold on the real render.
  4. Confirm the pinned Harmonic build exposes the thermal sensor on `ogre2` (Sensors system already
     runs `ogre2`, world line 13-15) — thermal is ogre2-only; verify `gz-sim-thermal-system` loads.
  5. **Principal point (cx,cy) unpinned** — georef defaults cx,cy to image-center (`CameraIntrinsics.from_config`);
     CONFIRM empirically against the real `/fg/*/camera_info` once Gate 1 publishes it (log in docs/runbooks/NDVI_VALIDATION.md).
  6. **Georef anchor rule (DECIDED, from stitch build):** anchor to the **live `/ap/gps_global_origin/filtered`**
     (WGS-84 EKF origin, ADR-005) at runtime — authoritative; `config/field_polygon.json` home is used **only**
     for offline/test. `home_lat/lon/alt` is a transform param, sourced live and config-defaulted offline.
  7. **Dependency boundary (DECIDED, from stitch build):** `fieldguard_planning` stays **stdlib-only** for the
     planning/avoidance core; **numpy** is permitted **only** in the NDVI image-math modules (`ndvi_fusion.py`,
     `ndvi_georef.py`) — genuine array math, already project-blessed via `requirements-eval.txt`.
Owner / roles: tech-lead (decided + verified against Gazebo Harmonic sensor docs + ros_gz bridge),
robotics-sim-engineer (builds the two-sensor mount + per-model temperature authoring + bridge),
perception-ml-engineer (ADR-003 re-run on `/fg/ndvi/image`), flight-software-engineer (georef stitch
consumes `/fg/ndvi/*` + ADR-005 pose/origin).

## ADR-008: Hosted-runner Gazebo-render CI is unproven — the sim CI job pulls a prebuilt image and stays manual-dispatch until one green run   (2026-08-05, status: ACCEPTED; promoted to ADR 2026-08-18 from docs/runbooks/SIM_CI.md "Feasibility verdict")
Decision: Split sim CI into (1) a prebuilt GHCR image (`sim-image.yml`, built manually / on
Dockerfile change, never from scratch per push) and (2) a headless smoke-flight job
(`build-test-sim`) gated to `workflow_dispatch` until a human confirms one green run. Full
Gazebo-render CI on GitHub-hosted runners is treated as UNPROVEN, not assumed.
Alternative(s) rejected: (a) Build the Gazebo+ArduPilot+ROS 2 stack in CI per push — disqualified by
resource math (hosted runners: 4 vCPU / 14GB SSD vs the documented ≥40GB workspace); (b) assume
headless rendering works because SITL-only CI does — upstream's own evidence says otherwise:
`ardupilot_gazebo`'s CI is build/lint-only, and ArduPilot's SITL autotests fly with NO Gazebo.
Why: The teams that own these exact components don't run live Gazebo on hosted runners — that's the
strongest available signal; we bake the build into an image (fixing the resource math) and claim
green only when a run IS green. Timeboxed with a documented cut-list (docs/runbooks/SIM_CI.md).
Owner / roles: devops-reliability-engineer, robotics-sim-engineer.

## ADR-009: Real-detector evidence contract — stamped detections with a policy staleness gate; bird position from apparent-size ray, never ground-plane projection   (2026-08-18, status: ACCEPTED — wired offline 2026-08-24 (amendment 1); **CONFIRMED live 2026-08-25** on the first real-detection avoidance take, amendment 2 — both rules held, and the seam's own measurement is what found the sensor-horizon problem)
Decision: Two contract rules locked BEFORE the real NDVI-blob detector replaces the `--demo` bird on
the `detection_source` seam:
  1. **Staleness (IMPLEMENTED 2026-08-18):** `Detection.stamp_s` (same clock as the policy's new
     `now_s` argument) + `PolicyParams.max_detection_age_s`. A stale detection is treated as ABSENT
     (observable in the maneuver reason/debug), never as a live threat or a dodge constraint.
     Unstamped detections fail OPEN (current behavior) because the demo/scripted sources don't stamp
     — dropping them would silently disable avoidance in every existing runbook.
  2. **Range/altitude (CONTRACT, Week-6 implementation):** a monocular NDVI blob has no depth; naive
     ground-plane projection puts a flying bird at z=0 — OUTSIDE the ±6 m threat cylinder at 15 m
     cruise, i.e. it would SUPPRESS real threats (fail-dangerous). The detector must instead place
     the bird along the pixel ray at range Zc = f·R_phys/r_px from apparent size (physical radius
     prior ~0.15 m, the value the sim ground truth already records as `range_m`), with a
     conservative inflation factor to be tuned against GT range error on the eval harness.
Alternative(s) rejected: ground-plane projection (fail-dangerous, above); treating every in-frame
detection as at-drone-altitude regardless of size (fail-safe but dodge-happy — it would manufacture
avoidance events and wreck the coverage story); waiting for the depth-sensor comparison arm (that
arm QUANTIFIES what depth buys over this monocular estimate — it can't be the v1 dependency).
Why: The seam's data shape is a one-line change today and a three-surface breaking change after the
detector exists; and the residual monocular range error becomes the measured argument for the
second sensor — the comparison arm's whole point.
Owner / roles: tech-lead, perception-ml-engineer (Week-6 implementation), qa-safety-reviewer
(staleness + range-error scenarios).

## ADR-010: v1 NDVI stitch is OFFLINE, post-flight, over a recorded clip — not a live in-node accumulator   (2026-08-18, status: ACCEPTED — implemented, scripts/stitch_ndvi.py)
Decision: The georeferenced heatmap (Weeks 5-6 exit criterion 1) is produced by
`scripts/stitch_ndvi.py`: a recorded spike-schema clip (real render or synthetic) → per-cell mean
NDVI on the SAME canonical 2.5 m / 720-cell grid the coverage ledger uses (joinable by `cell_id`) →
`heatmap.json` + false-color `heatmap.png`. Refuses to succeed on an empty stitch (a "ran but
carries no data" result exits nonzero — same discipline as the flat-NDVI gate).
Alternative(s) rejected: live in-node stitching during flight — days of extra work and new failure
modes (pose-at-stamp buffering, partial-map states, node lifecycle) for identical exit-criterion
output; offline over a recorded flight is rerunnable and debuggable against the same committed
evidence artifact it consumes. Promotable to a live accumulator later if the dashboard ever needs
in-flight NDVI (it doesn't for v1).
Why: One Docker session must produce the demo heatmap; the runner existing BEFORE the session is
what makes that single session sufficient (record the flight → stitch on the host afterward).
Owner / roles: flight-software-engineer, tech-lead; perception-ml-engineer consumes the same clip
for the ADR-003 real-render re-run.

## ADR-011: Rename the project FieldGuard → SwathKeeper; code identifiers deliberately keep the old name   (2026-08-18, status: ACCEPTED — user decision)
Decision: The project is **SwathKeeper** (one word, capital K): "swath" is the coverage-path domain
term (one pass of a survey), "keeper" carries the thesis (the survey stays intact through dodges).
All branding, docs, agent definitions, and workflow names renamed. **Code identifiers keep the old
name**: the `fieldguard_planning` package, the `fg_`/`/fg/*` topic prefix, `farmguard_field.sdf`,
the `fieldguard-sim` image/container, and `/workspace/fieldguard` container paths.
Alternative(s) rejected: (a) FieldGuard — reads as crop security/intrusion detection; the system
protects the *survey*, not the field. (b) FieldScan — names the commodity half, inert.
(c) Renaming the code identifiers too — the `/fg/*` topic contract is embedded in ADR-007 and
partially live-verified (Gate 0), the image name is baked into every runbook and the CI chain, and
re-opening confirmed interfaces for cosmetics is churn with zero functional gain. Deferred, not
forgotten: if ever done, it's a single mechanical PR after the sim CI chain is green.
Why: The name should point at the differentiator — keeping the swath — and the rename must not
invalidate verified state three sessions before the demo.
Owner / roles: user (final call), product-lead, gtm-narrative-lead.

## ADR-012: Birds are static models driven by an external set_pose script — not SDF actors   (2026-08-18, status: ACCEPTED — verified live in-container)
Decision: The 3 scripted birds are emitted by `gen_farm_world.py` as **static `<model>`s** (sphere
visual + ADR-007 per-visual thermal, spawned at their first waypoint) and moved at runtime by
`scripts/drive_birds.py`, which piecewise-linearly interpolates the unchanged
`config/birds/farm_world_birds.json` waypoints and teleports each bird via
`/world/<world>/set_pose` at ~5 Hz (= the camera rate, so the render never sees a stale hop).
Alternative(s) rejected: (a) Keep `<actor>` + `<script><trajectory>` — **it never worked**: a
skinless actor's link-visuals never enter Harmonic's ogre2 render scene (verified live 2026-08-18,
0 bird entities in scene/info since Week 2; unnoticed because the avoidance demo injects
positions, not pixels). (b) Actor with a `<skin>` mesh — renders, but the per-visual thermal
plugin doesn't attach to actor skins, so the authored 273 K bird signature (the NIR contrast the
detector needs) is lost. (c) `gz-sim-trajectory-follower-system` — planar, force-based, built for
surface vessels; wrong tool for a 3D flight path. Trade-off accepted: bird motion now needs the
driver process running (recorded in the runbooks) and assumes RTF ≈ 1.0 (true in every runbook;
Gate 3 checks RTF).
Why: Models render and take per-visual thermal exactly like the 18 trees already proven on this
stack, the committed trajectory data stays untouched (reproducibility unchanged), and the driver
is 150 lines of stdlib instead of a new Gazebo plugin.
Owner / roles: robotics-sim-engineer, perception-ml-engineer (consumer), qa-safety-reviewer
(bird trajectories are safety-scenario inputs — interpolation is unit-tested).
Amendment 1 (2026-08-20, perception-ml-engineer, unblocking the ADR-003 re-run): **`pose_at`'s loop
wrap is FORWARD-ONLY, because the spawn pose is ground truth for every t < 0.** Birds are `<static>`
models spawned at `waypoints[0]` (`gen_farm_world.sdf_bird_model`) and `drive_birds.py` is the only
writer of their pose, so between world load and the driver's first `set_pose` each bird demonstrably
sits at its t=0 waypoint — a fact, not a convention. The unguarded `t_s % tN` violated that:
`-15 % 20 == 5` in Python, so a frame recorded 15 s before driver start was labelled at the t=5
midpoint. `eval/annotate_real_clip.py` therefore flagged all pre-driver frames unshippable
(17/105 on the last real clip), which blocked the ADR-003 real-render re-run. The clamp lives in
`pose_at` — the ONE interpolation the driver and the annotator share by import — not in the
annotator, so the bird that was moved and the bird that gets labelled cannot describe different
positions. Deliberately NOT symmetric: the far end still wraps (loop=True) or holds the last
waypoint (loop=False), because a running driver really does keep ticking `pose_at` forever, and the
run sidecar records `t0_sim_s` with no stop time — clamping the far end would invent evidence about
when the birds stopped. Frames after the driver *exits* remain undetectable and unfixed; the
annotator now prints the pre-driver lead-in so an operator can recognise a wrong sidecar by it.
Owner: perception-ml-engineer.

### ADR-007 amendment (2026-08-18, real-render findings from the first recorded flight)
1. **Sun shadows OFF in the farm world** (`gen_farm_world.py`): the thermal band (synthetic NIR)
   ignores illumination but the RGB Red band does not, so a cast shadow darkens Red alone and
   reads as FALSE VEGETATION (NDVI rises). Real NIR is reflective and darkens *with* Red in
   shadow; shadowless is therefore the MORE faithful choice for this two-band emulation, not a
   cosmetic cut. Found via the drone's own moving shadow reading NDVI-positive.
2. **Frame↔pose pairing must be stamp-based in the Gazebo clock domain** (`/fg/gz_clock` added to
   the sensor bridge; `clip_recorder.PoseBuffer`): the software render STALLS AND BURSTS
   (instantaneous RTF 0.0016–0.48), so pairing frames with poses "at arrival" mislabels a burst's
   frames by meters — the first recorded flight put 0/18 trees at their true positions while
   producing a plausible-looking map (the exact failure mode this module's tests warn about).
   Per-frame pairing residuals are now recorded and out-of-bound frames are flagged
   (`pose_pair_stale`) and SKIPPED by the stitch rather than painted somewhere wrong.

### ADR-006 amendment (2026-08-18): the executor LATCHES one dodge setpoint per encounter
ADR-006's "one 3D-vetted setpoint" is now enforced mechanically: the policy stays pure (recomputes
every tick), and the executor latches the first accepted DIVERT setpoint and re-commands it until
resume — only a candidate > 3.0 m away (RELATCH_THRESHOLD_M: above per-tick recompute drift, below
a genuine threat-motion jump) can re-latch, and only through the same 3D re-vet; every commanded
point, latched or fresh, is still re-vetted on the tick it is sent. Measured on the four safety
scenarios: ledger/debt byte-identical, setpoint churn roughly halved (turnaround scenarios re-latch
legitimately — the threat really moves). Rationale: the 2026-08-18 live flight showed the walking
setpoint on film (one ~6 m outlier). Alternative rejected: smoothing in the policy — would couple
the pure decision function to actuation history.

### ADR-007 amendment addendum (2026-08-18, evening): two live-throughput lessons
3. **High-rate topics do not belong on the sensor bridge**: bridging Gazebo's /clock (~350 msg/s)
   for the recorder starved the image serialization (fused rate collapsed ~8x). The recorder now
   streams the gz clock natively (`gz topic` subprocess); the bridge carries the four sensor
   topics only.
4. **The fusion pairing queue must tolerate arrival skew**: under host CPU load each band drops
   frames independently and arrives bursty; with `ApproximateTimeSynchronizer(queue_size=10)` a
   stamp's partner was flushed before it could pair and fused output starved to ~zero while both
   raw bands looked alive. queue_size is now 60 — this tolerates ARRIVAL skew only; the stamp
   bound (slop = 25% of frame period) is unchanged. Operational corollary in the demo runbook:
   keep the host machine quiet during recording flights.

### ADR-007 amendment (2026-08-18, late): the sensor mount was NEVER nadir — and the gate that now proves it is
5. **Mount rpy corrected (π,0,0 → −π/2,+π/2,0): the camera faced the horizon, upside-down, from
   the day it was authored.** Gazebo camera sensors look along the sensor frame's **+X axis**
   (optical z = sensor +X, u+ = sensor −Y, v+ = sensor −Z — established empirically with a
   landmark-oracle world after crash-tumbling test vehicles produced hours of self-contradictory
   probes: `<static>` on a wrapper model does NOT propagate to a nested `<include>`, so every
   in-place camera test free-fell). The original rpy was derived under a pinhole Z-forward mental
   model. Every prior gate passed anyway because every gate measured VALUES (band separation,
   rates, topics) and none measured GEOMETRY — five recorded flights were lost to it. The missing
   gate now exists: `scripts/verify_mount_geometry.sh` (physics-free world copy, vehicle parked
   1 m from a known tree, canopy centroid must land within 15 px of the
   `ndvi_georef.world_enu_to_pixel` prediction; measured 2.2 px). Run it after ANY change to the
   mount, the vehicle SDF, or the georef extrinsics. Gate 2's band-separation PASS remains valid
   (same materials, same calibration — measured from a different viewpoint).

## ADR-013: One-command bringup is a HOST-side tmux orchestrator wrapping the documented docker-exec one-liners — not a new launch path   (2026-08-18, status: ACCEPTED — implemented `scripts/fly_pipeline.sh`; flown live, `test-flight` PASS, see amendments 3-4)
Decision: `scripts/fly_pipeline.sh` (macOS host) replaces the seven copy-pasted terminal tabs of
`docs/runbooks/FULL_PIPELINE_DEMO.md` with one tmux session (`swathkeeper`), **one window per
runbook shell**, each pane running that shell's `docker exec` one-liner **byte-identical** to the runbook
(mechanically diffed: all nine, including the Shell-0 apt line). The value added is ordering and
**gates**, each with a timeout and a named failure: Gazebo's four `fg/sensor` advertisements (and a
`Failed to load a world` fast-fail) → the four `/fg/sensor` ROS 2 topics → the render-alive probe,
**mandatory every flight**, which on DEGRADED restarts Gazebo + the bridge and re-probes, max 2
retries, then aborts → UDP 2019 bound **before** SITL boots. Three deliberate carve-outs: (1) the
script **never flies** — no `arm`, `mode`, or `wp load` is ever sent; SITL stays an interactive pane
and the fly recipe plus its wait-for conditions are *displayed* in a pane beside it; (2) **birds are
altitude-gated** — the birds pane polls `/ap/pose/filtered` and execs `drive_birds.py --rate 2` only
above 10 m (`fly_pipeline.sh birds` overrides manually); (3) **teardown is recorder-first** —
`down` SIGINTs the recorder, waits up to 120 s for finalize, and only then stops the rest and prints
the host-side stitch command with the clip dir the recorder actually printed.
Alternative(s) rejected: (a) A single script that also arms and flies — rejected on the standing
`run_farm_mission.sh` reasoning: the EKF/DDS/GPS ready messages must be *watched*, and scripting
past them has already cost this project debugging time; automating the one step a human must judge
buys nothing and hides the judgement. (b) A ROS 2 launch file / in-container supervisor — it would
become a second bringup path diverging from the runbook, exactly the class of bug
`SIM_BRINGUP.md` exists to prevent; the runbook must stay the single audited source. (c) Starting
birds with everything else — ADR-012's driver adds `set_pose` service traffic that is jitter the EKF
cannot tolerate while aligning. (d) Killing all panes at once on teardown — finalize is the step
that converts raw in-flight dumps to schema PNGs and writes `meta.json`; racing it loses the clip.
Why: The bringup order and its gates were each learned by losing a flight (horizon-facing mount,
sky-flat render, agent-after-SITL, understated coverage debt) — encoding them in one command makes
the expensive lessons unskippable, while keeping every executed line diffable against the runbook
keeps the automation honest instead of opaque.
Amendment 1 (2026-08-18, qa-safety-reviewer adversarial pass, pre-flight): **every gate in this
script is a LIVENESS gate, which means none of them can tell whose processes they found.** A
bringup already running in the container — a manual runbook session, or a tmux session killed
without `down` — makes all of them pass instantly: the second Gazebo double-publishes
`/fg/sensor/*`, the second micro-ROS agent silently loses the bind on UDP 2019, and SITL attaches to
whichever agent won. All green, two worlds, nothing reproducible. Found by running `status` against
a live manual bringup: three green gates, no tmux session. `up` now refuses on any surviving
`gz sim` / `parameter_bridge` / `micro_ros_agent` / `sim_vehicle.py` / ndvi / record / birds process;
`down` reports survivors after killing the session; the DEGRADED restart path waits for the old
world's topics to disappear before respawning (killing a pane kills the `docker exec` *client*, not
necessarily the process inside the container). Also from that pass: gates now fail fast on a dead
pane instead of burning their timeout, teardown SIGINTs *every* pane of a window (the sitl window
has the recipe pane beside SITL, and `send-keys` hits whichever the user last clicked), and the
`GZ_PARTITION=mountcheck` deviation on `--gate-geometry` was **removed** — `verify_mount_geometry.sh`
already renames its world to `mountcheck` and its topics to `mountcheck/sensor/*`, so the collision
it claimed to prevent does not exist and the runbook's line now runs verbatim.
Amendment 2 (2026-08-18, product-lead decision): **one scripted flight mode exists —
`fly_pipeline.sh test-flight` — and it is a regression gate, not a flight path.** Carve-out (1)
above stands for every flight a human or a camera watches: **demo and recording flights stay
human-flown** at the MAVProxy prompt. `test-flight` runs the same `up` (every gate, render probe
included), then pipes the SITL pane to a log and **waits, bounded at 240 s, for all three readiness
lines at once** — `DDS: Initialization passed`, `EKF3 IMU… tilt alignment complete` (or `is using
GPS`), `GPS 1: detected` — before sending a single key. Scripting *past* those is the failure this
carve-out was written about; scripting *after* them is not the same act, and the difference is the
whole design. It then types the runbook recipe verbatim on the short test mission
(`config/missions/test_2lane.waypoints`, ~2 sim-min), retries once on the documented
`Arm: Accels inconsistent` after 30 s, supervises ARMED → `Reached command` → disarm inside a 25-min
budget, and on disarm runs the recorder-first `down`, the host-side stitch, and a gate record at
`eval/results/testflight_gate_<UTC>.json` (timestamps, every gate's evidence line, frames recorded,
the altitude the birds fired at, finalize confirmation, stitch exit — un-gitignored like the other
committed evidence). **The birds are deliberately NOT special-cased**: the altitude-gated watcher
firing on its own is one of the things under test. An EXIT/INT/TERM trap guarantees the teardown —
recorder-first, then `pkill -9` of any `arducopter|mavproxy|gz sim|parameter_bridge|micro_ros_agent|
fieldguard_planning|drive_birds` that outlived its `docker exec` client, then the session — and it is
armed only *after* `up` succeeds, so a run that refuses on someone else's live bringup cannot tear
theirs down. The MAVProxy sequence now has ONE source in the script (`fly_lines`), printed by the
recipe pane and typed by `test-flight`, so the two can never drift from the runbook separately.
Alternative rejected: a separate scripted-flight script — it would become the second bringup path
this ADR exists to prevent. Status: **PASSED live on its first run** — see amendment 3.
Amendment 3 (2026-08-18, live gate + qa-safety-reviewer second adversarial pass, post-flight):
**`test-flight` ran unattended and PASSED in 253 s**, gate record
`eval/results/testflight_gate_20260818T222031Z.json`, clip
`eval/results/clips/real_flight_20260818T221641Z` (48 frames, 42 with RGB, 0 stale-pose pairs),
stitch exit 0. Every claim this ADR made in the abstract now has a measurement behind it: all four
bringup gates fired against a real container (Gazebo advertisements 8 s of a 180 s budget, ROS 2
crossover 12 s of 90, render-alive probe 19 s and **passed on attempt 1**, UDP 2019 at 22 s of 60);
the DDS + EKF3 + GPS wait completed at 38 s of 240 **before a single key was sent**; ARMED
immediately, first waypoint 15 s of a 300 s budget, disarm 192 s into a 1500 s budget; **the birds
pane fired its own altitude gate at 15.0 m** having waited through `-0.0 m` and `7.52 m` — carve-out
(2) working exactly as designed, with no special-casing; and teardown reported *"recorder SIGINTed
first; finalize confirmed; session killed; survivors force-killed"*. The remaining unproven paths
are the ones that only run when something is wrong: the render-alive DEGRADED restart
(`restart_world` has never executed — the probe has never failed), `up` actually refusing an
already-running bringup (its trigger was observed, the refusal was not), `down`'s `NOTHING RECORDED`
and finalize-timeout branches, and the accels-inconsistent arm retry.
Two defects were fixed in the same pass, both in the abort path this run did not take: `TF_PROCS`
omitted `sim_vehicle`, so a force-kill would take out the `arducopter`/`mavproxy` children while the
launcher survived — and the *next* `up` would then refuse to start on the corpse the abort was
supposed to clear; and `parse_alt_m` carried a second anchor on a raw `z: <n>` line, which that pane
never prints (`zget` consumes it) and which could only ever have matched something that was not a
launch — a fail-dangerous second reading of the one field that certifies the birds flew. It now has
exactly one anchor, on `launching`. The same pass removed the redundant work the style guide asks
about: one pane capture per finalize poll instead of two, one liveness probe per restart wait
instead of two, one dpkg dependency list instead of three copies and a magic `3`, and the birds
watcher's exec line is now `$INNER_BIRDS` itself rather than a fourth copy of it — emitted payloads
verified byte-identical to the ones this run flew. `tests/test_fly_pipeline.py` is **24 green**
(no sim): a tautology-adjacent test of the deleted `z:` branch was removed, and two were added —
that `up` never emits `arm`/`mode`/`wp` (carve-out (1), the reason `up` is safe unattended), and
that the real `cmd_down` SIGINTs `record` before every other window, kills the session only after
all of them, and recovers the clip path from the recorder's own finalize line (pinned against
`record_node.py`'s literal string, confirmed by mutation).
Amendment 4 (2026-08-19, after the 2 Hz throughput measurement): **the gate judged the flight, not
the evidence — so it PASSED a run that recorded 3 frames and imaged 1 of 720 cells.** Same mission,
same 12 `Reached command` lines, same self-firing birds, stitch exit 0, `result: PASS`
(`eval/results/testflight_gate_20260819T021136Z.json`) — a 16× throughput collapse walking straight
through the pre-demo regression gate whose entire purpose is to catch one. `test-flight` now ends on
an **evidence-yield floor**, read from the clip's own `meta.json` and `heatmap/heatmap.json` (never
from a counter the launcher kept): `frames_recorded >= 12` **and** `cells_imaged >= 40`, else FAIL.
Both are **floors derived from n=2**, and the record says so — the only two test-flights that exist
are the 48-frame / 291-cell baseline (clears by 4.0× / 7.3×) and the 3-frame / 1-cell collapse
(fails both) — placed at roughly a quarter of the healthy frame count and a seventh of its cell
count: below any plausible variance on a busy laptop, above any collapse within 4× of the measured
one. They are floors, not targets, tied to `test_2lane`, and they should rise when more than one
healthy run exists; raising them off a single good number would only buy flakiness. An unreadable
yield (missing/malformed `meta.json` or `heatmap.json`) is a FAIL, not a pass — "we could not tell"
scoring green is the shape of bug this amendment exists to close. Failing *only* the floor changes
nothing about teardown: it is judged after the recorder-first `down` and the stitch have already
run, so the run still produces the full record, with `failed_phase: evidence-yield` and the failure
naming the floor, plus new `cells_imaged` / `evidence_floor` fields (record schema 1.1).
The second half of the same defect was **instrumentation**: `pane_tails["ndvi"]` is empty in *both*
committed gate records, so the `fused_count` / `dropped_pair_count` heartbeats — the one signal that
separates "fusion never fused" from "the recorder dropped what fusion produced" — have never been
captured, and that run was diagnosed by inference instead. Root cause was not capture timing (the
tails are read before `down` touches the panes) but that **`tmux capture-pane` renders the whole
pane grid**: every row below the cursor comes back as a blank line, so a quiet pane — the ndvi node
heartbeats once per 25 fused frames, the recorder every ~30 s — keeps its output at the *top* of an
80×24 grid and `tail -n 15` returns nothing but the padding underneath. The noisy birds pane tailed
fine, which is exactly why it looked like a per-pane mystery; the baseline record's `record` pane,
3 real lines followed by 12 blanks, is the smoking gun. Every pane tail now drops blank rows first
(`meaningful`/`pane_tail`), which also repairs the dead-pane tails printed by a failing gate and by
`down` — both were reading the same padding. Honesty bar: **neither fix has run live.** Both are
pinned offline in `tests/test_fly_pipeline.py` (33 green, +9: the floor evaluated against the two
committed gate records and their clips' `heatmap.json` — baseline passes, 2 Hz fails, each half
short fails, an unreadable yield fails, the floor sits strictly between the two runs it came from;
the padding filter through the capture shim; and a tripwire that no pane tail bypasses it). The
first live exercise of both is the next `test-flight`.
Amendment 5 (2026-08-20, closing amendment 4's instrumentation half at the source): the fuser's
counters now leave the pane and land in **the clip's own `meta.json`** (`"fuser"`, schema 1.2) —
`red_frames`/`nir_frames` in, `dropped_pair_count`, `fused_count` out, `last_fused_stamp_sim_s`,
against `num_frames` recorded, which is the whole detect→pair→publish→record chain in one artifact
and the difference between "fusion never fused" and "the recorder dropped what fusion produced".
Transport: a **1 Hz atomically-replaced JSON sidecar** (`eval/results/ndvi_fuser_stats.json`,
written from a timer, never from the image path), read once by `clip_recorder.finalize()`.
Alternative(s) rejected: a ROS 2 stats topic — the recorder would then need a subscription whose
messages the same starved executor delivers, on a stack where routing one extra stream has already
collapsed the image pipeline 8× (the bridged `/clock`, ADR-007 amendment above), and it dies with
the node that publishes it; a gz-transport topic — same objection plus a second bringup dependency.
The file survives whichever node dies first, which is the case that matters: a fuser killed
mid-flight leaves its last real numbers on disk, and the reader stamps them `stats_age_s` /
`stats_stale` rather than passing frozen counters off as current. A missing or malformed sidecar
reads `present: false` with a reason and **no counter keys at all** — a fabricated `fused_count: 0`
would be indistinguishable from a real starve, which is the same "we could not tell scored green"
shape amendment 4 closed in the gate. Honesty bar: **not run live** — 9 offline tests
(`test_ndvi_fusion.py` round-trip/staleness/absent/malformed/atomicity/unwritable,
`test_clip_recorder.py` the three meta outcomes); the per-band counters ride
`message_filters.Subscriber.registerCallback`, standard API this repo has not used before, so the
first flight must confirm they climb rather than sit at 0.
Amendment 6 (2026-08-21, the recording-throughput measurement — four test-flights, one variable at a
time): **the counters of amendment 5 flew, they climb, and they named the starving stage on the
first flight — the RGB *image* band, alone.** Baseline (5 Hz, unchanged config, clip
`real_flight_20260821T032316Z`): `red_frames` 73 against `camera_info_frames` 692 from the *same
RGB sensor tick*, `nir_frames` 404, `fused_count` 45, `dropped_pair_count` **0**, 17 frames
recorded. That one row falsifies the two explanations the 2 Hz collapse left standing: the camera
is not under-rendering (692 ticks arrived), and the stale-pair guard is not eating pairs (0). ~89 %
of RGB *images* died between Gazebo and the node while the small `camera_info` off the same sensor
crossed intact — a payload-size-dependent transport loss, not a render or a pairing loss. This is
exactly the artifact amendment 5 was built to produce, and it converted a lever-hunt into a
measurement.
Two levers were then measured against that baseline as a 2×2, each flight the same `test_2lane`
mission through the same gate, with `camera_info_frames` (692 / 699 / 696 / 698) as the control that
the exposure window was identical:
  * **Lever A — bridge QoS, KEPT.** The bridge's ROS publishers are RELIABLE by default
    (`ros_gz_bridge/src/factory.hpp:79` creates them with `rclcpp::QoS(rclcpp::KeepLast(queue_size))`
    — default reliability, and `queue_size` defaults to 10 per `bridge_config.hpp:37`) while *every* consumer
    — `ndvi_node`, `record_node` — subscribes `qos_profile_sensor_data`, i.e. BEST_EFFORT. The
    reliable half was retransmission machinery for ~900 KB samples no reader had asked to have
    retransmitted. **It cannot be set in the yaml at the pinned SHA** (`ros_gz` @ `9d7f8c7`):
    `bridge_config.cpp:28-36` declares the entire accepted key set — nine keys, none of them QoS —
    and `parseEntry` (`:52-169`) silently ignores anything else, so a `qos:` block there would look
    configured and do nothing. The knob is real but is a per-topic ROS *parameter*:
    `factory.hpp:66-79` attaches `rclcpp::QosOverridingOptions{Depth, Durability, History,
    Reliability}` to each publisher. Applied as
    `-p qos_overrides./fg/sensor/{rgb,nir}/image.publisher.reliability:=best_effort` on the Shell-2
    one-liner, and **verified bound before it was flown** — with the parameters the two image topics
    report `Reliability: BEST_EFFORT` and `camera_info`, deliberately left alone, still reports
    RELIABLE, which is the control proving the parameter did it. Result: `red_frames` 73 → 126
    (10.5 % → 18.0 % of ticks), fused 45 → 78, recorded 17 → 41.
  * **Lever B — the preview publish, KEPT.** `/fg/ndvi/preview` is HUMAN-ONLY under ADR-007 and
    **nothing in this repo subscribes to it**, yet every fused frame paid a colormap over 307 k px,
    two 921,600 B copies and a serialize-and-write with no reader — on the single executor whose
    next job is to drain the 921,600 B RGB subscription the baseline had just named as the starving
    stage. Now guarded by `get_subscription_count() > 0`: work removed, feature intact (rviz gets
    its preview the moment it subscribes). Result on its own: `red_frames` 73 → 113 (16.2 %), fused
    45 → 76, recorded 17 → 36 — a self-inflicted starve, confirmed by removing it.
  * **Combined (both KEPT, confirm flight `real_flight_20260821T034116Z`): `red_frames` 217 (31.1 %
    of ticks, 3.0× baseline), fused 129 (2.9×), recorded 86 (5.1×), 368 of 720 cells imaged (2.3×).**
    The end metric is superadditive because coverage is not bought by frames but by frames *spread
    along the lanes*: survey-altitude frames off the takeoff point went 6 → 42 (7×), counting
    `poses.jsonl` rows with `drone.pos_m` z > 12 m and more than 1 m of horizontal range from the
    launch point — the frames that can image an unvisited cell at all.
Nothing was reverted; both levers won independently and together. The one honest wrinkle is
**Lever A's own flight imaged FEWER cells than baseline (125 vs 158) despite 2.4× the frames** —
not a regression but a sampling accident, and worth recording because it is the trap in judging this
work by cells on n=1: that flight's extra frames landed while the vehicle was slow or stationary
(three during the climb at the origin, five stacked at the far-end turn at x≈75), where extra frames
buy almost no new cells. `cells_imaged` on a 2-lane flight is dominated by *where* a handful of
frames fall; `red_frames / camera_info_frames` is the lever's honest, position-independent metric,
and it moved monotonically on every arm. Alternative(s) rejected: raising the amendment-4 evidence
floor to match the new 86 / 368 yield — there is exactly **one** healthy run at the new config, and
amendment 4's own rule is that a floor raised off a single good number buys flakiness, not
detection. It should rise once a second full-config run exists. Also rejected: touching
`publisher_queue` / `subscriber_queue` (settable in the yaml, `bridge_config.hpp:34-37`) in the same
pass — depth is a second variable and nothing has measured it.
Amendment 6a (2026-08-21, qa-safety-reviewer, reading the same four artifacts adversarially):
**transport is not the only surviving loss — the counters record a second stage, and it is the
larger of the two remaining.** `_on_pair` has exactly two outcomes, `dropped_pair_count++` or
`fused_count++`, so `red_frames - fused_count - dropped_pair_count` is precisely the red frames the
`ApproximateTimeSynchronizer` never handed over at all: they arrived at the node and never found a
NIR partner inside the 50 ms slop. That number is **28 / 48 / 37 / 88** on the four flights —
**38 % / 38 % / 33 % / 41 % of every red frame that survived transport**, essentially flat across
both levers, because neither lever touched pairing. The full F4 chain is therefore
`698 camera_info ticks → 217 red images (31.1 %) → 129 fused (59.4 % of red) → 86 recorded
(66.7 % of fused)` = **12.3 % end to end**, and `dropped_pair_count: 0` means only that the *guard*
rejected nothing — it was never evidence that pairing was lossless. Mechanism consistent with the
transport diagnosis rather than competing with it: NIR is mono16 (614,400 B) and lands ~411 frames
per flight (~3 Hz) while RGB is rgb8 (921,600 B) and lands 1.6 Hz even after both levers, so the
two bands tick at different effective rates and most red frames have no NIR neighbour close enough.
The consequence for whoever picks up item 1: **the next lever is not necessarily another transport
lever.** Closing the red/NIR rate gap, or widening `slop` off its ADR-007 25 %-of-period bound (a
georef-accuracy tradeoff, not a free one), addresses a bigger share of what is left than squeezing
transport further. The third stage — 129 fused vs 86 recorded — is **not** attributed here: Shell 6
starts before Shell 7 and teardown SIGINTs the recorder first (F4's clip ends at sim 141.0 s against
`last_fused_stamp_sim_s` 145.6), so part of that gap is window and part may be recorder-side loss,
and no counter separates them. That separation is the next counter to add, not the next lever.
Owner / roles: devops-reliability-engineer (owner), robotics-sim-engineer + flight-software-engineer
(the wrapped commands), qa-safety-reviewer (the gates are safety gates; the happy path is now
evidenced, and the failure paths listed in amendment 3 are the outstanding evidence).

## ADR-014: The docs get a rendering layer — an in-repo static generator in the "Heatmap Neutral" direction — and the Markdown stays untouched (2026-08-18, status: ACCEPTED — implemented `scripts/build_docs_site.py`, every doc renders)
Decision: Ship documentation styling as `scripts/build_docs_site.py`, a one-command generator that
renders `README.md`, `TIGER_TEAM_GUIDE.md` and every `docs/**/*.md` into a gitignored `docs-site/`.
The **generator is the tracked artifact; the site is disposable.** The visual direction is
**D · Heatmap Neutral**, chosen by the user tonight from a four-direction options artifact
(https://claude.ai/code/artifact/3890177c-62a1-4467-9c72-ecd2b3ba7bd6): warm-grey monochrome chrome,
New York for running prose, SF Pro for headings and tables, SF Mono for commands — and the NDVI
diverging ramp (canopy `#4A7A3E` / soil `#A04E33`, dark `#86BE72` / `#E08163`) held back for data
alone: status rows, gate markers, callout edges. Chrome never takes colour.
Alternative(s) rejected: **MkDocs Material** — nav, search and versioning arrive free, but its own
design system fights every custom token, and this direction is nothing but custom tokens; the
dependency would cost more than the nav it buys. **A published Artifact portal** — a link you can
send anyone instantly, but it lives outside the repo and drifts from the source the moment a doc
changes, which is exactly the failure mode a docs layer must not have. Also rejected: touching the
Markdown to carry styling hooks — the sources stay readable and diffable on GitHub as they are.
Why: In a repo whose culture is radical engineering honesty, a page where green means "green" is
the design argument — colour that carries meaning rather than mood, which is the repo's own
standard applied to its own docs. And an 8-pattern renderer we own outright is defensible line by
line in an interview, which a theme override never is.
Implementation notes: one dependency (`markdown`, `extra` + `toc`); one shared stylesheet with
three-state theming (bare `:root` light, `prefers-color-scheme` dark guarded by
`:not([data-theme="light"])`, explicit `[data-theme="dark"]`) and an Auto/Light/Dark toggle
persisted to `localStorage`. It styles the **eight patterns that actually recur in these files**:
status tables, emoji status headings, blockquote warning callouts, `*Look for:*` evidence lines,
gate/checklist blocks, ADR entries + nested amendments, narrated shell fences (`#` narration muted
against full-ink commands), and dated log headings. Intra-repo `.md` links are rewritten to the
generated `.html`; links to non-doc repo paths are rewritten back out to the tree. 16 pages in
~0.2 s, byte-identical on rebuild, nonzero exit on any source that won't read or convert.
**Two gates make the render falsifiable rather than merely pretty**, both added by the QA pass and
both failing the build: a *heading-parity* gate (the headings the source declares, blockquote-nested
ones included, must equal the headings the render produced) and a *link* gate (every relative link
must resolve to a file that exists). Heading parity exists because python-markdown accepts `#` with
no following space and GitHub does not, so `#5→#8),` — a wrapped body line in ADR-006 — silently
became a page-title `<h1>`; the renderer now follows GitHub's rule and the gate pins it.
Owner / roles: flight-software-engineer (front-end hat, implementation), product-lead (the pick),
qa-safety-reviewer (the two gates, the print-specificity and mobile-overflow fixes).

### ADR-014 amendment (2026-08-18, adversarial pass): four defects an exit code of 0 could not see
The generator built 16 pages, exited 0 and was byte-identical on rebuild while all four of these
were live, which is the point: **"the build passed" was never evidence that the render was right.**
(1) *Heading hierarchy* — as above; the gate now catches it. (2) *Broken `.md` links passed
silently*: the rewriter left an unresolvable target as-is and returned success, so a dead link could
ship; it now collects and fails. (3) *Print* — the override was `:root,:root[data-theme]`, but the
dark rule is `:root:not([data-theme="light"])`, which `:not()` gives specificity (0,2,0); a bare
`:root` is (0,1,0) and lost, so **Auto + dark OS — the default state for a dark-mode reader — printed
a black page.** It reads as verified because forcing dark *does* print white, and that is the state
that got tested. `:root:root` ties and wins on source order; proven by flipping the block's media to
`all` in each of the three states. (4) *Mobile* — one unbreakable token
(`eval/results/testflight_gate_20260818T222031Z.json`, 422 px against a 339 px column) widened the
document at 375 px and dragged the fixed bar sideways with it; `overflow-wrap:break-word` on `body`
fixes it, with fences opted out by their existing `white-space:pre`. All 16 pages now measure zero
horizontal overflow at 375 px, and all six theme × OS-preference combinations were read out of a
live browser rather than argued from the cascade.
Owner / roles: qa-safety-reviewer (found and fixed), flight-software-engineer (generator owner).

### ADR-005 amendment (2026-08-18, closes the trailing open follow-up)
Superseded by this entry's own header banner: the live `ros2 topic list` check ran 2026-08-05 (Week-3
Gate 2, `docs/archive/WEEK3_VALIDATION.md`) and all 18 `/ap/*` topics appeared exactly as locked. No
follow-up remains on ADR-005.

### ADR-006 amendment (2026-08-18, closes the trailing open follow-up)
Superseded by this entry's own header banner: Week-3 Gate 3 (2026-08-05,
`docs/archive/WEEK3_VALIDATION.md`) confirmed both halves live — a `/ap/cmd_gps_pose` setpoint was
honoured in GUIDED, and AUTO with `MIS_RESTART=0` resumed the interrupted leg rather than restarting.
No follow-up remains on ADR-006 beyond the MIS_RESTART pinning correction below.

### ADR-006 amendment (2026-08-18, factual correction — MIS_RESTART is not actually pinned)
The decision stands and was confirmed live; the "same explicit discipline as ADR-005" claim does not
hold in the repo. `config/sitl_params/dds_udp.parm` sets only `DDS_ENABLE 1` and `DDS_UDP_PORT 2019` —
`MIS_RESTART` appears in **no** committed param file. Every runbook, and `scripts/fly_pipeline.sh`'s
`fly_lines()`, instead sends `param set MIS_RESTART 0` live at flight start (typed by a human, or by
`fly_pipeline.sh test-flight`), so the executor's resume guarantee (`avoidance_executor.py`) depends on
a runtime step nothing enforces at SITL boot. Fix forward: add `MIS_RESTART 0` to
`config/sitl_params/dds_udp.parm` (or a sibling `mission.parm` loaded alongside it) so the pin is real.

### ADR-007 amendment (2026-08-18, correction to amendment item 2 above): `/fg/gz_clock` was never bridged
The frame↔pose pairing decision in the first ADR-007 amendment's item 2 stands; the mechanism it named
was reversed the same day, per this file's own addendum item 3 above — `/fg/gz_clock` is **not**
bridged. `sim/bridge/fg_sensor_bridge.yaml` carries only the four `/fg/sensor/*` topics; `record_node.py`
streams the Gazebo clock natively over gz-transport (commit `09e5bf2`) and `clip_recorder.PoseBuffer`
consumes that stream directly.

### ADR-007 amendment (2026-08-18, closes four of the five items in the original "Open follow-up" list)
1. **Item 1 CLOSED** — the four `/fg/sensor/*` topics bridge and publish; `/fg/ndvi/image` (`32FC1`) ran
   live for a full flight (`src/fieldguard_planning/ndvi_node.py`).
2. **Item 2 CLOSED (Gate 2, `gate2_summary.json`)** — over 996 frames the raw NIR band reads canopy
   0.854 > soil 0.212 > bird 0.040 (gaps 0.643 / 0.171), the direct proof the NIR band is genuinely
   independent of Red.
3. **Item 3 STILL OPEN** — the ADR-003 scored re-run on a real clip has not been executed. This is the
   last confirmation-pending item in the project (see `docs/ROADMAP.md` "Next up").
4. **Item 4 CLOSED** — `gz-sim-thermal-system` loads on the pinned Harmonic + ogre2 build (Gate 0,
   2026-08-05).
5. **Item 5 CLOSED** — live `camera_info` gives `cx=320.0, cy=240.0` (exact image centre) and
   `fx=fy≈520.006`, matching `CameraIntrinsics.from_config`'s default
   (`eval/results/clips/real_flight_20260818T221641Z/meta.json`). The image-centre assumption was
   correct; nothing downstream changes. (Items 6-7 were already-decided notes, not open questions, when
   ADR-007 was written.)

### ADR-007 amendment (2026-08-21, qa-safety-reviewer): the tree-check is promoted from an ad-hoc look to a gate — `scripts/check_tree_positions.py`
Amendment 5 above added a **pre-flight** geometry gate (`verify_mount_geometry.sh`, parked vehicle,
2.2 px). It cannot see a clip that was mislocated *after* bringup — by pose pairing, by georef, by a
mid-session SDF edit. The tree-check that caught the horizon-facing mount in the first place was
never code; the 2026-08-18 figures came from an ad-hoc look, so nothing stopped the next map from
being judged by eye. It is now `scripts/check_tree_positions.py`: reads a clip's committed
`heatmap/heatmap.json` + `config/static_obstacles.json`, prints the per-tree table (imaged /
canopy-grade / lift), and **exits nonzero on the georef-displacement signature**. Two gates, two
failure windows — the mount before the flight, the artifact after it.
  * **The FAIL condition is displacement ONLY: a positive-NDVI cell farther than 2 m from every tree
    centre.** Deliberately not "too few trees imaged" and not "too few canopy-grade" — those are
    coverage, which varies with recording throughput (ADR-013 am. 5-6a) and would make the gate a
    flaky proxy for a problem it does not test. Displacement is the failure that *looks like
    success*, and it is the one worth an exit code.
  * **The 2 m bar is measured, not chosen.** Every post-mount-fix clip in the repo puts 100 % of its
    positive cells at exactly 1.7678 m (a 2.5 m cell's centre-to-corner distance); the three
    horizon-mount clips put 100 % of theirs at 6.4-11.9 m. The bar sits in an empty gap, so it is
    not a tuning knob — pinned by `test_threshold_sits_in_the_measured_gap`.
  * **The port was pinned before it was trusted.** `tests/fieldguard_planning/
    test_check_tree_positions.py` (12 tests) reproduces all five published clip figures exactly —
    8/5, 6/5, 7/6, 11/6, and the demo take's 12/8 at median lift +0.8692 — and rejects the three
    horizon-mount clips. Mutation-checked: dropping the four-cell quad, moving the canopy threshold,
    using a mean instead of the modal soil, or widening the bar to 20 m each fail the suite. One
    test exists purely to pin the inversion the gate is for: the all-time-high 697/720 clip FAILS
    while the 410/720 demo take PASSES — `cells_imaged` is not the metric.
  * **Honest edge:** a clip with no positive cells has nothing to mislocate, so it exits 0 and says
    `PASS (vacuous)` in those words. Placement is what this gate tests; it is not evidence that a
    thin clip is a good one.

---

## ADR-015: Bird geometry answers to TWO gates — one lane-PARALLEL threat bird in the cylinder, two lane-crossing observation birds below it   (2026-08-21, status: ACCEPTED — **FLOWN 2026-08-25**, amendment 1: the THREAT gate held live (16 contiguous in-cylinder ticks, the encounter this ADR was written to create), the VISIBILITY prediction did not (2 frames in view against a predicted median of 8) — the cause is the predictor's default SPEED, not this geometry)
Decision: `config/birds/farm_world_birds.json` changes by **one patrol line and one altitude swap**;
the regenerated `sim/worlds/farmguard_field.sdf` diff is exactly two `<pose>` lines.
  * **bird_0: x 20 → 15 m, z 8 → 11 m.** It now patrols *down* the mission's row-0 lane (which is
    also orchard row 0), 4 m under cruise. **This is the threat bird.**
  * **bird_1: z 11 → 8 m.** Unchanged east↔west crossing sweep, now below the threat cylinder.
  * **bird_2: unchanged at 6 m.**
  * The altitude **multiset {6, 8, 11} is identical before and after** — this is a reassignment, not
    a lowered flock, and `test_bird_geometry_contract.py::test_the_altitude_multiset_is_unchanged`
    pins that so the change cannot later be mistaken for (or turned into) an altitude giveaway.

**The constraint, which is structural and worth saying out loud.** A strictly nadir camera makes the
two project priorities pull in opposite directions on this one file. Camera footprint scales with the
bird's **depth below the drone**, so a bird is photographable when it flies LOW; `avoidance_policy`'s
threat cylinder is `threat_radius_m` 12 m × `vertical_threat_m` ±6 m, so a bird is dangerous only when
it flies HIGH (z ≥ 9 m at 15 m cruise). Measured on the lane-**perpendicular** geometry (bird_1), the
two windows do not overlap at all: median frames in view is 10 / 6 / 4 / 3 / 3 at z = 6 / 8 / 9 / 10 /
11 m, so the 5-frame floor needs z ≤ 8 and the cylinder needs z ≥ 9. **For a bird that crosses the
lanes, "photogenic" and "dangerous" are mutually exclusive.** The resolution is not altitude at all:
a lane-**PARALLEL** bird has cross-track offset 0 on its lane, so it never has to beat the shrinking
cross-track half-footprint, and it can sit in the cylinder *and* in frame. That is the whole decision.

**The chosen geometry, measured** (`scripts/predict_bird_visibility.py`, 3 m/s, the 5 Hz sensor tick,
55 driver-start offsets — the table the tool prints, verbatim):

| bird | alt | depth | footprint @ bird alt | frames in view min/med/max | at gate (phase 0) | offsets seen | limited by |
|---|---|---|---|---|---|---|---|
| bird_0 | 11 m | 4 m | 4.9 × 3.7 m | **3 / 8 / 15** | 3 | **55/55** | timing |
| bird_1 | 8 m | 7 m | 8.6 × 6.5 m | 0 / 6 / 11 | 9 | 46/55 | timing |
| bird_2 | 6 m | 9 m | 11.1 × 8.3 m | 0 / 11 / 26 | 11 | 46/55 | timing |

VERDICT **PASS** (was FAIL on 2 of 3, with bird_0 STRUCTURAL — 0/55 offsets at every cadence). No bird
is structurally invisible any more, and the safety-relevant bird is the one that is **never**
invisible: 55/55 offsets, against 46/55 for the two crossers.

**And the avoidance story is not weaker — it is the same near-miss, in a harder place.** Against the
as-flown geometry (frozen at `tests/fieldguard_planning/fixtures/farm_world_birds_asflown_20260821.json`),
swept over every driver-start offset — all rows at ONE setting, the same 55-offset sweep as the camera
table above (path sampled at 5 Hz, phase step 0.5 s; dwell is quantised by that sampling rate, so a
coarser scan moves it by a tenth or two):

| | as flown (bird_1 @ 11 m) | ADR-015 (bird_0 @ 11 m) |
|---|---|---|
| birds in the threat cylinder | 1 | 1 |
| closest in-cylinder approach | 4.01 m | **4.00 m** |
| offsets with a threat event | 55/55 | 55/55 |
| median cylinder dwell | 9.6 s | 8.4 s |
| offsets where the threat bird is ALSO in frame | 37/55 | **55/55** |
| encounter geometry | perpendicular crossing | along-track, closest approach **0.02 m horizontal / 4 m vertical — straight overhead** |

The last row is the one that matters most and it is the one that improves: a threat the NDVI camera
never sees is a threat the real loop cannot act on. As flown, the threat bird was in frame at only
37 of 55 offsets (and for a median 3 frames, below the floor); the ADR-015 threat bird is in frame at
every one. At the closest approach it subtends a 48 px diameter of 480, and ADR-009's apparent-size
range (0.15 m radius prior against the true 0.18 m) reads it at 3.27 m against a true 3.92 m depth —
*closer* than it is, the fail-safe direction, and 3.27 m is well inside the ±6 m cylinder rather than
near its edge. So the avoidance event survives the real detection chain, not just an injected
ground-truth detection.

The 1.2 s of dwell is the only thing given up, and it buys a strictly harder encounter: at the closest
approach the real `AvoidancePolicy` returns **DIVERT** and **rejects its own preferred 0° dodge**
("swept path clears tree by only −1.11 m"), taking +45° with 1.00 m clearance — because the lane the
bird patrols runs down an orchard row. **The nominal world now reaches the "avoidance must never
create a new collision" branch that only the hand-built `geo_avoid_into_tree` scenario used to.**
All of the above is asserted, not narrated: `test_bird_geometry_contract.py` (14 tests) re-derives the
as-flown baseline from the fixture on every run rather than hardcoding 4.01 m, so the comparison
cannot rot.

Alternative(s) rejected — every one of them measured, none rejected on taste:
  1. **Lower all three birds to 2-3 m AGL** — ADR-003 amendment 1's own recommendation, and the trap
     this ADR exists to refuse. It maximises frames and deletes the avoidance story: 12-13 m below
     cruise is twice outside the ±6 m cylinder, so **zero** birds would remain threats; it also puts
     them at the 3.8 m canopy tops and makes ADR-009's apparent-size range estimate worst exactly
     where it is least tested (relative range error ≈ 1/r_px: ~4 % at bird_0's 23 px, ~13 % at 8 px).
     A bird that photographs beautifully and threatens nothing is not a dynamic obstacle.
  2. **Lower bird_0 without moving its patrol line.** Measured over z = 2…12 m: **structural (0
     frames at 0/55 offsets) for every z from 5 m up** — which is every altitude that is not already
     alternative 1. The miss was never depth, it was **cross-track** — 5.0 m off lane x=15 against a
     cross-track half-footprint of 0.4615·depth, so closing it needs 10.8 m of depth, i.e. ≤ 4.2 m
     AGL. Below that line it does become visible (median 23 / 25 / 27 frames at z = 4 / 3 / 2 m), and
     that is precisely the trade alternative 1 rejects: at 4 m AGL the bird sits 11 m under cruise,
     outside the ±6 m cylinder, threatening nothing. So "lower it" is not a third option — it is
     alternative 1 with one bird. Pinned by `TestNoAltitudeFixesTheOldLine`, which sweeps the threat
     band (z = 9…12 m) and separately asserts the 4 m case that *does* clear the floor and *does*
     cost the threat.
  3. **Slow bird_1 down instead of lowering it** (more dwell per crossing, same altitude). Measured
     backwards: at z=11 the median goes **3 → 0 → 0** at 1× / 1.5× / 2× trajectory time. Slowing
     lengthens each crossing but removes crossings, and the median follows the count, not the dwell.
     The max rises (5 → 16) — a lever that buys luck, not reliability.
  4. **Keep bird_1 at 11 m as a second threat.** Median 3 < the 5-frame floor. A bird the NDVI
     detector can never see is not a second threat; it is a threat the system is blind to, which is
     the ADR-003 failure mode wearing a different hat.
  5. **Promote bird_2 to 9 m as the second threat.** It actually clears both bars on paper (median 6,
     in-cylinder) — and |dz| is **exactly 6.00 m**, sitting on `vertical_threat_m`. A metre of
     altitude-hold error flickers the threat on and off. Do not build a safety claim on a boundary.
  6. **A vertical profile** — low at the ends, threat band at mid-trajectory, costing **no new
     waypoints** (the there-and-back middle waypoint already exists). It works: bird_1 at 6→11→6 gives
     median 5 with 3.5 s dwell and 4.90 m closest; bird_2 at 6→11→6 gives median 8, 4.0 s, 4.59 m, but
     a threat at only 25/28 offsets. Both are strictly worse than bird_0-on-the-lane on **both** axes,
     and a bird with no single altitude makes every report's "alt" column a lie. Kept in the drawer as
     the cheapest way to add a *second* threat if one is ever wanted; not needed for one.
  7. **Widen `vertical_threat_m` so the low birds count as threats.** Rejected outright: that is
     tuning a safety parameter to make a demo look good. The world moves, the policy does not.

**Honest limits — what this does NOT fix.** The predicted counts are frame **opportunity** at the
5 Hz sensor tick, not recorded yield (~12 % reaches a clip, ADR-013 am. 6a). At the demo take's actual
0.407 Hz the new geometry predicts medians **0 / 0 / 1 — identical to the old.** Geometry raised the
ceiling (total median across the three birds, 14 → 25 frames at 5 Hz; 6 → 11 at 2 Hz) and removed the
one bird no throughput could ever reach; it did **not** on its own make the ADR-003 real-render re-run
scoreable. Both levers are still required, and the pre-flight check is now the thing that says so
before a Docker session is spent, not after. Model limits inherited from the predictor: constant
speed, instant turns, no wind, no avoidance dodges, no occlusion — all optimistic, all in the safe
direction for a go/no-go check.
Why: A nadir camera makes "can photograph it" and "can collide with it" opposite properties for any
bird that crosses the survey lanes, so the fix was never an altitude — it was flying one bird *along*
a lane, where cross-track offset is zero and the two windows finally overlap. The result keeps the
identical 4 m near-miss, on a lane where the dodge has to thread an orchard row, and makes every bird
photographable for the first time.
Owner / roles: robotics-sim-engineer (decided, with the `product-lead` tiebreak: priority #1 avoidance
outranks #2 NDVI where they conflict); perception-ml-engineer (the predictor this was measured with,
ADR-003 am. 2); qa-safety-reviewer (the two-gate contract test is the regression that makes trading
one priority for the other loud).

### ADR-003 amendment 4 (2026-08-21, robotics-sim-engineer): criterion 3's geometry blocker is CLOSED; its throughput blocker is not
Amendment 1 listed "lower the birds" as unblock (1) and amendment 2 split the blocker into a
STRUCTURAL half (bird_0) and a TIMING half (bird_1, bird_2). **ADR-015 closes the structural half —
and does it by moving a patrol line, not by lowering anything**, because lowering was measured to fix
the camera at the cost of the avoidance story that outranks it. The committed geometry now predicts
PASS (medians 8 / 6 / 11 at the 5 Hz tick, no bird structural, every bird seen at 46-55 of 55
driver-start offsets) with the threat cylinder still occupied at an unchanged 4.00 m closest approach.
**The re-run is now worth a Docker session in a way it demonstrably was not on 2026-08-21** — but
`predict_bird_visibility.py` at the demo take's own 0.407 Hz still returns medians 0 / 0 / 1 on the new
geometry, so item 1's recording-throughput work (ADR-013 am. 5-6a) is the remaining blocker, not a
nice-to-have. Criterion 3 stays OPEN; the reason it is open has changed.

### ADR-013 amendment 7 (2026-08-22, throughput round 2 — instrumentation before levers): every lost frame now has a name, and three of four levers died to counters instead of flights
Amendment 6a asked for "the next counter, not the next lever." This round built six of them
(fuser: `nir_camera_info_frames`, `unpaired_red_count`, a one-off unpaired-red nearest-NIR
histogram; recorder: `ndvi_msgs_received`/`dropped_no_writer`/`dropped_no_pose`,
`on_ndvi_wall_ms` p95/max, `rgb_msgs_received`; finalize: airborne/painting frames + cadences;
clip schema 1.2→1.3, sidecar 1.0→1.1; +47 tests), flew them twice, and settled more than the
planned flight program would have:

* **Pairing is not a loss stage — it is the NIR band's transport loss re-expressed.** Both
  sensors tick one 0.2 s grid; slop is 50 ms; a red fuses iff its OWN tick's NIR survived. The
  multiplicative model `fused ≈ ticks × P(red) × P(nir)` predicts every instrumented flight
  (ratio 0.94–1.13). Corollary, verified in source: **`dropped_pair_count` is STRUCTURALLY
  unreachable in the live node** (the synchronizer's slop IS the guard bound, so no rejectable
  pair is ever handed over) — its four flights of reassuring zeros measured nothing. The
  misleading "belt-and-suspenders" comment in `ndvi_node.py` is corrected; the honest number is
  `unpaired_red_count`.
* **The slop-widening lever amendment 6a floated is DEAD, twice, without a flight spent on it.**
  Histogram: 79/79 (F5a) and 70/70 (F5b) unpaired reds had their nearest surviving NIR a full
  tick away (`ge_tick`; `le_slop` and `slop_to_tick` both 0, evictions 0). Widening below 0.2 s
  buys nothing; above it pairs different sensor ticks (~0.6 m of motion). Do not fly it; do not
  amend ADR-007 for it.
* **NIR render exonerated — the band is TRANSPORT-limited.** `nir_camera_info_frames` 689/690
  and 676/676 against the RGB control: the thermal sensor ticks at the full 5 Hz. The
  "render-limited, goal unreachable" branch is falsified.
* **Recorder logic and disk exonerated — F8 (bind mount) cancelled without flying.**
  received→written 100 % on both flights, both drop counters 0, `on_ndvi_wall_ms` p95 7.9–17.3 ms
  against the 200 ms budget: the executor idles while the middleware drops 1.23 MB samples. The
  fused→recorded gap is pure transport — exactly what F6 (recorder's `/fg/ndvi/image`
  subscription BEST_EFFORT→RELIABLE against the already-RELIABLE publisher) attacks.
* **F7 (drop the recorder's raw-RGB arm) cancelled** — user decision (the ADR-003 criterion-2
  comparison arm is protected for the whole round) and the evidence independently concurs:
  `/fg/sensor/nir/image` has exactly ONE subscriber and still loses ~65 %, so fan-out is not the
  dominant term.
* **Both F5 flights are VOID for absolute yields (clips carry `INVALID_DO_NOT_USE.md`) — and the
  void itself is the finding: ENVIRONMENT DRIFT, measured.** A 12-container stack from an
  unrelated project was created on the shared Docker VM at 2026-08-22T0318Z — mid-F5a, and a full
  day after F1–F4 set the 31.09 % baseline on a VM running `fieldguard-sim` alone. F5b, flown
  host-quiet by sampling, still returned red/ci 17.31 %. An interleaved bench A/B
  (instrumented/baseline ×2, Gazebo+bridge+fuser only) then measured the UNINSTRUMENTED code at
  7.19–15.58 % on the same host — the sign of the A−B difference flips between pairs, so the
  instrumentation is exonerated and the drift is the cause. **F4 remains the only clean anchor,
  and it is n=1.**
* **Two new traps for the record:** (a) host-quiet cannot be judged from one `docker stats`
  snapshot — sampling caught 267–352 %-of-a-core bursts between quiet snapshots; sample
  throughout the flight. (b) The exposure control and RTF both PASSED on F5a while contention
  halved both bands — neither gate detects host load, only a contemporaneous load log does.
* **Honest ceiling, computed off F4:** closing the recorder hop and the NIR hop entirely takes
  0.587 Hz airborne to ~1.48 Hz — the bottom edge of the 1.5–2 Hz target with zero margin,
  because nothing in the kept lever set attacks the RGB band's ~83 % loss. The next candidate
  there is re-encoding `/fg/ndvi/image` 32FC1→16UC1 (halves the system's largest sample; NDVI is
  bounded [−1,1], quantization ~3e-5) — **escalated to the user, held in reserve, not built.**

Open: F5c clean re-baseline in a user-granted host-quiet window (the other stack paused), then
F6, one variable, judged on `(fused_count − ndvi_msgs_received)/fused_count` with
`on_ndvi_wall_ms` watching for backpressure moving the loss upstream. Standing user decisions
this round also fixed: deliverables are BOTH short high-evidence flights (the measurement
instrument) and the full boustrophedon (the product artifact), plus a quantified short-vs-long
evidence comparison on the final config; a resolution cut stays off the table.
Owner / roles: flight-software-engineer (built + flew + bench), robotics-sim-engineer scope
co-owned, qa-safety-reviewer's amendment-6a discipline followed (counters before levers),
product-lead's user-escalations resolved in-session.

### ADR-013 amendment 8 (2026-08-22, throughput round 2 closes): L1 is a KEEP with an honest cost, the attribution closes to zero, and the remaining gap has a single mechanism
F5c and F6 flew back-to-back on the restored clean host (load sampled throughout, other-container
CPU 0.0 % on every sample), one variable apart:

* **Environment drift is confirmed end-to-end.** The same code that read red/ci 17.31 % against
  13 containers read **25.60 %** on the clean host (F5c). With the bench A/B of amendment 7, the
  2× shortfall is closed as fully environmental. F5c is also the **second healthy run at the A+B
  config** (tree gate PASS at lift **+0.9888**, the best on record) — amendment 4's rule now
  PERMITS raising the evidence floor for A+B, but the operative config moved to A+B+L1 the same
  hour at n=1, so the floor deliberately stays 12/40 until the L1 config has its own second
  healthy run. Anchors if raised later: the lower healthy A+B run is 36 frames / 158 cells.
* **L1 (recorder `/fg/ndvi/image` subscription BEST_EFFORT→RELIABLE): KEEP.** It closed its hop
  completely — NDVI→recorder transport loss **62.5 % → 0.0 %** — and the attribution identity
  closed exactly (received − written − no_writer − no_pose = **0** unaccounted), which was the
  round's whole goal. The predicted backpressure was real and is the recorded cost: red/ci
  25.60 % → 20.46 %, fused 96 → 72. Net **painting cadence 0.2823 → 0.4767 Hz (1.69×)**, recorded
  1.94×, cells 1.91× — the downstream leak was the bigger one. **Standing re-check:** if NIR
  transport is ever materially improved, re-fly the L1 trade — the upstream cost could outgrow
  the hop it closes.
* **The slop lever is dead across five flights** (histogram `ge_tick` 79/79, 70/70, 73/73, 66/66
  with zero in every other bucket). Retired permanently.
* **Where the remaining 3.1–4.2× lives, and what it is NOT:** best measured painting cadence is
  0.4767 Hz against the 1.5–2 Hz target. The only losses left are the two sensor-image hops,
  bridge→fuser (RGB **79.5 %**, NIR **53.8 %** on F6) — both already `best_effort`, so the QoS
  lever class is exhausted; closing NIR alone computes to ~0.93 Hz, not enough without red
  recovering too. The mechanism left standing is **payload-size fragmentation on an entirely
  untuned DDS layer** (nothing in the repo sets `RMW_IMPLEMENTATION`, a DDS profile, or
  `--shm-size`; amendment 7's escalated 16UC1 lever targeted the NDVI hop, which L1 just closed —
  that escalation is SUPERSEDED). Next round follows amendment 6a's discipline again:
  **instrument the DDS baseline before pulling a DDS lever** — record the active RMW, transports,
  and `/dev/shm` capacity into the artifact, then lever one variable at a time.
Owner / roles: flight-software-engineer (flew + measured), qa-safety-reviewer's counters-first
discipline held for a second consecutive round; the floor decision follows amendment 4's own rule.

### ADR-013 amendment 9 (2026-08-22, throughput round 3 — the transport root cause, fixed): painting cadence 0.48 → 5.0 Hz; the recording-throughput thread that began in amendment 4 is CLOSED
The mechanism, source-verified in Fast DDS 2.6.11 (the pinned image's only RMW): every large
sample fragments at **65,384 B even over shared memory** — SHM's own `max_message_size` defaults
to 65500, UDPv4 is hard-capped there, and a participant takes the MINIMUM across transports. The
default SHM segment is **512 KiB = 8 fragment slots**, against 10 (NIR), 15 (RGB) and 19 (NDVI)
fragments per sample; on overflow Fast DDS **silently discards and reports success** (the discard
path logs at logInfo, compiled out of release builds). Amendment 8's L1 result was the unwitting
control experiment: RELIABLE never made the transport faster, it NACK_FRAG-repaired the fragments
the segment was dropping. One honest correction: the iid per-fragment-loss model is **falsified**
(red implied ~8 %/fragment while NIR implied ~0.5 % in the same arm) — the data supports a
slot-exhaustion threshold. The anchors that hold: 65,384 B/fragment, 8 slots per default segment.

* **Lever L2 — KEPT: `config/dds/fg_fastdds.xml`, SHM segment 512 KiB → 8 MiB (128 slots).** QoS
  untouched; orthogonal to kept levers A/B/L1. Enabled by `--shm-size=1g` at container re-create
  (`sim_docker_run.sh` + the duplicated SIM_BRINGUP.md block, same commit; named-volume gate
  passed first). Bench (interleaved ×2, admissibility = segment min AND max ≈ 8.4 MB): red/ci
  28.8/26.4 % → **100.0 %**, nir → **100.0 %**, both pairs.
* **F9, the one-variable confirmation flight (A+B+L1+L2): red/ci 706/706 = 100.00 %, NIR
  707/707 = 100.00 %, `unpaired_red_count` 0 with every histogram bucket 0** — pairing has ceased
  to exist as a loss stage, exactly as amendment 7's same-tick model predicted. End-to-end
  96.46 %; **painting 502 frames / 5.0 Hz** (target was 1.5–2; round started at 0.4767); cells
  417/720 on `test_2lane`; the protected RGB comparison arm at 681/681 = 100 %. Attribution
  closes to zero unaccounted. Tree gate PASS.
* **Amendment 8's standing L1 re-check — CLOSED, KEEP (F10, one variable):** RELIABLE 1.56 % vs
  BEST_EFFORT 1.71 % hop loss at identical 5.0 Hz / 502 painting frames. L1's measured round-2
  cost is gone (both flights 100 % red/ci) because L2 removed the drops the repair traffic
  amplified. L1 stays as free insurance for a segment under pressure again.
* **Injection = in-pane exports (user decision):** `FASTRTPS_DEFAULT_PROFILES_FILE` exported
  inside the six participant pane payloads + `ctr()`'s probe, runbook mirrored in the same change
  — ADR-013's command-level parity claim stays fully true; 7 tripwire tests pin it (participants
  carry it, non-participants must not, both probe paths covered, single value, path resolves,
  runbook agrees).
* **L4 (SHM-only, zero-fragmentation) — SHELVED, decided:** the user delegated and leaned
  host-side; L2 saturated the metric without closing the door, and a reachable DDS graph keeps
  `ros2 topic echo` against a live sim available to anyone exploring the project. Revisit only if
  a longer mission underperforms, and with the user, since it closes that door.
* **Dead ends, measured so nobody re-walks them:** `net.core.rmem_max` is 212,992 and unraisable
  here (/proc/sys read-only in-container; `docker run --sysctl` rejected by runc on this Docker
  Desktop); XML socket-buffer knobs silently clamp to it; `FASTDDS_BUILTIN_TRANSPORTS=LARGE_DATA`
  landed in Fast DDS 2.10/2.11, not 2.6.11; CycloneDDS is not installed and its 1,344 B fragments
  would be ~24× the loss surface; the micro-ROS agent is hard-linked against rmw_fastrtps, so an
  RMW switch would split the graph.
* **Floor unchanged at 12/40** — one healthy run at the operative A+B+L1+L2 config (F9; F10
  differs by one variable). Amendment 4's rule, third application. **Caveat carried forward:**
  5.0 Hz on a 3-minute `test_2lane` is not a promise for the 14-minute boustrophedon — round 2
  measured real run-age decay, and `meta["dds"]` now makes transport state checkable per clip.

**Consequence: `predict_bird_visibility.py --fps 5.0` → PASS, medians 8/6/11, bird_0 visible at
55/55 driver-start offsets. The ADR-003 full-coverage re-fly — four blockers behind one clip — is
BOOKABLE for the first time since the demo take. Per ADR-013, the user flies it.**
Owner / roles: flight-software-engineer (built, benched, flew all of round 3),
robotics-sim-engineer scope co-owned, qa-safety-reviewer's instrument-before-lever discipline
held for a third consecutive round; injection-parity and L4 decisions escalated to and returned
from the user.

### ADR-013 amendment 10 (2026-08-22, the delegated flagship take): 720/720 cells at a dead-flat 5.00 Hz; two round-2 conclusions honestly reversed; the floor finally rises
**Delegation note (the human-flown rule, exercised knowingly):** the user delegated THIS
full-coverage boustrophedon take to Claude explicitly (offered the choice, chose "Claude flies,
with ADR note"). The flight was flown by driving the runbook's own 7-line MAVProxy recipe into
the pane via tmux send-keys — the operator's keystrokes, not a new scripted mode. The
demo-flights-stay-human-flown rule otherwise STANDS; future delegations get their own dated note.

The take (clip `real_flight_20260822T215516Z`, admissible: 5/5 participants on 8,413,728 B
segments): **956 sensor ticks → 956 red = 956 NIR = 956 fused (100.00 % at every fuser stage,
unpaired 0) → 948 received → 935 written, 0 unaccounted; end-to-end 97.80 %** against the
2026-08-21 demo take's 10.7 %. **Painting 624 frames at exactly 5.00 Hz — all 623 inter-frame
gaps are 0.200 s — and cells 720/720: the first full-grid, correctly-georeferenced map in the
project's history.** Tree gate PASS, 18/18 imaged, 14 canopy-grade, all 16 positive cells within
2.0 m. Birds visible for the first time ever: 10 ground-truth bird-frames, 3/3 birds — ADR-003's
evidence floor cleared (its verdict and the new blocker live in the ADR-003 amendment).

* **Round-2 conclusion reversed #1 — run-age decay does not exist.** The decay was segment
  exhaustion wearing a clock's clothes: with L2 in place the cadence is bit-perfect at full
  mission length. Amendment 7's decay measurements stand as data; their "elapsed time" reading
  is retired.
* **Round-2 conclusion reversed #2 — short flights do not out-yield long ones.** Same config,
  same per-minute frame yield (288 vs 290 painting frames/airborne-min); the boustrophedon is
  **1.4× better on cells/min** because it spreads frames over new ground. The user's evidence
  study lands the opposite of its round-2 premise: measure with short flights for one-variable
  discipline, but the long mission is the better evidence artifact too, not just the product one.
* **Evidence floor RAISED 12/40 → 300/200** (amendment 4's rule satisfied: two healthy runs at
  the operative config — F9 681/417 on the anchor mission, the take 935/720 as context). Every
  pre-L2 config now fails it, deliberately: a silently unloaded profile is the exact regression
  the floor exists to catch.
* **Avoidance was NOT exercised, correctly:** FULL_PIPELINE_DEMO.md's own scope excludes the
  avoidance node ("Not in this flight"), and the pilot-agent followed the runbook over the
  orchestrator's contrary expectation — the right call, recorded here as precedent. The
  avoidance-on-real-render half of the proof standard needs the separate AVOIDANCE_DEMO.md
  flight, which awaits its own booking (and its own delegation decision).
Owner / roles: flight-software-engineer (flew as delegated pilot, ran the full evaluation chain);
qa-safety-reviewer discipline: verdicts reported exactly as the harness printed them, artifact
FNR flagged as artifact rather than buried.

### ADR-003 amendment 5 (2026-08-22, criterion 3 re-run on the delegated flagship take): the evidence floor clears for the first time — and the blocker moves from throughput to harness ground-truth alignment
The re-run executed on `real_flight_20260822T215516Z` (scores in `eval/results/adr003_20260822/`)
and **cleared the evidence floor for the first time: 10 visible bird-frames, 3/3 birds seen** —
every prior attempt returned EVIDENCE INSUFFICIENT on zero. The harness printed, verbatim: both
arms at per-bird-track FNR 1.000, gap +0.000 → **AMBIGUOUS → default to (a) + scoped follow-up
ticket**. That verdict stands as printed, and this amendment is the scoped follow-up.

**The 1.000 is a measurement artifact, not a detector result — diagnosed, not asserted:** the
NDVI-direct detector fired on **exactly the 18 bird frames** (331-333, 392-398, 455-462) with
blob sizes matching ground truth to **1-2 px across four ranges** (47×47 vs 45×45 at 3.96 m;
21×21 vs 20×21 at 9.24 m) — the same physical objects — but ground-truth box centres sit a mean
**193.6 px** from the detections, so IoU ≥ 0.3 can never match: every true detection scores FP,
every bird scores FN. Leading hypothesis (consistent, unproven): `drive_birds.py --rate 2` moves
birds in **0.5 s steps** while `annotate_real_clip.py` interpolates the trajectory continuously,
so the RENDERED bird lags the annotated one by up to 0.5 s (implied offsets 0.7-4.4 m, the right
order; 16 failed `set_pose` calls compound it). **This was invisible at 0.407 Hz and only became
measurable at 5 Hz.** Fix direction: the annotator must replay the driver's own step function
(`t0 + k/rate`), never the continuous path. Re-score is offline — the clip is scoreable as
recorded; no re-fly is needed. Criterion 3 stays OPEN; the reason it is open has changed for the
second time (geometry → throughput → ground-truth alignment), each time with the previous cause
measured closed.
Owner / roles: flight-software-engineer (ran the chain, refused to let the artifact stand as a
detector verdict); perception-ml-engineer owns the annotator fix and the offline re-score.

### ADR-003 amendment 6 (2026-08-22, perception-ml-engineer, criterion 3's ground-truth blocker: measured, fixed at the source, clip re-scored): the render lags the labels by 0.12-0.81 s, no model can recover it, and the harness now refuses to score an estimate
Amendment 5's hypothesis was right in kind and its proposed fix would not have worked. Both were
checked before any code changed.

* **The lag is real, and it is TWO terms, not one.** All 22 NDVI-direct detections match a scripted
  bird's projected position to a mean **6.9 px** (max 17.7) and its projected apparent size to a mean
  **1.0 px** (max 2.5) once that bird is placed at a trajectory time **0.120-0.805 s (mean 0.524)
  BEFORE the frame's own stamp. 22/22 explained; zero non-bird detections in 935 frames.** The lag
  has structure, which is what makes it a mechanism rather than a fit: within one driver hold it
  grows by exactly the 0.200 s frame period and then drops, giving a hold of **0.427 s of sim**
  (bird_2) and **0.415 s** (bird_1) independently; on top sits a per-bird floor of **0.120 / 0.380 /
  0.415 s for bird_0 / bird_1 / bird_2 — ordered by their position in the driver's set_pose loop**,
  i.e. sequential `gz service` subprocess latency. Falsified alternatives: stale DRONE pose (best at
  zero staleness, monotonically worse after), a fixed image-space offset (202 px scatter about a
  47 px mean vector), and a wrong sidecar t0 (which would be constant and shared across birds).
* **`--rate` never bound, and ADR-012's stale-hop claim is retracted.** RTF measured independently
  of any detection, from the committed frames' file mtimes against `stamp_sim_s`: 0.94 pre-flight,
  0.60 airborne, **0.51-0.57 in the three detection windows**. 0.42 s of sim at RTF 0.55 is 0.76 s of
  wall per tick: **`--rate 2` achieved ~1.3 Hz**, saturated by one clock poll plus three gz-CLI
  round-trips. ADR-012's "matches the camera's 5 Hz update_rate -- the render never sees a stale hop"
  is false and is retracted. Consequence beyond labelling: **the birds HOP ~2 m between updates**,
  one full camera frame wide. Per-frame blob detection is unaffected; any future velocity or track
  estimate over these clips would not be.
* **Amendment 5's proposed fix is FALSIFIED, and so is every fixed model.** Mean/max centre residual
  over the 22 detections: current continuous labels **198.0 / 313.0 px**; the proposed
  `floor(t/rate)` step **133.1 / 299.9**; a step on the measured 0.43 s hold 129.6 / 224.4; a constant
  0.56 s lag 61.1 / 350.3; a 2-parameter hold+latency model fitted TO the detections 81.2 / **536.0**.
  IoU >= 0.3 needs 8-19 px. The reason no grid works: the driver's ticks are WALL-scheduled while RTF
  moves 0.51-0.94 within one flight, so a fixed sim-time grid drifts out of phase between bursts --
  and fitting the lag to the detector's own output would have made the resulting score
  unfalsifiable. The correction is measurement, not a better model.
* **THE FIX (source-side, so the class closes rather than this instance).** `scripts/drive_birds.py`
  now writes an applied-pose log beside its sidecar (`bird_drive_<stamp>_applied.jsonl`, schema 1.0;
  sidecar 1.0 -> 1.1 names it): per set_pose call the pose, the trajectory time, wall stamps around
  the call, the tick's gz-clock anchor, and **ok/failed**. `eval/annotate_real_clip.py` replays it --
  a frame shows the last call whose reply had returned, **a failed call holds** (the 16 failures on
  this take are exactly this case), and frames before the first landed call keep ADR-012 am. 1's
  exact spawn pose. Wall->sim conversion uses the RTF measured between consecutive tick anchors, so
  no constant is assumed and no extra subprocess worsens the latency being measured. Frames landing
  inside a call's own bracket are marked `label_ambiguous` rather than rounded to a side.
* **THE GUARD (so this cannot print a verdict again).** Every label carries `label_src` --
  `applied` (measured) / `spawn` (exact) / `generator` (synthetic) / `modeled` / `unknown` -- and it
  travels into `ground_truth.json`. `eval/score.py` refuses to apply the decision rule when any
  scored bird-frame is `modeled` or `unknown`. This is the SECOND denominator failure this file has
  had: am. 1 fixed "no denominator at all"; this one is "a full denominator whose numerator measured
  something else". The seed-42 synthetic re-run still prints ADOPT at 0.445 / 0.981 / 0.019 /
  per-bird 0.000, so the guard is not a blanket refusal.
* **RE-SCORE, verbatim.** Both arms: `TP=0 FP=22(a)/5(b) FN=10`, precision 0.000, recall 0.000,
  FNR 1.000, per-bird-track FNR 1.000, `evidence = 10 visible bird-frames over 3 birds`,
  `labels = 10 modeled`; decision rule ->
  **`EVIDENCE INSUFFICIENT -- no ADR-003 verdict from this clip. This is neither a confirmation nor a
  refutation: 10 of 10 visible bird-frames carry labels that are not measurements (10 modeled)`**.
  Amendment 5's printed `AMBIGUOUS -> default to (a)` is therefore **withdrawn**: it was produced by
  the pre-guard harness from labels that could not support it. The detections themselves reproduce
  byte-identically.
* **What this clip DOES establish, alignment-independently (a diagnosis, NOT a scored verdict, and
  it must not be quoted as precision/recall/FNR):** 22 detections in 935 frames, **all 22 birds,
  none spurious**; and for **every** lag hypothesis in [0, 0.70] s there is **no frame where a bird
  was in view and the detector produced nothing** -- at the measured lag band the "bird in view" and
  "detector fired" frame sets are the same 18 frames, both directions. The NDVI-direct arm looks at
  least as good on the real render as on the spike. It stays unscored until labels are measured.
* **Criterion 2 remains blocked, and now with numbers.** `baseline_rgb`'s 5 real-render detections
  are: three on bird_2 by a **2-LSB blue-channel accident** (bird patch min-channel 111.8 vs soil
  109.7 -- soil's own minimum is blue at 111) at 8 px against a true 21 px bird, i.e. **IoU 0.145,
  below the 0.3 bar even with perfect labels**; and two bottom-right corner artifacts with no bird.
  The documented inversion stands. The clean unblock is a gate2-style per-class PIXEL study on the
  real render (the evidence path that produced (a)'s -0.61) -- **not** calibrating (b) against (a)'s
  detections, which would destroy the arms' independence.
* **Criterion 3 stays OPEN; the reason it is open has changed for the third time** (geometry ->
  throughput -> ground-truth alignment -> **the alignment fix awaiting one flight**). What remains is
  no longer analysis: one re-fly with the logging driver, then `eval/run_spike.sh`. The driver half
  of the fix is **UNGATED until that flight** -- its first live check is that the log exists, its sim
  span overlaps the clip, and the annotator reports `applied` labels rather than `modeled`.
* **Regression pinned on the real clip, not a fixture:** `tests/fieldguard_planning/
  test_bird_label_timing.py` runs against the committed `real_flight_20260822T215516Z` and holds
  both halves -- detections are birds at a lagged time; modelled labels sit >= 94.98 px away with
  IoU 0.000 on all 22. Suite 449 -> 477 passed, 2 skipped.
Owner / roles: perception-ml-engineer (measurement, fix, guard, re-score); flight-software-engineer
owns the driver at flight time and the re-fly's live gate; robotics-sim-engineer for the retracted
ADR-012 cadence claim. Deferred without prejudice: issuing the three set_pose calls concurrently
(would shrink the ~0.5 s latency and the ~2 m hop) — a fidelity change to flight behaviour that
must not ride along with the labelling re-fly; one variable per flight applies to proof flights too.

### ADR-013 amendment 11 (2026-08-23, the delegated avoidance demo): the loop's first run on the current stack closes the ledger 720/0 — and the runbook, not the orchestrator, decided the flight's scope
**Delegation note #2:** the user delegated this AVOIDANCE_DEMO.md flight explicitly (same
mechanism as amendment 10; the rule otherwise stands). Flown via the runbook's 5-line MAVProxy
recipe; bringup in its order (agent before SITL); DISARMED at 121 s.

* **The event chain, from the flight log:** 19 detections → 1 takeover (AUTO→GUIDED at wp 6,
  trigger range 9.27 m) → 1 latch + 7 re-latches, **19/19 maneuvers vetted `accepted`, 0
  rejected**, each re-vetted on the tick it was sent → resume on `threat_cleared` at wp 7.
  `check_live_flight_log` PASS: **covered=720 debt=0**, partition sums exactly 720 (the 2026-08-18
  run closed 513/207 — this is the first FULL closure). Invariant checked directly on the
  artifact: 19 commanded setpoints, 0 overlap with the 984 flown-path points. Honest wrinkle,
  logged not smoothed: `resumed_same_waypoint: false` — the vehicle passed wp 6 mid-dodge and
  resumed at 7; ADR-006's MIS_RESTART claim is about not restarting at #1, and the log does not
  overstate it.
* **Scope, decided by the runbook over the orchestrator's brief (am. 10's precedent, applied
  twice):** the threat is the runbook's scripted `--demo` bird on the `detection_source` seam —
  no bridge, no fuser, no live detection on the real render, and `drive_birds.py` never runs, so
  the am.-6 applied-pose logger remains UNEXERCISED (its first live outing is the criterion-3
  re-fly, which runs the flagship path). **What remains genuinely unexercised after this flight
  is the combination: avoidance driven by a REAL detection off the NDVI render — the ADR-009
  rule-2 seam, Week 6's work — and it needs a runbook that does not exist yet (avoidance node +
  bridge/fuser in one bringup). Scoped, not improvised.**
* **Runbook drift, found and reported rather than adapted around:** (1) AVOIDANCE_DEMO.md
  delegates bringup to archived WEEK3_VALIDATION.md, whose SITL line lacks `--enable-DDS` and
  would produce zero `/ap/*` topics — the current canonical line satisfies the runbook's own
  stated prerequisite and was used; the archive doc needs a pointer fix. (2) Its Gate-1 tree
  check (`gz topic -l | grep model/tree_row0_0`) is structurally stale — static models advertise
  no pose topics. (3) No launcher path exists for this flight; it remains 4 manual shells.
* **Handed to qa-safety-reviewer, from the executor's own audit:** one numerically unstable tick
  at trigger range 0.052 m — the away-vector flipped and an accepted setpoint carried
  `swept_tree_clearance_m 0.846` (7-8 m on every other tick), accepted because
  `lateral_tree_margin_m` is 0.0; re-latched away one tick later. Not a failure in this flight;
  exactly the class of boundary a regression scenario exists to pin.
* **Process miss, recorded:** continuous load sampling did not run (sampler raced the tmux
  session and exited); host-quiet is evidenced by bracketing samples only (pre ~78 % idle, post
  ~87 %, one container both ends). Immaterial to an event-logic flight; would not be acceptable
  on a throughput measurement.
Owner / roles: flight-software-engineer (delegated pilot + executor audit); qa-safety-reviewer
takes the zero-range tick; robotics-sim-engineer takes the runbook drift fixes.

### ADR-013 amendment 12 (2026-08-23, qa-safety-reviewer adversarial pass on amendment 11): the demo encounter was a de-facto bird strike under green gates — CPA is now the number that must exist
The zero-range tick amendment 11 handed over was real (S4 below) — and the pass found four
findings that outrank it. All 19 ticks of the flown encounter replay bit-identically in
`tests/fieldguard_planning/test_degenerate_range_avoidance.py` (36 tests; CURRENT behavior
pinned, WANT behavior as paired xfails, mutation-proved).

* **S1 (critical): closest approach to the bird was 0.0518 m against the policy's own
  `min_bird_clearance_m` 3.0 — every gate green.** From the first accepted DIVERT (range 9.27 m)
  the vehicle gained 45 mm across-track in six ticks while closing 9.3 m along-track, still at
  6.57 m/s at CPA, moving AWAY from its own dodge target: candidate 0° (straight away) is a full
  reversal — the one escape ownship momentum forbids in a head-on closure at 7.7 m/s with 1.56 s
  of cylinder warning. Nothing in the pipeline computes CPA; "19/19 vetted" is a claim about
  setpoints. The runbook's proof standard said "avoidance exercised", and it was — the exercise
  revealed the loop's success metric was missing.
* **S2 (high, vacuous green):** `is_safe_3d` and the ADR-006 executor backstop are structurally
  unreachable in the flown configuration (setpoints pinned to 15 m cruise; trees end at 4.8 m) —
  `gate_reject: 0` meant COULD NOT FIRE. The gate re-arms below ~4.8 m; it is live code, armed
  and unproven.
* **S3 (high):** `lateral_tree_margin_m` defaults to **0.0 in code** and no caller or config sets
  it — the accept boundary IS the exclusion boundary; a dodge exactly tangent to a tree column
  is accepted (4.7 % of accepted degenerate-range dodges near rows clear by < 0.1 m). Bounded
  today only by two accidents: obstacle_radius 2.0 vs canopy 1.3 (0.7 m padding) and the
  10.2 m of altitude separation.
* **S4 (medium):** the away-vector has no range floor (guard at 1e-9 m): at the flown 0.052 m a
  0.5 m position error spans 337° of commanded bearing (6.2° at 9.27 m). The executor re-latched
  on the resulting 20.9 m setpoint jump — setpoint delta read as threat motion on a bird that
  never moved.
* **S5 (medium, latent):** the policy is the SOLE boundary authority (no ArduPilot `FENCE_*`
  set); setpoint-containment implies path-containment only by the polygon's unstated convexity;
  lanes x=0/x=75 lie ON the boundary (118/984 flown points ε-outside, worst 7.3 cm); `_handle_hold`
  sends an unvetted setpoint.
* **Side finding (favourable, unverified):** the camera's 18.46 m swath at 15 m exceeds the 15 m
  lane pitch, so coverage.py's 7.5 m half-width UNDER-claims — closeable on paper once
  `verify_mount_geometry.sh` asserts the wide axis is across-track. Not closed until it does.

**Recommendations, ranked (R1 ships now; control-law changes wait for their live gate):**
R1 add CPA-to-any-detection to `check_live_flight_log.py`, INVALID below `min_bird_clearance_m`
— it will fail the 2026-08-23 log, correctly (that log gets an acknowledged-finding marker so
the failure is loud without lying about history). R2 `lateral_tree_margin_m = 1.0` (the 18-tree
geometry supports it 3×; replaying the encounter keeps 19/19 DIVERT, rotates the bad tick to
+45° at 7.56 m clearance, reduces relatches 7→6). R3 policy flags `range_degenerate` below 1.0 m
and the executor refuses to RE-LATCH on a degenerate tick (keeps `decide` pure; hold-and-climb
deliberately NOT chosen — ADR-009 says bird z is the estimate we cannot trust). R4 the
reversal-preferring candidate order is recorded as an open control-law question (needs closing
geometry v1 doesn't have) — not ridden along. R5 an ArduPilot FENCE_* polygon as independent
backstop + lanes moved ≥1 m inboard. R2/R3/R5's live gate: the next avoidance flight, with
"every swept_tree_clearance_m ≥ 1.0" and "no relatch below 1.0 m range" asserted in the log.
Not tested, stated plainly: no flights, no dynamics model (no WPNAV_* pinned — stopping-distance
claims would be invented), one static bird / one altitude / one encounter; the descent case and
staleness gate remain armed-and-unproven.
Owner / roles: qa-safety-reviewer (found, pinned, priced); flight-software-engineer takes R1 now
and R2/R3 behind the next avoidance flight's gate; product-lead: this outranks polish — the
avoidance story is priority #1 and currently reads better than it flew.

### ADR-013 amendment 12 addendum (2026-08-23, R1's first run): a SECOND breaching flight, five days and one executor revision earlier
`check_live_flight_log.py` now computes CPA-to-any-detection (horizontal on purpose — ADR-009
says bird z is the estimate we cannot trust; the bar is read live from `PolicyParams`, one source
of truth). Its first pass over the committed evidence found the 2026-08-18 avoidance run breached
too: **CPA 0.0597 m** (61 detections, pre-latch executor) beside the 2026-08-23 run's 0.0518 m —
same static demo bird, different executor era. **S1 is the escape geometry, not the re-latch
logic**; R2/R3's live gate carries unchanged. Both historical logs carry `SAFETY_FINDING.md`
acknowledgement markers: the checker reports them loudly as ACKNOWLEDGED (exit 0, never VALID);
an unmarked breach or a stale marker fails hard. A clean log prints its CPA; no detections reads
NO-CPA-EVIDENCE, never a silent pass. Suite 530 passed / 2 skipped / 2 xfailed.

### ADR-003 amendment 7 (2026-08-23, criterion 3 CLOSED — the real-render re-run on measured labels): ADOPT (a) NDVI-direct
Flown delegated per ADR-013 am. 10's mechanism (user authorization: "fly it"); the FULL_PIPELINE
path with ONE variable against the am. 10 take — the am. 6 logging driver, on its first live
outing. Its gate PASSED: applied-pose log present (860 calls, 839 landed, 21 failed = 2.4 %),
span overlapping the clip, annotator provenance **2232 applied / 1536 spawn / 0 modeled**. The
achieved driver rate measured at 1.19 Hz of the requested 2.00 — the misalignment am. 6
diagnosed, now measured instead of modeled.

**The decision rule, verbatim:** evidence 20 visible bird-frames, 3/3 birds; (a) per-bird FNR
**0.000** (bar ≤ 0.1); (a) frame FNR 0.150 vs (b) 1.000 → **ADOPT (a) NDVI-direct** — clears the
per-bird bar and fidelity wins the tiebreak. Arm (a): TP=17 FP=7 FN=3, precision 0.708, recall
0.850, **every bird detected before closest approach** (bird_0 2/2 at 3.95 m, bird_1 4/5 at
6.97 m, bird_2 11/13 at 8.97 m). Arm (b) 0.000 across the board — the documented inverted
birdness, deliberately untouched; criterion 2 still awaits its independent pixel study.
**Criterion 3's three-cause history closes measured at every step: geometry (ADR-015),
throughput (ADR-013 am. 6-9), ground truth (am. 5-6), verdict (this).**

* The flight itself: another 720/720 map at a bit-perfect 5.00 Hz (1286 ticks → 100.00 % both
  bands → 1256 written, 0 unaccounted, end-to-end 97.67 %); tree gate PASS 18/18 imaged; host
  quiet sampled THROUGHOUT (the am. 11 sampler race fixed and verified writing before arming).
* **The −0.61 threshold's PROVISIONAL blocker is discharged, the label not yet lifted:** it now
  has precision/recall behind it (0.708 / 0.850) and supports the decision with margin on the
  safety bar — but n=20 with 7 FP / 3 FN is thin and 8 of 20 labels are `label_ambiguous`
  (inside a set_pose bracket). Lifting PROVISIONAL is perception-ml-engineer's call after the FP
  sources are characterised.
* **Predictor accuracy, first check against measured labels:** bird_1 (5 vs median 6) and bird_2
  (13 vs 11) in range; **bird_0 measured 2 against a predicted minimum of 3** — the
  uniform-sampling model is optimistic per-bird even when the total is close. Do not quote a
  per-bird median as a floor.
* No avoidance node on this path by runbook scope: no flight log, hence no CPA verdict — stated,
  not invented.
Owner / roles: flight-software-engineer (delegated pilot, gate + chain); perception-ml-engineer
(owns the PROVISIONAL call and the criterion-2 pixel study); the 0.445 synthetic precision bar
stands as the bar any learned model must beat.

### ADR-003 amendment 8 (2026-08-24, the adopted detector gets ONE home): `src/fieldguard_planning/ndvi_detect.py`, proved by a bit-identical re-score
Decision: the am. 7 ADOPTED core (`SYNTHETIC_THRESH`, `REAL_RENDER_THRESH`, `detect_blobs`,
`detect_ndvi`) moves **verbatim** into `src/fieldguard_planning/ndvi_detect.py`; `eval/blob.py` is
**deleted, not shimmed**; `eval/baseline_ndvi.py` and `eval/baseline_rgb.py` import the core and
re-export the constants instead of re-declaring them (pinned by a test). The live node and the eval
harness now run the same lines. Alternative(s) rejected: a numpy reimplementation so the container
needs no scipy — a hand-rolled morphology is a different detector wearing the same verdict, and
re-earning ADOPT costs a flight; a shim left at `eval/blob.py` — two homes for one concept.

**Equivalence gate — PASS, bit-identical, both arms** (host numpy 1.26.4 / scipy 1.13.1), the check
the artifact cannot fake: `baseline_ndvi.py` on `eval/results/clips/real_flight_20260823T073644Z`
→ thresh −0.61 → **24 detections over 1256 frames**, `frames` **identical** to the committed
`eval/results/adr003_20260823/detections_ndvi.json`, `params` identical (−0.61 / min_area 6 /
max_area 5000, `thresh_provisional: true`); `baseline_rgb.py` → thresh 110 → 4 detections,
identical. `score.py --iou 0.3` reproduced `spike_scores.json` by dict equality: TP=17 FP=7 FN=3,
precision **0.708**, recall **0.850**, frame FNR 0.150, **per-bird-track FNR 0.000**, 20 visible
bird-frames over 3 birds (8 `label_ambiguous`), verdict **ADOPT (a) NDVI-direct**. The synthetic arm
re-ran end-to-end too (seed 42: TP=53 FP=66 FN=1, precision 0.4454, FNR 0.0185, per-bird 0.000) and
still passes `scripts/check_spike_regression.py`. A pre-change baseline was captured first, so the
move is provably neutral rather than coincidentally green.

* **Regression pinned three independent ways** (`tests/fieldguard_planning/test_ndvi_detect.py`, 29
  tests): hand-derived morphology semantics worked out before running (half-open boxes, area counted
  POST-morphology — a 5×5 square is 21 px, not 25 — 8-connected labelling, raster order, no
  mutation); three real float32 NDVI frames committed as a 24 KB `.npz` whose expected boxes are
  READ FROM the artifact, not retyped, and whose arrays are compared element-wise to the clip's own
  `.npy` where the clip is on disk; and the whole 1256-frame clip re-scored (skipped in CI, where the
  gitignored `.npy` bulk is absent).
* **Finding — the image border is structurally invisible to this detector.** Closing ends in an
  erosion with `border_value=0`, so the outermost row/column can never survive; the committed
  evidence obeys it exactly (across all 24 boxes: min x0 = 1, max x1 = 639 = W−1, max y1 = 479).
  Consequence for the ADR-009 ray: a bird straddling the frame edge measures 1 px small on that side
  and is therefore ranged slightly **farther** than it is — ~2-5 % of range on a 20-50 px blob,
  small but one-sided and un-conservative. Now a test with the derivation written down; no code.
* **Finding — the area filter was never binding on the adopted clip.** All 24 accepted components
  measured 94-1781 px against bars of 6 and 5000, and no frame produced mask pixels the filter then
  rejected. 6/5000 are speck/saturation guards, not tuning — so the 7 FPs are real blobs, which is
  what the FP characterisation has to explain.
* **−0.61 stays PROVISIONAL** and is now an explicit node argument (`--ndvi-thresh`, ADR-009 am. 1),
  marked in three places: the constant's comment, the node's startup warning, and
  `run.detector.thresh_provisional` in the flight log. Lifting it remains perception-ml-engineer's
  call after the FP characterisation. A now-false line in `baseline_ndvi.py`'s stderr warning
  ("never yet checked against precision/recall") was corrected — am. 7 closed that.
* **Transfer is verified on ONE scipy version.** Host 1.13.1 only; CI pins 1.18.0 (the new test file
  IS that check — a red there is a genuine finding that the ADOPTED verdict does not transfer to the
  pinned dependency, not a flaky test) and the container ships jammy's 1.8.0 (unrun — ADR-004 am. 1).
* Criterion 2 is unchanged and still **not a comparison**: `baseline_rgb`'s birdness is inverted on
  this world, so its 1.000 FNR measures the wrong signal and must not be quoted as RGB's ceiling.
Owner / roles: perception-ml-engineer (core, the PROVISIONAL call, criterion 2); tech-lead (recorded).

### ADR-004 amendment 1 (2026-08-24, the image gains the detector's one dependency): `python3-scipy`, and a rebuild becomes a flight precondition
Decision: add `python3-scipy` as **one token** on the existing ArduPilot-build-deps apt line in
`sim/docker/Dockerfile` (no new layer, no pip), because `scipy.ndimage` IS the morphology the ADOPT
verdict was measured on (ADR-003 am. 8). Alternative(s) rejected: `pip install scipy` at container
runtime — a band-aid that makes the image non-reproducible and re-runs every session; a numpy
reimplementation — voids the measured transfer; running the detector host-side over a topic bridge —
invents a new hop on the band that has starved this system twice (ADR-013 am. 7-9).

* **Consequence, and it is on the critical path: the image must be rebuilt before the take** —
  `scripts/sim_docker_build.sh` then `scripts/sim_docker_run.sh` (multi-hour), plus the GHCR image if
  the session pulls rather than builds (`sim-image.yml`'s push trigger is commented out — manual
  `workflow_dispatch`). Until then `fly_pipeline.sh up` **refuses**, by design, including for demo
  takes.
* The tripwire lands in the EXISTING `preflight()` seam: `docker exec fieldguard-sim python3 -c
  'import scipy.ndimage'` (~200 ms), which **dies with the two rebuild commands** rather than
  apt-installing like the bridge-deps block above it — scipy missing means the IMAGE is stale, and
  pip-installing would hide the drift and burn the next session too. A matching `--dry-run` line keeps
  the enumeration parity `tests/test_fly_pipeline.py` pins. Node-side, `--detect` exits 2 with the
  rebuild instruction on `ImportError`; there is no numpy fallback, ever.
* `sim/docker/Dockerfile.ci` deliberately untouched (build-only image, never runs the detector), so
  **no CI job exercises the container-side import** — the preflight is the only gate on it. Named,
  not fixed: adding scipy to the CI image grows a multi-hour build for zero coverage of a path CI
  cannot run.
* **Unproven until a human rebuilds:** apt availability of `python3-scipy` on jammy (both prior image
  bugs — the dash SHELL and the emptied apt lists — surfaced only at build time), and the 1.8.0
  behaviour transfer. The runbook's preflight 0c re-scores the am. 7 clip in-container and requires
  bit-identical boxes; any diff is a scipy behaviour change and the flight does not fly.
Owner / roles: devops-reliability-engineer (image + preflight), robotics-sim-engineer (rebuild),
tech-lead (recorded).

### ADR-009 amendment 1 (2026-08-24, the seam is WIRED — offline): one clock domain end-to-end, the staleness gate finally armed, and the ray implemented with its ground-plane counter-proof as a test
Status: both contract rules are implemented behind `avoidance_node --detect` and measured offline.
**Nothing here has flown** — this stays confirmation-pending until the next avoidance flight.

**Rule 1 — the clock. BINDING: absolute Gazebo sim seconds, end to end, inside `avoidance_node`.**
The mechanism is the one `record_node`/`clip_recorder` already ship — a native `gz topic -e -t
/clock` subprocess feeding `StreamingClockParser`, plus a `PoseBuffer` — reused, not reinvented;
never a bridged `/clock` (bridging it collapsed the fused frame rate ~8× when measured live
2026-08-18).
* **The defect it fixes, and the worse one the obvious fix would have been.** The node built
  `t = get_clock().now() − t0` (elapsed wall seconds) and called `decide_multi` with **no `now_s`**,
  so `max_detection_age_s` could never evaluate. Passing that same `t` would have been WORSE: NDVI
  stamps are absolute gz seconds, so `age = elapsed − absolute` is large and **negative** — every
  detection reads fresh forever, silently, because unstamped detections fail OPEN by design.
* **Tripwire:** a detection stamped more than `CLOCK_DOMAIN_BOUND_S = 0.5` s in the future counts a
  `clock_domain_violation` (warn on the 1st and 10th); the flight-log gate fails any schema-2 log
  with violations > 0. Offline proof, paired: absolute stamps against an elapsed clock violate on
  **every** tick, and the same 60 s-old detection is PROCEED (`n_stale_dropped=1`) on the right clock
  and **DIVERT** on the wrong one — a test that only checked "stale is dropped" would pass with the
  clocks crossed.
* `--detect` **refuses to start** without a clock reading (10 s poll, exit 3): a startup check is
  cheaper than a burnt take. Without `--detect` the clock stays optional, so `--demo` is unchanged.
* Each NDVI frame pairs to `PoseBuffer.nearest(frame stamp)`, not to the latest pose: at 7.7 m/s an
  0.4 s pairing error is 3 m of bird-position error — exactly the magnitude that destabilises the
  away-vector. `DroneState` for the policy still uses the latest pose; different uses, both correct.
* **The gate is now ARMED: `PolicyParams.max_detection_age_s` None → 1.0**, with ONE home — the
  node's constant is deleted, not aliased (the anti-drift shape R2 established). `avoidance_node`
  declares nothing and passes nothing; it carries a NOTE naming where the bound lives, and a test
  reads the node's own source to pin the absence, because "one knob, two homes" is only prevented by
  something that fails when the second home reappears. Evidence, not taste: the am. 7 clip's own
  `frame_age_sim_s` is min 0.061 / p50 0.143 / p95 0.149 / **max 0.156 s** (n=1256), so 1.0 s is ~6×
  the measured max and ~3× worst-case-plus-one-control-period. Unstamped detections still fail OPEN.
* **What the gate throws away is now in the artifact.** `n_stale_dropped` / `stale_ids` /
  `max_detection_age_s` ride the PROCEED and HOLD events too, not only an accepted DIVERT — written
  only when something was actually dropped, so a healthy tick pays nothing. All-stale is precisely
  the case that produces PROCEED, so before this the counter that exists to reveal a dead loop read
  0 exactly when the loop was dead (`gate_detector_ran` reads the pair — ADR-013 am. 14 (b); the
  probe that forced it is am. 15 F2).

**Rule 2 — the ray, implemented.** `range_from_apparent_size` and `pixel_at_depth_to_enu` land in
`ndvi_georef.py` beside their forward twin `project_world_point` (round-trip < 1e-9);
`box_to_detection` uses r_px = 0.25·((x1−x0)+(y1−y0)), the same disc convention the labeller builds
GT boxes with; `pixel_to_ground_enu` is never called on this path. **The ADR's rationale is now an
executable assertion, not prose:** same pixel, same pose — the ray DIVERTs, the ground plane
PROCEEDs, because it puts the bird at |dz| = 15 m against `vertical_threat_m` 6.0. That test is the
interview slide.
* **The "conservative inflation factor" of the original ADR is COLLAPSED into one number:**
  `BIRD_RADIUS_PRIOR_M = 0.15` against the world's true 0.18 m. Zc scales linearly with R, so two
  multiplicative knobs for one scalar is a speculative flag; under-estimating radius under-estimates
  range, which places the bird NEARER — dodge early rather than late — and it stops the detector
  reading the answer out of the world config it is meant to be inferring.
* **Measured consequence, both directions, offline over the adopted clip** (1256 frames, 645
  airborne): **range-estimate error vs applied-pose truth median 1.65 m / max 3.67 m (n=24)** —
  materially larger than the single 3.27-vs-3.92 m case am. 7 quoted. And a new finding:
  under-ranging is conservative for RANGE but **not** for the cylinder test, because it shrinks |dz|
  too. It biases opposite to the border-trim bias in ADR-003 am. 8; neither is worth code yet.

**The pre-flight dry run, with a denominator** (the number that decided bookability): running the
live `NdviDetectionSource` over the adopted clip's own poses/intrinsics reproduced the committed
boxes **bit-identically** (24 boxes / 20 frames) and would have produced an in-cylinder threat on
**8 of 1256 frames (0.64 %), 8 of 645 airborne (1.24 %)**, in ~3 clusters — bookable, not a dodge
storm. Five of the eight coincide with a real in-cylinder bird; **the other three are bird_1 (true
|dz| 7 m) lifted INTO the ±6 m cylinder by the prior's under-ranging** (estimated |dz| 5.85-5.99 m).
`detect_wall_ms` p95 **4.8** / max 26.9 ms against the 200 ms tick, so the detector will not block
the single-threaded executor. A dress rehearsal (101 encounter frames → `PoseBuffer` → `on_frame` →
tick → run block → `check_live_flight_log.py`) had the gate consume the artifact, auto-discover the
truth track, and print `gt_cpa_m 0.177 m` vs `detection_cpa_m 0.026 m` at 101/101 truth coverage.
It also produced **2 relatches in 5 maneuvers**: monocular jitter can exceed the executor's
`RELATCH_THRESHOLD_M` 3.0 m, so re-latch churn is the live watch item — the lever is that threshold
or a tracker, decided on the flown measurement, not now.

**Deliberate non-features, each a component NOT built:** no tracker (`track_id=None` — the threat
test is per-frame and the executor latches on geometry, so an ID that exists to look sophisticated
would be untested state); no second expiry inside the source (ageing out is `max_detection_age_s`'s
job and only its job).

**Surface decisions, one sentence each.** The threshold is a **CLI argument** (`--ndvi-thresh`), not
a ROS 2 parameter: there is not one `declare_parameter` anywhere in `src/`, and the number that
matters is the one recorded in the artifact, not the one queryable at runtime. Intrinsics come from
the LIVE `/fg/ndvi/camera_info`, never `config/ndvi_camera.json` — the config is what we asked for,
the message is what we got — and the pre-`camera_info` window is COUNTED (`dropped_no_intrinsics`),
because a silently-discarded window is exactly the defect ADR-013 am. 6a found in the recorder. The
NDVI subscription is BEST_EFFORT depth 1: a control loop wants the newest frame, not every frame,
and this keeps a third reader off the RELIABLE NACK-repair path am. 8 priced. `argparse` is now
strict (an unknown flag exits 2) so a typo cannot silently fly a no-detector flight. The per-tick
path was extracted as a pure `AvoidanceLoop` (stdlib, no rclpy) precisely so the clock bug could be
driven with a deliberately wrong clock; the node is thin wiring around it and writes
`log["run"]` (schema 2) itself, leaving the executor's signature untouched.

**Also corrected while there:** `proximity_bird_source` / `scripted_bird_source` now tag
`source="demo_virtual"` instead of inheriting `Detection`'s `"ndvi_blob"` default — a virtual bird
had been claiming to be an NDVI blob in every log ever flown, and the safety gate branches on that tag.

**Not flown, stated plainly:** the gz CLI subprocess, the live BEST_EFFORT subscription, the
`camera_info` arming window and the startup refusal have never run against a real Gazebo. The dry run
and the dress rehearsal replayed recorded frames through the identical code path — as close as the
host can get.
Owner / roles: flight-software-engineer (seam, node, clock); perception-ml-engineer (detector core,
threshold); qa-safety-reviewer (the gate that reads it); tech-lead (the binding calls above).

### ADR-012 amendment 2 (2026-08-24, the applied-pose log is promoted to the flight's GATED ground truth): schema 1.1 measures the /clock poll instead of assuming it away
Decision: the bird ground truth the new CPA gate scores against is the applied-pose log
`drive_birds.py` already writes — **no writer redesign**, because the log already recorded gz-stamped,
applied-only poses. It is read by the gate through the SAME functions that build the ADR-003 labels
(`read_applied_log` / `applied_sim_brackets` / `applied_timeline` / `pose_from_applied` / `pose_at`),
imported and never re-implemented: if the bird-pose reconstruction is ever wrong, the labels and the
safety gate must be wrong together, never one silently right.

* **The defect an audit found, measured not suspected.** The log claimed `tick_sim_s` was observed at
  `tick_wall_s` — but `tick_wall_s` is taken BEFORE the `gz topic -e -t /clock -n 1` subprocess that
  produces the reading. On the 2026-08-23 take that poll cost **39 ms median / 42 ms p95 / 146 ms
  max**; at that flight's measured RTF (0.34-0.93, median 0.58) it is up to ~0.8 m of bird motion
  asserted with false precision, against a 3.0 m clearance bar and two 5 cm historical breaches.
* **Applied-pose schema 1.1** adds `clock_wall_s` (the instant the reading was parsed), so the tick
  anchor is an interval the driver MEASURES rather than a point it assumes; `applied_sim_brackets`
  widens each bracket over that interval (latest possible start, earliest possible end) so
  uncertainty can only widen the ambiguous window, never narrow it. A test proves the change is
  load-bearing: on identical data the old zero-width anchor places the bracket AFTER the pose had
  already landed — a confident wrong label with no ambiguity flag.
* **Backward compatibility pinned on the real artifact:** schema-1.0 records take the old path
  exactly, and the committed 860-record am. 7 log (839 landed / 21 failed, 3 birds, sim
  110.383-262.481 s) reconstructs **bit-identically** against HEAD's implementation. ADR-003 am. 7's
  labels cannot move retroactively.
* **Honest cost:** bracket widening raises the `label_ambiguous` rate ~16 % on FUTURE clips.
  `eval/score.py` counts those rather than dropping them, so this is a disclosure, not a regression.
* **Testable without Gazebo:** `drive_tick(...)` extracted with the set_pose service and the clock
  injected, plus a `FakeGazebo` whose replies consume wall time and land at instants nothing records
  — which let `main()` itself be flown offline, and caught a real bug (`now=time.monotonic` as a
  default argument binds the clock at import, so per-call timestamps would have come from a different
  clock than the tick anchors). 31 tests.
* **Operator path:** on Ctrl-C the driver prints the sim window its truth covers and the exact
  `check_live_flight_log.py ... --truth <path>` line, because sim time restarts near 0 every run and
  every take's log otherwise looks alike.
* Unflown: schema 1.1 has never been written by a real flight — expect `clock_wall_s − tick_wall_s`
  ≈ 0.039 s in the first one. `--once T_S` still writes no applied log (deterministic Gate-2 shots),
  so a flight that used it would have no truth track and, under ADR-013 am. 14, would be INVALID.
Owner / roles: robotics-sim-engineer (writer + audit); qa-safety-reviewer (consumer); tech-lead.

### ADR-013 amendment 13 (2026-08-24, am. 12's R2 and R3 are LANDED — offline): the price is measured, the assertions exist, the LIVE gate is still owed
**R2 — `lateral_tree_margin_m` 0.0 → 1.0**, changed at its ONE home (`PolicyParams`). While there,
`AvoidancePolicy.__init__`'s duplicate 12-parameter signature was deleted in favour of
`(*, field_polygon=None, **params)` forwarding straight to the dataclass — one sentence: a
constructor default that can drift from the dataclass default the checker reads as its bar is exactly
how a safety knob gets raised in one place and flown from the other. An unknown knob is now a
TypeError, never a silently ignored kwarg.
* **Price, measured on the 11,856-case degenerate sweep:** HOLD 5.64 % → **15.66 %** (+10.0 pp on a
  deliberately tree-dense worst case, under am. 12's 15 pp bar); min accepted swept clearance 0.000 →
  **1.000 m**; sub-metre tail 28.1 % → **0 %**. On the flown encounter: still **19/19 DIVERT**, and
  the degenerate tick rotates +0° → **+45° at 7.563 m** clearance.

**R3 — degenerate-range re-latch refusal**, split exactly as am. 12 specified. The policy attaches
`debug["range_degenerate"]` to every threat-branch maneuver (DIVERT *and* HOLD), computed from the
**rounded** `trigger_range_m` that actually reaches the log, so the gate's flag/number identity holds
by construction at the boundary rather than usually — a flag derived from a number nobody can see is
a flag nobody can audit. `decide` stays pure. The executor, on a jump past `RELATCH_THRESHOLD_M` at a
flagged tick, keeps the already-vetted latch and logs a **fourth** `latch_action` value,
`relatch_refused_degenerate`; no latch event, no state change, so R3 is countable only from that
field. A maneuver with no flag (pre-R3 caller) keeps exact pre-R3 behaviour, pinned.

* **What R3 buys, and no more:** replaying the 19 flown ticks through the real policy + executor, the
  noise-driven setpoint (37.6, 36.6, 15) — built from an away-vector a 5 cm position error could have
  pointed anywhere — is **never commanded**; the re-latch lands one tick later (0.2 s) at 1.192 m
  where the away-vector is geometry again. Relatches 7 → 6 + 1 refusal. The harness first reproduces
  the flight's entire `latch_action` column at as-flown params before claiming any delta.
* **R3's scope, stated so nobody reads it as a safety property:** R3 refuses only a *re*-latch. The
  bird-reject path kills the latch outright, and a FIRST latch at degenerate range is still
  permitted — so on that path R3 buys **one tick (0.2 s) of delay**, not a permanent refusal to act
  on a degenerate range. What actually keeps a degenerate-range setpoint from being commanded is the
  executor's bird-clearance backstop below, not R3.

**R3's own backstop — the executor's guarantee 1 gains a second half.** A refusal keeps a point that
was bird-vetted on the tick it was LATCHED, and the executor's only backstop was `is_safe_3d`, which
cannot see a bird at all: the refusal could therefore command a point the policy would refuse to
place today (measured: 1.000 m from the bird against the 3.00 m bar — am. 15 F3). The fix is
deliberately **wider than the refusal**, because the ordinary re-command path has the identical hole
and a refusal-only guard would leave the gate asserting more than the control law guarantees: every
point this module hands to the sink is now re-vetted against `is_safe_3d` **and**
`min_bird_clearance_m` over `debug["threat_positions_enu"]` — the policy writes those positions
beside `threat_ids`, so ALL in-cylinder threats are covered, not only the trigger. The bar is read
from that maneuver's own logged `debug["params"]`, never a second literal in the executor, and a
maneuver carrying no params fails OPEN (the same doctrine as the missing `range_degenerate` flag).
Rejection logs `gate_reject` with `bird_clearance_m` / `bird_track_id`, keeps the
`relatch_refused_degenerate` label, drops the dead latch so the next tick can latch fresh, and HOLDs.
* **What that claim is, exactly, stated so it cannot be read wider — and the guarantee is now NAMED
  for its own scope.** The vetting covers the point this module COMMANDS a DISPLACEMENT to, which is
  why guarantee 1 reads **"Never fly an unvetted DISPLACEMENT"** (round 3 renamed it from the wider
  wording it used to carry). The HOLD it falls back to is the vehicle's own current position — ZERO
  displacement, so it chooses no point, honours no clearance bar, and **can be nearer the bird than
  the point it just refused** (measured on one worked geometry: refused at 1.000 m, held at
  0.400 m). On the degenerate branch that hover point is inside the bar **by construction**, since
  the branch is only entered within `degenerate_range_m` of the trigger bird. So the guarantee is
  "this module never commands a NEW point inside the policy's bird bar", not "the vehicle stays 3 m
  from every bird". Proximity is escape geometry, and escape geometry is R4. The exemption is written
  into the module docstring as its own paragraph carrying those numbers, so the scope cannot be read
  wider from the code either.
* **Second-order behaviour, recorded rather than patched:** a bird-reject drops the latch, so the next
  tick may latch the same setpoint FRESH (a first latch at degenerate range is permitted by design).
  On that path the refusal is the same one-tick (0.2 s) delay measured above, not a permanent refusal.
  That sentence now also lives in the executor's design note 3, next to the code it describes.

**The assertions, in `check_live_flight_log.py`, schema-2 logs only, every bar read from
`PolicyParams()` at call time and never a literal** (the R1 precedent: a second `3.0` in the checker
would let gate and control law drift apart silently): every maneuver's `swept_tree_clearance_m` ≥ the
flown `lateral_tree_margin_m`; the flown margin ≥ today's default; **no `relatch` with
`trigger_range_m` below `degenerate_range_m`** — gated on the NUMBER, so a lying flag cannot buy a
re-latch; the flag/number identity (a mismatch means policy and executor are at different versions);
the flown `degenerate_range_m` ≥ today's default; and **R3.7** — every COMMANDED `setpoint_enu` kept
`min_bird_clearance_m` from every position in that decision's `debug.threat_positions_enu`, the same
inequality the executor now applies live, re-checked offline on the artifact. Refusals are counted
and reported — R3 doing its job must be visible, not inferred. With zero accepted dodges the line
reads **`R2/R3 PASS (vacuous): 0 accepted dodges to check`** in those words, because a gate that
passed because it measured nothing must say so.
* **R3.7's honest scope, because the executor fix moved the evidence — and R3.8, which reads where
  it moved TO:** on a log the CURRENT executor writes, a commanded point inside the bar becomes a
  `gate_reject`, never a `maneuver`, so R3.7's BREACH branch is the **exhaustion** property
  (defence-in-depth over replayed, older or hand-edited logs, and over the executor's documented
  fail-OPEN path when a maneuver carries no `debug["params"]`); its live value is the
  missing-`threat_positions_enu` branch, since a maneuver whose commanded point cannot be checked at
  all is a hard problem. The `gate_reject` events are where a current flight's evidence lands, and
  **`gate_r2_r3` now reads them (R3.8, round 3)**: rejects are counted, bird-bar rejects split from
  geofence rejects, the closest refused point reported as the backstop WORKING, each scored against
  the bar THAT FLIGHT flew, and a reject explaining itself with neither an `obstacle_id` nor a
  sub-bar `bird_clearance_m` is a hard problem — the only way field-name drift there could stay
  silent. The layering is deliberate and worth saying out loud: **the executor fails OPEN on missing
  data, the gate fails CLOSED on it.**

**Test fallout, handled without weakening anything.** Both xfails are gone.
`test_WANT_every_accepted_dodge_keeps_one_metre_of_swept_tree_clearance` flipped on its own and is
now a plain assertion reading the bar from `PolicyParams`.
`test_WANT_the_encounter_holds_the_policys_own_minimum_bird_clearance` **could not be promoted
honestly** — it asserts CPA ≥ 3.0 on a FROZEN
artifact whose flown path no code change can move, and R2/R3 explicitly do not fix S1; it was a
permanent xfail wearing a tripwire's clothes. It is retired, with the 0.0518 m breach still pinned in
the CURRENT test, the marker's existence asserted, and the bar moved to where it can actually bite —
`test_the_bird_clearance_bar_this_log_missed_is_carried_by_a_live_gate_and_a_marker`, which the
2026-08-23 `SAFETY_FINDING.md` now names in place of its stale xfail bullet, so the marker and the
suite point at the same live gate. **Nothing in the suite now asserts that flight was
safe**, and a genuinely self-activating tripwire replaced the dead one: `test_R4_is_still_open` goes
red the day the reversal-preferring candidate order changes. Every `test_CURRENT_*` pin was re-pinned
by passing the AS-FLOWN params explicitly (margin 0.0) — history preserved, not deleted, and no
longer confusable with what the vehicle would do today.

**R4 and R5 are recorded as CUT TO OPEN for v1.** 18 of the 19 replayed ticks still take candidate 0°
(straight reversal) and S1's 0.0518 m stands; R5 (an ArduPilot `FENCE_*` polygon as an independent
backstop, lanes ≥ 1 m inboard) is untouched. Deliberate deferrals, named so they are decisions rather
than blind spots: the latched setpoint's swept path is **not** re-vetted as ownship moves (the
executor re-vets the POINT, not the segment); a FIRST latch at degenerate range is still permitted
(am. 12 scoped R3 to re-latch); `_handle_hold` still sends an unvetted setpoint (S5) — now with a
number on it, 41 of 10,000 swept control ticks commanded a hover inside the 3.00 m bird bar, closest
0.288 m, and since round 3 that number **reaches the artifact**: the executor logs
`bird_clearance_m` / `bird_track_id` / `min_bird_clearance_m` on every hold and `gate_r2_r3` prints
the minimum as `[CONTEXT, NEVER GATED]`, so the first `--detect` take will QUANTIFY R4's gap instead
of leaving it to an argument; `is_safe_3d` remains structurally unreachable at cruise (S2).

**The live gate is still owed.** None of this has flown. The next avoidance flight is R2/R3's gate,
and the expectation is **pre-registered here, before the take**: because R4 is not in it, that flight
may honestly FAIL its own GT-CPA gate — a pre-registered failure is a measurement that ranks R4 next,
not a wasted take. **A breaching NEW flight is INVALID and stays INVALID.** Acknowledgement takes TWO
halves and only one of them is the operator's: **write the `<log-stem>.SAFETY_FINDING.md` marker**
(the context half — the written finding, beside the evidence, so the next reader gets the reason with
the verdict) **and do NOT add the pin**. The pin — the log stem in `ACKNOWLEDGED_BREACH_STEMS`, a
reviewed diff on the safety gate — is what turns a breach into exit 0, and it exists for recorded
history that cannot be re-flown. A take that can be re-flown after R4 is a failed take, and pinning it
would make "add a file" the documented remedy for a red gate. So the marker is written, the pin is
not, and the gate says **INVALID / exit 1 naming the missing half** — which is the correct record. The
acknowledged set is therefore **frozen at the two historical stems** (2026-08-18, 2026-08-23); a third
is an ADR-level act that must name why that flight cannot be re-flown. See am. 17 for both halves as
shipped, and `docs/runbooks/AVOIDANCE_REAL_DETECTION.md` §6a for the operator's version.

**Separately, and resolved rather than left as a question: `eval/scenarios/*/flight_log.json` do not
model separation, so the CPA gate must not be pointed at them.** Run by hand, 3 of the 4 read INVALID
on the legacy CPA path (cov_bird_over_cell **0.0000 m**, cov_two_birds_simultaneous **1.0000 m**,
geo_avoid_into_tree **1.0000 m**; only cov_bird_at_turnaround passes at 7.0000 m) — verified
**pre-existing at HEAD**, identical verdicts under the committed-HEAD checker, not a session
regression. The reason is the harness, not the control law: `generate_flight_logs.py` walks the drone
along `nominal_path()` whatever the executor commands, so all four logs have exactly 116 path points
however many dodges they contain, and the "CPA" is the distance from a lawnmower lane to a STATIONARY
bird the fixture parked on it. They are decision/ledger fixtures with an open-loop vehicle; adding
them to CI's `check_live_flight_log.py` line would turn CI red on fixture geometry and teach the team
to widen a safety gate. Cheapest correct fix, and it is one sentence of prose: say so in
`eval/scenarios/README.md`. Note also that CI's existing line is NOT vacuous — `.gitignore` un-ignores
`eval/results/live_flight_log_*.json`, both historical logs are tracked, and CI runs the gate on them
(ACKNOWLEDGED, exit 0) on every push. The scenario logs' params are still stale (margin 0.0, no
`threat_positions_enu`); regeneration is one command (`python3 eval/scenarios/generate_flight_logs.py`)
and was deliberately NOT part of this round, so the diff stayed reviewable — **am. 16, later the same
day, regenerated them** (owed anyway, because today's control-law changes would otherwise have turned
CI's regenerate-and-diff step red on the first commit) and closed this call with a measured
open-loop proof.
Owner / roles: flight-software-engineer (policy + executor); qa-safety-reviewer (assertions);
product-lead (R4/R5 remain cut for v1); tech-lead (recorded, and the `eval/scenarios` call above).

### ADR-013 amendment 14 (2026-08-24, am. 12 R1's successor): GROUND-TRUTH CPA is the gated number, detection-CPA is demoted to an estimator check, and no truth track is a hard fail
Decision, the whiteboard sentence: **CPA is measured against whatever is genuinely ground truth for
that flight, and when the threat is an estimate the estimate is not allowed to be the referee.**
R1 shipped a CPA computed from the flight's own logged detections — correct while the bird was a
constant we chose, self-referential the moment a real detector supplies the positions.

* **Versioned, so history keeps the verdict it was flown under.** `check_live_flight_log.py` branches
  on `run.schema_version`. Absent → today's path byte-for-byte: the two historical breach logs
  (**0.0597 m** 2026-08-18, **0.0518 m** 2026-08-23) were verified to have no `run` key and still
  report ACKNOWLEDGED with byte-identical wording, exit 0 (re-verified at the close of the fix round
  by diffing stdout AND stderr against the same invocation of the committed-HEAD checker: zero bytes
  different). The four `eval/scenarios` logs take that same legacy path unchanged — 3 of the 4 read
  INVALID on it, which is a property of the fixture, not of this gate (am. 13). A
  `run` block that is unreadable or below version 2 is **INVALID, not quietly demoted** — demotion
  onto the weaker detection-referenced CPA is a downgrade attack, not a default. The node always
  writes the block, so the new contract cannot be flown without meeting it.
  **Corrected in place, round 5:** this bullet used to end "no filename special cases, ever", and that
  is precisely what left the door open — with the branch keyed on CONTENTS alone, `del log["run"]`
  demoted a schema-2 flight to the legacy path and a ground-truth INVALID came back VALID. Absence of
  a run block is now a legacy signal **only for logs pinned as pre-seam** (`PRE_SEAM_LEGACY_STEMS`,
  plus the `eval/scenarios/<name>/flight_log.json` shape); everything else is INVALID. The pin is
  deliberately a property of the FILE rather than of its contents, because that is the one thing a
  log's author cannot edit: adding a stem is a reviewed diff on this gate, exactly as with
  `ACKNOWLEDGED_BREACH_STEMS`. Full reasoning and the del-`run` probe: am. 17.
* **GT-CPA** (`detector.source == "ndvi_blob"`): minimum **horizontal** distance over (tick, bird)
  pairs that have truth coverage AND satisfy |bird_z − drone_z| ≤ `PolicyParams().vertical_threat_m`
  (6.0), against `min_bird_clearance_m` 3.0. Measured over the flown **polyline**, not its vertices,
  and in **TWO passes — one per axis of the discretisation, with `gt_cpa_m` the minimum over both**
  (`cpa_from` names which pass produced it). Pass 1 walks the TICKS: each tick's bird candidate set
  is scored point-to-**segment** against BOTH segments bounding that tick, so a pose that landed
  after the tick meets the segment the drone was actually flying, and it is the only pass that can
  answer before a bird's first landed call. Pass 2 walks the LANDED BIRD POSES: every `set_pose` call
  is scored against exactly the piece of drone polyline its own in-effect window covers (endpoints
  interpolated along the bounding ticks), so a pose whose whole window falls between two ticks is no
  longer invisible — the tick grid stops mattering. Both halves were forced by a probe: F4 in am. 15
  closed the drone axis, and round 3 (am. 17) closed the bird one, which was the larger half because
  the bird is the faster body. The vertical scoping is not
  optional — bird_1 and bird_2
  patrol 7-9 m below cruise and pass under the lanes constantly, so an unscoped horizontal bar would
  fail every flight forever and mean nothing; the band is the policy's own threat definition, read
  from `PolicyParams`, so gate and control law cannot drift. Horizontal not 3D because folding
  altitude in can only manufacture clearance and ADR-009 says bird z is the estimate we cannot trust;
  the 3D distance and vertical separation are reported as non-gating context, so "but it was 4 m
  below" is answered inside the artifact. Ambiguity inside a `set_pose` bracket resolves to the
  **nearer** candidate: uncertainty must not buy clearance.
* **No truth track = INVALID, including when the flight logged zero detections** — because zero
  detections is exactly what a missed bird looks like, and the old "NO-CPA-EVIDENCE → VALID" path is
  the hole a real detector re-opens. Refused as no-truth: absent file, a wall-clock driver run, an
  all-calls-failed log, no sim-span overlap, more than one overlapping candidate, or a bird the world
  config does not define. **`--truth` selects, it does not silence:** the candidate scan runs
  unconditionally, so naming one log while a second overlaps the same sim window is `AMBIGUOUS TAKE`
  → INVALID, naming the other file. Every tick carrying an avoidance event must have truth, and
  `truth coverage N/M ticks` prints on every flight — a rate with a denominator. Round 3 added the
  **second** denominator that number never was: `truth poses scored K/N landed set_pose call(s)`, the
  BIRD axis's own coverage, because tick coverage reads 100 % whether or not a landed bird pose was
  ever looked at.
* **Detection-CPA demoted, never gated:** printed as `detection_cpa_m (ESTIMATOR CHECK, NOT A SAFETY
  GATE)` beside `range_estimate_error_at_cpa_m` — the measured argument ADR-009 says the
  second-sensor comparison arm exists to make. Both directions are pinned: a detector claiming 1 cm
  while truth says 8 m still PASSES; one claiming 8 m while truth says 5 cm still FAILS.
  `demo_virtual` keeps R1's detection gate unchanged (that bird's logged position IS truth); source
  `none` must carry zero encounter events.
* **Three gates beyond the six enumerated, all named:** `max_detection_age_s` must be ARMED for an
  `ndvi_blob` flight (flown as None, the ADR-009 staleness gate cannot fire at all — the hole in the
  artifact rather than the code); an encounter tick outside `1..len(flown_path_enu)` counts as blind,
  not skipped; and zero accepted dodges says `PASS (vacuous)` out loud.
* **Mutation-proven, 12/12.** Every gate was mutated one line at a time in a scratch copy — drop the
  vertical scoping, make the band edge exclusive, fall back to detections when truth is missing, gate
  R3 on the flag, disable the knob floors, disable R2, skip the encounter-truth requirement, skip
  off-path ticks, resolve ambiguity in the flight's favour, ignore clock violations, let a marker
  waive failed gates, drop the vacuous label — and every mutant was killed. The headline regression
  flies ONE artifact twice: identical path, identical (absent) detections, legacy **VALID** →
  schema-2 **INVALID at 0.0500 m**.
* **Its own adversarial pass then found four defects an exit code of 0 could not see; all four fixed
  the same day.** (a) A **frozen time axis** — source, violations and length do not move when the
  clock stops; stamps may now not go backwards, a zero-span axis is refused, and a frozen run is
  **PRICED, never permitted by a free constant**: `freeze_debit_m` = the hidden sim-time window ×
  the fastest bird the config scripts, subtracted from `gt_cpa_m` before it meets the bar, and a
  debit that reaches `min_bird_clearance_m` is a hard CLOCK fault instead — at which point
  `gt_cpa_gated_m` prints **NOT COMPUTED** rather than a negative separation, because a flight that
  measured nothing is not a close pass. The window is **measured from the flight's own stamps**, not
  converted from a nominal tick rate, so the price does not depend on the loop having run at 5 Hz:
  today's bar is crossed by **0.428 s** of hidden sim time (3.00 m ÷ 7.0043 m/s) at any tick count.
  Derivation and the two probes that successively replaced the bound: F1 in am. 15, then am. 17.
  (b) **`run.detector.counters`
  were written by the node and read by nothing** — `frames_detected_on == 0` is a hard INVALID
  ("DETECTOR NEVER RAN: 0 of N NDVI messages"), chosen over the softer option because R2/R3's vacuous
  case is a legitimate flight whereas an armed detector fed zero frames is a broken bringup; and the
  same counters carry a **rate floor** (`MIN_DETECT_RATE = 0.90`, justification in F6) so 1 frame of
  1256 cannot pass as a detect half. (c) **An invented
  spawn-pose bird** — a bird with zero landed `set_pose` calls is now omitted from the truth answer
  and named as a hard failure; `answered_from_spawn K/M ticks` prints with per-bird landed counts. On
  the real artifact with bird_0's records stripped, a fabricated `gt_cpa_m 0.0000` breach became
  NONE-IN-BAND plus INVALID naming bird_0. (d) The **staleness bound had no floor in the artifact** —
  a log flown at 3600 s is now INVALID unpatched.
* **New operational preconditions the gate enforces** (each silent until post-flight otherwise, so
  they belong in the runbook): `ndvi_node` must already be publishing `/fg/ndvi/camera_info` when the
  `--detect` shell starts; `drive_birds` must land at least one `set_pose` for **every** bird in the
  config; the gz clock must keep advancing.
* **Reported, not gated — deliberate, and each with a reason:** partial truth coverage (gating it
  needs a minimum-coverage number nobody has evidence for yet); `n_stale_dropped` totals, whose ONE
  gated combination is "drops > 0 AND zero engagements" (am. 15 F2) because that is the combination
  that means avoidance was dead — the totals themselves stay a reading, since "every detection
  expired" and "no bird was ever seen" are opposite diagnoses; and the missed-detection
  line "bird truly inside the cylinder on N tick(s); the loop engaged on M" — gating that would
  measure geometry, since a bird behind the drone is invisible to a forward-facing camera, but a
  large N−M on the first real-detector flight IS the FNR finding and will only be seen if someone
  reads the line.
* **One combined runbook**, `docs/runbooks/AVOIDANCE_REAL_DETECTION.md`: `fly_pipeline.sh up` (7
  panes, whose one-liners it deliberately does not re-spell — one source of truth per command) plus
  an 8th `docker exec` shell for `--detect`; both scipy preflights; the ADR-015 geometry precheck
  verified at the intended cadence (`predict_bird_visibility.py --fps 5.0` → PASS, medians 8/6/11; at
  0.41 Hz → FAIL, 1/0/1 — the abort rule with a worked example); **evidence-first teardown** spelled
  out in order (Ctrl-C the avoidance shell and wait for `wrote flight log →`, THEN `fly_pipeline.sh
  down`, which is already recorder-first); and the exact `--truth` scoring line. `avoidance_node` is
  deliberately NOT a `fly_pipeline.sh` pane and NOT in its `pkill` list — it writes the flight log in
  a `finally` after `rclpy.spin`, so a `pkill -9` would destroy the evidence the flight exists to
  produce, and ADR-013's own rule is that a one-liner flies once before it earns a pane.
  `AVOIDANCE_DEMO.md` keeps the `--demo` arm alive behind a precise partial-supersession banner.
  Known gap, documented rather than patched: `fly_pipeline.sh`'s already-running refusal does not
  grep `avoidance_node`, so a surviving 8th shell is invisible to the next `up`.
Owner / roles: qa-safety-reviewer (gate, mutations, the four fixes); flight-software-engineer (the
node block it reads); robotics-sim-engineer (runbook); tech-lead (recorded).

### ADR-013 amendment 15 (2026-08-24, adversarial pass on the NEW gate, and the round that closed it): six findings — four take-blocking — all six FIXED, each pinned by a test proven red against the pre-fix code
The gate of am. 14 was itself reviewed after its fixes landed, and the six defects it found were
fixed in the same session. Two rules make those fixes evidence rather than assertion. Every fix ships
with a test that was RUN against the pre-fix file and seen to FAIL (the originals were swapped back
in: 19 checker tests red, 6 executor/policy tests red, then restored) — a test written after a fix
proves only that the fix agrees with itself. And the re-review did not re-run the fix
author's tests: it rebuilt the pre-fix code in a shadow tree and ran the SAME probe against pre and
post for each finding, so what is recorded below is a difference, not an agreement. Each entry reads
finding → fix → the number.

* **F1 (critical) — the frozen-clock bound was sized against the wrong denominator; it is now a
  DERIVED debit, not a free constant.** A frozen `tick_stamp_sim_s` axis does not harm detection
  freshness (the 1.0 s staleness bound it borrowed): it corrupts the **truth join**, and that error
  scales with **bird speed**. bird_1 flies 7.0 m/s, so the permitted 0.8 s freeze was **5.6 m of bird
  motion pinned to one instant — 1.9× the 3.0 m bar the gate exists to enforce**; five ticks
  straddling a true **0.0000 m** pass, all reading one stamp, reported `gt_cpa_m 3.5000 m → PASS`
  with zero clock problems. **Fix:** `MAX_FROZEN_TICKS` is deleted and the derivation written at the
  top of the checker. A frozen stamp misplaces the BIRD, never the drone (`flown_path_enu` is
  telemetry and F4's fix walks the polyline between those points), so the join error is bounded by
  `v_bird_max × frozen_span`: `max_bird_speed_m_s()` reads `config/birds/farm_world_birds.json`
  (7.0043 m/s, bird_1 — re-scripting a faster bird tightens the gate by itself), and the frozen span
  was priced — **in this round only** — at the nominal `(N−1)/5 Hz`, the one assumption round 3
  removed (below). ONE inequality, two consequences: `freeze_debit_m` is subtracted
  from `gt_cpa_m` before it meets the bar, and a debit that reaches `min_bird_clearance_m` fails in
  `gate_clock` as a CLOCK fault — which, unlike a CPA breach, no `SAFETY_FINDING` marker can
  acknowledge, because a broken clock measured nothing rather than measuring a close pass.
  **Override, stated:** the bird-only term was used, not the reviewer's suggested bird + drone closing
  speed — the drone term double-counts a position the frozen stamp does not date, and at 17.3 m/s it
  would hard-fail any two-tick scheduler jitter. **Measured after:** the finding's own 5-tick probe
  returns INVALID (debit 5.6034 m, plus the un-acknowledgeable clock fault); a 3-tick freeze turns its
  flattering 3.5000 m into a debited BREACH; the boundary sits exactly where 3.00 m ÷ 7.0043 m/s =
  **0.428 s** of hidden sim time does.
  **Superseded in part the same day (round 3, am. 17), and the difference matters:** the inequality
  and both consequences stand, but the nominal-rate span is gone — the window is now measured from
  the flight's own stamps, so a freeze is priced in SECONDS and the tick→metres table this bullet
  originally quoted (2/3/4/5/6 ticks → 1.4009 … 7.0043 m, "1-3 debited, 4+ fail") describes a gate
  that no longer exists. The negative `gt_cpa_gated_m` that pricing could print was removed with it.
* **F2 (major) — the staleness gate could silently disable avoidance for a whole flight, and the one
  counter designed to reveal it read 0 exactly then.** `n_stale_dropped` rode `maneuver.debug`, which
  the executor copied only onto an accepted-DIVERT event; all-stale produces PROCEED, which logged no
  debug. Proven on one 20-tick encounter with a bird inside the cylinder every tick: fresh stamps gave
  20 detections / 20 maneuvers, 60 s-old stamps gave 0 / 0 / 20 proceeds, and `stale_dropped_total()`
  returned **0 in both cases** — while the artifact printed the affirmatively wrong diagnosis, "every
  box fell OUTSIDE the threat cylinder". Triggered by any systematic sub-0.5 s clock offset (the
  tripwire only fires on FUTURE stamps), a render stall > 1.0 s, or a freeze under F1's old bound.
  **Fix:** the executor writes `n_stale_dropped` / `stale_ids` / `max_detection_age_s` onto proceed
  and hold events as well (ADR-009 am. 1), only when non-zero so a healthy tick pays nothing, and
  `gate_detector_ran` fails the combination "stale drops > 0 AND zero detection events" as
  **AVOIDANCE WAS DEAD**, saying the honest opposite case (boxes > 0, 0 engagements, 0 stale drops =
  every box outside the cylinder) in words rather than leaving it to an absent number. **Measured
  after:** the same all-stale run reports `stale_dropped_total = 20`, `n_detection_events = 0`,
  AVOIDANCE WAS DEAD; `_log_detection` writes no debug, so there is exactly one debug-bearing event
  per tick and no double count. The runbook sentence that pre-committed the operator to the wrong
  diagnosis ("a vacuous pass is usually a cadence/phase miss") is replaced by a three-way diagnosis
  keyed to the numbers the gate prints.
* **F3 (major) — R3's refusal could command a point the policy's own bird-clearance guarantee
  forbids.** Proven end-to-end through the real policy, executor and geofence on the committed
  polygon: at a degenerate tick the executor kept the latch and commanded a point **1.000 m from the
  bird** against `min_bird_clearance_m` 3.00, verdict `accepted`, no `gate_reject` — while the
  policy's fresh setpoint was 10.400 m clear. The only backstop was `is_safe_3d` (trees + altitude),
  which never looks at a bird and is structurally unreachable at cruise (S2). **Fix, with the scope
  deliberately WIDENED (am. 13):** the backstop gains a bird half over `debug["threat_positions_enu"]`
  on every commanded point, not only refusals, because the ordinary re-command path had the identical
  hole and a refusal-only guard would leave the gate asserting more than the control law guarantees;
  rejection logs `gate_reject` with `bird_clearance_m` / `bird_track_id`, drops the dead latch and
  HOLDs; R3.7 re-checks the same inequality offline. The module docstring's "cannot make anything less
  safe" — true of the geofence guarantee, not the bird one — is corrected. **Measured after:** the
  finding's geometry logs `gate_reject`, `bird_clearance_m 1.0`, and a reason naming the 3.00 m bar.
  **What it does NOT fix, named here rather than implied:** the HOLD it falls through to commands the
  vehicle's own position, 0.400 m from that same bird — closer than the point it refused (residual 2;
  round 3 made those two numbers reach the artifact instead of a probe — am. 17).
* **F4 (major) — `gt_cpa_m` was a minimum over the 5 Hz flown-path VERTICES, not over the path.** It
  never evaluated between two logged ticks, nor the pair (drone at tick i, bird at its post-teleport
  pose) even though that configuration physically occurred. Measured on the real 2026-08-23 log:
  drone step p50 0.747 / p95 1.892 / **max 2.052 m** per tick; the bird teleports 3.16 m per
  `set_pose`. Both discretisations bias the same fail-dangerous way. Proven twice: a true 2.8200 m
  polyline CPA reported **3.0008 m → PASS**, and a teleport case with a true continuous minimum of
  2.6332 m reported **3.0500 m → PASS**. **Fix, ~8 stdlib lines:** `_point_segment_xy_m`, with each
  tick's bird candidate set scored against BOTH segments bounding that tick's vertex — so a pose that
  landed after the tick meets the segment the drone was actually flying. **Measured after, and the
  lower-bound claim was verified rather than accepted:** the hand case now reports 2.8200 m → BREACH,
  and 300 randomised encounters (4-9 ticks, dt 0.2-0.5 s, drone steps 0.5-2.05 m, teleport rates
  1.9-5.0 Hz, random headings) scored against an independent densely-sampled model of the continuous
  encounter produced **zero** trials where `gt_cpa_m` over-reported the true minimum. The drone axis
  is now a true lower bound; the bird axis is not (residual 1 — closed in round 3, am. 17, which made
  the same claim true on both axes).
* **F5 (major) — `--truth` bypassed the "exactly one overlapping truth track" guard entirely**, and
  the runbook's only documented invocation is `ls -t ... | head -1`. One aborted takeoff, or the
  documented `fly_pipeline.sh birds` override, leaves two applied logs for one take; every tick before
  the chosen log's first landed call was then answered from **config spawn poses** — bird_0 sits at
  (15, 5, 11), directly under mission lane x=15. Proven on that literal scenario: VALID, `truth
  coverage 3/3 ticks`, `gt_cpa_m 20.0000 m`, with `answered_from_spawn 2/3` as a note that looks
  identical to the legitimate case. **Fix:** `resolve_truth` runs `truth_candidates()`
  unconditionally — `--truth` says WHICH log to score against, not that the others do not exist.
  **Measured after:** the same scenario is INVALID with `AMBIGUOUS TAKE`, naming the other overlapping
  applied log; the no-usable-stamps case still falls through to the existing hard failure.
* **F6 (minor) — `gate_detector_ran` was a zero-check, not a rate check** on the take's headline
  claim: 1 detected frame of 1256 passed without comment, though this project's own precedent (am. 4)
  is that evidence bars are FLOORS with numbers behind them. **Fix:** `MIN_DETECT_RATE = 0.90` on
  `frames_detected_on / ndvi_msgs_received`, and the rate prints with BOTH raw counts on every flight.
  The number has a measurement behind it: the offline dry run is 1256/1256 = 100 %, the only
  legitimate loss is startup ordering (frames published before `/fg/ndvi/camera_info` lands) which
  costs ~3 % if it eats the first ten seconds of a five-minute take at 5 Hz, so 0.90 is ~3× that worst
  plausible transient and far above the defect it exists to catch, which loses 90-100 %. **Measured
  sweep** over frames_detected_on = 1256 / 1130 / 1129 / 1 / 0 of 1256: VALID / BARELY RAN / BARELY
  RAN / BARELY RAN / NEVER RAN, against a pre-fix gate that passed all but the last. **Revisable on
  the first `--detect` flight's number — revised there, not widened after a failure.** The related
  item stays code-free as ranked: the node refuses to start without a gz clock reading but has **no
  equivalent startup guard on `/fg/ndvi/camera_info`**, so that class is caught post-flight.

**What the re-review then found still standing, ranked as of that round. None of it blocked the take,
and the reason was the same each time: it is recomputable from artifacts the flight already retains,
or it is R4. FIVE OF THE SIX WERE THEN CLOSED IN ROUND 3 (am. 17) — each item below carries its
disposition, so this list is a record of what was found, never a to-do that outlived its fix.**
1. **(major) `gt_cpa_m` is a true lower bound over the drone POLYLINE and still a VERTEX sample of
   the BIRD.** `ground_truth_cpa` iterates TICKS and asks `candidates_at(t_i)`, so a landed
   `set_pose` whose whole in-effect window falls between two ticks is never scored — and the bird is
   the faster body (7.00 m/s against the drone's measured p50 0.747 m/tick), so F4 closed the smaller
   half. Proven: at a 0.70 s sim tick period with the driver at its measured 1.84 calls/s/bird, the
   gate reports `gt_cpa_m 3.8067 m → VALID` on a bird driven straight through a hovering drone (true
   0.0000 m), with a healthy clock, no freeze, and `truth coverage 24/24 ticks`. Today's margin is
   genuine: 5 Hz wall × measured RTF 0.605 = 0.121 s sim/tick, 4.5× finer than the driver's 0.543 s
   inter-call interval, and the never-scored fraction of the committed 839-pose applied log is
   **0.0 % at 0.121 s/tick**, 3.2 % at 0.50, 29.6 % at 0.80, 41.6 % at 1.00. The defect is that the
   margin is unmeasured and unprinted on the one number the take is booked to produce: `truth coverage
   K/N ticks` reads 100 % regardless, and the inverse rate — landed calls covered by a tick — has no
   denominator anywhere. In doctrine, cheap either way: print `truth_poses_scored K/N`, or score each
   landed call against the drone polyline over ITS OWN in-effect window so the tick grid stops
   mattering at all. **Not a re-fly risk:** both inputs (`flown_path_enu` and the applied log) are
   retained, so the number is recomputable after the flight.
   → **CLOSED (round 3, am. 17): BOTH suggestions taken** — the second pass scores every landed call
   over its own window, and `truth_poses_scored/total` prints as that axis's denominator.
2. **(major) the HOLD the executor falls through to vets nothing.** `_handle_hold` sends the vehicle's
   current position with neither `is_safe_3d` nor the bird bar applied, and on the degenerate branch
   that point is inside the bar BY CONSTRUCTION (the branch is only entered within
   `degenerate_range_m` of the trigger bird). Swept: 400 random encounters × 25 ticks = 10,000 control
   ticks through the real policy + executor + geofence gave 22 R3 refusals and **41 HOLD ticks
   commanding a setpoint inside the 3.00 m bar, closest 0.288 m**, read by nothing. This is S5 + R4
   rather than a measurement bug — the cure is escape geometry, cut for v1 — so the claim in am. 13 is
   narrowed to what the code does and `gt_cpa_m` still catches the flown proximity at the headline.
   → **CLOSED AS HONESTY, NOT AS R4 (round 3, am. 17):** the hold's own clearance is now logged and
   printed as ungated CONTEXT, guarantee 1 is renamed for the scope it actually has, and the reject
   reason says REFUSED rather than implying a safer alternative. **R4 itself stays open and uncut.**
3. **(major) R3.7's BREACH branch cannot fire on a log the CURRENT executor writes.** The executor
   converts exactly that case into a `gate_reject`, and `gate_r2_r3` only reads `maneuver` events, so
   R3.7 is defence-in-depth over replayed, older or hand-edited logs while a live flight's evidence
   lands in `gate_reject`'s `bird_clearance_m` / `bird_track_id`, which nothing reads. The reviewer
   named it as their own family: a gate that is green because the thing it measured was removed. Scope
   is now stated in am. 13; gating those fields is the open work.
   → **CLOSED (round 3, am. 17): R3.8 gates them**, and R3.7 is restated as the exhaustion property
   it always was.
4. **(minor) the freeze debit is priced at the NOMINAL 5 Hz.** A span of `(N−1)/5 Hz`
   bounds sim seconds by wall seconds only if the ROS timer really fires at 5 Hz, and the derivation
   names only the RTF > 1 caveat — the less likely half on a box that has twice lost >90 % of its
   frames to CPU starvation, and the two faults are correlated (a node whose clock reader stalls three
   ticks may be a starved node). Measured under-pricing: at an achieved 0.35 s/tick a 3-tick freeze
   hides 4.903 m and is priced 2.802 m (1.75×); at 1.00 s/tick a 2-tick freeze hides 7.004 m and is
   priced 1.401 m (5.0×). No verdict flipped in those probes — the honest neighbouring ticks still
   bracket the pass — and it needs ~1.26 s/tick to bite, ~10× today's 0.121 s. The log already
   MEASURES the quantity: `stamp_advance` walks the stamps, so pricing the debit off them removes the
   assumption outright.
   → **CLOSED (round 3, am. 17), and more strictly than the suggestion:** the round-3 fix did NOT take
   the proposed mean-rate division (`span_s/advanced` is still an average, and an average under-prices
   the worst run). It brackets each frozen run between the stamp it read and the next stamp that
   ADVANCED, which is assumption-free.
5. **(minor) the detector floor's failure sentence rounds to a contradiction:** 1130/1256 = 0.899681
   fails while the message prints "= 90.0%, below the 90% floor". One character (`:.2%`), and it
   matters because a floor is met near the floor — an operator reading that in a scrollback files it
   as a gate bug and may widen the very number F6 says to revise only on a measurement.
   → **CLOSED (round 3, am. 17):** `_floor_pct` TRUNCATES rather than rounds, so 1130/1256 prints
   89.96 % and no failing rate can ever print the floor it just missed.
6. **(minor) `MIN_DETECT_RATE = 0.90` has never been measured in the air** — an offline dry run plus a
   modelled startup transient. Revise it on the first take's number.
   → **STILL OPEN, and it is the only one of the six that is.** It closes on a flight, not on a fix;
   round 3 removed the misleading "90.0 %" sentence that made widening it after a failure tempting.

**Tech-lead's call: the GATE no longer blocks the take.** F1, F3, F4 and F5 would each have made the
take unbookable and F2 would have made its result unreadable — a gate that reports 3.0008 m on a
2.82 m pass, or scores the flight against a bird nobody watched, spends the flight and hands back the
wrong answer. All six are fixed, each pinned by a test proven red first, and each re-verified against
pre-fix code by someone who did not write it.
What remains before the take is operational, not evidential — the scipy image rebuild and its
in-container equivalence re-score (ADR-004 am. 1) — plus the pre-registered risk that this flight
honestly FAILS its own GT-CPA gate, because R4 is not in it. The six residuals are ranked, not
blocking: 1, 4 and 5 are recomputable or cosmetic on a flight whose inputs are all retained, 2 is R4
wearing a different hat, and 3 is defence-in-depth on a branch the executor now prevents. Residual 1
is the one to close first, because it is the missing denominator under the only number the take exists
to produce. (Ranking honoured: round 3 closed 1 first, then 2, 3, 4 and 5 — am. 17.)

**Session state (2026-08-24, at the close of THIS round — round 2; round 3's numbers are in am. 17),
measured not remembered.** Suite
**833 passed / 2 skipped / 0 xfailed / 0 xpassed** (`python3 -m pytest tests -q`), against 805/2
before this round; `unittest discover -s tests/fieldguard_planning` → **783 OK (skipped=2)** and
`unittest discover -s tests -p 'test_fly_pipeline.py'` → **52 OK** (the host-side pattern CI used at
the time; am. 16 widened it to `-p 'test_*.py'` so a new host-side file cannot sit un-run).
783 + 52 = 835 = 833 + 2 is the
consistency check that matters, because unittest is the runner that makes an unexpected pass RED. The
2 skips are the self-activating pending detection scenarios (`det_bird_crosses_path`,
`det_bird_over_low_ndvi`), unchanged. The legacy path was re-verified by byte-comparison rather than
by re-reading: both historical logs still print ACKNOWLEDGED SAFETY FINDING (0.0597 m, 0.0518 m) and
exit 0, with stdout AND stderr identical to the committed-HEAD checker. The ADR-003 equivalence gate
rode along rather than being taken on trust: `test_ndvi_detect.py`'s whole-clip re-score RAN (29
passed, 0 skipped — the clip is on this disk) and stayed bit-identical, so the ADOPTED verdict is
still the one this code produces. Everything landed this session is **offline**: no Docker, no
Gazebo, no ROS 2, no flight. The image rebuild, the in-container scipy transfer check, and every live
behaviour of the seam and the gate remain unproven.
Owner / roles: qa-safety-reviewer (found and priced all six, and re-reviewed the fixes against
pre-fix code); flight-software-engineer (F2/F3 and the executor backstop); tech-lead (the booking call
and the residual ranking above); product-lead (arbitrates if this is argued).

### ADR-013 amendment 16 (2026-08-24, round-3 finding 4 — what CI's CPA gate is pointed at): the filed premise is corrected by measurement, the scenario fixtures are scoped OUT with a proof, and the gate now prints its denominator

**The finding, as filed.** "CI invokes `check_live_flight_log.py eval/results/*flight_log*.json`;
`eval/results/` is gitignored, so in CI the glob matches nothing, the script prints SKIP and exits 0.
The R1 CPA gate is therefore, in CI, entirely vacuous… Meanwhile three of the four committed
`eval/scenarios/*/flight_log.json` are in CPA breach (0.0000 m, 1.0000 m, 1.0000 m). Adding them to
the CI line turns CI red today — which is the point." The reviewer explicitly surfaced the treatment
as a decision rather than guessing it. Both halves were checked before either was acted on.

**Correction 1 (measured, not argued): the CI gate is NOT vacuous at HEAD.** `.gitignore` ignores
`eval/results/*` and then **re-includes `!eval/results/live_flight_log_*.json`**, and two live logs
are committed under that rule. Reproduced the CI environment exactly — `git archive HEAD | tar -x`
into a clean tree, then the literal step — and the glob matched **2 files**; the gate ran, printed
both CPAs, and reported each as an ACKNOWLEDGED SAFETY FINDING (**0.0597 m**, 2026-08-18;
**0.0518 m**, 2026-08-23) before exiting 0. So the R1 CPA gate has been executing on real committed
evidence on every push since it landed, and the marker mechanism is exercised there too. Recorded
because the remedy the finding proposed — point the same gate at the scenario fixtures — would have
been wrong twice: it was not needed to make the gate real, and (correction 2) it would have gated a
number no control law can move.

**Correction 2: the scenario fixtures' "CPA" is a scenario PARAMETER, not a flown outcome — so the
CPA gate does not apply to them, and they get no `SAFETY_FINDING.md` markers.** The proof is
structural and was then confirmed by experiment. `eval/scenarios/generate_flight_logs.py` prescribes
the drone's `DroneState` from `nominal_path()` on every tick and never feeds the executor's commanded
setpoint back into the next tick — there is no vehicle model, deliberately, because the fixture holds
the *stimulus* fixed so the **ledger** is the only thing under test. Measured consequences:
`flown_path_enu` is **byte-identical to the scripted lawnmower** in all four fixtures, and the birds
are parked **on** the lane because that is what forces the dodge the scenario is about. The
experiment that settles it: regenerating all four under **today's landed control law** (R2 lateral
tree margin + the R3/bird-clearance backstop of am. 13/15) moved 1-5 commanded setpoints per scenario
by up to **17.205 m** and raised the worst *commanded* bird gap in `cov_bird_over_cell` from 10.0000 m
to 12.0000 m — while the flown CPA stayed **bit-identical at 0.0000 / 7.0000 / 1.0000 / 1.0000 m**.
A number that a 17 m change in the control law cannot move by 1 nm is not measuring the control law.
* **Rejected — acknowledge them with `SAFETY_FINDING.md` markers.** One sentence: it would file an
  authored scenario parameter as a safety finding and dilute the one channel that carries the two
  real historical breaches, which is the channel's whole value.
* **Rejected — move the birds off the lane so the fixtures pass the CPA gate.** The bird is on the
  lane *because* that is the stimulus; moving it makes four scenarios stop testing anything.
* **Accepted — scope stated, in the two places a reader will actually look:** a new "these fixtures
  are OPEN-LOOP" section in `eval/scenarios/README.md` §3 and a comment on the CI step itself.

**What the finding surfaced that IS real, and is fixed: the gate had no denominator.** The step
asserted nothing about how many files it had been shown, and its own comment asserted the opposite of
the truth ("eval/results/ is gitignored, so this normally SKIPs"). It was one `.gitignore` edit, one
rename or one deletion away from matching zero files, printing `SKIP … PASS: all present flight logs
valid` and going green having validated nothing — this repo's own forbidden failure mode, and the
reason it was invisible is that nobody had ever seen the step's file count. **Fix (ci.yml side):**
`shopt -s nullglob`, collect the matches into an array, **print the count on every run**, hard-FAIL on
zero with a message naming the two ways it can happen, then pass the explicit list to the checker.
* **Why ci.yml and not a `--fail-on-empty` flag in the checker** (the alternative offered): the
  checker's SKIP-on-absent contract is correct for a tool a human points at a path, "this CI run must
  have evidence to chew on" is a property of the *job*, and a `--fail-on-empty` flag on a safety tool
  is also a `--dont-fail-on-empty` flag for anyone who finds the gate inconvenient.

**Fixtures regenerated, and why that was owed anyway.** Today's control-law changes had already made
the four committed fixtures stale, so CI's existing regenerate-and-diff step would have gone red on
the first commit of this session's work. They are regenerated in place. Reproducibility was verified
before the output was trusted, not after: **five consecutive runs produced byte-identical files**
(the generator takes no runtime randomness — fixed per-scenario seeds and static bird poses — and
`_round_floats` at 1e-9 is the pre-existing cross-platform libm guard). Ledger outcome unchanged in
all four: **720 cells, 144 debt, 116 path points**; maneuver counts unchanged (13 / 8 / 16 / 11);
only `relatch` counts moved (6→5 in `cov_bird_over_cell`, 6→8 in `geo_avoid_into_tree`).

**What CI executes on the scenario fixtures, since the CPA gate does not** — both were already true
and are now *guaranteed* rather than incidental: the regenerate-and-diff reproducibility step, and
the ledger-honesty (P1-P4) + no-lying-covered + tree-band + field-polygon assertions in
`test_safety_scenarios_pending.py`. Those assertions are **self-activating, which means they SKIP on
a missing fixture** — the same vacuity in a different costume — so `tests/test_ci_evidence_gate.py`
now asserts every generator scenario has a *committed* fixture. Its pattern
`unittest discover -s tests -p 'test_*.py'` replaces the single-filename pattern for the same reason:
a new host-side test file must not be able to sit un-run (verified on Python 3.12 that discovery does
not recurse into `tests/fieldguard_planning`, so nothing runs twice).

**Pinned by tests proven red against the pre-fix step, per this project's rule.** The adversarial one
extracts the *real* step body out of `ci.yml` and runs it in a tree with no matching logs: pre-fix it
exits **0** printing "PASS: all present flight logs valid"; post-fix it exits **1** printing
`matched: 0`. Two more pin the denominators (the glob matches ≥1 committed file; every scenario has a
committed fixture), one runs the step hermetically on copies of the committed evidence and requires
exit 0, and one pins the open-loop fact this whole scoping decision rests on — **if the generator ever
becomes closed-loop, `flown_path_enu` stops equalling `nominal_path()`, that test goes red, and this
amendment must be re-read before CI is touched.** The two ACKNOWLEDGED historical logs were
re-verified by byte-comparison, not by re-reading: stdout AND stderr identical to the committed-HEAD
checker, exit 0.

**Left open, deliberately, and named rather than implied.** No scenario in `eval/scenarios/` exercises
separation *at all* — every fixture is open-loop, so "the vehicle stayed ≥ 3.00 m from the bird it
dodged" is measured only on live flights by the ground-truth CPA gate. That is why both historical
breaches were found by a gate and not by a test, and closing it needs a fixture that flies the
executor's *commanded* setpoints, i.e. a vehicle model — which is R4 (escape geometry), cut from v1
by the Product Lead. Recorded in `eval/scenarios/README.md` §4 as an open safety gap so a green
scenario suite is never read as evidence of clearance.
Owner / roles: tech-lead (this call, the ci.yml and scenario-README text); qa-safety-reviewer (filed
the finding and the three breaching fixtures); product-lead (owns R4's continued exclusion).

### ADR-013 amendment 17 (2026-08-24, round 3 — the adversarial pass on am. 15's own fixes): five of the six residuals CLOSED, the BIRD axis of the CPA join stops being a sample, the HOLD stops implying safety, and this log is corrected to match the code
The gate was reviewed a third time, after am. 15's fixes landed. Seven findings, four must-fix.
**Finding 4** (what CI's CPA gate is actually pointed at) is recorded in **am. 16** — premise
correction, open-loop proof and rejected alternatives — and is not repeated here. **Finding 6** was
this log itself, and this amendment is its fix (below). The other five are code and all five are
fixed, each pinned by a test **run against the pre-fix file and seen to FAIL**: backed out one at a
time they turn 5 / 6 / 5 / 3 / 3 tests red respectively, with **no collateral failures in any
back-out** — which is the check that each pin is on its fix and not on the weather. The re-review
then rebuilt the pre-fix code in a shadow tree and ran its OWN probes against pre and post, so what
is recorded below is a measured difference, not an agreement.

* **F1 (major) — `gt_cpa_m` was a true lower bound on the DRONE axis and still a VERTEX SAMPLE on the
  BIRD axis** (am. 15 residual 1, the one ranked to close first). `ground_truth_cpa` iterated ticks
  and asked `candidates_at(t_i)`, so a landed `set_pose` whose whole in-effect window fell between
  two ticks was never scored — and the bird is the faster body (7.0043 m/s scripted against the
  drone's measured p50 0.747 m/tick). **Fix: two passes, and `gt_cpa_m` is the minimum over both.**
  New `pose_windows(truth)` yields, per landed call, the sim-time window over which that pose could
  have been rendered — it OPENS at the call's `sim_start` and CLOSES at the NEXT call's `sim_end`,
  which is exactly the interval `pose_from_applied` can return it over, ambiguous bracket included,
  so the two agree by construction rather than by coincidence; the last call holds to
  `TruthTrack.span[1]`. Pass 2 scores each pose point-to-segment against the **drone sub-segment that
  window covers**, endpoints interpolated along the bounding tick stamps, joined by a monotone
  two-pointer. **Pass 1 is KEPT and is not redundant:** it is the only pass that can answer before a
  bird's first landed call, where the truth is the spawn pose. New report keys
  `truth_poses_total` / `truth_poses_scored` give the bird axis the denominator tick coverage never
  was, and `cpa_from` names which pass produced the number (`tick_sample` | `pose_window`).
  * **Measured:** the finding's probe — a bird driven through a hovering drone between two ticks at a
    0.70 s tick period — reported `gt_cpa_m 3.8067 m → VALID` and now reports **0.0000 m → BREACH**,
    `cpa_from='pose_window'`. The re-review reproduced the direction on its own geometry (3.8010 m →
    0.0000 m) and re-falsified the lower-bound claim independently: 300 randomised trials plus 200
    three-bird interleaved-window trials aimed at the new two-pointer, scored against a densely
    time-sampled model built from the checker's own truth accessor — **0 over-reports, worst
    0.000000 m**. On the committed 839-pose track the join scores 838-839/839 poses at every cadence
    from 0.121 to 1.00 s/tick in **0.08 s**, where the tick-only pass would have missed 0.0 / 3.2 /
    9.3 / 29.6 / 41.6 % of them. The windows on the real artifact are well-formed (0 with end < start,
    0 non-monotone starts, length p50 0.569 s / max 7.30 s, and the long ones are exact — nothing
    else moves a bird).
  * **Freeze interaction, written into the code so it is not re-derived later:** pose windows are
    gz-native truth-log timestamps and do not depend on `run.tick_stamp_sim_s` at all; the DRONE side
    of the join still does, so `freeze_debit_m` prices exactly that, unchanged.
* **F2 (major) — the HOLD the R3 refusal falls through to vets neither half of guarantee 1** (residual
  2). **Fixed as HONESTY AND MEASUREMENT, not as R4 — the call, with the alternative rejected:** at
  degenerate range the vehicle is inside the bird bar BY CONSTRUCTION, so there is no strictly-better
  *vetted* alternative to choose that is not escape geometry; choosing a point that IS outside the
  bar means deciding a direction, which is R4, cut for v1. Shipping a direction inside an executor
  fix round would have landed escape geometry with no gate on it — the band-aid this project's own
  rule forbids. So the code stops implying otherwise and starts printing the number instead:
  (a) `_handle_hold` logs `bird_clearance_m` / `bird_track_id` / `min_bird_clearance_m` on every hold
  (None when the decision names no threat); (b) the `gate_reject` reason no longer says "falling back
  to HOLD" — it says REFUSED, zero displacement, honours NO clearance bar, **can be nearer the bird
  than the point refused**, R4 owns escape geometry; (c) `gate_r2_r3` reports the minimum hold-tick
  clearance as `[CONTEXT, NEVER GATED]` and PRE-REGISTERS holds inside the bar at degenerate range as
  the known R4-open signature, so that line on the first take is an expected reading and not a new
  finding; (d) guarantee 1 is renamed **"Never fly an unvetted DISPLACEMENT"** with an explicit
  HOLD-IS-EXEMPT-BY-CONSTRUCTION paragraph carrying the measured numbers.
  * **Measured:** the worked geometry through the real policy + executor + geofence logs a reject at
    **1.000 m** and a hold at **0.400 m** — the artifact now states, in its own numbers, that the
    refusal made commanded separation 2.5× worse. Exhaustion sweeps: 10,000 control ticks gave 41
    HOLD ticks inside the 3.00 m bar, closest **0.288 m** (am. 15's sweep); the re-review's own
    geometry, also 10,000 ticks, gave 2597 holds, **2597 of 2597 carrying the number**, 332 inside
    the bar, closest 0.029 m. The two counts differ because the geometries differ — the point that
    survives both is that every hold now reports its clearance.
* **F3 (major) — R3.7 read the event the am. 15 F3 fix had removed** (residual 3). `gate_r2_r3` now
  consumes `gate_reject` events (**R3.8**): counts them, splits bird-bar from geofence rejects,
  reports the closest refused point as the backstop WORKING, scores each against the bar THAT FLIGHT
  flew, and **FAILS a reject that names neither an obstacle nor a sub-bar bird clearance** — the only
  way field-name drift there could have stayed silent. R3.7's BREACH branch is restated as what it
  is: the **exhaustion** property, unreachable on a log the current executor produces and therefore a
  defence against an older or edited one. **The layering is deliberate and worth saying out loud on a
  whiteboard: the executor fails OPEN on missing data, the gate fails CLOSED on it.** The re-review
  found the one path on which R3.7 IS live today and verified it: a maneuver whose debug carries no
  `params` gets no bird check in the executor (documented fail-open), is commanded, is logged as a
  maneuver — and R3.7 catches it offline. A 10,000-tick sweep confirmed 0 maneuvers commanding inside
  the bar.
* **F5 (minor by rank, structural by nature) — the freeze debit was still priced at a NOMINAL rate**
  (residual 4). `stamp_advance` now measures `frozen_window_s` from the flight's own stamps: a run of
  ticks all reading sim second `v` is closed by the next stamp that ADVANCED, `v_next`, and costs at
  most `v_next − v` — assumption-free, because a clock reading never runs ahead of sim time, so `v`
  is its own lower bound and the bound is loose by at most one tick period. The **WORST** run is
  priced, not the longest (seconds hidden, not ticks repeated). A trailing run with no closing stamp
  is priced at the flight's own measured mean sim-step × run length. `freeze_debit_m` now takes
  SECONDS, and `frozen_span_s` / `CONTROL_HZ` are deleted from the gate — **one home per concept:
  `CONTROL_HZ` lives in `avoidance_node`.** The re-review's suggested `span_s/advanced` was
  deliberately NOT taken: an average under-prices the worst run.
  * **Measured:** the round-3 probe stamps `[100.0, 100.5, 101.0, 101.0, 101.0, 102.5, 103.0, 103.5]`
    priced 0.400 s = **2.8017 m** under the old rule and PASSED; they measure 1.500 s = **10.5065 m**
    and are now a hard, un-acknowledgeable clock fault (re-verified in this file's own arithmetic:
    `frozen_at` = (tick 3, 3 ticks, 101.000 s), `frozen_window_s` 1.500). Worst-not-longest verified
    on a case built for it: a 5-tick run hiding 0.2 s loses to a 2-tick run hiding 2.0 s.
  * **One consequence FIXED rather than shipped:** when the debit reaches the bar the gate used to
    subtract it anyway and print "flew within −7.0065 m" plus a CPA BREACH on a flight that measured
    nothing. It now prints **`gt_cpa_gated_m NOT COMPUTED`** and stands on the clock fault, because
    an unmeasured flight and a close pass are opposite claims.
* **F7 (minor) — the detector floor's failure sentence printed the floor it had just failed.** New
  `_floor_pct` TRUNCATES the rate to the digits it prints, used for the note, the failure message and
  the floor itself. Verified in this file's own run: 1130/1256 prints **89.96 %** (was "90.0 %,
  below the 90 % floor"), 1131/1256 prints 90.04 %, the floor prints 90.00 %. Truncation makes the
  printed digits a true statement about the comparison in both directions — anything that prints
  90.00 % really is ≥ 0.9000 — so no operator reads a failing gate as a gate bug and widens
  `MIN_DETECT_RATE` after a failure, which am. 15 F6 says is the one thing not to do.

**F6 — the finding was this log, and the rule it forces.** For two consecutive rounds `DECISIONS.md`
described a gate the code did not implement: round 2 left `MAX_FROZEN_TICKS` prescriptions behind
after it was deleted, and round 3 found am. 15 still stating the freeze bound as
`(N−1)/CONTROL_HZ`, still quoting a negative `gt_cpa_gated_m` print and a tick→metres table that the
stamp-measured pricing had removed, still prescribing `max(1/CONTROL_HZ, span_s/advanced)` as the fix
— while `test_check_live_flight_log_schema2.py` asserts those very symbols are ABSENT from the
checker. **The doc and the test contradicted each other inside the same repo, which is the same
family as a green gate that measured nothing.** Fix, and the doctrine, stated once so it is not
argued again:
* Every amendment written today is still **uncommitted session text**, so it is corrected **IN
  PLACE** — am. 13's R3.7 scope and its HOLD/marker/scenario paragraphs, am. 14's GT-CPA and
  frozen-axis bullets, am. 15's F1 numbers and all six residual dispositions. **Once committed this
  file is APPEND-ONLY** and the identical corrections become a new amendment. This is the last window
  in which that distinction applies to today's text.
* What is never corrected in place is the RECORD of what each round found. Superseded numbers are
  marked superseded, not deleted: "the freeze bound was sized wrong twice, and here is each wrong
  denominator" is the interview answer, not an embarrassment to tidy away.
* The general rule this makes explicit: **a fix that changes a gate's behaviour is not done until the
  ADR text that describes that gate is changed in the same session.** Two rounds of drift is the
  evidence for the rule.

**Decision, mine, with the alternative rejected — the ACKNOWLEDGED marker set is FROZEN at the two
historical logs** (`live_flight_log_20260818T144711Z`, `live_flight_log_20260823T004031Z`). A
`SAFETY_FINDING.md` marker turns a CPA breach into exit 0, and the mechanism exists for recorded
history that **cannot be re-flown**. R4 is open, am. 13 pre-registers that the next take may honestly
breach, and the runbook's §6 row tells the operator to keep the log with a marker — so an unbounded
marker set makes "add a file" the documented remedy for a red gate, and every subsequent push is
green with a bird strike sitting in the evidence directory. A take that can be re-flown after R4 is a
**failed take**, not an acknowledged finding.
* **Rejected — leave the mechanism unbounded and rely on review.** One sentence: nothing in the repo
  states which logs may be acknowledged, so the bound would exist only in the reviewer's memory, and
  the composition above makes forgetting it green.
* **LANDED this round (am. 14 lineage) — acknowledgement is a TWO-STEP contract, and both steps are
  reviewed.** A breach exits 0 only if the log carries its `SAFETY_FINDING.md` marker **and** its
  stem is pinned in `ACKNOWLEDGED_BREACH_STEMS` in `scripts/check_live_flight_log.py`; either half
  alone is INVALID, and the failure message names the missing half so an operator is told what to do
  rather than guessing. **A marker alone was rejected** because a marker is a gitignored-adjacent
  file an operator can add in the same motion that produced the red gate — the remedy and the
  finding would be authored by the same hand, unreviewed — whereas the pinned stem forces a diff on
  the safety gate itself, which is the artifact a reviewer already reads. The bound is the point: two
  stems, and a third requires a deliberate edit with a reason.
* **LANDED (round 4, same day)** — the `AVOIDANCE_REAL_DETECTION.md` §6 row no longer sends the
  operator down the one-file path. §6a now states both halves, and states the *correct action after a
  real breach in so many words*: **write the marker, do NOT add the pin, let the take stand at
  INVALID / exit 1** — the pinned stems are historical logs that cannot be re-flown, and the list is
  meant to stay two long. The §6 verdict table's breach row reads "Not for a green, **and there is no
  one-file way to make it one**". Pinned by
  `test_check_live_flight_log.py::test_the_runbook_tells_the_operator_about_BOTH_halves`, which
  asserts the runbook names `ACKNOWLEDGED_BREACH_STEMS` by its own constant name and not only the
  marker suffix — so the doc cannot drift back without a red test.
* **EXTENDED (round 5, same day) — the same ratchet, applied to the LEGACY PATH ITSELF.** Pinning
  *which breaches are acknowledged* left a wider door open: `run_block_problem` returned None when
  the `run` key was simply ABSENT, so `del log["run"]` demoted a schema-2 flight to the legacy
  detection-referenced CPA path — and a ground-truth-gated INVALID (the detector missed the bird at
  closest approach, so the legacy metric has no evidence at all) came back **VALID
  "NO-CPA-EVIDENCE"**, by deleting one key in a gitignored directory. A log with no run block now
  takes the legacy path **only if it is pinned pre-seam**: the two historical stems in
  `PRE_SEAM_LEGACY_STEMS` (by STEM, because CI copies those logs into a tmp tree to run this gate
  hermetically) plus the `eval/scenarios/<name>/flight_log.json` fixtures (by SHAPE, because their
  generator drives the policy + executor OFF-ROS — no clock, no detector, no bird driver — so there
  is nothing for a run block to record, and because that set is meant to grow while the stem list is
  not). Anything else with no run block is **INVALID**, and the message says exactly that: every
  flight since the 2026-08-24 seam writes one, so its absence is a fault or tampering. The two lists
  are separate constants that happen to hold the same two stems — both pre-seam live logs breached —
  because they answer different questions ("may this log be scored on the old gate?" vs "is this
  breach reviewed?"). Pinned by the del-`run` probe itself
  (`test_THE_PROBE_deleting_the_run_key_cannot_downgrade_a_failing_flight`), plus the pinned contents
  of the list and the fixture-shape anchor. Both historical logs re-verified byte-identical on stdout
  AND stderr, and the four scenario fixtures keep their verdicts.

**Verified suite and evidence state (2026-08-24, close of round 3), measured in this pass, not
remembered.** `python3 -m pytest tests -q` → **860 passed / 2 skipped / 0 xfailed** (entering the
round: 833/2, so +27 tests across the five checker/executor fixes and am. 16's CI evidence gate);
`unittest discover -s tests/fieldguard_planning` → **805 OK (skipped=2)**;
`unittest discover -s tests -p 'test_*.py'` → **57 OK** (am. 16's widened pattern). 805 + 57 = 862 =
860 + 2 is the consistency check that matters, because unittest is the runner that makes an
unexpected pass RED. The schema-2 gate alone carries **160** tests. The 2 skips are still the
self-activating pending detection scenarios (`det_bird_crosses_path`, `det_bird_over_low_ndvi`).
**The two ACKNOWLEDGED historical logs still exit 0** on the default glob, printing 0.0597 m
(2026-08-18) and 0.0518 m (2026-08-23) — the legacy path was not touched this round, and both were
re-verified by byte-comparison of stdout AND stderr against the committed-HEAD checker. Everything in
rounds 1-3 is **offline**: no Docker, no Gazebo, no ROS 2, no flight.

**Re-measured at the close of round 5 (2026-08-24), superseding the numbers above as the CURRENT
state — the round-3 figures stay as the record of that round.** `pytest tests -q` → **877 passed / 2
skipped / 0 xfailed** (entering round 5: 870/2, so +7 across the run-block ratchet and the hold
field-drift widening); `unittest discover -s tests/fieldguard_planning` → **822 OK (skipped=2)**;
`unittest discover -s tests -p 'test_*.py'` → **57 OK**. 822 + 57 = 879 = 877 + 2, the same
consistency check. The two ACKNOWLEDGED historical logs were re-verified byte-identical on stdout AND
stderr against the committed-HEAD checker *again* after the ratchet landed (they are pinned pre-seam,
so they still take the legacy path), and the four `eval/scenarios/*/flight_log.json` fixtures keep
their existing verdicts (3 INVALID on authored, open-loop breaches + 1 VALID, am. 16). Still
**offline**: no Docker, no Gazebo, no ROS 2, no flight.

**Still open after this round, ranked, and none of it blocks the take.**
1. **R4 (escape geometry) stays open and uncut** — Product Lead's call, unchanged. What changed is
   that the first `--detect` take will now MEASURE its gap (the hold-clearance CONTEXT line) instead
   of leaving it to an argument. Expect that line on any take with a close encounter: **book R4 on
   the number, do not re-fly for it.**
2. `MIN_DETECT_RATE = 0.90` still has no in-air measurement behind it (am. 15 residual 6). Revise it
   on the first take's number; never widen it after a failure.
3. **The clock gate's FALSE-POSITIVE rate is unpriced, and a clock fault is un-acknowledgeable by
   design.** After F5 the debit crosses the whole bar at 3.00 ÷ 7.0043 = **0.428 s** of hidden sim
   time, and `_gz_now` is fed by a `gz topic -e -t /clock` subprocess reader thread on a box this
   project has twice documented starving — so a sub-second reader stall makes a booked session a hard
   `gate_clock` INVALID. That is the CORRECT conservative behaviour (an unmeasured flight is not a
   safe flight) and it is not the finding; the finding is that nobody has priced how often it fires
   on a healthy take, and the runbook's §6 booking table has no row for it, so the artifact would
   read like a control-law failure to anyone skimming. Owed: that row, and the base rate off the
   first take's stamps.
4. ~~The hold CONTEXT note has no denominator and disappears silently if `bird_clearance_m` is ever
   dropped.~~ **CLOSED (rounds 4-5).** The line now prints on every schema-2 log **with its
   denominator** (`holds with a threat=N of M hold(s)`, including `0 of 0` — a take that measured
   nothing about hold separation says so instead of falling silent), and a hold with **no usable**
   `bird_clearance_m` is a hard FIELD-DRIFT failure on the same rule R3.8 applies to a `gate_reject`.
   Round 5 closed the quieter half of that: a present value of the wrong TYPE (`"2.5"`, `{}`, `True`)
   was refused by `_num` and therefore fell into the "this hold named no threat" bucket, so a hold
   whose clearance had turned into a string read exactly like a hold with no bird near it while the
   hold COUNT kept rising. Drift is now *absent key OR unusable value*; an explicit `None` remains
   legitimate, because that is what `_handle_hold` writes when the decision names no threat. It still
   cannot flip a verdict on separation — it is explicitly ungated — but it is the number R4 will be
   booked on, so it may not go blank.
5. Two residual assumptions in the freeze bound, both written into the derivation comment rather than
   left implicit: a TRAILING frozen run has no closing stamp and is priced at the flight's own mean
   sim-step, and `v_next − v` under-prices a reader whose lag was still growing when it recovered.
   Worth revisiting only if a real flight ends on a frozen axis.
6. ~~`docs/ROADMAP.md` is stale on this round.~~ **CLOSED (round 5, 2026-08-24.)** It now carries the
   measured 877/2/0 + 822 + 57 counts, says the ADR amendments are written rather than owed, and its
   pre-registered breach remedy states the two-half contract (marker = context, pin = reviewed diff;
   **after a real R4 breach: marker only, and the take stands INVALID**) instead of the self-service
   green the old sentence described. Its doc long-tail item lost the three entries that had
   landed — the amendments, the ADR-003 header line, and the scenario fixtures, which are regenerated
   on `lateral_tree_margin_m` 1.0 and therefore describe the shipped control law again.
Owner / roles: qa-safety-reviewer (filed all seven and re-verified the fixes against rebuilt pre-fix
code); flight-software-engineer (F1/F3/F5/F7 in the checker, F2 in the executor); tech-lead (this
amendment, the in-place correction doctrine, the frozen marker set, and the ranking above);
product-lead (owns R4's continued exclusion and arbitrates if the marker call is argued).

### ADR-013 amendment 18 (2026-08-25, THE LIVE GATE — the whole 2026-08-24 offline stack flies): R2 PASSES on 4 of 4 dodges, R3 was never given its occasion, and the GT-CPA gate returns its first live verdict — BREACH at 0.0067 m, pre-registered, R4 now ranked by measurement
The first real-detection avoidance take flew (`docs/runbooks/AVOIDANCE_REAL_DETECTION.md`;
`eval/results/live_flight_log_20260825T210402Z.json`, schema 2, uncommitted at time of writing).
Everything ADR-003 am. 8, ADR-004 am. 1, ADR-009 am. 1, ADR-012 am. 2 and ADR-013 am. 13-17 built
offline was exercised in the air in one take.

**The verdict, first, and it is not softened anywhere below. INVALID — CPA BREACH, exit 1.**
`gt_cpa_m` **0.0067 m** horizontal to bird_0 at tick **991** (t_sim 202.775 s; drone z 15.03,
bird z 11.00, vertical separation **4.03 m**, i.e. inside the ±6 m threat band), against the
`min_bird_clearance_m` **3.00 m** bar; `gt_cpa_gated_m` **−1.1210 m** after the freeze debit. This is
**exactly the outcome am. 13 pre-registered in writing before the flight**, for the stated reason
(R4 escape geometry is deliberately cut-to-open), so it is reported as **the system working** and
never as a pass. Per am. 13/17 and runbook §6a the correct action is: **write the
`SAFETY_FINDING.md` marker, do NOT add the `ACKNOWLEDGED_BREACH_STEMS` pin, and let the take stand
INVALID until it is re-flown after R4.** The acknowledged set stays frozen at two historical stems.
* Re-derived by hand in this pass rather than quoted: bird_0's landed pose at t_sim 202.359 is
  (15.0, 21.110444, 11.0); the drone segment tick 991→992 runs (14.996943, 21.606987) →
  (14.987864, 20.382481); point-to-segment horizontal distance **0.006739 m** at parameter 0.405.
  The number is not a discretisation artifact — it is where the vehicle flew.

**R2's LIVE GATE: PASS, and non-vacuous — this is the gate am. 13 said was still owed.** Four
maneuvers, all `accepted`, swept tree clearances **1.393 / 1.756 / 1.340 / 1.857 m**, every one ≥ the
flown `lateral_tree_margin_m` **1.0**, and the flown margin ≥ today's `PolicyParams` default. The
policy refused **8 candidate headings** with its reasons in the artifact (every 0° candidate at
−1.93 to −1.97 m, the ±45° ones at 0.38 / 0.42 / 0.69 / 0.77 m) — because the lane the threat bird
patrols is orchard row 0, which is the encounter ADR-015 was written to create. Flown path: **0
`is_safe_3d` violations over 1858 points**. Ledger closed **720 covered / 0 debt** with 116 requeue
events, under a real detection encounter.
* **The honest limit on that PASS, stated so it cannot be read wider.** The GUIDED authority window
  was **0.434 s** (ticks 991→995) and the vehicle displaced **0.018 m** laterally inside it
  (0.054 m over the following 2 s) against a 10 m commanded dodge. **No tree clearance was ever
  tested in the air.** R2's live gate confirms the policy's arithmetic on live detector inputs; it
  does not confirm that a dodge keeps a metre off a tree, because no dodge was flown far enough to
  find out.
* ADR-006's maneuver held mechanically: AUTO → GUIDED at tick 991, one latch, two relatches, one
  `recommand_latched`, resume `threat_cleared` at tick 995 onto the **same** waypoint (index 5).
  `gate_rejects` 0, relatch refusals 0, holds **0 of 0**.

**R3 is VACUOUS on this take — and it missed its occasion by 15 mm.** The first latch (tick 991)
carried `trigger_range_m` **0.21** with `range_degenerate: true`; a FIRST latch at degenerate range
is permitted by design (am. 12 scoped R3 to *re*-latch), so R3 correctly did nothing there. The
18.896 m re-latch one tick later — the away-vector sign-flipping in 0.123 s as the drone passed over
the bird, which is the exact pathology R3 exists to refuse — carried `trigger_range_m` **1.015**
against `degenerate_range_m` **1.0**. It was commanded. Recorded as a decision rather than a knob
tweak: **`degenerate_range_m` was sized on one flight's noise, not derived from a physical quantity
the harm scales with**, and the first live encounter landed 15 mm outside it. Do not widen it by
taste; interrogate its denominator first (this is the same doctrine am. 15 F1 applied to the freeze
bound). R3's live gate is therefore still **OWED**, not passed.

**The GT-CPA gate's first live use: all three of its mechanisms fired on real data, and none of them
was the thing that failed.**
* **The truth join worked on both axes.** Truth coverage **1858/1858 ticks**; **610/610 landed
  `set_pose` calls scored** — the BIRD-axis denominator am. 17 added, exercised for the first time;
  `answered_from_spawn` 804/1858; `cpa_from` `tick_sample` (the pose-window pass agreed, it did not
  win). Ambiguity resolution never had to buy or refuse clearance at the CPA.
* **The freeze debit fired on a real stall and behaved as sized.** Worst frozen run: **2 ticks at
  sim 192.9 s, hidden window 0.161 s**, priced at 0.161 × 7.0043 m/s = **1.1277 m** — re-derived
  from the flight's own `tick_stamp_sim_s` in this pass. It is a real, measured stall, and it is
  priced from a freeze roughly **10 s and 40 m away from the encounter**, which is the conservative
  behaviour am. 17 designed: the debit did NOT reach the 3.00 m bar, so this is a CPA verdict and not
  a clock fault. The gate's am. 17 false-positive worry did not materialise on take one; that base
  rate now has its first datum.
* **The estimator split earned its demotion.** `detection_cpa_m` **0.2096 m** against `gt_cpa_m`
  0.0067 m, `range_estimate_error_at_cpa_m` **−0.2028 m**, printed and never gated. This is the
  first flight where the demotion mattered, because it is the first flight where the detector — not
  a constant we chose — supplied the bird position. Had R1's self-referential CPA still been the
  gated number, the flight would have been scored against its own estimate.
* Clock: **0 domain violations over 260,361 readings**, 0 ticks without a clock reading, 1858/1858.
  `n_stale_dropped` 0. The one-clock machinery of ADR-009 am. 1 is clean end-to-end (am. 2 there).

**The detector floor's FIRST IN-AIR READING — and the second instance of this project's standing
rule.** `frames_detected_on` **1301** of `ndvi_msgs_received` **1302** = **99.9232 %** against
`MIN_DETECT_RATE` 0.90. The single loss is `dropped_no_intrinsics` **1** — precisely the
startup-ordering transient the constant's comment predicted, at ONE frame rather than the ~3 % it
budgeted. `detect_wall_ms` p95 **8.2** / max **41.9** ms against the 200 ms tick, so the detector
never threatened the single-threaded executor.
* **Do NOT narrow the floor** (am. 15 F6's rule, restated with a number behind it now): n=1, and the
  failure mode 0.90 guards is bringup ordering, which is exactly what varies between takes. Revisit
  at n ≥ 3 takes.
* **The sentence that matters more than the reading: a green 99.92 % sat on top of a take where the
  detector saw a bird on 2 of 1301 frames.** This is the second time a value gate has gone green
  across a geometry failure — the first was ADR-007's four green gates with the camera facing the
  horizon (am. 5 there). **A gate that measures VALUES structurally cannot catch GEOMETRY.** That is
  now a pattern with two instances, not an anecdote.

**The 16-vs-4 line IS the finding of this take, and it re-scopes R4 before R4 is built.** am. 14
reported "bird truly inside the cylinder on N tick(s); the loop engaged on M" deliberately UNGATED,
because gating it would gate geometry — and that is precisely what it measured: **16 contiguous
in-cylinder ticks (984-999), the loop engaged on 4 (991-994)**. (Corroborated in this pass with a
cruder latest-landed-pose accessor: 15 ticks, 984-998 — same window, one boundary tick apart, which
is what a coarser accessor should give.) The mechanism is measured, not argued:
* **The mount is NADIR** — the gate's own explanatory note says "a bird behind the drone is invisible
  to a forward-facing camera", which is *wrong about this vehicle* and must be corrected to
  footprint-at-depth (a wrong explanation retires the right question). At the encounter's 4.03 m
  depth the half-footprint is **2.48 m along-track × 1.86 m cross-track** against a **12 m** threat
  radius: the camera images about **4 %** of the cylinder cross-section, and the half-width reaches
  12 m only at 19.5 m (x) / 26.0 m (y) depth — far outside the ±6 m vertical band. **The sensor
  horizon at the depth that matters is 2.48 m against a 12 m policy horizon.**
* **7** NDVI frames were captured while bird_0 was truly in-cylinder; **2** had the bird inside the
  image; the detector produced a box on **2**. The five misses were 1.4-7.8 m outside the image edge
  (median 3.8 m). Zero false positives in 1301 frames. **The detector converted every opportunity it
  was given — the miss is 100 % footprint geometry** (numbers and labels in ADR-003 am. 9).
* **Lead time, a number that did not exist before this take: sensor lead 0.175 s, policy lead
  0.000 s.** The first detection was consumed **on the CPA tick itself**. Two frames (795, 796) drove
  all four engaged ticks at detection ages 0.174-0.298 s against the armed 1.0 s bound. Camera dwell:
  1.4 s in the cylinder, **0.4 s in the image**, at ~14.4 m/s closing.
* **What this binds for R4, and it is a re-scope:** **no escape geometry can buy warning time the
  sensor never had.** Price any R4 proposal against **0.175 s of lead and 0.4 s of dwell**, not
  against the policy's 12 m cylinder, and pair it with at least one of: threat persistence, sensor
  horizon (mount/tilt — ADR-009 am. 2 surfaces that as a product call, not a guess), or flight
  speed (ADR-015 am. 1). **R4's gate must include LEAD TIME beside CPA**, because a green CPA bought
  on 0.175 s of lead is luck, not clearance. Two further constraints from this take: the reversal
  candidate R4's candidate order prefers is **structurally unavailable on lane x=15** (that lane is
  orchard row 0 — every 0° candidate here was rejected at ≤ −1.93 m), and **if R4 adopts a CLIMB the
  gate will then print `gt_cpa_m NONE-IN-BAND`, which is a pass that must be read together with the
  horizontal-separation context or it is a vacuous green.**
* **No threat hysteresis, named not fixed:** the resume at tick 995 fired `threat_cleared` because
  ONE empty frame replaced the latest detection — not because of staleness (ages were 0.174-0.298 s
  against a 1.0 s bound). One empty frame ends an encounter. On a 2-frames-of-1301 sensor that is a
  coin flip, and it belongs with R4 rather than in front of it.

**The teardown gap — RECORDED OPEN, deliberately not patched in this session.**
`scripts/fly_pipeline.sh down` was never invoked: the operator did runbook §4 step 1 (Ctrl-C the
avoidance shell; flight log written 21:04:02Z) and went straight to §5 scoring. **Nothing anywhere
notices.** `cmd_status` prints windows and liveness probes and would have said nothing was wrong;
`up`'s surviving-process refusal only fires on the *next* session; the safety gate scored a complete
verdict without ever needing the clip. Skipping `down` has **zero visible consequence at the moment
you skip it** — which is the whole defect. The recorder was found still alive and still writing at
5 Hz more than eight minutes after the flight log was written (frame count sampled twice a minute
apart, 2459 → 2669, to prove it was growing rather than assumed).
* Recovered by the **shipped** path — Ctrl-C the `record` pane and poll for `clip finalized`, which
  is what `cmd_down` does first — not by an offline rebuild. An offline rebuild would have been
  actively wrong: `ClipWriter.__init__` opens `poses.jsonl` with `"w"` and would have **truncated
  the evidence**, and the live counters, `fuser` block, DDS snapshot and live intrinsics exist only
  inside that process. Finalize took under 15 s for 3310 frames.
* **Measured cost of the skip:** 2639 post-landing parked frames (~80 % of the clip by count,
  ~1.1 GB) and, until recovery, no `meta.json` — which makes a clip unstitchable. The parked frames
  are harmless and self-reporting (the camera sits below the z=0 plane, so all of them are
  `frames_zero_update`), but **`num_frames` 3310 is inflated: quote 671 airborne / 649 painting.**
* Owed, one line each, and NOT written here (this session's ownership is this file): a
  `test -f "$CLIP/meta.json"` assertion in the runbook §5 capture block *before any gate runs* —
  highest value, because §5 is where the operator is standing when it matters — and a `cmd_status`
  warning when the `record` window is alive while the newest clip has no `meta.json`.
* **The clip, after recovery, is clean, and it covers the breach** (airborne window 174.6-308.6 sim s
  brackets the CPA at 202.775 s): 3310 frames, **671 airborne over 134.0 s at 5.0 Hz flat**, 649
  painting at 5.0 Hz, **720/720 cells imaged**, tree gate PASS **18/18 imaged, 11/18 canopy-grade,
  median lift +0.5562** — better on both counts than the ADR-003-adopted clip re-scored the same day
  for a like-for-like comparison (9/18, +0.5402). Transport: Red 3400 / camera_info 3400 = **100 %**;
  fuser 3399 → recorder 3327 = **97.9 %**; DDS block clean (4 segments, min_bytes = max_bytes =
  8,413,728). The am. 9 throughput fix held again on an independent flight, this time with the extra
  `--detect` shell competing for the box. **The NDVI half being intact does not soften the CPA
  verdict and is not offered as a counterweight to it.**

**The record cannot currently be written, and that is a decision to take before the marker, not a
chore.** As the repo stands the shipped gate **cannot score this take at all**: two applied truth
logs overlap the flight's sim window 43.518-303.683 s — `bird_drive_20260823T073836Z_applied.jsonl`
(110.383-262.481 s) and this take's own (183.057-996.343 s) — so `check_live_flight_log.py` returns
`AMBIGUOUS TAKE` → INVALID and **the CPA is never printed**; `--truth` selects but does not silence,
by design (am. 15 F5). Every number above was produced by pointing the shipped gate at a directory
holding only this take's track, or re-derived by hand from the artifacts. Consequently the marker/pin
contract of am. 17 **has still never run on a schema-2 log**, and committing this take's truth track
is exactly what would make the ambiguity permanent in CI. Options named and NOT chosen here —
product-lead's call, safety-vs-scope: keep this evidence uncommitted; move the stale 2026-08-23
applied log out of `eval/results/`; teach the CI step to pass `--truth`; pin a truth sidecar per log.
**What is not an option is adding a third stem to `ACKNOWLEDGED_BREACH_STEMS`** — am. 17 froze that
set at the two historical logs precisely so a re-flyable take cannot be made green by a diff.
**The contract was executed correctly on take one:**
`eval/results/live_flight_log_20260825T210402Z.SAFETY_FINDING.md` is written (the context half — it
states in its own title that the breach is **NOT ACKNOWLEDGED** and that the pin is deliberately
absent), and `ACKNOWLEDGED_BREACH_STEMS` is verified **unchanged at two stems**. Marker without pin
is half an acknowledgement; the take stands INVALID / exit 1. That is the record.

**And executing it correctly turns the suite RED — the third instance of the am. 17 F6 family (the
doc and the test contradicting each other inside the same repo), found by running the suite in this
pass rather than by reading it.** `pytest tests -q` → **876 passed / 1 failed / 2 skipped** (same 879
total as am. 17's close, so the single delta is this):
`test_check_live_flight_log.py::TestAcknowledgementMarkersOnRealEvidence::test_every_breaching_committed_log_has_BOTH_halves_of_an_acknowledgement`
globs **`eval/results/`** — the working tree, not the committed set its docstring describes — and
asserts that any breaching log **carrying a marker** must ALSO be pinned. That is exactly the state
am. 13/17 and runbook §6a **require** after a real breach, so the test demands the one thing the
contract forbids. Measured: the three logs in the directory read 0.0597 / 0.0518 (marker + pin) and
**0.2096 (marker, no pin)** — note the third number is `closest_approach`, the LEGACY
detection-referenced metric this gate demoted in am. 14, not the 0.0067 m ground-truth CPA the take
actually failed on, so the test is also reasoning from the demoted number.
* **Not fixed here, deliberately, because the fix is a decision and not a patch.** Read one way the
  test is right — an unreviewed breach must never be COMMITTED — and then it is a correct tripwire
  firing early on an uncommitted file, which means **this take's evidence cannot be committed at all
  until it is re-flown**, and that is a real constraint on the record shape above, not a nuisance.
  Read the other way its glob is wider than its docstring and the pin assertion should apply only to
  tracked files. Whoever takes the record-shape decision takes this one with it; whichever way it
  goes, the test and §6a must stop disagreeing in the same repo.

**What this take did NOT measure, listed so a quiet log is never read as a clean one.** Hold
clearance (**0 of 0 holds** — R4's own context number, the one am. 13/17 said the first `--detect`
take would quantify, got no reading at all); the executor's bird-clearance backstop (`gate_rejects`
0); R3's refusal branch (above); **phantom dodges — bird_1 and bird_2 were in frame on 0 of 1301
frames, so the false-positive dodge rate is UNMEASURED, not cleared**; and the swept-path re-vet as
ownship moves (S2). Each is worth a named scenario before it is claimed.

**Ranked, after this take.** (1) **R4 escape geometry — now ranked #1 by measurement rather than by
argument**, re-scoped by the lead-time and horizon numbers above, and it is a Product Lead call to
un-cut it. (2) The re-fly's own precondition is NOT R4: the runbook §0b abort gate is green at a
speed the vehicle has never flown (ADR-015 am. 1) — booking a re-fly under today's default buys
another 2-frame encounter. (3) The teardown assertion and the `cmd_status` warning. (4) The record-shape
decision above — the truth-log ambiguity AND the marker-without-pin test — which blocks the record
before it blocks the flight, and which currently holds the suite at 876/1/2.
Owner / roles: qa-safety-reviewer (the anatomy of the encounter, the gate's behaviour, the new safety
gaps); perception-ml-engineer (detector, lead time, visibility budget — ADR-003 am. 9);
robotics-sim-engineer (clip recovery by the shipped path, NDVI gates, the teardown finding);
flight-software-engineer (policy/executor under live inputs); product-lead (owns R4's cut and the
truth-log record shape); tech-lead (this amendment and the R4 re-scope above).

### ADR-009 amendment 2 (2026-08-25, the seam FLEW): both contract rules CONFIRMED live, the ray's bias failed safe as designed — and the seam's own measurement is what found the sensor horizon
am. 1 said "nothing here has flown — this stays confirmation-pending until the next avoidance
flight." It flew (ADR-013 am. 18). **Status: CONFIRMED live 2026-08-25.**
* **Rule 1, the clock: clean end-to-end.** 260,361 `/clock` readings, **0 clock-domain violations**,
  0 ticks without a clock reading over 1858 ticks, on the native `gz topic -e` subprocess reader that
  had never met a real Gazebo. The staleness gate was ARMED at `max_detection_age_s` 1.0 and never
  had to fire (`n_stale_dropped` 0): the two detection frames were consumed at ages **0.174-0.298 s**,
  which is ~3-6× inside the bound and consistent with the 0.156 s max the bound was sized on. The
  bound is neither loose nor tight on this evidence; leave it.
* **Rule 2, the ray: implemented, live, and biased the way the ADR promised.** Estimated depth
  **3.43 m** against a true **3.95 m** slant = **13.2 % under-range**, from the deliberate 0.15/0.18
  radius prior (0.833) compounded with ~4 % morphological erosion (r_px 22.75 vs a true 23.70). In
  cylinder terms the estimate placed the bird at **3.43-3.52 m** vertical separation against a true
  **4.03 m** — i.e. **deeper into the threat band than it really was, the fail-safe direction**,
  exactly as `BIRD_RADIUS_PRIOR_M` documents. Ground-plane projection would have placed it at z=0 and
  suppressed the threat; it was never called.
* **Live↔offline equivalence, to 1 µm.** The offline harness pushed the same two boxes through
  `ndvi_detect.box_to_detection` with the clip's own poses and reproduced the flight log's own
  `Detection.position_enu` to **|Δ| ≈ 1e-6 m**, agreeing on all 1301 in-window frames — across
  **scipy 1.8.0 in the air** (jammy `python3-scipy`, ADR-004 am. 1) versus 1.13.1 on the host. That
  closes ADR-003 am. 8's "transfer is verified on ONE scipy version" caveat with a third version
  measured **in flight**, which is the check the artifact cannot fake.
* **am. 1's live watch item, measured:** re-latch churn from monocular jitter is real — 2 relatches
  in 4 maneuvers, one of them an **18.896 m sign-flip in 0.123 s** as the drone passed over the bird.
  The lever (`RELATCH_THRESHOLD_M` or a tracker) is now decidable on a flown number rather than a
  dress rehearsal. R3 was supposed to be the cheap half of that and missed by 15 mm (ADR-013 am. 18).
* **The new finding, and it belongs to this contract because this contract's own numbers produced
  it: the SENSOR HORIZON is 2.48 m and the POLICY horizon is 12 m.** The apparent-size ray has
  roughly 40 m of usable range headroom; a strictly nadir mount inside the ±6 m band makes it
  unreachable, so the detector is FOV-limited, never range-limited. **OPEN QUESTION, surfaced not
  guessed, and it is a product-lead / ADR call: does the camera stay nadir?** A forward tilt is the
  single lever that most directly buys lead time — and nadir is what the entire NDVI half is built
  on, on a clip that scored this project's best-ever tree gate (ADR-013 am. 18). ADR-015 already
  arbitrated one collision between these two priorities on the world file; this one is on the mount,
  and it must not be decided inside an R4 implementation round. Non-mount alternatives on the table:
  fly the encounter lanes slower, or fund ADR-003 criterion 2's second sensor.
Owner / roles: flight-software-engineer (seam, clock, node); perception-ml-engineer (ray, the
equivalence check); qa-safety-reviewer (the gate that reads it); product-lead (owns the nadir
question); tech-lead (recorded, and the framing of the open question above).

### ADR-003 amendment 9 (2026-08-25, the ADOPTED detector's first evidence IN THE AIR): EVIDENCE INSUFFICIENT — 2 visible bird-frames, and the harness refusing to score is the harness working
The am. 7 ADOPT verdict is **neither challenged nor confirmed** by the 2026-08-25 take.
`eval/score.py` returned **EVIDENCE INSUFFICIENT** on its own decision rule ("only 1 of 3 birds were
ever visible"), which is the guard doing its job on a 2-frame denominator.
* **Scoreable, and stark.** Labels annotated from the driver's applied-pose log: **7325 applied /
  2605 spawn / 0 modeled**. Ground truth says the whole 3310-frame clip contained **2 visible
  bird-frames** (both bird_0). The detector produced boxes on exactly those 2: **TP 2 / FP 0 / FN 0**,
  precision 1.000, recall 1.000, per-bird-track FNR 0.000 — on n=2, over 1 of 3 birds. Arm (b),
  synthetic RGB: TP 0 / FP 3 / FN 2, birdness still deliberately INVERTED on this world.
* **`detected_before_closest = True` is technically earned and operationally worthless. Quote it only
  with the 0.175 s of sensor lead attached** (policy lead 0.000 s — the first detection was consumed
  on the CPA tick itself). A detector that sees the bird 0.175 s before the closest approach has not
  given the loop anything to act on; see ADR-013 am. 18 for what that binds for R4.
* **The threshold's BACKGROUND half of the FP characterisation is now DONE, and it is decisive.**
  Across all 3310 frames (**1.02 Gpx**) the darkest non-bird pixel is **−0.4406 on every frame**, and
  **zero pixels anywhere in the clip fall below −0.50**, while the warmest bird pixel is **−0.6697**.
  So **−0.61 sits in a 0.229-wide empty band** and any value in (−0.6697, −0.4406) is bit-identical
  on this clip — the threshold is not tuned, it is unconstrained on the background side.
* **−0.61 stays PROVISIONAL, and the reason is now specific rather than general: the RANGE half is
  untouched.** The threshold has only ever been exercised at ~4 m depth on a 47 px bird. Lifting the
  label needs a clip with birds at **3+ distinct ranges** — not another pass at 4 m. That is
  perception-ml-engineer's call, unchanged.
* **Criterion 2 (the comparison arm) now has its concrete measured case, and its input is on disk.**
  Seven in-cylinder frames yielded two in-image on the single nadir NDVI camera; the same clip ships
  **3310 real RGB PNGs (640×480)** — the independent RGB pixel study's input — untouched. The
  second-sensor question stopped being hypothetical on this take.
* The 5 in-cylinder frames the detector never got were **1.4-7.8 m outside the image edge**
  (median 3.8 m), and `predict_bird_visibility.py --backtest` reproduces the result independently
  (**2 / 0 / 0** frames in view). **Nothing here implicates the detector, the threshold or
  `MIN_DETECT_RATE`; no change to any of the three is proposed.**
Owner / roles: perception-ml-engineer (the scoring, the FP characterisation, the PROVISIONAL call
and criterion 2); tech-lead (recorded).

### ADR-015 amendment 1 (2026-08-25, the geometry FLEW): the THREAT gate held, the VISIBILITY prediction missed by ~4× — and the cause is the predictor's default SPEED, not this world file
* **The threat half held, exactly as designed.** bird_0 on lane x=15 at z=11 was in the threat
  cylinder for **16 contiguous ticks** and produced the take's only encounter, on a lane where the
  policy had to refuse every 0° candidate against orchard row 0 (ADR-013 am. 18). The ADR's central
  claim — a lane-PARALLEL bird can be in the cylinder *and* in frame — is not what failed.
* **The visibility half missed.** This ADR's table predicts medians **8 / 6 / 11** frames in view; the
  flown clip shows **2 / 0 / 0** (`predict_bird_visibility.py --backtest`: 2 bird-visible frames of
  3310, closest approach 3.95 m slant, bird_1 184.8 px and bird_2 212.2 px outside the frame). Note
  the table is honest about its own basis — it declares **3 m/s** in its caption. **The defect is in
  the tool's default and in the runbook that leans on it, not in this table.**
* **`scripts/predict_bird_visibility.py`: `DEFAULT_SPEED_MPS = 3.0`, and the vehicle does not fly
  3 m/s.** The clip's own airborne poses measure cruise p50 **3.13** / p90 **9.07** / max **10.21**
  m/s, and the encounter itself was flown at roughly 9 m/s. Re-run at the flown speed the gate
  **FAILS**: `--speed 8` → FAIL, 3 of 3 birds below the 5-frame floor (medians 2/0/4); `--speed 9.4`
  → FAIL. **So runbook §0b's abort gate was GREEN at a speed the vehicle has never flown** — it
  cleared the take that then bought a 2-frame encounter. Its provenance string is dangling too: it
  cites `docs/runbooks/SIM_BRINGUP.md` for "WPNAV_SPEED as flown", and that file contains no speed
  figure (`WPNAV_SPEED` appears nowhere in `scripts/`, `docs/runbooks/` or `config/`).
* **Owed before the next take is BOOKED, and it is cheaper than any of it:** fix the default (or make
  `--speed` required so the gate cannot be run without stating its assumption), re-run §0b at the
  speed the mission will actually fly, and correct the published 8/6/11 wherever it is quoted. A
  go/no-go gate whose default disagrees with the vehicle is the same failure family as a rate with no
  denominator.
* **The tradeoff this exposes, for whoever re-scopes R4:** dwell scales inversely with ground speed,
  so "fly the encounter lanes slower" is a real lever on lead time that costs no mount change and no
  new sensor — and it costs survey time, which is a Product Lead call, not an engineering one.
Owner / roles: robotics-sim-engineer (the geometry and the predictor); perception-ml-engineer (the
backtest); product-lead (owns the speed-vs-survey-time trade); tech-lead (recorded).

### ADR-012 amendment 3 (2026-08-25, schema 1.1 FLEW): the 0.039 s anchor is a FLOOR not a constant, and the driver outliving the flight is the hazard nobody had named
* **am. 2's one unflown prediction, now measured.** It said "expect `clock_wall_s − tick_wall_s` ≈
  0.039 s in the first [real flight]". Over 596 unique ticks on this take: median **0.0526 s**, min
  0.0413, p95 0.1048, max **0.3124 s** — about 35 % above the 2026-08-23 figure, consistent with the
  extra `--detect` shell competing for the box. **0.039 s is a floor, not a constant**, the wiring is
  correct (the anchor is always positive and post-poll), and the schema-1.1 bracket widening is
  load-bearing at that magnitude rather than decorative. Driver performance: `set_pose` round-trip
  0.251 s median / 2.053 p95 / 2.236 max, achieved **1.049 Hz** against `--rate 2`, and **278 of 2202
  calls failed (12.6 %)** — none within ±7.5 s of the CPA.
* **The hazard: `drive_birds.py` is NOT stopped by the evidence-first teardown, and its log keeps
  growing after the flight log is written.** On this take it ran on to sim **996.343 s** against the
  flight's last tick at 303.683 s, and the file grew **1348 → 2202 records** while the take was being
  reviewed. The breach record itself is safe — the log is append-only, so the tick-991 record is
  immutable and `gt_cpa_m` re-measures identically — but the gate's *counts around it move*: "truth
  landed `set_pose` calls per bird" counts the WHOLE track, so it re-ran at 489/478/485 → 655/625/644
  on the same flight. A safety artifact whose denominators change when you re-run it is not yet
  evidence.
* **Owed:** freeze the driver before an artifact set is called final (the runbook's evidence-first
  teardown covers the recorder and the avoidance shell but says nothing about the bird driver), and
  give that counter a **flight-window denominator** so it stops counting poses the flight never saw.
Owner / roles: robotics-sim-engineer (driver + teardown order); qa-safety-reviewer (the consumer that
noticed the drift); tech-lead (recorded).
