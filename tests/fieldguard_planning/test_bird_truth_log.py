"""The bird applied-pose log AS FLIGHT GROUND TRUTH — scripts/drive_birds.py.

`tests/fieldguard_planning/test_drive_birds.py` pins the trajectory interpolation and the record
shape. THIS file pins the thing a safety gate leans on: that the log says where the birds ACTUALLY
were, on the Gazebo sim clock, and that the driver loop which writes it can be exercised — end to
end, `main()` included — with no Gazebo anywhere.

Why it matters: `scripts/check_live_flight_log.py --truth <log>` measures closest approach against
this file instead of against the drone's own logged detections, because a monocular apparent-size
range cannot referee its own safety margin (3.27 m estimated vs 3.92 m true, measured) and a MISS at
closest approach would otherwise score as no-evidence-of-a-breach. Two historical flights breached
bird clearance by ~5 cm under green gates; the margin now comes from here, so "here" has to be
right and has to be honest about what it does not know.

Three properties, in order of how badly a bug would hurt:
  1. CONTAINMENT — the sim bracket a pose is reconstructed into must CONTAIN the instant Gazebo
     actually applied it, for every plausible position of the two unobservable instants (when the
     /clock reading was true, when the service applied the pose).
  2. HONESTY — a failed set_pose means the bird HELD; commanded intent must never reach the truth
     track. Uncertainty widens the bracket, it never narrows it.
  3. REPRODUCIBILITY — the committed schema-1.0 log that ADR-003 amendment 7's labels were derived
     from must reconstruct bit-identically forever.

Stdlib unittest, bare python, no numpy, no Gazebo.
"""
import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

import drive_birds as db  # noqa: E402
from drive_birds import (  # noqa: E402
    APPLIED_LOG_SCHEMA_VERSION, AppliedLogWriter, applied_log_path_for, applied_record,
    applied_sim_brackets, applied_sim_span, drive_tick, pose_at, read_applied_log,
)
import annotate_real_clip as arc  # noqa: E402

# The ADOPT decision's own bird ground truth (ADR-003 am. 7, flight 2026-08-23T07:38:36Z).
COMMITTED_LOG = REPO_ROOT / "eval" / "results" / "bird_drive_20260823T073836Z_applied.jsonl"

BIRDS = [
    {"bird_id": "bird_0", "physical_radius_m": 0.18, "loop": True, "waypoints": [
        {"t_s": 0.0, "x_m": 0.0, "y_m": 0.0, "z_m": 11.0, "yaw_deg": 0.0},
        {"t_s": 10.0, "x_m": 20.0, "y_m": 0.0, "z_m": 11.0, "yaw_deg": 90.0}]},
    {"bird_id": "bird_1", "physical_radius_m": 0.18, "loop": True, "waypoints": [
        {"t_s": 0.0, "x_m": 5.0, "y_m": 30.0, "z_m": 8.0, "yaw_deg": 0.0},
        {"t_s": 10.0, "x_m": 45.0, "y_m": 30.0, "z_m": 8.0, "yaw_deg": 0.0}]},
    {"bird_id": "bird_2", "physical_radius_m": 0.18, "loop": True, "waypoints": [
        {"t_s": 0.0, "x_m": 10.0, "y_m": 10.0, "z_m": 6.0, "yaw_deg": 36.0},
        {"t_s": 10.0, "x_m": 10.0, "y_m": 40.0, "z_m": 6.0, "yaw_deg": 36.0}]},
]


