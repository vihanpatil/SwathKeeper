---
name: week6-detection-seam-open-questions
description: The three Week-6 detection_source seam questions (clock domain, CPA reference, detector transfer) — ANSWERED 2026-08-24 with binding calls; use these, do not re-derive
metadata:
  type: project
---

Raised 2026-08-24 standup, **answered the same day** as binding architecture calls before the build
fanned out. Written here because each one is a rule a future session will otherwise re-litigate.

1. **Clock domain = Gazebo sim seconds, end to end inside `avoidance_node`.** Mechanism is the one
   `clip_recorder`/`record_node` already ship: a native `gz topic -e -t /clock` subprocess +
   `StreamingClockParser` + `PoseBuffer` — never a bridged `/clock` (bridging it starved the image
   pipeline, measured 2026-08-18). `Detection.stamp_s` = the `/fg/ndvi/image` header stamp;
   `now_s` = the gz stream reading. `--detect` REFUSES TO START without a clock reading (10 s wait,
   exit nonzero) — a whole take is more expensive than a startup check. A detection stamped in the
   future by > 0.5 s is counted as a clock-domain violation and fails the flight; that is the
   tripwire for the absolute-vs-elapsed inversion, which is otherwise invisible because unstamped
   detections fail OPEN. Evidence for `max_detection_age_s = 1.0`: the am.7 clip's own
   `frame_age_sim_s` is p50 0.143 / max 0.156 s (n=1256) — ~6x headroom, not taste.
2. **CPA is measured against GROUND TRUTH, and truth depends on what the threat was.** Real
   detector -> the bird's own applied-pose log (`drive_birds.py` already writes it; no writer
   change) read through `eval/annotate_real_clip.applied_timeline` / `pose_from_applied`, so the
   safety gate and the ADR-003 labels can never disagree about where a bird was. Virtual `--demo`
   bird -> the logged position IS exact truth, today's R1 code unchanged. Two scoping rules that
   are easy to get wrong and expensive to discover live: only bird/tick pairs INSIDE the threat
   cylinder's `vertical_threat_m` band are gated (bird_1/bird_2 fly 7-9 m below cruise and would
   otherwise fail every flight on horizontal distance alone), and inside a set_pose bracket the
   gate takes the NEARER candidate (uncertainty must not buy clearance).
3. **The detector lives in `src/fieldguard_planning/ndvi_detect.py`; `eval/` imports it; scipy is
   added to the image.** A numpy reimplementation would void the am.7 FNR-0.000 transfer, so the
   measured scipy code path moves verbatim and the transfer is proved by re-scoring the am.7 clip
   to BIT-IDENTICAL boxes against the committed `eval/results/adr003_20260823/detections_ndvi.json`
   — on the host AND inside the container (jammy ships scipy 1.8.0, the eval pin is 1.18.0).
   `-0.61` stays PROVISIONAL and becomes an explicit node argument recorded into the flight log.

**Why it matters beyond the seam:** the flight-log gets `run.schema_version` so gates travel in the
artifact — legacy logs keep exactly the verdict they were flown under, and the new contract cannot
be flown without meeting it. That pattern is reusable for the next gate.

**All three were BUILT the same day, offline** — the seam is wired behind `avoidance_node --detect`
(ADR-009 am. 1), the gate scores GT-CPA off the applied-pose log (ADR-013 am. 14), and the detector
is single-sourced with scipy in the image (ADR-003 am. 8 / ADR-004 am. 1). Nothing has flown, and the
gate's own adversarial pass left six open findings — see [[avoidance-take-blockers]] before booking.

**How to apply:** treat these as decided. The open ones that remain are named deliberately: the
latched setpoint's swept path is not re-vetted as ownship moves; a FIRST latch at degenerate range
is still allowed; S1's escape geometry (R4) is untouched, so the next avoidance flight may honestly
FAIL its own CPA gate — that is a measurement, not a wasted take. Related:
[[adr003-ndvi-detection]], [[adr006-avoidance-executor]], [[adr007-ndvi-render]].
