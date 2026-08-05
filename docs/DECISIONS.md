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

## ADR-003: NDVI-vs-RGB detection approach  (2026-08-04, status: ACCEPTED — confirmation-pending; spike landed, see docs/SPIKE_ndvi_vs_rgb.md §Outcome)
Decision: Detect directly on the **NDVI-rendered frame itself** (approach (a), NDVI-direct), faithful
to the single-NDVI-camera hardware (ADR-000). The synthetic-RGB pass (b) is **retained but not as the
detection path** — it becomes the NDVI+RGB comparison arm that quantifies what a second sensor buys.
No trained model is justified yet: the classical-CV blob baseline already clears the safety bar, so
any future model must beat it on the same `eval/` harness to earn its place (pre-empts scope creep).
Deciding numbers (spike clip `sim/spike/out/spike_seed42`, seed 42, 30s@10fps, 3 birds, blob baseline):
  - (a) NDVI-direct: precision 0.445, recall 0.981, **FNR 0.019, per-bird-track FNR 0.000**
  - (b) synthetic RGB: precision 1.000, recall 0.981, **FNR 0.019, per-bird-track FNR 0.000**
  Decision rule (spike §3) fires for (a): per-bird FNR 0.000 ≤ 0.10 AND frame FNR within 0.10 of (b)
  (gap 0.000) → fidelity wins the precision tiebreak. The feared failure mode (bird over bare low-NDVI
  soil → false negative) did NOT occur: caught 12/12 visible frames, birds read negative NDVI cleanly
  below soil (~0.15). (a)'s precision gap is explained, not mysterious: 66/66 false positives are ONE
  static clutter feature (zero random-noise FPs), suppressible later by the static-obstacle-map
  sanity-check + blob motion-tracking — a wasteful dodge is cheap, a missed bird is not.
Alternative(s) rejected: (b) detect on a synthetic RGB pass. Rejected as the detection path — it would
make the headline demo depend on a sensor the real drone doesn't have (an interview liability), and it
was no safer here (identical FNR), so there is no safety reason to pay the fidelity cost.
Why: We detect on the exact frame the real NDVI camera produces, so nothing about the perception demo
has to be walked back — and the numbers show the NDVI-only signal catches every bird as reliably as
RGB does, so fidelity costs us nothing but easily-suppressible extra dodges.
Open follow-up (do not silently forget): the spike clip is a **SYNTHETIC stand-in, not a real Gazebo
render** (`meta.json synthetic:true`) — the numbers validate the eval harness and give a strong first
signal but do NOT yet validate against the real render. The framing call is made **now** (default (a)
was never in real danger of falsification), but ADR-003 must be **re-confirmed by re-running
`eval/run_spike.sh` on the real Gazebo NDVI render** before it is treated as fully validated.
Owner / roles: perception-ml-engineer (decided on metric), tech-lead (recorded).

---

## ADR-004: Pin the simulation toolchain versions  (2026-07-27, status: ACCEPTED)
Confirmed by `robotics-sim-engineer` against ArduPilot's `ardupilot_gz` docs and the
`aerial-autonomy-stack` reference (both pin the same stack); no landscape shift as of mid-2026.
Exact pins live in `CLAUDE.md` "Pinned versions" and the bringup steps in `docs/WEEK1_BRINGUP.md`.
Note: `ardupilot_gazebo` uses the `ros2` branch (not `main`), and ArduPilot firmware tracks `master`
(not a stable Copter tag) because the AP_DDS/ROS 2 bridge surface tracks master — the one remaining
open item is capturing the exact firmware commit SHA once the Week 1 build is green.
Decision: pin **Gazebo Harmonic (LTS)** + ArduPilot's **`ardupilot_gz`** ROS 2
integration on **ROS 2 Humble** (Ubuntu 22.04), matching ArduPilot's officially documented and
CI-tested stack, run inside a **Docker/Ubuntu container** (the dev machine is macOS, where this
stack is not practically supported natively).
Alternative(s) rejected:
  (a) **ROS 2 Jazzy + Harmonic** — newer LTS, longer support horizon, but ArduPilot's docs and CI
      primarily exercise Humble, so it carries more first-run setup risk. Kept as the fallback.
  (b) **Native macOS install** — rejected; Gazebo + ArduPilot SITL + ROS 2 aren't practically
      supported on macOS, and fighting that would burn the Week 1-2 gate.
  (c) **Gazebo Garden** — rejected; Harmonic is the current LTS and the release ArduPilot targets.
Why: the Week 1-2 gate is "get a mission flying," so following ArduPilot's most-documented,
most-tested combination minimizes setup risk on the critical path; longevity is secondary for a
time-boxed portfolio build.
Owner / roles: robotics-sim-engineer (research + confirm exact branch/tags), devops-reliability-engineer
(container image), tech-lead (recorded). Promote to `accepted` with exact pins written into
`CLAUDE.md` once robotics-sim-engineer confirms compatibility.
