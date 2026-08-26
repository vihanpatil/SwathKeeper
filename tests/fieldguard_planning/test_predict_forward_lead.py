"""Tests for scripts/predict_forward_lead.py -- the ADR-019 booking gate.

THE POINT OF THIS FILE is that a gate which decides whether a Docker session gets spent must not be
able to (a) carry its own private copy of a number somebody else owns, (b) pass on optimism,
(c) call a config-sourced answer "bookable", or (d) launder garbage input into a verdict.

  * `TestImportedNotRestated` -- the bar, the plant, the bird speed and the frame period must be
    the SAME objects the policy, `eval/point_mass`, the birds config and the camera config own. A
    second literal 3.0 in a gate is how a gate ends up passing flights the control law would
    refuse (`check_live_flight_log.min_bird_clearance_m` exists for exactly this reason).
  * `TestPlantValuesAgainstClosedForms` -- the plant numbers this gate leans on are pinned to the
    ANALYTIC formulas `tests/test_point_mass_replay.py` already trusts (j*t^3/6 in the jerk regime,
    the three-phase accel form after it, and the quadratic root for t_req), recomputed here from
    the plant's own a/j constants. This replaces an earlier "the two plant functions agree" test
    that was structurally incapable of failing: `time_to_displace_s` IS a bisection on
    `max_displacement_m`, so a mutant that scaled displacement 3x moved t_req 1.79 -> 1.00 s and
    the "cross-check" stayed green. One implementation, pinned to closed forms, is the honest
    statement.
  * `TestTeeth` -- the gate must FAIL something. It fails at 10.0 m/s, which is ArduCopter's own
    WPNAV_SPD default, and it fails when the measured horizon comes in short.
  * `TestInputValidation` -- an out-of-clip horizon, a non-finite or non-positive speed, and half a
    set of live intrinsics are all REFUSALS (exit 2), never verdicts. `--acq-range-m inf` used to
    exit 0 BOOKABLE.
  * `TestBookability` -- exit 0 must be UNREACHABLE in every mode without a full live input set.
    That is the property; "the four exit codes are distinct integers" was not.

Runs on the host: stdlib only for the tool, ~1 s.
"""
import json
import math
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

import predict_forward_lead as pfl  # noqa: E402
from check_live_flight_log import max_bird_speed_m_s  # noqa: E402
from fieldguard_planning.avoidance_policy import PolicyParams  # noqa: E402
from point_mass import GUIDED_DEFAULT, max_displacement_m, time_to_displace_s  # noqa: E402

TOOL = REPO_ROOT / "scripts" / "predict_forward_lead.py"
DEPTH_CONFIG = REPO_ROOT / "config" / "depth_camera.json"

# The recommended mission speed and the numbers ADR-020 publishes for it.
RECOMMENDED_SPEED_MPS = 5.0
PUBLISHED_MARGIN = 1.811

# A full, self-consistent LIVE intrinsic set + a plausible measured horizon: what a session that
# actually ran docs/runbooks/FORWARD_DEPTH_SENSOR.md gates D1/D3 would hand the tool.
LIVE = ("--fx", "520.0058", "--cy", "240.0", "--acq-range-m", "40.0")
LIVE_KW = dict(fx_px=520.0058, cy_px=240.0, acq_range_m=40.0)


def _run(*args):
    return subprocess.run([sys.executable, str(TOOL), *args], capture_output=True, text=True)


class TestImportedNotRestated(unittest.TestCase):
    def setUp(self):
        self.rep = pfl.evaluate(RECOMMENDED_SPEED_MPS)

    def test_the_bar_is_the_policys_bar(self):
        self.assertEqual(self.rep["budget"]["bar_m"], PolicyParams().min_bird_clearance_m)

    def test_the_plant_is_the_one_plant_implementation(self):
        p = self.rep["plant"]
        self.assertEqual(p["name"], GUIDED_DEFAULT.name)
        self.assertEqual(p["a_max_ne_mps2"], GUIDED_DEFAULT.a_max_ne_mps2)
        self.assertAlmostEqual(p["t_req_s"], time_to_displace_s(3.0, GUIDED_DEFAULT), places=4)

    def test_the_bird_speed_comes_from_the_birds_config(self):
        self.assertAlmostEqual(self.rep["encounter"]["bird_speed_mps"], max_bird_speed_m_s(),
                               places=4)

    def test_the_latency_budget_is_the_camera_rate_plus_the_measured_tick(self):
        cfg = json.loads(DEPTH_CONFIG.read_text())
        want = 1.0 / cfg["camera"]["update_rate_hz"] + cfg["booking_gate"]["control_tick_latency_s"]
        self.assertAlmostEqual(self.rep["budget"]["pipeline_latency_s"], want, places=6)

    def test_the_margin_factor_is_the_adr_019_one(self):
        self.assertEqual(self.rep["budget"]["lead_margin_factor"],
                         json.loads(DEPTH_CONFIG.read_text())["booking_gate"]["lead_margin_factor"])


