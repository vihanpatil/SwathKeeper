"""The achieved-displacement NOTE in scripts/check_live_flight_log.py -- REPORTED, NEVER GATED
(G1/G2, 2026-09-10).

WHAT IS UNDER TEST. `maneuver.verdict` is the string "accepted", written on the tick the executor
PUBLISHES a setpoint; no gate has ever compared what was commanded with what the aircraft did. The
note block measures it on every flight the gate reads. It is a NOTE on purpose: the point-mass
replay (ADR-016 am. 2, 2026-08-26) showed the naive reading is wrong-axis -- on two of the three
committed flights the along-command displacement is NEGATIVE -- and a 0.434 s window cannot separate
a working command path from a dead one. So this file pins two things and they are different:

  1. THE NUMBERS, against the committed 2026-08-25 take: the 0.434 s window and the 0.018 m of
     cross-course dodge that ADR-013 am. 12 quotes, plus the 0.0541 m / 0.0359 m / 0.52 deg split
     the replay tool measured independently in `eval/replay_point_mass.py`. Two tools, one number.
  2. THAT IT CHANGES NOTHING. Every committed log's verdict, exit code and every OTHER message is
     compared against the same run with the note suppressed. A note that can move a verdict is a
     gate nobody reviewed.

And one synthetic flight where the vehicle DOES fly the dodge, so the metric is shown to be capable
of reading ~10 m -- otherwise "0.018 m" is indistinguishable from a broken measurement.

stdlib unittest only. Run: python3 -m unittest discover -s tests/fieldguard_planning -v
"""
import io
import json
import math
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_live_flight_log as checker  # noqa: E402

RESULTS = REPO_ROOT / "eval" / "results"
TAKE_20260825 = RESULTS / "live_flight_log_20260825T210402Z.json"
LEGACY_LOGS = (RESULTS / "live_flight_log_20260818T144711Z.json",
               RESULTS / "live_flight_log_20260823T004031Z.json")

# The note's own prefix. Every line of the block is either the head or an indented continuation, and
# the invariance test below strips exactly these -- so if the prefix drifts, that test fails loudly
# rather than silently comparing nothing.
HEAD = "achieved displacement, encounter "


def _load(path: Path) -> dict:
    if not path.exists():
        raise unittest.SkipTest(f"{path.name} absent (eval/results is gitignore-excepted)")
    return json.loads(path.read_text())


def _one(lines, needle):
    """The single note line containing `needle` -- asserting there is exactly one, because a metric
    that appears twice with two values is the failure this whole file is about."""
    hits = [ln for ln in lines if needle in ln]
    assert len(hits) == 1, f"expected exactly one line containing {needle!r}, got {len(hits)}"
    return hits[0]


def _num_after(line, label):
    """The first signed number printed after `label` on a note line."""
    m = re.search(re.escape(label) + r"\s*([+-]?\d+\.\d+)", line)
    assert m, f"no number after {label!r} in: {line}"
    return float(m.group(1))


