# Gazebo simulation assets

Owned by `robotics-sim-engineer`. Scenario parameters are data-driven (`config/`) so scenarios can
be added without code changes — see [Regenerating the world](#regenerating-the-world).

- `worlds/farmguard_field.sdf` — the custom farm world: bounded field polygon (green ground plane),
  3 orchard tree rows (18 trees, static/geofenced obstacles), 3 birds as **static models** driven
  at runtime by `scripts/drive_birds.py` (dynamic obstacles, ADR-012 — SDF `<actor>`s never entered
  the ogre2 render scene), the `iris_with_gimbal` vehicle, and (ADR-007) the dual-band NDVI sensor
  mount (`iris_with_gimbal_ndvi`) plus a calibrated `<temperature>` on every visual in the world.
  **Generated** by `scripts/gen_farm_world.py` — don't hand-edit; edit the `config/` inputs below
  and regenerate.
- `bridge/fg_sensor_bridge.yaml` — ros_gz_bridge config for the four `/fg/sensor/*` topics
  (ADR-007), and deliberately only those: Gazebo's `/clock` runs at ~350 msg/s and bridging it
  starved the image pipeline, so the recorder reads the sim clock natively over gz-transport
  instead. See `docs/runbooks/NDVI_VALIDATION.md` Gate 1.
- `models/` — reserved for future mesh/model assets. Still empty: the farm world (including the
  Week 5-6 NDVI sensor mount) uses only inline SDF primitives + first-class Gazebo sensor types, no
  external meshes, so it has no dependency on this directory or on `GZ_SIM_RESOURCE_PATH` beyond
  what `ardupilot_gazebo` already requires (see docs/runbooks/SIM_BRINGUP.md §5) — a deliberate choice to
  avoid adding new resource-path risk.
- `spike/` — the ADR-003 NDVI-vs-RGB spike clip generator (separate concern, see `spike/README.md`).
- `docker/` — the Week 1 starter container (see `docs/runbooks/SIM_BRINGUP.md`).

## The farm world's config-driven inputs

| File | What it defines | Consumed by |
|---|---|---|
| `config/field_polygon.json` | field boundary (home lat/lon, ENU polygon), mission altitude | `scripts/gen_boustrophedon.py` (mission) and `scripts/gen_farm_world.py` (world) — **the reason both stay geometrically consistent** |
| `config/static_obstacles.json` | tree row layout (input) + the flattened per-tree obstacle list (generated output) | `scripts/gen_farm_world.py` (world); **flight-software's geofence/planner** (see contract below) |
| `config/birds/farm_world_birds.json` | 3 scripted bird trajectories (piecewise-linear waypoints, there-and-back loops), replayed at runtime by `scripts/drive_birds.py` (ADR-012) | `scripts/gen_farm_world.py` (world) |
| `config/ndvi_camera.json` | ADR-007 dual-band NDVI sensor mount: intrinsics/rate, the sensor-mount attachment (parent link + pose), and the per-material-class `<temperature>` calibration table | `scripts/gen_farm_world.py` (world); `scripts/check_ndvi_bands.py` (Gate 2 smoke test) |

## NDVI sensor topics (ADR-007, Weeks 5-6)

Locked contract, `docs/DECISIONS.md` ADR-007 — **confirmed live 2026-08-18** (Gates 0-3;
`docs/runbooks/NDVI_VALIDATION.md`):

- `/fg/sensor/rgb/image` (`rgb8`) + `/fg/sensor/rgb/camera_info` — Red band; also the ADR-003
  NDVI+RGB comparison arm.
- `/fg/sensor/nir/image` (`mono16`) + `/fg/sensor/nir/camera_info` — Gazebo's thermal sensor
  repurposed as synthetic NIR, per-visual `<temperature>` authored from `config/ndvi_camera.json`.
- `/fg/ndvi/image` (`32FC1`, authoritative) + `/fg/ndvi/camera_info` + `/fg/ndvi/preview` (`rgb8`,
  human-only) — published by `src/fieldguard_planning/ndvi_node.py` over the tested
  `ndvi_fusion.py` core; ran live for a full flight 2026-08-18.

Bridge these four topics with `sim/bridge/fg_sensor_bridge.yaml`
(`ros2 run ros_gz_bridge parameter_bridge --ros-args -p config_file:=sim/bridge/fg_sensor_bridge.yaml`).
Validate with `scripts/check_ndvi_bands.py` — see `docs/runbooks/NDVI_VALIDATION.md` Gate 2.

### Regenerating the world

```bash
python3 scripts/gen_farm_world.py
```

Reads the three files above, rewrites `config/static_obstacles.json`'s `obstacles` array (computed
fresh from its own `layout` section) and `sim/worlds/farmguard_field.sdf` **in the same run**, so
the geofence export and the Gazebo world can never drift apart — there is exactly one place
(`scripts/gen_farm_world.py:compute_obstacles`) that turns tree-row layout into tree positions.
The script also checks the output SDF is well-formed XML before writing it (`xml.etree`) and that
every computed tree position falls inside the field polygon (raises if not). Change tree rows, add
a 4th bird, or resize the field by editing the `config/` inputs and rerunning — no code changes.

