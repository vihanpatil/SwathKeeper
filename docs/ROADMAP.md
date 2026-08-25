# SwathKeeper — Roadmap (living document)

Owner: `product-lead`. Update at each `/standup`. History lives in `docs/BUILD_LOG.md`; decisions
in `docs/DECISIONS.md`; this file is only ever **the current truth and what's next**.

**Deadline status (2026-08-18):** the original ~7-8-week / Europe-trip hard stop is **dropped**
(user decision). Quality over calendar — but the **standing scope guard survives the deadline**:
nothing gets added to scope without something else being cut in the same breath, and every
`/standup` is still measured against protecting the demo + dashboard exit.

## Where we are (2026-08-25)

| Phase | Status |
|---|---|
| Weeks 1-2 — sim foundation + detection decision | ✅ complete (2026-08-04) |
| Weeks 3-4 — reactive avoidance + coverage-debt loop | ✅ complete, **demonstrated live** (2026-08-05); first FULL ledger closure **720/0**, 19/19 vetted, on the current stack (2026-08-23, ADR-013 am. 11). **Safety asterisk (am. 12):** both historical avoidance flights breached bird clearance at ~5 cm under green gates. CPA is now a gated metric (R1 shipped); R2/R3 landed 2026-08-24 and await their live gate |
| Week 5 — NDVI pipeline | ✅ closed. Four ADR-007 gates green live; mount geometry corrected + gated (2.2 px). **Recording throughput CLOSED 2026-08-22** (ADR-013 am. 9): the Fast DDS SHM segment was the root cause — 100 % delivery on both bands, painting cadence 0.41 → **5.0 Hz flat**, and the first full-grid map, **720/720 cells**, 18/18 trees imaged / 14 canopy-grade (am. 10) |
| Week 6 — real detector on the seam + comparison arm | 🟡 **FLOWN 2026-08-25 — half live-gated, and the pre-registered breach happened.** The seam flew on one clock; the detector ran **1301/1302 frames = 99.92 %** in the air against a 90 % floor; R2 passed live (4 maneuvers accepted, min swept clearance 1.340 m ≥ 1.0, 8 candidate rejections); the ledger closed **720 covered / 0 debt**, 1858/1858 truth ticks, 0 clock-domain violations; the NDVI half is the best take yet (720/720 cells, **18/18 trees imaged, 11/18 canopy-grade, median lift +0.5562** vs the adopted clip's 9/18 / +0.5402). **The take is INVALID: `gt_cpa_m` 0.0067 m to bird_0, `gt_cpa_gated_m` −1.1210 m against the 3.00 m bar.** Marker written; **pin deliberately not added** — the record stands INVALID/exit 1 until re-flown after R4. Detail below. Still open: criterion 2's RGB study; −0.61 stays **PROVISIONAL** (background half now done, range half not) |
| Week 7 — dashboard, demo video, README/GTM | ⏳ not started (deliberately last) |

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
(`predict_bird_visibility.py`) **PASSes at its 3.0 m/s default and FAILs at the ~9.4 m/s the encounter
was actually flown**. Its `DEFAULT_SPEED_MPS` provenance cites a file that contains no speed figure.
That default is what booked a 2-frame encounter.

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

**The detector move is provably neutral, which is the claim that mattered most:** re-scoring the
adopted clip through the new home reproduces `detections_ndvi.json` **bit-identically** (1256 frames,
24 boxes, −0.61 / 6 / 5000) and the ADOPT verdict with identical numbers. A rewrite wearing am. 7's
verdict would have cost a flight to re-earn.

**Offline dry run of the whole seam over the adopted clip** — the numbers to compare the flight
against, not results: boxes bit-identical through the live class; **8 of 1256 frames (1.24 % of the
645 airborne) would have produced an in-cylinder threat** — bookable, not a dodge storm, though 3 of
the 8 are bird_1 *lifted into* the ±6 m cylinder by the 0.15 m radius prior's under-ranging; range
error vs truth **median 1.65 m / max 3.67 m** (n=24, materially worse than the single case am. 7
quoted); `detect_wall_ms` p95 **4.8** against a 200 ms tick, so the detector will not block the
executor.

**Then QA's adversarial pass found six open findings in the gate itself** (1 critical, 4 major, 1
minor, every one reproduced with a probe against the real code). **All six are fixed and
independently re-verified 2026-08-24**, each pinned by a test proven red against the pre-fix code;
the re-reviews then opened three shorter rounds, **all closed the same day** (see below). The ADR
amendments recording all of the above
are **written**: `docs/DECISIONS.md` **ADR-013 amendments 13-17** (all dated 2026-08-24) carry R2/R3
offline, the ground-truth CPA gate, the six-finding adversarial pass and its round-3 residuals, and
the CI denominator + frozen marker-set decision (with the two-half acknowledgement and the run-block
ratchet recorded in am. 14/17), alongside their companion ADR-003/ADR-009 notes.

