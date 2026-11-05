---
name: criterion2-rgb-study
description: ADR-003 criterion 2 ANSWERED 2026-08-26 — RGB's real ceiling on this world, the GRVI birdness that replaced the inverted min-channel, and why the arm is not a second sensor (recommendation RETIRE-ARM)
metadata:
  type: project
---

**Criterion 2's independent RGB pixel study RAN and produced an answer** (2026-08-26,
`eval/rgb_pixel_study.py`, evidence `eval/results/criterion2_rgb_study_20260826T022846Z/results.json`,
~3 min host, no Docker). Recommendation to product-lead: **RETIRE-ARM**. Not yet ratified — no ADR
amendment written, no `docs/` update beyond `eval/README.md`.

## The numbers (denominators attached)
Measured over **both committed real clips, every frame: 4,566 frames / 1.4027 Gpx / 16,686 bird
pixels on 22 frames / 3 birds at 3.9, 6.9, 9.0 m depth** (bird_0 8,401 px, bird_1 3,565, bird_2 4,720).

- **`baseline_rgb`'s old birdness was the wrong FEATURE, not the wrong sign.** min-channel
  bird=HIGH cannot beat FNR 0.99994 at any threshold; flipped, best is FNR 0.0042 at FPR 3.03e-03
  — **482.3x** the false-positive rate of the chromatic feature. Never "just flip the polarity".
