---
name: teardown-unfinalized-clip
description: A skipped `fly_pipeline.sh down` leaves the recorder AND drive_birds running forever — the 2026-08-25 take's clip grew 2639 parked frames and its truth track kept growing after scoring; recover with the shipped send_ctrl_c, never an offline meta rebuild.
metadata:
  type: project
---

**2026-08-25, the real-detection avoidance take:** the operator did runbook §4 step 1 (Ctrl-C shell 8,
flight log written 21:04:02Z) and then jumped straight to §5's post-flight gates. **Step 2,
`scripts/fly_pipeline.sh down`, was never run.** Found 22 minutes later: the `swathkeeper` tmux
session still attached, all 7 windows alive, and

- `record_node` still recording at 5 Hz — the clip reached **3310 frames of which only 671 were
  airborne**; 2639 were post-landing frames of a parked drone at (0,0,-0.0), ~+1.1 GB of `.npy`;
- **no `meta.json`**, so the clip was unstitchable (`stitch_ndvi.py` reads intrinsics from it);
- `drive_birds.py` still appending to the take's `_applied.jsonl` — the flight's ONLY bird ground
  truth grew 1787 → 1909 records *while the safety gate's verdict was already written*, so those
  denominators (`landed set_pose calls scored`, `answered_from_spawn`) are no longer reproducible.

**Why:** nothing anywhere notices an unfinalized clip. `cmd_status` prints windows and liveness
probes but never checks for one; `up`'s surviving-process refusal only fires on the *next* session;
the safety gate scores happily without a clip. Skipping `down` has no visible consequence at the
moment you skip it.

**How to apply:**
- **Before believing any clip is dead, check `docker exec fieldguard-sim ps aux | grep record_node`
  and sample the frame count twice.** If it is alive, the recovery is the SHIPPED path — the
  recorder-half of `cmd_down`, `tmux send-keys -t swathkeeper:record C-c`, then poll the pane for
  `clip finalized`. Do **not** rebuild `meta.json` offline: `ClipWriter.__init__` opens `poses.jsonl`
  with `"w"` (it would truncate the evidence), and the live counters, `fuser` block, DDS snapshot and
  live intrinsics exist only in that process. The real finalize took **<15 s for 3310 frames**
  (raw `.npy` → schema PNG, `rgb_raw/` removed — designed, lossless, 4.9 GB → 3.8 GB).
- Post-flight parked frames are **harmless to the map and honestly reported**: the camera sits below
  the z=0 ground plane so every one is a `frames_zero_update`, and `airborne.frames` /
  `frames_painting` carry the real denominators (671 / 649 here). Only `num_frames` is inflated.
- The truth track is NOT harmless — it is append-only evidence that a live driver keeps extending.
  Freeze it (stop `drive_birds`) before any gate is scored.

Two one-line fixes, **recorded open, not implemented**: (1) runbook §5's capture block should assert
`test -f "$CLIP/meta.json"` before any gate runs; (2) `fly_pipeline.sh status` should warn when the
`record` window is alive and the newest clip has no `meta.json`.

Related: [[avoidance-real-detection-take]], [[bird-ground-truth-track]],
[[recording-throughput-levers]].
