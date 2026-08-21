"""`scripts/fly_pipeline.sh` — the launcher's logic, pinned WITHOUT a sim.

What can only be proven live (a gate firing against a real container, a recorder finalize being
waited on) is the live-gate agent's job. What is provable here is everything that has already cost
this project a flight when it drifted: the bringup ORDER, the pane one-liners staying identical to
`docs/runbooks/FULL_PIPELINE_DEMO.md`, the refusal to start a second bringup on the same container,
`--dry-run` being a genuine paper exercise (no Docker call, no tmux server, not even a temp file),
and — for `test-flight` (ADR-013 amendment 2) — that the scripted recipe is the runbook's recipe
with only the mission swapped, and that it is gated behind the DDS/EKF/GPS wait.

No tmux or Docker needed: the subcommand tests put recording shims on PATH, which is also how
"a dry run changes nothing" is asserted rather than asserted-by-hope.

Lives in tests/ (not tests/fieldguard_planning/) on purpose: it tests a host-side shell script, not
the planning package, and CI's `unittest discover -s tests/fieldguard_planning` scopes that dir.
stdlib unittest, so it runs under both `python3 -m pytest tests/test_fly_pipeline.py -q` and
`python3 -m unittest`.
"""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "fly_pipeline.sh"
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "FULL_PIPELINE_DEMO.md"
TEST_MISSION = REPO_ROOT / "config" / "missions" / "test_2lane.waypoints"

HAVE_BASH = shutil.which("bash") is not None

# Records every call, and lets a test choose whether a tmux session "exists" and what a captured
# pane "says". list-panes must answer with a pane id or send_ctrl_c reads the window as missing.
SHIM = """#!/bin/sh
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$FG_SHIM_LOG"
if [ "$(basename "$0")" = tmux ]; then
  case "$1" in
    has-session)  exit "${FG_TMUX_HAS_SESSION:-1}" ;;
    list-panes)   echo "%1" ;;
    capture-pane) printf '%s\\n' "${FG_PANE_TEXT:-}" ;;
  esac
fi
exit 0
"""


def runbook_fly_lines():
    """The MAVProxy recipe as the runbook spells it — the one source both paths must match."""
    block = RUNBOOK.read_text().split("## Fly it", 1)[1].split("```", 2)[1]
    return [line.strip() for line in block.strip().splitlines() if line.strip()]


