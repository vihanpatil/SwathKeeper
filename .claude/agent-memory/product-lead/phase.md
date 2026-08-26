---
name: phase
description: Current SwathKeeper phase (as of 2026-08-26 — Ruling 002/ADR-019 ag-avoidance push is the program; forward depth sensor built host-side, commissioning today) and the booking bar for flights
metadata:
  type: project
---

**As of 2026-08-26: the program is the ADR-019 ag-avoidance push, not "finish Week 6".**
Council Ruling 002 RATIFIED WITH AMENDMENTS by the user (ADR-019): product-intent dual-track,
claims capped at "sim-demonstrated, evidence-gated". Engineering track in order, priced in
sessions (6-7, honest range 5-10): **forward depth camera in sim (1-2) → booking-gate PASS (1) →
bar-clearing BIRD dodge (1) → mapped-wire scenario (2) → wire demo take (1)**. Wires are
fresh-per-field-survey mapped infrastructure with a meters-scale sag buffer; no camera wire
detection promised; radar-in-sim researched and REJECTED.

**Why the order changed (the measurement, not appetite):** the 2026-08-26 point-mass replay fired
the ADR-017 tripwire — `speed_at_which_nadir_becomes_safe = None` on the flown encounter (bird_0
closes at its own 6.0 m/s, caps lead at 0.41 s from a hover; every escape needs ≥1.25 s; nadir
needs 17.8-38.8 m of forward sensing and has 2.48 m). So the **second forward sensor was promoted
from growth path to scope**, the tilt stays REJECTED, and **the R4 re-fly now sits behind the
sensor — and is not a separate flight, it IS the bar-clearing dodge take.**

**Sensor status (ADR-020, 2026-08-26):** built host-side, statically gated 23/23 + 80 host tests,
**never rendered** — the booking gate `scripts/predict_forward_lead.py` PASSes the design at
5.0 m/s (margin 1.811×) but exits **3 = NOT BOOKABLE** by construction until D1/D3 supply live
`fx`/`cy`/acquisition range. Commissioning Docker session = `docs/runbooks/FORWARD_DEPTH_SENSOR.md`
gates D1-D6, with the booking gate as D4. My placement/pricing, in ROADMAP: 2 sessions against the
ratified 1-2, D4 absorbed into commissioning; the segmenter session ADR-019 §8 never priced puts
the track at **7 of 6-7**, not under it.

**Closed — never re-open as "next up":** Weeks 1-2 foundation; Weeks 3-4 avoidance loop (ledger
720/0); Week 5 NDVI (four ADR-007 gates, mount gated); recording throughput (2026-08-22, Fast DDS
SHM segment, 5.0 Hz flat — do NOT retry `update_rate_hz` 5 → 2); **ADR-003 criterion 3** (ADOPT
NDVI-direct, per-bird FNR 0.000) and **criterion 2** (2026-08-26 RETIRE-ARM — the RGB R channel IS
the NDVI Red band bit-for-bit, so the arm never was a second sensor; its budget went to the forward
sensor). The 2026-08-25 take FLEW and breached as pre-registered (`gt_cpa_m` 0.0067 m, gated
−1.1210 m vs the 3.00 m bar) — INVALID stands, marker written, pin deliberately withheld, main CI
red by design until the clean re-fly.

**Frozen / cut for this push (2026-08-26, ADR-019 §7):** ALL NDVI work frozen (research verdict:
keep-as-is, invest nothing more — plain NDVI is commoditized, the live reactive loop is the gap);
short `test_2lane` arm RETIRED OUTRIGHT; doc long-tail + R5 move behind the wire demo; **Week 7
shrinks to its user-gated remainder only** (voiceover, README application, Pages — zero engineering
sessions) and runs in parallel. Dashboard is BUILT and browser-verified (ADR-018); README APPLIED.

**Still owed by me (product-lead):** the record shape for committed breach evidence (CI runs the
gate with no `--truth`; a second committed applied track makes takes ambiguous and the CPA never
prints). Unchanged, still a product-lead call.

**The booking bar — the durable part:** a Docker session is priced on the *artifact*, and an
artifact is worthless if the gate scoring it can print a false PASS (QA found 6 such holes in the
fresh GT-CPA gate; a 0.8 s frozen clock turned a true 0.0000 m CPA into a 3.5000 m PASS). "The code
is landed" is not the bar; **"the gate cannot lie" is.** New since ADR-019 §6: **the
no-failure-theater tripwire** — no flight is booked until the predictor clears 3.00 m with ≥1.3×
lead margin on `guided_default`. The next take is *designed to pass*; a failure after a predicted
pass is a plant-model finding that convenes Ruling 003, not another instructive breach.

**How to apply:** flights need the user at the controls, so a session goal is agent-doable offline
work unless it is explicitly prepping/booking a flight. Book a user-flown session only when ONE
take clears several blockers (that pattern has paid off twice). Run the host predictors first —
`predict_forward_lead.py` for the forward sensor (monotone in speed) AND
`predict_bird_visibility.py --speed <actual>` (required, no default since ADR-016; **non-monotone**
in speed, so sweep the range — the two gates do not substitute for each other). Pre-register the
expected outcome, run teardown, and freeze the bird driver before scoring.
*(Scope ruling: [[scope-guards]].)*
(The ~7-8-week hard deadline was **dropped 2026-08-18** — quality over calendar; the scope guard
survives it.)
