"""Tests for the forward depth SEGMENTER (`fieldguard_planning.depth_segment`).

THE POINT OF THIS FILE, beyond unit coverage:

  1. **The background estimator is measured, not asserted.** `TestRampInvariance` re-derives the
     border residual that FLOORS `margin_m` on every run, from the same analytic ground model the
     design note and the prototype independently landed on (1.425 m and 1.419 m at K=21; this
     measures it again). A silent change to the closing would move a safety constant, so the
     constant is re-measured here rather than restated.

  2. **The merge case is the reason the module exists** and it is tested directly: a sphere on a
     ramp must come back as ONE component carrying the SPHERE's depth, not the ramp's. The failure
     it prevents is not a miss -- it is a confident detection ~20 m too far, which looks like
     success.

  3. **The mask's conjuncts are mutated.** Each term is deleted in turn on the canned frame
     `eval/score_depth_segmenter.mutation_canned_frame` builds -- the SAME frame the committed
     score artifact records -- and the expected result must change. One of the three is measured
     REDUNDANT, and that finding is pinned as an executable fact rather than papered over.

  4. **It is gated on a real render, not only on synthetic fixtures.** `TestSeamOnARealFrame` runs
     the adopted segmenter through the real `DepthDetectionSource` over a committed dataset frame
     and requires a `Detection` at the bird's surveyed world position -- with
     `pixel_to_ground_enu` monkeypatched to explode, because ADR-009 rule 1 says a ground-plane
     projection here would put a flying bird at z=0 and silently suppress a real threat.

Runs on the host: numpy + scipy, no rclpy, no Docker, ~5 s.
"""
import json
import math
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402

import score_depth_segmenter as sds  # noqa: E402
from fieldguard_planning import ndvi_georef  # noqa: E402
from fieldguard_planning.depth_detect import DepthDetectionSource  # noqa: E402
from fieldguard_planning.depth_segment import (  # noqa: E402
    DEFAULT_PARAMS, DEFAULT_PARAMS_PROVENANCE, MASK_TERMS, DepthSegmenter, DepthSegmenterParams,
    analytic_ground_ramp, border_residual_m, closing, params_with,
)
from fieldguard_planning.ndvi_detect import detect_blobs  # noqa: E402
from fieldguard_planning.ndvi_georef import CameraIntrinsics  # noqa: E402

INTR = CameraIntrinsics.from_config(640, 480, 1.1033)
FIXTURES = REPO_ROOT / "eval" / "results" / "depth_dataset_20260907" / "fixtures"
ALT_M, FAR_M = 15.0, 60.0
BIRD_R_M = 0.18


def ramp() -> np.ndarray:
    return analytic_ground_ramp(INTR.height_px, INTR.width_px, INTR.fy, INTR.cy,
                                ALT_M, FAR_M, INTR.fx, INTR.cx)


def sky(h: int = 480, w: int = 640) -> np.ndarray:
    return np.full((h, w), np.inf, dtype=np.float32)


def disc(z: np.ndarray, cu: float, cv: float, r_px: float, depth_m: float) -> np.ndarray:
    """A filled disc at pinhole centre (cu, cv). The NEARER surface wins, so an occluder occludes."""
    out = z.copy()
    u = np.arange(z.shape[1], dtype=np.float64)[None, :] + 0.5
    v = np.arange(z.shape[0], dtype=np.float64)[:, None] + 0.5
    m = ((u - cu) ** 2 + (v - cv) ** 2) <= r_px * r_px
    out[m] = np.minimum(out[m], np.float32(depth_m))
    return out.astype(np.float32)


def boxes_of(frame, params=DEFAULT_PARAMS, **kw):
    return DepthSegmenter(params_with(params, **kw) if kw else params)(frame)


