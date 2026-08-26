# Config

Data-driven scenario + mission configuration so scenarios can be added without code changes:
- `field_polygon.json` — field boundary / boundary survey (home lat/lon + ENU polygon), shared by
  the mission generator (`scripts/gen_boustrophedon.py`) and the farm world generator
  (`scripts/gen_farm_world.py`) so they stay geometrically consistent.
- `missions/` — mission / coverage parameters (`boustrophedon.waypoints`, QGC WPL 110).
- `static_obstacles.json` — ADR-001 known-static-obstacle (tree) geofence export: hand-authored row
  layout + generator-computed per-tree positions/radii. The contract `flight-software-engineer`'s
  geofence/planner reads directly (schema documented in `sim/README.md`).
- `birds/` — scripted dynamic bird trajectories (2-3 birds; MVP scope, not a flock). Per ADR-012 the
  birds are static SDF models: `scripts/gen_farm_world.py` spawns them at their first waypoint and
  `scripts/drive_birds.py` replays these waypoints at runtime via Gazebo `set_pose`. Currently
  `birds/farm_world_birds.json` (the farm world's birds); `sim/spike/scenario_default.json` has a
  separate bird scripting for the NDVI-vs-RGB spike clip (different field size/purpose, same style).
- `sitl_params/dds_udp.parm` — the params every SITL flight needs: `DDS_ENABLE=1` +
  `DDS_UDP_PORT=2019` for the ROS 2 `/ap/*` bridge, and `MIS_RESTART=0` so re-entering AUTO after an
  avoidance dodge RESUMES the mission instead of restarting it at item 1 (ADR-006; pinned here
  2026-08-25 because it had only ever been typed at the MAVProxy prompt).
  **The param file alone does nothing for DDS:** SITL compiles AP_DDS out by default, so build with
  `sim_vehicle.py --enable-DDS --add-param-file=...` — without `--enable-DDS` the `DDS_ENABLE` param
  does not even exist and zero `/ap/*` topics appear, silently (ADR-005 correction). See
  `docs/runbooks/SIM_BRINGUP.md` §6b and `docs/DECISIONS.md` for the locked topic/frame-id contract
  this unblocks.
- `ndvi_camera.json` — ADR-007 dual-band NDVI sensor mount (Weeks 5-6): RGB (Red band, also the
  ADR-003 NDVI+RGB comparison arm) + Gazebo thermal sensor (repurposed as synthetic NIR) intrinsics,
  the sensor-mount attachment pose, and the per-material-class `<temperature>` calibration table
  (canopy/trunk/soil/bird). Consumed by `scripts/gen_farm_world.py` (world) and
  `scripts/check_ndvi_bands.py` (the Gate 2 pixel smoke test, `docs/runbooks/NDVI_VALIDATION.md`).
  **FROZEN** for the duration of the ag-avoidance push (ADR-019 item 7).
- `depth_camera.json` — ADR-019 forward depth camera: the SECOND aperture's mount pose, intrinsics,
  rate, clip planes and the booking-gate constants that are not owned elsewhere. Nadir cannot buy
  detection lead time at any speed (ADR-017 am. 1), so detection moves forward while NDVI stays
  closed. Every gz-sensors claim in it carries a source citation, including the one most likely to
  be got wrong by analogy with `ndvi_camera.json`: a `depth_camera` sensor IGNORES
  `<camera_info_topic>` and derives the name from `<topic>` instead. Consumed by
  `scripts/gen_farm_world.py` (world), `scripts/check_depth_mount.py` (static geometry gate) and
  `scripts/predict_forward_lead.py` (the booking gate).
