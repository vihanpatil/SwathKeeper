# FieldGuard — Decision Log (ADR-lite)

Owner: `tech-lead` (with `product-lead` for scope calls). **Every non-trivial choice goes here** with
the alternative rejected and a one-sentence reason. Per the playbook's escalation rule, when two
roles disagree the `product-lead` wins for v1 **and the disagreement is recorded here as a tradeoff.**
This log is the engineer's interview script for "why did you build it this way?"

Format per entry:

```
## ADR-NNN: <title>   (YYYY-MM-DD, status: accepted | superseded | proposed)
Decision: <what we're doing>
Alternative(s) rejected: <what we didn't do>
Why: <one to two sentences the engineer can say out loud in an interview>
Owner / roles involved:
```

---

## ADR-000: Build FieldGuard entirely in simulation (2026-07-27, accepted)
Decision: Develop the whole system in sim (Gazebo + ArduPilot SITL + ROS 2); no live hardware in v1.
Alternative(s) rejected: Fly on the single real NDVI-camera drone. Rejected — hardware team is
temporarily unavailable to add sensors, and sim lets us iterate on the hard autonomy problem safely
and reproducibly.
Why: Simulation is the honest, correct choice for iterating on safety-critical reactive avoidance —
and it lets us also simulate a second-sensor config to quantify sensor ROI, which hardware can't.
Owner / roles: product-lead, tech-lead, robotics-sim-engineer.

## ADR-001: Geofence trees as known static obstacles from a pre-flight boundary survey (2026-07-27, accepted)
Decision: Treat tree rows as known static obstacles from a pre-flight boundary survey; reserve the
perception/avoidance loop for genuinely unplanned dynamic obstacles (birds).
Alternative(s) rejected: Detect trees at runtime too. Rejected — ag operators already map field
boundaries in advance, so this is a legitimate real-world assumption, and it cleanly isolates the
actual hard problem (unplanned dynamic obstacles) instead of blurring it with static-map building.
Why: It mirrors how real ag operations work and focuses engineering effort on the differentiator.
Owner / roles: tech-lead, flight-software-engineer.

## ADR-002: v1 replanning = "avoid, return to next waypoint"; full coverage-debt reconciliation is a stretch goal (2026-07-27, accepted)
Decision: Ship the simplest correct avoidance-then-resume for v1; document full coverage-debt
reconciliation (requeue every missed cell) as an explicit stretch goal.
Alternative(s) rejected: Build full reconciliation up front. Rejected — it risks blocking v1 on the
hardest sub-problem; shipping the simple version first keeps the core loop demoable on schedule.
Why: Protects the deadline while keeping the harder version as documented, defensible interview material.
Owner / roles: product-lead, tech-lead, flight-software-engineer.

---

## ADR-003: NDVI-vs-RGB detection approach  (status: PROPOSED — resolve after the Week 1-2 spike)
Decision: _pending spike._
Alternative(s): (a) detect directly on NDVI-rendered frames (recommended, matches real hardware);
(b) render a synthetic RGB pass in sim for perception only.
Why: To be decided by `perception-ml-engineer` on a metric (detection precision/recall on a labeled
sim clip), not before. Fill this in when the spike lands.
Owner / roles: perception-ml-engineer, tech-lead.
