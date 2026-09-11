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
    WP_SPD default, and it fails when the measured horizon comes in short.
  * `TestInputValidation` -- an out-of-clip horizon, a non-finite or non-positive speed, and any
    PART of the six-number live intrinsic set are all REFUSALS (exit 2), never verdicts.
    `--acq-range-m inf` used to exit 0 BOOKABLE.
  * `TestFrameCornerBound` -- the QA probe C regressions (2026-09-06). The corner ray must be built
    from the FARTHEST corner (`max(cx, W-1-cx)`, `max(cy, H-1-cy)`), must divide the vertical term
    by `fy`, and must take W/H from the LIVE message. The formula this replaced got all three wrong
    in the same direction: at a live `cy` of 120 it published a 50.14 m corner horizon where the
    true one is 44.05 m, and exited 0 BOOKABLE on a 50.0 m acquisition range.
  * `TestLiveConfigCrossCheck` -- live `WxH` that disagrees with the config is a REFUSAL naming
    both. The world SDF is generated from that config, so a mismatch means the wrong camera.
  * `TestSchema12Clamp` -- the artifact must say whether the booked acquisition range was CLAMPED
    from a longer optical prefix (ADR-020 am. 1); a schema 1.2 report without those fields is
    invalid, and a `--acq-range-m` LONGER than the prefix it was clamped from is a refusal.
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
# actually ran docs/runbooks/FORWARD_DEPTH_SENSOR.md gates D1/D3 would hand the tool. All six
# intrinsics come off ONE camera_info; anything less is a refusal, which is what makes this a
# constant rather than six literals sprinkled through the file.
LIVE_INTRINSICS = ("--fx", "520.0058", "--fy", "520.0058", "--cx", "320", "--cy", "240.0",
                   "--width", "640", "--height", "480")
LIVE_INTRINSICS_KW = dict(fx_px=520.0058, fy_px=520.0058, cx_px=320.0, cy_px=240.0,
                          width_px=640.0, height_px=480.0)
LIVE = LIVE_INTRINSICS + ("--acq-range-m", "40.0")
LIVE_KW = dict(LIVE_INTRINSICS_KW, acq_range_m=40.0)

# The numbers gate D3 actually measured in the render on 2026-09-06 (ADR-020 am. 1): the live
# camera_info, the BOOKABLE acquisition range and the optical prefix it was clamped from.
D3_FX, D3_FY = 520.0058046927554, 520.0058046927553
D3_BOOKABLE_M, D3_OPTICAL_PREFIX_M = 46.0, 58.0
D3_LIVE = ("--fx", repr(D3_FX), "--fy", repr(D3_FY), "--cx", "320", "--cy", "240",
           "--width", "640", "--height", "480")
D3_KW = dict(fx_px=D3_FX, fy_px=D3_FY, cx_px=320.0, cy_px=240.0,
             width_px=640.0, height_px=480.0)


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

    def test_the_MARGIN_is_monotone_in_both_knobs_but_the_VERDICT_is_NOT(self):
        """The runbook published 'the gate's speed response is monotone (slower is never worse, a
        longer horizon is never worse)' and used it to justify 'when unsure, pass the safe end'.
        The margin is monotone; the VERDICT is not, in either knob, and the safe end of the horizon
        knob is the FAILING one (QA, 2026-09-07). Pinned here so the prose cannot drift back:

          * a LONGER --acq-range-m raises the margin all the way to the far clip, and then FAILS
            `acquisition_within_corner_far_clip` past 47.56 m -- 47.5 exits 0, 47.6 exits 1;
          * a SLOWER --speed raises the margin, and below the plant's speed cap the tool's own
            NOTE says t_req MOVES (0.6 m/s -> 5.326 s against the 1.792 s the verdict used), so
            the printed margin is no longer the escape it describes.

        ADR-016 am. 1 / G60 is the family: a monotonicity asserted in prose, relied on to skip a
        re-run, where the direction assumed safe is the one that fails."""
        margins = [pfl.evaluate(v)["budget"]["margin"] for v in (2.0, 4.0, 6.0, 8.0, 10.0)]
        self.assertEqual(margins, sorted(margins, reverse=True))
        by_range = [pfl.evaluate(5.0, acq_range_m=r)["budget"]["margin"] for r in (20, 30, 40, 47)]
        self.assertEqual(by_range, sorted(by_range))
        # ...and now the two places the VERDICT breaks that intuition.
        near, past = (pfl.evaluate(5.0, **dict(LIVE_INTRINSICS_KW, acq_range_m=r))
                      for r in (47.5, 47.6))
        self.assertTrue(near["verdict"]["pass"])
        self.assertFalse(past["verdict"]["pass"], "a longer horizon must be able to FAIL")
        self.assertGreater(past["budget"]["margin"], near["budget"]["margin"])
        self.assertEqual([c["name"] for c in past["checks"] if not c["ok"]],
                         ["acquisition_within_corner_far_clip"])
        slow = pfl.evaluate(0.6, **dict(LIVE_INTRINSICS_KW, acq_range_m=46.0))
        self.assertTrue(slow["plant"]["speed_cap_changes_t_req"],
                        "below the cap the escape gets SLOWER, which the margin does not show")
        self.assertGreater(slow["plant"]["t_req_s_at_mission_speed_cap"], slow["plant"]["t_req_s"])

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
        fx, fy, cx, cy = s["fx_px"], s["fy_px"], s["cx_px"], s["cy_px"]
        w, h = s["image_width_px"], s["image_height_px"]
        corner = math.sqrt(1.0 + (max(cx, w - 1 - cx) / fx) ** 2
                           + (max(cy, h - 1 - cy) / fy) ** 2)
        self.assertAlmostEqual(s["clip_far_at_frame_corner_m"], s["clip_far_m"] / corner, places=3)
        self.assertAlmostEqual(s["clip_far_at_frame_corner_m"], 47.558, places=2)
        self.assertLess(s["clip_far_at_frame_corner_m"], s["clip_far_m"])


