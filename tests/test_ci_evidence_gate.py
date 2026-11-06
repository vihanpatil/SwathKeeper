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
import hashlib
import json
import math
import os
import re
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
ACTION_DIR = REPO_ROOT / ".github" / "actions" / "swathkeeper-gates"
DESIGN_EXAMPLES = ("plane_nofix", "pymavlink_test_bin", "tarot_x4")   # design §8 / ADR-023 D7: three, by name
TAROT_BADGE = "gates: pass · 8/8 measured (post-hoc)"                 # the README badge, verbatim (ADR-023)
TAROT_LABEL = "tarot_x4 · public log"                                  # scripts/check_gates_examples.BADGE_LABELS
FAKE_RESULTS = (("alt_floor", "PASS", 100, 1.5), ("speed_ceiling", "PASS", 50, 2.0),
                ("no_errors", "EVIDENCE_INSUFFICIENT", 0, None))
FAKE_BADGE = "gates: pass · 2/3 measured (post-hoc)"

STUB_CURL = """#!/bin/bash
# stub curl for the reproduction step: `curl -fsSL --retry N --retry-delay N -o <path> <url>`
out=""; url=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2;;
    --retry|--retry-delay|--max-time) shift 2;;
    -*) shift;;
    *) url="$1"; shift;;
  esac
done
echo "curl $url -> $out" >> "$STUB_LOG"
src="$STUB_LOGS/$(basename "$url")"
[ -f "$src" ] || { echo "stub curl: 404 $url" >&2; exit 22; }
cp "$src" "$out"
"""

STUB_TOOL = """#!{python}
# stub swathkeeper-gates: writes $STUB_VERDICTS/<example dir name>.json to --out and exits with its exit_code
import json, os, sys
a = sys.argv[1:]
bars, out = a[a.index("--bars") + 1], a[a.index("--out") + 1]
name = os.path.basename(os.path.dirname(os.path.abspath(bars)))
with open(os.environ["STUB_LOG"], "a") as f:
    f.write("tool " + name + "\\n")
with open(os.path.join(os.environ["STUB_VERDICTS"], name + ".json")) as f:
    v = json.load(f)
with open(out, "w") as f:
    json.dump(v, f)
sys.exit(v["exit_code"])
"""


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _fake_verdict(log_sha, results=FAKE_RESULTS, badge=FAKE_BADGE, exit_code=0, status="HASH_MATCH", post_hoc=True):
    return {"schema": "swathkeeper-verdict/1.0", "tool": {"version": "0.1.0", "python": "3.12.12", "deps": {}},
            "source": {"sha256": log_sha}, "prereg": {"status": status, "post_hoc": post_hoc},
            "results": [{"id": i, "verdict": v, "n": n, "measured": m} for i, v, n, m in results],
            "badge": badge, "exit_code": exit_code, "refusal": None}


def _gates_tree(tmp: Path, names=("alpha", "beta", "gamma"), fresh=None, corrupt=(), tool=True):
    """A temp repo with `names` fake example dirs, the REAL scripts/, and stub `curl` + `swathkeeper-gates` on PATH.

    Each example's committed verdict is `_fake_verdict`; the stub tool writes `fresh[name]` (default: identical).
    `corrupt` names examples whose fetched bytes differ from the SOURCE.json pin. Returns the env for the step."""
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
        (logs / f"{name}.bin").write_bytes(log_bytes + (b"!" if name in corrupt else b""))
        (ex / "SOURCE.json").write_text(json.dumps({"url": f"https://example.invalid/logs/{name}.bin",
                                                    "sha256": _sha(log_bytes), "size_bytes": len(log_bytes),
                                                    "licence": "test fixture"}))
        (ex / "bars.yaml").write_bytes(bars)
        (ex / "bars.yaml.prereg.json").write_text(json.dumps({"schema": "swathkeeper-prereg/1.0", "bars_sha256": _sha(bars),
                                                              "tool_version": "0.1.0", "written_utc": "2026-11-05T00:00:00+00:00",
                                                              "log_sha256": _sha(log_bytes)}))
        committed = _fake_verdict(_sha(log_bytes))
        (ex / "verdict.json").write_text(json.dumps(committed))
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


