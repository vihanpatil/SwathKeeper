"""`scripts/validate_agents.py` must validate THIS repo, from any working directory.

It used to glob `.claude/agents/*.md` and `os.path.isdir("src")` relative to the caller's cwd, so it
only worked when run from the repo root (CI's happy path). Run from anywhere else it either failed
with bogus "missing expected directory" errors or -- the nastier case -- silently validated whatever
repo the caller happened to be standing in (2026-08-18 audit item 22).

stdlib unittest. Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validate_agents.py"

try:
    import yaml  # noqa: F401
    HAVE_YAML = True
except ImportError:
    HAVE_YAML = False


def run_from(cwd: Path):
    return subprocess.run([sys.executable, str(VALIDATOR)],
                          cwd=str(cwd), capture_output=True, text=True)


@unittest.skipUnless(HAVE_YAML, "PyYAML not installed (validator exits 2 without it)")
class TestValidatorIsCwdIndependent(unittest.TestCase):
    def test_passes_from_repo_root(self):
        r = run_from(REPO_ROOT)
        self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
        self.assertIn("config OK", r.stdout)

    def test_passes_from_an_unrelated_directory(self):
        """The regression: an empty tempdir has no src/, no .claude/ and no agents."""
        with tempfile.TemporaryDirectory() as td:
            r = run_from(Path(td))
            self.assertEqual(r.returncode, 0, msg=r.stdout + r.stderr)
            self.assertIn("config OK", r.stdout)

    def test_reports_the_same_agent_count_from_both_directories(self):
        """Not just 'exit 0 somewhere' -- it must have found the SAME agents, i.e. this repo's."""
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(run_from(Path(td)).stdout, run_from(REPO_ROOT).stdout)

    def test_error_paths_stay_repo_relative(self):
        """Messages must not leak the absolute checkout path -- they name files a reader can open."""
        r = run_from(REPO_ROOT)
        self.assertNotIn(str(REPO_ROOT), r.stdout)


if __name__ == "__main__":
    unittest.main()
