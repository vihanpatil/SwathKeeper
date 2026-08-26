"""The avoidance node's per-tick decision path: ONE CLOCK, a live staleness gate, and the run block
the flight-log gate scores.

Why this file exists at all. Until 2026-08-24 `avoidance_node._on_tick` built
`t = get_clock().now() - t0` (elapsed wall seconds since node start) and called `decide_multi` with
NO `now_s`, so `PolicyParams.max_detection_age_s` -- ADR-009 rule 1, the gate that makes a stale
detection ABSENT rather than a phantom threat -- could not evaluate at all. The obvious fix (pass
that `t`) is WORSE THAN THE BUG: NDVI frames are stamped in absolute Gazebo sim seconds, so
`age = elapsed - gz_absolute` is large and NEGATIVE, every detection reads fresh forever, and
nothing anywhere prints a warning, because unstamped detections already fail OPEN by design.

So the mismatch is tested directly, from both sides:
  * drive the loop with an elapsed clock against absolute stamps -> EVERY tick must be counted as a
    clock-domain violation (and the flight log must therefore be un-flyable), and
  * prove the damage the tripwire is protecting against: the same detection that the correct clock
    ages out as stale is scored FRESH under the wrong one, and the vehicle dodges a bird that is no
    longer there.
A test that only checked "the gate drops stale detections" would pass just as happily with the
clocks crossed, which is exactly how this class of bug survives.

Stdlib-only on purpose (no numpy/scipy): this is the same bare-interpreter tier as the policy and
executor it drives. The numpy/scipy half of the seam -- the real detector, the apparent-size ray --
is `test_detection_seam.py`.
"""
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning.avoidance_executor import AvoidanceExecutor, SimulatedVehicleSink  # noqa: E402
from fieldguard_planning.avoidance_node import (  # noqa: E402
    CLOCK_DOMAIN_BOUND_S,
    DEMO_BIRD_ENU,
    DEMO_SOURCE_TAG,
    RUN_SCHEMA_VERSION,
    AvoidanceLoop,
    DetectorConfig,
    build_run_block,
    detection_source_name,
    detector_log_block,
    parse_args,
    proximity_bird_source,
    scripted_bird_source,
)
from fieldguard_planning.avoidance_policy import AvoidancePolicy, PolicyParams, _params_dict  # noqa: E402
from fieldguard_planning.avoidance_types import Decision, Detection, DroneState  # noqa: E402
from fieldguard_planning import avoidance_node  # noqa: E402
from fieldguard_planning.coverage import (  # noqa: E402
    build_grid, derive_swath_half_width_m, load_field_polygon,
)
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402

NODE_SRC = (REPO_ROOT / "src" / "fieldguard_planning" / "avoidance_node.py").read_text()
# The ADR-009 staleness bound has exactly ONE home: the policy default. Read back from it here so
# this file follows the knob instead of pinning a second literal beside it.
MAX_DETECTION_AGE_S = PolicyParams().max_detection_age_s

# A geometry the real policy accepts: the drone mid-field on a clear lane, the bird 4 m east of it
# at cruise altitude (inside the 12 m x +/-6 m threat cylinder), so the away-vector points west into
# open field. Verified against the real geofence in `test_the_fixture_geometry_really_diverts`.
DRONE_ENU = (30.0, 30.0, 15.0)
BIRD_ENU = (34.0, 30.0, 15.0)
GZ_T0 = 1200.0          # a plausible absolute Gazebo sim time: flights start birds ~110 s in
TICK_S = 1.0 / 5.0


def _drone(pos=DRONE_ENU, wp=3):
    return DroneState(position_enu=pos, heading_rad=0.0, current_wp_index=wp)


