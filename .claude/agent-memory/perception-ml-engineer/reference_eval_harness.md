---
name: eval-harness-core
description: Structure and metric contract for the eval/ harness; score.py is the reusable core reused across all perception claims
metadata:
  type: reference
---

Eval harness lives under `eval/` (owned by perception-ml-engineer, CI wiring by
devops-reliability-engineer). Metric contract from `eval/README.md`: precision / recall /
**FNR (safety-critical, separate)**, detection range / lead-time, avoidance success rate,
coverage completeness, single-NDVI vs second-sensor deltas. `results/` is gitignored — commit
summary metrics into reports, not raw runs.

The NDVI-vs-RGB spike (see [[ndvi-rgb-spike]]) seeds the harness with:
`label_from_sim.py` (sim poses -> GT boxes), `baseline_ndvi.py` / `baseline_rgb.py` (blob
detectors), `score.py` (metrics core, reused for every later perception claim), and
`scenarios/*.yaml` for reproducible runs.

**How to apply:** any new "it works" perception/avoidance claim routes through `score.py` and
emits the same metric family; a missed bird (FN) is a safety bug reported apart from false
positives, never blended into one score.
