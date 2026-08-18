"""Tests for the bird ground-truth path: scripts/drive_birds.py + eval/annotate_real_clip.py.

The gz service calls are exercised live in the container (runbook); what THESE tests pin is the
pure half of the same story — one interpolation shared by the driver that MOVES the birds and the
annotator that LABELS them afterwards:
  * `pose_at` — the piecewise-linear replacement for the SDF <actor><script> interpolation the birds
    lost when they became models (ADR-012). A subtle wrap/hold bug here silently changes the
    committed bird trajectories, which are safety-scenario inputs.
  * the run sidecar + `eval/annotate_real_clip.py` — a real recorded clip has no birds[]; its labels
    are reconstructed as pose_at(stamp_sim_s - t0_sim). The annotator's tests live here, next to the
    driver they must agree with, because "the label says the bird was there" and "the driver put the
    bird there" are the same claim.
Stdlib unittest, bare python.
"""
import contextlib
import io
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

from drive_birds import parse_sim_time_s, pose_at, set_pose_request, write_run_sidecar  # noqa: E402
import annotate_real_clip as arc  # noqa: E402

WPS = [
    {"t_s": 0.0, "x_m": 0.0, "y_m": 0.0, "z_m": 10.0, "yaw_deg": 0.0},
    {"t_s": 10.0, "x_m": 20.0, "y_m": 0.0, "z_m": 10.0, "yaw_deg": 90.0},
    {"t_s": 20.0, "x_m": 20.0, "y_m": 30.0, "z_m": 14.0, "yaw_deg": 90.0},
]

# Two birds with different (and differently-looping) paths, so a bug that labels every bird with
# bird_0's position, or that ignores per-bird `loop`, cannot pass.
BIRDS_CFG = {"birds": [
    {"bird_id": "bird_0", "physical_radius_m": 0.18, "loop": True, "waypoints": WPS},
    {"bird_id": "bird_1", "physical_radius_m": 0.25, "loop": False,
     "waypoints": [{"t_s": 0.0, "x_m": 5.0, "y_m": 30.0, "z_m": 11.0, "yaw_deg": 0.0},
                   {"t_s": 8.0, "x_m": 45.0, "y_m": 30.0, "z_m": 11.0, "yaw_deg": 0.0}]},
]}

# A real-recorder pose line (clip_recorder schema 1.1): the annotator must add birds[] and touch
# nothing else, including the honesty extras stitch_ndvi reads.
def pose_line(frame_id: int, stamp_sim_s: float) -> dict:
    return {"frame_id": frame_id, "t_s": round(stamp_sim_s - 100.0, 6),
            "drone": {"pos_m": [10.0 + frame_id, 20.0, 15.0],
                      "quat_wxyz": [1.0, 0.0, 0.0, 0.0]},
            "ndvi_path": f"frames/ndvi/frame_{frame_id:06d}.npy",
            "stamp_sim_s": stamp_sim_s, "pose_pair_residual_s": 0.01}


class TestPoseAt(unittest.TestCase):
    def test_exact_waypoints(self):
        self.assertEqual(pose_at(0.0, WPS), (0.0, 0.0, 10.0, 0.0))
        x, y, z, yaw = pose_at(10.0, WPS)
        self.assertEqual((x, y, z), (20.0, 0.0, 10.0))
        self.assertAlmostEqual(yaw, math.pi / 2)

    def test_midpoint_interpolates_all_channels(self):
        x, y, z, yaw = pose_at(5.0, WPS)
        self.assertAlmostEqual(x, 10.0)
        self.assertAlmostEqual(y, 0.0)
        self.assertAlmostEqual(z, 10.0)
        self.assertAlmostEqual(yaw, math.pi / 4)  # 45 deg, halfway to 90
        x, y, z, _ = pose_at(15.0, WPS)
        self.assertAlmostEqual((y, z)[0], 15.0)
        self.assertAlmostEqual(z, 12.0)

    def test_loop_wraps_modulo_last_time(self):
        # t=25 with loop -> t=5 (25 % 20): same pose as the t=5 midpoint
        self.assertEqual(pose_at(25.0, WPS, loop=True), pose_at(5.0, WPS))

    def test_no_loop_holds_last_waypoint(self):
        x, y, z, yaw = pose_at(999.0, WPS, loop=False)
        self.assertEqual((x, y, z), (20.0, 30.0, 14.0))
        self.assertAlmostEqual(yaw, math.pi / 2)

    def test_before_start_holds_first(self):
        self.assertEqual(pose_at(-3.0, WPS, loop=False), (0.0, 0.0, 10.0, 0.0))

    def test_empty_waypoints_raise(self):
        with self.assertRaises(ValueError):
            pose_at(0.0, [])


