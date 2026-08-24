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
import json
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


def floor_constants():
    """(TF_MIN_FRAMES, TF_MIN_CELLS), read from the script so these tests pin the LOGIC, not the
    two numbers — which are expected to rise once more than one healthy flight exists."""
    code = f'source "{SCRIPT}"; printf "%s %s" "$TF_MIN_FRAMES" "$TF_MIN_CELLS"'
    out = subprocess.run(["bash", "-c", code], capture_output=True, text=True,
                         cwd=str(REPO_ROOT), check=True).stdout.split()
    return int(out[0]), int(out[1])


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

    def test_the_plan_advertises_the_floor_it_will_actually_judge_with(self):
        # The dry run is what a human reads before trusting the gate; if it quoted a different bar
        # than the one enforced, a PASS would mean something nobody agreed to.
        min_frames, min_cells = floor_constants()
        self.assertIn(f"frames_recorded >= {min_frames} AND cells_imaged >= {min_cells}", self.out)


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


class TestPaneTailDropsTheGridPadding(LauncherTestCase):
    """Why `pane_tails["ndvi"]` came back as 15 empty strings in BOTH committed gate records.

    `tmux capture-pane` renders the whole pane GRID, so every row below the cursor is captured as a
    blank line. A quiet pane — the ndvi node heartbeats once per 25 fused frames — keeps its output
    at the TOP of an 80x24 grid, so tailing that capture returns padding, never heartbeats. The
    capture was never late (the tails are read before `down` touches the panes); it was
    bottom-anchored. Confirmed by hand against tmux 3.7c; pinned here through the capture shim.
    """

    HEARTBEATS = ["[ndvi] fused_count=1 dropped_pair_count=0",
                  "[ndvi] fused_count=26 dropped_pair_count=3"]

    def pane_tail(self, pane_text, n=15):
        environ = dict(os.environ, PATH=f"{self.shim_path()}:{os.environ['PATH']}",
                       FG_SHIM_LOG=str(self.shim_log), FG_PANE_TEXT=pane_text)
        result = subprocess.run(["bash", "-c", f'source "{SCRIPT}"; pane_tail ndvi {n}'],
                                capture_output=True, text=True, cwd=str(REPO_ROOT), env=environ)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result.stdout.splitlines()

    def test_the_heartbeats_survive_the_padding_below_them(self):
        grid = "\n".join(self.HEARTBEATS + [""] * 22)     # two lines of output in a 24-row pane
        self.assertEqual(self.pane_tail(grid), self.HEARTBEATS)

    def test_a_pane_of_nothing_but_padding_yields_nothing_and_still_exits_zero(self):
        # The script runs -o pipefail: a filter that matches nothing must not abort a teardown
        # halfway through writing the gate record.
        self.assertEqual(self.pane_tail("\n" * 24), [])

    def test_every_pane_tail_goes_through_the_padding_filter(self):
        # The bug in one line: `pane_text <window> | tail -n <n>` reads the bottom of the grid.
        tails = [line for line in SCRIPT.read_text().splitlines()
                 if "tail -n" in line and ("pane_text" in line or "tail_txt" in line)]
        self.assertTrue(tails, "no pane tail left in the script — this tripwire went vacuous")
        for line in tails:
            self.assertIn("meaningful", line, msg=line)


