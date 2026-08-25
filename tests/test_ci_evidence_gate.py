"""`.github/workflows/ci.yml` — the committed-evidence gates, pinned so they cannot go vacuous.

CI is the only gate that runs on every push, and the cheapest way for one to lie is to *match no
files and exit 0*. Two of this repo's evidence gates are one rename away from exactly that:

  * the live flight-log gate globs `eval/results/*flight_log*.json`, and the checker's contract for
    an absent path is SKIP / exit 0 (right for a tool a human points at a path, wrong for a CI job
    that must have evidence to chew on);
  * the scenario safety assertions in `tests/fieldguard_planning/test_safety_scenarios_pending.py`
    are SELF-ACTIVATING — they *skip* when `eval/scenarios/<name>/flight_log.json` is missing, so a
    deleted fixture silently retires the ledger-honesty and geofence properties.

So this file asserts the denominators: the glob matches committed files, every generator scenario has
a committed fixture, and the workflow step FAILS on an empty match (run for real, in a tree with no
matching files — the pre-fix step exits 0 there).

It also pins the ONE fact ADR-013 amendment 16's scoping decision rests on: the scenario fixtures are
OPEN-LOOP. Their `flown_path_enu` is the scripted lawnmower, not an outcome of the control law, which
is why the CPA gate is not pointed at them. If the generator ever closes the loop, test_open_loop
below goes red and that decision must be re-read — that is the point of it.

Lives in tests/ (not tests/fieldguard_planning/) on purpose, like test_fly_pipeline.py: it tests a
host-side artifact — the workflow file — not the planning package. stdlib unittest, so it runs under
both `python3 -m pytest tests/test_ci_evidence_gate.py -q` and `python3 -m unittest`.
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SCENARIOS_DIR = REPO_ROOT / "eval" / "scenarios"

sys.path.insert(0, str(SCENARIOS_DIR))
import generate_flight_logs as GEN  # noqa: E402  (the generator IS the scenario set's one source)

# The step whose `run:` block is executed below. Matched on a fragment of its `name:` so the step can
# be reworded without silently un-testing it -- if the fragment stops matching, the helper raises.
EVIDENCE_STEP = "Validate committed live flight-log evidence"


def _step_run_block(name_fragment: str) -> str:
    """The shell body of the ci.yml step whose name contains `name_fragment`.

    A ~20-line indentation walk instead of a PyYAML dependency: the planning CI job installs
    requirements-eval.txt (numpy/scipy/markdown, no pyyaml), and adding a parser dependency so a test
    can read a config file is a worse trade than reading the two lines of YAML shape this file uses.
    """
    lines = CI_YML.read_text().splitlines()
    for i, line in enumerate(lines):
        if not (line.lstrip().startswith("- name:") and name_fragment in line):
            continue
        for j in range(i + 1, len(lines)):
            if lines[j].lstrip().startswith("- name:"):
                break                                    # next step: this one had no `run: |`
            if lines[j].strip() != "run: |":
                continue
            indent = len(lines[j]) - len(lines[j].lstrip()) + 2
            body = []
            for k in range(j + 1, len(lines)):
                ln = lines[k]
                if ln.strip() and (len(ln) - len(ln.lstrip())) < indent:
                    break                                # dedent: end of the block scalar
                body.append(ln[indent:] if len(ln) >= indent else ln)
            return "\n".join(body)
    raise AssertionError(f"no ci.yml step named ~{name_fragment!r} with a 'run: |' block -- if the "
                         f"step was renamed, update EVIDENCE_STEP; if it was deleted, this test is "
                         f"the thing telling you the gate went away")


def _tracked(pathspec: str):
    """Files matching `pathspec` that are COMMITTED (what a fresh CI checkout actually gets)."""
    out = subprocess.run(["git", "ls-files", "--", pathspec], cwd=REPO_ROOT,
                         capture_output=True, text=True, check=True)
    return [p for p in out.stdout.splitlines() if p]


class TestLiveFlightLogGateHasEvidence(unittest.TestCase):
    """The gate must be shown files, and must say so when it is not."""

    def test_glob_matches_committed_files(self):
        """A fresh checkout MUST contain at least one log for the CPA gate to score.

        `.gitignore` ignores `eval/results/*` and then re-includes `live_flight_log_*.json`; if that
        re-include is ever dropped, or the logs are renamed, the CI glob matches nothing and the CPA
        gate silently validates air. Today: the 2026-08-18 and 2026-08-23 acknowledged breaches."""
        matched = _tracked("eval/results/*flight_log*.json")
        self.assertGreater(len(matched), 0,
                           msg="the ci.yml live flight-log gate globs eval/results/*flight_log*.json "
                               "and NOTHING committed matches it -- the gate would run on zero files")

    def test_step_fails_when_the_glob_matches_nothing(self):
        """THE adversarial one: run the real ci.yml step in a tree with no matching logs.

        The checker itself exits 0 on an absent path by design, so before the ADR-013 am. 16 fix this
        exact block exited **0** here -- green, having validated nothing. The step now counts its own
        matches and fails on zero. `scripts/` is symlinked in so the checker is reachable: the point
        is to prove the COUNT stops the run, not that python couldn't find the script."""
        script = _step_run_block(EVIDENCE_STEP)
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(REPO_ROOT / "scripts", Path(tmp) / "scripts")
            proc = subprocess.run(["bash", "-c", script], cwd=tmp,
                                  capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0,
                            msg=f"the evidence step exited 0 with zero files matched -- a vacuous "
                                f"gate.\nstdout: {proc.stdout}\nstderr: {proc.stderr}")
        self.assertIn("matched: 0", proc.stdout,
                      msg="the step must PRINT its denominator, not just fail on it")

    def test_step_passes_on_the_committed_evidence(self):
        """The same block, on a tree carrying exactly the committed logs + their markers + the bird
        tracks, exits 0.

        Hermetic on purpose (copies of the tracked files, not the working tree): an unrelated local
        flight log left in eval/results/ must not decide whether this test is red, or the next person
        to see it go red for someone else's artifact will weaken it.

        The `bird_drive_*` files are part of that checkout and not decoration: since TRUTH_BINDINGS
        (QA finding G47) a real-detector log is scored against the applied-pose log committed BESIDE
        it, so a tree with the flight logs but not the tracks makes the gate report "no truth track"
        -- which would send whoever sees this test go red hunting a binding bug instead of reading
        the flight's actual verdict."""
        script = _step_run_block(EVIDENCE_STEP)
        logs = _tracked("eval/results/live_flight_log_*")
        self.assertTrue(logs, "no committed live flight-log evidence at all")
        tracked = logs + _tracked("eval/results/bird_drive_*")
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(REPO_ROOT / "scripts", Path(tmp) / "scripts")
            (Path(tmp) / "eval" / "results").mkdir(parents=True)
            for rel in tracked:
                (Path(tmp) / rel).write_bytes((REPO_ROOT / rel).read_bytes())
            proc = subprocess.run(["bash", "-c", script], cwd=tmp,
                                  capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0,
                         msg=f"the committed evidence no longer passes its own gate.\n"
                             f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
        n_logs = len([p for p in logs if p.endswith(".json")])
        self.assertIn(f"matched: {n_logs}", proc.stdout)


class TestScenarioFixturesAreGated(unittest.TestCase):
    """The scenario fixtures' gates are the regenerate+diff step and the self-activating pending
    tests -- both of which are only real if the fixtures are actually there."""

    def test_every_generated_scenario_has_a_committed_fixture(self):
        """`test_safety_scenarios_pending.py` SKIPS a missing fixture, so a deleted one silently
        retires the ledger-honesty (P1-P4) and geofence properties for that scenario. This is the
        assertion that turns that skip into a failure."""
        missing = [name for name in GEN.SCENARIOS
                   if not _tracked(f"eval/scenarios/{name}/flight_log.json")]
        self.assertEqual(missing, [],
                         msg=f"generator scenario(s) with no COMMITTED flight_log.json: {missing}. "
                             f"Their safety assertions are skipping, not passing.")

    def test_fixtures_are_open_loop_which_is_why_the_cpa_gate_is_scoped_off_them(self):
        """ADR-013 amendment 16's load-bearing fact, executable.

        `generate_flight_logs.py` prescribes the drone's position from `nominal_path()` every tick and
        never feeds the executor's commanded setpoint back into the next tick's `DroneState`. So a
        fixture's `flown_path_enu` IS the scripted stimulus, its closest approach to the scripted bird
        is a property of the scenario definition (the bird is parked ON the lane to force a dodge),
        and no control law can move it. That is why `check_live_flight_log.py`'s CPA gate is pointed
        at live logs only. If this ever fails, the generator has become closed-loop, the fixtures'
        CPA becomes a real flown outcome, and amendment 16 must be re-read before CI is changed."""
        nominal = [(x, y, GEN.CRUISE_M) for x, y, _wp in GEN.nominal_path()]
        for name, cfg in GEN.SCENARIOS.items():
            with self.subTest(scenario=name):
                log = json.loads((SCENARIOS_DIR / name / "flight_log.json").read_text())
                flown = [tuple(p) for p in log["flown_path_enu"]]
                self.assertEqual(flown, nominal,
                                 msg=f"[{name}] flown_path_enu is no longer the scripted lawnmower")
                # ... and the birds really are placed on/near that scripted path, i.e. the fixture's
                # CPA is authored, not flown. (3.0 m = min_bird_clearance_m; three of the four sit
                # inside it BY CONSTRUCTION and that is the scenario working, not a safety finding.)
                cpa = min(math.hypot(px - bx, py - by)
                          for px, py, _u in nominal for _bid, (bx, by, _bz) in cfg["birds"])
                self.assertLess(cpa, GEN.SWATH_HALF_M,
                                msg=f"[{name}] scripted bird is {cpa:.2f} m off the scripted path -- "
                                    f"it can no longer force the dodge the scenario is about")


if __name__ == "__main__":
    unittest.main()
