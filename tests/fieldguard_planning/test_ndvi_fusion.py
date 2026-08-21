"""Tests for ndvi_fusion.py -- NDVI math (incl. the 0/0 guard), the ADR-007 stale-pair drop path,
and raw image decode. Requires numpy (see ndvi_fusion.py's module docstring for why this module is
a scoped exception to the package's usual stdlib-only rule) -- unlike the rest of
tests/fieldguard_planning, which runs on a bare interpreter.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np  # noqa: E402

from fieldguard_planning.ndvi_fusion import (  # noqa: E402
    FUSER_STATS_STALE_S,
    NDVI_ZERO_DENOM_SENTINEL,
    NdviFuser,
    StampedFrame,
    compute_ndvi,
    decode_mono16,
    decode_rgb8,
    load_camera_config,
    max_stamp_delta_s,
    ndvi_to_preview_rgb,
    nearest_index,
    pair_and_fuse_stream,
    read_fuser_stats,
    rescale_nir,
    rescale_red,
    write_fuser_stats,
)

CFG = load_camera_config()


class TestLoadCameraConfig(unittest.TestCase):
    def test_expected_fields_present(self):
        self.assertEqual(CFG["camera"]["image_width_px"], 640)
        self.assertEqual(CFG["camera"]["image_height_px"], 480)
        self.assertEqual(CFG["camera"]["update_rate_hz"], 5.0)
        self.assertEqual(CFG["thermal"]["min_temp_k"], 270.0)
        self.assertEqual(CFG["thermal"]["max_temp_k"], 330.0)
        self.assertEqual(CFG["thermal"]["resolution_k_per_count"], 0.01)


class TestRescaleRed(unittest.TestCase):
    def test_known_values(self):
        red = np.array([0, 128, 255], dtype=np.uint8)
        out = rescale_red(red)
        self.assertAlmostEqual(out[0], 0.0, places=9)
        self.assertAlmostEqual(out[1], 128.0 / 255.0, places=9)
        self.assertAlmostEqual(out[2], 1.0, places=9)


class TestRescaleNir(unittest.TestCase):
    """Cross-checked against config/ndvi_camera.json's own temperature_calibration table: canopy
    rho_nir=0.85 <-> temperature_k=321.0, computed as min_temp_k + rho*(max_temp_k-min_temp_k) =
    270 + 0.85*60 = 321.0. raw uint16 count = round(321.0 / 0.01) = 32100 per the decode_formula."""

    def test_canopy_calibration_point_round_trips(self):
        raw = np.array([32100], dtype=np.uint16)
        rho = rescale_nir(raw, min_temp_k=270.0, max_temp_k=330.0, resolution_k_per_count=0.01)
        self.assertAlmostEqual(float(rho[0]), 0.85, places=3)

    def test_soil_and_bird_calibration_points(self):
        # soil: rho=0.20 -> T=270+0.20*60=282.0K -> raw=28200
        # bird: rho=0.05 -> T=270+0.05*60=273.0K -> raw=27300
        raw = np.array([28200, 27300], dtype=np.uint16)
        rho = rescale_nir(raw, 270.0, 330.0, 0.01)
        self.assertAlmostEqual(float(rho[0]), 0.20, places=3)
        self.assertAlmostEqual(float(rho[1]), 0.05, places=3)

    def test_clips_outside_declared_range(self):
        # raw count corresponding to T below min_temp_k or above max_temp_k must clip to [0,1],
        # never go negative or exceed 1 (a sensor artifact/off-calibration pixel should not corrupt
        # NDVI with an out-of-physical-range reflectance).
        raw = np.array([0, 65535], dtype=np.uint16)  # T=0K and T=655.35K -- both outside [270,330]
        rho = rescale_nir(raw, 270.0, 330.0, 0.01)
        self.assertAlmostEqual(float(rho[0]), 0.0, places=9)
        self.assertAlmostEqual(float(rho[1]), 1.0, places=9)


class TestComputeNdvi(unittest.TestCase):
    def test_known_formula_value(self):
        # red=0.2, nir=0.85 -> (0.85-0.2)/(0.85+0.2) = 0.65/1.05 = 0.619047619...
        red = np.array([[0.2]])
        nir = np.array([[0.85]])
        ndvi, zero_count = compute_ndvi(red, nir)
        self.assertAlmostEqual(float(ndvi[0, 0]), 0.65 / 1.05, places=5)
        self.assertEqual(zero_count, 0)

    def test_bird_reads_negative(self):
        # bird rho_nir=0.05 over full-reflectance red backdrop is an extreme case; use the
        # calibration table's actual bird/canopy-adjacent contrast instead: red=0.5 nir=0.05 (a
        # non-vegetation, low-NIR object against a mid-red background) -> negative NDVI.
        red = np.array([[0.5]])
        nir = np.array([[0.05]])
        ndvi, _ = compute_ndvi(red, nir)
        self.assertLess(float(ndvi[0, 0]), 0.0)

    def test_zero_denominator_guard_single_pixel(self):
        red = np.array([[0.0]])
        nir = np.array([[0.0]])
        ndvi, zero_count = compute_ndvi(red, nir)
        self.assertEqual(zero_count, 1)
        self.assertEqual(float(ndvi[0, 0]), NDVI_ZERO_DENOM_SENTINEL)
        self.assertFalse(np.isnan(ndvi[0, 0]), "must never emit NaN silently")

    def test_zero_denominator_guard_mixed_frame(self):
        """A frame with SOME degenerate pixels must sentinel only those, leave the rest correct,
        and count exactly the degenerate ones -- not vacuously all-zero, not silently dropped."""
        red = np.array([[0.0, 0.2], [0.5, 0.0]])
        nir = np.array([[0.0, 0.85], [0.5, 0.3]])
        # pixel (0,0): 0/0 -> sentinel.  (0,1): normal.  (1,0): 0.5&0.5 -> 0.0 (real zero, NOT
        # degenerate -- denom=1.0 != 0).  (1,1): 0.0&0.3 -> denom=0.3, ndvi=1.0 (nir only).
        ndvi, zero_count = compute_ndvi(red, nir)
        self.assertEqual(zero_count, 1)
        self.assertEqual(float(ndvi[0, 0]), NDVI_ZERO_DENOM_SENTINEL)
        self.assertAlmostEqual(float(ndvi[0, 1]), 0.65 / 1.05, places=5)
        self.assertAlmostEqual(float(ndvi[1, 0]), 0.0, places=9)  # genuine zero, not sentinel path
        self.assertAlmostEqual(float(ndvi[1, 1]), 1.0, places=9)

    def test_shape_mismatch_raises(self):
        with self.assertRaises(ValueError):
            compute_ndvi(np.zeros((2, 2)), np.zeros((3, 3)))


class TestDecodeImages(unittest.TestCase):
    def test_decode_rgb8_round_trip(self):
        h, w = 2, 3
        # pixel (0,0)=red, (0,1)=green, (0,2)=blue, row 1 = mid-gray
        pixels = [
            [255, 0, 0], [0, 255, 0], [0, 0, 255],
            [10, 20, 30], [40, 50, 60], [70, 80, 90],
        ]
        data = bytes(v for px in pixels for v in px)
        arr = decode_rgb8(h, w, data)
        self.assertEqual(arr.shape, (2, 3, 3))
        self.assertEqual(list(arr[0, 0]), [255, 0, 0])
        self.assertEqual(list(arr[1, 2]), [70, 80, 90])

    def test_decode_mono16_round_trip(self):
        h, w = 2, 2
        vals = np.array([[100, 200], [30000, 65535]], dtype=np.uint16)
        arr = decode_mono16(h, w, vals.tobytes())
        self.assertEqual(arr.shape, (2, 2))
        self.assertEqual(int(arr[1, 1]), 65535)
        self.assertEqual(int(arr[0, 0]), 100)


class TestStalePairGuard(unittest.TestCase):
    def test_max_stamp_delta_matches_config_update_rate(self):
        # 0.25 / 5.0 Hz = 0.05s = 50ms, per ADR-007's amendment scaling rule.
        self.assertAlmostEqual(max_stamp_delta_s(5.0), 0.05, places=9)
        # ADR-007 amendment's own reference example: 10 Hz -> 25 ms.
        self.assertAlmostEqual(max_stamp_delta_s(10.0), 0.025, places=9)

    def _fuser(self):
        return NdviFuser(update_rate_hz=5.0, min_temp_k=270.0, max_temp_k=330.0,
                         resolution_k_per_count=0.01)

    def test_within_tolerance_pair_is_fused(self):
        fuser = self._fuser()
        red = np.full((2, 2), 128, dtype=np.uint8)
        nir = np.full((2, 2), 32100, dtype=np.uint16)  # canopy calibration point
        result = fuser.fuse(rgb_stamp_s=10.000, red_u8=red, nir_stamp_s=10.010, nir_u16=nir)
        self.assertTrue(result.accepted)
        self.assertEqual(result.reason, "ok")
        self.assertIsNotNone(result.ndvi)
        self.assertEqual(fuser.fused_count, 1)
        self.assertEqual(fuser.dropped_pair_count, 0)
        self.assertEqual(fuser.event_log[-1]["kind"], "fused")

    def test_exactly_at_boundary_is_accepted(self):
        """delta == max_delta_s exactly must be accepted (the guard is '> max', not '>= max') --
        pin the boundary behavior explicitly so it can't silently flip."""
        fuser = self._fuser()
        red = np.zeros((1, 1), dtype=np.uint8)
        nir = np.zeros((1, 1), dtype=np.uint16)
        result = fuser.fuse(rgb_stamp_s=0.0, red_u8=red, nir_stamp_s=fuser.max_delta_s, nir_u16=nir)
        self.assertTrue(result.accepted)

    def test_stale_pair_is_dropped_and_counted(self):
        """THE required explicit case: a stale NIR frame (delta > 25% of one frame period) must be
        DROPPED, never fused into a mispaired NDVI, and the dropped_pair_count must increment."""
        fuser = self._fuser()
        red = np.full((2, 2), 128, dtype=np.uint8)
        nir = np.full((2, 2), 32100, dtype=np.uint16)
        result = fuser.fuse(rgb_stamp_s=10.000, red_u8=red, nir_stamp_s=10.060,  # 60ms > 50ms bound
                            nir_u16=nir)
        self.assertFalse(result.accepted)
        self.assertEqual(result.reason, "stale_pair")
        self.assertIsNone(result.ndvi)
        self.assertEqual(fuser.dropped_pair_count, 1)
        self.assertEqual(fuser.fused_count, 0)
        self.assertEqual(fuser.event_log[-1]["kind"], "dropped_pair")
        self.assertEqual(fuser.event_log[-1]["dropped_pair_count"], 1)

    def test_dropped_pair_counter_accumulates_across_calls(self):
        fuser = self._fuser()
        red = np.zeros((1, 1), dtype=np.uint8)
        nir = np.zeros((1, 1), dtype=np.uint16)
        for i in range(3):
            fuser.fuse(rgb_stamp_s=float(i), red_u8=red, nir_stamp_s=float(i) + 1.0, nir_u16=nir)
        self.assertEqual(fuser.dropped_pair_count, 3)
        self.assertEqual(fuser.fused_count, 0)


