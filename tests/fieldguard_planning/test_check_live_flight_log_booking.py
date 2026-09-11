"""Tests for the BOOKING gate in scripts/check_live_flight_log.py -- was this take flown at the
speed it was AUTHORISED at? (QA finding G128, 2026-09-07)

THE FAILURE THIS FILE EXISTS FOR. `eval/results/booking_gate_20260907T064136Z.json` says PASS and
BOOKABLE at **5.0 m/s**, margin 1.780x. Nothing in the repo made the vehicle fly at 5.0: there is no
`param set WP_SPD` anywhere, `fly_pipeline.sh`'s fly recipe set no speed, and ArduCopter's
`WP_SPD` default flies 10 m/s -- the 2026-09-06 scripted test-flight peaked at 10.576 m/s, a
speed at which that same booking gate exits **1**. So the evidence gate could print a green
GT-CPA on a take that was never authorised. `test_the_headline_regression_ten_metres_per_second_
against_a_five_metre_booking` is that flight, synthesised, and it must come back INVALID.

SECOND FAILURE, found by QA on 2026-09-07 (G138) and pinned in `TestEncounterWindowSpeedGate` and
`TestTheCommittedTakeIsTheRegression`: the whole-flight median CANNOT see the failure it exists
for. On this repo's only real avoidance take it reads 3.417 m/s against a 5.0 m/s booking -- a pass
with 32 % to spare -- while the encounter itself (takeover 991 -> resume 995) was flown at a median
9.012 m/s = 1.80x booked, a speed at which the booking gate exits 1. The encounter window is where
the booking's lead margin is actually spent, so it is gated too, on the same bar.

The flown speed is measured from the log's OWN poses -- the same `flown_path_enu` +
`run.tick_stamp_sim_s` pair the ground-truth CPA already walks -- so nothing new has to be recorded
in the air, and no parameter that was supposed to be set can vouch for itself.

Fixtures are reused from `test_check_live_flight_log_schema2` rather than re-declared: one
definition of a valid schema-2 log, one definition of a truth track.

Run: python3 -m pytest tests/fieldguard_planning/test_check_live_flight_log_booking.py -q
"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "eval"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_live_flight_log as checker  # noqa: E402
import predict_forward_lead as pfl  # noqa: E402
import test_check_live_flight_log_schema2 as s2  # noqa: E402

# The live input set gate D1 measured on 2026-09-06 and the horizon gate D3 measured -- the numbers
# the committed booking artifact was written from. Used here to produce REAL bookable artifacts
# through the real tool, so no test ever hand-writes an authorisation.
D3_KW = dict(fx_px=520.0058046927554, fy_px=520.0058046927553, cx_px=320.0, cy_px=240.0,
             width_px=640.0, height_px=480.0, acq_range_m=46.0)
BOOKED_MPS = 5.0

TICK_DT_S = 0.2                 # 5 Hz, the node's control rate
FLIGHT_T0_S = 100.5             # inside s2.TRUTH_SIM's 100..103 s window
BIRD_XY = (50.0, 58.0)          # 8 m north of the flown line: well clear of the 3 m bar


def booking_artifact(path: Path, speed_mps: float = BOOKED_MPS, **over) -> Path:
    """A REAL booking-gate artifact for `speed_mps`, produced by the tool and validated by the same
    function the tool runs before it writes one. `over` mutates the report AFTER validation, for the
    tests that need a malformed or unauthorising one."""
    rep = pfl.evaluate(speed_mps, **D3_KW)
    pfl.validate_report(rep)
    for key, value in over.items():
        rep[key] = value
    Path(path).write_text(json.dumps(rep, indent=1) + "\n")
    return Path(path)


def flight_at(speed_mps: float, *, n_air: int = 6, n_park: int = 2,
              source: str = checker.DET_NDVI_BLOB, events=None, dt: float = TICK_DT_S) -> dict:
    """A structurally clean schema-2 log that flies straight east at `speed_mps`, after `n_park`
    ticks parked on the ground at z = 0 (every committed log opens with one -- the node logs from
    bringup and the human takes off at the MAVProxy prompt).

    Nothing here comes near a bird: the flown line is y = 50 and the only driven bird sits 8 m
    north of it, so the CPA gate passes and the booking gate is the only thing under test."""
    path, stamps = [], []
    t = FLIGHT_T0_S
    for _ in range(n_park):
        path.append([s2.DRONE_XY[0], s2.DRONE_XY[1], 0.0])
        stamps.append(round(t, 6))
        t += dt
    for k in range(n_air):
        path.append([s2.DRONE_XY[0] + speed_mps * dt * k, s2.DRONE_XY[1], s2.CRUISE_Z])
        stamps.append(round(t, 6))
        t += dt
    run = s2.make_run(detector_source=source, stamps=stamps, n_path=len(path))
    return s2.make_log(events=events, run=run, path=path)


class Harness(s2.Harness):
    """s2's tmp dir (flight-log home AND the `eval/results` truth auto-discovery reads), plus a
    truth track that answers for the whole flight window."""

    def truth(self):
        return self.write_truth(s2.truth_records(
            [(t, {"bird_0": (BIRD_XY[0], BIRD_XY[1], s2.CRUISE_Z)}) for t in s2.TRUTH_SIM]))

    def check(self, log, booking=None, name="live_flight_log_TEST.json", truth=None):
        p = self.write_log(log, name)
        return checker.check_file(p, truth=truth or self.truth(), results_dir=self.dir,
                                  booking=booking)

    def blob(self, result):
        return " ".join(result[1])


# ================================================================================================
# 1. The measurement itself -- a speed a flight really flew, with every denominator
# ================================================================================================
class TestAirborneGroundSpeed(unittest.TestCase):
    def test_the_parked_prologue_is_excluded_or_every_flight_clears_every_booking(self):
        """40-52 % of the ticks on two of the three committed logs are a parked vehicle. A median
        over ALL ticks is ~0 m/s, which passes any booking ever issued."""
        path = [[0.0, 0.0, 0.0]] * 8 + [[2.0 * k, 0.0, 15.0] for k in range(5)]
        stamps = [0.2 * i for i in range(len(path))]
        got = checker.airborne_ground_speed(path, stamps)
        self.assertEqual(got["airborne_ticks"], 5)
        self.assertEqual(got["ticks_total"], 13)
        self.assertEqual(got["steps_scored"], 4)          # 4 airborne steps, not 12
        self.assertAlmostEqual(got["median_mps"], 10.0, places=6)

    def test_the_takeoff_step_itself_is_not_a_speed(self):
        """A step from a parked tick to an airborne one spans a real displacement over a real
        time, so it produces a number -- and that number is a climb, not a mission speed. Both
        ends must be airborne."""
        path = [[0.0, 0.0, 0.0], [30.0, 0.0, 15.0], [31.0, 0.0, 15.0]]
        got = checker.airborne_ground_speed(path, [0.0, 0.2, 0.4])
        self.assertEqual(got["steps_scored"], 1)
        self.assertAlmostEqual(got["median_mps"], 5.0, places=6)     # not the 150 m/s straddler

    def test_it_is_HORIZONTAL_because_that_is_what_wpnav_speed_caps(self):
        path = [[0.0, 0.0, 15.0], [0.0, 0.0, 25.0], [0.0, 0.0, 35.0]]
        got = checker.airborne_ground_speed(path, [0.0, 1.0, 2.0])
        self.assertEqual(got["median_mps"], 0.0)

    def test_the_three_statistics_are_the_three_they_claim_to_be(self):
        speeds = [1.0, 2.0, 3.0, 4.0, 40.0]
        path, stamps, x = [[0.0, 0.0, 15.0]], [0.0], 0.0
        for i, v in enumerate(speeds):
            x += v
            path.append([x, 0.0, 15.0])
            stamps.append(float(i + 1))
        got = checker.airborne_ground_speed(path, stamps)
        self.assertEqual(got["steps_scored"], 5)
        self.assertAlmostEqual(got["median_mps"], 3.0, places=6)
        self.assertAlmostEqual(got["p90_mps"], 40.0, places=6)       # nearest rank: a real sample
        self.assertAlmostEqual(got["max_mps"], 40.0, places=6)

    def test_a_frozen_or_backwards_or_unstamped_pair_measures_no_speed(self):
        """dt <= 0 is not a slow step, it is no step. A frozen axis is `gate_clock`'s business and
        dividing by it here would print inf."""
        path = [[0.0, 0.0, 15.0], [5.0, 0.0, 15.0], [10.0, 0.0, 15.0], [15.0, 0.0, 15.0]]
        for stamps in ([0.0, 0.0, 0.0, 0.0], [0.0, -1.0, -2.0, -3.0], [None, None, None, None]):
            got = checker.airborne_ground_speed(path, stamps)
            self.assertEqual(got["steps_scored"], 0, msg=str(stamps))
            self.assertIsNone(got["median_mps"], msg=str(stamps))

    def test_nothing_scoreable_reports_None_not_zero(self):
        """'we could not measure it' and 'it flew slowly' are opposite claims and only one of them
        clears a booking."""
        got = checker.airborne_ground_speed([[0.0, 0.0, 0.0]] * 4, [0.0, 0.2, 0.4, 0.6])
        self.assertIsNone(got["median_mps"])
        self.assertIsNone(got["max_mps"])
        self.assertEqual(got["steps_total"], 3)          # the denominator survives

    def test_a_malformed_sample_is_skipped_rather_than_crashing_the_gate(self):
        path = [[0.0, 0.0, 15.0], "junk", [4.0, 0.0, 15.0], [6.0, 0.0, 15.0]]
        got = checker.airborne_ground_speed(path, [0.0, 1.0, 2.0, 3.0])
        self.assertEqual(got["steps_scored"], 1)
        self.assertAlmostEqual(got["median_mps"], 2.0, places=6)

    def test_the_airborne_threshold_is_THIS_PROJECTS_one_and_not_a_new_invention(self):
        """1.0 m is the `z_threshold_m` written into every clip's meta.airborne block, and the same
        number `build_dashboard_data` trims the replay with. Since 2026-09-10 the constant has ONE
        home, `fieldguard_planning.geom.AIRBORNE_Z_M` (stdlib-only, so this stdlib-only gate can
        import it where it could not import numpy-bound `clip_recorder`); the gate, the recorder and
        the dashboard builder all re-export THAT object. What this pins is that none of the three
        has quietly grown a copy again -- identity, not just equality."""
        from fieldguard_planning import geom
        from fieldguard_planning.clip_recorder import AIRBORNE_Z_M as RECORDER_Z
        import build_dashboard_data as dash
        self.assertEqual(checker.AIRBORNE_Z_M, RECORDER_Z)
        self.assertEqual(checker.AIRBORNE_Z_M, dash.AIRBORNE_Z_M)
        self.assertEqual(checker.AIRBORNE_Z_M, geom.AIRBORNE_Z_M)
        for module in (checker, dash):
            self.assertIs(module.AIRBORNE_Z_M, geom.AIRBORNE_Z_M)
        self.assertIs(RECORDER_Z, geom.AIRBORNE_Z_M)


# ================================================================================================
# 2. Reading a booking -- only an artifact that AUTHORISED something may be bound to a flight
# ================================================================================================
class TestLoadBooking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_a_real_bookable_artifact_loads_and_carries_its_speed(self):
        rep, problem = checker.load_booking(booking_artifact(self.dir / "b.json", 5.0))
        self.assertIsNone(problem)
        self.assertEqual(rep["encounter"]["mission_speed_mps"], 5.0)
        self.assertIs(rep["verdict"]["bookable"], True)

    def test_an_absent_file_is_a_reason_not_a_silent_skip(self):
        rep, problem = checker.load_booking(self.dir / "nope.json")
        self.assertIsNone(rep)
        self.assertIn("does not exist", problem)

    def test_unreadable_json_is_refused(self):
        p = self.dir / "b.json"
        p.write_text("{not json")
        rep, problem = checker.load_booking(p)
        self.assertIsNone(rep)
        self.assertIn("not valid JSON", problem)

    def test_it_is_read_with_the_TOOLS_OWN_validator_so_a_maimed_artifact_cannot_authorise(self):
        rep = pfl.evaluate(5.0, **D3_KW)
        del rep["sensor"]["clip_far_at_frame_corner_m"]
        p = self.dir / "b.json"
        p.write_text(json.dumps(rep))
        got, problem = checker.load_booking(p)
        self.assertIsNone(got)
        self.assertIn("validate_report", problem)

    def test_a_SWEEP_artifact_authorises_nothing_and_may_not_be_bound_to_a_take(self):
        """A sweep CHOOSES a mission speed; a single --speed run authorises one. Its top-level
        verdict carries bookable:false by construction, and binding it to a flight would claim an
        authorisation that was never issued."""
        out = self.dir / "sweep.json"
        subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "predict_forward_lead.py"),
                        "--sweep", "2:6:2", "--json", str(out)], capture_output=True, text=True)
        rep, problem = checker.load_booking(out)
        self.assertIsNone(rep)
        self.assertIn("does not AUTHORISE anything", problem)

    def test_a_config_sourced_design_check_is_not_an_authorisation_either(self):
        """Exit 3: the geometry works, the sensor is unmeasured. ADR-019 item 6's whole point."""
        rep = pfl.evaluate(5.0)                     # no live intrinsics, no --acq-range-m
        self.assertIs(rep["verdict"]["bookable"], False)
        p = self.dir / "design.json"
        p.write_text(json.dumps(rep))
        got, problem = checker.load_booking(p)
        self.assertIsNone(got)
        self.assertIn("does not AUTHORISE anything", problem)

    def test_the_LAUNCHERS_bringup_record_is_a_pointer_and_is_refused_by_name(self):
        """`fly_pipeline.sh --booking` writes eval/results/live_flight_booking_<UTC>.json at
        bringup: the artifact's path, the booked speed, the recipe line. It sits beside the flight
        logs and is the obvious thing to reach for on flight day -- and it carries none of the
        gate's checks, so reading it as an authorisation would let a two-field JSON book a flight.
        The refusal has to NAME the file it points at; `validate_report`'s 'missing top-level
        key(s)' is a dead end at the MAVProxy prompt."""
        p = self.dir / "live_flight_booking_20260907T120000Z.json"
        p.write_text(json.dumps({
            "schema_version": "1.1", "kind": "live_flight_booking",
            "booking": {"path": "eval/results/booking_gate_20260907T064136Z.json",
                        "booked_speed_mps": 5.0, "parameter": "WP_SPD"},
            "recipe_line": "param set WP_SPD 5.0"}))
        rep, problem = checker.load_booking(p)
        self.assertIsNone(rep)
        self.assertIn("LAUNCHER'S bringup record", problem)
        self.assertIn("booking_gate_20260907T064136Z.json", problem)

    def test_a_booking_with_no_usable_speed_has_nothing_to_hold_a_flight_to(self):
        p = booking_artifact(self.dir / "b.json", 5.0)
        rep = json.loads(p.read_text())
        rep["encounter"]["mission_speed_mps"] = None
        p.write_text(json.dumps(rep))
        got, problem = checker.load_booking(p)
        self.assertIsNone(got)
        self.assertIn("mission_speed_mps", problem)

    def test_the_lazy_import_works_from_a_COLD_interpreter_in_the_dangerous_order(self):
        """`predict_forward_lead` imports `max_bird_speed_m_s` from the gate at module scope, so
        the gate may only import it back from INSIDE a function. This runs the order that would
        break: gate first, tool never imported by the caller."""
        p = booking_artifact(self.dir / "b.json", 5.0)
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path[:0] = ['src', 'scripts', 'eval']\n"
             "import check_live_flight_log as c\n"
             f"rep, problem = c.load_booking(__import__('pathlib').Path({str(p)!r}))\n"
             "assert problem is None, problem\n"
             "print(rep['encounter']['mission_speed_mps'])\n"],
            capture_output=True, text=True, cwd=str(REPO_ROOT))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(proc.stdout.strip(), "5.0")


