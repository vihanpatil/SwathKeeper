---
name: extractability-audit
description: What of the avoidance core is genuinely portable off the sim, what is sim-bound, the concrete extraction costs (no packaging, REPO_ROOT defaults), the two rival definitions of "covered", and the ecosystem facts that decide the product form
metadata:
  type: project
---

Audit done 2026-08-25 for the dual-track decision (finish portfolio v1 AND make the avoidance core
extractable as a product seed).

**Portable, verified by import on a bare host interpreter** (no numpy/scipy/rclpy loaded):
`avoidance_types`, `avoidance_policy`, `avoidance_executor`, `geofence`, `coverage`,
`mission_waypoints`, `ros2_adapter`, `dds_env` all import clean. The `VehicleCommandSink` Protocol
is a genuine seam — the entire vehicle binding is `ros2_adapter.py` (199 lines, ~75 of them rclpy),
so a MAVLink/MAVSDK sink is a small file, not a rewrite. On MAVLink it is actually *better*: AP_DDS
has no mission-current service at the pinned SHA (hence `_nearest_upcoming_wp`'s nearest-waypoint
guess), while MAVLink ships `MISSION_CURRENT`.

**Extraction costs that are real and specific:**
- There is **no packaging at all** — no `pyproject.toml`, no `setup.py`, no ROS 2 `package.xml`.
  Everything runs on `PYTHONPATH=src`. `src/fieldguard_planning/__init__.py` says so explicitly.
- Five modules hardcode `REPO_ROOT = Path(__file__).resolve().parent.parent.parent` and default
  their loaders to repo config paths (`GeofenceMap.from_file`, `coverage.load_field_polygon`,
  `ros2_adapter.load_home`). Every one already accepts an explicit path, so this is a
  default-argument change, not surgery.
- `scripts/check_live_flight_log.py` is the crown jewel of the safety story but imports
  `drive_birds` and `annotate_real_clip` at module scope — the ground-truth half is welded to
  Gazebo `set_pose` logs. The *pattern* transfers; the file does not.

**TWO DEFINITIONS OF "COVERED" LIVE SIDE BY SIDE — the highest-value fix available.**
`coverage.coverage_from_path` marks a cell covered when its centre is within
`DEFAULT_SWATH_HALF_WIDTH_M` (7.5 m, an *isotropic* radius) of the flown polyline — a
path-proximity claim. `ndvi_georef.NdviHeatmapGrid.accumulate_frame` marks a cell painted only when
its centre actually projects inside a real frame — an evidence claim. The ledger's headline
guarantee is computed with the former.
The 7.5 m came from lane-spacing/2 and the module docstring flags it as unvalidated. It is now
measurable and it is **wrong**: at 15 m cruise the footprint is 18.46 m along-track x **13.85 m
cross-track**, so the true cross-track half-swath is **6.92 m, not 7.5 m** — a 1.15 m unimaged
strip between every 15 m lane pair. 720/720 still holds only because 2.5 m cell centres land at
x=21.25/23.75 and miss the 21.9-23.1 m gap by 0.67 m. The guarantee is currently
quantization-dependent, not physical. Deriving `covered` from painted cells closes it and is what
makes the ledger a product-grade artifact.

**Sim-bound by deliberate scope (fine, say so):** thermal-as-NIR (ADR-007), gz `/clock` subprocess
streaming, `drive_birds` set_pose ground truth, the 0.15 m bird radius prior, the -0.61 threshold.
**Sim-bound by accident (worth flagging):** `RELATCH_THRESHOLD_M = 3.0` was sized on scenario
replays where the per-tick delta is the ownship step (2.00 m); real monocular jitter blew through
it — 2 relatches in 4 maneuvers on the 2026-08-25 take.

**Ecosystem facts that decide the product FORM (checked 2026-08-25):**
- `PX4/PX4-Avoidance` was **archived by its owner on 2024-08-01**, read-only
  (https://github.com/PX4/PX4-Avoidance) — a general-purpose ROS avoidance stack that the
  ecosystem did not sustain. That is a warning about the "full reference stack" product form.
- ArduPilot already ships avoidance in firmware: BendyRuler + Dijkstra + `AP_OADatabase`
  (https://ardupilot.org/copter/docs/common-oa-dijkstrabendyruler.html). An external mode-taking
  executor competes with the autopilot; the *supported* seam for external perception is
  `OBSTACLE_DISTANCE` / `DISTANCE_SENSOR` into `AP_Proximity` with `PRX_TYPE=2`
  (https://ardupilot.org/copter/docs/common-simple-object-avoidance.html).
- What nobody ships is the coverage-debt ledger and the flight-log evidence gate. That is the part
  with no incumbent.
- "Vaara Drone" is not publicly findable (searched 2026-08-25); treat it as the ag-survey CLASS.

Related: [[flight-20260825-lead-time]], [[node-topic-map]], [[detection-seam]]