class TestRampInvariance(unittest.TestCase):
    """A monotone ramp has no pits, so a flat-SE closing reproduces it -- exactly, over the
    interior. The whole 'the ground is never its own candidate' argument rests on this."""

    def test_the_ground_ramp_yields_zero_candidates_in_the_frame_interior(self):
        z = ramp()
        k = DEFAULT_PARAMS.bg_window_px
        with np.errstate(invalid="ignore"):
            step = closing(z, k) - z
        interior = np.zeros(z.shape, dtype=bool)
        interior[k:-k, k:-k] = True
        finite = np.isfinite(z) & interior
        self.assertTrue(finite.any(), "the analytic ramp produced no finite interior pixels")
        self.assertEqual(float(np.nanmax(np.where(finite, step, -np.inf))), 0.0,
                         "the closing must reproduce a monotone ramp EXACTLY over the interior")
        self.assertEqual(len(boxes_of(z)), 0, "the ground band must not be its own candidate")

    def test_the_border_residual_is_remeasured_and_it_floors_the_margin(self):
        """The one number that is not free: within K/2 rows of the image bottom there is no
        farther row to erode back with, so the residual is an image-BORDER artifact that grows
        one-for-one with K. `margin_m` must clear 1.5x it, which is the rule the committed sweep
        applied -- so a drift here would move a safety constant."""
        z = ramp()
        res = {k: border_residual_m(z, k) for k in (15, 17, 21, 25)}
        self.assertLess(res[15], res[17])
        self.assertLess(res[17], res[21])
        self.assertLess(res[21], res[25])
        # Independent agreement worth pinning: DESIGN §2.2's analytic check found 1.425 m at K=21
        # and the prototype measured 1.419 m. Two derivations, one number.
        self.assertAlmostEqual(res[21], 1.42, places=1)
        floor = 1.5 * res[DEFAULT_PARAMS.bg_window_px]
        self.assertGreaterEqual(DEFAULT_PARAMS.margin_m, floor,
                                f"margin {DEFAULT_PARAMS.margin_m} is below its own floor {floor}")
        # ...and the residual really does live at the bottom border, not in the interior.
        with np.errstate(invalid="ignore"):
            step = closing(z, 15) - z
        self.assertGreater(float(np.nanmax(np.where(np.isfinite(z), step, -np.inf)[470:, :])), 0.5)
        self.assertEqual(float(np.nanmax(np.where(np.isfinite(z), step, -np.inf)[:460, :])), 0.0)


class TestBackgroundClasses(unittest.TestCase):
    def test_pure_sky_returns_nothing_and_counts_every_pixel_as_pos_inf(self):
        seg = DepthSegmenter(DEFAULT_PARAMS)
        self.assertEqual(seg(sky()), [])
        c = seg.counters()
        self.assertEqual(c["px_pos_inf"], 640 * 480)
        self.assertEqual(c["candidate_px"], 0)
        self.assertEqual(c["frames"], 1)

    def test_pos_inf_is_never_a_candidate_but_is_always_a_valid_background(self):
        """Sky is the farthest thing there is: `bg - (+inf)` is NaN, which compares False. A
        sky-backed target therefore gets an INFINITE step and is detected at any range."""
        z = disc(sky(), 320.0, 240.0, INTR.fx * BIRD_R_M / 46.0, 46.0)
        got = boxes_of(z)
        self.assertEqual(len(got), 1)
        self.assertAlmostEqual(got[0][1], 46.0, places=4)
        # and the sky pixels themselves are not in any box
        self.assertLess((got[0][0][2] - got[0][0][0]) * (got[0][0][3] - got[0][0][1]), 100)

    def test_merge_case_a_sphere_on_a_ramp_carries_the_SPHERES_depth_not_the_ramps(self):
        """THE failure this module exists to prevent. Under an `isfinite` mask the bird 8-connects
        to the ground and the merged blob either gets deleted by an area ceiling (bird gone, no
        counter moves) or survives carrying the BACKGROUND's median depth."""
        z = ramp()
        bg_here = float(z[400, 320])
        self.assertTrue(math.isfinite(bg_here) and bg_here > 30.0, bg_here)
        z = disc(z, 320.0, 400.0, INTR.fx * BIRD_R_M / 20.0, 20.0)
        got = boxes_of(z)
        self.assertEqual(len(got), 1, f"expected exactly one component, got {got}")
        box, depth = got[0]
        self.assertAlmostEqual(depth, 20.0, places=3)
        self.assertGreater(abs(depth - bg_here), 15.0,
                           "the component must NOT carry the ground's depth")
        self.assertLess(abs(0.5 * (box[0] + box[2]) - 320.0), 1.0)
        self.assertLess(abs(0.5 * (box[1] + box[3]) - 400.0), 1.0)

    def test_a_bird_in_front_of_a_canopy_is_its_own_component_at_its_own_depth(self):
        z = disc(sky(), 320.0, 360.0, 40.0, 30.0)          # an 80 px 'canopy', far wider than K
        z2 = disc(z, 320.0, 360.0, INTR.fx * BIRD_R_M / 20.0, 20.0)
        near = [b for b in boxes_of(z2) if abs(b[1] - 20.0) < 0.1]
        self.assertEqual(len(near), 1, "the bird in front of the canopy must be its own component")


