# Tests

Unit + integration + **safety regression scenarios**. Owned across the team; safety scenarios by `qa-safety-reviewer`.

Every bug QA finds (missed detection, silently-skipped coverage cell, geofence breach) becomes a repeatable regression test here so it cannot silently return.

## How to run (both work, from repo root)

```bash
python3 -m unittest discover -s tests/fieldguard_planning   # the CI invocation
python3 -m pytest tests/ -q
```

Two traps, learned 2026-08-18:
- **Bare `python3 -m unittest discover` (no `-s`) finds 0 tests and exits GREEN** — always pass the
  start dir. A vacuous green is worse than a red.
- There is deliberately **no `tests/fieldguard_planning/__init__.py`**: with it, pytest imported the
  tests dir AS the `fieldguard_planning` package, shadowing `src/` and breaking collection entirely
  (11 errors). Each test file does its own `sys.path.insert` of `src/`; don't add the init back.
