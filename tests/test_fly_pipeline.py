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
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "fly_pipeline.sh"
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "FULL_PIPELINE_DEMO.md"
DODGE_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "AVOIDANCE_REAL_DETECTION.md"
TEST_MISSION = REPO_ROOT / "config" / "missions" / "test_2lane.waypoints"
# The committed booking every runbook example quotes: 5.0 m/s, bookable, from the 2026-09-07 depth
# commissioning. Pinned by tests/fieldguard_planning/test_booking_gate_artifact.py; used here as a
# REAL input, so what these tests prove is what an operator would actually get.
BOOKING = "eval/results/booking_gate_20260907T064136Z.json"
# The parameter is WP_SPD, in m/s, at ADR-004's pinned ArduPilot SHA -- AC_WPNav is registered under
# the group prefix "WP_" (ArduCopter/Parameters.cpp:370) and AC_WPNav.cpp:49-56 declares
# `@Param: SPD / @Units: m/s / @Range: 0.10 20.00`, with `// 0 was SPEED` marking the retired
# WPNAV_SPEED slot. The first cut of this feature typed a cm/s WPNAV_SPEED line: a name MAVProxy
# rejects, so the take flew the 10 m/s default while four artifacts said 5.0 (QA G135).
BOOKED_PARAM = "WP_SPD"
BOOKED_LINE = "param set WP_SPD 5.0"

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


def fenced_blocks(text):
    """Every ``` block in `text`, in order — odd-indexed pieces of a ```-split."""
    parts = text.split("```")
    return [parts[i] for i in range(1, len(parts), 2)]


def recipe_blocks(doc=None, heading="## Fly it"):
    """The recipe blocks of a runbook section, as lists of stripped lines.

    The section stops at the next `## ` heading, so a later shell's ```bash block can never be
    mistaken for a recipe. Since 2026-09-07 the demo runbook carries TWO: the unbooked recipe and
    the booked variant (one extra `param set WP_SPD <m/s>` line). Both are diffed against the
    launcher — the booked one is the whole point of the booking, so a copy of it that nobody diffs
    is exactly the drift this mechanism exists to prevent.
    """
    section = (doc or RUNBOOK.read_text()).split(heading, 1)[1].split("\n## ", 1)[0]
    return [[line.strip() for line in block.strip().splitlines() if line.strip()]
            for block in fenced_blocks(section)]


def runbook_fly_lines():
    """The UNBOOKED MAVProxy recipe as the runbook spells it — the one source both paths match."""
    return [b for b in recipe_blocks() if BOOKED_LINE not in b][0]


def runbook_booked_fly_lines():
    """...and the booked variant, the recipe an authorised dodge take flies."""
    return [b for b in recipe_blocks() if BOOKED_LINE in b][0]


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

    def test_the_fly_it_section_carries_exactly_the_two_recipes(self):
        """A count, not a floor — the same tripwire as the nine pane payloads. The section holds
        the unbooked recipe and the booked variant; a third block, or a lost one, means the
        extraction below is silently diffing something else."""
        blocks = recipe_blocks()
        self.assertEqual(len(blocks), 2, msg=blocks)
        self.assertEqual(len([b for b in blocks if BOOKED_LINE in b]), 1, msg=blocks)
        plain, booked = runbook_fly_lines(), runbook_booked_fly_lines()
        self.assertEqual([line for line in booked if line not in plain], [BOOKED_LINE])


class BookingTestCase(LauncherTestCase):
    """Shared plumbing for the booking (2026-09-07).

    Why the feature exists: the depth commissioning wrote a booking artifact that PASSES at 5.0 m/s
    and nothing in the repo enforced the speed it names. The recipe set no waypoint speed, so
    ArduCopter flew its default — 10.58 m/s peak on the 2026-09-06 scripted test-flight, a speed at
    which that same booking gate exits 1. A take flown faster than booked is not the authorised
    take, and no post-flight gate could say so.
    """

    def recipe_from(self, out):
        """The MAVProxy lines out of a printed recipe (`status` prints it; `up` never does)."""
        body = out.split("Then, at the MAVProxy prompt:\n", 1)[1].split("\n  Look for:", 1)[0]
        return [line.strip() for line in body.strip().splitlines() if line.strip()]

    def artifact(self, name, **override):
        """A copy of the committed booking with fields overridden — `None` deletes the key."""
        doc = json.loads((REPO_ROOT / BOOKING).read_text())
        for key, value in override.items():
            section, _, field = key.partition("__")
            target = doc[section] if field else doc
            name_ = field or section
            if value is None:
                target.pop(name_, None)
            else:
                target[name_] = value
        path = self.tmpdir / name
        path.write_text(json.dumps(doc, indent=1))
        return str(path)

    def source_and_run(self, code, **env):
        """Run one launcher function with REPO_ROOT pointed at this test's tmpdir, so the writers
        under test cannot leave anything in the real eval/results/."""
        prelude = f'source "{SCRIPT}"\nREPO_ROOT="{self.tmpdir}"\n'
        result = subprocess.run(["bash", "-c", prelude + code], capture_output=True, text=True,
                                cwd=str(REPO_ROOT),
                                env=dict(os.environ, TMPDIR=str(self.tmpdir), **env))
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        return result


