---
name: avoidance-real-detection-take
description: The Week-6 detect→avoid take — its runbook, the host-side precheck gates with their measured margins, the bringup shape (7 panes + an 8th deliberately unlaunched shell), and the post-flight gate sequence and what each verdict means.
metadata:
  type: project
---

`docs/runbooks/AVOIDANCE_REAL_DETECTION.md` (written 2026-08-24) is the ONE runbook for the flight
where a real NDVI detection drives the avoidance loop. It produces two artifacts in one take: the
schema-2 flight log and the NDVI clip. As of writing it has **never been flown**.

**Why it exists:** `AVOIDANCE_DEMO.md` drifted (bringup delegated to archived WEEK3_VALIDATION.md
whose SITL line lacks `--enable-DDS`; a structurally stale tree check `gz topic -l | grep
model/tree_row0_0` — static models advertise no pose topics; no launcher path). ADR-013 am. 11
assigned those drift fixes to robotics-sim-engineer. The new runbook bases bringup on
`FULL_PIPELINE_DEMO.md` + `scripts/fly_pipeline.sh` instead, and deliberately does **not** re-spell
the seven pane one-liners — one source per command, and `tests/test_fly_pipeline.py` byte-diffs them
against FULL_PIPELINE_DEMO.md only.

**How to apply — the host-side gates, with margins measured 2026-08-24, all ~1 s, no Docker:**
- `python3 scripts/predict_bird_visibility.py --fps 5.0` → **PASS, exit 0, medians 8/6/11** frames in
  view over the 55-offset phase sweep. At `--fps 0.41` (the pre-am.-9 cadence) the SAME committed
  geometry returns **1/0/1 and exit 1**. Nonzero = do not book the session.
- `python3 -m pytest tests/fieldguard_planning/test_bird_geometry_contract.py -q` → **17 passed** —
  the avoidance half of the two gates `config/birds/farm_world_birds.json` names (a bird must stay
  inside the ±6 m / 12 m threat cylinder; bird_0 holds it at 11 m under 15 m cruise).
- `scripts/check_tree_positions.py <clip>` on the adopted clip: 18/18 imaged, 9/18 canopy-grade,
  median lift +0.5402, all 12 positive cells within 2 m of a tree centre, exit 0.
- Preflight in-container: `import scipy` (the detector's morphology; `fly_pipeline.sh up` refuses
  without it) and a bit-identical re-score of the adopted clip — jammy 1.8.0 vs the eval pin 1.18.0
  vs host 1.13.1, and the ADOPT verdict was earned on one of them. Expect 24 boxes / 1256 frames.

**Bringup shape:** `fly_pipeline.sh up` (7 panes, golden order, birds altitude-gated at 10 m running
the real committed trajectories) **plus an 8th plain `docker exec`** running `avoidance_node
--detect`. The 8th shell is deliberately NOT a launcher pane: the node writes its flight log in a
`finally` after `rclpy.spin`, and teardown's `pkill` would destroy it. Consequence to remember:
`up`'s already-running refusal greps gazebo/bridge/agent/SITL/ndvi/record/birds — **not**
`avoidance_node` — so a survivor of that shell is invisible to it; check by hand before the next
`up`. Teardown order: Ctrl-C shell 8 and wait for `wrote flight log ->`, THEN `fly_pipeline.sh down`.

**Post-flight gate sequence:** `check_live_flight_log.py <log> --truth <bird_drive_*_applied.jsonl>`
(GT-CPA is the gated number, detection-CPA is an estimator check, R2/R3 + clock assertions), then
`stitch_ndvi.py`, then `check_tree_positions.py`. Verdict semantics worth remembering: INVALID on
"no truth track"/clock/missing fields = procedural, re-fly cheaply; INVALID on a GT-CPA breach = a
real S1-class finding, land R4 first and keep the log with a `SAFETY_FINDING.md` marker; a
`R2/R3 PASS (vacuous)` line means the loop never engaged, so the avoidance half needs a re-fly even
though the gate is green.

Related: [[bird-ground-truth-track]], [[recording-throughput-levers]], [[adr007-ndvi-sensor-mount]],
[[bringup-file-layout]].
