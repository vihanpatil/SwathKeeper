# FieldGuard — Decision Log (ADR-lite)

Owner: `tech-lead` (with `product-lead` for scope calls). **Every non-trivial choice goes here** with
the alternative rejected and a one-sentence reason. Per the playbook's escalation rule, when two
roles disagree the `product-lead` wins for v1 **and the disagreement is recorded here as a tradeoff.**
This log is the engineer's interview script for "why did you build it this way?"

Format per entry:

```
## ADR-NNN: <title>   (YYYY-MM-DD, status: accepted | superseded | proposed)
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
Exact pins live in `CLAUDE.md` "Pinned versions" and the bringup steps in `docs/WEEK1_BRINGUP.md`.
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

## ADR-005: Enable AP_DDS explicitly + lock the /ap/* topic/service/frame contract to the pinned ArduPilot SHA   (2026-08-04, status: ACCEPTED — confirmation-pending)
Decision: Enable AP_DDS via an explicit param file (`config/sitl_params/dds_udp.parm`: DDS_ENABLE=1,
DDS_UDP_PORT=2019), loaded through `sim_vehicle.py --add-param-file` rather than relying on the
compiled-in default or `ardupilot_gz_bringup`'s launch file. Keep DDS_USE_NS=0 (compiled default) so
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
      rejected project-wide, sim/README.md / WEEK1_BRINGUP.md), and its default DDS_USE_NS=1 would
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
