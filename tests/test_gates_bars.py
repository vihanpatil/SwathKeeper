"""swathkeeper_gates' bars (design §3, §9): the strict loader, the five kinds, and §3.2's fixed order.

Every fixture is a synthetic DataFlash log from test_gates_adapter (no third-party bytes). Each red-first
assertion names the mutant it was shown failing against (G-numbers are QA's findings, Q-numbers QA's mutants).
"""
import datetime as dt
import json
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from swathkeeper_gates import allowlist  # noqa: E402
from swathkeeper_gates import bars as B  # noqa: E402
from swathkeeper_gates import verdict as V  # noqa: E402
from swathkeeper_gates.contract import Refusal, fired_gaps, hits, log_holes, streams_map, unsure  # noqa: E402
from test_gates_adapter import (M_PER_DEG, STD, T0, at_time, edit, flight_rows, gps, latlon, parse, surgery,  # noqa: E402
                                us, zeroed)


def bar(kind, params, min_n=1, modes=None, armed=None):
    return {"id": "b", "kind": kind, "severity": "must", "provenance": {"text": "test", "param": "FENCE_RADIUS"},
            "scope": {"armed": armed, "modes": modes}, "min_n": min_n, "params": params}


def doc(*bars, **kw):
    return {"schema": B.SCHEMA, "contract": "swathkeeper-flightlog/1.0", **kw, "bars": list(bars)}


def judge(b, log, assume=None):
    return B.evaluate(B.validate(doc(b, **({"assume": assume} if assume else {}))), log)[0]


def batt(limit=20.0, **kw):
    return bar("series_bound", {"channel": "battery.voltage_v", "bound": "floor", "limit": limit}, **kw)


def gnss(max_outage=0, **kw):
    return bar("gnss_quality", {"fix_min": 3, "sats_min": 6, "max_outage_s": max_outage}, **kw)


def dropped(rows, at, dp=3):
    """DSF.Dp reads `dp` from t=at on: one drop interval [at - 1, at] (DSF logs at 1 Hz), k = dp."""
    return [(n, {**v, "Dp": dp} if n == "DSF" and v["TimeUS"] >= us(at) else v) for n, v in rows]


def cut(rows, a, b, keep=()):
    """Rows with a < t < b removed (a clean hole), except messages in `keep`."""
    return [x for x in rows if x[0] in keep or not us(a) < x[1]["TimeUS"] < us(b)]


FENCE = bar("containment", {"source": "log"})
MODES = bar("mode_transitions", {"allowed": [["<start>", "STABILIZE"], ["STABILIZE", "ALT_HOLD"], ["ALT_HOLD", "LOITER"]]})
EVENTS = bar("no_events", {"kinds": ["error"]}, min_n=20)
# A U in local metres (concave: the notch is 40 < x < 60, y > 20). The default track (x = t, y = 50) is in the left arm.
U = [list(latlon(x, y)) for x, y in ((-10, 0), (100, 0), (100, 100), (60, 100), (60, 20), (40, 20), (40, 100), (-10, 100))]
POLY = bar("containment", {"source": "yaml", "polygon": U, "alt_max_rel_home_m": 50})
JUMP = lambda t: (t if t < 15 else 65 + t, 50.0, 5.0)     # one 0.1 s step from x=14.9 (left arm) to x=80 (right arm)


class TestKinds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.clean = parse(flight_rows())

    def test_each_kind_passes_clean_and_fails_on_one_sample(self):
        ignored = bar("no_events", {"kinds": ["error"], "ignore": [[16, 1]]}, min_n=20)
        err = parse(flight_rows(events=STD + ((12.3, "ERR", 16),)))
        for b, log, want in ((batt(), parse(edit(flight_rows(), "BAT", 12.3, inst=1, Volt=19.0)), B.FAIL),
                             (gnss(), parse(edit(flight_rows(), "GPS", 12.4, inst=1, Status=1)), B.FAIL),
                             (gnss(), parse(edit(flight_rows(), "GPS", 12.4, inst=1, NSats=4)), B.FAIL),       # Q24
                             (FENCE, parse(flight_rows(track=lambda t: (t, 200.0 if t == 12.3 else 50.0, 5.0))), B.FAIL),
                             (MODES, parse(flight_rows(events=STD[:3] + ((20.0, "MODE", 6),))), B.FAIL),    # -> RTL
                             (EVENTS, err, B.FAIL), (ignored, err, B.PASS)):                                   # Q23
            with self.subTest(kind=b["kind"], want=want):
                self.assertEqual(judge(b, self.clean)["verdict"], B.PASS)
                self.assertEqual(judge(b, log)["verdict"], want)   # mutant: the kind's violation rule deleted -> red
        self.assertEqual(judge(batt(), self.clean)["param_in_log"]["values"], [150.0])    # the log's own value, printed

    def test_a_violation_on_a_thin_sample_is_fail_and_the_worse_instance_is_named(self):
        r = judge(batt(min_n=10_000), parse(edit(flight_rows(), "BAT", 12.3, inst=1, Volt=19.0)))
        self.assertEqual((r["verdict"], r["worst_instance"]), (B.FAIL, 1))   # mutants: rules 3/4 swapped; instance 0 only -> red
        self.assertAlmostEqual(r["measured"], 19.0, places=5)

    def test_ei_and_na_never_print_a_pass_or_a_number(self):
        for r in (judge(batt(min_n=10_000), self.clean), judge(batt(modes=["AUTO"]), self.clean)):
            self.assertIn(r["verdict"], (B.EI, B.NA))
            self.assertEqual((r["measured"], r["worst_instance"]), (None, None))   # mutant: measured always shown -> red
            self.assertNotIn("worst", r["note"])

    def test_a_non_finite_sample_in_scope_is_ei(self):
        for v in (float("nan"), float("inf"), float("-inf")):              # G237: inf is not a value either
            with self.subTest(v=v):
                r = judge(batt(), parse(edit(flight_rows(), "BAT", 12.3, inst=0, Volt=v)))
                self.assertEqual(r["verdict"], B.EI)                         # mutant: plain min (NaN as a value) -> red
                self.assertIn("NaN/inf", r["note"])

    def test_a_2_s_hole_or_a_late_start_is_ei_with_the_gap_printed(self):
        r = judge(batt(), parse(cut(flight_rows(), 10.0, 12.0)))
        self.assertEqual(r["verdict"], B.EI)        # mutants: no gap rule; the 1 s floor -> 3 s; 5p -> 50p -> red
        self.assertEqual({("battery", 0, T0 + 10, T0 + 12), ("battery", 1, T0 + 10, T0 + 12), ("log", None, T0 + 10, T0 + 12)},
                         {(g["stream"], g["instance"], g["t0"], g["t1"]) for g in r["gaps"]})   # every raw stream: the logger
        late = [x for x in flight_rows() if not (x[0] == "BAT" and x[1]["TimeUS"] < us(3.0))]
        self.assertEqual(judge(batt(), parse(late))["verdict"], B.EI)       # Q1 mutant: window edges not gaps -> red

    def test_the_gap_threshold_is_max_of_1_s_and_5_periods_from_both_sides(self):
        ten_hz, slow = [k / 10 for k in range(100)], [k * 0.4 for k in range(50)]     # p = 0.1 s; p = 0.4 s (5p = 2 s)
        holes = lambda ts, a, b: fired_gaps([t for t in ts if not a < t < b], [(0.0, ts[-1])])
        # G259 HM7 mutant: a point hole at a window's start does not hit it -> red (its end is outside: half-open)
        self.assertEqual((hits((5.0, 5.0), [(5.0, 6.0)]), hits((6.0, 6.0), [(5.0, 6.0)])), (True, False))
        # mutants: the floor 1 s -> 0.85 s or -> 1.2 s; 5p -> 3.5p or -> 6.5p: each turns one line red
        self.assertEqual((holes(ten_hz, 2.0, 2.9), len(holes(ten_hz, 2.0, 3.1))), ([], 1))     # 0.9 s no; 1.1 s yes
        self.assertEqual((holes(slow, 2.0, 3.6), len(holes(slow, 2.0, 4.4))), ([], 1))         # 1.6 s no; 2.4 s yes

    def test_no_window_is_na_only_when_the_absence_was_measured(self):
        self.assertEqual(judge(batt(modes=["AUTO"]), self.clean)["verdict"], B.NA)
        for name, log in (("no MODE", parse([x for x in flight_rows() if x[0] != "MODE"])),   # mutant: ABSENT mode as NA
                          ("vehicle ABSENT", parse(flight_rows(banner=None))),
                          # G233: AUTO entered only inside a 4 s byte hole (11..15 s) -> the absence is not measured
                          ("AUTO inside a hole", zeroed(flight_rows(events=STD[:3] + ((12.0, "MODE", 3), (14.0, "MODE", 2),
                                                                                       (20.0, "MODE", 5))), span=(11.0, 15.0))[0]),
                          # G234: mode unknown for 5 s before the first MODE row
                          ("mode prefix 5 s", parse(flight_rows(events=((5.0, "MODE", 5),))))):
            with self.subTest(name):
                self.assertEqual(judge(batt(modes=["AUTO"]), log)["verdict"], B.EI)
        self.assertIn("mode unknown for 0.000 s", judge(batt(modes=["LOITER"]), self.clean)["note"])
        for at in (0.5, 1.0):        # mutants: MODE_PREFIX_S 1.0 -> 0.3 (or -> 10, above); G259 HM5 `>` -> `>=`
            self.assertEqual(judge(batt(modes=["STABILIZE"]), parse(flight_rows(events=((at, "MODE", 0),))))["verdict"], B.PASS)

    def test_a_fully_excluded_instance_is_ei_never_a_greener_pass(self):
        ekf = bar("series_bound", {"channel": "ekf.vel_ratio", "bound": "ceiling", "limit": 0.8})
        speed = bar("series_bound", {"channel": "velocity.groundspeed_mps", "bound": "ceiling", "limit": 12.5})
        for b, rows, stream in ((ekf, [(n, {**v, "SS": 0} if n == "XKF4" and v["C"] == 1 else v) for n, v in flight_rows()], "ekf"),
                                (speed, [(n, {**v, "Status": 1} if n == "GPS" and v["I"] == 1 else v) for n, v in flight_rows()],
                                 "velocity")):
            with self.subTest(stream):   # G256 mutant: the instance vanishes -> PASS on the other one -> red
                r = judge(b, parse(rows))
                self.assertEqual((r["verdict"], [(g["stream"], g["instance"]) for g in r["gaps"]]), (B.EI, [(stream, 1)]))
                self.assertIn("are EMPTY", r["note"])

    def test_touching_scope_windows_are_one_window(self):
        # G228 / Q13: the chord and the outage straddle the ALT_HOLD -> LOITER switch at t = 20
        jump20 = parse(flight_rows(track=lambda t: (t if t < 20 else 60 + t, 50.0, 5.0)))
        self.assertEqual(judge({**POLY, "scope": {"armed": None, "modes": ["ALT_HOLD", "LOITER"]}}, jump20)["verdict"], B.FAIL)
        r = judge(gnss(5, modes=["ALT_HOLD", "LOITER"]), parse(gps(flight_rows(), 16.0, 24.0, Status=1)))
        self.assertEqual((r["verdict"], r["measured"]), (B.FAIL, 8.0))

    def test_an_armed_scope_before_the_first_arm_row_is_ei(self):
        # mutant: the ABSENT prefix skipped (arming judged from the first row only) -> red
        self.assertIn("ABSENT before the first ARM row", judge(batt(armed=True), self.clean)["note"])
        self.assertEqual(judge(batt(armed=True, modes=["LOITER"]), self.clean)["verdict"], B.PASS)

    def test_the_note_says_when_every_sample_is_one_value_and_what_was_excluded(self):
        speed = bar("series_bound", {"channel": "velocity.groundspeed_mps", "bound": "ceiling", "limit": 12.5})
        self.assertIn("all 302 judged samples equal 3", judge(speed, self.clean)["note"])       # G230c
        floor = bar("series_bound", {"channel": "position.alt_rel_home_m", "bound": "floor", "limit": 4.0})
        log = parse(flight_rows(home_at=5.0, track=lambda t: (t, 50.0, 0.0 if t < 5 else 5.0)))
        r = judge(floor, log)                      # G240 mutant: RelHomeAlt before home judged -> FAIL -> red
        self.assertEqual((r["verdict"], r["n"]), (B.PASS, 251))
        self.assertIn("50 sample(s) excluded", r["note"])

    def test_a_gnss_run_ends_at_a_gap_or_the_window_end(self):
        # (orchestrator) bad 0-2 s, rows missing 2-4 s, bad 4-6 s: two 2 s runs and a gap (EI), never a 6 s outage
        r = judge(gnss(3), parse(cut(gps(flight_rows(), 0.0, 6.0, Status=1), 2.0, 4.0, keep=("POS", "BAT", "XKF4"))))
        self.assertEqual(r["verdict"], B.EI)
        r = judge(gnss(3), parse(gps(flight_rows(), 25.0, 99.0, Status=1)))
        self.assertEqual(r["verdict"], B.FAIL)     # Q5 mutant: an outage open at the window end is dropped -> red
        self.assertAlmostEqual(r["measured"], 5.0, places=3)
        # G255: a byte hole ENDING at the run's first row (shared timestamp) must not cut it. Unscoped since G314: that
        # hole may hide a MODE row, so an ALT_HOLD scope starting there is no longer sure
        log, _ = zeroed(gps(flight_rows(), 10.0, 15.0, Status=1), span=(9.9, 10.0))
        r = judge(gnss(4.9), log)
        self.assertEqual((r["verdict"], round(r["measured"], 3)), (B.FAIL, 5.0))   # mutant: `prev <= a` -> any overlap


