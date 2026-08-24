---
name: ndvi-rgb-spike
description: ADR-003 NDVI-vs-RGB — DECIDED and CLOSED (am. 7, ADOPT on the real render); the live numbers, the bars, and what is still open (criterion 2, PROVISIONAL threshold)
metadata:
  type: project
---

**Framing DECIDED 2026-08-04 on the synthetic clip; criterion 3 (real render) CLOSED 2026-08-23
(ADR-003 amendment 7, ADOPT).** Do not relitigate (a)-vs-(b).

Deciding numbers, both renders, precision / recall / frame FNR / per-bird-track FNR:
- **Synthetic** `sim/spike/out/spike_seed42`, thresh 0.05: (a) NDVI-direct **0.445 / 0.981 / 0.019 /
  0.000**; (b) synthetic RGB **1.000 / 0.981 / 0.019 / 0.000** → ADOPT (a) on the fidelity
  tiebreak. **0.445 is the bar any learned model must beat.**
- **Real render** `eval/results/clips/real_flight_20260823T073644Z` (1256 frames, measured
  applied-pose labels, thresh -0.61 / min_area 6 / max_area 5000, IoU 0.3): (a) **0.708 / 0.850 /
  0.150 / 0.000**, TP 17 / FP 7 / FN 3 over **20 visible bird-frames, 3/3 birds**, every bird seen
  before closest approach. (b) RGB **0.000 / 0.000 / 1.000 / 1.000** — and that is NOT a comparison
  result, see below. Artifact: `eval/results/adr003_20260823/`.
- Both re-run and reproduced **bit-identically** on 2026-08-24 after the detector moved into
  `src/fieldguard_planning/ndvi_detect.py` (numpy 1.26.4 / scipy 1.13.1 host).

**Still open, and neither is a detector problem:**
- **The -0.61 threshold stays PROVISIONAL.** It is the gate2 bird/soil pixel-class midpoint;
  amendment 7 proves it WORKS, not that it belongs there. Lifting it needs the false-positive
  characterisation (7 FP at n=20), not another passing run. Say this out loud whenever the number
  is quoted — the node prints it, `baseline_ndvi.py` prints it, and a test pins the word.
- **Criterion 2 has no comparison arm yet.** `baseline_rgb`'s "bright + achromatic" birdness is
  INVERTED on this world (dark birds, bright soil), so its 1.000 FNR measures the wrong signal, not
  RGB's ceiling. It needs an independent RGB pixel study, and deliberately has not been "fixed"
  blind — see [[eval-harness-core]].

**How to apply:** quote these numbers with their denominator attached (20 bird-frames is small; the
per-bird-track FNR moves in steps of 0.333). Any new detector claim re-runs `eval/run_spike.sh`
and `scripts/check_spike_regression.py`, and must not change the committed boxes without saying so.
See [[bird-label-timing]] for why the real-render labels are only scoreable from the driver's
applied-pose log.
