"""The ADR-003 amendment-6 gate, run against the REAL flagship clip — not a fixture.

`eval/results/clips/real_flight_20260822T215516Z/{poses.jsonl,meta.json}` and the driver sidecar
`eval/results/bird_drive_20260822T215608Z.json` are committed evidence (see .gitignore's evidence
exceptions), so the clip that produced the defect is the clip these tests run on. Frames are not
committed, so the 22 NDVI-direct detections that clip produced are pinned below as literals,
transcribed from `eval/results/adr003_20260822/detections_ndvi.json` (thresh -0.61, min_area 6,
max_area 5000 — the run recorded in ADR-003 amendment 5).

What is pinned here is the DIAGNOSIS, both halves, because a fix that moved the labels somewhere
else entirely would also make half of it pass:

  1. The detections ARE the birds. Every one of the 22 boxes matches a scripted bird's projected
     apparent size to within 4 px at the depth that bird was at, once the bird is placed at a
     trajectory time 0.1-0.9 s BEFORE the frame's own stamp. A soil artifact does not do that
     22 times on a 1-D trajectory curve.
  2. The MODELLED labels are not. At the frame's own stamp — what `pose_at(stamp - t0)` gives, the
     only thing available without the driver's applied-pose log — the closest any bird projects to
     any detection is 94.98 px (mean 198, max 313 for the correctly-assigned bird), and IoU is
     0.000 on all 22. IoU >= 0.3 needs a centre within ~0.4 of a box width: 8-19 px. So the harness
     must refuse to score, and it does.

If a future change makes 1 fail, the "these are birds" claim in ADR-003 amendment 6 is wrong and
the amendment must be revisited. If 2 starts passing (labels landing on the birds) it will be
because a real applied-pose log arrived — at which point this test should be re-pointed at that
clip, not deleted.

Stdlib + the project's own projection primitive. No numpy, no frames, ~1 s.
"""
import json
import math
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "eval"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "spike"))

import annotate_real_clip as arc  # noqa: E402
import label_from_sim  # noqa: E402
import score  # noqa: E402
from drive_birds import pose_at  # noqa: E402
from fieldguard_planning.ndvi_georef import CameraIntrinsics, project_world_point  # noqa: E402

CLIP = REPO_ROOT / "eval/results/clips/real_flight_20260822T215516Z"
SIDECAR = REPO_ROOT / "eval/results/bird_drive_20260822T215608Z.json"
BIRDS_CONFIG = REPO_ROOT / "config/birds/farm_world_birds.json"

# eval/results/adr003_20260822/detections_ndvi.json — the 18 frames the NDVI-direct baseline fired
# on, and nothing else fired anywhere in the other 917 frames.
DETECTIONS = {
    331: [[487.0, 3.0, 515.0, 32.0]],
    332: [[342.0, 6.0, 368.0, 35.0], [347.0, 222.0, 392.0, 267.0]],
    333: [[105.0, 225.0, 153.0, 270.0]],
    392: [[564.0, 271.0, 588.0, 292.0]],
    393: [[517.0, 369.0, 539.0, 391.0]],
    394: [[400.0, 364.0, 421.0, 385.0]],
    395: [[538.0, 417.0, 567.0, 445.0], [357.0, 463.0, 377.0, 479.0]],
    396: [[392.0, 413.0, 418.0, 441.0], [241.0, 462.0, 262.0, 479.0]],
    397: [[252.0, 196.0, 278.0, 222.0], [126.0, 463.0, 148.0, 479.0]],
    398: [[112.0, 195.0, 140.0, 221.0]],
    455: [[574.0, 71.0, 598.0, 94.0]],
    456: [[457.0, 82.0, 479.0, 104.0]],
    457: [[420.0, 187.0, 441.0, 207.0]],
    458: [[306.0, 190.0, 326.0, 211.0]],
    459: [[263.0, 286.0, 283.0, 307.0]],
    460: [[147.0, 286.0, 169.0, 307.0]],
    461: [[105.0, 386.0, 127.0, 407.0]],
    462: [[1.0, 387.0, 16.0, 408.0]],
}