class TestContainment(unittest.TestCase):
    def test_a_concave_chord_with_both_ends_inside_fails(self):
        self.assertEqual(judge(POLY, parse(flight_rows()))["verdict"], B.PASS)
        r = judge(POLY, parse(flight_rows(track=JUMP)))
        self.assertEqual(r["verdict"], B.FAIL)                         # mutant: points only -> red
        self.assertIn("crossed the polygon boundary between samples at t=16.000 s", r["note"])   # G246

    def test_a_chord_across_a_gap_or_a_nan_is_not_judged(self):
        rows = [x for x in flight_rows(track=JUMP) if not (x[0] == "POS" and us(13.0) < x[1]["TimeUS"] < us(15.0))]
        r = judge(POLY, parse(rows))
        self.assertEqual((r["verdict"], r["gaps"][0]["stream"]), (B.EI, "position"))   # mutant: bridge the gap -> red
        nan = edit(flight_rows(track=JUMP), "POS", 15.0, RelHomeAlt=float("nan"))
        self.assertEqual(judge(POLY, parse(nan))["verdict"], B.EI)    # Q14 mutant: a NaN sample bridged -> FAIL -> red

    def test_a_fail_on_the_row_before_a_byte_hole_is_flagged_unverifiable(self):
        def half_zero_pos(raw):          # G265: POS at 12.3 keeps its header, loses its values and the next header
            o = at_time(raw, 12.3)
            raw[o + 11:o + 32] = bytes(21)
        r = judge(FENCE, surgery(flight_rows(), half_zero_pos))
        self.assertEqual(r["verdict"], B.FAIL)
        self.assertIn("sits beside a byte hole", r["note"])      # mutant: the line dropped -> red

    def test_alt_max_and_exclusion_segments_are_judged(self):
        r = judge(FENCE, parse(flight_rows(track=lambda t: (t, 50.0, 101.0 if t == 12.3 else 5.0))))
        self.assertEqual(r["verdict"], B.FAIL)                               # mutant: alt_max ignored -> red
        self.assertAlmostEqual(r["measured"], -1.0, places=3)
        circle = bar("containment", {"source": "log", "exclusions": [dict(zip(("lat", "lon"), latlon(47, 50)), radius_m=5)]})
        self.assertEqual(judge(circle, parse(flight_rows()))["verdict"], B.PASS)
        self.assertEqual(judge(circle, parse(flight_rows(track=JUMP)))["verdict"], B.FAIL)  # mutant: samples only -> red

    def test_delta_longitude_wraps_at_the_antimeridian(self):
        d = 100 / M_PER_DEG                                          # G232: a 200 m square straddling lon 180
        square = bar("containment", {"source": "yaml", "polygon": [[-d, 180 - d], [-d, -180 + d], [d, -180 + d], [d, 180 - d]]})
        west = lambda x, y: (0.0, 180 - (300 + x) / M_PER_DEG)        # 300-330 m west of 180: outside
        self.assertEqual(judge(square, parse(flight_rows(geo=west)))["verdict"], B.FAIL)


class TestModeTransitions(unittest.TestCase):
    def test_n_counts_real_transitions_and_the_startup_row_is_judged_apart(self):
        late = parse(flight_rows(events=((8.0, "MODE", 0), (12.0, "MODE", 2))))
        self.assertEqual(judge(MODES, late)["verdict"], B.EI)          # G258 mutant: B7 ignores an 8 s unknown prefix -> red
        one = parse(flight_rows(events=((0.0, "MODE", 5),)))
        r = judge(bar("mode_transitions", {"allowed": [["*", "LOITER"]]}), one)
        self.assertEqual((r["verdict"], r["n"]), (B.EI, 0))            # G235 mutant: the startup row counted -> PASS -> red
        r = judge(bar("mode_transitions", {"allowed": [["<start>", "STABILIZE"], ["*", "ALT_HOLD"]]}), one)
        self.assertEqual((r["verdict"], r["n"]), (B.FAIL, 0))
        self.assertIn("<start> -> LOITER (Rsn 1)", r["note"])          # G253

    def test_a_hole_anywhere_in_scope_is_ei_and_a_transition_across_it_is_not_judged(self):
        self.assertEqual(judge(MODES, zeroed(flight_rows(), span=(22.0, 26.0))[0])["verdict"], B.EI)   # G231: after the last row
        no_alt = bar("mode_transitions", {"allowed": [["<start>", "STABILIZE"], ["ALT_HOLD", "LOITER"]]})
        r = judge(no_alt, zeroed(flight_rows(), span=(6.0, 8.0))[0])
        self.assertEqual(r["verdict"], B.FAIL)         # G312: no `from` may enter ALT_HOLD, so a hidden one is no excuse
        self.assertIn("? -> ALT_HOLD (Rsn 1) at t=11.000 s (from unknown: a log hole", r["note"])


class TestLoggerHoles(unittest.TestCase):
    def test_a_gap_in_every_raw_stream_is_the_logger_and_in_one_stream_the_sensor(self):
        gps_only = parse(cut(flight_rows(), 22.0, 26.0, keep=("POS", "BAT", "XKF4", "MODE", "DSF")))
        for b in (batt(), MODES, EVENTS):              # G260 mutant: the UNION of stream gaps -> EI here -> red
            with self.subTest(gps_only=b["kind"]):
                self.assertEqual(judge(b, gps_only)["verdict"], B.PASS)
        auto = STD[:3] + ((12.0, "MODE", 3), (14.0, "MODE", 2), (20.0, "MODE", 5))
        for b, log in ((MODES, parse(cut(flight_rows(), 22.0, 26.0))),      # mutant: byte holes only -> PASS / NA -> red
                       (batt(modes=["AUTO"]), parse(cut(flight_rows(events=auto), 11.0, 15.0)))):
            with self.subTest(all_raw=b["kind"]):
                self.assertEqual(judge(b, log)["verdict"], B.EI)
        self.assertEqual(judge(EVENTS, parse(cut(flight_rows(), 22.0, 26.0)))["n"], 26.0)    # B8 subtracts the 4 s
        blind = parse([x for x in flight_rows() if x[0] not in ("POS", "GPS", "BAT")])
        for b in (MODES, EVENTS):                      # mutant: liveness unwitnessed, judged anyway -> PASS -> red
            with self.subTest(unwitnessed=b["kind"]):
                self.assertIn("to witness logger liveness", judge(b, blind)["note"])


AS = ["arming_before_first_arm_row"]
ARMED = batt(armed=True)


def red_at(rows, t):
    return edit(rows, "BAT", t, inst=1, Volt=19.0)


