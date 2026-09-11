"""The DEPTH detection source, wired into `avoidance_node` behind a flag that ships OFF.

WHAT THIS FILE PINS, and why each one is here rather than trusted:

  1. **The flag ships OFF and the default is unchanged.** `--detection-source` defaults to `ndvi`,
     the default build is still `NdviDetectionSource`, and the NDVI log block's FIELD SET is
     snapshotted (in `test_avoidance_node_seam.py`, stdlib tier) so an added key fails a test rather
     than a gate six weeks later.
  2. **The flight log names the detector that RAN.** `detection_source_name` reads the source's own
     `SOURCE_TAG`; the previous `hasattr(source, "on_frame")` test is true of BOTH frame detectors,
     so a depth flight would have been logged -- and gated -- as `ndvi_blob` (DESIGN §6 item 2).
  3. **The decode is arithmetic, so it is tested as arithmetic.** `decode_depth_frame` derives every
     number from the message and refuses a stride or a payload length that disagrees, because a
     mis-strided buffer reshapes silently into a plausible depth image with every pixel in the wrong
     place -- the ADR-007 am. 5 family (a value correct under a geometry nobody checked).
  4. **Annotate, never suppress.** A detection inside a mapped tree's geofence is still EMITTED,
     carrying `static_map_hint` and a counter (depth_detect rule 9). The forward frame is full of
     mapped canopy from ~24.4 m; a filter here would delete the bird-beside-a-tree case.
  5. **One detection source per flight**, by construction: the node holds one source and subscribes
     to that source's own topic pair.

Runs on the host: numpy + scipy, no rclpy, no renderer, no Docker. Nothing here is flown -- the
claim ceiling for every number below is "sim-demonstrated, evidence-gated".
"""
import json
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from fieldguard_planning import avoidance_node as node  # noqa: E402
from fieldguard_planning import depth_detect, ndvi_detect, ndvi_georef  # noqa: E402
from fieldguard_planning.avoidance_node import (  # noqa: E402
    DetectorConfig,
    build_detection_source,
    decode_depth_frame,
    detection_source_name,
    detector_config_from_args,
    detector_log_block,
    feed_depth_frame,
    parse_args,
)
from fieldguard_planning.clip_recorder import PoseBuffer  # noqa: E402
from fieldguard_planning.depth_detect import DepthDetectionSource  # noqa: E402
from fieldguard_planning.depth_segment import (  # noqa: E402
    DEFAULT_PARAMS, DEFAULT_PARAMS_PROVENANCE, DepthSegmenter, params_with,
)
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402
from fieldguard_planning.ndvi_georef import CameraIntrinsics  # noqa: E402

NODE_SRC = (REPO_ROOT / "src" / "fieldguard_planning" / "avoidance_node.py").read_text()

# The live sensor's own numbers (ADR-020 am. 1; `config/depth_camera.json` mirrors them, and the
# node takes them from the MESSAGE either way -- this is a test fixture, not a source of truth).
W, H = 640, 480
FX = FY = 520.0058046927554
CX, CY = 320.0, 240.0
INTR = CameraIntrinsics(width_px=W, height_px=H, fx=FX, fy=FY, cx=CX, cy=CY)
IDENTITY_Q = (0.0, 0.0, 0.0, 1.0)          # (x, y, z, w): nose east, wings level
GZ_T0 = 1200.0                             # absolute Gazebo sim seconds
DRONE_ENU = (10.0, 20.0, 15.0)
TARGET_DEPTH_M = 20.0


# ------------------------------------------------------------------------------------ fixtures
def sky_frame_with_block(depth_m=TARGET_DEPTH_M, u0=317, u1=323, v0=237, v1=243):
    """A 32FC1 frame the real segmenter must fire on: sky (+inf, as gz writes beyond the far clip)
    with ONE near square. Default block is 6x6 = 36 px (above `min_area_px` 10) centred exactly on
    the principal point, so the box midpoint un-projects along the optical axis and the expected ENU
    is arithmetic anyone can check by hand."""
    frame = np.full((H, W), np.inf, dtype=np.float32)
    frame[v0:v1, u0:u1] = np.float32(depth_m)
    return frame


class _Msg:
    """A duck-typed `sensor_msgs/Image` -- the node's ROS-facing depth code is pure functions
    precisely so this is enough to drive it."""

    class _Stamp:
        def __init__(self, t):
            self.sec = int(t)
            self.nanosec = int(round((t - int(t)) * 1e9))

    class _Header:
        def __init__(self, t):
            self.stamp = _Msg._Stamp(t)
            self.frame_id = "fg_depth_mount"       # frame_ids lie on this stack; content is truth

    def __init__(self, frame, stamp_s=GZ_T0, encoding=node.DEPTH_IMAGE_ENCODING,
                 is_bigendian=0, step=None, data=None, height=None, width=None):
        self.header = _Msg._Header(stamp_s)
        self.height = int(frame.shape[0]) if height is None else height
        self.width = int(frame.shape[1]) if width is None else width
        self.encoding = encoding
        self.is_bigendian = is_bigendian
        self.step = (self.width * 4) if step is None else step
        if data is None:
            wire = frame.astype(">f4") if is_bigendian else frame.astype("<f4")
            data = wire.tobytes()
        self.data = data