class FakeGazebo:
    """The one collaborator this driver cannot have offline: a simulator with its own clock, whose
    /clock reply and whose set_pose both take real wall time and land at instants nothing records.

    `read_frac` / `apply_frac` are where inside those two round-trips the truth happens (0 = at the
    request, 1 = at the reply). Nothing outside this class may know them — that is exactly the
    knowledge the real driver does not have, and the reconstruction has to be right without it."""

    def __init__(self, rtf=0.5, sim0=100.0, poll_s=0.04, call_s=0.2, read_frac=1.0,
                 apply_frac=0.5, fail_calls=(), stop_after=None):
        self.wall0 = 1000.0
        self.wall = self.wall0
        self.sim0 = sim0
        self.rtf = rtf
        self.poll_s = poll_s
        self.call_s = call_s
        self.read_frac = read_frac
        self.apply_frac = apply_frac
        self.fail_calls = set(fail_calls)      # 0-based indices of set_pose calls that fail
        self.stop_after = stop_after           # raise KeyboardInterrupt before this call index
        self.n_calls = 0
        self.applied = []                      # (bird_id, true_sim_s, pose) -- ground truth itself

    def sim_at(self, wall_s):
        return self.sim0 + (wall_s - self.wall0) * self.rtf

    def now(self):
        return self.wall

    def clock_poll(self, timeout_s=3.0):
        """Stands in for gz_sim_now_s(): a subprocess whose reading was true partway through."""
        reading = self.sim_at(self.wall + self.poll_s * self.read_frac)
        self.wall += self.poll_s
        return round(reading, 3)               # gz prints sec+nsec; the driver never sees more

    def set_pose(self, bird_id, pose):
        if self.stop_after is not None and self.n_calls >= self.stop_after:
            raise KeyboardInterrupt                       # how a real run ends: Ctrl-C
        idx = self.n_calls
        self.n_calls += 1
        ok = idx not in self.fail_calls
        if ok:
            self.applied.append((bird_id, self.sim_at(self.wall + self.call_s * self.apply_frac),
                                 tuple(pose)))
        self.wall += self.call_s
        return ok

    def truth_at(self, bird_id, sim_s):
        """What the RENDER was showing for `bird_id` at `sim_s` — the answer the log has to
        reproduce. None before this bird's first landed call (it is at its spawn pose then)."""
        shown = None
        for name, applied_sim, pose in self.applied:
            if name == bird_id and applied_sim <= sim_s:
                shown = pose
        return shown


class FakeTime:
    """`drive_birds.time`, wired to the fake simulator's wall clock. Only monotonic/sleep are
    faked; the sidecar's UTC naming still comes from the real clock."""

    def __init__(self, fake):
        self._fake = fake

    def monotonic(self):
        return self._fake.wall

    def sleep(self, seconds):
        self._fake.wall += max(0.0, seconds)

    def strftime(self, *a, **kw):
        return time.strftime(*a, **kw)

    def gmtime(self, *a, **kw):
        return time.gmtime(*a, **kw)


def run_ticks(fake, birds, log, n_ticks, t0_sim):
    """The driver's tick, wired exactly as `main` wires it (anchor before the poll, clock_wall
    after). `test_main_writes_a_truth_track_with_no_gazebo_anywhere` proves main really does."""
    for _ in range(n_ticks):
        tick_begin = fake.now()
        tick_sim = fake.clock_poll()
        clock_wall = fake.now()
        drive_tick(birds, tick_sim - t0_sim, fake.set_pose, log, tick_sim_s=tick_sim,
                   tick_wall_s=tick_begin, clock_wall_s=clock_wall, now=fake.now)


class CollectingLog:
    """AppliedLogWriter's interface, in memory — the record stream without the file."""

    def __init__(self):
        self.records = []

    def write(self, record):
        self.records.append(record)


