---
name: swath-vs-camera-footprint
description: KNOWN-RISKY — the coverage ledger's 7.5 m swath half-width exceeds the measured 6.886 m cross-track half-footprint, so "covered" over-claims a 1.23 m band per lane pair (8.2 % of pitch); the number is derivable from live camera_info today
metadata:
  type: project
---

The coverage-debt ledger scores a cell `covered` when its centre is within
`DEFAULT_SWATH_HALF_WIDTH_M = 7.5` m of a flown leg (`src/fieldguard_planning/coverage.py`). That
7.5 is **lane-pitch/2, not an imaging number**, and `coverage.py`'s own module docstring says so in
the section headed "THE SWATH ASSUMPTION (read this — it is where the coverage guarantee can
silently rot)".

**It is now measurable and it does not hold.** Live `camera_info` (fx=fy=520.0058, 640x480 —
`eval/results/clips/real_flight_20260823T073644Z/meta.json`) at 15 m cruise with the mount 0.08 m
below the drone gives a **cross-track half-footprint of 6.886 m** (the 480-px axis is the
cross-track one — ADR-003 amendment 2 fixed exactly this axis confusion) against the assumed 7.5.
Full cross-track swath **13.77 m vs a 15 m lane pitch** leaves **1.23 m unimaged per lane pair, 8.2 %
of the pitch**, scored `covered`.

**Why 720/720 painted maps did not catch it:** the discrepancy (0.61 m per side) is smaller than one
2.5 m cell, and the stitch paints a cell if *any* pixel lands in it, so a partly-imaged edge cell
still fills. Cell count cannot see this; only the derivation can.

**Why:** the project's headline honesty claim is "no cell is silently skipped". A swath constant
that over-states the camera makes that claim structurally false at the 8 % level — and this is the
exact failure class ADR-007 amendment 5 was written about (every value gate passed while the camera
faced the horizon; values cannot catch geometry).

**How to apply:** treat this as a live bug, not a nitpick, before any dashboard/demo/GTM number
quotes coverage. Minimal fix: derive the swath half-width from `camera_info` + cruise altitude at
ledger-build time and either re-pitch lanes to ~13.5 m or record the honest narrower swath and let
the debt appear. Add a gate that fails when `swath_half_width_m > measured cross-track half`.
Related: [[adr007-ndvi-render]], [[adr-log-must-track-the-gate]].
