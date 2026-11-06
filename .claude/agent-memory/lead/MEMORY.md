Consolidated 2026-11-05 from exec-council, product-lead, tech-lead (team v2); entries below keep their original dates and role names.

# lead — memory index

## From exec-council
- [Ruling 002 — ag-avoidance push](ruling-002-ag-avoidance-push.md) — 2026-08-26 **RATIFIED WITH
  AMENDMENTS A1–A3 (ADR-019)**: product-intent dual-track (claims capped "sim-demonstrated"); birds-first
  working dodge on a forward DEPTH sensor (separate aperture, replay-specced); wires = mapped
  infrastructure v1, no camera wire detection promised; booking gate = predictor must clear
  3.00 m with 1.3x lead margin on guided_default before ANY re-fly; 6-7 sessions (range 5-10);
  cuts: short-arm study dies, NDVI frozen, license decision booked for extraction time.
- [Ruling 001 — founding re-evaluation](ruling-001-founding-reevaluation.md) — 2026-08-25: NOT a
  hole, but value mislabeled (evidence culture + ledger are the asset; bird framing is proxy;
  full-stack-wholesale <5 % odds → demonstrator-hybrid); actuation blind spot found (84 maneuvers,
  0.5–4 % compliance, confound resolvable offline); next session = point-mass replay + cheap
  honesty fixes, then ONE re-fly, then Week 7 immediately; tripwires inside. **RATIFIED by the
  user 2026-08-25 — binding; recorded as ADR-016 + ROADMAP entries.**

## From product-lead
- [Phase](phase.md) — as of 2026-08-26: ADR-019's ag-avoidance push IS the program; forward depth sensor built but never rendered, commissioning + booking gate D4 next
- [Scope guards](scope-guards.md) — standing "DO NOT ADD SCOPE, guard the exits" call + the recorded cuts (ADR-019's NDVI freeze, R4 promoted/re-scoped, R5 still out, no booking on a design number)

## From tech-lead
- [DIRECTION IS C 2026-11-05](project_direction-c-ruling-2026-11-05.md) — owner ruled C: build the gate tool, 10 posts, B deferred; ADR-022 **am. 4** (am. 2/3 are R8)
- [ADR-022 DIRECTION RESET 2026-09-10](project_adr022-direction-reset.md) — portfolio floor → 10-conversation method market test → drone-as-product deferred; wire CUT; four standing freezes
- [ADR-003 NDVI detection CLOSED](project_adr003-ndvi-detection.md) — ADOPT NDVI-direct on the real render (2026-08-23); −0.61 threshold still PROVISIONAL, no model justified
- [Week-6 seam: ANSWERED](project_week6-detection-seam-open-questions.md) — binding calls 2026-08-24: gz clock end-to-end, GT-CPA vs applied-pose log, detector single-sourced to src/ + scipy in the image
- [Avoidance take: FLOWN + SCORED + BREACHED](project_avoidance-take-blockers.md) — gt_cpa 0.0067 m, pre-registered (ADR-013 am. 18); R2 passed live, R3 vacuous by 15 mm, R4 re-scoped by 0.175 s of LEAD TIME
- [Swath over-claims the camera](project_swath-vs-camera-footprint.md) — ledger swath 7.5 m vs measured 6.886 m cross-track half-footprint: 8.2 % of every lane pitch is scored covered but never imaged
- [ADR-020 depth mount COMMISSIONED](project_adr020-depth-commissioning.md) — all 6 D-gates measured 2026-09-06/07; D4 exit 0 at 46.0 m/5 m/s; D5+D6 flown at 3.50 m/s so the booked speed is unmeasured
- [ADR-021 segmenter SCORED, never flown](project_depth-segmenter-design.md) — 7 bars pass on 85 cluttered stations, 46.0 m QUALIFIES; blocker = a depth log is deliberately UNSCOREABLE
- [A gate is only as true as its scene](project_a-gate-is-only-as-true-as-its-scene.md) — 5 instances of green-over-nothing + the guard-side twins: mutate the conjunct, and measure your tolerance's own margin
- [ADR log must track the gate](project_adr-log-must-track-the-gate.md) — DECISIONS.md went stale on the same gate twice; correct today's uncommitted text in place, append once committed
- [Moving a doc costs a stub](project_moving-a-doc-costs-a-stub.md) — append-only DECISIONS forces stubs; build_docs_site.py is the only doc gate (run it); a doc test that SKIPs is not a pin
- [Scenario fixtures are OPEN-LOOP](project_scenario-fixtures-are-open-loop.md) — their CPA is a scenario parameter, not a flown outcome; CPA gate stays scoped to committed live logs (ADR-013 am. 16)
- [ADR-005 AP_DDS contract locked](project_adr005-apdds-contract.md) — /ap/* map locked to pinned SHA, CONFIRMED live 2026-08-05; the most extractable artifact in the repo
- [ADR-006 avoidance executor](project_adr006-avoidance-executor.md) — AUTO->GUIDED->AUTO, our code owns the maneuver; CONFIRMED live; MIS_RESTART=0 still typed at flight time, not pinned
- [ADR-007 NDVI render](project_adr007-ndvi-render.md) — Red=RGB cam, NIR=thermal sensor repurposed; gates green live 2026-08-18; the NIR band is authored, so this NDVI does not transfer to hardware
- [ADR-023 gates tool BUILT 2026-11-05](project_adr023-gates-tool-built.md) — scored on 3 public logs; ERR citation reach ruling, G260 intersection rule, G257 open
- [Gates tool design 2026-11-05](project_gates-tool-design-2026-11-05.md) — C step 1; Rev 2 after QA G211-G227 (all accepted); limits from log PARM; now the pre-registration of ADR-023
