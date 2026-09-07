---
name: evidence-consumption-seams
description: How to consume committed flight/NDVI evidence without re-deriving it — the gate functions to call, the joins that DO NOT exist (flight↔clip has no run id; schema-1 has no time axis), and the two things a flight log cannot answer (acquisition range, orientation)
metadata:
  type: project
---

Anything that reads the committed evidence (the dashboard, a report, a future backend) **calls the
gates rather than re-deriving them**, and the four call sites are stable.

**Why:** a second implementation of a verdict is a second opinion, and the one that gets published
is whichever one is wrong. `scripts/build_dashboard_data.py` (ADR-018, 2026-08-26) was built this
way and it is the pattern to copy. The same session's `spike_scores.json` drift is the counterexample:
a committed copy of a derived artifact that silently stopped matching its source, with two
internally-consistent stale files agreeing with each other.

**How to apply:**

* `check_live_flight_log.check_file(path) -> (verdict, messages)` — the whole verdict, including the
  legacy/schema-2 branch, the acknowledgement halves and the printed metric lines. `verdict` is one
  of `SKIP|VALID|INVALID|ACKNOWLEDGED`. Do not reimplement the branch.
* `check_live_flight_log.resolve_truth(log_path, run)` then `ground_truth_cpa(path, stamps, truth,
  vertical_threat_m, threat_radius_m)` — the structured GT-CPA report dict (`gt_cpa_m`, `tick`,
  `t_sim_s`, `bird_id`, `cylinder_ticks`, the pose/tick denominators). Pair with
  `stamp_advance(stamps)` + `freeze_debit_m(frozen_window_s)` for the gated number.
* `check_tree_positions.analyse(clip_dir) -> dict` — trees imaged / canopy-grade / median lift /
  soil modal NDVI / displacement, from `heatmap/heatmap.json` + `config/static_obstacles.json`.
* `coverage.build_grid(load_field_polygon(), 2.5)` — the canonical 720 cells. **Verified 2026-08-26:
  the grid, every flight log's `coverage_ledger`, and both committed clips' heatmap cells carry the
  IDENTICAL 720 `cell_id` set with identical centres.** That join is total in both directions.

**Path index ↔ tick:** `flown_path_enu[tick - 1]`. Confirmed against the 2026-08-25 GT-CPA
(tick 991 → index 990, drone z 15.03 m). `ground_truth_cpa` reports 1-based ticks.

**Dodge displacement is WINDOW-DEPENDENT — do not quote "1.8 cm" from the ROADMAP as the GUIDED-window
number.** Measured 2026-08-26 over the full takeover→resume window, projecting the displacement onto
the first commanded setpoint direction:

| log | commanded | along command | across | total |
|---|---|---|---|---|
| 20260825 (ticks 991→995, 0.434 s) | 10.00 m | **+0.0541 m** (0.5 %) | 3.95 m | 3.95 m |
| 20260823 (ticks 323→342) | 10.00 m | **−21.7965 m** | 0.40 m | 21.80 m |
| 20260818 (ticks 3528→3589) | 10.00 m | **−14.5385 m** | 0.16 m | 14.54 m |

ADR-016's 1.8 cm is over the point-mass study's own shorter window; at tick 992 the along-command
figure is 2.02 cm. Both are right for their window — say which window. The two NEGATIVE rows are the
documented "flew the wrong way" encounters; the commanded point lay behind the vehicle's motion, so
the sign alone does not prove the command path failed (only the offline replay separates plant from
command path). Also: schema-1 logs have NO `latch` events, so the commanded point must be read from
the first `maneuver.setpoint_enu` in the window.

