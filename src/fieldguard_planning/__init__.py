"""fieldguard_planning -- coverage planning + geofence consumer.

Week 2 scope: the static-obstacle geofence consumer (`geofence.py`) and a QGC WPL mission-file
parser (`mission_waypoints.py`) used to sanity-check the boustrophedon mission against
`config/static_obstacles.json`. Both modules are stdlib-only on purpose (see
`src/fieldguard_planning/geofence.py` module docstring) so they're testable without a ROS 2 /
colcon environment.

This is not yet wired up as a proper ament/colcon ROS 2 package (no `package.xml` / `setup.py`) --
that lands when the Week 3-4 avoidance-loop ROS 2 nodes need it as an installed dependency. Until
then, import it by adding `src/` to `sys.path` (see `scripts/check_mission_geofence.py` and
`tests/fieldguard_planning/` for the pattern).
"""
