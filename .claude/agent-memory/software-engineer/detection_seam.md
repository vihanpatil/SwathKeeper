---
name: detection-seam-live
description: The live ADR-009 detection seam in avoidance_node (one gz clock, apparent-size ray, run-block schema 2, the pinned-pre-seam legacy ratchet, the TRUTH_BINDINGS truth-join pin) plus the offline dry-run numbers and why committing a breaching take turns CI red
metadata:
  type: project
---

Landed 2026-08-24 (`avoidance_node.py` + `ndvi_detect.py` seam half + `ndvi_georef` inverse). NOT
YET FLOWN — everything below is offline evidence gathered before booking the take.

## The contract, in one paragraph
`--detect` arms `NdviDetectionSource` on the `detection_source` seam. The node subscribes
`/fg/ndvi/image` (**BEST_EFFORT depth 1** — a control loop wants the newest frame; the recorder's
RELIABLE depth 10 is the opposite requirement) and `/fg/ndvi/camera_info` (ndvi_node's own
pass-through; intrinsics come from the MESSAGE, never `config/ndvi_camera.json`). Frames pair to the
pose nearest their OWN gz stamp via `clip_recorder.PoseBuffer`; a pair whose residual exceeds
`STALE_PAIR_BOUND_S` (0.35 s) is dropped and counted. Boxes become world-ENU positions by
`ndvi_georef.range_from_apparent_size` + `pixel_at_depth_to_enu` — **never** `pixel_to_ground_enu`,
which puts a bird at z=0, 15 m below cruise, outside the ±6 m threat cylinder (a real threat,
silently suppressed; pinned as an executable test).

## ONE CLOCK — the bug that was there and the tripwire that replaced it
Before this build `_on_tick` built `t = get_clock().now() - t0` (elapsed wall seconds) and called
`decide_multi` with NO `now_s`, so `max_detection_age_s` could never evaluate. **Passing that same
`t` would have been worse than the bug**: NDVI stamps are absolute Gazebo sim seconds, so
`age = elapsed - gz_absolute` is large and NEGATIVE → every detection reads fresh forever, silently,
because unstamped detections already fail OPEN. Now: a native `gz topic -e -t /clock` subprocess
(same `StreamingClockParser` the recorder uses; NEVER a bridged /clock) supplies both the pose tags
and `now_s`. `CLOCK_DOMAIN_BOUND_S = 0.5` — a detection stamped further in the future than that
counts as a clock-domain violation, and the flight-log gate fails any run with `violations > 0`.
`--detect` REFUSES TO START without a clock reading (10 s poll, exit 3).

## Numbers measured offline, 2026-08-24 (host, scipy 1.13.1)
Dry run of the whole seam over the ADOPTED clip `real_flight_20260823T073644Z` (1256 frames, 645
airborne), using the clip's own poses + intrinsics:
- **Boxes bit-identical** to `eval/results/adr003_20260823/detections_ndvi.json` (24 boxes over 20
  frames) — the live seam is the same detector ADR-003 am. 7 adopted, not a lookalike.
- **Phantom-dodge rate WITH a denominator: 8 / 1256 frames (0.64 %), 8 / 645 airborne (1.24 %)**
  would have produced an IN-CYLINDER threat. 5 of those 8 coincide with a real in-cylinder bird;
  the other 3 are **bird_1 lifted into the cylinder by the range bias** (true z=8 → |dz| 7 m,
  outside the ±6 band; estimated |dz| 5.85-5.99 m, just inside). So the 0.15 m radius prior's
  under-ranging does not merely shorten range — it can pull a sub-cylinder bird INTO the threat
  band. Conservative direction, real coverage cost. Three clusters, so ~3 encounters per flight:
  the flight is BOOKABLE, not a dodge storm.
- **Range-estimate error vs applied-pose truth: median 1.65 m, max 3.67 m (n=24)** — much larger
  than the single 3.27-vs-3.92 m case quoted in am. 7. Position error to the nearest true bird:
  0.50-3.69 m.
- **`detect_wall_ms` p95 4.8 / max 26.9 ms over 1256 frames** (8.2 / 11.0 in the busy encounter
  window) against the 200 ms control tick — the detector will not block the executor.
- Dress rehearsal (101 encounter frames replayed through PoseBuffer → on_frame → tick → run block →
  `check_live_flight_log.py`): gate consumes the artifact, auto-discovers the truth track,
  reports `gt_cpa_m 0.177 m` vs `detection_cpa_m 0.026 m` on the recorded (un-dodged) path. Also
  showed **2 relatches in 5 maneuvers** — monocular position jitter can exceed
  `RELATCH_THRESHOLD_M` 3.0 m, so re-latch churn is a live watch item (R3 only refuses below 1.0 m).