def depth_source(annotator=None, intr=INTR):
    """The source the node builds, minus the geofence unless a test asks for it."""
    src = DepthDetectionSource(DepthSegmenter(DEFAULT_PARAMS),
                               min_range_m=DEFAULT_PARAMS.near_m,
                               max_range_m=DEFAULT_PARAMS.far_m,
                               static_map_annotator=annotator)
    if intr is not None:
        src.set_intrinsics(intr)
    return src


# ================================================================================================
# 1. The flag: OFF by default, and it selects ONE detector
# ================================================================================================
class TestTheFlagShipsOff(unittest.TestCase):
    def test_the_default_still_builds_the_ndvi_detector(self):
        args = parse_args(["--detect"])
        self.assertEqual(args.detection_source, node.KIND_NDVI)
        cfg = detector_config_from_args(args)
        src = build_detection_source(cfg, args.detection_source)
        self.assertIsInstance(src, ndvi_detect.NdviDetectionSource)
        self.assertEqual(detection_source_name(src), node.NDVI_SOURCE_TAG)
        self.assertIsNone(cfg.depth_params)              # the depth half stays empty on an NDVI run

    def test_the_default_is_also_what_a_bare_build_call_gives(self):
        """`build_detection_source(cfg)` is called with one argument in the committed seam tests and
        by anything else that predates the depth wiring; the default must be the NDVI arm."""
        cfg = detector_config_from_args(parse_args(["--detect"]))
        self.assertIsInstance(build_detection_source(cfg), ndvi_detect.NdviDetectionSource)

    def test_depth_builds_the_depth_source_wrapping_the_adopted_segmenter(self):
        args = parse_args(["--detect", "--detection-source", "depth"])
        cfg = detector_config_from_args(args)
        src = build_detection_source(cfg, args.detection_source)
        self.assertIsInstance(src, DepthDetectionSource)
        self.assertIsInstance(src.segmenter, DepthSegmenter)
        self.assertEqual(src.segmenter.params, DEFAULT_PARAMS)
        self.assertEqual(detection_source_name(src), node.DEPTH_SOURCE_TAG)

    def test_the_config_carries_the_adopted_params_with_their_provenance(self):
        cfg = detector_config_from_args(parse_args(["--detect", "--detection-source", "depth"]))
        self.assertIs(cfg.depth_params, DEFAULT_PARAMS)
        self.assertEqual(cfg.depth_params_provenance, DEFAULT_PARAMS_PROVENANCE)
        self.assertFalse(cfg.depth_params_provisional)   # every constant is a scored output
        self.assertIn("depth_segmenter_score_", cfg.depth_params_provenance)
        self.assertIsNone(cfg.thresh)                    # ...and no NDVI threshold it never used

    def test_the_seams_refusal_window_is_the_segmenters_clip_window_not_a_second_number(self):
        """DESIGN §1.3: the segmenter's clip window exists only to keep pixels the seam would refuse
        out of the mask. Two spellings of one number is how they drift.

        Driven with a NON-DEFAULT window, because the two values are equal by default and the
        comparison alone cannot tell a read from a copy: replacing `params.near_m/far_m` with the
        literals `0.1, 60.0` survived the equality version of this test (QA mutation M14)."""
        src = build_detection_source(
            detector_config_from_args(parse_args(["--detect", "--detection-source", "depth"])),
            node.KIND_DEPTH)
        self.assertEqual(src.min_range_m, src.segmenter.params.near_m)
        self.assertEqual(src.max_range_m, src.segmenter.params.far_m)

        odd = params_with(DEFAULT_PARAMS, near_m=0.7, far_m=41.0)
        moved = build_detection_source(DetectorConfig(depth_params=odd), node.KIND_DEPTH)
        self.assertEqual((moved.min_range_m, moved.max_range_m), (0.7, 41.0))
        self.assertEqual((moved.segmenter.params.near_m, moved.segmenter.params.far_m), (0.7, 41.0))

    def test_an_unknown_kind_refuses_rather_than_defaulting_to_something(self):
        cfg = detector_config_from_args(parse_args(["--detect"]))
        with self.assertRaises(ValueError):
            build_detection_source(cfg, "lidar")


