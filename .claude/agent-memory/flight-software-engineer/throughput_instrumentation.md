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

## ROUND 3 — ROOT CAUSE FOUND, and the bench says it is fixable (2026-08-22)
The large-sample loss was never QoS. Fast DDS fragments every sample at **65,384 B even over shared
memory** (SHM's own `max_message_size` defaults to 65500 and the participant takes the MIN across
transports, where UDPv4 is hard-capped), and only **eight** fragments fit the default 512 KiB SHM
segment. On exhaustion Fast DDS **discards the fragment and reports success** — no error, no counter.

**Lever L2** (`config/dds/fg_fastdds.xml`, segment_size 8 MiB = 128 slots, injected via
`FASTRTPS_DEFAULT_PROFILES_FILE`) measured on a 4-arm interleaved bench, all admissible:

| arm | red/ci | nir/ci | SHM segment min=max |
|---|---|---|---|
| B0 baseline | 28.81 % | 96.71 % | 549,408 B |
| **B1 L2** | **100.0 %** | **100.0 %** | **8,413,728 B** |
| B0 baseline | 26.40 % | 93.68 % | 549,408 B |
| **B1 L2** | **100.0 %** | **100.0 %** | **8,413,728 B** |

Both pairs agree, same sign, **3.62x on the red band and zero loss on both**. Bench = 2 participants
and no SITL/recorder/birds, so these are clean-room numbers — flight will be lower (flight nir/ci was
46 % where the bench baseline reads 95 %).

**The (1-q)^frags model is FALSIFIED and should not be quoted.** In the SAME arm, same segment, same
tick, red (15 frags) implies q ≈ 8 %/fragment while nir (10 frags) implies q ≈ 0.5 % — a 24x
discrepancy. The data supports a **slot-exhaustion threshold**, not iid per-fragment loss: delivery
collapses once a sample's fragment count materially exceeds the 8 slots, and removing the threshold
takes both bands to exactly 100 %.

**Two instrumentation traps found live, both now pinned by test.** `/dev/shm/fastrtps_*` includes
(a) fixed 52,416 B `fastrtps_port*` queues and (b) **zero-byte `<name>_el` companions** beside every
segment and port — counting either destroys `min_bytes`, which is the only thing that can detect a
participant that missed the profile. Also: orphaned segments outlive a hard-killed participant, so
`min_bytes` reported a DEAD default segment as a live miss until the bench started clearing
`/dev/shm` after its liveness guard.

## L2 FLEW AND THE THROUGHPUT PROBLEM IS CLOSED (F9, 2026-08-22)
The bench held in flight, fully admissible (profile present, SHM segments min=max=8,413,728 across
all 4 participants):

| | F4 (A+B) | F6 (+L1) | **F9 (+L2)** |
|---|---|---|---|
| red/ci | 31.09 % | 20.46 % | **100.00 %** |
| nir/nir_ci | ~58.9 % | 46.22 % | **100.00 %** |
| fused / red | 59.4 % | 51.1 % | **100.00 %** (unpaired **0**) |
| end-to-end | 12.32 % | 10.16 % | **96.46 %** |
| painting cadence | — | 0.4767 Hz | **5.0 Hz** (502 painting frames) |
| RGB comparison arm | 57 % | — | **681/681 = 100 %** |

`predict_bird_visibility.py --fps 5.0` now **PASSES** (medians 8/6/11, bird_0 visible at 55/55
driver-start offsets), so the ADR-003 full-coverage re-fly is bookable — it had been blocked on
throughput since the demo take.
**CORRECTED 2026-08-25 (ADR-016): that PASS is a 3.0 m/s figure and nothing else.** The medians are
monotonic in ground speed — PASS at 3.0, FAIL at 5.0 (2 of 3 birds), FAIL 3-of-3 from 8.5 up, and
2/2/3 at the ~9 m/s the 2026-08-25 take flew. `--speed` is now REQUIRED with no default (`ap.error`,
exit 2 = refusal, distinct from PASS 0 / FAIL 1); `REFERENCE_SPEED_MPS = 3.0` survives only to keep
the published medians reproducible in tests. **The gate FAILs on the committed geometry at every
speed the vehicle actually flies** — booking the next detection take needs a geometry or a speed
change first.

**Pairing is no longer a stage at all:** `unpaired_red_count` 0, every histogram bucket 0. The
same-tick model was right all along — pairing loss was purely NIR transport loss re-expressed, and
fixing transport erased it.

**L1 re-check CLOSED (F9 vs F10, one variable):** dead heat. RELIABLE lost 1.56 % of fused frames,
BEST_EFFORT 1.71 %; identical 5.0 Hz cadence, 502 painting frames each. **KEPT** on a 0.15-point
margin, and note L1's round-2 cost (red/ci 25.60 % -> 20.46 % backpressure) has VANISHED — both
flights sit at 100 % red/ci, because L2 removed the drops the retransmission was repairing.

## THE FULL-COVERAGE DEMO TAKE (2026-08-22, clip real_flight_20260822T215516Z)
Full boustrophedon, flown from the runbook's MAVProxy recipe. **720/720 cells, 18/18 trees imaged,
14 canopy-grade, displacement gate PASS.** 935 frames, 935 with RGB (100 %), 0 stale-pose pairs,
end-to-end 97.80 % of sensor ticks. Painting 624 frames at **5.00 Hz**.

**Run-age decay is GONE, and it was never a separate phenomenon.** 623 of 623 painting inter-frame
gaps are exactly 0.200 s — median = p90 = max. 5.00 Hz in every 60 s bin across the whole mission.
Round 2's decay (median gap 1.4 s, p90 6 s, max 18.4 s) was a symptom of segment-exhaustion loss.

