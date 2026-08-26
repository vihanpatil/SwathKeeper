"""`scripts/build_dashboard_data.py` — the dashboard's data pipeline, and its freshness pin.

TWO THINGS ARE PINNED HERE, and they fail for different reasons.

  * FRESHNESS. `dashboard/data/` is a COMMITTED COPY of derived and copied evidence, served
    statically off GitHub Pages. A committed copy that can go stale is exactly the shape of the
    2026-08-26 `spike_scores.json` drift (ADR-003 am. 10): two internally-consistent stale files
    agreed with each other for days while both disagreed with the source. So `--check` runs a full
    rebuild into a temp tree and byte-compares. If this test is red, the fix is one command —
    `python3 scripts/build_dashboard_data.py` — and the diff is the evidence that changed.

  * SCHEMA SANITY + PROVENANCE. The page renders whatever is in these files, so this suite asserts
    the shapes it relies on exist, that every declared source really is a byte-identical copy of the
    artifact it names, and — the load-bearing one — that the VERDICTS in the published tree are the
    gate's own. A dashboard that quietly published VALID for a flight the safety gate calls INVALID
    would be the single worst defect this page could have, so the verdict is re-derived here by
    calling `check_live_flight_log.check_file` directly and compared field by field.

Also pins the honesty invariants that are cheap to state and expensive to lose: the ledger and the
heatmaps live on the SAME canonical cell grid (they join by `cell_id`), the clip metadata carries the
airborne/painting denominators the ROADMAP insists on quoting instead of `num_frames`, and the
derived tree oracle reproduces `check_tree_positions.analyse` exactly.

Lives in tests/ (not tests/fieldguard_planning/) like test_ci_evidence_gate.py: it tests host-side
tooling and a committed artifact tree, not the planning package.
"""
import hashlib
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

import build_dashboard_data as BD  # noqa: E402
import check_live_flight_log as GATE  # noqa: E402
import check_tree_positions as TREES  # noqa: E402
from fieldguard_planning.coverage import DEFAULT_CELL_SIZE_M, build_grid, load_field_polygon  # noqa: E402

DATA = REPO_ROOT / "dashboard" / "data"


def load(rel):
    return json.loads((DATA / rel).read_text())


