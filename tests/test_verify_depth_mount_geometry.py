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
import base64
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
SCRIPT = REPO_ROOT / "scripts" / "verify_depth_mount_geometry.sh"
WORLD_SDF = REPO_ROOT / "sim" / "worlds" / "farmguard_field.sdf"
DEPTH_CONFIG = REPO_ROOT / "config" / "depth_camera.json"
NADIR_GATE = REPO_ROOT / "scripts" / "verify_mount_geometry.sh"
PREDICTOR = REPO_ROOT / "scripts" / "predict_forward_lead.py"
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
try:                                    # the scoring block's own dependencies, for driving it here
    import numpy                        # noqa: F401
    import scipy.ndimage                # noqa: F401  (ndvi_detect.detect_blobs)
    HAVE_NUMERICS = True
except Exception:                       # pragma: no cover — a host without the numeric stack
    HAVE_NUMERICS = False


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


class TestTheSweepFramesAreAssertedDistinct(unittest.TestCase):
    """G105: fifteen captures have to be fifteen DIFFERENT frames.

    A wedged renderer that republishes one frame would have every swept range scored off ONE
    capture, and D3 would report a long contiguous prefix that measures the stuck frame — the same
    failure shape as the run that scored a bird which never moved, with the repetition on the
    sensor side instead of the pose side. Until 2026-09-07 the only protection was INCIDENTAL: the
    offaxis and near captures come after the sweep, so a stuck frame would have failed D2 OFFAX /
    D2 NEAR. Incidental is not gated; this is.
    """

    def _frames(self, directory, payloads):
        paths = []
        for i, payload in enumerate(payloads):
            path = Path(directory) / f"frame_{10 * (i + 1)}.json"
            path.write_text(json.dumps({"width": 2, "height": 2, "data": payload}))
            paths.append(str(path))
        return paths

    def _run(self, script, files):
        harness = "\n".join([
            "set -euo pipefail",
            "distinct_frames() {" + func_body("distinct_frames") + "\n}",
            script.format(files=" ".join(files)),
        ])
        return subprocess.run(["bash", "-c", harness], capture_output=True, text=True)

    @unittest.skipUnless(HAVE_BASH, "bash is unavailable")
    def test_it_counts_distinct_frames_and_succeeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = self._frames(tmp, ["AAAA", "BBBB", "CCCC"])
            got = self._run("distinct_frames {files}", files)
        self.assertEqual(got.returncode, 0, msg=got.stdout + got.stderr)
        self.assertEqual(got.stdout.strip(), "3")

    @unittest.skipUnless(HAVE_BASH, "bash is unavailable")
    def test_two_identical_frames_are_rejected_and_both_are_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = self._frames(tmp, ["AAAA", "BBBB", "AAAA"])
            got = self._run("distinct_frames {files}", files)
        self.assertNotEqual(got.returncode, 0)
        self.assertIn("frame_30.json", got.stdout)
        self.assertIn("frame_10.json", got.stdout)      # the one it collided WITH, not just itself

    @unittest.skipUnless(HAVE_BASH, "bash is unavailable")
    def test_a_missing_or_unreadable_frame_is_rejected_too(self):
        # The list is built from the capture loop, so "all distinct" is also "all present": a
        # capture that left a 0-byte frame must not read as fourteen distinct frames.
        with tempfile.TemporaryDirectory() as tmp:
            got = self._run("distinct_frames {files}", [str(Path(tmp) / "frame_nope.json")])
        self.assertNotEqual(got.returncode, 0)
        self.assertIn("unreadable", got.stdout)

    @unittest.skipUnless(HAVE_BASH, "bash is unavailable")
    def test_the_real_guard_turns_a_repeated_frame_into_exit_4(self):
        """The script's own `if ! DISTINCT=...` block, run against a stubbed `harness_fail`.

        Exit 4 is the code that disowns every number above it. Exit 1 here would be read as a MOUNT
        failure and 0 as a measurement, so the routing is the assertion.
        """
        guard = re.search(r"if ! DISTINCT=.*?\nfi\n", TEXT, re.S)
        self.assertTrue(guard, "the sweep-distinctness guard is gone from the script")
        with tempfile.TemporaryDirectory() as tmp:
            files = self._frames(tmp, ["AAAA", "AAAA"])
            harness = "\n".join([
                "set -euo pipefail",
                f"OUT={tmp}",
                'harness_fail() { echo "[verify_depth_mount] FAIL (harness self-check): $*";'
                ' echo "exit 4 - NOTHING PRINTED IS A MEASUREMENT"; exit 4; }',
                "distinct_frames() {" + func_body("distinct_frames") + "\n}",
                f'SWEEP_FRAMES="{" ".join(files)}"',
                guard.group(0),
                "echo SCORED_ANYWAY",
            ])
            got = subprocess.run(["bash", "-c", harness], capture_output=True, text=True)
        self.assertEqual(got.returncode, 4, msg=got.stdout + got.stderr)
        self.assertNotIn("SCORED_ANYWAY", got.stdout)
        self.assertIn("NOT all distinct", got.stdout)

    def test_the_guard_runs_after_the_sweep_and_before_anything_is_scored(self):
        self.assertLess(CODE.index("for R in $SWEEP_RANGES"), CODE.index("distinct_frames $SWEEP"))
        self.assertLess(CODE.index("distinct_frames $SWEEP"), CODE.index('capture "offaxis"'))
        self.assertIn("harness_fail", TEXT.split("if ! DISTINCT=", 1)[1].split("\nfi", 1)[0])
        # The list comes from the loop that captured it, not from a glob that could pick up the
        # offaxis/near frames (or miss one) and quietly change what "distinct" means.
        self.assertIn('SWEEP_FRAMES="$SWEEP_FRAMES $OUT/frame_$R.json"', CODE)
        self.assertNotIn("frame_*.json", CODE)

    def test_the_distinct_count_is_printed_as_evidence(self):
        self.assertIn("${DISTINCT} distinct of ${SWEEP_N} captured", TEXT)

    def test_the_header_and_the_exit_table_carry_the_rule(self):
        self.assertIn("AND THE SWEEP IS ASSERTED TO BE A SWEEP", FLAT)
        self.assertIn("BYTE-IDENTICAL", EXIT_TABLE)

    def test_its_heredoc_delimiter_stays_out_of_the_PYEOF_index(self):
        # `heredoc(i)` indexes the PYEOF blocks positionally (0 = pose_check, 1 = the scoring
        # block). A third PYEOF ahead of them would silently re-point SCORING at this hasher.
        self.assertEqual(TEXT.count("<<'PYEOF'"), 2)
        self.assertIn("<<'PYHASH'", TEXT)
        self.assertIn("import hashlib", SCRIPT.read_text())


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

    def test_the_printed_booking_command_uses_flags_the_tool_actually_accepts(self):
        """The line this gate prints is the one an operator copies to authorise a flight — so it
        has to survive changes on the OTHER side of the seam.

        On 2026-09-07 `predict_forward_lead.py` grew from two live intrinsics to a SET OF SIX and
        began REFUSING a partial set (exit 2, QA probe C). That silently turned the command printed
        here into a refusal: a passing gate handing over a line that cannot run. A cross-file seam
        gets a cross-file test.
        """
        printed = set(re.findall(r"--[a-z][a-z0-9-]+", SCORING))
        accepted = set(re.findall(r'add_argument\("(--[a-z0-9-]+)"', PREDICTOR.read_text()))
        self.assertTrue(printed, "the gate prints no booking-gate flags at all")
        self.assertLessEqual(printed, accepted,
                             msg=f"printed flags the tool rejects: {sorted(printed - accepted)}")
        # The intrinsics are a SET: printing a subset would be printing a refusal.
        for flag in ("--speed", "--fx", "--fy", "--cx", "--cy", "--width", "--height",
                     "--acq-range-m", "--acq-optical-prefix-m"):
            self.assertIn(flag, printed)

    def test_the_six_intrinsics_are_SUBSTITUTED_and_not_placeholders(self):
        """The operator must copy a SET, not retype six numbers into one.

        The gate refuses a partial set (exit 2) and a hand-retyped intrinsic is how a partial or
        mismatched set happens — the failure mode is silent, because five live numbers beside one
        stale one still parse. Until 2026-09-07 this line printed `<K[0]> <K[4]> …` and left the
        transcription to the reader. `fx` and `fy` differ in the LAST ULP on this sensor, so they
        are printed at full `repr` and never rounded: a rounded pair reads as "square pixels,
        confirmed" when the truth is "square to fifteen digits".
        """
        for spelled in ("--fx {fx!r}", "--fy {fy!r}", "--cx {cx_px!r}", "--cy {cy_px!r}",
                        "--width {ci_w:.0f}", "--height {ci_h:.0f}"):
            self.assertIn(spelled, SCORING, msg=f"{spelled} is not substituted from camera_info")
        self.assertNotIn("<K[0]>", SCORING)
        self.assertNotIn("--width <w>", SCORING)

    def test_config_fallback_intrinsics_cannot_wear_the_live_flags(self):
        """Six config numbers under `--fx … --height` would PASS the booking gate's set check and
        answer ADR-019 item 6 with prose — undetectably, since the flags are the only thing
        downstream that says "live". So the command line is guarded on the parse, not just on the
        verdict."""
        self.assertIn("if acq_book > 0.0 and intr_live:", SCORING)
        self.assertIn("intr_live = True", SCORING)
        self.assertIn("intr_live = False", SCORING)

    def test_a_failed_run_labels_the_number_and_refuses_the_command(self):
        self.assertIn("NOT A MEASUREMENT OF THIS MOUNT", SCORING)
        self.assertIn("REFUSING", SCORING)
        # The sweep table itself still prints: it is the diagnostic, it is just not a measurement.
        self.assertLess(SCORING.index("DETECTED"), SCORING.index("REFUSING"))

    def test_the_summary_verdict_is_still_the_last_thing_printed(self):
        prints = [node.lineno for node in ast.walk(SCORING_AST)
                  if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print"]
        self.assertEqual(max(prints), max(linenos_of("forward depth mount geometry")))


class TestTheCornerBoundIsTheOneImportedCopy(unittest.TestCase):
    """The frame-corner far-clip bound is IMPORTED, never re-derived here.

    Three gates need this number from three different input sources — the host static gate
    (config), the host booking gate (live `camera_info`) and this in-render one (the frame's own
    `camera_info`) — and it lived as three hand-written copies until two were measured wrong at
    once. THIS was the wrong one: it read the principal point as `w/2` and `cy`, divided BOTH terms
    by `fx`, and never touched `K[2]` or `K[4]` at all. Each error is optimistic in the same
    direction, and under ADR-020 am. 1 this bound is what CLAMPS the acquisition range a flight is
    booked on — at a live `cy` of 120 the sibling copy published 50.14 m where the honest bound is
    44.05 m (QA probe C).
    """

    def test_it_is_imported_from_the_tree_the_container_puts_on_sys_path(self):
        # The scoring block runs inside the container; `sys.path.insert(0, ".../src")` is the only
        # tree it can import from, which is why the primitive lives in src/ and not in scripts/.
        self.assertIn('sys.path.insert(0, "/workspace/fieldguard/src")', SCORING)
        imports = {node.module: {alias.name for alias in node.names}
                   for node in ast.walk(SCORING_AST) if isinstance(node, ast.ImportFrom)}
        self.assertIn("fieldguard_planning.depth_detect", imports,
                      msg="the corner bound is no longer imported from the one copy")
        self.assertIn("corner_ray_ratio", imports["fieldguard_planning.depth_detect"])

    def test_every_call_passes_all_six_live_inputs_in_order(self):
        calls = [node for node in ast.walk(SCORING_AST) if isinstance(node, ast.Call)
                 and getattr(node.func, "id", None) == "corner_ray_ratio"]
        self.assertTrue(calls, "corner_ray_ratio is imported but never called")
        for call in calls:
            self.assertEqual([getattr(a, "id", None) for a in call.args],
                             ["ci_w", "ci_h", "fx", "fy", "cx_px", "cy_px"],
                             msg="W, H, fx, fy, cx, cy — in that order, all six from camera_info")
            self.assertEqual(call.keywords, [])

    def test_the_six_are_read_off_camera_info_and_nothing_else(self):
        for spelled in ('float(kk[0])', 'float(kk[4])', 'float(kk[2])', 'float(kk[5])',
                        'float(ci["width"])', 'float(ci["height"])'):
            self.assertIn(spelled, SCORING, msg=f"{spelled} is not read from camera_info.json")

    def test_the_bound_is_never_recomputed_by_hand(self):
        assigns = [node for node in ast.walk(SCORING_AST) if isinstance(node, ast.Assign)
                   and any(getattr(t, "id", None) == "corner_ray" for t in node.targets)]
        self.assertTrue(assigns, "corner_ray is no longer computed at all")
        for node in assigns:
            self.assertIsInstance(node.value, ast.Call)
            self.assertEqual(getattr(node.value.func, "id", None), "corner_ray_ratio")

    def test_no_surviving_sqrt_computes_a_corner_bound(self):
        """The two `math.sqrt` expressions that remain are the OFF-AXIS ratio and the CULL ray —
        both per-pixel, neither a corner bound. Naming them is the assertion: a third one would be
        a fourth copy of the formula this class exists to delete."""
        owners = []
        for node in ast.walk(SCORING_AST):
            if isinstance(node, ast.Assign) and any(
                    isinstance(sub, ast.Attribute) and sub.attr == "sqrt"
                    for sub in ast.walk(node.value)):
                owners += [t.id for t in node.targets if isinstance(t, ast.Name)]
        self.assertEqual(sorted(owners), ["ratio", "ray"], msg=f"sqrt assignments: {owners}")

    def test_the_three_wrong_spellings_are_gone(self):
        self.assertNotIn("(cy_px / fx)", SCORING)      # vertical term over the horizontal focal
        self.assertNotIn("(w / 2.0) / fx", SCORING)    # principal point assumed at frame centre
        self.assertNotIn("math.sqrt(1.0 + ((w", SCORING)

    def test_the_vertical_terms_all_divide_by_fy(self):
        # Same class of bug as the corner formula's, in the two per-pixel rays beside it: they are
        # equal on this sensor (square pixels, live camera_info agreed with config fx to 1 ULP) and
        # the arithmetic must not silently depend on that staying true.
        self.assertIn("(oa_dv / fy) ** 2", SCORING)
        self.assertIn("((vv[i] - cy_px) / fy) ** 2", SCORING)

    def test_the_primitive_really_is_there_and_reproduces_the_live_bound(self):
        """A cross-file seam gets a cross-file test: this asserts the import will RESOLVE in the
        container and that the number it returns is the one the session was booked on."""
        import sys
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from fieldguard_planning.depth_detect import corner_ray_ratio
        import inspect
        self.assertEqual(list(inspect.signature(corner_ray_ratio).parameters),
                         ["width_px", "height_px", "fx", "fy", "cx", "cy"])
        # The live run-2 intrinsics (2026-09-07): the bound the D4 artifact was clamped against.
        ratio = corner_ray_ratio(640.0, 480.0, 520.0058046927554, 520.0058046927553, 320.0, 240.0)
        self.assertAlmostEqual(60.0 / ratio, 47.558, places=2)

    def test_a_degenerate_live_set_falls_back_instead_of_faking_a_mount_verdict(self):
        # corner_ray_ratio RAISES on fx<=0 or a <2 px frame. Called only at the bottom of the
        # block, that exception would abort python at exit 1 — the code the exit table sells as a
        # MOUNT failure. Called inside the parse's `try`, it routes to the config fallback, which
        # then refuses the booking line.
        parse = SCORING.split("try:", 1)[1].split("except Exception", 1)[0]
        self.assertIn("corner_ray_ratio(ci_w, ci_h, fx, fy, cx_px, cy_px)", parse)


class TestEverySweptStationCarriesItsRange(unittest.TestCase):
    """Frame DISTINCTNESS (G105) is necessary and not sufficient.

    Fifteen different frames can still be fifteen frames of a bird that is not where the sweep
    thinks it is — sensor noise alone makes two captures of one scene distinct — and `r_apparent`
    cannot tell, because the footprint has PLATEAUED at 4x4 px from 40 m out, which is exactly the
    band the booked number is read from. So each detected station's component must CARRY ITS RANGE:
    median finite depth inside its box against the bird's true Z. Measured on the run-2 frames
    (2026-09-07): member depths track true Z to 0.02-0.16 m at every station 10..58 m.
    """

    def test_the_assertion_exists_and_is_bound_by_the_shared_TOL_M(self):
        self.assertIn("abs(z_med - want_z) <= tol_m", SCORING)
        # The SAME tolerance D2 RANGE uses, threaded in as $TOL_M — not a second private literal
        # that could be relaxed without anyone noticing which gate it belonged to.
        self.assertNotRegex(SCORING, r"abs\(z_med - want_z\) <= [0-9]")
        self.assertEqual(float(const("TOL_M")), 0.20)
        self.assertIn('"$OUT" "$D2_RANGE" "$TOL_PX" "$TOL_M"', TEXT)

    def test_the_expectation_is_the_birds_true_Z_and_not_the_commanded_range(self):
        self.assertIn("want_z = r - BIRD_R", SCORING)
        self.assertIn("BIRD_R = 0.18", SCORING)

    def test_the_median_is_taken_over_FINITE_members_of_the_blob_box(self):
        # +inf background inside a half-open box would poison a mean and an unmasked median alike.
        self.assertIn("member = patch[np.isfinite(patch)]", SCORING)
        self.assertIn("np.median(member)", SCORING)

    def test_a_MISSED_station_is_not_a_harness_failure(self):
        # A miss is the horizon — the thing being measured. Only a DETECTED blob owes a depth.
        self.assertIn("if hit and not z_ok:", SCORING)

    def test_it_prints_beside_r_apparent_in_the_same_sweep_row(self):
        rows = []
        for node in ast.walk(SCORING_AST):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
                rows.append("".join(sub.value for sub in ast.walk(node)
                                    if isinstance(sub, ast.Constant)
                                    and isinstance(sub.value, str)))
        self.assertTrue(any("r_app" in row and "z_med" in row for row in rows),
                        msg="the depth evidence must ride the sweep row, not a separate table")

    def test_a_mismatch_is_the_HARNESS_class_and_not_a_mount_verdict(self):
        block = SCORING.split("if depth_bad:", 1)[1].split("\n\n", 1)[0]
        self.assertIn("raise SystemExit(4)", block)
        self.assertIn("NOTHING PRINTED IS A MEASUREMENT", block)
        self.assertIn("NOT A MEASUREMENT", block)
        self.assertNotIn("SystemExit(1)", block)

    def test_it_runs_before_the_prefix_and_before_the_booking_line(self):
        # Refusing the booking line by CONSTRUCTION: a bad sweep never reaches the number, so there
        # is no `if` anyone can get wrong later.
        self.assertLess(SCORING.index("if depth_bad:"), SCORING.index("acq = 0.0"))
        self.assertLess(SCORING.index("if depth_bad:"),
                        SCORING.index("predict_forward_lead.py --speed"))

    def test_G105_is_kept_alongside_it_and_both_are_documented(self):
        self.assertIn("distinct_frames $SWEEP", CODE)          # the hash guard survives
        self.assertIn("G105 DISTINCTNESS", FLAT)
        self.assertIn("PER-STATION DEPTH EVIDENCE", FLAT)
        self.assertIn("WRONG DEPTH", EXIT_TABLE)               # exit 4 names this cause


@unittest.skipUnless(HAVE_NUMERICS, "numpy/scipy unavailable — cannot drive the scoring block")
class TestTheScoringBlockOnSyntheticFrames(unittest.TestCase):
    """The real scoring heredoc, driven host-side against frames from an INDEPENDENT pinhole model.

    The container's run-2 frames cannot be reached from here, so the depth assertion is exercised
    red and green on synthetic ones: a ray-traced sphere of the bird's radius, +inf sky past the
    far clip, -inf inside the near clip, one painted `far/|ray|` pixel so D2 CULL has its ground.
    That model is not the renderer's, which is the point — it reproduces the live run's own numbers
    (D2 CULL 58.01 m at pixel (289,374), |ray| 1.034; corner bound 47.56 m) from first principles.
    """

    FX, FY, CX, CY = 520.0058046927554, 520.0058046927553, 320.0, 240.0
    W, H, R, FAR, NEAR = 640, 480, 0.18, 60.0, 0.1

    @classmethod
    def _sphere(cls, z_c, du=0.0, dv=0.0, cull_pixel=None):
        """Z-depth frame of a sphere of radius R centred at Z=z_c, offset (du, dv) px."""
        import numpy as np
        a = (np.arange(cls.W, dtype=float)[None, :] - cls.CX) / cls.FX
        b = (np.arange(cls.H, dtype=float)[:, None] - cls.CY) / cls.FY
        a0, b0 = du / cls.FX, dv / cls.FY
        # |(a z, b z, z) - C|^2 = R^2, solved for the NEAR root in z.
        qa = a * a + b * b + 1.0
        qb = z_c * (a * a0 + b * b0 + 1.0)
        qc = z_c * z_c * (a0 * a0 + b0 * b0 + 1.0) - cls.R * cls.R
        disc = qb * qb - qa * qc
        d = np.full((cls.H, cls.W), np.inf)
        hit = disc >= 0.0
        d[hit] = ((qb - np.sqrt(np.maximum(disc, 0.0))) / qa)[hit]
        slant = d * np.sqrt(qa)                       # gz culls on EUCLIDEAN range, stores Z-depth
        d[np.isfinite(d) & (slant > cls.FAR)] = np.inf
        d[np.isfinite(d) & (slant < cls.NEAR)] = -np.inf
        if cull_pixel is not None:
            cu, cv = cull_pixel
            ray = math.sqrt(1.0 + ((cu - cls.CX) / cls.FX) ** 2 + ((cv - cls.CY) / cls.FY) ** 2)
            d[cv, cu] = cls.FAR / ray                 # a lone pixel: 3x3 opening deletes it
        return d

    @classmethod
    def _dump(cls, path, d):
        import numpy as np
        path.write_text(json.dumps({
            "width": cls.W, "height": cls.H,
            "data": base64.b64encode(np.asarray(d, dtype="<f4").tobytes()).decode()}))

    def _run(self, station_20_z, camera_info=True):
        """Two stations (10 m, 20 m); `station_20_z` is what the 20 m frame ACTUALLY shows.

        `None` renders an empty sky at station 2 — a legitimate MISS, i.e. the horizon.
        """
        import numpy as np
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            if camera_info:
                (out / "camera_info.json").write_text(json.dumps(
                    {"width": self.W, "height": self.H,
                     "intrinsics": {"k": [self.FX, 0.0, self.CX,
                                          0.0, self.FY, self.CY, 0.0, 0.0, 1.0]}}))
            self._dump(out / "frame_10.json", self._sphere(10.0, cull_pixel=(289, 374)))
            self._dump(out / "frame_20.json",
                       np.full((self.H, self.W), np.inf) if station_20_z is None
                       else self._sphere(station_20_z))
            self._dump(out / "frame_offaxis.json", self._sphere(20.0, du=240.0, dv=-120.0))
            self._dump(out / "frame_near.json", np.full((self.H, self.W), -np.inf))
            for tag in ("10", "20", "offaxis", "near"):
                (out / f"pose_{tag}.txt").write_text("synthetic\n")
            env = dict(os.environ, PYTHONPATH=str(REPO_ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
            return subprocess.run(
                [sys.executable, "-c", SCORING, str(out), "10", "15", "0.20", "10 20",
                 "20.0", "240.0", "-120.0", "0.25"],
                capture_output=True, text=True, env=env)

    def test_green_every_station_carries_its_range_and_the_gate_passes(self):
        got = self._run(20.0)
        self.assertEqual(got.returncode, 0, msg=got.stdout + got.stderr)
        for gate in ("D2 CLEAR PASS", "D2 RANGE PASS", "D2 AIM   PASS", "D2 OFFAX PASS",
                     "D2 AXES  PASS", "D2 NEAR  PASS", "D2 FAR   PASS", "D2 CULL  PASS"):
            self.assertIn(gate, got.stdout)
        self.assertIn("z_med   9.87 vs   9.82 m", got.stdout)
        self.assertIn("z_med  19.87 vs  19.82 m", got.stdout)
        self.assertNotIn("WRONG DEPTH", got.stdout)

    def test_green_the_booking_line_carries_the_six_live_values(self):
        got = self._run(20.0)
        self.assertIn("--fx 520.0058046927554 --fy 520.0058046927553 --cx 320.0 --cy 240.0",
                      got.stdout)
        self.assertIn("--width 640 --height 480", got.stdout)
        self.assertIn("--acq-range-m 20.0 --acq-optical-prefix-m 20.0", got.stdout)
        # The bound is the imported one, on the live set — unchanged at 47.56 m by this refactor.
        self.assertIn("47.56 m frame-corner", got.stdout)

    def test_the_pinhole_bound_is_DERIVED_from_this_runs_fx_and_labelled_corroboration(self):
        """It printed the literal string `46.80 m` until 2026-09-07 — right for this mount and
        silently wrong for the next one — and the runbook then published a min-of-three rule the
        `acq_book` expression does not contain (QA, 2026-09-07). The bookable number is the
        two-bound one (prefix INTERSECT corner); the morphology bound is corroboration, and it now
        says so and is computed from the same live `fx` as everything else on the line."""
        got = self._run(20.0)
        prefix_line = next(ln for ln in got.stdout.splitlines() if "OPTICAL PREFIX" in ln)
        self.assertIn("from this run's fx: 46.80 m", prefix_line)
        self.assertIn("NOT a term in the bookable number", prefix_line)
        # ...and it is genuinely fx * R / MIN_RESOLVING_RADIUS_PX, not a coincidence of formatting.
        sys.path.insert(0, str(REPO_ROOT / "src"))
        from fieldguard_planning.depth_detect import acquisition_range_m
        self.assertIn(f"{acquisition_range_m(self.FX, self.R):.2f} m", prefix_line)

    def test_red_a_frame_from_another_station_is_exit_4_and_no_booking_line(self):
        """The 20 m station shows a 30 m frame: the blob is still centred, still one component,
        still a DISTINCT frame — and G105 cannot see it. Only the depth can."""
        got = self._run(30.0)
        self.assertEqual(got.returncode, 4, msg=got.stdout + got.stderr)
        self.assertIn("WRONG DEPTH", got.stdout)
        self.assertIn("blob median depth 29.874 m vs the bird's true Z 19.820 m", got.stdout)
        self.assertIn("NOT A MEASUREMENT", got.stdout)
        self.assertNotIn("predict_forward_lead.py", got.stdout)
        self.assertNotIn("BOOKABLE", got.stdout)

    def test_a_missed_station_is_still_a_measurement_it_is_the_horizon(self):
        got = self._run(None)
        self.assertEqual(got.returncode, 0, msg=got.stdout + got.stderr)
        self.assertIn("missed", got.stdout)
        self.assertIn("--acq-range-m 10.0", got.stdout)      # the prefix stops at the last hit

    def test_without_camera_info_the_booking_line_is_refused_not_faked(self):
        got = self._run(20.0, camera_info=False)
        self.assertEqual(got.returncode, 0, msg=got.stdout + got.stderr)   # the MOUNT is fine
        self.assertIn("CONFIG FALLBACK", got.stdout)
        self.assertIn("REFUSING to print a booking command line", got.stdout)
        self.assertNotIn("predict_forward_lead.py --speed", got.stdout)


class TestTheAvoidanceRunbookBooksOnTheWholeSet(unittest.TestCase):
    """§0f of AVOIDANCE_REAL_DETECTION.md is where a dodge take actually gets booked.

    It published a THREE-flag command (`--fx --cy --acq-range-m`) after the tool grew to a set of
    six, and told the reader a partial set was exit 3 when it is exit 2. Both errors point the same
    way: exit 3 reads as "PASS, just not bookable", so a refusal would have been filed as a passing
    design check.
    """

    AVOIDANCE_RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "AVOIDANCE_REAL_DETECTION.md"

    def setUp(self):
        doc = self.AVOIDANCE_RUNBOOK.read_text()
        self.assertIn("### 0f.", doc, msg="§0f, the booking gate, is gone from the runbook")
        self.section = doc.split("### 0f.", 1)[1].split("\n---", 1)[0]

    def test_the_command_carries_the_seven_flags(self):
        for flag in ("--fx", "--fy", "--cx", "--cy", "--width", "--height", "--acq-range-m"):
            self.assertIn(flag, self.section, msg=f"§0f's booking command is missing {flag}")

    def test_every_flag_it_prints_is_one_the_tool_accepts(self):
        printed = set(re.findall(r"--[a-z][a-z0-9-]+", self.section))
        accepted = set(re.findall(r'add_argument\("(--[a-z0-9-]+)"', PREDICTOR.read_text()))
        self.assertLessEqual(printed, accepted,
                             msg=f"flags the tool rejects: {sorted(printed - accepted)}")

    def test_a_partial_set_is_exit_2_and_config_prose_is_exit_3(self):
        self.assertNotIn("all three, or exit 3", self.section)
        rows = {m.group(1): m.group(2) for m in
                re.finditer(r"^\|\s*\*{0,2}(\d)\*{0,2}\s*\|(.*)$", self.section, re.M)}
        for code in ("0", "1", "2", "3"):
            self.assertIn(code, rows, msg=f"§0f no longer documents exit {code}")
        self.assertIn("part", rows["2"].lower())          # a PARTIAL live set refuses
        self.assertIn("refusal", rows["2"].lower())
        self.assertIn("config-sourced", rows["3"])
        self.assertIn("bookable", rows["0"].lower())

    def test_the_set_is_described_as_a_set_and_the_gate_is_named_as_its_source(self):
        self.assertIn("SET", self.section)
        self.assertIn("verify_depth_mount_geometry.sh", self.section)


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