## Flight-log `run` block (schema 2) — written by the NODE, not the executor
`log["run"] = {schema_version: 2, policy_params, clock, tick_stamp_sim_s, detector}`.
`tick_stamp_sim_s` has exactly one entry per `executor.step()` (step records exactly one flown-path
position on every branch), which is why the gate can assert the two lengths match. Legacy logs have
no `run` key and keep the verdict they were flown under — **but only if the gate PINS them as
pre-seam** (`PRE_SEAM_LEGACY_STEMS` = the two historical live logs, matched by STEM because CI copies
them into tmp trees; plus the `eval/scenarios/<name>/flight_log.json` shape, whose generator runs
OFF-ROS and has nothing to put in a run block). Round 5, 2026-08-24: `run_block_problem` used to
return None whenever the key was simply ABSENT, so `del log["run"]` demoted a schema-2 flight onto
the legacy detection-referenced CPA path — and a ground-truth INVALID (detector missed the bird at
closest approach → no detections → nothing to measure) came back **VALID "NO-CPA-EVIDENCE"**, by
deleting one key in a gitignored directory. Any other log with no run block is now INVALID. **The pin
is a property of the FILE, never of its contents** — the same doctrine as `ACKNOWLEDGED_BREACH_STEMS`:
whoever produced a log can edit its contents but cannot edit a reviewed diff on the gate.
`detector.source` is `ndvi_blob` |
`demo_virtual` | `none` — and the demo sources now stamp `demo_virtual` instead of inheriting
`Detection`'s `ndvi_blob` default (a virtual bird had been claiming to be an NDVI blob in every log
ever flown; the gate branches on this because a demo bird's logged position IS exact truth).