class TestNonFiniteHandling(unittest.TestCase):
    def test_neg_inf_is_counted_and_is_never_a_candidate(self):
        z = sky()
        z[100:120, 100:120] = -np.inf
        seg = DepthSegmenter(DEFAULT_PARAMS)
        self.assertEqual(seg(z), [])
        self.assertEqual(seg.counters()["px_neg_inf"], 400)

    def test_a_stray_neg_inf_costs_a_FAR_false_component_and_never_the_near_true_one(self):
        """-inf is kept out of the background estimate, but "kept out" means mapped to +inf ("an
        unknown background is FAR"), and that is not free: MEASURED, a stray refusal on a ramp
        inflates the local far-envelope for ~K rows and yields a small spurious component carrying
        the BACKGROUND's depth. The direction is the whole point -- the error is FP-ward, never
        FN-ward: the bird beside it survives with its depth unchanged to 1e-4 m.

        `px_neg_inf` is 0 over all 85 dataset frames, so this path is exercised here and nowhere
        else; if a flight ever moves that counter, this is the behaviour to expect."""
        z = disc(ramp(), 320.0, 400.0, INTR.fx * BIRD_R_M / 20.0, 20.0)
        without = boxes_of(z)
        self.assertEqual(len(without), 1)
        z2 = z.copy()
        z2[400, 328] = -np.inf                    # one stray refusal right beside the bird
        withit = boxes_of(z2)
        near = [b for b in withit if abs(b[1] - 20.0) < 1e-3]
        self.assertEqual(len(near), 1, "the TRUE near component must survive a stray refusal")
        self.assertAlmostEqual(near[0][1], without[0][1], places=4)
        for _, d in withit:
            self.assertGreaterEqual(d, 20.0 - 1e-3,
                                    "any extra component must be FARTHER than the true one, i.e. "
                                    "the safe direction, never a phantom nearer obstacle")

    def test_a_NaN_patch_wider_than_K_beside_a_target_must_NOT_erase_the_target(self):
        """THE GUARD THAT HAD NO TEST. `_mask` replaces -inf/NaN with +inf BEFORE the closing, and
        that substitution was described in the source as protecting against `-inf`. Measured, it is
        the other way round: `-inf` is inert (the dilation runs first, so it never survives its own
        window) and **NaN is what poisons the filter pair** -- it can survive the maximum and then be
        eroded across a KxK neighbourhood, blinding the background of every pixel within K/2 and
        DELETING a real obstacle there.

        Deleting the guard (`closing(z)` instead of `closing(zb)`) left all 49 other tests green,
        which is what makes this the one that has to exist. The mechanism is asserted alongside the
        behaviour, because 'the box came back' alone does not say the guard is why."""
        u = np.arange(640, dtype=np.float64)[None, :] + 0.5
        v = np.arange(480, dtype=np.float64)[:, None] + 0.5
        tgt = ((u - 320.0) ** 2 + (v - 400.0) ** 2) <= (INTR.fx * BIRD_R_M / 20.0) ** 2
        z = ramp().copy()
        z[385:416, 315:346] = np.float32(np.nan)               # 31x31, wider than K=15
        z[tgt] = np.float32(20.0)                              # the bird sits inside the patch
        seg = DepthSegmenter(DEFAULT_PARAMS)
        got = seg(z)
        near = [(b, d) for b, d in got if abs(d - 20.0) < 1e-3]
        self.assertEqual(len(near), 1, f"the 20 m target was erased by a NaN patch: {got}")
        box = near[0][0]
        self.assertLess(abs(0.5 * (box[0] + box[2]) - 320.0), 1.0)
        self.assertLess(abs(0.5 * (box[1] + box[3]) - 400.0), 1.0)
        self.assertGreater(seg.counters()["px_nan"], 900 - 100)

        # ...and the mechanism: without the substitution the target keeps 2 candidate pixels of 68,
        # i.e. it falls under min_area_px and disappears with no counter moving.
        k = DEFAULT_PARAMS.bg_window_px
        with np.errstate(invalid="ignore"):
            raw = closing(z, k) - z
            san = closing(np.where(np.isnan(z), np.float32(np.inf), z), k) - z

        def on_target(step):
            return int((np.isfinite(z) & (step > DEFAULT_PARAMS.margin_m) & tgt).sum())

        self.assertGreaterEqual(on_target(san), DEFAULT_PARAMS.min_area_px)
        self.assertLess(on_target(raw), DEFAULT_PARAMS.min_area_px,
                        "if the raw closing now keeps the target, the guard has stopped being "
                        "load-bearing and this test's premise needs re-measuring, not deleting")

    def test_nan_is_counted_separately_and_is_never_a_candidate(self):
        z = sky()
        z[200:210, 200:210] = np.nan
        seg = DepthSegmenter(DEFAULT_PARAMS)
        self.assertEqual(seg(z), [])
        self.assertEqual(seg.counters()["px_nan"], 100)
        self.assertEqual(seg.counters()["px_neg_inf"], 0)

    def test_a_finite_depth_at_the_clip_plane_is_the_clamp_signature_and_is_refused(self):
        z = sky()
        z[100:112, 100:112] = np.float32(FAR_M)
        seg = DepthSegmenter(DEFAULT_PARAMS)
        self.assertEqual(seg(z), [], "exactly far_m is what a CLAMP looks like, not a measurement")
        self.assertEqual(seg.counters()["px_outside_clip_window"], 144)


