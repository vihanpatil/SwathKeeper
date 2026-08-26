# Tests

Unit + integration + **safety regression scenarios**. Owned across the team; safety scenarios by `qa-safety-reviewer`.

Every bug QA finds (missed detection, silently-skipped coverage cell, geofence breach) becomes a repeatable regression test here so it cannot silently return.

## How to run (all three work, from repo root)

This file is the **one home** for the suite totals; `README.md` and `SETUP.md` quote them from here.
Measured on the verified host 2026-08-26 — re-run all three and re-quote if you change any of them.

```bash
python3 -m unittest discover -s tests/fieldguard_planning   # 911 tests, OK (skipped=2) — the original CI invocation
python3 -m unittest discover -s tests -p 'test_*.py'        # 150 host-side tests, FAILED (failures=1) — see below
python3 -m pytest tests -q                                  # both at once: 1058 passed, 1 FAILED, 2 skipped, 0 xfail
```

**The 1 failure is deliberate and load-bearing:** `test_ci_evidence_gate…test_step_passes_on_the_
committed_evidence` is red because the committed 2026-08-25 take breached its GT-CPA bar and the
acknowledgement's second half is deliberately withheld (marker, no pin — runbook §6a). It stays red
until the clean re-fly; a run where it is the ONLY failure is the expected green-state of this tree.

`discover -s tests/fieldguard_planning` never walks `tests/test_*.py` (they're one level up and a
different discover pattern), so CI runs it as a **second, separate job** — a stale CI config silently
ran only the first for a while; both are gated now. That second command uses the pattern `test_*.py`,
not a filename: naming one file is how `tests/test_ci_evidence_gate.py` becomes invisible to it.

The planning root is **not** install-free: ten of its modules import numpy, and on a bare interpreter
`discover -s tests/fieldguard_planning` exits 1 with 614 of 822 green (unittest turns a module-scope
import failure into an ERROR, not a skip). `pip install -r requirements-eval.txt` first — see
`SETUP.md` §0, including its Python-version floor.

Two traps, learned 2026-08-18:
- **Bare `python3 -m unittest discover` (no `-s`) finds 0 tests and exits GREEN** — always pass the
  start dir. A vacuous green is worse than a red.
- There is deliberately **no `tests/fieldguard_planning/__init__.py`**: with it, pytest imported the
  tests dir AS the `fieldguard_planning` package, shadowing `src/` and breaking collection entirely
  (11 errors). Each test file does its own `sys.path.insert` of `src/`; don't add the init back.
