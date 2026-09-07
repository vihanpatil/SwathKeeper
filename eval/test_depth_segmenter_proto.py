"""`eval/depth_segmenter_proto.py` — the depth segmenter's stress suite, host-only, synthetic frames.

WHY SYNTHETIC IS NOT A COMPROMISE HERE. The 12 commissioned depth frames are ~1.2 MB of base64 each
and are not in the repo, so this suite reconstructs the scene instead of shipping it — and the
reconstruction is checked to BE the scene, not to resemble it: `ground_band()` fed the sensor's own
live intrinsics reproduces the commissioned render's ground band to the pixel (finite rows 374-479,
Z 32.568-57.993, finite fraction 0.2036). A fixture that is only plausible would let the constants
drift; this one shares its evidence with the real frames.

WHAT THIS SUITE IS FOR, in the order it matters:

  * THE FIVE BACKGROUNDS the algorithm claims to handle, each asserted to detect or to MISS for the
    stated reason: bird against sky (trivial), bird in front of the ground band (the merge case that
    an `isfinite` mask plus an area ceiling deletes silently), bird in front of / beside a canopy,
    bird BEYOND a canopy (occluded — and the suite asserts the bird contributed ZERO pixels first,
    so the miss is attributed to occlusion rather than merely accepted), and the whole-frame -inf
    near case (a REFUSAL, specifically not an empty detection list).

  * THE TWO PROPERTIES THE WHOLE DESIGN RESTS ON, which are what a grey closing buys over the median
    background that was built and scored first: the ground band produces ZERO candidate pixels, and
    a canopy produces ZERO candidate pixels. If either ever produces one, the closing has stopped
    being a background model and every false-positive number in the design note is void.

  * K's TRADE, pinned in BOTH directions, because K is the only shape parameter: at K=21 the ground
    band starts reporting itself (the bottom-edge residual crosses the margin), and lowering K pulls
    in the range out to which an object is reported whole. A test that pinned only the working value
    would let the next person raise K without meeting its cost.

  * THE LINK BREAK, against the failure it exists for: a bird crossing a tree TRUNK (narrower than
    K, so unlike a canopy it IS a candidate) merges into it and the frame reports one component at
    the TRUNK's depth — a confident detection 4 m too far, which is worse than a miss because it
    looks like success.

  * THE RANGE LIMITS, measured rather than asserted, which is the re-measurement
    `config/depth_camera.json:min_resolving_radius_source` books for this session.

  * THE REFUSAL SEMANTICS, because "0 components" and "I could not tell" reading alike is the defect
    `score.py.evidence_shortfall()` exists for.

stdlib unittest, so it runs under `python3 -m pytest eval/test_depth_segmenter_proto.py -q` and
`python3 -m unittest` alike. No gz, no Docker, no network.
"""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "eval"))

import depth_segmenter_proto as DS  # noqa: E402

# The LIVE intrinsics from the commissioned sensor's own /fg/depth/camera_info (run 2), not
# config/depth_camera.json: the config is what was asked for, the message is what was got.
INTR = DS.Intrinsics(fx=520.00580469275542, fy=520.00580469275531,
                     cx=320.0, cy=240.0, width=640, height=480)
BIRD_R_M = 0.18          # config/birds/farm_world_birds.json — all three birds
CAM_ALT_M = 15.0         # the commissioning camera pose (60.15, 30, 15), level, looking +E
SHAPE = (480, 640)


def r_px(z_m, radius_m=BIRD_R_M):
    return INTR.fx * radius_m / z_m


def bird_frame(z_m, u=320.0, v=240.0, background=None, radius_m=BIRD_R_M):
    return DS.render_disc(SHAPE, u, v, r_px(z_m, radius_m), z_m, background=background)


def find(result, u, v, tol=10.0):
    for c in result.components:
        if math.hypot(c.bbox_centre_px[0] - u, c.bbox_centre_px[1] - v) <= tol:
            return c
    return None


