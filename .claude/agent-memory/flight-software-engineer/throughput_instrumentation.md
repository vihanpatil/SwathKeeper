---
name: throughput-instrumentation-results
description: NDVI recording-throughput counters (2026-08-21/22) and what each measured — the slop lever is DEAD, the thermal sensor is NOT render-limited, the recorder's own logic drops nothing
metadata:
  type: project
---

The six frame-loss counters built on branch `feat/throughput-instrumentation` (2026-08-22) and what
their first flight measured. Verify the counter names still exist before quoting them.

**Why:** the fused→recorded stage was a single unattributed black box (ADR-013 am. 6a called the
separation "the next counter to add, not the next lever"), and three incompatible mechanisms were
each consistent with the artifacts. One instrumented flight was supposed to settle them.

**How to apply:** these results retire two candidate levers outright. Do not spend a flight on
either. The absolute throughput number from that flight is VOID (see [[host-quiet-is-a-flight-gate]])
— only the RATIOS below are trustworthy.

## The counters and where they live
- `ndvi_node.counters()` → the 1 Hz sidecar → `meta.json["fuser"]` (stats schema 1.1):
  `nir_camera_info_frames`, `unpaired_red_count`, `unpaired_red_nearest_nir` (histogram).
- `clip_recorder.RecorderCounters` → `meta.json["recorder"]` (clip schema 1.3):
  `ndvi_msgs_received`, `rgb_msgs_received`, `dropped_no_writer`, `dropped_no_pose`,
  `on_ndvi_wall_ms_p95/max/n`.
- `clip_recorder.ClipWriter.airborne_summary()` → `meta.json["airborne"]`; painting frames +
  cadence → `heatmap.json` from `stitch_ndvi.py` (painting depends on the projection, so it is an
  offline question — it cannot be computed in the recorder).

## What the first flight settled (ratios, robust to the load confound)
- **The thermal sensor is NOT render-limited.** `nir_camera_info_frames` 689 vs
  `camera_info_frames` 690 — the NIR sensor ticked on essentially every RGB tick. The
  "thermal renders at ~3 Hz so the pairing stage is uncloseable" hypothesis is FALSIFIED. NIR is
  transport-limited, so transport levers DO apply to it. This was the round's decisive counter.
- **The slop lever is DEAD — do not fly it, do not amend ADR-007 for it.** The unpaired-red
  nearest-partner histogram came back 79 of 79 in the `ge_tick` bucket (`le_slop` 0,
  `slop_to_tick` 0, `no_nir_in_window` 0, `pending` 0, `evicted_undrained` 0). Every unpaired red's
  nearest surviving NIR was a full 200 ms tick away, i.e. its own-tick partner never arrived.
  Widening slop below one tick recovers literally nothing; widening past it pairs different sensor
  ticks. Measured under heavy CPU contention, which is the direction that would have SHOWN arrival
  skew if any existed — so the disproof is conservative.
- **The recorder's own logic drops nothing.** `dropped_no_writer` 0, `dropped_no_pose` 0, and
  received 7 → written 7. The whole fused→recorded gap was transport on the 1.2 MB
  `/fg/ndvi/image` sample (37 fused → 7 received).
- **The disk / bind mount is not the wall.** `on_ndvi_wall_ms` p95 = max = 17.3 ms against a 200 ms
  tick, i.e. the callback occupies ~9 % of a tick *including* its ~2.15 MB of synchronous .npy +
  flushed-JSON writes. The executor was idle when frames died. (n=7, so thin — but the direction
  exonerates the disk.) Moving clip output off the macOS bind mount is not worth a flight.
- **Subscriber fan-out is not the dominant term.** `/fg/sensor/nir/image` has exactly ONE subscriber
  and still lost ~71 % of its ticks. Separately, the recorder's `rgb_msgs_received` (102) tracked
  the fuser's `red_frames` (116) at 88 % — the second reader is being served. Dropping the
  recorder's RGB arm would cost the ADR-003 comparison arm for little throughput.