class TestBookingRecipeInjection(BookingTestCase):
    """What the recipe pane prints, with and without a booking. `status` is used because `up`
    deliberately never prints a flying command — it writes the recipe to the pane file instead."""

    def test_without_a_booking_the_recipe_is_the_runbook_recipe_unchanged(self):
        # The NDVI survey and the demo take book nothing and must be untouched by this feature.
        out = self.run_script("--dry-run", "status").stdout
        self.assertEqual(self.recipe_from(out), runbook_fly_lines())
        # The header still NAMES the parameter (saying which default it will fly); what must not
        # exist is a `param set` for it in the lines the operator types.
        self.assertNotIn(f"param set {BOOKED_PARAM}", "\n".join(self.recipe_from(out)))

    def test_with_a_booking_the_recipe_is_the_runbook_booked_recipe(self):
        out = self.run_script("--dry-run", "--booking", BOOKING, "status").stdout
        self.assertEqual(self.recipe_from(out), runbook_booked_fly_lines())

    def test_the_booked_line_is_exactly_one_line_in_exactly_one_place(self):
        booked = self.recipe_from(
            self.run_script("--dry-run", "--booking", BOOKING, "status").stdout)
        plain = runbook_fly_lines()
        self.assertEqual([line for line in booked if line not in plain], [BOOKED_LINE])
        self.assertEqual(len(booked), len(plain) + 1)
        # Before BOTH mode changes: AUTO reads the speed when it takes the leg, and `mode guided`
        # is the bounce that forces the fresh AUTO entry. Grouped with the other param sets.
        self.assertLess(booked.index("param set AUTO_OPTIONS 3"), booked.index(BOOKED_LINE))
        self.assertLess(booked.index(BOOKED_LINE), booked.index("mode guided"))
        self.assertLess(booked.index(BOOKED_LINE), booked.index("mode auto"))

    def test_the_header_names_the_booking_and_the_speed(self):
        out = self.run_script("--dry-run", "--booking", BOOKING, "status").stdout
        header = out.split("FLY IT", 1)[1].split("WAIT for all three", 1)[0]
        self.assertIn(BOOKING, header)
        self.assertIn("5.0 m/s", header)
        self.assertIn(BOOKED_LINE, header)

    def test_the_unbooked_header_says_so_and_names_the_flag(self):
        # An operator who reads a recipe with no WPNAV line must be TOLD that is what they have —
        # the two recipes differ by one line, and the missing one decides whether the take counts.
        header = self.run_script("--dry-run", "status").stdout \
                     .split("FLY IT", 1)[1].split("WAIT for all three", 1)[0]
        self.assertIn("NO SPEED BOOKED", header)
        self.assertIn("--booking", header)

    def test_the_env_var_books_too_and_the_flag_wins_over_it(self):
        out = self.run_script("--dry-run", "status", SWATHKEEPER_BOOKING=BOOKING).stdout
        self.assertEqual(self.recipe_from(out), runbook_booked_fly_lines())
        # The flag must win, including over an env var pointing at an UNBOOKABLE artifact: an
        # exported SWATHKEEPER_BOOKING left over from an earlier session cannot veto an explicit one.
        bad = self.artifact("stale.json", verdict={"bookable": False, "why_not_bookable": "stale"})
        result = self.run_script("--dry-run", "--booking", BOOKING, "status",
                                 SWATHKEEPER_BOOKING=bad)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(self.recipe_from(result.stdout), runbook_booked_fly_lines())

    def test_dry_run_up_prints_the_injected_line_and_still_runs_nothing(self):
        # `up` prints no recipe (it must never print a flying command), so it names the ONE line it
        # will inject — that is what a human checks before spending a Docker session.
        result = self.run_script("--dry-run", "--booking", BOOKING, "up", shims=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(BOOKED_LINE, result.stdout)
        self.assertEqual(self.shim_calls(), [])                      # no tmux, no docker
        self.assertEqual(sorted(p.name for p in self.tmpdir.iterdir()), ["shims"])
        for forbidden in ("arm throttle", "mode auto", "mode guided", "wp load", "wp set"):
            self.assertNotIn(forbidden, result.stdout)

    def test_test_flight_types_the_booked_line_too(self):
        # test-flight is the ONE launcher-typed flight: it types the recipe verbatim, so the
        # booking has to reach the typed lines, not just the printed pane.
        out = self.run_script("--dry-run", "--booking", BOOKING, "test-flight").stdout
        typed = [line.replace("  DRY      ", "") for line in out.splitlines()
                 if line.startswith("  DRY      ")]
        expected = list(runbook_booked_fly_lines())
        expected[0] = expected[0].replace("boustrophedon.waypoints", "test_2lane.waypoints")
        self.assertEqual(typed, expected)


class TestBookingRefusals(BookingTestCase):
    """Every way a booking can fail to authorise a flight. All of them REFUSE — an unreadable
    authorisation is never a silent fall-back to the unbooked recipe, because that fall-back is
    exactly the 10 m/s flight this whole mechanism exists to stop."""

    def refuse(self, *args, **env):
        result = self.run_script("--dry-run", *args, shims=True, **env)
        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        self.assertIn("REFUSING", result.stderr)
        # Before preflight: a refusal must not have touched the container or a tmux server.
        self.assertEqual(self.shim_calls(), [])
        return result.stderr

    def test_the_launcher_reads_a_booking_with_THE_GATES_OWN_FUNCTION(self):
        """QA finding G137: the two ends of the chain used to validate differently, and the
        unguarded end was the PRE-flight one. `{"verdict":{"bookable":true},"encounter":
        {"mission_speed_mps":9.0}}` booked a flight that the post-flight gate then refused as
        malformed -- so a take could be flown believing it was authorised and only found
        unauthorised afterwards. One definition of "authorises a flight", and it is
        `check_live_flight_log.load_booking`, which the gate uses too."""
        stub = self.tmpdir / "stub.json"
        stub.write_text(json.dumps({"verdict": {"bookable": True},
                                    "encounter": {"mission_speed_mps": 9.0}}))
        err = self.refuse("--booking", str(stub), "up")
        # `validate_report` and this wording exist ONLY in check_live_flight_log.load_booking, so
        # seeing them here is the proof that the launcher went through the gate's own reader
        # rather than a second opinion of its own.
        self.assertIn("not a well-formed booking-gate artifact", err)
        self.assertIn("validate_report", err)
        self.assertIn("missing top-level key(s)", err)

    def test_a_not_bookable_verdict_is_refused_with_its_own_reason(self):
        path = self.artifact("nb.json", verdict={"pass": True, "bookable": False, "exit_code": 3,
                                                 "why_not_bookable": "config-sourced inputs"})
        err = self.refuse("--booking", path, "up")
        self.assertIn("does not AUTHORISE anything", err)
        self.assertIn("config-sourced inputs", err)

    def test_a_pass_that_is_not_bookable_is_still_refused(self):
        # exit 3 of the booking gate: PASS but NOT bookable. `pass: true` must not read as booked.
        path = self.artifact("p3.json", verdict={"pass": True, "bookable": False,
                                                 "exit_code": 3, "why_not_bookable": None})
        self.assertIn("does not AUTHORISE anything", self.refuse("--booking", path, "up"))

    def test_only_a_real_json_true_books(self):
        """`bookable` is read as an identity, not a truthiness: a string "true", a 1, or a missing
        verdict block are all artifacts this launcher does not understand, and the safe reading of
        "I do not understand this authorisation" is to refuse it. Every one of these is refused by
        the gate's own reader, so the refusal names `verdict` and the flight never starts."""
        for name, verdict in (("s.json", {"pass": True, "bookable": "true"}),
                              ("n.json", {"pass": True, "bookable": 1}),
                              ("e.json", {}), ("z.json", None)):
            with self.subTest(verdict=verdict):
                err = self.refuse("--booking", self.artifact(name, verdict=verdict), "up")
                self.assertIn("verdict", err)

    def test_the_recorded_path_is_repo_relative_however_it_was_given(self):
        """One path form in the record and the header, so a booking quoted from a gate record can
        be found from the repo root by anyone — including CI, on a different machine."""
        out = self.run_script("--dry-run", "--booking", str(REPO_ROOT / BOOKING), "status").stdout
        self.assertIn(f"BOOKED 5.0 m/s from {BOOKING}", out)
        self.assertNotIn(str(REPO_ROOT), out)

    def test_a_missing_file_is_refused(self):
        # The gate's own words: there is no second reader here to drift from them.
        self.assertIn("does not exist",
                      self.refuse("--booking", str(self.tmpdir / "gone.json"), "up"))

    def test_a_malformed_artifact_is_refused(self):
        path = self.tmpdir / "garbage.json"
        path.write_text("{not json")
        self.assertIn("not valid JSON", self.refuse("--booking", str(path), "up"))

    def test_the_launchers_OWN_bringup_record_cannot_book_a_flight(self):
        """`eval/results/live_flight_booking_<UTC>.json` is a pointer written at bringup, sits
        beside the flight logs, and is the obvious thing to reach for on flight day. The flight-log
        gate refuses it by name -- and because the launcher now reads through that same function,
        so does the launcher, instead of booking a flight off its own note-to-self."""
        path = self.tmpdir / "live_flight_booking_20260907T120000Z.json"
        path.write_text(json.dumps({
            "schema_version": "1.1", "kind": "live_flight_booking",
            "booking": {"path": BOOKING, "booked_speed_mps": 5.0, "parameter": BOOKED_PARAM},
            "recipe_line": BOOKED_LINE}))
        err = self.refuse("--booking", str(path), "up")
        self.assertIn("LAUNCHER'S bringup record", err)
        self.assertIn(BOOKING, err)                    # and it names the artifact to pass instead

    def test_a_repo_whose_gate_cannot_be_IMPORTED_refuses_rather_than_falling_back(self):
        """There is deliberately no weaker fallback reader: a two-field read is the G137 defect
        wearing an ImportError. Only a dodge take passes `--booking`, so this can never block the
        NDVI survey, the demo or teardown -- it blocks exactly the flight that needs the
        authorisation. Proven by running a COPY of the launcher out of a tree with no gate in it."""
        fake = self.tmpdir / "fakerepo" / "scripts"
        fake.mkdir(parents=True)
        shutil.copy(SCRIPT, fake / SCRIPT.name)
        result = subprocess.run(
            ["bash", str(fake / SCRIPT.name), "--dry-run", "--booking",
             str(REPO_ROOT / BOOKING), "status"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
            env=dict(os.environ, TMPDIR=str(self.tmpdir), PATH=f"{self.shim_path()}:"
                     f"{os.environ['PATH']}", FG_SHIM_LOG=str(self.shim_log)))
        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        self.assertIn("cannot import check_live_flight_log.load_booking", result.stderr)
        self.assertIn("does not authorise a flight", result.stderr)
        self.assertEqual(self.shim_calls(), [])        # refused before anything was touched

    def test_an_unreadable_speed_is_refused(self):
        """A string, a bool, a zero, a negative -- none of them is a speed to hold a flight to. The
        expected substring differs for the last case only because deleting the whole `encounter`
        block is caught one level earlier, by the schema check."""
        for name, override, expect in (
                ("nospeed.json", {"encounter__mission_speed_mps": None}, "mission_speed_mps"),
                ("str.json", {"encounter__mission_speed_mps": "5.0"}, "mission_speed_mps"),
                ("zero.json", {"encounter__mission_speed_mps": 0}, "mission_speed_mps"),
                ("neg.json", {"encounter__mission_speed_mps": -5.0}, "mission_speed_mps"),
                ("bool.json", {"encounter__mission_speed_mps": True}, "mission_speed_mps"),
                ("noenc.json", {"encounter": None}, "missing 'encounter'")):
            with self.subTest(case=name):
                err = self.refuse("--booking", self.artifact(name, **override), "up")
                self.assertIn(expect, err)

    def test_a_speed_arducopter_would_ignore_is_refused(self):
        """WP_SPD's documented range is 0.10..20.00 m/s (AC_WPNav.cpp:53). Outside it the vehicle
        would keep its default while the recipe CLAIMED the booked speed, which is the same lie in
        a different direction."""
        for name, speed in (("slow.json", 0.05), ("fast.json", 20.01)):
            with self.subTest(speed=speed):
                err = self.refuse("--booking", self.artifact(
                    name, encounter__mission_speed_mps=speed), "up")
                self.assertIn("outside the 0.1..20 m/s", err)
        # ...and the two edges themselves are accepted, so the check is a band, not a wall.
        for name, speed, shown in (("min.json", 0.1, "0.1"), ("max.json", 20.0, "20.0")):
            with self.subTest(speed=speed):
                out = self.run_script("--dry-run", "--booking", self.artifact(
                    name, encounter__mission_speed_mps=speed), "status").stdout
                self.assertIn(f"param set {BOOKED_PARAM} {shown}", out)

    def test_test_flight_refuses_before_it_can_arm_anything(self):
        # The one scripted flight path: a refusal here has to happen before the teardown trap is
        # armed and before a single pane exists.
        path = self.artifact("nb2.json", verdict={"bookable": False, "why_not_bookable": "x"})
        self.refuse("--booking", path, "test-flight")

    def test_the_flag_needs_a_value(self):
        result = self.run_script("--dry-run", "--booking", shims=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--booking needs a path", result.stderr)

    def test_a_booking_on_a_command_that_cannot_use_one_is_named_not_obeyed(self):
        """`down` must never be blocked by a booking file — teardown is what finalizes the clip.
        But silently ignoring it would be worse than saying so, so it says so."""
        bad = self.artifact("nb3.json", verdict={"bookable": False, "why_not_bookable": "x"})
        result = self.run_script("down", "--booking", bad, shims=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("has no effect on 'down'", result.stderr)

    def test_the_booked_speed_reaches_the_recipe_UNCONVERTED_and_unrounded(self):
        """WP_SPD's unit IS m/s, so the number typed at the vehicle is the number in the artifact.
        The first cut multiplied by 100 and rounded to a whole centimetre; there is now no
        conversion to get wrong and no rounding step to lose a digit in."""
        for speed, shown in ((5.0, "5.0"), (3.456, "3.456"), (7.891, "7.891"), (1.0, "1.0"),
                             (12.345, "12.345")):
            with self.subTest(speed=speed):
                out = self.run_script("--dry-run", "--booking", self.artifact(
                    f"r{shown}.json", encounter__mission_speed_mps=speed), "status").stdout
                self.assertIn(f"param set {BOOKED_PARAM} {shown}", out)
                self.assertIn(f"{speed} m/s", out)          # the header quotes the booked m/s


class TestBookingReaderIsolation(BookingTestCase):
    """QA finding G136: the reader used to merge stderr into stdout and read three positional lines
    out of the merged stream with no numeric check, and the recipe printed the result with `%s`.

    Reproduced at the time with `PYTHONVERBOSE=1`: the launcher printed
    `BOOKED import _frozen_importlib # frozen m/s` and put
    `param set WPNAV_SPEED import _imp # builtin` into a recipe a human types verbatim. Any stderr
    on the SUCCESS path did it -- a sitecustomize print, a .pth banner, a DeprecationWarning under
    PYTHONWARNINGS. Pinned here with a python3 shim that pollutes each stream in turn.
    """

    def python_shim(self, before="", after=""):
        """A `python3` earlier on PATH that emits noise around the real interpreter's own output."""
        shims = self.shim_path()                       # tmux + docker, so nothing real is touched
        shim = shims / "python3"
        shim.write_text('#!/bin/bash\n%s\n"$REAL_PYTHON" "$@"\nrc=$?\n%s\nexit $rc\n'
                        % (before, after))
        shim.chmod(0o755)
        return shims

    def run_with_shim(self, *args, before="", after=""):
        env = dict(os.environ, TMPDIR=str(self.tmpdir), FG_SHIM_LOG=str(self.shim_log),
                   REAL_PYTHON=sys.executable)
        env["PATH"] = f"{self.python_shim(before, after)}:{env['PATH']}"
        return subprocess.run(["bash", str(SCRIPT), *args], cwd=str(REPO_ROOT),
                              capture_output=True, text=True, env=env)

    def test_noise_on_STDERR_does_not_become_the_booked_speed(self):
        result = self.run_with_shim("--dry-run", "--booking", BOOKING, "status",
                                    before='echo "a deprecation warning" >&2')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(f"booked: {BOOKING} -> 5.0 m/s", result.stdout)
        self.assertIn(BOOKED_LINE, self.recipe_from(result.stdout))
        self.assertIn("a deprecation warning", result.stderr)   # visible, not swallowed

    def test_noise_on_STDOUT_is_REFUSED_rather_than_flown(self):
        """The reader takes the last two lines, so a banner ahead of the payload survives -- but
        anything that lands AFTER it must refuse. `%s` in the recipe would pass literally
        anything to the vehicle, so the number is validated as a plain decimal before it is used."""
        result = self.run_with_shim("--dry-run", "--booking", BOOKING, "status",
                                    after='echo TRAILING_NOISE')
        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        self.assertIn("REFUSING", result.stderr)
        self.assertIn("booked mission speed in m/s was expected", result.stderr)
        self.assertNotIn("param set", result.stdout)

    def test_a_banner_BEFORE_the_payload_still_books_correctly(self):
        result = self.run_with_shim("--dry-run", "--booking", BOOKING, "status",
                                    before='echo "BANNER: some .pth file said hello"')
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(f"booked: {BOOKING} -> 5.0 m/s", result.stdout)


class TestBookingSidecar(BookingTestCase):
    """`eval/results/live_flight_booking_<UTC>.json` — the booking, dropped beside the flight logs.

    The scripted test-flight records its booking in its own gate record. A HUMAN-flown take (every
    demo and every dodge take, ADR-013) has no record here at all: its flight log is written by the
    avoidance node inside the container, minutes later. Without this file the booked speed would
    exist only in a tmux pane, and the flight-log gate could never be shown what the flight was
    authorised to fly.
    """

    def write(self, **assign):
        code = "\n".join(f'{k}="{v}"' for k, v in assign.items()) + "\nwrite_booking_sidecar\n"
        self.source_and_run(code)
        written = sorted((self.tmpdir / "eval" / "results").glob("live_flight_booking_*.json"))
        return written

    def test_it_lands_beside_the_flight_logs_with_the_flight_log_stamp_format(self):
        (path,) = self.write(BOOKING_PATH_REL=BOOKING, BOOKING_SPEED="5.0", CMD="up")
        self.assertRegex(path.name, r"^live_flight_booking_\d{8}T\d{6}Z\.json$")
        # Same directory and stamp shape as live_flight_log_<UTC>.json on purpose: the sidecar is
        # written at BRINGUP, so it always sorts BEFORE the log of the flight it belongs to.
        self.assertEqual(path.parent.name, "results")

    def test_it_carries_the_path_the_speed_and_the_recipe_line(self):
        (path,) = self.write(BOOKING_PATH_REL=BOOKING, BOOKING_SPEED="5.0", CMD="up")
        doc = json.loads(path.read_text())
        self.assertEqual(doc["booking"], {"path": BOOKING, "booked_speed_mps": 5.0,
                                          "parameter": BOOKED_PARAM})
        self.assertEqual(doc["recipe_line"], BOOKED_LINE)
        self.assertEqual(doc["kind"], "live_flight_booking")
        self.assertIn("scripts/fly_pipeline.sh up", doc["written_by"])
        # The explicit flag is the contract; the sidecar only makes it typeable. Say so in the file.
        self.assertIn("--booking", doc["note"])
        self.assertTrue((REPO_ROOT / doc["booking"]["path"]).exists(),
                        msg="the sidecar must name a path that exists from the repo root")

    def test_an_unbooked_bringup_writes_no_sidecar_at_all(self):
        # Absence is the signal: no file means nothing booked this flight. An empty or null-filled
        # sidecar would let a reader believe a booking was checked and found blank.
        self.assertEqual(self.write(BOOKING_PATH_REL="", BOOKING_SPEED="", CMD="up"), [])

    def test_up_is_what_writes_it_and_a_dry_run_never_does(self):
        body = SCRIPT.read_text().split("\ncmd_up() {", 1)[1].split("\n}", 1)[0]
        self.assertIn("write_booking_sidecar", body)
        # ...and it is on the non-dry branch: a dry run must leave the machine as it found it.
        self.assertIn("write_booking_sidecar", body.split("else", 1)[1])
        out = self.run_script("--dry-run", "--booking", BOOKING, "up").stdout
        self.assertIn("eval/results/live_flight_booking_", out)

    def test_the_sidecar_is_git_allowlisted_so_it_survives_into_the_repo(self):
        """eval/results/* is gitignored. An evidence file nobody committed does not exist (the
        2026-08-05 clobber lesson), and this one is what says the take was the authorised take."""
        self.assertIn("!eval/results/live_flight_booking_*.json",
                      (REPO_ROOT / ".gitignore").read_text())


class TestGateRecordCarriesTheBooking(BookingTestCase):
    """The test-flight gate record, schema 1.1 -> 1.2."""

    def record(self, **assign):
        code = ('mkdir -p "$REPO_ROOT/work/tails"; : >"$REPO_ROOT/work/evidence.txt"\n'
                'TF_WORK="$REPO_ROOT/work"; TF_START=2026-09-07T00:00:00Z; TF_T0=0\n'
                'TF_MISSION_NAME=test_2lane; TF_FRAMES=681; TF_CELLS=417\n'
                + "\n".join(f'{k}="{v}"' for k, v in assign.items())
                + '\ntf_write_record\nprintf "%s\\n" "$TF_RECORD"\n')
        path = Path(self.source_and_run(code).stdout.strip())
        return json.loads(path.read_text())

    def test_a_booked_flight_records_what_it_was_authorised_to_fly(self):
        record = self.record(BOOKING_PATH_REL=BOOKING, BOOKING_SPEED="5.0")
        self.assertEqual(record["schema_version"], "1.2")
        self.assertEqual(record["booking"], {"path": BOOKING, "booked_speed_mps": 5.0,
                                             "parameter": BOOKED_PARAM})

    def test_an_unbooked_flight_records_null_not_a_guess(self):
        record = self.record(BOOKING_PATH_REL="", BOOKING_SPEED="")
        self.assertEqual(record["schema_version"], "1.2")
        self.assertIsNone(record["booking"])

    def test_the_rest_of_the_record_is_unchanged_by_the_bump(self):
        record = self.record(BOOKING_PATH_REL="", BOOKING_SPEED="")
        for key in ("frames_recorded", "cells_imaged", "evidence_floor", "result", "mission",
                    "clip", "pane_tails", "evidence"):
            self.assertIn(key, record)
        self.assertEqual(record["frames_recorded"], 681)


class TestTheDodgeRunbookFliesTheBookedRecipe(unittest.TestCase):
    """`docs/runbooks/AVOIDANCE_REAL_DETECTION.md` — the page a dodge take is booked and flown from.

    Its §2 recipe is a COPY of the launcher's, and a copy is how a runbook stops describing the
    flight. Diffed here against the launcher's booked recipe for the committed artifact, which is
    also the one §0g tells the operator to pass.
    """

    def setUp(self):
        self.doc = DODGE_RUNBOOK.read_text()

    def test_its_fly_recipe_is_the_booked_recipe(self):
        self.assertEqual(recipe_blocks(self.doc, "## 2. Fly it")[0], runbook_booked_fly_lines())

    def test_it_makes_booking_the_bringup_mandatory_and_names_the_artifact(self):
        section = self.doc.split("### 0g.", 1)[1].split("\n---", 1)[0]
        self.assertIn("MANDATORY", self.doc.split("### 0g.", 1)[1].split("\n", 1)[0] + section)
        self.assertIn(f"--booking {BOOKING}", section)
        self.assertIn(BOOKED_LINE, section)              # the exact line the recipe will carry
        self.assertIn("not the authorised take", section)
        self.assertIn("live_flight_booking_", section)          # names the sidecar it writes

    def test_the_launcher_flag_stays_out_of_section_0f(self):
        """A LOAD-BEARING boundary, not style: tests/test_verify_depth_mount_geometry.py checks
        that every `--flag` printed in §0f is one `predict_forward_lead.py` accepts. `--booking` is
        the LAUNCHER's flag, so putting it in §0f turns that test red on a doc edit."""
        section_0f = self.doc.split("### 0f.", 1)[1].split("\n---", 1)[0]
        self.assertNotIn("--booking", section_0f)

    def test_the_bringup_command_it_publishes_carries_the_booking(self):
        bringup = self.doc.split("## 1. Bringup", 1)[1].split("\n## ", 1)[0]
        self.assertIn(f"scripts/fly_pipeline.sh --booking {BOOKING} up", bringup)

    def test_the_POST_FLIGHT_scoring_command_carries_the_booking_too(self):
        """QA finding G139: §0g called booking the bringup MANDATORY while §5's own scoring command
        omitted `--booking`, so an operator following the page verbatim never ran the enforcement
        the same page calls mandatory. Doc contradicting doc, in the one procedure that decides.
        Without the flag the gate prints a NOTE and the verdict is unaffected."""
        section = self.doc.split("## 5. Post-flight gates", 1)[1].split("\n## ", 1)[0]
        gate1 = section.split("**Gate 1", 1)[1].split("```", 2)[1]
        self.assertIn("check_live_flight_log.py", gate1)
        self.assertIn("--booking", gate1)
        # ...and the variable it uses is captured in the same section, so the block is runnable.
        self.assertIn("BOOKING=", section)
        self.assertIn(BOOKING, section)

    def test_the_evidence_table_names_the_booking_flag(self):
        """Line 13's table is what a reader skims instead of §5. It said `--truth ...` alone."""
        row = [line for line in self.doc.splitlines()
               if "live_flight_log_<UTC>.json" in line and line.startswith("|")]
        self.assertEqual(len(row), 1, msg=row)
        self.assertIn("--booking", row[0])

    def test_the_visibility_precheck_runs_at_the_BOOKED_speed_not_a_literal(self):
        """QA finding G140: §0b's abort gate was hard-coded to `--speed 9.4` while §0g booked 5.0 --
        the exact speed-mismatch failure ADR-016 exists to prevent, and the answer really moves
        (5.0: 2 of 3 birds below the floor; 9.4: 3 of 3). The command must read the speed out of
        the booking artifact rather than carry a number of its own."""
        section = self.doc.split("### 0b.", 1)[1].split("\n### ", 1)[0]
        cmd = [b for b in fenced_blocks(section) if "predict_bird_visibility.py" in b][0]
        self.assertIn("mission_speed_mps", cmd, msg=cmd)
        self.assertNotIn("--speed 9.4", cmd, msg=cmd)
        self.assertIn(BOOKING, cmd)


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


class TestSitlParamFile(unittest.TestCase):
    """`config/sitl_params/dds_udp.parm` — the ONE param file every DDS SITL start loads.

    A flight parameter the mission logic DEPENDS ON must live here, not in a line a human types at
    the MAVProxy prompt: the prompt line is per-session and silently skippable, and the failure it
    would cause (a dodge restarting the mission at item 1) reads as a plausible flight, not as an
    error. Pinned after the 2026-08-25 red team named `MIS_RESTART` as pinned nowhere (ADR-016
    doctrine: physical/flight parameters come from a file, never from prose)."""

    PARM = REPO_ROOT / "config" / "sitl_params" / "dds_udp.parm"
    # Every file that spells out a DDS-enabled SITL start. ci_sim_smoke.sh is deliberately absent:
    # it starts SITL WITHOUT --enable-DDS (its own header says why) and flies no mission.
    SITL_START_SITES = ("scripts/fly_pipeline.sh", "scripts/run_farm_mission.sh",
                        "docs/runbooks/FULL_PIPELINE_DEMO.md", "docs/runbooks/SIM_BRINGUP.md",
                        "sim/README.md")

    def params(self):
        """{name: value} from the .parm file — comments and blank lines stripped."""
        out = {}
        for line in self.PARM.read_text().splitlines():
            body = line.split("#", 1)[0].split()
            if body:
                out[body[0]] = float(body[1])
        return out

    def test_mission_restart_is_pinned_to_resume(self):
        params = self.params()
        self.assertIn("MIS_RESTART", params,
                      msg="MIS_RESTART is not pinned in any param file, so every flight runs "
                          "whatever the SITL eeprom.bin happens to hold — see this class's docstring")
        self.assertEqual(params["MIS_RESTART"], 0.0,
                         msg="ADR-006: the executor takes AUTO -> GUIDED -> one setpoint -> AUTO and "
                             "claims the mission RESUMES at the waypoint it was flying to. That is "
                             "ArduPilot's `mission.start_or_resume()`, which resumes only while "
                             "MIS_RESTART == 0. At 1 every dodge re-flies the field from lane 1.")

    def test_the_dds_pins_are_still_there(self):
        # The file's original job. Losing either is silent: zero /ap/* topics, no error.
        self.assertEqual(self.params()["DDS_ENABLE"], 1.0)
        self.assertEqual(self.params()["DDS_UDP_PORT"], 2019.0)

    def test_every_dds_enabled_sitl_start_loads_this_file(self):
        """A pin in a file nobody loads is not a pin. Line continuations are joined and `VAR=`
        shell assignments expanded first: three of the five sites put `--add-param-file` on the
        line after `--enable-DDS`, and one reaches it through a variable."""
        import re
        for site in self.SITL_START_SITES:
            text = (REPO_ROOT / site).read_text().replace("\\\n", " ")
            for name, value in re.findall(r'^(\w+)="([^"]+)"', text, re.M):
                text = text.replace(f"${name}", value)
            starts = [ln for ln in text.splitlines()          # `-v` = a real invocation, not prose
                      if "sim_vehicle.py -v" in ln and "--enable-DDS" in ln]
            with self.subTest(site=site):
                self.assertTrue(starts, msg=f"{site} no longer starts a DDS SITL — update this list")
                for line in starts:
                    self.assertIn("sitl_params/dds_udp.parm", line, msg=line)


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