class TestOrderingAndSaturation(unittest.TestCase):
    def test_max_boxes_truncation_drops_the_FARTHEST_never_the_nearest(self):
        z = sky()
        for depth, cu in ((40.0, 100.0), (20.0, 300.0), (30.0, 500.0)):
            z = disc(z, cu, 240.0, INTR.fx * BIRD_R_M / 20.0, depth)
        seg = DepthSegmenter(params_with(DEFAULT_PARAMS, max_boxes=2))
        got = seg(z)
        self.assertEqual([round(d, 1) for _, d in got], [20.0, 30.0],
                         "boxes must come back nearest-first and the 40 m one must be the casualty")
        self.assertEqual(seg.counters()["boxes_truncated"], 1)

    def test_no_max_area_exists_and_the_largest_component_the_MASK_makes_is_always_returned(self):
        """An area CEILING is fail-dangerous by construction: it deletes the largest thing in the
        frame, which is the nearest large obstacle. Saturation is handled by nearest-first ordering
        plus a box cap instead, so nothing is ever dropped for being big."""
        self.assertNotIn("max_area_px", DepthSegmenterParams.__dataclass_fields__,
                         "a max_area field reappearing is the regression this asserts against")
        # A 6 px x 200 px mast at 20 m: narrower than K in one axis, so the closing fills it and the
        # whole 1200 px silhouette is a candidate. `ndvi_detect.DEFAULT_MAX_AREA` is 4000, and an
        # area ceiling anywhere near the frame's own scale would delete exactly this.
        z = ramp()
        z[250:450, 317:323] = np.float32(20.0)
        seg = DepthSegmenter(DEFAULT_PARAMS)
        got = seg(z)
        self.assertTrue(got, "the largest near object the mask made came back as nothing")
        biggest = max(got, key=lambda bd: (bd[0][2] - bd[0][0]) * (bd[0][3] - bd[0][1]))
        self.assertGreater(seg.counters()["largest_component_px"], 1000)
        self.assertAlmostEqual(biggest[1], 20.0, places=3)

    def test_a_LARGE_NEAR_OBJECT_IS_A_MEASURED_BLIND_SPOT_and_both_design_notes_say_otherwise(self):
        """DESIGN §2.5: an object wider than K "returns as a RING of its own silhouette carrying
        its own depth, NOT AS NOTHING". ALGORITHM §2.4 says the same. **Both are wrong**, and this
        pins the measurement instead of the prose: a grey closing by definition PRESERVES a pit
        wider than the structuring element, so `closing(D) - D = 0` across it and a sufficiently
        large near object yields ZERO candidates.

        Why the mission case still holds, and it is a property of THIS world rather than of the
        operator: the large objects here are the mapped, geofenced trees (ADR-001, not this
        detector's problem) and the unplanned obstacle is a 0.18 m bird, which the ladder below
        keeps detectable to ~2 m. An unplanned LARGE obstacle at close range -- another airframe, a
        flock, a wall -- is a NAMED BLIND SPOT, and no bar on the 85-frame dataset can see it."""
        wall = disc(sky(), 320.0, 240.0, 150.0, 8.0)       # 300 px, flat, sky-backed
        self.assertEqual(boxes_of(wall), [], "a closing preserves a wide pit; step is 0 across it")
        canopy_near = sds.analytic_sphere(INTR, 320.0, 240.0, 1.3, 20.0)
        self.assertEqual(boxes_of(canopy_near), [], "a 1.3 m canopy at 20 m (68 px) is invisible")
        canopy_far = sds.analytic_sphere(INTR, 320.0, 240.0, 1.3, 40.0)
        self.assertTrue(boxes_of(canopy_far), "the same canopy at 40 m (34 px) does return")

    def test_the_bird_ladder_has_no_hole_from_46_m_down_to_2_m(self):
        """The near-field counterpart of the blind-spot test above, and the reason it is survivable:
        the 0.18 m target this world actually contains stays detectable at every range swept, as one
        component to ~10 m and as rim arcs at its own correct depth below that."""
        for r in (46.0, 30.0, 20.0, 14.0, 12.0, 10.0, 8.0, 6.0, 4.0, 2.0):
            got = boxes_of(sds.analytic_sphere(INTR, 320.0, 240.0, BIRD_R_M, r))
            self.assertTrue(got, f"NO detection of a 0.18 m sphere at {r} m -- a false negative")
            self.assertLess(abs(min(d for _, d in got) - (r - BIRD_R_M)), 0.25, f"at {r} m")
            self.assertEqual(len(got), 1 if r >= 10.0 else 4,
                             f"at {r} m: whole below the crossover, four rim arcs above it")

    def test_boxes_agree_with_detect_blobs_box_for_box_on_a_shared_mask(self):
        """The two detectors' boxes must MEAN the same thing (half-open, x=column, y=row), which is
        what lets one policy consume both. Coupled by convention, not by code."""
        rng = np.random.default_rng(20260907)
        mask = np.zeros((480, 640), dtype=bool)
        for _ in range(12):
            y, x = int(rng.integers(20, 440)), int(rng.integers(20, 600))
            # Kept under K on purpose: a patch as wide as the structuring element is FILLED by the
            # closing and produces no candidates at all (see the blind-spot test above), which
            # would make this a test of the operator rather than of the box convention.
            h, w = int(rng.integers(4, 12)), int(rng.integers(4, 12))
            mask[y:y + h, x:x + w] = True
        z = np.where(mask, np.float32(20.0), np.float32(np.inf)).astype(np.float32)
        mine = sorted([tuple(b) for b, _ in boxes_of(z, min_area_px=1, max_boxes=999)])
        theirs = sorted(tuple(b) for b in detect_blobs(mask, 1, 10 ** 9, open_iter=0, close_iter=0))
        self.assertEqual(mine, theirs)