# ================================================================================================
# 3. The gate -- a take flown faster than it was booked is not the authorised take
# ================================================================================================
class TestBookedSpeedGate(Harness):
    def test_the_headline_regression_ten_metres_per_second_against_a_five_metre_booking(self):
        """ArduCopter's 10 m/s WP_SPD default against the committed 5.0 m/s authorisation. Before
        this gate existed the same log came back VALID with a green GT-CPA printed on it."""
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        status, messages = self.check(flight_at(10.0), booking=booking)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("FLOWN FASTER THAN BOOKED", blob)
        self.assertIn("2.000x", blob)                      # the ratio, said out loud
        self.assertIn("NOT THE AUTHORISED TAKE", blob)

    def test_the_same_flight_at_the_booked_speed_is_valid_and_prints_all_five_numbers(self):
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        status, messages = self.check(flight_at(5.0), booking=booking)
        blob = " ".join(messages)
        self.assertEqual(status, checker.VALID, blob)
        for needle in ("booked_speed_mps 5.000", "median 5.000", "p90 5.000", "max 5.000",
                       "ratio 1.000"):
            self.assertIn(needle, blob)

    def test_the_tolerance_is_a_named_ten_percent_on_the_MEDIAN_and_bites_just_past_it(self):
        """The waypoint speed is a CAP: transients cross it and a 5 Hz derivative has its own
        noise, so the median is the gated number and 10 % is the headroom. Tested either side of
        the 5.5 m/s bar rather than ON it -- a claim resting on a boundary is not a claim."""
        self.assertEqual(checker.BOOKED_SPEED_TOLERANCE, 1.10)
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        self.assertEqual(self.check(flight_at(5.49), booking=booking)[0], checker.VALID)
        status, messages = self.check(flight_at(5.51), booking=booking)
        self.assertEqual(status, checker.INVALID, " ".join(messages))
        self.assertIn("FLOWN FASTER THAN BOOKED", " ".join(messages))

    def test_a_transient_ABOVE_the_bar_does_not_fail_a_flight_whose_median_is_honest(self):
        """The p90 and the max are printed as context, deliberately not gated: one leg-entry
        overshoot must not fail a mission flown at its booked speed."""
        log = flight_at(5.0, n_air=9)
        log["flown_path_enu"][-1][0] += 4.0            # one 25 m/s step at the end
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        status, messages = self.check(log, booking=booking)
        blob = " ".join(messages)
        self.assertEqual(status, checker.VALID, blob)
        self.assertIn("max 25.000", blob)              # visible, not hidden
        self.assertIn("median 5.000", blob)
        # ...and the tail is NAMED, not left for the reader to spot in a number.
        self.assertIn("TAIL of that distribution is above the bar", blob)
        self.assertIn("max 25.000 m/s = 5.000x booked", blob)

    def test_a_distribution_entirely_under_the_bar_says_nothing_about_a_tail(self):
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        status, messages = self.check(flight_at(5.0), booking=booking)
        self.assertEqual(status, checker.VALID, " ".join(messages))
        self.assertNotIn("TAIL", " ".join(messages))

    def test_a_booking_bound_to_a_flight_whose_speed_cannot_be_measured_is_INVALID(self):
        """An unverifiable authorisation is not a verified one."""
        log = flight_at(5.0, n_air=0, n_park=6)        # never left the ground
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        status, messages = self.check(log, booking=booking)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("NOT MEASURABLE", blob)
        self.assertIn("unverifiable authorisation", blob)

    def test_an_unmeasurable_speed_with_NO_booking_is_context_not_a_failure(self):
        log = flight_at(5.0, n_air=0, n_park=6, source=checker.DET_NONE)
        status, messages = self.check(log)
        self.assertEqual(status, checker.VALID, " ".join(messages))
        self.assertIn("NOT MEASURABLE", " ".join(messages))

    def test_an_unusable_booking_fails_the_flight_rather_than_being_ignored(self):
        booking = self.dir / "booking_gate_X.json"
        booking.write_text("{}")
        status, messages = self.check(flight_at(5.0), booking=booking)
        self.assertEqual(status, checker.INVALID, " ".join(messages))
        self.assertIn("booking_gate_X.json", " ".join(messages))

    def test_a_speed_failure_is_NOT_acknowledgeable_by_a_safety_finding_marker(self):
        """A marker acknowledges a recorded CPA finding. 'This is not the flight that was booked'
        is not one, and the two halves of an acknowledgement must not be able to clear it."""
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        name = f"{checker.ACKNOWLEDGED_BREACH_STEMS[0]}.json"
        self.mark(name)
        status, messages = self.check(flight_at(10.0), booking=booking, name=name)
        self.assertEqual(status, checker.INVALID, " ".join(messages))
        self.assertIn("FLOWN FASTER THAN BOOKED", " ".join(messages))


