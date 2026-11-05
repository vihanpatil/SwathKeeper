---
name: flight-20260825-lead-time
description: The 2026-08-25 first real-detection flight breached at 0.0067 m horizontal CPA because nadir-camera FOV gives ~0.4 s of detection lead time and the executor has no maneuver-completion concept — not because of candidate ordering (which is what R4 was scoped as)
metadata:
  type: project
---

The 2026-08-25 `--detect` take (`eval/results/live_flight_log_20260825T210402Z.json`, truth
`bird_drive_20260825T210030Z_applied.jsonl`) failed its own GT-CPA gate exactly as pre-registered.
Measured with the gate's own `ground_truth_cpa`: **gt_cpa 0.006739 m horizontal, bird_0, tick 991,
t_sim 202.775 s; vertical separation 4.03 m, 3D distance 4.030 m.** 1858 ticks, ONE encounter of
FOUR ticks (991-994), 4 detections, 4 maneuvers, **2 relatches in 4 maneuvers**, resume at 995.

**Why it breached — the causal chain, measured, not inferred:**
1. The sensor is a rigid **nadir** mount (`config/ndvi_camera.json` mount rpy (-pi/2,+pi/2,0)),
   63.2 deg h-FOV / 49.5 deg v-FOV. At bird_0's 4 m depth below cruise the ground footprint is
   **4.9 x 3.7 m** (`scripts/predict_bird_visibility.py` prints exactly this) — half-widths 2.45 m
   along-track / 1.85 m cross-track. **The bird becomes visible only INSIDE the policy's own
   3.0 m `min_bird_clearance_m`.** A passing CPA is geometrically unreachable on this
   configuration, whatever the policy decides.
2. The drone flew **8-10 m/s** through the encounter (per-tick steps 0.60-1.26 m at 0.076-0.150 s
   sim steps), so the detection window is ~0.4 s = 4 control ticks.
3. In those 4 ticks the vehicle's x moved **14.997 -> 14.979 m**: 18 mm. A 10 m lateral GUIDED
   position setpoint cannot move a 9 m/s multirotor sideways in 0.5 s.
4. `AvoidanceExecutor._handle_proceed` hands back to AUTO the moment the policy returns PROCEED —
   which happens because the drone flew PAST the bird. **There is no concept of maneuver
   completion anywhere in the repo** (grep: no `dwell`, `converg`, `setpoint_reached`,
   `maneuver_complete` in src/, tests/, or the gate). A dodge that never executed is
   indistinguishable in the log from a dodge that worked.

**How this should reshape R4.** R4 was ranked as "reversal-preferring candidate ORDERING"
(ROADMAP cut log, 2026-08-24). Ordering changes which of 7 vetted directions is chosen; it cannot
buy lead time and cannot make the vehicle move within 0.5 s. Building R4 as scoped will produce a
second honest failure. The binding constraints, in order, are: (a) detection lead time = sensor
FOV geometry, (b) maneuver completion / commitment in the executor, (c) only then candidate
choice. Real ag platforms solve (a) with dedicated FORWARD-looking sensors, never the nadir survey
camera (DJI Agras T50: front/rear phased-array radar + fore/aft binocular vision,
https://ag.dji.com/t50/specs).

**Also true and worth keeping:** the loop behaved correctly and the evidence system caught it. The
detector ran at 99.92 % (1301/1302 frames), the clock never violated, the ledger closed 720/0, and
the gate refused to call it VALID. That is the system working.

**Gate hygiene — FIXED 2026-08-25 (was: *AMBIGUOUS TAKE*).** The 2026-08-23 applied log overlaps
this take's sim window (sim time restarts near 0 every run), so the gate used to decline to score
CPA at all and then wrongly called this take's marker stale. The take is now pinned in
`TRUTH_BINDINGS` (scripts/check_live_flight_log.py) and scores with both tracks present: `gt_cpa_m
0.0067 m` → **CPA BREACH → INVALID, exit 1, HALF acknowledgement (marker, no pin) — the correct
state for a new breach.** No moving evidence files. See [[detection-seam]] for the CI consequence.

Related: [[extractability-audit]], [[detection-seam]], [[node-topic-map]]