**Short-vs-long is REVERSED by L2.** Painting frames per airborne minute: 2-lane 288.0 vs full
boustrophedon 290.2 (identical); cells per airborne minute 239.2 vs **334.9**. The long flight is now
strictly better per minute, because the boustrophedon spreads frames over new ground. Round 2's
"several short flights beat one long one" no longer holds — do not carry it forward.

## ADR-003 CRITERION 3 IS CLOSED — ADOPT on the real render (2026-08-23, clip real_flight_20260823T073644Z)
The criterion-3 re-fly, flown once the am. 6 applied-pose logger existed. Decision rule printed
**`-> ADOPT (a) NDVI-direct`**: per-bird-track FNR **0.000** (bar <= 0.1), frame FNR 0.150 vs RGB's
1.000, on **20 visible bird-frames, 3/3 birds**, all **20 labels `applied` (measured)** and
**0 `modeled`**. NDVI precision 0.708 / recall 0.850 (TP 17 / FP 7 / FN 3); RGB arm 0.000/0.000 —
still the inverted-birdness bug, untouched by design.

**The label-provenance gate is what unblocked it**, not throughput: `2232 applied / 1536 spawn /
0 modeled`. The previous take scored FNR 1.000 purely because continuously-interpolated labels sat
a mean 193.6 px from the render; replaying the driver's ACTUAL applied poses fixed it. Driver
achieved **1.19 Hz of the 2.00 requested**, 21 of 860 set_pose calls failed (2.4 %) — that gap IS
the misalignment, now measured instead of modeled.

**Predictor accuracy, first check against measured labels:** predicted medians 8/6/11 vs measured
2/5/13. bird_1 and bird_2 inside the predicted range; **bird_0 measured 2, BELOW its predicted
minimum of 3** — the uniform-sampling model is optimistic per-bird even when the total (20 vs 25) is
close. Do not quote a per-bird median as a floor.

## ADR-003 WAS THROUGHPUT-BLOCKED, THEN HARNESS-BLOCKED (superseded by the above)
The clip cleared the evidence floor for the first time: **10 visible bird-frames, 3/3 birds seen**
(previously 0, structurally). But both arms scored **FNR 1.000** and the rule printed
`AMBIGUOUS -> default to (a)`. **That number is an artifact, not a detector property:**
- The NDVI detector fired on **18 frames**, exactly the frames the birds are in (331-333, 392-398,
  455-462), with blob sizes matching the ground truth to **1-2 px across four ranges** (47x47 vs
  45x45 at 3.96 m; 21x21 vs 20x21 at 9.24 m). Same physical objects.
- But GT box centres sit a **mean 193.6 px** from the detections, so IoU >= 0.3 can never match:
  every real detection scores FP and every real bird scores FN.
- Leading hypothesis (consistent, not proven): `drive_birds --rate 2` moves birds in **0.5 s steps**
  while `annotate_real_clip.py` interpolates the trajectory **continuously**, so the rendered bird is
  up to 0.5 s stale. Implied bird travel from the offsets is 0.7-4.4 m, the right order for 0.5 s —
  but the implied speeds vary 1.4-8.7 m/s, and 16 `set_pose` calls failed, which compounds it.
  Fix direction: replay the driver's STEP function (t0 + k/rate), not the continuous path.
- This only became visible at 5 Hz. At the demo take's old 0.407 Hz a 0.5 s quantisation is invisible.

## LEVER L1 — KEEP (measured 2026-08-22, F6, host verifiably quiet)
Making `record_node`'s `/fg/ndvi/image` subscription **RELIABLE** (reliability only; every other
field copied from `qos_profile_sensor_data`; the publisher was already RELIABLE depth 10) **closed
that hop completely**: `fused_count - ndvi_msgs_received` went **62.5 % → 0.0 %** (72 of 72 fused
frames received). Recorder attribution now closes exactly: 72 received − 70 written − 0 no_writer
− 2 no_pose = **0 unaccounted**.

**It has a real, predicted cost — do not quote the win without it.** RELIABLE backpressures the
publisher's executor, pushing loss upstream into the fuser: red/ci **25.60 % → 20.46 %**, nir/nir_ci
50.82 % → 46.22 %, fused 96 → 72. Net is still strongly positive because the downstream hop was the
bigger leak: recorded 36 → 70, cells 158 → 301, painting cadence **0.2823 → 0.4767 Hz** (1.69x),
end-to-end 5.39 % → 10.16 %. If NIR transport is ever fixed, RE-CHECK whether L1 still nets positive
— the trade could invert.

## Where the remaining loss lives (F5b, 676 ticks)
Three independent transport hops, all lossy, and pairing is NOT a fourth:
`RGB image bridge→fuser 82.7 % lost` · `NIR image bridge→fuser 65.4 % lost` ·
`NDVI fuser→recorder 84.8 % lost`. Recorder's own logic: 0 % lost.
**UPDATED after F6 (689 ticks), the best config measured:** the NDVI→recorder hop is CLOSED (0 %).
What is left is `RGB image bridge→fuser 79.5 % lost` and `NIR image bridge→fuser 53.8 % lost`;
pairing remains fully explained by NIR delivery (model predicts 65.2 fused vs 72 measured, 1.10).
Best painting cadence **0.4767 Hz**, so **3.1x** is still needed for 1.5 Hz and 4.2x for 2.0 Hz.
Closing NIR transport entirely buys ~1.96x → ~0.93 Hz — **not enough on its own**. 1.5 Hz needs NIR
closed AND red/ci back to ~31 % (F4's best-ever). 2.0 Hz needs red/ci ~44 %, beyond anything ever
measured. Both remaining hops are already `best_effort` at the bridge (lever A), so the residual is
payload-size fragmentation — which points at the wire-encoding/resolution levers, not at more QoS.

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