class TestTeeth(unittest.TestCase):
    def test_it_fails_at_arducopters_own_default_cruise_speed(self):
        rep = pfl.evaluate(10.0)
        self.assertFalse(rep["verdict"]["pass"])
        self.assertEqual(_run("--speed", "10.0").returncode, pfl.EXIT_FAIL)

    def test_it_fails_when_the_measured_horizon_comes_in_short(self):
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS, **dict(LIVE_INTRINSICS_KW, acq_range_m=20.0))
        self.assertFalse(rep["verdict"]["pass"])
        self.assertFalse(rep["verdict"]["bookable"])
        self.assertEqual(
            _run("--speed", "5.0", *LIVE_INTRINSICS, "--acq-range-m", "20.0").returncode,
            pfl.EXIT_FAIL)

    def test_it_fails_when_the_band_is_out_of_frame_at_acquisition(self):
        rep = pfl.evaluate(1.0, **dict(LIVE_INTRINSICS_KW, acq_range_m=5.0))
        band = next(c for c in rep["checks"] if c["name"] == "band_in_frame_at_acquisition")
        self.assertFalse(band["ok"])

    def test_it_fails_when_acquisition_outruns_the_corner_far_clip(self):
        """An acquisition range inside the on-axis 60 m clip but beyond the 47.56 m corner clip is a
        real failure: a target at the frame corner is culled before it can ever be detected."""
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS, **dict(LIVE_INTRINSICS_KW, acq_range_m=55.0))
        corner = next(c for c in rep["checks"] if c["name"] == "acquisition_within_corner_far_clip")
        self.assertFalse(corner["ok"])
        self.assertFalse(rep["verdict"]["pass"])

    def test_the_2026_09_06_optical_prefix_is_refused_and_the_bookable_range_is_not(self):
        """The measured contrast that ADR-020 am. 1's clamp rule exists for, on the real live
        intrinsics: 58.0 m (D3's optical prefix) FAILS the corner check and nothing else, at every
        speed, while 46.0 m (D3's bookable range) exits 0 at margin 1.780x."""
        bad = _run("--speed", "5.0", *D3_LIVE, "--acq-range-m", str(D3_OPTICAL_PREFIX_M))
        self.assertEqual(bad.returncode, pfl.EXIT_FAIL, msg=bad.stdout)
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS,
                           **dict(D3_KW, acq_range_m=D3_OPTICAL_PREFIX_M))
        failing = [c["name"] for c in rep["checks"] if not c["ok"]]
        self.assertEqual(failing, ["acquisition_within_corner_far_clip"])

        good = _run("--speed", "5.0", *D3_LIVE, "--acq-range-m", str(D3_BOOKABLE_M),
                    "--acq-optical-prefix-m", str(D3_OPTICAL_PREFIX_M))
        self.assertEqual(good.returncode, pfl.EXIT_PASS_BOOKABLE, msg=good.stdout + good.stderr)
        ok = pfl.evaluate(RECOMMENDED_SPEED_MPS, **dict(D3_KW, acq_range_m=D3_BOOKABLE_M))
        self.assertAlmostEqual(ok["budget"]["margin"], 1.780, places=3)
        self.assertAlmostEqual(ok["sensor"]["clip_far_at_frame_corner_m"], 47.56, places=2)


class TestInputValidation(unittest.TestCase):
    """Garbage in must be a REFUSAL (exit 2), never a verdict. `--acq-range-m inf` exiting 0
    BOOKABLE is the failure this class exists to make impossible."""

    def test_acquisition_beyond_the_far_clip_is_refused_and_names_the_clip(self):
        for bad in ("100", "inf", "1e9"):
            proc = _run("--speed", "5.0", *LIVE_INTRINSICS, "--acq-range-m", bad)
            self.assertEqual(proc.returncode, pfl.EXIT_REFUSED, msg=f"{bad}: {proc.stdout}")
            self.assertIn("60", proc.stderr + proc.stdout, msg=f"{bad}: must name the far clip")

    def test_non_positive_or_non_finite_acquisition_is_refused(self):
        for bad in ("0", "-5", "nan"):
            self.assertEqual(
                _run("--speed", "5.0", *LIVE_INTRINSICS, "--acq-range-m", bad).returncode,
                pfl.EXIT_REFUSED, msg=bad)

    def test_non_finite_or_non_positive_speed_is_refused_not_failed(self):
        """It used to exit 1 -- i.e. garbage read as 'the sensor is insufficient', which is a
        conclusion about the hardware drawn from a typo."""
        for bad in ("nan", "inf", "-inf", "0", "-3"):
            self.assertEqual(_run("--speed", bad).returncode, pfl.EXIT_REFUSED, msg=bad)

    def test_ANY_part_of_the_six_number_live_set_is_refused(self):
        """A live number beside a config one is an answer assembled from two cameras. Every
        one-short set is refused, and the refusal must NAME the missing flags -- an operator who
        pasted five of six numbers should not have to diff the usage text to find the sixth."""
        for drop in ("--fx", "--fy", "--cx", "--cy", "--width", "--height"):
            i = LIVE_INTRINSICS.index(drop)
            partial = LIVE_INTRINSICS[:i] + LIVE_INTRINSICS[i + 2:]
            proc = _run("--speed", "5.0", *partial, "--acq-range-m", "40.0")
            self.assertEqual(proc.returncode, pfl.EXIT_REFUSED, msg=f"{drop}: {proc.stdout}")
            self.assertIn(drop, proc.stderr, msg=f"the refusal must name the missing {drop}")
        # and the two-number set that used to be the whole live contract
        self.assertEqual(_run("--speed", "5.0", "--fx", "520.0", "--cy", "240.0").returncode,
                         pfl.EXIT_REFUSED)

    def test_insane_intrinsics_are_refused(self):
        overrides = (("--fx", "0"), ("--fx", "-520"), ("--fx", "nan"), ("--fy", "0"),
                     ("--fy", "inf"), ("--cx", "0"), ("--cy", "0"), ("--cy", "nan"),
                     ("--width", "0"), ("--height", "-480"))
        for flag, bad in overrides:
            i = LIVE_INTRINSICS.index(flag)
            args = LIVE_INTRINSICS[:i + 1] + (bad,) + LIVE_INTRINSICS[i + 2:]
            self.assertEqual(_run("--speed", "5.0", *args).returncode, pfl.EXIT_REFUSED,
                             msg=f"{flag}={bad}")

    def test_a_non_integral_frame_size_is_refused_not_rounded(self):
        """camera_info.width/height are uint32; 640.5 is a transcription slip, and rounding it
        would move the frame-corner bound silently."""
        i = LIVE_INTRINSICS.index("--width")
        args = LIVE_INTRINSICS[:i + 1] + ("640.5",) + LIVE_INTRINSICS[i + 2:]
        proc = _run("--speed", "5.0", *args, "--acq-range-m", "40.0")
        self.assertEqual(proc.returncode, pfl.EXIT_REFUSED)
        self.assertIn("whole number", proc.stderr)

    def test_a_principal_point_outside_the_frame_is_refused(self):
        """cy=600 in a 480-row frame is not a camera. It would also make the farthest-corner term
        6.4x too large, i.e. fail SAFE -- refused anyway, because a bound computed from a number
        that cannot be true is not evidence in either direction."""
        proc = _run("--speed", "5.0", "--fx", "520.0", "--fy", "520.0", "--cx", "320",
                    "--cy", "600", "--width", "640", "--height", "480", "--acq-range-m", "40.0")
        self.assertEqual(proc.returncode, pfl.EXIT_REFUSED)
        self.assertIn("outside", proc.stderr)

    def test_evaluate_itself_refuses_rather_than_trusting_its_caller(self):
        with self.assertRaises(ValueError):
            pfl.evaluate(0.0)
        with self.assertRaises(ValueError):
            pfl.evaluate(5.0, **dict(LIVE_INTRINSICS_KW, acq_range_m=1e6))
        with self.assertRaises(ValueError):
            pfl.evaluate(5.0, fx_px=520.0)          # part of a live set
        with self.assertRaises(ValueError):
            pfl.evaluate(5.0, **dict(LIVE_INTRINSICS_KW, fy_px=None))


