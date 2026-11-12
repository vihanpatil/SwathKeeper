"""`.github/workflows/ci.yml` — the committed-evidence gates, pinned so they cannot go vacuous.

CI is the only gate that runs on every push, and the cheapest way for one to lie is to *match no
files and exit 0*. Two of this repo's evidence gates are one rename away from exactly that:

  * the live flight-log gate globs `eval/results/*flight_log*.json`, and the checker's contract for
    an absent path is SKIP / exit 0 (right for a tool a human points at a path, wrong for a CI job
    that must have evidence to chew on);
  * the scenario safety assertions in `tests/fieldguard_planning/test_safety_scenarios_pending.py`
    are SELF-ACTIVATING — they *skip* when `eval/scenarios/<name>/flight_log.json` is missing, so a
    deleted fixture silently retires the ledger-honesty and geofence properties.

A third way is louder and was live for longer: run the gate and throw its exit code away. The
mission-geofence step did exactly that (`|| true`) from 2026-08-18 until R8 closed it on 2026-09-11
— see `TestMissionGeofenceGateIsArmed`.

So this file asserts the denominators: the glob matches committed files, every generator scenario has
a committed fixture, and the workflow step FAILS on an empty match (run for real, in a tree with no
matching files — the pre-fix step exits 0 there).

Since 2026-11-05 (ADR-023 am. 1) it also arms the evidence-gate TOOL's CI job, `gates-tool`: the step that
re-fetches the three pinned public logs by sha256 and diffs the committed `examples/*/verdict.json` is run
here against stubs (a wrong sha256, a `should` bar slid PASS -> EI, a missing tool, two examples instead of
three -- each must be red), and the Action's `run.sh` is run against a stub tool and the real one to prove
it never softens an exit code. See `TestGatesReproductionStepIsArmed` and friends at the bottom.

It also pins the ONE fact ADR-013 amendment 16's scoping decision rests on: the scenario fixtures are
OPEN-LOOP. Their `flown_path_enu` is the scripted lawnmower, not an outcome of the control law, which
is why the CPA gate is not pointed at them. If the generator ever closes the loop, test_open_loop
below goes red and that decision must be re-read — that is the point of it.

Lives in tests/ (not tests/fieldguard_planning/) on purpose, like test_fly_pipeline.py: it tests a
host-side artifact — the workflow file — not the planning package. stdlib unittest, so it runs under
both `python3 -m pytest tests/test_ci_evidence_gate.py -q` and `python3 -m unittest`.
"""
import datetime as _dt
import hashlib
import json
import math
import os
import re
import shutil
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
GEOFENCE_STEP = "tree geofence"          # the mission-vs-geofence gate (R8, ADR-022 am. 2)


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


def _job_lines(job: str):
    lines = CI_YML.read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == f"{job}:")
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() and not lines[i].startswith(" " * (indent + 1))), len(lines))
    return lines[start:end]


def _job_steps(job: str):
    """[(name, [body lines]), ...] for the job's steps, in order (a bare `- uses:` step is named by that line)."""
    steps, current = [], None
    for line in _job_lines(job):
        stripped = line.strip()
        if stripped.startswith("- name:"):
            current = (stripped.split("- name:", 1)[1].strip(), [])
            steps.append(current)
        elif stripped.startswith("- uses:"):
            current = (stripped, [])
            steps.append(current)
        elif current is not None:
            current[1].append(stripped)
    return steps


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