class TestArmingAssumption(unittest.TestCase):
    """A1-A5 (owner ruling 2026-11-10): the declared prefix, and the arming losses that replace the blanket R3."""

    def test_the_assume_key_is_closed_and_must_be_used(self):
        for kw, why in (({"assume": ["arming_before"]}, "is not one of"), ({"assume": AS * 2}, "duplicate"),
                        ({"assume": []}, "at least 1"), ({"assume": AS[0]}, "expected a list")):
            with self.subTest(why=why), self.assertRaisesRegex(Refusal, why):
                B.validate(doc(ARMED, **kw))
        with self.assertRaisesRegex(Refusal, "an assumption no bar uses"):      # mutant: the refusal dropped -> red
            B.validate(doc(batt(), assume=AS))

    def test_the_prefix_takes_the_opposite_state_of_the_first_arm_row(self):
        arm = ((0.0, "MODE", 0), (5.0, "ARM", 1), (15.0, "ARM", 0), (20.0, "ARM", 1))
        self.assertIn("ABSENT before the first ARM row", judge(ARMED, parse(flight_rows(events=arm)))["note"])    # no key
        for t, want in ((2.0, B.PASS), (17.0, B.PASS), (10.0, B.FAIL)):    # disarmed prefix, disarmed gap, armed
            with self.subTest(t=t):     # mutants: s_1 ignored (armed either way); applied when not declared -> red
                self.assertEqual(judge(ARMED, parse(red_at(flight_rows(events=arm), t)), AS)["verdict"], want)
        log = parse(flight_rows(events=arm))
        before = streams_map(log)
        self.assertEqual(judge(ARMED, log, AS)["n"], 2 * (100 + 101))
        self.assertEqual(streams_map(log), before)                       # A3: the observed stream is never rewritten
        disarm = ((0.0, "MODE", 0), (10.0, "ARM", 0))
        r = judge(ARMED, parse(red_at(flight_rows(events=disarm), 3.0)), AS)     # armed before a first disarm
        self.assertEqual((r["verdict"], judge(ARMED, parse(flight_rows(events=disarm)), AS)["n"]), (B.FAIL, 200))
        self.assertIn(f"arming before t={T0 + 10:.3f} s assumed armed (assume: arming_before_first_arm_row)", r["note"])
        none = parse(flight_rows(events=((0.0, "MODE", 0),)))
        self.assertEqual(judge(ARMED, none, AS)["note"], "n=0; the scope needs arming, which is ABSENT: no ARM rows")
        self.assertEqual([(x["applied"], x["detail"]) for x in B.assumptions(B.validate(doc(ARMED, assume=AS)), none)],
                         [(False, "no ARM rows: not applied, arming stays ABSENT")])
        r = judge(batt(armed=True, modes=["AUTO"]), parse(flight_rows()), AS)
        self.assertEqual(r["verdict"], B.NA)
        self.assertIn("no window of the scope exists (measured, given the assumption)", r["note"])   # mutant -> red

    def test_a_loss_before_the_first_arm_row_makes_the_stretch_before_it_unsure(self):
        disarm = ((0.0, "MODE", 0), (20.0, "ARM", 0))                 # armed before t=21 s; loss [9, 10]
        rows = lambda t=None: parse(dropped(red_at(flight_rows(events=disarm), t) if t else flight_rows(events=disarm), 9))
        self.assertEqual(judge(ARMED, rows(5.0), AS)["verdict"], B.EI)         # inside [t0, 10]: mutant "after the loss"
        self.assertEqual(judge(ARMED, rows(12.0), AS)["verdict"], B.FAIL)      # after b_max, before the first row
        r = judge(ARMED, rows(), AS)
        self.assertEqual((r["verdict"], r["n"]), (B.PASS, 2 * 109))            # sure: (10, 21); wide: [t0, 21)
        self.assertIn("wide scope (quoted)", r["note"])
        straddle = ((0.0, "MODE", 0), (9.5, "ARM", 0), (20.0, "ARM", 1))       # loss [10, 11] straddles t=10.5 s
        for t in (3.0, 15.0):                       # (3) before the loss and (2) after it, up to the next row (V1)
            self.assertEqual(judge(ARMED, parse(dropped(red_at(flight_rows(events=straddle), t), 10)), AS)["verdict"], B.EI)
        for first in (1, 0):                         # G339: a loss STARTING on the first row's tick may precede it
            tick = ((0.0, "MODE", 0), (10.0, "ARM", first), (15.0, "ARM", 1 - first), (20.0, "ARM", first))
            log = parse(dropped(red_at(flight_rows(events=tick), 5.0), 11))
            self.assertEqual(judge(ARMED, log, AS)["verdict"], B.EI)
            self.assertIn("judged both ways", B.assumptions(B.validate(doc(ARMED, assume=AS)), log)[0]["detail"])
        at = ((0.0, "MODE", 0), (1.0, "ARM", 1), (10.0, "ARM", 0))             # loss [1, 2] ends AT the first row (G313)
        self.assertEqual(judge(ARMED, parse(dropped(red_at(flight_rows(events=at), 5.0), 1)), AS)["verdict"], B.EI)

    def test_a_loss_after_the_first_arm_row_and_same_state_rows(self):
        ev = ((0.0, "MODE", 0), (5.0, "ARM", 1), (10.0, "ARM", 0), (20.0, "ARM", 1))   # loss [12, 13]: U = [12, 21)
        rows = lambda t=None: parse(dropped(red_at(flight_rows(events=ev), t) if t else flight_rows(events=ev), 12))
        for t, want in ((14.0, B.EI), (25.0, B.FAIL), (None, B.PASS)):    # the old blanket R3 read EI on all three
            with self.subTest(t=t):     # mutants: U ending at b; wide arming without U_arm -> red
                self.assertEqual(judge(ARMED, rows(t), AS)["verdict"], want)
        twice = ((0.0, "MODE", 0), (2.0, "ARM", 1), (8.0, "ARM", 0), (29.0, "ARM", 0))  # QA N6b: DISARM, DISARM
        for log in (parse(red_at(flight_rows(events=twice), 18.0)), zeroed(red_at(flight_rows(events=twice), 18.0), span=(12.0, 13.0))[0]):
            self.assertEqual(judge(ARMED, log, AS)["verdict"], B.EI)  # mutant: same-state rows ignored -> PASS -> red

    def test_armed_with_modes_and_b7(self):
        ev = ((0.0, "MODE", 0), (0.5, "ARM", 1), (2.0, "MODE", 5), (10.0, "ARM", 0), (16.0, "MODE", 5), (20.0, "ARM", 1))
        b = batt(armed=True, modes=["LOITER"])           # loss [14, 15]: mode unsure to 17, arming to 21
        for t, want in ((5.0, B.FAIL), (18.0, B.EI), (25.0, B.FAIL)):
            with self.subTest(t=t):
                self.assertEqual(judge(b, parse(dropped(red_at(flight_rows(events=ev), t), 14)), AS)["verdict"], want)
        same = STD + ((25.0, "ARM", 1),)                  # ARM, ARM: arming unsure over [1.5, 26), no MODE row lost
        b7 = {**MODES, "scope": {"armed": True, "modes": None}}
        r = judge(b7, parse(flight_rows(events=same)), AS)
        self.assertEqual(r["verdict"], B.EI)              # mutant: B7 judged on the wide scope -> PASS -> red
        self.assertIn("ARM rows at", r["note"])
        self.assertEqual(judge(b7, parse(flight_rows(events=same + ((27.0, "MODE", 6),))), AS)["verdict"], B.FAIL)
        ev = ((0.0, "MODE", 0), (20.0, "ARM", 1), (25.0, "MODE", 5), (27.0, "MODE", 0), (28.0, "MODE", 5))   # G334 (QA S1)
        log, _ = zeroed(flight_rows(events=ev), span=(10.0, 11.0))         # a hole before the first ARM row: outside base
        tab = sorted(set(log.meta["mode_table"].values()))
        every = [[m, "LOITER"] for m in tab] + [["<start>", "*"]] + [[a, c] for a in tab for c in tab if c != "LOITER"]
        self.assertEqual(judge(bar("mode_transitions", {"allowed": every}, armed=True, modes=["LOITER"]), log)["verdict"], B.EI)