LAG_SEARCH_S = [i / 200.0 for i in range(20, 181)]  # 0.10 .. 0.90 s, 5 ms steps


def centre(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


class RealClipFixture:
    """Loaded once — reading 935 pose lines per test would dominate the runtime."""

    def __init__(self):
        meta = json.loads((CLIP / "meta.json").read_text())
        self.intr = CameraIntrinsics.from_meta(meta["camera"])
        self.mount = tuple(meta["camera_extrinsic"]["offset_from_drone_m"])
        self.t0 = json.loads(SIDECAR.read_text())["t0_sim_s"]
        self.birds = json.loads(BIRDS_CONFIG.read_text())["birds"]
        self.lines = {}
        for raw in (CLIP / "poses.jsonl").read_text().splitlines():
            if raw.strip():
                d = json.loads(raw)
                self.lines[d["frame_id"]] = d

    def project(self, bird, t_traj_s, line):
        """(centre_u, centre_v, diameter_px) for `bird` at trajectory time `t_traj_s`, seen from
        the frame's own recorded drone pose — the project's one projection primitive."""
        wq, xq, yq, zq = line["drone"]["quat_wxyz"]
        x, y, z, _yaw = pose_at(t_traj_s, bird["waypoints"], bird.get("loop", True))
        p = project_world_point((x, y, z), tuple(line["drone"]["pos_m"]), (xq, yq, zq, wq),
                                self.intr, self.mount)
        if p is None:
            return None
        u, v, zc = p
        return (u, v, 2.0 * self.intr.fx * bird["physical_radius_m"] / zc)


FIX = RealClipFixture()


class TestTheDetectionsAreBirdsAtALaggedTime(unittest.TestCase):
    def test_every_detection_matches_a_bird_at_a_lagged_trajectory_time(self):
        worst_resid, lags = 0.0, []
        for fid, boxes in sorted(DETECTIONS.items()):
            line = FIX.lines[fid]
            t_nominal = line["stamp_sim_s"] - FIX.t0
            for box in boxes:
                dcx, dcy = centre(box)
                det_size = max(box[2] - box[0], box[3] - box[1])
                best = None
                for bird in FIX.birds:
                    for lag in LAG_SEARCH_S:
                        proj = FIX.project(bird, t_nominal - lag, line)
                        if proj is None or abs(proj[2] - det_size) > 4.0:
                            continue          # wrong apparent size for that depth: not this bird
                        d = math.hypot(proj[0] - dcx, proj[1] - dcy)
                        if best is None or d < best[0]:
                            best = (d, bird["bird_id"], lag)
                self.assertIsNotNone(best, f"frame {fid} box {box} matches no bird at any lag")
                self.assertLess(best[0], 20.0,
                                f"frame {fid} box {box}: best {best[1]} at lag {best[2]:.3f}s is "
                                f"still {best[0]:.1f} px away")
                worst_resid = max(worst_resid, best[0])
                lags.append(best[2])
        self.assertEqual(len(lags), 22)
        # The lag is a real, bounded, one-sided quantity — the render is always BEHIND the label,
        # never ahead. Bounds are the measured spread, kept loose enough not to pin fit noise.
        self.assertGreater(min(lags), 0.10)
        self.assertLess(max(lags), 0.90)
        self.assertLess(worst_resid, 20.0)

    def test_the_lag_is_not_a_fixed_image_offset(self):
        """Falsifies the cheap alternative: a constant mis-registration (bad principal point, bad
        mount) would put every GT box the SAME vector from its detection. The scatter about the
        mean vector is measured at ~200 px — an order of magnitude larger than the mean itself."""
        vectors = []
        for fid, boxes in sorted(DETECTIONS.items()):
            line = FIX.lines[fid]
            t_nominal = line["stamp_sim_s"] - FIX.t0
            for box in boxes:
                dcx, dcy = centre(box)
                det_size = max(box[2] - box[0], box[3] - box[1])
                cands = [FIX.project(b, t_nominal, line) for b in FIX.birds]
                cands = [c for c in cands if c is not None and abs(c[2] - det_size) <= 6.0]
                if not cands:
                    continue
                best = min(cands, key=lambda c: math.hypot(c[0] - dcx, c[1] - dcy))
                vectors.append((best[0] - dcx, best[1] - dcy))
        mx = sum(v[0] for v in vectors) / len(vectors)
        my = sum(v[1] for v in vectors) / len(vectors)
        scatter = math.sqrt(sum((v[0] - mx) ** 2 + (v[1] - my) ** 2 for v in vectors) / len(vectors))
        self.assertGreater(scatter, 100.0)
        self.assertGreater(scatter, 2.0 * math.hypot(mx, my))


class TestModelledLabelsCannotBeScored(unittest.TestCase):
    def test_modelled_labels_miss_every_detection_by_more_than_a_bird(self):
        """The number that justifies the guard: at the frame's OWN stamp the nearest bird lands
        94.98 px from the nearest detection — and IoU 0.3 needs a centre within 8-19 px."""
        worst_iou, closest = 0.0, 1e9
        for fid, boxes in sorted(DETECTIONS.items()):
            line = FIX.lines[fid]
            t_nominal = line["stamp_sim_s"] - FIX.t0
            for bird in FIX.birds:
                proj = FIX.project(bird, t_nominal, line)
                if proj is None:
                    continue
                u, v, dia = proj
                gt = [u - dia / 2, v - dia / 2, u + dia / 2, v + dia / 2]
                for box in boxes:
                    closest = min(closest, math.hypot(u - centre(box)[0], v - centre(box)[1]))
                    ix0, iy0 = max(gt[0], box[0]), max(gt[1], box[1])
                    ix1, iy1 = min(gt[2], box[2]), min(gt[3], box[3])
                    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
                    union = dia * dia + (box[2] - box[0]) * (box[3] - box[1]) - inter
                    worst_iou = max(worst_iou, inter / union if union else 0.0)
        self.assertGreater(closest, 90.0)     # measured 94.98 px, over every (bird, box) pair
        self.assertEqual(worst_iou, 0.0)

    def _annotate(self, tmp, extra_argv=()):
        clip = Path(tmp) / "clip"
        clip.mkdir()
        for name in ("poses.jsonl", "meta.json"):
            shutil.copy(CLIP / name, clip / name)
        rc = arc.main(["--clip", str(clip), "--sidecar", str(SIDECAR), "--in-place",
                       "--no-applied-log", *extra_argv])
        self.assertEqual(rc, 0)
        return clip

    def test_the_clip_annotates_as_spawn_then_modeled_and_the_chain_refuses(self):
        import contextlib
        import io
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                clip = self._annotate(tmp)
                gt, _ = label_from_sim.build_ground_truth(clip)
            counts = {}
            for f in gt["frames"]:
                for b in f["birds"]:
                    counts[b["label_src"]] = counts.get(b["label_src"], 0) + 1
            # 227 frames predate the driver (exact spawn pose); the other 708 are modelled.
            self.assertEqual(counts, {"spawn": 227 * 3, "modeled": 708 * 3})

            gt_by_fid = {f["frame_id"]: f for f in gt["frames"]}
            m = score.score(gt_by_fid, [{"frame_id": k, "boxes": v} for k, v in DETECTIONS.items()],
                            iou_thresh=0.3)
            # The evidence FLOOR clears — this is a clip with birds in frame, the first one — and
            # the verdict is still refused, on the labels rather than on the count.
            self.assertEqual(m["visible_bird_frames"], 10)
            self.assertEqual(m["birds_with_visible_frames"], 3)
            self.assertEqual(m["unscoreable_label_frames"], 10)
            self.assertEqual(m["TP"], 0)
            shortfall = score.evidence_shortfall(m, birds_in_clip=3)
            self.assertIn("modeled", shortfall)
            _lines, verdict = score.decide(m, m, birds_in_clip=3)
            self.assertIn("EVIDENCE INSUFFICIENT", verdict)


if __name__ == "__main__":
    unittest.main()
