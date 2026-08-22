"""Tests for the pure message-assembly seam in ndvi_node.py (the rclpy node itself is verified live).

These cover the part of the node that is arithmetic rather than wiring, and that used to live inside
the `_on_pair` rclpy callback where nothing could reach it:

  * the ADR-007 stamp anchor -- the fused NDVI frame inherits the RGB header, NEVER the NIR one. Get
    this wrong and every stitched cell is georeferenced against the wrong pose, silently.
  * the `step` arithmetic for both outputs (32FC1 -> width*4, rgb8 -> width*3) and the buffer length
    that must agree with it.
  * dtype + contiguity of the serialised buffer: `FusionResult.ndvi` may be a float64 view, and
    `.tobytes()` on a raw view emits the parent's layout, not the view's.

Requires numpy (see ndvi_fusion.py's module docstring for why the NDVI slice is a scoped exception to
this package's stdlib-only rule) -- unlike most of tests/fieldguard_planning, which runs bare.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np  # noqa: E402

from fieldguard_planning.ndvi_fusion import ndvi_to_preview_rgb  # noqa: E402
from fieldguard_planning.ndvi_node import (  # noqa: E402
    NDVI_ENCODING,
    PREVIEW_ENCODING,
    UNPAIRED_STAMP_WINDOW,
    ImageMsgFields,
    UnpairedNirDeltaHistogram,
    apply_image_fields,
    assemble_ndvi_msg_fields,
    assemble_preview_msg_fields,
    georef_anchor_header,
    unpaired_red_count,
)


class _Stamp:
    def __init__(self, sec, nanosec):
        self.sec = sec
        self.nanosec = nanosec


class _Header:
    """Stand-in for std_msgs/Header. The assembly functions only ever pass it through by reference,
    so a bare object is enough -- and identity makes 'which header shipped?' unambiguous."""

    def __init__(self, sec, nanosec, frame_id):
        self.stamp = _Stamp(sec, nanosec)
        self.frame_id = frame_id


class _StubImage:
    """Duck-typed sensor_msgs/Image -- apply_image_fields only assigns attributes."""


# A realistic pair: NIR trails RGB by 40 ms, inside the 50 ms stale-pair tolerance at 5 Hz, so this
# pair WOULD be fused -- exactly the case where picking the wrong stamp is a silent 40 ms georef lie
# rather than an obvious blow-up.
RGB_HEADER = _Header(100, 0, "ndvi_camera_optical")
NIR_HEADER = _Header(100, 40_000_000, "nir_camera_optical")


def _ndvi(height=4, width=6):
    """A deterministic NDVI-shaped float32 array spanning [-1, 1]."""
    return np.linspace(-1.0, 1.0, height * width, dtype=np.float32).reshape(height, width)


class TestGeorefAnchorHeader(unittest.TestCase):
    def test_returns_the_rgb_header(self):
        self.assertIs(georef_anchor_header(RGB_HEADER, NIR_HEADER), RGB_HEADER)

    def test_never_returns_the_nir_header(self):
        """ADR-007: the RGB stamp is the georef anchor. This is the regression that fails if someone
        'fixes' the fused frame to carry the NIR stamp instead."""
        self.assertIsNot(georef_anchor_header(RGB_HEADER, NIR_HEADER), NIR_HEADER)


class TestAssembleNdviMsgFields(unittest.TestCase):
    def setUp(self):
        self.ndvi = _ndvi()
        self.fields = assemble_ndvi_msg_fields(self.ndvi, RGB_HEADER, NIR_HEADER)

    def test_stamp_anchor_is_the_rgb_header(self):
        self.assertIs(self.fields.header, RGB_HEADER)
        self.assertEqual(self.fields.header.stamp.nanosec, 0)          # RGB's stamp, not NIR's 40 ms

    def test_encoding_and_dimensions(self):
        self.assertEqual(self.fields.encoding, NDVI_ENCODING)
        self.assertEqual(self.fields.encoding, "32FC1")
        self.assertEqual((self.fields.height, self.fields.width), (4, 6))
        self.assertEqual(self.fields.is_bigendian, 0)

    def test_step_is_width_times_four(self):
        self.assertEqual(self.fields.step, self.fields.width * 4)

    def test_buffer_length_agrees_with_step(self):
        """A step/length disagreement is the classic silently-corrupt-image bug: rviz reads rows at
        the declared stride and shears the frame."""
        self.assertEqual(len(self.fields.data), self.fields.height * self.fields.step)

    def test_pixel_values_round_trip(self):
        decoded = np.frombuffer(self.fields.data, dtype=np.float32).reshape(
            self.fields.height, self.fields.width)
        np.testing.assert_allclose(decoded, self.ndvi)

    def test_dimensions_are_plain_ints(self):
        """numpy ints round-trip through rclpy, but the msg fields are uint32 -- keep them plain."""
        for value in (self.fields.height, self.fields.width, self.fields.step):
            self.assertIsInstance(value, int)

    def test_non_contiguous_float64_view_serialises_its_own_values(self):
        """`result.ndvi` can be a view (a strided slice or a transpose) and need not be float32.
        `.tobytes()` on the raw view would emit the PARENT buffer's layout and element size -- the
        declared step would then describe bytes that aren't there."""
        base = np.arange(24, dtype=np.float64).reshape(4, 6) / 24.0
        view = base[:, ::2]                                   # (4, 3), strided, float64
        self.assertFalse(view.flags["C_CONTIGUOUS"])

        fields = assemble_ndvi_msg_fields(view, RGB_HEADER, NIR_HEADER)
        self.assertEqual((fields.height, fields.width), (4, 3))
        self.assertEqual(fields.step, 12)                     # 3 px * 4 bytes, not the parent's 6 px
        self.assertEqual(len(fields.data), 4 * 12)
        decoded = np.frombuffer(fields.data, dtype=np.float32).reshape(4, 3)
        np.testing.assert_allclose(decoded, view.astype(np.float32))

    def test_rejects_non_2d_array(self):
        with self.assertRaises(ValueError):
            assemble_ndvi_msg_fields(np.zeros((4, 6, 3), dtype=np.float32), RGB_HEADER, NIR_HEADER)