class TestQaRound2(unittest.TestCase):
    """QA G369-G374 (2026-11-11): K1-K6 are QA's kill fixtures for mutants Q1, Q5, Q11, Q15, Q22, Q2 (qa369/kill2.py)."""
    NAN = float("nan")

    def J(self, b, rows, assume=None):
        return B.evaluate(B.validate(doc(b, {**batt(), "id": "m"}, **({"assume": assume} if assume else {}))), parse(rows))[0]

    def test_k1_to_k6(self):
        t0 = 3_099_811                                  # K1 (Q1): t0 off the float grid, t1 exactly 5.000000 s later
        rows = [x for x in flight_rows() if x[0] in ("PARM", "MSG") or x[1]["TimeUS"] > t0]
        rows.insert(next(i for i, x in enumerate(rows) if x[0] not in ("PARM", "MSG")), ("DSF", {"TimeUS": t0, "Dp": 0}))
        self.assertEqual(self.J(spd(), parm(rows, ((t0 + 5_000_000) / 1e6 - T0, 4.0)), LA)["verdict"], B.PASS)   # Q1: r6 dropped
        other = parm(parm(flight_rows(), U4), (2.0, self.NAN), name="BATT_LOW_VOLT")        # K2 (Q5): another name's NaN row
        self.assertEqual(self.J(spd(), other)["verdict"], B.PASS)
        self.assertEqual(self.J(spd(scale=None), parm(flight_rows(), (-0.5, 3.0)))["verdict"], B.PASS)   # K3 (Q11): x == S*v
        r = self.J(spd(), parm(flight_rows(), U4, (2.1, 4.0), (2.1, self.NAN)))           # K4 (Q15): NaN on a finite row's tick
        self.assertEqual(r["verdict"], B.EI)
        r = self.J(spd(), parm(flight_rows(), U4, (6.2, 2.0), (6.2, 4.0, 1)))              # K5 (Q22): a split on the 7.2 s tick
        self.assertEqual(r["verdict"], B.EI)
        r = self.J(spd(), parm(cut(flight_rows(), 3.0, 4.6), (3.0, 4.0)), LA)               # K6 (Q2): a hole starting on t1
        self.assertEqual((r["verdict"], r["n"]), (B.EI, 0))                 # Q2: the 32 pre-row samples judged -> red

    def test_g369_an_infinite_limit_refuses(self):
        with self.assertRaises(Refusal) as cm:
            load(limit="{param: WP_SPD, scale: 1.0e+308, accept: [1, 20]}")
        self.assertEqual(str(cm.exception), "bar batt.params.limit: scale x accept is not finite")

    def test_g374_a_run_of_exactly_max_outage_is_not_longer_than_it(self):
        r = judge(gnss(0.2), parse(gps(flight_rows(), 1.0, 1.2, Status=1)))      # 2.2 - 2.0 = 0.20000000000000018 raw
        self.assertEqual((r["verdict"], r["measured"]), (B.PASS, 0.2))           # mutant: span un-rounded -> FAIL -> red
        self.assertEqual(judge(gnss(0.19), parse(gps(flight_rows(), 1.0, 1.2, Status=1)))["verdict"], B.FAIL)

    def test_g374_a_gap_and_a_mode_prefix_of_exactly_the_threshold(self):
        no_gap = cut(flight_rows(), 2.4, 3.4, keep=("POS", "GPS", "XKF4", "MODE", "ARM", "DSF"))    # BAT: 3.4 - 2.4 = 1.0 s
        self.assertEqual(judge(batt(), parse(no_gap))["gaps"], [])           # S-a mutant: raw span 1.0000000000000004 -> red
        late = [x for x in flight_rows(events=((1.2, "MODE", 0), (10.0, "MODE", 2))) if x[0] in ("PARM", "MSG") or
                x[1]["TimeUS"] >= us(0.2)]                                    # t0 at rel 0.2, the first MODE row 1.0 s later
        self.assertEqual(judge(batt(modes=["STABILIZE"]), parse(late))["verdict"], B.PASS)   # S-d mutant -> EI -> red

    def test_g374_every_other_span_site_at_an_exact_tie(self):
        """Round 3: each remaining r6 site at a tie the raw float breaks (rel 2.4 -> 3.4 s: 1.0000000000000004 raw)."""
        self.assertEqual(judge(batt(), parse(cut(flight_rows(), 2.4, 3.4)))["verdict"], B.PASS)    # S-b: all-stream gap = 1 s
        r = judge(gnss(1.0), parse(gps(cut(flight_rows(), 2.4, 3.4, keep=("POS", "BAT", "XKF4", "MODE", "ARM", "DSF")),
                                        2.0, 2.6, Status=1)))                  # bad 2.0-2.4, GPS step of exactly 1 s
        self.assertEqual((r["verdict"], r["measured"]), (B.FAIL, 1.4))         # S-c: the run cut at 2.4 -> 0.4 -> PASS
        pos = lambda: cut(flight_rows(), 2.4, 3.4, keep=("GPS", "BAT", "XKF4", "MODE", "ARM", "DSF"))
        self.assertEqual(judge(FENCE, parse(pos()))["n"], 291)                 # S-e: the 1 s step judged (raw: 290)
        mode = lambda off: [x for x in flight_rows(events=()) if x[0] != "MODE"] + [
            ("MODE", {"TimeUS": u, "Mode": 0, "ModeNum": 0, "Rsn": 1}) for u in (us(off), us(off) + 4_000_000, us(off) + 8_000_001)]
        med = [streams_map(parse(mode(off)))["mode"]["instances"]["0"]["median_period_s"] for off in (0.0, 0.1)]
        self.assertEqual(med, [4.000001, 4.000001])             # S-f: the same us diffs print one median (raw: 4.0 at 0.0)
        bat = [x for x in flight_rows() if x[0] != "BAT"] + [
            ("BAT", {"TimeUS": us(0) + i * 200_003, "Inst": k, "Volt": 24.0, "Curr": 10.0})
            for i in range(150) if not 50 < i < 55 for k in (0, 1)]           # p = 0.200003 s; one step of exactly 5p
        self.assertEqual(judge(batt(), parse(bat))["gaps"], [])               # S-g: 5 * 0.200003 = 1.0000149999999999
        disarm = ((0.0, "MODE", 0), (20.0, "ARM", 0))                         # armed before t=21 s under the assumption
        rows = [(n, {**v, "TimeUS": us(1.3) - 1} if n == "DSF" and v["TimeUS"] == us(2) else v)
                for n, v in red_at(flight_rows(events=disarm), 1.3)]          # loss [1, 1.3 - 1 us]: U = [t0, 2.3) abs
        self.assertEqual(judge(ARMED, parse(dropped(rows, 1.3 - 1e-6)), AS)["verdict"], B.FAIL)   # S-h: raw end 2.3000000000000003

    def test_g375_the_gap_threshold_is_exact_on_the_half_microsecond(self):
        """theta = max(1 s, 5 x median of the us spans), a multiple of 0.5 us; a gap fires iff span > theta, strictly."""
        fires = lambda us: bool(fired_gaps(ts := [round(u * 1e-6, 6) for u in us], [(ts[0], ts[-1] + 1e-6)]))
        half = [0, 200_000, 400_000, 600_000, 800_000, 1_000_001, 1_200_002, 1_400_003]   # median 0.2000005: theta 1.0000025
        self.assertEqual([fires(half + [half[-1] + g]) for g in (1_000_003, 1_000_002)], [True, False])  # (a) M1 r6; (b)
        odd = [k * 200_003 for k in range(9)]                     # median 0.200003 s: theta exactly 1.000015 s
        self.assertEqual([fires(odd + [odd[-1] + g]) for g in (1_000_015, 1_000_016)], [False, True])    # (c) M2 raw 5.0*m

    def test_g373_a_fail_says_what_the_limit_did_not_judge(self):
        r = judge(spd(), W((-0.5, self.NAN), (10.0, 4.0), rows=fast(flight_rows(), 20.0)))
        self.assertEqual((r["verdict"], r["n"]), (B.FAIL, 200))
        self.assertIn(unjudged(102, "nonfinite", 0, 10), r["note"])          # mutant: blind not shown on FAIL -> red

    def test_g372_g371_drop_notes(self):
        nobat = dropped([x for x in flight_rows() if x[0] != "BAT"], 11)
        self.assertNotIn("firmware-dropped", judge(batt(), parse(nobat))["note"])        # G372: an ABSENT bar judged nothing
        at = dropped(flight_rows(events=((0.0, "MODE", 5), (3.0, "MODE", 2), (10.0, "MODE", 5))), 1)
        r = judge(spd(modes=["LOITER"]), W((2.0, 4.0), rows=at), LA)
        self.assertIn("not located; judged across (design §3.3) for the limit (assume: limit_before_first_parm_row)", r["note"])
        self.assertIn("mode not known", r["note"])


def on_tick(rows, frm, to):
    """The DSF row at `frm` moved to `to` (relative s): a drop interval can then start on another row's tick."""
    return [(n, {**v, "TimeUS": us(to)} if n == "DSF" and v["TimeUS"] == us(frm) else v) for n, v in rows]


class TestOneTickGrid(unittest.TestCase):
    """Fix round 1 (2026-11-11): every contract time is on the adapter's 1 us grid. At rel 6.2 s (7_200_000 us) the raw
    product 7_200_000 * 1e-6 = 7.199999999999999 sits BELOW the rounded loss bound 7.2, so a same-tick closed tie (G313,
    G339) read as "after". Each fixture puts a drop interval [6.2, 7] on that tick; mutant G-a: the helper returns the
    raw product -> red."""

    def test_the_clock_is_on_the_grid(self):
        log = parse(flight_rows(events=STD[:2] + ((6.2, "MODE", 2),)))
        self.assertIn(7.2, log.streams["mode"].data[0]["t_s"])        # raw: 7.199999999999999

    def test_g339_a_loss_starting_on_the_first_arm_rows_tick_is_at_or_before_it(self):
        ev = ((0.0, "MODE", 0), (6.2, "ARM", 0), (15.0, "ARM", 1))
        log = parse(dropped(red_at(on_tick(flight_rows(events=ev), 6.0, 6.2), 3.0), 7))
        self.assertEqual(judge(ARMED, log, AS)["verdict"], B.EI)        # raw times: FAIL (the prefix read as sure)

    def test_unsure_runs_past_a_mode_row_on_the_tick_of_b(self):
        ev = STD[:2] + ((6.2, "MODE", 5), (12.0, "MODE", 2))
        log = parse(dropped(on_tick(flight_rows(events=ev), 7.0, 6.2), 6.2))       # loss [6, 6.2], b on the MODE row's tick
        self.assertEqual(unsure(log, B._losses(log, log_holes(log))), [(T0 + 6, T0 + 12)])     # `t > b`: not the row at b

    def test_b7_a_loss_starting_on_a_mode_rows_tick_cuts_that_transition(self):
        ev = STD[:2] + ((6.2, "MODE", 2), (20.0, "MODE", 5))
        r = judge(MODES, parse(dropped(on_tick(flight_rows(events=ev), 6.0, 6.2), 7)))
        self.assertIn(f"the mode entering ALT_HOLD at t={T0 + 6.2:.3f} s may be lost", r["note"])   # raw: judged as known


class TestNoEvents(unittest.TestCase):
    def test_n_is_drop_free_seconds(self):
        r = judge(bar("no_events", {"kinds": ["error"]}, min_n=40), parse(flight_rows()))
        self.assertEqual((r["verdict"], r["n"]), (B.EI, 30.0))               # mutant: n counts rows -> PASS -> red
        rose = dropped(flight_rows(), 11)
        self.assertEqual(judge(EVENTS, parse(rose))["n"], 29.0)             # the second in which Dp rose is not drop-free
        # G257 mutants: the note dropped; tested against the windows, not the base range (a LOITER bar misses it) -> red
        for b, how in ((EVENTS, "excluded from n"), (batt(), "judged across"), (batt(modes=["LOITER"]), "mode not known")):
            self.assertIn(f"3 firmware-dropped writes in [{T0 + 10:.3f}, {T0 + 11:.3f}] s", judge(b, parse(rose))["note"])
            self.assertIn(how, judge(b, parse(rose))["note"])
        log, _ = zeroed(flight_rows(), span=(12.0, 14.0))
        hole = log.integrity["holes"][0]
        self.assertEqual(judge(EVENTS, log)["n"], round(30.0 - (hole[1] - hole[0]), 3))   # G259 HM8: holes not subtracted
        early = [x for x in flight_rows() if not (x[0] == "DSF" and x[1]["TimeUS"] > us(20))]
        self.assertEqual(judge(EVENTS, parse(early))["n"], 20.0)            # Q3 mutant: seconds after the last DSF -> red
        self.assertEqual(judge(EVENTS, parse(flight_rows(banner="ArduCopter V4.7.0 (x)")))["verdict"], B.EI)

    def test_a_lost_err_row_is_never_a_pass(self):
        log, _ = zeroed(flight_rows(events=STD + ((12.3, "ERR", 16),)), at=42)
        self.assertEqual(judge(EVENTS, log)["verdict"], B.EI)        # G229 mutant: byte holes ignored -> PASS -> red


