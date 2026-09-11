"""The failing set of this repo's own test suite, declared — `KNOWN_RED` and nothing else.

WHY THIS EXISTS. `main`'s CI is red on purpose: the 2026-08-25 real-detection take breached its own
pre-registered clearance bar, the safety gate calls that log INVALID, and
`tests/test_ci_evidence_gate.py` fails because the committed evidence really does not pass its own
gate. Keeping that visible is the point (`docs/runbooks/AVOIDANCE_REAL_DETECTION.md` §6a: "write the
marker, do **not** add the pin, and let the take stand at **INVALID / exit 1**").

But a permanent red is a blindfold. Between 2026-08-25 and 2026-09-10 that one declared failure sat
on `main` while TWO further failures (`tests/test_build_dashboard_data.py`, Linux-only float and
staleness reds) rode in behind it unnoticed, and every CI step after the failing one — the seed-42
FNR regression, the scenario regenerate+diff, the generator smoke — was SKIPPED for 16 days. "CI is
red, on purpose" only stays true if somebody names, every push, exactly WHICH red.

So this file is the declaration. It re-runs both test roots in a child process (excluding itself)
and asserts the failing set is EXACTLY `KNOWN_RED`. Three failure modes, each a real finding:

  * an UNDECLARED failure         -> something broke and the standing red hid it;
  * a declared failure that PASSES -> the allowlist has gone vacuous; delete the entry (a red that
                                     cannot happen proves nothing, and this suite has 1,602 tests
                                     that could be quietly protecting the wrong thing);
  * an entry past its `expires`    -> nobody re-read a failure in months. An allowlist without
                                     expiry dates is a landfill.

COST, STATED. The child runs are the whole suite, both roots, sequentially: ~2 min on the
2026-09-10 host (44 s for `tests`, ~78 s for `tests/fieldguard_planning`), and the suite that
contains this file pays it again. That is deliberate on both counts — the only honest way to know
the failing set is to produce it, and the roots are NOT run in parallel because tests in the two
roots touch some of the same paths and a flaky honesty gate is worse than a slow one. It runs
`unittest`, not `pytest`, because `unittest discover` is what CI itself runs (and CI installs no
pytest), so the set measured here IS the set CI reports.

Lives in tests/ (not tests/fieldguard_planning/) like test_ci_evidence_gate.py and
test_fly_pipeline.py: it tests a host-side artifact — the state of CI — not the planning package.
"""
import datetime as _dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SELF_MODULE = Path(__file__).stem          # excluded from the child run: it IS the child run

# The two roots, in CI's own order and with CI's own patterns (.github/workflows/ci.yml, job
# `planning-and-eval`). Both are needed: `discover -s tests/fieldguard_planning` never walks
# tests/test_*.py, and `discover -s tests` does not recurse into the package-less subdirectory.
ROOTS = ("tests/fieldguard_planning", "tests")

# ================================================================================================
# THE DECLARATION
# ================================================================================================
# test id (pytest style: <path>::<Class>::<method>) -> why it is red, and when that reason expires.
#
# RULES FOR ADDING AN ENTRY (they are the whole value of the mechanism):
#   * the reason names the EVIDENCE that makes the failure correct, not the symptom;
#   * `expires` is a date by which the red must be fixed or re-argued. On that date this test goes
#     red and someone re-reads the finding. Pick a date you would actually defend.
#   * an entry is never added to make a build green. A genuine regression is fixed, not declared.
KNOWN_RED = {
    "tests/test_ci_evidence_gate.py::TestLiveFlightLogGateHasEvidence"
    "::test_step_passes_on_the_committed_evidence": {
        "reason": (
            "PRE-REGISTERED. The 2026-08-25 real-detection take flew 0.0067 m from bird_0 against "
            "a 3.00 m bar, so scripts/check_live_flight_log.py reports it INVALID and exits 1 on "
            "the committed evidence — which is exactly what this test runs. "
            "docs/runbooks/AVOIDANCE_REAL_DETECTION.md §6a: 'write the marker, do **not** add the "
            "pin, and let the take stand at **INVALID / exit 1**. That is the correct record for a "
            "flight that breached.' The red clears when the take is RE-FLOWN and clears its bar; "
            "silencing it by pinning a third stem in ACKNOWLEDGED_BREACH_STEMS is the one thing "
            "§6a forbids."
        ),
        "expires": "2026-12-31",
    },
}


# ================================================================================================
# the child run — ids come from unittest itself, never from parsing a runner's prose
# ================================================================================================
def _pytest_id(root: str, uid: str) -> str:
    """A unittest `TestCase.id()` rendered the way CI logs, READMEs and this allowlist spell it."""
    if uid.startswith("unittest.loader._FailedTest."):
        # A module that could not be imported. Named as the file so the reader goes to the file.
        return f"{root}/{uid.rsplit('.', 1)[1]}.py::<MODULE FAILED TO IMPORT>"
    parts = uid.split(".")
    return f"{root}/{parts[0]}.py::" + "::".join(parts[1:])


def _flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten(item)
        else:
            yield item


