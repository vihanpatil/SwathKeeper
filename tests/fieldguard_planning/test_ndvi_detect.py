"""Regression pins for the ADOPTED detector core (src/fieldguard_planning/ndvi_detect.py).

ADR-003 amendment 7 adopted a MEASUREMENT, and the measurement belongs to this exact code:
precision 0.708 / recall 0.850 / frame FNR 0.150 / per-bird-track FNR 0.000 over 20 visible
bird-frames, on `eval/results/clips/real_flight_20260823T073644Z` at thresh -0.61, min_area 6,
max_area 5000. Now that the same code also flies (the live `detection_source` seam imports this
module, not a copy), an edit that silently changes a box changes what the drone dodges. So this
file makes boxes a pinned output, from three independent directions:

  1. HAND-DERIVED SEMANTICS -- every expected box below was worked out from the algorithm
     (erode-then-dilate with a 4-connected cross, dilate-then-erode, 8-connected labelling,
     area filter on the POST-morphology component) BEFORE running it, so a change in scipy's
     behaviour or in this module's wiring fails a number, not just a self-consistency check.
  2. THE REAL RENDER, IN GIT -- `fixtures/ndvi_detect_real_frames.npz` carries three float32 NDVI
     frames copied verbatim out of the adopted clip, and the expected boxes are read from the
     COMMITTED artifact `eval/results/adr003_20260823/detections_ndvi.json` rather than retyped.
     The pin's source of truth is therefore the evidence the ADR cites. The fixture cannot be a
     hand-tuned array that happens to produce the right boxes: when the clip is present on the
     host, `test_fixture_frames_are_verbatim_copies_of_the_clip` compares them element-wise to the
     clip's own `.npy` files.
  3. THE WHOLE CLIP -- when the (gitignored) 1256-frame clip is on disk, the full offline pipeline
     must reproduce the committed artifact bit-identically. Skipped where the frames are absent
     (CI), which is why 1 and 2 exist.

FIXTURE PROVENANCE. Frames 610 (empty mask), 613 (two components, the clip's largest at 1781 px)
and 679 (morphology-active -- 743 raw mask px open/close down to 722 -- and the clip's smallest
accepted component at 94 px, sitting one pixel from the left and bottom borders, which is as close
to the edge as this detector can ever report) of
`eval/results/clips/real_flight_20260823T073644Z`. Regenerate with:

    python3 -c "import json,numpy as np;from pathlib import Path;\
c=Path('eval/results/clips/real_flight_20260823T073644Z');\
p={json.loads(l)['frame_id']:json.loads(l) for l in (c/'poses.jsonl').read_text().splitlines()};\
np.savez_compressed('tests/fieldguard_planning/fixtures/ndvi_detect_real_frames.npz',\
**{f'frame_{i}':np.load(c/p[i]['ndvi_path']) for i in (610,613,679)})"

numpy + scipy, same convention as test_ndvi_fusion.py: imported unconditionally because CI installs
requirements-eval.txt before the suite runs.
"""
import json
import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