class TestEvidenceYieldFloor(LauncherTestCase):
    """The evidence-yield floor, judged against committed test-flight artifacts.

    Frames come from the gate records, cells from the clips' own `heatmap/heatmap.json` — the same
    two artifacts the live gate reads, so this cannot pass on numbers the launcher would never see.
    Provenance (2026-08-22, ADR-013 am. 10): the floor was raised 12/40 -> 300/200 off the F9
    healthy run at the operative A+B+L1+L2 transport config. The pre-transport-fix "healthy" run
    (48/291) now FAILS it BY DESIGN — a silently unloaded DDS profile reverts delivery to exactly
    that regime, and catching it is the floor's job.
    """

    HEALTHY = "testflight_gate_20260822T181022Z.json"    # 2026-08-22, F9, A+B+L1+L2, healthy
    PRE_FIX = "testflight_gate_20260818T222031Z.json"    # 2026-08-18, healthy THEN, fails floor NOW
    COLLAPSE = "testflight_gate_20260819T021136Z.json"   # 2026-08-19, 2 Hz, PASSED on 3 frames

    def yield_of(self, record_name):
        record = json.loads((REPO_ROOT / "eval" / "results" / record_name).read_text())
        heatmap = json.loads((REPO_ROOT / record["clip"] / "heatmap" / "heatmap.json").read_text())
        return record["frames_recorded"], heatmap["cells_imaged"]

    def floor(self, frames, cells):
        """The failure text, or '' when the yield clears the floor."""
        code = f'source "{SCRIPT}"; tf_floor_failure "{frames}" "{cells}"'
        result = subprocess.run(["bash", "-c", code], capture_output=True, text=True,
                                cwd=str(REPO_ROOT))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result.stdout.strip()

    def test_the_healthy_flight_clears_the_floor(self):
        self.assertEqual(self.yield_of(self.HEALTHY), (681, 417))   # pin the fixture itself
        self.assertEqual(self.floor(*self.yield_of(self.HEALTHY)), "")

    def test_the_pre_transport_fix_run_now_fails_the_floor_by_design(self):
        # 48/291 was the healthy anchor before the DDS fix. If the profile silently stops loading,
        # delivery reverts to that regime — and this is the gate that must catch it.
        self.assertEqual(self.yield_of(self.PRE_FIX), (48, 291))
        failure = self.floor(*self.yield_of(self.PRE_FIX))
        self.assertIn("evidence-yield floor", failure)
        self.assertIn("frames_recorded=48", failure)

    def test_the_2hz_collapse_fails_the_floor_and_names_it(self):
        self.assertEqual(self.yield_of(self.COLLAPSE), (3, 1))
        failure = self.floor(*self.yield_of(self.COLLAPSE))
        self.assertIn("evidence-yield floor", failure)
        self.assertIn("frames_recorded=3", failure)
        self.assertIn("cells_imaged=1", failure)

    def test_the_floor_sits_between_the_regressions_and_the_healthy_run(self):
        # The provenance claim, as an assertion: a floor above the healthy run would flake; one at
        # or below the pre-fix regime would let a silent transport regression PASS again.
        min_frames, min_cells = floor_constants()
        good_frames, good_cells = self.yield_of(self.HEALTHY)
        pre_frames, pre_cells = self.yield_of(self.PRE_FIX)
        bad_frames, bad_cells = self.yield_of(self.COLLAPSE)
        self.assertLess(bad_frames, min_frames)
        self.assertLess(pre_frames, min_frames)   # the frames half is what catches the pre-fix regime
        self.assertLess(min_frames, good_frames)
        self.assertLess(bad_cells, min_cells)
        self.assertLess(min_cells, good_cells)
        # Deliberately NOT asserted: pre_cells < min_cells. The pre-fix run imaged 291 cells and
        # the floor is an OR — it fails that run on frames alone. Pinning cells too would force
        # the cell floor above 291 and start flaking ordinary healthy variance.
        self.assertGreater(pre_cells, min_cells)  # documents the OR-logic dependency instead

    def test_either_half_short_is_a_failure_and_the_floor_itself_passes(self):
        min_frames, min_cells = floor_constants()
        self.assertNotEqual(self.floor(min_frames - 1, 291), "")
        self.assertNotEqual(self.floor(48, min_cells - 1), "")
        self.assertEqual(self.floor(min_frames, min_cells), "")

    def test_an_unreadable_yield_fails_instead_of_passing(self):
        # Fail-dangerous otherwise: a missing meta.json / heatmap.json would score itself green,
        # which is the exact shape of the bug this floor exists to close.
        for frames, cells in (("", ""), (48, ""), ("", 291), ("none", 291)):
            with self.subTest(frames=frames, cells=cells):
                self.assertIn("cannot read the yield", self.floor(frames, cells))