class TestDriveTick(unittest.TestCase):
    """The loop that writes the ground truth, with the simulator injected. If this needs Gazebo,
    the only test of the file a safety gate reads is a live one nobody re-runs."""

    def test_one_record_per_bird_per_tick_in_call_order(self):
        fake = FakeGazebo()
        log = CollectingLog()
        run_ticks(fake, BIRDS, log, 2, t0_sim=100.0)
        self.assertEqual([r["bird_id"] for r in log.records],
                         ["bird_0", "bird_1", "bird_2"] * 2)
        for r in log.records:
            self.assertEqual(r["ok"], True)
        # ...and every position is the shared interpolation, not a second copy of it
        for r in log.records:
            bird = next(b for b in BIRDS if b["bird_id"] == r["bird_id"])
            x, y, z, yaw = pose_at(r["t_traj_s"], bird["waypoints"], True)
            self.assertEqual(r["pos_m"], [round(x, 6), round(y, 6), round(z, 6)])
            self.assertEqual(r["yaw_rad"], round(yaw, 6))

    def test_the_three_birds_of_one_tick_share_an_anchor_but_not_a_bracket(self):
        """Measured on the flagship take: the three lagged 0.12 / 0.38 / 0.42 s by their position
        in this loop, so one shared tick anchor cannot place them."""
        fake = FakeGazebo()
        log = CollectingLog()
        run_ticks(fake, BIRDS, log, 1, t0_sim=100.0)
        anchors = {(r["tick_sim_s"], r["tick_wall_s"], r["clock_wall_s"]) for r in log.records}
        self.assertEqual(len(anchors), 1)
        starts = [r["wall_start_s"] for r in log.records]
        self.assertEqual(starts, sorted(starts))
        self.assertEqual(len(set(starts)), 3)
        for r in log.records:                      # each call brackets its own round-trip
            self.assertLess(r["wall_start_s"], r["wall_end_s"])

    def test_a_failed_call_is_recorded_and_the_rest_of_the_tick_still_flies(self):
        """`ok=False` is the record that keeps a label honest: the bird HELD. Dropping the record
        (or the tick) would make a held bird look like a moving one."""
        fake = FakeGazebo(fail_calls=(1,))
        log = CollectingLog()
        run_ticks(fake, BIRDS, log, 1, t0_sim=100.0)
        self.assertEqual([r["ok"] for r in log.records], [True, False, True])
        self.assertEqual(len(fake.applied), 2)

    def test_returns_the_two_counts_the_heartbeat_reports(self):
        fake = FakeGazebo(fail_calls=(0, 2))
        n_ok, n_failed = drive_tick(BIRDS, 1.0, fake.set_pose, None, tick_sim_s=101.0,
                                    tick_wall_s=1000.0, clock_wall_s=1000.04, now=fake.now)
        self.assertEqual((n_ok, n_failed), (1, 2))

    def test_no_log_is_a_valid_configuration_and_still_flies_the_birds(self):
        fake = FakeGazebo()
        drive_tick(BIRDS, 0.0, fake.set_pose, None, tick_sim_s=100.0, tick_wall_s=1000.0,
                   clock_wall_s=1000.04, now=fake.now)
        self.assertEqual(len(fake.applied), 3)

    def test_the_tick_never_reaches_for_gazebo_itself(self):
        """The injection is the point, so pin it: with both gz entry points booby-trapped the tick
        still completes. A future refactor that calls `gz_set_pose` directly fails here rather
        than the next time somebody books a Docker session."""
        def explode(*a, **kw):
            raise AssertionError("drive_tick reached for the real Gazebo CLI")

        fake = FakeGazebo()
        with unittest.mock.patch.object(db, "gz_set_pose", explode), \
                unittest.mock.patch.object(db, "gz_sim_now_s", explode), \
                unittest.mock.patch.object(db.subprocess, "run", explode):
            n_ok, _ = drive_tick(BIRDS, 0.0, fake.set_pose, CollectingLog(), tick_sim_s=100.0,
                                 tick_wall_s=1000.0, clock_wall_s=1000.04, now=fake.now)
        self.assertEqual(n_ok, 3)

    def test_a_wall_clock_run_records_no_clock_anchor_at_all(self):
        """No /clock reading means no sim anchor and no interval around one -- the field is absent,
        not zero, so a consumer cannot mistake 'unmeasured' for 'measured as instantaneous'."""
        fake = FakeGazebo()
        log = CollectingLog()
        drive_tick(BIRDS, 0.0, fake.set_pose, log, tick_sim_s=None, tick_wall_s=1000.0,
                   clock_wall_s=None, now=fake.now)
        for r in log.records:
            self.assertIsNone(r["tick_sim_s"])
            self.assertNotIn("clock_wall_s", r)
        self.assertEqual(applied_sim_brackets(log.records), [None, None, None])
        self.assertIsNone(applied_sim_span(log.records))