def _old_corner_bound_m(fx, cx, cy, far_m=60.0):
    """The formula this file's regressions exist to keep dead: `sqrt(1 + (cx/fx)^2 + (cy/fx)^2)`.
    Written out once, here, so the tests can state what the bug PRODUCED rather than only what the
    fix produces -- a test that pins 44.05 m without pinning the 50.14 m it replaced does not say
    which direction the error ran."""
    return far_m / math.sqrt(1.0 + (cx / fx) ** 2 + (cy / fx) ** 2)


class TestFrameCornerBound(unittest.TestCase):
    """QA probe C, 2026-09-06 -- reproduced live and fixed here.

    `acquisition_within_corner_far_clip` is the check that keeps a horizon inside the range gz can
    actually return off-axis, and its bound was built from `sqrt(1 + (cx/fx)^2 + (cy/fx)^2)` with
    `cx` from CONFIG. Three independent errors, all optimistic: the vertical term used `cy` rather
    than the FARTHEST corner row `max(cy, H-1-cy)`, it divided by `fx` rather than `fy`, and the
    frame size never came off the live message at all. None of them bit at the live (320, 240) of
    this mount, which is exactly why they had to be fixed before a live number that is not (320,
    240) is ever pasted in."""

    LIVE_120 = ("--fx", repr(D3_FX), "--fy", repr(D3_FY), "--cx", "320", "--cy", "120",
                "--width", "640", "--height", "480")
    KW_120 = dict(fx_px=D3_FX, fy_px=D3_FY, cx_px=320.0, cy_px=120.0,
                  width_px=640.0, height_px=480.0)

    def test_a_low_principal_point_is_bounded_by_the_FAR_row_and_now_FAILS(self):
        """THE regression. `--cy 120 --acq-range-m 50.0` exited 0 BOOKABLE against a 50.14 m bound;
        the farthest corner row is 359 px away, not 120, and the true bound is 44.05 m."""
        self.assertAlmostEqual(_old_corner_bound_m(D3_FX, 320.0, 120.0), 50.14, places=2)
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS, **dict(self.KW_120, acq_range_m=50.0))
        self.assertAlmostEqual(rep["sensor"]["clip_far_at_frame_corner_m"], 44.05, places=2)
        corner = next(c for c in rep["checks"] if c["name"] == "acquisition_within_corner_far_clip")
        self.assertFalse(corner["ok"])
        proc = _run("--speed", "5.0", *self.LIVE_120, "--acq-range-m", "50.0")
        self.assertEqual(proc.returncode, pfl.EXIT_FAIL, msg=proc.stdout)
        self.assertNotIn("BOOKABLE", proc.stdout)

    def test_the_bound_is_never_looser_than_the_formula_it_replaced(self):
        """The whole class of fix in one property: over every principal-point row, the farthest-row
        bound is <= the old one, and STRICTLY below it whenever cy sits above frame centre."""
        for cy in (60.0, 120.0, 239.0, 240.0, 300.0, 400.0):
            new = pfl.evaluate(RECOMMENDED_SPEED_MPS,
                               **dict(self.KW_120, cy_px=cy))["sensor"][
                                   "clip_far_at_frame_corner_m"]
            old = _old_corner_bound_m(D3_FX, 320.0, cy)
            self.assertLessEqual(new, old + 1e-3, msg=f"cy={cy}")   # 1e-3 = the report's rounding
            if cy < 239.5:
                self.assertLess(new, old - 0.01, msg=f"cy={cy} must be strictly tighter")

    def test_the_reported_corner_pixel_is_the_farthest_one(self):
        low = pfl.evaluate(RECOMMENDED_SPEED_MPS, **self.KW_120)["sensor"]
        self.assertEqual(low["clip_far_corner_pixel_uv"], [0.0, 479.0])
        self.assertEqual(low["clip_far_corner_offset_px"], [320.0, 359.0])
        high = pfl.evaluate(RECOMMENDED_SPEED_MPS,
                            **dict(self.KW_120, cx_px=100.0, cy_px=400.0))["sensor"]
        self.assertEqual(high["clip_far_corner_pixel_uv"], [639.0, 0.0])
        self.assertEqual(high["clip_far_corner_offset_px"], [539.0, 400.0])

    def test_the_vertical_term_divides_by_fy_not_fx(self):
        """Non-square pixels are the case that separates them. fy = fx/2 doubles the vertical
        angular extent, and a bound that used fx would not move at all."""
        kw = dict(LIVE_INTRINSICS_KW, fy_px=260.0029)
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS, **kw)["sensor"]
        want = 60.0 / math.sqrt(1.0 + (320.0 / 520.0058) ** 2 + (240.0 / 260.0029) ** 2)
        self.assertAlmostEqual(rep["clip_far_at_frame_corner_m"], want, places=3)
        self.assertLess(rep["clip_far_at_frame_corner_m"],
                        pfl.evaluate(RECOMMENDED_SPEED_MPS,
                                     **LIVE_INTRINSICS_KW)["sensor"]["clip_far_at_frame_corner_m"])
        # and the same fy reaches the band-coverage number, which is also a vertical quantity.
        # 239, not 240: the band must fit above AND below the axis, so the binding half-extent is
        # min(cy, H-1-cy) -- the frame's last row is 479.
        self.assertAlmostEqual(rep["band_covered_from_m"], 6.0 * 260.0029 / 239.0, places=3)

    def test_the_bound_agrees_with_the_STATIC_gate_that_computes_the_same_thing(self):
        """`check_depth_mount.corner_ray_ratio` is the same primitive on config inputs, and the two
        copies are deliberate (three gates, three interpreters, three input sources -- see its
        docstring). Deliberate duplication is only honest if something pins the copies equal; this
        is that thing. If this fails with an ImportError, the primitive MOVED and both copies plus
        the in-render gate's scoring block have to move with it."""
        from check_depth_mount import corner_ray_ratio
        for cx, cy in ((320.0, 240.0), (320.0, 120.0), (100.0, 400.0), (600.0, 20.0)):
            s = pfl.evaluate(RECOMMENDED_SPEED_MPS,
                             **dict(LIVE_INTRINSICS_KW, cx_px=cx, cy_px=cy))["sensor"]
            want = 60.0 / corner_ray_ratio(640.0, 480.0, s["fx_px"], s["fy_px"],
                                           s["cx_px"], s["cy_px"])
            self.assertAlmostEqual(s["clip_far_at_frame_corner_m"], want, places=3,
                                   msg=f"cx={cx} cy={cy}")

    def test_the_frame_size_actually_reaches_the_bound(self):
        """W/H are not decoration: on a 1280x960 sensor the same principal point sits at frame
        centre and the corner is twice as far out. Driven through a config whose generated world
        would be that camera, since a live WxH that disagrees with the config is a refusal."""
        cfg = json.loads(DEPTH_CONFIG.read_text())
        cfg["camera"]["image_width_px"], cfg["camera"]["image_height_px"] = 1280, 960
        with tempfile.TemporaryDirectory() as td:
            other = Path(td) / "depth_camera.json"
            other.write_text(json.dumps(cfg))
            big = pfl.evaluate(RECOMMENDED_SPEED_MPS,
                               **dict(LIVE_INTRINSICS_KW, width_px=1280.0, height_px=960.0),
                               depth_config=other)["sensor"]
        want = 60.0 / math.sqrt(1.0 + (959.0 / 520.0058) ** 2 + (719.0 / 520.0058) ** 2)
        self.assertAlmostEqual(big["clip_far_at_frame_corner_m"], want, places=3)
        self.assertEqual(big["clip_far_corner_pixel_uv"], [1279.0, 959.0])
        self.assertLess(big["clip_far_at_frame_corner_m"], 30.0)


