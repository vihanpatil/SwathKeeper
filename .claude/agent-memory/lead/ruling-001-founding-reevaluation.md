# Council Ruling 001 — the founding re-evaluation (2026-08-25)

> **RATIFIED by the user 2026-08-25.** The §4 direction is binding; the §5 tripwires are live.
> Recorded as `docs/DECISIONS.md` ADR-016 and in `docs/ROADMAP.md` (Next up + cut log, same date).

**Question (from the user):** Is SwathKeeper a hole — outdated, not useful, a waste of code and
tokens? Evaluate every decision. Set direction under the new dual-track charter (portfolio v1 +
extractable product seed for ag-survey drone companies; preferred form: full reference stack).

**Evidence base:** 3 sourced research sweeps (market, DAA state of the art, OSS adoption), 2 full
ADR audits (ADR-000 → am. 18), a foundations/extractability audit, an adversarial red team that
attacked all of it, and the scored 2026-08-25 first real-detection take. Sources in the
strategic-reeval workflow record; load-bearing claims spot-verified by the red team.

---

## RULING: Not a hole. But the value is mislabeled, the roadmap's next item is wrong, and the
## clock on making any of it visible is running.

### 1. What is real (all five lenses agree; red team confirmed)
- **The evidence culture is the asset.** Gates that fail their own flights, pre-registered negative
  results, ground-truth CPA, acknowledgment as a reviewed diff, "commanded is never recorded as
  flown." Both auditors independently called the ADR log better than most production teams keep;
  the red team's only correction was scope ("top-decile discipline applied to the *decision*
  layer"). The industry's defining scandal is unverifiable DAA claims (ASSURE's stated motivation:
  the LACK of independent performance data) — this repo is a working miniature of the fix.
- **The extractable core is real.** Policy/executor/ledger verified stdlib-pure by import probe;
  `VehicleCommandSink` and `detection_source` are genuine seams; extraction priced at ~5 focused
  sessions (packaging from zero, API surface already right-sized).
- **The coverage-debt ledger is the most product-shaped idea in the repo** — in spraying (where the
  money is), a silently skipped swath is unsprayed crop; operators already complain avoidance
  "stopped missions" with no reconciliation. Nobody ships "avoidance that books its debt."

### 2. What is proxy, said once and plainly
- **Bird avoidance has no commercial referent.** The ag hazard list is wires > poles/trees >
  terrain > manned aircraft > birds (ordering directional, not strictly sourced — red team). No
  incumbent ships or is asked for bird avoidance; incumbents ship radar. Birds-attacking-drones is
  a real niche (raptors, survey ops) but an operational-loss story, not a product category. Keep
  the scenario, rename the abstraction: "small dynamic intruder, exercised on scripted birds."
- **The NDVI detector is scaffolding** — the repo already says so; the seam is the product surface.
- **Full-stack-wholesale adoption has <5 % odds** (PX4's own avoidance stack died archived; the
  best current reference stack has 579 stars and zero visible commercial adopters; incumbents are
  vertically integrated). The viable version of the user's preference is the hybrid: **a reference
  stack that demonstrates the extractable component** — read and cited, not `pip install`ed.

### 3. The blind spot nobody had named (red team, then independently confirmed by the take anatomy)
**No avoidance command has ever moved the aircraft.** Across 3 live flights, 84 accepted
maneuvers: commanded ~10 m, achieved 0.18 / 0.42 / 0.05 m lateral — 0.5–4 % compliance, NOT
improved by warning time. Every gate answers "was the setpoint vetted?"; nothing answers "did the
aircraft go there?" The 2026-08-25 breach anatomy agrees: 0.434 s of GUIDED authority, 1.8 cm
flown, sensor lead 0.175 s, policy lead 0.000 s. Candidate-ordering (R4-as-scoped), warning time,
and plant compliance are **confounded** — and the confound is resolvable OFFLINE with a ~50-line
velocity-limited point-mass replay of the committed logs. The vehicle flies at ArduCopter defaults
(no WPNAV_*/GUID_* tuning anywhere in the repo); the flagship negative result may be part
configuration artifact. Three constants-from-prose defects form the same pattern (swath 7.5 m vs
camera's 6.886 m; predictor DEFAULT_SPEED 3.0 vs flown ~9 m/s; MIS_RESTART pinned nowhere):
**physical parameters must come from the vehicle/sensor, never from a document.**

### 4. Direction (binding recommendations to the user)
1. **Next session is the offline confound-resolver, not R4.** Point-mass vehicle model + replay of
   all three flights, sweeping candidate order × lead time × plant limits. It settles the R4
   debate without a flight, becomes the first executable missed-detection scenario, and is the
   transfer-gap register's first entry (the plant IS the biggest sim-to-real gap).
2. **Bundle the cheap honesty fixes in that same session:** MIS_RESTART into the param file;
   predictor speed read from the flight, not a constant; threat persistence/hysteresis (~10 lines,
   one empty frame must not end an encounter); swath half-width derived from camera_info (the
   ~7.7 % area over-claim dies before any dashboard quotes coverage); criterion-2 forced binary
   (run the 1 h RGB pixel study or retire the arm — limbo buys nothing).
3. **Then ONE re-fly** with whatever the replay says actually buys clearance (likely: maneuver
   completion R4a + plant tuning + warning time; R5 FENCE backstop for independence) — and then
   **Week 7 immediately**: demo, README description, dashboard-light. The repo has 0 stars and no
   description after 30 days; for BOTH tracks the highest-return remaining work is making the work
   visible. Adoption talk is fiction until one real integrator conversation exists.
4. **Extraction starts only after the clean pass** — publishing a component whose headline safety
   claim is a documented failure inverts the whole story. Scope it to the seams that exist.

### 5. Tripwires (reverse this ruling if hit)
- If the point-mass replay shows even a perfect escape cannot clear 3 m at the maximum lead time
  this sensor geometry can ever give → **reopen the nadir-only mount decision** (accidental
  coupling, not scoped) before any further avoidance work.
- If two more working sessions pass with Week 7 still unstarted → CEO lens forces the demo
  regardless of engineering state.
- If a real integrator conversation happens → re-convene on the product form with actual data.

**Price paid:** R4-as-candidate-ordering (the roadmap's #1) is deferred behind the replay; the
full-stack-wholesale ambition is demoted to demonstrator-hybrid. Nothing else is cut.

*Recorded by the Executive Council, inaugural convening. The measured basis lives in the
2026-08-25 strategic-reeval and take-scoring records; contradicting evidence supersedes this
ruling through Ruling 002, not silence.*
