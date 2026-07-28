# Evaluation harness

Owned by `perception-ml-engineer` (with `devops-reliability-engineer` for CI).

Runs scripted scenarios headless and emits metrics — no "it works" without a number:
- detection precision / recall, **false-negative rate** (safety-critical)
- detection range / lead-time-to-collision
- avoidance success rate, coverage completeness
- single-NDVI vs second-sensor comparison-arm deltas

`results/` is gitignored; commit summary metrics into reports, not raw runs.