class TestParseSimTime(unittest.TestCase):
    """The sim-clock parse (RTF-proof timing — a wall-clock driver flies birds 1/RTF too fast on
    this software-rendered stack, where measured RTF << 1)."""

    def test_full_clock_message(self):
        txt = "system {\n  sec: 1\n}\nreal {\n  sec: 99\n  nsec: 5\n}\nsim {\n  sec: 123\n  nsec: 500000000\n}\n"
        self.assertAlmostEqual(parse_sim_time_s(txt), 123.5)

    def test_sim_block_without_nsec(self):
        self.assertEqual(parse_sim_time_s("sim {\n  sec: 42\n}"), 42.0)

    def test_missing_sim_block_returns_none(self):
        self.assertIsNone(parse_sim_time_s("real {\n  sec: 99\n}"))
        self.assertIsNone(parse_sim_time_s(""))


class TestSetPoseRequest(unittest.TestCase):
    def test_yaw_to_quaternion(self):
        req = set_pose_request("bird_0", (1.0, 2.0, 3.0, math.pi))  # 180 deg: z=1, w=0
        self.assertIn('name: "bird_0"', req)
        self.assertIn("z: 1.000000", req)
        self.assertIn("w: 0.000000", req)

    def test_zero_yaw_identity_quaternion(self):
        req = set_pose_request("bird_1", (0.0, 0.0, 0.0, 0.0))
        self.assertIn("z: 0.000000", req)
        self.assertIn("w: 1.000000", req)


def make_clip(tmp: Path, stamps, meta=None) -> Path:
    clip = tmp / "clip"
    clip.mkdir()
    (clip / "poses.jsonl").write_text(
        "".join(json.dumps(pose_line(i, s)) + "\n" for i, s in enumerate(stamps)))
    if meta is not None:
        (clip / "meta.json").write_text(json.dumps(meta))
    return clip


def write_cfg(tmp: Path) -> Path:
    path = tmp / "birds.json"
    path.write_text(json.dumps(BIRDS_CFG))
    return path