- **The same-tick model held at a 5th, very different operating point.** predicted fused =
  red × (nir/nir_ci) = 116 × 0.293 = 34.0 vs measured 37 (ratio 1.09), inside the 1.01-1.15 band
  from F1-F4.

## The open problem this left (2026-08-22, two flights)
`red_frames/camera_info_frames` came in at **16.81 %** and **17.31 %** on two flights against F4's
**31.09 %** the day before, on the same config — reproducible, and the second flight was on a
verifiably quiet host. NIR halved the same way (58.9 % → 29-35 % of ticks). Unattributed. The
instrumentation is *unlikely* to be the cause — both camera_info streams delivered 100 % (676/676),
and the recorder's callback ran in 7.9 ms against a 200 ms tick, so neither node's executor was
saturated — but it is **not yet ruled out by measurement**.

**SETTLED 2026-08-22 by an interleaved bench A/B — the instrumentation is EXONERATED.** Gazebo +
bridge held constant, only `ndvi_node` swapped (git stash of `ndvi_node.py` + `ndvi_fusion.py`),
four 60 s runs interleaved instrumented/baseline/instrumented/baseline:

| run | red/ci | nir/ci | host load |
|---|---|---|---|
| A1 instrumented | 8.09 % | 52.9 % | sum 15-23 % |
| B1 baseline | 15.58 % | 37.0 % | sum 2-10 % |
| A2 instrumented | 10.71 % | 72.9 % | sum 8-14 % |
| B2 baseline | 7.19 % | 34.6 % | sum 2-11 % |

The sign FLIPS between pairs on red/ci (-7.49 pts, then +3.52 pts), and the baseline swings 2.2x
against itself (7.19-15.58 %) — run-to-run variance dwarfs any systematic effect. On `nir/ci`, which
has ~5x the counts and so far less Poisson noise, the instrumented build is **ahead in all four
comparisons**, which cannot be a cost.

**The decisive number:** the UNINSTRUMENTED build also measured 7.19-15.58 % on today's host,
nowhere near F4's 31.09 % from the day before. The 2x shortfall is **environment drift, not code**.
(The whole Supabase stack was created 2026-08-22T03:38Z and is churning; F1-F4 ran on a VM hosting
`fieldguard-sim` alone.) Bench technique worth reusing: it costs no flight and needs no consent.
Caveat: a stationary no-SITL scene, so absolute red/ci is not comparable to a flight — only the
within-bench comparisons are.

## Where the remaining loss lives (F5b, 676 ticks)
Three independent transport hops, all lossy, and pairing is NOT a fourth:
`RGB image bridge→fuser 82.7 % lost` · `NIR image bridge→fuser 65.4 % lost` ·
`NDVI fuser→recorder 84.8 % lost`. Recorder's own logic: 0 % lost.
**Honest ceiling of the current lever set, computed from the clean F4 baseline:** closing BOTH
remaining hops (NIR transport, and the NDVI→recorder hop that L1 targets) takes F4's 0.587 Hz
airborne to ~**1.48 Hz** — the bottom edge of the 1.5-2 Hz target, with zero margin, and only if
every one of them lands. Reaching the target with margin requires attacking the RGB band's ~83 %
transport loss, which no lever in the current set touches.

## Micro-fix measured live
- **float32 instead of float64** through `rescale_red`/`rescale_nir`/`compute_ndvi`
  (`ndvi_fusion.NDVI_DTYPE`). Removes ~8 MB of allocation per fused frame; output was always
  float32. NOT bit-identical: worst case 3.5e-5 on an adversarial-random 640x480 frame, 0-3e-8 on
  the material calibration points. Live-confirmed harmless — the flight's soil modal still read
  **-0.4377** (published value -0.437687) and `check_tree_positions.py` PASSED.

## Deliberately NOT done
- Destroying `record_node`'s camera_info subscription after the first message. It is a real
  micro-lever (~4.2k wasted dispatches/flight) but it is a **subscription removal**, i.e. a tuning
  lever, and destroying a subscription from inside its own callback is an rclpy hazard that cannot
  be gated off-sim. Keep it out of any flight whose job is to be a clean control.