class TestLiveConfigCrossCheck(unittest.TestCase):
    """The world SDF is GENERATED from config/depth_camera.json, so a live frame size that
    disagrees with it is not a discrepancy to average over -- it means the number being read
    belongs to a different camera, or the world was built from an older config."""

    def test_a_live_frame_size_that_disagrees_with_the_config_is_refused_naming_both(self):
        proc = _run("--speed", "5.0", "--fx", "520.0", "--fy", "520.0", "--cx", "160",
                    "--cy", "120", "--width", "320", "--height", "240", "--acq-range-m", "40.0")
        self.assertEqual(proc.returncode, pfl.EXIT_REFUSED)
        self.assertIn("320x240", proc.stderr)
        self.assertIn("640x480", proc.stderr)
        self.assertIn("depth_camera.json", proc.stderr)

    def test_one_axis_off_is_enough(self):
        for w, h in (("640", "481"), ("641", "480")):
            proc = _run("--speed", "5.0", "--fx", "520.0", "--fy", "520.0", "--cx", "320",
                        "--cy", "240", "--width", w, "--height", h, "--acq-range-m", "40.0")
            self.assertEqual(proc.returncode, pfl.EXIT_REFUSED, msg=f"{w}x{h}")

    def test_the_agreeing_case_records_the_cross_check_it_did(self):
        s = pfl.evaluate(RECOMMENDED_SPEED_MPS, **LIVE_KW)["sensor"]
        self.assertEqual((s["image_width_px"], s["image_height_px"]), (640, 480))
        self.assertIn("live", s["image_size_source"])
        self.assertIn("640x480", s["image_size_cross_check"])

    def test_evaluate_raises_rather_than_preferring_one_source(self):
        with self.assertRaises(ValueError):
            pfl.evaluate(5.0, **dict(LIVE_KW, width_px=1024.0, height_px=768.0))