class TestNdviFuserConfigValidation(unittest.TestCase):
    """Audit follow-up: nonsensical config must be rejected at construction, not fail silently
    downstream (max_temp_k <= min_temp_k -> zero/negative span -> NaN pixels in rescale_nir;
    update_rate_hz <= 0 -> ZeroDivisionError or a negative stale-pair bound that drops everything).
    The ValueError message must name the bad value so a misconfigured run is diagnosable from the
    traceback alone."""

    def test_rejects_max_temp_not_greater_than_min_temp(self):
        # equal (the exact silent-NaN path: span=0 -> 0/0 in rescale_nir) and inverted
        for bad_max in (270.0, 260.0):
            with self.assertRaises(ValueError) as ctx:
                NdviFuser(update_rate_hz=5.0, min_temp_k=270.0, max_temp_k=bad_max,
                          resolution_k_per_count=0.01)
            self.assertIn(str(bad_max), str(ctx.exception))  # must name the bad value

    def test_rejects_nonpositive_update_rate(self):
        for bad_rate in (0.0, -5.0):
            with self.assertRaises(ValueError) as ctx:
                NdviFuser(update_rate_hz=bad_rate, min_temp_k=270.0, max_temp_k=330.0,
                          resolution_k_per_count=0.01)
            self.assertIn(str(bad_rate), str(ctx.exception))  # must name the bad value

    def test_from_config_inherits_the_same_rejection(self):
        # from_config delegates to __init__, so a bad config dict must raise identically -- pin
        # that so a future from_config refactor can't bypass the guard.
        bad_cfg = {"camera": {"update_rate_hz": 5.0},
                   "thermal": {"min_temp_k": 330.0, "max_temp_k": 270.0,
                               "resolution_k_per_count": 0.01}}
        with self.assertRaises(ValueError):
            NdviFuser.from_config(bad_cfg)

    def test_minimal_valid_boundary_config_constructs(self):
        # just-valid boundary: max_temp_k barely above min_temp_k, tiny positive update rate --
        # must construct (the guards are strict >, not >=-with-margin).
        fuser = NdviFuser(update_rate_hz=0.001, min_temp_k=270.0, max_temp_k=270.001,
                          resolution_k_per_count=0.01)
        self.assertEqual(fuser.max_temp_k, 270.001)
        self.assertEqual(fuser.update_rate_hz, 0.001)


