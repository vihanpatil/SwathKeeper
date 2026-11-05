---
name: ruling-002-ag-avoidance-push
description: 2026-08-26 ruling on the user's ag-avoidance product push — charter evolves to
  product-intent dual-track, birds-first working-dodge milestone on a forward DEPTH sensor,
  wires as mapped infrastructure (not camera detection), no-failure-theater booking gate,
  6-8 session timeline. RATIFIED WITH AMENDMENTS A1-A3 2026-08-26 (ADR-019).
metadata:
  type: project
---

# Council Ruling 002 — the ag-avoidance product push (2026-08-26)

> **STATUS: RATIFIED BY THE USER 2026-08-26, WITH THREE AMENDMENTS (A1–A3 below, earned by the
> five-track market research run at the user's request before ratification).** Binding; recorded
> as `docs/DECISIONS.md` ADR-019. Supersedes Ruling 001 [[ruling-001-founding-reevaluation]]
> §4 items 3–4 where they conflict; everything else in Ruling 001 stands.
>
> **A1 — "Mapped" means a fresh per-field survey, never an external GIS layer.** Research
> finding: no public dataset covers rural distribution wires (HIFLD starts at 69 kV; the FAA
> obstacle file starts at 200 ft AGL; farm poles are 30–45 ft); the only sub-decimeter wire data
> is proprietary utility LiDAR. The shipping-product model is DJI Agras' mandatory operator
> marking, per field, day-of. The wire scenario's map is framed exactly that way, with a
> sag-aware buffer measured in METERS (published spans move 0.15–1.4 m across NESC's own
> 60–120 °F design swing, before wind sway) — exact buffer set at scenario build from those
> sourced figures. Residual-risk note on the record: 43 % of fatal wire strikes in crewed ag
> aviation involved a wire the pilot already knew about (ATSB 2012–2022). A map reduces risk;
> it does not retire it.
>
> **A2 — The wire-mapping reconnaissance pass is a GATED STRETCH GOAL, not v1 scope.** Reuse the
> forward depth camera; one slow corridor pass; returns accumulated OFFLINE into a fitted curve
> (the ADR-010 offline-stitch pattern — real-time wire recovery is ~79 % even for dedicated
> LiDAR rigs); promotion into `static_obstacles.json` gated on a standalone completeness/accuracy
> measurement; sequenced strictly after the birds-first working dodge.
>
> **A3 — The positioning line is now part of the record and the GTM surface:** phased-array
> radar is standard equipment on every shipping mid-to-flagship ag platform, and the market
> leaders' own manuals still disclaim wire bypass (DJI T50 FAQ: "Obstacle Bypassing is not
> recommended around electric or guy wires"); no commercial mapping platform does live reactive
> avoidance mid-flight. Mapped-wires + measured-limits is aligned with — and more honest than —
> current market practice, and the live reactive loop is the unfilled gap this product occupies.
> One evidence correction from the same research: the pre-ratification draft cited DJI's radar
> as "specifically for powerline sensing" — DJI's own documentation says the opposite for the
> Agras line; the ruling's conclusion (no camera wire detection promised) is STRENGTHENED by the
> corrected evidence, not weakened.

**Question (the user, verbatim intent):** "I need object avoidance to work. I need wire avoidance
to be included. I need solid, repeatable and reproducible experiments. I need software built as an
'ag-avoidance' that I own, that a company can see demos and tests run, and be convinced this is
essential software they need to pay for." Plus: begin the bird dodge that actually works; when can
wire avoidance start.

**Evidence:** `eval/results/replay_point_mass_20260826T160218Z.json` (q3: `speed_at_which_nadir_
becomes_safe_mps = null`; required horizon 17.8–38.8 m at 9.2 m/s; ≥1.25 s physically-resolving
lead); ADR-017 am. 1 (forward sensor promoted to scope); ADR-003 am. 10 (same-aperture second band
buys nothing — RGB R channel IS the NDVI Red band bit-for-bit); ADR-016 am. 2 (lead time, not
ordering, is the binding constraint; XY-only tree vet is a third confound); ROADMAP items 1/6
(Week 7 active, dashboard built, remainder user-gated); DJI Agras ships phased-array radar
specifically for powerline/small-obstacle sensing, 1–50 m (ag.dji.com/newsroom/agras-t40-radar-
and-vision-systems) — the industry does NOT do camera wire detection; no LICENSE file exists in
the public repo (default all-rights-reserved).

---

## RULING

### 1. Charter: PRODUCT-INTENT DUAL-TRACK — the milestone changes, the honesty ceiling does not
The user is the owner; the direction is legitimate and moves WITH Ruling 001 §2's own finding
(the real hazard list is wires > poles/trees > birds; "keep the scenario, rename the abstraction").
The charter evolves: **after Week 7's user-gated remainder ships, the avoidance product track
leads and the portfolio becomes its demo surface.** The deliverable is renamed in the docs to what
it is: an **ag-avoidance module** (dynamic-intruder + mapped-infrastructure avoidance with a
coverage-debt ledger), demonstrated on the reference stack.

*Steelman for the full flip (product-first now, portfolio demoted):* the user knows what they
want; demo assets a company can watch are worth more than a hiring manager's click-through, and
waiting for an "integrator conversation" that nobody has scheduled is passivity dressed as rigor.

*Why the council stops short of the flip:* "companies pay for this" has prerequisites that do not
exist yet and cannot be built this quarter: zero integrator conversations (Ruling 001 tripwire (c)
untouched), TG-1..5 all unmeasured (the plant model — the biggest sim-to-real gap — is unvalidated
against even SITL; ADR-016 am. 2 fitted a_max 1.05 vs the 2.5 default on ONE axis of ONE flight,
ESTIMATED), no hardware, no support surface. A sim demo can honestly earn **"watch it work,
watch it refuse, read the gates"** — it cannot earn "essential, pay for it." The claims ceiling is
**"sim-demonstrated, evidence-gated"**; the evidence culture is the one asset a buyer's engineer
would actually respect, and it is spent the first time a claim outruns a gate.

**"That I own":** the extraction gate does NOT move — extraction after the clean pass (Ruling 001
§4.4), and the clean pass is now this ruling's centerpiece milestone. New booking: the public repo
has **no LICENSE file**, which is all-rights-reserved by default — full ownership, but also
legally unusable as a reference stack. A deliberate license decision (proprietary core +
permissive demo, BUSL, dual) is **owed at extraction time, not now**; recorded here so it cannot
be improvised the night something ships.

### 2. The centerpiece: the WORKING-DODGE milestone (birds first)
ONE clean, bar-clearing, reproducible avoidance flight — the drone detects a bird on the forward
sensor and clears 3.00 m, gated on **lead time AND GT-CPA**, pinned, CI green, re-runnable.
- **Sensor: forward DEPTH camera, separate aperture.** Criterion 2 measured that a same-optics
  second band buys zero geometry (gap +0.000, ADR-003 am. 10); the replay specced the horizon
  (17.8–38.8 m plant-dependent at flown speeds — a stock Gazebo depth sensor covers it); depth
  gives range without the monocular apparent-size prior (median 1.65 m range error today), evades
  the trunk≈bird_1 material collision, and is the only candidate that also serves unmapped-wire
  detection later. Integration point is ADR-009's `detection_source` seam — swap the sensor, keep
  the contract.
- **Birds before wires**, because: (a) it is the user's own first ask and the flagship INVALID
  blocks the extraction gate, CI green, and every demo claim; (b) the dynamic dodge is the
  differentiator — mapped-wire avoidance alone is static-obstacle avoidance, the part incumbents
  already ship; (c) the 3D vet the wire work needs (`is_safe_3d` replacing the XY-only tree vet,
  ADR-016 am. 2's third confound) is the same code the forward-sensor escape sizing needs anyway.
  Build it once, under the milestone.

### 3. Wire avoidance: REAL, and honestly scoped — mapped infrastructure now, sensed later
- **v1 wires are KNOWN mapped infrastructure**, mirroring the trees/birds split that already
  exists: powerline corridors are surveyed and registered in reality, and flying with a wire map
  is what shipping products do. `config/static_obstacles.json` grows a polyline-with-sag obstacle
  class; catenaries authored as chained cylinder segments between pole models in the world.
- **Camera-based wire detection is NOT promised.** A ~10–20 mm conductor is sub-pixel past a few
  meters at this camera's fx 520 px; the industry answer is radar (DJI Agras phased array, 1–50 m,
  marketed for powerlines). In sim, UNMAPPED wire detection is the forward depth sensor's later
  arc — and if authored at true diameter the sim depth camera will honestly struggle at range,
  which is the sim telling the truth. Promising camera wire detection would be the exact
  overclaim this repo exists to refuse.
- **The credible wire demo:** corridor-crossing mission over a mapped catenary; vertical + lateral
  avoidance through the same swept-path vetting (now 3D); GT-CPA gate extended to 3D
  point-to-segment distance against the wire polyline (the `_point_segment_xy_m` machinery gets a
  3D sibling); a reproducible scenario in `eval/scenarios/`; pre-registered expectation before the
  take. Same discipline, new obstacle class.

### 4. The price (scope guard — what pays for this)
- **CUT: ROADMAP item 3's remaining short-`test_2lane` arm and write-up** — retired outright, not
  deferred (n=1 already answered the question that mattered; the shipping-config number exists).
- **FROZEN: all NDVI work for the push's duration** — the half is closed; it is the demo's B-roll.
  Includes the under-lane-vs-between-lane open question (stays unbooked) and the −0.61 range half
  beyond 11 m (stays PROVISIONAL, unbooked).
- **DEFERRED FURTHER: the doc fix-list long-tail (~70 items)** — now behind the wire demo, not
  just behind sequencing. **R5 (FENCE backstop) stays refused on sight.** Full coverage-debt
  reconciliation stays a stretch goal through the entire push.
- **Week 7 shrinks to its user-gated remainder only** (voiceover, README sign-off, Pages) — one
  recording take, no polish loops; it runs on user time in parallel and costs zero engineering
  sessions.

### 5. Tripwires (the no-failure-theater clause is (a))
- **(a) The booking gate — protects the user from "looking pretty failure-like":** the forward-
  sensor re-fly may NOT be booked until the offline predictor (point-mass replay extended with the
  forward sensor's live-measured horizon from `camera_info`, never from config prose) shows the
  planned escape clears 3.00 m with **≥1.3× lead-time margin under `guided_default`** — the
  conservative plant, not the ANGLE_MAX ceiling — at the mission's booked speed. The R-series
  "honest FAIL ranks the next fix" discipline was right for discovery; the next flight is
  **designed to pass**. If it books under this gate and still fails, that is a PLANT-MODEL finding
  (TG register) → Ruling 003 before any second attempt, not another re-fly.
- **(b)** Two forward-sensor engineering sessions without the predictor reaching a bookable spec
  → stop and re-convene; the sensor approach is wrong-sized.
- **(c)** Any artifact that says "essential / pay for / field-ready" without a named external
  conversation or hardware data → CSO veto, text reverts. "Sim-demonstrated, evidence-gated" is
  the ceiling until tripwire (d) fires.
- **(d)** Ruling 001 (c) survives verbatim: first real integrator conversation → re-convene on
  product form with actual data.
- **(e)** If Week 7's user-gated items are still unshipped when the bird dodge lands → the demo
  ships with what exists that session.

### 6. Timeline the user can hold the council to (sessions, not calendar)
| arc | sessions | error bar |
|---|---|---|
| forward depth sensor in sim (mount, bridge, `detection_source` adapter, predictor extension) | 1–2 | +1 if bridge friction |
| escape sizing + booking-gate PASS offline (R4 re-scoped on the measured horizon, `is_safe_3d`) | 1 | +1 if margins are thin |
| the bar-clearing bird dodge: fly, score, pin, CI green | 1 | +1 re-fly only for a non-plant defect; plant failure → Ruling 003 |
| wire world + map schema + 3D vet + GT-CPA wire extension + eval scenario | 2 | +1 (the 3D vet partially prepaid above) |
| wire corridor demo take, scored and pinned | 1 | +1 |
| **total to "working dodge + wire demo"** | **6–7** | **honest range 5–10** |

**Price paid, in one line:** the short-arm study dies, NDVI freezes, docs long-tail and R5 wait
longer, and the product claim is capped at "sim-demonstrated" until an external signal exists.

*Recorded by the Executive Council, second convening, 2026-08-26. Contradicting evidence
supersedes this ruling through Ruling 003, not silence. On ratification: ADR entry via tech-lead;
ROADMAP next-up and cut log updated by product-lead.*
