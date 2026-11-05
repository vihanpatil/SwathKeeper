---
name: adr003-ndvi-detection
description: ADR-003 CLOSED 2026-08-23 — ADOPT NDVI-direct on the real render; classical blob baseline stands, no model justified
metadata:
  type: project
---

ADR-003 (NDVI-vs-RGB detection) — **criterion 3 CLOSED 2026-08-23 (amendment 7): ADOPT (a)
NDVI-direct on the REAL render.** Per-bird-track FNR 0.000 (bar ≤ 0.1) on measured (applied-pose)
labels, every bird detected before closest approach, precision 0.708 / recall 0.850, n=20 visible
bird-frames, 3/3 birds. Arm (b) synthetic-RGB scored 0.000 across the board — birdness is INVERTED
on this world.

**Why it took three tries:** the three causes closed measured, one at a time — geometry (ADR-015
bird patrol lines), throughput (ADR-013 am. 6-9, Fast DDS SHM segment), ground truth (am. 5-6, the
render lags the labels 0.12-0.81 s).

**How to apply:**
- Detection framing is settled twice over — do not relitigate NDVI-vs-RGB, and do not propose a
  trained model: the classical blob baseline cleared the bar, and the 0.445 synthetic precision
  figure is the bar any learned model must beat on the same `eval/` harness.
- **The detector now has ONE home: `src/fieldguard_planning/ndvi_detect.py`** (moved 2026-08-24,
  ADR-003 am. 8; `eval/blob.py` deleted, `eval/` imports the core). The move was gated by a
  bit-identical re-score — 24 detections over 1256 frames, `score.py` reproducing `spike_scores.json`
  exactly — so ADOPT transferred rather than being re-earned. Repeat that gate for any future move.
  Verified on host scipy 1.13.1 ONLY; jammy's 1.8.0 (container) and CI's 1.18.0 are unproven.
- Two things are still genuinely open and worth flagging: the **−0.61 real-render threshold stays
  PROVISIONAL** (n=20, 7 FP / 3 FN, 8 of 20 labels `label_ambiguous`) — lifting it is
  perception-ml-engineer's call after FP characterisation; and **criterion 2's independent RGB
  pixel study** (~1 h offline, the measured-label clip already exists).
- The adopted detector is an OFFLINE host-side artifact. Moving it onto the live seam is its own
  interface problem — see [[week6-detection-seam-open-questions]].