@unittest.skipUnless(HAVE_BASH, "bash is unavailable — nothing to run the launcher with")
class LauncherTestCase(unittest.TestCase):
    """Every run gets a private TMPDIR (so a stray temp file is visible) and optional PATH shims."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp.name)
        self.shim_log = self.tmpdir / "shim.log"
        self.addCleanup(self.tmp.cleanup)

    def shim_path(self):
        shims = self.tmpdir / "shims"
        shims.mkdir(exist_ok=True)
        for tool in ("tmux", "docker"):
            path = shims / tool
            path.write_text(SHIM)
            path.chmod(0o755)
        return shims

    def run_script(self, *args, shims=False, **env):
        environ = dict(os.environ, TMPDIR=str(self.tmpdir), FG_SHIM_LOG=str(self.shim_log), **env)
        if shims:
            environ["PATH"] = f"{self.shim_path()}:{environ['PATH']}"
        return subprocess.run(["bash", str(SCRIPT), *args], cwd=str(REPO_ROOT),
                              capture_output=True, text=True, env=environ)

    def shim_calls(self):
        return self.shim_log.read_text().splitlines() if self.shim_log.exists() else []


class TestDryRunUpPlan(LauncherTestCase):
    def setUp(self):
        super().setUp()
        self.out = self.run_script("--dry-run", "up").stdout

    def test_bringup_order_is_the_runbook_order(self):
        order = ["gz sim -v4", "fg_sensor_bridge.yaml", "check_render_alive.py",
                 "udp4 --port 2019", "sim_vehicle.py", "ndvi_node", "record_node", "drive_birds.py"]
        found = [self.out.index(fragment) for fragment in order if fragment in self.out]
        self.assertEqual(len(found), len(order), msg=self.out)
        self.assertEqual(found, sorted(found), msg="bringup order drifted:\n" + self.out)

    def test_load_bearing_pane_fragments_survive(self):
        # Each of these has its own failure story: no --headless-rendering = no render in Docker;
        # no --enable-DDS / dds_udp.parm = zero /ap/* topics, silently; the birds rate is ADR-012.
        for fragment in ("--headless-rendering", "fg_sensor_bridge.yaml", "udp4 --port 2019",
                         "--enable-DDS", "dds_udp.parm", "record_node", "drive_birds.py --rate 2"):
            self.assertIn(fragment, self.out)

    def test_every_pane_one_liner_is_a_runbook_one_liner(self):
        runbook = RUNBOOK.read_text()
        payloads = [line.split("bash -c '", 1)[1].rsplit("'", 1)[0]
                    for line in self.out.splitlines() if "docker exec -it" in line]
        # Exactly nine, because that is the number the runbook and ADR-013 both claim are diffed.
        # A floor let a payload go missing while the claim stayed "all nine"; a count is a tripwire.
        self.assertEqual(len(payloads), 9, msg=self.out)
        for payload in payloads:
            if "\n" in payload:      # the birds watcher wraps the runbook's Shell-5 line
                payload = payload.rsplit("exec ", 1)[1]
            self.assertIn(payload, runbook)


class TestTestFlightPlan(LauncherTestCase):
    def setUp(self):
        super().setUp()
        self.out = self.run_script("--dry-run", "test-flight").stdout

    def test_it_is_the_up_path_plus_the_recipe(self):
        self.assertIn("check_render_alive.py", self.out)        # gates are not skipped
        self.assertIn("sim_vehicle.py", self.out)

    def test_it_types_the_runbook_recipe_with_only_the_mission_swapped(self):
        typed = [line.replace("  DRY      ", "") for line in self.out.splitlines()
                 if line.startswith("  DRY      ")]
        expected = list(runbook_fly_lines())
        expected[0] = expected[0].replace("boustrophedon.waypoints", "test_2lane.waypoints")
        self.assertEqual(typed, expected)
        self.assertTrue(TEST_MISSION.exists(), "the test mission itself must be committed")

    def test_it_refuses_to_fly_before_dds_ekf_and_gps(self):
        for fragment in ("DDS.*[Ii]nitialization passed", "EKF3 IMU.", "GPS 1: detected"):
            self.assertIn(fragment, self.out)

    def test_it_never_starts_the_birds_itself(self):
        # The altitude-gated watcher firing on its own IS the thing under test on a live run.
        self.assertIn("the birds pane must fire ITSELF", self.out)
        self.assertNotIn("bypassing the altitude gate", self.out)

    def test_the_abort_path_promises_a_force_kill_and_a_gate_record(self):
        self.assertIn("pkill -9 -f", self.out)
        self.assertIn("eval/results/testflight_gate_", self.out)


class TestRecipePaneMatchesTheRunbook(LauncherTestCase):
    def test_status_prints_the_runbook_recipe_verbatim(self):
        out = self.run_script("--dry-run", "status").stdout
        for line in runbook_fly_lines():
            self.assertIn(line, out)


class TestSubcommandsWithNoSession(LauncherTestCase):
    def test_attach_exits_nonzero_with_a_named_cause(self):
        result = self.run_script("attach", shims=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no tmux session", result.stderr)

    def test_down_is_a_no_op_that_exits_zero(self):
        result = self.run_script("down", shims=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("nothing to tear down", result.stdout)

    def test_status_reports_down_and_exits_zero(self):
        result = self.run_script("status", shims=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("is DOWN", result.stdout)

    def test_up_refuses_a_second_bringup(self):
        result = self.run_script("up", shims=True, FG_TMUX_HAS_SESSION="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        # It must refuse BEFORE preflight touches the container.
        self.assertEqual([c for c in self.shim_calls() if c.startswith("docker")], [])

    def test_up_never_sends_a_flying_command(self):
        # ADR-013 carve-out (1), the whole reason `up` is safe to run unattended: it brings the
        # stack up and stops. A single arm/mode/wp line reaching a pane would break that promise.
        out = self.run_script("--dry-run", "up").stdout
        for forbidden in ("arm throttle", "mode auto", "mode guided", "wp load", "wp set"):
            self.assertNotIn(forbidden, out)

    def test_test_flight_refuses_a_session_it_does_not_own(self):
        result = self.run_script("test-flight", shims=True, FG_TMUX_HAS_SESSION="0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        # Critical: the teardown trap must not be armed over someone else's session.
        self.assertEqual([c for c in self.shim_calls() if "kill-session" in c or "pkill" in c], [])


class TestTeardownOrder(LauncherTestCase):
    """`down` against a shimmed session whose record pane reports a real finalize.

    The dry-run print of `down` is hand-written printfs — asserting THEIR order would prove
    nothing. This drives the real `cmd_down` instead, so the ordering the gate record depends on
    ("recorder SIGINTed first; finalize confirmed; session killed") is the ordering under test.
    """

    FINALIZED = ("[record_node] clip finalized: {'num_frames': 12}\n"
                 "[record_node] next: python3 scripts/stitch_ndvi.py "
                 "--clip /workspace/fieldguard/eval/results/clips/real_flight_20260818T221641Z")

    _run = None   # `down` sleeps 5 s waiting out the panes; pay that once, assert on it three times

    def setUp(self):
        super().setUp()
        if TestTeardownOrder._run is None:
            result = self.run_script("down", shims=True, FG_TMUX_HAS_SESSION="0",
                                     FG_PANE_TEXT=self.FINALIZED)
            TestTeardownOrder._run = (result, self.shim_calls())
        self.result, self.calls = TestTeardownOrder._run

    def index_of(self, needle, *also):
        for i, call in enumerate(self.calls):
            if needle in call and all(a in call for a in also):
                return i
        self.fail(f"no shim call matching {needle!r} {also}:\n" + "\n".join(self.calls))

    def test_the_recorder_is_signalled_before_every_other_window(self):
        # send_ctrl_c resolves each window's panes first, so the list-panes order IS the SIGINT
        # order — and it is the one thing teardown may not get wrong (finalize writes meta.json).
        record = self.index_of("list-panes", ":record")
        others = [self.index_of("list-panes", f":{w}") for w in
                  ("birds", "ndvi", "sitl", "agent", "bridge", "gazebo")]
        self.assertLess(record, min(others), msg="\n".join(self.calls))

    def test_the_session_is_killed_only_after_every_window_is_signalled(self):
        kill = self.index_of("kill-session")
        last_signal = max(self.index_of("list-panes", f":{w}") for w in
                          ("record", "birds", "ndvi", "sitl", "agent", "bridge", "gazebo"))
        self.assertLess(last_signal, kill, msg="\n".join(self.calls))

    def test_it_waits_for_the_real_finalize_string_and_recovers_the_clip(self):
        # Pinned against src/fieldguard_planning/record_node.py: if either side reworded, `down`
        # would burn its 120 s timeout and then hand the stitch a guess.
        self.assertIn("recorder finalized", self.result.stdout)
        self.assertIn("--clip eval/results/clips/real_flight_20260818T221641Z",
                      self.result.stdout)


class TestDryRunChangesNothing(LauncherTestCase):
    def test_no_docker_no_tmux_no_temp_file(self):
        for subcommand in ("up", "test-flight", "down", "status", "birds", "attach"):
            with self.subTest(subcommand=subcommand):
                self.run_script("--dry-run", subcommand, shims=True)
        self.assertEqual(self.shim_calls(), [])
        self.assertEqual(sorted(p.name for p in self.tmpdir.iterdir()), ["shims"])


class TestFlightSupervisionPatterns(LauncherTestCase):
    """The regexes test-flight supervises a real SITL pane with, against a canned log."""

    def has(self, log_text, pattern_var):
        log = self.tmpdir / "sitl.log"
        log.write_text(log_text)
        code = f'source "{SCRIPT}"; TF_LOG="{log}"; tf_has "${pattern_var}"'
        return subprocess.run(["bash", "-c", code], cwd=str(REPO_ROOT),
                              capture_output=True, text=True).returncode == 0

    def test_readiness_patterns_match_the_lines_the_runbook_says_to_wait_for(self):
        ready = ("DDS: Initialization passed\n"
                 "EKF3 IMU0 tilt alignment complete\n"
                 "GPS 1: detected u-blox\n")
        for var in ("TF_RE_DDS", "TF_RE_EKF", "TF_RE_GPS"):
            self.assertTrue(self.has(ready, var), var)
            self.assertFalse(self.has("AP: ArduPilot Ready\n", var), var)

    def test_ekf_readiness_also_accepts_the_gps_wording(self):
        self.assertTrue(self.has("EKF3 IMU1 is using GPS\n", "TF_RE_EKF"))

    def test_armed_and_disarmed_never_match_each_other(self):
        # Both directions are fail-dangerous: a DISARMED read as ARMED would arm-detect on the
        # boot banner, and an ARMED read as DISARMED would end the flight at takeoff.
        self.assertTrue(self.has("ARMED\n", "TF_RE_ARMED"))
        self.assertFalse(self.has("AP: DISARMED\n", "TF_RE_ARMED"))
        self.assertTrue(self.has("AP: DISARMED\n", "TF_RE_DISARM"))
        self.assertFalse(self.has("ARMED\n", "TF_RE_DISARM"))


class TestAltitudeParse(LauncherTestCase):
    """The gate record's birds evidence, fed canned text through FG_ALT_SOURCE_CMD."""

    def alt_from(self, text):
        canned = self.tmpdir / "pane.txt"
        canned.write_text(text)
        result = subprocess.run(["bash", "-c", f'source "{SCRIPT}"; birds_gate_alt'],
                                capture_output=True, text=True, cwd=str(REPO_ROOT),
                                env=dict(os.environ, FG_ALT_SOURCE_CMD=f'cat "{canned}"'))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result.stdout.strip()

    def test_reads_the_altitude_the_birds_pane_launched_at(self):
        self.assertEqual(
            self.alt_from("[birds] altitude 12.34 m > 10 m -- launching drive_birds.py --rate 2\n"),
            "12.34")

    def test_a_pane_that_only_ever_waited_yields_nothing(self):
        # The fail-dangerous case: if a "waiting ... altitude 3.2 m" line parsed as a launch, a
        # flight where the birds never fired would score itself green.
        self.assertEqual(self.alt_from("[birds] waiting for takeoff: altitude 3.2 m (need > 10 m)\n"),
                         "")


if __name__ == "__main__":
    unittest.main()
