# ROS 2 packages (colcon workspace `src/`)

Each FieldGuard ROS 2 package lives here as its own directory. Suggested packages (create as needed):
- `fieldguard_bringup` — launch files, params, top-level bringup
- `fieldguard_perception` — NDVI-frame detector + avoidance decision policy
- `fieldguard_planning` — boustrophedon coverage planner + coverage-debt replanning
- `fieldguard_control` — MAVLink/ArduPilot mission execution + avoidance executor
- `fieldguard_mapping` — NDVI georeferencing + heatmap stitching
- `fieldguard_msgs` — shared ROS 2 message/service/action definitions (the interface contracts)

Owned primarily by `flight-software-engineer` and `perception-ml-engineer`; interfaces by `tech-lead`.

## `fieldguard_planning/` (Week 2 start)

Started as the static-obstacle **geofence consumer** (`geofence.py`, ADR-001) + a QGC WPL mission
parser (`mission_waypoints.py`) — see `sim/README.md` "Static-obstacle geofence contract" for the
API and `tests/fieldguard_planning/` for tests. Deliberately **stdlib-only**, and **not yet a real
colcon package** (no `package.xml`/`setup.py`): it's pure logic, importable today via
`sys.path.insert(0, ".../src")` (see `scripts/check_mission_geofence.py`), and gets promoted to a
proper ament package when the Week 3-4 avoidance-loop ROS 2 nodes need it as an installed
dependency. The coverage planner itself (boustrophedon-as-a-ROS-2-node, coverage-debt tracking)
is still the Week 1 standalone `scripts/gen_boustrophedon.py` script — not yet ported in here.
