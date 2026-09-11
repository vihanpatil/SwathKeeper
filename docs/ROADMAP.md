# SwathKeeper — Roadmap (living document)

Owner: `product-lead`. Update at each `/standup`. History lives in `docs/BUILD_LOG.md`; decisions
in `docs/DECISIONS.md`; this file is only ever **the current truth and what's next**.

**Deadline status (2026-08-18):** the original ~7-8-week / Europe-trip hard stop is **dropped**
(user decision). Quality over calendar — but the **standing scope guard survives the deadline**:
nothing gets added to scope without something else being cut in the same breath, and every
`/standup` is still measured against protecting the demo + dashboard exit.

**Direction (ADR-022, 2026-09-10):** after an end-to-end audit the owner reset the program —
**portfolio floor first**, then a **market test of the METHOD** (~10 conversations about running
pre-registered evidence gates on other teams' logs; kill criterion 0 of 10), with
**drone-as-product deferred** behind that answer and hardware behind that. The wire program is CUT;
NDVI and the depth segmenter are frozen. *Next up* below is that sequence and nothing else.

## Where we are (2026-09-10)

One table, one date, one state per row. Where a row and any other document disagree, this row and
`docs/SPEC.md` win (ADR-022). Claims ceiling on every line: **sim-demonstrated, evidence-gated**.

| Area | State, measured | The number that says so |
|---|---|---|
| Weeks 1-2 — sim foundation + detection decision | ✅ closed 2026-08-04 | boustrophedon flew autonomously; ADR-003 decided NDVI-direct on a fixed-seed clip |
| Weeks 3-4 — reactive avoidance loop | ✅ **flew 2026-08-05** and has flown 3 times since. **Three flights, three bird-clearance breaches** — the loop takes over, dodges and resumes; it does not yet clear the bar | gate-recomputed CPA **0.0393 / 0.0391 / 0.0067 m** vs **3.00 m**. Two `--demo` takes ACKNOWLEDGED exit 0; the 2026-08-25 take **INVALID exit 1, and it stands** |
| Week 5 — NDVI pipeline | ✅ closed 2026-08-22, **FROZEN since 2026-08-26** (ADR-019 §7, ADR-022 8(d)). Kept as the working demo | **720/720** cells, **5.0 Hz flat**, 18/18 trees imaged. The world authors 4 temperatures — a canopy-vs-soil sign test, no health variation |
| Week 6 — real detector on the seam | ✅ **flown 2026-08-25**; seam, R2 and the GT-CPA gate all behaved. The take is INVALID and the diagnosis is **geometry, not the detector** | 1302 frames received / 1301 reached the detector / **2 frames with a detection, 2 boxes**; GUIDED window **0.434 s**, lateral **0.018 m** against a 10 m command |
| Week 7 — dashboard, video, GTM | 🟡 **dashboard BUILT 2026-08-26** (ADR-018): static, client-side, verdicts derived by importing the gate. **Pages + demo video are PENDING THE OWNER**, not engineering | `--check` FRESH 17/17; the 2,887-word script in `docs/drafts/DEMO_VIDEO_SCRIPT.md` is finished and unrecorded |
| ADR-020 forward depth sensor | ✅ **COMMISSIONED live 2026-09-06/07** — all six D-gates measured, exit 0, and the booked speed is now enforced at both ends (am. 3) | **46.0 m bookable at 5.0 m/s**, margin 1.780×. **Asterisk: D5 and D6 were measured at a 3.50 m/s median ground speed**, so delivery and pitch at the booked 5.0 remain UNMEASURED |
| ADR-021 depth segmenter | ✅ **SCORED 2026-09-07** and **NEVER FLOWN**; **FROZEN** until a depth flight exists | 7/7 pre-registered bars on **85 parked, noiseless stations**: FNR 0/49, merge 0/71, unmapped FP 0/8, range p95 0.1076 m. Cluttered acquisition **46.0 m** — clutter-backed evidence reads to **28 m** |
| Scoring a depth flight log | ✅ **SCOREABLE since 2026-09-07** (P1) — `depth_blob` is in `DETECTOR_SOURCES` with seven pre-registered bars. *(The "a depth log is UNSCOREABLE" blocker is CLOSED; any doc still saying it is stale.)* | bar 5 will read **CENSORED** and bar 6 **UNMEASURED** until the executor logs the seam's longest-range detection and `static_map_hint` (P2) |
| Evidence gates + CI | 🟡 `main` is red **by design** on the pre-registered half-acknowledgement — **plus two undeclared Linux-only failures** in `tests/test_build_dashboard_data.py` (a staleness check and a last-digit float compare). An undeclared red is how a real one hides | one declared red; steps 7-12 skipped behind it, including the seed-42 FNR regression |
| Repo state | 🟡 `origin/main` is **`98096e8` (2026-09-07)**; `feat/depth-segmenter` is **5 commits ahead, unpushed**, tree clean | push + PR is step 0 of *Next up* |
| Suite totals | one home: **`tests/README.md`** — re-run the three commands there, re-quote every quoter or none | *(deliberately not quoted here; five doc homes with no test enforcing them is how they went stale)* |
| Open safety findings | 🔴 **R8** — the committed coverage mission violates its own XY geofence by **−1.997 m** on leg 4, waived on altitude, and CI runs the check `\|\| true`. Owed a diff (ADR-022) | `scripts/check_mission_geofence.py` exits 1 today |

### The 2026-08-25 take — what it measured (the system working)

The flight was pre-registered in writing to be allowed to fail its own gate, and it did. That is the
outcome, reported as-is: **a 0.0067 m horizontal overflight of bird_0 at tick 991 (t_sim 202.775 s),
4.03 m vertical separation — inside the ±6 m threat band — while a dodge was nominally in progress.**
The avoidance loop moved the vehicle **1.8 cm** laterally against a 10 m command, in a 0.434 s GUIDED
window. Freeze debit 1.1277 m off a 2-tick / 0.161 s stall.

The diagnosis is **geometry, not the detector**. Of 3 birds, only bird_0 was ever visible: 7 frames
truly in the threat cylinder, **2 of them inside the image**, and the detector boxed **both** —
TP 2 / FP 0 / FN 0 on a denominator of 2, which is why `score.py` correctly refused with **EVIDENCE
INSUFFICIENT** rather than re-confirming ADR-003. The nadir footprint at 4.03 m depth is 4.96 × 3.72 m
against a 12 m threat radius; inside the vertical band the camera images at most 9 % of the cylinder
cross-section. **Sensor lead time 0.175 s; policy lead time 0.000 s** — the first detection arrived on
the CPA tick itself. No escape geometry can buy warning time the sensor never had.

Two gates were green on top of it — the 99.92 % detect rate and the ledger — which is the second
instance of the standing trap: **gates that measure VALUES cannot catch GEOMETRY.**

Also measured, and load-bearing for the next booking: the runbook's own §0b abort gate
(`predict_bird_visibility.py`) **PASSed at its then-3.0 m/s default and FAILs at the ~9.4 m/s the
encounter was actually flown**. That default's provenance cited a file containing no speed figure,
and it is what booked a 2-frame encounter. **CLOSED 2026-08-25 (ADR-016):** `--speed` is now
REQUIRED with no default (a missing speed exits 2 — a refusal, distinct from PASS 0 / FAIL 1), and
the gate FAILs the committed geometry at every speed the vehicle actually flies.

Quote **671 airborne / 649 painting** frames from this clip, never `num_frames` 3310 — teardown was
skipped, so 2639 frames are a parked drone below the ground plane (all zero-update; the honest
denominators are in the artifact).

### What landed offline 2026-08-24, and what gates each piece

Four things shipped in one session. None of them is *done* by this project's own definition until a
flight exercises it — "landed offline" is a claim about the host suite, not about the vehicle.

| landed | what it is | its live gate |
|---|---|---|
| **The seam** | the ADOPTED am. 7 blob detector on `avoidance_node.py`'s `detection_source` under ADR-009 (`stamp_s` staleness gate, apparent-size ray, **never** ground-plane). ONE clock end to end: absolute Gazebo sim seconds, with a >0.5 s-future tripwire and a refuse-to-start if no `/clock` reading arrives | the flight |
| **R2 + R3** | `lateral_tree_margin_m` 0.0 → **1.0** and degenerate-range re-latch refusal (ADR-013 am. 12). Priced, not guessed: over 11,856 degenerate cases HOLD 5.64 % → 15.66 %, min accepted swept clearance 0.000 → **1.000 m**, sub-metre tail 28.1 % → **0 %**; the flown encounter still dodges 19/19. Hardened 2026-08-24: the executor re-vets every commanded point against the bird bar; a refusal is now stated as **REFUSED — zero displacement, honours no clearance bar**, and the HOLD it falls through to logs its own bird clearance so the gate can **report it as ungated CONTEXT** (never a verdict; R4 owns escape geometry) | the flight |
| **GT-CPA** | the safety bar is now measured against the birds' **applied-pose ground truth**, read through the same functions the ADR-003 labels use. Monocular `detection_cpa_m` is demoted to a labelled estimator check and is never a gate. Legacy logs keep their verdict on a versioned branch — both historical breach logs still read ACKNOWLEDGED, byte-identical. Hardened 2026-08-24: `gt_cpa_m` is a segment (polyline) lower bound on **both** axes — a second pass joins each landed bird pose to the drone sub-segment its render window covers, so a bird driven through the drone *between* ticks is now a breach, not a 3.8 m PASS; a frozen clock is priced as a bird-motion debit **measured in seconds off the flight's own stamps** (at/over the bar the gate stands on the clock fault and reports `gt_cpa_gated_m NOT COMPUTED`); `--truth` no longer bypasses the ambiguous-take guard; a detector *rate* floor replaces the zero-check | the flight |
| **The runbook** | `docs/runbooks/AVOIDANCE_REAL_DETECTION.md` — 7 panes + the 8th `--detect` shell, both preflights, evidence-first teardown, the exact `--truth` scoring line, and a pre-registered expectation | the flight |

**Public `main` is `98096e8` (2026-09-07).** `feat/depth-segmenter` carries **5 unpushed commits**
on top of it (booking enforcement, the segmenter, the node wiring, the docs, the P1 depth gates);
the tree is clean. `main`'s CI is red by design on the pre-registered half-acknowledgement — see the
*Evidence gates + CI* row above for the two undeclared reds beside it. **Suite totals live in
`tests/README.md` and nowhere else**; re-run the three commands there rather than quoting a number
from this file. Full narrative: `docs/BUILD_LOG.md`.

## Standing traps (learned the expensive way; still live)

- **Do not retry `camera.update_rate_hz` 5 → 2** (2026-08-19: 16× *worse* delivery at unchanged RTF).
  Reasons preserved in `config/ndvi_camera.json`'s `update_rate_note`.
- **Judge a lever by `red_frames / camera_info_frames`; judge a *map* by painting frames.** The
  2026-08-21 take's "454 frames" read five times better than the 51-frame artifact it produced.
- **Cells imaged is not the metric.** Three pre-mount-fix clips imaged *more* cells and *more* trees
  and returned **zero** canopy-grade trees, with every positive cell 6.4-11.9 m off any tree.
- **Run the host predictor before booking any flight**
  (`scripts/predict_bird_visibility.py --speed <the mission's actual speed>`, ~1 s; `--speed` is
  required and has no default since ADR-016).
  **Run it at the speed the mission will actually fly** — 2026-08-25 proved the default is the defect:
  PASS at the 3.0 m/s default, FAIL at `--speed 8` and `--speed 9.4`, and the take flew ~9.4 and got
  2 bird-visible frames of 3310. The published medians 8/6/11 are the 3 m/s figure. **Refuse the
  session on medians 0/0/1** — that is how the 2026-08-21 take produced 0 of 454.
- **No speed makes nadir safe on the flown encounter geometry (2026-08-26, QA-confirmed).** Do not
  book a nadir real-detection avoidance take expecting a GT-CPA green: bird_0's own 6.0 m/s closing
  speed caps sensor lead at 0.41 s *from a hover*, and every escape needs ≥1.25 s. §0b now refuses
  every real booking speed on this geometry — that refusal is the gate working (ADR-017 am. 1).
- **The §0b visibility medians are NOT monotone in speed** (lane-arrival phase aliasing; measured
  2026-08-26): sweep the mission's speed range, never assume "faster is conservative". And a
  `guided_ceiling` resume in any flight log makes that take **diagnostic, not evidence**.
- **One open question, unproven at n=3, no ADR until someone separates it:** trees sitting *under* a
  flight lane read soil-grade (+0.000 / +0.614 / +0.622) while trees imaged from *between* lanes read
  +0.85…+0.92. Parallax fill vs sample poverty are both consistent. It would matter for the NDVI
  product, not just for the check.

## Next up, in order (the ADR-022 sequence, 2026-09-10)

**0. The owner's two calls, then push.** (a) ~~confirm or overturn~~ **ADR-020 amendment 4 — CONFIRMED 2026-09-11, with am. 5's forward-looking rule: no depth-camera dodge is booked until the segmenter is re-scored on a tall-obstacle world with clutter at ≥ 33.6 m** (owed only if the deferred loop path is pursued); the original call: — the P5
ruling that cluttered acquisition is 46.0 m on the pre-registered definition, so the invalidation
clause did not fire; (b) choose a **LICENSE** (Apache-2 / BSL / AGPL — it decides who may evaluate
this repo tomorrow). Then push `feat/depth-segmenter` and open its PR.

**1. The portfolio floor lands** — this refactor: the five state documents reconciled to the measured
tree, the debris deleted, the honesty artifacts **widened** (all three breaches disclosed, the
INVALID verdict kept, the red CI declared *exactly*). New engineering is capped at the launcher's
`--detection-source` flag and the source-comment truth pass. Nothing below opens before it lands.

**2. Enable Pages, record the video.** `/dashboard` served at
`https://vihanpatil.github.io/SwathKeeper/`; the finished script in
`docs/drafts/DEMO_VIDEO_SCRIPT.md` recorded — fixing its "81 configurations" line first (81 is the
speed axis alone, not the grid).

**3. The ten conversations — zero code.** ~10 ArduPilot/PX4 autonomy teams, university labs and
Part-108-minded integrators, on one question: would you run a **pre-registered evidence gate on your
own flight logs**? **Kill criterion, fixed before the first call: 0 of 10 interested → "strong
portfolio, no product."** Stop there; the portfolio is the deliverable and option B stays a personal
quarter.

**4. Then ONE branch — C or B, never both.**

**(C) Extract the method** — taken if ≥1 of 10 says yes. First three steps:
1. a versioned flight-log contract plus one adapter for a log we did not write (ArduPilot `.bin` or
   PX4 ULog → schema);
2. gate bars in YAML, the pre-registration hash committed **before** the flight, a JSON verdict and
   documented exit codes — today **no gate emits JSON**;
3. a GitHub Action + badge, demonstrated on a repo we did not write.

**(B) Close the loop in sim** — taken only if the owner declares the drone the product. First three:
1. closed-loop executor: `/ap/mode` and `ready_for_external_control` fed back into the state machine,
   `commanded_vs_achieved_m` logged per maneuver, and a **designed** achieved-displacement gate (the
   naive lateral metric is wrong-axis — the 2026-08-26 replay measured that already);
2. nearest-neighbour association + a constant-velocity estimate over 3 frames, and closing-rate dodge
   sizing — today every decision is per-frame at 5 Hz against a 6.0 m/s closer;
3. the headless batch path: workspace baked at the pinned SHAs **with** `--enable-DDS`, a rented
   Linux box at RTF ≥ 1, ≥20 seeded encounters a night.

**B's kill criterion, written before its day one: if ≥20 seeded headless encounters cannot clear
3.00 m, the drone is not the product** — say so in the README and fall back to (C) or stop.

**B's terminal event is the pre-registered dodge take** (also the R4 re-fly, and the flight that
finally measures delivery + pitch at the booked 5.0 m/s): `docs/runbooks/AVOIDANCE_REAL_DETECTION.md`
§1a for the depth-source shell, `docs/runbooks/DODGE_TAKE_PREREGISTRATION_20260907.md` for the bars.
It is **NOT YET FLYABLE** — P2 (two log fields + the launcher flag + a step-0 test-flight), P3 (two
product-lead ratifications) and P4 (container state) are open. **If it breaches:** write the
`<log-stem>.SAFETY_FINDING.md` marker and **do NOT add the pin** — acknowledgement takes both halves,
the marker *and* the stem in `ACKNOWLEDGED_BREACH_STEMS`, a reviewed diff on the safety gate (§6a),
precisely so the runbook's own remedy cannot be the one-file way to turn a new strike green. That
pinned list is meant to stay two long.