def run_cli(argv):
    """arc.main with the console swallowed -> (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = arc.main(argv)
    return rc, out.getvalue(), err.getvalue()


class TestRunSidecar(unittest.TestCase):
    """The sidecar exists so a recorded clip's bird labels don't depend on the scrollback of the
    terminal that started the driver — if it loses t0, the clip is unlabelable forever."""

    def test_records_anchor_rate_config_and_ids(self):
        with tempfile.TemporaryDirectory() as td:
            path = write_run_sidecar(Path(td), 152.44, 5.0, Path("/workspace/fieldguard/x.json"),
                                     ["bird_0", "bird_1"], "farmguard_field")
            self.assertTrue(path.name.startswith("bird_drive_") and path.name.endswith(".json"))
            side = json.loads(path.read_text())
            self.assertEqual(side["t0_sim_s"], 152.44)
            self.assertEqual(side["rate_hz"], 5.0)
            self.assertEqual(side["clock"], "sim")
            self.assertEqual(side["bird_ids"], ["bird_0", "bird_1"])
            self.assertEqual(side["config"], "/workspace/fieldguard/x.json")
            self.assertEqual(side["world"], "farmguard_field")

    def test_wall_clock_run_leaves_no_anchor_and_the_annotator_refuses_it(self):
        # Wall-clock mode has no sim t0 at all; inventing one would produce confident wrong labels.
        with tempfile.TemporaryDirectory() as td:
            path = write_run_sidecar(Path(td), None, 5.0, Path("x.json"), ["bird_0"], "w")
            side = json.loads(path.read_text())
            self.assertEqual(side["clock"], "wall")
            self.assertIsNone(side["t0_sim_s"])
            with self.assertRaises(ValueError):
                arc.t0_from_sidecar(side)


class TestAnnotateRealClip(unittest.TestCase):
    """Labels for a real clip = pose_at(stamp_sim_s - t0) — the driver's own interpolation, not a
    second copy of it."""

    def test_bird_positions_match_pose_at(self):
        lines = [pose_line(i, s) for i, s in enumerate([100.0, 105.5, 130.0])]
        annotated, stats = arc.annotate_lines(lines, BIRDS_CFG["birds"], 100.0)
        self.assertEqual(stats["n_frames"], 3)
        self.assertEqual([b["traj_t_s"] for b in annotated[1]["birds"]], [5.5, 5.5])
        # hand-computed at t=5.5s: bird_0 55% along leg 1 (0->20 in x), bird_1 68.75% of 5->45
        self.assertEqual(annotated[1]["birds"][0]["pos_m"], [11.0, 0.0, 10.0])
        self.assertEqual(annotated[1]["birds"][1]["pos_m"], [32.5, 30.0, 11.0])
        # t=30s: bird_0 loops (30 % 20 = 10 -> the second waypoint), bird_1 does not (holds last)
        self.assertEqual(annotated[2]["birds"][0]["pos_m"], [20.0, 0.0, 10.0])
        self.assertEqual(annotated[2]["birds"][1]["pos_m"], [45.0, 30.0, 11.0])
        for line in annotated:
            for entry, bird in zip(line["birds"], BIRDS_CFG["birds"]):
                x, y, z, _ = pose_at(entry["traj_t_s"], bird["waypoints"], bird.get("loop", True))
                self.assertEqual(entry["pos_m"], [round(x, 6), round(y, 6), round(z, 6)])

    def test_entries_carry_exactly_what_label_from_sim_requires(self):
        annotated, _ = arc.annotate_lines([pose_line(0, 101.0)], BIRDS_CFG["birds"], 100.0)
        entry = annotated[0]["birds"][0]
        self.assertEqual(set(entry), {"bird_id", "pos_m", "physical_radius_m", "traj_t_s"})
        self.assertEqual(entry["bird_id"], "bird_0")
        self.assertEqual(entry["physical_radius_m"], 0.18)          # from the config, per bird
        self.assertEqual(annotated[0]["birds"][1]["physical_radius_m"], 0.25)

    def test_existing_pose_fields_are_untouched(self):
        original = pose_line(7, 111.25)
        annotated, _ = arc.annotate_lines([dict(original)], BIRDS_CFG["birds"], 100.0)
        got = dict(annotated[0])
        got.pop("birds")
        self.assertEqual(got, original)  # frame_id, t_s, drone pose, ndvi_path, honesty extras

    def test_default_writes_a_sidecar_file_and_leaves_the_recording_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            clip = make_clip(tmp, [100.0, 100.2])
            before = (clip / "poses.jsonl").read_bytes()
            rc, out, _ = run_cli(["--clip", str(clip), "--bird-t0", "100.0",
                                  "--config", str(write_cfg(tmp))])
            self.assertEqual(rc, 0)
            self.assertEqual((clip / "poses.jsonl").read_bytes(), before)
            written = arc.read_poses(clip / "poses_annotated.jsonl")
            self.assertEqual(len(written), 2)
            self.assertEqual(len(written[0]["birds"]), 2)
            self.assertIn("--in-place", out)  # the next-step instructions

    def test_in_place_rewrites_the_recording(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            clip = make_clip(tmp, [100.0, 100.2])
            rc, _, _ = run_cli(["--clip", str(clip), "--bird-t0", "100.0",
                                "--config", str(write_cfg(tmp)), "--in-place"])
            self.assertEqual(rc, 0)
            self.assertFalse((clip / "poses_annotated.jsonl").exists())
            self.assertFalse((clip / "poses.jsonl.tmp").exists())  # atomic write cleaned up
            written = arc.read_poses(clip / "poses.jsonl")
            self.assertEqual([b["bird_id"] for b in written[0]["birds"]], ["bird_0", "bird_1"])

    def test_sidecar_supplies_the_same_t0_as_the_flag(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            cfg = write_cfg(tmp)
            side = write_run_sidecar(tmp, 100.0, 5.0, cfg, ["bird_0", "bird_1"], "farmguard_field")
            clip = make_clip(tmp, [103.0])
            run_cli(["--clip", str(clip), "--sidecar", str(side), "--config", str(cfg)])
            via_sidecar = arc.read_poses(clip / "poses_annotated.jsonl")[0]["birds"]
            via_flag, _ = arc.annotate_lines([pose_line(0, 103.0)], BIRDS_CFG["birds"], 100.0)
            self.assertEqual(via_sidecar, via_flag[0]["birds"])

    def test_missing_stamp_sim_s_refuses_rather_than_using_relative_t_s(self):
        line = pose_line(0, 100.0)
        del line["stamp_sim_s"]
        with self.assertRaises(ValueError) as ctx:
            arc.annotate_lines([line], BIRDS_CFG["birds"], 100.0)
        self.assertIn("stamp_sim_s", str(ctx.exception))

    def test_reannotating_replaces_birds_instead_of_appending(self):
        first, _ = arc.annotate_lines([pose_line(0, 108.0)], BIRDS_CFG["birds"], 100.0)
        second, stats = arc.annotate_lines(first, BIRDS_CFG["birds"], 100.0)
        self.assertEqual(len(second[0]["birds"]), 2)
        self.assertEqual(stats["n_replaced"], 1)
        self.assertEqual(second[0]["birds"], first[0]["birds"])

    def test_negative_trajectory_time_is_counted_and_warned_about(self):
        # t0 after the frame stamp = wrong sidecar. pose_at's modulo wrap would hand back a
        # confident wrong position (-20 % 20 == 0), so this has to be loud, not silent.
        _, stats = arc.annotate_lines([pose_line(0, 100.0)], BIRDS_CFG["birds"], 120.0)
        self.assertEqual(stats["n_negative_t"], 1)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            clip = make_clip(tmp, [100.0])
            _, _, err = run_cli(["--clip", str(clip), "--bird-t0", "120.0",
                                 "--config", str(write_cfg(tmp))])
            self.assertIn("NEGATIVE", err)

    def test_synthetic_clip_is_warned_about(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            clip = make_clip(tmp, [100.0], meta={"synthetic": True})
            _, _, err = run_cli(["--clip", str(clip), "--bird-t0", "100.0",
                                 "--config", str(write_cfg(tmp))])
            self.assertIn("synthetic", err)

    def test_default_config_is_the_committed_farm_world_birds(self):
        """Driver and annotator must label from the SAME file the world was generated from."""
        birds = arc.load_birds(arc.DEFAULT_BIRDS_CONFIG)
        self.assertEqual([b["bird_id"] for b in birds], ["bird_0", "bird_1", "bird_2"])
        for b in birds:
            self.assertIn("physical_radius_m", b)
            self.assertTrue(b["waypoints"])


if __name__ == "__main__":
    unittest.main()
