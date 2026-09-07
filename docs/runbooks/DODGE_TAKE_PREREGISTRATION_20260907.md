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
