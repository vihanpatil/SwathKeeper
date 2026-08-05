---
name: feedback-bug-hunter-not-yaml-author
description: For this role, actually run everything locally (real venv, real interpreter version) before touching CI YAML — don't just write plausible-looking workflow steps
metadata:
  type: feedback
---

When wiring new work into CI, the expectation is bug-hunter first, YAML author second. Concretely,
before writing/editing `.github/workflows/ci.yml`:
1. Build a venv matching the CI Python version exactly (this repo pins `python-version: "3.12"`;
   local default was 3.13 — `brew install python@3.12` / `/opt/homebrew/bin/python3.12 -m venv` to
   get a real match, don't just reason about version-sensitive code from memory).
2. Actually execute every command you're about to put in a CI step, in that venv, from a
   clean/moved-aside state for any gitignored generated dirs (e.g. `eval/results/`,
   `sim/spike/out/`) to catch "assumes it already exists" bugs.
3. Re-run twice to check determinism claims before asserting them in a regression gate (diffed
   `eval/results/spike_scores.json` byte-for-byte across two independent regenerations — this is
   what justified the fixed-seed regression assertion in `scripts/check_spike_regression.py`).
4. Don't blindly chain new scripts with `set -euo pipefail`: read exit-code semantics first. Found
   one script (`scripts/check_mission_geofence.py`) that returns 1 by design on a
   documented-safe finding, not an error — see [[known_ci_flake_check_mission_geofence]]. Wiring it
   into CI without noticing would have made the build permanently red for a non-bug.
5. Validate workflow YAML with `actionlint` (installed via `brew install actionlint` when not
   present) rather than only a bare `yaml.safe_load` — catches schema-level mistakes a plain parse
   misses.
6. Never claim "CI is green" — this environment can't run GitHub Actions or Docker/Gazebo. State
   precisely which commands were executed-and-verified locally (with real output/counts) vs. what
   only the actual runner will exercise.

**Why**: explicit instruction from the human on the Week 2 CI task — Week 1 shipped with several
small bugs from work that was written but not run. The fix is cheap (run the venv, run the script)
relative to the cost of a future demo-day CI red X or, worse, a green CI that was never actually
exercised.

**How to apply**: treat this as the standing default for every future CI/reproducibility task on
this repo, not a one-off for Week 2.