class TestAssemblePreviewMsgFields(unittest.TestCase):
    def setUp(self):
        self.ndvi = _ndvi()
        self.fields = assemble_preview_msg_fields(self.ndvi, RGB_HEADER, NIR_HEADER)

    def test_encoding_and_step_are_rgb8(self):
        self.assertEqual(self.fields.encoding, PREVIEW_ENCODING)
        self.assertEqual(self.fields.encoding, "rgb8")
        self.assertEqual(self.fields.step, self.fields.width * 3)
        self.assertEqual(self.fields.is_bigendian, 0)

    def test_buffer_length_agrees_with_step(self):
        self.assertEqual(len(self.fields.data), self.fields.height * self.fields.step)

    def test_shares_the_authoritative_frames_dimensions(self):
        """The preview is non-authoritative but must stay frame-for-frame comparable with
        /fg/ndvi/image -- same shape, same anchor."""
        ndvi_fields = assemble_ndvi_msg_fields(self.ndvi, RGB_HEADER, NIR_HEADER)
        self.assertEqual((self.fields.height, self.fields.width),
                         (ndvi_fields.height, ndvi_fields.width))
        self.assertIs(self.fields.header, ndvi_fields.header)

    def test_stamp_anchor_is_the_rgb_header(self):
        self.assertIs(self.fields.header, RGB_HEADER)

    def test_pixels_match_the_colormap(self):
        decoded = np.frombuffer(self.fields.data, dtype=np.uint8).reshape(
            self.fields.height, self.fields.width, 3)
        np.testing.assert_array_equal(decoded, ndvi_to_preview_rgb(self.ndvi))

    def test_non_contiguous_view_serialises_its_own_values(self):
        base = np.linspace(-1.0, 1.0, 24, dtype=np.float32).reshape(4, 6)
        view = base[:, ::2]
        fields = assemble_preview_msg_fields(view, RGB_HEADER, NIR_HEADER)
        self.assertEqual((fields.height, fields.width), (4, 3))
        self.assertEqual(len(fields.data), 4 * 3 * 3)
        decoded = np.frombuffer(fields.data, dtype=np.uint8).reshape(4, 3, 3)
        np.testing.assert_array_equal(decoded, ndvi_to_preview_rgb(view))

    def test_rejects_non_2d_array(self):
        with self.assertRaises(ValueError):
            assemble_preview_msg_fields(np.zeros((2, 2, 3), dtype=np.float32), RGB_HEADER, NIR_HEADER)