class TestNearestIndex(unittest.TestCase):
    def test_picks_closest(self):
        self.assertEqual(nearest_index(10.08, [9.9, 10.0, 10.1, 10.2]), 2)

    def test_empty_candidates_returns_none(self):
        self.assertIsNone(nearest_index(1.0, []))

    def test_tie_prefers_first_seen(self):
        self.assertEqual(nearest_index(10.0, [9.9, 10.1]), 0)


class TestPairAndFuseStream(unittest.TestCase):
    def _fuser(self):
        return NdviFuser(update_rate_hz=5.0, min_temp_k=270.0, max_temp_k=330.0,
                         resolution_k_per_count=0.01)

    def test_regular_stream_all_fused(self):
        red = np.full((1, 1), 100, dtype=np.uint8)
        nir = np.full((1, 1), 30000, dtype=np.uint16)
        rgb_frames = [StampedFrame(t, red) for t in (0.0, 0.2, 0.4, 0.6)]
        nir_frames = [StampedFrame(t + 0.005, nir) for t in (0.0, 0.2, 0.4, 0.6)]  # 5ms jitter
        fuser = self._fuser()
        results = pair_and_fuse_stream(rgb_frames, nir_frames, fuser)
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r.accepted for r in results))
        self.assertEqual(fuser.fused_count, 4)
        self.assertEqual(fuser.dropped_pair_count, 0)

    def test_a_stale_nir_frame_is_dropped_not_mispaired(self):
        """A single NIR frame drop mid-stream (e.g. a missed render) must not cause the surviving
        RGB frame to silently pair with a NIR frame from the WRONG period -- it must be dropped and
        counted instead. This is the exact scenario the ADR-007 amendment exists to prevent: at 5Hz
        (200ms period) losing one NIR frame pushes the nearest surviving match ~200ms away, far past
        the 50ms bound."""
        red = np.full((1, 1), 100, dtype=np.uint8)
        nir = np.full((1, 1), 30000, dtype=np.uint16)
        rgb_frames = [StampedFrame(t, red) for t in (0.0, 0.2, 0.4, 0.6)]
        # NIR frame at t=0.2 is MISSING (simulates a dropped render frame).
        nir_frames = [StampedFrame(t, nir) for t in (0.0, 0.4, 0.6)]
        fuser = self._fuser()
        results = pair_and_fuse_stream(rgb_frames, nir_frames, fuser)
        self.assertEqual(len(results), 4)
        self.assertTrue(results[0].accepted)   # rgb t=0.0 <-> nir t=0.0, delta=0
        self.assertFalse(results[1].accepted)  # rgb t=0.2 <-> nearest nir is t=0.0 or 0.4, delta=0.2s
        self.assertEqual(results[1].reason, "stale_pair")
        self.assertTrue(results[2].accepted)   # rgb t=0.4 <-> nir t=0.4, delta=0
        self.assertTrue(results[3].accepted)   # rgb t=0.6 <-> nir t=0.6, delta=0
        self.assertEqual(fuser.dropped_pair_count, 1)
        self.assertEqual(fuser.fused_count, 3)

    def test_empty_nir_stream_drops_every_rgb_frame(self):
        red = np.full((1, 1), 100, dtype=np.uint8)
        rgb_frames = [StampedFrame(t, red) for t in (0.0, 0.2)]
        fuser = self._fuser()
        results = pair_and_fuse_stream(rgb_frames, [], fuser)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(not r.accepted for r in results))
        self.assertTrue(all(r.reason == "no_nir_frames" for r in results))
        self.assertEqual(fuser.dropped_pair_count, 2)