## Explicit stretch goals (documented, NOT v1 blockers)
- Full coverage-debt reconciliation (v1 ships "avoid, return to next waypoint" + honest debt,
  ADR-002; AP_DDS exposes no mission-current service at the pinned SHA, so this is genuinely
  harder, not just deferred — source-verified, see ADR-006).
- Scaling from 2-3 birds to a flock / higher obstacle density.
- Second sensor as a supported operating mode: **the forward depth camera is BUILT (ADR-020/021)
  and has never flown** — promoting it out of stretch needs a flight, not more offline evidence.
- Live in-node NDVI stitching (offline is the v1 decision, ADR-010).

## Cut / deferred log
_(product-lead records cuts here with date + reason — interview material.)_

- **2026-09-10 — DIRECTION RESET (ADR-022): the ADR-019 WIRE PROGRAM is CUT** — items 3-4 (the
  mapped-catenary scenario and the wire demo take) and the A2 reconnaissance stretch goal, recorded
  as **ADR-019 amendment 1**. Two of the ratified 6-7 sessions, stacked behind a centerpiece dodge
  that has never flown, on a sensor with zero flights. **An NDVI/crop-health analytics product is
  REJECTED** (ADR-019 §5 had already ruled plain NDVI commoditised; this world has no health
  variation to sell). **Drone-as-product is deferred** behind a market test of the evidence method
  (~10 conversations; kill criterion 0 of 10). Paid for: nothing enters — this is a net cut. Frozen
  with it: NDVI (ADR-019 §7), the depth segmenter until a flight exists, `DECISIONS.md` amendments
  ≤ 10 lines, no new ADR without a cut, tests:src capped at 3.70:1 (re-baselined from the 3.45
  the cap shipped at — the floor round grew it; ADR-022 am. 1). Deleted with it: the
  depth-segmenter prototype + its orphan tests, the superseded README drafts, the duplicated in-repo
  flight logs, the stale worktree shadow.