class TestApplyImageFields(unittest.TestCase):
    def test_copies_every_field_onto_the_message(self):
        """Iterates ImageMsgFields._fields rather than listing them, so adding a field to the tuple
        without adding a copy line in apply_image_fields fails here instead of in rviz."""
        fields = assemble_ndvi_msg_fields(_ndvi(), RGB_HEADER, NIR_HEADER)
        msg = apply_image_fields(_StubImage(), fields)
        for name in ImageMsgFields._fields:
            self.assertEqual(getattr(msg, name), getattr(fields, name),
                             msg=f"apply_image_fields did not copy '{name}'")

    def test_returns_the_same_message_object(self):
        msg = _StubImage()
        fields = assemble_preview_msg_fields(_ndvi(), RGB_HEADER, NIR_HEADER)
        self.assertIs(apply_image_fields(msg, fields), msg)

    def test_header_is_assigned_by_reference_not_copied(self):
        msg = apply_image_fields(_StubImage(),
                                 assemble_ndvi_msg_fields(_ndvi(), RGB_HEADER, NIR_HEADER))
        self.assertIs(msg.header, RGB_HEADER)


class TestUnpairedRedCount(unittest.TestCase):
    """The number `dropped_pair_count: 0` was misread as, for four flights."""

    def test_reproduces_the_four_measured_gate_flights(self):
        # ADR-013 am. 6a: red / fused / dropped on F1-F4, and the unpaired counts it published.
        for red, fused, dropped, expected in ((73, 45, 0, 28), (126, 78, 0, 48),
                                              (113, 76, 0, 37), (217, 129, 0, 88)):
            self.assertEqual(unpaired_red_count(red, fused, dropped), expected)

    def test_reproduces_the_full_mission_demo_take(self):
        self.assertEqual(unpaired_red_count(962, 634, 0), 328)

    def test_the_stale_pair_guard_is_subtracted_too(self):
        """A pair the guard rejected DID reach fuse(); it is not an unpaired red."""
        self.assertEqual(unpaired_red_count(100, 60, 10), 30)

    def test_returns_a_plain_int_even_for_numpy_inputs(self):
        """json.dumps(np.int64) raises TypeError inside the 1 Hz stats timer, which would take the
        fusion node down MID-FLIGHT. The write boundary must never see a numpy scalar."""
        out = unpaired_red_count(np.int64(962), np.int64(634), np.int64(0))
        self.assertIs(type(out), int)
        self.assertEqual(json.dumps({"unpaired_red_count": out}), '{"unpaired_red_count": 328}')

    def test_never_reports_a_negative_count(self):
        """The counters are read from one thread while another is mid-`_on_pair`, so fused can be
        one ahead of red for an instant. A negative here would read as a bug that isn't one."""
        self.assertEqual(unpaired_red_count(10, 11, 0), 0)