class TestMissionGeofenceGateIsArmed(unittest.TestCase):
    """R8 (ADR-022 am. 2): the mission-vs-geofence step has to be able to FAIL.

    From 2026-08-18 to 2026-09-11 it ran `python3 scripts/check_mission_geofence.py || true`, because
    the script exited 1 on the committed mission's documented, safe XY overlap on leg 4. The waiver
    was sound and the gate was disarmed anyway — an XY geofence that cannot fail is not one. The
    script now judges the mission in 3D (and passes it), so the exit code means something again;
    these two tests are what stop a future `|| true` from coming back.
    """

    STUB_MARKER = "stub-check-mission-geofence-ran"

    def _run_step_with_stub(self, exit_code):
        """The REAL step body, in a tree where the checker is a stub with a known exit code. This
        tests the shell wiring — the thing `|| true` broke. The checker's own verdicts are pinned in
        tests/fieldguard_planning/test_mission_geofence.py, against the real mission and real trees."""
        body = _step_run_block(GEOFENCE_STEP)
        with tempfile.TemporaryDirectory() as tmp:
            scripts = Path(tmp) / "scripts"
            scripts.mkdir()
            (scripts / "check_mission_geofence.py").write_text(
                "import sys\n"
                f"print({self.STUB_MARKER!r})\n"
                f"sys.exit(0 if '--help' in sys.argv else {exit_code})\n")
            return subprocess.run(["bash", "-c", body], cwd=tmp, capture_output=True, text=True)

    def test_the_step_fails_when_the_checker_does(self):
        """The mutation: a checker that exits 1 must take the step — and the build — with it."""
        proc = self._run_step_with_stub(1)
        self.assertIn(self.STUB_MARKER, proc.stdout,
                      msg=f"the step never reached the checker, so its exit code proves nothing.\n"
                          f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
        self.assertNotEqual(proc.returncode, 0,
                            msg=f"the mission-geofence step swallowed a FAILING checker — this is "
                                f"exactly the `|| true` R8 closed.\nstdout: {proc.stdout}")
        self.assertEqual(self._run_step_with_stub(0).returncode, 0,
                         msg="...and it must still be green when the checker passes, or the test "
                             "above is just asserting that the step is broken")

    def test_the_real_invocation_is_not_swallowed(self):
        """Read the block too: `|| true`, `|| :` and `set +e` all reproduce the disarmed gate while
        the stub test above still passes if they are applied only to a later line."""
        body = _step_run_block(GEOFENCE_STEP)
        self.assertIn("set -euo pipefail", body,
                      msg="without `set -e` a non-final failing command does not fail the step")
        calls = [ln.strip() for ln in body.splitlines()
                 if "check_mission_geofence.py" in ln and not ln.strip().startswith("#")]
        gating = [c for c in calls if "--help" not in c]
        self.assertTrue(gating, msg=f"the step no longer runs the mission through the checker at "
                                    f"all (only --help smokes it):\n{body}")
        for call in gating:
            for swallow in ("|| true", "|| :", "continue-on-error"):
                self.assertNotIn(swallow, call,
                                 msg=f"the gate's exit code is thrown away again: {call!r}")
        self.assertNotIn("set +e", body)


class TestNoRedCanHideBehindTheDeclaredOne(unittest.TestCase):
    """The gates after the test suites must RUN when a test suite is red.

    `main` carries a declared red (the 2026-08-25 breach, `docs/runbooks/
    AVOIDANCE_REAL_DETECTION.md` 6a). GitHub skips every later step of a job once one fails, so
    between 2026-08-25 and 2026-09-10 that single honest failure took the seed-42 FNR regression,
    the scenario regenerate+diff and the generator smoke test dark for 16 days — and two unrelated
    failures reached `main` inside the blind spot. `if: always()` on each of those steps is what
    makes "CI is red on purpose" a statement about ONE test instead of a blindfold over the rest,
    so it is asserted here rather than remembered.
    """

    JOB = "planning-and-eval"
    # Once this step can fail, everything after it needs `if: always()` to keep reporting.
    FIRST_FALLIBLE = "Planning test suite"

    def _job_lines(self):
        return _job_lines(self.JOB)

    def _steps(self):
        return _job_steps(self.JOB)

    def test_every_step_after_the_first_fallible_one_runs_anyway(self):
        steps = self._steps()
        names = [name for name, _ in steps]
        self.assertIn(self.FIRST_FALLIBLE, names, f"{self.JOB} lost its test suite step")
        after = steps[names.index(self.FIRST_FALLIBLE) + 1:]
        self.assertGreaterEqual(len(after), 5, "suspiciously few gates after the test suite")
        missing = [name for name, body in after
                   if not any(ln.startswith("if:") and "always()" in ln for ln in body)]
        self.assertEqual(missing, [], msg=(
            "these CI steps run AFTER a step that is red on purpose, with no `if: always()`, so "
            "they are skipped on every push and prove nothing:\n"
            + "\n".join("    " + name for name in missing)))

    def test_the_allowlist_gate_is_one_of_them_and_runs_the_allowlist(self):
        """The step that names WHICH red is declared. Without it, `if: always()` above just means
        more output: something has to assert that the failing set is exactly the declared one."""
        step = next((s for s in self._steps() if "KNOWN_RED" in s[0]), None)
        self.assertIsNotNone(step, "no CI step runs the KNOWN_RED allowlist")
        body = " ".join(step[1])
        self.assertIn("test_known_red_allowlist.py", body)
        self.assertTrue((REPO_ROOT / "tests" / "test_known_red_allowlist.py").exists())

    def test_the_allowlist_step_fails_instead_of_matching_nothing(self):
        """The vacuous-gate rule, applied to the gate that exists to stop vacuous reds.

        `unittest discover -p <pattern>` on a pattern that matches no file prints "Ran 0 tests",
        reports OK and exits 0. So this step is run FOR REAL in an empty tree: deleting the
        allowlist must break the build, not quietly pass it. (It exits on the guard, so this costs
        milliseconds rather than the two minutes the real run takes.)"""
        script = _step_run_block("KNOWN_RED")
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(["bash", "-c", script], cwd=tmp,
                                  capture_output=True, text=True, timeout=120)
        self.assertNotEqual(proc.returncode, 0,
                            msg=f"the allowlist step passed with no allowlist to run.\n"
                                f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
        self.assertIn("test_known_red_allowlist.py is gone", proc.stderr)

    def test_the_seed_42_safety_regression_is_one_of_the_steps_it_protects(self):
        """Named, because it is the one the 16-day blind spot actually cost: `check_spike_
        regression.py` gates per-bird-track FNR on the ADOPTED detector (ADR-003 am. 8 moved it
        into `src/fieldguard_planning/ndvi_detect.py`, and `eval/baseline_ndvi.py` imports it), so
        while this step was skipped, the flown detector had no CI regression gate at all."""
        step = next((s for s in self._steps() if "seed-42 headline metric" in s[0]), None)
        self.assertIsNotNone(step, "the seed-42 regression gate left CI")
        self.assertTrue(any(ln.startswith("if:") and "always()" in ln for ln in step[1]))
        self.assertIn("check_spike_regression.py", " ".join(step[1]))


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
                # CPA is authored, not flown. (3.0 m = min_bird_clearance_m; measured as SEGMENTS --
                # which `check_live_flight_log.closest_approach` does since 2026-08-25 -- ALL FOUR
                # are fly-throughs, cov_bird_at_turnaround included: it read 7.0000 m only because
                # the old vertex-only minimum missed a bird passed between two samples. That is the
                # scenario working BY CONSTRUCTION, not a safety finding, and it is precisely why
                # amendment 16 points the CPA gate at live logs only.)
                cpa = min(math.hypot(px - bx, py - by)
                          for px, py, _u in nominal for _bid, (bx, by, _bz) in cfg["birds"])
                self.assertLess(cpa, GEN.SWATH_HALF_M,
                                msg=f"[{name}] scripted bird is {cpa:.2f} m off the scripted path -- "
                                    f"it can no longer force the dodge the scenario is about")


# ================================================================================================
# The evidence-gate TOOL's job (ADR-023 am. 1, option C step 5): the reproduction step, the Action
# ================================================================================================
GATES_JOB = "gates-tool"
REPRO_STEP = "Re-fetch the three pinned public logs"           # the step whose `run: |` body is executed below
DEMO_FETCH_STEP = "Fetch the two demo logs"
TAROT_ASSERT_STEP = "outputs equal the committed demo verdict"
PLANE_ASSERT_STEP = "and it did fail"
ACTION_DIR = REPO_ROOT / ".github" / "actions" / "swathkeeper-gates"
# design §8 / ADR-023 D7: three public logs, by name, sha256 AND exact url (QA G279: the url regex alone accepted
# `..`, query strings and any owner). A changed pin is a reviewed diff here.
DESIGN_EXAMPLES = {
    "plane_nofix": ("28dcbac522ceb75eee10f6af37b0d6e342c1dc79e2be1a9f766fe18a14336766",
                    "https://raw.githubusercontent.com/ArduPilot/plotjuggler-apbin-plugins/43a8d81224b62c88e3f646d7a0429c3ae7140ae9/tests/logs/00000001.BIN"),
    "pymavlink_test_bin": ("a51f040b2ad7f55185c1da5705f226f51469b86562c4ff76d05c99e0e52c2bf4",
                           "https://raw.githubusercontent.com/ArduPilot/pymavlink/544d9016f6e19fed105b28fb41e9ade19c45d8c2/tests/test.BIN"),
    "tarot_x4": ("a4dc00507cc8448c0ce320279e70040de3af3439dd4c3dd5363a7fa388609108",
                 "https://raw.githubusercontent.com/ArduPilot/MethodicConfigurator/3d14a14353eeb9fca73c82995855bf977a7d5fcc/"
                 "ardupilot_methodic_configurator/vehicle_templates/ArduCopter/Tarot_X4/2024-08-05%2018-48-54.bin"),
}
EXAMPLE_FILES = {"SOURCE.json", "bars.yaml", "bars.yaml.prereg.json", "verdict.json", "badge.svg"}   # nothing else (QA G280)
EXCLUDED_LEAVES = {"tool.python", "tool.deps.PyYAML", "allowlist.run_date_utc"}                     # exactly these (QA G281)
TODAY = _dt.datetime.now(_dt.timezone.utc).date()                                                     # the checker's run date


def _canonical(obj) -> str:
    """The tool's own serialisation; the checker requires every committed JSON file in this form (QA G277)."""
    return json.dumps(obj, indent=1, allow_nan=False) + "\n"
TAROT_BADGE = "gates: could not tell · 7/8 measured (post-hoc)"       # the README badge, verbatim (ADR-023, v0.2.0 G257)
WALKTHROUGH_SHA256 = "185074c12430389f65ec6f071ab988fc1f4e4d67e3ba0ee2f28183cfea563884"   # tool README lines 55-64 (G325)
TAROT_LABEL = "tarot_x4 · public log"                                  # scripts/check_gates_examples.BADGE_LABELS
FAKE_BADGE = "gates: pass · 2/3 measured (post-hoc)"

STUB_CURL = """#!/bin/bash
# stub curl for the reproduction step: `curl -fsSL --proto '=https' --proto-redir '=https' --retry N --retry-delay N -o <path> <url>`
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2;;
    --retry|--retry-delay|--max-time|--proto|--proto-redir) shift 2;;
    -*) shift;;
    *) url="$1"; shift;;
  esac
done
echo "curl $url -> $out" >> "$STUB_LOG"
base="${url%%\\?*}"; base="${base%%#*}"     # raw.githubusercontent.com ignores a query/fragment; so does this stub
src="$STUB_LOGS/$(basename "$base")"
[ -f "$src" ] || { echo "stub curl: 404 $url" >&2; exit 22; }
cp "$src" "$out"
"""

STUB_TOOL = """#!{python}
# stub swathkeeper-gates for the reproduction step: writes $STUB_VERDICTS/<example dir name>.json to --out and
# exits with its exit_code ($STUB_PROCESS_EXIT overrides the process exit alone)
import json, os, sys
a = sys.argv[1:]
bars = next(x[len("--bars="):] for x in a if x.startswith("--bars="))
out = next(x[len("--out="):] for x in a if x.startswith("--out="))
name = os.path.basename(os.path.dirname(os.path.abspath(bars)))
with open(os.environ["STUB_LOG"], "a") as f:
    f.write("tool " + name + "\\n")
with open(os.path.join(os.environ["STUB_VERDICTS"], name + ".json")) as f:
    v = json.load(f)
with open(out, "w") as f:
    json.dump(v, f)
sys.exit(int(os.environ.get("STUB_PROCESS_EXIT", v["exit_code"])))
"""

STUB_RUN_TOOL = """#!{python}
# stub swathkeeper-gates for run.sh: records argv, writes a minimal verdict (or not), exits {code}
import json, os, sys
a = sys.argv[1:]
if os.environ.get("STUB_ARGS"):
    open(os.environ["STUB_ARGS"], "w").write("\\n".join(a))
out = next((x[len("--out="):] for x in a if x.startswith("--out=")), None)
if {write} and out:
    open(out, "w").write(json.dumps({{"badge": {badge!r}, "exit_code": {code}}}))
sys.exit({code})
"""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _fake_verdict(log_sha, bars_sha, sidecar_sha, name="beta"):
    """Shaped like a real swathkeeper-verdict/1.0 where the checker looks: pins, prereg, results with every leaf."""
    results = (("alt_floor", "PASS", 100, 1.5, "must", "series_bound", {"channel": "position.alt_rel_home_m", "bound": "floor", "limit": -10.0}),
               ("speed_ceiling", "PASS", 50, 2.0, "should", "series_bound", {"channel": "velocity.groundspeed_mps", "bound": "ceiling", "limit": 12.5}),
               ("no_errors", "EVIDENCE_INSUFFICIENT", 0, None, "should", "no_events", {"kinds": ["error"]}))
    return {"schema": "swathkeeper-verdict/1.0", "contract": "swathkeeper-flightlog/1.0",
            "tool": {"version": "0.1.0", "python": "3.12.12", "deps": {"PyYAML": "6.0.3", "pymavlink": "2.4.50"}},
            "source": {"path": f"{name}.bin", "sha256": log_sha, "size_bytes": 1234},
            "integrity": {"bytes_skipped": 0, "dsf_dropped_max": 15, "holes": []},
            "streams": {"position": {"state": "PRESENT", "n": 100}},
            "bars": {"path": "bars.yaml", "sha256": bars_sha, "schema": "swathkeeper-bars/1.0"},
            "prereg": {"status": "HASH_MATCH", "sidecar": "bars.yaml.prereg.json", "sidecar_sha256": sidecar_sha,
                       "bars_sha256": bars_sha, "bars_sha256_registered": bars_sha, "log_sha256_pinned": log_sha, "post_hoc": True},
            "results": [{"id": i, "kind": k, "verdict": v, "n": n, "measured": m, "severity": sev, "bar": bar, "note": None}
                        for i, v, n, m, sev, k, bar in results],
            "allowlist": {"path": None, "run_date_utc": TODAY.isoformat(), "declared": [], "undeclared": []},
            "exit_code": 0, "badge": FAKE_BADGE, "refusal": None}


def _gates_tree(tmp: Path, names=("alpha", "beta", "gamma"), fresh=None, corrupt=(), tool=True, url=None):
    """A temp repo with `names` fake example dirs, the REAL scripts/, and stub `curl` + `swathkeeper-gates` on PATH.

    Each example's committed verdict is `_fake_verdict`; the stub tool writes `fresh[name]` (default: identical).
    `corrupt` names examples whose fetched bytes have ONE BIT flipped at the same size (a size check alone must
    not kill the sha256 mutant). Returns the env for the step; the committed files are under tmp/examples/."""
    bin_ = tmp / "bin"
    bin_.mkdir()
    os.symlink(REPO_ROOT / "scripts", tmp / "scripts")
    os.symlink(sys.executable, bin_ / "python3")                # the body says `python3`; make it this interpreter
    logs, verdicts = tmp / "stub_logs", tmp / "stub_verdicts"
    logs.mkdir()
    verdicts.mkdir()
    for name in names:
        ex = tmp / "examples" / name
        ex.mkdir(parents=True)
        log_bytes = (b"\xa3\x95 fixture " + name.encode()) * 64
        bars = f"schema: swathkeeper-bars/1.0\ncontract: swathkeeper-flightlog/1.0\nbars: [{name}]\n".encode()
        fetched = bytearray(log_bytes)
        if name in corrupt:
            fetched[-1] ^= 0x01
        (logs / f"{name}.bin").write_bytes(bytes(fetched))
        (ex / "SOURCE.json").write_text(_canonical({
            "url": url or f"https://raw.githubusercontent.com/example/fixtures/{'a' * 40}/logs/{name}.bin",
            "sha256": _sha(log_bytes), "size_bytes": len(log_bytes), "licence": "test fixture"}))
        (ex / "bars.yaml").write_bytes(bars)
        sidecar = _canonical({"schema": "swathkeeper-prereg/1.0", "bars_sha256": _sha(bars), "tool_version": "0.1.0",
                              "written_utc": "2026-11-05T00:00:00+00:00", "log_sha256": _sha(log_bytes)}).encode()
        (ex / "bars.yaml.prereg.json").write_bytes(sidecar)
        committed = _fake_verdict(_sha(log_bytes), _sha(bars), _sha(sidecar), name)
        (ex / "verdict.json").write_text(_canonical(committed))
        (verdicts / f"{name}.json").write_text(json.dumps((fresh or {}).get(name, committed)))
    (bin_ / "curl").write_text(STUB_CURL)
    (bin_ / "curl").chmod(0o755)
    if tool:
        (bin_ / "swathkeeper-gates").write_text(STUB_TOOL.format(python=sys.executable))
        (bin_ / "swathkeeper-gates").chmod(0o755)
    # PATH is NOT inherited: the stubs, then only the system dirs for bash/coreutils -- an installed real tool
    # (this repo's .venv/bin) must never answer for a stub that was deliberately left out.
    return {**os.environ, "PATH": f"{bin_}{os.pathsep}/usr/bin{os.pathsep}/bin", "STUB_LOGS": str(logs),
            "STUB_VERDICTS": str(verdicts), "STUB_LOG": str(tmp / "stub.log")}


def _run_repro_step(tmp: Path, env):
    return subprocess.run(["bash", "-c", _step_run_block(REPRO_STEP)], cwd=tmp, env=env,
                          capture_output=True, text=True, timeout=120)


def _code_lines(text: str):
    """The non-comment lines of a shell body or a YAML file: a word in a comment must not satisfy a check."""
    return "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))


def _fresh(**over):
    """A fresh verdict for example `beta`, equal to the committed one but for `over` (dotted keys allowed)."""
    v = _fake_verdict("", "", "")                       # pins are patched in by _apply below
    return ("beta", over)


class TestGatesReproductionStepIsArmed(unittest.TestCase):
    """The REAL ci.yml step body, in a tree where curl and the tool are stubs: the question is not whether the tool
    judges well (tests/test_gates_*.py) but whether THIS step can go red for each thing it claims to catch.

    After QA round 1 (G266/G267) the checker diffs the WHOLE verdict and binds the committed bars + sidecar to the
    verdict by hash, so the artifact that still passes it is a committed verdict that was wrong on the day it was
    committed under the same bars, sidecar and log -- which is why ADR-023 has QA's independent re-derivation of
    every Tarot number, and why this test cannot replace it."""

    def _committed(self, tmp, name="beta"):
        return json.loads((Path(tmp) / "examples" / name / "verdict.json").read_text())

    def _with_fresh(self, mutate):
        """Build a tree, derive `beta`'s fresh verdict from its committed one via `mutate(verdict)`, run the step."""
        tmp = tempfile.mkdtemp()
        try:
            env = _gates_tree(Path(tmp))
            v = self._committed(tmp)
            mutate(v)
            (Path(tmp) / "stub_verdicts" / "beta.json").write_text(json.dumps(v))
            return _run_repro_step(Path(tmp), env), (Path(tmp) / "stub.log").read_text()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_control_three_identical_examples_are_green_and_the_denominator_is_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _gates_tree(Path(tmp))
            proc = _run_repro_step(Path(tmp), env)
            ran = (Path(tmp) / "stub.log").read_text()
        self.assertEqual(proc.returncode, 0, msg=f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
        self.assertIn("committed gate examples matched: 3", proc.stdout)
        self.assertIn("3/3 examples reproduce their committed verdict, every byte", proc.stdout)
        self.assertEqual(ran.count("tool "), 3, msg=f"the tool must run once per example:\n{ran}")

    def test_every_leaf_that_moves_in_the_fresh_verdict_turns_the_step_red(self):
        """One mutation per subTest, applied to the FRESH verdict only; the step must fail and NAME the leaf.
        The first six are the pre-registered {verdict,n,badge,exit} diff; the rest are QA G266's survivors."""
        def set_(path, value):
            def m(v):
                cur = v
                for k in path[:-1]:
                    cur = cur[k]
                cur[path[-1]] = value
            return m

        def refusal(v):
            v.update(refusal="internal error, no verdict: parser", results=[], exit_code=2, badge="gates: refused")

        cases = (("a should bar slid PASS -> EI", set_(("results", 1, "verdict"), "EVIDENCE_INSUFFICIENT"), ("results[1].verdict", "speed_ceiling")),
                 ("n moved", set_(("results", 0, "n"), 99), ("results[0].n", "99")),
                 ("the badge moved", set_(("badge",), "gates: pass · 3/3 measured (post-hoc)"), ("badge", "3/3")),
                 ("the exit code moved", set_(("exit_code",), 1), ("exit_code",)),
                 ("the sidecar was not bound", lambda v: v.update(prereg=dict(v["prereg"], status="NOT_REGISTERED", post_hoc=False),
                                                                badge="gates: pass · 2/3 measured (unregistered)"), ("HASH_MATCH",)),
                 ("a result was added", lambda v: v["results"].append({"id": "extra_bar", "verdict": "PASS", "n": 1}), ("results[3]",)),
                 ("measured moved (G266)", set_(("results", 1, "measured"), 12.4), ("results[1].measured", "12.4")),
                 ("a bar limit moved (G266)", set_(("results", 1, "bar", "limit"), 99), ("results[1].bar.limit",)),
                 ("a severity moved (G266)", set_(("results", 0, "severity"), "should"), ("results[0].severity",)),
                 ("a note appeared (G266)", set_(("results", 2, "note"), "made up"), ("results[2].note",)),
                 ("integrity erased (G266, G257's evidence)", set_(("integrity", "dsf_dropped_max"), 0), ("integrity.dsf_dropped_max",)),
                 ("the bars hash zeroed (G266)", set_(("bars", "sha256"), "0" * 64), ("bars.sha256",)),
                 ("a stream state moved (G266)", set_(("streams", "position", "state"), "ABSENT"), ("streams.position.state",)),
                 ("the fresh run refused", refusal, ("REFUSED",)),
                 ("a null leaf went absent (G281)", lambda v: v["results"][2].pop("note"), ("results[2].note",)),
                 ("a PASS whose number contradicts its own bar (G284)", set_(("results", 0, "measured"), -20.0), ("CONTRADICTS", "alt_floor")),
                 ("a FAIL whose number satisfies its bar (G284)", lambda v: v["results"][1].update(verdict="FAIL"), ("CONTRADICTS", "speed_ceiling")),
                 ("the fresh run date is not today (G283)", set_(("allowlist", "run_date_utc"), (TODAY - _dt.timedelta(days=1)).isoformat()), ("allowlist.run_date_utc",)),
                 ("a non-finite measured value", set_(("results", 0, "measured"), float("nan")), ("non-finite",)))
        for why, mutate, tokens in cases:
            with self.subTest(why=why):
                proc, _ = self._with_fresh(mutate)
                self.assertNotEqual(proc.returncode, 0, msg=f"[{why}] the step stayed GREEN.\nstdout: {proc.stdout}")
                out = proc.stdout + proc.stderr
                for token in tokens:
                    self.assertIn(token, out, msg=f"[{why}] the red does not name the drift:\n{out}")
                self.assertIn("FAIL beta", out)
                self.assertIn("2/3 examples reproduce", out,
                              msg="the other two must still be judged and counted: one red does not blind the rest")

    def test_the_fresh_run_must_be_on_the_matrix_leg_the_job_declares(self):
        """QA G283: ci.yml passes `PYTHON_LEG=${{ matrix.python-version }}`; the fresh tool.python must start with it."""
        for leg, red in (("3.12", False), ("3.10", True), ("", False)):
            with self.subTest(leg=leg), tempfile.TemporaryDirectory() as tmp:
                env = _gates_tree(Path(tmp))
                proc = _run_repro_step(Path(tmp), {**env, "PYTHON_LEG": leg})
                self.assertEqual(proc.returncode != 0, red, msg=f"[leg={leg!r}]\n{proc.stdout}\n{proc.stderr}")
                if red:
                    self.assertIn("matrix leg", proc.stdout + proc.stderr)

    def test_the_process_exit_is_checked_not_only_the_json(self):
        """A CLI that printed the right JSON but exited 0 on a FAIL would pass the diff alone (QA G273)."""
        with tempfile.TemporaryDirectory() as tmp:
            env = _gates_tree(Path(tmp))
            proc = _run_repro_step(Path(tmp), {**env, "STUB_PROCESS_EXIT": "1"})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("PROCESS exited 1", proc.stdout + proc.stderr)

    def test_a_committed_file_edited_after_the_verdict_is_red_before_the_tool_runs(self):
        """The committed side: bars, sidecar, SOURCE.json and verdict must agree by hash, or nothing is judged."""
        def bars_edited(tmp):
            with open(tmp / "examples" / "beta" / "bars.yaml", "ab") as f:
                f.write(b"# loosened\n")

        def edit_json(rel, change):                         # canonical in, canonical out: only the CONTENT moves
            def m(tmp):
                path = tmp / "examples" / "beta" / rel
                doc = json.loads(path.read_text())
                change(doc)
                path.write_text(_canonical(doc))
            return m

        def bars_edited_and_reregistered(tmp):             # QA G267: the one that passed round 0
            bars_edited(tmp)
            edit_json("bars.yaml.prereg.json", lambda d: d.update(bars_sha256=_sha((tmp / "examples" / "beta" / "bars.yaml").read_bytes())))(tmp)

        def set_url(value):
            return edit_json("SOURCE.json", lambda d: d.update(url=value))

        pinned = f"https://raw.githubusercontent.com/example/fixtures/{'a' * 40}"
        for why, mutate, token in (("bars.yaml edited, sidecar stale", bars_edited, "bars"),
                                   ("bars.yaml edited AND sidecar re-registered (G267)", bars_edited_and_reregistered, "re-registered"),
                                   ("sidecar rewritten with the same pins (an extra key)", edit_json("bars.yaml.prereg.json", lambda d: d.update(note="x")), "sidecar"),
                                   ("verdict names another log", edit_json("verdict.json", lambda d: d["source"].update(sha256="b" * 64)), "WHICH log"),
                                   ("url pins a branch, not a commit", set_url("https://raw.githubusercontent.com/example/fixtures/main/logs/beta.bin"), "commit-pinned"),
                                   ("url pins a SHORT sha (G281)", set_url("https://raw.githubusercontent.com/example/fixtures/aaaaaaa/logs/beta.bin"), "commit-pinned"),
                                   ("url is not https", set_url("file:///etc/beta.bin"), "commit-pinned"),
                                   ("url climbs out of the commit with .. (G279)", set_url(f"{pinned}/../main/logs/beta.bin"), "commit-pinned"),
                                   ("url carries a query string (G279)", set_url(f"{pinned}/logs/beta.bin?token=x"), "commit-pinned"),
                                   ("url carries a fragment (G279)", set_url(f"{pinned}/logs/beta.bin#x"), "commit-pinned"),
                                   ("url owner spelt with a non-ASCII letter (G285)", set_url(f"https://raw.githubusercontent.com/ArduP\u00edlot/x/{'a' * 40}/logs/beta.bin"), "commit-pinned"),
                                   ("SOURCE.json with a duplicate key", lambda tmp: (tmp / "examples" / "beta" / "SOURCE.json").write_text(
                                       (tmp / "examples" / "beta" / "SOURCE.json").read_text().replace('{\n', '{\n "sha256": "' + 'c' * 64 + '",\n', 1)), "duplicate key")):
            with self.subTest(why=why), tempfile.TemporaryDirectory() as tmp:
                env = _gates_tree(Path(tmp))
                mutate(Path(tmp))
                proc = _run_repro_step(Path(tmp), env)
                ran = (Path(tmp) / "stub.log").read_text()
                self.assertNotEqual(proc.returncode, 0, msg=f"[{why}] stayed GREEN.\nstdout: {proc.stdout}")
                self.assertIn(token, proc.stdout + proc.stderr, msg=f"[{why}] the red does not say why")
                self.assertNotIn("tool beta", ran, msg=f"[{why}] the tool ran on an example whose pins disagree")

    def test_the_committed_file_must_be_the_canonical_bytes_of_the_fresh_run(self):
        """QA G277: every one of these parses EQUAL to the fresh verdict (`json.loads` keeps the last duplicate,
        `100.0 == 100`, `False == 0`, a dropped `[]` is just a missing leaf) and GitHub's file view shows the lie.
        Bytes catch all of them. Also QA G278: an excluded leaf is shape-checked, not a free-text slot."""
        bullet = "\\u00b7"                                   # the badge's middle dot, as ensure_ascii writes it
        def text(old, new):
            def m(t):
                self.assertEqual(t.count(old), 1, f"fixture text lacks {old!r}")
                return t.replace(old, new, 1)
            return m
        prepend = lambda line: (lambda t: "{\n" + line + t[2:])       # the file starts with "{\n"
        cases = (("a duplicate badge key, the real one last", text(' "badge": ', f' "badge": "gates: fail {bullet} 0/3 measured (post-hoc)",\n "badge": '), ("duplicate key", "badge")),
                 ("a smuggled path-shaped key", prepend(' "results[1].measured": 2.0,\n'), ("results[1].measured",)),
                 ("a float for an int n", text('"n": 100,', '"n": 100.0,'), ("canonical", "n")),
                 ("false for exit_code 0", text('"exit_code": 0', '"exit_code": false'), ("canonical",)),
                 ("a dropped empty container", text(',\n  "holes": []', ""), ("integrity.holes",)),
                 ("[] turned into {}", text('"holes": []', '"holes": {}'), ("canonical",)),
                 ("an extra leaf only the committed side has", prepend(' "extra": 1,\n'), ("extra",)),
                 ("tool.python as free text (G278)", text('"python": "3.12.12"', '"python": "3.12.12 (independently certified safe)"'), ("tool.python", "free-text")),
                 ("tool.python deleted (G278)", text('  "python": "3.12.12",\n', ""), ("tool.python",)),
                 ("PyYAML as free text (G278)", text('"PyYAML": "6.0.3"', '"PyYAML": "any"'), ("tool.deps.PyYAML",)),
                 ("hand formatting (two-space indent)", lambda t: json.dumps(json.loads(t), indent=2) + "\n", ("canonical",)),
                 ("CRLF line endings (G282)", lambda t: t.replace("\n", "\r\n"), ("canonical",)),
                 ("a lone CR (G282)", lambda t: t.replace("\n", "\r", 1), ("canonical",)),
                 ("a UTF-8 BOM", lambda t: "\ufeff" + t, ("BOM",)),
                 ("tool.python below the floor (G283)", text('"python": "3.12.12"', '"python": "3.8.0"'), ("tool.python",)),
                 ("tool.python off the matrix (G283)", text('"python": "3.12.12"', '"python": "3.11.9"'), ("tool.python",)),
                 ("PyYAML below its pin (G283)", text('"PyYAML": "6.0.3"', '"PyYAML": "6.0"'), ("tool.deps.PyYAML", "outside the pin")),
                 ("an impossible run date (G283)", text(f'"run_date_utc": "{TODAY.isoformat()}"', '"run_date_utc": "9999-99-99"'), ("allowlist.run_date_utc",)),
                 ("a committed run date AFTER the fresh one (G283)", text(f'"run_date_utc": "{TODAY.isoformat()}"', f'"run_date_utc": "{(TODAY + _dt.timedelta(days=1)).isoformat()}"'), ("AFTER",)))
        for why, mutate, tokens in cases:
            with self.subTest(why=why), tempfile.TemporaryDirectory() as tmp:
                env = _gates_tree(Path(tmp))
                v = Path(tmp) / "examples" / "beta" / "verdict.json"
                v.write_bytes(mutate(v.read_bytes().decode("utf-8")).encode("utf-8"))   # bytes: no newline translation
                proc = _run_repro_step(Path(tmp), env)
                self.assertNotEqual(proc.returncode, 0, msg=f"[{why}] stayed GREEN.\nstdout: {proc.stdout}")
                out = proc.stdout + proc.stderr
                self.assertIn("FAIL beta", out, msg=f"[{why}]\n{out}")
                for token in tokens:
                    self.assertIn(token, out, msg=f"[{why}] the red does not say why:\n{out}")

    def test_the_excluded_leaves_are_exactly_three(self):
        """QA G281: widening EXCLUDED by one more leaf (say `integrity.bytes_skipped`) survived every test."""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import check_gates_examples as C
        self.assertEqual(set(C.EXCLUDED), EXCLUDED_LEAVES)
        for leaf, (_, shape) in C.EXCLUDED.items():
            self.assertFalse(shape.match("3.12.12 (independently certified safe)"), leaf)
        self.assertTrue(C.EXCLUDED["tool.python"][1].match("3.10.21") and C.EXCLUDED["tool.deps.PyYAML"][1].match("6.0.3")
                        and C.EXCLUDED["allowlist.run_date_utc"][1].match("2026-11-06"))
        for off in ("3.8.0", "3.11.9", "3.99.999", "3.13.0"):
            self.assertFalse(C.EXCLUDED["tool.python"][1].match(off), msg=f"{off} is not a matrix leg (G283)")

    def test_a_wrong_sha256_is_a_hard_fail_and_the_tool_never_runs_on_those_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _gates_tree(Path(tmp), corrupt=("beta",))
            proc = _run_repro_step(Path(tmp), env)
            ran = (Path(tmp) / "stub.log").read_text()
            pinned = json.loads((Path(tmp) / "examples" / "beta" / "SOURCE.json").read_text())["sha256"]
            fetched = (Path(tmp) / "stub_logs" / "beta.bin").read_bytes()
        self.assertNotEqual(proc.returncode, 0, msg=f"stdout: {proc.stdout}")
        out = proc.stdout + proc.stderr
        self.assertIn("FAIL beta", out)
        for sha in (pinned, _sha(fetched)):
            self.assertIn(sha, out, msg="both hashes must be printed, the pinned and the fetched")
        self.assertIn(f"({len(fetched)} B)", out, msg="the size is printed too -- here it is the SAME size, one bit off")
        self.assertIn("Not judged", out)
        self.assertNotIn("tool beta", ran, msg="the tool ran on bytes that failed the sha256 check -- the hash gate is cosmetic")
        self.assertIn("tool alpha", ran)
        self.assertIn("tool gamma", ran)

    def test_the_denominator_is_exactly_three_pinned_distinct_logs(self):
        def stray_dir(tmp):
            (tmp / "examples" / "stray").mkdir()
            (tmp / "examples" / "stray" / "bars.yaml").write_text("bars: []\n")

        def beta_is_alpha(tmp):
            for f in ("SOURCE.json", "bars.yaml", "bars.yaml.prereg.json", "verdict.json"):
                shutil.copy(tmp / "examples" / "alpha" / f, tmp / "examples" / "beta" / f)
            shutil.copy(tmp / "stub_logs" / "alpha.bin", tmp / "stub_logs" / "beta.bin")

        for why, names, mutate, token in (("two examples", ("alpha", "beta"), None, "matched: 2"),
                                          ("four examples", ("alpha", "beta", "gamma", "delta"), None, "expected exactly 3"),
                                          ("a dir without SOURCE.json", ("alpha", "beta", "gamma"), stray_dir, "SOURCE.json files"),
                                          ("two dirs, one log (G271)", ("alpha", "beta", "gamma"), beta_is_alpha, "more than one example dir")):
            with self.subTest(why=why), tempfile.TemporaryDirectory() as tmp:
                env = _gates_tree(Path(tmp), names=names)
                if mutate:
                    mutate(Path(tmp))
                proc = _run_repro_step(Path(tmp), env)
                self.assertNotEqual(proc.returncode, 0, msg=f"[{why}] stayed GREEN.\nstdout: {proc.stdout}")
                self.assertIn(token, proc.stdout + proc.stderr, msg=f"[{why}]\n{proc.stdout}\n{proc.stderr}")

    def test_the_tool_missing_from_path_is_red_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _gates_tree(Path(tmp), tool=False)
            proc = _run_repro_step(Path(tmp), env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("swathkeeper-gates", proc.stderr)
        self.assertIn("not on PATH", proc.stderr)

    def test_a_committed_badge_svg_must_equal_a_render_of_the_fresh_badge(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from render_gates_badge import render_svg
        for why, svg, red in (("stale SVG", "<svg>edited by hand</svg>", True),
                              ("fresh render", render_svg("swathkeeper-gates", FAKE_BADGE), False)):
            with self.subTest(why=why), tempfile.TemporaryDirectory() as tmp:
                env = _gates_tree(Path(tmp))
                (Path(tmp) / "examples" / "alpha" / "badge.svg").write_text(svg)
                proc = _run_repro_step(Path(tmp), env)
                self.assertEqual(proc.returncode != 0, red, msg=f"[{why}] stdout: {proc.stdout}\nstderr: {proc.stderr}")
                self.assertIn("badge.svg", proc.stdout + proc.stderr)

    def test_the_real_invocation_is_not_swallowed(self):
        """Read on NON-COMMENT lines only (QA G273: a `curl -fL` in a comment satisfied the old regex)."""
        for step in (REPRO_STEP, DEMO_FETCH_STEP):
            with self.subTest(step=step):
                body = _step_run_block(step)
                code = _code_lines(body)
                self.assertIn("set -euo pipefail", code)
                self.assertNotIn("set +e", code)
                curls = [ln for ln in code.splitlines() if re.search(r"\bcurl\b", ln)]
                self.assertTrue(curls, f"no curl in the {step!r} step")
                for ln in curls:
                    self.assertRegex(ln, r"\bcurl\s+-\w*f", msg=f"curl without -f: an HTTP 404 page is saved as the 'log': {ln!r}")
                    for flag in ("--proto '=https'", "--proto-redir '=https'"):
                        self.assertIn(flag, ln, msg=f"curl may follow a redirect off https ({flag} missing): {ln!r}")
                for swallow in ("|| true", "|| :", "continue-on-error"):
                    self.assertNotIn(swallow, code, msg=f"{step!r} swallows a failure with {swallow!r}")
        code = _code_lines(_step_run_block(REPRO_STEP))
        self.assertTrue([ln for ln in code.splitlines() if "check_gates_examples.py" in ln], "the step no longer runs the checker")
        self.assertIn("sha256sum -c", _code_lines(_step_run_block(DEMO_FETCH_STEP)), "the demo logs are not sha256-checked before the Action")
        step = next(s for s in _job_steps(GATES_JOB) if REPRO_STEP in s[0])
        self.assertFalse([ln for ln in step[1] if ln.startswith("continue-on-error")],
                         msg="the reproduction step itself must be allowed to fail the job")


class TestCommittedGateExamplesAreConsistent(unittest.TestCase):
    """The committed `examples/` the reproduction job will judge: three by name and sha256, four files each."""

    def test_exactly_the_three_design_logs_are_committed_each_with_its_four_files_and_its_pin(self):
        dirs = sorted({p.split("/")[1] for p in _tracked("examples/*/SOURCE.json")})
        self.assertEqual(dirs, sorted(DESIGN_EXAMPLES), msg="design §8 / ADR-023 D7 pin three public logs by name; "
                         "adding or removing one is a reviewed change to ci.yml's `-ne 3` line and to this map")
        self.assertEqual(sorted({p.split("/")[1] for p in _tracked("examples/*")}), dirs,
                         msg="an examples/ dir without a SOURCE.json is a verdict nobody can re-fetch")
        for name, (sha, url) in DESIGN_EXAMPLES.items():
            for f in ("SOURCE.json", "bars.yaml", "bars.yaml.prereg.json", "verdict.json"):
                self.assertTrue(_tracked(f"examples/{name}/{f}"), msg=f"examples/{name}/{f} is not committed")
            extra = {p.rsplit("/", 1)[1] for p in _tracked(f"examples/{name}/*")} - EXAMPLE_FILES
            self.assertEqual(extra, set(), msg=f"examples/{name}/ carries files the job never judges (QA G280): {extra}")
            source = json.loads((REPO_ROOT / "examples" / name / "SOURCE.json").read_text())
            self.assertEqual((source["sha256"], source["url"]), (sha, url),
                             msg=f"{name}: the pinned log or its url changed -- a reviewed diff, here and in ADR-023")
            for f in ("SOURCE.json", "bars.yaml.prereg.json", "verdict.json"):
                t = (REPO_ROOT / "examples" / name / f).read_bytes().decode("utf-8")     # bytes: CRLF must not pass (G282)
                self.assertEqual(t, _canonical(json.loads(t)), msg=f"examples/{name}/{f} is not in canonical form (QA G277)")
        self.assertEqual([p for p in _tracked("examples/") if p.lower().endswith((".bin", ".log", ".ulg"))], [],
                         msg="a third-party log is committed -- design §8's fixture rule forbids it (licence)")

    def test_the_pins_agree_and_the_sidecar_binds_the_committed_bars_so_the_run_reads_post_hoc(self):
        for name in DESIGN_EXAMPLES:
            with self.subTest(example=name):
                ex = REPO_ROOT / "examples" / name
                source = json.loads((ex / "SOURCE.json").read_text())
                sidecar_bytes = (ex / "bars.yaml.prereg.json").read_bytes()
                sidecar = json.loads(sidecar_bytes)
                verdict = json.loads((ex / "verdict.json").read_text())
                bars_sha = _sha((ex / "bars.yaml").read_bytes())
                self.assertEqual({source["sha256"], sidecar["log_sha256"], verdict["source"]["sha256"]}, {source["sha256"]},
                                 msg="SOURCE.json, the sidecar and the verdict name different logs")
                self.assertEqual({sidecar["bars_sha256"], verdict["bars"]["sha256"], verdict["prereg"]["bars_sha256_registered"]}, {bars_sha},
                                 msg="the committed bars.yaml is not the one the verdict was judged under (G267)")
                self.assertEqual(verdict["prereg"]["sidecar_sha256"], _sha(sidecar_bytes), msg="the sidecar was re-registered after the verdict")
                self.assertEqual((verdict["prereg"]["status"], verdict["prereg"]["post_hoc"]), ("HASH_MATCH", True))
                self.assertTrue(verdict["badge"].endswith("(post-hoc)"), verdict["badge"])
                word = verdict["badge"].split("gates: ", 1)[1].split(" ·", 1)[0]
                self.assertEqual(verdict["exit_code"], 0 if word == "pass" else 1, msg=f"{word!r} vs exit {verdict['exit_code']}")
                self.assertEqual(source["size_bytes"], verdict["source"]["size_bytes"])

    def test_the_numbers_adr_023_publishes_are_the_committed_ones(self):
        """QA G284: a buggy tool committed WITH its regenerated verdicts reproduces byte for byte. The one thing outside
        that loop is the record: ADR-023's published values (QA re-derived with raw pymavlink). Pinned here."""
        published = {("tarot_x4", "alt_floor"): (0.0147, 4), ("tarot_x4", "speed_ceiling_loiter"): (2.421, 3),
                     ("tarot_x4", "battery_floor"): (23.48, 2), ("tarot_x4", "ekf_vel_ceiling"): (0.11, 2),
                     ("tarot_x4", "geofence"): (115.743, 3), ("tarot_x4", "no_errors"): (0, 0),
                     ("plane_nofix", "gnss_quality"): (52.72, 2), ("pymavlink_test_bin", "battery_floor"): (12.39, 2)}
        for (name, bar), (value, places) in published.items():
            with self.subTest(example=name, bar=bar):
                results = {r["id"]: r for r in json.loads((REPO_ROOT / "examples" / name / "verdict.json").read_text())["results"]}
                self.assertEqual(round(results[bar]["measured"], places), value,
                                 msg=f"{name}/{bar}: the committed measured value is not the one ADR-023 publishes")

    def test_the_readme_badge_is_the_tarot_verdict_verbatim_and_regenerates_byte_identical(self):
        verdict = json.loads((REPO_ROOT / "examples" / "tarot_x4" / "verdict.json").read_text())
        self.assertEqual((verdict["badge"], verdict["exit_code"]), (TAROT_BADGE, 1))
        svg = REPO_ROOT / "examples" / "tarot_x4" / "badge.svg"
        self.assertTrue(_tracked("examples/tarot_x4/badge.svg"), "the README badge SVG is not committed")
        proc = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "render_gates_badge.py"),
                               str(REPO_ROOT / "examples" / "tarot_x4" / "verdict.json"), "--label", TAROT_LABEL,
                               "--check", str(svg)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, msg=f"badge.svg is stale: {proc.stderr}")
        self.assertIn(TAROT_BADGE, svg.read_text(), "the SVG does not carry the badge string verbatim")
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from render_gates_badge import render_svg
        self.assertNotEqual(render_svg(TAROT_LABEL, TAROT_BADGE.replace("7/8", "6/8")), svg.read_text(),
                            msg="--check would pass a different badge: the comparison is vacuous")
        readme = (REPO_ROOT / "README.md").read_text()
        self.assertIn("examples/tarot_x4/badge.svg", readme, "README.md does not show the badge")
        self.assertIn(TAROT_BADGE, readme, "README.md's badge line must quote the string the image depicts")

    def test_only_pass_is_painted_green(self):
        """QA G273: a renderer painting `fail` or `could not tell` green survived every test."""
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from render_gates_badge import render_svg
        green = 'fill="#4c1"'
        self.assertIn(green, render_svg("x", "gates: pass · 1/1 measured"))
        self.assertIn("· 1 assumed (post-hoc)", render_svg("x", "gates: pass · 1/1 measured · 1 assumed (post-hoc)"))   # A7
        for word in ("fail", "could not tell", "refused", "passing", "PASS", "green"):
            with self.subTest(word=word):
                self.assertNotIn(green, render_svg("x", f"gates: {word} · 1/1 measured"), msg=f"{word!r} painted green")
        self.assertIn('fill="#e05d44"', render_svg("x", "gates: fail · 0/1 measured"))
        import xml.etree.ElementTree as ET
        ET.fromstring(render_svg('say "hi" & <x>', 'gates: pass · 1/1 measured "q"'))   # QA G274/G281: quotes escaped


class TestGatesJobKeepsEveryGateReporting(unittest.TestCase):
    """TestNoRedCanHideBehindTheDeclaredOne, applied to the gates-tool job, plus its matrix and its one probe."""

    FIRST_FALLIBLE = "Gates tool unit tests"

    def test_every_step_after_the_unit_tests_runs_anyway(self):
        steps = _job_steps(GATES_JOB)
        names = [n for n, _ in steps]
        idx = next(i for i, n in enumerate(names) if n.startswith(self.FIRST_FALLIBLE))
        after = steps[idx + 1:]
        self.assertGreaterEqual(len(after), 4, "suspiciously few gates after the unit tests")
        missing = [n for n, body in after if not any(ln.startswith("if:") and "always()" in ln for ln in body)]
        self.assertEqual(missing, [], msg="gates-tool steps that would be SKIPPED behind a red unit test:\n"
                                          + "\n".join("    " + n for n in missing))

    def test_the_matrix_tests_exactly_the_interpreters_requires_python_promises(self):
        """Design §1: `requires-python = ">=3.10"` ONLY if CI tests 3.10 and 3.12. The floor is the lowest leg."""
        lines = " ".join(_job_lines(GATES_JOB))
        legs = re.search(r"python-version:\s*\[([^\]]*)\]", lines)
        self.assertIsNotNone(legs, "gates-tool has no python-version matrix")
        versions = sorted(v.strip().strip('"') for v in legs.group(1).split(","))
        self.assertEqual(versions, ["3.10", "3.12"])
        floor = re.search(r'requires-python\s*=\s*">=([0-9.]+)"', (REPO_ROOT / "pyproject.toml").read_text())
        self.assertIsNotNone(floor)
        self.assertEqual(floor.group(1), versions[0], msg="the pyproject floor must equal the lowest tested leg")

    def test_the_two_action_steps_judge_their_own_logs_with_their_own_bars(self):
        steps = dict(_job_steps(GATES_JOB))
        tarot = " ".join(next(b for n, b in steps.items() if "Tarot X4 must exit 1" in n))
        plane = " ".join(next(b for n, b in steps.items() if "must FAIL this step" in n))
        for body, name in ((tarot, "tarot_x4"), (plane, "plane_nofix")):
            self.assertIn("uses: ./.github/actions/swathkeeper-gates", body)
            self.assertIn(f"steps.demo-logs.outputs.{name}", body, f"the {name} step is not pointed at the {name} log")
            self.assertIn(f"examples/{name}/bars.yaml", body)
        self.assertNotIn("tarot_x4", plane, "the no-softening probe must run the log whose correct verdict is exit 1")

    def test_only_the_no_softening_probes_carry_continue_on_error_and_the_assertions_really_assert(self):
        """QA G273: `[ … ] || true` and a dropped CODE check in the assertion steps survived. So the two assertion
        bodies are EXECUTED here with OUTCOME / CODE / BADGE set the way a softened Action run would set them. Since
        v0.2.0 (G257) both demo logs' correct verdict is exit 1, so exactly two steps are soft, each asserted next."""
        steps = _job_steps(GATES_JOB)
        soft = [i for i, (_, body) in enumerate(steps) if any(ln.startswith("continue-on-error") for ln in body)]
        self.assertEqual(len(soft), 2, msg=f"continue-on-error on {[steps[i][0] for i in soft]}")
        for i, name, check in zip(soft, ("tarot_x4", "plane_nofix"), (TAROT_ASSERT_STEP, PLANE_ASSERT_STEP)):
            self.assertIn(f"examples/{name}/bars.yaml", " ".join(steps[i][1]), "a probe must be a log whose correct verdict is exit 1")
            self.assertIn(check, steps[i + 1][0], "the step right after a probe must assert its outcome")
        tarot_badge = json.loads((REPO_ROOT / "examples" / "tarot_x4" / "verdict.json").read_text())["badge"]
        plane_badge = json.loads((REPO_ROOT / "examples" / "plane_nofix" / "verdict.json").read_text())["badge"]
        cases = ((PLANE_ASSERT_STEP, "failure", "1", plane_badge, 0),       # the honest run: the step was red, exit 1
                 (PLANE_ASSERT_STEP, "success", "0", plane_badge, 1),       # a softened Action: green on a FAIL log
                 (PLANE_ASSERT_STEP, "failure", "2", plane_badge, 1),       # red for the wrong reason (a refusal)
                 (PLANE_ASSERT_STEP, "failure", "1", tarot_badge, 1),       # red with the wrong verdict
                 (TAROT_ASSERT_STEP, "failure", "1", tarot_badge, 0),
                 (TAROT_ASSERT_STEP, "success", "0", tarot_badge, 1),
                 (TAROT_ASSERT_STEP, "failure", "2", tarot_badge, 1),
                 (TAROT_ASSERT_STEP, "failure", "1", plane_badge, 1))
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(sys.executable, Path(tmp) / "python3")
            env = {**os.environ, "PATH": f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}"}
            for step, outcome, code, badge, want in cases:
                with self.subTest(step=step, outcome=outcome, code=code, badge=badge[:12]):
                    proc = subprocess.run(["bash", "-c", _step_run_block(step)], cwd=REPO_ROOT, capture_output=True, text=True,
                                          env={**env, "OUTCOME": outcome, "CODE": code, "BADGE": badge}, timeout=60)
                    self.assertEqual(proc.returncode != 0, want != 0,
                                     msg=f"[{step}] OUTCOME={outcome} CODE={code} -> exit {proc.returncode}, expected {want}\n{proc.stdout}{proc.stderr}")


    def test_the_success_path_runs_the_readme_walkthrough_bars_and_asserts_a_green(self):
        """QA G325/G332: both real-log probes exit 1, so one step trio runs the Action's green path on the Tarot log with
        the tool README's walkthrough: its bars written inline and hashed, registered with `prereg` as the README does, and
        the run's bar line and badge required verbatim in the README, so the README and CI cannot drift apart silently."""
        steps = dict(_job_steps(GATES_JOB))
        lines = next(b for n, b in steps.items() if "The Action's success path" in n)
        for want in ("uses: ./.github/actions/swathkeeper-gates", "steps.demo-logs.outputs.tarot_x4", "walkthrough_bars.yaml"):
            self.assertIn(want, " ".join(lines))
        self.assertFalse(any(ln.startswith("continue-on-error") for ln in lines), "the green path may not be soft")
        block = lambda text: text.split("### 2. Write the bars", 1)[1].split("```yaml\n", 1)[1].split("```", 1)[0]
        readme = (REPO_ROOT / "src" / "swathkeeper_gates" / "README.md").read_text()
        self.assertEqual(hashlib.sha256(block(readme).encode()).hexdigest(), WALKTHROUGH_SHA256,
                         msg="the README walkthrough's bars changed: re-pin it here and in ci.yml together")
        self.assertEqual(block("moved prose\n" + readme.replace("## Install", "## Install it")), block(readme))   # by content
        self.assertNotEqual(block(readme.replace("min_n: 30", "min_n: 31")), block(readme))
        green, verdict = "gates: pass · 1/1 measured (post-hoc)", {"verdict": "PASS", "severity": "must", "id": "batt_floor",
                                                                   "n": 1419, "measured": 23.48213005065918}
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink(sys.executable, Path(tmp) / "python3")
            (Path(tmp) / "swathkeeper-gates").write_text('#!/bin/bash\necho "$@" > "$RUNNER_TEMP/called"\n')
            (Path(tmp) / "swathkeeper-gates").chmod(0o755)
            env = {**os.environ, "PATH": f"{tmp}{os.pathsep}{os.environ.get('PATH', '')}", "RUNNER_TEMP": tmp, "TAROT": "t.bin"}
            write = subprocess.run(["bash", "-c", _step_run_block("one-bar walkthrough bars")], capture_output=True, text=True, env=env)
            self.assertEqual(write.returncode, 0, msg=write.stdout + write.stderr)   # the heredoc hashes as pinned
            called = Path(tmp) / "called"                 # the README's step 3, so the badge reads (post-hoc)
            self.assertEqual(called.exists() and called.read_text().split(), ["prereg", "--bars", f"{tmp}/walkthrough_bars.yaml", "--log", "t.bin"])
            for outcome, code, badge, n, want in (("success", "0", green, 1419, 0), ("failure", "1", green, 1419, 1),
                                                  ("success", "0", TAROT_BADGE, 1419, 1), ("success", "1", green, 1419, 1),
                                                  ("success", "0", "gates: pass · 1/1 measured (unregistered)", 1419, 1),
                                                  ("success", "0", green, 1418, 1)):          # the README's n drifted
                with self.subTest(outcome=outcome, code=code, badge=badge[-14:], n=n):
                    (Path(tmp) / "v.json").write_text(json.dumps({"results": [{**verdict, "n": n}]}))
                    proc = subprocess.run(["bash", "-c", _step_run_block("the walkthrough step passed")], capture_output=True, cwd=REPO_ROOT,
                                          text=True, env={**env, "OUTCOME": outcome, "CODE": code, "BADGE": badge,
                                                          "VERDICT": f"{tmp}/v.json"}, timeout=60)
                    self.assertEqual(proc.returncode != 0, want != 0, msg=proc.stdout + proc.stderr)

class TestTheActionNeverSoftensTheExitCode(unittest.TestCase):
    """`.github/actions/swathkeeper-gates/run.sh`, with a stub tool and with the real one. The composite action's
    YAML is read, not executed (no runner here); the contract it declares is pinned by string."""

    def _run(self, tmp: Path, tool_script: str, out: Path, extra_env=None):
        bin_ = tmp / "bin"
        bin_.mkdir(exist_ok=True)
        (bin_ / "swathkeeper-gates").write_text(tool_script)
        (bin_ / "swathkeeper-gates").chmod(0o755)
        if not (bin_ / "python3").exists():
            os.symlink(sys.executable, bin_ / "python3")
        gh_out = tmp / "github_output"
        env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}", "GITHUB_OUTPUT": str(gh_out),
               "LOG": str(tmp / "flight.bin"), "BARS": str(tmp / "bars.yaml"), "OUT": str(out), **(extra_env or {})}
        proc = subprocess.run(["bash", str(ACTION_DIR / "run.sh")], cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
        lines = gh_out.read_text().splitlines() if gh_out.exists() else []
        return proc, dict(ln.split("=", 1) for ln in lines), lines

    @staticmethod
    def _stub(code, badge, write=True):
        return STUB_RUN_TOOL.format(python=sys.executable, write=write, badge=badge, code=code)

    def test_exit_1_and_2_fail_the_step_with_the_outputs_already_written(self):
        cases = (("fail", 1, "gates: fail · 1/5 measured (post-hoc)", True),
                 ("could not tell", 1, "gates: could not tell · 3/6 measured (post-hoc)", True),
                 ("refused, verdict written", 2, "gates: refused", True),
                 ("refused, --out unwritable (no file)", 2, "gates: refused", False),
                 ("pass", 0, "gates: pass · 8/8 measured (post-hoc)", True))
        for why, code, badge, write in cases:
            with self.subTest(why=why), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "verdict.json"
                proc, outputs, _ = self._run(Path(tmp), self._stub(code, badge, write), out)
                self.assertEqual(proc.returncode, code, msg=f"[{why}] run.sh exited {proc.returncode}, the tool {code}.\n"
                                                            f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
                self.assertEqual(outputs, {"exit-code": str(code), "badge": badge, "verdict": str(out)},
                                 msg=f"[{why}] outputs must be written before the exit, red or not")

    def test_a_stale_verdict_at_out_is_never_reported_as_this_runs(self):
        """QA G268: with an old verdict.json at --out and a tool that refuses before writing, the outputs read the
        OLD badge. run.sh now removes the file first; a stale badge here is a forged green."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "verdict.json"
            out.write_text(json.dumps({"badge": "gates: pass · 8/8 measured (post-hoc)", "exit_code": 0}))
            proc, outputs, _ = self._run(Path(tmp), self._stub(2, "unused", write=False), out)
            self.assertEqual((proc.returncode, outputs["exit-code"], outputs["badge"]), (2, "2", "gates: refused"))
            self.assertFalse(out.exists(), "the stale file survived")

    def test_a_stale_out_that_cannot_be_removed_refuses_and_a_multiline_badge_is_flattened(self):
        """QA G281: the `[ ! -e "$OUT" ] || refuse` guard and the badge flattening had no test pinning them."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "verdict.json"
            out.mkdir()
            (out / "keep").write_text("a non-empty directory: rm -f cannot remove it")
            proc, outputs, _ = self._run(Path(tmp), self._stub(0, "gates: pass · 1/1 measured"), out)
            self.assertEqual((proc.returncode, outputs["exit-code"], outputs["badge"]), (2, "2", "gates: refused"), msg=proc.stderr)
            self.assertIn("stale file", proc.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "verdict.json"
            proc, outputs, lines = self._run(Path(tmp), self._stub(1, "gates: fail · 0/1 measured\nexit-code=0"), out)
            self.assertEqual((proc.returncode, len(lines), outputs["exit-code"]), (1, 3, "1"), msg=f"forged lines: {lines}")
            self.assertEqual(outputs["badge"], "gates: fail · 0/1 measured exit-code=0")

    def test_a_missing_or_line_broken_input_is_a_refusal_with_outputs(self):
        """QA G269/G270: `${LOG:?}` exited 1 with NO outputs; a line break in `out` forged a second output line."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "verdict.json"
            proc, outputs, lines = self._run(Path(tmp), self._stub(0, "gates: pass · 1/1 measured"), out, {"LOG": ""})
            self.assertEqual((proc.returncode, outputs), (2, {"exit-code": "2", "badge": "gates: refused", "verdict": str(out)}))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "verdict.json"
            forged = f"{out}\nexit-code=0\nbadge=gates: pass · 9/9 measured"
            proc, outputs, lines = self._run(Path(tmp), self._stub(1, "gates: fail · 0/1 measured"), out, {"OUT": forged})
            self.assertEqual(proc.returncode, 2, msg=proc.stderr)
            self.assertEqual(len(lines), 3, msg=f"forged output lines: {lines}")
            self.assertEqual(outputs["exit-code"], "2")

    def test_optional_inputs_reach_the_tool_only_when_set_and_paths_are_never_options(self):
        """QA G273: dropping `--declared` or `--prereg` from run.sh survived every test. And QA G268: a path that
        starts with '-' must reach the tool as a path (`--log=-x`), not be parsed as an option."""
        with tempfile.TemporaryDirectory() as tmp:
            args = Path(tmp) / "argv"
            self._run(Path(tmp), self._stub(0, "gates: pass · 1/1 measured"), Path(tmp) / "v.json",
                      {"STUB_ARGS": str(args), "DECLARED": "d.yaml", "PREREG": "p.json", "LOG": "-flight.bin"})
            got = args.read_text().splitlines()
            self.assertEqual(got, ["run", "--log=-flight.bin", f"--bars={tmp}/bars.yaml", f"--out={tmp}/v.json",
                                   "--declared=d.yaml", "--prereg=p.json"])
            self._run(Path(tmp), self._stub(0, "gates: pass · 1/1 measured"), Path(tmp) / "v.json", {"STUB_ARGS": str(args)})
            self.assertFalse([a for a in args.read_text().splitlines() if a.startswith(("--declared", "--prereg"))])

    def test_the_real_tool_through_the_action_on_a_synthetic_log(self):
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from test_gates_adapter import flight_rows, write_synthetic_log
        from test_gates_verdict import BARS
        wrapper = (f"#!/bin/bash\nexport PYTHONPATH={REPO_ROOT / 'src'}\n"
                   f"exec {sys.executable} -m swathkeeper_gates.cli \"$@\"\n")
        with tempfile.TemporaryDirectory() as tmp:
            write_synthetic_log(Path(tmp) / "flight.bin", flight_rows())
            (Path(tmp) / "bars.yaml").write_text(BARS)
            out = Path(tmp) / "verdict.json"
            proc, outputs, _ = self._run(Path(tmp), wrapper, out)
            verdict = json.loads(out.read_text())
        self.assertEqual(proc.returncode, 0, msg=f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
        self.assertEqual(outputs["badge"], verdict["badge"])
        self.assertTrue(outputs["badge"].endswith("(unregistered)"), outputs["badge"])  # no sidecar beside these bars: SAID
        self.assertEqual(outputs["exit-code"], "0")

    def test_action_yml_declares_the_contract_installs_from_its_own_checkout_and_carries_no_softener(self):
        text = (ACTION_DIR / "action.yml").read_text()
        self.assertIn("using: composite", text)
        for out in ("exit-code:", "badge:", "verdict:"):
            self.assertIn(out, text)
        self.assertRegex(text, r"log:\s*\n\s+description:[^\n]*\n\s+required: true")
        self.assertRegex(text, r"bars:\s*\n\s+description:(?:[^\n]*\n)+?\s+required: true")
        self.assertIn('run: bash "${GITHUB_ACTION_PATH}/run.sh"', text)
        code = _code_lines(text)
        self.assertIn('root="$(cd "${GITHUB_ACTION_PATH}/../../.." && pwd)"', code,
                      "the Action must install the tool from ITS OWN checkout, so the judge is pinned to the action's ref")
        self.assertFalse(re.search(r"pip install[^\n]*swathkeeper-gates", code), "the Action installs the tool from an index, not its ref")
        for f in ("action.yml", "run.sh"):
            code = _code_lines((ACTION_DIR / f).read_text())
            for swallow in ("continue-on-error", "|| true", "|| :", "set +e"):
                self.assertNotIn(swallow, code.replace('rm -f -- "$OUT" 2>/dev/null || true', ""),   # the one `|| true`: on rm, re-checked
                                 msg=f"{f} softens the exit code: {swallow!r}")
        run_sh = (ACTION_DIR / "run.sh").read_text()
        self.assertIn('exit "$rc"', run_sh)
        self.assertIn("set -euo pipefail", run_sh)
        self.assertTrue(_tracked(".github/actions/swathkeeper-gates/run.sh"))


if __name__ == "__main__":
    unittest.main()