Test suite: **877 green, 2 skipped** (measured 2026-08-24, after the round-5 fixes) — 57 host-side
tests under `tests/`, which need neither Docker nor tmux, plus 822
collected in `tests/fieldguard_planning` (820 green and the 2 long-standing pending-scenario skips).
822 + 57 = 879 = 877 + 2 is the consistency check that matters, because `unittest` is the runner that
makes an unexpected pass red.
Up from 530/2/2 at session start (870/2 entering the last fix round), with **zero xfailed**: one xfail was promoted to a plain assertion when R2
landed, the other honestly retired — it asserted that a *frozen artifact* would one day become safe,
so it could never activate; the breach it stood for is now pinned by a live gate plus BOTH halves of
its acknowledgement (the marker file and the stem in `ACKNOWLEDGED_BREACH_STEMS`).
Run **both** runners: `python3 -m pytest tests -q` and
`python3 -m unittest discover -s tests/fieldguard_planning` — only the second makes an xpass red.
CI discovers both — host-side discovery is now `-p 'test_*.py'`, so a new `tests/test_*.py` file
cannot sit un-run — and also gates seed-42 FNR (`check_spike_regression.py`) and flight-log evidence
(`check_live_flight_log.py` over the two **committed** `eval/results/live_flight_log_*.json`). That
evidence step is **no longer vacuous**: it prints the file count every run and hard-FAILs on zero,
where before it printed SKIP…PASS and went green having validated nothing.
Public main is **behind**: everything since 2026-08-22 — throughput round 3, ADR-003 am. 7, R1, and
today's four — lives on `feat/throughput-instrumentation`. Full narrative: `docs/BUILD_LOG.md`.

## Standing traps (learned the expensive way; still live)

- **Do not retry `camera.update_rate_hz` 5 → 2** (2026-08-19: 16× *worse* delivery at unchanged RTF).
  Reasons preserved in `config/ndvi_camera.json`'s `update_rate_note`.
- **Judge a lever by `red_frames / camera_info_frames`; judge a *map* by painting frames.** The
  2026-08-21 take's "454 frames" read five times better than the 51-frame artifact it produced.
- **Cells imaged is not the metric.** Three pre-mount-fix clips imaged *more* cells and *more* trees
  and returned **zero** canopy-grade trees, with every positive cell 6.4-11.9 m off any tree.
- **Run the host predictor before booking any flight** (`scripts/predict_bird_visibility.py`, ~1 s).
  **Run it at the speed the mission will actually fly** — 2026-08-25 proved the default is the defect:
  PASS at the 3.0 m/s default, FAIL at `--speed 8` and `--speed 9.4`, and the take flew ~9.4 and got
  2 bird-visible frames of 3310. The published medians 8/6/11 are the 3 m/s figure. **Refuse the
  session on medians 0/0/1** — that is how the 2026-08-21 take produced 0 of 454.
- **One open question, unproven at n=3, no ADR until someone separates it:** trees sitting *under* a
  flight lane read soil-grade (+0.000 / +0.614 / +0.622) while trees imaged from *between* lanes read
  +0.85…+0.92. Parallax fill vs sample poverty are both consistent. It would matter for the NDVI
  product, not just for the check.

## Next up, in order

