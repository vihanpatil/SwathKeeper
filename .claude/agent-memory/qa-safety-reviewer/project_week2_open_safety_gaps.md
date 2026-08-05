---
name: project-week2-open-safety-gaps
description: Open FieldGuard safety gaps the QA reviewer is actively hunting; the standing to-break list for Weeks 3-4
metadata:
  type: project
---

Standing safety-hunt list for FieldGuard. Recheck each before signing off on the Weeks 3-4
avoidance loop; close/append as they resolve. Catalog + how-to-run: [[reference-safety-scenario-catalog]].

**GAP 1 — geofence.py is XY-only.** The nominal boustrophedon lane at x=15 flies straight THROUGH
orchard row 0 in XY (min clearance -1.997 m); it is safe only by 11.5 m vertical separation (mission
15 m vs tree 3.5 m). So an XY breach at altitude is NOT a collision — but any avoidance/imaging
manoeuvre that DESCENDS into the tree band (<= ~5.5 m) makes that overlap a real strike.
**Why:** the avoidance safety gate must be 3D-aware; reusing the XY-only nominal check would pass a
descending dodge into a tree. **How to apply:** the pending `geo_avoid_into_tree` assertion is
deliberately 3D (altitude band + radius). Do not let Week 3-4 gate avoidance on XY alone.

**GAP 2 — camera swath is unvalidated.** Coverage guarantee assumes downward NDVI swath at 15 m >=
15 m lane spacing (`swath_half_width_m = 7.5`). Not measured against the real Gazebo camera.
**Why:** if the true swath is narrower, uncovered strips open between lanes — a coverage hole no
avoidance logic can fix. **How to apply:** push perception-ml/robotics-sim to measure real swath and
replace the constant in `coverage.py`; `test_negative_control_narrow_swath_opens_gaps` proves the
checker would catch the resulting gaps.

**GAP 3 — detection numbers are synthetic-only.** ADR-003's FNR (incl. the bird-over-bare-soil case)
is from a SYNTHETIC clip, not a real render. **Why:** the "no missed bird" claim isn't trustworthy
until re-run on the real Gazebo NDVI render. **How to apply:** `det_bird_over_low_ndvi` requires
`meta.json synthetic == false`; block the safety sign-off on it.

**v1 bar reminder (ADR-002):** coverage debt > 0 is ALLOWED for v1 ("avoid, return to next
waypoint") — but every dropped cell must be EXPLICIT in the ledger, never absent. The invariant
proves the loop is honest, not complete. `debt_count == 0` is the separate STRETCH assertion.

**Top 3 scenarios most likely to catch a real Week 3-4 bug:** (1) `cov_bird_at_turnaround` — cell
lost in the lane-handoff during a dodge; (2) `cov_two_birds_simultaneous` — 2nd avoidance clobbering
1st's requeue/debt state; (3) `geo_avoid_into_tree` — naive away-from-threat dodge steering into a
geofenced tree.