class TestLinkBreakAndMultipleObjects(unittest.TestCase):
    """Two near objects that touch in image space -- the case the 85-frame dataset never contains
    (every station has exactly one bird; birds 1 and 2 are parked out of the world) and the case
    CLAUDE.md's own MVP obstacle density is made of. It is also what decides `link_break`."""

    def _pair(self, half_w):
        z = sky()
        z[240:243, 320:320 + half_w] = np.float32(20.0)
        z[240:243, 320 + half_w:320 + 2 * half_w] = np.float32(30.0)
        return z

    def test_two_touching_objects_return_ONE_component_at_a_depth_belonging_to_NEITHER(self):
        """The fail-dangerous direction, and it is unmeasured by the render: 20 m beside 30 m comes
        back as 25 m, which is not a conservative rounding of 20 m -- it is a threat pushed 5 m out.
        The dataset's nearest analogue is the partial fusion at S042/S046, correct only because the
        bird holds 53 % of the component (artifact `metrics.median_flip_margin`)."""
        got = boxes_of(self._pair(4))
        self.assertEqual(len(got), 1, got)
        self.assertAlmostEqual(got[0][1], 25.0, places=3)

    def test_link_break_CAN_withhold_a_component_which_is_why_it_is_off(self):
        """`_link_break`'s docstring used to promise "SPLITS AND TAGS, NEVER WITHHOLDS", and the
        design note made that promise the CONDITION for keeping the rule at all. It is falsifiable
        in one construction: cutting the seam costs pixels, and two adjacent small objects can both
        drop below `min_area_px`. Pinned rather than assumed, because the corrected merge metric
        removed the OTHER reason the rule was rejected -- so this is now the load-bearing one."""
        got = boxes_of(self._pair(4), link_break=True)
        self.assertEqual(got, [], "the pair survived the cut -- re-open the link_break decision")
        seg = DepthSegmenter(params_with(DEFAULT_PARAMS, link_break=True))
        seg(self._pair(4))
        self.assertEqual(seg.counters()["components_below_min_area"], 2)
        self.assertGreater(seg.counters()["link_cut_px"], 0)

    def test_the_withholding_is_an_INTERACTION_with_min_area_not_a_defect_of_the_cut(self):
        """Give both halves enough pixels to clear the floor and the rule does exactly what it
        promises. This is what makes the honest guarantee 'withholds no component still larger than
        min_area_px after the cut' rather than 'the link break deletes things'."""
        got = boxes_of(self._pair(20), link_break=True)
        self.assertEqual([round(d, 3) for _, d in got], [20.0, 30.0])