class TestFuserStatsSideChannel(unittest.TestCase):
    """The counters' side-channel: ndvi_node writes it once a second, clip_recorder reads it once at
    finalize. Everything here is about the failure modes -- the reason it exists is that the
    heartbeat-only version could not tell a starved flight from a dead fuser (ADR-013 amendment 4),
    so 'absent' and 'frozen' must be as legible as 'fine'.
    """

    COUNTERS = {"fused_count": 48, "dropped_pair_count": 2, "red_frames": 664, "nir_frames": 660,
                "camera_info_frames": 664, "last_fused_stamp_sim_s": 253.4,
                "update_rate_hz": 5.0, "max_delta_s": 0.05, "sync_queue_size": 60}

    def test_round_trip_carries_every_counter(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stats.json"
            write_fuser_stats(self.COUNTERS, path)
            block = read_fuser_stats(path)
            self.assertTrue(block["present"])
            for key, value in self.COUNTERS.items():
                self.assertEqual(block[key], value, msg=key)
            self.assertEqual(block["source"], str(path))
            self.assertLess(block["stats_age_s"], FUSER_STATS_STALE_S)   # just written
            self.assertFalse(block["stats_stale"])

    def test_a_dead_fuser_keeps_its_last_numbers_and_is_marked_stale(self):
        """The mid-flight death: the counters are real, they are simply frozen. Reading them as
        current is how a starved run gets blamed on the recorder."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stats.json"
            write_fuser_stats(self.COUNTERS, path)
            written_at = json.loads(path.read_text())["wall_time_s"]

            fresh = read_fuser_stats(path, now_s=written_at + FUSER_STATS_STALE_S - 0.5)
            self.assertFalse(fresh["stats_stale"])

            dead = read_fuser_stats(path, now_s=written_at + 600.0)
            self.assertTrue(dead["stats_stale"])
            self.assertEqual(dead["fused_count"], 48)         # last known, not discarded
            self.assertAlmostEqual(dead["stats_age_s"], 600.0, places=2)
            self.assertEqual(dead["stats_stale_after_s"], FUSER_STATS_STALE_S)

    def test_missing_sidecar_is_absent_never_zeros(self):
        """A fabricated `fused_count: 0` would read as 'fusion produced nothing' -- the wrong
        diagnosis, indistinguishable from a real starve. Absence must say absent."""
        with tempfile.TemporaryDirectory() as td:
            block = read_fuser_stats(Path(td) / "never_written.json")
            self.assertFalse(block["present"])
            self.assertIn("no fuser stats sidecar", block["reason"])
            for key in ("fused_count", "red_frames", "nir_frames", "stats_age_s"):
                self.assertNotIn(key, block)

    def test_malformed_sidecar_is_absent_not_a_crash(self):
        with tempfile.TemporaryDirectory() as td:
            garbage = Path(td) / "garbage.json"
            garbage.write_text("{truncated mid-wri")
            self.assertFalse(read_fuser_stats(garbage)["present"])
            self.assertNotIn("fused_count", read_fuser_stats(garbage))

            wrong_shape = Path(td) / "list.json"           # valid JSON, not a stats payload
            wrong_shape.write_text("[1, 2, 3]")
            self.assertFalse(read_fuser_stats(wrong_shape)["present"])

            no_stamp = Path(td) / "no_stamp.json"          # counters but no staleness marker
            no_stamp.write_text(json.dumps(self.COUNTERS))
            block = read_fuser_stats(no_stamp)
            self.assertFalse(block["present"])             # unaged counters are not trustworthy
            self.assertIn("KeyError", block["reason"])

    def test_rewriting_replaces_in_place_and_leaves_no_debris(self):
        """The observable half of the atomic write (the indivisibility itself is os.replace's own
        POSIX guarantee, not something a single-threaded test can witness): the target is whole and
        current after a rewrite rather than appended to, and the pid-scoped temp file it landed
        through does not survive -- a 1 Hz writer that leaked one would litter the bind mount."""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "stats.json"
            write_fuser_stats({"fused_count": 1}, path)
            write_fuser_stats({"fused_count": 2}, path)
            self.assertEqual(read_fuser_stats(path)["fused_count"], 2)   # replaced, not appended
            self.assertEqual([p.name for p in Path(td).iterdir()], ["stats.json"])

    def test_an_unwritable_sidecar_never_takes_the_flight_down(self):
        """Both ways the write can fail, from a callback whose exceptions would kill the node."""
        with tempfile.TemporaryDirectory() as td:
            blocker = Path(td) / "not_a_dir"
            blocker.write_text("a file where the stats directory would have to be")
            path = blocker / "stats.json"
            write_fuser_stats(self.COUNTERS, path)          # must not raise (OSError)
            self.assertFalse(read_fuser_stats(path)["present"])

            # ...and an unserialisable counter. The live way in is a numpy-typed one -- np.int64 is
            # not JSON-serialisable, numpy is everywhere in this package, and the obvious next
            # counter to add (`zero_denom_count`) is computed by it.
            unserialisable = Path(td) / "stats.json"
            write_fuser_stats({"fused_count": np.int64(5)}, unserialisable)   # must not raise
            self.assertFalse(read_fuser_stats(unserialisable)["present"])     # absent, not corrupt


class TestNdviPreviewColormap(unittest.TestCase):
    def test_low_mid_high_spot_checks(self):
        ndvi = np.array([[-1.0, 0.0, 1.0]])
        preview = ndvi_to_preview_rgb(ndvi)
        self.assertEqual(preview.shape, (1, 3, 3))
        self.assertEqual(list(preview[0, 0]), [255, 0, 0])   # ndvi=-1 -> red
        self.assertEqual(list(preview[0, 1]), [255, 255, 0])  # ndvi=0 -> yellow
        self.assertEqual(list(preview[0, 2]), [0, 255, 0])   # ndvi=+1 -> green


if __name__ == "__main__":
    unittest.main()
