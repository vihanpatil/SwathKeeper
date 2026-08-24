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

from drive_birds import (  # noqa: E402
    AppliedLogWriter, applied_log_path_for, applied_record, applied_sim_brackets, parse_sim_time_s,
    pose_at, read_applied_log, set_pose_request, write_run_sidecar,
)
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

    def test_before_start_holds_the_spawn_pose_even_when_looping(self):
        """The wrap is FORWARD-ONLY. A static bird sits at waypoints[0] from world load until the
        driver's first set_pose (ADR-012 amendment 1), so a negative t_s must hold the spawn pose
        for a looping bird too. t=-15 is the pin: `-15 % 20 == 5` in Python, so the old unguarded
        modulo teleported it to the t=5 midpoint (10, 0, 10) -- a confident, wrong position."""
        spawn = (0.0, 0.0, 10.0, 0.0)
        self.assertEqual(pose_at(-15.0, WPS, loop=True), spawn)
        self.assertEqual(pose_at(-15.0, WPS, loop=False), spawn)
        self.assertEqual(pose_at(-1e4, WPS, loop=True), spawn)  # no far-past decay either
        self.assertEqual(pose_at(0.0, WPS, loop=True), spawn)   # the boundary belongs to the hold

    def test_the_two_ends_are_deliberately_asymmetric(self):
        """Near end clamps, far end does NOT -- because the driver keeps ticking pose_at with the
        same `loop` flag forever, so past the span it really does wrap (or hold last). Clamping the
        far end would invent a stop the sidecar does not record."""
        self.assertEqual(pose_at(25.0, WPS, loop=True), pose_at(5.0, WPS))          # wraps
        self.assertNotEqual(pose_at(25.0, WPS, loop=True), pose_at(0.0, WPS))       # ...not clamped
        self.assertEqual(pose_at(999.0, WPS, loop=False), pose_at(20.0, WPS, loop=False))

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


def applied(bird_id, t_traj, pos, ok=True, tick_sim=None, tick_wall=0.0,
            start=None, end=None):
    """One applied-pose record, with the timestamps spelled out at the call site."""
    return applied_record(bird_id, t_traj, (pos[0], pos[1], pos[2], 0.0), ok, tick_sim, tick_wall,
                          tick_wall if start is None else start,
                          (tick_wall if start is None else start) + 0.05 if end is None else end)