class TestDeterminism(unittest.TestCase):
    def test_same_bytes_in_same_list_out(self):
        z = disc(ramp(), 320.0, 400.0, 6.0, 20.0)
        self.assertEqual(repr(DepthSegmenter(DEFAULT_PARAMS)(z)),
                         repr(DepthSegmenter(DEFAULT_PARAMS)(z)))

    def test_no_frame_to_frame_state_so_station_ORDER_cannot_change_a_score(self):
        a = disc(ramp(), 320.0, 400.0, 6.0, 20.0)
        b = disc(sky(), 100.0, 100.0, 4.0, 30.0)
        seg = DepthSegmenter(DEFAULT_PARAMS)
        first = repr(seg(a))
        seg(b)
        self.assertEqual(repr(seg(a)), first)


class TestMaskMutation(unittest.TestCase):
    """DESIGN §4.5 item 3, run on the SAME canned frame the committed artifact records."""

    def setUp(self):
        self.frame, self.meta = sds.mutation_canned_frame(INTR)
        self.intact = DepthSegmenter(DEFAULT_PARAMS)(self.frame)

    def _mutant(self, *drop):
        kept = tuple(t for t in MASK_TERMS if t not in drop)
        return DepthSegmenter(DEFAULT_PARAMS, _mask_terms=kept)(self.frame)

    def test_the_intact_mask_finds_exactly_the_bird_and_nothing_else(self):
        self.assertEqual(len(self.intact), 1, self.intact)
        self.assertAlmostEqual(self.intact[0][1], self.meta["bird_depth_m"], places=3)

    def test_mutation_dropping_step_over_margin_turns_the_whole_ground_band_into_one_blob(self):
        got = self._mutant("step_over_margin")
        self.assertNotEqual(repr(got), repr(self.intact))
        self.assertGreater(max((b[2] - b[0]) * (b[3] - b[1]) for b, _ in got), 50000,
                           "without the discontinuity test the ground band IS the detection")

    def test_mutation_dropping_the_clip_window_detects_the_60m_clamp_signature(self):
        got = self._mutant("clip_window")
        self.assertNotEqual(repr(got), repr(self.intact))
        self.assertTrue(any(abs(d - self.meta["clamp_patch_depth_m"]) < 1e-3 for _, d in got),
                        f"expected a component at exactly the far clip plane, got {got}")

    def test_mutation_dropping_isfinite_ALONE_is_a_measured_NO_OP_and_the_PAIR_is_what_is_red(self):
        """The pre-registered expectation was three independent conjuncts. The measurement says
        TWO: the EXCLUSIVE clip window already rejects every non-finite value, because
        `-inf > near_m`, `+inf < far_m` and every NaN comparison are all False. Pinned as an
        executable fact so nobody counts `isfinite` as a second, independent safeguard -- and so
        that the day the window stops being exclusive at both ends, this test goes red and says
        why."""
        self.assertEqual(repr(self._mutant("isfinite")), repr(self.intact))
        pair = self._mutant("isfinite", "clip_window")
        self.assertNotEqual(repr(pair), repr(self.intact))
        x0, y0, x1, y1 = self.meta["neg_inf_patch_px"]
        self.assertTrue(any(b[0] >= x0 - 1 and b[2] <= x1 + 1 and b[1] >= y0 - 1 and b[3] <= y1 + 1
                            for b, _ in pair),
                        f"the -inf patch should return as a candidate once BOTH terms go: {pair}")


