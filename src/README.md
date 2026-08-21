# ROS 2 packages (colcon workspace `src/`)

**Actual structure:** the reactive-avoidance loop (Weeks 1-4) **and** the NDVI fusion / georeference
/ recording pipeline (Weeks 5-6) consolidated into a single package, `fieldguard_planning/` (below)
— decision policy, executor, geofence, coverage, and the ROS 2 adapter
all live there, kept pure-Python so they unit-test without a ROS 2 environment. The original plan was to
split these across separate ament packages (`fieldguard_perception` for the detector/policy,
`fieldguard_control` for the executor, `fieldguard_mapping` for NDVI georeferencing, `fieldguard_msgs`
for interface contracts, `fieldguard_bringup` for launch files); that split remains a reasonable future
refactor once the modules are promoted to colcon packages, but was not needed to demonstrate the loop.

Owned primarily by `flight-software-engineer` and `perception-ml-engineer`; interfaces by `tech-lead`.

## `fieldguard_planning/` — the reactive-avoidance core (Weeks 2–4, DONE)

The whole avoidance loop lives here, deliberately **stdlib-only** so it is unit-testable on a bare
interpreter with no sim/ROS 2 (see `tests/README.md` for how to run the suite). **One documented
exception (ADR-007 follow-up 7):** the NDVI image-math modules (`ndvi_fusion.py`, `ndvi_georef.py`,
and the recorder that feeds them) may use **numpy** — genuine array math, already a project
dependency via `requirements-eval.txt`. The planning/avoidance core stays pure stdlib.

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

## The NDVI pipeline (Weeks 5-6, ADR-007/ADR-010) — ran live 2026-08-18

Same discipline as the avoidance loop: testable math in a pure module, a thin rclpy binding on top.

- `ndvi_fusion.py` (numpy) — the fusion core: pairs Red↔NIR by stamp, enforces the ADR-007 stale-pair
  guard (25% of a frame period; a violating pair is dropped and counted, never fused), rescales both
  bands and computes NDVI = (NIR−Red)/(NIR+Red).
- `ndvi_node.py` — the rclpy binding: `/fg/sensor/{rgb,nir}/image` → `ApproximateTimeSynchronizer` →
  `/fg/ndvi/image` (`32FC1`, authoritative) + `camera_info` + `preview`.
- `ndvi_georef.py` (numpy) — **the load-bearing seam**: NDVI pixel → camera ray → body → world-ENU →
  canonical grid cell. A sign or frame error here yields a plausible-but-wrong map, so it was built
  test-first against hand-computed fixtures in `test_ndvi_georef.py` — read those alongside the module.
- `clip_recorder.py` — the pure clip writer: emits the `sim/spike/README.md` schema from live flight
  data, owning the wxyz↔xyzw quaternion conversion and the gz-clock stamp pairing in exactly one place each.
- `record_node.py` — the rclpy recorder: subscribes NDVI + RGB + pose + GPS origin and writes a real
  clip (`synthetic: false`) that `stitch_ndvi.py` and `eval/run_spike.sh` consume unchanged.

**Not yet a colcon package** (no `package.xml`/`setup.py`): the pure modules import via `PYTHONPATH=src`
and the node runs as `PYTHONPATH=src:$PYTHONPATH python3 -m fieldguard_planning.avoidance_node`.
Promoting it to a proper ament package (for `ros2 run` + `colcon build`) is a documented follow-up. The
boustrophedon mission generator is still the standalone `scripts/gen_boustrophedon.py` (its output,
`config/missions/boustrophedon.waypoints`, is what the loop flies).
