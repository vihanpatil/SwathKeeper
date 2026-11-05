---
name: farm-world-layout
description: Where the Week 2 farm world (sim/worlds/farmguard_field.sdf) and its config-driven inputs live, the generator pattern that keeps the Gazebo world and the ADR-001 geofence export in sync, and SDF gotchas discovered while authoring it (comment double-hyphens, actor trajectory syntax).
metadata:
  type: project
---

Built 2026-08-04 for Week 2 workstream C (custom farm world: field polygon, orchard tree rows as
ADR-001 known-static-obstacles, 2-3 scripted bird actors as dynamic obstacles). Same
environment-honesty situation as [[spike_clip_generator]]: the real `gz sim` parser only runs in the
human-operated Docker container, so everything here was validated for XML well-formedness and
structural/numeric consistency, but not by actually loading in Gazebo. See
`sim/README.md`'s "What's been validated statically vs. what still needs a human Docker run" for the
full breakdown — keep that section current if this world changes.

**Generator pattern** (same spirit as the spike's config→generator→artifact pattern): a single
script, `scripts/gen_farm_world.py`, reads `config/field_polygon.json` + `config/static_obstacles.json`
(hand-authored `layout` section: row x-positions, y start/end/spacing, tree geometry defaults) +
`config/birds/farm_world_birds.json`, and in **one run** both (a) rewrites
`config/static_obstacles.json`'s `obstacles` array and (b) emits matching tree `<model>` blocks in
`sim/worlds/farmguard_field.sdf` — from the same in-memory list, so the geofence export (the
contract flight-software consumes) and the actual Gazebo world can never drift apart. Don't
hand-edit `sim/worlds/farmguard_field.sdf` or `config/static_obstacles.json`'s `obstacles` array
directly; edit `layout`/`tree_defaults`/`config/birds/farm_world_birds.json` and rerun.

**Key design decision — trees are short, mission flies high, so "the mission flies through it"
holds today with zero avoidance logic**: tree canopy height is 3.5m (`trunk_height_m` +
`canopy_height_m` in `static_obstacles.json`'s `tree_defaults`), while the existing boustrophedon
mission flies at 15m (`config/field_polygon.json`'s `mission_altitude_m`) — >11m clearance. This is
what makes Week 2's exit criteria simultaneously satisfiable: trees present as real, geofenced,
collidable Gazebo obstacles AND the dumb, no-obstacle-awareness Week-1 mission still completes
without a physics collision. If a future scenario needs the mission to actually have to avoid a
tree, this margin needs to shrink deliberately (lower mission altitude or taller trees) — don't
let that regress by accident when tuning either config.

**SDF gotchas hit while writing this** (both were "well-formed XML" failures caught by the
generator's own `xml.etree.ElementTree.fromstring` validation step, not by a Docker run):
- **XML comments cannot contain a literal `--` anywhere**, including inside prose like "iris_runway
  .sdf's -- this exact ...". Any `<!-- ... -->` content written in these generators must use a
  single hyphen or different punctuation, not em-dash-style double hyphens. Bit me immediately on
  the first generation attempt; worth checking first if a future SDF-generating script throws a
  `ParseError: not well-formed (invalid token)` on a comment line.
- **Gazebo (Harmonic) `<actor>` elements do NOT need a `<skin>`/mesh** to move along a scripted
  `<script><trajectory><waypoint>` path — a plain `<link><visual><geometry><sphere>...` works fine,
  confirmed against `gz-sim`'s own `examples/worlds/actor.sdf` and the Harmonic actors doc (both
  fetched live this session, not from training-data memory, since this detail is easy to get wrong
  from general Gazebo-classic knowledge). No plugin needed either — `auto_start: true` is
  sufficient. Actors don't physically collide in gz-sim's actor system (a gz-sim limitation, not a
  choice) — fine for this MVP since birds are meant for the future NDVI-camera detection loop, not
  Gazebo physics collision.

**World-level plugin set, `spherical_coordinates`, and the vehicle `<include>`/pose were copied
verbatim from `ardupilot_gz`'s own `iris_runway.sdf`/`iris_with_gimbal` model** (fetched from
GitHub this session — `ardupilot_gazebo`/`ardupilot_gz` repos aren't vendored locally, only
`vcs import`-ed inside the human's Docker container) rather than hand-reconstructed from memory —
deliberately, since that exact combination is the one already proven to load per
`docs/runbooks/SIM_BRINGUP.md` §5-6, and reinventing it risks reopening the "world fails to load" class of
bug that doc already fought through once. If `ardupilot_gz` upstream changes that world file
significantly, re-diff before assuming this one still matches.

File locations: `config/field_polygon.json` (field boundary, shared with
`scripts/gen_boustrophedon.py`), `config/static_obstacles.json` (tree layout input + generated
geofence export — the flight-software contract, schema documented in `sim/README.md`),
`config/birds/farm_world_birds.json` (bird trajectories), `scripts/gen_farm_world.py` (the
generator), `sim/worlds/farmguard_field.sdf` (output, committed).

How to apply: when extending the farm world (more trees, a 4th bird, a smaller/larger field), edit
the `config/` inputs and rerun `python3 scripts/gen_farm_world.py` — don't hand-edit the SDF or the
obstacles array. When asked to build the actual NDVI camera sensor or reactive avoidance (Week
3-4/5-6), this world is the base to extend, and `sim/models/` is still empty/reserved for that.