class TestBenchTransportArm(unittest.TestCase):
    """scripts/bench_transport.sh measures the SAME stack the flight flies, and it does that by
    reading the launcher's payload strings rather than retyping them. If the launcher renames a
    payload variable the bench would silently bench nothing -- so the coupling is pinned here.

    Host-side and Docker-free, like the rest of this file."""

    BENCH = REPO_ROOT / "scripts" / "bench_transport.sh"

    def test_the_bench_script_exists_and_is_executable(self):
        self.assertTrue(self.BENCH.exists())
        self.assertTrue(os.access(self.BENCH, os.X_OK), msg="bench_transport.sh is not executable")

    def test_it_parses_under_bash(self):
        subprocess.run(["bash", "-n", str(self.BENCH)], check=True)

    def test_it_sources_the_three_payloads_it_needs_from_the_launcher(self):
        """The whole anti-drift property: the bench must not carry its own copy of a pane one-liner,
        because a copy is exactly how a bench stops measuring the flight's transport stack."""
        bench = self.BENCH.read_text()
        launcher = SCRIPT.read_text()
        for var in ("INNER_GAZEBO", "INNER_BRIDGE", "INNER_NDVI"):
            with self.subTest(var=var):
                self.assertIn(var, bench, msg=f"{var} is not referenced by the bench")
                self.assertIn(f"{var}=", launcher, msg=f"{var} no longer exists in the launcher")
        self.assertIn("fly_pipeline.sh", bench)
        # And it must NOT inline a payload of its own.
        for smell in ("gz sim -v4", "ros2 run ros_gz_bridge", "fieldguard_planning.ndvi_node"):
            self.assertNotIn(smell, bench.split("# Usage")[-1].split("set -euo")[0] + "",
                             msg=f"bench appears to inline the payload {smell!r}")

    def test_the_profile_env_var_is_only_attached_when_a_profile_is_given(self):
        """The baseline arm must run the exec line the untuned stack actually runs -- an empty
        FASTRTPS_DEFAULT_PROFILES_FILE would be a third, undocumented condition."""
        bench = self.BENCH.read_text()
        self.assertIn("FASTRTPS_DEFAULT_PROFILES_FILE", bench)
        # The injection is a function with an explicit no-profile branch, not an array: macOS ships
        # bash 3.2, where expanding an EMPTY array under `set -u` aborts the script -- which is
        # exactly the baseline arm.
        self.assertIn("dex()", bench)
        self.assertIn('if [ -n "$PROFILE" ]; then', bench)
        self.assertIn("else\n    docker exec ", bench)
        self.assertNotIn("ENVFLAG", bench)

    def test_the_no_profile_injection_path_survives_strict_mode_bash(self):
        """bash 3.2 regression guard, reproducing the real abort. `bash -n` does NOT catch it: an
        EMPTY array expanded as "${a[@]}" under `set -u` is an 'unbound variable' error only at
        RUNTIME, and the baseline arm is exactly the empty case -- so the first bench arm died
        mid-bringup after paying for a full Gazebo start."""
        src = self.BENCH.read_text()
        body = src.split("dex() {", 1)[1].split("\n}", 1)[0]
        harness = ('set -euo pipefail\n'
                   'PROFILE=""\n'
                   'docker() { printf "ok %s\\n" "$1"; }\n'
                   'dex() {' + body + '\n}\n'
                   'dex exec somecontainer bash -c true\n')
        res = subprocess.run(["/bin/bash", "-c", harness], capture_output=True, text=True)
        self.assertNotIn("unbound variable", res.stderr)
        self.assertEqual(res.returncode, 0, msg=res.stderr)

    def test_it_refuses_to_bench_on_top_of_a_live_bringup(self):
        bench = self.BENCH.read_text()
        self.assertIn("refusing to bench on top of it", bench)

    def test_it_clears_stale_shm_segments_only_after_the_live_bringup_guard(self):
        """Orphaned /dev/shm segments outlive a hard-killed participant and make min_bytes report a
        DEAD default-sized segment as a live participant that missed the profile -- which voids the
        admissibility check. Clearing is safe ONLY because the guard above has already proved
        nothing is running, so the ORDER is the property under test, not just the presence."""
        bench = self.BENCH.read_text()
        guard = bench.index("refusing to bench on top of it")
        clear = bench.index("rm -f /dev/shm/fastrtps_*")
        self.assertLess(guard, clear, msg="stale-segment clear must come AFTER the liveness guard")


