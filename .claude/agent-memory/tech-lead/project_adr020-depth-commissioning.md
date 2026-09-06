---
name: adr020-depth-commissioning
description: ADR-020 am. 1 (2026-09-06) — the forward depth mount is render-verified (D2 8/8); D3 hands the booking gate the CORNER-CLAMPED range (46.0 m), not the optical prefix (58.0 m); far clip stays 60 m
metadata:
  type: project
---

**The forward depth mount is LIVE-VERIFIED (2026-09-06, ADR-020 amendment 1).** D2 **8/8 PASS**,
live `fx` 520.0058046927554 / `cy` 240.0 (config-derived fx is ...555 — they agree to 1 ULP; say
"1 ULP", not "identical"). D2 CULL measured the cull law itself:
greatest finite Z-depth **57.99 m at (289, 374)**, |ray| 1.034 = far/|ray| — so **the far cull is on
Euclidean slant while the stored value is Z-depth** is now render-verified, not source-read, and
`clip_far_m` back-solves to 59.96 m (i.e. it is a *measured* quantity now).

**THE RULE — D3 prints two numbers and only one books a flight.**
`D3-bookable = the longest contiguous-prefix swept range that also sits inside far_clip/|ray_corner|`
computed from the LIVE fx/cy (**47.56 m** today) → **46.0 m**. The **optical prefix (58.0 m)** is a
best-case-scene resolvability **FLOOR** and never enters the booking gate.
* **Why (the whiteboard sentence):** a horizon has to hold at the **worst pixel in the frame, not
  the best one** — past the corner bound the same bird a few degrees off-axis is culled to `+inf`.
* **ADR-019 item 6 ("from camera_info, never config prose") is satisfied:** the line item 6 draws is
  **measured-vs-asserted, not config-vs-not-config**. fx/cy are live; the far clip and the cull law
  it extrapolates along are both measured by D2 CULL.
* **Known cost, do not pretend otherwise:** the clamp makes the gate's
  `acquisition_within_corner_far_clip` check unfailable *on that input path* (it still bites in the
  design/`--sweep` modes). Open follow-up: `predict_forward_lead.py` schema 1.2 should record that
  the number was clamped (`acquisition_optical_prefix_m`).
* Sweep quantum 2 m: 46.0 is the last SWEPT value under 47.56, and quantisation rounds the horizon
  **down** = less lead = the safe direction.

**Far clip STAYS 60 m — the clutter argument, quantified.** Raising it buys the booking gate nothing
(46.0 already passes at 5 m/s with 27 % horizon headroom over the required 33.59 m) and imports
clutter: at far 60 the ground goes finite from row ~374 and the ±6 m threat band's lower edge shares
rows with it only below **23.2 m**; at far 100 that overlap grows to **39.6 m** — essentially the
whole required horizon. If more horizon is ever needed, the cheap lever is a **tighter bound, not a
longer clip** (corner from the threat band's worst pixel = 50.8 m, ~+4 m).

**Booking gate at 5.0 m/s on live intrinsics:** 46.0 → **exit 0 BOOKABLE, margin 1.780×**;
58.0 → exit 1 failing ONLY the corner check. The design number was 1.811× on the geometric bound —
the measurement came in slightly worse, as measurements do.

**STILL PENDING:** D5 (depth delivery ratio under flight load) and D6 (cruise pitch) — they come
from a flight; slots are left blank in the amendment, do not invent them. Also open: the segmenter
must re-measure the 2 px floor against this render (the footprint **plateaus at a 4×4 px patch**
past ~40 m and survives on *area*, so the disc-calibrated floor does not describe this renderer),
and whether the nadir bird-visibility gate is still a dodge precondition (recommendation: keep it
REPORTED, make the forward booking gate the authorising one — needs product-lead ratification).

Related: [[adr007-ndvi-render]], [[a-gate-is-only-as-true-as-its-scene]], [[adr-log-must-track-the-gate]].