def trunk_over_ground(ground, z_m=24.0, half_width_px=3):
    """A tree TRUNK: narrow enough to be a pit at K=15, so — unlike a canopy — it IS a candidate."""
    f = ground.copy()
    lo, hi = 320 - half_width_px, 320 + half_width_px + 1
    f[:, lo:hi] = np.minimum(f[:, lo:hi], np.float32(z_m))
    return f


# ============================================================ the reconstruction IS the scene
class TestGroundBandMatchesTheRealRender(unittest.TestCase):
    """If these drift, every constant below is derived from a different world than the one the sensor
    was commissioned in, and the suite is measuring itself."""

    def setUp(self):
        self.g = DS.ground_band(SHAPE, INTR, CAM_ALT_M)

    def test_extent_and_depths_match_the_commissioned_frames(self):
        fin = np.isfinite(self.g)
        rows = np.where(fin.any(axis=1))[0]
        self.assertEqual((int(rows.min()), int(rows.max())), (374, 479))
        self.assertAlmostEqual(float(self.g[fin].min()), 32.568, places=2)
        self.assertAlmostEqual(float(self.g[fin].max()), 57.993, places=2)
        self.assertAlmostEqual(float(fin.mean()), 0.2036, places=3)

    def test_the_ground_band_produces_ZERO_candidates(self):
        """The headline property. A ramp has no pits, so the closing reproduces it and none of it is
        ever 'nearer than its background' — including the far cull, where the ground ends against
        sky. The median background this replaced left 498 candidate pixels here, in 11 components."""
        res = DS.segment(self.g, INTR)
        self.assertEqual(res.counters["candidate_px"], 0)
        self.assertEqual(res.components, [])
        self.assertIsNone(res.refused)

    def test_closing_residual_is_an_edge_effect_and_the_margin_clears_it(self):
        """Where the residual lives matters as much as how big it is: it is the bottom K/2 rows,
        where the ground ramp is truncated by the image, and it is EXACTLY ZERO above 40 m. That
        measurement — structure falling with range, not rising — is why MARGIN_FRAC is 0.0."""
        bg = DS.estimate_background(self.g)
        fin = np.isfinite(self.g) & np.isfinite(bg)
        with np.errstate(invalid="ignore"):
            resid = np.where(fin, bg - self.g, 0.0)
        self.assertLess(float(resid.max()), DS.MARGIN_ABS_M)
        self.assertAlmostEqual(float(resid.max()), 0.981, places=2)
        rows = np.where((resid > 0.01).any(axis=1))[0]
        self.assertGreaterEqual(int(rows.min()), SHAPE[0] - DS.CLOSING_K_PX)
        far = fin & (self.g > 40.0)
        self.assertEqual(float(resid[far].max()), 0.0)


