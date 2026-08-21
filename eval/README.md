# Evaluation harness

Owned by `perception-ml-engineer` (with `devops-reliability-engineer` for CI).

Runs scripted scenarios headless and emits metrics — no "it works" without a number:
- detection precision / recall, **false-negative rate** (safety-critical)
- detection range / lead-time-to-collision
- avoidance success rate, coverage completeness
- single-NDVI vs second-sensor comparison-arm deltas (Weeks 5-6)

**What exists now:**
- `score.py` — the reusable metric core (precision / recall / **FNR** / per-bird-track FNR); the seed of
  the permanent harness. Run the full NDVI-vs-RGB spike with `run_spike.sh` (needs `requirements-eval.txt`).
- `label_from_sim.py`, `baseline_ndvi.py`, `baseline_rgb.py` — the ADR-003 spike pipeline, built on
  the shared `blob.py` (one classical-CV detector, used by both arms so the comparison is
  apples-to-apples) and `spike_common.py` (clip IO).
- `scenarios/` — the QA safety scenarios (spec + coverage-debt invariant); `generate_flight_logs.py`
  drives the real avoidance loop to produce each scenario's `flight_log.json`, activating its assertion.

`results/` is gitignored by default (`eval/results/*`), with explicit negations for the evidence
that must survive a clobber: `live_flight_log_*.json`, `gate2_summary.json`,
`testflight_gate_*.json`, `bird_drive_*.json`, and each recorded clip's `meta.json` / `poses.jsonl`
/ `heatmap/` / `INVALID_DO_NOT_USE.md` under `clips/real_flight_*/` — 54 files committed as of
2026-08-18. The `.npy` frame bulk and any other raw run output stay ignored; commit summary metrics
into reports, not raw frame data.

## Ground truth for real clips

The synthetic spike clips carry `birds[]` on every `poses.jsonl` line; a clip from the live
recorder (`src/fieldguard_planning/clip_recorder.py`) does not — nothing in the ROS 2 graph
publishes bird poses. It doesn't have to: the birds are deterministic. `scripts/drive_birds.py`
flies the committed `config/birds/farm_world_birds.json` waypoints on the **Gazebo sim clock**, and
every recorded pose line carries that frame's own gz stamp (`stamp_sim_s`), so a bird's position in
a frame is exactly `pose_at(stamp_sim_s - t0_sim)`.

```bash
# 1. the driver writes its anchor at startup (eval/results/bird_drive_<UTCstamp>.json)
python3 scripts/drive_birds.py                      # prints the sidecar path

# 2. after the flight, label the clip (writes poses_annotated.jsonl, recording untouched)
python3 eval/annotate_real_clip.py --clip eval/results/clips/<clip> \
    --sidecar eval/results/bird_drive_<UTCstamp>.json
# ... eyeball a line, then adopt it:
python3 eval/annotate_real_clip.py --clip <clip> --sidecar <same file> --in-place
```

`--bird-t0 <sim seconds>` replaces `--sidecar` for runs older than the sidecar (the driver's
`t0=...` console line). Labels are **commanded** bird poses, not observed ones (same rule as the
coverage ledger) — the render lags by one driver tick of sim time, ≈ `period x RTF`, which is
centimetres at this stack's measured RTF and ~1.2 m only if RTF ever reaches 1.

**Still open — annotated real clips are not yet scoreable.** `label_from_sim.py` was written for
the synthetic clip and needs two changes before it can turn one into `ground_truth.json`
(deliberately not made here; they belong to whoever runs the ADR-003 re-run):
1. it reads a per-frame `camera.pos_m`, which real clips don't record — derive it from
   `drone.pos_m`/`drone.quat_wxyz` + `meta.camera_extrinsic.offset_from_drone_m`
   (`ndvi_georef.camera_world_position` already does exactly this).
2. `spike_common.project_bird` hardcodes the spike's fixed nadir axes (image-right = East) and
   ignores camera orientation. A real AUTO mission yaws onto each boustrophedon leg, so on return
   legs every box would be mirrored about the principal point — wrong labels, not missing ones. Use
   the orientation-aware `ndvi_georef.world_enu_to_pixel` instead.
