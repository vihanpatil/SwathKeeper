---
name: ndvi-rgb-spike
description: ADR-003 NDVI-vs-RGB — decided on synthetic (ADOPT (a), per-bird FNR 0.000); criterion 3 real-render re-confirmation still OPEN, now on bird-label timing
metadata:
  type: project
---

**Framing DECIDED 2026-08-04 on the synthetic clip; criterion 3 (real render) still OPEN.** Do not
relitigate (a)-vs-(b); do relitigate nothing else about it either — the open item is evidence.

Synthetic deciding numbers (`sim/spike/out/spike_seed42`, seed 42, frame precision/recall/FNR):
- (a) NDVI-direct **0.445 / 0.981 / 0.019**, per-bird-track FNR **0.000**
- (b) synthetic RGB **1.000 / 0.981 / 0.019**, per-bird-track FNR **0.000**
→ ADOPT (a) on the fidelity tiebreak. **0.445 is the bar any learned model must beat.** Re-verified
2026-08-22 after the label-provenance guard landed: reproduces exactly, still prints ADOPT.

**Criterion 3's blocker has moved three times, each time with the previous cause measured closed:**
geometry (ADR-015) → recording throughput (ADR-013 am. 9-10, 5.0 Hz) → **bird-label timing**
(ADR-003 am. 6, 2026-08-22 — mine). Current verdict on the flagship clip
`real_flight_20260822T215516Z`: **EVIDENCE INSUFFICIENT**, and it is the labels, not the detector.

What the flagship clip DOES establish (alignment-independent, so it survives the label defect):
- 22 NDVI-direct detections in 935 frames; **all 22 sit within 20 px of a scripted bird** at a lag
  of 0.12-0.81 s and match its projected apparent size to **≤2.5 px**. Zero non-bird detections.
- **Zero silent frames**: for every lag hypothesis in [0, 0.70] s there is no frame where a bird was
  in view and the detector produced nothing. At the measured lag band the "bird in view" frame set
  and the "detector fired" frame set are the SAME 18 frames.
- So the detector looks strong on the real render — but that is a *diagnosis*, not a scored verdict,
  and it must not be written up as precision/recall/FNR. Those need measured labels.
- Criterion 2's RGB arm is still not a comparison arm: `baseline_rgb`'s min-channel birdness is
  inverted here, and its 5 real-render detections are a 2-LSB blue-channel accident (3 on bird_2 at
  8 px against a true 21 px → IoU 0.145, would miss even with perfect labels) plus 2 corner
  artifacts. Do not calibrate it against a clip whose labels are unscoreable.

**Next for an ADOPT/REJECT:** one re-fly with the applied-pose-logging driver, then re-run
`eval/run_spike.sh`. Nothing else is blocking. See [[bird-label-timing]] and [[eval-harness-core]].