class TestPlantValuesAgainstClosedForms(unittest.TestCase):
    """Independent of `eval/point_mass`'s own internals: every expectation below is written out
    from the plant's a_max / jerk / v_max constants using the formulas
    `tests/test_point_mass_replay.py` pins the simulator against."""

    def setUp(self):
        self.a = GUIDED_DEFAULT.a_max_ne_mps2
        self.j = GUIDED_DEFAULT.jerk_ne_mps3
        self.t1 = self.a / self.j                    # end of the jerk ramp: 0.5 s
        self.s1 = self.j * self.t1 ** 3 / 6.0        # 0.10417 m
        self.v1 = 0.5 * self.j * self.t1 ** 2        # 0.625 m/s

    def test_jerk_regime_matches_j_t_cubed_over_six(self):
        for t in (0.3, 0.4):
            self.assertLess(t, self.t1)
            self.assertAlmostEqual(max_displacement_m(t, GUIDED_DEFAULT),
                                   self.j * t ** 3 / 6.0, places=9, msg=f"t={t}")

    def test_accel_regime_matches_the_three_phase_form(self):
        for t in (1.0, 1.5):
            u = t - self.t1
            self.assertAlmostEqual(max_displacement_m(t, GUIDED_DEFAULT),
                                   self.s1 + self.v1 * u + 0.5 * self.a * u * u,
                                   places=9, msg=f"t={t}")

    def test_t_req_matches_the_analytic_quadratic_root(self):
        """The number the whole gate hangs on, solved in closed form rather than bisected: after the
        jerk ramp, 0.5*a*u^2 + v1*u + s1 = bar. A displacement mutant that scaled the plant 3x would
        move this to ~1.00 s and be caught here, where the bisection cross-check could not see it."""
        bar = PolicyParams().min_bird_clearance_m
        u = (-self.v1 + math.sqrt(self.v1 ** 2 - 4 * (0.5 * self.a) * (self.s1 - bar))) / self.a
        analytic = self.t1 + u
        self.assertAlmostEqual(analytic, 1.792454754, places=6)     # the published value
        self.assertAlmostEqual(pfl.evaluate(RECOMMENDED_SPEED_MPS)["plant"]["t_req_s"],
                               analytic, places=4)

    def test_the_escape_figure_is_labelled_as_a_restatement_not_a_check(self):
        """It is algebraically implied by `margin`, so it must not appear in `checks`."""
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS)
        self.assertNotIn("escape_clears_the_bar", [c["name"] for c in rep["checks"]])
        self.assertIn("escape_at_available_lead_m", rep["budget"])