- **2026-09-10 — R8 recorded OPEN: not cut, not fixed.** The committed coverage mission violates its
  own XY geofence by **−1.997 m** on leg 4 and CI runs the check `|| true`. The altitude waiver
  (15.0 m vs 3.5 m trees) is sound and the gate is still disarmed — an XY geofence that cannot fail
  is not one. Owed a mission-or-radius diff, and it did not happen on 2026-09-10.
- **2026-08-26 — Ruling 002 ratified with amendments (ADR-019): the short `test_2lane` arm is
  RETIRED OUTRIGHT, ALL NDVI work is FROZEN for the avoidance push, and the doc long-tail + R5
  move behind the wire demo.** Paid for: the forward depth sensor + birds-first working dodge +
  mapped-wire scenario enter scope. Claims ceiling recorded: "sim-demonstrated, evidence-gated" —
  nothing stronger until external validation exists. NDVI research verdict banked with the freeze:
  keep-as-is, invest nothing more (plain NDVI is commoditized; the live reactive loop is the
  market gap).
- **2026-08-26 — criterion 2's NDVI+RGB comparison arm RETIRED as open work (ADR-003 closure;
  product-lead call under the ratified "forced binary").** Not because RGB lost — it matched the
  safety numbers exactly — but because the study *measured* that the arm was never a second
  sensor: the RGB R channel is the NDVI Red band bit-for-bit, so it cannot answer what a second
  sensor buys in range or lead time, and the measured bottleneck is geometric. The arm stays in
  `run_spike.sh` as the regression check that guards the shared blob detector; criterion 2's
  remaining budget moves to ADR-017's forward-facing sensor.
