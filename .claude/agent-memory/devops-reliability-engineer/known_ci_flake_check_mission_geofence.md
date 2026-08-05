---
name: known-ci-flake-check-mission-geofence
description: scripts/check_mission_geofence.py exits 1 by design on a documented, safe XY overlap — never gate CI on its exit code directly
metadata:
  type: project
---

`scripts/check_mission_geofence.py` (see `main()`, returns 1 at the end) intentionally exits 1 when
it finds a leg with XY clearance <= 0 against a tree, EVEN THOUGH the overlap is currently safe: at
`mission_altitude_m=15.0` vs `tree height=3.5m` there is >11m of vertical separation, so a 2D/XY
overlap is not a real collision. This is leg 4 of the nominal boustrophedon mission, clearance
-1.997m, documented explicitly in the script's own printed output and docstring.

**Why this matters for CI**: a naive `set -euo pipefail` step that calls this script directly will
always fail the build for a non-issue. The Week 2 `planning-and-eval` CI job (see
[[project_ci_pipeline]]) calls it as `python3 scripts/check_mission_geofence.py || true` specifically
to still catch import/CLI breakage (a traceback, missing config, argparse error) without gating on
this already-understood business-logic exit code.

**How to apply**: if Week 3-4 avoidance work changes the mission altitude or tree height (the
script's own comment flags this as exactly where a *real* XY dodge requirement would first show up),
revisit whether this should become a real CI gate — at that point a leg-4-style violation would mean
something different and the `|| true` would need to be removed and replaced with a real
pass/fail check tied to the new safety invariant.