class TestUnpairedNirDeltaHistogram(unittest.TestCase):
    """Settles the slop question offline: for a red frame that arrived and never fused, how far
    away was the nearest NIR that DID arrive? >= one tick means the own-tick partner never came and
    widening slop cannot recover it."""

    SLOP, TICK = 0.05, 0.2

    def _hist(self, **kw):
        return UnpairedNirDeltaHistogram(slop_s=self.SLOP, tick_s=self.TICK, **kw)

    def test_a_red_whose_own_tick_nir_died_lands_in_ge_tick(self):
        h = self._hist(settle_s=1.0)
        h.on_nir(10.0)                 # the previous tick's NIR arrived
        h.on_red(10.2)                 # this tick's red arrived; its own-tick NIR never did
        h.on_nir(10.4)                 # the next tick's NIR arrived
        h.on_red(20.0)                 # advances the clock past the settle window
        h.drain()
        snap = h.snapshot()
        self.assertEqual(snap["ge_tick"], 1)
        self.assertEqual((snap["le_slop"], snap["slop_to_tick"]), (0, 0))
        self.assertEqual(snap["classified"], 1)

    def test_a_red_with_a_skewed_but_reachable_partner_lands_in_slop_to_tick(self):
        """The case that would make slop-widening a LIVE lever -- pinned so the disproof is a
        measurement, not an assumption baked into the bucketing."""
        h = self._hist(settle_s=1.0)
        h.on_red(10.0)
        h.on_nir(10.12)                # 120 ms away: outside the 50 ms slop, inside the 200 ms tick
        h.on_red(20.0)
        h.drain()
        self.assertEqual(h.snapshot()["slop_to_tick"], 1)

    def test_an_unpaired_red_with_a_partner_inside_slop_is_reported_not_hidden(self):
        """If this bucket ever fires live, the same-tick model is WRONG and something else is
        eating pairs -- so it must be visible rather than folded into the nearest neighbour."""
        h = self._hist(settle_s=1.0)
        h.on_red(10.0)
        h.on_nir(10.01)
        h.on_red(20.0)
        h.drain()
        self.assertEqual(h.snapshot()["le_slop"], 1)

    def test_boundary_deltas_follow_the_guard_not_the_other_way_round(self):
        """delta == slop is ACCEPTED by NdviFuser ('> max' is the drop condition), so it belongs in
        le_slop; delta == tick belongs in ge_tick."""
        h = self._hist(settle_s=1.0)
        h.on_red(10.0)
        h.on_nir(10.0 + self.SLOP)
        h.on_red(11.0)
        h.on_nir(11.0 + self.TICK)
        h.on_red(30.0)
        h.drain()
        snap = h.snapshot()
        self.assertEqual((snap["le_slop"], snap["ge_tick"]), (1, 1))
        self.assertEqual(snap["slop_to_tick"], 0)

    def test_float_noise_on_real_stamps_cannot_flip_a_bucket(self):
        """The failure this nearly shipped with: a real 0.2 s tick between two `sec + nanosec*1e-9`
        floats is 0.19999999999999929, so a bare `< tick_s` sorted a dead own-tick partner into
        slop_to_tick -- i.e. it would have reported the slop lever as LIVE on exactly the evidence
        that disproves it. Stamps here are built the way the node builds them."""
        def stamp(sec, nanosec):
            return sec + nanosec * 1e-9

        h = self._hist(settle_s=1.0)
        h.on_nir(stamp(1787289000, 0))
        h.on_red(stamp(1787289000, 200_000_000))     # exactly one tick after the only NIR
        h.on_nir(stamp(1787289000, 400_000_000))     # and exactly one tick before the next
        h.on_red(stamp(1787289020, 0))
        h.drain()
        self.assertEqual(h.snapshot()["ge_tick"], 1)

    def test_a_paired_red_is_never_counted(self):
        h = self._hist(settle_s=1.0)
        h.on_red(10.0)
        h.on_nir(10.0)
        h.on_pair(10.0)
        h.on_red(20.0)
        h.drain()
        snap = h.snapshot()
        self.assertEqual(snap["classified"], 0)
        self.assertEqual(snap["pending"], 1)      # the 20.0 red has not settled yet

    def test_pairing_matches_across_the_float_stamp_round_trip(self):
        """Both sides build the stamp from the same sec/nanosec fields, but the histogram must not
        depend on float equality surviving that -- it keys on microseconds."""
        stamp = 1234 + 567_000_000 * 1e-9
        h = self._hist(settle_s=0.5)
        h.on_red(stamp)
        h.on_nir(stamp)
        h.on_pair(1234 + 567_000_000 * 1e-9)
        h.on_red(stamp + 10.0)
        h.drain()
        self.assertEqual(h.snapshot()["classified"], 0)

    def test_a_red_inside_the_settle_window_is_pending_not_classified(self):
        """A red that has not settled is not evidence about pairing. Reporting it as unpaired would
        be exactly the fabrication the sidecar exists to prevent."""
        h = self._hist(settle_s=2.0)
        h.on_nir(10.0)
        h.on_red(10.2)
        h.on_red(10.4)                 # newest stamp 10.4, cutoff 8.4 -> nothing settled
        h.drain()
        snap = h.snapshot()
        self.assertEqual(snap["classified"], 0)
        self.assertEqual(snap["pending"], 2)

    def test_a_red_with_no_nir_ever_seen_is_its_own_bucket(self):
        """'the NIR band is dead' and 'the NIR band is late' are different diagnoses."""
        h = self._hist(settle_s=1.0)
        h.on_red(10.0)
        h.on_red(20.0)
        h.drain()
        snap = h.snapshot()
        self.assertEqual(snap["no_nir_in_window"], 1)
        self.assertEqual((snap["le_slop"], snap["slop_to_tick"], snap["ge_tick"]), (0, 0, 0))
        self.assertEqual(snap["classified"], 1)

    def test_memory_is_bounded_and_every_eviction_is_counted(self):
        """Absence must never read as zero: a red evicted before it could be classified is an
        `evicted_undrained`, not a silent skip."""
        h = self._hist(settle_s=1e9, window=8)   # settle so long nothing ever drains
        for i in range(50):
            h.on_red(float(i))
            h.on_nir(float(i))
        snap = h.snapshot()
        self.assertEqual(snap["pending"], 8)
        self.assertEqual(snap["evicted_undrained"], 42)
        self.assertEqual(snap["pending"] + snap["evicted_undrained"], 50)

    def test_default_window_is_bounded(self):
        h = UnpairedNirDeltaHistogram(slop_s=self.SLOP, tick_s=self.TICK)
        for i in range(UNPAIRED_STAMP_WINDOW * 2):
            h.on_red(float(i) * 0.2)
            h.on_nir(float(i) * 0.2)
            h.on_pair(float(i) * 0.2)
        self.assertLessEqual(h.snapshot()["pending"], UNPAIRED_STAMP_WINDOW)

    def test_snapshot_is_json_serialisable_plain_types(self):
        h = self._hist()
        h.on_red(np.float64(1.0))     # a numpy stamp must not leak to the write boundary
        h.on_nir(np.float64(1.0))
        snap = h.snapshot()
        for k, v in snap.items():
            self.assertIn(type(v), (int, float), msg=f"{k} is {type(v)}")
        json.dumps(snap)

    def test_an_empty_histogram_reports_zeros_that_are_real_measurements(self):
        """Distinct from absence: the fuser ran, classified nothing, and says so. The bucket
        boundaries ride along so the numbers are readable without the config."""
        snap = self._hist().snapshot()
        self.assertEqual(snap["classified"], 0)
        self.assertEqual(snap["pending"], 0)
        self.assertEqual((snap["slop_s"], snap["tick_s"]), (self.SLOP, self.TICK))


if __name__ == "__main__":
    unittest.main()
