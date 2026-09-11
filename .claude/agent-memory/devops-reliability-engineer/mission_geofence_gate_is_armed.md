---
name: mission-geofence-gate-is-armed
description: scripts/check_mission_geofence.py is a REAL CI gate since 2026-09-11 (3D verdict, exit 0 on the committed mission) — never re-add `|| true`; the old exit-1-by-design flake is history, kept here as the why
metadata:
  type: project
---

**Gate it. `scripts/check_mission_geofence.py` exits 0 on the committed mission and CI runs it armed**
(`.github/workflows/ci.yml`, step "Gate the committed mission against the tree geofence in 3D",
under `set -euo pipefail`). Exit 1 = a leg really enters a tree's 3D volume; exit 2 = unreadable
inputs. `tests/test_ci_evidence_gate.py::TestMissionGeofenceGateIsArmed` runs that YAML block against
a failing stub, so removing the arming breaks a test.

**Why (the history this file used to record as current):** until 2026-09-11 the script answered an
**XY-only** question the committed mission could not pass — leg 4, the lane at x=15, runs down tree
row 0 at −1.997 m clearance — so it exited 1 on a documented-safe finding and the Week 2 CI job ran
it `|| true` to keep catching import/CLI breakage without gating. That made it a gate that could not
fail. ADR-022 (finding R8) called it: *an XY geofence that cannot fail is not one.* The fix was at the
source — the gate now takes its verdict from the executor's own `geofence.unsafe_obstacle_3d`, so the
XY overlap is REPORTED (still −1.997 m) and cleared by +10.200 m of altitude over the 4.80 m canopy
band rather than treated as a violation. The mission was **not** re-planned; every committed flight
log flew it and comparability outranks a cosmetic lane shift. See `docs/DECISIONS.md` ADR-022
amendments 2 and 3.

**How to apply:** if this step ever goes red, read the output before touching the YAML — it names the
leg and every tree it enters. A red here means a mission (or a tree-map export, or the vertical
margin) changed such that the flight path now passes through a canopy. `|| true` is not the answer;
it was the bug. The general lesson in
[[feedback_bug_hunter_not_yaml_author]] item 4 — read a script's exit-code semantics before chaining
it under `set -euo pipefail` — still stands; this script is simply no longer an example of it.
