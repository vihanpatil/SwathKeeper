# ROS 2 packages (colcon workspace `src/`)

**Actual structure (Weeks 1–4):** the reactive-avoidance loop consolidated into a single stdlib package,
`fieldguard_planning/` (below) — decision policy, executor, geofence, coverage, and the ROS 2 adapter
all live there, kept pure-Python so they unit-test without a ROS 2 environment. The original plan was to
split these across separate ament packages (`fieldguard_perception` for the detector/policy,
`fieldguard_control` for the executor, `fieldguard_mapping` for NDVI georeferencing, `fieldguard_msgs`
for interface contracts, `fieldguard_bringup` for launch files); that split remains a reasonable future
refactor once the modules are promoted to colcon packages, but was not needed to demonstrate the loop.

Owned primarily by `flight-software-engineer` and `perception-ml-engineer`; interfaces by `tech-lead`.

## `fieldguard_planning/` — the reactive-avoidance core (Weeks 2–4, DONE)

The whole avoidance loop lives here, deliberately **stdlib-only** so it is unit-testable on a bare
interpreter with no sim/ROS 2 (55 tests in `tests/fieldguard_planning/`):

- `geofence.py` — static-obstacle geofence consumer (ADR-001): XY exclusion queries **plus the 3D
  safety gate `is_safe_3d`** (a setpoint over a tree at cruise altitude is safe; one that descends into
  the canopy band is not).
- `coverage.py` — canonical field grid + the **coverage-debt ledger invariant** (`check_ledger`): a
  cell absent from the ledger = the silently-skipped bug.
- `mission_waypoints.py` — QGC WPL parser + lat/lon↔ENU conversion.
- `avoidance_types.py` — the policy↔executor contract (`Detection`, `DroneState`, `AvoidanceManeuver`).
- `avoidance_policy.py` (perception) — decides PROCEED/DIVERT/HOLD; a DIVERT carries only a 3D-vetted
  setpoint, else HOLD.
- `avoidance_executor.py` (flight-software) — ADR-006 latching `AUTO→GUIDED→setpoint→AUTO` state machine
  behind a `VehicleCommandSink` seam; re-vets every setpoint; books coverage-debt from the flown path.
- `ros2_adapter.py` + `avoidance_node.py` — the thin rclpy layer that binds the seam to the confirmed
  AP_DDS interface (`/ap/mode_switch`, `/ap/cmd_gps_pose`, `/ap/pose/filtered`) and runs the loop live.
  **Demonstrated end-to-end on the real stack (2026-08-05)** — see `docs/runbooks/AVOIDANCE_DEMO.md`.

**Not yet a colcon package** (no `package.xml`/`setup.py`): the pure modules import via `PYTHONPATH=src`
and the node runs as `PYTHONPATH=src:$PYTHONPATH python3 -m fieldguard_planning.avoidance_node`.
Promoting it to a proper ament package (for `ros2 run` + `colcon build`) is a documented follow-up. The
boustrophedon mission generator is still the standalone `scripts/gen_boustrophedon.py` (its output,
`config/missions/boustrophedon.waypoints`, is what the loop flies).
