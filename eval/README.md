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
  apples-to-apples) and `spike_common.py` (clip IO). **`baseline_ndvi.py`'s threshold is per-render**
  and resolved from the clip's own `meta.json`: `0.05` on a synthetic clip (ADR-003's deciding value),
  `-0.61` on a real Gazebo render (the gate2 bird/soil midpoint — real soil reads −0.4377, where 0.05
  masks the whole image). The real-render value is PROVISIONAL until a clip exists with a bird in
  frame; ADR-003 amendment 3. Before flying for one, run
  `scripts/predict_bird_visibility.py` — it says whether the mission can produce one at all.
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

Frames recorded **before** the driver started (the recorder always starts first) label at each
bird's **spawn pose** — the `waypoints[0]` the static model sits at until the first `set_pose`, so
they are ground truth, not filler (ADR-012 amendment 1). Their `traj_t_s` stays negative as
provenance, and the annotator prints how long that lead-in was: if it is longer than the gap you
actually left between recorder and driver, you are holding the wrong sidecar. Frames recorded after
the driver **exits** are the one case still undetectable — the sidecar records a start, not a stop.

**Real clips ARE scoreable (both blockers closed).** This section listed two `label_from_sim.py`
gaps as open; both were implemented before the 2026-08-21 re-run and the list had gone stale.
`build_ground_truth` now derives the camera position from `drone.pos_m`/`drone.quat_wxyz` +
`meta.camera_extrinsic.offset_from_drone_m` (`ndvi_georef.camera_world_position`), and
`project_bird_oriented` replaces the spike's fixed nadir axes with the orientation-aware
`ndvi_georef` primitives — so a yawed return leg no longer mirrors every box about the principal
point. The synthetic clip keeps the legacy fixed-extrinsic path, selected per line by whether it
carries a `camera.pos_m`. Verified 2026-08-21: 454/454 frames of the demo take labelled, 0 refused,
projection hand-checked (a bird 5 m below a level hover lands on the principal point (320.0, 240.0);
2 m East at 4.92 m depth lands at u = 531.38 = 320 + 520·2/4.92).

**Still open — what a real clip needs before its numbers mean anything** (all three found on the
2026-08-21 re-run, which produced **zero** scoreable bird-frames; see ADR-003 criterion 3):
1. **A clip with a bird in frame at all.** As flown, nadir at 15 m over birds at 6/8/11 m AGL gave a
   footprint of 4.9×3.7 to 11.1×8.3 m at bird altitude against a **15 m** boustrophedon lane pitch —
   the ground plane tiles, the bird-altitude plane does not. **The geometry half is fixed
   (ADR-015):** bird_0 now patrols *down* the x=15 lane, and
   `scripts/predict_bird_visibility.py` predicts PASS — medians 8/6/11 frames at the 5 Hz sensor
   tick, no bird structural. **The throughput half is not:** at the demo take's actual 0.407 Hz the
   same geometry still predicts 0/0/1, so this item stays open on recording throughput
   (ADR-013 am. 5-6a), not on where the birds are. Run the predictor before spending a session.
2. **`baseline_rgb.py`'s birdness is inverted for this world** — see that file's KNOWN-WRONG note.
   (b)'s numbers on a real clip are meaningless until it is recalibrated.
3. **(b)'s FNR is not comparable to (a)'s on a partial-RGB clip** — `score.py` iterates the ground
   truth's frames, so frames that carry no RGB score against (b) as missed rather than as unseen.
   See `baseline_rgb.run`'s LIMITATION note.

`score.py` will now **refuse to decide** rather than emit a verdict on an empty ground truth
(`EVIDENCE INSUFFICIENT`); before 2026-08-21 the same input printed `ADOPT (a) NDVI-direct`.
