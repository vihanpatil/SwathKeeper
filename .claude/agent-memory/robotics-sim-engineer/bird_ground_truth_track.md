---
name: bird-ground-truth-track
description: The bird applied-pose log is the flight's ONLY bird ground truth (labels + safety CPA); its measured clock-anchor numbers, schema versions, and the offline rehearsal harness that tests it without Gazebo.
metadata:
  type: project
---

`eval/results/bird_drive_<UTC>_applied.jsonl`, written by `scripts/drive_birds.py`, is the only
record of where the birds actually were — nothing in the ROS 2 graph publishes bird poses. It feeds
BOTH `eval/annotate_real_clip.py` (ADR-003 labels) and, from 2026-08-24, the safety gate's
closest-approach measurement (`check_live_flight_log.py --truth`).

**Why:** a monocular apparent-size range cannot referee its own safety margin (3.27 m estimated vs
3.92 m true), and a detector MISS at closest approach used to score as no-evidence-of-a-breach.
Two historical flights breached bird clearance by ~5 cm under green gates.

**How to apply:** never add a second bird-truth path. If a consumer needs bird poses, it reads this
log through `drive_birds.applied_sim_brackets` / `applied_sim_span` +
`annotate_real_clip.applied_timeline` / `pose_from_applied` — one reconstruction, so a bug is wrong
for the labels and the safety gate together, never quietly for one.

Measured numbers worth keeping (2026-08-23 take, 860 records / 839 ok / 3 birds, sim 110.4-263.8 s):
- `/clock` poll (`gz topic -e -t /clock -n 1`) costs **39 ms median, 42 ms p95, 146 ms max** of wall.
  Schema 1.0 logs anchored `tick_sim_s` at the PRE-poll instant, so every bracket was late by that
  much × RTF — up to ~0.8 m of bird motion asserted with false precision. Schema **1.1** records
  `clock_wall_s` (post-poll) and widens the bracket over that interval. 1.0 logs reconstruct
  bit-identically (verified against the committed am. 7 log).
- `set_pose` round-trip: 237 ms median, 2.04 s max. Achieved tick rate ~1.3 Hz at `--rate 2`.
- RTF over one flight: 0.34 → 0.93 (median 0.58) — never assume a constant.

The offline rehearsal lives in `tests/fieldguard_planning/test_bird_truth_log.py`: a `FakeGazebo`
with its own clock lets `drive_birds.main()` itself be flown (KeyboardInterrupt from the fake ends
the run), so anchor wiring and bracket containment are checked with **no Docker session**. Use it
before booking a take. Related: [[recording_throughput_levers]], [[farm_world_layout]].
