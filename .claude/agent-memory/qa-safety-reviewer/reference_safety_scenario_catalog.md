---
name: reference-safety-scenario-catalog
description: Where the FieldGuard safety scenarios, coverage-debt/geofence assertions, and the ledger invariant live and how to run them
metadata:
  type: reference
---

FieldGuard safety scaffolding (built Week 2 by qa-safety-reviewer). Grows session over session —
add new scenarios here, don't reset.

- Scenario specs (YAML, one per scenario, `name:` == filename): `eval/scenarios/*.yaml`
- Scenario spec FORMAT + the coverage-debt ledger invariant (prose contract) + open-gaps list:
  `eval/scenarios/README.md`
- Coverage grid + `check_ledger` invariant (executable): `src/fieldguard_planning/coverage.py`
- Running assertions (now, pure geometry): `tests/fieldguard_planning/test_coverage.py`,
  `tests/fieldguard_planning/test_mission_geofence.py`
- Pending, SELF-ACTIVATING assertions (skip until `eval/scenarios/<name>/flight_log.json` exists,
  then go live with zero edits): `tests/fieldguard_planning/test_safety_scenarios_pending.py`
- Detection FNR metric everything routes through: `eval/score.py` (`per_bird_track_fnr`).

Run all: `python3 -m unittest discover -s tests/fieldguard_planning -v` (stdlib only, no venv/ROS 2).
As of Week 2: 27 run+pass, 7 pending-skip.

Starter scenarios: nominal_coverage_baseline, nominal_geofence_baseline (both runnable-now);
cov_bird_over_cell, cov_bird_at_turnaround*, cov_two_birds_simultaneous*, det_bird_crosses_path,
det_bird_over_low_ndvi*, geo_avoid_into_tree* (pending; * = adversarial). See [[project-week2-open-safety-gaps]].

Flight-log contract the Week 3-4 avoidance loop must emit is defined in BOTH `eval/scenarios/README.md`
and the docstring of `test_safety_scenarios_pending.py` — keep the two in sync.
