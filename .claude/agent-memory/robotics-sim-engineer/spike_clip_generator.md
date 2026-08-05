---
name: spike-clip-generator
description: Where the ADR-003 NDVI-vs-RGB synthetic spike clip generator lives, its schema/camera-convention decisions, and a waypoint-design gotcha worth remembering before scripting new actor trajectories.
metadata:
  type: project
---

Built 2026-08-04 for Week 2 workstream A (`docs/SPIKE_ndvi_vs_rgb.md` / ADR-003), when the real
Gazebo/ArduPilot/ROS 2 stack wasn't available in-session (it only runs in the human-run
Docker/Ubuntu container per [[macos_arm64_bringup_gotchas]]). Solution: a code-generated,
fixed-seed **synthetic stand-in** clip that emits the exact directory layout/schema a future
Gazebo NDVI-camera render should emit, so perception's harness (`eval/label_from_sim.py` etc.,
[[eval-harness-core]] if that memory exists) can be built now and swapped to a real render later
with ~zero downstream changes.

**Location**: `sim/spike/gen_spike_clip.py` (generator, numpy-only + a hand-rolled stdlib PNG
writer — no imageio/opencv dependency), `sim/spike/scenario_default.json` (data-driven bird
trajectories/field patches, matches the "config-driven, no code changes for new scenarios"
convention), `sim/spike/README.md` (full schema doc + the "assumptions the future Gazebo render
must honor to stay a drop-in" list), `sim/spike/sample/` (tiny 3-frame 160x120 fixture, committed
to git so the schema is inspectable without regenerating). `sim/spike/out/` (full clips) is
gitignored — regenerate locally with `python3 sim/spike/gen_spike_clip.py`.

**Key schema decisions** (documented in full in the README, don't relitigate without reading it
first):
- World frame = **ENU meters** (matches what AP_DDS/ROS 2 will publish per REP-103), explicitly
  NOT ArduPilot's internal NED — call this out any time raw MAVLink/SITL logs get compared
  against this clip's poses.
- Raw NDVI is `float32 .npy` in `[-1,1]` (maps 1:1 to a future `sensor_msgs/Image` 32FC1 topic);
  `ndvi_preview/*.png` is a false-color human-eyeball convenience only, never authoritative.
- Per-bird `generator_bbox_px`/`in_frustum_hint` in `poses.jsonl` are convenience cross-checks the
  generator computes itself — the authoritative GT projection is `eval/label_from_sim.py`'s job
  (perception's), from raw `birds[].pos_m` + camera intrinsics/extrinsics. Don't let a future
  generator silently become the source of truth for GT boxes; that ownership boundary was
  deliberate.
- Camera is nadir, fixed heading, no gimbal for this spike (matches "straight leg, no avoidance"
  scope) — rotation is a clean 180° about world X (quat `(0,1,0,0)`); `camera.quat_wxyz` is still
  emitted per-frame (not just once) so a future gimbaled camera doesn't require a schema change.

**Gotcha worth remembering when scripting new actor waypoints**: it's easy to place waypoints
that read as "crosses near X" in world coordinates but never actually enter the camera frustum,
because the *camera* is also moving (footprint dwell time is short — at 3 m/s groundspeed and a
15m altitude with a ~63° HFOV, the footprint is only ~18.5m wide and the camera dwells over a
given world-x for well under 3s). First pass at the ADR-003 spike's `bird_1` trajectory read as
plausible but never entered frame at all (u pixel coord was always >640) because the bird's x
crept ahead of the camera's x over its whole crossing window. Fix: for a transverse crossing,
hold the bird's x roughly constant near the camera's x *at the midpoint of the crossing window*,
and size the window so `|bird_x - cam_x|` stays under the footprint half-width for its whole
span — don't just eyeball it, compute `cam_x(t) = start_x + speed*t` at the window's start/end and
check the margin. Always spot-check a new scenario's `in_frustum_hint` counts per bird after
generating (a bird with zero visible frames is a silent, easy-to-miss failure) — see the
verification snippet pattern used in this session (load `poses.jsonl`, count
`in_frustum_hint: true` per `bird_id`).

**Dev-environment note**: this project's default `python3` (Homebrew 3.13) has no numpy installed.
Testing the generator requires a throwaway venv (`python3 -m venv ... && pip install numpy`) —
not part of the repo, just a session-local step to sanity-check output before committing.

How to apply: when asked to extend the spike clip (more birds, trees/occlusion, a gimbaled
camera) or to build the real Gazebo NDVI camera render that eventually replaces this, start from
`sim/spike/README.md`'s "Assumptions the future Gazebo render must honor" section rather than
re-deriving the schema from scratch.