class TestFreshness(unittest.TestCase):
    """The committed tree must equal a fresh build, byte for byte."""

    def test_committed_data_matches_a_fresh_rebuild(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = BD.main(["--check"])
        self.assertEqual(rc, 0,
                         "dashboard/data/ is stale. Rerun `python3 scripts/build_dashboard_data.py` "
                         "and commit the result.\n" + err.getvalue())

    def test_build_is_idempotent(self):
        """Two builds over the same inputs produce identical bytes -- no timestamps, no ordering
        drift. Without this, --check would be a coin flip and the freshness pin would be noise."""
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            for d in (a, b):
                stage = Path(d) / "data"
                stage.mkdir()
                BD.build(stage)
            first = {str(p.relative_to(Path(a) / "data")): p.read_bytes()
                     for p in (Path(a) / "data").rglob("*") if p.is_file()}
            second = {str(p.relative_to(Path(b) / "data")): p.read_bytes()
                      for p in (Path(b) / "data").rglob("*") if p.is_file()}
            self.assertEqual(sorted(first), sorted(second))
            for rel in first:
                self.assertEqual(first[rel], second[rel], f"{rel} differs between two builds")

    def test_check_detects_a_tampered_file(self):
        """A negative control: the freshness pin must actually bite. Without it, a green --check
        would prove nothing (the gate that only ever passes is the gate nobody tested)."""
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "data"
            with redirect_stdout(io.StringIO()):
                BD.main(["--out", str(out)])
            victim = out / "verdicts.json"
            victim.write_text(victim.read_text().replace("INVALID", "VALID"))
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                rc = BD.main(["--out", str(out), "--check"])
            self.assertEqual(rc, 1)
            self.assertIn("verdicts.json", err.getvalue())


class TestProvenance(unittest.TestCase):
    """Every declared source is a real file, and every copy is byte-identical to it."""

    def test_manifest_sources_exist_and_hash_correctly(self):
        manifest = load("manifest.json")
        self.assertTrue(manifest["sources"], "manifest declares no sources")
        for src in manifest["sources"]:
            path = REPO_ROOT / src["path"]
            self.assertTrue(path.exists(), f"declared source missing: {src['path']}")
            blob = path.read_bytes()
            self.assertEqual(len(blob), src["bytes"], src["path"])
            self.assertEqual(hashlib.sha256(blob).hexdigest(), src["sha256"], src["path"])

    def test_flight_logs_and_markers_are_verbatim_copies(self):
        for stem in BD.FLIGHT_STEMS:
            src = BD.RESULTS / f"{stem}.json"
            self.assertEqual((DATA / "flights" / f"{stem}.json").read_bytes(), src.read_bytes(),
                             f"{stem}: published log is not a byte-identical copy")
            marker = GATE.marker_path_for(src)
            if marker.exists():
                self.assertEqual((DATA / "flights" / marker.name).read_bytes(), marker.read_bytes(),
                                 f"{stem}: published safety-finding marker differs from the source")

    def test_heatmaps_and_clip_meta_are_verbatim_copies(self):
        for name in BD.CLIP_NAMES:
            clip = BD.RESULTS / "clips" / name
            self.assertEqual((DATA / "clips" / name / "heatmap.json").read_bytes(),
                             (clip / "heatmap" / "heatmap.json").read_bytes(), name)
            self.assertEqual((DATA / "clips" / name / "meta.json").read_bytes(),
                             (clip / "meta.json").read_bytes(), name)

    def test_no_stray_files_in_the_published_tree(self):
        """Everything served must be something the build declares -- an orphan file under data/ is
        a byte a reader would take as evidence and nothing produced."""
        expected = set()
        for stem in BD.FLIGHT_STEMS:
            expected.add(f"flights/{stem}.json")
            marker = GATE.marker_path_for(BD.RESULTS / f"{stem}.json")
            if marker.exists():
                expected.add(f"flights/{marker.name}")
        for name in BD.CLIP_NAMES:
            expected |= {f"clips/{name}/heatmap.json", f"clips/{name}/meta.json",
                         f"clips/{name}/tree_check.json"}
        expected |= {"manifest.json", "field.json", "verdicts.json", "clips/index.json"}
        expected |= {f"truth/{s}.json" for s in load("verdicts.json")["flights"]
                     if (DATA / "truth" / f"{s}.json").exists()}
        actual = {str(p.relative_to(DATA)) for p in DATA.rglob("*") if p.is_file()}
        self.assertEqual(actual, expected)


class TestVerdictsArePublishedHonestly(unittest.TestCase):
    """The published verdict IS the gate's verdict -- re-derived here, not trusted."""

    def test_every_flight_verdict_matches_the_gate(self):
        published = load("verdicts.json")["flights"]
        self.assertEqual(sorted(published), sorted(BD.FLIGHT_STEMS))
        for stem, entry in published.items():
            status, messages = GATE.check_file(BD.RESULTS / f"{stem}.json")
            self.assertEqual(entry["verdict"], status, stem)
            self.assertEqual(entry["gate_messages"], list(messages), stem)
            self.assertEqual(entry["acknowledged_pin"], stem in GATE.ACKNOWLEDGED_BREACH_STEMS, stem)

    def test_the_20260825_take_is_published_as_the_failure_it_was(self):
        """The flagship take breached its own pre-registered bar. If this page ever softens that,
        the whole artifact is worthless as evidence -- so the shape of the failure is pinned."""
        e = load("verdicts.json")["flights"]["live_flight_log_20260825T210402Z"]
        self.assertEqual(e["verdict"], "INVALID")
        self.assertFalse(e["acknowledged_pin"], "a NEW breach must not be pinned as acknowledged")
        self.assertIn("marker", e, "the written finding must be published beside the log")
        cpa = e["cpa"]
        self.assertLess(cpa["gt_cpa_m"], cpa["bar_m"])
        self.assertLess(cpa["gt_cpa_gated_m"], cpa["gt_cpa_m"],
                        "the freeze debit must make the gated number worse, never better")
        self.assertEqual(cpa["bird_id"], "bird_0")
        self.assertTrue(any(GATE.CPA_BREACH_TAG in m for m in e["gate_messages"]))

    def test_historical_breaches_are_published_as_acknowledged_not_valid(self):
        published = load("verdicts.json")["flights"]
        for stem in GATE.ACKNOWLEDGED_BREACH_STEMS:
            if stem not in published:
                continue
            self.assertEqual(published[stem]["verdict"], "ACKNOWLEDGED", stem)
            self.assertTrue(published[stem]["acknowledged_pin"], stem)
            self.assertLess(published[stem]["cpa"]["cpa_m"], published[stem]["cpa"]["bar_m"], stem)

    def test_legacy_cpa_marker_position_reproduces_the_gate_value(self):
        """The page draws the CPA marker at a located point; the located minimum must BE the gate's
        number, or the picture and the verdict are measuring different things."""
        for stem, entry in load("verdicts.json")["flights"].items():
            cpa = entry["cpa"]
            if "segment_index" not in cpa:
                continue
            log = json.loads((BD.RESULTS / f"{stem}.json").read_text())
            self.assertEqual(cpa["cpa_m"], GATE.closest_approach(log)[0], stem)
            path = log["flown_path_enu"]
            self.assertLess(cpa["segment_index"], len(path) - 1, stem)


class TestSchemaSanity(unittest.TestCase):

    def test_field_grid_is_the_canonical_grid(self):
        field = load("field.json")
        grid = build_grid(load_field_polygon(), DEFAULT_CELL_SIZE_M)
        self.assertEqual([c["cell_id"] for c in field["cells"]], [c.cell_id for c in grid])
        self.assertEqual([[c["cx_m"], c["cy_m"]] for c in field["cells"]],
                         [[c.cx_m, c.cy_m] for c in grid])
        self.assertEqual(field["cell_size_m"], DEFAULT_CELL_SIZE_M)
        self.assertEqual(len(field["trees"]), 18)
        self.assertIn("boustrophedon", field["missions"])

    def test_ledgers_and_heatmaps_share_the_cell_grid(self):
        """The join the NDVI view makes by cell_id has to be total in both directions -- a heatmap
        cell with no ledger row (or the reverse) is a cell that could be silently skipped."""
        ids = {c["cell_id"] for c in load("field.json")["cells"]}
        for stem in BD.FLIGHT_STEMS:
            log = load(f"flights/{stem}.json")
            self.assertEqual({r["cell_id"] for r in log["coverage_ledger"]}, ids, stem)
            self.assertTrue(all(r["status"] in ("covered", "debt") for r in log["coverage_ledger"]),
                            f"{stem}: a non-terminal ledger status -- absence from the ledger IS the bug")
        for name in BD.CLIP_NAMES:
            self.assertEqual({c["cell_id"] for c in load(f"clips/{name}/heatmap.json")["cells"]}, ids, name)

    def test_clip_meta_carries_the_honest_frame_denominators(self):
        """The page must be able to quote airborne/painting rather than num_frames. If these keys
        ever disappear, the only counter left is the one the ROADMAP forbids quoting."""
        for name in BD.CLIP_NAMES:
            meta = load(f"clips/{name}/meta.json")
            heat = load(f"clips/{name}/heatmap.json")
            self.assertIn("airborne", meta)
            self.assertGreater(meta["airborne"]["frames"], 0)
            self.assertLessEqual(meta["airborne"]["frames"], meta["num_frames"])
            self.assertLessEqual(heat["frames_painting"], meta["airborne"]["frames"])

    def test_tree_oracle_reproduces_the_gate(self):
        for name in BD.CLIP_NAMES:
            fresh = TREES.analyse(BD.RESULTS / "clips" / name)
            published = load(f"clips/{name}/tree_check.json")
            for key in ("cells_imaged", "cells_total", "trees_imaged", "trees_canopy_grade",
                        "median_lift", "soil_modal_ndvi", "displaced_cells", "passed"):
                self.assertEqual(published[key], fresh[key], f"{name}.{key}")

    def test_airborne_window_is_derived_not_guessed(self):
        """The replay opens on the airborne window instead of a long parked prologue (40-52 % of the
        ticks on two of the three logs). The rule must be re-derivable and must not be a hand-picked
        tick, so it is recomputed here from the published path and compared field by field."""
        for stem, entry in load("verdicts.json")["flights"].items():
            path = load(f"flights/{stem}.json")["flown_path_enu"]
            self.assertEqual(entry["airborne"], BD.airborne_window(path), stem)
            air = entry["airborne"]
            self.assertTrue(air["found"], f"{stem}: no airborne window found in a flight log")
            self.assertEqual(air["z_threshold_m"], BD.AIRBORNE_Z_M)
            # the window is real: parked before it, flying inside it
            self.assertLessEqual(path[air["first_motion_tick"] - 2][2], BD.AIRBORNE_Z_M,
                                 f"{stem}: the tick before first_motion is already airborne")
            self.assertGreater(path[air["first_motion_tick"] - 1][2], BD.AIRBORNE_Z_M, stem)
            self.assertGreater(path[air["last_motion_tick"] - 1][2], BD.AIRBORNE_Z_M, stem)
            self.assertEqual(air["pre_flight_ticks"], air["first_motion_tick"] - 1, stem)
            self.assertEqual(air["post_flight_ticks"], len(path) - air["last_motion_tick"], stem)

    def test_the_sustain_requirement_costs_nothing_on_the_committed_logs(self):
        """The 5-tick sustain run exists to reject a spurious sample, and on every committed log it
        moves NO boundary. Pinning that keeps it honest insurance rather than a tunable that could
        quietly start trimming real flight away."""
        for stem, entry in load("verdicts.json")["flights"].items():
            air = entry["airborne"]
            self.assertEqual(air["first_motion_tick"], air["bare_first_crossing_tick"], stem)
            self.assertEqual(air["last_motion_tick"], air["bare_last_crossing_tick"], stem)

    def test_airborne_window_degrades_honestly_on_a_log_that_never_flew(self):
        """A negative control. A log with no sustained climb must open on tick 1 and SAY it found
        nothing, not silently pick a tick and imply the vehicle flew."""
        flat = BD.airborne_window([[0.0, 0.0, 0.0]] * 40)
        self.assertFalse(flat["found"])
        self.assertEqual((flat["first_motion_tick"], flat["last_motion_tick"]), (1, 40))
        self.assertIn("claims nothing", flat["rule"])
        spike = BD.airborne_window([[0, 0, 0.0]] * 10 + [[0, 0, 9.0]] + [[0, 0, 0.0]] * 10)
        self.assertFalse(spike["found"], "one airborne sample is not a takeoff")

    def test_bound_truth_track_is_the_reviewed_pin(self):
        for stem, entry in load("verdicts.json")["flights"].items():
            if (entry["schema_version"] or 0) < 2:
                self.assertFalse((DATA / "truth" / f"{stem}.json").exists(),
                                 f"{stem}: a schema-1 log has no bird ground truth to publish")
                continue
            truth = load(f"truth/{stem}.json")
            self.assertEqual(truth["track"], GATE.TRUTH_BINDINGS[stem])
            self.assertTrue(truth["poses"])
            for bird_id, rows in truth["poses"].items():
                self.assertEqual(len(rows), truth["landed_calls"][bird_id], bird_id)
                self.assertEqual(rows, sorted(rows, key=lambda r: r[0]),
                                 f"{bird_id}: poses must be ordered so the page can step them")

    def test_page_files_exist_and_reference_no_network(self):
        """ADR-018: no CDN, no external anything -- the page has to render offline."""
        page = REPO_ROOT / "dashboard"
        for name in ("index.html", "app.js", "style.css", "README.md"):
            self.assertTrue((page / name).exists(), name)
        html = (page / "index.html").read_text()
        for token in ("http://", "https://", "//cdn", "integrity="):
            self.assertNotIn(token, html, f"index.html references {token} -- the page must work offline")
        self.assertNotIn("https://", (page / "style.css").read_text())

    def test_published_tree_stays_small_enough_to_serve(self):
        total = sum(p.stat().st_size for p in DATA.rglob("*") if p.is_file())
        self.assertLess(total, 16_000_000, f"dashboard/data/ is {total / 1e6:.1f} MB")


if __name__ == "__main__":
    unittest.main()