- **The signal is chromatic.** Soil (138,161,115) and canopy are green-dominant; all three bird
  materials are not. `GRVI = (G-R)/(G+R)`, bird = LOW, thresh **+0.0322** (bird/background class-mean
  midpoint, -0.01260784 vs +0.07695006 — the same construction as NDVI's -0.61 from gate2).
  At it: pixel FNR 0.0360, FPR 5.111e-06. Detector window `[0.005, 0.07]`, **not empty** (soil sits
  0.045 above; two bird materials render G-R = 0 *exactly*, so `< 0` loses their cores).
- **Detector arm, same blob code / same score.py / same GT.** 08-23 (n=20 bird-frames, 3 birds):
  (a) NDVI TP17 FP**7** FN3 P**0.708**; (b) RGB-GRVI TP17 FP**58** FN3 P**0.227**. 08-25 (n=2,
  1 bird): (a) 2/0/0 P1.000; (b) 2/**52**/0 P0.037. **Per-bird tables are IDENTICAL** (2/2, 4/5,
  11/13, all detected before closest approach). RGB matches NDVI exactly on every safety metric and
  loses only precision. ADR-003's rule still fires ADOPT (a), now with gap **+0.000** against a
  working arm instead of -0.850 against a broken one; `run_spike.sh` on the adopted clip prints it.
- **All 103 FP boxes the RGB arm adds land inside the 2 m ADR-001 tree geofence.** Cause: trunk
  material `0.35/0.22/0.10` vs bird_1 `0.30/0.22/0.10` — same brown to 0.05 in red, and the trunk is
  the *more* bird-like in GRVI, so **per-bird `fnr_at_zero_fpr` = 1.000 for all three birds**: no
  threshold catches one bird pixel without catching trunk. Thermal resolves it (gate 2: trunk -0.026
  vs bird -0.789); visible bands cannot.
- **The Bayes-optimal colour-cube ceiling is memorisation, and the study proves it.** In-sample
  FNR 0.0192 @ FPR 0 / FPR 1.911e-07 @ FNR 0. Leave-one-bird-out the same LUT scores FNR
  **0.9998 / 1.0000 / 0.9998**; the one-parameter GRVI rule scores 0.032 / 0.010 / 0.064 at FPR
  5.11e-06 and transfers across clips too. **Honest ceiling: FNR ~0.03 at FPR ~5e-06.**

## The finding that decides it: the arm is NOT a second sensor (measured, not quoted)
Inverting NDVI with `rho_red = R/255` from the RGB PNG collapses **72–93 distinct 8-bit red levels
onto exactly 3 ρ_nir values (24–31× collapse): 0.040333 / 0.211666 / 0.854167**, on every frame
tested. **The COLLAPSE is the proof** — only bit-for-bit band identity folds dozens of red levels
onto a handful of reflectances. So the RGB PNG's R channel **is** the NDVI Red band: the "second
sensor" shares band, sensor, optics, mount, FOV and frame clock, contributes only G and B, and
cannot buy range or lead time — which is what criterion 2 asks. Real bottleneck is geometric
(2.48 m horizon, 0.175 s lead, 5 of 7 in-cylinder frames outside the edge) → **ADR-017's
forward-facing sensor**, priced with `predict_bird_visibility.py`, not with pixels.
**Do NOT call those values "authored"** — they are `gate2_summary.json`'s *measured* `mean_rho_nir`,
not `config/ndvi_camera.json`'s *authored* `calibrated_rho_nir` (0.05/0.20/0.85, −19.3/+5.8/+0.5 %).
gate2 came from the same pipeline, so the value match is self-consistency + code identity
(`ndvi_fusion.rescale_red:85-87`), **not** cross-validation against config.
Pinned by `tests/fieldguard_planning/test_rgb_pixel_study.py` so it goes red if that ever changes.

## Why GRVI ships when it is 8th of 12 on the pixel table (the reviewer objection, foreclosed)
G−B beats GRVI on pixel FNR (0.00082 vs 0.00306) and by 3 orders of magnitude on `fpr_at_zero_fnr`
— **and at its own class-mean midpoint (+26.2554) it scores per-bird-track FNR 0.333: it never sees
bird_1 (0 of 5 frames), whose brown G−B of 24 sits on the background minimum of 23.** GRVI / ExG /
G−R all hold **0.000** at precision 0.227 / 0.230 / 0.218 — statistically the same. **The DETECTOR
decides which feature ships; the pixel table only shortlists.** Any future feature proposal runs
`rival_features` in the study before it is believed.

## The committed artifacts were REGENERATED (adversarial QA F1, 2026-08-26)
`eval/results/adr003_20260823/` and `adr003_20260825/` held the superseded min-channel arm, so
re-scoring the **committed** evidence — the reproducible path, and the one an interviewer takes —
printed gap **−0.850** and arm-(b) FNR **1.000**, the exact numbers this study retires. Both
`detections_rgb.json` + `spike_scores.json` regenerated with the GRVI arm (75 and 54 detections);
08-23 now prints **gap +0.000 → ADOPT**, 08-25 still prints **EVIDENCE INSUFFICIENT**. Arm (a) is
untouched and re-verified (TP 17 / FP 7 / FN 3 / 0.708 / 0.850). Pinned red-first by
`TestTheCommittedArtifactsAgreeWithTheStudy`, including a self-consistency check that
`spike_scores.json` matches a fresh re-score of the detections beside it.
**`docs/DECISIONS.md` ADR-003 am. 7 ("Arm (b) 0.000 across the board") and am. 9 ("TP 0 / FP 3 /
FN 2") now contradict the artifacts they cite** — tech-lead's amendment must correct them.

## Correction owed to the record
- ADR-003 am. 9 / ROADMAP item 3 say -0.61 "has only ever been exercised at ~4 m depth on a 47 px
  bird". True of the 08-25 clip; it **understates the adopted 08-23 clip**, whose bird cores sit at
  3.9 / 6.9 / 9.0 m (radii 22.6 / 13.4 / 10.4 px) and all read <= -0.8276. The RANGE half is
  **narrowed, not closed** — nothing measured beyond ~11 m, r_px ~2.2 -> ~40 m stays DERIVED, n=20
  with 8 ambiguous stands. **PROVISIONAL not lifted.**
- ADR-003 am. 1 quotes bird `color_rgba 0.12 / 0.30 / 0.18` — that is the RED channel of each of the
  three birds read as one triple. Real: bird_0 `0.12/0.12/0.12`, bird_1 `0.30/0.22/0.10`,
  bird_2 `0.18/0.18/0.20`. "Dark" survives; the chromatic structure it hid is the whole finding.

**How to apply:** never quote `baseline_rgb`'s old 1.000 FNR as RGB's ceiling — quote 0.227-vs-0.708
precision at equal safety instead. Any RGB claim re-runs the study; the threshold is recomputed from
its results.json by test, so moving one without the other fails. See [[ndvi-rgb-spike]] for the ADR-003
verdict itself, [[sensor-horizon-vs-threat-cylinder]] for why the geometry, not the spectrum, binds.
