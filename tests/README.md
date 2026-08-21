# Tests

Unit + integration + **safety regression scenarios**. Owned across the team; safety scenarios by `qa-safety-reviewer`.

Every bug QA finds (missed detection, silently-skipped coverage cell, geofence breach) becomes a repeatable regression test here so it cannot silently return.

## How to run (both work, from repo root)

```bash
python3 -m unittest discover -s tests/fieldguard_planning   # 248 tests, the original CI invocation
python3 -m unittest discover -s tests -p 'test_fly_pipeline.py'   # 33 host-side launcher tests
python3 -m pytest tests/ -q                                 # both at once: 279 passed, 2 skipped
```

`discover -s tests/fieldguard_planning` never walks `tests/test_fly_pipeline.py` (it's one level up
and a different discover pattern), so CI runs it as a **second, separate job** — a stale CI config
silently ran only the first for a while; both are gated now.

Two traps, learned 2026-08-18:
- **Bare `python3 -m unittest discover` (no `-s`) finds 0 tests and exits GREEN** — always pass the
  start dir. A vacuous green is worse than a red.
- There is deliberately **no `tests/fieldguard_planning/__init__.py`**: with it, pytest imported the
  tests dir AS the `fieldguard_planning` package, shadowing `src/` and breaking collection entirely
  (11 errors). Each test file does its own `sys.path.insert` of `src/`; don't add the init back.
