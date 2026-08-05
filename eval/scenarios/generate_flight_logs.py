#!/usr/bin/env python3
"""Generate `flight_log.json` for the AVOIDANCE-side pending scenarios by driving the REAL
`avoidance_policy` + `avoidance_executor` along a nominal boustrophedon path with each scenario's
bird(s). Writing `eval/scenarios/<name>/flight_log.json` self-activates the matching assertions in
`tests/fieldguard_planning/test_safety_scenarios_pending.py` (no test edits -- that's the design).

These logs are produced by the actual loop, not hand-authored: the coverage ledger comes straight
from `AvoidanceExecutor.finalize()` (honest by construction), so the tests check a genuine artifact.

NOT generated here (on purpose): the detection scenarios `det_bird_crosses_path` /
`det_bird_over_low_ndvi`. Their "no missed bird" property reuses `eval/score.py` and needs DETECTION
artifacts (ground_truth.json + detections.json), i.e. the detection pipeline on a real NDVI render
(Weeks 5-6) -- NOT an avoidance flown path. Fabricating detection data to turn them green would be
exactly the fake-a-metric move this project refuses. They stay pending on the real render.

Run (stdlib + fieldguard_planning only, no numpy/ROS 2):
    python3 eval/scenarios/generate_flight_logs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from fieldguard_planning.avoidance_types import Detection, DroneState  # noqa: E402
from fieldguard_planning.avoidance_policy import AvoidancePolicy  # noqa: E402
from fieldguard_planning.avoidance_executor import AvoidanceExecutor, SimulatedVehicleSink  # noqa: E402
from fieldguard_planning.geofence import GeofenceMap  # noqa: E402
from fieldguard_planning.coverage import build_grid, load_field_polygon  # noqa: E402

CRUISE_M = 15.0        # cruise altitude (world-ENU U); the loop never descends, so it never
SWATH_HALF_M = 7.5     # turns the benign at-altitude tree overlap into a strike
CELL_M = 2.5
LANES_X = [15.0, 30.0, 45.0, 60.0]   # boustrophedon lanes over the field (covers each scenario bird)
Y_LO, Y_HI = 2.0, 58.0
STEP_M = 2.0
HEADING_N = 1.5708     # facing +N (radians), ENU

# Bird threat positions = the in-altitude-band (z=15) waypoint from each scenario yaml (kept in sync
# with eval/scenarios/<name>.yaml). Static-at-threat is a fair reduction: the property under test is
# "a bird at P forces a dodge, and coverage/geofence stay honest," not the bird's exact timing.
SCENARIOS = {
    "cov_bird_over_cell":         {"seed": 101, "birds": [("intruder_0", (30.0, 30.0, 15.0))]},
    "cov_bird_at_turnaround":     {"seed": 102, "birds": [("intruder_0", (22.0, 58.0, 15.0))]},
    "cov_two_birds_simultaneous": {"seed": 103, "birds": [("intruder_0", (45.0, 25.0, 15.0)),
                                                          ("intruder_1", (45.0, 33.0, 15.0))]},
    "geo_avoid_into_tree":        {"seed": 301, "birds": [("pincher_0", (59.0, 30.0, 15.0))]},
}


def nominal_path():
    """Boustrophedon lane centers, densified, each tagged with its mission-waypoint (lane) index."""
    pts = []
    for i, lx in enumerate(LANES_X):
        y0, y1 = (Y_LO, Y_HI) if i % 2 == 0 else (Y_HI, Y_LO)
        n = max(1, int(abs(y1 - y0) / STEP_M))
        for k in range(n + 1):
            pts.append((lx, y0 + (y1 - y0) * (k / n), i))
    return pts


def run(name: str, cfg: dict) -> dict:
    geo = GeofenceMap.from_file()
    poly = load_field_polygon()
    cells = build_grid(poly)                       # canonical grid the tests also build
    policy = AvoidancePolicy(field_polygon=poly)   # field containment on, so dodges stay in-field
    sink = SimulatedVehicleSink(initial_wp_index=0)
    ex = AvoidanceExecutor(geo, cells, sink, swath_half_width_m=SWATH_HALF_M, alt_bounds=(2.0, 30.0))
    birds = cfg["birds"]

    for fid, (x, y, wp) in enumerate(nominal_path()):
        sink.current_wp_index = wp                 # the mission tracker (AUTO) owns this
        drone = DroneState((x, y, CRUISE_M), heading_rad=HEADING_N, current_wp_index=wp)
        dets = [Detection(pos, frame_id=fid, track_id=bid) for bid, pos in birds]
        ex.step(drone, policy.decide_multi(dets, drone, geo))

    ex.finalize()
    log = ex.flight_log(name, cfg["seed"], cell_size_m=CELL_M)
    out = REPO / "eval" / "scenarios" / name / "flight_log.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(log, indent=2))
    return log


def main() -> int:
    for name, cfg in SCENARIOS.items():
        log = run(name, cfg)
        debt = sum(1 for r in log["coverage_ledger"] if r["status"] == "debt")
        diverts = sum(1 for e in log["events"] if e["kind"] == "maneuver")
        holds = sum(1 for e in log["events"] if e["kind"] == "hold")
        rejects = sum(1 for e in log["events"] if e["kind"] == "gate_reject")
        print(f"  {name}: {len(log['coverage_ledger'])} cells, {debt} debt, "
              f"{diverts} diverts, {holds} holds, {rejects} gate-rejects")
    print("Done. det_bird_* scenarios intentionally NOT generated (need the detection pipeline).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
