---
name: adr003-ndvi-detection
description: ADR-003 decided — detect on NDVI-direct frames; accepted but pending real-render re-confirmation
metadata:
  type: project
---

ADR-003 (NDVI-vs-RGB detection) is **ACCEPTED, confirmation-pending** as of 2026-08-04. Decision:
detect directly on the NDVI-rendered frame (approach (a), NDVI-direct); the synthetic-RGB pass (b)
is retained only as the NDVI+RGB comparison arm, not the detection path.

**Why:** faithful to the single-NDVI-camera hardware (ADR-000), and the Week-2 spike showed NDVI-only
was no less safe than RGB (identical FNR 0.019, per-bird-track FNR 0.000 for both) — so fidelity cost
nothing but easily-suppressed extra dodges. Numbers came from a **synthetic stand-in clip**
(`sim/spike/out/spike_seed42`, `meta.json synthetic:true`), NOT a real Gazebo render.

**How to apply:** treat the framing call as settled — do not relitigate NDVI-vs-RGB. BUT there is a
live open follow-up: ADR-003 must be re-confirmed by re-running `eval/run_spike.sh` on the real Gazebo
NDVI render before it is fully validated. Flag this if anyone treats detection as "done." Also: no
trained detector model is justified yet — the classical-CV blob baseline already clears the FNR bar,
so any proposed model must beat it on the same `eval/` harness to earn its place (scope-creep guard).
This closed the last unmet exit criterion for the Weeks 1-2 gate.