# ================================================================================================
# 2. Exclusion -- one detection source per flight, by construction
# ================================================================================================
class TestTheTwoDetectorsAreExclusive(unittest.TestCase):
    """The orchestrator's call on DESIGN §7 Q2: `--detection-source depth` DISARMS the NDVI
    detector for that run. It is enforced structurally -- one source variable, one topic pair --
    rather than by a check that could be forgotten."""

    def test_the_topic_map_is_keyed_by_the_detectors_OWN_tags(self):
        """The node spells the two tags as literals (importing either detector module would pull
        numpy into a node that must parse `--demo` on a bare interpreter). This is the cross-pin
        that keeps the two spellings from drifting apart."""
        self.assertEqual(node.NDVI_SOURCE_TAG, ndvi_detect.SOURCE_TAG)
        self.assertEqual(node.DEPTH_SOURCE_TAG, depth_detect.SOURCE_TAG)
        self.assertEqual(sorted(node.FRAME_TOPICS),
                         sorted([ndvi_detect.SOURCE_TAG, depth_detect.SOURCE_TAG]))
        self.assertEqual(node.FRAME_TOPICS[depth_detect.SOURCE_TAG],
                         ("/fg/depth/image", "/fg/depth/camera_info"))
        self.assertEqual(node.FRAME_TOPICS[ndvi_detect.SOURCE_TAG],
                         ("/fg/ndvi/image", "/fg/ndvi/camera_info"))

    def test_each_source_selects_exactly_one_topic_pair_and_it_is_not_the_others(self):
        depth = node.FRAME_TOPICS[detection_source_name(depth_source())]
        ndvi = node.FRAME_TOPICS[node.NDVI_SOURCE_TAG]
        self.assertEqual(len(set(depth) & set(ndvi)), 0)
        self.assertNotIn(node.NDVI_IMAGE_TOPIC, depth)

    def test_the_node_subscribes_the_RESOLVED_pair_and_no_hard_wired_ndvi_topic(self):
        """`build_node` cannot be called off-sim (rclpy, ros messages), so the property is asserted
        on its source: a literal `create_subscription(Image, NDVI_IMAGE_TOPIC` would subscribe the
        NDVI band on a depth flight, which is the exact thing this wiring must make impossible."""
        self.assertNotIn("create_subscription(Image, NDVI_IMAGE_TOPIC", NODE_SRC)
        self.assertNotIn("create_subscription(Image, DEPTH_IMAGE_TOPIC", NODE_SRC)
        self.assertIn("self._frame_topics = (FRAME_TOPICS.get(", NODE_SRC)
        # ...and the DECODER is looked up by the same key as the topics, so a detector cannot get
        # the other one's wire format by falling through a default.
        self.assertIn("Image, image_topic, decoders[self._source_name]", NODE_SRC)

    def test_there_is_exactly_ONE_image_subscription_and_its_topic_is_the_RESOLVED_one(self):
        """The assertions above are substring pins, and a mutant that adds a SECOND image
        subscription spelled any other way survives them (QA mutation M4, 2026-09-07: inserting
        `create_subscription(Image, "/fg/ndvi/image", ...)` into `build_node` reddened nothing).
        This one counts the subscriptions instead of matching a spelling, which is the property --
        one detector, one band -- rather than one way of writing it. It matters more than it looks:
        `build_node` cannot be constructed off-sim, so these source pins ARE the exclusion's only
        enforcement until something flies."""
        topics = [t.strip() for t in
                  re.findall(r"create_subscription\(\s*Image\s*,\s*([^,]+),", NODE_SRC)]
        self.assertEqual(topics, ["image_topic"])
        self.assertNotIn('create_subscription(Image, "/fg/', NODE_SRC)

    def test_a_depth_run_prints_that_the_ndvi_detector_is_disarmed(self):
        """The operator must not discover it from the artifact afterwards: a depth take produces no
        ADR-003 in-air detection evidence, and that is a cost, not a footnote."""
        self.assertIn("the NDVI detector is DISARMED for this run", NODE_SRC)