class TestGatesReproductionStepIsArmed(unittest.TestCase):
    """The REAL ci.yml step body, in a tree where curl and the tool are stubs: the question is not whether the tool
    judges well (tests/test_gates_*.py) but whether THIS step can go red for each thing it claims to catch. The
    one artifact that would pass it while the verdicts are wrong is a fetched log with the pinned sha256 whose
    committed verdict was wrong on the day it was committed -- which is why ADR-023 has QA's independent
    re-derivation of every Tarot number, and why this test cannot replace it."""

    def test_control_three_identical_examples_are_green_and_the_denominator_is_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _gates_tree(Path(tmp))
            proc = _run_repro_step(Path(tmp), env)
            ran = (Path(tmp) / "stub.log").read_text()
        self.assertEqual(proc.returncode, 0, msg=f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
        self.assertIn("committed gate examples matched: 3", proc.stdout)
        self.assertIn("3/3 examples reproduce", proc.stdout)
        self.assertEqual(ran.count("tool "), 3, msg=f"the tool must run once per example:\n{ran}")

    def test_every_drift_the_pre_registered_diff_names_turns_the_step_red(self):
        """One mutation per subTest, each applied to the FRESH verdict only; the step must fail and NAME it."""
        base = _fake_verdict("")
        slid = json.loads(json.dumps(base))
        slid["results"][1]["verdict"] = "EVIDENCE_INSUFFICIENT"           # the `should` bar sliding PASS -> EI (design §9)
        n_moved = json.loads(json.dumps(base))
        n_moved["results"][0]["n"] = 99
        badge_moved = dict(base, badge="gates: pass · 3/3 measured (post-hoc)")
        exit_moved = dict(base, exit_code=1)
        unbound = dict(base, prereg={"status": "NOT_REGISTERED", "post_hoc": False},
                       badge="gates: pass · 2/3 measured (unregistered)")
        extra = json.loads(json.dumps(base))
        extra["results"].append({"id": "extra_bar", "verdict": "PASS", "n": 1, "measured": 0})
        for why, fresh, names in ((" a should bar slid PASS -> EI", slid, ("speed_ceiling", "EVIDENCE_INSUFFICIENT")),
                                  ("n moved", n_moved, ("alt_floor", "99")),
                                  ("the badge moved", badge_moved, ("badge", "3/3")),
                                  ("the exit code moved", exit_moved, ("exit code",)),
                                  ("the sidecar was not bound", unbound, ("HASH_MATCH",)),
                                  ("a result was added", extra, ("4 results",))):
            with self.subTest(why=why), tempfile.TemporaryDirectory() as tmp:
                env = _gates_tree(Path(tmp), fresh={"beta": fresh})
                proc = _run_repro_step(Path(tmp), env)
                self.assertNotEqual(proc.returncode, 0, msg=f"[{why}] the step stayed GREEN.\nstdout: {proc.stdout}")
                for token in names:
                    self.assertIn(token, proc.stdout + proc.stderr, msg=f"[{why}] the red does not name the drift")
                self.assertIn("FAIL beta", proc.stdout + proc.stderr)
                self.assertIn("2/3 examples reproduce", proc.stdout + proc.stderr,
                              msg="the other two must still be judged and counted: one red does not blind the rest")

    def test_a_wrong_sha256_is_a_hard_fail_and_the_tool_never_runs_on_those_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _gates_tree(Path(tmp), corrupt=("beta",))
            proc = _run_repro_step(Path(tmp), env)
            ran = (Path(tmp) / "stub.log").read_text()
            pinned = json.loads((Path(tmp) / "examples" / "beta" / "SOURCE.json").read_text())["sha256"]
            fetched = _sha((Path(tmp) / "stub_logs" / "beta.bin").read_bytes())
        self.assertNotEqual(proc.returncode, 0, msg=f"stdout: {proc.stdout}")
        out = proc.stdout + proc.stderr
        self.assertIn("FAIL beta", out)
        for sha in (pinned, fetched):
            self.assertIn(sha, out, msg="both hashes must be printed, the pinned and the fetched")
        self.assertIn("Not judged", out)
        self.assertNotIn("tool beta", ran, msg="the tool ran on bytes that failed the sha256 check -- the hash gate is cosmetic")
        self.assertIn("tool alpha", ran)
        self.assertIn("tool gamma", ran)

    def test_two_examples_instead_of_three_is_red_with_the_count_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = _gates_tree(Path(tmp), names=("alpha", "beta"))
            proc = _run_repro_step(Path(tmp), env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("matched: 2", proc.stdout)
        self.assertIn("expected exactly 3", proc.stderr)

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
        body = _step_run_block(REPRO_STEP)
        self.assertIn("set -euo pipefail", body)
        self.assertNotIn("set +e", body)
        self.assertRegex(body, r"curl\s+-\S*f", msg="curl needs -f: without it an HTTP 404 page is saved as the 'log'")
        calls = [ln.strip() for ln in body.splitlines()
                 if "check_gates_examples.py" in ln and not ln.strip().startswith("#")]
        self.assertTrue(calls, msg=f"the step no longer runs the checker:\n{body}")
        for call in calls:
            for swallow in ("|| true", "|| :", "continue-on-error"):
                self.assertNotIn(swallow, call)
        step = next(s for s in _job_steps(GATES_JOB) if REPRO_STEP in s[0])
        self.assertFalse([ln for ln in step[1] if ln.startswith("continue-on-error")],
                         msg="the reproduction step itself must be allowed to fail the job")


class TestCommittedGateExamplesAreConsistent(unittest.TestCase):
    """The committed `examples/` the reproduction job will judge: three by name, four files each, one log per dir."""

    def test_exactly_the_three_design_logs_are_committed_each_with_its_four_files(self):
        dirs = sorted({p.split("/")[1] for p in _tracked("examples/*/SOURCE.json")})
        self.assertEqual(tuple(dirs), DESIGN_EXAMPLES, msg="design §8 / ADR-023 D7 pin three public logs by name; "
                         "adding or removing one is a reviewed change to ci.yml's `-ne 3` line and to this tuple")
        for name in DESIGN_EXAMPLES:
            for f in ("SOURCE.json", "bars.yaml", "bars.yaml.prereg.json", "verdict.json"):
                self.assertTrue(_tracked(f"examples/{name}/{f}"), msg=f"examples/{name}/{f} is not committed")
        self.assertEqual([p for p in _tracked("examples/") if p.lower().endswith((".bin", ".log", ".ulg"))], [],
                         msg="a third-party log is committed -- design §8's fixture rule forbids it (licence)")

    def test_the_pins_agree_and_the_sidecar_binds_the_committed_bars_so_the_run_reads_post_hoc(self):
        for name in DESIGN_EXAMPLES:
            with self.subTest(example=name):
                ex = REPO_ROOT / "examples" / name
                source = json.loads((ex / "SOURCE.json").read_text())
                sidecar = json.loads((ex / "bars.yaml.prereg.json").read_text())
                verdict = json.loads((ex / "verdict.json").read_text())
                self.assertEqual(len(source["sha256"]), 64)
                self.assertEqual({source["sha256"], sidecar["log_sha256"], verdict["source"]["sha256"]}, {source["sha256"]},
                                 msg="SOURCE.json, the sidecar and the verdict name different logs")
                self.assertEqual(sidecar["bars_sha256"], _sha((ex / "bars.yaml").read_bytes()),
                                 msg="the sidecar does not hash the committed bars.yaml: the run would refuse (MISMATCH)")
                self.assertEqual((verdict["prereg"]["status"], verdict["prereg"]["post_hoc"]), ("HASH_MATCH", True))
                self.assertTrue(verdict["badge"].endswith("(post-hoc)"), verdict["badge"])
                word = verdict["badge"].split("gates: ", 1)[1].split(" ·", 1)[0]
                self.assertEqual(verdict["exit_code"], 0 if word == "pass" else 1, msg=f"{word!r} vs exit {verdict['exit_code']}")
                self.assertEqual(source["size_bytes"], verdict["source"]["size_bytes"])

    def test_the_readme_badge_is_the_tarot_verdict_verbatim_and_regenerates_byte_identical(self):
        verdict = json.loads((REPO_ROOT / "examples" / "tarot_x4" / "verdict.json").read_text())
        self.assertEqual((verdict["badge"], verdict["exit_code"]), (TAROT_BADGE, 0))
        svg = REPO_ROOT / "examples" / "tarot_x4" / "badge.svg"
        self.assertTrue(_tracked("examples/tarot_x4/badge.svg"), "the README badge SVG is not committed")
        proc = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "render_gates_badge.py"),
                               str(REPO_ROOT / "examples" / "tarot_x4" / "verdict.json"), "--label", TAROT_LABEL,
                               "--check", str(svg)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, msg=f"badge.svg is stale: {proc.stderr}")
        self.assertIn(TAROT_BADGE, svg.read_text(), "the SVG does not carry the badge string verbatim")
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        from render_gates_badge import render_svg
        self.assertNotEqual(render_svg(TAROT_LABEL, TAROT_BADGE.replace("8/8", "7/8")), svg.read_text(),
                            msg="--check would pass a different badge: the comparison is vacuous")
        readme = (REPO_ROOT / "README.md").read_text()
        self.assertIn("examples/tarot_x4/badge.svg", readme, "README.md does not show the badge")
        self.assertIn(TAROT_BADGE, readme, "README.md's badge line must quote the string the image depicts")


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

    def test_only_the_no_softening_probe_carries_continue_on_error_and_the_next_step_asserts_it_failed(self):
        steps = _job_steps(GATES_JOB)
        soft = [i for i, (_, body) in enumerate(steps) if any(ln.startswith("continue-on-error") for ln in body)]
        self.assertEqual(len(soft), 1, msg=f"continue-on-error on {[steps[i][0] for i in soft]}")
        probe, nxt = steps[soft[0]], steps[soft[0] + 1]
        self.assertIn("plane_nofix", " ".join(probe[1]), "the probe must be the log whose correct verdict is exit 1")
        self.assertIn('"failure"', " ".join(nxt[1]), "the step after the probe must assert the probe's outcome WAS failure")
        self.assertIn("exit-code", " ".join(nxt[1]))
        self.assertIn("uses: ./.github/actions/swathkeeper-gates", " ".join(probe[1]))


