# NDVI-vs-RGB spike clip generator

Owner: `robotics-sim-engineer` · Consumer: `perception-ml-engineer` (`eval/label_from_sim.py`,
`eval/baseline_ndvi.py`, `eval/baseline_rgb.py`) · Resolves: `docs/SPIKE_ndvi_vs_rgb.md` / ADR-003.

## What this is (read this before using the output)

**This is a synthetic stand-in, NOT a Gazebo render.** The real Gazebo + `ardupilot_gazebo` +
ArduPilot SITL + ROS 2 stack only runs inside the human-operated Docker/Ubuntu container
(`docs/WEEK1_BRINGUP.md`), which was not available to generate this Week-2 deliverable. Rather than
block the perception spike on that, this script code-generates a clip that emits data in the
**exact directory layout and schema** the future Gazebo NDVI-camera render will emit — a drop-in
input for `eval/label_from_sim.py` today, swapped for the real render later with (ideally) zero
downstream changes. Every field/file below that only exists because of the synthetic approach is
called out explicitly in "Assumptions the future Gazebo render must honor."

Every output directory's `meta.json` has `"synthetic": true, "pending_gazebo_replacement": true` —
treat any clip without those fields, or with `false`, as the real render.

## Quick start

```bash
# Full default clip (30s @ 10fps, 640x480, seed 42) -> sim/spike/out/spike_seed42/
python3 sim/spike/gen_spike_clip.py

# Reproduce with an explicit seed / output dir
python3 sim/spike/gen_spike_clip.py --seed 42 --out sim/spike/out/spike_seed42

# Fast iteration: skip the (cheap but numerous) preview PNGs
python3 sim/spike/gen_spike_clip.py --no-previews

# Custom scenario file (same schema as scenario_default.json)
python3 sim/spike/gen_spike_clip.py --scenario path/to/scenario.json --out sim/spike/out/custom
```

Dependency: **numpy only**. PNG writing uses a ~40-line stdlib `zlib`/`struct` encoder (see
`write_png()` in `gen_spike_clip.py`) specifically so the eval harness doesn't need
imageio/opencv to stay headless-friendly.

Runtime: ~10-20s for the default clip on a laptop. Disk: the default clip is ~450MB (mostly the
raw float32 `.npy` NDVI frames) — `sim/spike/out/` is gitignored. A tiny **committed** fixture
(3 frames, 160x120) lives at `sim/spike/sample/` so the schema is inspectable without regenerating.

## Output layout

```
<out_dir>/
  meta.json            # run-level metadata: seed, fps, duration, camera intrinsics/extrinsics,
                        # coordinate frame convention, synthetic/pending-replacement flags
  scenario.json         # exact resolved scenario config used (birds, patches, field, flight) --
                        # the full reproducibility record, alongside the seed in meta.json
  poses.jsonl            # one JSON object per line, one per frame -- see schema below
  frames.csv              # flat per-frame index: frame_id,t_s,cam_x_m,cam_y_m,cam_z_m,ndvi_path,rgb_path
  frames/
    ndvi/frame_NNNNNN.npy         # AUTHORITATIVE: float32 (H,W), values in [-1,1]
    rgb/frame_NNNNNN.png           # AUTHORITATIVE: uint8 (H,W,3)
    ndvi_preview/frame_NNNNNN.png  # human-eyeball-only false-color NDVI visualization -- NOT
                                    # authoritative, do not label or score against it
```

## `poses.jsonl` schema (the ground-truth input `eval/label_from_sim.py` should consume)

One line = one JSON object per frame:

```jsonc
{
  "frame_id": 165,
  "t_s": 16.5,
  "drone": {
    "pos_m": [65.23, 20.84, 14.97],       // world ENU meters
    "quat_wxyz": [1.0, 0.0, 0.0, 0.0]      // constant heading-east this spike (straight leg)
  },
  "camera": {
    "pos_m": [65.23, 20.84, 14.97],        // rigid nadir mount, zero offset from drone this spike
    "quat_wxyz": [0.0, 1.0, 0.0, 0.0],     // world->camera fixed extrinsic, see "Camera model"
    "note": "rigid nadir mount, zero offset from drone origin in this spike"
  },
  "birds": [
    {
      "bird_id": "bird_1",
      "pos_m": [65.0, 20.84, 8.0],          // world ENU meters, bird actor position this frame
      "physical_radius_m": 0.15,             // wingspan-ish proxy used for apparent-size projection
      "ndvi_value": -0.08,                    // NDVI value this bird actor was rendered with
      "rgb_color": [195, 195, 200],            // RGB color this bird actor was rendered with
      "range_m": 6.91,                         // vertical camera-to-bird range (nadir camera => this IS the pinhole depth Zc)
      "in_frustum_hint": true,                  // convenience only, see note below
      "generator_bbox_px": [346.7, 165.3, 369.3, 187.9]  // convenience only, see note below
    }
  ],
  "ndvi_path": "frames/ndvi/frame_000165.npy",
  "rgb_path": "frames/rgb/frame_000165.png"
}
```