class TestTheFlownTake(unittest.TestCase):
    """2026-08-25 -- the only real-detection take, and the one whose numbers are published."""

    @classmethod
    def setUpClass(cls):
        cls.log = _load(TAKE_20260825)
        cls.notes = checker.displacement_notes(cls.log)

    def test_one_block_for_the_one_encounter(self):
        self.assertEqual(sum(1 for ln in self.notes if ln.startswith(HEAD)), 1)
        self.assertEqual(len(self.notes), 6)

    def test_the_guided_authority_window_is_the_published_0_434_s(self):
        """ADR-013 am. 12 / DECISIONS.md: 'the GUIDED authority window was 0.434 s (ticks
        991->995)'. Recomputed here from the log's own takeover/resume events and stamps."""
        head = _one(self.notes, HEAD)
        self.assertIn("ticks 991 -> 995 (takeover -> resume)", head)
        self.assertIn("4 tick step(s)", head)
        self.assertIn("0.434 s sim (202.775 -> 203.209 s)", head)

    def test_the_dodge_moved_the_aircraft_18_millimetres(self):
        """THE NUMBER. 0.018 m of cross-course displacement against a 10 m commanded dodge --
        the figure the ADR publishes, and the one `eval/replay_point_mass.py` measured offline.
        Audits that recompute it over other windows land in 0.018-0.027 m; this is the window the
        executor itself delimited."""
        line = _one(self.notes, "ON THE COMMANDED AXIS")
        self.assertAlmostEqual(_num_after(line, "cross-course dodge"), 0.0182, places=4)
        self.assertAlmostEqual(_num_after(line, "ON THE COMMANDED AXIS"), 0.0541, places=4)
        self.assertAlmostEqual(_num_after(line, "cruise leak"), 0.0359, places=4)
        self.assertAlmostEqual(_num_after(line, "seen through"), 0.52, places=2)
        self.assertIn("= 0.54 % of the 10.0000 m commanded", line)
        self.assertIn("is NOT a dodge measurement", line)

    def test_the_commanded_vector_is_the_tick_991_latch(self):
        line = _one(self.notes, "commanded 10.0000 m")
        self.assertIn("from the tick-991 latch", line)
        self.assertIn("setpoint (4.9974, 21.5161, 15.0000)", line)
        self.assertIn("minus the tick-991 position (14.9969, 21.6070, 15.0300)", line)
        self.assertIn("commanded axis (E -1.0000, N -0.0091)", line)
        self.assertIn("2 re-latch(es) inside the window", line)

    def test_the_raw_vector_and_the_3d_straight_line(self):
        """3.95 m of it is the vehicle continuing down its lane. Printing the 3D number without the
        raw vector beside it would read as a 4 m dodge."""
        line = _one(self.notes, "achieved 3D straight line")
        self.assertIn("achieved 3D straight line 3.9519 m", line)
        self.assertIn("raw delta-ENU (-0.0182, -3.9518, -0.0200) m", line)

    def test_the_two_second_tail(self):
        """'0.054 m over the following 2 s' (DECISIONS.md) -- the cross-course term again, measured
        from the same takeover position out to the last tick within 2.0 s of the resume."""
        line = _one(self.notes, "+2.0 s past resume")
        self.assertIn("(ticks 991 -> 1012, 2.372 s from takeover, AUTO for the tail)", line)
        self.assertAlmostEqual(_num_after(line, "cross-course"), 0.0545, places=4)
        self.assertAlmostEqual(_num_after(line, "on the commanded axis"), 0.2005, places=4)
        self.assertAlmostEqual(_num_after(line, "3D straight line"), 16.0751, places=4)

    def test_the_settle_tick_really_is_inside_two_seconds(self):
        stamps = self.log["run"]["tick_stamp_sim_s"]
        self.assertLessEqual(stamps[1012 - 1] - stamps[995 - 1], checker.DISPLACEMENT_SETTLE_S)
        self.assertGreater(stamps[1013 - 1] - stamps[995 - 1], checker.DISPLACEMENT_SETTLE_S)

    def test_the_numbers_survive_the_whole_gate(self):
        """The block reaches the operator, not just the unit test -- and on a log whose verdict is
        INVALID, where messages go to stderr."""
        buf_out, buf_err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf_out), redirect_stderr(buf_err):
            code = checker.main([str(TAKE_20260825)])
        self.assertEqual(code, 1)                      # the pre-registered breach still fails
        blob = buf_out.getvalue() + buf_err.getvalue()
        self.assertIn("achieved displacement, encounter 1", blob)
        self.assertIn("cross-course dodge +0.0182 m", blob)