class TestArithmetic(unittest.TestCase):
    def test_margin_matches_the_conservative_reading_recomputed_by_hand(self):
        rep = pfl.evaluate(4.0)
        b, e = rep["budget"], rep["encounter"]
        need = b["need_s"]
        lead = rep["sensor"]["acquisition_range_m"] / e["closing_speed_mps"]
        self.assertAlmostEqual(b["available_lead_s"], lead, places=3)
        self.assertAlmostEqual(b["margin"], lead / need, places=3)
        # The LENIENT reading (subtract latency, then multiply) would give a different, larger
        # number. Pinned so the published margin can never silently switch conventions.
        lenient = (lead - b["pipeline_latency_s"]) / (need - b["pipeline_latency_s"])
        self.assertGreater(lenient, b["margin"])

    def test_slower_is_never_worse_and_a_longer_horizon_is_never_worse(self):
        """Unlike the NADIR bird-visibility predictor -- whose speed response ADR-016 am. 1
        measured NON-monotone -- this gate is monotone in both knobs by construction."""
        margins = [pfl.evaluate(v)["budget"]["margin"] for v in (2.0, 4.0, 6.0, 8.0, 10.0)]
        self.assertEqual(margins, sorted(margins, reverse=True))
        by_range = [pfl.evaluate(5.0, acq_range_m=r)["budget"]["margin"] for r in (20, 30, 40, 47)]
        self.assertEqual(by_range, sorted(by_range))

    def test_a_speed_cap_below_wpnav_default_does_not_move_t_req(self):
        """ADR-016 am. 2's tuning-override concern, priced rather than assumed."""
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS)
        self.assertFalse(rep["plant"]["speed_cap_changes_t_req"])
        self.assertAlmostEqual(rep["plant"]["t_req_s_at_mission_speed_cap"],
                               rep["plant"]["t_req_s"], places=6)

    def test_the_far_clip_bound_is_the_frame_CORNER_not_the_axis(self):
        """The gz far cull is on EUCLIDEAN slant range while the stored value is Z-depth, so the
        effective Z-depth horizon shrinks by |ray| off-axis: 60 m becomes 47.56 m at the corner.
        Quoting the on-axis 60 m would overstate the margin over the 46.80 m acquisition bound by
        more than an order of magnitude (22 % vs the true 1.6 %)."""
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS)
        s = rep["sensor"]
        fx, cx, cy = s["fx_px"], s["cx_px"], s["cy_px"]
        corner = math.sqrt(1.0 + (cx / fx) ** 2 + (cy / fx) ** 2)
        self.assertAlmostEqual(s["clip_far_at_frame_corner_m"], s["clip_far_m"] / corner, places=3)
        self.assertAlmostEqual(s["clip_far_at_frame_corner_m"], 47.558, places=2)
        self.assertLess(s["clip_far_at_frame_corner_m"], s["clip_far_m"])


class TestTeeth(unittest.TestCase):
    def test_it_fails_at_arducopters_own_default_cruise_speed(self):
        rep = pfl.evaluate(10.0)
        self.assertFalse(rep["verdict"]["pass"])
        self.assertEqual(_run("--speed", "10.0").returncode, pfl.EXIT_FAIL)

    def test_it_fails_when_the_measured_horizon_comes_in_short(self):
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS, fx_px=520.0, cy_px=240.0, acq_range_m=20.0)
        self.assertFalse(rep["verdict"]["pass"])
        self.assertFalse(rep["verdict"]["bookable"])
        self.assertEqual(
            _run("--speed", "5.0", "--fx", "520.0", "--cy", "240.0",
                 "--acq-range-m", "20.0").returncode, pfl.EXIT_FAIL)

    def test_it_fails_when_the_band_is_out_of_frame_at_acquisition(self):
        rep = pfl.evaluate(1.0, fx_px=520.0, cy_px=240.0, acq_range_m=5.0)
        band = next(c for c in rep["checks"] if c["name"] == "band_in_frame_at_acquisition")
        self.assertFalse(band["ok"])

    def test_it_fails_when_acquisition_outruns_the_corner_far_clip(self):
        """An acquisition range inside the on-axis 60 m clip but beyond the 47.56 m corner clip is a
        real failure: a target at the frame corner is culled before it can ever be detected."""
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS, fx_px=520.0058, cy_px=240.0, acq_range_m=55.0)
        corner = next(c for c in rep["checks"] if c["name"] == "acquisition_within_corner_far_clip")
        self.assertFalse(corner["ok"])
        self.assertFalse(rep["verdict"]["pass"])


