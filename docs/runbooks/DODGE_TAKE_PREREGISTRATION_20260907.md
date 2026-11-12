# Dodge take on the forward depth camera — PRE-REGISTRATION *(2026-09-07, qa-safety-reviewer)*

Written **before** the flight, so no result below can be reinterpreted afterwards (ADR-016
doctrine; the same instrument as `AVOIDANCE_REAL_DETECTION.md` §7, which correctly called the
2026-08-25 breach in advance). This file is **append-only after takeoff** — see §6.

---

## 0. STATUS BOX — **NOT YET FLYABLE**

Five prerequisites. Each names an owner and the **artifact** that closes it. Ranked by consequence,
not by ease. Nothing here is a code change I made tonight; this document changes no behaviour.

### P5 — **the pre-registered invalidation may have ALREADY FIRED.** *(QA, new tonight; rank 1)*
ADR-020 am. 2's clause: *"if the segmenter's real, cluttered acquisition range comes in under
33.6 m, this gate goes red and the dodge take is not bookable at 5 m/s."*
`eval/results/depth_segmenter_score_20260907T110000Z.json` reports **`cluttered_acquisition_m:
46.0`** — and, in its own `acquisition.clutter_qualifier_note`, that the upper rungs are **100 %
sky-backed**: `clutter_backed_max_range_m` = **28.0 m** (canopy), **22.0 m** (ground_band),
**14.0 m** (ground_band_edge), `sky_backed_only_from_range_m: 30.0`. **Breakeven is 33.591 m and
the clutter-backed evidence stops at 28.0 m.** The clause reads 46.0 m one way and 28.0 m the
other, and the two sit on opposite sides of the bar; the artifact itself says the 46.0 reading "is
not one" (a clutter measurement at 46 m). **Owner: product-lead** — safety-vs-scope, escalated
rather than guessed; the clause is QA's own and I will not widen it after the fact. **Closes with:**
a dated ADR-020 amendment naming which reading the clause is evaluated on, *or* a clutter-backed
acquisition measurement at ≥ 33.6 m. The geometry defence already on the record (am. 2, probe 5) —
the whole ±6 m band **is** sky-backed at 33.6 m, sharing rows with finite ground only below ~23 m —
argues 28 m is not a ceiling *here*. It is not a measurement at 33.6 m, and it is the same
best-case-scene reasoning that amendment forbids quoting bare.

> **Disposition (orchestrator, 2026-09-07 ~12:45Z, product-lead tiebreak rule; USER TO CONFIRM OR
> OVERTURN on waking — this is the first item in the morning handoff): CLOSED BY RULING, ADR-020
> amendment 4.** The clause is evaluated on the definition pre-registered in
> `docs/design/DEPTH_SEGMENTER_DESIGN.md` §4.4 before any frame was rendered (longest contiguous prefix
> over the WORST background PRESENT at each rung) — that is **46.0 m**, so the invalidation did **not**
> fire and the booking stands. The 28 m figure becomes a mandatory transfer qualifier on every quote of
> 46.0 m ("clutter robustness demonstrated to 28 m; beyond 30 m no clutter can stand behind an in-band
> target in THIS world — untested, not refuted"). Redefining the quantity after seeing the numbers was
> refused in either direction. If the user overturns: the take is not bookable at 5 m/s until a
> clutter-backed measurement at ≥ 33.6 m exists, which needs a taller-obstacle world model (its own ADR).

> **CONFIRMED by the user 2026-09-11 (ADR-020 am. 5), with a forward-looking requirement:** no depth-camera
> dodge is booked until the segmenter is re-scored on a tall-obstacle world (≥ ~12 m structure behind the band
> at 34–46 m) so clutter is tested at or beyond 33.591 m — same 85-station protocol, same seven bars. **P5 is
> CLOSED**; the re-score is owed only if the deferred close-the-loop path (ADR-022 clause 3) is pursued.

### P1 — the depth-log scoring gates diff *(owner: flight-software-engineer + QA review)*
`scripts/check_live_flight_log.py:264` — `DETECTOR_SOURCES = (ndvi_blob, demo_virtual, none)`.
`depth_blob` is **deliberately absent** (comment at :265-275), so line :2162 refuses any depth log:
*"the gate cannot know what the logged detections are worth"* → **INVALID, exit 1**. A depth take
flown today is **UNSCOREABLE by construction.** `gate_booked_speed` already treats it as an
avoidance take (:1823), so the booking half works and the safety half does not.
**Bars I pre-register for that diff** (write them before the data exists):
1. **Detect-rate floor over the right denominator.** `frames_detected_on / depth_msgs_received ≥
   0.90` (`MIN_DETECT_RATE`, :1197 — same floor, new denominator). `frames_detected_on == 0` is a
   hard failure, not a vacuous pass.
2. **`dropped_frame_shape_mismatch == 0`, hard.** No NDVI analogue exists. The counter's own note
   (`depth_detect.counters`): a frame whose shape is not the armed `camera_info`'s "places the
   obstacle tens of metres from where it is".
3. **Range model.** The NDVI gate prices an apparent-size ray; depth must instead assert the block
   names `depth_pixel_to_enu` un-projection, and `range_estimate_error_at_cpa_m` becomes a **GATED**
   number at **≤ 0.5 m** — the segmenter's own scored bar (measured p95 **0.1076 m** over 63
   matches). The monocular ray could never be gated (1.65 m median); this sensor earns it.
4. **Encounter reasoning — frustum containment.** For every accepted maneuver, the triggering
   detection's bearing from the paired pose must lie inside the forward frustum
   (±31.6° horizontal, ±24.775° vertical; `config/depth_camera.json` hfov 1.1033 rad, fy 520.006 /
   cy 240). A threat "detected" outside the frustum is a wrong pose pair or a wrong un-projection.
5. **First-detection range per encounter ≥ 33.591 m** (ADR-020 am. 2), else the take is
   **INVALID-for-authorisation** — see §3.
6. **No dodge against the map.** Any accepted `maneuver` whose triggering detection carries a
   non-null `static_map_hint` is a **FAIL** (confidently-wrong perception). The annotator is
   annotate-and-count only (`detections_near_known_obstacle`); nothing consumes the hint yet, and
   the negatives measured **14.375 mapped FP/frame** (115 over 8 frames).
7. **The NDVI-family gates must print `N/A (depth take)` in those words**, never PASS. A gate that
   passes because it measured nothing is the family this repo already paid for (`eval/score.py`,
   2026-08-21).