class TestTheClockAnchorIsMeasuredNotAssumed(unittest.TestCase):
    """`tick_sim_s` is read by a subprocess (39 ms median, 146 ms max on the 2026-08-23 take), so
    the instant it was true is an interval. Schema 1.1 records that interval instead of collapsing
    it onto the tick's start, which was a claim of precision the driver never had."""

    def test_schema_version_says_so(self):
        self.assertEqual(APPLIED_LOG_SCHEMA_VERSION, "1.1")

    def test_the_widening_is_exactly_the_measured_poll_interval(self):
        # rtf 0.5 measured between two readings 1.0 s of wall apart; the poll cost 0.04 s of wall.
        recs = [
            applied_record("b", 0.0, (0, 0, 0, 0), True, 100.0, 0.0, 0.10, 0.30, clock_wall_s=0.04),
            applied_record("b", 0.5, (1, 0, 0, 0), True, 100.5, 1.0, 1.10, 1.30, clock_wall_s=1.04),
        ]
        (s0, e0), (s1, e1) = applied_sim_brackets(recs)
        self.assertAlmostEqual(s0, 100.0 + (0.10 - 0.04) * 0.5)   # latest possible anchor
        self.assertAlmostEqual(e0, 100.0 + (0.30 - 0.00) * 0.5)   # earliest possible anchor
        self.assertAlmostEqual(s1, 100.5 + 0.03)                  # last tick reuses the rate
        self.assertAlmostEqual(e1, 100.5 + 0.15)
        # ...and it only ever widens: the start moved earlier, the end did not move.
        no_anchor = [dict(r) for r in recs]
        for r in no_anchor:
            r.pop("clock_wall_s")
        (os0, oe0), _ = applied_sim_brackets(no_anchor)
        self.assertLess(s0, os0)
        self.assertAlmostEqual(e0, oe0)

    def test_a_schema_1_0_record_keeps_the_old_zero_width_anchor_exactly(self):
        """Every committed label and every historical verdict was derived through the old formula;
        adding a field must not silently re-date them."""
        old = [
            applied_record("b", 0.0, (0, 0, 0, 0), True, 100.0, 0.0, 0.1, 0.3),
            applied_record("b", 0.5, (1, 0, 0, 0), True, 100.5, 1.0, 1.1, 1.3),
        ]
        self.assertEqual(applied_sim_brackets(old),
                         [(100.05, 100.15), (100.55, 100.65)])

    def test_the_rate_is_measured_between_the_two_readings_not_the_two_tick_starts(self):
        """A poll that takes 0.5 s on one tick and none on the next would bias a tick-start
        anchored rate by 50 %; anchoring on the readings themselves compares like with like."""
        recs = [
            applied_record("b", 0.0, (0, 0, 0, 0), True, 100.0, 0.0, 0.6, 0.7, clock_wall_s=0.5),
            applied_record("b", 1.0, (1, 0, 0, 0), True, 101.0, 1.4, 1.5, 1.6, clock_wall_s=1.5),
        ]
        (s0, _e0), _ = applied_sim_brackets(recs)
        rtf = 1.0 / (1.5 - 0.5)                        # readings 1.0 s of wall apart, not 1.4
        self.assertAlmostEqual(s0, 100.0 + (0.6 - 0.5) * rtf)


