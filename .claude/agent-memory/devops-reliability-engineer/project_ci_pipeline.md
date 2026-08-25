---
name: project-ci-pipeline
description: CI job map, the exact local repro commands, and the measured trap that only ONE test root is truly install-free (re-verified 2026-08-25)
metadata:
  type: project
---

CI lives at `.github/workflows/ci.yml`, `ubuntu-latest`, `python-version: "3.12"` via
`actions/setup-python@v5`. **Four jobs** (as of 2026-08-25):

1. `validate-config` — `scripts/validate_agents.py` (needs `pyyaml`, installed inline/unpinned in
   that job; see [[reference_pinned_versions]]).
2. `planning-and-eval` — the real gate. **Install-before-test is load-bearing** (a 2026-08-18
   reorder left it red 12 days with the seed-42 FNR gate never executing), and it needs **both**
   discover roots: `-s tests/fieldguard_planning` never walks `tests/test_*.py`.
3. `docs-site` — `scripts/build_docs_site.py`; its link + heading-parity gates are the repo's only
   automated doc-integrity check (ADR-014), and they DO fail the build.
4. `build-test-sim` — `workflow_dispatch`-only, **never once green**; see [[project_week5_ci_gazebo]]
   before touching it or flipping its trigger.

**Measured trap (clean Python 3.12 venv, nothing installed, 2026-08-25):** only
`python3 -m unittest discover -s tests -p 'test_*.py'` is genuinely install-free (57 tests, OK).
`discover -s tests/fieldguard_planning` **exits 1** on a bare interpreter — ten modules import numpy
at module scope, and unittest's loader turns that into `_FailedTest` ERRORs, not skips (614 tests
still run green). `tests/README.md` and any "needs no install at all" phrasing are wrong at that
level of precision; `SETUP.md` §0 now states it with the numbers. Same reason CI installs
`requirements-eval.txt` first.

Local verification (run these, in this order, before touching the pipeline):
```
python3 -m unittest discover -s tests/fieldguard_planning
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m pytest tests -q                      # both roots at once
pip install -r requirements-eval.txt            # numpy/scipy/markdown, the only Python pins
python3 sim/spike/gen_spike_clip.py --seed 42 --out sim/spike/out/spike_seed42
CLIP=sim/spike/out/spike_seed42 bash eval/run_spike.sh
python3 scripts/check_spike_regression.py eval/results/spike_scores.json
python3 scripts/check_live_flight_log.py eval/results/live_flight_log_*.json
python3 scripts/build_docs_site.py
actionlint .github/workflows/ci.yml             # brew install actionlint if missing
```
The whole set is ~1 minute of compute on the host; the spike chain alone is 17 s. Current counts
live in `docs/ROADMAP.md` and `README.md`, not here.

**Docs that quote outputs rot silently:** `SETUP.md` §0 quotes measured stdout (test counts,
gate lines, cadence). No test pins them — if the suite counts or a gate's wording move, re-run the
section's commands and re-quote. Prefer that over deleting the numbers: a tier with no expected
output can't tell a reader whether it worked.