1. **R4 — escape geometry, promoted from RECORDED-OPEN by measurement, not by appetite.** The
   one-line evidence: **0.0067 m horizontal overflight of bird_0 at 4.03 m vertical separation while
   the loop was engaged, with 1.8 cm of lateral displacement flown.** R4 was deferred 2026-08-24 with
   the promotion condition written down — "a flight that fails its own GT-CPA gate is the measurement
   that would promote R4" — and that flight has now happened. **Something is cut to pay for it: see
   the 2026-08-25 cut-log line.**

   **R4 must be re-scoped before it is built, and it cannot ship alone.** Price it against the
   **0.175 s of sensor lead and 0.4 s of in-image dwell that were actually available**, not against
   the policy's 12 m cylinder — the sensor horizon is 2.48 m. Three consequences:
   - the reversal-preferring candidate order is structurally unavailable on lane x=15 (that lane *is*
     tree row 0), so the fix cannot be candidate ordering alone;
   - **gate R4 on lead time as well as CPA** — a green CPA on 0.175 s of lead is bought by luck;
   - if R4 adopts a CLIMB, the gate will print `gt_cpa_m NONE-IN-BAND`, which must be read alongside
     `min_horizontal_any_band_m` or it is a vacuous green.

   The cheapest lever is not R4 at all: **fix `DEFAULT_SPEED_MPS` (or make `--speed` required) and
   re-run the §0b abort gate at the flown speed before booking anything.** Booking under the 3 m/s
   default buys another 2-frame encounter.

   **Then the re-fly** — same runbook, same pre-registration, same one-outcome-that-fails-it
   (an unscoreable artifact). Two things it must fix that this take exposed: freeze `drive_birds.py`
   before scoring (the truth track grew 1348 → 2202 records *after* the flight log was written, so
   this take's per-bird denominators are irreproducible), and **run teardown** — §4 step 2 was skipped
   and nothing in `status` or the runbook noticed.

   **Decision owed before the marker/evidence set is committed:** CI runs the safety gate with no
   `--truth`, and committing this take's applied track makes ≥2 candidates overlap → the log goes
   INVALID for *ambiguous truth track* and the CPA breach is **never printed**. The two-half
   acknowledgement has only ever run on legacy-pinned logs. Pick the record shape (keep evidence
   uncommitted / prune the 2026-08-23 track / teach CI to pass `--truth` / sidecar-pinned truth)
   **before** anything is committed. This is a product-lead call, not a build's.

   **Open question this raises and I am not deciding by default: does the camera stay NADIR?** A
   forward tilt is the single biggest lever on lead time (the detector has ~40 m of unusable range
   headroom) — and nadir is what the entire NDVI half is built on, which this same clip scored its
   best-ever tree gate with. Non-mount alternatives: fly encounter lanes slower, or fund criterion 2's
   second sensor. Costs a `docs/DECISIONS.md` entry either way; ask the user, do not guess.

<details>
<summary>Superseded: the pre-flight plan for the 2026-08-25 take (kept for the pre-registration record)</summary>

   This is the flight the project
   has been building toward: the drone dodges a bird **it detected**, not one we injected. It is the
   only flight on the board because it is the only artifact that can close what landed today —
   R2's margin, R3's refusal, the GT-CPA gate, and the seam itself all become real on the same take.
   Runbook: `docs/runbooks/AVOIDANCE_REAL_DETECTION.md` (full boustrophedon, so its NDVI clip also
   feeds item 2). It has never been flown; every command in it is offline-verified only.

   **Two preconditions, both host-side, neither optional:**

   *(a) The image must carry scipy.* `sim/docker/Dockerfile` now installs `python3-scipy` because
   `scipy.ndimage` **is** the morphology am. 7 adopted. `scripts/sim_docker_build.sh` is multi-hour —
   run it days ahead, not at session time — then `sim_docker_run.sh` to recreate the container (it
   also carries `--shm-size=1g`). `fly_pipeline.sh up` refuses to open a single pane until
   `import scipy.ndimage` works in-container, so a stale image costs 200 ms instead of 90 s into a
   booked take. If the session *pulls* the GHCR image, that one needs rebuilding and pushing too.
   The in-container transfer check (re-score the am. 7 clip on jammy's scipy 1.8.0, require
   bit-identical boxes) is preflight 0c and **has not been run** — host 1.13.1 is the only version
   verified.

   *(b) The gate must not be able to print a false PASS.* QA's adversarial pass, 2026-08-24:

   | # | severity | the gate/law would… | proven |
   |---|---|---|---|
   | 1 | **critical** | accept a 0.8 s frozen clock = 5.6 m of bird motion (1.9× the 3.0 m bar) | true CPA 0.0000 m reported as **3.5000 m PASS** |
   | 2 | major | read `n_stale_dropped` 0 for both "no bird seen" and "every detection expired" | a fully-dead avoidance flight certifies VALID with a vacuous pass |
   | 3 | major | let R3's refusal command a setpoint the policy's own bird bar forbids | commanded **1.000 m** from the bird against a 3.00 m bar |
   | 4 | major | minimise CPA over 5 Hz path *vertices*, not the path | true 2.6332 m BREACH reported as **3.0500 m PASS** |
   | 5 | major | let explicit `--truth` bypass the one-track guard — the runbook's only documented invocation | a second applied log fabricates or hides a breach |
   | 6 | minor | pass a detector that ran on 1 frame of 1256 (zero-check, not a rate floor) | three vacuous greens stack |

   **All six closed 2026-08-24**, host-side and offline, each pinned by a test proven red against the
   pre-fix code, with both historical logs still ACKNOWLEDGED byte-identically. This was not new
   scope; it was the no-band-aids rule applied to the gate that certifies the take. Re-reviews then
   opened **three shorter rounds, all closed the same day**: the bird axis of the CPA join (a landed
   pose is scored over its own in-effect window, not at tick instants), the HOLD's own clearance
   printed as ungated CONTEXT *with a denominator*, R3.8 reading the executor's `gate_reject` events
   as the backstop's live evidence, am. 16's measured scoping decision for the
   `eval/scenarios/*/flight_log.json` breaches, the **two-half acknowledgement** (a
   `SAFETY_FINDING.md` marker no longer buys a green on its own — the log stem must also be pinned in
   `ACKNOWLEDGED_BREACH_STEMS`, a reviewed diff on the gate), and the **run-block ratchet** (deleting
   `run` from a schema-2 log used to demote it to the legacy detection-referenced CPA path and turn a
   ground-truth INVALID into VALID; a log with no run block is now INVALID unless it is pinned
   pre-seam). The ADR amendments for all of it are **written**: `docs/DECISIONS.md` ADR-013
   amendments 13-17, all dated 2026-08-24.

   **Pre-registered, before flying:** R2/R3 do **not** fix S1 (escape geometry) and R4 is deferred, so
   this flight may honestly **FAIL its own GT-CPA gate**. That is a measurement that ranks R4 next,
   not a wasted take. **What to do if it breaches:** write the `<log-stem>.SAFETY_FINDING.md` marker
   (the context half — the finding, beside the evidence) and **do NOT add the pin**. Acknowledgement
   takes *both* halves — the marker *and* the log stem in `ACKNOWLEDGED_BREACH_STEMS`, which is a
   reviewed diff on the safety gate — precisely so that the runbook's own remedy for a breach cannot
   also be the one-file way to turn a new bird strike green. So the take **stands at INVALID /
   exit 1**: that is the correct record for a flight that breached and can be re-flown after R4. The
   two pinned stems are *historical* logs that cannot be re-flown, and that list is meant to stay two
   long (`docs/runbooks/AVOIDANCE_REAL_DETECTION.md` §6a). **The one outcome that makes it a failed session
   is an unscoreable artifact:** no truth track, a detector fed zero frames, or a clock that never
   advanced. Three bringup preconditions the gate now enforces and the operator must respect —
   `ndvi_node` publishing `/fg/ndvi/camera_info` *before* the `--detect` shell starts, at least one
   landed `set_pose` for **every** bird in the config, and evidence-first teardown (Ctrl-C the
   avoidance shell and wait for `wrote flight log →` **before** `fly_pipeline.sh down`).

   **Watch list for the take, from the offline rehearsal:** re-latch churn (monocular jitter can
   exceed the executor's 3.0 m re-latch threshold; a replay produced 2 relatches in 5 maneuvers), and
   the phantom-dodge rate against its 8/1256 prediction. Decide on the measurement, not now.

   *Outcome:* the seam, R2 and the GT-CPA gate all flew and behaved as designed; R3 missed by 15 mm
   (`trigger_range` 1.015 m vs `degenerate_range_m` 1.0) and is still un-exercised. The phantom-dodge
   rate is **unmeasured, not cleared** — bird_1 and bird_2 had 0 in-image opportunities.

</details>

2. **Full boustrophedon + the short-vs-long evidence study, on the FINAL config.** ADR-013 am. 10
   answered both questions as byproducts of one flight (n=1 per arm): run-age decay was segment
   exhaustion wearing a clock's clothes and is retired, and the long mission is the better evidence
   artifact too — same per-minute frame yield, **1.4× better on cells/min**, because it spreads frames
   over new ground. What is missing is the same comparison **on the configuration that ships** — R2's
   margin 1.0, the real detector on the seam, ADR-015 geometry — so the NDVI number quoted in the demo
   and the dashboard comes off the flown config rather than an earlier one. **Cheap by construction:**
   item 1's take is already a full boustrophedon, so the long arm rides it for free; only the short
   `test_2lane` arm and the write-up are extra. **The long arm now exists** — the 2026-08-25 clip flew
   the full boustrophedon on the shipping config and scored 720/720 cells, 18/18 imaged, 11/18
   canopy-grade, median lift +0.5562, 5.0 Hz flat for a third independent flight. Its CPA verdict does
   not touch the NDVI half; only the short `test_2lane` arm and the write-up remain, offline.

3. **Criterion 2 — the independent RGB pixel study (deferred 2026-08-24; see cut log).** ~1 h,
   offline, and the clip already exists. Required because `baseline_rgb.py`'s "bright + achromatic"
   birdness is **inverted on this world**: its 1.000 FNR measures the wrong signal and **must not be
   quoted as RGB's ceiling** in any interview or README line. Same visit closes the −0.61 threshold's
   PROVISIONAL flag, which needs false-positive characterisation (7 FP at n=20; on the adopted clip
   the area filter rejected nothing, so those FPs are real blobs, not speck noise) — that is
   perception-ml-engineer's call, not a build's. **The background half of that characterisation is now
   DONE (2026-08-25):** across 3310 frames / 1.02 Gpx, **zero** non-bird pixels fall below −0.50 while
   bird pixels top out at −0.6697 — a 0.229-wide empty band, so any threshold in it is bit-identical
   on this clip. What remains is the **range** half: −0.61 has only ever been exercised at ~4 m depth
   on a 47 px bird, so lifting PROVISIONAL needs a clip with birds at 3+ distinct ranges, not another
   pass at 4 m. The take also handed criterion 2 its input for free: 3310 real 640×480 RGB PNGs, and a
   concrete measured case (7 in-cylinder frames → 2 in-image on the single NDVI camera).

4. **Doc + evidence long-tail.** The three items that were at the top of this list are **done**
   (2026-08-24): the ADR amendments for everything that landed that day are written (ADR-013 am.
   13-17 plus their ADR-003/ADR-009 companions, so `DECISIONS.md` no longer stops at 2026-08-23);
   the ADR-003 header line no longer contradicts its own amendment 7; and
   `eval/scenarios/*/flight_log.json` have been regenerated on the shipped control law
   (`lateral_tree_margin_m` 1.0 — check the `params` block in any `maneuver` event), so they may be
   quoted as current behaviour again. What remains: the documentation-review fix-list (78 items,
   ~70 remaining — list + exact edits preserved), **deferred 2026-08-25 behind R4 (see cut log)**.
   Two entries are exempt because they are wrong-in-a-load-bearing-way, not polish: the published
   `predict_bird_visibility` medians 8/6/11 are the 3 m/s figure and appear in this file, `BUILD_LOG.md`
   and `DECISIONS.md`; and the safety gate's own note explains the missed-detection signal as "a bird
   behind the drone is invisible to a forward-facing camera" — **the mount is nadir**, and a wrong
   explanation retires the right question.

5. **Week 7 — the exit being guarded.** Dashboard (replay + avoidance log + NDVI overlay on the
   shared cell grid), demo video, GTM pass. Last and light: it is the proof, not the point.

## Explicit stretch goals (documented, NOT v1 blockers)
- Full coverage-debt reconciliation (v1 ships "avoid, return to next waypoint" + honest debt,
  ADR-002; AP_DDS exposes no mission-current service at the pinned SHA, so this is genuinely
  harder, not just deferred — source-verified, see ADR-006).
- Scaling from 2-3 birds to a flock / higher obstacle density.
- Second-sensor config promoted from comparison arm to a supported operating mode.
- Live in-node NDVI stitching (offline is the v1 decision, ADR-010).

## Cut / deferred log
_(product-lead records cuts here with date + reason — interview material.)_

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