def _loop(detection_source=None, warn=None, **policy_kwargs):
    """A loop wired to the REAL policy/executor/geofence/grid -- no doubles below the seam, so a
    decision here is the decision the vehicle would make."""
    polygon = load_field_polygon()
    geofence = GeofenceMap.from_file()
    params = {"cruise_alt_m": 15.0}
    params.update(policy_kwargs)
    policy = AvoidancePolicy(field_polygon=polygon, **params)
    executor = AvoidanceExecutor(geofence, build_grid(polygon), SimulatedVehicleSink(),
                                 swath_half_width_m=7.5, alt_bounds=(2.0, 30.0))
    return AvoidanceLoop(policy, geofence, executor, detection_source, warn=warn)


def _bird_source(stamp_of_tick):
    """A detection source that stamps its bird with `stamp_of_tick(i)` on the i-th call -- the knob
    the clock-domain tests turn."""
    state = {"i": 0}

    def src(t, drone):
        i = state["i"]
        state["i"] += 1
        return [Detection(BIRD_ENU, frame_id=i, track_id="b0", source="ndvi_blob",
                          stamp_s=stamp_of_tick(i))]
    return src


class TestTheFixtureItself(unittest.TestCase):
    """If the fixture geometry stopped producing a DIVERT, every 'the gate suppressed the dodge'
    assertion below would pass for the wrong reason."""

    def test_the_fixture_geometry_really_diverts(self):
        loop = _loop(_bird_source(lambda i: GZ_T0 + i * TICK_S))
        m = loop.tick(_drone(), GZ_T0, GZ_T0)
        self.assertIs(m.decision, Decision.DIVERT)
        self.assertIsNotNone(m.setpoint_enu)


class TestClockDomainMismatchIsLoud(unittest.TestCase):
    """The absolute-vs-elapsed inversion must be impossible to fly through quietly."""

    def test_absolute_stamps_against_an_elapsed_clock_violate_on_every_tick(self):
        warnings = []
        loop = _loop(_bird_source(lambda i: GZ_T0 + i * TICK_S), warn=warnings.append)
        n_ticks = 12
        for i in range(n_ticks):
            loop.tick(_drone(), now_s=i * TICK_S, source_t=i * TICK_S)  # elapsed-since-start: WRONG
        self.assertEqual(loop.clock_domain_violations, n_ticks)
        # Warned on the 1st and the 10th -- loud once, then not a log flood.
        self.assertEqual(len(warnings), 2)
        self.assertIn("CLOCK DOMAIN VIOLATION", warnings[0])
        self.assertIn("FUTURE", warnings[0])

    def test_the_same_flight_on_one_clock_has_zero_violations(self):
        loop = _loop(_bird_source(lambda i: GZ_T0 + i * TICK_S))
        for i in range(12):
            loop.tick(_drone(), now_s=GZ_T0 + i * TICK_S, source_t=GZ_T0 + i * TICK_S)
        self.assertEqual(loop.clock_domain_violations, 0)

    def test_the_inversion_scores_a_long_dead_detection_as_fresh(self):
        """THE DAMAGE, not just the symptom. One detection stamped 60 s ago on the gz clock:
        * on the correct clock the staleness gate makes it ABSENT -> PROCEED;
        * with an elapsed `now_s` the age goes NEGATIVE, it reads fresh, and the vehicle takes
          control and dodges a bird that left a minute ago.
        Both halves are asserted so the gate cannot be 'fixed' by disabling it."""
        stale_stamp = GZ_T0 - 60.0

        right = _loop(_bird_source(lambda i: stale_stamp))
        m_right = right.tick(_drone(), now_s=GZ_T0, source_t=GZ_T0)
        self.assertIs(m_right.decision, Decision.PROCEED)
        self.assertEqual(m_right.debug["n_stale_dropped"], 1)
        self.assertIn("stale", m_right.reason)

        wrong = _loop(_bird_source(lambda i: stale_stamp))
        m_wrong = wrong.tick(_drone(), now_s=0.2, source_t=0.2)   # elapsed clock
        self.assertIs(m_wrong.decision, Decision.DIVERT)          # <- the bug, reproduced
        self.assertNotIn("n_stale_dropped", m_wrong.debug)
        self.assertEqual(wrong.clock_domain_violations, 1)        # <- and caught

    def test_the_bound_is_a_bound_not_a_sign_test(self):
        """A stamp a hair in the future is normal jitter (measured max frame age 0.156 s, and that
        is the other sign); half a second is a different clock."""
        at_bound = _loop(_bird_source(lambda i: GZ_T0 + CLOCK_DOMAIN_BOUND_S))
        at_bound.tick(_drone(), now_s=GZ_T0, source_t=GZ_T0)
        self.assertEqual(at_bound.clock_domain_violations, 0)

        past_bound = _loop(_bird_source(lambda i: GZ_T0 + CLOCK_DOMAIN_BOUND_S + 1e-6))
        past_bound.tick(_drone(), now_s=GZ_T0, source_t=GZ_T0)
        self.assertEqual(past_bound.clock_domain_violations, 1)

    def test_an_ordinary_frame_age_is_never_a_violation(self):
        """The adopted clip's own frame ages: min 0.061 / p50 0.143 / max 0.156 s (n=1256)."""
        for age in (0.061, 0.143, 0.156, 0.5, 0.99):
            loop = _loop(_bird_source(lambda i, a=age: GZ_T0 - a))
            loop.tick(_drone(), now_s=GZ_T0, source_t=GZ_T0)
            self.assertEqual(loop.clock_domain_violations, 0, age)

    def test_unstamped_detections_can_never_violate(self):
        """The --demo bird carries no stamp; it must not be able to trip the tripwire."""
        loop = _loop(lambda t, d: [Detection(BIRD_ENU, frame_id=0, source=DEMO_SOURCE_TAG)])
        for i in range(20):
            loop.tick(_drone(), now_s=GZ_T0 + i * TICK_S, source_t=GZ_T0 + i * TICK_S)
        self.assertEqual(loop.clock_domain_violations, 0)

    def test_no_clock_reading_yet_is_counted_not_guessed(self):
        loop = _loop(_bird_source(lambda i: GZ_T0))
        loop.tick(_drone(), now_s=None, source_t=3.0)
        self.assertEqual(loop.ticks_without_clock, 1)
        self.assertEqual(loop.clock_domain_violations, 0)   # nothing to compare against
        self.assertEqual(loop.tick_stamp_sim_s, [None])     # null, never an invented number