## Static-obstacle geofence contract (for `flight-software-engineer`)

**File**: `config/static_obstacles.json`, `obstacles` array. **Frame**: local ENU meters (x=East,
y=North, z=Up), origin = `config/field_polygon.json`'s `home_lat`/`home_lon` — same convention as
`sim/spike/README.md`. Per ADR-001 (`docs/DECISIONS.md`), these are **known static obstacles from a
pre-flight boundary survey** — geofence against them directly, do not run detection on them; the
runtime perception/avoidance loop is reserved for the birds (genuinely unplanned dynamic
obstacles).

Each entry:
```jsonc
{
  "id": "tree_row0_0",          // stable, unique
  "type": "tree",
  "row_id": 0,
  "pos_m": [15.0, 5.0, 0.0],     // ENU meters, ground-level (x,y,z=0)
  "obstacle_radius_m": 2.0,       // USE THIS for geofence exclusion (canopy radius + safety margin)
  "canopy_radius_m": 1.3,          // Gazebo collision/visual geometry only, not the geofence radius
  "height_m": 3.5                   // approximate total tree height (trunk + canopy), not a tight bbox
}
```
Read `obstacle_radius_m` for the exclusion radius, not `canopy_radius_m` — the latter is what the
Gazebo model's collision sphere actually uses, the former already includes a safety margin on top.
Tree height (3.5m) is well below `config/field_polygon.json`'s `mission_altitude_m` (15m), so the
existing boustrophedon mission physically clears every tree — this is why "the mission flies through
the world" held even before the avoidance loop existed. (The reactive-avoidance loop is now built and
demonstrated live — see `docs/runbooks/AVOIDANCE_DEMO.md`; it adds its own 3D safety gate on top of this
geofence for dodge maneuvers that may leave cruise altitude, `geofence.is_safe_3d`.)

**Consumer implementation (Week 2, `flight-software-engineer`):** `src/fieldguard_planning/geofence.py`
loads this file and exposes `GeofenceMap.from_file(...)` with `is_point_excluded(x, y)`,
`excluding_obstacle(x, y)`, `point_clearance(x, y)`, and `segment_clearance(p1, p2)` /
`check_path(points)` for mission-leg (not just point) checks — see that module's docstring and
`tests/fieldguard_planning/test_geofence.py`. Stdlib-only on purpose so the whole avoidance loop that
now consumes it (`avoidance_policy.py`, `avoidance_executor.py`) stays unit-testable without a ROS 2 /
Gazebo dependency just to ask "is this point a known tree." Still not packaged as a colcon package (no
`package.xml`); the live ROS 2 node runs via `python3 -m fieldguard_planning.avoidance_node` — colcon
packaging (for `ros2 run`) is a documented follow-up.

## Frame conventions (must match across the project)

