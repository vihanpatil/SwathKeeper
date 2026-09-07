"""The COMMITTED booking-gate artifacts -- the files that authorise a dodge flight.

`tests/fieldguard_planning/test_predict_forward_lead.py` pins the TOOL: given inputs, what it
computes and what it refuses. Nothing there reads the artifact the tool actually wrote, so the file
`eval/results/booking_gate_*.json` -- the one a reviewer, the runbook and ADR-020 am. 1 all quote --
could rot, be hand-edited, or be replaced by a sweep, and every test would stay green. This file
reads it.

The assertions are HARD, not skipped-if-absent: `booking_gate_*.json` is un-ignored in .gitignore
(beside `testflight_gate_*.json`) precisely so the authorisation travels with the repo, and
`tests/test_fly_pipeline.py::TestEvidenceYieldFloor` already treats a committed gate record as a
fixture that must exist. A missing artifact is the failure, not a reason to pass quietly.

Runs on the host, stdlib only, ~1 s.
"""
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

import predict_forward_lead as pfl  # noqa: E402

RESULTS_DIR = REPO_ROOT / "eval" / "results"
GLOB = "booking_gate_*.json"

# Gate D4, 2026-09-07: the run that authorised the dodge flight at 5.0 m/s, on the live camera_info
# gate D1 measured and the 46.0 m horizon gate D3 measured and the user ratified.
D4_ARTIFACT = "booking_gate_20260907T064136Z.json"
D4_SPEED_MPS = 5.0
D4_ACQ_M, D4_PREFIX_M = 46.0, 58.0
D4_FX, D4_FY = 520.0058046927554, 520.0058046927553