# ================================================================================================
# 2b. The node refuses to fly a detector that cannot detect
# ================================================================================================
class TestItRefusesToFlyBlind(unittest.TestCase):
    """A frame detector with no `camera_info` is silent, not loud: it counts and drops every frame
    for the whole take (measured off-sim: 1200 frames in -> `dropped_no_intrinsics` 1200,
    `frames_detected_on` 0, `src(t)` empty on every tick) while the 2 s heartbeat prints the
    normal-looking `nearest_bird=none in view`. Nothing else caught it -- `check_render_alive.py`
    probes the two IMAGE topics and not their `camera_info`, and the flight-log gate's own
    DETECTOR NEVER RAN check reads the artifact after the take is burnt. So the node gets the same
    startup refusal the gz clock has (QA, 2026-09-07)."""

    class _Node:
        """The two attributes the wait reads. `build_node` cannot be constructed off-sim, and
        duck-typing it here is the same trick `feed_depth_frame` is tested with."""

        def __init__(self, detector):
            self._frame_detector = detector
            self._frame_topics = node.FRAME_TOPICS[node.DEPTH_SOURCE_TAG]

    class _Clock:
        def __init__(self, step=0.1):
            self.t, self.step = 0.0, step

        def __call__(self):
            self.t += self.step
            return self.t

    def test_it_returns_true_as_soon_as_the_intrinsics_arm(self):
        src = depth_source(intr=None)
        calls = []

        def spin_once(_n, timeout_sec=None):
            calls.append(timeout_sec)
            if len(calls) == 3:
                src.set_intrinsics(INTR)                  # the camera_info lands on the 3rd spin

        self.assertTrue(node.wait_for_live_intrinsics(self._Node(src), spin_once))
        self.assertEqual(len(calls), 3)                   # ...and it stopped there

    def test_it_gives_up_after_the_window_rather_than_blocking_forever(self):
        spins = []
        ok = node.wait_for_live_intrinsics(
            self._Node(depth_source(intr=None)),
            lambda _n, timeout_sec=None: spins.append(1),
            timeout_s=1.0, now=self._Clock())
        self.assertFalse(ok)
        self.assertTrue(spins, "it must SPIN: a subscription that is never spun delivers nothing, "
                               "so a sleep-only wait could never see camera_info arrive")

    def test_an_already_armed_detector_does_not_spin_at_all(self):
        def boom(*a, **k):
            raise AssertionError("nothing to wait for")

        self.assertTrue(node.wait_for_live_intrinsics(self._Node(depth_source()), boom))

    def test_a_scripted_source_has_nothing_to_wait_for(self):
        """`--demo` reads no frames. Inventing a camera requirement for it would refuse the
        ADR-013 am. 2 regression arm on a camera it never uses."""
        class _NoDetector:
            _frame_detector = None
            _frame_topics = None

        self.assertTrue(node.wait_for_live_intrinsics(_NoDetector(), lambda *a, **k: None))

    def test_main_refuses_with_its_own_exit_code_and_names_the_topic(self):
        """Source-asserted: `main` needs rclpy. The exit code is DISTINCT from the clock's 3 and
        from the import failure's 2, because 'the camera never armed' and 'no clock' are different
        bringup faults with different fixes."""
        main_src = NODE_SRC.split("def main(")[1]
        self.assertIn("if not wait_for_live_intrinsics(node, rclpy.spin_once):", main_src)
        self.assertIn("return 4", main_src)
        self.assertIn("node._frame_topics[1]", main_src)          # the message names the topic
        self.assertIn("dropped_no_intrinsics", main_src)          # ...and the counter to look at
        self.assertLess(main_src.index("node._gz_now is None"),   # after the clock gate, not before
                        main_src.index("wait_for_live_intrinsics"))

    def test_an_unusable_camera_info_leaves_the_detector_unarmed_so_the_same_refusal_fires(self):
        """The node catches the seam's arming refusal, logs it ONCE and does not arm; the wait then
        turns it into the same exit. An uncalibrated K would otherwise arm the detector and raise
        ZeroDivisionError out of a subscription callback after takeoff."""
        src = depth_source(intr=None)
        with self.assertRaises(ValueError):
            src.set_intrinsics(CameraIntrinsics(width_px=W, height_px=H, fx=0.0, fy=0.0,
                                                cx=0.0, cy=0.0))
        self.assertIsNone(src.intr)
        self.assertFalse(node.wait_for_live_intrinsics(
            self._Node(src), lambda *a, **k: None, timeout_s=1.0, now=self._Clock()))
        self.assertIn("REFUSED the camera_info on", NODE_SRC)
        self.assertIn("self._intrinsics_refused", NODE_SRC)