class TestSchema12Clamp(unittest.TestCase):
    """ADR-020 am. 1: D3 prints an optical PREFIX and a BOOKABLE range clamped to the frame-corner
    bound, and only the second may be booked. Schema 1.1 recorded `acquisition_range_source: live
    render measurement` for both, so nothing downstream could tell a clamped 46.0 from an
    unclamped one -- which is the difference between a horizon and a scene artifact."""

    def test_the_clamp_is_recorded_with_the_prefix_and_the_bound(self):
        s = pfl.evaluate(RECOMMENDED_SPEED_MPS,
                         **dict(D3_KW, acq_range_m=D3_BOOKABLE_M,
                                acq_optical_prefix_m=D3_OPTICAL_PREFIX_M))["sensor"]
        self.assertEqual(s["acquisition_optical_prefix_m"], D3_OPTICAL_PREFIX_M)
        self.assertIs(s["acquisition_clamped_from_optical_prefix"], True)
        self.assertAlmostEqual(s["acquisition_clamp_bound_m"], 47.56, places=2)
        self.assertEqual(s["acquisition_range_m"], D3_BOOKABLE_M)
        # the most-read field says it on its own, rather than pointing at the ones below it
        self.assertIn("CLAMPED", s["acquisition_range_source"])
        self.assertIn("58", s["acquisition_range_source"])

    def test_no_prefix_records_no_clamp_rather_than_asserting_there_was_none(self):
        s = pfl.evaluate(RECOMMENDED_SPEED_MPS, **dict(D3_KW, acq_range_m=D3_BOOKABLE_M))["sensor"]
        self.assertIsNone(s["acquisition_optical_prefix_m"])
        self.assertIs(s["acquisition_clamped_from_optical_prefix"], False)
        self.assertIn("cannot say", s["acquisition_clamp_note"])

    def test_an_unclamped_prefix_is_not_reported_as_a_clamp(self):
        s = pfl.evaluate(RECOMMENDED_SPEED_MPS,
                         **dict(D3_KW, acq_range_m=46.0, acq_optical_prefix_m=46.0))["sensor"]
        self.assertIs(s["acquisition_clamped_from_optical_prefix"], False)
        self.assertIsNone(s["acquisition_clamp_bound_m"])

    def test_a_booked_range_LONGER_than_its_prefix_is_refused(self):
        """The fail-dangerous transcription: booking 58 m off a 46 m sweep. It cannot be a clamp in
        that direction, so it is a typo in one of the two numbers -- and the optimistic one."""
        proc = _run("--speed", "5.0", *D3_LIVE, "--acq-range-m", "46.0",
                    "--acq-optical-prefix-m", "40.0")
        self.assertEqual(proc.returncode, pfl.EXIT_REFUSED)
        self.assertIn("EXCEEDS", proc.stderr)

    def test_a_prefix_without_a_measured_range_is_refused(self):
        """A live prefix recorded beside a CONFIG-sourced acquisition range is the mixed-source
        artifact this tool refuses everywhere else."""
        proc = _run("--speed", "5.0", *D3_LIVE, "--acq-optical-prefix-m", "58.0")
        self.assertEqual(proc.returncode, pfl.EXIT_REFUSED)
        self.assertIn("--acq-range-m", proc.stderr)

    def test_a_prefix_past_the_far_clip_is_refused(self):
        proc = _run("--speed", "5.0", *D3_LIVE, "--acq-range-m", "46.0",
                    "--acq-optical-prefix-m", "100")
        self.assertEqual(proc.returncode, pfl.EXIT_REFUSED)

    def test_the_artifact_carries_1_2s_fields_and_validate_report_demands_them(self):
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS,
                           **dict(D3_KW, acq_range_m=D3_BOOKABLE_M,
                                  acq_optical_prefix_m=D3_OPTICAL_PREFIX_M))
        pfl.validate_report(rep)
        for dropped in ("acquisition_clamped_from_optical_prefix", "fy_px", "image_width_px",
                        "clip_far_corner_ray_ratio"):
            maimed = json.loads(json.dumps(rep))
            del maimed["sensor"][dropped]
            with self.assertRaises(ValueError, msg=dropped):
                pfl.validate_report(maimed)

    def test_a_1_1_artifact_still_reads(self):
        """1.1 artifacts predate the clamp fields; a reader must not reject them retroactively --
        it must only refuse to treat them as 1.2."""
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS, **LIVE_KW)
        rep["schema_version"] = "1.1"
        del rep["sensor"]["acquisition_clamped_from_optical_prefix"]
        pfl.validate_report(rep)

    def test_an_unknown_schema_version_is_refused(self):
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS, **LIVE_KW)
        rep["schema_version"] = "2.0"
        with self.assertRaises(ValueError):
            pfl.validate_report(rep)