# =========================================================================== the five backgrounds
class TestTheFiveBackgrounds(unittest.TestCase):

    def setUp(self):
        self.ground = DS.ground_band(SHAPE, INTR, CAM_ALT_M)
        self.canopy = DS.render_disc(SHAPE, 340.0, 250.0, 70.0, 24.0)

    def test_bird_against_sky(self):
        res = DS.segment(bird_frame(46.0), INTR)
        c = find(res, 320.0, 240.0)
        self.assertIsNotNone(c)
        self.assertAlmostEqual(c.depth_median_m, 46.0, places=3)
        self.assertEqual(len(res.components), 1)

    def test_bird_in_front_of_the_ground_band_does_not_merge_into_it(self):
        """THE case an `isfinite` mask plus a max_area ceiling deletes silently: the bird's pixels are
        4-connected to the ground's, so a finiteness mask yields one ~62k-px component."""
        for v_row, z_bird in ((400.0, 20.0), (440.0, 30.0), (470.0, 20.0), (390.0, 25.0)):
            with self.subTest(row=v_row):
                res = DS.segment(bird_frame(z_bird, v=v_row, background=self.ground), INTR)
                c = find(res, 320.0, v_row)
                self.assertIsNotNone(c, f"bird at row {v_row} lost in the ground band")
                self.assertAlmostEqual(c.depth_median_m, z_bird, places=3)
                self.assertEqual(len(res.components), 1, "the ground itself must not be reported")

    def test_a_canopy_produces_ZERO_candidates_and_a_bird_on_it_survives(self):
        """A canopy is wider than K, so it is its own background everywhere INCLUDING its rim. The
        median background this replaced reported 10 rim fragments here, one of which (31 px at 24 m)
        has the same apparent size as a bird at that range — which is why no size rule can be the
        answer and why the background model has to be."""
        self.assertEqual(DS.segment(self.canopy, INTR).counters["candidate_px"], 0)
        for u in (340.0, 410.0):        # canopy interior, then straddling its outline
            with self.subTest(u=u):
                res = DS.segment(bird_frame(20.0, u=u, v=250.0, background=self.canopy), INTR)
                c = find(res, u, 250.0)
                self.assertIsNotNone(c)
                self.assertAlmostEqual(c.depth_median_m, 20.0, places=3)
                self.assertEqual(len(res.components), 1)

    def test_bird_beyond_a_canopy_is_missed_because_it_is_occluded(self):
        frame = bird_frame(30.0, u=340.0, v=250.0, background=self.canopy)
        # Attribute the miss BEFORE asserting it: a miss for the wrong reason is not a pass.
        self.assertEqual(int((frame == np.float32(30.0)).sum()), 0,
                         "the occluder must actually occlude, or this test proves nothing")
        res = DS.segment(frame, INTR)
        self.assertIsNone(find(res, 340.0, 250.0))
        self.assertEqual(len(res.components), 0)

    def test_whole_frame_near_clip_is_a_refusal_not_an_empty_answer(self):
        res = DS.segment(np.full(SHAPE, -np.inf, dtype=np.float32), INTR)
        self.assertEqual(res.refused, "near_clip")
        self.assertEqual(res.components, [])
        self.assertEqual(res.counters["neg_inf_px"], SHAPE[0] * SHAPE[1])

    def test_pure_sky_is_empty_but_NOT_a_refusal(self):
        """The sensor answered; the answer was 'nothing in range'. That is a different fact from
        'I could not tell', and the flight log has to be able to tell them apart."""
        res = DS.segment(np.full(SHAPE, np.inf, dtype=np.float32), INTR)
        self.assertIsNone(res.refused)
        self.assertEqual(res.components, [])
        self.assertEqual(res.counters["finite_px"], 0)


# ================================================================== K, and the link break
class TestKAndTheLinkBreak(unittest.TestCase):

    def setUp(self):
        self.ground = DS.ground_band(SHAPE, INTR, CAM_ALT_M)

    def test_K_is_pinned_from_BOTH_directions(self):
        """Raising K is not free and lowering it is not free; both costs are asserted, so moving it
        requires meeting one of them."""
        # UPPER: at K=21 the bottom-edge residual (1.419 m) crosses the 1.2 m margin and the ground
        # band starts reporting itself.
        big = DS.segment(self.ground, INTR, DS.SegmenterParams(closing_k_px=21))
        self.assertGreater(big.counters["candidate_px"], 1000)
        # LOWER: K sets how CLOSE an object may come and still be reported whole (`2*fx*R/K`), so
        # lowering K pushes that crossover FARTHER out -- K=9 gives up 8.3 m of whole-object range.
        self.assertAlmostEqual(DS.whole_object_range_m(INTR), 12.48, places=1)
        self.assertGreater(DS.whole_object_range_m(INTR, DS.SegmenterParams(closing_k_px=9)), 20.0)

    def test_an_object_wider_than_K_returns_as_arcs_never_as_nothing(self):
        """The near-field behaviour, stated as a property rather than left to be discovered: closer
        than `whole_object_range_m` the object is still detected at its own correct depth, but as
        several components. A scorer expecting one box per bird has to know where that starts."""
        res = DS.segment(bird_frame(6.0), INTR)
        self.assertGreater(len(res.components), 1)
        for c in res.components:
            self.assertAlmostEqual(c.depth_median_m, 6.0, places=3)

    def test_link_break_keeps_a_bird_from_inheriting_a_trunk(self):
        """The failure this rule exists for, and the reason it is kept despite no case in the check
        world: a trunk is narrower than K, so it IS a candidate, and a bird crossing it merges."""
        frame = DS.render_disc(SHAPE, 320.5, 300.0, r_px(20.0), 20.0,
                               background=trunk_over_ground(self.ground))
        merged = DS.segment(frame, INTR, DS.SegmenterParams(link_break=False))
        self.assertEqual(len(merged.components), 1)
        self.assertAlmostEqual(merged.components[0].depth_median_m, 24.0, places=3)  # 4 m too far

        split = DS.segment(frame, INTR)
        bird = find(split, 320.5, 300.0, tol=6.0)
        self.assertIsNotNone(bird, "the bird must survive the split, not just the trunk")
        self.assertAlmostEqual(bird.depth_median_m, 20.0, places=3)
        self.assertGreater(split.counters["link_cut_px"], 0)

    def test_two_close_birds_do_not_merge(self):
        """A flock going dark, or reporting as one object at one depth, is the worst failure a bird
        detector has available."""
        frame = bird_frame(20.0, u=300.0, v=240.0)
        frame = DS.render_disc(SHAPE, 316.0, 240.0, r_px(20.0), 20.0, background=frame)
        res = DS.segment(frame, INTR)
        self.assertEqual(len(res.components), 2)


