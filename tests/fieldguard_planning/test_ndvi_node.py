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
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np  # noqa: E402

from fieldguard_planning.ndvi_fusion import ndvi_to_preview_rgb  # noqa: E402
from fieldguard_planning.ndvi_node import (  # noqa: E402
    NDVI_ENCODING,
    PREVIEW_ENCODING,
    ImageMsgFields,
    apply_image_fields,
    assemble_ndvi_msg_fields,
    assemble_preview_msg_fields,
    georef_anchor_header,
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


if __name__ == "__main__":
    unittest.main()