from fieldguard_planning import ndvi_detect  # noqa: E402
from fieldguard_planning.ndvi_detect import (  # noqa: E402
    DEFAULT_MAX_AREA,
    DEFAULT_MIN_AREA,
    REAL_RENDER_THRESH,
    SYNTHETIC_THRESH,
    detect_blobs,
    detect_ndvi,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ndvi_detect_real_frames.npz"
ADOPTED = REPO_ROOT / "eval" / "results" / "adr003_20260823" / "detections_ndvi.json"
CLIP = REPO_ROOT / "eval" / "results" / "clips" / "real_flight_20260823T073644Z"
GATE2 = REPO_ROOT / "eval" / "results" / "gate2_summary.json"
FIXTURE_FRAME_IDS = (610, 613, 679)


def blank(shape=(40, 60)):
    return np.zeros(shape, dtype=bool)


def adopted_artifact():
    return json.loads(ADOPTED.read_text())


class TestDetectBlobsSemantics(unittest.TestCase):
    """Hand-derived pins on the shared blob machinery. Shapes are placed away from the array border
    so nothing here depends on scipy's edge handling -- the real-render fixture covers edges."""

    def test_box_is_half_open_and_x_is_the_column(self):
        """A solid 5x5 at rows 10-14 / cols 20-24. Opening erodes it to its 3x3 interior and
        dilates that back to a plus-thickened 5x5 (the four corners do not come back: their
        outward neighbours are never in the dilation, so closing cannot restore them either).
        Row and column EXTENT survive, so the box is the original square's, half-open:
        [x0=20, y0=10, x1=25, y1=15] -- x1-x0 = 5 is the column count, not an inclusive index."""
        mask = blank()
        mask[10:15, 20:25] = True
        self.assertEqual(detect_blobs(mask, 1, 10000), [[20.0, 10.0, 25.0, 15.0]])

    def test_area_filter_counts_the_post_morphology_component_not_the_raw_mask(self):
        """Same 5x5: 25 raw pixels, 21 after the corners erode away. min_area 21 keeps it and 22
        drops it -- which is only true if the count happens AFTER open/close. This matters live: a
        bird thinned by morphology is a bird that has to clear min_area at its thinned size."""
        mask = blank()
        mask[10:15, 20:25] = True
        self.assertEqual(detect_blobs(mask, 21, 10000), [[20.0, 10.0, 25.0, 15.0]])
        self.assertEqual(detect_blobs(mask, 22, 10000), [])

    def test_opening_deletes_a_single_pixel_speck(self):
        """The whole point of the open step: one hot pixel is sensor noise, not a bird. With
        open_iter=0 it survives, so this pins the morphology and not the area filter."""
        mask = blank()
        mask[7, 9] = True
        self.assertEqual(detect_blobs(mask, 1, 10000), [])
        self.assertEqual(detect_blobs(mask, 1, 10000, open_iter=0, close_iter=0),
                         [[9.0, 7.0, 10.0, 8.0]])

    def test_closing_fills_a_one_pixel_hole(self):
        """5x5 with the centre pixel missing: 24 raw pixels, 25 after closing. min_area 25 passes
        only with close_iter=1, so this pins that closing ran AND that it fed the area count."""
        mask = blank()
        mask[10:15, 20:25] = True
        mask[12, 22] = False
        self.assertEqual(detect_blobs(mask, 25, 10000, open_iter=0, close_iter=1),
                         [[20.0, 10.0, 25.0, 15.0]])
        self.assertEqual(detect_blobs(mask, 25, 10000, open_iter=0, close_iter=0), [])
        self.assertEqual(detect_blobs(mask, 24, 10000, open_iter=0, close_iter=0),
                         [[20.0, 10.0, 25.0, 15.0]])

    def test_labelling_is_8_connected_so_a_diagonal_touch_is_one_bird(self):
        """Two pixels touching only at a corner label as ONE component, box [5,5,7,7]. Under
        4-connected labelling they would be two boxes -- i.e. one bird counted twice, two dodges
        argued for. Deliberate: the label structure is 8-conn while the morphology structure is
        the 4-conn cross, and neither is an accident."""
        mask = blank()
        mask[5, 5] = True
        mask[6, 6] = True
        self.assertEqual(detect_blobs(mask, 1, 10000, open_iter=0, close_iter=0),
                         [[5.0, 5.0, 7.0, 7.0]])

    def test_area_bars_are_inclusive_at_both_ends(self):
        mask = blank()
        mask[10:15, 20:25] = True   # 25 px with morphology off
        box = [[20.0, 10.0, 25.0, 15.0]]
        self.assertEqual(detect_blobs(mask, 25, 25, open_iter=0, close_iter=0), box)
        self.assertEqual(detect_blobs(mask, 26, 10000, open_iter=0, close_iter=0), [])
        self.assertEqual(detect_blobs(mask, 1, 24, open_iter=0, close_iter=0), [])

    def test_boxes_come_back_in_raster_order_of_the_first_pixel(self):
        """Not alphabetical, not by size: scipy labels in raster order, so the upper-right blob
        (row 3) precedes the lower-left one (row 20). detections.json is compared bit-identically
        against committed evidence, so the ORDER is part of the contract, not a detail."""
        mask = blank()
        mask[20:25, 5:10] = True
        mask[3:8, 40:45] = True
        self.assertEqual(detect_blobs(mask, 1, 10000, open_iter=0, close_iter=0),
                         [[40.0, 3.0, 45.0, 8.0], [5.0, 20.0, 10.0, 25.0]])

    def test_bounding_box_of_a_concave_component_is_its_full_extent(self):
        """An L: the box covers empty space, and that is correct -- a box is an extent claim, not
        an occupancy claim. Downstream (ADR-009) reads the box's mean side as an apparent radius,
        so a concave detection reads LARGER, i.e. nearer. Conservative in the safe direction."""
        mask = blank()
        mask[10:20, 20:23] = True
        mask[17:20, 20:30] = True
        self.assertEqual(detect_blobs(mask, 1, 10000, open_iter=0, close_iter=0),
                         [[20.0, 10.0, 30.0, 20.0]])

    def test_the_image_border_is_structurally_invisible(self):
        """A 5x5 block in the array corner reports [1,1,5,5], not [0,0,5,5]: closing ends in an
        erosion whose out-of-array neighbours are False, so the outermost row and column can never
        survive it. Isolated below -- opening alone keeps them, closing alone removes them.

        This is a real property of the ADOPTED detector, not a test artefact, and the committed
        evidence obeys it: across all 24 boxes of the am. 7 run, min x0 = 1, max x1 = 639 (W-1),
        max y1 = 479 (H-1). Consequence for the ADR-009 seam: a bird straddling the frame edge is
        measured 1 px small on that side, so the apparent-size ray reads it very slightly FARTHER
        than it is -- a bias in the un-conservative direction, ~2-5 % of range on a 20-50 px blob.
        Small, one-sided, and now written down rather than discovered later."""
        mask = blank()
        mask[0:5, 0:5] = True
        self.assertEqual(detect_blobs(mask, 1, 10000), [[1.0, 1.0, 5.0, 5.0]])
        self.assertEqual(detect_blobs(mask, 1, 10000, close_iter=0), [[0.0, 0.0, 5.0, 5.0]])
        self.assertEqual(detect_blobs(mask, 1, 10000, open_iter=0), [[1.0, 1.0, 5.0, 5.0]])

    def test_empty_mask_yields_no_boxes(self):
        self.assertEqual(detect_blobs(blank(), 1, 10000), [])

    def test_does_not_mutate_the_caller_s_mask(self):
        """The live node hands in a mask derived from the frame it is about to log."""
        mask = blank()
        mask[10:15, 20:25] = True
        before = mask.copy()
        detect_blobs(mask, 1, 10000)
        self.assertTrue(np.array_equal(mask, before))

    def test_boxes_are_plain_json_serializable_floats(self):
        mask = blank()
        mask[10:15, 20:25] = True
        boxes = detect_blobs(mask, 1, 10000)
        self.assertEqual(json.loads(json.dumps(boxes)), boxes)
        self.assertTrue(all(type(v) is float for box in boxes for v in box))


class TestDetectNdvi(unittest.TestCase):
    def test_threshold_has_no_default(self):
        """The threshold IS the detector and it differs by half a unit between renders, so it must
        be stated by the caller -- offline from the clip's meta.json, live from a node parameter
        recorded in the flight log. A default here is how a synthetic number reaches a real
        render (ADR-003 am. 1)."""
        import inspect
        params = inspect.signature(detect_ndvi).parameters
        self.assertIs(params["thresh"].default, inspect.Parameter.empty)
        self.assertEqual(params["min_area"].default, DEFAULT_MIN_AREA)
        self.assertEqual(params["max_area"].default, DEFAULT_MAX_AREA)

    def test_birdness_is_strictly_below_threshold(self):
        """`ndvi < thresh`, not `<=`: a pixel sitting exactly on the threshold is background."""
        at = np.zeros((40, 60), dtype=np.float32)
        at[10:20, 10:20] = REAL_RENDER_THRESH
        self.assertEqual(detect_ndvi(at, REAL_RENDER_THRESH, 1, 10000), [])

        below = np.zeros((40, 60), dtype=np.float32)
        below[10:20, 10:20] = np.nextafter(np.float32(REAL_RENDER_THRESH), np.float32(-1.0))
        self.assertEqual(detect_ndvi(below, REAL_RENDER_THRESH, 1, 10000),
                         [[10.0, 10.0, 20.0, 20.0]])

    def test_nan_pixels_are_never_candidates_and_do_not_hide_a_real_blob(self):
        """NDVI is (NIR-Red)/(NIR+Red); a zero-sum pixel is NaN. It must read as background rather
        than as the nearest possible obstacle, and it must not suppress a real blob elsewhere."""
        frame = np.zeros((40, 60), dtype=np.float32)
        frame[10:20, 10:20] = np.nan
        self.assertEqual(detect_ndvi(frame, REAL_RENDER_THRESH, 1, 10000), [])
        frame[25:32, 25:32] = -0.9
        self.assertEqual(detect_ndvi(frame, REAL_RENDER_THRESH, 1, 10000),
                         [[25.0, 25.0, 32.0, 32.0]])

    def test_the_wrong_render_s_threshold_saturates_into_silence(self):
        """ADR-003 amendment 1's defect, executable. Real-render soil reads -0.4377, so the
        synthetic 0.05 masks essentially every pixel: one whole-image component, which max_area
        then discards. Zero detections from a detector that looked like it ran -- the failure mode
        that is worse than a crash, because it writes a clean-looking number into the record."""
        soil = np.full((480, 640), -0.4377, dtype=np.float32)
        soil[200:220, 300:320] = -0.79   # bird core, gate2's measured class mean
        self.assertEqual(detect_ndvi(soil, SYNTHETIC_THRESH), [])
        self.assertEqual(detect_ndvi(soil, REAL_RENDER_THRESH), [[300.0, 200.0, 320.0, 220.0]])


class TestAdoptedConstants(unittest.TestCase):
    def test_real_render_threshold_is_still_the_gate2_bird_soil_midpoint(self):
        """Recomputed from the committed evidence rather than trusted, now against the constant's
        NEW home -- moving a number must not cost it its provenance check."""
        classes = json.loads(GATE2.read_text())["classes"]
        midpoint = (classes["bird"]["mean_proxy_ndvi"] + classes["soil"]["mean_proxy_ndvi"]) / 2.0
        self.assertAlmostEqual(REAL_RENDER_THRESH, midpoint, delta=0.01)

    def test_synthetic_threshold_is_the_adr_003_deciding_value(self):
        self.assertEqual(SYNTHETIC_THRESH, 0.05)

    def test_real_render_threshold_stays_flagged_provisional_in_its_new_home(self):
        """ADOPT is not the same as CALIBRATED: -0.61 came from per-class pixel means, and the
        n=20 detection evidence confirms it works, not that it belongs there. If the word ever
        disappears from the module that owns the constant, someone has promoted an unverified
        number on the strength of a passing run."""
        self.assertIn("PROVISIONAL", Path(ndvi_detect.__file__).read_text())

    def test_area_defaults_are_the_params_the_adr_was_adopted_at(self):
        """The module's defaults must equal the numbers recorded in the ADOPTED artifact -- so a
        tweak here contradicts the evidence file instead of quietly outliving it."""
        params = adopted_artifact()["params"]
        self.assertEqual(params["min_area"], DEFAULT_MIN_AREA)
        self.assertEqual(params["max_area"], DEFAULT_MAX_AREA)
        self.assertEqual(params["thresh"], REAL_RENDER_THRESH)


class TestOneSourceOfTruth(unittest.TestCase):
    """The move's actual deliverable: there is exactly ONE detector, and both eval arms plus the
    live seam run that one."""

    def test_eval_blob_module_is_gone(self):
        """Deleted, not shimmed. A re-added eval/blob.py would be a second detector able to drift
        from the one that flies -- which is the whole reason ADR-003's numbers moved into src/."""
        self.assertFalse((REPO_ROOT / "eval" / "blob.py").exists())

    def test_both_eval_arms_call_the_module_s_own_functions(self):
        import baseline_ndvi
        import baseline_rgb
        self.assertIs(baseline_ndvi.detect_ndvi, detect_ndvi)
        self.assertIs(baseline_rgb.detect_blobs, detect_blobs)
        self.assertEqual(baseline_ndvi.REAL_RENDER_THRESH, REAL_RENDER_THRESH)
        self.assertEqual(baseline_ndvi.SYNTHETIC_THRESH, SYNTHETIC_THRESH)

    def test_the_thresholds_are_not_re_declared_in_the_eval_harness(self):
        src = (REPO_ROOT / "eval" / "baseline_ndvi.py").read_text()
        self.assertNotIn("REAL_RENDER_THRESH =", src)
        self.assertNotIn("SYNTHETIC_THRESH =", src)

    def test_the_morphology_is_scipy_s(self):
        """ADR-003 am. 7 adopted what scipy.ndimage computed. A numpy reimplementation would be a
        different detector wearing the same verdict, so the container carries the dependency
        instead (sim/docker/Dockerfile installs python3-scipy) and there is no silent fallback."""
        self.assertEqual(ndvi_detect.ndimage.__name__.split(".")[0], "scipy")


class TestAdoptedDetectorOnTheRealRender(unittest.TestCase):
    """The pin that matters: real Gazebo NDVI frames in, the ADR's own committed boxes out."""

    @classmethod
    def setUpClass(cls):
        cls.frames = np.load(FIXTURE)
        artifact = adopted_artifact()
        cls.expected = {f["frame_id"]: f["boxes"] for f in artifact["frames"]}
        cls.params = artifact["params"]

    def test_reproduces_the_committed_boxes_frame_for_frame(self):
        for fid in FIXTURE_FRAME_IDS:
            with self.subTest(frame_id=fid):
                boxes = detect_ndvi(self.frames[f"frame_{fid}"], self.params["thresh"],
                                    self.params["min_area"], self.params["max_area"])
                self.assertEqual(boxes, self.expected[fid])

    def test_the_fixture_covers_the_cases_that_can_break(self):
        """Guards the pin itself: if the fixture ever degraded to three blank frames every
        assertion above would still pass. It must keep an empty frame, a multi-component frame,
        and a component pushed as far into the border as this detector can report one (x0 == 1 /
        y1 == H-1, per test_the_image_border_is_structurally_invisible)."""
        boxes = {fid: self.expected[fid] for fid in FIXTURE_FRAME_IDS}
        self.assertIn([], boxes.values())
        self.assertTrue(any(len(b) >= 2 for b in boxes.values()))
        height, width = self.frames["frame_613"].shape
        self.assertTrue(any(b[0] == 1.0 or b[1] == 1.0 or b[2] == width - 1 or b[3] == height - 1
                            for bs in boxes.values() for b in bs))

    def test_the_wrong_render_s_threshold_finds_nothing_on_a_real_frame(self):
        """The am. 1 saturation defect on real pixels rather than a constructed array: 613's bird
        is unmissable at -0.61 and invisible at 0.05."""
        self.assertEqual(detect_ndvi(self.frames["frame_613"], SYNTHETIC_THRESH), [])
        self.assertEqual(len(detect_ndvi(self.frames["frame_613"], REAL_RENDER_THRESH)), 2)

    @unittest.skipUnless((CLIP / "poses.jsonl").exists() and (CLIP / "frames" / "ndvi").is_dir(),
                         f"adopted clip frames absent (gitignored .npy bulk): {CLIP}")
    def test_fixture_frames_are_verbatim_copies_of_the_clip(self):
        """The check the fixture cannot fake. A .npz is opaque, so on any host that still has the
        flown clip, prove these arrays ARE the flown render rather than arrays fitted to the
        expected answer."""
        poses = {json.loads(line)["frame_id"]: json.loads(line)
                 for line in (CLIP / "poses.jsonl").read_text().splitlines() if line.strip()}
        for fid in FIXTURE_FRAME_IDS:
            with self.subTest(frame_id=fid):
                source = np.load(CLIP / poses[fid]["ndvi_path"])
                fixture = self.frames[f"frame_{fid}"]
                self.assertEqual(fixture.dtype, source.dtype)
                self.assertTrue(np.array_equal(fixture, source))


class TestWholeClipTransfer(unittest.TestCase):
    """Skipped wherever the gitignored .npy bulk is absent (CI); on the flight host it is the real
    gate -- the ENTIRE adopted run, all 1256 frames, must still land bit-identically. Run it before
    booking a take: the fixture proves three frames, this proves no new box appeared on the other
    1253."""

    @unittest.skipUnless((CLIP / "frames" / "ndvi").is_dir(),
                         f"adopted clip frames absent (gitignored .npy bulk): {CLIP}")
    def test_the_offline_pipeline_reproduces_the_adopted_artifact_exactly(self):
        import baseline_ndvi
        thresh, source = baseline_ndvi.resolve_threshold(CLIP, None)
        artifact = adopted_artifact()
        self.assertEqual(thresh, artifact["params"]["thresh"])
        self.assertEqual(source, artifact["params"]["thresh_source"])
        frames = baseline_ndvi.run(CLIP, thresh, artifact["params"]["min_area"],
                                   artifact["params"]["max_area"])
        self.assertEqual(frames, artifact["frames"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