# ======================================================================== the range limits
class TestRangeLimitsAreMeasured(unittest.TestCase):

    def test_resolving_floor_beats_the_NDVI_morphology(self):
        """`config/depth_camera.json:min_resolving_radius_px = 2.0` was measured against the NDVI
        detector's open+close, and the config names re-measuring it here as a booked gap. Both are
        measured in one place so the comparison is like-for-like."""
        floor = DS.resolving_floor_px(INTR)
        ndvi_floor = DS.resolving_floor_px(INTR, DS.SegmenterParams(open_iter=1, close_iter=1))
        self.assertAlmostEqual(ndvi_floor, 2.0, places=1)          # reproduces the booked number
        self.assertLessEqual(floor, 1.6)                           # this morphology does better
        self.assertGreater(INTR.fx * BIRD_R_M / floor, 58.0)       # in the unit the gate reads

    def test_the_near_limit_is_measured_and_sits_inside_the_clearance_bar(self):
        limit = DS.near_detection_limit_m(INTR)
        self.assertLess(limit, DS.whole_object_range_m(INTR))
        # avoidance_policy.PolicyParams.min_bird_clearance_m is 3.0 m. Going blind OUTSIDE that bar
        # would leave the segmenter unable to witness the very breach avoidance is judged on.
        self.assertLessEqual(limit, 3.0)

    def test_resolving_standoff_matches_the_margin_it_is_derived_from(self):
        """A bird less than margin(z) in front of its background is not separable — stated as a
        number so the labeller records `standoff_m` and a miss can be attributed rather than
        guessed at."""
        canopy = DS.render_disc(SHAPE, 340.0, 250.0, 70.0, 24.0)
        self.assertIsNone(find(DS.segment(bird_frame(23.0, u=340.0, v=250.0, background=canopy),
                                          INTR), 340.0, 250.0))       # 1.0 m < 1.2 m margin
        self.assertIsNotNone(find(DS.segment(bird_frame(22.5, u=340.0, v=250.0, background=canopy),
                                             INTR), 340.0, 250.0))    # 1.5 m > 1.2 m margin


