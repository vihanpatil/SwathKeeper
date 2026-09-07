---
name: depth-segmenter-design
description: Pre-ADR-021 depth segmenter design (2026-09-07) — discontinuity not isfinite, the >=11.3 m in-band step that makes the margin free, and the two open deltas against the parallel prototype
metadata:
  type: project
---

`docs/design/DEPTH_SEGMENTER_DESIGN.md` + `docs/design/depth_segmenter_stations.json` (79 stations)
were written 2026-09-07 as the design that becomes **ADR-021** once built and gated. Nothing is
built and nothing is measured on a render.

**Why:** ADR-020 commissioned the forward depth mount but the 46.0 m booked acquisition range is a
best-case-scene upper bound taken with a blind `isfinite` mask and NO SEGMENTER; the runbook's
Known-gaps merge hazard (bird in the ground band joins the ground component, `max_area` deletes it)
is the thing the segmenter must close. See [[adr020-depth-commissioning]].

**How to apply:** the load-bearing facts, so they are not re-derived —

* **The geometric fact that makes the whole design cheap:** with a LEVEL camera at 15 m over flat
  ground with 3.8 m trees, *any* obstacle inside the ±6 m threat band is **≥ 11.3 m nearer than its
  background** (ground: step ≥ 1.5R; canopy: ≥ 0.867R; above-axis: sky = inf). Minimum across the
  79 stations is 16.35 m. So a ~2 m discontinuity margin has a 5.6× factor and costs safety nothing.
  All three qualifiers matter; **attitude breaks it first** (worst observed −12.50°).
* **A flat-SE morphological closing (local far-envelope) reproduces a monotone ground ramp EXACTLY**
  — measured 0.0 m residual over the frame interior — so the ground band never becomes its own
  candidate, and the cull boundary produces no false candidate either. The only residual is a
  frame-border artifact, **1.425 m at K=21**, which is what puts a floor under the margin.
* **Cost:** min/max closing 4.6 ms/frame on host, flat in K (scipy separable path); naive
  `median_filter(size=21)` is **1061 ms**. Budget anchor: the NDVI detector measured
  **p95 8.211 ms / max 41.917 ms, n=1302** in-container on the same 640×480
  (`eval/results/live_flight_log_20260825T210402Z.json`).
* **Never `max_area`.** Deleting the largest thing in the frame is fail-dangerous; saturation is
  handled by nearest-first ordering plus a box cap, which discards the FAR candidates.
* **The annotator can never fire on an in-band bird in this world** (trees top at 3.8 m, geofence
  4.8 m, band starts at 9 m): `detections_near_known_obstacle` is a clutter accountant, not a bird
  discriminator. Corollary — canopy rims and cull edges un-project below the band and the policy's
  own vertical test deletes them for free, with no appearance-based suppression.
* **Dataset:** must be rendered on the **COMMITTED 125×110 m ground plane, not the 425 m check-world
  extension** — the finite-ground footprint is bounded at 57.78 m forward / ±30.38 m lateral, and
  every station pose keeps it on the committed plane (min margin 7.07 m). The plane's extent IS part
  of what is being measured. Labels must come from the **camera LINK pose readback**, not the
  commanded model pose (`base_link` sits 0.195 m up).

**Two OPEN deltas against the parallel prototype** (`eval/depth_segmenter_proto.py`, written
concurrently by another lane; both arrived independently at discontinuity-not-isfinite):
1. background estimator — block-median-of-medians (their measured ground residual 0.070/0.609 m) vs
   morphological closing (exact, 200× cheaper than a naive median). Settle on the dataset.
2. **their "ring test" WITHHOLDS components judged to be the near side of a larger surface** — which
   is also what a large unplanned obstacle looks like, and it withholds *before* un-projection.
   Recommendation: tag and count, never withhold (same rule as `DepthDetectionSource` rule 9).
   This is a safety-direction disagreement, not a tuning choice.

Two design docs now live in `docs/design/` (mine `_DESIGN.md`, theirs `_ALGORITHM.md`) — they need
reconciling into one before ADR-021, and neither is in `docs/README.md`'s map or
`build_docs_site.py`'s GROUPS yet (they will land under "Other documents"; see
[[moving-a-doc-costs-a-stub]]).
