"""Tests for clip_recorder — the live-flight recorder's pure core (ClipWriter + PoseBuffer).

The one that matters most: `test_written_clip_is_stitchable` closes the recorder->stitcher
contract by feeding a ClipWriter-produced clip STRAIGHT into scripts/stitch_ndvi.stitch_clip —
if the two ever drift (schema keys, path layout, quat order), that test fails, not the one
scarce Docker recording session. PoseBuffer is the burst-proof stamp pairing that replaced
arrival pairing after the 2026-08-18 flight mislabeled every canopy frame (0/18 trees showed).
numpy allowed (ndvi_* module family).
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from fieldguard_planning.clip_recorder import (  # noqa: E402
    AIRBORNE_Z_M, ClipWriter, PoseBuffer, RecorderCounters, SCHEMA_VERSION, STALE_PAIR_BOUND_S,
    StreamingClockParser, nearest_rank_p95,
)
from fieldguard_planning.ndvi_fusion import write_fuser_stats  # noqa: E402
from fieldguard_planning.coverage import build_grid, load_field_polygon  # noqa: E402
import stitch_ndvi  # noqa: E402

CAM = {"image_width_px": 64, "image_height_px": 48, "fx": 52.0, "fy": 52.0, "cx": 32.0, "cy": 24.0}
IDENTITY_XYZW = (0.0, 0.0, 0.0, 1.0)


class TestStreamingClockParser(unittest.TestCase):
    """The native gz clock stream parser (replaced the bridged /fg/gz_clock topic, which at ~350
    msgs/s starved the image pipeline — measured live 2026-08-18)."""

    def test_full_message_stream(self):
        p = StreamingClockParser()
        lines = ["system {", "  sec: 1", "}", "real {", "  sec: 99", "  nsec: 5", "}",
                 "sim {", "  sec: 123", "  nsec: 500000000", "}", ""]
        out = [t for t in (p.feed(l) for l in lines) if t is not None]
        self.assertEqual(out, [123.5])

    def test_consecutive_messages(self):
        p = StreamingClockParser()
        stream = ["sim {", "  sec: 10", "  nsec: 0", "}", "sim {", "  sec: 11", "  nsec: 250000000", "}"]
        out = [t for t in (p.feed(l) for l in stream) if t is not None]
        self.assertEqual(out, [10.0, 11.25])

    def test_sim_block_without_nsec(self):
        p = StreamingClockParser()
        out = [t for t in (p.feed(l) for l in ["sim {", "  sec: 42", "}"]) if t is not None]
        self.assertEqual(out, [42.0])

    def test_non_sim_blocks_yield_nothing(self):
        p = StreamingClockParser()
        out = [t for t in (p.feed(l) for l in ["real {", "  sec: 9", "}"]) if t is not None]
        self.assertEqual(out, [])


class TestPoseBuffer(unittest.TestCase):
    def test_nearest_picks_closest_gz_tag(self):
        b = PoseBuffer()
        b.tag(10.0, (0, 0, 15), IDENTITY_XYZW)
        b.tag(10.5, (1, 0, 15), IDENTITY_XYZW)
        b.tag(11.0, (2, 0, 15), IDENTITY_XYZW)
        pos, quat, residual = b.nearest(10.6)
        self.assertEqual(pos, (1, 0, 15))
        self.assertAlmostEqual(residual, -0.1)  # tag(10.5) - stamp(10.6): pose from BEFORE frame

    def test_burst_scenario_pairs_old_frame_with_old_pose(self):
        """The exact 2026-08-18 failure: a render burst delivers a frame stamped seconds ago.
        Arrival pairing grabbed the CURRENT pose; stamp pairing must reach back to the pose
        tagged near the frame's render time."""
        b = PoseBuffer()
        for i in range(60):  # drone flying north at 3 m/s, poses tagged every 0.1 sim-s
            b.tag(100.0 + i * 0.1, (15.0, 5.0 + i * 0.3, 15.0), IDENTITY_XYZW)
        # frame rendered at t=101.0 (drone was at y=8.0), arriving late at t=106.0
        pos, _, residual = b.nearest(101.0)
        self.assertAlmostEqual(pos[1], 8.0)         # y at render time, NOT y=23 (current)
        self.assertAlmostEqual(residual, 0.0)

    def test_empty_buffer_returns_none(self):
        self.assertIsNone(PoseBuffer().nearest(1.0))

    def test_maxlen_bounds_memory(self):
        b = PoseBuffer(maxlen=10)
        for i in range(25):
            b.tag(float(i), (i, 0, 15), IDENTITY_XYZW)
        self.assertEqual(len(b), 10)
        self.assertIsNotNone(b.nearest(24.0))