# ================================================================================================
# 3. The log block (DESIGN §6 item 3)
# ================================================================================================
class TestDepthDetectorLogBlock(unittest.TestCase):
    def _block(self, **kw):
        cfg = detector_config_from_args(parse_args(["--detect", "--detection-source", "depth"]))
        return detector_log_block(depth_source(**kw), cfg)

    def test_it_names_the_depth_detector_and_both_modules_that_ran(self):
        block = self._block()
        self.assertEqual(block["source"], "depth_blob")
        self.assertEqual(block["module"], "fieldguard_planning.depth_segment")
        self.assertEqual(block["seam_module"], "fieldguard_planning.depth_detect")

    def test_it_records_the_frozen_params_as_one_object_with_their_provenance(self):
        block = self._block()
        self.assertEqual(block["params"], {
            "bg_window_px": 15, "margin_m": 1.5, "min_area_px": 10, "open_iter": 0,
            "max_boxes": 64, "near_m": 0.1, "far_m": 60.0, "link_break": False})
        self.assertEqual(block["params_provenance"], DEFAULT_PARAMS_PROVENANCE)
        self.assertFalse(block["params_provisional"])

    def test_the_params_are_read_off_the_SEGMENTER_THAT_RAN_not_the_CLI_intent(self):
        """The block's own stated principle, and the COMMANDED-recorded-as-FLOWN family in
        miniature: the two objects are identical on every real run, so a fallback to `cfg`
        (mutation M21) passes every test that does not make them differ. Here the segmenter carries
        a margin the config does not, and the artifact must report the one that segmented."""
        flown = params_with(DEFAULT_PARAMS, margin_m=2.25)
        src = DepthDetectionSource(DepthSegmenter(flown), min_range_m=flown.near_m,
                                   max_range_m=flown.far_m)
        src.set_intrinsics(INTR)
        adopted_cfg = detector_config_from_args(
            parse_args(["--detect", "--detection-source", "depth"]))
        block = detector_log_block(src, adopted_cfg)
        self.assertEqual(block["params"]["margin_m"], 2.25)
        self.assertEqual(adopted_cfg.depth_params.margin_m, 1.5)   # ...and they really did differ

    def test_the_intrinsics_are_the_LIVE_ones_and_say_so(self):
        block = self._block()
        self.assertEqual(block["intrinsics"]["fx"], FX)
        self.assertEqual(block["intrinsics"]["provenance"],
                         "live /fg/depth/camera_info (not config/depth_camera.json)")

    def test_intrinsics_are_null_before_camera_info_rather_than_config_values(self):
        self.assertIsNone(self._block(intr=None)["intrinsics"])

    def test_the_range_model_names_what_it_is_NOT(self):
        model = self._block()["range_model"]
        self.assertEqual(model,
                         "measured depth (ADR-020); no radius prior, no ground-plane projection")

    def test_it_carries_BOTH_counter_dicts_because_they_measure_different_halves(self):
        src = depth_source()
        src.on_frame(GZ_T0, sky_frame_with_block(), DRONE_ENU, IDENTITY_Q)
        cfg = detector_config_from_args(parse_args(["--detect", "--detection-source", "depth"]))
        block = detector_log_block(src, cfg)
        self.assertEqual(block["counters"]["depth_msgs_received"], 1)
        self.assertEqual(block["counters"]["frames_detected_on"], 1)
        self.assertEqual(block["segmenter_counters"]["frames"], 1)
        self.assertEqual(block["segmenter_counters"]["boxes_returned"], 1)

    def test_the_annotator_is_recorded_as_ANNOTATE_ONLY(self):
        block = self._block(annotator=lambda p: None)
        self.assertIn("ANNOTATE + COUNT ONLY, never suppress", block["static_map_annotator"])
        self.assertIsNone(self._block()["static_map_annotator"])

    def test_the_block_is_json_serialisable_with_no_numpy_scalars_in_it(self):
        """The counters cross a `json.dumps` into the flight log, where a numpy scalar raises
        TypeError -- and the segmenter's counters come from numpy sums."""
        src = depth_source()
        src.on_frame(GZ_T0, sky_frame_with_block(), DRONE_ENU, IDENTITY_Q)
        cfg = detector_config_from_args(parse_args(["--detect", "--detection-source", "depth"]))
        block = detector_log_block(src, cfg)
        round_tripped = json.loads(json.dumps(block))
        self.assertEqual(round_tripped, block)
        for name, counters in (("source", block["counters"]),
                               ("segmenter", block["segmenter_counters"])):
            for k, v in counters.items():
                self.assertNotIsInstance(v, np.generic, msg=f"{name}.{k}")

    def test_the_field_set_is_the_one_a_reader_of_the_artifact_gets(self):
        self.assertEqual(sorted(self._block()), sorted([
            "source", "module", "seam_module", "params", "params_provenance",
            "params_provisional", "min_range_m", "max_range_m", "range_model",
            "static_map_annotator", "intrinsics", "counters", "segmenter_counters"]))

    def test_without_a_config_the_provenance_says_unknown_rather_than_inventing_one(self):
        block = detector_log_block(depth_source(), None)
        self.assertEqual(block["params_provenance"], "unknown (no DetectorConfig)")
        self.assertTrue(block["params_provisional"])     # unprovenanced == provisional, both halves

    def test_the_seams_own_refusal_window_is_on_the_artifacts_face(self):
        block = self._block()
        self.assertEqual((block["min_range_m"], block["max_range_m"]), (0.1, 60.0))
        self.assertEqual((block["min_range_m"], block["max_range_m"]),
                         (block["params"]["near_m"], block["params"]["far_m"]))


# ================================================================================================
# 4. The decode -- every number derived from the message, then asserted
# ================================================================================================
class TestDecodeDepthFrame(unittest.TestCase):
    def test_a_canned_frame_round_trips_to_float32_HxW(self):
        frame = sky_frame_with_block()
        got = decode_depth_frame(_Msg(frame))
        self.assertEqual(got.shape, (H, W))
        self.assertEqual(got.dtype, np.float32)
        np.testing.assert_array_equal(got, frame)

    def test_is_bigendian_is_READ_not_assumed(self):
        """The one term here no live frame has ever exercised in the other state -- gz publishes
        little-endian on this host. So both halves are asserted: a big-endian payload decodes to the
        SAME array when the flag says so, and to something else entirely when it lies. There is no
        way to REFUSE a wrong flag (bytes carry no byte order), which is exactly why it is taken
        from the message rather than assumed."""
        frame = sky_frame_with_block()
        np.testing.assert_array_equal(decode_depth_frame(_Msg(frame, is_bigendian=1)), frame)

        swapped = _Msg(frame, is_bigendian=1)
        swapped.is_bigendian = 0                     # the payload is BE; the flag now says LE
        self.assertFalse(np.array_equal(decode_depth_frame(swapped), frame))

    def test_a_step_that_disagrees_with_the_width_is_REFUSED_not_reshaped(self):
        """A padded or mis-strided row reshapes without complaint into a plausible depth image with
        every pixel in the wrong place -- a confident obstacle at a fictional bearing."""
        frame = sky_frame_with_block()
        for step in (W * 4 + 4, W * 4 - 4, W * 2, 0):
            with self.subTest(step=step):
                with self.assertRaises(ValueError) as ctx:
                    decode_depth_frame(_Msg(frame, step=step))
                # The distinctive half of the STRIDE message: `assertIn("step", ...)` is also
                # satisfied by the PAYLOAD-length one, so deleting the stride check outright
                # survived it (QA mutation M7). Bounded either way -- `reshape(h, w)` refuses a
                # mis-strided frame anyway, since height*step/4 == height*width forces
                # step == 4*width -- so this is test precision, not a safety hole.
                self.assertIn("!= width", str(ctx.exception))

    def test_a_payload_length_that_disagrees_with_height_x_step_is_refused(self):
        frame = sky_frame_with_block()
        truncated = _Msg(frame)
        truncated.data = truncated.data[: -4 * W]      # one row short
        with self.assertRaises(ValueError) as ctx:
            decode_depth_frame(truncated)
        self.assertIn("payload", str(ctx.exception))

    def test_a_non_32FC1_encoding_is_refused_rather_than_reinterpreted(self):
        for encoding in ("16UC1", "32FC2", "mono8", "", None):
            with self.subTest(encoding=encoding):
                with self.assertRaises(ValueError) as ctx:
                    decode_depth_frame(_Msg(sky_frame_with_block(), encoding=encoding))
                self.assertIn("encoding", str(ctx.exception))

    def test_a_degenerate_frame_is_refused(self):
        empty = _Msg(sky_frame_with_block(), height=0)
        empty.step = W * 4
        with self.assertRaises(ValueError):
            decode_depth_frame(empty)

    def test_the_decoded_frame_is_what_the_segmenter_accepts(self):
        """The segmenter refuses anything that is not float32 (H, W) -- coercing is how a uint16
        millimetre encoding becomes a metre-valued obstacle. The decode's output must satisfy it
        with no conversion in between, on BOTH byte orders."""
        for is_bigendian in (0, 1):
            with self.subTest(is_bigendian=is_bigendian):
                arr = decode_depth_frame(_Msg(sky_frame_with_block(), is_bigendian=is_bigendian))
                self.assertEqual(len(DepthSegmenter(DEFAULT_PARAMS)(arr)), 1)


