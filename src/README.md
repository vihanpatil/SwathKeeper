# ROS 2 packages (colcon workspace `src/`)

Each FieldGuard ROS 2 package lives here as its own directory. Suggested packages (create as needed):
- `fieldguard_bringup` — launch files, params, top-level bringup
- `fieldguard_perception` — NDVI-frame detector + avoidance decision policy
- `fieldguard_planning` — boustrophedon coverage planner + coverage-debt replanning
- `fieldguard_control` — MAVLink/ArduPilot mission execution + avoidance executor
- `fieldguard_mapping` — NDVI georeferencing + heatmap stitching
- `fieldguard_msgs` — shared ROS 2 message/service/action definitions (the interface contracts)

Owned primarily by `flight-software-engineer` and `perception-ml-engineer`; interfaces by `tech-lead`.
