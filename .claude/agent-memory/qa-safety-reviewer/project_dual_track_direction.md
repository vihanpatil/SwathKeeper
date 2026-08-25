---
name: project-dual-track-direction
description: The 2026-08-25 binding direction — finish portfolio v1 AND make the avoidance core extractable as a product seed; what that changes about how QA ranks findings
metadata:
  type: project
---

**Set 2026-08-25 by the user, binding on evaluations from that date.** SwathKeeper runs DUAL-TRACK:
(1) finish the portfolio v1 arc — R4 → clean take → dashboard/demo; (2) make the avoidance core
**cleanly extractable as a product seed**, aimed at the ag-survey-drone company class ("Vaara Drone"
named as the archetype; **not publicly findable** as of 2026-08-25, so treat it as the CLASS, never
as a named customer). The user's stated preference is the FULL REFERENCE STACK adopted wholesale;
the user explicitly asked for that preference to be pressure-tested rather than agreed with.

**Why:** the project was at risk of being "a waste of code and tokens" — the user asked for a
brutally honest re-assessment and set this direction as the answer. "This part is a dead end" is a
successful finding; performed harshness is not.

**How to apply — what it changes for QA specifically:**
- Rank findings by **which track they hurt**. A defect inside `src/fieldguard_planning/{avoidance_policy,
  avoidance_executor,coverage,geofence,avoidance_types}.py` (1,584 LOC, verified pure-stdlib —
  no numpy, no rclpy) hurts BOTH tracks and outranks a sim-world or docs defect.
- The extraction boundary is real and is a genuine strength: the five core modules import only
  stdlib, so the seed can ship without ROS/Gazebo. Say so plainly when it holds; check it still
  holds before leaning on it (`grep '^import\|^from'` on those five files).
- Add a lens to every audit: **would this embarrass, or impress, a drone-company engineer?** Named
  external anchor: the industry norm for reactive avoidance is a depth-producing sensor (PX4-Avoidance
  uses stereo/ToF/LiDAR; the repo's own `aerial-autonomy-stack` reference uses YOLO + simulated
  LiDAR), so ADR-009's monocular apparent-size ranging will always draw the question "why no depth?"
  — the answer must lead with the measured range error (median 1.65 m / max 3.67 m, ADR-009 am. 1),
  not with the rationale.
- ADR-011's "code identifiers keep the FieldGuard name" was cheap under a portfolio-only charter.
  Under extraction it is a per-consumer cost: 77 files carry `fieldguard`/`fg_`/`/fg/*`. Do not
  rename unilaterally — ADR-011 is a live-verified contract — but price it when extraction is
  actually scheduled.

Related: [[project-open-safety-gaps]], [[reference-safety-scenario-catalog]],
[[reference-docs-evidence-chain]].