class TestAppliedLog(unittest.TestCase):
    """The applied-pose log is the fix for ADR-003 amendment 6: without it a label says where the
    driver ASKED the bird to be, and the render was measured a mean 198 px away from that."""

    def test_log_path_is_derived_from_the_sidecar_it_belongs_to(self):
        self.assertEqual(applied_log_path_for(Path("/r/bird_drive_20260822T215608Z.json")).name,
                         "bird_drive_20260822T215608Z_applied.jsonl")

    def test_record_keeps_the_request_and_all_four_clocks(self):
        r = applied_record("bird_0", 12.5, (1.0, 2.0, 3.0, 0.5), True, 66.0, 100.0, 100.02, 100.19)
        self.assertEqual(r["bird_id"], "bird_0")
        self.assertEqual(r["t_traj_s"], 12.5)
        self.assertEqual(r["pos_m"], [1.0, 2.0, 3.0])
        self.assertTrue(r["ok"])
        self.assertEqual((r["tick_sim_s"], r["tick_wall_s"]), (66.0, 100.0))
        self.assertEqual((r["wall_start_s"], r["wall_end_s"]), (100.02, 100.19))

    def test_brackets_convert_wall_to_sim_at_the_MEASURED_rtf(self):
        """RTF is not 1 and not constant on this stack (0.94 pre-flight to 0.51 mid-lane on the
        flagship take), so the conversion uses the rate measured between consecutive tick anchors,
        never an assumed one."""
        recs = [applied("bird_0", 0.0, (0, 0, 0), tick_sim=100.0, tick_wall=0.0, start=0.1, end=0.3),
                applied("bird_0", 0.5, (1, 0, 0), tick_sim=100.5, tick_wall=1.0, start=1.1, end=1.3)]
        # tick 0 -> tick 1: 0.5 s of sim over 1.0 s of wall = RTF 0.5
        b0, b1 = applied_sim_brackets(recs)
        self.assertAlmostEqual(b0[0], 100.05)   # 100.0 + 0.1*0.5
        self.assertAlmostEqual(b0[1], 100.15)
        self.assertAlmostEqual(b1[0], 100.55)   # last tick reuses the last measured RTF
        self.assertAlmostEqual(b1[1], 100.65)

    def test_three_birds_in_one_tick_get_three_different_brackets(self):
        """The per-call latency is the point: on the flagship take the three birds' lags ordered by
        their position in the loop (0.12 / 0.38 / 0.42 s), i.e. one shared tick anchor is not
        enough to place them."""
        recs = [applied("bird_0", 0.0, (0, 0, 0), tick_sim=10.0, tick_wall=0.0, start=0.0, end=0.2),
                applied("bird_1", 0.0, (0, 0, 0), tick_sim=10.0, tick_wall=0.0, start=0.2, end=0.4),
                applied("bird_2", 0.0, (0, 0, 0), tick_sim=10.0, tick_wall=0.0, start=0.4, end=0.6),
                applied("bird_0", 1.0, (1, 0, 0), tick_sim=11.0, tick_wall=1.0, start=1.0, end=1.2)]
        ends = [b[1] for b in applied_sim_brackets(recs)]
        self.assertAlmostEqual(ends[0], 10.2)
        self.assertAlmostEqual(ends[1], 10.4)
        self.assertAlmostEqual(ends[2], 10.6)
        self.assertNotEqual(ends[0], ends[2])

    def test_single_tick_collapses_to_the_anchor_rather_than_inventing_a_rate(self):
        recs = [applied("bird_0", 0.0, (0, 0, 0), tick_sim=10.0, tick_wall=0.0, start=0.0, end=0.9)]
        self.assertEqual(applied_sim_brackets(recs), [(10.0, 10.0)])

    def test_wall_clock_run_records_have_no_sim_bracket_at_all(self):
        recs = [applied("bird_0", 0.0, (0, 0, 0), tick_sim=None, tick_wall=0.0)]
        self.assertEqual(applied_sim_brackets(recs), [None])

    def test_writer_appends_flushes_and_survives_an_unwritable_path(self):
        with tempfile.TemporaryDirectory() as td:
            w = AppliedLogWriter(Path(td) / "log.jsonl")
            w.write(applied("bird_0", 0.0, (0, 0, 0), tick_sim=1.0))
            # flushed per call: readable BEFORE close, because a Ctrl-C'd flight must keep its poses
            self.assertEqual(len(read_applied_log(w.path)), 1)
            w.write(applied("bird_1", 0.0, (0, 0, 0), tick_sim=1.0))
            w.close()
            self.assertEqual(w.written, 2)
            self.assertEqual([r["bird_id"] for r in read_applied_log(w.path)],
                             ["bird_0", "bird_1"])
        # A read-only mount must never stop a flight: the writer disables itself, silently to the
        # birds and loudly to stderr.
        dead = AppliedLogWriter(Path(td) / "gone" / "nested" / "log.jsonl")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            dead.write(applied("bird_0", 0.0, (0, 0, 0), tick_sim=1.0))
            dead.write(applied("bird_0", 0.1, (0, 0, 0), tick_sim=1.1))
        self.assertEqual(dead.written, 0)
        self.assertIn("applied-pose log disabled", err.getvalue())

    def test_truncated_final_line_costs_one_record_not_the_run(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "log.jsonl"
            good = json.dumps(applied("bird_0", 0.0, (0, 0, 0), tick_sim=1.0))
            p.write_text(good + "\n" + good + "\n" + good[:20])
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(len(read_applied_log(p)), 2)


class TestAppliedReplay(unittest.TestCase):
    """`applied_timeline` + `pose_from_applied` answer one question: what pose was the RENDERER
    showing at this frame's stamp? Not what the driver asked for at it."""

    def _timeline(self, recs):
        return arc.applied_timeline(recs)

    def test_pose_holds_between_applies_and_is_never_ahead_of_one(self):
        tl = self._timeline([
            applied("b", 0.0, (0, 0, 0), tick_sim=10.0, tick_wall=0.0, start=0.0, end=0.1),
            applied("b", 1.0, (5, 0, 0), tick_sim=11.0, tick_wall=1.0, start=1.0, end=1.1),
        ])["b"]
        self.assertEqual(arc.pose_from_applied(tl, 10.5)[0], (0.0, 0.0, 0.0))   # first still held
        self.assertEqual(arc.pose_from_applied(tl, 11.09)[0], (0.0, 0.0, 0.0))  # call in flight
        self.assertEqual(arc.pose_from_applied(tl, 11.2)[0], (5.0, 0.0, 0.0))   # landed

    def test_a_failed_call_means_the_bird_HELD_and_so_must_the_label(self):
        """16 set_pose calls failed on the flagship take. A failed call changed nothing in the
        render, so a label that moves the bird on it is a label of a bird that was never there."""
        tl = self._timeline([
            applied("b", 0.0, (0, 0, 0), tick_sim=10.0, tick_wall=0.0, start=0.0, end=0.1),
            applied("b", 1.0, (5, 0, 0), ok=False, tick_sim=11.0, tick_wall=1.0, start=1.0, end=1.1),
            applied("b", 2.0, (9, 0, 0), tick_sim=12.0, tick_wall=2.0, start=2.0, end=2.1),
        ])["b"]
        self.assertEqual(arc.pose_from_applied(tl, 11.5)[0], (0.0, 0.0, 0.0))   # held, not (5,0,0)
        self.assertEqual(arc.pose_from_applied(tl, 12.5)[0], (9.0, 0.0, 0.0))

    def test_before_the_first_landed_call_there_is_no_applied_pose(self):
        tl = self._timeline([
            applied("b", 0.0, (0, 0, 0), tick_sim=10.0, tick_wall=0.0, start=0.0, end=0.1)])["b"]
        self.assertIsNone(arc.pose_from_applied(tl, 9.0))

    def test_a_frame_inside_a_call_bracket_is_reported_ambiguous_not_rounded(self):
        tl = self._timeline([
            applied("b", 0.0, (0, 0, 0), tick_sim=10.0, tick_wall=0.0, start=0.0, end=0.1),
            applied("b", 1.0, (5, 0, 0), tick_sim=11.0, tick_wall=1.0, start=1.0, end=1.4),
        ])["b"]
        pos, _t, ambiguous = arc.pose_from_applied(tl, 11.2)   # request out, reply not back
        self.assertEqual(pos, (0.0, 0.0, 0.0))
        self.assertTrue(ambiguous)
        self.assertFalse(arc.pose_from_applied(tl, 11.5)[2])

    def test_failed_and_unclocked_records_never_enter_the_timeline(self):
        tl = self._timeline([
            applied("b", 0.0, (0, 0, 0), ok=False, tick_sim=10.0),
            applied("b", 1.0, (1, 0, 0), tick_sim=None, tick_wall=1.0),
            applied("b", 2.0, (2, 0, 0), tick_sim=12.0, tick_wall=2.0),
        ])
        self.assertEqual(len(tl["b"]), 1)

    def test_annotate_lines_labels_from_the_log_and_says_so(self):
        recs = [
            applied("bird_0", 0.0, (0, 0, 10), tick_sim=100.0, tick_wall=0.0, start=0.0, end=0.1),
            applied("bird_1", 0.0, (5, 30, 11), tick_sim=100.0, tick_wall=0.0, start=0.1, end=0.2),
            applied("bird_0", 5.0, (10, 0, 10), tick_sim=105.0, tick_wall=5.0, start=5.0, end=5.1),
            applied("bird_1", 5.0, (30, 30, 11), tick_sim=105.0, tick_wall=5.0, start=5.1, end=5.2),
        ]
        lines = [pose_line(0, 99.0), pose_line(1, 103.0), pose_line(2, 107.0)]
        out, stats = arc.annotate_lines(lines, BIRDS_CFG["birds"], 100.0,
                                        arc.applied_timeline(recs))
        # frame 0 predates every landed call -> the static spawn pose, and that is EXACT
        self.assertEqual([b["label_src"] for b in out[0]["birds"]], ["spawn", "spawn"])
        self.assertEqual(out[0]["birds"][0]["pos_m"], [0.0, 0.0, 10.0])
        # frame 1: the t=0 poses have landed, the t=5 ones have not -> held at t=0
        self.assertEqual([b["label_src"] for b in out[1]["birds"]], ["applied", "applied"])
        self.assertEqual(out[1]["birds"][1]["pos_m"], [5.0, 30.0, 11.0])
        self.assertEqual(out[1]["birds"][1]["traj_t_s"], 0.0)
        # frame 2: t=5 landed. The MODEL would have said pose_at(7.0) here — the whole bug.
        self.assertEqual(out[2]["birds"][0]["pos_m"], [10.0, 0.0, 10.0])
        self.assertNotEqual(out[2]["birds"][0]["pos_m"],
                            [round(c, 6) for c in pose_at(7.0, WPS)[:3]])
        self.assertEqual(stats["label_src_counts"], {"spawn": 2, "applied": 4, "modeled": 0})

    def test_without_a_log_every_post_t0_label_is_marked_modeled(self):
        out, stats = arc.annotate_lines([pose_line(0, 99.0), pose_line(1, 105.0)],
                                        BIRDS_CFG["birds"], 100.0)
        self.assertEqual([b["label_src"] for b in out[0]["birds"]], ["spawn", "spawn"])
        self.assertEqual([b["label_src"] for b in out[1]["birds"]], ["modeled", "modeled"])
        self.assertEqual(stats["label_src_counts"], {"spawn": 2, "applied": 0, "modeled": 2})

    def test_cli_auto_discovers_the_log_next_to_the_sidecar(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            clip = make_clip(tmp, [100.0, 105.0])
            sidecar = write_run_sidecar(tmp, 100.0, 2.0, write_cfg(tmp),
                                        ["bird_0", "bird_1"], "farmguard_field")
            log = applied_log_path_for(sidecar)
            log.write_text("".join(json.dumps(r) + "\n" for r in [
                applied("bird_0", 0.0, (0, 0, 10), tick_sim=100.0, tick_wall=0.0, end=0.1),
                applied("bird_1", 0.0, (5, 30, 11), tick_sim=100.0, tick_wall=0.0, end=0.1),
                applied("bird_0", 4.0, (8, 0, 10), tick_sim=104.0, tick_wall=4.0, start=4.0, end=4.1),
                applied("bird_1", 4.0, (25, 30, 11), tick_sim=104.0, tick_wall=4.0, start=4.0, end=4.1),
            ]))
            rc, out, err = run_cli(["--clip", str(clip), "--sidecar", str(sidecar),
                                    "--config", str(write_cfg(tmp))])
            self.assertEqual(rc, 0)
            self.assertIn("applied-pose log", out)
            self.assertNotIn("MODELED", err)
            written = arc.read_poses(clip / "poses_annotated.jsonl")
            self.assertEqual(written[1]["birds"][0]["pos_m"], [8.0, 0.0, 10.0])
            # ...and --no-applied-log reproduces the old modelled labelling, loudly
            rc, _out, err = run_cli(["--clip", str(clip), "--sidecar", str(sidecar),
                                     "--config", str(write_cfg(tmp)), "--no-applied-log"])
            self.assertEqual(rc, 0)
            self.assertIn("MODELED", err)

    def test_a_log_from_another_run_is_called_out_not_silently_replayed(self):
        """Holding the wrong log produces a full clip of confident spawn-pose labels — the same
        shape of quiet-wrong-answer the pre-driver lead-in note exists to catch."""
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            clip = make_clip(tmp, [100.0, 100.2])          # sim 100.0..100.2
            sidecar = write_run_sidecar(tmp, 100.0, 2.0, write_cfg(tmp),
                                        ["bird_0", "bird_1"], "farmguard_field")
            applied_log_path_for(sidecar).write_text("".join(json.dumps(r) + "\n" for r in [
                applied("bird_0", 0.0, (0, 0, 10), tick_sim=900.0, tick_wall=0.0, end=0.1),
                applied("bird_1", 0.0, (5, 30, 11), tick_sim=900.0, tick_wall=0.0, end=0.1),
                applied("bird_0", 1.0, (2, 0, 10), tick_sim=901.0, tick_wall=1.0, start=1.0, end=1.1),
            ]))
            rc, _out, err = run_cli(["--clip", str(clip), "--sidecar", str(sidecar),
                                     "--config", str(write_cfg(tmp))])
            self.assertEqual(rc, 0)
            self.assertIn("do not overlap", err)

    def test_a_bird_the_log_never_moved_is_called_out(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            clip = make_clip(tmp, [100.0, 105.0])
            sidecar = write_run_sidecar(tmp, 100.0, 2.0, write_cfg(tmp),
                                        ["bird_0", "bird_1"], "farmguard_field")
            applied_log_path_for(sidecar).write_text("".join(json.dumps(r) + "\n" for r in [
                applied("bird_0", 0.0, (0, 0, 10), tick_sim=100.0, tick_wall=0.0, end=0.1),
                applied("bird_0", 4.0, (8, 0, 10), tick_sim=104.0, tick_wall=4.0, start=4.0, end=4.1),
            ]))
            rc, _out, err = run_cli(["--clip", str(clip), "--sidecar", str(sidecar),
                                     "--config", str(write_cfg(tmp))])
            self.assertEqual(rc, 0)
            self.assertIn("bird_1", err)
            self.assertIn("no landed set_pose", err)
            written = arc.read_poses(clip / "poses_annotated.jsonl")
            self.assertEqual([b["label_src"] for b in written[1]["birds"]], ["applied", "spawn"])


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
        self.assertEqual(set(entry),
                         {"bird_id", "pos_m", "physical_radius_m", "traj_t_s", "label_src"})
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

    def test_pre_driver_frames_are_labelled_at_the_spawn_pose_and_still_counted(self):
        """The frames a clip records before the birds start moving (17/105 on the last real clip).
        They are labelled, not refused: both birds sit at waypoints[0] until the first set_pose.
        t0=115 puts the frame 15 s early -- the value the old modulo wrapped to the t=5 midpoint."""
        annotated, stats = arc.annotate_lines([pose_line(0, 100.0)], BIRDS_CFG["birds"], 115.0)
        self.assertEqual(stats["n_pre_driver_start"], 1)
        self.assertEqual(annotated[0]["birds"][0]["pos_m"], [0.0, 0.0, 10.0])   # bird_0, loop=True
        self.assertEqual(annotated[0]["birds"][1]["pos_m"], [5.0, 30.0, 11.0])  # bird_1, loop=False
        # The negative time is kept verbatim as provenance: it is what separates a spawn-pose label
        # from a genuine t=0 one when a human checks a line by hand.
        self.assertEqual([b["traj_t_s"] for b in annotated[0]["birds"]], [-15.0, -15.0])

    def test_pre_driver_frames_ship_with_a_note_not_a_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            clip = make_clip(tmp, [100.0])
            rc, _, err = run_cli(["--clip", str(clip), "--bird-t0", "115.0",
                                  "--config", str(write_cfg(tmp))])
            self.assertEqual(rc, 0)
            self.assertIn("SPAWN pose", err)
            self.assertNotIn("do not ship", err)
            # ...and the labels actually reached the file, which is what unblocks the ADR-003 re-run.
            written = arc.read_poses(clip / "poses_annotated.jsonl")
            self.assertEqual(written[0]["birds"][0]["pos_m"], [0.0, 0.0, 10.0])

    def test_a_missing_trajectory_config_still_refuses(self):
        """The clamp narrowed what counts as unlabelable; it must not have emptied it. No waypoint
        file means no ground truth at all -- there is nothing to clamp to."""
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(OSError):
                arc.load_birds(Path(td) / "does_not_exist.json")
            empty = Path(td) / "empty.json"
            empty.write_text(json.dumps({"birds": []}))
            with self.assertRaises(ValueError):
                arc.load_birds(empty)

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
