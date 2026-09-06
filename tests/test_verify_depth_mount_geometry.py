"""`scripts/verify_depth_mount_geometry.sh` — the harness's own honesty, pinned WITHOUT a renderer.

The gate ran for the first time on 2026-09-06 and scored a bird that had never moved: it stripped
the physics plugin so the nested-include vehicle would not free-fall, and `/world/<w>/set_pose` is
applied ONLY by the Physics system (`PhysicsPrivate::UpdatePhysics` is the sole consumer of
`components::WorldPoseCmd`, which `UserCommands::PoseCommand::Execute` merely creates). The service
still answered `data: true` — that Boolean means QUEUED, not MOVED — so two of the eight assertions
"passed" while the rest read nan and D3 came back 0.0 m.

What can only be proven live (the render, the intrinsics, the acquisition range) belongs to the
commissioning session. What is provable here is everything that made that run scoreable-but-empty:
physics is kept, gravity is zeroed instead, every teleport is verified by a pose readback, the
vehicle's park pose is asserted, the stale-server guard cannot kill the shell that runs it, and
teardown waits for the process AND its topics to go.

Lives in tests/ (not tests/fieldguard_planning/) like `test_fly_pipeline.py`: it tests a shell
script, not the planning package. stdlib unittest, so it runs under both pytest and
`python3 -m unittest`. No Docker, no gz, no numpy — one `bash -n` and one `sed` over the world file.
"""
import ast
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "verify_depth_mount_geometry.sh"
WORLD_SDF = REPO_ROOT / "sim" / "worlds" / "farmguard_field.sdf"
DEPTH_CONFIG = REPO_ROOT / "config" / "depth_camera.json"
NADIR_GATE = REPO_ROOT / "scripts" / "verify_mount_geometry.sh"
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "FORWARD_DEPTH_SENSOR.md"

TEXT = SCRIPT.read_text()
# Comment lines removed. The header and the inline notes have to be free to NAME the anti-patterns
# they warn against (`pgrep -f "gz sim"`, `/gz-sim-physics-system/d`), so the tripwires that forbid
# those constructs read the code, not the prose — the same reason `test_fly_pipeline.py` checks the
# DDS profile on a parsed tree instead of by substring.
CODE = "\n".join(ln for ln in TEXT.splitlines() if not ln.lstrip().startswith("#"))
# The header with its comment markers and line wraps flattened, so a claim can be asserted as a
# sentence rather than as whatever fragment survived the 100-column margin.
FLAT = " ".join(TEXT.replace("\n#", " ").split())
HAVE_BASH = shutil.which("bash") is not None
EXIT_TABLE = TEXT.split("# EXIT CODES", 1)[1].split("source /root", 1)[0]


def logical_lines():
    """The script's bash statements: comment-free, with backslash continuations JOINED.

    Line-at-a-time scanning lies about guards — `timeout 10 gz ... \\` / `> f 2>/dev/null || true`
    is one guarded statement wearing two lines, and reading them apart would flag the safe one and
    hide nothing.
    """
    out, buf = [], ""
    for raw in CODE.splitlines():
        buf += raw.rstrip()
        if buf.endswith("\\"):
            buf = buf[:-1] + " "
            continue
        out.append(buf.strip())
        buf = ""
    if buf:
        out.append(buf.strip())
    return [ln for ln in out if ln]


def unconditional(lines):
    """Statements bash runs for their SIDE EFFECT, so `set -e` kills the script on their failure.

    A conditional context (`if`/`while`/`until`, or a `case` pattern) neutralises `set -e`, which
    is why the teardown poll and the topic wait-loop are allowed to run bare greps.
    """
    return [ln for ln in lines if not re.match(r"^(if|elif|while|until|case|\))\b", ln)]


def heredoc(index):
    """Source of the index-th `<<'PYEOF'` block: 0 = `pose_check`'s, 1 = the scoring pass."""
    return TEXT.split("<<'PYEOF'\n")[index + 1].split("\nPYEOF", 1)[0]


SCORING = heredoc(1)
SCORING_AST = ast.parse(SCORING)


def linenos_of(text_fragment):
    """Line numbers, within the scoring block, of every string literal containing the fragment."""
    return [node.lineno for node in ast.walk(SCORING_AST)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and text_fragment in node.value]