- **2026-08-26 — Ruling 001's "ONE re-fly, then Week 7" sequence is VOIDED by measurement, and the
  sequencing decision escalates to the user.** The replay proved no nadir re-fly can pass the
  GT-CPA bar (tripwire (a) fired; ADR-017 am. 1), so the re-fly now sits *behind* the promoted
  forward sensor. Options on the table: Week 7 first on the honest story (product-lead
  recommendation; tripwire (b) forces the demo after two more sessions anyway) vs sensor first.
  Nothing is cut yet — this line exists so the voiding is booked, not slid past. **Resolved the
  same day: the user chose (A) then (B) — see ADR-017 am. 1; superseded by ADR-022.**
- **2026-08-25 — Council Ruling 001 RATIFIED (user); R4-as-candidate-ordering is deferred behind
  the offline point-mass replay, and full-stack-wholesale is demoted to demonstrator-hybrid.** The
  replay re-scopes R4 by measurement (the direction/warning/plant confound on the 84 committed
  maneuvers is resolvable offline, no flight needed); the demotion trades an ambition with <5 %
  odds for the viable hybrid — a reference stack that proves the extractable core. Recorded as
  ADR-016; ruling text in `.claude/agent-memory/exec-council/ruling-001-founding-reevaluation.md`.
- **2026-08-25 — R4 is IN; the doc fix-list long-tail and item 2's short `test_2lane` arm are cut out
  of its way.** R4 was promoted by its own written condition (a flight that fails its GT-CPA gate) —
  0.0067 m at 4.03 m vertical with 1.8 cm of lateral escape flown — so scope is paid for in the same
  breath, per the standing guard. The ~70 remaining documentation-review items and the short-arm
  comparison are **deferred until after the R4 re-fly scores**; neither gates a flight, neither
  appears in the demo, and both are offline work that will still be there. **Not cut, and explicitly
  refused as R4's "while we're in there":** R5 stays RECORDED-OPEN, and no threshold, detector or
  `MIN_DETECT_RATE` change rides along — all three were measured stable on this take and none is
  implicated in the breach.