# ================================================================================================
# 3b. THE ENCOUNTER WINDOW -- the speed the booking's lead margin is actually spent at (G138)
# ================================================================================================
def encounter_flight(cruise_mps: float, dash_mps: float, *, n_pre: int = 12, n_dash: int = 5,
                     n_post: int = 12, dt: float = TICK_DT_S) -> dict:
    """A mission flown at `cruise_mps` that sprints at `dash_mps` between a takeover and a resume.

    This is the SHAPE of the failure, not an invention: on a boustrophedon most airborne ticks are
    turnarounds and accel/decel, so the mission median sits well under the speed the legs are flown
    at -- and the bird arrives on a leg. The takeover/resume ticks are 1-based indices into
    `flown_path_enu`, the same relation `flown_path_enu[tick - 1]` the executor writes."""
    path, stamps, x, t = [], [], 0.0, FLIGHT_T0_S
    for _ in range(2):                                   # the parked prologue every real log opens
        path.append([s2.DRONE_XY[0], s2.DRONE_XY[1], 0.0])
        stamps.append(round(t, 6))
        t += dt
    speeds = [cruise_mps] * n_pre + [dash_mps] * n_dash + [cruise_mps] * n_post
    path.append([s2.DRONE_XY[0], s2.DRONE_XY[1], s2.CRUISE_Z])
    stamps.append(round(t, 6))
    t += dt
    for v in speeds:
        x += v * dt
        path.append([s2.DRONE_XY[0] + x, s2.DRONE_XY[1], s2.CRUISE_Z])
        stamps.append(round(t, 6))
        t += dt
    takeover = 3 + n_pre                                 # first tick of the dash
    resume = takeover + n_dash                           # the tick the dash ends on
    events = [{"kind": "takeover", "tick": takeover},
              {"kind": "resume", "tick": resume, "trigger": "threat_cleared"}]
    run = s2.make_run(stamps=stamps, n_path=len(path))
    return s2.make_log(events=events, run=run, path=path)