class TestDroppedWrites(unittest.TestCase):
    """G257 as ruled 2026-11-10 (v0.2.0): k writes dropped in [a, b] may include a MODE or ARM row, so the mode is
    unsure over U = [a, first MODE row after b, else the log's end). Fixture: STD, Dp rises at 11 -> [10, 11, 3]."""
    R = staticmethod(lambda **kw: dropped(flight_rows(**kw), 11))
    RTL = STD[:3] + ((20.0, "MODE", 6),)                                     # ALT_HOLD -> RTL at 20: disallowed by MODES

    def test_b7_judges_a_transition_across_a_drop_on_every_from_it_could_have_had(self):
        for at, n in ((10, 0), (13, 1), (11, 0)):     # G313 closed-closed: a MODE row AT b (10), AT a (11); control (13)
            r = judge(MODES, parse(self.R() if at == 11 else dropped(flight_rows(), at)))
            self.assertEqual((r["verdict"], r["n"]), (B.EI, n))      # mutants: R1 skip removed; half-open overlap -> red
        self.assertIn(f"3 firmware-dropped writes in [{T0 + 10:.3f}, {T0 + 11:.3f}] s (DSF.Dp), not located: a MODE row may",
                      r["note"])
        self.assertEqual(judge(MODES, parse(dropped(flight_rows(events=self.RTL), 25)))["verdict"], B.FAIL)  # observed red wins
        r = judge(MODES, parse(dropped(flight_rows(events=self.RTL), 16)))     # G312: nothing may enter RTL, from anywhere
        self.assertEqual(r["verdict"], B.FAIL)
        self.assertIn(f"? -> RTL (Rsn 1) at t={T0 + 20:.3f} s (from unknown: 3 firmware-dropped writes", r["note"])
        anything = bar("mode_transitions", {"allowed": [["*", "*"]]})        # G320: no hidden row can fail it
        self.assertEqual([judge(anything, parse(x))["verdict"] for x in (self.R(), dropped(flight_rows(), 0))], [B.PASS] * 2)
        self.assertEqual(judge(anything, parse(self.R()))["n"], 2)
        self.assertEqual(judge({**anything, "scope": {"armed": None, "modes": ["ALT_HOLD", "LOITER"]}}, parse(self.R()))["n"], 2)  # no R2 for B7
        tarot = bar("mode_transitions", {"allowed": [["*", "STABILIZE"], ["*", "ALT_HOLD"], ["*", "LOITER"]]})
        self.assertEqual(judge(tarot, parse(self.R()))["verdict"], B.EI)    # one mode missing: a hidden row could fail it
        z = parse(dropped(flight_rows(), 0))
        no_start = bar("mode_transitions", {"allowed": [[m, "*"] for m in sorted(set(z.meta["mode_table"].values()))]})
        self.assertEqual(judge(no_start, z)["verdict"], B.EI)     # a hidden FIRST row is `<start> -> ?`, which may fail
        self.assertEqual(judge(tarot, z)["verdict"], B.EI)        # no (iii) here: base blindness alone (M19: `a < b` only)
        r = judge(MODES, z)                                        # [t0, t0] (corpus 08/09); M18/M19: `a < b` only -> red
        self.assertEqual((r["verdict"], r["n"]), (B.EI, 1))
        r = judge(MODES, parse(dropped(flight_rows(events=self.RTL), 0)))
        self.assertIn("the startup row <start> -> STABILIZE is not judged (from unknown)", r["note"])     # G322
        loiter = bar("mode_transitions", {"allowed": [["*", "LOITER"], ["LOITER", "*"]]}, modes=["LOITER"])
        self.assertEqual(judge(loiter, parse(self.R()))["verdict"], B.EI)  # M7 mutant: blind over windows, not base -> red
        self.assertEqual(judge(anything, zeroed(flight_rows(), span=(14.0, 15.0))[0])["verdict"], B.PASS)   # G331: Ni mutant
        z = parse(dropped(flight_rows(), 12, 2))                       # G330: a hidden UNKNOWN(n) row matches only "*"
        tbl = sorted(set(z.meta["mode_table"].values()))
        every = bar("mode_transitions", {"allowed": [["<start>", "*"]] + [[a, b] for a in tbl for b in tbl]})
        self.assertEqual(judge(every, z)["verdict"], B.EI)
        self.assertEqual(judge(every, parse(dropped(flight_rows(), 25)))["verdict"], B.EI)   # after the last row: G320 alone

    def test_a_loss_outside_the_base_still_blinds_a_transition_it_cuts(self):
        """G326 (QA N1, N2): an armed LOITER B7; the loss sits where arming is off or ABSENT, so outside the base, but it
        cuts the span of the LOITER entry at 25 s, whose hidden `from` may be ALT_HOLD (not allowed into LOITER)."""
        b7 = bar("mode_transitions", {"allowed": [["<start>", "*"], ["*", "STABILIZE"], ["*", "ALT_HOLD"], ["STABILIZE", "LOITER"],
                                                 ["LOITER", "*"]]}, armed=True, modes=["LOITER"])
        tail = ((20.0, "ARM", 1), (25.0, "MODE", 5), (27.0, "MODE", 0), (28.0, "MODE", 5))
        n1 = ((0.0, "MODE", 0), (2.0, "ARM", 1), (4.0, "ARM", 0)) + tail
        self.assertEqual(judge(b7, parse(flight_rows(events=n1)))["verdict"], B.PASS)            # control
        self.assertEqual(judge(b7, zeroed(flight_rows(events=n1), span=(10.0, 11.0))[0])["verdict"], B.EI)   # hole, disarmed
        self.assertEqual(judge(b7, parse(dropped(flight_rows(events=((0.0, "MODE", 0),) + tail), 10, 2)))["verdict"], B.EI)

    def test_a_mode_scoped_bar_is_judged_on_the_sure_and_the_wide_scope(self):
        loiter, clean = batt(modes=["LOITER"]), judge(batt(modes=["LOITER"]), parse(flight_rows()))
        r = judge(loiter, parse(self.R()))
        self.assertEqual([r[k] for k in ("verdict", "n", "measured")], [B.PASS, clean["n"], clean["measured"]])  # swap -> red
        self.assertIn("passes too: sure worst 24 on n=202; wide worst 24 on n=402", r["note"])
        r = judge(loiter, parse(edit(self.R(), "BAT", 15.0, inst=1, Volt=20.01)))     # G318: a PASS quotes the wide bound
        self.assertEqual((r["verdict"], r["n"], round(r["measured"], 2), r["worst_instance"]), (B.PASS, 202, 20.01, 1))
        self.assertTrue(r["note"].startswith("n=202; wide scope (quoted): worst 20.01 on instance 1"), r["note"])   # G329
        r = judge(loiter, parse(edit(self.R(), "BAT", 15.0, inst=1, Volt=19.0)))      # a red only inside U = [10, 20)
        self.assertEqual((r["verdict"], r["measured"]), (B.EI, None))   # mutants: AND -> OR (PASS); FAIL from wide; U ends at b
        self.assertIn(f"violation at t={T0 + 15:.3f} s, which may or may not be in scope", r["note"])
        r = judge(loiter, parse(edit(self.R(), "BAT", 25.0, inst=1, Volt=19.0)))      # a red in the sure scope
        self.assertEqual((r["verdict"], r["n"]), (B.FAIL, clean["n"]))
        r = judge(batt(modes=["LOITER"], min_n=300), parse(self.R()))  # sure n 202 < 300, wide n 402: never a PASS
        self.assertEqual(r["verdict"], B.EI)                            # mutant: sure/wide swapped -> PASS -> red
        self.assertIn("n 202 < min_n 300", r["note"])
        self.assertNotIn("worst", r["note"])                            # an EI prints no number a reader could quote
        self.assertIn("passes too", r["note"])
        # no MODE row after b: U runs to the log's end, so LOITER (entered AT b = 11) is never sure
        r = judge(loiter, parse(dropped(flight_rows(events=STD[:2] + ((11.0, "MODE", 5),)), 11)))
        self.assertEqual(r["verdict"], B.EI)                            # mutants: `t > b` -> `t >= b` / `t > a`; U ends at b
        twice = dropped(dropped(flight_rows(events=STD + ((24.5, "MODE", 5),)), 5, 1), 25, 2)   # U2 = [25, end)
        r = judge(loiter, parse(edit(twice, "BAT", 27.0, inst=1, Volt=19.0)))
        self.assertEqual(r["verdict"], B.EI)                 # M16/M17: only the first U kept / subtracted -> FAIL -> red
        hole = zeroed(edit(flight_rows(), "BAT", 15.0, inst=1, Volt=19.0), span=(12.0, 13.0))[0]
        self.assertEqual(judge(loiter, hole)["verdict"], B.EI)      # G314: a hole may hide a MODE row as a drop may -> red
        bat_gap = dropped(cut(flight_rows(), 13.0, 16.0, keep=("POS", "GPS", "XKF4", "MODE", "DSF")), 11)
        self.assertEqual(judge(loiter, parse(bat_gap))["gaps"], [])     # M20: the wide pass's gap printed -> red
        ne = judge(bar("no_events", {"kinds": ["error"]}, modes=["ALT_HOLD"]), parse(self.R()))
        self.assertIn("excluded from n", ne["note"])                # M9 mutant: mode-scoped no_events loses its note -> red

    def test_arming_is_unsure_after_a_drop_past_the_first_arm_row(self):
        r = judge(batt(armed=True, modes=["LOITER"]), parse(edit(self.R(), "BAT", 25.0, inst=1, Volt=19.0)))
        self.assertEqual(r["verdict"], B.EI)                         # A4: [11, end) may be disarmed, so a red there is not sure
        self.assertIn(f"arming not known over [{T0 + 10:.3f}, {T0 + 30:.3f}", r["note"])
        self.assertNotIn("judged across", judge(batt(armed=True), parse(self.R()))["note"])   # M10 mutant -> red
        # G311: U = [2, 4) lies before the first ARM row (t=6 s), where arming is ABSENT: the wide pass reaches it -> EI
        early = STD[:1] + ((3.0, "MODE", 0), (5.0, "ARM", 1), (20.0, "MODE", 5))
        for b in (batt(armed=True, modes=["LOITER"]), gnss(armed=True, modes=["LOITER"])):
            with self.subTest(b["kind"]):     # M12 mutant: the R2 gate on hits(drop, base) -> PASS -> red
                self.assertEqual(judge(b, parse(dropped(flight_rows(events=early), 2)))["verdict"], B.EI)
                self.assertIn("mode not known over [2.000, 4.000)", judge(b, parse(dropped(flight_rows(events=early), 2)))["note"])
        self.assertEqual(judge(batt(armed=True), parse(dropped(flight_rows(events=early), 2))), judge(batt(armed=True), parse(flight_rows(events=early))))
        lone = ((0.0, "MODE", 0), (25.0, "MODE", 2), (29.0, "ARM", 0))     # QA Q8: was a vacuous NA "(measured)"
        r = judge(batt(armed=True, modes=["LOITER"]), parse(edit(self.R(events=lone), "BAT", 15.0, inst=1, Volt=19.0)))
        self.assertEqual(r["verdict"], B.EI)

    def test_unscoped_series_bars_and_drop_free_logs_are_unchanged(self):
        red = edit(flight_rows(), "BAT", 15.0, inst=1, Volt=19.0)
        for rows in (flight_rows(), red):
            a, b = judge(batt(), parse(rows)), judge(batt(), parse(dropped(rows, 11)))
            self.assertEqual([a[k] for k in ("verdict", "n", "measured")], [b[k] for k in ("verdict", "n", "measured")])
            self.assertIn("not located; judged across", b["note"])
        blind = parse([x for x in flight_rows() if x[0] != "DSF"])            # G321: loss unmeasured, said so
        self.assertEqual(["DSF ABSENT" in judge(b, blind)["note"] for b in (batt(), batt(modes=["LOITER"]), MODES)], [False, True, True])
        clean = parse(flight_rows())         # (verdict, n) pinned from v0.1.0 on the drop-free log: the regression
        panel = ((batt(), B.PASS, 602), (batt(modes=["LOITER"]), B.PASS, 202), (batt(modes=["AUTO"]), B.NA, 0),
                 (batt(armed=True, modes=["LOITER"]), B.PASS, 202), (gnss(modes=["ALT_HOLD"]), B.PASS, 100),
                 (bar("containment", {"source": "log"}, modes=["LOITER"]), B.PASS, 100), (MODES, B.PASS, 2),
                 (bar("no_events", {"kinds": ["error"]}, modes=["ALT_HOLD"]), B.PASS, 10.0))
        for b, v, n in panel:
            with self.subTest(b["kind"], modes=b["scope"]["modes"]):
                r = judge(b, clean)
                self.assertEqual((r["verdict"], r["n"]), (v, n))
                self.assertNotIn("wide scope", r["note"])