def _run_root(root: str, out_path: str) -> dict:
    """Discover and RUN one root in this process; write {ids, failed, total} as JSON.

    Only ever called in the child (see `__main__` below), because it runs ~1,600 tests.
    """
    loader = unittest.TestLoader()
    discovered = loader.discover(str(REPO_ROOT / root), pattern="test_*.py")
    cases = [t for t in _flatten(discovered)
             if not t.id().startswith(SELF_MODULE + ".")          # never re-enter this file
             and not t.id().endswith("." + SELF_MODULE)]          # ...nor its import failure
    suite = unittest.TestSuite(cases)
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=0).run(suite)
    payload = {
        "root": root,
        "total": result.testsRun,
        "ids": [_pytest_id(root, t.id()) for t in cases],
        "failed": sorted({_pytest_id(root, t.id())
                          for t, _ in list(result.failures) + list(result.errors)}),
        "skipped": len(result.skipped),
    }
    Path(out_path).write_text(json.dumps(payload))
    return payload


def _collect() -> dict:
    """Run every root in child processes and merge. One process per root, exactly like CI."""
    merged = {"total": 0, "ids": set(), "failed": set(), "skipped": 0}
    with tempfile.TemporaryDirectory() as tmp:
        for root in ROOTS:
            out = Path(tmp) / f"{root.replace('/', '_')}.json"
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--emit-failures", root, str(out)],
                cwd=str(REPO_ROOT), capture_output=True, text=True,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            if not out.exists():
                raise AssertionError(
                    f"the child run of '{root}' produced no result file (rc={proc.returncode}). "
                    f"This test cannot tell a declared red from an undeclared one without it.\n"
                    f"--- child stdout ---\n{proc.stdout[-4000:]}\n"
                    f"--- child stderr ---\n{proc.stderr[-4000:]}")
            payload = json.loads(out.read_text())
            merged["total"] += payload["total"]
            merged["skipped"] += payload["skipped"]
            merged["ids"] |= set(payload["ids"])
            merged["failed"] |= set(payload["failed"])
    return merged


class TestKnownRedAllowlist(unittest.TestCase):
    """One child run, three assertions on it."""

    _collected = None

    @classmethod
    def setUpClass(cls):
        if TestKnownRedAllowlist._collected is None:
            TestKnownRedAllowlist._collected = _collect()
        cls.run_result = TestKnownRedAllowlist._collected

    # --- the allowlist is well-formed before it is believed ---------------------------------
    def test_every_declared_red_is_a_test_that_exists(self):
        """A declaration pointing at a renamed or deleted test silently stops declaring anything."""
        missing = sorted(set(KNOWN_RED) - self.run_result["ids"])
        self.assertEqual(missing, [], msg=(
            "KNOWN_RED names test(s) that the suite no longer collects — renamed, moved or "
            "deleted. Fix the id or drop the entry; a declaration nothing can match declares "
            "nothing."))

    def test_no_declared_red_has_outlived_its_expiry_date(self):
        today = _dt.date.today()
        expired = []
        for test_id, entry in sorted(KNOWN_RED.items()):
            expires = _dt.date.fromisoformat(entry["expires"])       # raises on a malformed date
            self.assertTrue(entry["reason"].strip(), f"{test_id}: an entry with no reason")
            if today >= expires:
                expired.append(f"{test_id} (expired {entry['expires']})")
        self.assertEqual(expired, [], msg=(
            "a declared red has reached its expiry date. Re-read the finding and either fix the "
            "failure or re-argue the entry with a NEW date and a reason that is still true. "
            "Extending the date without re-reading it is how a permanent red is born."))

    # --- and then: the measured failing set IS the declared one ------------------------------
    def test_the_failing_set_is_exactly_the_allowlist(self):
        failed = self.run_result["failed"]
        declared = set(KNOWN_RED)
        undeclared = sorted(failed - declared)
        vacuous = sorted(declared - failed)
        self.assertEqual(self.run_result["total"] > 0, True, "the child run collected no tests")
        self.assertEqual(undeclared, [], msg=(
            f"UNDECLARED FAILURE(S) — {len(undeclared)} test(s) fail that nothing in this repo "
            f"declares. This is the exact failure class the standing red hides: run them "
            f"individually and fix them, or add a KNOWN_RED entry with evidence and an expiry.\n"
            + "\n".join("    " + t for t in undeclared)))
        self.assertEqual(vacuous, [], msg=(
            f"VACUOUS ALLOWLIST ENTRY — {len(vacuous)} declared red(s) now PASS. Good news, and a "
            f"finding: delete the entry so the next undeclared failure cannot hide behind it.\n"
            + "\n".join("    " + t for t in vacuous)))


if __name__ == "__main__":
    # Child entry point: `python3 tests/test_known_red_allowlist.py --emit-failures <root> <out>`.
    # Deliberately NOT unittest.main() — running this module directly is the expensive suite run,
    # and it must be reachable without re-entering the allowlist assertions above.
    if len(sys.argv) == 4 and sys.argv[1] == "--emit-failures":
        result = _run_root(sys.argv[2], sys.argv[3])
        print(f"[known_red] {result['root']}: {result['total']} run, "
              f"{len(result['failed'])} failed, {result['skipped']} skipped")
        raise SystemExit(0)
    raise SystemExit(__doc__)