class TestEncounterWindows(unittest.TestCase):
    """The window bound comes out of the FLIGHT -- takeover to resume -- and never out of a +/-N
    tuning constant. A window nobody logged is a window somebody chose, and this one is gated."""

    def win(self, events, n_ticks=100):
        return checker.encounter_windows({"events": events}, n_ticks)

    def test_a_takeover_and_its_resume_are_one_inclusive_window(self):
        got = self.win([{"kind": "takeover", "tick": 991},
                        {"kind": "resume", "tick": 995, "trigger": "threat_cleared"}])
        self.assertEqual([(lo, hi) for lo, hi, _ in got], [(991, 995)])
        self.assertIn("takeover 991 -> resume 995", got[0][2])

    def test_two_encounters_are_two_windows(self):
        got = self.win([{"kind": "takeover", "tick": 10}, {"kind": "resume", "tick": 14},
                        {"kind": "takeover", "tick": 40}, {"kind": "resume", "tick": 44}])
        self.assertEqual([(lo, hi) for lo, hi, _ in got], [(10, 14), (40, 44)])

    def test_a_RELATCH_inside_an_open_encounter_does_not_open_a_second_window(self):
        """The executor re-latches inside an encounter that never closed. One encounter, one
        window, running from the FIRST takeover to the resume that ends it."""
        got = self.win([{"kind": "takeover", "tick": 10}, {"kind": "takeover", "tick": 12},
                        {"kind": "resume", "tick": 20}])
        self.assertEqual([(lo, hi) for lo, hi, _ in got], [(10, 20)])

    def test_an_UNCLOSED_takeover_runs_to_the_last_tick(self):
        """That log is already INVALID for the unclosed encounter, but the speed it flew into the
        dodge is still the honest thing to measure -- silence would be a free pass."""
        got = self.win([{"kind": "takeover", "tick": 30}], n_ticks=48)
        self.assertEqual([(lo, hi) for lo, hi, _ in got], [(30, 48)])
        self.assertIn("UNCLOSED", got[0][2])

    def test_a_resume_with_nothing_open_is_not_a_window(self):
        self.assertEqual(self.win([{"kind": "resume", "tick": 5}]), [])

    def test_a_take_with_no_encounter_has_no_window(self):
        self.assertEqual(self.win([{"kind": "detection", "tick": 5}]), [])

    def test_a_non_integer_or_boolean_tick_is_ignored_rather_than_crashing_the_gate(self):
        self.assertEqual(self.win([{"kind": "takeover", "tick": None},
                                   {"kind": "takeover", "tick": True},
                                   {"kind": "resume", "tick": "9"}]), [])