LA = ["limit_before_first_parm_row"]
U4 = (-0.5, 4.0)                       # WP_SPD 4.0 at boot 0.5 s, before the first sample: limit 1.1 x 4.0 = 4.4 everywhere


def parm(rows, *entries, name="WP_SPD"):
    """rows + PARM rows of `name`, entries (t, value[, extra us]) inserted in time order (a tie keeps the given order)."""
    out = list(rows)
    for t, v, *d in entries:
        tu = us(t) + (d[0] if d else 0)
        out.insert(next((i for i, (_, r) in enumerate(out) if r["TimeUS"] > tu), len(out)),
                   ("PARM", {"TimeUS": tu, "Name": name, "Value": v}))
    return out


def spd(scale=1.1, accept=(0, 50), **kw):
    lim = {"param": "WP_SPD", **({"scale": scale} if scale is not None else {}), "accept": list(accept)}
    return {**bar("series_bound", {"channel": "velocity.groundspeed_mps", "bound": "ceiling", "limit": lim}, **kw),
            "provenance": {"text": "test", "param": "WP_SPD"}}


def fast(rows, t, v=5.0):
    return edit(rows, "GPS", t, inst=1, Spd=v)


def W(*entries, rows=None):
    return parse(parm(flight_rows() if rows is None else rows, *entries))


def unjudged(n, why, a, b, breaks=None, scale="1.1"):
    extra = f" ({breaks} of them break {scale} x every logged value they may have had)" if why == "outside" else ""
    return f"{n} {B.WHY[why]}{extra}, t in [{T0 + a:.3f}, {T0 + b:.3f}] s"


