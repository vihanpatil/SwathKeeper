"""`eval/point_mass.py` + `eval/replay_point_mass.py` — the offline confound-resolver (ADR-016).

TWO SUITES IN ONE FILE, because they fail for two different reasons and a reader needs to know
which:

  * THE MODEL, against CLOSED FORMS. A point-mass integrator is the kind of code that is quietly
    wrong by a factor of two and still looks plausible on a plot. Every dynamic claim this study
    makes rests on it, so it is pinned against hand-integrable cases: zero elapsed time gives zero
    displacement, a jerk-limited start gives j*t^3/6, an accel-saturated start gives a*t^2/2, a
    velocity-capped run goes linear, and a long window converges to the commanded point and STAYS
    there (a controller that overshoots forever would make every counterfactual optimistic).

  * THE CONFOUND SEPARATION, against synthesised encounters whose answer is known by construction.
    These are the properties that make the study's verdicts mean anything: a DEFERRED encounter
    (the vehicle stops short of a static obstacle and never passes it) must not be counted as a
    clearance; a window too short to separate the hypotheses must report EVIDENCE INSUFFICIENT
    rather than pick one; the static demo-bird shim must produce the same CPA number the real gate
    produces on the same path; and the ADR-017 speed sweep must report "no safe speed" as itself
    instead of interpolating a comfortable one.

Lives in tests/ (not tests/fieldguard_planning/) like test_ci_evidence_gate.py and
test_fly_pipeline.py: it tests host-side study tooling under eval/, not the planning package.
stdlib unittest, so it runs under `python3 -m pytest tests -q` and `python3 -m unittest` alike.
"""
import io
import json
import math
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

import point_mass as PM  # noqa: E402
import replay_point_mass as RP  # noqa: E402


def _far_target(direction, distance=1e6):
    """A target so distant that the sqrt controller always demands the velocity cap -- isolating the
    accel/jerk limits from the arrival behaviour."""
    return (direction[0] * distance, direction[1] * distance, 0.0)