class TestCommittedBookingGateArtifacts(unittest.TestCase):
    def artifacts(self):
        found = sorted(RESULTS_DIR.glob(GLOB))
        self.assertTrue(found, f"no {GLOB} committed under eval/results -- the booking gate's own "
                               f"evidence is missing, and no flight is authorised without it")
        return found

    def test_every_committed_artifact_is_one_this_reader_can_vouch_for(self):
        """`validate_report` is the same function the tool runs before it writes. Reading with it
        means a hand-edited or truncated artifact cannot sit in the repo looking like evidence."""
        for path in self.artifacts():
            rep = json.loads(path.read_text())
            pfl.validate_report(rep)                          # raises with the reason
            self.assertEqual(rep["tool"].startswith("scripts/predict_forward_lead.py"), True,
                             msg=path.name)

    def test_the_D4_artifact_authorises_the_flight_and_says_what_it_was_clamped_from(self):
        rep = pfl.validate_report(json.loads((RESULTS_DIR / D4_ARTIFACT).read_text()))
        s, b, v = rep["sensor"], rep["budget"], rep["verdict"]
        self.assertEqual(rep["schema_version"], "1.2")
        self.assertIs(v["bookable"], True)
        self.assertIs(v["pass"], True)
        self.assertEqual(v["exit_code"], pfl.EXIT_PASS_BOOKABLE)
        self.assertIsNone(v["why_not_bookable"])
        self.assertTrue(all(c["ok"] for c in rep["checks"]),
                        msg=[c["name"] for c in rep["checks"] if not c["ok"]])
        # the horizon, and the fact that it is a CLAMPED one (ADR-020 am. 1)
        self.assertEqual(s["acquisition_range_m"], D4_ACQ_M)
        self.assertEqual(s["acquisition_optical_prefix_m"], D4_PREFIX_M)
        self.assertIs(s["acquisition_clamped_from_optical_prefix"], True)
        self.assertAlmostEqual(s["acquisition_clamp_bound_m"], 47.558, places=3)
        self.assertIs(s["live_intrinsics"], True)
        self.assertEqual((s["fx_px"], s["fy_px"]), (round(D4_FX, 4), round(D4_FY, 4)))
        # the margin, at the speed it was booked at
        self.assertEqual(rep["encounter"]["mission_speed_mps"], D4_SPEED_MPS)
        self.assertAlmostEqual(b["margin"], 1.780, places=3)
        self.assertGreaterEqual(b["margin"], b["lead_margin_factor"])
        self.assertAlmostEqual(b["available_lead_s"], 3.832, places=3)
        self.assertAlmostEqual(b["need_s"], 2.152, places=3)
        self.assertAlmostEqual(b["required_horizon_m"], 33.59, places=2)

    def test_the_authorisation_still_follows_from_TODAYS_code(self):
        """The artifact is a record of what the tool said in that session; this recomputes it from
        the inputs the artifact itself records. If a later change to the plant, the policy bar, the
        birds config or the corner bound would move the verdict, the committed authorisation is
        stale and must be re-run before anyone flies on it.

        `band_covered_from_m` is deliberately NOT compared: this artifact predates the 2026-09-07
        fix that made the band's binding half-extent min(cy, H-1-cy), so it records 13.00 m where
        the honest figure is 13.05 m. That difference is verdict-invariant (the band is compared
        against a 46.0 m acquisition range either way) and is pinned as such in the next test --
        not waved through here."""
        rep = json.loads((RESULTS_DIR / D4_ARTIFACT).read_text())
        s = rep["sensor"]
        today = pfl.evaluate(rep["encounter"]["mission_speed_mps"],
                             fx_px=D4_FX, fy_px=D4_FY, cx_px=s["cx_px"], cy_px=s["cy_px"],
                             width_px=s["image_width_px"], height_px=s["image_height_px"],
                             acq_range_m=s["acquisition_range_m"],
                             acq_optical_prefix_m=s["acquisition_optical_prefix_m"])
        self.assertIs(today["verdict"]["bookable"], True)
        self.assertEqual(today["verdict"]["exit_code"], rep["verdict"]["exit_code"])
        for key in ("margin", "available_lead_s", "need_s", "required_horizon_m",
                    "acq_range_headroom_frac", "bar_m", "lead_margin_factor"):
            self.assertAlmostEqual(today["budget"][key], rep["budget"][key], places=3, msg=key)
        for key in ("acquisition_range_m", "clip_far_at_frame_corner_m",
                    "clip_far_corner_ray_ratio", "geometric_acquisition_range_m"):
            self.assertAlmostEqual(today["sensor"][key], rep["sensor"][key], places=3, msg=key)
        self.assertEqual(today["plant"]["t_req_s"], rep["plant"]["t_req_s"])
        self.assertEqual(today["encounter"]["bird_speed_mps"], rep["encounter"]["bird_speed_mps"])

    def test_the_ONE_number_that_moved_since_the_artifact_was_written_is_named_and_harmless(self):
        """13.00 -> 13.05 m: the threat band has to fit above AND below the optical axis, and a
        480-row frame has 239 rows below cy=240, not 240. The artifact was written before that fix.
        Pinned here rather than silently re-generated, because re-running the D4 command would
        produce a NEW artifact with a new timestamp and the ratified one is the record of what
        authorised the flight. The check the number feeds is `band_in_frame_at_acquisition`, and it
        passes by 33 m on either value -- so this is a documentation drift, not a verdict drift.
        The day the band number is load-bearing, re-run D4 instead of editing this test."""
        rep = json.loads((RESULTS_DIR / D4_ARTIFACT).read_text())
        self.assertAlmostEqual(rep["sensor"]["band_covered_from_m"], 13.000, places=2)
        today = pfl.evaluate(D4_SPEED_MPS, fx_px=D4_FX, fy_px=D4_FY, cx_px=320.0, cy_px=240.0,
                             width_px=640.0, height_px=480.0, acq_range_m=D4_ACQ_M)
        self.assertAlmostEqual(today["sensor"]["band_covered_from_m"], 13.055, places=3)
        for band, source in ((rep["sensor"]["band_covered_from_m"], D4_ARTIFACT),
                             (today["sensor"]["band_covered_from_m"], "today")):
            self.assertLess(band, D4_ACQ_M, msg=source)
        self.assertTrue(next(c for c in rep["checks"]
                             if c["name"] == "band_in_frame_at_acquisition")["ok"])

    def test_no_committed_artifact_authorises_a_flight_from_a_SWEEP(self):
        """A sweep chooses a mission speed; a single --speed run authorises one. An artifact
        carrying `sweep` rows can never be the thing a flight was booked on, and `validate_report`
        refuses one that claims to be -- this asserts the committed set actually obeys that."""
        for path in self.artifacts():
            rep = json.loads(path.read_text())
            if "sweep" in rep:
                self.assertIs(rep["verdict"]["bookable"], False, msg=path.name)
                self.assertNotEqual(rep["verdict"]["exit_code"], pfl.EXIT_PASS_BOOKABLE,
                                    msg=path.name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