def const(name):
    """A top-level scalar assignment, read out of the script text (it cannot be sourced: line 1
    sources the container's ROS setup and the body launches Gazebo)."""
    match = re.search(rf"(?:^|;\s*){name}=([^\s;#]+)", TEXT, re.M)
    assert match, f"{name} is no longer assigned in {SCRIPT.name}"
    return match.group(1)


def func_body(name):
    """A function's source, comments and all — for asserting that the WHY is written down."""
    return TEXT.split(f"{name}() {{", 1)[1].split("\n}", 1)[0]


def func_code(name):
    """The same, with comment lines dropped — for absence and ORDER assertions, which a comment
    that merely mentions the construct would otherwise satisfy or scramble."""
    return "\n".join(ln for ln in func_body(name).splitlines() if not ln.lstrip().startswith("#"))


class TestTheWorldCopyKeepsPhysics(unittest.TestCase):
    """Edit 1: the physics plugin STAYS, gravity is zeroed instead."""

    def test_the_physics_plugin_is_never_deleted(self):
        # The one line that made every teleport a no-op. Any spelling of the delete is the bug.
        self.assertNotIn("/gz-sim-physics-system/d", CODE)
        self.assertNotRegex(CODE, r"gz-sim-physics-system[^\n]*/d['\"]")

    def test_gravity_is_zeroed_and_appended_to_the_RENAMED_world(self):
        world = const("WORLD")
        self.assertIn(f'/<world name="${{WORLD}}">/a', TEXT)
        self.assertIn("<gravity>0 0 0</gravity>", TEXT)
        # Order is the property: the rename runs in the -e list, so the append's address matches the
        # already-renamed line. sed concatenates -e and -f in argv order.
        body = func_code("make_check_world")
        self.assertLess(body.index("farmguard_field"), body.index("-f "),
                        msg="the world rename must precede the -f append script")
        self.assertEqual(world, "depthcheck")

    def test_the_reason_is_written_down_where_the_next_reader_will_look(self):
        # A gate whose harness trick is undocumented gets "simplified" back into the bug.
        for citation in ("UserCommands.cc", "Physics.cc", "WorldPoseCmd", "QUEUED, not MOVED"):
            self.assertIn(citation, TEXT, msg=f"the header no longer explains {citation}")
        self.assertIn("does not inherit", TEXT)      # why <static> is not the fix

    def test_the_nadir_gate_is_left_alone(self):
        # ADR-019 forbids re-opening closed NDVI state; that script is live-verified at 2.2 px and
        # parks a static-scene camera that never teleports anything, so its sed is not this one's.
        self.assertIn("/gz-sim-physics-system/d", NADIR_GATE.read_text())


class TestTheGroundExtension(unittest.TestCase):
    """Edit 2: field_ground grows east-west IN THE COPY, so D2 CULL has geometry to cull."""

    def test_it_targets_the_committed_plane_size_and_makes_it_larger(self):
        self.assertIn("s|<size>125.00 110.00</size>|<size>${GROUND_EW_M} 110.00</size>|", TEXT)
        self.assertIn("<size>125.00 110.00</size>", WORLD_SDF.read_text(),
                      msg="the committed world's plane size changed — the check-world sed is dead")
        self.assertGreater(float(const("GROUND_EW_M")), 125.00)

    def test_the_north_south_extent_is_untouched(self):
        # Only the east-west run matters (the camera looks east); growing both would be a bigger
        # change to the scene than the measurement needs.
        self.assertIn("<size>${GROUND_EW_M} 110.00</size>", CODE)

    def test_the_header_says_why_and_scopes_it_to_the_copy(self):
        self.assertIn("39.85 m", TEXT)              # where the real ground ends, ahead of the park
        self.assertIn("COPY ONLY", TEXT)