class TestTheLegacyTakes(unittest.TestCase):
    """2026-08-18 and 2026-08-23 carry no `run` block, so they have no time axis -- the same
    refusal `check_file` already makes for a booking's flown speed. The tick displacements are
    still facts, and they are the ones that put the along-command figure NEGATIVE."""

    def test_seconds_are_refused_and_ticks_are_not(self):
        for path in LEGACY_LOGS:
            with self.subTest(log=path.name):
                notes = checker.displacement_notes(_load(path))
                self.assertIn("n/a (no `run` block: this log has no time axis)", _one(notes, HEAD))
                self.assertIn("n/a -- no tick stamps", _one(notes, "+2.0 s past resume"))
                self.assertRegex(_one(notes, HEAD), r"ticks \d+ -> \d+ \(takeover -> resume\)")

    def test_the_historical_flights_flew_the_other_way(self):
        """ADR-016 am. 2: 'along-command the historical figures are -145 % / -218 % -- the vehicle
        went the OTHER way'. Reproduced by this note from the logs themselves."""
        pcts = []
        for path in LEGACY_LOGS:
            line = _one(checker.displacement_notes(_load(path)), "ON THE COMMANDED AXIS")
            pcts.append(_num_after(line, "="))
        self.assertAlmostEqual(pcts[0], -145.39, places=2)
        self.assertAlmostEqual(pcts[1], -217.97, places=2)


class TestItCanReadARealDodge(unittest.TestCase):
    """A metric that reports 0.018 m has to be shown capable of reporting 10 m, or the reading is
    indistinguishable from a broken measurement."""

    def _flown_dodge_log(self):
        """A vehicle cruising north at 5 m/s that is commanded 10 m EAST at tick 3 and flies it:
        2 m of east displacement per tick over the 5-tick GUIDED window, then holds."""
        path = [[0.0, float(n) * 1.0, 15.0] for n in range(3)]          # ticks 1-3, cruising
        for k in range(1, 6):                                           # ticks 4-8, the dodge
            path.append([2.0 * k, 2.0 + float(k), 15.0])
        path.extend([[10.0, 7.0 + float(k), 15.0] for k in range(1, 30)])
        stamps = [100.0 + 0.2 * i for i in range(len(path))]
        events = [
            {"seq": 1, "tick": 3, "kind": "takeover", "reason": "divert",
             "from_mode": "AUTO", "to_mode": "GUIDED"},
            {"seq": 2, "tick": 3, "kind": "latch", "setpoint_enu": [10.0, 2.0, 15.0]},
            {"seq": 3, "tick": 8, "kind": "resume", "trigger": "threat_cleared"},
        ]
        return {"flown_path_enu": path, "events": events,
                "run": {"schema_version": 2, "tick_stamp_sim_s": stamps}}

    def test_a_flown_dodge_reads_ten_metres(self):
        notes = checker.displacement_notes(self._flown_dodge_log())
        head, cmd = _one(notes, HEAD), _one(notes, "commanded 10.0000 m")
        self.assertIn("ticks 3 -> 8 (takeover -> resume)", head)
        self.assertIn("1.000 s sim (100.400 -> 101.400 s)", head)
        self.assertIn("commanded axis (E +1.0000, N +0.0000)", cmd)
        along = _one(notes, "ON THE COMMANDED AXIS")
        self.assertAlmostEqual(_num_after(along, "ON THE COMMANDED AXIS"), 10.0, places=4)
        self.assertIn("= 100.00 % of the 10.0000 m commanded", along)
        # The command is due east and the track due north, so the whole 10 m is cross-course dodge
        # and the cruise leak is zero -- the clean case the 2026-08-25 window is not.
        self.assertAlmostEqual(_num_after(along, "cross-course dodge"), 10.0, places=4)
        self.assertAlmostEqual(_num_after(along, "cruise leak"), 0.0, places=4)

    def test_a_vehicle_that_ignores_the_command_reads_zero(self):
        """Same command, same window, vehicle keeps cruising north: the metric must not credit the
        along-track travel to the dodge. This is the negative control for the test above."""
        log = self._flown_dodge_log()
        log["flown_path_enu"] = [[0.0, float(i) * 1.0, 15.0]
                                 for i in range(len(log["flown_path_enu"]))]
        along = _one(checker.displacement_notes(log), "ON THE COMMANDED AXIS")
        self.assertAlmostEqual(_num_after(along, "ON THE COMMANDED AXIS"), 0.0, places=4)
        self.assertAlmostEqual(_num_after(along, "cross-course dodge"), 0.0, places=4)