class TestWindowedGroundSpeed(unittest.TestCase):
    """`airborne_ground_speed(..., tick_range=...)` -- ONE speed function, two gated statistics."""

    def flight(self):
        # 1-based ticks 1..7; steps 1-2..6-7 at 1, 2, 3, 4, 5, 6 m/s over 1 s each.
        path = [[0.0, 0.0, 15.0]]
        for v in (1.0, 2.0, 3.0, 4.0, 5.0, 6.0):
            path.append([path[-1][0] + v, 0.0, 15.0])
        return path, [float(i) for i in range(len(path))]

    def test_a_range_keeps_only_steps_with_BOTH_ticks_inside_it(self):
        path, stamps = self.flight()
        got = checker.airborne_ground_speed(path, stamps, (3, 5))
        self.assertEqual(got["steps_scored"], 2)              # ticks 3-4 and 4-5 -> 3 and 4 m/s
        self.assertAlmostEqual(got["median_mps"], 3.5, places=6)
        self.assertEqual(got["tick_range"], [3, 5])
        self.assertEqual(got["ticks_total"], 3)               # the denominator is the window's

    def test_no_range_is_the_whole_flight_and_is_unchanged(self):
        path, stamps = self.flight()
        got = checker.airborne_ground_speed(path, stamps)
        self.assertIsNone(got["tick_range"])
        self.assertEqual(got["steps_scored"], 6)
        self.assertAlmostEqual(got["median_mps"], 3.5, places=6)

    def test_a_single_tick_range_scores_no_step_and_says_so(self):
        path, stamps = self.flight()
        got = checker.airborne_ground_speed(path, stamps, (4, 4))
        self.assertEqual(got["steps_scored"], 0)
        self.assertIsNone(got["median_mps"])