class TestParamLimit(unittest.TestCase):
    """0.3.0 (SPEC v2 as ruled 2026-11-11): a series_bound limit that follows the log's own PARM rows. GPS.Spd is 3.0 at
    5 Hz on 2 instances (151 samples each, t = 0..30 s); DSF rows at whole seconds, so `dropped(rows, k)` is [k-1, k].
    Mutants named Pn-x were run on a shadow copy of the final code; each kills by an AssertionError in its test."""

    def test_p4_a_certain_violation_stays_fail_whatever_the_other_samples_are(self):
        every = dropped(fast(parm(flight_rows(), (5.0, 4.0), (25.0, 4.0), (25.0, 2.0), (28.0, 99.0)), 12.0), 21)
        log = parse(every)        # pre [0, 5], unsure [20, 25], tie (25, 28), outside [28, 30]; the red at 12 is sure
        for sev in ("must", "should"):
            for assume in (None, LA):
                for b in (spd(), spd(modes=["ALT_HOLD", "LOITER"])):          # the second: sure [10, 20), wide [10, 31)
                    with self.subTest(sev=sev, assume=assume, modes=b["scope"]["modes"]):
                        r = B.evaluate(B.validate(doc({**b, "severity": sev}, {**batt(), "id": "m"},
                                                      **({"assume": assume} if assume else {}))), log)[0]
                        code = V.outcome([r], allowlist.compare([r], [], dt.date(2026, 11, 11)), None, None)[0]
                        self.assertEqual((r["verdict"], code), (B.FAIL, 1))     # P4-a: blind as `absent` -> EI -> red
                        self.assertAlmostEqual(r["measured"], 5.0, places=5)
                        self.assertEqual(r["limit_in_log"]["at_worst"], 1.1 * 4.0)

    def test_p5_no_pass_while_any_sample_is_unjudged_each_cause_alone(self):
        for log, want in ((W((5.0, 4.0)), unjudged(52, "pre", 0, 5)),
                          (W(U4, (15.0, 4.0), rows=dropped(flight_rows(), 10)), unjudged(62, "unsure", 9, 15)),
                          (W(U4, (20.0, 60.0)), unjudged(102, "outside", 20, 30, 0)),
                          (W(U4, (20.0, 4.0), (20.0, 2.0)), unjudged(102, "tie", 20, 30))):
            with self.subTest(want):                       # P5-a mutant: unjudged samples skipped silently -> PASS -> red
                r = judge(spd(), log)
                self.assertEqual((r["verdict"], r["measured"]), (B.EI, None))
                self.assertIn(f"limit WP_SPD not usable on {want.split()[0]} sample(s): {want}", r["note"])
        self.assertEqual(judge(spd(), W(U4))["verdict"], B.PASS)          # control: the same log, one clean row

    def test_p7_loss_boundaries_are_closed(self):
        move = lambda frm, to: [(n, {**v, "TimeUS": to} if n == "DSF" and v["TimeUS"] == us(frm) else v) for n, v in flight_rows()]
        tick9, off = move(9, us(9) + 1), move(6, us(6.2))     # 7_200_000 us * 1e-6 < round(that, 6): a raw compare misses it
        for name, rows, want in (("b = p(t)", parm(dropped(flight_rows(), 10), U4, (10.0, 4.0)), unjudged(212, "unsure", 9, 30)),
                                 ("b = p(t) - TICK", parm(dropped(flight_rows(), 10), U4, (10.0, 4.0, 1)),
                                  unjudged(12, "unsure", 9, 10)),
                                 ("a = t; inside (p, t)", parm(dropped(flight_rows(), 10), U4, (20.0, 4.0)),
                                  unjudged(112, "unsure", 9, 20)),
                                 ("a = t + TICK", parm(dropped(tick9, 10), U4, (20.0, 4.0)), unjudged(110, "unsure", 9.2, 20)),
                                 ("a = t off the float grid", parm(dropped(off, 7), U4, (20.0, 4.0)), unjudged(140, "unsure", 6.2, 20))):
            with self.subTest(name):
                # mutants: P7-a `b >= p` -> `b > p`; P7-b `a <= t` -> `a < t`; P7-c the `b >= p` term dropped; P7-d the
                # `a <= t` term dropped; P7-e point test (an endpoint of [p, t] inside the loss); G-a raw times in the adapter -> red
                self.assertIn(want, judge(spd(), parse(rows))["note"])

    def test_p8_pre_first_row_without_the_key_is_unjudged_up_to_and_including_t1(self):
        r = judge(spd(), W((5.0, 4.0)))                   # samples at t < 5 and AT t = 5: 26 per instance
        self.assertEqual(r["verdict"], B.EI)              # P8-a mutant: `t <= T[0]` -> `t < T[0]` -> 50 -> red
        self.assertIn(unjudged(52, "pre", 0, 5), r["note"])

    def test_p9_pre_first_row_with_the_key_takes_the_first_rows_values(self):
        red = W((5.0, 4.0), (10.0, 5.0), rows=fast(flight_rows(), 3.0, 4.5))    # 4.5 > 1.1 x 4.0, < 1.1 x 5.0
        self.assertEqual(judge(spd(), red)["verdict"], B.EI)
        r = judge(spd(), red, LA)
        self.assertEqual((r["verdict"], r["limit_in_log"]["at_worst"]), (B.FAIL, 1.1 * 4.0))   # P9-a: later row -> PASS
        self.assertTrue(r["note"].startswith(f"limit 4.4 = 1.1 x WP_SPD 4 (PARM row at t={T0 + 5:.3f} s); n=302"), r["note"])
        at = dropped(flight_rows(), 5)                                       # loss [4, 5]
        r = judge(spd(), W((4.0, 4.0), rows=at), LA)                       # a = t1: removed
        self.assertEqual((r["verdict"], r["n"]), (B.PASS, 302))          # P9-b mutant: `a <= t1` -> `a < t1` -> EI -> red
        r = judge(spd(), W((4.0, 4.0, -1), rows=at), LA)                   # a = t1 + TICK: not removed
        self.assertEqual(r["verdict"], B.EI)                              # P9-c mutant: every loss removed -> PASS -> red
        self.assertIn(unjudged(262, "unsure", 4, 30), r["note"])

    def test_p10_every_value_at_a_timestamp_enters_c(self):
        r = judge(spd(), W(U4, (10.0, 2.0), (10.0, 4.0)))          # file order 2.0, 4.0: 1.1 x 2.0 < 3.0 < 1.1 x 4.0
        self.assertEqual(r["verdict"], B.EI)        # P10-a last index only -> PASS; P10-b split judged as VIOLATION -> red
        self.assertIn(unjudged(202, "tie", 10, 30), r["note"])
        r = judge(spd(), W(U4, (10.0, 60.0)))        # the row AT t enters C: the sample at 10.0 is unusable too
        self.assertIn(unjudged(202, "outside", 10, 30, 0), r["note"])   # P10-c mutant: C without {v : t_i = t} -> 200 -> red
        back = [("PARM", {"TimeUS": us(-0.3), "Name": "WP_SPD", "Value": 4.0}),
                ("PARM", {"TimeUS": us(-0.5), "Name": "WP_SPD", "Value": 2.0})] + flight_rows()   # file order != time order
        self.assertEqual(judge(spd(), parse(back))["verdict"], B.PASS)    # P10-d mutant: rows in file order -> FAIL -> red

    def test_p11_accept_is_closed(self):
        volt = lambda acc: {**bar("series_bound", {"channel": "battery.voltage_v", "bound": "floor", "limit": {
            "param": "BATT_LOW_VOLT", "scale": 0.5, "accept": acc}}), "provenance": {"text": "t", "param": "BATT_LOW_VOLT"}}
        bl = lambda v: parse(parm(flight_rows(), (-0.5, v), name="BATT_LOW_VOLT"))
        for v, acc, want in ((9.0, [9, 30], B.PASS), (30.0, [9, 30], B.PASS), (9.0, [9.000001, 30], B.EI),
                             (30.0, [9, 29.999999], B.EI)):
            with self.subTest(v=v, acc=acc):            # P11-a mutant: accept open `lo < v < hi` -> red
                self.assertEqual(judge(volt(acc), bl(v))["verdict"], want)
        r = judge({**volt([9, 30]), "params": {**volt([9, 30])["params"], "limit": {"param": "BATT_LOW_VOLT", "accept": [9, 30]}}}, bl(0.0))
        self.assertEqual(r["verdict"], B.EI)            # P11-b mutant: accept never checked -> floor 0 -> PASS -> red
        self.assertIn(unjudged(602, "outside", 0, 30, 0, "1"), r["note"])

    def test_p12_p13_one_limit_value_reads_as_the_literal_and_measured_is_the_smallest_margin(self):
        literal = bar("series_bound", {"channel": "velocity.groundspeed_mps", "bound": "ceiling", "limit": 4.4})
        for rows in (flight_rows(), fast(flight_rows(), 12.0), fast(fast(flight_rows(), 12.0, 4.0), 20.0, 4.0)):
            a, b = judge(literal, parse(rows)), judge(spd(), W(U4, rows=rows))
            self.assertEqual([a[k] for k in ("verdict", "n", "measured", "worst_instance")],
                             [b[k] for k in ("verdict", "n", "measured", "worst_instance")])
            self.assertNotIn("limit_in_log", a)
        huge = {**literal, "params": {**literal["params"], "limit": 1e17}}    # 1e17 - 3.0 == 1e17 - 3.0000002: margins tie
        r = judge(huge, parse(fast(flight_rows(), 12.0, 3.0000002)))
        self.assertEqual(r["measured"], struct.unpack("<f", struct.pack("<f", 3.0000002))[0])   # P12-a: scan order only -> red
        r = judge(spd(scale=None), W(U4, (15.0, 10.0), rows=fast(fast(flight_rows(), 5.0, 3.9), 20.0, 9.0)))
        self.assertEqual((r["verdict"], r["limit_in_log"]["at_worst"]), (B.PASS, 4.0))   # scale defaults to 1
        self.assertAlmostEqual(r["measured"], 3.9, places=5)    # P13-a mutant: the extreme x (9.0) -> red
        self.assertTrue(r["note"].startswith("limit 4 = 1 x WP_SPD 4 (PARM row at t=0.500 s); n=302"), r["note"])
        self.assertEqual(r["limit_in_log"]["rows"], [[0.5, 4.0], [16.0, 10.0]])
        many = judge(spd(), W(*((k, 4.0) for k in range(10))))
        self.assertEqual((many["limit_in_log"]["rows"][-1], many["limit_in_log"]["n_rows"]), ([8.0, 4.0], 10))   # X-c: first 8
        for r in (judge(spd(), W((5.0, 4.0))), judge(spd(modes=["AUTO"]), W(U4))):     # EI, NA
            self.assertEqual((r["measured"], r["limit_in_log"]["at_worst"]), (None, None))
            self.assertTrue(r["note"].startswith("n="), r["note"])

    def test_p15_dsf_absent_and_a_drop_is_judged_never_judged_across(self):
        no_dsf = [x for x in flight_rows() if x[0] != "DSF"]
        r = judge(spd(), W(U4, rows=no_dsf))
        self.assertEqual(r["verdict"], B.PASS)
        self.assertIn("DSF ABSENT", r["note"])                       # P15-a mutant: not scoped in _decide -> red
        r = judge(spd(), zeroed(parm(no_dsf, U4, (20.0, 4.0)), span=(12.0, 13.0))[0])
        self.assertEqual(r["verdict"], B.EI)
        self.assertIn(B.WHY["unsure"], r["note"])                     # P15-b mutant: holes left out of the losses -> red
        r = judge(spd(), W(U4, (12.0, 4.0), rows=dropped(flight_rows(), 11)))
        self.assertNotIn("judged across", r["note"])                  # P15-a again
        self.assertIn(unjudged(22, "unsure", 10, 12), r["note"])

    def test_p16_scoped_bars_fail_iff_the_sure_pass_fails(self):
        # LOITER [0, 3) and [10, end); the drop [0, 1] makes the mode unsure over [0, 3): sure [10, end), wide adds [0, 3).
        # The key removes it from the limit (a == t0); 1.1 x 4.0 up to t=3, 1.1 x 10.0 after: the wide pass is the tighter
        at = dropped(flight_rows(events=((0.0, "MODE", 5), (3.0, "MODE", 2), (10.0, "MODE", 5))), 1)
        loiter = spd(modes=["LOITER"])
        for t, want in ((25.0, B.FAIL), (1.0, B.EI), (None, B.PASS)):
            with self.subTest(t=t):
                r = judge(loiter, W((2.0, 4.0), (3.0, 10.0), rows=fast(at, t, 12.0) if t else at), LA)
                self.assertEqual(r["verdict"], want)
        self.assertEqual((r["measured"], r["limit_in_log"]["at_worst"]), (3.0, 1.1 * 4.0))   # P16-a: wide's limit not quoted
        self.assertTrue(r["note"].startswith(f"limit 4.4 = 1.1 x WP_SPD 4 (PARM row at t={T0 + 2:.3f} s)"), r["note"])
        self.assertIn("wide scope (quoted)", r["note"])
        ev = ((0.0, "MODE", 0), (5.0, "ARM", 1), (10.0, "ARM", 0), (20.0, "ARM", 1))      # arming unsure over [12, 21)
        rows = lambda t: parm(dropped(fast(flight_rows(events=ev), t), 13), U4, (13.5, 4.0))
        for t, want in ((25.0, B.FAIL), (14.0, B.EI)):
            with self.subTest(armed=t):
                self.assertEqual(judge(spd(armed=True), parse(rows(t)), AS)["verdict"], want)

    def test_p14_the_key_and_its_detail(self):
        for kw, why in (({"assume": LA * 2}, "duplicate"), ({"assume": ["limit_before_first_row"]}, "is not one of")):
            with self.subTest(why=why), self.assertRaisesRegex(Refusal, why):
                B.validate(doc(spd(), **kw))
        for bars, assume, text in (((batt(),), LA, "['limit_before_first_parm_row'] is an assumption no bar uses (no bar's "
                                    "limit follows a parameter)"),
                                   ((ARMED,), AS + LA, "['limit_before_first_parm_row'] is an assumption no bar uses (no bar's "
                                    "limit follows a parameter)"),
                                   ((spd(),), AS + LA, "['arming_before_first_arm_row'] is an assumption no bar uses (no bar "
                                    "has scope.armed: true)"),
                                   ((batt(),), AS, "['arming_before_first_arm_row'] is an assumption no bar uses (no bar has "
                                    "scope.armed: true)")):      # the last: 0.2.0's text, byte for byte
            with self.subTest(text=text):
                with self.assertRaises(Refusal) as cm:
                    B.validate(doc(*bars, assume=assume))
                self.assertEqual(str(cm.exception), f"bars file.assume: {text}")
        two = [spd(), {**spd(), "id": "c", "params": {**spd()["params"], "limit": {"param": "WPNAV_SPEED", "accept": [0, 9]}},
                       "provenance": {"text": "t"}}]
        bars = B.validate(doc(*two, assume=LA))
        got = B.assumptions(bars, W((4.0, 4.0), rows=dropped(flight_rows(), 5)))
        self.assertEqual([(x["name"], x["applied"], x["detail"]) for x in got],
                         [(LA[0], True, f"WP_SPD: first PARM row at t={T0 + 4:.3f} s; removed 3 firmware-dropped writes in "
                                        f"[{T0 + 4:.3f}, {T0 + 5:.3f}] s (DSF.Dp) | WPNAV_SPEED: no PARM row")])
        self.assertEqual(list(got[0]), ["name", "text", "applied", "detail"])
        self.assertFalse(B.assumptions(bars, parse(flight_rows()))[0]["applied"])

    def test_no_row_is_ei(self):
        r = judge(spd(), parse(flight_rows()))
        self.assertEqual((r["verdict"], r["note"]), (B.EI, "n=0; limit parameter WP_SPD has no PARM row in this log"))

    def test_p18_a_non_finite_row_hides_only_the_samples_it_could_judge(self):
        log = W(U4, (20.0, float("nan")), rows=fast(flight_rows(), 10.0, 9.0))    # 9.0 > 1.1 x 4.0 before the NaN row
        for sev in ("should", "must"):
            r = B.evaluate(B.validate(doc({**spd(), "severity": sev}, {**batt(), "id": "m"})), log)[0]
            code = V.outcome([r], allowlist.compare([r], [], dt.date(2026, 11, 11)), None, None)[0]
            self.assertEqual((r["verdict"], code), (B.FAIL, 1))     # P18-a mutant: the v2 whole-bar EI -> red
        r = judge(spd(), W(U4, (20.0, float("nan"))))
        self.assertEqual(r["verdict"], B.EI)                         # P18-b mutant: the NaN row skipped -> PASS -> red
        self.assertIn(unjudged(102, "nonfinite", 20, 30), r["note"])
        self.assertEqual((r["limit_in_log"]["rows"], r["limit_in_log"]["n_rows"]), ([[0.5, 4.0], [21.0, None]], 2))
        r = judge(spd(), W((20.0, float("nan"))))                     # only a non-finite row: P is not empty
        self.assertIn(unjudged(202, "pre", 0, 20), r["note"])

    def test_p19_the_limit_key_touches_no_mode_or_arming_judgement(self):
        ev = ((0.0, "MODE", 0), (0.5, "ARM", 1), (10.0, "MODE", 2), (20.0, "MODE", 5), (25.0, "ARM", 1))
        log = parse(dropped(dropped(parm(flight_rows(events=ev), U4), 5), 15))         # losses [4, 5] and [14, 15]
        lit = [batt(modes=["LOITER"]), batt(armed=True), batt(armed=True, modes=["LOITER"]), MODES,
               gnss(modes=["ALT_HOLD"]), bar("no_events", {"kinds": ["error"]}, modes=["ALT_HOLD"])]
        lit = [{**b, "id": f"b{i}"} for i, b in enumerate(lit)]
        for arm in ([], AS):
            with self.subTest(arm=arm):   # P19-a mutant: the key's removal fed into `lost` (mode/arming) -> red
                bare, keyed = (B.validate(doc(spd(), *lit, **({"assume": arm + x} if arm + x else {}))) for x in ([], LA))
                self.assertEqual(json.dumps(B.evaluate(bare, log)[1:]), json.dumps(B.evaluate(keyed, log)[1:]))
                if arm:
                    self.assertEqual(json.dumps(B.assumptions(bare, log)), json.dumps(B.assumptions(keyed, log)[:1]))

    def test_p20_p21_p22_which_losses_the_key_removes(self):
        r = judge(spd(), zeroed(parm(flight_rows(), (4.0, 4.0)), span=(2.0, 3.0))[0], LA)       # a hole in [t0, t1]
        self.assertEqual(r["verdict"], B.EI)               # P20-a mutant: the key removes log holes too -> PASS -> red
        self.assertIn(f"{B.WHY['unsure']}, t in [{T0:.3f}, {T0 + 4:.3f}] s", r["note"])   # P20-b: pre never unsure -> red
        r = judge(spd(), W((4.0, 4.0), rows=dropped(flight_rows(), 3)), LA)   # a DSF interval there: removed, judged
        self.assertEqual((r["verdict"], r["n"]), (B.PASS, 302))
        r = judge(spd(), W(U4, rows=dropped(flight_rows(), 1)), LA)    # row before t0; first interval [t0, 1]: removed
        self.assertEqual((r["verdict"], r["n"]), (B.PASS, 302))       # P21-a mutant: `or a == t0` dropped -> EI -> red
        self.assertEqual(judge(spd(), W(U4, rows=dropped(flight_rows(), 1)))["verdict"], B.EI)    # no key: judged
        for extra, want, applied in ((0, B.PASS, True), (1, B.EI, False)):     # t1 - t0 = 5.0 s; 5.0 s + TICK
            with self.subTest(extra=extra):                # P22-a mutant: `<= PARM_DUMP_S` -> `<` -> red
                log = W((5.0, 4.0, extra))
                self.assertEqual(judge(spd(), log, LA)["verdict"], want)
                a = B.assumptions(B.validate(doc(spd(), assume=LA)), log)[0]
                self.assertEqual((a["applied"], a["detail"].endswith("first row more than 5 s after the log's start: "
                                                                      "not applied")), (applied, not applied))

    def test_p23_disclosure_and_the_provenance_refusal(self):
        r = judge(spd(), W((4.0, 4.0), rows=dropped(flight_rows(), 3)), LA)
        self.assertIn(f"3 firmware-dropped writes in [{T0 + 2:.3f}, {T0 + 3:.3f}] s (DSF.Dp), not located; judged across",
                      r["note"])                           # P23-a mutant: no D5 note for a removed drop -> red
        r = judge(spd(accept=(2, 50)), W(U4, (20.0, 1.0)))   # 1.0 outside accept; 3.0 > 1.1 x 1.0, but at t=20 C has 4.0 too
        self.assertIn(unjudged(102, "outside", 20, 30, 100), r["note"])   # P23-b mutant: break count not counted -> red
        with self.assertRaises(Refusal) as cm:
            B.validate(doc({**spd(), "provenance": {"text": "t", "param": "WPNAV_SPEED"}}))
        self.assertEqual(str(cm.exception), "bar b: provenance.param 'WPNAV_SPEED' differs from the limit's parameter 'WP_SPD'")