class TestStalenessGateIsLive(unittest.TestCase):
    def test_the_gate_is_armed_by_the_policy_and_the_node_does_not_own_a_second_copy(self):
        """ONE HOME for the ADR-009 bound (2026-08-24). It used to be `avoidance_node`'s own
        constant while `PolicyParams.max_detection_age_s` stayed None -- one knob, two homes, and
        the flight-log gate's upper bound (`gate_staleness`) was dead code as a result: a flight
        could record a 3600 s tolerance and be certified as current behaviour. The node must not
        declare or pass it; a node-side literal reads identically in every artifact whose detections
        happen to be fresh."""
        self.assertEqual(PolicyParams().max_detection_age_s, 1.0)
        # Assignment-shaped, not bare-name: the node may NAME the knob in a comment (and does), it
        # may not declare or pass one.
        self.assertNotIn("MAX_DETECTION_AGE_S =", NODE_SRC)
        self.assertNotIn("max_detection_age_s=", NODE_SRC)
        self.assertIn("now_s=now_s", NODE_SRC)   # ...and actually passes a now_s to the policy

    def test_a_stale_detection_is_absent_not_merely_ignored(self):
        loop = _loop(_bird_source(lambda i: GZ_T0 - (MAX_DETECTION_AGE_S + 0.001)))
        m = loop.tick(_drone(), now_s=GZ_T0, source_t=GZ_T0)
        self.assertIs(m.decision, Decision.PROCEED)
        self.assertEqual(m.debug["n_stale_dropped"], 1)
        self.assertEqual(m.debug["max_detection_age_s"], MAX_DETECTION_AGE_S)

    def test_a_detection_exactly_at_the_age_bound_is_still_fresh(self):
        loop = _loop(_bird_source(lambda i: GZ_T0 - MAX_DETECTION_AGE_S))
        self.assertIs(loop.tick(_drone(), GZ_T0, GZ_T0).decision, Decision.DIVERT)

    def test_unstamped_detections_fail_OPEN_with_the_gate_armed(self):
        """ADR-009 rule 1's other half: dropping unstamped detections would silently disable
        avoidance for the --demo bird and every scripted scenario."""
        loop = _loop(lambda t, d: [Detection(BIRD_ENU, frame_id=0, source=DEMO_SOURCE_TAG)])
        m = loop.tick(_drone(), now_s=GZ_T0, source_t=GZ_T0)
        self.assertIs(m.decision, Decision.DIVERT)
        self.assertNotIn("n_stale_dropped", m.debug)

    def test_without_a_clock_the_gate_fails_open_rather_than_dropping_everything(self):
        """No gz reading yet: an age cannot be computed, so a stamped detection must still act.
        Fail OPEN on missing data, fail SAFE only on provably stale data."""
        loop = _loop(_bird_source(lambda i: GZ_T0 - 3600.0))
        m = loop.tick(_drone(), now_s=None, source_t=1.0)
        self.assertIs(m.decision, Decision.DIVERT)

    def test_a_dead_clock_stream_expires_detections_instead_of_flipping_sign(self):
        """If the gz stream dies, `now_s` freezes at its last value while frames keep arriving with
        newer stamps -- so detections read as FUTURE-stamped, not as fresh-forever. The tripwire
        fires and the flight is scored INVALID rather than silently trusted."""
        frozen = GZ_T0
        loop = _loop(_bird_source(lambda i: GZ_T0 + i * TICK_S))
        for i in range(10):
            loop.tick(_drone(), now_s=frozen, source_t=frozen)
        # The first few ticks are within the bound (normal jitter); the later ones are not.
        self.assertGreater(loop.clock_domain_violations, 0)