# ================================================================================================
# 5. Decode -> pairing -> seam, end to end, with the REAL segmenter
# ================================================================================================
class TestFeedDepthFrame(unittest.TestCase):
    def _buf(self, tag_s=GZ_T0, pos=DRONE_ENU):
        buf = PoseBuffer()
        buf.tag(tag_s, pos, IDENTITY_Q)
        return buf

    def test_a_canned_message_becomes_a_detection_at_the_expected_ENU(self):
        """Hand-derivable: the block's box midpoint IS the principal point, so the ray is the
        optical axis; nose east means body +X = world +X; the mount sits 0.15 m ahead of the drone.
        Expected = drone + (0.15 + 20.0, 0, 0)."""
        src = depth_source()
        dets = feed_depth_frame(src, self._buf(), _Msg(sky_frame_with_block()))
        self.assertEqual(len(dets), 1)
        det = dets[0]
        self.assertAlmostEqual(det.position_enu[0], DRONE_ENU[0] + 0.15 + TARGET_DEPTH_M, places=6)
        self.assertAlmostEqual(det.position_enu[1], DRONE_ENU[1], places=6)
        self.assertAlmostEqual(det.position_enu[2], DRONE_ENU[2], places=6)
        self.assertEqual(det.source, depth_detect.SOURCE_TAG)
        self.assertIsNone(det.track_id)

    def test_pixel_to_ground_enu_is_NEVER_called(self):
        """ADR-009 rule 1, as an executable assertion on the live path. The ground-plane answer for
        this ray is z=0 -- 15 m below ownship and outside the policy's +/-6 m threat cylinder -- so
        it does not merely mis-place a bird, it SUPPRESSES it."""
        def boom(*a, **k):
            raise AssertionError("pixel_to_ground_enu was called on the depth path")

        with mock.patch.object(ndvi_georef, "pixel_to_ground_enu", boom):
            dets = feed_depth_frame(depth_source(), self._buf(), _Msg(sky_frame_with_block()))
        self.assertEqual(len(dets), 1)
        self.assertGreater(dets[0].position_enu[2], 5.0)      # emphatically not the ground answer

    def test_the_stamp_passes_through_unshifted_on_the_frames_OWN_clock(self):
        src = depth_source()
        stamp = 1234.5
        dets = feed_depth_frame(src, self._buf(tag_s=stamp), _Msg(sky_frame_with_block(), stamp))
        self.assertAlmostEqual(dets[0].stamp_s, stamp, places=6)

    def test_the_pose_is_the_one_nearest_the_frames_own_stamp_not_the_latest(self):
        """The render stalls and bursts; arrival-pairing puts an obstacle metres down-track. The
        buffer holds a pose 3 m further north tagged AFTER the frame -- the pairing must pick the
        one tagged at the frame's own stamp, so the detection lands off the earlier pose."""
        buf = PoseBuffer()
        buf.tag(GZ_T0, DRONE_ENU, IDENTITY_Q)
        buf.tag(GZ_T0 + 1.0, (DRONE_ENU[0], DRONE_ENU[1] + 3.0, DRONE_ENU[2]), IDENTITY_Q)
        dets = feed_depth_frame(depth_source(), buf, _Msg(sky_frame_with_block(), GZ_T0))
        self.assertAlmostEqual(dets[0].position_enu[1], DRONE_ENU[1], places=6)

    def test_a_stale_pose_pair_is_dropped_and_counted_rather_than_used(self):
        src = depth_source()
        buf = self._buf(tag_s=GZ_T0 + 30.0)          # 30 s from the frame: metres of error at cruise
        self.assertEqual(feed_depth_frame(src, buf, _Msg(sky_frame_with_block(), GZ_T0)), [])
        self.assertEqual(src.counters()["dropped_stale_pose_pair"], 1)

    def test_a_frame_with_no_pose_at_all_is_counted_not_crashed(self):
        src = depth_source()
        self.assertEqual(feed_depth_frame(src, PoseBuffer(), _Msg(sky_frame_with_block())), [])
        self.assertEqual(src.counters()["dropped_no_pose_pair"], 1)

    def test_frames_before_the_first_camera_info_are_counted_and_dropped(self):
        """ORDERING (DESIGN §6 item 4). Intrinsics arrive LIVE and may arrive late; a silently
        discarded pre-`camera_info` window is exactly how the recorder lost most of a flight
        (ADR-013 am. 6a). After `set_intrinsics` the same frame detects normally."""
        src = depth_source(intr=None)
        buf = self._buf()
        self.assertEqual(feed_depth_frame(src, buf, _Msg(sky_frame_with_block())), [])
        counters = src.counters()
        self.assertEqual(counters["depth_msgs_received"], 1)   # counted BEFORE the guard
        self.assertEqual(counters["dropped_no_intrinsics"], 1)
        self.assertEqual(counters["frames_detected_on"], 0)

        src.set_intrinsics(INTR)
        self.assertEqual(len(feed_depth_frame(src, buf, _Msg(sky_frame_with_block()))), 1)
        self.assertEqual(src.counters()["frames_detected_on"], 1)

    def test_an_empty_sky_clears_the_previous_detections(self):
        """'The bird left the frame' and 'no frame arrived' must not look alike to the policy."""
        src = depth_source()
        buf = self._buf()
        self.assertEqual(len(feed_depth_frame(src, buf, _Msg(sky_frame_with_block()))), 1)
        empty = np.full((H, W), np.inf, dtype=np.float32)
        self.assertEqual(feed_depth_frame(src, buf, _Msg(empty, GZ_T0)), [])
        self.assertEqual(src(GZ_T0), [])

    def test_a_target_beyond_the_clip_window_is_refused_never_clamped(self):
        """gz stops MEASURING at the clip planes, so a value outside them is not a range. Nothing is
        detected and nothing is invented at 60.0 m -- and the pixels are COUNTED, so "outside the
        window" and "empty sky" do not look alike in the artifact."""
        src = depth_source()
        far = np.full((H, W), np.inf, dtype=np.float32)
        far[237:243, 317:323] = np.float32(61.0)     # finite, but outside the exclusive window
        self.assertEqual(feed_depth_frame(src, self._buf(), _Msg(far)), [])
        self.assertEqual(src.segmenter.counters()["px_outside_clip_window"], 36)