class TestDdsProfileInjection(unittest.TestCase):
    """THE partial-injection tripwire (round 3).

    Every process that creates a Fast DDS participant must load the SAME transport profile. Miss one
    and the gates go green while measuring a different transport stack than the flight — and because
    the profile only DEGRADES an un-injected participant (UDPv4 is deliberately retained), the
    symptom is a wrong number, not a crash. There is no other check that can catch this: CI has no
    sim, `check_render_alive` passes on a single frame, and `verify_mount_geometry` never creates a
    ROS node at all.

    The invariant pinned here is SAMENESS across every site, not the literal path."""

    VAR = "FASTRTPS_DEFAULT_PROFILES_FILE"
    # Verified against the image, not guessed: these create Fast DDS participants. Gazebo is
    # gz-transport, SITL speaks XRCE over plain UDP and never even sources ROS, the raw birds line
    # shells out to the gz CLI, and the apt line is apt.
    PARTICIPANTS = ("INNER_BRIDGE", "INNER_PROBE", "INNER_AGENT", "INNER_NDVI", "INNER_RECORD",
                    "INNER_BIRDS_WATCH")
    NON_PARTICIPANTS = ("INNER_GAZEBO", "INNER_SITL", "INNER_BIRDS", "INNER_APT")

    def setUp(self):
        self.src = SCRIPT.read_text()

    def _values(self, text):
        # Stop at shell separators: the gate-probe site ends the export with `;` and the pane
        # payloads end it with ` &&`, so a bare \S+ would capture punctuation and report drift that
        # is not there.
        import re
        return re.findall(re.escape(self.VAR) + r"=([^\s;&'\"]+)", text)

    def _payload(self, var):
        i = self.src.index(var + "=")
        return self.src[i:self.src.index("\n", i)] if var != "INNER_BIRDS_WATCH" \
            else self.src[i:self.src.index("\nexec ", i)]

    def test_every_participant_pane_carries_the_profile(self):
        for var in self.PARTICIPANTS:
            with self.subTest(pane=var):
                self.assertIn(self.VAR, self._payload(var),
                              msg=f"{var} creates a DDS participant but has no {self.VAR}")

    def test_non_participant_panes_do_not_carry_it(self):
        """Not cosmetic: an export on the SITL or Gazebo pane would imply those processes are on the
        tuned transport when they are not on DDS at all, and would mislead the next reader."""
        for var in self.NON_PARTICIPANTS:
            with self.subTest(pane=var):
                self.assertNotIn(self.VAR, self._payload(var))

    def test_the_gate_probe_path_is_injected_too(self):
        """`ctr()` runs probe_ros_topics' `ros2 topic list`, which creates a participant of its own.
        do_not #8: miss this and gate_bridge measures a different stack than the flight."""
        self.assertIn(self.VAR, self.src[self.src.index("ros2 topic list") - 400:
                                         self.src.index("ros2 topic list")])

    def test_the_render_probe_exec_is_injected_too(self):
        """gate_render_alive has its OWN docker exec that bypasses exec_line — it runs INNER_PROBE,
        so injecting the payload covers it. Pinned because the coupling is invisible."""
        self.assertIn('bash -c "$INNER_PROBE"', self.src)
        self.assertIn(self.VAR, self._payload("INNER_PROBE"))

    def test_all_sites_agree_on_one_value(self):
        values = set(self._values(self.src))
        self.assertEqual(len(values), 1,
                         msg=f"{self.VAR} drifted across sites: {sorted(values)}")

    def test_the_profile_path_points_at_the_committed_file(self):
        (value,) = set(self._values(self.src))
        self.assertTrue(value.startswith("/workspace/fieldguard/"), msg=value)
        repo_rel = value.replace("/workspace/fieldguard/", "", 1)
        self.assertTrue((REPO_ROOT / repo_rel).exists(),
                        msg=f"profile path {value} does not exist in the repo as {repo_rel}")

    def test_the_runbook_carries_the_same_value(self):
        """Option (b): command-level parity is the property being protected, so a human doing the
        manual bringup flies the SAME transport the launcher does."""
        runbook_values = set(self._values(RUNBOOK.read_text()))
        self.assertEqual(runbook_values, set(self._values(self.src)))


class TestDdsProfile(unittest.TestCase):
    """The L2 profile is a committed artifact whose failure mode is silent, so the invariants that
    make it valid are pinned rather than trusted to review."""

    PROFILE = REPO_ROOT / "config" / "dds" / "fg_fastdds.xml"

    def setUp(self):
        self.xml = self.PROFILE.read_text()

    def test_profile_exists_and_is_well_formed_xml(self):
        import xml.etree.ElementTree as ET
        ET.fromstring(self.xml)   # malformed XML falls back to defaults with only a log line

    def test_segment_size_is_above_max_message_size(self):
        """SharedMemTransport::init logs an error and REJECTS the descriptor if segment_size <
        max_message_size -- which would silently leave the stack on defaults."""
        import xml.etree.ElementTree as ET
        ns = {"d": "http://www.eprosima.com"}
        root = ET.fromstring(self.xml)
        seg = int(root.find(".//d:segment_size", ns).text)
        mms = int(root.find(".//d:maxMessageSize", ns).text)
        self.assertGreater(seg, mms)
        self.assertEqual(seg, 8388608)
        # 65500 on purpose: raising it is inert while UDPv4 is registered (min across transports).
        self.assertEqual(mms, 65500)

    def test_udpv4_is_retained_so_a_missed_injection_degrades_rather_than_blacks_out(self):
        self.assertIn("UDPv4", self.xml)
        self.assertIn("useBuiltinTransports>false", self.xml.replace(" ", ""))

    def test_port_queue_capacity_is_left_alone_so_the_lever_stays_one_variable(self):
        """Checked on the PARSED tree, not the raw text -- the prose explains why the knob is
        absent, and a substring match would fail on its own explanation."""
        import xml.etree.ElementTree as ET
        ns = {"d": "http://www.eprosima.com"}
        self.assertIsNone(ET.fromstring(self.xml).find(".//d:port_queue_capacity", ns))


if __name__ == "__main__":
    unittest.main()