class TestTickStampAxis(unittest.TestCase):
    """`run.tick_stamp_sim_s` is the flight log's first time axis. The gate asserts it is the same
    length as `flown_path_enu`; that identity must hold across every decision branch."""

    def test_one_stamp_per_flown_position_across_proceed_divert_and_hold(self):
        dets = {"on": False}

        def src(t, drone):
            return ([Detection(BIRD_ENU, frame_id=0, track_id="b0", stamp_s=t)]
                    if dets["on"] else [])
        loop = _loop(src)
        decisions = []
        for i in range(9):
            dets["on"] = 3 <= i < 7
            decisions.append(loop.tick(_drone(), GZ_T0 + i * TICK_S, GZ_T0 + i * TICK_S).decision)
        self.assertIn(Decision.PROCEED, decisions)
        self.assertIn(Decision.DIVERT, decisions)
        self.assertEqual(len(loop.tick_stamp_sim_s), 9)
        self.assertEqual(len(loop.tick_stamp_sim_s), len(loop.executor.flown_path))

    def test_a_boxed_in_hold_still_records_exactly_one_stamp(self):
        """HOLD is the branch that takes a different path through the executor; if it recorded a
        different number of positions the axis would silently shear. Forced with a clearance bar no
        10 m dodge can satisfy -- 'boxed in' is the policy's business, this test is the executor's."""
        loop = _loop(_bird_source(lambda i: GZ_T0), min_bird_clearance_m=25.0)
        m = loop.tick(_drone(), GZ_T0, GZ_T0)
        self.assertIs(m.decision, Decision.HOLD)
        self.assertEqual(len(loop.tick_stamp_sim_s), len(loop.executor.flown_path))