@unittest.skipUnless(HAVE_BASH, "bash is unavailable — nothing to run the world copy with")
class TestTheGeneratedCopy(unittest.TestCase):
    """Runs the script's OWN `make_check_world` over the committed world, in a temp dir.

    Asserting on the sed text proves the intent; running it proves the two edits actually land —
    and that the committed world is not touched, which is the property `gen_farm_world.py`'s
    byte-reproducibility depends on.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        dst = Path(cls.tmp.name) / "world.sdf"
        before = hashlib.sha256(WORLD_SDF.read_bytes()).hexdigest()
        harness = "\n".join([
            "set -euo pipefail",
            f"WORLD={const('WORLD')}",
            f"PARK_E={const('PARK_E')}", f"PARK_N={const('PARK_N')}", f"PARK_U={const('PARK_U')}",
            f"GROUND_EW_M={const('GROUND_EW_M')}",
            "make_check_world() {" + func_body("make_check_world") + "\n}",
            f'make_check_world "{WORLD_SDF}" "{dst}"',
        ])
        cls.result = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
        cls.after = hashlib.sha256(WORLD_SDF.read_bytes()).hexdigest()
        cls.before = before
        cls.copy = dst.read_text() if dst.exists() else ""

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_copy_was_produced(self):
        self.assertEqual(self.result.returncode, 0, msg=self.result.stderr)
        self.assertTrue(self.copy)

    def test_the_committed_world_is_byte_identical_afterwards(self):
        self.assertEqual(self.before, self.after)

    def test_exactly_one_zero_gravity_element_and_it_is_inside_the_world(self):
        lines = self.copy.splitlines()
        gravity = [i for i, ln in enumerate(lines) if "<gravity>0 0 0</gravity>" in ln]
        world = [i for i, ln in enumerate(lines) if f'<world name="{const("WORLD")}">' in ln]
        self.assertEqual(len(gravity), 1, msg="a second <gravity> would be ambiguous, not safer")
        self.assertEqual(len(world), 1)
        self.assertEqual(gravity[0], world[0] + 1)
        self.assertEqual(self.copy.count("<gravity>"), 1)

    def test_the_copy_still_runs_physics(self):
        self.assertIn("gz-sim-physics-system", self.copy)

    def test_both_ground_planes_are_enlarged(self):
        # The visual AND the collision plane: a visual-only extension renders a ground the depth
        # camera can see, which is the half that matters — but a mismatched pair is a scene nobody
        # reviewed, so the sed is expected to hit both and the script asserts the count too.
        self.assertEqual(self.copy.count(f"<size>{const('GROUND_EW_M')} 110.00</size>"), 2)
        self.assertNotIn("<size>125.00 110.00</size>", self.copy)

    def test_the_vehicle_is_parked_and_the_topics_are_renamed(self):
        park = f'<pose degrees="true">{const("PARK_E")} {const("PARK_N")} {const("PARK_U")} 0 0 0'
        self.assertIn(park, self.copy)
        self.assertNotIn("fg/sensor", self.copy)     # cannot collide with a live bringup
        self.assertNotIn("fg/depth", self.copy)
        self.assertIn(f"{const('WORLD')}/depth/image", self.copy)


class TestTeleportsAreVerified(unittest.TestCase):
    """A queued command is not a moved bird: the readback is the whole fix."""

    def test_teleport_reads_the_pose_back_and_fails_the_harness_on_a_mismatch(self):
        body = func_code("teleport")
        self.assertIn("pose_check", body)
        self.assertIn("harness_fail", body)
        self.assertIn("DID NOT MOVE", body)
        # `data: true` is checked FIRST and is explicitly not sufficient.
        self.assertIn("data:true", body.replace(" ", ""))
        self.assertLess(body.index("data:true".replace(" ", "")) if "data:true" in body
                        else body.index("data: true"), body.index("pose_check"))

    def test_the_readback_comes_from_the_pose_info_topic(self):
        body = func_code("pose_check")
        self.assertIn(f"/world/${{WORLD}}/pose/info", body)
        self.assertIn('name: "{name}"', body)        # the model entry, not a link's
        self.assertIn("SystemExit(1)", body)

    def test_the_tolerance_is_tight_and_applies_to_every_axis(self):
        self.assertLessEqual(float(const("POSE_TOL_M")), 0.05)
        self.assertIn("all(abs(g - w) <= tol for g, w in zip(got, want))", TEXT)

    def test_the_vehicle_park_is_asserted_at_world_up_and_after_the_last_capture(self):
        calls = re.findall(r"^vehicle_check .*$", TEXT, re.M)
        self.assertEqual(len(calls), 2, msg=f"vehicle_check calls: {calls}")
        self.assertIn("at world-up", calls[0])
        self.assertIn("after the last capture", calls[1])
        self.assertLess(TEXT.index("vehicle_check \"at world-up\""),
                        TEXT.index("for R in $SWEEP_RANGES"))

    def test_a_failed_self_check_exits_4_and_disowns_every_number_above_it(self):
        body = func_body("harness_fail")
        self.assertIn("exit 4", body)
        self.assertIn("NOTHING PRINTED IS A MEASUREMENT", body.upper())

    def test_every_capture_logs_the_pose_that_was_read_back(self):
        body = func_code("capture")
        self.assertIn("BIRD_POSE", body)
        self.assertIn("pose_$1.txt", body)           # the python scoring reads these back


class TestTheStaleServerGuard(unittest.TestCase):
    def test_it_never_matches_its_own_command_line(self):
        # `pgrep -f "gz sim"` matched (and killed) the probe that ran it on 2026-09-06: -f matches
        # the WHOLE command line, so a `bash -c '... gz sim ...'` wrapper matches itself.
        self.assertNotIn('pgrep -f "gz sim"', CODE)
        self.assertNotIn("pgrep -f 'gz sim'", CODE)
        self.assertNotIn("pgrep -f gz", CODE)
        self.assertNotIn("pgrep", CODE, msg="no pgrep spelling survives a `bash -c` wrapper: "
                                            "-f self-matches and -x is vacuous against ruby")

    def test_it_matches_the_server_by_argv_including_the_ruby_spelling(self):
        body = func_code("gz_server_pids")
        self.assertIn("ps -eo pid=,args=", body)
        self.assertIn("ruby", body, msg="`gz` is a ruby script — matching only `gz` is vacuous")
        self.assertIn('$3 == "sim"', body)

    def test_it_refuses_before_launching_anything(self):
        self.assertIn("STALE_TOPICS", TEXT)
        guard = TEXT.index("refusing to start a second server")
        self.assertLess(guard, TEXT.index("gz sim -v1 -s -r"))
        self.assertLess(guard, TEXT.index('rm -rf "$OUT"'))


class TestTeardownWaits(unittest.TestCase):
    def test_it_polls_the_process_and_then_the_topics(self):
        body = func_code("teardown")
        self.assertIn("kill -0", func_code("gz_alive"))
        self.assertIn("while gz_alive; do", body)
        self.assertIn("kill -9", body)               # bounded, then SIGKILL, and it says so
        self.assertIn("SIGKILL", body)
        self.assertIn("gz topic -l", body)           # topics gone, not just the process
        self.assertLess(body.index("while gz_alive"), body.index("gz topic -l"))
        self.assertIn("teardown: server gone in", body)   # prints how long it took

    def test_a_zombie_is_not_read_as_alive(self):
        # `kill -0` succeeds on an unreaped child, so a bare kill -0 loop would burn its whole
        # timeout and then SIGKILL a corpse.
        self.assertIn("ps -o stat=", func_code("gz_alive"))

    def test_the_trap_is_armed_for_every_exit_path_including_exit_4(self):
        self.assertIn("trap teardown EXIT", TEXT)
        self.assertLess(TEXT.index("trap teardown EXIT"), TEXT.index("refusing to start a second"))
        self.assertIn('[ -n "${GZ_PID:-}" ] || return 0', func_code("teardown"))


class TestTheSweep(unittest.TestCase):
    def setUp(self):
        quoted = re.search(r'^SWEEP_RANGES="([^"]+)"', TEXT, re.M)
        self.assertTrue(quoted, "SWEEP_RANGES is no longer a quoted list")
        self.ranges = [float(r) for r in quoted.group(1).split()]

    def test_it_is_ascending_and_starts_at_the_D2_capture(self):
        self.assertEqual(self.ranges, sorted(self.ranges))
        self.assertEqual(self.ranges[0], float(const("D2_RANGE")))

    def test_it_ends_inside_the_far_clip_so_the_last_step_is_not_culled(self):
        clip_far = json.loads(DEPTH_CONFIG.read_text())["camera"]["clip_far_m"]
        self.assertLess(self.ranges[-1], clip_far,
                        msg="a swept range at or past the far clip measures the clip, not the bird")

    def test_it_reaches_past_the_host_side_pinhole_bound(self):
        # The 2026-09-06 probe still resolved a 4x4 px component at 46 m, so a sweep that stopped at
        # the 46.80 m bound would report a FLOOR and send the reader back for a second session.
        self.assertGreater(self.ranges[-1], 46.80)


class TestTheContract(unittest.TestCase):
    @unittest.skipUnless(HAVE_BASH, "bash is unavailable")
    def test_it_parses_under_bash(self):
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True)

    def test_every_exit_code_it_can_return_is_documented(self):
        header = TEXT.split("# EXIT CODES", 1)[1].split("source /root", 1)[0]
        for code in ("0", "1", "2", "3", "4"):
            self.assertRegex(header, rf"#\s+{code}\s+\S")
        used = {m for m in re.findall(r"^\s*(?:exit|raise SystemExit\()\s*(\d)", TEXT, re.M)}
        self.assertTrue(used <= {"0", "1", "2", "3", "4"}, msg=f"undocumented exit codes: {used}")

    def test_D3_is_a_measurement_and_not_a_pass_fail(self):
        # The booking gate is where a short horizon must bite; this script only reports it.
        self.assertIn("never fails the gate on its own", FLAT)
        self.assertIn("D3 MEASURED acquisition range", TEXT)


class TestAnAbortIsNeverMistakenForAVerdict(unittest.TestCase):
    """An unscoreable run must not read to the operator as a verdict on the mount.

    Two paths bypassed the published exit table (found 2026-09-06, both reproduced on the host
    with no renderer): the unguarded `gz topic -l | grep "^/<w>/depth"` pipeline aborts at **exit
    1** — the code the table sells as "GATE FAIL, with the failing assertion named" — before the D1
    diagnostic can print; and `capture()`'s bare `timeout 30 gz topic -e` aborts at **exit 124**,
    which the table did not mention at all, leaving a 0-byte frame behind. Both are fail-closed
    (never a false PASS) and both point the one booked session at the wrong thing.
    """

    def test_no_unconditional_grep_can_abort_the_run(self):
        # grep is the one command here that fails as a matter of COURSE: "no match" is exit 1, and
        # under `set -euo pipefail` that ends the script wearing the gate-fail exit code.
        naked = [ln for ln in unconditional(logical_lines())
                 if re.search(r"(?:^|[|;&]\s*)grep\b", ln) and "||" not in ln]
        self.assertEqual(naked, [], msg="an unmatched grep would abort the run as exit 1, which "
                                        "the exit table sells as a GATE FAIL: " + repr(naked))

    def test_every_timeout_is_guarded(self):
        # `timeout` exits 124, a code no gate assertion can produce. Bare, it aborts the run with a
        # number the table never taught and no banner at all.
        naked = [ln for ln in unconditional(logical_lines())
                 if re.search(r"(?:^|[|;&]\s*)timeout\s+\d", ln) and "||" not in ln]
        self.assertEqual(naked, [], msg="an expired timeout would abort at exit 124: " + repr(naked))

    def test_the_wait_loop_and_the_topic_list_agree_on_the_topic_name(self):
        # The loop waited on an UNANCHORED match while the listing that follows anchors, so the
        # loop could pass on a topic the listing then misses — turning "the sensor is namespaced
        # somewhere unexpected" into a bare exit 1 instead of the documented exit 2.
        self.assertIn('grep -q "^/${WORLD}/depth/image$"', CODE)

    def test_the_exit_table_covers_the_abort_only_codes(self):
        for code in ("124", "130", "143"):
            self.assertIn(code, EXIT_TABLE, msg=f"exit {code} is reachable and undocumented")
        self.assertIn("ABORTED, NOT SCORED", EXIT_TABLE)

    def test_an_abort_disowns_its_output_the_same_way_a_self_check_failure_does(self):
        # Whatever the code, the operator needs the same sentence: nothing above is a measurement.
        self.assertIn("NOTHING PRINTED IS A MEASUREMENT", func_body("harness_fail").upper())
        self.assertIn("same standing as 4", EXIT_TABLE.split("124", 1)[1])


class TestAFailedGateCannotHandOverANumber(unittest.TestCase):
    """D3's number and its copy-pasteable booking-gate command are the two things an operator
    carries out of this session. A run whose MOUNT gates failed must hand over neither.

    Reproduced 2026-09-06 by driving the real scoring heredoc with synthetic frames from an
    independent pinhole model: injecting a slant-range sensor gave `D2 OFFAX FAIL` + `D2 CULL FAIL`
    and exit 1 — and still printed `D3 MEASURED acquisition range: 46.0 m` and the exact
    `predict_forward_lead.py ... --acq-range-m 46.0` line that authorises a flight.
    """

    def test_the_verdict_fold_is_computed_before_the_D3_section(self):
        folds = [node.lineno for node in SCORING_AST.body if isinstance(node, ast.Assign)
                 and any(getattr(t, "id", None) == "ok" for t in node.targets)]
        self.assertTrue(folds, "the scoring block no longer folds the results into `ok`")
        self.assertLess(min(folds), min(linenos_of("D3 acquisition sweep")),
                        msg="D3 cannot know whether to disown itself until `ok` exists")

    def test_the_verdict_name_is_never_rebound_after_the_fold(self):
        """The verdict has to survive everything printed after it.

        Found 2026-09-06 by re-running the block: the sweep's `for r, ok in zip(ranges, detected)`
        reused the verdict's name, and a bash `for` target leaks. Harmless while the fold ran last;
        fatal once it runs first. A sweep that detected at EVERY range would leave `ok = True` and a
        mount that FAILED D2 would print PASS and exit 0 — a false PASS, the one outcome this gate
        exists to prevent (and the exact shape of the ADR-007 amendment-5 bug: a green tick over
        geometry nobody measured).
        """
        fold = min(node.lineno for node in SCORING_AST.body if isinstance(node, ast.Assign)
                   and any(getattr(t, "id", None) == "ok" for t in node.targets))
        rebinds = []
        for node in ast.walk(SCORING_AST):
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, (ast.For, ast.AugAssign,
                                                               ast.comprehension))
                       else [])
            rebinds += [t.lineno for target in targets for t in ast.walk(target)
                        if isinstance(t, ast.Name) and t.id == "ok" and t.lineno > fold]
        self.assertEqual(rebinds, [], msg=f"`ok` is rebound after the fold at lines {rebinds} — "
                                          f"the verdict printed at the bottom would not be the one "
                                          f"the gates computed")

    def test_the_named_verdicts_print_before_the_sweep_they_qualify(self):
        # So "the gate FAILED above" is literally true on the operator's screen, and so the failing
        # assertion is named BEFORE the long sweep table rather than after it.
        self.assertLess(SCORING.index("for name, good, detail in results:"),
                        SCORING.index("D3 acquisition sweep"))

    def test_the_booking_gate_command_is_printed_only_when_the_gate_passed(self):
        guarded = set()
        for node in ast.walk(SCORING_AST):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "ok":
                for stmt in node.body:
                    guarded.update(sub.lineno for sub in ast.walk(stmt)
                                   if hasattr(sub, "lineno"))
        # The INVOCATION, not every mention: the failure branch has to be free to name the script
        # it is refusing to hand over. `--acq-range-m` is checked separately because that is the
        # flag the number travels on, and it must never leave the guard either.
        invocation = linenos_of("predict_forward_lead.py --speed")
        self.assertTrue(invocation, "the booking-gate command line is no longer printed at all")
        for lineno in invocation + linenos_of("--acq-range-m"):
            self.assertIn(lineno, guarded,
                          msg="the booking-gate command must sit inside `if ok:` — a failed mount "
                              "cannot hand the operator the command that books a flight")

    def test_a_failed_run_labels_the_number_and_refuses_the_command(self):
        self.assertIn("NOT A MEASUREMENT OF THIS MOUNT", SCORING)
        self.assertIn("REFUSING", SCORING)
        # The sweep table itself still prints: it is the diagnostic, it is just not a measurement.
        self.assertLess(SCORING.index("DETECTED"), SCORING.index("REFUSING"))

    def test_the_summary_verdict_is_still_the_last_thing_printed(self):
        prints = [node.lineno for node in ast.walk(SCORING_AST)
                  if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print"]
        self.assertEqual(max(prints), max(linenos_of("forward depth mount geometry")))


class TestTheRunbookConditionsTheNumberOnExitZero(unittest.TestCase):
    """The script's refusal is only half the fix: the runbook told the operator to write the
    number down and put it in an ADR-020 amendment, neither sentence conditioned on exit 0."""

    def setUp(self):
        self.doc = RUNBOOK.read_text()

    def test_writing_the_number_down_is_conditioned(self):
        claim = re.search(r"Write the printed number down[^.]*\.", self.doc)
        self.assertTrue(claim, "the runbook no longer tells the operator to record D3")
        self.assertIn("exited 0", claim.group(0))

    def test_the_ADR_amendment_item_is_conditioned(self):
        item = re.search(r"1\. The D3 number.*", self.doc)
        self.assertTrue(item, "§6 item 1 no longer names the D3 number")
        self.assertIn("exited 0", item.group(0))


if __name__ == "__main__":
    unittest.main()