class TestEncounterWindowSpeedGate(Harness):
    """QA finding G138. The whole-flight median is a MISSION statistic and cannot see a sprint
    through the one moment the booking is about."""

    def gate(self, log, booking=None, name="live_flight_log_TEST.json"):
        """`gate_booked_speed` directly: the encounter events would otherwise have to satisfy every
        other schema-2 gate too, and what is under test here is one function."""
        return checker.gate_booked_speed(log, log.get("run") or {}, self.dir / name, booking)

    def test_the_flip_a_slow_mission_median_hiding_a_fast_encounter(self):
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        log = encounter_flight(cruise_mps=2.0, dash_mps=9.0)
        problems, notes = self.gate(log, booking)
        blob = " ".join(problems + notes)
        # The whole-flight median PASSES...
        self.assertNotIn("FLOWN FASTER THAN BOOKED: median", blob)
        # ...and the encounter window FAILS, on the same bar. That flip IS the fix.
        self.assertTrue(any("ENCOUNTER FLOWN FASTER THAN BOOKED" in p for p in problems), blob)
        self.assertIn("1.800x", blob)
        self.assertIn("NOT THE AUTHORISED TAKE", blob)

    def test_an_encounter_flown_AT_the_booking_is_not_a_problem(self):
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        problems, notes = self.gate(encounter_flight(cruise_mps=2.0, dash_mps=5.0), booking)
        self.assertEqual(problems, [])
        self.assertIn("ENCOUNTER window speed (GATED", " ".join(notes))

    def test_the_same_10_percent_tolerance_applies_and_bites_just_past_it(self):
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        self.assertEqual(self.gate(encounter_flight(2.0, 5.49), booking)[0], [])
        self.assertTrue(self.gate(encounter_flight(2.0, 5.51), booking)[0])

    def test_a_take_with_no_encounter_says_so_rather_than_passing_silently(self):
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        problems, notes = self.gate(flight_at(5.0), booking)
        self.assertEqual(problems, [])
        self.assertIn("no encounter window on this take", " ".join(notes))

    def test_an_unmeasurable_encounter_is_INVALID_not_ignored(self):
        """A booking bound to a take whose encounter cannot be scored is an authorisation nobody
        can verify -- the same rule the whole-flight NOT MEASURABLE case already follows."""
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        log = encounter_flight(cruise_mps=2.0, dash_mps=5.0)
        # Freeze the clock across the whole encounter window: dt <= 0 measures no speed at all.
        stamps = log["run"]["tick_stamp_sim_s"]
        for i in range(14, 21):
            stamps[i] = stamps[14]
        problems, _notes = self.gate(log, booking)
        self.assertTrue(any("ENCOUNTER SPEED NOT MEASURABLE" in p for p in problems), problems)

    def test_ONE_dead_window_beside_a_good_one_loses_neither_half(self):
        """Every window is owed a verdict. A take with one measurable encounter and one dead one
        must report the measurement AND the gap -- reporting only the subset that happened to be
        scoreable is how an unverifiable authorisation reads as a verified one."""
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        log = encounter_flight(cruise_mps=2.0, dash_mps=9.0)
        n = len(log["flown_path_enu"])
        log["events"] += [{"kind": "takeover", "tick": n - 3},
                          {"kind": "resume", "tick": n - 1, "trigger": "threat_cleared"}]
        for i in range(n - 4, n):                       # freeze the clock over the second window
            log["run"]["tick_stamp_sim_s"][i] = log["run"]["tick_stamp_sim_s"][n - 5]
        problems, notes = self.gate(log, booking)
        blob = " ".join(problems + notes)
        self.assertTrue(any("ENCOUNTER SPEED NOT MEASURABLE on 1 of 2" in p for p in problems), blob)
        self.assertTrue(any("ENCOUNTER FLOWN FASTER THAN BOOKED" in p for p in problems), blob)

    def test_without_a_booking_the_encounter_speed_is_printed_as_CONTEXT(self):
        """It is the number that pointed at this whole finding. With nothing to hold it to it is
        not a check -- but it is never absent, because absence is what hid it."""
        problems, notes = self.gate(encounter_flight(2.0, 9.0))
        self.assertEqual(problems, [])
        blob = " ".join(notes)
        self.assertIn("ENCOUNTER window(s)", blob)
        self.assertIn("CONTEXT here", blob)
        self.assertIn("9.000 m/s", blob)