class TestRunBlock(unittest.TestCase):
    """`log["run"]` is the contract scripts/check_live_flight_log.py branches on."""

    def _block(self, loop, readings=42, detector=None):
        return build_run_block(policy_params=_params_dict(loop.policy.params),
                               clock=loop.clock_block(readings),
                               tick_stamp_sim_s=loop.tick_stamp_sim_s,
                               detector=detector or detector_log_block(None, None))

    def test_it_is_schema_2_and_json_serialisable(self):
        loop = _loop(_bird_source(lambda i: GZ_T0))
        loop.tick(_drone(), GZ_T0, GZ_T0)
        block = self._block(loop)
        self.assertEqual(block["schema_version"], RUN_SCHEMA_VERSION)
        self.assertEqual(RUN_SCHEMA_VERSION, 2)
        round_tripped = json.loads(json.dumps(block))
        self.assertEqual(round_tripped, block)

    def test_it_carries_every_bar_the_gate_reads_from_policy_params(self):
        """R2/R3 assertions compare the flown params against `PolicyParams()`; the fields have to
        be there, spelled the same way `_params_dict` spells them in every maneuver's debug."""
        loop = _loop()
        p = self._block(loop)["policy_params"]
        for key in ("lateral_tree_margin_m", "degenerate_range_m", "min_bird_clearance_m",
                    "vertical_threat_m", "threat_radius_m", "max_detection_age_s"):
            self.assertIn(key, p)
        self.assertEqual(p["lateral_tree_margin_m"], PolicyParams().lateral_tree_margin_m)
        self.assertEqual(p["degenerate_range_m"], PolicyParams().degenerate_range_m)
        self.assertEqual(p["max_detection_age_s"], MAX_DETECTION_AGE_S)

    def test_the_clock_block_names_its_own_source(self):
        loop = _loop()
        loop.tick(_drone(), GZ_T0, GZ_T0)
        streamed = loop.clock_block(readings=350)
        self.assertEqual(streamed["source"], "gz_clock_stream")
        self.assertEqual(streamed["readings"], 350)
        self.assertEqual(streamed["violations"], 0)
        self.assertEqual(streamed["ticks_total"], 1)
        self.assertEqual(streamed["violation_bound_s"], CLOCK_DOMAIN_BOUND_S)

    def test_a_flight_with_no_clock_reading_says_so_instead_of_claiming_gz(self):
        loop = _loop()
        loop.tick(_drone(), None, 1.0)
        block = loop.clock_block(readings=0)
        self.assertEqual(block["source"], "node_elapsed_fallback")
        self.assertEqual(block["ticks_without_clock"], 1)

    def test_violations_reach_the_artifact(self):
        loop = _loop(_bird_source(lambda i: GZ_T0))
        loop.tick(_drone(), now_s=0.2, source_t=0.2)
        self.assertEqual(self._block(loop)["clock"]["violations"], 1)

    def test_stamp_axis_and_flown_path_agree_in_the_artifact(self):
        loop = _loop(_bird_source(lambda i: GZ_T0 + i * TICK_S))
        for i in range(5):
            loop.tick(_drone(), GZ_T0 + i * TICK_S, GZ_T0 + i * TICK_S)
        loop.executor.finalize()
        log = loop.executor.flight_log("t", seed=0, cell_size_m=2.5)
        log["run"] = self._block(loop)
        self.assertEqual(len(log["run"]["tick_stamp_sim_s"]), len(log["flown_path_enu"]))