Same as `sim/spike/README.md`: **world ENU meters** (x=East, y=North, z=Up), matching REP-103 /
what the AP_DDS ROS 2 bridge publishes — not ArduPilot's internal NED. The world's
`spherical_coordinates` (lat/lon/elevation) is identical to `ardupilot_gz`'s stock `iris_runway.sdf`
and to `config/field_polygon.json`'s `home_lat`/`home_lon`, so `(0,0)` in this ENU frame is both the
SITL home and the field polygon's SW corner — no offset to track between the mission, the world, and
the obstacle export.

## Launching the world (human, inside the Docker container — see `docs/runbooks/SIM_BRINGUP.md`)

**Quick start:** `scripts/run_farm_mission.sh` (run inside the container) packages Shell A below
into one command and prints the exact Shell B recipe — added by `flight-software-engineer` in Week
2 as the mission-through-world launch helper, not a new launch path (see that script's header
comment for why Shell B stays manual). The manual two-shell flow below is still the documented
ground truth if you want to run it by hand or the script needs debugging.

Follow the same **two-shell flow** already proven for `iris_runway.sdf` in
`docs/runbooks/SIM_BRINGUP.md` §5-6, just pointing at this world file directly instead of relying on a ROS
2 launch file (`ardupilot_gz_bringup`'s launch files hardcode their own world path internally, so
they can't point at a custom world without editing them — the two-shell flow sidesteps that and is
also what docs/runbooks/SIM_BRINGUP.md already recommends as the more debuggable default):

```bash
# Shell A — start the world and leave it running:
source /root/ardu_ws/install/setup.bash
export GZ_SIM_RESOURCE_PATH="$GZ_SIM_RESOURCE_PATH:/root/ardu_ws/install/ardupilot_gazebo/share"
gz sim -v4 -s -r --headless-rendering /workspace/fieldguard/sim/worlds/farmguard_field.sdf
```

**Verify:** the world stays up — no `Unable to find uri` / `Failed to load a world` (the same
failure modes docs/runbooks/SIM_BRINGUP.md §5 already documents for `iris_runway.sdf`; this world only adds
inline primitives + one `model://iris_with_gimbal` include, so if it fails, it's almost certainly
the same `GZ_SIM_RESOURCE_PATH` issue, not something new). `gz topic -l | grep model/tree_row0_0`
or `gz model -m tree_row0_0 -p` (Gazebo Harmonic CLI) confirm a tree loaded where expected.
**Birds (ADR-012):** the 3 birds are static models moved by `scripts/drive_birds.py` (run it in
its own shell whenever a flight needs visible moving birds — Gate 2, recordings). Confirm they
render: `gz service -s /world/farmguard_field/scene/info --reqtype gz.msgs.Empty --reptype
gz.msgs.Scene --timeout 3000 --req "" | grep -c bird` → expect > 0 (was 0 in the actor era);
confirm motion (driver running) via the bird's entry changing in
`gz topic -e -t /world/farmguard_field/pose/info -n 1` between calls — NOTE `scene/info` caches
spawn poses and `dynamic_pose/info` excludes static models; `pose/info` is the live one.

```bash
# Shell B — SITL, wired to Gazebo (identical to docs/runbooks/SIM_BRINGUP.md §6 -- vehicle model/pose is the
# same iris_with_gimbal at the same spawn pose, so nothing about the SITL side changes).
# --enable-DDS + the param file are LOAD-BEARING (bringup bug #6): SITL builds DDS OUT by default,
# so without them this recipe silently produces ZERO /ap topics and everything downstream starves:
cd /root/ardu_ws/src/ardupilot
export PATH="$PWD/Tools/autotest:$PATH"
sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --enable-DDS \
  --add-param-file=/workspace/fieldguard/config/sitl_params/dds_udp.parm
```

Then fly the existing mission exactly as in `docs/runbooks/SIM_BRINGUP.md` §8 (`wp load
/workspace/fieldguard/config/missions/boustrophedon.waypoints`, `mode auto`, `arm throttle`) — no
mission regeneration needed, since `config/field_polygon.json` (and therefore this world) matches
the polygon that mission already sweeps.

## What's been validated statically vs. what still needs a human Docker run