class TestTheCommittedTakeIsTheRegression(unittest.TestCase):
    """The pin QA asked for, on the REAL artifacts rather than a synthesis: bind the committed
    2026-09-07 booking (5.0 m/s, exit 0) to the committed 2026-08-25 avoidance take.

    That take set no waypoint-speed parameter at all -- nothing in the repo did before 2026-09-07 --
    so it is the exact flight this gate exists to refuse, and it is the one whose two medians
    disagree."""

    LOG = REPO_ROOT / "eval" / "results" / "live_flight_log_20260825T210402Z.json"
    BOOKING = REPO_ROOT / "eval" / "results" / "booking_gate_20260907T064136Z.json"

    def setUp(self):
        if not (self.LOG.exists() and self.BOOKING.exists()):   # pragma: no cover
            self.skipTest("committed evidence is not in this checkout")
        self.log = json.loads(self.LOG.read_text())
        self.run = self.log["run"]

    def test_the_whole_flight_median_PASSES_the_booking_it_should_have_failed(self):
        stat = checker.airborne_ground_speed(self.log["flown_path_enu"],
                                             self.run["tick_stamp_sim_s"])
        self.assertAlmostEqual(stat["median_mps"], 3.4172, places=3)
        self.assertLess(stat["median_mps"], BOOKED_MPS * checker.BOOKED_SPEED_TOLERANCE,
                        "the mission median clears a 5.0 m/s booking with room to spare -- which is "
                        "why it cannot be the only gated statistic")

    def test_the_ENCOUNTER_median_fails_it_and_that_flip_is_the_fix(self):
        windows = checker.encounter_windows(self.log, len(self.log["flown_path_enu"]))
        self.assertEqual([(lo, hi) for lo, hi, _ in windows], [(991, 995)])
        stat = checker.airborne_ground_speed(self.log["flown_path_enu"],
                                             self.run["tick_stamp_sim_s"], (991, 995))
        self.assertEqual(stat["steps_scored"], 4)
        self.assertAlmostEqual(stat["median_mps"], 9.0121, places=3)
        self.assertGreater(stat["median_mps"], BOOKED_MPS * checker.BOOKED_SPEED_TOLERANCE)

    def test_the_gate_refuses_the_take_and_names_the_encounter(self):
        problems, notes = checker.gate_booked_speed(self.log, self.run, self.LOG, self.BOOKING)
        blob = " ".join(problems + notes)
        self.assertTrue(any("ENCOUNTER FLOWN FASTER THAN BOOKED" in p for p in problems), blob)
        self.assertIn("takeover 991 -> resume 995", blob)
        self.assertIn("1.802x", blob)                      # 9.012 / 5.000
        self.assertIn("median 3.417", blob)                # the mission number, still printed
        # ...and the whole-flight statistic alone would NOT have failed it.
        self.assertFalse(any(p.startswith("FLOWN FASTER THAN BOOKED") for p in problems), problems)