class TestDetectorLogBlock(unittest.TestCase):
    class _FakeIntr:
        width_px, height_px, fx, fy, cx, cy = 640, 480, 520.0, 520.0, 320.0, 240.0

    class _FakeSource:
        """Duck-typed stand-in for `NdviDetectionSource` -- the block reads values back from the
        source that RAN, so this test needs no numpy."""
        thresh, min_area, max_area, radius_prior_m = -0.61, 6, 5000, 0.15

        def __init__(self, intr=None):
            self.intr = intr

        def on_frame(self, *a, **k):
            return []

        def counters(self):
            return {"ndvi_msgs_received": 7}

    def test_no_source_is_an_observation_run(self):
        block = detector_log_block(None, None)
        self.assertEqual(block["source"], "none")
        self.assertEqual(detection_source_name(None), "none")

    def test_a_scripted_source_stops_claiming_to_be_an_ndvi_blob(self):
        src = proximity_bird_source(DEMO_BIRD_ENU)
        self.assertEqual(detection_source_name(src), DEMO_SOURCE_TAG)
        block = detector_log_block(src, None)
        self.assertEqual(block["source"], "demo_virtual")
        self.assertIn("ground truth", block["note"])

    def test_the_real_detector_records_threshold_provenance_and_provisionality(self):
        cfg = DetectorConfig(thresh=-0.61, thresh_provenance="node default REAL_RENDER_THRESH",
                             thresh_provisional=True, min_area=6, max_area=5000)
        src = self._FakeSource(self._FakeIntr())
        block = detector_log_block(src, cfg)
        self.assertEqual(block["source"], "ndvi_blob")
        self.assertEqual(block["module"], "fieldguard_planning.ndvi_detect")
        self.assertEqual(block["thresh"], -0.61)
        self.assertTrue(block["thresh_provisional"])
        self.assertIn("REAL_RENDER_THRESH", block["thresh_provenance"])
        self.assertEqual(block["radius_prior_m"], 0.15)
        self.assertIn("apparent_size_ray", block["range_model"])
        self.assertIn("never", block["range_model"])
        self.assertEqual(block["intrinsics"]["fx"], 520.0)
        self.assertIn("live /fg/ndvi/camera_info", block["intrinsics"]["provenance"])
        self.assertEqual(block["counters"]["ndvi_msgs_received"], 7)

    def test_values_come_from_the_source_that_ran_not_the_cli_intent(self):
        """If the two ever disagree, the artifact must state what the DETECTOR used."""
        cfg = DetectorConfig(thresh=0.05, thresh_provenance="stale cli", thresh_provisional=False,
                             min_area=1, max_area=2)
        block = detector_log_block(self._FakeSource(), cfg)
        self.assertEqual(block["thresh"], -0.61)
        self.assertEqual(block["min_area"], 6)

    def test_intrinsics_are_null_before_camera_info_rather_than_config_values(self):
        block = detector_log_block(self._FakeSource(intr=None), None)
        self.assertIsNone(block["intrinsics"])


class TestCli(unittest.TestCase):
    def test_detect_and_demo_are_mutually_exclusive(self):
        with self.assertRaises(SystemExit) as ctx:
            parse_args(["--detect", "--demo"])
        self.assertEqual(ctx.exception.code, 2)

    def test_detector_knobs_default_to_none_so_ndvi_detect_owns_the_values(self):
        args = parse_args([])
        self.assertIsNone(args.ndvi_thresh)
        self.assertIsNone(args.min_area)
        self.assertIsNone(args.max_area)
        self.assertFalse(args.detect)
        self.assertFalse(args.demo)

    def test_the_threshold_is_a_cli_arg_not_a_ros_parameter(self):
        """One configuration mechanism per repo: nothing in src/ declares a ROS 2 parameter, and
        the number that matters is the one recorded in the artifact."""
        self.assertNotIn("declare_parameter(", NODE_SRC)

    def test_explicit_values_parse(self):
        args = parse_args(["--detect", "--ndvi-thresh", "-0.5", "--min-area", "9",
                           "--max-area", "1000"])
        self.assertTrue(args.detect)
        self.assertEqual(args.ndvi_thresh, -0.5)
        self.assertEqual(args.min_area, 9)
        self.assertEqual(args.max_area, 1000)


class TestDemoSourcesAreHonestAboutBeingVirtual(unittest.TestCase):
    """A virtual bird claimed `source: "ndvi_blob"` in every log ever flown (the `Detection` field
    default). The flight-log gate now branches on this tag -- a demo bird's logged position IS exact
    ground truth, so it is gated differently from a monocular estimate -- so the tag has to be true."""

    def test_proximity_source(self):
        dets = proximity_bird_source(DEMO_BIRD_ENU, trigger_radius_m=15.0)(1.0, _drone((30.0, 35.0, 15.0)))
        self.assertEqual([d.source for d in dets], [DEMO_SOURCE_TAG])
        self.assertIsNone(dets[0].stamp_s)   # unstamped -> the gate fails OPEN for it

    def test_scripted_source(self):
        dets = scripted_bird_source([("b0", BIRD_ENU, 0.0, 5.0)])(1.0, None)
        self.assertEqual([d.source for d in dets], [DEMO_SOURCE_TAG])


