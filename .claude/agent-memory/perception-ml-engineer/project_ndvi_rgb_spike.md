---
name: ndvi-rgb-spike
description: ADR-003 NDVI-vs-RGB spike — RAN 2026-08-04, recommend ADOPT (a) NDVI-direct on synthetic clip (provisional, pending Gazebo render)
metadata:
  type: project
---

**RESOLVED (provisionally) 2026-08-04.** Ran the harness end-to-end on synthetic clip
`sim/spike/out/spike_seed42` (seed 42, 3 birds). Numbers (frame precision/recall/FNR):
- (a) NDVI-direct: **0.445 / 0.981 / 0.019**, per-bird-track FNR **0.000**.
- (b) synthetic RGB: **1.000 / 0.981 / 0.019**, per-bird-track FNR **0.000**.
Both clear the FNR bar; gap 0.000 → **ADOPT (a)** on fidelity tiebreak. The feared NDVI wash-out on
the bird-over-soil hard case (`bird_1`) did NOT happen (bird reads negative NDVI, soil ~0.15). All
66 of (a)'s false positives are the ONE static `clutter_0` feature → suppressible by the planned
static-obstacle map + blob motion-tracking, not random noise. **Caveat:** clip is SYNTHETIC (not a
Gazebo render); numbers validate the harness + give a strong first signal — confirm on the real
render before treating ADR-003 as final. tech-lead records the ADR (I did not edit DECISIONS.md).
Outcome written to `docs/SPIKE_ndvi_vs_rgb.md`. Baseline params: NDVI thresh 0.05, RGB min-channel
thresh 110, IoU 0.3, blob min_area 6.

---

Spike plan written 2026-07-27 at `docs/SPIKE_ndvi_vs_rgb.md` to resolve ADR-003
(detect on NDVI-rendered frames vs. render a synthetic RGB pass for perception).

- **Recommended default going in: (a) NDVI-direct** — matches the real single-NDVI-camera
  hardware. Spike exists to try to falsify that cheaply, not rubber-stamp it.
- **Decision metric:** precision / recall / **false-negative rate (FNR, the safety-critical one,
  reported separately, never averaged in)** on one short (~20-40s, 2-3 birds) scripted-bird clip
  rendered twice (NDVI + RGB) from the same seed/flight. Detection = box with IoU >= 0.3 vs GT.
  Ground truth is generated from sim (bird actor poses + camera intrinsics + SITL telemetry
  projected to image boxes), not hand-labeled.
- **Decision rule:** keep (a) unless it is clearly unsafe. Adopt (a) if per-bird FNR <= 0.10 and
  within 0.10 FNR of (b). If (a) misses and (b) materially better (FNR gap > 0.10), escalate to
  product-lead (fidelity vs safety). Ambiguous -> default (a) + follow-up, do not extend spike.
- **Baseline is classical CV first:** NDVI threshold + morphology + blob detection. No trained
  model unless it beats this baseline on the same harness.
- **Time-box: 3 working days**, gated on the sim clip.

**Why:** the choice sets fidelity of the whole perception->avoidance loop (priority #1); picking
RGB for convenience would make the demo depend on a sensor the real drone lacks.

**How to apply:** don't design detector architecture beyond the blob baseline until ADR-003 is
settled. Note the RGB render is not wasted even if (a) wins — it becomes the NDVI+RGB
comparison-arm config. See [[eval-harness-core]].
