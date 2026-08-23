---
name: eval-harness-core
description: Structure and metric contract for the eval/ harness; score.py is the reusable core, and it now has TWO refusal guards (denominator + label provenance)
metadata:
  type: reference
---

Eval harness lives under `eval/` (owned by perception-ml-engineer, CI wiring by
devops-reliability-engineer). Metric contract from `eval/README.md`: precision / recall /
**FNR (safety-critical, separate)**, detection range / lead-time, avoidance success rate,
coverage completeness, single-NDVI vs second-sensor deltas. `results/` is gitignored except a small
evidence allowlist (clip `meta.json`/`poses.jsonl`/`heatmap/`, `bird_drive_*` sidecars AND their
`_applied.jsonl` logs) — commit summary metrics into reports, not raw frames.

Pipeline: `annotate_real_clip.py` (real clips: bird labels from the driver's applied-pose log) →
`label_from_sim.py` (poses → GT boxes via the ONE `ndvi_georef.project_world_point` primitive) →
`baseline_ndvi.py` / `baseline_rgb.py` (the shared `blob.py` detector) → `score.py`. One-shot:
`eval/run_spike.sh` with `CLIP=` / `RESULTS=` env overrides.

**`score.py` refuses rather than deciding, on two independent grounds — both were live defects:**
1. **Denominator** (`evidence_shortfall`, 2026-08-21): ≥1 visible bird-frame AND every bird in the
   clip seen at least once, checked BEFORE the rates. It used to print `ADOPT` on an empty ground
   truth, four zeros reading as a clean sweep.
2. **Label provenance** (2026-08-22, ADR-003 am. 6): every visible GT box carries `label_src`, and
   `modeled`/`unknown` labels are refused. A full denominator with estimated positions produced a
   confident `AMBIGUOUS → default to (a)` from labels 198 px off the bird. Scoreable sources:
   `generator` (synthetic), `spawn` (static model unmoved — exact), `applied` (driver log).
   See [[bird-label-timing]].

Real-clip regression gate: `tests/fieldguard_planning/test_bird_label_timing.py` runs against the
COMMITTED flagship clip (not a fixture) and pins both halves of the diagnosis — the detections are
birds at a lagged time, and the modelled labels are ≥94.98 px away with IoU 0.000.

**How to apply:** any new "it works" perception/avoidance claim routes through `score.py` and emits
the same metric family; a missed bird (FN) is a safety bug reported apart from false positives,
never blended. Before quoting any rate from a real clip, check what the `labels =` line says.