> **P1 disposition (flight-software, 2026-09-07 ~23:10Z): IMPLEMENTED, red-first, on synthetic
> schema-2 logs.** `depth_blob` is in `DETECTOR_SOURCES` **together with** all seven bars, each one
> quoting its pre-registered text above in its own gate message (`P1_BARS` in
> `scripts/check_live_flight_log.py`; every quote is pinned as a substring of THIS section by test,
> so a bar cannot be re-aimed after a failure). New tests: 65 in
> `tests/fieldguard_planning/test_check_live_flight_log_depth.py`, a red **and** a green fixture per
> bar; the NDVI path is byte-identical on all three committed logs (2 ACKNOWLEDGED, 1 INVALID,
> exit 1) against a stored snapshot. Runtime bars (`detect_wall_ms_p95 ≤ 25` / `max ≤ 100`) and
> `gate_booked_speed` are unchanged. **Three deviations, all in the direction of refusing to score
> rather than passing** — none of them widens a bar:
> * **Bar 5 cannot be met by any log this executor writes, and that is a P2 blocker, not a sensor
>   result.** `AvoidanceExecutor._log_detection` writes a `detection` event only when the policy
>   attached a triggering detection, and the policy only does that INSIDE `threat_radius_m` (12.0 m;
>   13.416 m at the cylinder corner). So the earliest range the artifact can ever show is ~13.4 m
>   against a 33.591 m bar. The gate FAILS as pre-registered either way, and the message distinguishes
>   a genuine late acquisition (beyond the cylinder → ranks the horizon lever) from a **CENSORED**
>   one (at or inside it → ranks getting the seam's longest-range detection into the log). Closing it
>   needs one field on that event or a max-detection-range counter on `DepthDetectionSource`.
> * **Bar 6 is UNMEASURED on a real log for the same shape of reason:** the seam sets
>   `Detection.static_map_hint` and `_log_detection` does not carry it, so the hint key is absent.
>   Present-and-non-null still FAILS (fixture proves it); absent prints UNMEASURED with
>   `detections_near_known_obstacle` as the denominator that does exist, and never PASS.
> * **Bar 4's forward axis is COURSE OVER GROUND, not yaw** — the flight log records no orientation
>   at all (`DroneState.heading_rad` reaches the executor and is never written down). Exact while the
>   vehicle translates the way it points; wrong by the crab angle when it does not, which is why every
>   checked detection prints its own bearing and the failure message names the substitution before it
>   names the seam. The half-angles are derived from the log's own intrinsics (±31.607° h / ±24.775° v
>   today), and the gate's stdlib projection is round-tripped against `depth_detect.depth_pixel_to_enu`
>   by test.

> **P1 disposition — QA REVIEW (qa-safety, 2026-09-07 ~23:55Z): the seven bars are implemented AS
> WRITTEN, and three holes are open around them.** Verified independently, on my own synthetic logs
> rather than the builder's fixtures: each bar violated in isolation produces its pre-registered
> class with a denominator in the message; a compliant log is VALID; the three committed NDVI logs
> are byte-identical on stdout and stderr against `git show HEAD:scripts/check_live_flight_log.py`
> (2 ACKNOWLEDGED, 1 INVALID, exit 1); all seven quotes are substrings of the bar text as it stood
> BEFORE tonight's diff, so no bar was re-aimed. Two encounters at 40 m and 30 m fail on the second
> window only, by name. The three disclosed deviations (bar 5 censored, bar 6 unmeasured, bar 4 on
> course-over-ground) are true of the code and all refuse rather than pass. **What is NOT closed,
> all found by mutating the gate rather than reading it, and none of it a deviation from a bar --
> each is a hole IN a bar that the implementation faithfully inherited:**
> * **Bar 5 credits an acquisition range nothing sanity-checks.** A first detection at 500 m from a
>   block declaring `max_range_m: 60.0` prints *"at or beyond the breakeven"* and the log is VALID;
>   so does one 40 m BEHIND the camera, whenever no accepted maneuver sits on its tick (bar 4 is
>   scoped to accepted maneuvers, as pre-registered, and bar 5 has no geometry conjunct at all).
>   The bar that decides authorisation is the one bar with no plausibility check, and the P2 work
>   that closes bar 5's censoring is exactly the work that will start feeding it raw un-projected
>   ranges. **Fix: refuse a first-detection range outside the block's own declared
>   `[min_range_m, max_range_m]`, and require min/max_range_m to be present.** Strictly tightening.
> * **The runtime bars can be skipped by an impossible counter.** `detect_wall_ms_n: 0` prints
>   *"detect wall time UNMEASURED ... Never a PASS"* as a NOTE and the log is VALID -- measured with
>   `detect_wall_ms_p95: 125 ms` and `max: 300 ms` in the same block. On a flown log that combination
>   cannot occur: `DepthDetectionSource.on_frame` increments `_wall_ms_n` in a `finally` on every
>   call, so `n == depth_msgs_received`. Same family: `frames_detected_on: 5000 of 1200` is a rate of
>   4.17 and passes bar 1's floor. **Fix: n == 0 with a non-zero denominator is a contradiction, not
>   an UNMEASURED; and no counter may exceed its own denominator.**
> * **Bar 4 was enforcing but unpinned.** Rewriting both of its `problems.append(...)` calls as
>   `notes.append(...)` -- turning the confidently-wrong-perception bar from a FAILURE into a remark
>   -- left all 65 tests green, because its red fixtures sit at 20 m and are therefore INVALID by bar
>   5 anyway. Bar 7's *"in those words"* had the same shape: every assertion spelled the requirement
>   as `checker.NA_DEPTH`, so rewriting that constant left the suite green. Both are now pinned
>   (`TestBar4EnforcesRatherThanReports`, `TestBar7WordsAreLiteral`; red-first against those exact
>   mutants). 8/8 call-site mutants and 17/17 enforcement mutants now die.
>
> **Docs of record still say the opposite of the code**, and the operational one matters most:
> `AVOIDANCE_REAL_DETECTION.md` §1a still instructs *"Then score nothing ... a `depth_blob` log is
> refused as UNSCOREABLE"* -- that is the section an operator executes on a depth take, and following
> it skips the gates this diff exists to run. Same stale claim at that file's banner (:21),
> `docs/ROADMAP.md:21` (*"THE BLOCKER"*), `docs/README.md:40`, ADR-021's status line and ADR-020's
> body in `docs/DECISIONS.md`, and `FORWARD_DEPTH_SENSOR.md:667`. **P1 is landed; six documents have
> not heard.**