- **2026-08-25 — headless-render sim CI stays manual-dispatch; not a v1 blocker (ADR-008).** Its
  plan doc was a plan and a feasibility verdict, never a procedure, so it moved to
  `docs/archive/SIM_CI.md` in the docs cleanup. The image-build half is green (`sim-image.yml`,
  2026-08-18); the render-smoke half ("What needs the human", steps 1-4) has never run and is
  **recorded open here** rather than swept away with the file — archiving open work without booking
  the deferral is exactly what this log exists to prevent.
- **2026-08-24 — safety scope bounded to R2/R3 for v1; R4 and R5 stay RECORDED-OPEN.** ADR-013
  am. 12 ranked five fixes. R1 shipped, R2 + R3 land and fly on the next avoidance flight. **R4**
  (reversal-preferring candidate order) needs closing geometry v1 does not have — 18 of 19 replayed
  ticks still take the straight reversal — and **R5** (ArduPilot `FENCE_*` backstop + lanes moved
  inboard) bolts a second boundary authority beside a working one. Both are the classic "while we're
  in there" and are refused on sight until R2/R3 have flown. Recorded-open is not swept under the
  rug: S1's 0.0518 m CPA stands, and a flight that fails its own GT-CPA gate is the measurement that
  would promote R4.
- **2026-08-24 — criterion 2's RGB pixel study deferred behind the avoidance flight.** Perception
  wanted it this session; product-lead call. The flight live-gates four landed things and criterion 2
  gates none of them; the study is offline, ~1 h, and its clip already exists, so deferring costs
  ordering and nothing else. The tradeoff is owed a `docs/DECISIONS.md` entry — that log is free
  interview material.