class TestSchema13Provenance(unittest.TestCase):
    """1.3 (QA, 2026-09-07): the artifact records an ABSOLUTE config path carrying a home directory
    that means nothing on another machine, and rounds `fx`/`fy` to 4 dp -- a rounding that cannot
    show the 13th-digit difference between this mount's live fx and fy. Both are additive: every
    1.2 field is still written, and the committed 1.2 artifact is still read AS a 1.2 artifact
    rather than being retroactively malformed."""

    def setUp(self):
        self.rep = pfl.evaluate(RECOMMENDED_SPEED_MPS,
                                **dict(D3_KW, acq_range_m=D3_BOOKABLE_M,
                                       acq_optical_prefix_m=D3_OPTICAL_PREFIX_M))

    def test_the_artifact_says_1_3(self):
        self.assertEqual(self.rep["schema_version"], "1.3")
        self.assertEqual(pfl.SCHEMA_VERSION, "1.3")

    def test_the_config_is_named_the_way_the_repo_names_it_as_well(self):
        s = self.rep["sensor"]
        self.assertEqual(s["config_relpath"], "config/depth_camera.json")
        self.assertTrue(s["config"].endswith(s["config_relpath"]))

    def test_a_config_outside_the_repo_has_no_repo_relative_name_and_says_so(self):
        """None, not a fabricated path and not a crash: a test fixture or an out-of-tree copy has
        no name in this repo, and the absolute field is then the only locator."""
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "depth_camera.json"
            copy.write_text(DEPTH_CONFIG.read_text())
            rep = pfl.evaluate(RECOMMENDED_SPEED_MPS, depth_config=copy)
        self.assertIsNone(rep["sensor"]["config_relpath"])
        pfl.validate_report(rep)                       # the KEY is required, the value may be null

    def test_the_intrinsics_survive_at_full_precision_beside_the_readable_ones(self):
        """As strings, so that no reader or re-writer can round them a second time -- and the live
        fx/fy differ in the 13th digit, which 4 dp cannot show."""
        s = self.rep["sensor"]
        self.assertEqual(float(s["fx_px_exact"]), D3_FX)
        self.assertEqual(float(s["fy_px_exact"]), D3_FY)
        self.assertEqual(float(s["cx_px_exact"]), 320.0)
        self.assertEqual(float(s["cy_px_exact"]), 240.0)
        self.assertNotEqual(s["fx_px_exact"], s["fy_px_exact"])
        self.assertEqual(s["fx_px"], s["fy_px"])       # ...which the 4-dp pair cannot distinguish
        self.assertEqual((s["fx_px"], s["fy_px"]), (round(D3_FX, 4), round(D3_FY, 4)))

    def test_validate_report_demands_the_1_3_fields_ONLY_of_a_1_3_artifact(self):
        pfl.validate_report(self.rep)
        for dropped in pfl.SENSOR_FIELDS_1_3:
            maimed = json.loads(json.dumps(self.rep))
            del maimed["sensor"][dropped]
            with self.assertRaises(ValueError, msg=dropped):
                pfl.validate_report(maimed)
            maimed["schema_version"] = "1.2"           # ...and a 1.2 artifact never promised them
            pfl.validate_report(maimed)

    def test_THE_COMMITTED_1_2_ARTIFACT_still_validates_untouched(self):
        """The file that authorised the 2026-09-07 dodge booking. A schema bump may not make a
        ratified authorisation retroactively malformed; `tests/fieldguard_planning/
        test_booking_gate_artifact.py` reads it with this same function."""
        committed = REPO_ROOT / "eval" / "results" / "booking_gate_20260907T064136Z.json"
        rep = json.loads(committed.read_text())
        self.assertEqual(rep["schema_version"], "1.2")
        self.assertNotIn("config_relpath", rep["sensor"])
        pfl.validate_report(rep)

    def test_every_sweep_ROW_owes_the_same_fields_as_a_standalone_report(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sweep.json"
            _run("--sweep", "2:6:2", *LIVE, "--json", str(out))
            rep = pfl.validate_report(json.loads(out.read_text()))
        for row in rep["sweep"]:
            for key in pfl.SENSOR_FIELDS_1_3:
                self.assertIn(key, row["sensor"])


class TestMissionSpeedCapIsAChecK(unittest.TestCase):
    """QA finding G127. `t_req_s_at_mission_speed_cap` was computed, printed and gated on nothing:
    below 0.788 m/s on the booked live set the tool printed PASS/BOOKABLE and a NOTE reading
    'Re-derive before booking' -- an instruction to a human, sitting underneath the exit code that
    says no action is needed. It is now the same margin bar re-run against the plant the mission
    speed implies."""

    KW = dict(D3_KW, acq_range_m=D3_BOOKABLE_M)
    CHECK = "escape_survives_mission_speed_cap"

    def _check(self, rep):
        return next(c for c in rep["checks"] if c["name"] == self.CHECK)

    def test_a_half_metre_per_second_mission_FAILS_although_the_headline_margin_is_2_8x(self):
        rep = pfl.evaluate(0.5, **self.KW)
        self.assertGreater(rep["budget"]["margin"], 2.8)            # the optimistic reading
        self.assertLess(rep["budget"]["margin_at_mission_speed_cap"], 1.3)
        self.assertFalse(self._check(rep)["ok"])
        self.assertFalse(rep["verdict"]["pass"])
        proc = _run("--speed", "0.5", *D3_LIVE, "--acq-range-m", str(D3_BOOKABLE_M))
        self.assertEqual(proc.returncode, pfl.EXIT_FAIL, msg=proc.stdout)
        self.assertIn(self.CHECK, proc.stdout)

    def test_the_booked_5_metre_speed_is_untouched_and_the_check_says_the_cap_does_not_bind(self):
        """The authorisation this repo actually rests on must not move. The cap does not bind at
        5.0 m/s, so the check restates `lead_margin` -- and says so rather than passing silently."""
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS, **self.KW)
        self.assertTrue(rep["verdict"]["bookable"])
        self.assertAlmostEqual(rep["budget"]["margin"], 1.780, places=3)
        self.assertAlmostEqual(rep["budget"]["margin_at_mission_speed_cap"], 1.780, places=3)
        self.assertTrue(self._check(rep)["ok"])
        self.assertIn("does not bind", self._check(rep)["detail"])

    def test_the_crossover_is_where_the_measurement_says_it_is_in_both_directions(self):
        """0.788 m/s on the booked live set. Tested either side, never ON it."""
        self.assertTrue(self._check(pfl.evaluate(0.80, **self.KW))["ok"])
        self.assertFalse(self._check(pfl.evaluate(0.77, **self.KW))["ok"])

    def test_the_check_can_never_fail_a_speed_the_uncapped_reading_would_not(self):
        """Above the cap the two readings are identical, so the new check adds no false failures --
        pinned across the whole range the runbook sweeps."""
        for v in [x / 10.0 for x in range(10, 141)]:
            rep = pfl.evaluate(v, **self.KW)
            lead = next(c for c in rep["checks"] if c["name"] == "lead_margin")
            if not self._check(rep)["ok"]:
                self.assertFalse(lead["ok"] or v < 3.9,
                                 msg=f"{v} m/s: the cap check failed where lead_margin passed "
                                     f"above the plant's cap")

    def test_a_speed_so_low_the_escape_is_UNREACHABLE_fails_rather_than_reading_as_fine(self):
        """`time_to_displace_s` returns None past its 60 s horizon. Before this check that printed
        `speed_cap_changes_t_req: false` and the line '(a 0.04 m/s speed cap does not change
        t_req -- checked, not assumed)', which is false in the most dangerous direction."""
        rep = pfl.evaluate(0.04, **self.KW)
        self.assertIsNone(rep["plant"]["t_req_s_at_mission_speed_cap"])
        self.assertIsNone(rep["budget"]["margin_at_mission_speed_cap"])
        self.assertFalse(self._check(rep)["ok"])
        self.assertIn("UNREACHABLE", self._check(rep)["detail"])
        self.assertFalse(rep["verdict"]["pass"])

    def test_the_report_prints_ONE_value_for_the_cap_honest_margin_not_two(self):
        """The check detail and the NOTE both read `budget.margin_at_mission_speed_cap`; formatting
        the raw float in one and its own 4-dp rounding in the other printed 0.922x beside 0.921x."""
        rep = pfl.evaluate(0.5, **self.KW)
        shown = f"{rep['budget']['margin_at_mission_speed_cap']:.3f}x"
        text = pfl.format_report(rep)
        self.assertIn(shown, self._check(rep)["detail"])
        self.assertEqual(text.count("0.921x"), 2)
        self.assertNotIn("0.922x", text)

    def test_the_FAIL_line_names_the_failing_checks_and_prescribes_no_direction(self):
        """It used to say 'slow the mission, or measure a longer horizon' -- and BOTH of those can
        be the failing direction (past 47.56 m a longer horizon fails; below 0.79 m/s a slower
        mission fails). G60's family, in prose, on the line an operator acts on."""
        text = pfl.format_report(pfl.evaluate(0.5, **self.KW))
        self.assertIn(f"Failing: {self.CHECK}", text)
        self.assertNotIn("Slow the mission, or measure a longer horizon", text)


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
        code carrying two meanings.

        The last two modes are the live intrinsics WITHOUT a measured horizon. They belong here
        because `--acq-range-m` is part of the live input set, not an extra: without it the
        acquisition range falls back to the pinhole x morphology GEOMETRIC BOUND, i.e. host
        arithmetic on config prose."""
        modes_without_the_full_live_set = (
            ("--speed", "5.0"),
            ("--speed", "5.0", "--json", "/dev/null"),
            ("--sweep", "2:10:2"),
            ("--sweep", "2:10:2", "--json", "/dev/null"),
            ("--speed", "5.0", *LIVE_INTRINSICS),
            ("--speed", "5.0", *LIVE_INTRINSICS, "--json", "/dev/null"),
        )
        for mode in modes_without_the_full_live_set:
            proc = _run(*mode)
            self.assertNotEqual(proc.returncode, pfl.EXIT_PASS_BOOKABLE, msg=f"{mode}: {proc.stdout}")
            self.assertEqual(proc.returncode, pfl.EXIT_PASS_NOT_BOOKABLE, msg=str(mode))

    def test_live_intrinsics_WITHOUT_a_measured_horizon_are_NOT_bookable(self):
        """THE MUTANT THIS CLASS DID NOT KILL (QA, 2026-09-07). `bookable` is a three-term
        conjunction and only two of the terms were pinned: deleting `and acq_range_m is not None`
        broke ZERO tests in the whole suite, and the mutant then printed `PASS and BOOKABLE at
        5 m/s -- margin 1.811x on live-measured inputs`, exit 0, on an acquisition range of
        46.80 m that no sensor ever produced -- the pinhole x morphology bound computed on the
        host from `config/depth_camera.json`. That is booking on config prose, the one thing
        ADR-019 item 6 and this tool's docstring exist to forbid.

        Six live intrinsics are NECESSARY and NOT SUFFICIENT: the horizon is a separate
        measurement (gate D3, in the render), and a run that has the camera's own numbers but not
        its own horizon is still a DESIGN check."""
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS, **LIVE_INTRINSICS_KW)
        self.assertTrue(rep["verdict"]["pass"], "the design still passes -- that is the point")
        self.assertTrue(rep["sensor"]["live_intrinsics"])
        self.assertFalse(rep["verdict"]["bookable"])
        self.assertEqual(rep["verdict"]["exit_code"], pfl.EXIT_PASS_NOT_BOOKABLE)
        self.assertIn("measured render horizon", rep["verdict"]["why_not_bookable"])
        # ...and it names THE cause, not A cause (QA finding G131). This path used to print
        # "inputs are config-sourced", which sends the operator back to `ros2 topic echo
        # camera_info` -- the one input they already have -- instead of to gate D3.
        why = rep["verdict"]["why_not_bookable"]
        self.assertIn("live intrinsics given but no --acq-range-m (D3)", why)
        self.assertNotIn("config-sourced", why)
        self.assertIn("D3", _run("--speed", str(RECOMMENDED_SPEED_MPS), *LIVE_INTRINSICS).stdout)
        # The genuinely config-sourced run keeps the sentence that is true of IT.
        config_why = pfl.evaluate(RECOMMENDED_SPEED_MPS)["verdict"]["why_not_bookable"]
        self.assertIn("config-sourced", config_why)
        # ...and the range it would have booked on is the geometric bound, named as one.
        self.assertAlmostEqual(rep["sensor"]["acquisition_range_m"],
                               rep["sensor"]["geometric_acquisition_range_m"], places=6)
        proc = _run("--speed", str(RECOMMENDED_SPEED_MPS), *LIVE_INTRINSICS)
        self.assertEqual(proc.returncode, pfl.EXIT_PASS_NOT_BOOKABLE, msg=proc.stdout)
        self.assertIn("NOT BOOKABLE", proc.stdout)
        self.assertNotIn("PASS and BOOKABLE", proc.stdout)

    def test_a_sweep_NEVER_exits_zero_however_live_its_inputs(self):
        """A sweep CHOOSES a mission speed; a single --speed run AUTHORISES one (gate D4). The
        earlier rule -- exit 0 iff every swept row passed on live inputs -- still made exit 0
        reachable from a mode whose printed output is a table of speeds, i.e. an authorisation
        whose subject is a range. `--sweep 4:5:1 <live>` exited 0 while saying nothing about which
        of the two speeds the flight would be flown at."""
        for spec in ("2:6:2", "4:5:1", "5:5:1", "2:10:2", "20:24:2"):
            proc = _run("--sweep", spec, *LIVE)
            self.assertNotEqual(proc.returncode, pfl.EXIT_PASS_BOOKABLE,
                                msg=f"--sweep {spec}: {proc.stdout}")
            self.assertIn(proc.returncode, (pfl.EXIT_FAIL, pfl.EXIT_PASS_NOT_BOOKABLE), msg=spec)

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
        """13.05, not the 13.00 published until 2026-09-07: the threat band has to fit above AND
        below the optical axis, and a 480-row frame has 240 rows above cy=240 but only 239 below
        it. Verdict-invariant (the band is compared against a 46 m acquisition range) and
        conservative in the honest direction, but the number is quoted in ADR-020 and in
        config/depth_camera.json's tilt_rejected_note, so it is pinned here."""
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS)
        self.assertAlmostEqual(rep["sensor"]["geometric_acquisition_range_m"], 46.800, places=2)
        # 13.0545 m exactly; the artifact rounds to 3 dp, and the published figure is 13.05 m.
        self.assertAlmostEqual(rep["sensor"]["band_covered_from_m"], 13.055, places=6)

    def test_the_D4_row_the_runbook_publishes_is_reproducible_from_the_live_numbers(self):
        """FORWARD_DEPTH_SENSOR.md section 3's result table, recomputed rather than transcribed. If
        any of these move, that table and ADR-020 am. 1 are wrong, not this test."""
        rep = pfl.evaluate(RECOMMENDED_SPEED_MPS,
                           **dict(D3_KW, acq_range_m=D3_BOOKABLE_M,
                                  acq_optical_prefix_m=D3_OPTICAL_PREFIX_M))
        self.assertAlmostEqual(rep["budget"]["margin"], 1.780, places=3)
        self.assertAlmostEqual(rep["budget"]["available_lead_s"], 3.832, places=3)
        self.assertAlmostEqual(rep["budget"]["need_s"], 2.152, places=3)
        self.assertAlmostEqual(rep["budget"]["required_horizon_m"], 33.59, places=2)
        self.assertAlmostEqual(rep["budget"]["acq_range_headroom_frac"], 0.270, places=3)
        self.assertAlmostEqual(rep["sensor"]["clip_far_at_frame_corner_m"], 47.558, places=3)
        self.assertTrue(rep["verdict"]["bookable"])


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

    def test_validate_report_recurses_INTO_the_sweep_rows(self):
        """A sweep's rows ARE booking-gate reports -- same schema, same fields -- and the 1.2 clamp
        fields are the ones a reader takes absence for `false` on. Checking only that the row list
        was non-empty let a sweep carrying rows with no clamp fields at all validate clean, which
        is the exact hole schema 1.2 was cut to close for single-speed artifacts."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sweep.json"
            _run("--sweep", "2:6:2", "--json", str(out))
            rep = json.loads(out.read_text())
        pfl.validate_report(rep)
        for dropped in ("acquisition_clamped_from_optical_prefix", "fy_px", "image_height_px"):
            maimed = json.loads(json.dumps(rep))
            del maimed["sweep"][1]["sensor"][dropped]
            with self.assertRaises(ValueError, msg=dropped) as caught:
                pfl.validate_report(maimed)
            self.assertIn("sweep row", str(caught.exception), msg=dropped)
        # ...and a row whose verdict is not a verdict
        maimed = json.loads(json.dumps(rep))
        maimed["sweep"][0]["verdict"]["pass"] = "yes"
        with self.assertRaises(ValueError):
            pfl.validate_report(maimed)

    def test_the_D4_artifact_is_written_readable_and_says_it_was_clamped(self):
        """End to end, exactly as gate D4 runs it: the file that authorises the dodge flight must
        read back, validate, carry `bookable: true`, and say on its face that its 46.0 m horizon
        was clamped from a 58.0 m optical prefix."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "booking_gate_D4.json"
            proc = _run("--speed", "5.0", *D3_LIVE, "--acq-range-m", str(D3_BOOKABLE_M),
                        "--acq-optical-prefix-m", str(D3_OPTICAL_PREFIX_M), "--json", str(out))
            self.assertEqual(proc.returncode, pfl.EXIT_PASS_BOOKABLE, msg=proc.stdout + proc.stderr)
            rep = pfl.validate_report(json.loads(out.read_text()))
            self.assertEqual(rep["schema_version"], "1.3")
            self.assertIs(rep["verdict"]["bookable"], True)
            s = rep["sensor"]
            self.assertIs(s["acquisition_clamped_from_optical_prefix"], True)
            self.assertEqual(s["acquisition_optical_prefix_m"], D3_OPTICAL_PREFIX_M)
            self.assertEqual(s["acquisition_range_m"], D3_BOOKABLE_M)
            self.assertEqual((s["fx_px"], s["fy_px"]), (round(D3_FX, 4), round(D3_FY, 4)))
            self.assertTrue(all("live" in s[k] for k in
                                ("fx_source", "fy_source", "cx_source", "cy_source",
                                 "image_size_source", "acquisition_range_source")))
            self.assertIn("CLAMPED", proc.stdout)


