---
name: ship
description: Pre-PR checklist — gates, suite-total homes, tests:src, roadmap row, commit, push, open the PR (never merge)
argument-hint: "[branch or PR title]"
disable-model-invocation: true
---

Ship the current branch as a PR. Target: $ARGUMENTS. Stop and report at the first failed step.

1. **Gates.** Run `/gates` (`scripts/gates.sh`). Anything not in its expected state stops the ship.
2. **Suite totals.** If any test was added or removed, re-run all three commands in
   `tests/README.md` with `.venv/bin/python` and re-quote the totals at ALL three homes —
   `tests/README.md`, the `README.md` evidence table, `SETUP.md` §(b) — or at none.
   `tests/test_suite_totals_one_home.py` enforces it; run it.
3. **tests:src ratio.** Measure `src/**/*.py` lines (ADR-022 am. 4) vs `tests/**.{py,sh}` lines
   against the 3.70 cap (3.33 since 2026-11-05, by dilution; OVER at 3.84 from 2026-09-11). If this branch adds a test file, name the
   test file it retires; no new test file ships without one.
4. **Roadmap.** `docs/ROADMAP.md` "Repo state" row names this branch, its head, and its PR as they
   will be after the push.
5. **Commit** in the house style: `type(scope): what landed — the measured numbers, and what is NOT
   done`. End with the attribution trailer the session gives. Only the paths this work changed.
6. **Push** the branch (never `main`, never `--force` without the owner's word).
7. **`gh pr create`** with a body in two parts: *Verified* (each command run, its result) and
   *Not verified / CI-only* (what only the runner or a live flight exercises). Declared reds named
   exactly.
8. **Never merge.** The owner merges. Report the PR URL and the CI run to watch.
