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
  `spike_common.py` (clip IO) and on **`src/fieldguard_planning/ndvi_detect.py`, which is where the
  detector itself lives** (one classical-CV detector, used by both arms so the comparison is
  apples-to-apples — and by the live avoidance node, so the flight runs the code these numbers were
  measured on rather than a copy of it). **The threshold is per-render** and `baseline_ndvi.py`
  resolves it from the clip's own `meta.json`: `0.05` on a synthetic clip (ADR-003's deciding value),
  `-0.61` on a real Gazebo render (the gate2 bird/soil midpoint — real soil reads −0.4377, where 0.05
  masks the whole image). The real-render value is still PROVISIONAL after ADR-003 amendment 7
  adopted the detector at it: ADOPT says it works (n=20 bird-frames, 7 FP / 3 FN), not that it is
  where the threshold belongs — lifting it needs the false-positive characterisation.
  `tests/fieldguard_planning/test_ndvi_detect.py` pins the detector's boxes against three committed
  real-render frames and, where the clip is on disk, against the whole 1256-frame adopted run.
- `rgb_pixel_study.py` — ADR-003 **criterion 2**, the independent RGB pixel study (2026-08-26).
  4,566 frames / 1.4027 Gpx / 16,686 bird pixels across both committed real clips, ~3 min on the
  host, no Docker. Emits `results/criterion2_rgb_study_<UTC>/results.json`, which is the evidence
  `baseline_rgb.py`'s real-render threshold is recomputed from. Read `SUMMARY.md` beside it for the
  verdict; the numbers are generated, the verdict is authored.
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
publishes bird poses. `scripts/drive_birds.py` is the only thing that moves them, so it is also the
only thing that can say where they were.

**Label from the driver's APPLIED-POSE LOG, never from its start anchor alone** (ADR-003
amendment 6). `pose_at(stamp_sim_s - t0_sim)` is where the driver *asked* the bird to be at that
instant; the render shows the last pose that *arrived*, one driver tick plus a per-call service
latency later. Measured on the 2026-08-22 flagship take: **lag 0.12–0.81 s, mean 0.52 s**, putting
modelled labels a mean **198 px (max 313)** from a bird whose box is **21–47 px** — IoU can never
match, and every true detection scores as a false positive. The driver therefore logs every
`set_pose` call (pose, trajectory time, sim-time bracket, landed/failed) next to its sidecar, and
the annotator replays that.

```bash
# 1. the driver writes both files at startup (eval/results/bird_drive_<UTCstamp>{.json,_applied.jsonl})
python3 scripts/drive_birds.py                      # prints both paths

# 2. after the flight, label the clip (writes poses_annotated.jsonl, recording untouched).
#    The applied log is auto-discovered next to the sidecar; --applied-log names a moved one.
python3 eval/annotate_real_clip.py --clip eval/results/clips/<clip> \
    --sidecar eval/results/bird_drive_<UTCstamp>.json
# ... eyeball a line, then adopt it:
python3 eval/annotate_real_clip.py --clip <clip> --sidecar <same file> --in-place
```

Every label carries its own provenance in `label_src`, and it travels into `ground_truth.json`:
`applied` (measured — the call had landed), `spawn` (exact — nothing had moved the static model
yet), `generator` (synthetic clip), `modeled` (estimated from t0 alone). **`score.py` refuses to
issue an ADR-003 verdict on `modeled` or `unknown` labels** — a rate needs a denominator *and* a
numerator that measured the same thing. A frame that falls inside a call's own bracket is marked
`label_ambiguous` rather than rounded to a side.

`--bird-t0 <sim seconds>` replaces `--sidecar` for runs older than the sidecar (the driver's
`t0=...` console line); those labels are `modeled` by construction. Labels remain **commanded**
poses, not poses observed back out of Gazebo (same rule as the coverage ledger) — the applied log
closes the timing half of that gap, not the "did Gazebo do what it was told" half.

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
   tick **and 3 m/s**, no bird structural. **Neither the throughput half nor the SPEED half is:** at
   the demo take's actual 0.407 Hz the same geometry predicts 0/0/1, and at the ~9 m/s the
   2026-08-25 take actually flew it predicts 2/2/3 and FAILs — the medians above are a 3 m/s figure
   and nothing else (ADR-016; `--speed` is now required, with no default). Run the predictor at the
   speed and cadence you will really fly before spending a session.
2. ~~**`baseline_rgb.py`'s birdness is inverted for this world.**~~ **CLOSED 2026-08-26** by the
   criterion-2 pixel study (`rgb_pixel_study.py`, evidence in
   `results/criterion2_rgb_study_*/results.json`). The fix was **not** a polarity flip — measured
   over 1.4027 Gpx, min-channel is the wrong *feature* in either direction. (b)'s real-render
   birdness is now **GRVI = (G−R)/(G+R) < +0.0322**, a class-mean midpoint recomputed from the
   study by `tests/fieldguard_planning/test_rgb_pixel_study.py`; the synthetic arm keeps
   min-channel > 110 and reproduces ADR-003's deciding run box-for-box. **`results/adr003_20260823/`
   and `adr003_20260825/` were regenerated on the new arm** — re-scoring the committed artifacts now
   prints **gap +0.000 → ADOPT (a)** (it printed the retired gap −0.850 until 2026-08-26); arm (a) is
   untouched at TP 17 / FP 7 / FN 3.
3. **(b)'s FNR is not comparable to (a)'s on a partial-RGB clip** — `score.py` iterates the ground
   truth's frames, so frames that carry no RGB score against (b) as missed rather than as unseen.
   See `baseline_rgb.run`'s LIMITATION note.

`score.py` will now **refuse to decide** rather than emit a verdict on an empty ground truth
(`EVIDENCE INSUFFICIENT`); before 2026-08-21 the same input printed `ADOPT (a) NDVI-direct`.
