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

## ADR-003: NDVI-vs-RGB detection approach  (2026-08-04, status: ACCEPTED — confirmation-pending; spike landed, see docs/SPIKE_ndvi_vs_rgb.md §Outcome)
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
