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

## ADR-003: NDVI-vs-RGB detection approach  (2026-08-04, status: ACCEPTED — confirmation-pending; criterion 3 ATTEMPTED 2026-08-21 and returned EVIDENCE INSUFFICIENT, see amendments 1-3)
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

## ADR-009: Real-detector evidence contract — stamped detections with a policy staleness gate; bird position from apparent-size ray, never ground-plane projection   (2026-08-18, status: ACCEPTED — implementation lands with the Week-6 detector)
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

## ADR-015: Bird geometry answers to TWO gates — one lane-PARALLEL threat bird in the cylinder, two lane-crossing observation birds below it   (2026-08-21, status: ACCEPTED — host-verified on both gates, not yet flown)
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