class TestItRefusesWhatItCannotMeasure(unittest.TestCase):

    def test_no_encounter_no_block(self):
        self.assertEqual(checker.displacement_notes(
            {"flown_path_enu": [[0.0, 0.0, 15.0]], "events": []}), [])

    def test_an_empty_path_says_nothing(self):
        self.assertEqual(checker.displacement_notes({"flown_path_enu": [], "events": []}), [])

    def test_a_window_with_no_setpoint_is_named_not_measured(self):
        log = {"flown_path_enu": [[0.0, 0.0, 15.0]] * 4,
               "events": [{"tick": 1, "kind": "takeover"}, {"tick": 3, "kind": "resume"}]}
        self.assertIn("NOT MEASURED", _one(checker.displacement_notes(log), HEAD))

    def test_a_purely_vertical_command_defines_no_axis(self):
        log = {"flown_path_enu": [[0.0, 0.0, 15.0]] * 4,
               "events": [{"tick": 1, "kind": "takeover"},
                          {"tick": 1, "kind": "latch", "setpoint_enu": [0.0, 0.0, 25.0]},
                          {"tick": 3, "kind": "resume"}]}
        self.assertIn("defines no horizontal axis", _one(checker.displacement_notes(log), HEAD))

    def test_a_parked_vehicle_gets_no_dodge_split_rather_than_a_wrong_one(self):
        """No entry course -> no track normal -> the dodge/leak split is undefined. It says so
        instead of dividing by a zero vector or quietly calling the leak zero."""
        log = {"flown_path_enu": [[0.0, 0.0, 15.0]] * 4,
               "events": [{"tick": 2, "kind": "takeover"},
                          {"tick": 2, "kind": "latch", "setpoint_enu": [10.0, 0.0, 15.0]},
                          {"tick": 4, "kind": "resume"}]}
        line = _one(checker.displacement_notes(log), "ON THE COMMANDED AXIS")
        self.assertIn("no entry course", line)
        self.assertNotIn("cross-course dodge", line)

    def test_the_entry_course_ignores_the_maneuver_it_is_measuring(self):
        """`_entry_course_unit` looks strictly BACKWARD, unlike `_course_unit` which straddles the
        tick. A bracket that reached forward would mix the response into its own baseline."""
        log = {"flown_path_enu": [[0.0, 0.0, 15.0], [0.0, 5.0, 15.0], [9.0, 5.0, 15.0]]}
        self.assertEqual(checker._entry_course_unit(log, 2), (0.0, 1.0))       # arriving: north
        self.assertNotEqual(checker._course_unit(log, 2), (0.0, 1.0))          # straddling: not

    def test_the_entry_course_walks_back_past_repeated_poses(self):
        log = {"flown_path_enu": [[0.0, 0.0, 15.0], [0.0, 5.0, 15.0],
                                  [0.0, 5.0, 15.0], [0.0, 5.0, 15.0]]}
        self.assertEqual(checker._entry_course_unit(log, 4), (0.0, 1.0))


