# Evaluation harness

Owned by `perception-ml-engineer` (with `devops-reliability-engineer` for CI).

Runs scripted scenarios headless and emits metrics — no "it works" without a number:
- detection precision / recall, **false-negative rate** (safety-critical)
- detection range / lead-time-to-collision
- avoidance success rate, coverage completeness
- single-NDVI vs second-sensor comparison-arm deltas (Weeks 5-6)

**What exists now:**
- `score.py` — the reusable metric core (precision / recall / **FNR** / per-bird-track FNR); the seed of
  the permanent harness. Run the full NDVI-vs-RGB spike with `run_spike.sh` (needs `requirements-eval.txt`).
- `label_from_sim.py`, `baseline_ndvi.py`, `baseline_rgb.py` — the ADR-003 spike pipeline.
- `scenarios/` — the QA safety scenarios (spec + coverage-debt invariant); `generate_flight_logs.py`
  drives the real avoidance loop to produce each scenario's `flight_log.json`, activating its assertion.

`results/` is gitignored (raw runs, incl. the live demo's timestamped `live_flight_log_<UTCstamp>.json`); commit summary
metrics into reports, not raw runs.
