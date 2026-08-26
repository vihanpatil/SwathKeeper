---
name: evidence-consumption-seams
description: How to consume committed flight/NDVI evidence without re-deriving it — the gate functions to call, and the joins that DO NOT exist (flight↔clip has no run id; schema-1 has no time axis)
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