Validated in this (non-Docker) session:
- `sim/worlds/farmguard_field.sdf` is well-formed XML (`xml.etree.ElementTree`, cross-checked with
  `xmllint --noout`).
- Structural sanity: 23 `<model>` elements (1 ground plane + 18 trees + 3 birds + 1
  `iris_with_gimbal_ndvi` vehicle/sensor-mount wrapper), **0 `<actor>` elements** (ADR-012), no
  duplicate model names, and exactly 40 per-visual `gz::sim::systems::Thermal` plugins (1 ground +
  18×2 tree trunk/canopy + 3 birds — every visual in the world, ADR-007).
- Every computed tree position falls inside `config/field_polygon.json`'s polygon (generator
  raises otherwise).
- `config/static_obstacles.json`'s `obstacles` array numerically matches the tree `<pose>` values
  actually written into the SDF (both come from the same in-memory list in one generator run).
- World-level plugins, `spherical_coordinates`, and the vehicle `<include>`/pose are copied
  verbatim from `ardupilot_gz`'s own `iris_runway.sdf`/`iris_with_gimbal` model (fetched and
  diffed against upstream during this session) — not hand-guessed.
- **(Week 2, `flight-software-engineer`)** The mission's flight path checked numerically against
  the geofence export with `scripts/check_mission_geofence.py` (uses the new
  `src/fieldguard_planning/geofence.py` + `mission_waypoints.py`, stdlib-only, no Docker needed):
  the mission regenerates byte-for-byte from the checked-in `config/` inputs (confirmed unchanged),
  and **in the XY plane** the return leg of lane x=15 runs directly along tree row 0's centerline
  (min clearance **-2.0 m**, i.e. 0 m lateral separation minus the 2.0 m `obstacle_radius_m`) —
  every other leg clears by ≥3.0 m. This is expected and safe *only* because of the ≥11.5 m
  vertical separation (15 m mission altitude − 3.5 m tree height); see
  `docs/runbooks/SIM_BRINGUP.md`-style framing above. Flagged for Week 3-4: tree row 0 is already primed
  to be the "always-clips-in-XY" case if avoidance work later needs a forced dodge scenario
  (lower altitude / taller trees), whereas rows 1-2 sit 3-8 m off every lane by design.

**Now validated live** (2026-08-05 Week-3 gates, `docs/archive/WEEK3_VALIDATION.md`; 2026-08-18
NDVI gates, `docs/runbooks/NDVI_VALIDATION.md`): `gz sim` loads this SDF end-to-end, the
boustrophedon mission flies it without physics surprises, and the thermal/NDVI sensor mount works
(Gate 0 loads on pinned Harmonic+ogre2, Gate 2 reads canopy 0.854 > soil 0.212 > bird 0.040).

**Still unvalidated:**
- Render/performance headroom is confirmed *poor but workable*: the software-rendered path runs at
  RTF ≈ 0.2 and stalls-and-bursts (instantaneous RTF 0.0016–0.48), which is why frame↔pose pairing
  is stamp-based (ADR-007 amendment 2).
- **(ADR-007)** Everything about the dual-band NDVI sensor mount: whether
  `gz-sim-thermal-system`/`gz-sim-thermal-sensor-system` actually load on this pinned Harmonic +
  ogre2 build, whether the `iris_with_gimbal_ndvi` wrapper model's fixed-joint sensor-mount
  attachment resolves, and whether the per-visual `<temperature>` calibration produces genuinely
  different canopy/soil/bird readings. This is a **separate, dedicated gate** —
  `docs/runbooks/NDVI_VALIDATION.md` — not folded into the two-shell flow above.

**Status (2026-08-18):** done. The world flies, the ADR-007 gates are green, and a full flight has
been recorded end to end — `docs/runbooks/FULL_PIPELINE_DEMO.md` is the current showpiece recipe (7
shells: Gazebo, bridge, agent, SITL, birds, fusion node, recorder). The only live-verification debt
left is the ADR-003 scored re-run on a real clip; see `docs/ROADMAP.md`.
