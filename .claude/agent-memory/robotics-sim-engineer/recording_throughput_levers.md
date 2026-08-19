---
name: recording-throughput-levers
description: Fused-frame recording throughput on the software-rendered stack — the 5→2 Hz camera lever was measured live 2026-08-19 and DISPROVEN (16x worse); delivery is bursty, not rate-limited; and no artifact separates "never fused" from "recorder dropped it".
metadata:
  type: project
---

**Do not re-run the `camera.update_rate_hz` 5 → 2 experiment without new evidence.** It was measured
live on 2026-08-19 (one `scripts/fly_pipeline.sh test-flight` gate, same `test_2lane` mission, same
launcher) and made recording throughput **16x worse**: 3 fused frames / 1 of 720 cells at 2 Hz vs
48 / 291 at 5 Hz over a comparable sim-time window. Reverted the same session; `5.0` now stands on
measured grounds and `config/ndvi_camera.json`'s `update_rate_note` carries the basis.

**Why:** the hypothesis (halve render+transport load → the starved pipeline delivers a larger
fraction) was reasonable and is wrong on this stack. The load relief was real and measurable — RTF
went *up* slightly (0.585 vs 0.561) and the mission flew identically — but delivery still collapsed.
Best available explanation: **delivery is bursty, not steadily rate-limited.** The pipeline
intermittently runs at the configured ceiling and harvests whole bursts (9 of the 5 Hz baseline's 47
inter-frame gaps ≤ 0.4 s, 4 exactly at the 0.2 s ceiling); a 2 Hz ceiling (0.5 s) cannot harvest a
burst at all. That explains part of a 16x, not all of it — the mechanism is **unproven on n=1**.

**How to apply:**
- Remaining levers for ROADMAP item 1 are **bridge QoS** and a leaner `ndvi_node` publish path.
  Lowering the camera rate is spent.
- **Instrument before the next attempt.** Nothing today persists the fuser's
  `fused_count`/`dropped_pair_count` (they live only in the ndvi node's console, and
  `pane_tails["ndvi"]` comes back empty in *every* gate record), so no artifact distinguishes "the
  fusion node never fused" from "the recorder dropped what it fused". Persist those counters into
  the gate record or clip `meta.json` first; otherwise the next lever is guessed, not diagnosed.
- **The comparison method is reusable and cheap:** the `bird_drive_*.json` sidecar's `t0_sim_s` +
  its `written_utc` is a hard sim↔wall anchor, so RTF and the recorder's sim-time exposure window
  can be reconstructed from committed artifacts alone. Compare *delivered / expected over the
  sim-time window*, never raw frame counts — and compare like-for-like missions (a 2-lane strip
  cannot be judged against a full boustrophedon's tree-check bar).
- Evidence: `eval/results/testflight_gate_20260819T021136Z.json` (2 Hz) vs
  `eval/results/testflight_gate_20260818T222031Z.json` (5 Hz baseline) + their clips' meta/poses/
  heatmap. Numbers table in `docs/BUILD_LOG.md`.
- **Host-quiet is confirmed load-bearing but was NOT the confound here**: birds' `set_pose` failure
  rate (10/522 vs 6/531) and RTF are usable independent load proxies when judging a suspect run.

Related: [[adr007-ndvi-sensor-mount]] (the sensor the rate belongs to), [[macos-arm64-bringup-gotchas]]
(why the render is starved in the first place — no GPU passthrough, llvmpipe), [[bringup-file-layout]].