- **2026-08-24 — no detection tracker in v1 (`track_id` stays `None`), and no second staleness
  expiry.** The policy's threat test is per-frame and the executor latches on geometry, so an ID that
  exists only to look sophisticated would be untested state; ageing detections out is
  `max_detection_age_s`'s job and only its job. One source of truth per concept.
- **2026-08-18 — code-identifier rename deferred (ADR-011):** `fieldguard_planning`, `fg_`/`/fg/*`,
  `farmguard_field.sdf`, `fieldguard-sim` image stay under the old name; the `/fg/*` contract is
  embedded in ADR-007 and live-verified, and renaming verified interfaces for cosmetics re-opens
  confirmed state for zero functional gain.
- **2026-08-05 — no YOLOv8 bolt-on for resume keywords.** The metric-driven story is stronger: a
  classical blob baseline cleared the safety bar and has since been **ADOPTED on the real render**
  (ADR-003 am. 7). Any learned model must beat it on the same harness before it earns a place.
- **2026-08-05 — no retrofitted startup narrative.** Sim-only, solo, portfolio-honest framing is
  the asset; inflating it converts the honesty in every ADR into an interview red flag.
- **2026-08-05 — colcon/ament packaging of the planning package.** Zero demo value; PYTHONPATH
  works in-container. Restated 2026-08-18 (audit re-confirmed the cut).