# ================================================================================================
# 4. Binding -- the flag, the sidecar, and the case where a take has two authorisations
# ================================================================================================
class TestBookingBinding(Harness):
    def test_the_sidecar_is_found_beside_the_log_with_no_flag_at_all(self):
        name = "live_flight_log_TEST.json"
        booking_artifact(checker.booking_path_for(self.dir / name), BOOKED_MPS)
        status, messages = self.check(flight_at(10.0), name=name)
        self.assertEqual(status, checker.INVALID, " ".join(messages))
        self.assertIn("FLOWN FASTER THAN BOOKED", " ".join(messages))

    def test_the_sidecar_name_is_derived_from_the_logs_own_stem(self):
        self.assertEqual(checker.booking_path_for(Path("/x/live_flight_log_20260907T1Z.json")).name,
                         "live_flight_log_20260907T1Z.booking.json")

    def test_a_flag_and_an_AGREEING_sidecar_are_not_an_ambiguity(self):
        name = "live_flight_log_TEST.json"
        booking_artifact(checker.booking_path_for(self.dir / name), BOOKED_MPS)
        flag = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        status, messages = self.check(flight_at(5.0), booking=flag, name=name)
        self.assertEqual(status, checker.VALID, " ".join(messages))

    def test_TWO_DISAGREEING_bookings_for_one_take_are_refused_not_silently_resolved(self):
        """The `AMBIGUOUS TAKE` shape this file already refuses for truth tracks: a flag that
        quietly overrides a sidecar lets the strictest authorisation on disk be the one nobody
        reads."""
        name = "live_flight_log_TEST.json"
        booking_artifact(checker.booking_path_for(self.dir / name), BOOKED_MPS)
        loose = booking_artifact(self.dir / "booking_gate_X.json", 8.0)
        status, messages = self.check(flight_at(7.0), booking=loose, name=name)
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("TWO BOOKINGS FOR ONE TAKE", blob)

    def test_an_avoidance_take_with_NO_booking_gets_a_loud_warning_and_still_passes(self):
        """Optional for the launcher, mandatory for a dodge take. Silence would read as verified;
        turning it into a failure would retroactively redden two committed flights."""
        status, messages = self.check(flight_at(5.0))
        blob = " ".join(messages)
        self.assertEqual(status, checker.VALID, blob)
        self.assertIn("NO BOOKING BOUND -- WARNING", blob)
        self.assertIn("AVOIDANCE take", blob)
        self.assertIn("median 5.000", blob)            # the number exists either way

    def test_the_demo_bird_take_is_an_avoidance_take_too(self):
        status, messages = self.check(flight_at(5.0, source=checker.DET_DEMO_VIRTUAL))
        self.assertIn("NO BOOKING BOUND -- WARNING", " ".join(messages))

    def test_the_DEPTH_take_is_an_avoidance_take_too_and_it_is_the_one_this_gate_is_FOR(self):
        """The forward depth aperture is the sensor ADR-019/020 booked in the first place, so
        exempting it told the ONE take that needs an authorisation that it needs none (QA,
        2026-09-07). Gated at the FUNCTION, not through `check_file`, so the assertion is about the
        booking half alone: when this was written a depth log was INVALID at the door (unscoreable
        source) and that would have masked both the right and the wrong answer; since P1 landed
        (same day) the log is scored on its own seven bars, and this test still has to hold with the
        rest of the gate out of the way."""
        log = flight_at(5.0, source=checker.DET_DEPTH_BLOB)
        problems, notes = checker.gate_booked_speed(log, log["run"],
                                                    self.dir / "live_flight_log_TEST.json")
        blob = " ".join(problems + notes)
        self.assertIn("NO BOOKING BOUND -- WARNING", blob)
        self.assertIn("depth_blob", blob)
        self.assertNotIn("not an avoidance take", blob)

    def test_the_NDVI_SURVEY_needs_no_booking_and_is_not_warned_at(self):
        """`detector.source == 'none'`: no dodge, nothing the forward-sensor gate authorises."""
        status, messages = self.check(flight_at(5.0, source=checker.DET_NONE))
        blob = " ".join(messages)
        self.assertEqual(status, checker.VALID, blob)
        self.assertNotIn("WARNING", blob)
        self.assertIn("not an avoidance take", blob)

    def test_a_booking_bound_to_a_PRE_SEAM_legacy_log_is_INVALID_not_quietly_skipped(self):
        """Legacy logs have no `run` block and therefore no time axis at all -- their only axis is
        the tick index, and 5 Hz is the node's NOMINAL rate, not something those flights measured.
        There is no flown speed to hold an authorisation to."""
        legacy = flight_at(5.0)
        legacy.pop("run")
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        status, messages = self.check(legacy, booking=booking,
                                      name=f"{checker.PRE_SEAM_LEGACY_STEMS[0]}.json")
        blob = " ".join(messages)
        self.assertEqual(status, checker.INVALID, blob)
        self.assertIn("PRE-SEAM log", blob)

    def test_a_legacy_log_with_NO_booking_keeps_the_verdict_it_was_flown_under(self):
        legacy = flight_at(5.0)
        legacy.pop("run")
        status, _ = self.check(legacy, name=f"{checker.PRE_SEAM_LEGACY_STEMS[0]}.json")
        self.assertEqual(status, checker.VALID)


# ================================================================================================
# 5. The CLI -- the flag reaches check_file and the exit code is the gate's
# ================================================================================================
class TestCli(Harness):
    def main(self, argv):
        """`checker.main` calls `check_file` with its DEFAULT results_dir, i.e. the real
        eval/results; bind it to the harness tmp dir so a committed artifact cannot colour this
        test, and leave parsing / exit codes / the stdout-stderr split running unmodified."""
        real = checker.check_file

        def isolated(path, truth=None, results_dir=None, booking=None):
            return real(path, truth=truth, results_dir=self.dir, booking=booking)

        with mock.patch.object(checker, "check_file", isolated):
            return checker.main(argv)

    def test_the_flag_end_to_end_turns_an_overspeed_take_red(self):
        truth = self.truth()
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        p = self.write_log(flight_at(10.0))
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = self.main([str(p), "--truth", str(truth), "--booking", str(booking)])
        self.assertEqual(code, 1)
        self.assertIn("FLOWN FASTER THAN BOOKED", err.getvalue())

    def test_the_same_command_at_the_booked_speed_exits_zero_and_prints_the_numbers(self):
        truth = self.truth()
        booking = booking_artifact(self.dir / "booking_gate_X.json", BOOKED_MPS)
        p = self.write_log(flight_at(5.0))
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = self.main([str(p), "--truth", str(truth), "--booking", str(booking)])
        self.assertEqual(code, 0)
        self.assertIn("booked_speed_mps 5.000", out.getvalue())
        self.assertIn("ratio 1.000", out.getvalue())

    def test_the_gate_is_still_stdlib_only_after_growing_a_booking_reader(self):
        """`predict_forward_lead` is imported lazily and is itself stdlib; numpy must not arrive
        through the new door either."""
        source = (REPO_ROOT / "scripts" / "check_live_flight_log.py").read_text()
        for banned in ("import numpy", "import scipy", "from numpy", "from scipy"):
            self.assertNotIn(banned, source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
