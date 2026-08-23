---
name: reference-safety-scenario-catalog
description: Where the SwathKeeper safety scenarios, regression files, ledger invariant and flight-log evidence live, and how to run them
metadata:
  type: reference
---

SwathKeeper safety scaffolding, owned by qa-safety-reviewer. Grows session over session — add new
files here, don't reset. Open gaps: [[project-open-safety-gaps]].

**Scenario layer (Week 2 origin)**
- Scenario specs (YAML, one per scenario, `name:` == filename): `eval/scenarios/*.yaml`
- Spec FORMAT + the coverage-debt ledger invariant (prose contract): `eval/scenarios/README.md`
- Generator that produces `eval/scenarios/<name>/flight_log.json`: `eval/scenarios/generate_flight_logs.py`
- Coverage grid + `check_ledger` invariant (executable): `src/fieldguard_planning/coverage.py`
- Self-activating assertions (skip until the scenario's `flight_log.json` exists, then go live with
  zero edits): `tests/fieldguard_planning/test_safety_scenarios_pending.py` — 4 of the scenarios now
  have logs and are live; the remaining skips are `det_bird_crosses_path`, `det_bird_over_low_ndvi`.

**Live-flight evidence layer**
- Flight-log evidence gate (ledger validity only — NOT separation): `scripts/check_live_flight_log.py`
- Committed flight logs are a gitignore EXCEPTION (`!eval/results/live_flight_log_*.json`), so tests
  may read them, but should skip if absent.
- Degenerate-range / vet-margin regressions off the 2026-08-23 delegated demo:
  `tests/fieldguard_planning/test_degenerate_range_avoidance.py` (36 tests, ~1.5 s). Conventions
  worth reusing: `test_CURRENT_*` pins today's behaviour including where it is wrong and names the
  recommendation that must break it; `test_WANT_*` is `@unittest.expectedFailure` and flips to a RED
  unittest run the moment a fix makes it true. **pytest treats an unexpected success as xpass (not
  red)** — the `unittest discover` job is what makes WANT tests bite, so always pair a WANT with a
  CURRENT pin, which fails under both runners.
- Mutation-check habit that paid off: copy `src/` to a scratch tree, apply the candidate fix,
  symlink `config/` + `eval/`, pre-import the patched package so the test file's own
  `sys.path.insert` is a no-op, then run the test module. Proves the new tests actually bite and
  exposes tests that ERROR (empty `min()`) instead of failing legibly.

**Run everything (stdlib only, no venv/ROS 2)**
```
python3 -m unittest discover -s tests/fieldguard_planning        # canonical CI job; WANT tests bite here
python3 -m unittest discover -s tests -p 'test_fly_pipeline.py'  # second CI job, host launcher
python3 -m pytest tests/ -q                                       # both at once
```
Baseline 2026-08-23 after the degenerate-range file: pytest 511 passed / 2 skipped / 2 xfailed;
unittest discover 463 tests OK (skipped=2, expected failures=2).

Detection FNR metric everything routes through: `eval/score.py` (`per_bird_track_fnr`).