DOC = """schema: swathkeeper-bars/1.0
contract: {contract}
bars:
  - id: batt
    kind: series_bound
    severity: {severity}
    provenance: {{text: t}}
    scope: {{armed: {armed}, modes: {modes}}}
    min_n: {min_n}
    params: {{channel: battery.voltage_v, bound: floor, limit: {limit}}}
"""
GOOD = {"contract": "swathkeeper-flightlog/1.0", "severity": "must", "armed": "null", "modes": "null", "min_n": 1, "limit": 18.6}


def load(text=None, **kw):
    return B.validate(B.load_yaml(text or DOC.format(**{**GOOD, **kw}), "bars"))


class TestLoader(unittest.TestCase):
    def test_the_template_loads(self):
        self.assertEqual(load()[0]["params"]["limit"], 18.6)

    def test_each_malformed_value_refuses(self):
        for kw, why in (({"limit": "1e3"}, "not a finite number"), ({"limit": ".nan"}, "plain decimal"),
                        ({"limit": "yes"}, "not a finite number"), ({"min_n": 0}, r"integer in \[1"),
                        ({"min_n": 1.5}, "integer"), ({"modes": "[NO]"}, "non-empty string"),
                        ({"modes": "[]"}, "at least 1"), ({"armed": "false"}, "true or null"), ({"armed": 1}, "true or null"),
                        ({"severity": "should"}, "zero `must`"), ({"contract": "swathkeeper-flightlog/2.0"}, "major"),
                        ({"contract": "swathkeeper-flightlog/1.9"}, "this tool speaks"),                     # G249
                        ({"modes": '["*"]'}, "only for mode_transitions"), ({"modes": "[<start>]"}, "only for"),  # G239
                        *(({"limit": x}, "plain decimal") for x in ("022", "18:36", "0x12", "1_8.6", ".inf")),   # G236
                        ({"min_n": "030"}, "plain decimal")):
            with self.subTest(kw=kw), self.assertRaisesRegex(Refusal, why):   # mutants: number() takes str/bool; min_n lo 0
                load(**kw)

    def test_a_duplicate_key_unknown_key_or_bad_pairing_refuses(self):
        text = DOC.format(**GOOD)
        poly = "[[0, 0], [0, 1], [1, 1], [1, 0]]"
        bowtie = "[[0, 0], [1, 1], [1, 0], [0, 1]]"
        geo = lambda params: text.replace("kind: series_bound", "kind: containment").replace(
            "{channel: battery.voltage_v, bound: floor, limit: 18.6}", params)
        for bad, why in ((text.replace("limit: 18.6", "limit: 18.6, limit: 0"), "duplicate"),   # mutant: plain SafeLoader
                         (text + "schema: swathkeeper-bars/1.0\n", "duplicate"),
                         (text.replace("min_n: 1", "min_n: 1\n    stat: max"), "unknown keys"),
                         (text + text[text.index("  - id"):], "duplicate id"),
                         (text[:text.index("bars:")] + "bars: []\n", "at least 1"),
                         (text.replace("kind: series_bound", "kind: mode_transitions").replace(
                             "{channel: battery.voltage_v, bound: floor, limit: 18.6}", "{allowed: [[STABILIZE, <start>]]}"),
                          "only ever a `from`"),                                                         # Q15
                         (geo("{source: yaml}"), "needs a polygon"), (geo(f"{{source: log, polygon: {poly}}}"), "needs a polygon"),
                         (geo("{source: log, alt_max_rel_home_m: 5}"), "FENCE_"),                         # Q16
                         (geo(f"{{source: yaml, polygon: {poly}, alt_max_m: 5}}"), "unknown keys"),       # G254
                         (geo(f"{{source: yaml, polygon: {bowtie}}}"), "intersects itself")):             # G247
            with self.subTest(why=why), self.assertRaisesRegex(Refusal, why):
                load(bad)
        load(geo(f"{{source: yaml, polygon: {poly}, alt_max_rel_home_m: 5}}"))

    def test_p3_a_limit_mapping_and_each_of_its_refusals(self):
        self.assertEqual(load(limit="{param: WP_SPD, accept: [9, 9]}")[0]["params"]["limit"], {"param": "WP_SPD", "accept": [9, 9]})
        load(limit="{param: ABCDEFGHIJKLMNOP, scale: 0.01, accept: [0, 2000]}")              # 16 characters
        w = "bar batt.params.limit"
        for limit, text in (("[1, 2]", f"{w}: [1, 2] is not a finite number or a mapping {{param, scale?, accept}}"),
                            ("{param: wp_spd, accept: [0, 1]}", f"{w}.param: 'wp_spd' is not a parameter name of [A-Z][A-Z0-9_]{{0,15}}"),
                            ("{param: ABCDEFGHIJKLMNOPQ, accept: [0, 1]}",
                             f"{w}.param: 'ABCDEFGHIJKLMNOPQ' is not a parameter name of [A-Z][A-Z0-9_]{{0,15}}"),
                            ("{param: WP_SPD, scale: 0, accept: [0, 1]}", f"{w}.scale: 0 is not a finite number > 0"),
                            ("{param: WP_SPD, scale: -1.5, accept: [0, 1]}", f"{w}.scale: -1.5 is not a finite number > 0"),
                            ("{param: WP_SPD, scale: yes, accept: [0, 1]}", f"{w}.scale: True is not a finite number > 0"),
                            ("{param: WP_SPD, accept: [30, 9]}", f"{w}.accept: low 30 > high 9"),
                            ("{param: WP_SPD}", f"{w}: missing keys ['accept'], unknown keys []"),
                            ("{param: WP_SPD, accept: [0, 1], offset: 1}", f"{w}: missing keys [], unknown keys ['offset']"),
                            ("{param: WP_SPD, accept: [1]}", f"{w}.accept: expected a list of 2, got [1]"),
                            ("{param: WP_SPD, accept: [x, 1]}", f"{w}.accept[0]: 'x' is not a finite number in [None, None]")):
            with self.subTest(limit=limit):
                with self.assertRaises(Refusal) as cm:
                    load(limit=limit)
                self.assertEqual(str(cm.exception), text)
        m = "{param: WP_SPD, accept: [0, 1]}"          # a mapping is legal ONLY at series_bound.params.limit
        text = DOC.format(**GOOD)
        for bad in (text.replace("min_n: 1", f"min_n: {m}"),
                    text.replace("kind: series_bound", "kind: gnss_quality").replace(
                        "{channel: battery.voltage_v, bound: floor, limit: 18.6}", f"{{fix_min: 3, sats_min: 6, max_outage_s: {m}}}"),
                    text.replace("kind: series_bound", "kind: containment").replace(
                        "{channel: battery.voltage_v, bound: floor, limit: 18.6}",
                        f"{{source: yaml, polygon: [[0, 0], [0, 1], [1, 1]], alt_max_rel_home_m: {m}}}")):
            with self.assertRaisesRegex(Refusal, "is not a finite (integer|number) in"):
                load(bad)

    def test_a_mode_name_must_be_in_the_resolved_vehicles_table(self):
        clean = parse(flight_rows())
        B.check_modes(load(modes="[LOITER]"), clean)
        for name in ("LOITR", "FBWA"):                       # a typo; a Plane name on a Copter
            with self.assertRaisesRegex(Refusal, name):      # mutant: check_modes a no-op -> red
                B.check_modes(load(modes=f"[{name}]"), clean)


if __name__ == "__main__":
    unittest.main()