class TestInputValidation(unittest.TestCase):
    """Garbage in must be a REFUSAL (exit 2), never a verdict. `--acq-range-m inf` exiting 0
    BOOKABLE is the failure this class exists to make impossible."""

    def test_acquisition_beyond_the_far_clip_is_refused_and_names_the_clip(self):
        for bad in ("100", "inf", "1e9"):
            proc = _run("--speed", "5.0", "--fx", "520.0", "--cy", "240.0", "--acq-range-m", bad)
            self.assertEqual(proc.returncode, pfl.EXIT_REFUSED, msg=f"{bad}: {proc.stdout}")
            self.assertIn("60", proc.stderr + proc.stdout, msg=f"{bad}: must name the far clip")

    def test_non_positive_or_non_finite_acquisition_is_refused(self):
        for bad in ("0", "-5", "nan"):
            self.assertEqual(
                _run("--speed", "5.0", "--fx", "520.0", "--cy", "240.0",
                     "--acq-range-m", bad).returncode, pfl.EXIT_REFUSED, msg=bad)

    def test_non_finite_or_non_positive_speed_is_refused_not_failed(self):
        """It used to exit 1 -- i.e. garbage read as 'the sensor is insufficient', which is a
        conclusion about the hardware drawn from a typo."""
        for bad in ("nan", "inf", "-inf", "0", "-3"):
            self.assertEqual(_run("--speed", bad).returncode, pfl.EXIT_REFUSED, msg=bad)

    def test_half_a_live_intrinsic_set_is_refused(self):
        """fx live + cy from config is a 2x-optimistic mixed-intrinsics answer: fx sets the
        acquisition range and cy sets the band coverage, and they must come from the same message."""
        self.assertEqual(_run("--speed", "5.0", "--fx", "520.0").returncode, pfl.EXIT_REFUSED)
        self.assertEqual(_run("--speed", "5.0", "--cy", "240.0").returncode, pfl.EXIT_REFUSED)

    def test_insane_intrinsics_are_refused(self):
        for args in (("--fx", "0", "--cy", "240"), ("--fx", "-520", "--cy", "240"),
                     ("--fx", "520", "--cy", "0"), ("--fx", "nan", "--cy", "240")):
            self.assertEqual(_run("--speed", "5.0", *args).returncode, pfl.EXIT_REFUSED,
                             msg=str(args))

    def test_evaluate_itself_refuses_rather_than_trusting_its_caller(self):
        with self.assertRaises(ValueError):
            pfl.evaluate(0.0)
        with self.assertRaises(ValueError):
            pfl.evaluate(5.0, fx_px=520.0, cy_px=240.0, acq_range_m=1e6)
        with self.assertRaises(ValueError):
            pfl.evaluate(5.0, fx_px=520.0)          # half a live set


class TestBookability(unittest.TestCase):
    def test_no_speed_is_a_refusal_not_a_verdict(self):
        proc = _run()
        self.assertEqual(proc.returncode, pfl.EXIT_REFUSED)
        self.assertIn("--speed is REQUIRED", proc.stderr)

    def test_config_sourced_pass_is_not_bookable(self):
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS)
        self.assertTrue(rep["verdict"]["pass"])
        self.assertFalse(rep["verdict"]["bookable"])
        proc = _run("--speed", str(RECOMMENDED_SPEED_MPS))
        self.assertEqual(proc.returncode, pfl.EXIT_PASS_NOT_BOOKABLE)
        self.assertIn("NOT BOOKABLE", proc.stdout)

    def test_exit_zero_is_unreachable_without_live_inputs_in_EVERY_mode(self):
        """THE property. The single-speed mode and the sweep publish the same exit code, and
        FORWARD_DEPTH_SENSOR.md/AVOIDANCE_REAL_DETECTION.md both say 'exit 0 = book the flight'.
        A sweep that exits 0 on config numbers is the 2026-08-25 defect in a new costume: one exit
        code carrying two meanings."""
        config_only_modes = (
            ("--speed", "5.0"),
            ("--speed", "5.0", "--json", "/dev/null"),
            ("--sweep", "2:10:2"),
            ("--sweep", "2:10:2", "--json", "/dev/null"),
        )
        for mode in config_only_modes:
            proc = _run(*mode)
            self.assertNotEqual(proc.returncode, pfl.EXIT_PASS_BOOKABLE, msg=f"{mode}: {proc.stdout}")
            self.assertEqual(proc.returncode, pfl.EXIT_PASS_NOT_BOOKABLE, msg=str(mode))

    def test_live_measured_pass_is_bookable_and_exits_zero(self):
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS, **LIVE_KW)
        self.assertTrue(rep["verdict"]["bookable"])
        proc = _run("--speed", "5.0", *LIVE)
        self.assertEqual(proc.returncode, pfl.EXIT_PASS_BOOKABLE)
        self.assertIn("PASS and BOOKABLE", proc.stdout)

    def test_the_four_exit_codes_are_distinct(self):
        self.assertEqual(len({pfl.EXIT_PASS_BOOKABLE, pfl.EXIT_FAIL, pfl.EXIT_REFUSED,
                              pfl.EXIT_PASS_NOT_BOOKABLE}), 4)