class TestTheActionNeverSoftensTheExitCode(unittest.TestCase):
    """`.github/actions/swathkeeper-gates/run.sh`, with a stub tool and with the real one. The composite action's
    YAML is read, not executed (no runner here); the contract it declares is pinned by string."""

    def _run(self, tmp: Path, tool_script: str, out: Path, extra_env=None):
        bin_ = tmp / "bin"
        bin_.mkdir(exist_ok=True)
        (bin_ / "swathkeeper-gates").write_text(tool_script)
        (bin_ / "swathkeeper-gates").chmod(0o755)
        os.symlink(sys.executable, bin_ / "python3")
        gh_out = tmp / "github_output"
        env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}", "GITHUB_OUTPUT": str(gh_out),
               "LOG": str(tmp / "flight.bin"), "BARS": str(tmp / "bars.yaml"), "OUT": str(out), **(extra_env or {})}
        proc = subprocess.run(["bash", str(ACTION_DIR / "run.sh")], cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
        outputs = dict(ln.split("=", 1) for ln in gh_out.read_text().splitlines()) if gh_out.exists() else {}
        return proc, outputs

    def test_exit_1_and_2_fail_the_step_with_the_outputs_already_written(self):
        stub = ("#!{py}\nimport json, sys\na = sys.argv[1:]\nout = a[a.index('--out') + 1]\n"
                "if {write}:\n    open(out, 'w').write(json.dumps({{'badge': {badge!r}, 'exit_code': {code}}}))\n"
                "sys.exit({code})\n")
        cases = (("fail", 1, "gates: fail · 1/5 measured (post-hoc)", True),
                 ("could not tell", 1, "gates: could not tell · 3/6 measured (post-hoc)", True),
                 ("refused, verdict written", 2, "gates: refused", True),
                 ("refused, --out unwritable (no file)", 2, "gates: refused", False),
                 ("pass", 0, "gates: pass · 8/8 measured (post-hoc)", True))
        for why, code, badge, write in cases:
            with self.subTest(why=why), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "verdict.json"
                proc, outputs = self._run(Path(tmp), stub.format(py=sys.executable, write=write, badge=badge, code=code), out)
                self.assertEqual(proc.returncode, code, msg=f"[{why}] run.sh exited {proc.returncode}, the tool {code}.\n"
                                                            f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
                self.assertEqual(outputs, {"exit-code": str(code), "badge": badge, "verdict": str(out)},
                                 msg=f"[{why}] outputs must be written before the exit, red or not")

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
            proc, outputs = self._run(Path(tmp), wrapper, out)
            verdict = json.loads(out.read_text())
        self.assertEqual(proc.returncode, 0, msg=f"stdout: {proc.stdout}\nstderr: {proc.stderr}")
        self.assertEqual(outputs["badge"], verdict["badge"])
        self.assertTrue(outputs["badge"].endswith("(unregistered)"), outputs["badge"])  # no sidecar beside these bars: SAID
        self.assertEqual(outputs["exit-code"], "0")

    def test_action_yml_declares_the_contract_and_carries_no_softener(self):
        text = (ACTION_DIR / "action.yml").read_text()
        self.assertIn("using: composite", text)
        for out in ("exit-code:", "badge:", "verdict:"):
            self.assertIn(out, text)
        self.assertRegex(text, r"log:\s*\n\s+description:[^\n]*\n\s+required: true")
        self.assertRegex(text, r"bars:\s*\n\s+description:(?:[^\n]*\n)+?\s+required: true")
        self.assertIn('run: bash "${GITHUB_ACTION_PATH}/run.sh"', text)
        for f in ("action.yml", "run.sh"):
            code = "\n".join(ln for ln in (ACTION_DIR / f).read_text().splitlines() if not ln.lstrip().startswith("#"))
            for swallow in ("continue-on-error", "|| true", "|| :", "set +e"):
                self.assertNotIn(swallow, code, msg=f"{f} softens the exit code: {swallow!r}")
        run_sh = (ACTION_DIR / "run.sh").read_text()
        self.assertIn('exit "$rc"', run_sh)
        self.assertIn("set -euo pipefail", run_sh)
        self.assertTrue(_tracked(".github/actions/swathkeeper-gates/run.sh"))


if __name__ == "__main__":
    unittest.main()