class TestInputRefusals(unittest.TestCase):
    def test_non_ndarray_raises(self):
        with self.assertRaises(TypeError):
            DepthSegmenter(DEFAULT_PARAMS)([[1.0, 2.0], [3.0, 4.0]])

    def test_non_float32_raises_because_a_uint16_millimetre_encoding_must_not_be_coerced(self):
        for dtype in (np.float64, np.uint16, np.int32):
            with self.assertRaises(TypeError):
                DepthSegmenter(DEFAULT_PARAMS)(np.zeros((8, 8), dtype=dtype))

    def test_non_2d_raises(self):
        for shape in ((8,), (2, 8, 8), (1, 2, 3, 4)):
            with self.assertRaises(ValueError):
                DepthSegmenter(DEFAULT_PARAMS)(np.zeros(shape, dtype=np.float32))

    def test_params_are_validated_at_construction(self):
        bad = [dict(bg_window_px=16), dict(bg_window_px=1), dict(margin_m=0.0),
               dict(margin_m=-1.0), dict(min_area_px=0), dict(open_iter=-1), dict(max_boxes=0),
               dict(near_m=0.0), dict(near_m=61.0)]
        for kw in bad:
            with self.assertRaises(ValueError, msg=kw):
                params_with(DEFAULT_PARAMS, **kw)

    def test_the_segmenter_refuses_anything_that_is_not_the_frozen_params_object(self):
        with self.assertRaises(TypeError):
            DepthSegmenter({"bg_window_px": 15})
        with self.assertRaises(ValueError):
            DepthSegmenter(DEFAULT_PARAMS, _mask_terms=("isfinite", "not_a_term"))


class TestAdoptedConstants(unittest.TestCase):
    def test_the_clip_window_is_the_SEAMS_window_and_there_is_one_number_not_two(self):
        """`DepthDetectionSource` refuses depths outside its own exclusive window and counts them.
        If the two windows drifted apart the segmenter would hand up boxes it knows will be
        rejected -- or, worse, keep pixels the seam would refuse."""
        src = DepthDetectionSource(lambda f: [])
        self.assertEqual((DEFAULT_PARAMS.near_m, DEFAULT_PARAMS.far_m),
                         (src.min_range_m, src.max_range_m))

    def test_the_defaults_carry_the_artifact_that_chose_them(self):
        self.assertIn("depth_segmenter_score_", DEFAULT_PARAMS_PROVENANCE)
        self.assertIn("depth_dataset_20260907", DEFAULT_PARAMS_PROVENANCE)
        for field in ("bg_window_px", "margin_m", "min_area_px", "open_iter", "max_boxes",
                      "link_break"):
            self.assertIn(field, DEFAULT_PARAMS_PROVENANCE,
                          f"{field} has no stated provenance -- it is then a number someone typed")

    def test_open_iter_zero_ships_and_an_opening_can_only_COST_pixels_on_the_smallest_target(self):
        """`open_iter` was scored both ways on the dataset and came out IDENTICAL, so this pins the
        reason 0 ships anyway rather than claiming a measurement that was not made: `min_area_px`
        already does speck rejection with one knob instead of two, and an opening can only remove
        pixels -- from the 12-px footprint at 46 m, which is where the horizon is set.

        Measured on the real 46 m fixture, not on a synthetic disc: the render's antialiased plus
        is not the shape a filled disc makes, and inheriting `ndvi_detect`'s morphology on the basis
        of a synthetic shape is exactly the assumption ADR-020 am. 1 open item 3 flagged."""
        self.assertEqual(DEFAULT_PARAMS.open_iter, 0)
        path = FIXTURES / "S015.npz"
        if not path.exists():
            self.fail(f"missing regression fixture {path}")
        with np.load(path, allow_pickle=False) as d:
            frame = d["depth"]
        cand = np.isfinite(frame) & (frame > 40.0) & (frame < 50.0)
        raw = int(cand.sum())
        self.assertGreaterEqual(raw, 12, "the 46 m bird should be ~12 raw pixels")
        opened = ndimage.binary_opening(cand,
                                        structure=ndimage.generate_binary_structure(2, 1))
        self.assertLessEqual(int(opened.sum()), raw)
        self.assertEqual(len(DepthSegmenter(DEFAULT_PARAMS)(frame)) >= 1, True)
        with_open = DepthSegmenter(params_with(DEFAULT_PARAMS, open_iter=1))(frame)
        near = [d for _, d in with_open if 45.0 < d < 47.0]
        self.assertTrue(near, "open_iter=1 lost the 46 m bird on the real frame -- if this ever "
                              "fires, the sweep's 'identical' result has stopped being true")


