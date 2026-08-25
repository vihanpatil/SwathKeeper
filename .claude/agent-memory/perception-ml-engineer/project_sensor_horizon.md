---
name: sensor-horizon-vs-threat-cylinder
description: The nadir NDVI camera can never image the policy's 12 m threat cylinder inside the ±6 m band — measured 2/7 in-cylinder frames and 0.175 s of lead on the 2026-08-25 take; this is what R4 must be priced against
metadata:
  type: project
---

**Measured on the first real-detection avoidance take (2026-08-25,
`eval/results/adr003_20260825/visibility_budget.json`). The 2026-08-25 CPA breach was a GEOMETRY
failure, not a detector-sensitivity failure, and every value-based gate stayed green through it.**

The numbers, from the clip's own measured (`applied`) labels through the one projection primitive
(`ndvi_georef.project_world_point`), airborne window only (671 frames):

| bird | frames in threat cylinder | frames in image |
|---|---|---|
| bird_0 | 7 | **2** |
| bird_1 | 0 | 0 |
| bird_2 | 0 | 0 |

The 5 missed in-cylinder frames were **1.4–7.8 m outside the image edge** (median 3.8 m). The bird
entered the cylinder at 8.41 m horizontal and only entered the *image* at 1.75 m.

**Why it is structural, not tuning.** The nadir footprint scales with depth; the threat cylinder
does not. Half-footprint reaches the 12 m threat radius only at **19.5 m (along-track) / 26.0 m
(cross-track)** depth — both far outside the policy's **±6 m** vertical threat band. Inside the
band the camera images at most **9.0 %** of the cylinder cross-section (at 6 m below) and **4.0 %**
at this encounter's 4.03 m separation. Birds *above* the drone — half the band — are behind a nadir
camera and are unimageable at any range.

**Lead time, the metric that damns the take** (this metric family was in `eval/README.md` and had
never been measured in the air):
- **sensor lead = 0.175 s** (first frame containing the bird, stamp 202.6 → GT-CPA 202.775);
- **policy lead = 0.000 s** — the first detection was consumed on the CPA tick itself;
- camera dwell in cylinder 1.4 s, dwell **in image 0.4 s**, closing ~14.4 m/s.
Estimated detection range at first sight: 3.43 m (true 3.95 m depth / 4.32 m slant) inside a 12 m
cylinder.

**The abort gate would have caught it, at the right speed.** `scripts/predict_bird_visibility.py`
PASSes at its 3.0 m/s default and **FAILs (3 of 3 birds below the 5-frame floor) at --speed 8 and
--speed 9.4**. The encounter was flown at ~9.4 m/s. `--backtest` on the flown clip reproduces
reality exactly: **2 / 0 / 0** frames in view, nearest miss for bird_1 184.8 px, bird_2 212.2 px.
The predictor's model is sound; its `DEFAULT_SPEED_MPS = 3.0` is the defect.

**Gates that measure VALUES cannot catch GEOMETRY — second instance.** `MIN_DETECT_RATE`'s first
in-air measurement is **1301/1302 = 99.92 %** against a 0.90 floor, i.e. 130× slack, on a take where
the detector saw a bird on 2 frames of 1301. The single lost frame was `dropped_no_intrinsics=1`,
the startup-ordering transient the constant's own comment predicted — but one frame, not the ~3 %
it budgeted for. Do **not** narrow the floor on n=1: the failure mode it guards is bringup ordering,
which is exactly what varies between takes; it needs ≥3 takes. Record the measurement, keep the
floor.

**How to apply:** price any R4 escape-geometry proposal against **0.175 s of sensor lead and 0.4 s
of dwell**, not against the policy's 12 m cylinder — R4 alone cannot buy warning time that the
sensor never had. The levers that actually move this number are ground speed, mount tilt (a
forward-tilted camera would use the detector's ~40 m of unused range headroom, see
[[ndvi-rgb-spike]]), and a second sensor — which makes this the concrete case ADR-003 criterion 2's
comparison arm exists to answer. Before booking any re-fly, run the predictor **at the speed the
mission will actually fly**.