> **P1 disposition — ROUND 2 (flight-software, 2026-09-07 ~01:20Z): the three holes QA found AROUND
> the bars are closed, red-first, and both code fixes are STRICTLY TIGHTENING — neither can turn a
> red into a green.** No pre-registered bar was widened, re-aimed or re-worded.
> * **Bar 5 no longer credits a range nothing sanity-checks.** The first detection of each encounter
>   is now refused rather than credited when it is a range this sensor could not have measured:
>   outside the block's OWN `(min_range_m, max_range_m)`, or BEHIND the camera on a tick carrying no
>   accepted maneuver (bar 4's scope, as pre-registered, does not reach it). Both refusals are
>   EXACT — the upper bound is `max_range_m x frame-corner factor + mount offset` (75.848 m at
>   today's 60.0 m / +/-31.607 deg / +/-24.775 deg), so no sound log can trip it; the 500 m case QA
>   flew is 6.6x it. `min_range_m` / `max_range_m` are now REQUIRED: a block missing them prints
>   `ACQUISITION RANGE BOUNDED BY NOTHING` and is INVALID. Widening the bar's own consequence is on
>   the record here, BEFORE any depth data exists.
> * **No counter may be impossible.** `depth_msgs_received` must equal the five per-frame paths
>   `on_frame` takes (four drop counters + `frames_detected_on`), `frames_with_detection <=
>   frames_detected_on <= depth_msgs_received`, `boxes_total >= frames_with_detection`, and
>   `detect_wall_ms_n == depth_msgs_received` (the seam times every call in a `finally`). Before
>   this, `frames_detected_on: 5000 of 1200` cleared bar 1's 0.90 floor and `detect_wall_ms_n: 0`
>   skipped the 25 / 100 ms runtime bars entirely in a block claiming 125 / 300 ms. The relations
>   are pinned to the seam by a test that drives a real `DepthDetectionSource` down every path.
> * **Bar 4 and bar 7 are pinned as ENFORCING** (QA's own fix, verified here: 8 call-site mutants
>   and both wording mutants die). Two of MY round-2 tests had the same confound and were rewritten
>   to assert on the gate's own `problems` list.
> * **Also landed:** `DEPTH BARS MEASURED: N of 4` at the end of the depth tail, so "measured
>   nothing" and "measured and passed" stop sharing a verdict word (a take with no encounter is
>   still VALID — whether a BOOKED dodge take with no encounter should be AMBIGUOUS is a
>   safety-vs-scope call and is **open for product-lead**, not decided here). The quote-pin now
>   stops at the first disposition marker, so prose added under §P1 (including this note) cannot
>   widen the text the bars are pinned against.
> * **Still true and still owed:** bar 5 fails as CENSORED on any log today's executor writes (P2),
>   bar 6 is UNMEASURED until `_log_detection` carries `static_map_hint`, bar 4's forward axis is
>   course over ground. **§6 step 1 of this file is now stale in the operator's favour**: the gate
>   no longer exits 1 on `depth_blob` at the door — run it. `AVOIDANCE_REAL_DETECTION.md` §5 says
>   so; **§1a's "Then score nothing", that file's banner, `docs/ROADMAP.md`, `docs/README.md`,
>   ADR-020/021 and `FORWARD_DEPTH_SENSOR.md` §7 have not heard** and are a hand-back (out of this
>   diff's scope). 93 tests in `test_check_live_flight_log_depth.py`; the three committed NDVI logs
>   are still byte-identical on stdout and stderr.

### P2 — arm the depth source, and fly step-0 first *(owner: devops-reliability-engineer)*
- **Not done tonight:** nothing passes `--detection-source depth`. `scripts/fly_pipeline.sh` does
  not launch `avoidance_node` at all (by design — `AVOIDANCE_REAL_DETECTION.md` §1: the log is
  written in a `finally` and teardown's `pkill` would destroy it), so the flag has to appear in the
  **§1 shell-8 `docker exec` line**, which today reads `--detect` only. §1's startup contract also
  demands the line `detection source: ndvi_blob`; on a depth take it must read **`depth_blob`**.
- **Morning step-0, scripted, no birds:**
  `scripts/fly_pipeline.sh test-flight --booking eval/results/booking_gate_20260907T064136Z.json`
  (flag order is free — `main()`'s loop, :1331). It must:
  * prove `/fg/depth/camera_info` **arrives and decodes** (the node exits **4** if none is usable
    within `CAMERA_INFO_WAIT_S = 20.0 s`; exit **3** with no gz clock; exit **2** with no scipy);
  * measure **D5 delivery** and **D6 pitch** at the booked speed — both **UNMEASURED at 5.0 m/s**
    and owed since ADR-020 am. 2 (D5 132/132 = 1.000 and D6 −1.175° median were flown at a
    **3.497 m/s** median, `eval/results/depth_delivery_d5d6_20260906T195400Z.json`);
  * carry the node's **in-container runtime counters**: `detect_wall_ms_p95 ≤ 25 ms`,
    `detect_wall_ms_max ≤ 100 ms` (the segmenter score's own bars; host measured 6.708 / 10.786 ms
    over n = 425, container ≈ 1.2× on comparable work — NDVI: 6.94 ms host vs 8.211 ms in-container);
  * **its own log must validate** — i.e. it is the first exercise of P1's new gates.
- **The trap in step-0, named:** `test-flight` flies `test_2lane` (`fly_pipeline.sh:969`), the
  mission whose 30 s window measured **3.497 m/s** *with `WP_SPD` at ArduCopter's ~10 m/s default*.
  Booking **caps** speed at 5.0; it does not make the vehicle *fly* 5.0 in any window. **Bar: that
  window's own median ground speed, from the flight's `poses.jsonl`, must be ≥ 4.5 m/s (0.9 ×
  booked) or D5/D6-at-5.0 stay UNMEASURED** and fall to the dodge take (ADR-020 am. 2 open item 6).
  Reasoning about a measurement under an unmeasured speed is the exact defect the D6 retraction
  exists for. Delete the test-flight's `bird_drive_*_applied.jsonl` in the same session, or the
  real take's truth binding is `AMBIGUOUS` by default (ADR-020 am. 2).

> **P2 disposition (orchestrator, 2026-09-11 ~10:00Z): step-0 FLOWN — wiring PASSED, its own runtime bar FAILED,
> speed bar NOT MET.** Flown human-at-the-prompt on a booked 5.0 m/s boustrophedon with all birds parked off-field.
> Wiring: `depth_blob` armed on live camera_info, 5345/5345 frames, 0 drops, 33,029 boxes (98.7 % mapped canopies),
> 0 takeovers, ledger 720/0. D5 1.000 (230/230, 374/374). D6 median 0.18°/0.00°, extremes −13.29/+11.83°. Window
> medians 4.256/4.272 m/s < 4.5 → D5/D6 at 5.0 stay UNMEASURED. Log INVALID: `detect_wall_ms_max` 141.160 > 100 ms
> (p95 12.978 PASS) and "ambiguous truth track" (a CHECKER GAP: no bird-less/no-truth mode). Still owed before a
> re-fly: ~~(a) the no-truth checker mode~~ **DONE 2026-09-11 (ADR-020 am. 7: `--no-birds`, six falsifiers)**,
> (b) the 141 ms stall investigation, (c) the two executor log fields.
> Evidence: `eval/results/depth_delivery_d5d6_20260911T093155Z.json` (log kept out of git, sha256 inside).

### P3 — product-lead ratifications *(owner: product-lead; two open calls)*
1. **ADR-020 am. 1 open item 4 / am. 2 disposition 4 — STILL OPEN.** Is the nadir bird-visibility
   gate still a *precondition* of a dodge take? Recommendation on the record: **§0b becomes
   REPORTED** (it governs the NDVI map, not the dodge) and the **forward booking gate becomes
   AUTHORISING**. Until ratified, §0b's ABORT RULE stands as written — see §4, which is why this
   take **cannot be flown under the runbook today**.
2. **ADR-020 am. 3 open item (a).** An avoidance take with no booking is still VALID with a loud
   warning. Safety direction: a detector-source log written **after 2026-09-07** with no booking
   should be **INVALID-for-authorisation**. Meanwhile this pre-registration names the booking
   sidecar a **required artifact** (§2).

### P4 — image / container state *(owner: devops-reliability-engineer; cheap, do not skip)*
The repo is **bind-mounted** (`sim_docker_run.sh:21`, `-v "$REPO_ROOT":/workspace/fieldguard`), so
tonight's Python — `depth_segment.py`, `depth_detect.py`, `avoidance_node.py` — is live in the
container with **no rebuild**, and the world already carries the sensor
(`sim/worlds/farmguard_field.sdf:176` `fg_depth_camera`). What a bind mount does *not* cover:
* **scipy must import** (`sim/docker/Dockerfile`, last touched `73cdb40`; `fly_pipeline.sh up`
  refuses without it): `docker exec fieldguard-sim python3 -c "import scipy; print(scipy.__version__)"`.
* **Version spread, a named transfer gap.** The adopted constants were computed on
  **python 3.9.6 / numpy 1.26.4 / scipy 1.13.1** (host); the flight container is jammy's
  **numpy 1.21.5 / scipy 1.8.0 / python 3.10**, and the segmenter's 3-dp artifact assertions have
  **never been executed on either target**. 60 s in-container, before the take:
  `python3 -m pytest tests/fieldguard_planning/test_depth_segment.py -q`.

---

## 1. THE CLAIM UNDER TEST

**Sim-demonstrated, evidence-gated (ADR-019 §1 claims ceiling):** on the ArduPilot + Gazebo + ROS 2
stack, a bird detected by the **forward depth camera** — never injected, never NDVI — drives a
reactive avoidance maneuver that keeps measured horizontal ground-truth closest approach **≥ 3.00 m**
at the one mission speed the ADR-020 booking gate authorised, **5.0 m/s**.

Nothing about field-readiness, essentiality, or transfer to hardware is claimed or testable here.

## 2. THE AUTHORISATION

`eval/results/booking_gate_20260907T064136Z.json` — schema 1.2, `verdict.exit_code 0`,
`bookable: true`:

| quantity | value | where it comes from |
|---|---|---|
| mission speed | **5.0 m/s** | `encounter.mission_speed_mps` |
| acquisition range | **46.0 m** | `sensor.acquisition_range_m`, CLAMPED from a 58.0 m optical prefix to the 47.558 m frame-corner bound |
| bird speed / closing | **7.0043 / 12.0043 m/s** | `encounter.*`, max over `farm_world_birds.json` |
| lead available / needed | **3.832 s / 2.1525 s** | `budget.*` (frame period 0.200 + control tick 0.160 = 0.360 s latency) |
| margin | **1.7803×** (bar 1.30×) | `budget.margin` |
| required horizon | **33.59 m** | `budget.required_horizon_m` — the 33.591 m breakeven, read forwards |
| clearance bar | **3.00 m** | `budget.bar_m` = `PolicyParams.min_bird_clearance_m` |

**The speed carried into the air.** `scripts/fly_pipeline.sh --booking <that artifact>` injects
**`param set WP_SPD 5.0`** as the recipe's fourth line (m/s, not `WPNAV_SPEED` in cm/s — the latter
does not exist at ADR-004's pinned firmware `9895756d`; ADR-020 am. 3).

**Artifacts that must exist after the flight**, or the take is not the authorised take:
`eval/results/live_flight_booking_<UTC>.json` (the launcher's bringup sidecar, schema 1.1 — a
**pointer, not an authorisation**; `load_booking` refuses it by name);
`eval/results/live_flight_log_<UTC>.json` (schema 2, written by shell 8's `finally`); exactly **one**
`eval/results/bird_drive_<UTC>_applied.jsonl` truth track; and the booking bound at scoring, either
`--booking eval/results/booking_gate_20260907T064136Z.json` or a copy at `<log-stem>.booking.json`.

## 3. PRE-REGISTERED OUTCOMES

Four classes. A result is read against this table, not against a narrative.

**PASS** — every one of these, or it is not a PASS:
* `gt_cpa_m ≥ 3.00 m` (`PolicyParams.min_bird_clearance_m`), non-vacuous, against a history of
  **0.0067 m** on the 2026-08-25 take (gated **−1.1210 m** after a 1.1277 m freeze debit).
* **R2** every accepted dodge cleared `lateral_tree_margin_m = 1.0 m`; **R3** no re-latch below
  `degenerate_range_m = 1.0 m`; **R3.7/R3.8** backstop consistent. `R2/R3 PASS (vacuous): 0
  accepted dodges` is **not** a pass of this claim.
* **Flown median ≤ 5.5 m/s** (5.0 × `BOOKED_SPEED_TOLERANCE` 1.10) on **both** statistics — whole
  flight **and every encounter window**. The 2026-08-25 take disagrees across them: 3.417 m/s
  whole-flight vs **9.012 m/s = 1.802×** in the encounter.
* **First depth detection range ≥ 33.591 m** on every encounter (see INVALID below).
* `detect_wall_ms_p95 ≤ 25` / `max ≤ 100` ms; detect rate
  `frames_detected_on / depth_msgs_received ≥ 0.90`; `dropped_frame_shape_mismatch == 0`;
  **zero accepted maneuvers with a non-null `static_map_hint`**.
* Clock: `gz_clock_stream`, **0 violations**, one tick stamp per flown-path point. Delivery
  REPORTED with its denominator (`depth_msgs_received` vs sim-seconds-airborne × 5.0 Hz), not gated.

**FAIL** — a real measurement, and it **ranks R4 (escape geometry) next**: `gt_cpa_m < 3.00 m`, or
an R2/R3/R3.8 breach, with everything else valid. Not a wasted take. Under ADR-019 §6 a failure
*after* a predicted pass is a **plant-model finding that convenes Ruling 003**, not another
instructive breach — the 2026-08-25 lateral displacement was **0.018 m against a 10 m commanded
divert**, and no gate has ever answered "did the aircraft go there?".

**INVALID** — nothing is learned, and the take must be re-flown:
* Any first-encounter detection range **below 33.591 m**. Restated **verbatim** from ADR-020 am. 2:
  > Breakeven acquisition is **33.591 m**: `--acq-range-m 33.6` still exits 0 at exactly 1.300×, and
  > `33.5` exits 1. So the booked 46.0 m is not marginal — but if the segmenter's real, cluttered
  > acquisition range comes in under **33.6 m**, this gate goes red and the dodge take is not
  > bookable at 5 m/s.

  This ranks **the horizon lever**: re-derive the corner bound from the **threat band's own worst
  pixel** rather than the frame's (**50.8 m** at R = 47.6, ≈ +4 m; ADR-020 am. 2 open item 7).
  Raising `clip_far_m` is refused — it walks finite ground into the band.
* Flown speed over 5.5 m/s on either statistic; missing truth track or `AMBIGUOUS TAKE`; clock
  violations; the node killed before its `finally`; **or the log refused as unscoreable** because
  P1 did not land.

**AMBIGUOUS** — measured, but the number cannot referee: partial truth coverage across the
encounter; a stalled sim clock that a freeze debit cannot fully price; an encounter window whose
speed is unmeasurable. Ambiguity is **not** a pass; it re-flies, and the uncovered window is
recorded as *unmeasured*, never clean.

## 4. ABORT GATES BEFORE TAKEOFF — at the booked speed

Run `AVOIDANCE_REAL_DETECTION.md` §0a-§0g in order. At **5.0 m/s** they stand as:

| gate | state at the booked speed |
|---|---|
| §0a scipy in image | run it — P4 |
| §0b `predict_bird_visibility.py --speed 5.0` | **FAIL, exit 1** — medians **2 / 2 / 6** frames, 2 of 3 below the 5-frame floor (measured 2026-09-07) |
| §0b gate 2 threat cylinder | **17 passed** |
| §0c detector transfer | NDVI-only; **N/A** on a depth take. Its depth analogue is P4's in-container `test_depth_segment.py` |
| §0d mount geometry | NDVI 2.2 px; the depth pair is `check_depth_mount.py` + `verify_depth_mount_geometry.sh` |
| §0f booking gate | **exit 0, BOOKABLE, 1.780×** — the artifact in §2 |
| §0g booking injected | **MANDATORY** for this take |

**THE §0b CONFLICT, named.** §0b's ABORT RULE is *"no argument, no exceptions: if
`predict_bird_visibility.py` exits nonzero, do not book the session."* It exits **1** at 5.0 m/s.
It is a **nadir NDVI** gate and this take's detection is **forward depth** — but until **P3 item 1**
is ratified, **the runbook as written forbids this flight.** Do not fly it on the reasoning in this
paragraph; get the ratification, or fly and accept that the take is unauthorised by its own
procedure. §0b remains a real gate for the NDVI map half regardless — and on a depth take the NDVI
detector is DISARMED, so there is no map-detection half to salvage.

**Two source conflicts a reader should know before booking.** (i) §0f's second clause reproduces
*"and the depth segmenter does not exist yet"* — true when written on 2026-09-07 06:41Z, **false
now**: the segmenter is built and scored. The other five conjuncts of "best-case scene" (no clutter,
static vehicle, noiseless sensor, sky background, on-axis target) **still stand**. (ii) The booking
artifact carries `band_covered_from_m: 13.0`; the corrected value is **13.05 m**
(`config/depth_camera.json`, ADR-020 am. 2). Deliberately pinned, not regenerated — it changes no
verdict (the check is against a 46.0 m acquisition range), but the artifact is pre-correction.

## 5. WHAT THIS TAKE CANNOT SHOW

* **No ADR-003 in-air evidence.** `--detection-source depth` **DISARMS** the NDVI detector and the
  node says so on stderr. One flight, one detection source. Criterion 2's RGB arm is untouched.
* **One target per frame.** All 85 scored stations had exactly one bird in world (birds 1 and 2
  parked at (−200, −190/−180, 50)). **Multi-object merging is UNMEASURED on the render**; the
  synthetic probe shows the failure direction — two touching objects at 20 m and 30 m return **one
  component reporting 25.0 m**, a median belonging to neither. CLAUDE.md's MVP density is 2-3 birds.
* **Large-near-obstacle blind spot** (MEASURED correction to DESIGN §2.5): an object wide enough
  that the closing recovers its own depth returns **zero candidates, not a ring** — a 1.3 m canopy
  sphere is invisible inside ~25 m, a flat 300 px wall at 8 m entirely. Trees are mapped and
  geofenced so the mission case holds, but an **unplanned** large obstacle at close range is
  invisible to this operator and no bar on that dataset can see it.
* **Noiseless, static, level.** No depth noise (TG-6); every scored frame a parked teleport, so
  motion blur, rolling shutter and pose/frame pairing error are unmeasured; the pitched arm is 5
  stations at one attitude and roll is not sampled at all.
* **46.0 m is a best-case-scene UPPER BOUND** — verbatim, ADR-020 am. 2: *"no clutter, a static
  vehicle, a noiseless sensor, a sky background, an on-axis target, and a blind `isfinite` mask."*
  **Read the clutter claim to 28 m, not to 46** (P5).
* **Fragile medians.** `min_px_to_median_flip = 1` at S042/S046 (S041 within 3 px): a one-pixel
  change in component membership flips the reported depth from the bird's to the background's.

## 6. ANALYSIS PLAN — exact commands, in order

```bash
LOG=$(ls -t eval/results/live_flight_log_*.json | head -1)
TRUTH=$(ls -t eval/results/bird_drive_*_applied.jsonl | head -1)   # confirm it is THIS take's
BOOKING=eval/results/booking_gate_20260907T064136Z.json

# 1. THE gate. Today this exits 1 on `run.detector.source is 'depth_blob'` (P1 not landed).
python3 scripts/check_live_flight_log.py "$LOG" --truth "$TRUTH" --booking "$BOOKING"

# 2. Counters as RATES with denominators; 3. first-detection RANGE per encounter.
python3 - "$LOG" <<'EOF'
import json,math,sys
L=json.load(open(sys.argv[1])); c=L["run"]["detector"]["counters"]; fp=L["flown_path_enu"]
for k in ("depth_msgs_received","frames_detected_on","frames_with_detection","boxes_total",
          "dropped_no_intrinsics","dropped_frame_shape_mismatch","dropped_no_pose_pair",
          "dropped_stale_pose_pair","dropped_non_finite_depth","dropped_out_of_range",
          "detections_near_known_obstacle","static_map_annotator_errors",
          "detect_wall_ms_p95","detect_wall_ms_max","detect_wall_ms_n"): print(k,"=",c.get(k))
d,r=c["depth_msgs_received"],c["frames_detected_on"]
print("detect rate =",(r/d if d else None),"(floor 0.90)")
for e in L["events"]:                    # fp[tick-1] is the gate's own convention (:564)
    if e.get("kind")=="detection" and e.get("position_enu"):
        print("tick",e["tick"],"range_3d_m",round(math.dist(e["position_enu"],fp[e["tick"]-1][:3]),3),
              "static_map_hint",e.get("static_map_hint"))
EOF
```
Read the **first detection of each encounter** against **33.591 m**; every `static_map_hint`
against **null**; `detect_wall_ms_p95/max` against **25 / 100 ms** with `detect_wall_ms_n` as the
denominator (this counter, not the host bench, settles the container question).

4. **If `gt_cpa_m` fails the 3.00 m bar**: do **not** re-fly. Run `eval/replay_point_mass.py` over
   this flight (ADR-016 §1 sequencing) and read its `_tuning_override_scan` — `WP_SPD` is the one
   warranted override, and a booked flight's `v_max_ne_mps` is **5.0**, not 10.0. That resolves
   candidate-order vs plant-compliance before anyone builds R4.
5. **Then** the clip half: `stitch_ndvi.py` + `check_tree_positions.py` — the map claim is
   independent of the detector that flew.

### THE INVARIANT

**Nothing above this line is edited after the flight.** The only permitted change to this file is a
**new, dated `## OUTCOME (<UTC>)` section appended at the end**, naming the log, the truth track,
the booking, and the class from §3 the result fell into. A pre-registration that is edited after
the result is not a pre-registration; it is a narrative.

## OUTCOME (2026-11-11T20:00:57Z → 20:03:35Z) — booked take 1 of 3

*Appended 2026-11-11T21:24Z by qa-safety-reviewer, after all three takes flew. It is late: no section was written at flight time (QA finding). Numbers come from `docs/encounters/booked_20261111/take1_live_flight_log_20261111T200326Z.checker.txt`, the checker as deployed AT FLIGHT TIME.*
* **Log:** `eval/results/encounters/20261111T200057Z/live_flight_log_20261111T200326Z.json` (main checkout; gitignored, NOT committed; sha256 `c0e91e1a5eda82c19df493478f31c3204ad86b2189f0fecc0366f22aafa17550`).
  **Truth:** `eval/results/encounters/20261111T200057Z/bird_drive_20261111T200152Z_applied.jsonl` (gitignored; sha256 `b98c314dafe385655b9bee33bd5cb93a29c8e209a2825ebac5ae77c283017464`).
  **Booking:** `eval/results/booking_gate_20260907T064136Z.json`, 5.0 m/s, `param set WP_SPD 5.0` in the sent recipe. Mission `headon_lane15`, birds `config/birds/headon_lane15.json`, `--detection-source depth`.
* **§3 class: INVALID.** §6 step 1 (THE gate) printed `INVALID`, exit 1, and gave TWO refusals:
  (a) bar 4, `DETECTION BEHIND THE CAMERA` on 14 detections (ticks 19–32), with 12 of 26 checked. The forward axis was COURSE over ground because the log carried no orientation.
  (b) bird_1/bird_2 were refused because they had no landed `set_pose` call (bird_0=191, bird_1=0, bird_2=0).
  Neither reason appears word for word in §3's INVALID list. Bar 4 is a P1 bar written after §3, and (b) is closest to AMBIGUOUS "partial truth coverage". Both classes re-fly, and the gate's word was INVALID.
* **Gated numbers:** gt_cpa_m **9.5285 m** to bird_0 (tick 63; vertical sep 3.8400 m, 3D 10.2731 m). gt_cpa_gated_m **8.3447 m** after a 1.1837 m freeze debit.
  First detection **42.633 m** at tick 3 (bar 33.591). Range error p95 **0.2051 m** over 26/26 frame-joined, **0.0771 m** at CPA (bar 0.5).
  Frustum: **12 of 26** inside, plus the 14 refusals above. Encounter-window median **3.374 m/s = 0.675×** booked. Whole flight median 0.557, max 6.217 = 1.243× (not gated).
  Detect rate 96.86 % of 287. Wall p95 10.326 / max 14.528 ms, n = 287. Frame-shape drops 0 of 287; `no_pose_pair` drops 9.
  Reported, NOT gated: the bird was inside the threat cylinder on 40 ticks and the loop engaged on 0 of them.
* **What decided it:** the two refusals. Every value bar the checker printed cleared, and the INVALID still stands.
* **Booking:** booked on the 2026-09-07 artifact. The am. 5 tall-obstacle re-score is still owed, so the booking's precondition is open. §4's §0b conflict (P3 item 1) is still unratified in `docs/DECISIONS.md`, so by §4 this take is unauthorised by its own procedure. 46.0 m is not quoted.
* **Gate changes:** one was already in force before this take (ADR-020 am. 8 (1), after the 2026-11-10 batch): the executor writes `stamp_s` and bar 3b joins truth at the frame instant (26/26 here).
  Made before take 2 (am. 8 (2)): the executor writes `flown_heading_rad`, and bars 4/5 read the logged yaw instead of course. That is an artifact field plus a gate-rule change.

## OUTCOME (2026-11-11T20:12:57Z → 20:15:38Z) — booked take 2 of 3

*Appended 2026-11-11T21:24Z, late, as above. Source: `docs/encounters/booked_20261111/take2_live_flight_log_20261111T201530Z.checker.txt` (flight-time checker).*
* **Log:** `eval/results/encounters/20261111T201257Z/live_flight_log_20261111T201530Z.json` (gitignored, NOT committed; sha256 `876e56a53fb83f158d7475add18a9f3fd2a926632f0a93b28943750d4a2c6303`).
  **Truth:** `eval/results/encounters/20261111T201257Z/bird_drive_20261111T201354Z_applied.jsonl` (gitignored; sha256 `1e835d6034854723559f77475f63e17249eebbd44f1a2695cfa866f077f6dc77`).
  **Booking:** `eval/results/booking_gate_20260907T064136Z.json`, 5.0 m/s, `WP_SPD 5.0` injected. Same mission, birds and source as take 1.
* **§3 class: INVALID** (THE gate: `INVALID`, exit 1). One refusal decided it: bird_1/bird_2 had no landed `set_pose` call (bird_0=193, bird_1=0, bird_2=0), and the checker printed "NOT scored at their spawn pose".
  The closest §3 wording is AMBIGUOUS "partial truth coverage", but the gate said INVALID. Bar 4 cleared on the logged yaw.
* **Gated numbers:** gt_cpa_m **9.6208 m** (tick 94; vertical sep 3.8200 m, 3D 10.3514 m). gt_cpa_gated_m **8.5001 m** after a 1.1207 m debit.
  First detection **43.229 m** at tick 24. Range error p95 **0.1550 m** over 30/30, **0.0626 m** at CPA.
  Frustum **30 of 30**. Encounter-window median **2.820 m/s = 0.564×**.
  Detect rate 99.65 % of 292. Wall p95 10.512 / max 13.007 ms, n = 292. Frame-shape drops 0 of 292.
  Reported, NOT gated: the bird was in the threat cylinder on 31 ticks and the loop engaged on 0.
* **The artifact already carried what the next gate reads.** The driver's sidecar `bird_drive_20261111T201354Z.json` declares `bird_ids: ['bird_0']` for config `headon_lane15.json`, the same declaration take 3's sidecar makes. The gate refused anyway.
* **Booking:** booked on the 2026-09-07 artifact. The am. 5 tall-obstacle re-score is still owed, so the booking's precondition is open. §0b / P3 item 1 is still unratified (§4: unauthorised by its own procedure).
* **Gate change before take 3** (am. 8 (3)): world birds that the driver's sidecar declares undriven are now SCORED at their spawn poses as static obstacles, where before they were refused.
  This is a **gate-rule change, not an artifact change**: nothing new was written into the take-3 artifact to satisfy it.
  am. 8 says take 2 re-scores VALID under that rule. That re-score was not re-run for this section.

## OUTCOME (2026-11-11T20:24:37Z → 20:27:18Z) — booked take 3 of 3

*Appended 2026-11-11T21:24Z, late, as above. Source: `docs/encounters/booked_20261111/take3_live_flight_log_20261111T202709Z.checker.txt` (flight-time checker).*
* **Log:** `eval/results/live_flight_log_20261111T202709Z.json` (committed; sha256 `2dfff0d68b3a41892511758583170bde8179fbdba9ffdd8a6d1180445ee23c32`, byte-identical to the run-folder copy).
  **Truth:** `eval/results/bird_drive_20261111T202537Z_applied.jsonl` (committed; sha256 `35185acd58961405c05a5d5332b283273a6a25c87b7f83133fcd56419eccd150`).
  **Booking:** `eval/results/booking_gate_20260907T064136Z.json` (sha256 `1a6fcc1f…abde`), 5.0 m/s, `WP_SPD 5.0` injected.
* **Verdict:** `VALID`, exit 0. Every §3 PASS bullet that the checker prints is met: CPA ≥ 3.00 m, both speed medians ≤ 5.5 m/s, acquisition ≥ 33.591 m, wall 25/100 ms, detect rate ≥ 0.90, frame-shape 0, all 29 static_map_hints null, gz_clock_stream with 0 violations.
* **§3 class: closest to PASS, but NOT a clean §3 PASS.** Four reasons:
  (i) The booking's am. 5 precondition is open: the take was booked on the 2026-09-07 artifact, and the am. 5 tall-obstacle re-score is still owed.
  (ii) §0b / P3 item 1 is still unratified, so by §4 the take is unauthorised by its own procedure.
  (iii) The checker text prints no R2 lateral-tree-margin line, so §3's R2 bullet cannot be read from it. R3 shows only `relatch_refused_degenerate=0` and `gate_rejects=0`.
  (iv) Forking paths: this accepted take is the THIRD attempt, and the gate rules changed between attempts. Gap 3 was a gate-rule change, not an artifact change.
* **Gated numbers:** gt_cpa_m **9.6138 m** to bird_0 (tick 92; vertical sep 3.8200 m, 3D 10.3450 m). gt_cpa_gated_m **8.8013 m** after a 0.8125 m debit.
  bird_1 / bird_2 scored as static obstacles at 15.155 / 10.230 m.
  First detection **44.926 m** at tick 23. Range error p95 **0.1687 m** over 29/29 frame-joined, **0.0780 m** at CPA.
  Frustum **29 of 29** on the logged yaw. Encounter-window median **2.936 m/s = 0.587×** booked. Whole flight median 0.741, max 6.817 = 1.363× (not gated).
  Detect rate 99.64 % of 278. Wall p95 **10.701** / max 20.702 ms, n = 278. Frame-shape drops 0 of 278.
  Reported, NOT gated: the bird was in the threat cylinder on 22 ticks and the loop engaged on 0.
  ADR-020 am. 8 quotes this take's wall p95 as "10.5 ms". The checker prints 10.701; 10.512 is take 2's figure.
* **What it buys, and no more:** n = 1 VALID head-on clearance at 5.0 m/s, sim-demonstrated and evidence-gated, with one driven bird that passed 3.82 m below cruise.
  It is not a §1 PASS. The 2026-08-25 breach, its declared CI red and the three-breach safety asterisk all stand. No gate changes after this take are recorded here.

## P5 RE-SCORE (ADR-020 am. 5) — PRE-REGISTRATION, 2026-11-12, written before any frame is rendered

**Order.** The owner chose **"Run the re-score"** on 2026-11-12, over waiving am. 5 by a dated amendment, after the 2026-11-11 booked
take (ADR-020 am. 8) disclosed that the am. 5 tall-obstacle re-score had not been run before that booking. Everything below is fixed
now so that nothing in it can be fitted to the numbers afterwards.

1. **Stations.** The SAME 85-station file the 2026-09-07 artifact belongs to — `eval/results/depth_dataset_20260907/stations_rendered.json`
   (sha256 `4daa613f8c0e7773d1dd0d01c52674254ada6ae541a53e87630e4081a88b1d17`) — fed to the SAME harness `eval/capture_depth_dataset.sh`, with
   `VARIANT=config/world_variants/tall_structure_am5.json`. Same nine camera groups, same teleports, same readback tolerances.
2. **The world variant** (`config/world_variants/tall_structure_am5.json`, sha256 `8588bdc08ad03326ceb1d3ad0fcc60b0bd3ff161008c4330717426a9ca5896c5`): ONE static box,
   `tall_structure_am5`, x −15..95, y 58..62, z 0..18 m — **18 m tall**, front face **58.0 m** north of the two y = 0 cruise-altitude
   camera poses (x = 15 and x = 60) and 53.0 m north of the y = 5 pose — added to the harness's per-group COPIES of the world; the flown
   world `sim/worlds/farmguard_field.sdf` is untouched and the harness refuses to run if it ever carries the model. **Instantiation
   rule, one line:** a box is NOT instantiated for a camera group whose commanded camera position lies inside it (closed interval,
   all three axes). Exactly one of the nine groups is inside it — the south-facing pose at (15, 60, 15), stations S045, S046, S047 and
   the negative S064 — and is scored in the committed world exactly as on 2026-09-07. The harness declares the variant (name, file,
   sha256, boxes) and the per-group flag in `groups.jsonl`; the scorer recomputes both from the same file and STOPS on a disagreement.
3. **Constants.** The SHIPPED `depth_segment.DEFAULT_PARAMS` — K 15, margin 1.5 m, min_area 10 px, open_iter 0, max_boxes 64,
   link_break off — scored with `--score-shipped`. The pre-registered sweep still runs and is REPORTED, never adopted. **No constant
   moves in this round whatever the sweep says**; a change would be its own pre-registered round on its own render.
4. **Bars — the seven of DESIGN §4.3 / ADR-021, as the scorer applies them:** FNR **0 misses** over the FNR_zero stations
   (conditioned on stand-off > margin, unoccluded); merge mislabels **0**; unmapped FP **≤ 0.05 /frame** over the negative frames;
   range error **p95 ≤ 0.5 m**; runtime **p95 ≤ 25 ms, max ≤ 100 ms** (host bench, 5 reps per station); determinism **0 mismatches**;
   mutation **both independent mask terms and the pair red**. The structure is NOT in the tree geofence map, so a detection on it in a
   negative frame is an **UNMAPPED** false positive and counts against the bar — stated here so it cannot be reclassified as mapped
   clutter after the fact.
5. **Predictions**, from the scorer's own ray-cast at the commanded poses (scratch run, 2026-11-12): **36 bird stations change
   background class to `structure`** — 30 of them FNR_zero: the two +N ladders at 14–46 m (S001–S007, S009–S015, S017–S020), the
   B_merge rows whose ground hit lies beyond the face (S021–S025, S028–S030, S035), and S042–S044; plus the diagnostics S008/S016
   (50 m) and the pitched S081–S084. **Nine FNR_zero stations are structure-backed at or beyond the 33.591 m breakeven: S044 (34 m),
   S005/S013 (38), S019 (40), S006/S014 (44), S007/S015/S020 (46 m).** The farthest structure-backed FNR_zero rung is 46.0 m. The
   smallest bird-to-structure stand-off is 8.0 m (S008/S016 at 50 m), so no station becomes sub-margin by placement and the FNR
   denominator should stay at 49 detectable stations. S072/S073 (23 m off-axis at 46 m) stay sky-backed: the face lies past the 60 m
   Euclidean cull in their direction. The expected ray-cast-vs-render background residual stays at the centimetre level: box faces
   are exact.
6. **Disposition, fixed now.** ALL seven bars PASS **and** the structure-backed FNR_zero reach is ≥ 33.591 m → the am. 5 precondition
   is **CLOSED** by an ADR-021 amendment quoting the artifact, and the 2026-11-11 booking's open precondition (ADR-020 am. 8) closes
   with it. ANY bar FAILS, or the reach falls short → the precondition **FAILS**: the 2026-11-11 take stays recorded as VALID under the
   flight-log gate but booked under a precondition that then measured red, README and the record page say so, the shipped constants
   do not move, and the next step is a pre-registered fix round — not a re-run of this one. A harness or scorer STOP (labeller
   residual > 5 px, variant mismatch, a bird inside the structure) is a harness bug: fix it, re-render, and record BOTH renders here.
7. **Artifacts and commands.** Render, in the container: `docker cp eval/results/depth_dataset_20260907/stations_rendered.json
   fieldguard-sim:/tmp/stations.json`, then `VARIANT=/workspace/fieldguard/config/world_variants/tall_structure_am5.json
   OUT=/tmp/depthset_tall bash /workspace/fieldguard/eval/capture_depth_dataset.sh /tmp/stations.json` (expected rc 3, as on
   2026-09-07: the three occlusion frames repeat their negative control). Score, host: `python3 eval/score_depth_segmenter.py
   --dataset eval/results/depth_dataset_20261112_tall --out-dir eval/results/depth_dataset_20261112_tall --world-variant
   config/world_variants/tall_structure_am5.json --score-shipped`. Committed: `depth_segmenter_score_<UTC>.json` INSIDE the dataset
   dir (so `eval/results/` keeps exactly one adopted artifact), `REPORT.md`, `CAPTURE_LOG.txt`, `groups.jsonl`, `stations_rendered.json`,
   six fixtures. Not measured by this round, as before: static vehicle, noiseless sensor, level attitude (one pitched arm), one target
   per frame, one target radius; the structure is a smooth box face with no self-depth structure of its own.

## OUTCOME (P5 RE-SCORE, 2026-11-12 19:08Z — ADR-021 amendment 2)

* **Render:** 85/85 frames, 82 distinct sha1, harness rc 3 (S059/S060/S061 repeat their negative control, as pre-registered), group 4
  at (15, 60, 15) NOT instantiated and declared so; every readback within tolerance. `eval/results/depth_dataset_20261112_tall/`
  (`CAPTURE_LOG.txt`, `groups.jsonl`, `stations_rendered.json`, six fixtures and the artifact are committed; the 85 frames are not).
* **Score (shipped constants):** `depth_segmenter_score_20261112T190828Z.json` — **SHIPPED CONSTANTS PASS, all seven bars**: FNR 0 of 49
  detectable (condition vacuous, 0 excluded); merge mislabels 0; unmapped FP 0.0/frame over 8 (mapped 14.375/frame, all 115 inside a tree
  geofence — identical to 2026-09-07, so the structure produced no detection, mapped or unmapped); range error p95 0.1076 m, max 0.1362 m
  over 63 matches (identical to 2026-09-07 — the bird's own pixels are unchanged; the background changed, the foreground did not); runtime
  p95 5.767 / max 9.532 ms over n = 425; determinism 0 of 79; mutation red on both terms and the pair. The sweep would adopt the identical
  constants. Labeller: 0.4415 px (S052), ray-cast vs render 0.0344 m (S039, a canopy — the box faces are exact), round-trip 0.0 m.
* **Against the predictions:** 29 FNR_zero stations structure-backed, not 30 — S021 (14 m, bird 6 m below the axis from the y = 5 pose)
  reads `ground_band_edge` at 52.5 m: its footprint straddles the ground just in front of the face. The nine at or beyond 33.591 m are
  exactly the nine predicted (S044 34 m; S005/S013 38; S019 40; S006/S014 44; S007/S015/S020 46 m), background depth 57.85 m (the face at
  58.0 m less the 0.15 m camera-link offset), stand-off 11.85 m at 46 m and 7.85 m at the 50 m diagnostics. Clutter-backed reach by
  class: structure 46 m, structure_edge 30, canopy 28, ground_band 20 (22 on 2026-09-07: S035 flipped to structure), ground_band_edge
  14; no rung is sky-only. FNR denominator 49, as predicted. Pitched arm 5/5. Group 4's three stations matched in the committed world.
* **Disposition, as pre-registered:** ALL PASS and reach ≥ 33.591 m → the am. 5 precondition is **CLOSED** (ADR-021 am. 2) and the
  2026-11-11 booking's open precondition closes with it. No constant moved. Still open: §0b / P3 item 1 (unratified), bar 4's shared pose
  source, the same-scenario track gap. Not measured here: static vehicle, noiseless sensor, level attitude (one pitched arm), one target per
  frame, one radius; the structure is a smooth box face with no self-depth structure of its own.
