---
name: bird-label-timing
description: Bird ground-truth labels lag the render by 0.12-0.81 s (driver hold + gz-CLI latency); only the applied-pose log makes them scoreable — and even APPLIED labels carry a measured ~15 px residual
metadata:
  type: project
---

**Measured 2026-08-22 on `real_flight_20260822T215516Z`: the rendered bird is 0.12-0.81 s (mean
0.52) BEHIND the trajectory time its label claims.** Never label a real clip from the driver's t0
anchor alone and then score IoU against it.

Mechanism, decomposed and each part measured:
- `drive_birds.py` polls the gz clock once per tick and holds each pose until the next tick. The
  hold is **0.415-0.427 s of SIM time** (visible as a 2-frame sawtooth in the detections: within a
  hold the lag grows by exactly the 0.200 s frame period, then drops by hold−0.200).
- On top of that a **per-bird actuation latency ordered by position in the driver's loop**
  (floors 0.120 / 0.380 / 0.415 s for bird_0/1/2) — sequential `gz service` subprocess calls.
- `--rate` is only a sleep floor and **does not bind**: `--rate 2` achieved ~1.3 Hz because one
  clock poll plus three `gz service` round-trips cost ~0.75 s of wall clock. ADR-012's "matches the
  camera's 5 Hz, so the render never sees a stale hop" is FALSE and is retracted.
- Consequence for perception work beyond labelling: **birds HOP ~2 m between updates**, one full
  frame wide. Per-frame blob detection is unaffected; any velocity/track estimate would be garbage.

**Why:** modelled labels put the bird a mean 198 px (max 313) from a 21-47 px box, so IoU ≥ 0.3 can
never match — every true detection scores FP and every bird scores FN. That produced ADR-003
amendment 5's "per-bird-track FNR 1.000", which was an artifact, not a detector result. A fitted
lag cannot repair it either: the driver's ticks are wall-scheduled while RTF varies 0.51-0.94
within one flight, so no fixed sim-time grid stays in phase (best 2-param model still left 81 px
mean / 536 px max), and fitting the lag to the detector's own output would make the score
unfalsifiable.

**How to apply:** the fix is measurement — `drive_birds.py` writes
`bird_drive_<stamp>_applied.jsonl` (pose, trajectory time, sim-time bracket, landed/failed) and
`annotate_real_clip.py` replays it; failed calls hold, pre-first-apply frames are the exact spawn
pose. Every label carries `label_src` (`applied`/`spawn`/`generator` = scoreable, `modeled`/
`unknown` = refused by `score.py`). The driver half is UNGATED until a flight runs it — first
re-fly must confirm the log exists, covers the clip's sim span, and that the annotator reports
`applied` labels. See [[ndvi-rgb-spike]], [[eval-harness-core]].

**APPLIED labels are scoreable, not exact — measured 2026-08-26 by overlaying box on pixel.** On
the 2026-08-25 take's only two bird-visible frames, the applied-pose GT box vs the committed
detector box: frame 964 IoU **0.826** (boxes nearly coincident), frame 965 (the CPA frame, range
3.95 m) IoU **0.511** — the label sits ~15 px LEFT of the rendered bird, about a third of the
47 px box. Visible to the eye in
`eval/results/adr003_20260825/overlays/gtdet_a_ndvi_direct_ndvi_frame_000965.png`. So the residual
survives the applied-log fix at roughly 1/13 of the modelled error, and the CPA frame — the one
that matters — clears the 0.3 IoU bar by 0.21, not by a mile. Two consequences: do not raise the
scoring IoU above ~0.4 without re-measuring this, and never present a bare `gt_*` still as "the
detector's box" — on frame 965 the red label box visibly misses the bird the detector framed
tightly, which reads as a detector failure and is the opposite of the truth.
