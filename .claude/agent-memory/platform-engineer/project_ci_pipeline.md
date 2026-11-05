---
name: project-ci-pipeline
description: CI job map (incl. the 2026-09-10 if-always + KNOWN_RED allowlist rework and the Pages workflow), the exact local repro commands, and the measured trap that only ONE test root is install-free
metadata:
  type: project
---

**Workflows:** `.github/workflows/ci.yml`, `sim-image.yml`, and (new 2026-09-10) `pages.yml`.
CI runs on `ubuntu-latest`, `python-version: "3.12"` via `actions/setup-python@v5`.

`ci.yml` — **four jobs**:

1. `validate-config` — `scripts/validate_agents.py` (needs `pyyaml`, installed inline/unpinned in
   that job; see [[reference_pinned_versions]]).
2. `planning-and-eval` — the real gate. **Install-before-test is load-bearing** (a 2026-08-18
   reorder left it red 12 days with the seed-42 FNR gate never executing), and it needs **both**
   discover roots: `-s tests/fieldguard_planning` never walks `tests/test_*.py`.
   **2026-09-10 rework (R1):** every step from *Host-side test suite* down carries `if: always()`,
   because this repo runs a DECLARED red (the 2026-08-25 breach) and a failing step skips all the
   rest — the seed-42 regression, scenario regenerate+diff and generator smoke were dark 16 days
   and two Linux-only reds rode in unnoticed. A dedicated step runs
   `tests/test_known_red_allowlist.py`, which re-runs both roots in child processes and asserts the
   failing set is EXACTLY the `KNOWN_RED` allowlist (undeclared red / vacuous entry / expired entry
   all FAIL). It costs ~2 min per invocation and CI pays it twice (the host-side suite collects it
   too). `tests/test_ci_evidence_gate.py` pins the `if: always()` shape and that the allowlist step
   refuses an empty match.
3. `docs-site` — `scripts/build_docs_site.py`; its link + heading-parity gates are the repo's only
   automated doc-integrity check (ADR-014), and they DO fail the build.
4. `build-test-sim` — `workflow_dispatch`-only, **never once green**; see [[project_week5_ci_gazebo]]
   before touching it or flipping its trigger.

`pages.yml` — builds `_site/` = `dashboard/` + `eval/results/live_flight_log_*` (copied at build
time; the page reads the evidence in place, it is no longer duplicated under `dashboard/data/`) +
`docs/` from `build_docs_site.py`, then `configure-pages@v5` / `upload-pages-artifact@v3` /
`deploy-pages@v4`. It REFUSES to publish a stale `dashboard/data/` (`--check`, no silent rebuild).
**Requires a human to set Settings → Pages → Source: GitHub Actions once**; until then the deploy
job fails and nothing in the repo can tell you it is off. Its assembly block is executed by
`tests/test_dashboard_data_paths.py`, so the served layout is tested rather than described.

**Measured trap (clean Python 3.12 venv, nothing installed, 2026-08-25):** only
`python3 -m unittest discover -s tests -p 'test_*.py'` is genuinely install-free.
`discover -s tests/fieldguard_planning` **exits 1** on a bare interpreter — ten modules import numpy
at module scope, and unittest's loader turns that into `_FailedTest` ERRORs, not skips. Same reason
CI installs `requirements-eval.txt` first. **CI installs no pytest** — anything a test shells out to
must be `unittest`.

Local verification (run these, in this order, before touching the pipeline):
```
python3 -m unittest discover -s tests/fieldguard_planning
python3 -m unittest discover -s tests -p 'test_*.py'      # now ~3 min: it runs the allowlist gate
python3 -m pytest tests -q -p no:cacheprovider            # both roots at once
pip install -r requirements-eval.txt            # numpy/scipy/markdown, the only Python pins
python3 sim/spike/gen_spike_clip.py --seed 42 --out sim/spike/out/spike_seed42
CLIP=sim/spike/out/spike_seed42 bash eval/run_spike.sh
python3 scripts/check_spike_regression.py eval/results/spike_scores.json
python3 scripts/check_live_flight_log.py eval/results/live_flight_log_*.json
python3 scripts/build_dashboard_data.py --check
python3 scripts/build_docs_site.py
actionlint .github/workflows/*.yml              # brew install actionlint if missing
shellcheck scripts/fly_pipeline.sh
```
Current counts live in `docs/ROADMAP.md` / `tests/README.md` (and `tests/test_suite_totals_one_home.py`
now enforces that those homes agree with the tree), not here.

**The seed-42 spike chain is NOT dead weight** (audit finding D8, checked 2026-09-10 and REFUTED):
`eval/baseline_ndvi.py` imports `src/fieldguard_planning/ndvi_detect.py` — the ADOPTED, FLOWN
detector (ADR-003 am. 8, "the live node and the eval harness now run the same lines"), and
`test_ndvi_detect.py`'s full-clip re-score is skipped in CI. Those three steps are the flown
detector's ONLY CI regression gate. Keep them.

**Docs that quote outputs rot silently:** `SETUP.md` §0 quotes measured stdout. Re-run and re-quote
rather than deleting the numbers.