**The airborne window** (used to trim the dashboard's default replay) is derived, not stored: first
tick whose next 5 telemetry samples read `z > 1.0 m` — the clip recorder's own
`meta.airborne.z_threshold_m` — and the last whose preceding 5 do. Measured pre-flight prologues:
2246/4328 ticks (08-18), 109/984 (08-23), 752/1858 (08-25). The sustain requirement moves no
boundary on any committed log.

**`check_file`/`resolve_truth`/`truth_candidates` default `results_dir` to the REAL `eval/results`,
and `check_live_flight_log.main` does not plumb it.** So any test that drives the CLI has its colour
decided by which flight artefacts happen to be committed: a stray `bird_drive_*.json` whose sim span
overlaps a fixture makes auto-discovery resolve a truth track that was never meant to exist, and
`TestCli` goes red with nothing in the gate changed (this is why the two 2026-09-06 test-flight
`bird_drive_*` files were deleted). **Bind the directory, do not delete the evidence** — tests wrap
`checker.check_file` so `results_dir` is the harness tmp dir and let `main`'s parsing/exit
codes/printing run unmodified (`tests/fieldguard_planning/test_check_live_flight_log_schema2.py`
`TestCli.main`). Verified 2026-09-07 both ways: with a stray overlapping `bird_drive` in
`eval/results`, the unbound version fails 3/4 and the bound one passes 4/4.

**TWO THINGS A FLIGHT LOG CANNOT ANSWER, both found 2026-09-07 while building the depth-take gates
(P1) — check before designing any gate on top of them:**

* **Acquisition range is CENSORED at the threat cylinder, not measured.**
  `AvoidanceExecutor._log_detection` writes a `detection` event only when the maneuver carries a
  `triggering_detection`, and `AvoidancePolicy.decide` attaches one only for a threat INSIDE
  `threat_radius_m` (12.0 m; 13.416 m at the cylinder corner with `vertical_threat_m` 6.0). So the
  earliest range any log can show is ~13.4 m — a PROOF that no current log can evidence the
  33.591 m acquisition the ADR-020 booking gate is premised on. Out-of-cylinder detections reach the
  policy and vanish: PROCEED's `debug.n_detections` is only logged when `n_stale_dropped` is set.
  Closing it = one field on that event, or a max-detection-range counter on `DepthDetectionSource`.
* **No orientation is recorded anywhere in the log.** `DroneState.heading_rad` is computed in the
  node (from the pose quaternion) and reaches the executor, which logs positions only. Any bearing /
  frustum / camera-geometry reasoning off a flight log must substitute COURSE OVER GROUND from
  `flown_path_enu` and say so — exact while the vehicle translates the way it points, wrong by the
  crab angle in a GUIDED dodge.

**A `depth_blob` log is SCOREABLE since 2026-09-07** (P1 of the dodge-take pre-registration): seven
bars in `check_live_flight_log.py`, quoted verbatim from §P1 and pinned as substrings of it. The
four event-dependent gates (`depth_range_error`, `gate_depth_acquisition`, `gate_depth_frustum`,
`gate_depth_static_map`) return **`(problems, notes, measured)`** — the third element feeds the
`DEPTH BARS MEASURED: N of 4` line, because a depth take with no encounter is VALID with every one
of them UNMEASURED. Two invariants worth not re-deriving:

* **The counter identity is the seam's own arithmetic**, so it can be gated: `on_frame` takes
  exactly one of five paths per call (4 per-frame drop counters + `frames_detected_on` sum to
  `depth_msgs_received`) and times every call in a `finally`, so `detect_wall_ms_n ==
  depth_msgs_received`. `dropped_non_finite_depth` / `dropped_out_of_range` are per-BOX and are NOT
  in the sum.
* **A detection's plausible along-axis depth from a position alone**: `(range − 0.15 m) / corner ≤
  d ≤ range + 0.15 m`, `corner = √(1 + tan²h + tan²v) = 1.2616` at 640×480 / fx = fy = 520.006.
  That gives an EXACT upper bound of `max_range_m × 1.2616 + 0.15` = **75.848 m** at the seam's
  60 m clip — no heading substitution needed, so it can never false-fire on a sound log.

**The joins that DO NOT exist — do not invent them:**

* **flight log ↔ NDVI clip.** No shared run id, no shared field. Sim time restarts near zero every
  run, so overlapping `tick_stamp_sim_s` / clip stamps prove nothing (the checker refuses truth
  tracks on the same reasoning). The only signal is the UTC stamp in the two FILENAMES
  (`live_flight_log_20260825T210402Z` vs `real_flight_20260825T205705Z`, ~7 min apart). State that
  as a filename hint, never as identity.
* **schema-1 logs have no time axis at all** (2026-08-18, 2026-08-23 — no `run` block, so no
  `tick_stamp_sim_s`). Their only axis is the tick index; 5 Hz is the node's NOMINAL control rate,
  not something those flights measured. Never render a schema-1 tick as a second.
* Legacy logs' detections are a static injected bird at (30, 30, 15) with `track_id
  demo_bird_0` — but the event's `source` field still reads `ndvi_blob`. Trust `track_id` and the
  absent run block, not `source`, when deciding whether a schema-1 detection is real.
* Only maneuver events carry `verdict`, and it is always `"accepted"`. A REFUSAL is a separate
  `gate_reject` event followed by a `hold`; counting "refused maneuvers" off the maneuver kind
  returns zero on every log and always will.

See [[node_topic_map]] for the ledger/control-parameter model and [[detection_seam]] for the
schema-2 run block.
