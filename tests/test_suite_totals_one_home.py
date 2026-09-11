"""The suite totals have ONE home, and this test is what makes that true (G12).

THE DEFECT. `tests/README.md` declares itself "the one home for the suite totals" and then lists the
other three files that quote the same numbers: `README.md`'s evidence row, `SETUP.md` §(a)/(b), and
`docs/drafts/README_FULL.md`. Nothing enforced the agreement, so the four copies went stale together
through two sessions -- the README quoted a total 722 tests short of the tree while every one of
those documents read as a measurement. A number that four documents assert and no test checks is
not a measurement; it is a rumour with a decimal point.

WHAT IS CHECKED
  1. the four homes agree WITH EACH OTHER (three, if the drafts copy has been deleted);
  2. the arithmetic `tests/README.md` publishes closes: planning + host == passed + failed +
     skipped, which is the invariant that catches a test file invisible to one of the two runners --
     the failure the second CI job exists to prevent;
  3. the quoted numbers agree with a LIVE count of this tree: `unittest` discovery over both roots,
     and `pytest --collect-only` when pytest is importable.

THIS TEST IS EXPECTED TO BE RED WHENEVER THE SUITE CHANGES, and that is its whole function: the
person who adds a test re-quotes the four documents, or CI tells them the documents are lying. The
failure message prints every number it found and where, so re-quoting is copy-and-paste rather than
a hunt. It NEVER edits a document -- a self-healing docs test would remove the review step that is
the point of having the number written down at all.

stdlib unittest only. Run: python3 -m unittest discover -s tests -p 'test_*.py' -v
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_README = REPO_ROOT / "tests" / "README.md"
README = REPO_ROOT / "README.md"
SETUP = REPO_ROOT / "SETUP.md"
DRAFT_README = REPO_ROOT / "docs" / "drafts" / "README_FULL.md"

PLANNING_ROOT = REPO_ROOT / "tests" / "fieldguard_planning"
HOST_ROOT = REPO_ROOT / "tests"
HOST_PATTERN = "test_*.py"

# The pytest triple as every home writes it: "1599 passed, 1 failed, 2 skipped". Case-insensitive on
# the middle word because `tests/README.md` shouts it ("1 FAILED") and the others do not.
PYTEST_TRIPLE = re.compile(r"(\d+)\s+passed,\s+(\d+)\s+(?:failed|FAILED),\s+(\d+)\s+skipped")
# `Ran 1325, OK (skipped=2)` in one home and `Ran 277 tests in 38.137s` in another: the
# word after the number is not load-bearing, the number is.
RAN_N = re.compile(r"Ran\s+(\d+)\b")


def _triple(text, path):
    hits = PYTEST_TRIPLE.findall(text)
    if not hits:
        return None
    return tuple(int(x) for x in hits[0])


def _key(path: Path) -> str:
    """Documents are keyed by their path relative to the repo, not by `.name`: `tests/README.md`
    and `README.md` are two of the four homes and share a filename."""
    return str(path.relative_to(REPO_ROOT))


def quoted_totals():
    """{document: {...numbers it quotes...}} -- only the documents that exist and quote any."""
    out = {}

    tr = TESTS_README.read_text()
    ran = [int(n) for n in RAN_N.findall(tr)]
    out[_key(TESTS_README)] = {
        "pytest": _triple(tr, TESTS_README),
        "runs": sorted(ran),
        # The consistency sentence the file publishes: "1325 + 277 = 1602 = 1599 + 1 + 2".
        "closure": [int(n) for n in re.findall(r"(\d+) \+ (\d+) = (\d+) = (\d+) \+ (\d+) \+ (\d+)",
                                               tr)[0]] if re.search(
            r"\d+ \+ \d+ = \d+ = \d+ \+ \d+ \+ \d+", tr) else None,
    }

    for path in (README, SETUP, DRAFT_README):
        if not path.exists():
            continue
        text = path.read_text()
        triple = _triple(text, path)
        if triple is None:
            continue
        entry = {"pytest": triple}
        if path is SETUP:
            entry["runs"] = sorted(int(n) for n in RAN_N.findall(text))
        out[_key(path)] = entry
    return out


def discovered_counts():
    """(planning tests, host-side tests) as `unittest` discovery sees them right now.

    Counted in-process rather than by parsing a subprocess's "Ran N": it is the same loader CI's two
    jobs use, it costs no second interpreter, and a module that fails to IMPORT shows up as a
    `_FailedTest` rather than as a missing test -- which is the case this skips on, because a count
    taken against a broken environment would fail this test for the wrong reason."""
    def count(start_dir, pattern):
        suite = unittest.TestLoader().discover(str(start_dir), pattern=pattern)
        broken = []

        def walk(s):
            for t in s:
                if isinstance(t, unittest.TestSuite):
                    walk(t)
                elif type(t).__name__ == "_FailedTest":
                    broken.append(str(t))
        walk(suite)
        if broken:
            raise unittest.SkipTest(
                f"{len(broken)} test module(s) under {start_dir.name} could not be imported, so a "
                f"count taken here would not be the suite's size: {broken[:3]}")
        return suite.countTestCases()

    return count(PLANNING_ROOT, "test_*.py"), count(HOST_ROOT, HOST_PATTERN)


def pytest_collected():
    """How many tests `pytest tests` collects, or None if pytest is not installed. This is the
    number the `passed + failed + skipped` triple has to add up to."""
    try:
        import pytest  # noqa: F401
    except ImportError:
        return None
    proc = subprocess.run([sys.executable, "-m", "pytest", str(REPO_ROOT / "tests"),
                           "--collect-only", "-q", "-p", "no:cacheprovider"],
                          cwd=str(REPO_ROOT), capture_output=True, text=True)
    m = re.search(r"(\d+) tests? collected", proc.stdout)
    if not m:
        m = re.search(r"(\d+)/(\d+) tests collected", proc.stdout)
        return int(m.group(2)) if m else None
    return int(m.group(1))


def _report(quoted, planning, host, collected):
    lines = ["suite totals disagree -- every number this test can see:"]
    for doc, vals in sorted(quoted.items()):
        lines.append(f"    {doc:<18} {vals}")
    lines.append(f"    {'MEASURED now':<18} planning={planning} host={host} "
                 f"sum={planning + host} pytest_collected={collected}")
    lines.append("    re-run the three commands in tests/README.md and re-quote EVERY home above.")
    return "\n".join(lines)


class TestSuiteTotalsHaveOneHome(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.quoted = quoted_totals()
        cls.planning, cls.host = discovered_counts()
        cls.collected = pytest_collected()

    def test_every_document_quotes_the_same_pytest_triple(self):
        triples = {doc: v["pytest"] for doc, v in self.quoted.items() if v.get("pytest")}
        self.assertGreaterEqual(len(triples), 3,
                                f"expected the totals in at least three homes, found {list(triples)}")
        self.assertEqual(len(set(triples.values())), 1,
                         _report(self.quoted, self.planning, self.host, self.collected))

    def test_every_document_quotes_the_same_per_root_counts(self):
        runs = {doc: tuple(v["runs"]) for doc, v in self.quoted.items() if v.get("runs")}
        self.assertEqual(len(set(runs.values())), 1,
                         _report(self.quoted, self.planning, self.host, self.collected))

    def test_the_published_arithmetic_closes(self):
        """planning + host == passed + failed + skipped. When this fails, a test file is invisible
        to one of the two runners -- which has happened, and is why CI runs both."""
        closure = self.quoted[_key(TESTS_README)]["closure"]
        self.assertIsNotNone(closure, "tests/README.md no longer publishes its consistency sentence")
        planning, host, total, passed, failed, skipped = closure
        self.assertEqual(planning + host, total,
                         _report(self.quoted, self.planning, self.host, self.collected))
        self.assertEqual(passed + failed + skipped, total,
                         _report(self.quoted, self.planning, self.host, self.collected))
        self.assertEqual((passed, failed, skipped), self.quoted[_key(TESTS_README)]["pytest"],
                         _report(self.quoted, self.planning, self.host, self.collected))

    def test_the_quoted_counts_are_this_tree(self):
        """The one that goes red when someone adds a test and forgets the documents."""
        planning, host = sorted((self.planning, self.host))
        quoted = self.quoted[_key(TESTS_README)]["runs"]
        self.assertEqual([planning, host], quoted,
                         _report(self.quoted, self.planning, self.host, self.collected))

    def test_the_pytest_triple_is_this_tree(self):
        if self.collected is None:
            raise unittest.SkipTest("pytest is not installed on this interpreter (SETUP.md (a) is "
                                    "the install-free path; this check belongs to (b))")
        passed, failed, skipped = self.quoted[_key(TESTS_README)]["pytest"]
        self.assertEqual(passed + failed + skipped, self.collected,
                         _report(self.quoted, self.planning, self.host, self.collected))
        self.assertEqual(self.planning + self.host, self.collected,
                         "unittest discovery and pytest collection disagree about how many tests "
                         "this tree has -- a file one runner cannot see:\n"
                         + _report(self.quoted, self.planning, self.host, self.collected))


if __name__ == "__main__":
    unittest.main()