**Important — `in_frustum_hint` / `generator_bbox_px` are convenience cross-checks, not the
authoritative ground truth.** Per `docs/SPIKE_ndvi_vs_rgb.md` §3, `eval/label_from_sim.py` should
independently project `birds[].pos_m` through `camera` (pose + `meta.json`'s intrinsics) and
`drone` pose into `ground_truth.json` boxes. This generator's own bbox is exposed so you can
sanity-check your projection math against a second, independently-computed number — if they
disagree, that's worth investigating, not silently trusting either one. A bird is **absent from
the `birds` list entirely** in frames outside its scripted waypoint window (not spawned yet /
already despawned), which is different from `in_frustum_hint: false` (spawned but out of the
camera's view this frame).

Only `birds[].pos_m`, `physical_radius_m`, `camera.pos_m`, `camera.quat_wxyz`, and
`meta.json`'s `camera` intrinsics block are required to independently reproduce ground truth —
everything else is convenience.

## Camera model (pinhole, fixed nadir extrinsic)

- **Mount**: rigid, no gimbal, constant for the whole clip (matches the "straight leg, no
  avoidance" spike scope). A future gimbaled camera would need `camera.quat_wxyz` to vary per
  frame — the field already exists per-frame in `poses.jsonl` for that reason, even though it's
  constant here.
- **World frame**: ENU, meters (x=East, y=North, z=Up) — REP-103 convention, matching what the
  AP_DDS ROS 2 bridge publishes, **not** ArduPilot's internal NED. This is the one thing most
  likely to bite you if you cross-reference raw MAVLink/SITL logs, which are NED.
- **Camera axes, expressed in world coordinates** (this is the world->camera rotation, i.e. each
  row of the rotation matrix):
  - camera **X** (image right, `u+`) = world **+X** (East)
  - camera **Y** (image down, `v+`) = world **−Y** (South)
  - camera **Z** (optical/depth axis, forward) = world **−Z** (Down)
  - This is a proper right-handed rotation (180° about world X) = quaternion `(w,x,y,z) = (0,1,0,0)`.
  - Net effect: as the drone flies east, ground features drift from image-right toward
    image-left; "up" in the image corresponds to world North.
- **Projection**: standard pinhole/OpenCV convention. For a world point relative to the camera,
  `rel = P_world - cam_pos`: `Xc = rel.x`, `Yc = -rel.y`, `Zc = -rel.z`, then
  `u = fx*Xc/Zc + cx`, `v = fy*Yc/Zc + cy`. `Zc` is the depth used both for projection and for
  apparent-radius scaling (`r_px = fx * physical_radius_m / Zc`).
- **Intrinsics** (default scenario): `fx=fy=520px`, `cx=320, cy=240`, `640x480` → ~63°
  horizontal FOV. Defined once in `meta.json["camera"]`.

## Scenario config (`scenario_default.json`)

Data-driven, no code changes needed to add scenarios (per `CLAUDE.md` convention) — pass
`--scenario path/to/file.json`. Fields:
- `seed`, `duration_s`, `fps` — reproducibility knobs (all overridable via CLI flags).
- `camera` — intrinsics + output resolution.
- `flight` — straight-leg altitude/start/heading/speed + a small reproducible position jitter
  (Gaussian, seeded) standing in for SITL telemetry noise.
- `field` — world extent (meters) + ground-texture sampling resolution (`gsd_m_per_px`).
- `ndvi_background` — `canopy_base`/`canopy_noise_std` plus three feature classes, each a list of
  world-space circular patches with a soft-feathered edge:
  - `soil_patches` — bare ground, low NDVI, high RGB brightness/brown — the false-negative hard
    case when a bird crosses one.
  - `shadow_patches` — moderate NDVI depression relative to canopy, not as low as soil.
  - `clutter_blobs` — small, bird-blob-sized, static low-NDVI ground features that are **not**
    birds — the false-positive hard case for a naive NDVI threshold.
- `birds` — 3 scripted actors (matches MVP 2-3 bird scope), each a `bird_id`, rendered
  `ndvi_value`/`rgb_color`/`physical_radius_m`, and a **piecewise-linear waypoint list**
  (`t_s, x_m, y_m, z_m`). A bird only appears in a frame's `birds[]` list while `t_s` is within
  its own waypoint time window (birds spawn/despawn, they aren't present for the whole clip).

### The three scripted birds and what each is designed to test

| bird | crossing window | range (below camera) | background it crosses | tests |
|---|---|---|---|---|
| `bird_0` | ~4.9–6.5s | ~10m | clean canopy | sanity baseline — both (a) and (b) should catch this |
| `bird_1` | ~16.1–17.2s | ~7m (closest) | dead-center of `soil_0` (NDVI ~0.15 vs bird ~-0.08 — low contrast) | **the false-negative hard case** the spike exists to test for approach (a) |
| `bird_2` | ~24.8–27.2s | ~13m (farthest, smallest blob) | clean canopy, passes ~2.4m from `clutter_0` (never overlapping) | range sensitivity + bird-vs-static-clutter discrimination (only motion distinguishes them) |

Verified (see generation checks below): `bird_1`'s minimum distance to `soil_0`'s center is
0.28m (i.e. it flies essentially through the patch center, confirmed background NDVI directly
under it ≈0.15 vs. the bird's own -0.08 — a genuinely low-contrast case, not just nominally
inside the patch radius). `bird_2`'s minimum distance to `clutter_0` is 2.4m, safely outside the
patch's feathered radius (1.4m) — confirmed non-overlapping.

## Assumptions the future Gazebo render must honor to stay a drop-in replacement

If/when the real Gazebo NDVI camera render replaces this generator, it must preserve:
1. **Directory layout and file names** above (`frames/ndvi/*.npy` float32 [-1,1],
   `frames/rgb/*.png` uint8, `poses.jsonl`, `meta.json`, `frames.csv`) — or `eval/label_from_sim.py`
   needs a path-mapping shim.
2. **World frame = ENU meters**, not ArduPilot NED. If Gazebo/AP_DDS gives NED or a different
   local frame, convert at the boundary — don't change `eval/`'s assumed frame.
3. **The camera axis convention** in "Camera model" above (X=East, Y=South, Z=Down when nadir) —
   or update `meta.json["camera_extrinsic"]` to whatever the real mount is and make sure
   `eval/label_from_sim.py` reads the convention from `meta.json` rather than hardcoding it.
4. **Same NDVI formula and range**: `(NIR-Red)/(NIR+Red)`, clipped to `[-1,1]`, float32. This
   generator fabricates plausible values directly; the real render must compute them from actual
   Red+NIR passes (per `CLAUDE.md` sensor architecture) but should land in the same range/dtype.
5. **`in_frustum_hint`/`generator_bbox_px` become optional/removed** once real projection is done
   by `label_from_sim.py` against real camera intrinsics from the Gazebo sensor plugin — they're
   scaffolding for this synthetic clip, not a contract the real render must implement.
6. **Occlusion is out of scope for this spike either way** — this generator only checks the
   camera frustum, not true 3D occlusion (no static obstacles in this scenario, matching ADR-001 /
   `docs/SPIKE_ndvi_vs_rgb.md`'s explicit "no trees needed" scoping). If a future scenario adds
   trees/occluders, both the real render's visibility computation and any updated generator need
   to add real occlusion — flagged here so it isn't silently assumed away later.
7. **Fixed-seed reproducibility**: same seed -> byte-identical output. If the real render adds
   its own sources of nondeterminism (physics substeps, render order), pin/seed those too so eval
   numbers stay comparable run-over-run — this is the whole point of doing the spike in sim.

## Regenerating the checked-in sample

```bash
python3 sim/spike/gen_spike_clip.py --duration 1.5 --fps 2 --width 160 --height 120 \
  --out sim/spike/sample
```

Kept intentionally tiny (3 frames, 160x120, ~350KB) — it's a schema fixture, not a usable eval
clip. Use the full default clip (`sim/spike/out/spike_seed42/`, gitignored, regenerate locally)
for the actual ADR-003 spike run.