# ================================================================================================
# 6. Annotate, never suppress (DESIGN §6 item 5)
# ================================================================================================
class TestTheGeofenceAnnotatorIsWiredOnAndOnlyAnnotates(unittest.TestCase):
    """depth_detect rule 9. Tree canopies enter the forward frame from ~24.4 m and depth cannot tell
    a tree from a bird, so the map ANNOTATES and COUNTS; the policy decides. A filter here would
    delete the bird-beside-a-tree case, and a missed obstacle is a safety bug where a wasted dodge
    is not."""

    def setUp(self):
        self.gmap = GeofenceMap.from_file()
        self.tree = self.gmap.obstacles[0]

    def _aimed_at_the_tree(self):
        """A frame + pose whose principal ray lands inside a MAPPED tree's 3D volume: park the drone
        `TARGET_DEPTH_M` west of the tree at the tree's own height, nose east."""
        pos = (self.tree.x_m - 0.15 - TARGET_DEPTH_M, self.tree.y_m, self.tree.z_m + 1.0)
        buf = PoseBuffer()
        buf.tag(GZ_T0, pos, IDENTITY_Q)
        return buf

    def test_the_node_wires_the_annotator_on_for_a_depth_flight(self):
        src = build_detection_source(
            detector_config_from_args(parse_args(["--detect", "--detection-source", "depth"])),
            node.KIND_DEPTH)
        self.assertIsNotNone(src.static_map_annotator)

    def test_a_detection_inside_a_mapped_tree_is_STILL_EMITTED_and_counted(self):
        src = depth_source(annotator=depth_detect.geofence_annotator(self.gmap))
        dets = feed_depth_frame(src, self._aimed_at_the_tree(), _Msg(sky_frame_with_block()))
        self.assertEqual(len(dets), 1, "annotation must never suppress -- the policy decides")
        self.assertEqual(dets[0].static_map_hint, self.tree.id)
        self.assertEqual(src.counters()["detections_near_known_obstacle"], 1)

    def test_the_same_detection_in_clear_air_carries_no_hint(self):
        src = depth_source(annotator=depth_detect.geofence_annotator(self.gmap))
        buf = PoseBuffer()
        buf.tag(GZ_T0, DRONE_ENU, IDENTITY_Q)          # mid-field at cruise, clear of every tree
        dets = feed_depth_frame(src, buf, _Msg(sky_frame_with_block()))
        self.assertEqual(len(dets), 1)
        self.assertIsNone(dets[0].static_map_hint)
        self.assertEqual(src.counters()["detections_near_known_obstacle"], 0)