class TestSweep(unittest.TestCase):
    def test_sweep_on_config_inputs_is_pass_but_NOT_bookable(self):
        proc = _run("--sweep", "2:10:2")
        self.assertEqual(proc.returncode, pfl.EXIT_PASS_NOT_BOOKABLE)
        for v in ("2.00", "4.00", "6.00", "8.00", "10.00"):
            self.assertIn(v, proc.stdout)
        self.assertIn("fastest passing mission speed", proc.stdout)
        self.assertIn("authorises no flight", proc.stdout)
        self.assertIn("config/depth_camera.json", proc.stdout)   # ...for a second reason

    def test_no_sweep_row_is_ever_LABELLED_bookable(self):
        """The row label is what an operator reads off the table, so it must not say the one word
        the runbooks equate with 'book the flight'. PASS*, with the footnote, is the honest label
        for both input sources: a row is a candidate speed, never an authorisation."""
        for args in (("--sweep", "2:6:2"), ("--sweep", "2:6:2") + LIVE):
            out = _run(*args).stdout
            self.assertIn("PASS*", out, msg=str(args))
            self.assertNotIn("  BOOKABLE", out, msg=f"{args}: a row claimed bookability")
            self.assertIn("single --speed run", out, msg=str(args))

    def test_sweep_with_live_inputs_exits_three_not_zero(self):
        proc = _run("--sweep", "2:6:2", *LIVE)
        self.assertEqual(proc.returncode, pfl.EXIT_PASS_NOT_BOOKABLE, msg=proc.stdout)
        self.assertIn("authorises", proc.stdout)

    def test_every_row_of_a_live_sweep_records_that_it_authorises_nothing(self):
        """Not only the top-level verdict: a reader who greps the rows of a sweep artifact for
        `bookable` must not find a true there either. The artifact is the thing that outlives the
        terminal."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "sweep_live.json"
            _run("--sweep", "2:6:2", *LIVE, "--json", str(out))
            rep = pfl.validate_report(json.loads(out.read_text()))
        self.assertIs(rep["verdict"]["bookable"], False)
        for row in rep["sweep"]:
            self.assertIs(row["verdict"]["bookable"], False,
                          msg=str(row["encounter"]["mission_speed_mps"]))
            self.assertNotEqual(row["verdict"]["exit_code"], pfl.EXIT_PASS_BOOKABLE)
            self.assertIn("authorises", row["verdict"]["why_not_bookable"])

    def test_a_live_sweep_with_ANY_failing_row_says_which_and_still_exits_three(self):
        proc = _run("--sweep", "2:10:2", *LIVE)   # 8 and 10 m/s FAIL on this config
        self.assertEqual(proc.returncode, pfl.EXIT_PASS_NOT_BOOKABLE)
        self.assertIn("FAIL", proc.stdout)
        self.assertIn("single --speed run", proc.stdout)

    def test_sweep_fails_when_nothing_passes(self):
        proc = _run("--sweep", "20:24:2", *LIVE)
        self.assertEqual(proc.returncode, pfl.EXIT_FAIL)
        self.assertIn("NO mission speed in this range passes", proc.stdout)

    def test_the_footer_does_not_MISSTATE_the_exit_code_it_is_about_to_return(self):
        """QA, 2026-09-07: the footer read 'exits 3 whatever the rows say' -- and printed that
        sentence verbatim on the run that exits 1. A gate misstating its own exit code, in the
        tool that exists because one code carrying two meanings cost the 2026-08-25 booking.
        The unconditional property is 'never 0'; the exit itself is conditional on any_pass."""
        passing = _run("--sweep", "2:10:1", *LIVE)
        failing = _run("--sweep", "20:30:5", *LIVE)
        self.assertEqual(passing.returncode, pfl.EXIT_PASS_NOT_BOOKABLE, msg=passing.stdout)
        self.assertEqual(failing.returncode, pfl.EXIT_FAIL, msg=failing.stdout)
        for proc in (passing, failing):
            self.assertNotIn("whatever the rows say", proc.stdout)
            self.assertIn("CANNOT EXIT 0", proc.stdout)
            self.assertIn("3 when some row passes / 1 when none does", proc.stdout)

    def test_sweep_spec_is_validated(self):
        for bad in ("2:10", "10:2:1", "2:10:0", "a:b:c"):
            self.assertEqual(_run("--sweep", bad).returncode, 2)

    def test_sweep_endpoints_are_inclusive(self):
        self.assertEqual(pfl._parse_sweep("2:4:0.5"), [2.0, 2.5, 3.0, 3.5, 4.0])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