# =================================================================================== the plant
class TestPointMassClosedForms(unittest.TestCase):
    def setUp(self):
        # An accel-limited plant whose jerk ramp is short but RESOLVED by the integrator (a_max is
        # reached in 0.01 s = two integration steps). A literally infinite jerk would ask the model
        # to represent a discontinuity inside one step, which is a statement about the integrator
        # rather than about the plant.
        self.accel_limited = PM.PlantLimits(name="t", v_max_ne_mps=100.0, a_max_ne_mps2=2.0,
                                            jerk_ne_mps3=200.0, v_max_up_mps=5.0,
                                            v_max_down_mps=5.0, a_max_u_mps2=2.0,
                                            jerk_u_mps3=200.0, pos_p=1.0, provenance="test")

    def test_zero_elapsed_time_gives_zero_displacement(self):
        """The zero-lead case, which the counterfactual sweep leans on: an escape commanded with no
        time to execute moves the vehicle exactly nowhere."""
        out = PM.simulate((0.0, 0.0, 15.0), (0.0, 0.0, 0.0), [(0.0, (100.0, 0.0, 15.0))],
                          0.0, 0.0, self.accel_limited)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[-1][1], (0.0, 0.0, 15.0))
        self.assertAlmostEqual(PM.max_displacement_m(0.0, self.accel_limited), 0.0)

    def test_accel_limited_short_window_matches_half_a_t_squared(self):
        """From rest, once the acceleration has saturated, displacement is a*t^2/2 -- the textbook
        case and the one the 0.434 s GUIDED window lives in. The simulation is pinned against the
        closed form exactly (both model the same jerk ramp) and against the textbook a*t^2/2 to
        within the ramp's own cost, which shrinks as t grows."""
        lim = self.accel_limited
        for t in (0.1, 0.25, 0.5, 1.0):
            out = PM.simulate((0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                              [(0.0, _far_target((1.0, 0.0)))], 0.0, t, lim, sample_times=[t])
            closed = PM.max_displacement_m(t, lim)
            self.assertAlmostEqual(out[-1][1][0], closed, delta=1e-4, msg=f"t={t}")
            textbook = 0.5 * lim.a_max_ne_mps2 * t * t
            self.assertAlmostEqual(closed, textbook, delta=0.11 * textbook, msg=f"t={t}")
        # The ramp's cost is a fixed displacement deficit, so the AGREEMENT improves with time.
        near = 1.0 - PM.max_displacement_m(0.1, lim) / (0.5 * 2.0 * 0.1 ** 2)
        far = 1.0 - PM.max_displacement_m(1.0, lim) / (0.5 * 2.0 * 1.0 ** 2)
        self.assertLess(far, near)

    def test_jerk_limited_start_matches_j_t_cubed_over_six(self):
        """Before the acceleration saturates, displacement is j*t^3/6. This is the regime that
        actually governs a sub-second dodge at PSC_NE_JERK 5 m/s^3, so getting it wrong would
        mis-price every lead-time answer in the study."""
        jerky = PM.PlantLimits(name="j", v_max_ne_mps=100.0, a_max_ne_mps2=100.0,
                               jerk_ne_mps3=5.0, v_max_up_mps=5.0, v_max_down_mps=5.0,
                               a_max_u_mps2=2.0, jerk_u_mps3=5.0, pos_p=1.0, provenance="test")
        for t in (0.1, 0.2, 0.4):
            out = PM.simulate((0.0, 0.0, 0.0), (0.0, 0.0, 0.0),
                              [(0.0, _far_target((1.0, 0.0)))], 0.0, t, jerky, sample_times=[t])
            expect = jerky.jerk_ne_mps3 * t ** 3 / 6.0
            self.assertAlmostEqual(out[-1][1][0], expect, delta=max(1e-6, 0.005 * expect),
                                   msg=f"t={t}")
            self.assertAlmostEqual(PM.max_displacement_m(t, jerky), expect, delta=1e-9)

    def test_velocity_cap_makes_displacement_linear_in_time(self):
        capped = PM.PlantLimits(name="c", v_max_ne_mps=2.0, a_max_ne_mps2=100.0,
                                jerk_ne_mps3=1e4, v_max_up_mps=5.0, v_max_down_mps=5.0,
                                a_max_u_mps2=2.0, jerk_u_mps3=1e4, pos_p=1.0, provenance="test")
        d1 = PM.max_displacement_m(5.0, capped)
        d2 = PM.max_displacement_m(10.0, capped)
        self.assertAlmostEqual(d2 - d1, capped.v_max_ne_mps * 5.0, delta=0.02)
        out = PM.simulate((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), [(0.0, _far_target((1.0, 0.0)))],
                          0.0, 10.0, capped, sample_times=[10.0])
        self.assertAlmostEqual(out[-1][1][0], d2, delta=0.05)

    def test_long_window_converges_to_the_commanded_point_and_stays(self):
        """A controller that reaches the setpoint and then oscillates would hand the counterfactual
        sweep free clearance, so arrival AND settling are both pinned."""
        target = (10.0, -4.0, 20.0)
        out = PM.simulate((0.0, 0.0, 15.0), (0.0, 0.0, 0.0), [(0.0, target)],
                          0.0, 60.0, PM.GUIDED_DEFAULT, sample_times=[20.0, 40.0, 60.0])
        for t, p in out[1:]:
            self.assertAlmostEqual(math.dist(p, target), 0.0, delta=0.01,
                                   msg=f"not settled at t={t}: {p}")

    def test_the_approach_does_not_limit_cycle(self):
        """The regression for the bug that a naive `(v_des - v)/dt` accel demand produces: bang-bang
        acceleration that a 5 m/s^3 jerk limit cannot reverse in time, so the vehicle oscillates
        around the setpoint forever. Measured before the fix: overshoot to 13.7 m on a 10.8 m
        command and +/-0.5 m still swinging at t = 20 s. A counterfactual sweep run on that model
        would have harvested clearance out of chatter."""
        target = (10.0, -4.0, 15.0)
        out = PM.simulate((0.0, 0.0, 15.0), (0.0, 0.0, 0.0), [(0.0, target)],
                          0.0, 30.0, PM.GUIDED_DEFAULT, sample_dt_s=0.05)
        reach = math.dist((0.0, 0.0, 15.0), target)
        peak = max(math.dist((0.0, 0.0, 15.0), p) for _t, p in out)
        self.assertLess(peak, 1.10 * reach, "overshoot beyond 10 % is chatter, not damping")
        tail = [math.dist(p, target) for t, p in out if t >= 15.0]
        self.assertLess(max(tail), 0.01, "still moving 15 s after a 10 m command")

    def test_entry_velocity_must_be_arrested_before_the_vehicle_reverses(self):
        """The single most load-bearing behaviour for Q1: told to fly 10 m BACKWARDS at cruise, the
        vehicle first overshoots by roughly v^2/(2a). Pinned loosely (the sqrt controller does not
        demand full authority immediately) but tightly enough to catch a sign error."""
        v = 9.0
        out = PM.simulate((0.0, 0.0, 15.0), (0.0, v, 0.0), [(0.0, (0.0, -10.0, 15.0))],
                          0.0, 12.0, PM.GUIDED_DEFAULT, sample_dt_s=0.05)
        overshoot = max(p[1] for _t, p in out)
        ballistic = v * v / (2.0 * PM.GUIDED_DEFAULT.a_max_ne_mps2)
        self.assertGreater(overshoot, 0.5 * ballistic)
        self.assertLess(overshoot, 2.0 * ballistic)
        settled = PM.simulate((0.0, 0.0, 15.0), (0.0, v, 0.0), [(0.0, (0.0, -10.0, 15.0))],
                              0.0, 45.0, PM.GUIDED_DEFAULT, sample_times=[45.0])
        self.assertAlmostEqual(settled[-1][1][1], -10.0, delta=0.05)

    def test_horizontal_accel_is_a_shared_vector_budget(self):
        """A dodge that also demands a stop gets less lateral acceleration than one that does not --
        the effect the `sidestep_ahead` candidate exists to measure. If the axes were shaped
        independently this test fails, and the sweep's candidate ranking would be wrong."""
        lim = PM.GUIDED_DEFAULT
        t = 1.0
        stop_and_dodge = PM.simulate((0.0, 0.0, 15.0), (0.0, 9.0, 0.0), [(0.0, (-10.0, 0.0, 15.0))],
                                     0.0, t, lim, sample_times=[t])
        dodge_only = PM.simulate((0.0, 0.0, 15.0), (0.0, 0.0, 0.0), [(0.0, (-10.0, 0.0, 15.0))],
                                 0.0, t, lim, sample_times=[t])
        self.assertLess(abs(stop_and_dodge[-1][1][0]), abs(dodge_only[-1][1][0]))

    def test_no_limit_is_ever_exceeded(self):
        """Property check over a coarse random-ish grid of targets: speed, accel and jerk stay
        inside the plant on every step. A limiter that leaks is a model that flatters escapes."""
        lim = PM.GUIDED_DEFAULT
        veh = PM.PointMass((0.0, 0.0, 15.0), (3.0, -4.0, 0.0), lim)
        dt = 0.01
        prev_a = (0.0, 0.0)
        for i in range(1200):
            target = (12.0 * math.cos(i / 37.0), 12.0 * math.sin(i / 23.0), 15.0 + 5.0 * (i % 3))
            veh.step(dt, target)
            self.assertLessEqual(math.hypot(veh.vel[0], veh.vel[1]), lim.v_max_ne_mps + 1e-6)
            self.assertLessEqual(math.hypot(veh.acc[0], veh.acc[1]), lim.a_max_ne_mps2 + 1e-6)
            self.assertLessEqual(math.hypot(veh.acc[0] - prev_a[0], veh.acc[1] - prev_a[1]),
                                 lim.jerk_ne_mps3 * dt + 1e-6)
            self.assertLessEqual(veh.vel[2], lim.v_max_up_mps + 1e-6)
            self.assertGreaterEqual(veh.vel[2], -lim.v_max_down_mps - 1e-6)
            prev_a = (veh.acc[0], veh.acc[1])

    def test_time_to_displace_inverts_max_displacement(self):
        for lim in PM.PLANTS:
            for d in (0.5, 3.0, 12.0):
                t = PM.time_to_displace_s(d, lim)
                self.assertIsNotNone(t)
                self.assertAlmostEqual(PM.max_displacement_m(t, lim), d, delta=1e-3)

    def test_sqrt_controller_is_continuous_at_the_linear_join(self):
        """The join between the linear and sqrt branches is where an off-by-one-half hides."""
        a, p = 2.5, 1.0
        join = a / (p * p)
        lo = PM.sqrt_controller(join - 1e-7, p, a)
        hi = PM.sqrt_controller(join + 1e-7, p, a)
        self.assertAlmostEqual(lo, hi, delta=1e-4)
        self.assertAlmostEqual(PM.sqrt_controller(-4.0, p, a), -PM.sqrt_controller(4.0, p, a))

    def test_plant_constants_match_the_pinned_ardupilot_defaults(self):
        """A guard on the doctrine, not on arithmetic: these are the numbers that actually flew, and
        an edit to one of them changes every verdict in the study. Each carries its source in
        eval/point_mass.py's comments; if one has to change here, the URL there must be re-read."""
        self.assertEqual(PM.GUIDED_DEFAULT.v_max_ne_mps, 10.0)     # WPNAV_SPD
        self.assertEqual(PM.GUIDED_DEFAULT.a_max_ne_mps2, 2.5)     # WPNAV_ACC
        self.assertEqual(PM.GUIDED_DEFAULT.jerk_ne_mps3, 5.0)      # PSC_NE_JERK
        self.assertEqual(PM.GUIDED_DEFAULT.v_max_up_mps, 2.5)      # WPNAV_SPD_UP
        self.assertEqual(PM.GUIDED_DEFAULT.a_max_u_mps2, 1.0)      # WPNAV_ACC_Z
        self.assertEqual(PM.POSCONTROL_BARE.v_max_ne_mps, 5.0)     # POSCONTROL_SPEED_MS
        self.assertEqual(PM.POSCONTROL_BARE.a_max_ne_mps2, 1.0)    # POSCONTROL_ACCEL_NE_MSS
        self.assertEqual(PM.ANGLE_MAX_DEG, 30.0)                   # ANGLE_MAX
        self.assertAlmostEqual(PM.ANGLE_MAX_CEILING.a_max_ne_mps2, 9.80665 * math.tan(math.pi / 6),
                               places=9)
        for lim in PM.PLANTS:
            self.assertTrue(lim.provenance.strip(), f"{lim.name} has no provenance")


# ====================================================================== the confound separation
def _synth_encounter(*, path, setpoints, takeover=1, resume=None, bird=(30.0, 30.0, 15.0),
                     dt=0.2, params=None):
    """A flight log in memory: a flown path, a GUIDED window, and a static demo bird -- exactly the
    shape of the two historical logs, so the study's own loaders and shims are exercised."""
    resume = resume if resume is not None else len(path)
    params = params or {"min_bird_clearance_m": 3.0, "divert_distance_m": 10.0,
                        "cruise_alt_m": 15.0, "threat_radius_m": 12.0, "vertical_threat_m": 6.0,
                        "lateral_tree_margin_m": 0.0, "field_margin_m": 1.0,
                        "alt_bounds": [2.0, 30.0]}
    events = [{"kind": "takeover", "tick": takeover, "from_mode": "AUTO", "to_mode": "GUIDED"},
              {"kind": "resume", "tick": resume, "trigger": "threat_cleared"}]
    for tick, sp in setpoints:
        events.append({"kind": "maneuver", "tick": tick, "decision": "divert",
                       "setpoint_enu": list(sp), "verdict": "accepted",
                       "debug": {"params": dict(params)}})
        events.append({"kind": "detection", "tick": tick, "track_id": "demo_bird_0",
                       "position_enu": list(bird), "confidence": 1.0, "source": "ndvi_blob"})
    log = {"events": events, "flown_path_enu": [list(p) for p in path]}
    enc = RP.Encounter(stem="synthetic", path=Path("synthetic.json"), log=log,
                       schema_version=None, flown_path=[tuple(p) for p in path],
                       measured_stamps=None, takeover_tick=takeover, resume_tick=resume,
                       maneuvers=[(t, tuple(sp)) for t, sp in setpoints], params=dict(params),
                       truth_kind="", truth=None)
    axis = {"label": f"assumed_dt_{dt:.2f}s", "kind": "assumed", "dt_s": dt,
            "times": [i * dt for i in range(len(path))], "source": "synthetic"}
    RP.attach_truth(enc, axis["times"])
    return enc, axis


class TestStaticBirdShim(unittest.TestCase):
    def test_shim_reproduces_the_real_gates_cpa_on_the_same_path(self):
        """The demo-bird shim exists so the historical flights go through
        `check_live_flight_log.ground_truth_cpa` rather than a second CPA routine. If it did not
        agree with a direct point-to-segment computation on the same path, every historical number
        in the study would be from a private implementation."""
        path = [(30.0, y, 15.0) for y in range(20, 41)]
        enc, axis = _synth_encounter(path=path, setpoints=[(1, (30.0, 10.0, 15.0))])
        rep = RP.cpa_of([(axis["times"][i], path[i]) for i in range(len(path))],
                        enc.truth, enc.params)
        self.assertAlmostEqual(rep["gt_cpa_m"], 0.0, delta=1e-6)   # flies straight through (30,30)
        off = [(31.5, float(y), 15.0) for y in range(20, 41)]
        rep2 = RP.cpa_of([(axis["times"][i], off[i]) for i in range(len(off))],
                         enc.truth, enc.params)
        self.assertAlmostEqual(rep2["gt_cpa_m"], 1.5, delta=1e-6)

    def test_the_two_cpa_paths_in_this_repo_agree_on_one_flown_path(self):
        """The study scores counterfactuals with `ground_truth_cpa`; the safety gate's legacy path
        scores demo-bird flights with `closest_approach`. Until the gate's C1 fix (2026-08-25) the
        second sampled VERTICES and the first walked SEGMENTS, so the same flight had two CPAs and
        the optimistic one was the published one. Both now walk the polyline, and this pins the
        agreement so it cannot silently re-open -- a property, not a hard-coded number, so it stays
        true whichever value the geometry yields.

        Deliberately a fly-THROUGH between two samples: that is the only configuration where the
        vertex and segment answers differ, so a test on a path that passes near a vertex would
        agree either way and prove nothing."""
        path = [(30.0, 20.0, 15.0), (30.0, 40.0, 15.0)]          # bird at (30,30) sits mid-segment
        enc, axis = _synth_encounter(path=path, setpoints=[(1, (30.0, 10.0, 15.0))],
                                     takeover=1, resume=2)
        mine = RP.cpa_of([(axis["times"][i], path[i]) for i in range(len(path))],
                         enc.truth, enc.params)["gt_cpa_m"]
        theirs = RP.gate.closest_approach(enc.log)
        self.assertIsNotNone(theirs, "the synthetic log must carry detections for the legacy path")
        self.assertAlmostEqual(mine, theirs[0], delta=1e-6,
                               msg="the study's CPA and the safety gate's legacy CPA must not "
                                   "diverge on the same flown path")
        self.assertAlmostEqual(mine, 0.0, delta=1e-6, msg="this fixture IS a fly-through")

    def test_shim_refuses_a_moving_demo_bird(self):
        """Averaging two detection positions into one 'static' bird would be a silent lie; the shim
        refuses and points at the real truth track instead."""
        log = {"events": [{"kind": "detection", "tick": 1, "position_enu": [30, 30, 15]},
                          {"kind": "detection", "tick": 2, "position_enu": [31, 30, 15]}]}
        with self.assertRaises(ValueError) as ctx:
            RP.StaticBirdTruth.from_log(log, (0.0, 10.0))
        self.assertIn("MOVING", str(ctx.exception))

    def test_shim_answers_nothing_outside_its_span(self):
        shim = RP.StaticBirdTruth("demo_bird_0", (30.0, 30.0, 15.0), (5.0, 10.0))
        self.assertIsNone(shim.candidates_at(4.99))
        self.assertIsNone(shim.candidates_at(10.01))
        self.assertIsNotNone(shim.candidates_at(7.0))


class TestDeferralIsNotClearance(unittest.TestCase):
    """The property that keeps the counterfactual sweep honest."""

    # Drone flies north up lane x=30 at 3 m/s toward a static bird at (30, 20, 15); GUIDED opens at
    # tick 20 (y ~ 11.4), 8.6 m short of it. A 10 m reversal makes the vehicle retreat and never get
    # past -- large CPA, encounter DEFERRED. A forward sidestep takes it past at ~10 m offset --
    # encounter RESOLVED. Both must be classified correctly by the same sweep.
    PATH = [(30.0, 0.6 * i, 15.0) for i in range(60)]
    KW = dict(path=PATH, setpoints=[(20, (30.0, PATH[19][1] - 10.0, 15.0))],
              takeover=20, resume=60, bird=(30.0, 20.0, 15.0))

    def test_stopping_short_of_a_static_bird_is_a_deferral_not_a_resolution(self):
        enc, axis = _synth_encounter(**self.KW)
        rows = RP.counterfactual_sweep(enc, axis, RP.GeofenceMap.from_file())["rows"]
        reversals = [r for r in rows if r["candidate"] == "lateral_+0"]
        self.assertTrue(reversals)
        self.assertTrue(any(r["cleared"] for r in reversals),
                        "a retreat does open distance -- that is exactly the trap")
        self.assertFalse(any(r["resolved_physically"] for r in reversals),
                         "retreating past the bar must NOT count as resolving the encounter")

    def test_a_sidestep_that_passes_the_bird_does_resolve(self):
        enc, axis = _synth_encounter(**self.KW)
        rows = RP.counterfactual_sweep(enc, axis, RP.GeofenceMap.from_file())["rows"]
        side = [r for r in rows if r["candidate"].startswith("sidestep_ahead")]
        self.assertTrue(any(r["resolved_physically"] for r in side),
                        "a forward sidestep should clear AND pass a static bird")
        self.assertTrue(any(r["passed_bird"] for r in side))

    def test_an_out_of_field_escape_is_marked_illegal(self):
        """A counterfactual that clears the bird by leaving the field is not an escape."""
        legal, why = RP._setpoint_legal((-50.0, -50.0, 15.0), 99.0, 0.0,
                                        {"field_margin_m": 1.0, "alt_bounds": [2.0, 30.0]})
        self.assertFalse(legal)
        self.assertIn("field", why)
        legal, why = RP._setpoint_legal((30.0, 30.0, 99.0), 99.0, 0.0,
                                        {"field_margin_m": 1.0, "alt_bounds": [2.0, 30.0]})
        self.assertFalse(legal)
        self.assertIn("alt_bounds", why)


class TestHypothesisDiscrimination(unittest.TestCase):
    def test_a_window_too_short_to_separate_the_hypotheses_says_so(self):
        """The 2026-08-25 failure mode: 0.434 s of GUIDED authority separates 'the command worked'
        from 'the command did nothing' by a few centimetres. Answering it anyway would be a
        coin-flip dressed as a finding."""
        q = 0.009078                      # the flights' measured telemetry quantum
        path = [(15.0, 30.0 - 1.5 * i, 15.0) for i in range(6)]
        path = [(15.0 - q * i, p[1], p[2]) for i, p in enumerate(path)]
        enc, axis = _synth_encounter(path=path, setpoints=[(3, (5.0, path[2][1], 15.0))],
                                     takeover=3, resume=5, dt=0.15,
                                     bird=(15.0, 20.0, 15.0))
        fit = RP.plant_fit(enc, axis, RP.CMD_PRIMARY, fit_a_max=False)
        self.assertLess(fit["hypothesis_separation_quanta"], 4.0)
        self.assertEqual(fit["discriminating_power"], "NOT DISCRIMINATING")
        self.assertTrue(fit["fit_verdict"].startswith("EVIDENCE INSUFFICIENT"))

    def test_a_long_window_does_separate_them_and_a_compliant_path_reads_as_plant(self):
        """The control case: simulate a vehicle that genuinely obeys, then feed that simulated path
        back in as telemetry. The separator must return H_plant and FIT, or it cannot detect
        compliance when compliance is what happened."""
        # 2.6 s: long enough to separate the hypotheses, short enough that the plant has NOT yet
        # arrived -- so H_plant and H_compliant stay distinct and the argmin is meaningful.
        # PRE-WINDOW CRUISE IS MANDATORY: the entry velocity is estimated from the 0.6 s of
        # telemetry before the takeover, and a synthetic that opens GUIDED on tick 1 hands the
        # estimator no history at all -- it then reads 0 m/s and every hypothesis is computed from
        # the wrong initial state. (That is a property of the study, not a quirk of the test: a real
        # flight always has a cruise leg in front of the encounter.)
        dt, pre, n = 0.2, 6, 14
        target = (24.0, -8.0, 15.0)
        path = [(30.0, 3.0 * dt * (i - pre + 1), 15.0) for i in range(pre)]
        sim = PM.simulate(path[-1], (0.0, 3.0, 0.0), [(0.0, target)], 0.0, dt * n,
                          PM.GUIDED_DEFAULT, sample_times=[dt * i for i in range(1, n + 1)])
        path += [p for t, p in sim if t > 0.0]
        enc, axis = _synth_encounter(path=path, setpoints=[(pre, target)], takeover=pre,
                                     resume=len(path), dt=dt, bird=(30.0, 30.0, 15.0))
        fit = RP.plant_fit(enc, axis, RP.CMD_PRIMARY, fit_a_max=True)
        self.assertEqual(fit["discriminating_power"], "DISCRIMINATING")
        self.assertEqual(fit["nearest_hypothesis"], "H_plant_m")
        self.assertTrue(fit["command_path_worked"])
        self.assertTrue(fit["fit_verdict"].startswith("FIT"), fit["fit_verdict"])
        self.assertEqual(fit["best_plant_by_rms"], "guided_default")
        self.assertAlmostEqual(fit["fitted_a_max_ne_mps2"], PM.GUIDED_DEFAULT.a_max_ne_mps2,
                               delta=0.35)

    def test_a_window_long_enough_to_arrive_collapses_plant_onto_compliant(self):
        """Over a long window the two 'the command worked' hypotheses converge, so the three-way
        argmin stops meaning anything -- which is why `command_path_worked` is reported separately
        and is the field the Q1 verdict is built on."""
        dt, pre, n = 0.2, 6, 60
        target = (24.0, -8.0, 15.0)
        path = [(30.0, 3.0 * dt * (i - pre + 1), 15.0) for i in range(pre)]
        sim = PM.simulate(path[-1], (0.0, 3.0, 0.0), [(0.0, target)], 0.0, dt * n,
                          PM.GUIDED_DEFAULT, sample_times=[dt * i for i in range(1, n + 1)])
        path += [p for t, p in sim if t > 0.0]
        enc, axis = _synth_encounter(path=path, setpoints=[(pre, target)], takeover=pre,
                                     resume=len(path), dt=dt, bird=(30.0, 30.0, 15.0))
        fit = RP.plant_fit(enc, axis, RP.CMD_PRIMARY, fit_a_max=False)
        h = fit["hypotheses_along_cmd_m"]
        self.assertAlmostEqual(h["H_plant_m"], h["H_compliant_m"], delta=0.05)
        self.assertTrue(fit["command_path_worked"])

    def test_a_vehicle_that_ignores_the_command_reads_as_broken_not_as_plant(self):
        """The other control case, and the one that matters for 2026-08-18: a vehicle that flies
        straight on through a reversal command must NOT be excused as plant-limited."""
        dt, n = 0.2, 40
        path = [(30.0 - 0.009078 * (i % 3), 3.0 * dt * i, 15.0) for i in range(n)]
        enc, axis = _synth_encounter(path=path, setpoints=[(1, (24.0, -8.0, 15.0))],
                                     takeover=1, resume=n, dt=dt, bird=(30.0, 60.0, 15.0))
        fit = RP.plant_fit(enc, axis, RP.CMD_PRIMARY, fit_a_max=False)
        self.assertEqual(fit["nearest_hypothesis"], "H_broken_m")
        self.assertFalse(fit["command_path_worked"])
        self.assertTrue(fit["fit_verdict"].startswith("NO-FIT"), fit["fit_verdict"])

    def test_position_quantum_ignores_float_noise(self):
        """A handful of 1e-6 m differences survive the geodetic round-trip. Taking the raw minimum
        would return the noise, every window would look discriminating, and the EVIDENCE
        INSUFFICIENT verdict would never fire."""
        enc, _axis = _synth_encounter(
            path=[(0.0, 0.0, 15.0), (0.0, 1.0, 15.0), (1e-6, 2.0, 15.0),
                  (0.009079, 3.0, 15.0), (0.018157, 4.0, 15.0)],
            setpoints=[(1, (0.0, -10.0, 15.0))], takeover=1, resume=5)
        self.assertAlmostEqual(RP._axis_quanta_m(enc)[0], 0.009078, places=5)
        # ...and the command-axis form is the worst case over the two, not a global minimum.
        self.assertAlmostEqual(RP._command_axis_quantum_m(enc, (1.0, 0.0)), 0.009078, places=5)
        qe, qn = RP._axis_quanta_m(enc)
        self.assertAlmostEqual(RP._command_axis_quantum_m(enc, (0.0, 1.0)), qn, places=6)


class TestSpeedDoctrineSweep(unittest.TestCase):
    """ADR-017 reads the encounter-lane speed off this sweep, so its contingency branch is pinned."""

    HORIZON = {"depth_m": 4.03, "half_footprint_x_m": 2.48, "half_footprint_y_m": 1.86,
               "along_track_m": 2.48, "cross_track_m": 1.86, "axis_taken": "x",
               "provenance": "test"}

    def test_no_safe_speed_is_reported_as_itself(self):
        trip = RP.tripwire(self.HORIZON, bar_m=3.0, bird_mps=6.0, vertical_threat_m=6.0,
                           vertical_gap_m=4.03)
        self.assertFalse(trip["safe_speed_exists_in_2_10"])
        self.assertIsNone(trip["safe_speed_band_mps"])
        self.assertIsNone(trip["max_safe_speed_mps"])
        self.assertIn("bird", trip["why_no_safe_speed"])
        self.assertFalse(trip["hover_limit"]["cleared_by_any_plant"])
        # ...and every swept cell agrees, on every plant, including the physical ceiling.
        self.assertTrue(all(not c["cleared"] for row in trip["speed_sweep"]
                            for c in row["plants"].values()))

    def test_the_hover_limit_is_the_bird_not_the_drone(self):
        """The reason no speed works: the closing speed floor is the bird's own. If this ever
        inverts, the doctrine's premise changes and the ADR must be re-read."""
        trip = RP.tripwire(self.HORIZON, bar_m=3.0, bird_mps=6.0, vertical_threat_m=6.0,
                           vertical_gap_m=4.03)
        self.assertAlmostEqual(trip["hover_limit"]["max_lead_s"], 2.48 / 6.0, places=4)
        slowest = trip["speed_sweep"][0]
        self.assertLess(slowest["max_lead_s"], trip["hover_limit"]["max_lead_s"])

    def test_a_generous_sensor_would_find_a_safe_speed_so_the_sweep_can_say_yes(self):
        """The sweep must be capable of a positive answer, or 'no safe speed' proves nothing about
        the geometry -- only about the code. A forward sensor with a 40 m horizon clears the bar at
        the slow end and stops clearing as the speed rises."""
        generous = dict(self.HORIZON, along_track_m=40.0)
        trip = RP.tripwire(generous, bar_m=3.0, bird_mps=6.0, vertical_threat_m=6.0,
                           vertical_gap_m=4.03)
        self.assertTrue(trip["safe_speed_exists_in_2_10"])
        lo, hi = trip["safe_speed_band_mps"]
        self.assertLessEqual(lo, hi)
        self.assertEqual(lo, RP.SPEED_SWEEP_MPS[0])
        self.assertEqual(trip["max_safe_speed_mps"], hi)
        self.assertIsNone(trip["why_no_safe_speed"])
        # Clearing must be a CONTIGUOUS band starting at the slow end -- slower is always more lead.
        flags = [r["cleared_by_any_plant"] for r in trip["speed_sweep"]]
        self.assertTrue(flags[0])
        self.assertEqual(flags, sorted(flags, reverse=True))

    def test_required_sensor_horizon_is_reported_for_every_plant(self):
        trip = RP.tripwire(self.HORIZON, bar_m=3.0, bird_mps=6.0, vertical_threat_m=6.0,
                           vertical_gap_m=4.03)
        row = next(r for r in trip["speed_sweep"] if abs(r["mission_speed_mps"] - 9.0) < 1e-9)
        for name, cell in row["plants"].items():
            self.assertIsNotNone(cell["required_lead_s"], name)
            self.assertGreater(cell["required_sensor_horizon_m"], self.HORIZON["along_track_m"],
                               f"{name}: required horizon must exceed what nadir supplies")

    def test_sensor_horizon_comes_from_intrinsics(self):
        """The half-footprint is (width/2)/fx * depth, from the LIVE camera_info -- 2.48 m at the
        flown 4.03 m depth, the figure ADR-013 am. 18 quotes."""
        h = RP.sensor_horizon_m({"fx": 520.0057601928711, "fy": 520.0057983398438,
                                 "image_width_px": 640, "image_height_px": 480}, 4.03)
        self.assertAlmostEqual(h["along_track_m"], 2.48, places=2)
        self.assertAlmostEqual(h["cross_track_m"], 1.86, places=2)
        self.assertEqual(h["axis_taken"], "x")

    def test_climb_is_priced_as_band_exit_not_as_clearance(self):
        trip = RP.tripwire(self.HORIZON, bar_m=3.0, bird_mps=6.0, vertical_threat_m=6.0,
                           vertical_gap_m=4.03)
        self.assertIn("NONE-IN-BAND", trip["climb_escape"]["note"])
        for name, cell in trip["climb_escape"]["plants"].items():
            self.assertAlmostEqual(cell["climb_needed_m"], 1.97, places=2)
            self.assertGreater(cell["time_to_exit_band_s"], trip["hover_limit"]["max_lead_s"],
                               f"{name}: a climb that outran the sensor lead would change the "
                               f"answer and must be noticed")


class TestUnansweredIsNotFalse(unittest.TestCase):
    """QA finding C2: a window that cannot separate the hypotheses must contribute UNANSWERABLE.

    The bug it pins: `command_path_worked = winner != "H_broken_m"` ignored discriminating power,
    so the 2026-08-25 row -- whose own verdict is EVIDENCE INSUFFICIENT at 0.56 quanta -- was
    counted as a True and the report printed "THE COMMAND PATH MOVED THE AIRCRAFT on 3 of 5
    windows". Restoring that one line turns every test in this class red."""

    def _thin_window(self):
        q = 0.009078
        path = [(15.0, 30.0 - 1.5 * i, 15.0) for i in range(9)]
        path = [(15.0 - q * (i // 3), p[1], p[2]) for i, p in enumerate(path)]
        return _synth_encounter(path=path, setpoints=[(6, (5.0, path[5][1], 15.0))],
                                takeover=6, resume=8, dt=0.15, bird=(15.0, 20.0, 15.0))

    def test_a_non_discriminating_window_answers_none_not_false(self):
        enc, axis = self._thin_window()
        fit = RP.plant_fit(enc, axis, RP.CMD_PRIMARY, fit_a_max=False)
        self.assertNotEqual(fit["discriminating_power"], "DISCRIMINATING")
        self.assertIsNone(fit["command_path_worked"],
                          "an unanswerable window must be None, never a default of False/True")

    def test_a_marginal_window_never_prints_FIT(self):
        """4-10 quanta used to print 'FIT ... [MARGINAL]', which reads as a fit with a footnote and
        got quoted as a fit. Every rung of the ladder is exercised here, including MARGINAL, which
        no synthesised flight fixture happens to land on -- a branch no test reaches is a branch
        that can be rewritten to say FIT with nothing going red."""
        for power, expect in (("DISCRIMINATING", "FIT"),
                              ("MARGINAL", "EVIDENCE THIN"),
                              ("NOT DISCRIMINATING", "EVIDENCE INSUFFICIENT"),
                              ("UNKNOWN", "EVIDENCE INSUFFICIENT")):
            shape, verdict = RP._fit_verdict(power, 6.0, 0.05, frac=0.01)
            self.assertTrue(shape.startswith("FIT"), shape)     # the rms alone always says FIT here
            self.assertTrue(verdict.startswith(expect), f"{power}: {verdict}")
            if power != "DISCRIMINATING":
                self.assertFalse(verdict.startswith("FIT"), f"{power}: {verdict}")
        # ...and on a real thin window the same holds, with the rms reading kept as context.
        enc, axis = self._thin_window()
        fit = RP.plant_fit(enc, axis, RP.CMD_PRIMARY, fit_a_max=False)
        self.assertFalse(fit["fit_verdict"].startswith("FIT"), fit["fit_verdict"])
        self.assertTrue(fit["fit_verdict"].startswith("EVIDENCE"), fit["fit_verdict"])
        self.assertTrue(fit["rms_shape_verdict"])

    def test_the_ladder_passes_the_rms_verdict_through_only_when_discriminating(self):
        for frac, expect in ((0.01, "FIT"), (0.20, "PARTIAL"), (0.90, "NO-FIT"), (None, "NO-FIT")):
            shape, verdict = RP._fit_verdict("DISCRIMINATING", 50.0, 1.0, frac)
            self.assertTrue(shape.startswith(expect), shape)
            self.assertEqual(shape, verdict)

    def test_the_verdict_counts_unanswerable_separately_and_never_as_worked(self):
        enc, axis = self._thin_window()
        flight = {"stem": "thin", "plant_fit": [RP.plant_fit(enc, axis, m, fit_a_max=False)
                                                for m in (RP.CMD_AS_SENT, RP.CMD_LATCHED)],
                  "counterfactual": [], "timing_robustness": None}
        v = RP.verdicts([flight], None, 3.0)["q1"]
        self.assertEqual(v["command_path_worked_by_flight"]["thin"], RP.UNANSWERABLE)
        self.assertEqual(v["command_path_worked_counts_by_flight"]["unanswerable"], 1)
        self.assertEqual(v["command_path_worked_counts_by_flight"]["true"], 0)
        self.assertEqual(v["command_path_worked_counts_by_flight"]["false"], 0)
        self.assertIn("CANNOT TELL", v["headline"])

    def test_a_two_mode_argmin_conflict_is_surfaced_and_classified(self):
        """The two command modes returning opposite winners off one telemetry set is evidence in
        itself; it used to be invisible because only the primary mode reached the verdict."""
        enc, axis = self._thin_window()
        flight = {"stem": "thin", "plant_fit": [RP.plant_fit(enc, axis, m, fit_a_max=False)
                                                for m in (RP.CMD_AS_SENT, RP.CMD_LATCHED)],
                  "counterfactual": [], "timing_robustness": None}
        v = RP.verdicts([flight], None, 3.0)["q1"]
        for c in v["two_command_mode_conflicts"]:
            self.assertIn("informative", c)
            self.assertTrue(c["reading"].startswith("REAL") or c["reading"].startswith("NOISE"))


class TestBandExitIsNotClearance(unittest.TestCase):
    """QA finding C3: a PARTIAL band exit must not inherit the scoped CPA as a clearance.

    `ground_truth_cpa` is vertically scoped, so a climb that leaves the +/-6 m band reports the last
    IN-BAND instant as its CPA -- measured on the real sweep as 5.35/14.77/14.34/28.08 m against
    true horizontal minima of 0.78/0.17/0.014/0.50 m."""

    def _climbing_encounter(self):
        # Drone north up lane x=30 at 3 m/s, bird static at (30, 20, 15) dead ahead in-band.
        path = [(30.0, 0.6 * i, 15.0) for i in range(40)]
        return _synth_encounter(path=path, setpoints=[(20, (30.0, path[19][1] - 10.0, 15.0))],
                                takeover=20, resume=40, bird=(30.0, 20.0, 15.0))

    def test_band_audit_detects_a_partial_exit_and_reports_the_bandfree_minimum(self):
        enc, _axis = self._climbing_encounter()
        # A path that starts level with the bird and climbs 20 m clear of the band while passing
        # straight over it: in band at the start, out of band at the end, 0 m horizontal at the pass.
        samples = [(float(i) * 0.2, (30.0, 10.0 + 0.5 * i, 15.0 + 0.5 * i)) for i in range(40)]
        band, min_horiz = RP._band_audit(samples, enc, "demo_bird_0", 6.0)
        self.assertEqual(band, "partial_band_exit")
        self.assertLess(min_horiz, 0.5, "the band-free minimum must see the pass the scoped CPA "
                                        "cannot")

    def test_a_climb_cell_is_never_counted_as_resolving(self):
        enc, axis = self._climbing_encounter()
        cf = RP.counterfactual_sweep(enc, axis, RP.GeofenceMap.from_file())
        climbs = [r for r in cf["rows"] if r["candidate"] == "climb"]
        self.assertTrue(climbs)
        exits = [r for r in climbs if r["band_exit"]]
        self.assertTrue(exits, "a climb to the altitude ceiling must leave the +/-6 m band")
        for r in exits:
            self.assertFalse(r["cleared"])
            self.assertFalse(r["resolved_physically"])
            self.assertFalse(r["resolved_legally"])
            self.assertIsNotNone(r["min_horizontal_threat_m"],
                                 "a BAND-EXIT row must still print the band-free minimum")
        self.assertNotIn("climb", cf["summary"]["per_candidate"]["climb"].keys())  # shape guard
        self.assertFalse(cf["summary"]["per_candidate"]["climb"]["ever_resolved_physically"])

    def test_every_row_carries_the_band_free_minimum(self):
        enc, axis = self._climbing_encounter()
        cf = RP.counterfactual_sweep(enc, axis, RP.GeofenceMap.from_file())
        self.assertTrue(all("min_horizontal_threat_m" in r for r in cf["rows"]))
        for c in cf["summary"]["per_candidate"].values():
            self.assertIsNotNone(c["worst_min_horizontal_threat_m"])


class TestLegalAndPhysicalLeadsAreBothReported(unittest.TestCase):
    """QA finding M2, and the surviving mutant it names: deleting `and r["setpoint_legal"]` from
    `_cf_summary` broke ZERO tests. It cannot any more -- the legal and physical numbers are
    separate fields and this class pins both."""

    def _boxed_in(self):
        # An escape that RESOLVES the encounter but whose setpoint is outside the field polygon:
        # physically fine, legally refused. The lane runs off the west edge of the 75x60 field.
        path = [(2.0, 0.6 * i, 15.0) for i in range(40)]
        return _synth_encounter(path=path, setpoints=[(20, (2.0, path[19][1] - 10.0, 15.0))],
                                takeover=20, resume=40, bird=(2.0, 20.0, 15.0))

    @staticmethod
    def _row(lead, legal, resolved=True, candidate="lateral_+90", plant="guided_default"):
        return {"lead_s": lead, "candidate": candidate, "plant": plant,
                "setpoint_enu": [0, 0, 15], "gt_cpa_m": 5.0 if resolved else 0.5,
                "min_horizontal_any_band_m": 5.0, "min_horizontal_threat_m": 5.0,
                "band": "in_band", "band_exit": False, "cleared": resolved,
                "passed_bird": resolved, "resolved_physically": resolved,
                "resolved_legally": bool(resolved and legal),
                "binding_constraint": None if (resolved and legal) else
                ("tree/field vet" if resolved else "plant/lead"),
                "swept_tree_clearance_m": 5.0, "setpoint_legal": legal, "illegal_reason": None,
                "displacement_m": 8.0}

    def test_the_mutant_deleting_the_legality_guard_is_caught(self):
        """THE SURVIVING MUTANT QA NAMED: removing `and r["setpoint_legal"]` from `_cf_summary`
        broke zero tests. Hand-built rows, so the assertion is about the summariser and not about
        whatever the field geometry happens to allow: the earliest cell that resolves is ILLEGAL
        and a later one is legal. The two numbers must differ."""
        rows = [self._row(0.5, legal=False), self._row(2.0, legal=True)]
        s = RP._cf_summary(rows, bar=3.0)
        self.assertEqual(s["min_physically_resolving_lead_s"], 0.5)
        self.assertEqual(s["min_legally_resolving_lead_s"], 2.0)
        self.assertEqual(s["min_physically_resolving_lead_by_plant_s"], {"guided_default": 0.5})
        self.assertEqual(s["min_legally_resolving_lead_by_plant_s"], {"guided_default": 2.0})
        self.assertEqual(s["n_physically_resolving_but_illegal"], 1)
        c = s["per_candidate"]["lateral_+90"]
        self.assertEqual(c["min_physically_resolving_lead_s"], 0.5)
        self.assertEqual(c["min_legally_resolving_lead_s"], 2.0)

    def test_an_all_illegal_sweep_reports_a_physical_lead_and_no_legal_one(self):
        s = RP._cf_summary([self._row(0.5, legal=False), self._row(1.0, legal=False)], bar=3.0)
        self.assertEqual(s["min_physically_resolving_lead_s"], 0.5)
        self.assertIsNone(s["min_legally_resolving_lead_s"],
                          "no legal escape exists here and the summary must say so, not fall back "
                          "to the physical number")
        self.assertTrue(s["any_resolved_physically"])
        self.assertFalse(s["any_resolved_legally"])

    def test_a_band_exit_row_never_sets_the_headline_cpa(self):
        """C3 at the summary level: a BAND-EXIT cell's gt_cpa is the last in-band instant."""
        exit_row = dict(self._row(0.0, legal=True), band="partial_band_exit", band_exit=True,
                        gt_cpa_m=28.0, min_horizontal_threat_m=0.014, cleared=False,
                        resolved_physically=False, resolved_legally=False)
        s = RP._cf_summary([exit_row], bar=3.0)
        c = s["per_candidate"]["lateral_+90"]
        self.assertIsNone(c["best_cpa_m"], "a band-exit CPA may not become the headline number")
        self.assertTrue(c["band_exit_only"])
        self.assertAlmostEqual(c["worst_min_horizontal_threat_m"], 0.014)
        self.assertFalse(c["ever_resolved_physically"])

    def test_every_row_names_which_constraint_bound_it(self):
        enc, axis = self._boxed_in()
        cf = RP.counterfactual_sweep(enc, axis, RP.GeofenceMap.from_file())
        for r in cf["rows"]:
            self.assertIn(r["binding_constraint"], (None, "plant/lead", "tree/field vet"))
            if r["resolved_legally"]:
                self.assertIsNone(r["binding_constraint"])


class TestEveryCellCoversTheEncounter(unittest.TestCase):
    """QA finding G76: the simulated window must CONTAIN the flown-CPA instant.

    The bird arrives at a fixed sim time. An equal-duration-after-the-command horizon (the fix for
    QA's own m8, which was wrong and is retracted) ends a long-lead cell BEFORE the bird gets there,
    so nothing is scored and the cell reports huge separation -- C3's vacuous green moved from
    vertical scoping to temporal scoping. Measured with that rule live: 72/429 cells changed, 32
    flipped resolved False -> True. Restoring `t_end = t_cmd + horizon_s` turns this class red."""

    def _encounter(self):
        """3 m/s north up lane x=30, long history before the takeover so the sweep reaches its
        3.0 s leads, and a SHORT GUIDED window -- 2 ticks, like the real 2026-08-25 encounter.

        The short window is what makes this fixture bite: the horizon is 0.4 + 3.0 = 3.4 s, so
        under the retracted equal-duration rule a lead-3.0 cell ends 0.4 s past takeover while the
        bird is not reached until ~0.87 s past it. That is exactly the 2026-08-25 geometry."""
        path = [(30.0, 0.6 * i, 15.0) for i in range(80)]
        return _synth_encounter(path=path, setpoints=[(60, (30.0, path[59][1] - 10.0, 15.0))],
                                takeover=60, resume=62, bird=(30.0, 38.0, 15.0))

    def test_every_cell_simulates_through_the_flown_cpa_instant(self):
        enc, axis = self._encounter()
        cf = RP.counterfactual_sweep(enc, axis, RP.GeofenceMap.from_file())
        self.assertIsNotNone(cf["flown_cpa_t_sim_s"], "the fixture must produce a flown CPA")
        t_cpa = cf["flown_cpa_t_sim_s"]
        self.assertTrue(cf["rows"])
        for r in cf["rows"]:
            lo, hi = r["simulated_span_s"]
            self.assertTrue(lo <= t_cpa <= hi,
                            f"lead {r['lead_s']} / {r['candidate']} / {r['plant']} simulated "
                            f"[{lo}, {hi}] which does not contain the encounter at {t_cpa}")
            self.assertTrue(r["covers_flown_cpa"])
        self.assertTrue(cf["all_cells_cover_flown_cpa"])

    def test_a_longer_lead_simulates_longer_not_earlier(self):
        """The corollary that distinguishes the two rules: under the corrected one the END is fixed
        and the START moves back, so duration GROWS with lead. Under the retracted one duration was
        constant and the end slid backwards past the bird."""
        enc, axis = self._encounter()
        cf = RP.counterfactual_sweep(enc, axis, RP.GeofenceMap.from_file())
        by_lead = {}
        for r in cf["rows"]:
            by_lead.setdefault(r["lead_s"], (r["simulated_span_s"], r["simulated_duration_s"]))
        leads = sorted(by_lead)
        self.assertGreater(len(leads), 2)
        ends = {round(by_lead[k][0][1], 6) for k in leads}
        self.assertEqual(len(ends), 1, f"the simulated END must be the same instant for every "
                                       f"lead, got {ends}")
        durations = [by_lead[k][1] for k in leads]
        self.assertEqual(durations, sorted(durations),
                         "duration must be non-decreasing in lead")
        self.assertGreater(durations[-1], durations[0])


class TestSkippedLogsAreNamed(unittest.TestCase):
    """QA finding M1: a log the replay cannot score must be named with its reason, and a run that
    scores nothing must not exit 0."""

    def _write(self, tmp: Path, name: str, log: dict) -> Path:
        p = tmp / name
        p.write_text(json.dumps(log))
        return p

    def test_a_guided_lock_is_reported_not_silently_dropped(self):
        """takeover with no resume = the vehicle never handed back. That is the failure mode the
        threat-hysteresis change could produce, and it used to be a silent `return None`."""
        log = {"events": [{"kind": "takeover", "tick": 3},
                          {"kind": "maneuver", "tick": 3, "setpoint_enu": [1, 2, 15]}],
               "flown_path_enu": [[0, 0, 15]] * 5}
        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d), "live_flight_log_lock.json", log)
            enc, reason = RP.load_encounter(p)
        self.assertIsNone(enc)
        self.assertIn("GUIDED LOCK", reason)

    def test_a_takeover_with_no_maneuver_is_reported(self):
        log = {"events": [{"kind": "takeover", "tick": 3}, {"kind": "resume", "tick": 5}],
               "flown_path_enu": [[0, 0, 15]] * 5}
        with tempfile.TemporaryDirectory() as d:
            p = self._write(Path(d), "live_flight_log_nomaneuver.json", log)
            enc, reason = RP.load_encounter(p)
        self.assertIsNone(enc)
        self.assertIn("NO maneuver", reason)

    def test_all_logs_skipped_exits_2_and_names_every_one(self):
        log = {"events": [{"kind": "takeover", "tick": 3}], "flown_path_enu": [[0, 0, 15]] * 5}
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            p = self._write(tmp, "live_flight_log_lock.json", log)
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = RP.main(["--logs", str(p), "--out", str(tmp / "out.json")])
            self.assertEqual(rc, 2,
                             "an all-skipped run is an instrument failure, not an empty result")
            self.assertIn("live_flight_log_lock.json", err.getvalue())
            self.assertIn("NO FLIGHT COULD BE REPLAYED", err.getvalue())
            # THE REASON MUST REACH THE OPERATOR, not just the artifact (QA finding G78). The
            # machinery was pinned and the operator-facing wording was not, so a warning could be
            # reduced to "skipped <file>" -- which tells whoever is standing at the MAVProxy prompt
            # that something was dropped but not that the vehicle never left GUIDED.
            self.assertIn("GUIDED LOCK", err.getvalue())
            rep = json.loads((tmp / "out.json").read_text())
        self.assertEqual([s["log"] for s in rep["logs_skipped"]], ["live_flight_log_lock.json"])
        self.assertEqual(rep["logs_considered"], ["live_flight_log_lock.json"])
        self.assertIn("GUIDED LOCK", rep["logs_skipped"][0]["reason"])

    def test_the_stdout_banner_carries_the_reason_too(self):
        """The other operator-facing surface: a run with SOME logs skipped still prints a report,
        and the banner at the top of it is the only place a reader sees the hole."""
        good = {"events": [{"kind": "takeover", "tick": 2}, {"kind": "resume", "tick": 4},
                           {"kind": "maneuver", "tick": 2, "setpoint_enu": [30.0, 10.0, 15.0],
                            "debug": {"params": {"min_bird_clearance_m": 3.0,
                                                 "divert_distance_m": 10.0, "cruise_alt_m": 15.0,
                                                 "threat_radius_m": 12.0, "vertical_threat_m": 6.0,
                                                 "lateral_tree_margin_m": 0.0,
                                                 "field_margin_m": 1.0,
                                                 "alt_bounds": [2.0, 30.0]}}},
                           {"kind": "detection", "tick": 2, "track_id": "demo_bird_0",
                            "position_enu": [30.0, 30.0, 15.0]}],
                "flown_path_enu": [[30.0, 5.0 * i, 15.0] for i in range(8)]}
        lock = {"events": [{"kind": "takeover", "tick": 3}], "flown_path_enu": [[0, 0, 15]] * 5}
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            a = self._write(tmp, "live_flight_log_good.json", good)
            b = self._write(tmp, "live_flight_log_lock.json", lock)
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = RP.main(["--logs", str(a), str(b), "--out", str(tmp / "out.json")])
        self.assertEqual(rc, 0, "one scoreable log means the run is a result, not a failure")
        self.assertIn("1 of 2 LOG(S) SKIPPED", out.getvalue())
        # Whitespace-normalised: the banner word-wraps, and where the line break lands is a
        # presentation detail. What is pinned is that the REASON reaches the operator.
        self.assertIn("GUIDED LOCK", " ".join(out.getvalue().split()))
        self.assertIn("GUIDED LOCK", " ".join(err.getvalue().split()))


class TestTuningScanner(unittest.TestCase):
    """QA finding M5, and the second surviving mutant: neutering the scanner broke zero tests.

    The scanner is the only thing standing between "these are firmware defaults" and a study that
    is silently void, and this project sets parameters at the MAVProxy prompt -- which the first
    version did not look at, and which is exactly where ADR-017's `param set WPNAV_SPD` will land."""

    def test_a_planted_parm_override_is_found(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "x.parm").write_text("DDS_ENABLE 1\nWPNAV_ACC 4.0\n")
            scan = RP._tuning_override_scan(Path(d))
        self.assertTrue(scan["overrides"])
        self.assertIn("WPNAV_ACC", scan["overrides"][0])
        self.assertIn("TUNING OVERRIDE FOUND", scan["statement"])

    def test_a_planted_mavproxy_param_set_is_found(self):
        """THE MUTANT: drop `_PARAM_SET_GLOBS` from the scan and this is the test that goes red."""
        with tempfile.TemporaryDirectory() as d:
            scripts = Path(d) / "scripts"
            scripts.mkdir()
            (scripts / "fly.sh").write_text("#!/bin/bash\n"
                                            "  param set MIS_RESTART 0\n"
                                            "  param set WPNAV_SPD 4\n")
            scan = RP._tuning_override_scan(Path(d))
        self.assertTrue(scan["overrides"], "a `param set WPNAV_SPD` at the MAVProxy prompt sets the "
                                           "parameter just as surely as a .parm file does")
        self.assertIn("WPNAV_SPD", " ".join(scan["overrides"]))
        self.assertIn("param set", " ".join(scan["overrides"]))

    def test_a_planted_runbook_param_set_is_found(self):
        with tempfile.TemporaryDirectory() as d:
            rb = Path(d) / "docs" / "runbooks"
            rb.mkdir(parents=True)
            (rb / "AVOID.md").write_text("Then type:\n\n    param set PSC_NE_JERK 12\n")
            scan = RP._tuning_override_scan(Path(d))
        self.assertIn("PSC_NE_JERK", " ".join(scan["overrides"]))

    def test_an_unrelated_param_set_is_not_a_false_positive(self):
        with tempfile.TemporaryDirectory() as d:
            scripts = Path(d) / "scripts"
            scripts.mkdir()
            (scripts / "fly.sh").write_text("param set MIS_RESTART 0\nparam set DISARM_DELAY 0\n")
            scan = RP._tuning_override_scan(Path(d))
        self.assertEqual(scan["overrides"], [])
        self.assertIn("CHECKED at run time", scan["statement"])

    def test_the_real_repo_is_clean_and_carries_the_sitl_warrant(self):
        scan = RP._tuning_override_scan()
        self.assertEqual(scan["overrides"], [], f"unexpected override: {scan['overrides']}")
        self.assertIn("default_params", scan["sitl_default_warrant"])
        self.assertIn("sim_vehicle.py", scan["statement"])
        self.assertNotIn(".claude", scan["statement"],
                         "another agent's worktree is not this vehicle's parameter set")

    def test_dot_directories_are_not_scanned(self):
        """`.claude/worktrees/` holds concurrent agents' checkouts of this same repo. A stale
        worktree must not be able to void this study -- or to certify it."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "config").mkdir()
            (root / "config" / "real.parm").write_text("DDS_ENABLE 1\n")
            wt = root / ".claude" / "worktrees" / "other" / "config"
            wt.mkdir(parents=True)
            (wt / "real.parm").write_text("WPNAV_SPD 4\n")
            scan = RP._tuning_override_scan(root)
        self.assertEqual(scan["overrides"], [],
                         "a parm file inside a dot-directory must not be scanned")
        self.assertIn("config/real.parm", scan["statement"])
        self.assertNotIn(".claude", scan["statement"])


class TestCruiseLeakDecomposition(unittest.TestCase):
    """QA finding M6: the along-command projection is not dodge compliance."""

    def test_a_pure_cruise_leg_through_a_misaligned_command_reports_zero_dodge(self):
        # Vehicle flies dead straight (no dodge at all) while commanded 10 m to one side, with the
        # command 3 deg off the track normal. Along-command displacement is NON-zero -- entirely
        # leak -- and the cross-track term must be zero.
        dt, pre, n = 0.2, 6, 12
        ang = math.radians(3.0)
        path = [(0.0, 0.6 * i, 15.0) for i in range(pre + n)]
        p0 = path[pre - 1]
        sp = (p0[0] - 10.0 * math.cos(ang), p0[1] - 10.0 * math.sin(ang), 15.0)
        enc, axis = _synth_encounter(path=path, setpoints=[(pre, sp)], takeover=pre,
                                     resume=len(path), dt=dt, bird=(0.0, 40.0, 15.0))
        fit = RP.plant_fit(enc, axis, RP.CMD_PRIMARY, fit_a_max=False)
        self.assertAlmostEqual(fit["observed_cross_track_m"], 0.0, delta=1e-6)
        self.assertNotAlmostEqual(fit["observed_along_cmd_window_m"], 0.0, delta=1e-3)
        dec = fit["along_cmd_decomposition_m"]
        self.assertAlmostEqual(dec["dodge_term"], 0.0, delta=1e-6)
        self.assertAlmostEqual(dec["cruise_leak_term"], fit["observed_along_cmd_window_m"],
                               delta=1e-3)
        self.assertAlmostEqual(fit["cmd_vs_track_normal_deg"], 3.0, delta=0.01)

    def test_the_decomposition_is_exact(self):
        enc, axis = _synth_encounter(
            path=[(30.0 - 0.02 * i, 0.6 * i, 15.0) for i in range(20)],
            setpoints=[(8, (20.0, 5.0, 15.0))], takeover=8, resume=20)
        fit = RP.plant_fit(enc, axis, RP.CMD_PRIMARY, fit_a_max=False)
        dec = fit["along_cmd_decomposition_m"]
        self.assertAlmostEqual(dec["dodge_term"] + dec["cruise_leak_term"],
                               fit["observed_along_cmd_window_m"], delta=1e-3)


class TestTimingRobustnessAdmissibility(unittest.TestCase):
    """QA finding M4: a sweep cell implying a cruise speed the vehicle cannot fly is not evidence."""

    def test_cells_implying_a_cruise_above_wpnav_spd_are_inadmissible(self):
        path = [(30.0, 1.5 * i, 15.0) for i in range(40)]      # 1.5 m per tick
        enc, _axis = _synth_encounter(path=path, setpoints=[(10, (30.0, -10.0, 15.0))],
                                      takeover=10, resume=40)
        tr = RP.timing_robustness(enc, RP.timing_axes(enc))
        self.assertIsNotNone(tr)
        self.assertGreater(tr["admissible_dt_floor_s"], 0.1)   # 1.5 m / 10 m/s = 0.15 s
        for r in tr["rows"]:
            expect = r["implied_cruise_speed_mps"] <= PM.GUIDED_DEFAULT.v_max_ne_mps + 1e-9
            self.assertEqual(r["admissible"], expect, r)
        self.assertTrue(tr["best_admissible"]["admissible"])
        self.assertGreaterEqual(tr["best_admissible"]["dt_s"], tr["admissible_dt_floor_s"])

    def test_a_declared_axis_implying_an_impossible_cruise_is_inadmissible(self):
        """QA finding G77: the admissibility filter used to apply ONLY to the robustness probe, so a
        DECLARED schema-1 axis implying a 12.31 m/s cruise against WPNAV_SPD 10 carried a FIT
        verdict into the published aggregates and was the sole source of the upper endpoint of
        `fitted_a_max_ne_mps2_range`."""
        # 1.5 m per tick: 0.20 s implies 7.5 m/s (fine), 0.16 s implies 9.4 m/s (fine); 2.5 m per
        # tick makes the faster axis impossible while the slower one stays legal.
        path = [(30.0, 2.0 * i, 15.0) for i in range(40)]
        enc, _axis = _synth_encounter(path=path, setpoints=[(10, (30.0, -10.0, 15.0))],
                                      takeover=10, resume=40)
        axes = RP.timing_axes(enc)
        self.assertEqual(len(axes), 2)
        for a in axes:
            implied = RP.p99_step_m(enc) / a["dt_s"]
            self.assertEqual(a["admissible"], implied <= PM.GUIDED_DEFAULT.v_max_ne_mps + 1e-9, a)
            self.assertAlmostEqual(a["implied_cruise_speed_mps"], implied, places=3)
        self.assertFalse(axes[1]["admissible"], "the 0.16 s axis must be impossible on this path")

    def test_a_measured_axis_is_always_admissible(self):
        """A heuristic does not get to overrule an observation -- and the one real-clock flight
        scores 1.01x on it, so a naive application would exclude the only measured axis there is."""
        ok, implied = RP.axis_admissible(_synth_encounter(
            path=[(30.0, 5.0 * i, 15.0) for i in range(10)],
            setpoints=[(3, (30.0, -10.0, 15.0))], takeover=3, resume=10)[0], "measured", 0.16)
        self.assertTrue(ok)
        self.assertIsNone(implied)

    def test_inadmissible_rows_are_shown_but_never_aggregated(self):
        def row(axis_label, admissible, verdict, a_max):
            return {"stem": "f", "timing_axis": axis_label, "timing_kind": "assumed",
                    "admissible": admissible, "implied_cruise_speed_mps": 12.3,
                    "observed_along_cmd_m": 1.0, "observed_cross_track_m": 1.0,
                    "along_cmd_decomposition_m": {"dodge_term": 1.0, "cruise_leak_term": 0.0},
                    "nearest_hypothesis": "H_plant_m", "command_path_worked": True,
                    "hypotheses_m": {}, "discriminating_power": "DISCRIMINATING",
                    "hypothesis_separation_m": 1.0, "hypothesis_separation_quanta": 100.0,
                    "best_plant_by_rms": "guided_default", "best_rms_m": 0.1,
                    "best_rms_frac_of_path": 0.01, "rms_shape_verdict": verdict,
                    "fit_verdict": verdict, "fitted_a_max_ne_mps2": a_max}
        good = row("assumed_dt_0.20s", True, "FIT -- x", 1.05)
        bad = row("assumed_dt_0.16s", False, "FIT -- x", 1.85)
        flight = {"stem": "f", "counterfactual": [], "timing_robustness": None,
                  "plant_fit": [dict(r, command_mode=RP.CMD_PRIMARY,
                                     timing_admissible=r["admissible"],
                                     timing_implied_cruise_speed_mps=r["implied_cruise_speed_mps"],
                                     observed_along_cmd_window_m=r["observed_along_cmd_m"],
                                     hypotheses_along_cmd_m={}) for r in (good, bad)]}
        v = RP.verdicts([flight], None, 3.0)["q1"]
        self.assertEqual(v["n_rows_total_admissible"], [2, 1])
        self.assertEqual(v["fit_verdict_counts"]["FIT"], 1, "the inadmissible FIT must not count")
        self.assertEqual(v["fitted_a_max_ne_mps2_range"], [1.05, 1.05],
                         "1.85 comes from the inadmissible axis and must not reach the range")
        self.assertEqual(v["fitted_a_max_sources"], ["f / assumed_dt_0.20s"])
        self.assertEqual([e["timing_axis"]
                          for e in v["inadmissible_rows_excluded_from_aggregates"]],
                         ["assumed_dt_0.16s"])
        # ...and the excluded value is still VISIBLE, just labelled.
        self.assertEqual(v["inadmissible_rows_excluded_from_aggregates"][0]
                         ["fitted_a_max_ne_mps2"], 1.85)

    def test_tg5_does_not_publish_a_range_it_cannot_defend(self):
        tg5 = next(g for g in RP.TRANSFER_GAPS if g["id"] == "TG-5")
        self.assertIn("ESTIMATED", tg5["direction"])
        self.assertNotIn("MEASURED (", tg5["direction"])
        self.assertIn("admissible", tg5["note"])

    def test_the_entry_velocity_window_is_swept_too(self):
        path = [(30.0, 1.5 * (i // 3), 15.0) for i in range(40)]   # a staircase, like 2026-08-18
        enc, _axis = _synth_encounter(path=path, setpoints=[(10, (30.0, -10.0, 15.0))],
                                      takeover=10, resume=40)
        tr = RP.timing_robustness(enc, RP.timing_axes(enc))
        windows = {r["entry_window_s"] for r in tr["rows"]}
        self.assertEqual(windows, set(RP.ENTRY_VELOCITY_WINDOWS_S))
        speeds = {r["entry_speed_mps"] for r in tr["rows"] if r["dt_s"] == 0.20}
        self.assertGreater(len(speeds), 1, "on a staircase the estimator window must matter -- if "
                                           "it does not, the sweep is not being applied")


class TestTripwireRobustnessAttacks(unittest.TestCase):
    """The three attacks QA ran, carried in the artifact because they STRENGTHEN Q3."""

    HORIZON = {"depth_m": 4.03, "half_footprint_x_m": 2.48, "half_footprint_y_m": 1.86,
               "along_track_m": 2.48, "cross_track_m": 1.86, "axis_taken": "x",
               "provenance": "test"}

    def setUp(self):
        self.trip = RP.tripwire(self.HORIZON, bar_m=3.0, bird_mps=6.0, vertical_threat_m=6.0,
                                vertical_gap_m=4.03)
        self.at = self.trip["robustness_attacks"]

    def test_a_altitude_sweep_stays_inside_the_band_and_still_falls_short(self):
        a = self.at["a_altitude_sweep"]
        self.assertTrue(all(r["depth_m"] <= 6.0 for r in a["rows"]))
        self.assertFalse(any(r["cleared"] for r in a["rows"]))
        self.assertAlmostEqual(a["best"]["best_lateral_m"], 0.654, delta=0.01)
        self.assertGreater(a["shortfall_factor_at_best"], 4.0)
        self.assertTrue(a["depth_needed_is_outside_band"])
        self.assertAlmostEqual(a["depth_needed_by_ceiling_plant_m"], 11.39, delta=0.05)

    def test_b_axis_choice_admits_it_is_optimistic(self):
        b = self.at["b_axis_choice"]
        self.assertLess(b["pessimistic_alternative_m"], b["along_track_taken_m"])
        self.assertIn("OPTIMISTIC", b["direction"])

    def test_c_angle_max_45_degrees_is_still_an_order_short(self):
        c = self.at["c_angle_max_45deg"]
        self.assertAlmostEqual(c["a_max_ne_mps2"], 9.80665, delta=1e-4)
        self.assertAlmostEqual(c["max_lateral_m"], 0.2352, delta=0.001)
        self.assertFalse(c["cleared"])
        self.assertGreaterEqual(c["shortfall_factor"], 12.0)


class TestReportShape(unittest.TestCase):
    def test_assumptions_block_names_every_load_bearing_assumption(self):
        block = RP.assumptions_block()
        for key in ("plant", "command_path", "params_are_defaults", "schema1_timing",
                    "schema1_bird", "truth_span", "entry_velocity", "compliance_definition",
                    "cpa_geometry", "sweep_grid", "not_a_gate"):
            self.assertIn(key, block)
            self.assertTrue(block[key].strip())

    def test_the_defaults_assumption_is_checked_against_the_repo_not_asserted(self):
        """If someone lands a WPNAV_*/GUID_*/PSC_* override, every plant constant in this study
        stops being what flies -- so the claim is re-checked on each run and the assumptions block
        says TUNING OVERRIDE FOUND instead of reassuring the reader."""
        scan = RP._tuning_override_scan()
        self.assertIn("overrides", scan)
        if scan["overrides"]:
            self.assertIn("TUNING OVERRIDE FOUND", scan["statement"])
        else:
            self.assertIn("CHECKED at run time", scan["statement"])
            self.assertIn(".parm", scan["statement"])

    def test_transfer_gap_register_is_populated_and_signed(self):
        """Every gap must say which WAY it biases the model, or the register is a list of excuses
        rather than a bound."""
        self.assertGreaterEqual(len(RP.TRANSFER_GAPS), 5)
        for g in RP.TRANSFER_GAPS:
            self.assertTrue(g["id"] and g["gap"] and g["note"])
            self.assertTrue(any(k in g["direction"] for k in
                                ("OPTIMISTIC", "unsigned", "MEASURED", "ESTIMATED")),
                            f"{g['id']} has an unsigned-but-unlabelled direction: {g['direction']}")
            if "ESTIMATED" in g["direction"]:
                self.assertNotIn("MEASURED", g["direction"],
                                 "an estimate may not also call itself measured")

    def test_schema1_gets_two_timing_axes_and_neither_claims_to_be_measured(self):
        enc, _axis = _synth_encounter(path=[(30.0, float(i), 15.0) for i in range(10)],
                                      setpoints=[(1, (30.0, -10.0, 15.0))], takeover=1, resume=10)
        axes = RP.timing_axes(enc)
        self.assertEqual(len(axes), 2)
        self.assertTrue(all(a["kind"] == "assumed" for a in axes))
        self.assertTrue(all("ASSUMED" in a["source"] for a in axes))


if __name__ == "__main__":
    unittest.main()