## What the take must now SHOW for the gate to score it (QA rounds 1-3, all 2026-08-24)
Ways a schema-2 pass could still mean nothing, closed in `check_live_flight_log.py`. Each is a
bringup precondition, not just a checker rule:
- **The time axis must MOVE, and a stall is PRICED — FROM THE STAMPS.** `run.clock` stays
  `gz_clock_stream`/0 violations if the node's `gz topic` thread dies or Gazebo pauses — `_gz_now`
  just stops — and the domain tripwire can only fire on a tick that carries a detection (8 of 1256
  frames on the adopted clip), so a freeze is silent for ~99 % of a flight while the GT-CPA join
  re-dates the whole path onto one instant AT 100 % REPORTED TRUTH COVERAGE (measured: 2.0402 m
  breach → 3.4490 m pass). TWO wrong denominators have now been deleted: `MAX_FROZEN_TICKS = 5`
  (borrowed from the 1.0 s staleness bound — freshness has nothing to do with the truth JOIN), and
  then `(N-1)/CONTROL_HZ` at a hard-coded 5 Hz (round 3, F5: the ROS timer is on a WALL clock on a
  box that starves, so the nominal bound UNDER-counts — measured 1.75x at 0.35 s/tick, 2.5x at 0.50,
  5.0x at 1.00). **The window is now read off the flight's own stamps**: a run of ticks all reading
  `v`, closed by the next stamp that advanced to `v_next`, hides `v_next − v` seconds (a clock
  reading never runs ahead, so `v` is its own lower bound); a run that never recovers is priced at
  the flight's measured mean sim-step × its length. `freeze_debit_m(window_s) = window_s × max
  scripted bird speed` (7.0043 m/s from `config/birds/farm_world_birds.json`). The **worst** run is
  priced, not the longest. A debit reaching `min_bird_clearance_m` is a CLOCK fault (no marker can
  acknowledge it) and is **not** subtracted — a negative gated CPA would dress an unmeasured flight
  as a close pass.
- **NEITHER body is vertex-sampled.** Drone: `gt_cpa_m` is over the flown POLYLINE (point-to-SEGMENT
  against both segments bounding each tick), because vertex sampling is >= the true minimum by
  construction — a true 2.8200 m pass read 3.0008 m PASS. Bird (round 3, F1): sampling the bird at
  TICK instants misses any landed `set_pose` whose whole in-effect window falls between two ticks,
  and the bird is the faster body — a bird driven through a hovering drone at a 0.70 s tick period
  read **3.8067 m → VALID on a 0.0000 m strike, at 24/24 truth coverage**. Every landed pose is now
  ALSO scored over its OWN window (`pose_windows`: opens at the call's `sim_start`, closes at the
  NEXT call's `sim_end`) against the drone sub-segment that window covers. Fraction of poses no tick
  ever saw, on the committed 839-pose log: 0.0 % at 0.121 s/tick (today's healthy rate), 3.2 % at
  0.50, 29.6 % at 0.80, 41.6 % at 1.00. Read BOTH denominators — `truth coverage K/N ticks` (drone
  axis) and `truth poses scored K/N` (bird axis); the first reads 100 % regardless of the second.
  `joined via tick_sample|pose_window` names which pass produced the number.
- **`ndvi_node` must be publishing `/fg/ndvi/camera_info` BEFORE the `--detect` shell starts.**
  `NdviDetectionSource.on_frame` drops every frame while `intr is None`, and the node has no
  startup guard on intrinsics the way it has one on the clock. A take that starts them in the wrong
  order flies to completion and writes a clean log with `frames_detected_on: 0`. The gate fails that
  (`DETECTOR NEVER RAN`) **and now fails a RATE** below `MIN_DETECT_RATE = 0.90`
  (`frames_detected_on / ndvi_msgs_received`; the offline dry run is 1256/1256 = 100 %, and a 10 s
  startup transient at 5 Hz is ~3 %) — 1 frame of 1256 used to pass with no comment. Revisable once
  a real `--detect` flight measures the rate in the air.
- **A flight whose every detection EXPIRED must be distinguishable from a quiet sky.** All-stale →
  PROCEED on every tick, and PROCEED carried no `debug`, so `n_stale_dropped` read 0 in BOTH cases
  while avoidance was dead (a sub-second clock offset does this silently — the domain tripwire only
  fires on stamps in the FUTURE). `AvoidanceExecutor._stale_detail` now writes the drops on
  proceed/hold events too, and drops > 0 with 0 detection events is a hard `AVOIDANCE WAS DEAD`.
- **Every COMMANDED DISPLACEMENT must hold the bird bar (R3.7 + R3.8) — and a HOLD is EXEMPT.** The
  executor's backstop was `is_safe_3d` only, which cannot see a bird — an R3 refusal re-commanded a
  latch the bird had walked to 1.000 m of, against 3.00 m, logged `accepted`. The executor now
  re-vets the point it is about to command against `debug["threat_positions_enu"]` and writes a
  `gate_reject` instead. Round 3 split the gate's two halves honestly: **R3.8** reads the
  `gate_reject` events (the only LIVE evidence the backstop fired; a reject naming neither an
  obstacle nor a sub-bar bird gap is a hard failure), **R3.7** is the exhaustion property (no
  `maneuver` may record a setpoint inside the bar — unreachable on a log this executor produced,
  proved by 10,000 random control ticks, so it defends against older/edited logs only).
  **The carve-out is structural, not a bug to fix here:** a HOLD commands the vehicle's own position
  — ZERO displacement — so it chooses no point and honours no bar, and the R3-refusal branch is only
  entered when `range_degenerate` is True, i.e. the vehicle is inside `degenerate_range_m` and
  therefore inside the 3.00 m bird bar BY CONSTRUCTION. Measured: a reject at 1.000 m holding at
  0.400 m (2.5x worse), and 41 of 10,000 ticks holding inside the bar, closest 0.288 m. The
  executor logs `bird_clearance_m` on every hold; the gate prints the minimum as CONTEXT, NEVER
  gated, pre-registered as the R4-open signature — **always, and with its denominator**
  (`holds with a threat=N of M hold(s)`, `0 of 0` included), because a silent line made "no hold
  named a threat" and "the field stopped being written" look identical. A hold with NO USABLE
  `bird_clearance_m` — key absent, or a value `_num` refuses (string/dict/bool) — is a hard FIELD
  DRIFT failure; an explicit `None` stays legitimate (the decision named no threat). The wrong-TYPE
  half was the quiet one: it fell into the "named no threat" bucket while the hold count kept rising. **Commanding a point that IS outside the bar is
  escape geometry — R4, open and deliberately uncut.** Also on that path: rejecting the latch kills
  it, and a FIRST latch at degenerate range is permitted, so the next tick may latch the same
  noise-driven point fresh — R3 buys a tick there, not a refusal.
- **A failing rate never prints as the floor.** `_floor_pct` TRUNCATES the detect rate to the digits
  it prints, so `1130/1256 = 89.96%` can never read "90.0%" beside "below the 90% floor" (round 3,
  F7 — the sentence reads as a gate bug and invites widening the floor after a failure).
- **`drive_birds` must drive EVERY bird the config defines.** A bird with zero LANDED set_pose
  calls used to be answered at its config spawn pose for the whole flight and counted as coverage —
  and bird_0 (z=11, |dz| 4 from cruise) is the ONLY bird the ±6 m vertical scoping ever gates, so
  an invented one either fabricates a breach or hides a real one. Unobserved birds are now omitted
  from the truth answer and named as a hard failure; spawn-derived answers are reported separately
  as `answered_from_spawn N/M`.
- **ONE take, ONE applied log.** `--truth` used to skip candidate discovery entirely, so the
  runbook's own `ls -t …_applied.jsonl | head -1` silently picked the tail-covering log after an
  aborted takeoff or a `fly_pipeline.sh birds` restart, and every earlier tick was answered from
  SPAWN poses. `resolve_truth` now counts candidates even with an explicit `--truth` and fails
  `AMBIGUOUS TAKE`, naming the other logs. (Sim time restarts near 0 each run, so overlap alone can
  never pick the take — that is why this is a refusal, not a heuristic.)
- **…and the THIRD reviewed pin, `TRUTH_BINDINGS`, is what makes that refusal survivable (G47,
  fixed 2026-08-25).** Because sim time restarts near 0, the first COMMITTED applied log overlaps
  every later take, so from the second committed take onward the refusal above fired on every new
  flight: `AMBIGUOUS TAKE → INVALID`, **no CPA printed at all**, and then a wrong "stale marker"
  complaint (the breach was unreachable, so the marker looked like it sat beside a passing log).
  CI could never have reproduced a breach verdict. `TRUTH_BINDINGS` maps flight-log stem →
  applied-log FILENAME, is consulted FIRST, bypasses the overlap scan, and is resolved BESIDE the
  log (same as the `.SAFETY_FINDING.md` marker) so a log copied without its truth is unscoreable
  rather than silently joined to whatever sits in this repo. An explicit `--truth` must AGREE by
  name. Unpinned flights are byte-identical to before. **The pin is per take, landed in the same
  reviewed diff as the evidence commit** — the runbook's old workaround (`mv` the 2026-08-23 track
  to /tmp and `git checkout --` it back) is no longer the answer for a committed take.
- **The driver sidecar cannot do this job, checked and rejected.** A `run_id` field in
  `bird_drive_<stamp>.json` would be a NO-OP: the driver's own stem is already the filename, the
  `applied_log` field and `written_utc` (2026-08-25T21:00:30Z). And a stem-timestamp-proximity
  auto-join needs a free constant N minutes with no derivation, on the one join a safety verdict
  rests on. The only non-heuristic future alternative is WALL-CLOCK CONTAINMENT (wall time does not
  restart) — but the flight log carries **no wall stamps at all** (`run` = clock/detector/
  policy_params/schema_version/tick_stamp_sim_s), so it would need a new node-written field and
  would only help future takes. Not built; the pin is one reviewed line per take.

## COMMITTING A BREACHING TAKE TURNS CI RED — measured 2026-08-25, and it is the gate working
A NEW breach is a FAILED flight: the marker beside the evidence, **no** `ACKNOWLEDGED_BREACH_STEMS`
pin (that list is for recorded history that cannot be re-flown), verdict INVALID, exit 1. So the
moment the 2026-08-25 evidence is committed, **two** things go red and both are correct:
1. `ci.yml` step "Validate committed live flight-log evidence" — the glob matches all three logs
   (`.gitignore` re-includes `live_flight_log_*.json`, `*.SAFETY_FINDING.md` AND
   `bird_drive_*_applied.jsonl`), the two historical logs stay ACKNOWLEDGED, the new take is
   INVALID → step exits 1. Simulated on a fresh-checkout tree: it reproduces `gt_cpa_m 0.0067 m`.
2. `tests/test_ci_evidence_gate.py::test_step_passes_on_the_committed_evidence`, which asserts
   exit 0 on a hermetic copy of the committed evidence — that premise ends with this take. (Its tmp
   tree now also copies the `bird_drive_*` tracks, so when it does go red it says BREACH and not
   "no truth track".)
The choices are: accept red CI until R4 lands and the take is re-flown clean; or acknowledge the
breach with both halves (a reviewed pin — the doctrine says that is for history, not a new
failure); or hold the evidence out of the tree. **Not a code decision — escalate it.** Whatever is
chosen, do NOT weaken the gate or the count assertion to get green.

## Deliberate non-features (do not "fix" without evidence)
No tracker (`track_id=None`). No second expiry inside the source — `__call__` returns the latest
frame's detections unconditionally and ageing them is `max_detection_age_s`'s job, one home. No
numpy fallback for scipy: `--detect` exits 2 with the rebuild instruction. Related:
[[node-topic-map]], [[throughput-instrumentation-results]].