class TestPublishedNumbers(unittest.TestCase):
    def test_the_recommended_speed_reproduces_the_adr_020_margin(self):
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS)
        self.assertAlmostEqual(rep["budget"]["margin"], PUBLISHED_MARGIN, places=3,
                               msg="the published booking-gate margin moved -- re-open ADR-020 "
                                   "rather than editing this number")

    def test_the_geometric_horizon_is_the_documented_one(self):
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS)
        self.assertAlmostEqual(rep["sensor"]["geometric_acquisition_range_m"], 46.800, places=2)
        self.assertAlmostEqual(rep["sensor"]["band_covered_from_m"], 13.000, places=2)


class TestArtifact(unittest.TestCase):
    """The JSON is what authorises a flight, so its shape is pinned and the tool refuses to write a
    malformed one."""

    def test_single_speed_artifact_validates_and_carries_a_verdict(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "booking_gate.json"
            proc = _run("--speed", "5.0", "--json", str(out))
            self.assertEqual(proc.returncode, pfl.EXIT_PASS_NOT_BOOKABLE)
            rep = json.loads(out.read_text())
            pfl.validate_report(rep)                       # raises on a malformed artifact
            self.assertAlmostEqual(rep["budget"]["margin"], PUBLISHED_MARGIN, places=3)
            self.assertIs(rep["verdict"]["bookable"], False)

    def test_sweep_artifact_carries_a_TOP_LEVEL_verdict(self):
        """Without one, a reader of `booking_gate_*.json` has to re-derive bookability from rows."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sweep.json"
            _run("--sweep", "2:10:2", "--json", str(out))
            rep = json.loads(out.read_text())
            pfl.validate_report(rep)
            self.assertIn("verdict", rep)
            self.assertIs(rep["verdict"]["bookable"], False)
            self.assertTrue(rep["verdict"]["pass"])
            self.assertEqual(rep["verdict"]["exit_code"], pfl.EXIT_PASS_NOT_BOOKABLE)
            self.assertEqual(len(rep["sweep"]), 5)

    def test_validate_report_rejects_a_missing_verdict(self):
        with self.assertRaises(ValueError):
            pfl.validate_report({"schema_version": "1.1", "tool": "x"})


class TestSweep(unittest.TestCase):
    def test_sweep_on_config_inputs_is_pass_but_NOT_bookable(self):
        proc = _run("--sweep", "2:10:2")
        self.assertEqual(proc.returncode, pfl.EXIT_PASS_NOT_BOOKABLE)
        for v in ("2.00", "4.00", "6.00", "8.00", "10.00"):
            self.assertIn(v, proc.stdout)
        self.assertIn("fastest passing mission speed", proc.stdout)
        self.assertIn("NOT BOOKABLE", proc.stdout)

    def test_sweep_prints_bookability_per_row(self):
        cfg = _run("--sweep", "2:6:2").stdout
        self.assertIn("PASS*", cfg)              # passes, not bookable
        self.assertNotIn("BOOKABLE  ", cfg)
        live = _run("--sweep", "2:6:2", *LIVE).stdout
        self.assertIn("BOOKABLE", live)

    def test_sweep_with_live_inputs_exits_zero(self):
        self.assertEqual(_run("--sweep", "2:6:2", *LIVE).returncode, pfl.EXIT_PASS_BOOKABLE)

    def test_a_live_sweep_with_ANY_failing_row_is_not_bookable(self):
        """QA round-2 N1: exit 0 from a sweep must mean EVERY swept speed is bookable.

        'Some speed in this range passes' is a choosing claim, not an authorising one --
        and the mixed live sweep was the single case that exited 0 while printing FAIL
        rows with no caveat. A sweep never authorises; a single --speed run does (D4)."""
        proc = _run("--sweep", "2:10:2", *LIVE)   # 8 and 10 m/s FAIL on this config
        self.assertEqual(proc.returncode, pfl.EXIT_PASS_NOT_BOOKABLE)
        self.assertIn("FAIL", proc.stdout)
        self.assertIn("single --speed run", proc.stdout)

    def test_sweep_fails_when_nothing_passes(self):
        proc = _run("--sweep", "20:24:2", *LIVE)
        self.assertEqual(proc.returncode, pfl.EXIT_FAIL)
        self.assertIn("NO mission speed in this range passes", proc.stdout)

    def test_sweep_spec_is_validated(self):
        for bad in ("2:10", "10:2:1", "2:10:0", "a:b:c"):
            self.assertEqual(_run("--sweep", bad).returncode, 2)

    def test_sweep_endpoints_are_inclusive(self):
        self.assertEqual(pfl._parse_sweep("2:4:0.5"), [2.0, 2.5, 3.0, 3.5, 4.0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
