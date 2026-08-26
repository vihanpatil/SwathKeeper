---
name: ndvi-rgb-spike
description: ADR-003 NDVI-vs-RGB — DECIDED and CLOSED (am. 7, ADOPT); the live numbers on both renders, the 0.445 bar, the first IN-AIR evidence (2026-08-25), and what is still open
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
  0.150 / 0.000**, TP 17 / FP 7 / FN 3 over **20 visible bird-frames, 3/3 birds**. Artifact:
  `eval/results/adr003_20260823/`.
- Both re-run and reproduced **bit-identically** on 2026-08-24 after the detector moved into
  `src/fieldguard_planning/ndvi_detect.py` (numpy 1.26.4 / scipy 1.13.1 host).

## First IN-AIR evidence — 2026-08-25 take, `real_flight_20260825T205705Z`
Artifact `eval/results/adr003_20260825/` (ground_truth / detections_ndvi / detections_rgb /
spike_scores / visibility_budget / `clipview/` — a symlink view so the raw clip stays unmutated;
`annotate_real_clip.py --in-place` is not always permitted, and `label_from_sim` reads only
`poses.jsonl`).

- **`score.py` REFUSED, correctly: EVIDENCE INSUFFICIENT — 1 of 3 birds ever visible.** Ground
  truth (measured `applied` labels, 0 modeled) says the whole 3310-frame clip contained
  **2 visible bird-frames**, both bird_0, clip frames 964/965. bird_1 and bird_2 had **zero**
  opportunities. Not a confirmation and not a refutation of ADR-003.
- On that 2-frame denominator: (a) **TP 2 / FP 0 / FN 0**, precision 1.000, recall 1.000, FNR
  0.000. (b) RGB 0 / 3 / 2 — still the INVERTED-birdness artifact, still not a comparison.
- **Live↔offline equivalence, 1 micrometre.** The offline harness re-derived both world positions
  to `|Δ| = 1e-6 m` of the flight log's own `Detection.position_enu`, across **scipy 1.8.0 in the
  air (jammy `python3-scipy`) vs 1.13.1 on the host** — and agreed on all 1301 in-window frames
  (2 boxes each). That closes ADR-013's "transfer verified on ONE scipy version" caveat with a
  third version measured in flight.
- **The 2 boxes:** bird pixels 79 % of the box below threshold, core p10 −0.80, warmest bird pixel
  **−0.6697**; box r_px 22.75 vs a true apparent 23.70 (morphology erodes ~4 %); est depth 3.4286 m
  vs true 3.95 m (the deliberate 0.15/0.18 radius prior, fail-near as documented). XY error vs GT
  0.29 / 0.11 m — most of that is the known label lag, not the estimator.

## The threshold: the FP side is now characterised, the range side is not
Measured over **all 3310 frames (1.02 Gpx)** of the 2026-08-25 clip: the darkest non-bird pixel in
the entire take is **−0.4406**, on every single frame, and **zero** pixels anywhere fall below
−0.50. Bird pixels top out at −0.6697. So −0.61 sits inside a **0.229-wide empty band** and *any*
value in (−0.6697, −0.4406) is bit-identical on this clip. A typical cruise frame has only **two
distinct NDVI values** (−0.4406/−0.4377 soil); the bird is the only wide excursion.
Re-reading the adopted clip's 7 FP with this: 2 of 7 sit 7–15 px from a real bird (IoU 0.248 —
label lag, not cry-wolf), 3 sit 120–234 px away (inside the known 198 px mean label lag), 1 has no
GT box at all. **Background false positives are close to non-existent on this world.**
What is still uncharacterised is the **RANGE** limit: the threshold has only ever been exercised at
~4 m depth where the bird is 47 px wide. Derived (not measured) bound — a bird needs r_px ≈ 2.2 to
put 6 interior pixels below threshold, i.e. depth ≲ 40 m — meaning **the FOV, not the threshold, is
what limits detection range** (see [[sensor-horizon-vs-threat-cylinder]]). PROVISIONAL should be
lifted on a clip with birds at 3+ distinct ranges, not on another pass at 4 m.

**Still open:**
- **−0.61 stays PROVISIONAL**, but the reason narrowed again on 2026-08-26: the range side IS
  exercised at 3.9 / 6.9 / 9.0 m on the adopted clip (all cores ≤ −0.8276), so "only ever at ~4 m"
  describes the 08-25 clip alone. What is left: nothing beyond ~11 m, and n=20 with 8 ambiguous.
- ~~**Criterion 2 has no comparison arm.**~~ **ANSWERED 2026-08-26** — the arm works now
  (GRVI, not min-channel) and matches NDVI on every safety metric at 0.227 precision vs 0.708.
  See [[criterion2-rgb-study]]; recommendation to product-lead is RETIRE-ARM, unratified.

**How to apply:** quote every rate with its denominator attached. Any new detector claim re-runs
`eval/run_spike.sh` + `scripts/check_spike_regression.py`. See [[bird-label-timing]] for why real
clips are only scoreable from the driver's applied-pose log, and [[eval-harness-core]] for the
refusal guards.
