---
name: depth-segmenter-design
description: ADR-021 (2026-09-07) — the depth segmenter is BUILT, SCORED (all 7 bars) and WIRED, and has NEVER FLOWN; the blocker before the dodge is that a depth flight log is deliberately UNSCOREABLE
metadata:
  type: project
---

**Status 2026-09-07: the design note became ADR-021 — ACCEPTED, confirmation-pending the first
depth flight.** `docs/design/DEPTH_SEGMENTER_DESIGN.md` (pre-registered rules + bars) and
`docs/design/DEPTH_SEGMENTER_ALGORITHM.md` (perception's parallel note) are both in
`docs/README.md`'s map and `build_docs_site.py`'s GROUPS under "Design notes"; the JSON station file
cannot be in GROUPS (discovery walks `docs/**/*.md` only) and is linked from `docs/README.md`.

**Why this memory still matters:** the numbers below are the ones a future session will want to
quote, and two of them are counter-intuitive enough to be re-derived wrongly.

**How to apply — the load-bearing facts, verified against the artifact before quoting:**

* **Adopted constants** (`src/fieldguard_planning/depth_segment.py::DEFAULT_PARAMS`, provenance
  string points at the artifact): K **15**, margin **1.5 m**, min_area **10 px**, open_iter **0**,
  max_boxes **64**, near/far 0.1/60.0, `link_break` **False**. Every one is a sweep output.
  Artifact: `eval/results/depth_segmenter_score_20260907T110000Z.json`; human report:
  `eval/results/depth_dataset_20260907/REPORT.md`.
* **Bars, all PASS, with denominators:** FNR 0/49 · merge mislabels 0/71 · unmapped FP 0.0/frame
  over 8 · range p95 0.1076 m over 63 matches (vs **1.65 m median** for the monocular ray it
  replaces) · runtime host p95 6.708 ms **n=425** (NOT the n=79 counters row) · determinism 0/79 ·
  mutation red on the two independent terms.
* **Acquisition 46.0 m QUALIFIES the ADR-020 booking and never raises it**, read as `≥` (no station
  failed → last rung, not a horizon). **Clutter claim reaches only 28 m**; every rung from 30 m is
  sky-backed, geometrically forced (an in-band bird at 46 m has its ground background past the 60 m
  cull). Best-case clause KEEPS static vehicle / noiseless sensor / level attitude.
* **The resolving floor was re-measured on THIS operator: 2.0 px → 46.80 m** (arithmetic coincidence
  with the NDVI number, not inheritance) — it binds the horizon 0.76 m tighter than the 47.558 m
  corner clamp. At `min_area_px=6` it would be 58.50 m. Closes ADR-020 am. 1 item 3.
* **Two REPORTED-not-barred numbers, and the first is the safety one.** *Median-flip margin:* the
  box ships the component MEDIAN, so a mixed component is truthful only while the bird holds the
  majority — worst case **1 pixel** (S042/S046: 32 of 60 px; a flip reports **54.511 m instead of
  29.956 m**), and `range_error_p95` structurally cannot see it. Centroid p95 0.93 px / max 4.335.
* **The correction the render forced:** an object **wider than K returns ZERO candidates, not a
  ring** (a grey closing preserves a pit wider than the SE) — a 1.3 m canopy sphere is invisible
  inside ~25 m. **An unplanned LARGE near obstacle is a named blind spot** no bar on this dataset can
  see; survivable only because this world's large objects are the mapped trees.
* **The two design-vs-prototype deltas are SETTLED by measurement:** the morphological closing won
  (it is the shipped operator), and the ring test / `link_break` is **OFF** — under the corrected
  merge rule it moves no bar, and it can **withhold** (a seam cut drops two adjacent 12-px objects
  below min_area and returns nothing). Its better REPORTED numbers are on the record (range p95
  0.1076→0.0775, centroid 4.335→0.665 px) and were deliberately not adopted: retuning after seeing
  the numbers is fitting to one's own data. Pre-registerable next round = `link_break` with cut
  components exempt from `min_area_px`, plus a two-bird station arm.

**THE BLOCKER before any dodge take is booked (ADR-021 open item 1):** `DETECTOR_SOURCES` in
`scripts/check_live_flight_log.py` **deliberately excludes `depth_blob`** — every schema-2 detector
gate was written for the nadir NDVI camera — so a depth flight log is **UNSCOREABLE** and the take
would produce an INVALID log by construction. A reviewed diff with depth-specific gates must land
first. Booking already applies (`gate_booked_speed` counts `depth_blob` as avoidance: authorisation
is not scoring). Then: launcher must pass `--detection-source depth`, and a scripted `test-flight`
with no birds gets D5/D6 **at the booked 5.0 m/s** (both are still 3.50 m/s numbers).

Related: [[adr020-depth-commissioning]], [[a-gate-is-only-as-true-as-its-scene]],
[[avoidance-take-blockers]].