class TestClipWriter(unittest.TestCase):
    def test_written_clip_is_stitchable(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM, mount_offset_body_m=(0.0, 0.0, 0.0))
            ndvi = np.full((48, 64), 0.7, dtype=np.float32)
            w.add_frame(100.0, ndvi, (40.0, 20.0, 15.0), IDENTITY_XYZW, pose_pair_residual_s=0.02)
            w.add_frame(100.2, ndvi, (41.0, 20.0, 15.0), IDENTITY_XYZW, pose_pair_residual_s=0.01)
            summary = w.finalize()
            self.assertEqual(summary["n_frames"], 2)

            grid, stats = stitch_ndvi.stitch_clip(Path(td), build_grid(load_field_polygon()))
            self.assertEqual(stats["frames_total"], 2)
            self.assertFalse(stats["clip_synthetic"])          # the real thing at last
            self.assertEqual(stats["frames_stale_pose_skipped"], [])
            means = grid.mean_grid()
            cell = min(grid.cells, key=lambda c: (c.cx_m - 40.5) ** 2 + (c.cy_m - 20.0) ** 2)
            self.assertAlmostEqual(means[cell.cell_id], 0.7, places=5)

    def test_stale_pose_pair_is_flagged_and_stitch_skips_it(self):
        """A residual beyond bound flags the frame; the stitch must SKIP it, not paint it —
        the exact plausible-but-wrong mode the first real flight produced."""
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            good = np.full((48, 64), 0.2, dtype=np.float32)
            bad = np.full((48, 64), 0.9, dtype=np.float32)   # would poison the mean if painted
            w.add_frame(10.0, good, (40.0, 20.0, 15.0), IDENTITY_XYZW, pose_pair_residual_s=0.05)
            w.add_frame(10.2, bad, (40.0, 20.0, 15.0), IDENTITY_XYZW,
                        pose_pair_residual_s=STALE_PAIR_BOUND_S + 1.0)
            s = w.finalize()
            self.assertEqual(s["n_frames"], 2)

            lines = [json.loads(x) for x in (Path(td) / "poses.jsonl").read_text().splitlines()]
            self.assertNotIn("pose_pair_stale", lines[0])
            self.assertTrue(lines[1]["pose_pair_stale"])
            meta = json.loads((Path(td) / "meta.json").read_text())
            self.assertEqual(meta["num_stale_pose_pairs"], 1)

            grid, stats = stitch_ndvi.stitch_clip(Path(td), build_grid(load_field_polygon()))
            self.assertEqual(stats["frames_stale_pose_skipped"], [1])
            cell = min(grid.cells, key=lambda c: (c.cx_m - 40.0) ** 2 + (c.cy_m - 20.0) ** 2)
            self.assertAlmostEqual(grid.mean_grid()[cell.cell_id], 0.2, places=5)  # only the good frame

    def test_quat_conversion_xyzw_to_wxyz(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            w.add_frame(0.0, np.zeros((48, 64), np.float32),
                        (0.0, 0.0, 15.0), IDENTITY_XYZW, pose_pair_residual_s=0.0)
            w.finalize()
            line = json.loads((Path(td) / "poses.jsonl").read_text().splitlines()[0])
            self.assertEqual(line["drone"]["quat_wxyz"], [1.0, 0.0, 0.0, 0.0])  # w first

    def test_t_s_relative_and_honesty_extras(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            z = np.zeros((48, 64), np.float32)
            w.add_frame(500.0, z, (0, 0, 15.0), IDENTITY_XYZW, pose_pair_residual_s=0.11,
                        frame_age_sim_s=2.5)
            w.add_frame(500.2, z, (1, 0, 15.0), IDENTITY_XYZW, pose_pair_residual_s=-0.02)
            w.finalize()
            lines = [json.loads(s) for s in (Path(td) / "poses.jsonl").read_text().splitlines()]
            self.assertEqual([ln["t_s"] for ln in lines], [0.0, 0.2])
            self.assertEqual(lines[0]["stamp_sim_s"], 500.0)      # absolute stamp kept for audit
            self.assertEqual(lines[0]["pose_pair_residual_s"], 0.11)
            self.assertEqual(lines[0]["frame_age_sim_s"], 2.5)    # burst delay, quantified
            self.assertNotIn("frame_age_sim_s", lines[1])

    def test_nan_residual_serializes_as_null(self):
        """Arrival-fallback mode (no gz clock) has no residual — must be JSON null, never NaN."""
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            w.add_frame(0.0, np.zeros((48, 64), np.float32), (0, 0, 15.0), IDENTITY_XYZW,
                        pose_pair_residual_s=float("nan"))
            w.finalize()
            raw = (Path(td) / "poses.jsonl").read_text()
            self.assertNotIn("NaN", raw)
            line = json.loads(raw.splitlines()[0])
            self.assertIsNone(line["pose_pair_residual_s"])
            self.assertNotIn("pose_pair_stale", line)  # unknowable, not flagged

    def test_rgb_raw_in_flight_png_at_finalize(self):
        """RGB saves as raw .npy per frame (fast path); PNGs appear only at finalize, and the
        raw dir is cleaned away."""
        calls = []
        with tempfile.TemporaryDirectory() as td:
            def stub_png(path, arr):
                Path(path).write_bytes(b"png")
                calls.append((Path(path).name, arr.shape))
            w = ClipWriter(Path(td), CAM, png_writer=stub_png)
            z = np.zeros((48, 64), np.float32)
            w.add_frame(0.0, z, (0, 0, 15.0), IDENTITY_XYZW, 0.0,
                        rgb=np.zeros((48, 64, 3), np.uint8))
            self.assertEqual(calls, [])                                    # nothing during flight
            self.assertTrue((Path(td) / "frames/rgb_raw/frame_000000.npy").exists())
            w.add_frame(0.2, z, (1, 0, 15.0), IDENTITY_XYZW, 0.0)          # no rgb this frame
            s = w.finalize()
            self.assertEqual(s["n_rgb"], 1)
            self.assertEqual(calls, [("frame_000000.png", (48, 64, 3))])   # converted at finalize
            self.assertFalse((Path(td) / "frames/rgb_raw").exists())       # raw cleaned up
            lines = [json.loads(x) for x in (Path(td) / "poses.jsonl").read_text().splitlines()]
            self.assertEqual(lines[0]["rgb_path"], "frames/rgb/frame_000000.png")
            self.assertNotIn("rgb_path", lines[1])

    def test_no_png_writer_skips_rgb(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM, png_writer=None)
            w.add_frame(0.0, np.zeros((48, 64), np.float32), (0, 0, 15.0), IDENTITY_XYZW, 0.0,
                        rgb=np.zeros((48, 64, 3), np.uint8))  # rgb passed but no writer -> skipped
            s = w.finalize()
            self.assertEqual(s["n_rgb"], 0)
            self.assertFalse((Path(td) / "frames" / "rgb").exists())

    def test_meta_carries_the_fuser_counters(self):
        """Schema 1.2: the clip records WHERE the pipeline starved. 664 red frames in, 48 fused,
        2 recorded says 'the recorder lost them'; 664 in, 3 fused says 'pairing starved' -- the
        distinction the 2 Hz run had to guess at (ADR-013 amendments 4-5)."""
        with tempfile.TemporaryDirectory() as td:
            stats = Path(td) / "ndvi_fuser_stats.json"
            write_fuser_stats({"fused_count": 48, "dropped_pair_count": 2, "red_frames": 664,
                               "nir_frames": 660, "camera_info_frames": 664,
                               "last_fused_stamp_sim_s": 253.4}, stats)
            out = Path(td) / "clip"
            w = ClipWriter(out, CAM, fuser_stats_path=stats)
            w.add_frame(0.0, np.zeros((48, 64), np.float32), (0, 0, 15.0), IDENTITY_XYZW, 0.0)
            summary = w.finalize()

            meta = json.loads((out / "meta.json").read_text())
            self.assertEqual(meta["schema_version"], SCHEMA_VERSION)
            fuser = meta["fuser"]
            self.assertTrue(fuser["present"])
            self.assertEqual(fuser["fused_count"], 48)
            self.assertEqual(fuser["dropped_pair_count"], 2)
            self.assertEqual((fuser["red_frames"], fuser["nir_frames"]), (664, 660))
            self.assertEqual(fuser["last_fused_stamp_sim_s"], 253.4)
            self.assertFalse(fuser["stats_stale"])
            self.assertEqual(meta["num_frames"], 1)      # the recorder-side half of the comparison
            self.assertIn("fused_count=48", summary["fuser"])   # printed at Ctrl-C

    def test_meta_marks_a_missing_fuser_absent_and_finalize_still_writes(self):
        """A clip recorded with no fusion node (or one that never published) must finalize
        normally and say so -- zeros here would read as 'fusion produced nothing'."""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "clip"
            w = ClipWriter(out, CAM, fuser_stats_path=Path(td) / "never_written.json")
            w.add_frame(0.0, np.zeros((48, 64), np.float32), (0, 0, 15.0), IDENTITY_XYZW, 0.0)
            summary = w.finalize()

            meta = json.loads((out / "meta.json").read_text())
            self.assertEqual(meta["num_frames"], 1)             # the clip itself is unaffected
            self.assertFalse(meta["fuser"]["present"])
            self.assertNotIn("fused_count", meta["fuser"])
            self.assertIn("no fuser stats sidecar", meta["fuser"]["reason"])
            self.assertIn("no fuser stats sidecar", summary["fuser"])

    def test_meta_marks_a_fuser_that_died_mid_flight_stale(self):
        with tempfile.TemporaryDirectory() as td:
            stats = Path(td) / "ndvi_fuser_stats.json"
            write_fuser_stats({"fused_count": 3, "red_frames": 240, "nir_frames": 238}, stats)
            frozen = json.loads(stats.read_text())
            frozen["wall_time_s"] -= 900.0                      # died 15 minutes into the flight
            stats.write_text(json.dumps(frozen))

            out = Path(td) / "clip"
            w = ClipWriter(out, CAM, fuser_stats_path=stats)
            w.add_frame(0.0, np.zeros((48, 64), np.float32), (0, 0, 15.0), IDENTITY_XYZW, 0.0)
            summary = w.finalize()

            fuser = json.loads((out / "meta.json").read_text())["fuser"]
            self.assertTrue(fuser["stats_stale"])
            self.assertGreater(fuser["stats_age_s"], 890.0)
            self.assertEqual(fuser["fused_count"], 3)           # last known, labelled as frozen
            self.assertIn("STALE", summary["fuser"])

class TestNearestRankP95(unittest.TestCase):
    def test_no_samples_is_none_not_zero(self):
        """'the callback never ran' and 'the callback always returned instantly' are opposite
        diagnoses of a thin clip; 0.0 would merge them."""
        self.assertIsNone(nearest_rank_p95([]))

    def test_single_sample_is_that_sample(self):
        self.assertEqual(nearest_rank_p95([7.5]), 7.5)

    def test_nearest_rank_picks_a_value_a_callback_actually_took(self):
        # 100 samples 1..100: ceil(0.95*100) = 95 -> the 95th smallest.
        self.assertEqual(nearest_rank_p95([float(i) for i in range(1, 101)]), 95.0)

    def test_order_of_arrival_does_not_matter(self):
        self.assertEqual(nearest_rank_p95([9.0, 1.0, 5.0]), nearest_rank_p95([1.0, 5.0, 9.0]))

    def test_twenty_samples_never_indexes_past_the_end(self):
        for n in range(1, 25):
            self.assertIsNotNone(nearest_rank_p95([float(i) for i in range(n)]))


class TestRecorderCounters(unittest.TestCase):
    """The stage that had NO counter until 2026-08-21: 180 of the demo take's 634 fused frames
    vanished between publish and poses.jsonl with nothing in any artifact to attribute them."""

    def test_a_fresh_counter_reports_real_zeros_and_absent_timings(self):
        m = RecorderCounters().to_meta()
        self.assertTrue(m["present"])
        self.assertEqual(m["ndvi_msgs_received"], 0)      # a real measurement: nothing arrived
        self.assertEqual(m["rgb_msgs_received"], 0)
        self.assertEqual(m["dropped_no_writer"], 0)
        self.assertEqual(m["dropped_no_pose"], 0)
        self.assertIsNone(m["on_ndvi_wall_ms_p95"])       # absence: no callback was ever timed
        self.assertIsNone(m["on_ndvi_wall_ms_max"])
        self.assertEqual(m["on_ndvi_wall_ms_n"], 0)

    def test_the_attribution_arithmetic_closes(self):
        """The whole point: received - written - no_writer - no_pose is the loss that is NOT the
        recorder's own logic, and (fused - received) is the transport hop."""
        c = RecorderCounters()
        for _ in range(100):
            c.ndvi_msgs_received += 1
        c.dropped_no_writer += 4
        c.dropped_no_pose += 6
        written = 90
        m = c.to_meta()
        self.assertEqual(m["ndvi_msgs_received"] - written - m["dropped_no_writer"]
                         - m["dropped_no_pose"], 0)

    def test_wall_ms_p95_and_max_track_the_distribution(self):
        c = RecorderCounters()
        for v in list(range(1, 100)) + [900.0]:
            c.observe_on_ndvi_wall_ms(float(v))
        m = c.to_meta()
        self.assertEqual(m["on_ndvi_wall_ms_max"], 900.0)
        self.assertEqual(m["on_ndvi_wall_ms_n"], 100)
        self.assertLess(m["on_ndvi_wall_ms_p95"], 900.0)   # one outlier must not become the p95

    def test_max_survives_a_truncated_percentile_window(self):
        """p95 is over the most recent window; max is over the WHOLE flight. A blocking write early
        in a long flight must still be visible."""
        c = RecorderCounters(wall_ms_window=10)
        c.observe_on_ndvi_wall_ms(500.0)
        for _ in range(50):
            c.observe_on_ndvi_wall_ms(1.0)
        m = c.to_meta()
        self.assertEqual(m["on_ndvi_wall_ms_max"], 500.0)
        self.assertEqual(m["on_ndvi_wall_ms_p95"], 1.0)
        self.assertEqual(m["on_ndvi_wall_ms_n"], 51)       # total observed, not window size
        self.assertEqual(m["on_ndvi_wall_ms_window"], 10)

    def test_every_value_is_a_plain_json_type_even_from_numpy_inputs(self):
        """json.dumps(np.int64) raises TypeError. This dict is written inside the recorder's
        finalize; a raise there loses the clip the flight was flown for."""
        c = RecorderCounters()
        c.ndvi_msgs_received = np.int64(634)
        c.rgb_msgs_received = np.int32(217)
        c.observe_on_ndvi_wall_ms(np.float32(12.5))
        m = c.to_meta()
        for k, v in m.items():
            self.assertIn(type(v), (int, float, bool, str, type(None)), msg=f"{k} is {type(v)}")
        self.assertEqual(json.loads(json.dumps(m))["ndvi_msgs_received"], 634)


class TestAirborneSummary(unittest.TestCase):
    """The round's target metric, made readable off the artifact instead of re-derived by hand from
    poses.jsonl (which is how the demo take's 0.407 Hz was produced)."""

    def _writer(self, td):
        return ClipWriter(Path(td), CAM)

    def _add(self, w, stamp, z):
        w.add_frame(stamp, np.zeros((48, 64), np.float32), (0.0, 0.0, z), IDENTITY_XYZW, 0.0)

    def test_reproduces_the_demo_takes_53_of_454_split_and_its_published_cadence(self):
        """Fixture from eval/results/clips/real_flight_20260821T045848Z: 401 frames parked at
        (0,0,-0.0) around a contiguous run of 53 airborne frames spanning sim 430.8 -> 558.6 s, and
        the 0.407 Hz that ADR-003 amendment 2 and ADR-015 are both quoted against."""
        with tempfile.TemporaryDirectory() as td:
            w = self._writer(td)
            for i in range(274):                                   # pre-arm, parked at home
                self._add(w, 10.2 + i * 1.5, -0.0)
            for i in range(53):                                    # airborne
                self._add(w, 430.8 + i * (127.8 / 52.0), 2.87 + i * 0.2)
            for i in range(127):                                   # post-land, parked again
                self._add(w, 560.0 + i * 2.2, -0.0)
            summary = w.finalize()
            meta = json.loads((Path(td) / "meta.json").read_text())

            air = meta["airborne"]
            self.assertEqual(air["frames"], 53)
            self.assertEqual(air["frames_total"], 454)
            self.assertEqual(air["span_s"], 127.8)
            self.assertAlmostEqual(air["cadence_hz"], 0.407, places=3)
            self.assertEqual(air["z_threshold_m"], AIRBORNE_Z_M)
            self.assertEqual(summary["n_airborne"], 53)
            self.assertAlmostEqual(summary["airborne_cadence_hz"], 0.407, places=3)

    def test_a_clip_flown_entirely_on_the_ground_reports_zero_frames_and_no_cadence(self):
        """Zero airborne frames is a real measurement; a cadence over them is not. None, not 0.0 --
        a rate with no denominator is EVIDENCE INSUFFICIENT."""
        with tempfile.TemporaryDirectory() as td:
            w = self._writer(td)
            for i in range(5):
                self._add(w, float(i), 0.0)
            w.finalize()
            air = json.loads((Path(td) / "meta.json").read_text())["airborne"]
            self.assertEqual(air["frames"], 0)
            self.assertIsNone(air["cadence_hz"])
            self.assertIsNone(air["span_s"])
            self.assertIsNone(air["first_stamp_sim_s"])

    def test_one_airborne_frame_has_no_cadence(self):
        with tempfile.TemporaryDirectory() as td:
            w = self._writer(td)
            self._add(w, 100.0, 15.0)
            w.finalize()
            air = json.loads((Path(td) / "meta.json").read_text())["airborne"]
            self.assertEqual(air["frames"], 1)
            self.assertEqual(air["span_s"], 0.0)
            self.assertIsNone(air["cadence_hz"])

    def test_the_threshold_is_on_magnitude_so_a_negative_down_axis_still_counts(self):
        """Telemetry frame_ids lie (ADR-005) and a sign flip upstream would otherwise silently
        report a whole flight as parked."""
        with tempfile.TemporaryDirectory() as td:
            w = self._writer(td)
            self._add(w, 0.0, -15.0)
            self._add(w, 1.0, 15.0)
            w.finalize()
            self.assertEqual(json.loads((Path(td) / "meta.json").read_text())["airborne"]["frames"],
                             2)

    def test_a_frame_exactly_at_the_threshold_is_not_airborne(self):
        with tempfile.TemporaryDirectory() as td:
            w = self._writer(td)
            self._add(w, 0.0, AIRBORNE_Z_M)
            w.finalize()
            self.assertEqual(json.loads((Path(td) / "meta.json").read_text())["airborne"]["frames"],
                             0)

    def test_the_airborne_window_is_the_span_not_the_clip(self):
        """Frames recorded after landing must not stretch the denominator -- that is exactly how a
        whole-clip 0.547 Hz gets quoted where the comparable number is 0.407."""
        with tempfile.TemporaryDirectory() as td:
            w = self._writer(td)
            self._add(w, 0.0, 0.0)
            self._add(w, 10.0, 15.0)
            self._add(w, 20.0, 15.0)
            self._add(w, 900.0, 0.0)
            w.finalize()
            air = json.loads((Path(td) / "meta.json").read_text())["airborne"]
            self.assertEqual(air["span_s"], 10.0)
            self.assertEqual(air["cadence_hz"], 0.1)


class TestMetaRecorderBlock(unittest.TestCase):
    def test_meta_carries_the_recorder_counters(self):
        with tempfile.TemporaryDirectory() as td:
            c = RecorderCounters()
            c.ndvi_msgs_received = 600
            c.rgb_msgs_received = 900
            c.dropped_no_writer = 3
            c.dropped_no_pose = 1
            c.observe_on_ndvi_wall_ms(42.0)
            w = ClipWriter(Path(td), CAM)
            w.add_frame(0.0, np.zeros((48, 64), np.float32), (0, 0, 15.0), IDENTITY_XYZW, 0.0)
            w.finalize(recorder_counters=c.to_meta())

            rec = json.loads((Path(td) / "meta.json").read_text())["recorder"]
            self.assertTrue(rec["present"])
            self.assertEqual(rec["ndvi_msgs_received"], 600)
            self.assertEqual(rec["rgb_msgs_received"], 900)
            self.assertEqual((rec["dropped_no_writer"], rec["dropped_no_pose"]), (3, 1))
            self.assertEqual(rec["on_ndvi_wall_ms_max"], 42.0)

    def test_a_clip_finalized_without_counters_says_absent_and_fabricates_nothing(self):
        """Same rule as the fuser block: a fabricated ndvi_msgs_received: 0 is indistinguishable
        from a recorder whose subscription never fired."""
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            w.add_frame(0.0, np.zeros((48, 64), np.float32), (0, 0, 15.0), IDENTITY_XYZW, 0.0)
            w.finalize()
            rec = json.loads((Path(td) / "meta.json").read_text())["recorder"]
            self.assertFalse(rec["present"])
            self.assertNotIn("ndvi_msgs_received", rec)
            self.assertIn("reason", rec)

    def test_the_fuser_and_recorder_blocks_are_independent(self):
        """A dead fuser must not take the recorder's numbers with it, and vice versa -- they are
        the two halves of the attribution."""
        with tempfile.TemporaryDirectory() as td:
            c = RecorderCounters()
            c.ndvi_msgs_received = 7
            w = ClipWriter(Path(td) / "clip", CAM,
                           fuser_stats_path=Path(td) / "never_written.json")
            w.add_frame(0.0, np.zeros((48, 64), np.float32), (0, 0, 15.0), IDENTITY_XYZW, 0.0)
            w.finalize(recorder_counters=c.to_meta())
            meta = json.loads((Path(td) / "clip" / "meta.json").read_text())
            self.assertFalse(meta["fuser"]["present"])
            self.assertTrue(meta["recorder"]["present"])
            self.assertEqual(meta["recorder"]["ndvi_msgs_received"], 7)


class TestMetaHonesty(unittest.TestCase):
    def test_meta_honesty_fields(self):
        with tempfile.TemporaryDirectory() as td:
            w = ClipWriter(Path(td), CAM)
            w.origin = {"x": 1.0, "y": 2.0, "z": 3.0, "note": "PoseStamped passthrough",
                        "lat_deg?": None}
            w.add_frame(0.0, np.zeros((48, 64), np.float32), (0, 0, 15.0), IDENTITY_XYZW, 0.0)
            w.finalize()
            meta = json.loads((Path(td) / "meta.json").read_text())
            self.assertFalse(meta["synthetic"])
            self.assertFalse(meta["pending_gazebo_replacement"])
            self.assertEqual(meta["camera"]["fx"], 52.0)
            self.assertIn("clock_note", meta)
            self.assertEqual(meta["pose_pairing"], "gz_clock_stamp")
            self.assertEqual(meta["stale_pair_bound_s"], STALE_PAIR_BOUND_S)
            self.assertEqual(meta["gps_global_origin"]["x"], 1.0)


if __name__ == "__main__":
    unittest.main()
