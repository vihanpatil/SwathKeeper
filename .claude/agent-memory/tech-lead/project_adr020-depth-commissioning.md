---
name: adr020-depth-commissioning
description: ADR-020 am. 1-2 — the forward depth mount is COMMISSIONED (all six D-gates measured 2026-09-06/07); D4 exit 0 BOOKABLE at 46.0 m / 5 m/s, but D5+D6 were flown at 3.50 m/s so delivery and pitch AT THE BOOKED SPEED are unmeasured
metadata:
  type: project
---

**COMMISSIONED 2026-09-06/07 (ADR-020 amendments 1-2). All six D-gates have numbers.**

**D2 8/8 PASS.** Live `fx` 520.0058046927554 / `fy` ...553 / `cx` 320 / `cy` 240 / 640×480 (config
fx agrees to **1 ULP** — say "1 ULP", never "identical"). D2 CULL measured the cull law: greatest
finite Z-depth **57.99 m at (289, 374)**, |ray| 1.034 = far/|ray| → the far cull is on **Euclidean
slant while the stored value is Z-depth**, render-verified; `clip_far_m` back-solves to 59.96 m.

**D3 — the rule, as ADR-020 am. 1 ratified it AND as the `.sh` computes it (two bounds, not
three):** *D3-bookable = the longest contiguous-prefix swept range that ALSO sits inside
`far_clip / |ray_corner|` on the live intrinsics.* → prefix 58.0 ∩ corner 47.56 → last swept
station **46.0 m**. The **optical prefix 58.0 m** is a clip-limited resolvability FLOOR and never
books anything.
* **The host pinhole × morphology bound (46.80 m) is NOT a term** — it is one of am. 2's four
  corroborating bounds. A "min of the named bounds" wording sat in the runbook for a day; it
  coincides at 46.0 today only because no swept station falls in (46.80, 47.56], and it diverges
  the moment the morphology bound binds. Corrected 2026-09-07. **If the min-of-three rule is ever
  wanted, it is a rule change: dated amendment first, then the `acq_book` filter in the `.sh`.**
* Whiteboard sentence: **a horizon has to hold at the worst pixel in the frame, not the best one.**
* **USER RATIFIED 46.0 m on 2026-09-07** (options offered: 46.0 / 44.0 / hold-until-segmenter).
* **The plateau is COVERAGE, not blur** (probe B, on run 2's retained frames): plateau member
  *depths* match true Z within 0.02–0.16 m at every station — which also **retro-proves the frames
  were distinct** (depths advance with R), covering the run that predates the G105 hash check.
* Probe 5 (2026-09-07): QA probe A **5/5** at sub-pixel offsets (r_app 2.00, floor 1.75 holds); the
  cull law **bracketed OFF-AXIS** at (580,60) — Z 50 finite, **Z 52 inf**; a bird 6 m below the axis
  is **sky-backed** at 30/40/46 m (ground starts row 374), so the whole ±6 m band is sky-backed at
  the 33.6 m required horizon — which is also the condition the segmenter will NOT enjoy.
* **Far clip STAYS 60 m.** If more horizon is ever needed: **tighter bound, not longer clip**
  (corner from the threat band's own worst pixel = 50.8 m, ~+4 m). Named as a lever, not adopted.

**D4 — `eval/results/booking_gate_20260907T064136Z.json`: exit 0, PASS and BOOKABLE at 5.0 m/s,
margin 1.780×** (3.832 s vs 2.152 s), corner headroom 3.4 %, required horizon 33.59 m. Schema 1.2
records the clamp (`acquisition_clamped_from_optical_prefix` / `..._optical_prefix_m 58.0` /
`..._clamp_bound_m 47.558`). **Two clauses that must travel with the number:** breakeven acquisition
is **33.591 m** (33.6 → exit 0 at 1.300×; 33.5 → exit 1), and 46.0 m is a **best-case-scene UPPER
BOUND** (no clutter, static vehicle, noiseless sensor, sky background, on-axis, blind `isfinite`
mask, no segmenter) — never quote it without that clause.
* **Those two clauses are NOT fields on the artifact, by decision** (2026-09-07): the tool can only
  vouch for arithmetic it performed, and "no clutter, no segmenter" is a fact about the render
  session that produced `--acq-range-m`. Rejected: a `caveats` array required by `validate_report`
  whenever `bookable` is true. They live in ADR-020 am. 2 and are reproduced verbatim in
  `AVOIDANCE_REAL_DETECTION.md` §0f. The half the tool CAN vouch for is already there:
  `budget.required_horizon_m: 33.59` **is** the 33.591 m breakeven, read forwards.
* **The D4 artifact is never regenerated** — `tests/…/test_booking_gate_artifact.py` pins it as the
  record of what authorised the flight, including its now-superseded `band_covered_from_m: 13.0`.

**D5/D6 — MEASURED, AND AT THE WRONG SPEED.** D5 **132 ÷ 132 = 1.000** over a 30 s window, 32FC1, gz
sim clock, 8 SHM segments all 8,413,728 B. D6 pitch (`asin(2(wy−zx))`, negative = nose-down): window
median **−1.175°**; **whole flight −12.498° / +11.240°** — the load-bearing pair, giving 7.3 m of band
edge at 33.59 m against ±6 m = **1.3 m spare**, so the level mount holds.
* **The window's median ground speed was 3.50 m/s, not the booked 5.0** (from the clip's own
  `poses.jsonl`). **Delivery and pitch at 5 m/s are UNMEASURED** — owed by the dodge flight.
* **RETRACTED, do not restate:** "the 5 m/s pitch is bounded above by −1.18°." The window was flown
  SLOWER than the booking speed, so −1.18° is a lower bound on the pitch **MAGNITUDE** (at least
  that far nose-down at 5 m/s, possibly much further) — **say MAGNITUDE**: on a signed quantity
  where nose-down is negative, "a lower bound on the pitch" restates the retracted claim. See
  [[a-gate-is-only-as-true-as-its-scene]] instance 4.
* **`--sweep` never exits 0; it exits 3 when some row passes and 1 when none does.** "Exits 3
  unconditionally" was written in the ADR and printed by the tool's own footer on the run that
  exits 1. Corrected + pinned 2026-09-07.
* Do not quote the gz-side frame counters from that run (0 / 68): `timeout` killed `gz topic -e`
  before its buffer flushed. The metric is the ROS-side pair over one window.

**STILL OPEN after am. 2:** (a) delivery + pitch at 5 m/s, off the dodge flight; (b) the segmenter —
key on depth **DISCONTINUITY**, not `isfinite`, and re-measure the 2 px floor against this render's
morphology in a **cluttered** scene (touched-pixel coverage exceeds a centre-sampled disc by ~3 px at
46–58 m); (c) whether `predict_bird_visibility.py` stays a dodge precondition (recommendation: keep
it REPORTED, forward booking gate AUTHORISING — needs **product-lead ratification before the take is
booked**); (d) the third `corner_ray_ratio` copy in `scripts/verify_depth_mount_geometry.sh` is
unrepaired (still `(w/2)/fx`, `cy/fx`, never parses fy/cx — numerically right on this symmetric
sensor, latent otherwise).

Related: [[adr007-ndvi-render]], [[a-gate-is-only-as-true-as-its-scene]], [[adr-log-must-track-the-gate]].
