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
| Week 6 — real detector on the seam + comparison arm | 🟡 **FLOWN 2026-08-25 — half live-gated, and the pre-registered breach happened.** The seam flew on one clock; the detector ran **1301/1302 frames = 99.92 %** in the air against a 90 % floor; R2 passed live (4 maneuvers accepted, min swept clearance 1.340 m ≥ 1.0, 8 candidate rejections); the ledger closed **720 covered / 0 debt**, 1858/1858 truth ticks, 0 clock-domain violations; the NDVI half is the best take yet (720/720 cells, **18/18 trees imaged, 11/18 canopy-grade, median lift +0.5562** vs the adopted clip's 9/18 / +0.5402). **The take is INVALID: `gt_cpa_m` 0.0067 m to bird_0, `gt_cpa_gated_m` −1.1210 m against the 3.00 m bar.** Marker written; **pin deliberately not added** — the record stands INVALID/exit 1 until re-flown after R4. Detail below. **2026-08-26 offline arc (ADR-016 executed):** the point-mass replay resolved the actuation confound and **fired the ADR-017 tripwire** (no safe nadir speed exists → second forward sensor promoted to scope); the honesty-fix bundle landed through three QA rounds; the legacy CPA gate's vertex-only geometry fixed red-first (the one "passing" fixture was a direct hit); **criterion 2 CLOSED — RETIRE-ARM** (the arm shares the primary's band/aperture/mount/clock; ADOPT re-confirmed against a *working* arm, gap +0.000); −0.61 stays **PROVISIONAL**, now narrowed (background half done; range half exercised to a 2.3× depth span, open beyond ~11 m) |
| Week 7 — dashboard, demo video, README/GTM | ⏳ not started (deliberately last) |
| ADR-019 forward depth sensor — sensor-in-sim | 🟡 **built host-side 2026-08-26, NEVER RENDERED.** A `depth_camera` mount now sits in `sim/worlds/farmguard_field.sdf` (`/fg/depth/*`, bridged, `up` gates on it) — authored, statically gated (23/23) and 80 host tests, but **no frame of it has ever existed**. The booking gate (`scripts/predict_forward_lead.py`) PASSes the design at 5.0 m/s with margin **1.811×** and exits **3 = NOT BOOKABLE** by construction until the render is measured. Next: one commissioning Docker session, [`docs/runbooks/FORWARD_DEPTH_SENSOR.md`](runbooks/FORWARD_DEPTH_SENSOR.md) gates D1-D6. **`product-lead`: this is a scope line that arrived from ADR-019, not from a `/standup` — place it and price it.** |

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
Public main is **current as of 2026-08-25** (the take evidence went to main directly —
`3c08d82`, a clean fast-forward, no PR; main CI is **red by design** on the pre-registered
half-acknowledgement until the clean re-fly). The 2026-08-26 session's work (ADR-016 execution:
replay + bundle + gate CPA fix + criterion-2 closure) is in the working tree, **uncommitted**.
Full narrative: `docs/BUILD_LOG.md`.

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

## Next up, in order

**2026-08-25 — Council Ruling 001 RATIFIED (ADR-016). 2026-08-26 — its item 1 EXECUTED and the
tripwire FIRED.** The point-mass confound-resolver ran over all three committed flights, survived
two adversarial QA rounds, and answered everything it was built to answer (ADR-016 am. 2,
ADR-017 am. 1). The honesty-fix bundle landed the same session through three QA rounds (ADR-016
am. 1), the legacy CPA gate's vertex-only geometry was found and fixed red-first (ADR-013 am. 19),
and criterion 2 closed (ADR-003; RETIRE-ARM — the comparison arm measurably shares its band,
aperture, mount and clock with the primary sensor).

0. **RULING 002 RATIFIED WITH AMENDMENTS 2026-08-26 (user; ADR-019) — the ag-avoidance product
   push is the program.** Charter is product-intent dual-track (claims capped at
   "sim-demonstrated, evidence-gated"). The engineering track, in order, priced in sessions
   (6–7, honest range 5–10): **forward DEPTH camera in sim (1–2) → booking-gate PASS (1) →
   bar-clearing BIRD dodge (1) → mapped-wire scenario (2) → wire demo take (1)** — wires as
   fresh-per-field-survey mapped infrastructure with a meters-scale sag buffer (A1), the
   wire-mapping pass as a gated stretch goal (A2), no camera wire detection promised and
   radar-in-sim researched-and-rejected (A3). **The no-failure-theater gate:** no flight is
   booked until the predictor clears 3.00 m with ≥1.3× lead margin on `guided_default` — the
   next take is designed to pass. Week 7 runs in parallel as its user-gated remainder only
   (voiceover, README application, Pages). Sensor-in-sim work STARTED 2026-08-26.

1. **DECIDED 2026-08-26 (user): (A) then (B) — superseded the same day by Ruling 002's ratified
   program above, which absorbs (B) and shrinks (A) to its user-gated remainder.** Background —
   the replay voided Ruling 001's "ONE re-fly, then Week 7" order by measurement:
   **no speed makes nadir safe on the flown encounter** (`speed_at_which_nadir_becomes_safe = None`
   across 81 cells × 3 plants; bird_0's own 6.0 m/s closing speed caps lead at 0.41 s from a hover;
   every escape needs ≥ 1.25 s; nadir needs 17.8–38.8 m of forward sensing and has 2.48 m). Per
   ADR-017's pre-written contingency the **second forward-facing sensor is promoted from growth
   path to scope** — the tilt stays rejected — so a green re-fly requires the sensor first, and
   the choice is:
   - **(A) Week 7 now** — demo/README/dashboard on the honest story ("the system measured its own
     sensor's limit and refused to fly what it can't pass"), sensor + re-fly after.
     **Product-lead recommendation**, aligned with Ruling 001's visibility argument and its
     tripwire (b), which forces the demo after two more sessions regardless.
   - **(B) Forward sensor first** — multiple engineering sessions before anything is visible.

2. **R4, re-scoped by the replay (built AFTER the sequencing decision, WITH the sensor):** the
   binding constraint is **lead time, not candidate ordering** — the 0° reversal never resolves at
   any lead × plant, and the earliest physically-resolving lead on the flown encounter is
   **1.25 s** (±90° forward sidesteps at the ANGLE_MAX ceiling; 2.00 s through the policy's
   XY-only tree vet, which is a third confound R4's sizing must not inherit — relax it with
   `is_safe_3d`, it is not a plant property). Gate R4 on **lead time as well as CPA**; a climb
   prints `NONE-IN-BAND` and must be read beside `min_horizontal_any_band_m`. Also owed to the
   next flight, whatever it is: record the **achieved flight mode per tick** in the schema-2 log
   (the 2026-08-18 wrong-way anomaly — commanded 10 m south, flew 14.5 m north — cannot be
   diagnosed offline without it), freeze `drive_birds.py` before scoring, and run teardown.

   **Decision still owed before this session's marker/evidence pattern repeats:** the record shape
   for committed breach evidence (CI runs the gate with no `--truth`; a second committed applied
   track makes takes ambiguous and the CPA never prints). Product-lead call, unchanged.

   **DECIDED 2026-08-25 (user, ADR-017): the camera stays NADIR for v1** — sensor-honest speed
   doctrine, second sensor as the lead-time path, tilt REJECTED. The contingency in that ADR
   **fired 2026-08-26** (no safe speed exists): see item 1.

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

3. **RETIRED OUTRIGHT 2026-08-26 (ADR-019 cut — was: full boustrophedon + the short-vs-long
   evidence study).** The long arm's numbers are banked (720/720, 18/18, 11/18, +0.5562); the
   short `test_2lane` arm dies with the NDVI freeze and is not coming back as v1 work.
   Superseded text kept below for the record.
   **Was:** Full boustrophedon + the short-vs-long evidence study, on the FINAL config. ADR-013 am. 10
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

4. **Criterion 2 — CLOSED 2026-08-26 (see the ADR-003 closure and the cut log): RETIRE-ARM.** The
   independent RGB pixel study ran over both committed clips (4,566 frames / 1.40 Gpx / 16,686
   measured bird pixels at 3.9/6.9/9.0 m) and answered everything the arm could answer: the old
   1.000-FNR birdness was the wrong *feature*, not the wrong sign (the real RGB signal is
   chromatic); at its honest ceiling RGB matches the adopted detector's safety numbers identically
   and loses 3.1×/27× on precision to a trunk≈bird_1 material collision only the thermal band
   separates — so **ADR-003's ADOPT now rests on a working comparison arm (gap +0.000)**. The
   decisive measurement: the RGB R channel **is** the NDVI Red band bit-for-bit, so the arm never
   was a second sensor and cannot answer criterion 2's geometry question; its budget moves to
   ADR-017's forward-facing sensor. The −0.61 threshold's **range half is partially closed** (the
   adopted clip exercises it over a 2.3× depth span, every bird core ≤ −0.83); PROVISIONAL stays
   for ranges beyond ~11 m. Carry-forward hazard, recorded: v1 flies NDVI-only, so the live
   exposure is the **invisible brown object** not in the static map.

5. **Doc + evidence long-tail.** The documentation-review fix-list (78 items, ~70 remaining — list
   + exact edits preserved) stays **deferred behind the sequencing decision** (cut log 2026-08-25).
   The two load-bearing-wrong exemptions are now **both fixed (2026-08-26)**: every runnable
   `predict_bird_visibility` invocation carries `--speed` and the medians are qualified at every
   site the bundle's QA could find; and the safety gate's "forward-facing camera" explanation is
   corrected in place with a dated note — the mount is nadir, and the take measured the real
   geometry (≤9 % of the cylinder in view).

6. **Week 7 — ACTIVE NOW (decided 2026-08-26, option A).** Dashboard (replay + avoidance log +
   NDVI overlay on the shared cell grid), demo video, GTM pass. Light: it is the proof, not the
   point. The story it tells is the honest one this session finished measuring — "the system
   found its own sensor's limit and refused to fly what it can't pass." **README and doc shaping
   happen WITH the user in the loop** (their standing instruction), not delegated to an agent.

## Explicit stretch goals (documented, NOT v1 blockers)
- Full coverage-debt reconciliation (v1 ships "avoid, return to next waypoint" + honest debt,
  ADR-002; AP_DDS exposes no mission-current service at the pinned SHA, so this is genuinely
  harder, not just deferred — source-verified, see ADR-006).
- Scaling from 2-3 birds to a flock / higher obstacle density.
- Second-sensor config promoted from comparison arm to a supported operating mode — **now the
  documented growth path for detection lead time (ADR-017): a forward-facing detection sensor
  beside the nadir survey camera, chosen over any tilt of the single mount.**
- Live in-node NDVI stitching (offline is the v1 decision, ADR-010).
- **The wire-mapping reconnaissance pass (ADR-019 A2, gated):** one slow corridor pass with the
  forward depth camera, returns fitted offline into a catenary curve, promoted into
  `static_obstacles.json` only after a standalone completeness/accuracy measurement — sequenced
  strictly after the birds-first dodge works.

## Cut / deferred log
_(product-lead records cuts here with date + reason — interview material.)_

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
  same day: the user chose (A) then (B) — see ADR-017 am. 1 and Next-up items 1/6.**
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
