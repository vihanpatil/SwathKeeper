---
name: recording-throughput-levers
description: Recording throughput is CLOSED (2026-08-22, Fast DDS SHM segment root cause, 5.0 Hz flat) — plus the levers tried on the way, including the 5→2 Hz camera rate that was measured and DISPROVEN (16x worse) and must never be retried.
metadata:
  type: project
---

**STATUS: CLOSED 2026-08-22 (ADR-013 am. 9).** Root cause was **not** render, pairing, or the
recorder: Fast DDS 2.6.11 fragments samples at 65,384 B even over shared memory, and the default
512 KiB SHM segment holds 8 fragment slots against the 10-19 a ~900 KB frame needs — overflow is
discarded **silently**. Fix = `config/dds/fg_fastdds.xml` (SHM segment → 8 MiB) + `--shm-size=1g` on
the container (`scripts/sim_docker_run.sh`), injected in-pane with runbook parity intact. Result:
**100 % delivery on both bands, zero unpaired reds, end-to-end 96.5 %, painting cadence 0.41 → 5.0 Hz
flat** (the full sensor tick), first 720/720 maps.

**How to apply now:**
- **5.0 Hz is the honest cadence input** for anything that asks "how many frames will we get" —
  notably `scripts/predict_bird_visibility.py --fps`. Before am. 9 the truthful number was 0.41 Hz.
- Two preconditions travel with it and are easy to lose: the container must be created with
  `--shm-size=1g` (recreate via `scripts/sim_docker_run.sh`), and every pane must export
  `FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml`. A container or
  pane missing either silently returns to the old regime; `meta["dds"]` in the clip makes it
  checkable after the fact.
- **Held on the 2026-08-25 real-detection take, the third independent confirmation:** airborne
  cadence **5.0 Hz flat** over a 134.0 s window (671 airborne frames), painting cadence **5.0 Hz**
  (649 painting frames), 720/720 cells. `meta["dds"]` read `min_bytes == max_bytes == 8,413,728`
  across 4 segments — the profile reached every participant. Transport that flight: `red_frames`
  3400 / `camera_info_frames` 3400 = **100 %**; fuser 3399 → recorder 3327 = **97.9 %** on the
  NDVI→recorder hop (72 lost, the only non-zero leak), `on_ndvi_wall_ms` p95 12.1 / max 88.2 ms.
- **A THIRD image stream joined this bus on 2026-08-26** (ADR-019 `/fg/depth/image`, 640x480x4 =
  19 fragments/tick). The 8 MiB segment was sized for ~27 fragments/tick and now carries ~46 (still
  128 slots), so it should hold — but it is UNMEASURED, and re-measuring depth+RGB+NIR delivery
  together is gate D5 in `docs/runbooks/FORWARD_DEPTH_SENSOR.md`. Raising `segment_size` is a
  pinned-config change: DECISIONS.md entry + an ADR-007 delivery re-run, not a quiet edit.
- Not yet proven at boustrophedon length (5.0 Hz was measured on the 3-min `test_2lane` and on the
  flagship take; run-age decay is still an open question, ADR-013 am. 7).

**Do not re-run the `camera.update_rate_hz` 5 → 2 experiment.** Measured live 2026-08-19 (one
`fly_pipeline.sh test-flight`, same `test_2lane` mission): **16x worse** — 3 fused frames / 1 of 720
cells at 2 Hz vs 48 / 291 at 5 Hz, with RTF slightly *up* (0.585 vs 0.561) and the mission flown
identically. Reverted the same session; the basis lives in `config/ndvi_camera.json`'s
`update_rate_note`. In hindsight the mechanism is the fragment-overflow one above: a lower ceiling
cannot harvest the bursts that were getting through.

**Kept levers from the earlier rounds (nothing reverted):** bridge QoS `best_effort` as a per-topic
ROS parameter (NOT a bridge-yaml key at the pinned SHA) and gating the `/fg/ndvi/preview` publish on
`get_subscription_count` — together 10.5 % → 31.1 % red/tick on 2026-08-21; L1 (the NDVI→recorder
hop) closed 62.5 % → 0 %.

**Two traps that outlived the fix:** judge a lever by `red_frames / camera_info_frames`, never by
`cells_imaged` (judge a *map* by painting frames — the demo take recorded 454 frames of which only
51 painted a cell); and compare like-for-like missions.

Related: [[adr007-ndvi-sensor-mount]] (the sensor the rate belongs to),
[[macos-arm64-bringup-gotchas]] (why the render is starved at all), [[bird-ground-truth-track]],
[[avoidance-real-detection-take]],
[[forward-depth-sensor]].