# =============================================================================== machinery
class TestMachineryAndRefusals(unittest.TestCase):

    def test_nan_is_treated_as_far_and_counted_never_as_a_range(self):
        frame = bird_frame(30.0)
        frame[100:110, 100:110] = np.nan
        res = DS.segment(frame, INTR)
        self.assertEqual(res.counters["nan_px"], 100)
        self.assertIsNotNone(find(res, 320.0, 240.0))
        self.assertIsNone(find(res, 105.0, 105.0), "a NaN patch must never become a detection")

    def test_a_value_at_a_clip_plane_is_refused_not_clamped(self):
        frame = np.full(SHAPE, np.inf, dtype=np.float32)
        frame[200:220, 200:220] = 60.0        # exactly the far clip = the clamp signature
        res = DS.segment(frame, INTR)
        self.assertEqual(res.counters["invalid_range_px"], 400)
        self.assertEqual(res.components, [])

    def test_a_single_stray_near_clip_pixel_is_counted_but_does_not_refuse(self):
        frame = bird_frame(30.0)
        frame[10, 10] = -np.inf
        res = DS.segment(frame, INTR)
        self.assertIsNone(res.refused)
        self.assertEqual(res.counters["neg_inf_px"], 1)
        self.assertIsNotNone(find(res, 320.0, 240.0),
                             "one -inf pixel must not blind a KxK window of the background")

    def test_bbox_midpoint_is_the_pinhole_coordinate(self):
        """Boxes are half-open slice bounds exactly as `ndvi_detect.detect_blobs` returns them, so
        `DepthDetectionSource.box_to_detection`'s 0.5*(x0+x1) is already the pinhole (u,v) that
        `depth_pixel_to_enu` un-projects. A half-pixel convention error here is a systematic
        cross-track bias that no value gate would catch."""
        for u, v in ((320.0, 240.0), (560.0, 120.0), (200.0, 380.0)):
            with self.subTest(u=u, v=v):
                c = find(DS.segment(bird_frame(25.0, u=u, v=v), INTR), u, v, tol=3.0)
                self.assertIsNotNone(c)
                self.assertLess(abs(c.bbox_centre_px[0] - u), 0.51)
                self.assertLess(abs(c.bbox_centre_px[1] - v), 0.51)

    def test_median_depth_is_biased_FARTHER_than_the_nearest_surface_by_under_a_radius(self):
        """Quantified because the direction is fail-dangerous: the seam consumes the median, which
        sits BEHIND the sphere's nearest surface. Bounded by the object's own radius, and
        `depth_p05_m` is carried as the safety-forward alternative."""
        z0, R = 30.0, BIRD_R_M
        rp = r_px(z0)
        u = np.arange(SHAPE[1], dtype=np.float64)[None, :] + 0.5
        v = np.arange(SHAPE[0], dtype=np.float64)[:, None] + 0.5
        rr = np.sqrt((u - INTR.cx) ** 2 + (v - INTR.cy) ** 2)
        frame = np.full(SHAPE, np.inf, dtype=np.float32)
        m = rr <= rp
        frame[m] = (z0 - R * np.sqrt(np.clip(1.0 - (rr[m] / rp) ** 2, 0.0, 1.0))).astype(np.float32)
        c = find(DS.segment(frame, INTR), INTR.cx, INTR.cy)
        self.assertIsNotNone(c)
        self.assertGreaterEqual(c.depth_median_m, z0 - R)
        self.assertLess(c.depth_median_m - (z0 - R), R)
        self.assertLessEqual(c.depth_p05_m, c.depth_median_m)

    def test_size_ratio_is_reported_and_filters_nothing_by_default(self):
        """It is a tag, not a filter, and the reason is measured: a canopy-rim fragment at 24 m is
        31 px against the 33 px a 0.15 m bird subtends there. If a size band is ever switched on it
        has to come from the cluttered dataset's NEGATIVES, not from the positives alone."""
        p = DS.SegmenterParams()
        self.assertIsNone(p.size_ratio_lo)
        self.assertIsNone(p.size_ratio_hi)
        c = find(DS.segment(bird_frame(46.0), INTR), 320.0, 240.0)
        self.assertGreater(c.size_ratio, 0.5)
        self.assertLess(c.size_ratio, 3.0)

    def test_frame_shape_disagreeing_with_camera_info_raises(self):
        with self.assertRaises(ValueError):
            DS.segment(np.full((240, 320), np.inf, dtype=np.float32), INTR)

    def test_segmenter_adapter_returns_the_seam_shape(self):
        seg = DS.as_segmenter(INTR)
        out = seg(bird_frame(40.0))
        self.assertEqual(len(out), 1)
        box, depth = out[0]
        self.assertEqual(len(box), 4)
        self.assertAlmostEqual(depth, 40.0, places=3)
        self.assertAlmostEqual(0.5 * (box[0] + box[2]), 320.0, delta=0.51)


if __name__ == "__main__":
    unittest.main()
