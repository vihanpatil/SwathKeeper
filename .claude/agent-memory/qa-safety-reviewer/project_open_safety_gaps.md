---
name: project-open-safety-gaps
description: Standing to-break list of open SwathKeeper safety gaps, ranked by consequence, current as of 2026-08-23
metadata:
  type: project
---

Standing safety-hunt list. Recheck before any sign-off; close/append as they resolve. Scenario and
regression locations: [[reference-safety-scenario-catalog]]. Supersedes the Week-2 list (its GAP 1
and GAP 3 survive below in updated form; GAP 2 is now closeable on paper — see G6).

**G1 — nothing measures ACHIEVED separation from the bird.** The 2026-08-23 delegated demo closed to
CPA 0.0518 m against a policy whose own `min_bird_clearance_m` is 3.0, and every gate was green:
`check_live_flight_log.py` validates the coverage ledger, and "19/19 maneuvers vetted" is a claim
about SETPOINTS. The dodge bought 0.045 m of lateral escape in the 6 ticks to CPA while the vehicle
travelled 9.306 m toward the bird at >6.5 m/s, because the preferred candidate (angle 0, straight
away) is a full reversal for a head-on closure — the one escape ownship momentum forbids.
**Why:** a missed bird is THE safety-critical failure; a loop that dodges and still hits is worse
than one that holds. **How to apply:** demand a CPA number from every avoidance flight; push the CPA
assertion into `check_live_flight_log.py` so it cannot be reported as green again.

**G2 — the vet's tree gate has zero margin.** `lateral_tree_margin_m` defaults to 0.0
(`avoidance_policy.py`) and no caller sets it, so the ACCEPT boundary is the EXCLUSION boundary: a
swept path exactly tangent to a tree column is accepted. Range-independent. Pinned by
`test_degenerate_range_avoidance.py`; 1.0 m is what the 18-tree geometry supports (within-row
corridor caps any margin at 3.0 m) and costs +1.6 pp HOLD on the flown path.
**Why:** ADR-015 — never rest a safety claim on a boundary. **How to apply:** the only thing between
an accepted dodge and the canopy is 0.700 m of `obstacle_radius_m` - `canopy_radius_m` padding.

**G3 — `is_safe_3d` cannot fire in the flown configuration.** Every v1 setpoint is pinned to
`cruise_alt_m` 15.0; the tallest tree volume tops out at 4.8 m; `alt_bounds` is (2, 30). So gate 1
AND the executor's ADR-006 safety BACKSTOP return True for every XY, including a trunk. The flight
log's "0 gate_reject events" means *could not fire*, not *nothing was wrong*.
**Why:** vacuous-green family. **How to apply:** the backstop becomes live only if a maneuver ever
descends below ~4.8 m or a taller obstacle enters the map — treat any descent feature as re-arming
an untested gate, not as reusing a proven one.

**G4 — degenerate-range away-vector.** Below ~1 m of trigger range the away-vector is numerically
valid and physically meaningless (only guard is `_unit`'s 1e-9 m). ADR-009 apparent-size ranging has
metre-scale error, so at 0.052 m the commanded dodge direction is noise; measured bearing span
337 deg vs 6.2 deg at 9.27 m. The executor then re-latches on it, because it reads "setpoint moved
> 3 m" as "the threat moved" — the demo bird never moved once in 19 ticks.
**How to apply:** any fix must keep the 19/19 vetted encounter and ADR-006's one-setpoint semantics.

**G5 — no independent geofence backstop, and the mission rides the boundary.** No ArduPilot `FENCE_*`
parameter is set anywhere (`config/sitl_params/dds_udp.parm` carries DDS params only), so the ONLY
boundary protection is the policy's setpoint containment. Mission lanes x=0 and x=75 lie ON the field
polygon, so 118 of 984 flown points in the 2026-08-23 log were outside it (worst 0.073 m). Accepted
dodges stay inside — but only because the polygon is CONVEX (the vet checks the setpoint, never the
swept path). **How to apply:** a non-convex field, or any lane on the boundary, turns this from
bounded to live.

**G6 — swath assumption is conservative, and now checkable.** `coverage.py` still flags
`DEFAULT_SWATH_HALF_WIDTH_M = 7.5` as unmeasured, but `config/ndvi_camera.json` (hfov 1.1033 rad,
640x480) gives an 18.46 m ground swath at 15 m — wider than the 15 m lane spacing, so the ledger
UNDER-claims coverage. Closeable on paper if `verify_mount_geometry.sh` is asked to assert the
63.2 deg axis is across-track. **How to apply:** don't quote it as closed until the mount gate says so.

**G7 — ADR-003 on the real render is still unexercised** (zero bird-visible frames was structural;
the criterion-3 re-fly is the outstanding evidence). Detection numbers remain synthetic-origin.

**v1 bar reminder (ADR-002):** coverage debt > 0 is ALLOWED — but every dropped cell must be
EXPLICIT in the ledger, never absent. `debt_count == 0` is a separate stretch assertion.