# ================================================================================================
# 6b. What the artifact says when something is wrong with the artifact
# ================================================================================================
class TestTheLogSurvivesAndDoesNotMisdescribeItself(unittest.TestCase):
    def test_a_clean_log_is_serialised_exactly_as_before(self):
        log = {"run": {"detector": {"counters": {"depth_msgs_received": 3}}}, "cells": []}
        self.assertEqual(node.serialise_flight_log(log), json.dumps(log, indent=2))
        self.assertNotIn("log_serialisation_degraded", json.loads(node.serialise_flight_log(log)))

    def test_an_unserialisable_value_degrades_the_log_instead_of_destroying_it(self):
        """`dump_flight_log` runs in `main`'s finally: a TypeError there writes NO FILE and
        replaces whatever ended the flight. A numpy scalar in a counters dict is the live shape of
        it -- unreachable with the shipped detectors (pinned above on the real path), which is why
        this is a contract note and not a bug report."""
        log = {"run": {"detector": {"counters": {"depth_msgs_received": np.int64(3)}}}}
        with self.assertRaises(TypeError):
            json.dumps(log)                                    # the premise, not an assumption
        got = json.loads(node.serialise_flight_log(log))
        self.assertIn("log_serialisation_degraded", got)
        # ...and the rescued value is a STRING, so a gate reading it as a number says so.
        self.assertIsInstance(got["run"]["detector"]["counters"]["depth_msgs_received"], str)

    def test_an_unknown_DECLARED_tag_is_not_described_as_declaring_none(self):
        """A note that says the opposite of what happened is worse than no note. Both unknown
        cases are unscoreable; they are not the same fault and the artifact must not confuse them."""
        class _Declared:
            SOURCE_TAG = "lidar_blob"

            def on_frame(self, *a, **k):
                return []

        class _Untagged:
            def on_frame(self, *a, **k):
                return []

        declared = detector_log_block(_Declared(), None)
        self.assertEqual(declared["source"], "lidar_blob")
        self.assertIn("has no log branch for", declared["note"])
        untagged = detector_log_block(_Untagged(), None)
        self.assertEqual(untagged["source"], node.UNTAGGED_FRAME_SOURCE)
        self.assertIn("declares no SOURCE_TAG", untagged["note"])

    def test_the_import_failure_names_the_detector_that_was_ASKED_for(self):
        """`--detect --detection-source depth` on an image without scipy printed the NDVI arm's
        wording, ADR-003 am. 7 and all -- the adoption verdict of the other sensor. Reachable
        without rclpy: this branch runs before the node is built."""
        import io
        from contextlib import redirect_stderr

        def no_scipy(*a, **k):
            raise ImportError("No module named 'scipy'")

        out = {}
        for kind in ("ndvi", "depth"):
            buf = io.StringIO()
            with mock.patch.object(node, "build_detection_source", no_scipy):
                with redirect_stderr(buf):
                    code = node.main(["--detect", "--detection-source", kind])
            self.assertEqual(code, 2)
            out[kind] = buf.getvalue()
        self.assertIn("--detection-source depth", out["depth"])
        self.assertIn("depth_segment", out["depth"])
        self.assertNotIn("ADR-003", out["depth"])              # the OTHER sensor's verdict
        self.assertIn("ndvi_detect", out["ndvi"])
        self.assertIn("ADR-003 am. 7", out["ndvi"])


# ================================================================================================
# 7. The gate reads what the node writes
# ================================================================================================
class TestTheFlightLogGateAndTheNodeAgree(unittest.TestCase):
    def test_the_gate_knows_the_depth_tag_by_the_same_name_the_node_writes(self):
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import check_live_flight_log as checker

        self.assertEqual(checker.DET_DEPTH_BLOB, node.DEPTH_SOURCE_TAG)
        self.assertEqual(checker.DET_NDVI_BLOB, node.NDVI_SOURCE_TAG)
        # A depth block the node itself wrote must not trip the mislabel rule...
        cfg = detector_config_from_args(parse_args(["--detect", "--detection-source", "depth"]))
        block = detector_log_block(depth_source(), cfg)
        self.assertEqual(checker.gate_detector_block_matches_source({"detector": block}), [])
        # ...and every depth-only field the rule keys on is one this block actually carries.
        for field in checker.DEPTH_ONLY_DETECTOR_FIELDS:
            self.assertIn(field, block)
        for key in checker.DEPTH_ONLY_COUNTERS:
            self.assertIn(key, block["counters"])
        # ...while relabelling it `ndvi_blob` is refused, which is the point of the rule.
        mislabelled = dict(block, source=checker.DET_NDVI_BLOB)
        self.assertTrue(checker.gate_detector_block_matches_source({"detector": mislabelled}))


if __name__ == "__main__":
    unittest.main()