class TestTheBracketContainsTheTruth(unittest.TestCase):
    """THE property. Two instants are unobservable — when the /clock reading was true, and when
    Gazebo applied the pose — so the reconstruction is only honest if it is right for every
    position they could occupy inside their round-trips."""

    def _records(self, **kw):
        fake = FakeGazebo(**kw)
        log = CollectingLog()
        run_ticks(fake, BIRDS, log, 4, t0_sim=100.0)
        return fake, log.records

    def test_every_landed_pose_lands_inside_its_reconstructed_bracket(self):
        for read_frac in (0.0, 0.5, 1.0):
            for apply_frac in (0.0, 0.5, 1.0):
                with self.subTest(read_frac=read_frac, apply_frac=apply_frac):
                    fake, recs = self._records(read_frac=read_frac, apply_frac=apply_frac)
                    brackets = applied_sim_brackets(recs)
                    landed = [(r, b) for r, b in zip(recs, brackets) if r["ok"]]
                    self.assertEqual(len(landed), len(fake.applied))
                    for (r, (lo, hi)), (bird_id, true_sim, _pose) in zip(landed, fake.applied):
                        self.assertEqual(r["bird_id"], bird_id)
                        self.assertLessEqual(lo, true_sim + 1e-9)
                        self.assertGreaterEqual(hi, true_sim - 1e-9)

    def test_the_old_zero_width_anchor_could_place_the_bracket_after_the_pose_had_landed(self):
        """Why the field earns its keep, on identical data: with the reading true at the END of the
        poll and the pose applied at the START of its call, the schema-1.0 bracket begins after the
        bird has already moved -- so a frame in the gap is labelled at the bird's OLD position with
        no ambiguity flag. That is a confident wrong answer, the failure mode this repo keeps
        finding behind green gates."""
        fake, recs = self._records(read_frac=1.0, apply_frac=0.05)
        stripped = [{k: v for k, v in r.items() if k != "clock_wall_s"} for r in recs]
        old = applied_sim_brackets(stripped)
        new = applied_sim_brackets(recs)
        truth = {(bird, i) for i, (bird, _s, _p) in enumerate(fake.applied)}
        self.assertTrue(truth)                       # guard: the fake really did apply poses
        misses = sum(1 for (lo, _hi), (_b, true_sim, _p) in zip(old, fake.applied)
                     if true_sim < lo - 1e-9)
        self.assertGreater(misses, 0)
        self.assertEqual(0, sum(1 for (lo, _hi), (_b, true_sim, _p) in zip(new, fake.applied)
                                if true_sim < lo - 1e-9))

    def test_the_reconstruction_answers_where_the_bird_actually_was(self):
        """End to end through the consumers a safety gate uses: log -> applied_timeline ->
        pose_from_applied, checked against what the fake simulator actually applied."""
        fake, recs = self._records(read_frac=0.5, apply_frac=0.5)
        timeline = arc.applied_timeline(recs)
        lo, hi = applied_sim_span(recs)
        stamp = lo + 0.6 * (hi - lo)
        for bird in BIRDS:
            got = arc.pose_from_applied(timeline[bird["bird_id"]], stamp)
            self.assertIsNotNone(got)
            pos, _t_traj, ambiguous = got
            truth = fake.truth_at(bird["bird_id"], stamp)
            if not ambiguous:
                self.assertEqual(tuple(round(c, 6) for c in truth[:3]), tuple(pos))


class TestCommandedIntentNeverBecomesTruth(unittest.TestCase):
    """The repo's honesty rule at this seam: what the driver ASKED for is not evidence. Only the
    calls Gazebo confirmed may reach a label or a clearance number."""

    def test_a_failed_call_holds_the_previous_APPLIED_pose_not_the_requested_one(self):
        fake = FakeGazebo(fail_calls=(3,))        # tick 1, bird_0
        log = CollectingLog()
        run_ticks(fake, BIRDS, log, 3, t0_sim=100.0)
        timeline = arc.applied_timeline(log.records)
        requested = [r for r in log.records if r["bird_id"] == "bird_0" and not r["ok"]]
        self.assertEqual(len(requested), 1)
        held, _t, _amb = arc.pose_from_applied(timeline["bird_0"],
                                               applied_sim_brackets(log.records)[3][1] + 1e-6)
        self.assertNotEqual(list(held), requested[0]["pos_m"])
        self.assertEqual([round(c, 6) for c in held],
                         [r for r in log.records
                          if r["bird_id"] == "bird_0" and r["ok"]][0]["pos_m"])

    def test_a_bird_the_driver_never_moved_has_no_truth_to_offer(self):
        """Not a zero, not a guess: nothing. The consumer falls back to the spawn pose, which is
        exact because the model is <static> until the first set_pose (ADR-012 amendment 1)."""
        fake = FakeGazebo(fail_calls=range(0, 60, 3))     # every bird_0 call fails
        log = CollectingLog()
        run_ticks(fake, BIRDS, log, 3, t0_sim=100.0)
        timeline = arc.applied_timeline(log.records)
        self.assertNotIn("bird_0", timeline)
        self.assertIsNone(arc.pose_from_applied(timeline.get("bird_0", ()), 200.0))
        spawn = pose_at(0.0, BIRDS[0]["waypoints"], True)
        self.assertEqual(spawn[:3], (0.0, 0.0, 11.0))

    def test_an_unconfirmed_call_is_written_down_rather_than_dropped(self):
        """The record of a failure is itself evidence: it separates 'the bird held' from 'the
        driver was not running', which are opposite diagnoses for a flight with no dodge in it."""
        fake = FakeGazebo(fail_calls=(0, 1, 2))
        log = CollectingLog()
        run_ticks(fake, BIRDS, log, 1, t0_sim=100.0)
        self.assertEqual(len(log.records), 3)
        self.assertEqual([r["ok"] for r in log.records], [False] * 3)
        self.assertIsNone(applied_sim_span(log.records))


