---
name: ndvi-rgb-spike
description: Week 1-2 spike framing that resolves ADR-003 (NDVI-direct vs synthetic-RGB detection); default, metric, and decision rule
metadata:
  type: project
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