class TestSeamOnARealFrame(unittest.TestCase):
    """The live gate: the adopted segmenter, the real seam, a REAL rendered frame -- not a synthetic
    fixture. `S015` is a 0.18 m bird at 46.0 m down the worst-clutter orchard lane."""

    FIXTURE = "S015"

    def setUp(self):
        path = FIXTURES / f"{self.FIXTURE}.npz"
        if not path.exists():
            self.fail(f"missing regression fixture {path} -- it is written by "
                      f"eval/score_depth_segmenter.py and is the thing that makes this a gate on a "
                      f"real render rather than on synthetic frames")
        with np.load(path, allow_pickle=False) as d:
            self.frame = d["depth"]
            self.meta = json.loads(str(d["meta"]))
        k = self.meta["intrinsics"]
        self.intr = CameraIntrinsics(width_px=k["width_px"], height_px=k["height_px"],
                                     fx=k["fx"], fy=k["fy"], cx=k["cx"], cy=k["cy"])

    def test_the_seam_returns_a_detection_at_the_birds_surveyed_world_position(self):
        src = DepthDetectionSource(DepthSegmenter(DEFAULT_PARAMS), intr=self.intr)
        dets = src.on_frame(12.5, self.frame, tuple(self.meta["vehicle_pos_enu"]),
                            tuple(self.meta["vehicle_quat_xyzw"]))
        self.assertTrue(dets, "no detection at all on a frame with a 46 m bird in it")
        truth = np.asarray(self.meta["bird_enu"], dtype=float)
        best = min(dets, key=lambda d: np.linalg.norm(np.asarray(d.position_enu) - truth))
        err = float(np.linalg.norm(np.asarray(best.position_enu) - truth))
        # The estimate is the component's MEDIAN depth, i.e. the bird's near surface plus a few cm,
        # so it lands ~0.18 m in front of the centre -- named and bounded, not hidden.
        self.assertLess(err, 0.30, f"{best.position_enu} vs {truth} = {err:.3f} m")
        self.assertGreater(err, 0.05, "an error of zero would mean the label leaked into the answer")
        self.assertEqual(best.source, "depth_blob")
        self.assertEqual(best.stamp_s, 12.5)
        self.assertIsNone(best.track_id)
        self.assertIsNone(best.static_map_hint)

    def test_no_ground_plane_projection_is_ever_reached(self):
        """ADR-009 rule 1, made executable: `pixel_to_ground_enu` answers 'where does this ray meet
        the ground', which puts a flying bird at z=0 -- 15 m below ownship and outside the policy's
        +/-6 m threat cylinder. A real threat, silently suppressed."""
        original = ndvi_georef.pixel_to_ground_enu

        def explode(*_a, **_k):
            raise AssertionError("pixel_to_ground_enu was called on the depth path (ADR-009 rule 1)")

        ndvi_georef.pixel_to_ground_enu = explode
        try:
            src = DepthDetectionSource(DepthSegmenter(DEFAULT_PARAMS), intr=self.intr)
            dets = src.on_frame(1.0, self.frame, tuple(self.meta["vehicle_pos_enu"]),
                                tuple(self.meta["vehicle_quat_xyzw"]))
        finally:
            ndvi_georef.pixel_to_ground_enu = original
        self.assertTrue(dets)
        self.assertTrue(all(d.position_enu[2] > 5.0 for d in dets if
                            abs(d.position_enu[2] - self.meta["bird_enu"][2]) < 1.0))

    def test_the_negative_control_frame_puts_nothing_in_the_threat_band(self):
        """The other half of the same gate, on the same pose: S061 is the P1 lane with NO bird in
        the world. Everything the segmenter finds there is canopy, and every one of them
        un-projects BELOW the geofence top -- so nothing enters the +/-6 m band around cruise."""
        path = FIXTURES / "S061.npz"
        if not path.exists():
            self.fail(f"missing regression fixture {path}")
        with np.load(path, allow_pickle=False) as d:
            frame, meta = d["depth"], json.loads(str(d["meta"]))
        src = DepthDetectionSource(DepthSegmenter(DEFAULT_PARAMS), intr=self.intr)
        dets = src.on_frame(1.0, frame, tuple(meta["vehicle_pos_enu"]),
                            tuple(meta["vehicle_quat_xyzw"]))
        self.assertTrue(dets, "the cluttered lane should produce canopy detections, not silence")
        self.assertTrue(all(d.position_enu[2] <= 4.8 for d in dets),
                        sorted(round(d.position_enu[2], 2) for d in dets)[-3:])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