class TestAppliedSimSpan(unittest.TestCase):
    """The association key: which take does this truth track belong to?"""

    def test_span_is_the_landed_window_and_matches_the_timeline_it_will_be_queried_from(self):
        fake = FakeGazebo()
        log = CollectingLog()
        run_ticks(fake, BIRDS, log, 5, t0_sim=100.0)
        lo, hi = applied_sim_span(log.records)
        entries = [e for v in arc.applied_timeline(log.records).values() for e in v]
        self.assertAlmostEqual(lo, min(e[0] for e in entries))
        self.assertAlmostEqual(hi, max(e[1] for e in entries))
        self.assertLess(lo, hi)

    def test_failed_calls_do_not_stretch_the_window_they_could_not_fill(self):
        fake = FakeGazebo(fail_calls=(0, 1, 2, 12, 13, 14))   # first and last tick all fail
        log = CollectingLog()
        run_ticks(fake, BIRDS, log, 5, t0_sim=100.0)
        lo, hi = applied_sim_span(log.records)
        landed = [b for r, b in zip(log.records, applied_sim_brackets(log.records)) if r["ok"]]
        self.assertAlmostEqual(lo, min(b[0] for b in landed))
        self.assertAlmostEqual(hi, max(b[1] for b in landed))
        self.assertGreater(lo, applied_sim_brackets(log.records)[0][0])

    def test_an_empty_or_unclocked_log_has_no_span(self):
        self.assertIsNone(applied_sim_span([]))