class TestTheNoteChangesNothing(unittest.TestCase):
    """REPORTED, NOT GATED -- proven by running every committed log twice, once with the note
    suppressed, and comparing the verdict, the exit code and every other message."""

    def _without_notes(self, path):
        with mock.patch.object(checker, "displacement_notes", lambda log: []):
            return checker.check_file(path)

    def test_every_committed_log_keeps_its_verdict_and_its_other_messages(self):
        for path in (TAKE_20260825,) + LEGACY_LOGS:
            with self.subTest(log=path.name):
                if not path.exists():
                    raise unittest.SkipTest(f"{path.name} absent")
                status_with, msgs_with = checker.check_file(path)
                status_without, msgs_without = self._without_notes(path)
                self.assertEqual(status_with, status_without)
                kept = [m for m in msgs_with
                        if not (m.startswith(HEAD) or m.startswith("  "))]
                self.assertEqual(kept, msgs_without)
                self.assertGreater(len(msgs_with), len(msgs_without))   # the block really ran

    def test_the_exit_codes_are_the_ones_the_repo_publishes(self):
        """Two ACKNOWLEDGED breaches (exit 0) and one INVALID (exit 1). If a note could move one of
        these, the honesty artifacts on the front page would be reporting this tool, not the
        flights."""
        expected = {TAKE_20260825: 1, LEGACY_LOGS[0]: 0, LEGACY_LOGS[1]: 0}
        for path, want in expected.items():
            with self.subTest(log=path.name):
                if not path.exists():
                    raise unittest.SkipTest(f"{path.name} absent")
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(checker.main([str(path)]), want)

    def test_a_dodge_that_did_nothing_is_still_VALID(self):
        """The block is appended to `notes`, which print before problems and never enter the
        INVALID decision. Here is the case that proves it is not a gate: a flight whose commanded
        10 m dodge displaced the aircraft by ZERO comes back VALID, with the zero printed. If a
        future session wants that to fail, it has to say so in a gate and a decision record.

        Flown on the legacy path (a pinned pre-seam stem in a tmp dir) so the fixture needs no
        clock, detector or truth track -- none of which this property depends on."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        src = _load(TAKE_20260825)
        log = {"flown_path_enu": [[0.0, float(i), 15.0] for i in range(6)],
               "coverage_ledger": src["coverage_ledger"],
               "events": [{"tick": 2, "kind": "takeover"},
                          {"tick": 2, "kind": "latch", "setpoint_enu": [10.0, 1.0, 15.0]},
                          {"tick": 5, "kind": "resume"}]}
        p = Path(tmp.name) / f"{checker.PRE_SEAM_LEGACY_STEMS[0]}.json"
        p.write_text(json.dumps(log))
        status, messages = checker.check_file(p, results_dir=Path(tmp.name))
        self.assertEqual(status, checker.VALID, " | ".join(messages))
        self.assertTrue(any(m.startswith(HEAD) for m in messages))
        line = _one(messages, "ON THE COMMANDED AXIS")
        self.assertAlmostEqual(_num_after(line, "ON THE COMMANDED AXIS"), 0.0, places=4)
        self.assertAlmostEqual(_num_after(line, "cross-course dodge"), 0.0, places=4)


class TestTheArithmeticItself(unittest.TestCase):
    """The split is an identity, not an approximation: along = dodge + leak, exactly."""

    def test_the_decomposition_closes(self):
        for cmd_deg in range(0, 360, 7):
            for course_deg in range(0, 360, 11):
                u = (math.cos(math.radians(cmd_deg)), math.sin(math.radians(cmd_deg)))
                c = (math.cos(math.radians(course_deg)), math.sin(math.radians(course_deg)))
                split = checker._displacement_split((1.0, 2.0, 3.0), (4.5, -2.0, 3.5), u, c)
                self.assertAlmostEqual(split["along"], split["cross"] + split["leak"], places=9)

    def test_the_3d_length_is_the_raw_vector(self):
        split = checker._displacement_split((0.0, 0.0, 0.0), (3.0, 4.0, 12.0), (1.0, 0.0), (0.0, 1.0))
        self.assertAlmostEqual(split["d3"], 13.0)
        self.assertEqual(split["d"], (3.0, 4.0, 12.0))


if __name__ == "__main__":
    unittest.main()