class TestTheNodeFliesTheCameraDerivedSwath(unittest.TestCase):
    """What `build_node` actually hands the executor -- not what `coverage` computes for itself.

    QA M1 (2026-08-25): mutating `derive_swath_half_width_m(CRUISE_ALT_M)` in the node back to the
    old `7.5` literal broke ZERO tests, because the swath tests pin
    `coverage.DEFAULT_SWATH_HALF_WIDTH_M`, which the node never reads. `build_node` cannot be called
    here (rclpy, numpy, ros messages), so the expression the node flies is located in its AST and
    EVALUATED -- a grep would pass on `derive_swath_half_width_m(20.0)`."""

    def _executor_call(self):
        import ast
        for node in ast.walk(ast.parse(NODE_SRC)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "AvoidanceExecutor"):
                return node
        self.fail("build_node no longer constructs an AvoidanceExecutor")

    def _flown_swath_expr(self):
        """The expression the node passes as `swath_half_width_m`, resolved through one level of
        local variable, exactly as the source reads."""
        import ast
        kw = {k.arg: k.value for k in self._executor_call().keywords}
        self.assertIn("swath_half_width_m", kw, "the executor is built without an explicit swath")
        expr = kw["swath_half_width_m"]
        if isinstance(expr, ast.Name):                       # `swath_half_width_m=swath_half_m`
            assigns = [n for n in ast.walk(ast.parse(NODE_SRC))
                       if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == expr.id for t in n.targets)]
            self.assertEqual(len(assigns), 1, f"{expr.id} is assigned in more than one place")
            expr = assigns[0].value
        return expr

    def test_the_value_handed_to_the_executor_is_the_camera_derived_one(self):
        import ast
        flown = eval(compile(ast.Expression(self._flown_swath_expr()), "<avoidance_node>", "eval"),
                     {"derive_swath_half_width_m": derive_swath_half_width_m,
                      "CRUISE_ALT_M": avoidance_node.CRUISE_ALT_M})
        self.assertAlmostEqual(flown, derive_swath_half_width_m(avoidance_node.CRUISE_ALT_M),
                               places=9)
        self.assertAlmostEqual(flown, 6.886077, places=5)    # and it is the real camera's number
        self.assertNotEqual(flown, 7.5, "the node is back on the lane-spacing/2 assumption")

    def test_the_nodes_cruise_altitude_matches_the_altitude_the_mission_was_planned_at(self):
        """`CRUISE_ALT_M` and `config/field_polygon.json`'s `mission_altitude_m` are two homes for
        one number (pre-existing; cross-pinned rather than refactored). If they ever diverge, the
        node derives its swath at one altitude while the lanes were planned at another, and the
        ledger claims coverage the camera never had at the height flown."""
        import json
        planned = json.loads(
            (REPO_ROOT / "config" / "field_polygon.json").read_text())["mission_altitude_m"]
        self.assertEqual(avoidance_node.CRUISE_ALT_M, planned)
        self.assertEqual(PolicyParams().cruise_alt_m, planned)   # and the policy's dodge altitude

    def test_the_node_declares_no_swath_constant_of_its_own(self):
        """One home. A node-side literal is what the 7.5 defect was, in both of its lives."""
        self.assertNotIn("SWATH_HALF_M", NODE_SRC)

    def test_it_is_derived_at_the_altitude_the_node_actually_cruises(self):
        """A swath derived at some other altitude would be a third number: the ledger would claim
        coverage the camera never had at the height this node flies."""
        import ast
        expr = self._flown_swath_expr()
        self.assertIsInstance(expr, ast.Call)
        self.assertEqual(expr.func.id, "derive_swath_half_width_m")
        self.assertEqual([a.id for a in expr.args if isinstance(a, ast.Name)], ["CRUISE_ALT_M"])


if __name__ == "__main__":
    unittest.main()