class TestMainWritesTheTruthTrack(unittest.TestCase):
    """A rehearsal of the real thing with the simulator swapped out: `main()`'s own loop, its own
    sidecar, its own file. This is what pins the ANCHOR WIRING -- that `tick_wall_s` is taken
    BEFORE the /clock poll and `clock_wall_s` after it. Wire those the other way round and every
    test above still passes while every flight's brackets are quietly wrong."""

    def _fly(self, td, fake, clock=None, argv_extra=()):
        cfg = Path(td) / "birds.json"
        cfg.write_text(json.dumps({"birds": BIRDS}))
        argv = ["--config", str(cfg), "--sidecar-dir", str(td), "--rate", "2",
                "--world", "farmguard_field", *argv_extra]
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.object(db, "time", FakeTime(fake)), \
                unittest.mock.patch.object(db, "gz_sim_now_s", clock or fake.clock_poll), \
                unittest.mock.patch.object(
                    db, "gz_set_pose", lambda world, name, pose: fake.set_pose(name, pose)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = db.main(argv)
        sidecars = sorted(Path(td).glob("bird_drive_*.json"))
        self.assertEqual(len(sidecars), 1)
        return rc, sidecars[0], out.getvalue(), err.getvalue()

    def test_main_writes_a_truth_track_with_no_gazebo_anywhere(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeGazebo(stop_after=9)            # 3 ticks, then Ctrl-C
            rc, sidecar, out, _err = self._fly(td, fake)
            self.assertEqual(rc, 0)
            side = json.loads(sidecar.read_text())
            self.assertEqual(side["clock"], "sim")
            self.assertEqual(side["applied_log_schema_version"], "1.1")
            self.assertEqual(side["bird_ids"], ["bird_0", "bird_1", "bird_2"])
            recs = read_applied_log(applied_log_path_for(sidecar))
            self.assertEqual(len(recs), 9)
            self.assertEqual(sum(r["ok"] for r in recs), 9)
            self.assertEqual(side["applied_log"], applied_log_path_for(sidecar).name)
            # Teardown hands the operator the window and the exact gate command: the post-flight
            # check has to be given the log that overlaps THIS flight, and every take's filename
            # looks alike.
            lo, hi = applied_sim_span(recs)
            self.assertIn(f"covers sim {lo:.1f}..{hi:.1f}s", out)
            self.assertIn(f"--truth {applied_log_path_for(sidecar)}", out)
            # t0 is the FIRST reading; the loop's own readings come after it
            self.assertAlmostEqual(side["t0_sim_s"],
                                   fake.sim0 + fake.poll_s * fake.read_frac * fake.rtf, places=6)
            self.assertTrue(all(r["tick_sim_s"] > side["t0_sim_s"] for r in recs))

    def test_the_anchor_wiring_brackets_the_poll_instead_of_assuming_it_was_free(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeGazebo(stop_after=6)
            _rc, sidecar, _out, _err = self._fly(td, fake)
            recs = read_applied_log(applied_log_path_for(sidecar))
            for r in recs:
                self.assertLess(r["tick_wall_s"], r["clock_wall_s"])           # the poll cost time
                self.assertAlmostEqual(r["clock_wall_s"] - r["tick_wall_s"], fake.poll_s, places=6)
                self.assertLessEqual(r["clock_wall_s"], r["wall_start_s"])     # ...before any call
                self.assertLess(r["wall_start_s"], r["wall_end_s"])

    def test_a_flight_rehearsed_this_way_reconstructs_to_what_the_simulator_applied(self):
        """The whole point, offline: drive -> log -> read -> timeline -> pose, checked against the
        fake's own record of what it applied. If this passes, the only thing the live take adds is
        a real renderer."""
        with tempfile.TemporaryDirectory() as td:
            fake = FakeGazebo(stop_after=15, read_frac=0.5, apply_frac=0.5)
            _rc, sidecar, _out, _err = self._fly(td, fake)
            recs = read_applied_log(applied_log_path_for(sidecar))
            brackets = applied_sim_brackets(recs)
            for (lo, hi), (_bird, true_sim, _pose) in zip(brackets, fake.applied):
                self.assertLessEqual(lo, true_sim + 1e-9)
                self.assertGreaterEqual(hi, true_sim - 1e-9)
            timeline = arc.applied_timeline(recs)
            self.assertEqual(sorted(timeline), ["bird_0", "bird_1", "bird_2"])
            for bird_id in timeline:
                stamp = timeline[bird_id][-1][1] + 1e-6     # just after the last landed call
                pos, _t, ambiguous = arc.pose_from_applied(timeline[bird_id], stamp)
                self.assertFalse(ambiguous)
                self.assertEqual(tuple(pos),
                                 tuple(round(c, 6) for c in fake.truth_at(bird_id, stamp)[:3]))

    def test_a_dead_clock_costs_the_tick_not_the_run(self):
        """A transient /clock hiccup must not kill a driver mid-flight, and must not fabricate a
        pose either: the tick is skipped, so nothing enters the truth track for it."""
        with tempfile.TemporaryDirectory() as td:
            fake = FakeGazebo(stop_after=6)
            polls = {"n": 0}

            def flaky(timeout_s=3.0):
                polls["n"] += 1
                if polls["n"] in (3, 4):        # 1 = t0, then two dead polls mid-run
                    fake.wall += fake.poll_s
                    return None
                return fake.clock_poll()

            _rc, sidecar, _out, _err = self._fly(td, fake, clock=flaky)
            recs = read_applied_log(applied_log_path_for(sidecar))
            self.assertEqual(len(recs), 6)                 # 2 ticks of 3, the dead ones skipped
            self.assertGreater(polls["n"], 4)

    def test_no_sidecar_means_no_truth_track_and_the_operator_is_told(self):
        with tempfile.TemporaryDirectory() as td:
            fake = FakeGazebo(stop_after=3)
            cfg = Path(td) / "birds.json"
            cfg.write_text(json.dumps({"birds": BIRDS}))
            out = io.StringIO()
            with unittest.mock.patch.object(db, "time", FakeTime(fake)), \
                    unittest.mock.patch.object(db, "gz_sim_now_s", fake.clock_poll), \
                    unittest.mock.patch.object(
                        db, "gz_set_pose", lambda w, n, p: fake.set_pose(n, p)), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                rc = db.main(["--config", str(cfg), "--sidecar-dir", str(td), "--no-sidecar"])
            self.assertEqual(rc, 0)
            self.assertEqual(sorted(Path(td).glob("bird_drive_*")), [])
            self.assertNotIn("applied-pose log ->", out.getvalue())


class TestTheCommittedTruthTrackStillReproduces(unittest.TestCase):
    """`eval/results/bird_drive_20260823T073836Z_applied.jsonl` is the bird ground truth ADR-003
    amendment 7's ADOPT verdict was measured against (per-bird FNR 0.000 on applied-pose labels).
    Its reconstruction has to be frozen: change the bracket math and every one of those labels
    moves, retroactively, with no flight to re-run."""

    def setUp(self):
        self.assertTrue(COMMITTED_LOG.exists(),
                        f"{COMMITTED_LOG} is missing. It is the ADR-003 am. 7 verdict's bird "
                        f"ground truth (committed by a .gitignore exception); without it those "
                        f"labels can never be re-verified.")
        self.recs = read_applied_log(COMMITTED_LOG)

    def test_it_is_a_schema_1_0_log_and_takes_the_unchanged_path(self):
        self.assertEqual(len(self.recs), 860)
        self.assertEqual(sum(r["ok"] for r in self.recs), 839)
        self.assertFalse(any("clock_wall_s" in r for r in self.recs))
        self.assertEqual(sorted({r["bird_id"] for r in self.recs}),
                         ["bird_0", "bird_1", "bird_2"])

    def test_its_brackets_and_span_are_unchanged(self):
        brackets = applied_sim_brackets(self.recs)
        self.assertEqual(len(brackets), 860)
        self.assertAlmostEqual(brackets[0][0], 110.40831274893256, places=9)
        self.assertAlmostEqual(brackets[0][1], 110.54670624759109, places=9)
        self.assertAlmostEqual(brackets[-1][0], 263.7027777946321, places=9)
        self.assertAlmostEqual(brackets[-1][1], 263.84153428712915, places=9)
        lo, hi = applied_sim_span(self.recs)
        self.assertAlmostEqual(lo, 110.40831274893256, places=9)
        self.assertAlmostEqual(hi, 263.84153428712915, places=9)

    def test_the_take_it_belongs_to_is_identifiable_by_that_span(self):
        """How `check_live_flight_log.py --truth` associates a truth track with a flight: overlap
        between this span and the flight's own tick stamps. This take covers sim 110-264 s, so a
        flight whose ticks sit there is a candidate and one starting from a fresh sim clock is not
        -- necessary, not sufficient, because sim time restarts near 0 every run."""
        lo, hi = applied_sim_span(self.recs)
        self.assertLessEqual(lo, 150.0)
        self.assertGreaterEqual(hi, 200.0)
        self.assertGreater(lo, 100.0)                 # a fresh run's early ticks do not overlap

    def test_a_known_pose_replays_from_the_file(self):
        """One hand-checkable line: bird_0's first landed call, replayed through the same reader
        the labels and the safety gate use."""
        timeline = arc.applied_timeline(self.recs)
        first_end = timeline["bird_0"][0][1]
        pos, t_traj, _amb = arc.pose_from_applied(timeline["bird_0"], first_end)
        self.assertEqual(list(pos), [15.0, 5.264106, 11.0])
        self.assertAlmostEqual(t_traj, 0.044)


class TestTheLogSurvivesTheWayFlightsEnd(unittest.TestCase):
    """Flights end by Ctrl-C, by pkill, and by full disks. The truth track has to survive all
    three, because it cannot be recreated without re-flying."""

    def test_records_are_readable_before_close(self):
        with tempfile.TemporaryDirectory() as td:
            writer = AppliedLogWriter(Path(td) / "bird_drive_x_applied.jsonl")
            fake = FakeGazebo()
            run_ticks(fake, BIRDS, writer, 2, t0_sim=100.0)
            self.assertEqual(len(read_applied_log(writer.path)), 6)   # no close() called
            writer.close()

    def test_a_disabled_writer_costs_the_evidence_not_the_flight(self):
        with tempfile.TemporaryDirectory() as td:
            writer = AppliedLogWriter(Path(td) / "nope" / "deeper" / "log.jsonl")
            fake = FakeGazebo()
            with contextlib.redirect_stderr(io.StringIO()) as err:
                run_ticks(fake, BIRDS, writer, 2, t0_sim=100.0)
            self.assertEqual(writer.written, 0)
            self.assertEqual(len(fake.applied), 6)                    # the birds still flew
            self.assertIn("applied-pose log disabled", err.getvalue())


if __name__ == "__main__":
    unittest.main()
