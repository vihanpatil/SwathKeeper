# SAFETY FINDING — closest approach 0.0067 m, **NOT ACKNOWLEDGED** (S1 class, 2026-08-25)

**This log is kept as the recorded evidence of a FAILED take. It is not evidence of a safe flight,
and — unlike its two siblings in this directory — it is not acknowledged history either.**

`scripts/check_live_flight_log.py` reports this file as **INVALID, exit 1**, and it stays that way
until the flight is re-flown after R4. This marker exists to record **why** the take failed, beside
the evidence, so nobody meets the log without the reason. **It does not acknowledge the breach and
must not be read as doing so.** Acknowledgement takes two halves (runbook §6a) and the second half —
the log stem pinned in `ACKNOWLEDGED_BREACH_STEMS` — is *deliberately absent*. Marker without pin is
half an acknowledgement, half acknowledges nothing, and the gate says so by name. That is the
correct record for a flight that breached; the two pinned stems are *historical* logs that cannot be
re-flown, and that list is meant to stay two long.

## The number

| | |
|---|---|
| ground-truth CPA (horizontal) | **0.0067 m** to `bird_0`, tick 991, `t_sim` 202.775 s |
| the number actually gated (freeze-debited) | **−1.1210 m** = 0.0067 − 1.1277 m |
| policy bar (`PolicyParams.min_bird_clearance_m`) | **3.00 m** |
| geometry at CPA | drone z 15.0300 m, bird z 11.0000 m, vertical sep **4.0300 m** — inside the ±6 m threat band |
| freeze debit | 1.1277 m = 2 identically-stamped ticks from tick 890 hiding 0.161 s × the fastest scripted bird at 7.00 m/s |
| detection-CPA (estimator check, **not** the gate) | 0.2096 m; `range_estimate_error_at_cpa_m` −0.2028 m |
| sensor lead / policy lead | **0.175 s / 0.000 s** — the first detection of the encounter arrived *on the CPA tick* |

The gated number is the debited one on purpose: a frozen truth join can only ever over-report
separation, never under-report it, so the worst case is what gets compared to the bar.

## The anatomy, in three sentences

`bird_0` patrols mission lane x=15 at z=11 and the drone flew that same lane southbound at ~8.4 m/s,
giving a 14.4 m/s closure with 4.03 m of vertical separation — inside the ±6 m threat band — while
the first detection of the entire encounter arrived on the CPA tick itself at a trigger range of
0.21 m (`range_degenerate: true`). The loop then did everything it is built to do inside 0.434 s of
GUIDED authority — latch @991, relatch @992 (offset 18.896 m, the away-vector sign-flipped in
0.123 s as the drone passed over the bird), recommand @993, relatch @994 (6.285 m), resume @995 —
and displaced the vehicle **0.018 m** laterally against a 10 m commanded divert. No dodge was in
progress at closest approach because there was no interval in which one could have been started:
the bird was truly inside the threat cylinder on 16 ticks and the loop engaged on 4 of them, the
camera saw it on 2 frames of 1301, and `resume` fired on `threat_cleared` because one empty frame
replaced the latest detection — not because anything had cleared.

## This was pre-registered, in writing, before the flight

`docs/runbooks/AVOIDANCE_REAL_DETECTION.md` §7, verbatim:

> **PRE-REGISTERED EXPECTATION — read this before you read the result**
>
> R2 (`lateral_tree_margin_m` 1.0 m) and R3 (degenerate re-latch refusal) fly for the first time
> here. **R4 does not.** The reversal-preferring candidate order that produced the two historical
> ~5 cm bird strikes is unchanged, and ADR-015's threat bird passes nearly overhead. **This flight
> may honestly FAIL its own GT-CPA gate.** That is a measurement which ranks R4 next, not a wasted
> take — and it is written here *before* the flight so it cannot be reinterpreted afterwards.

The take landed on exactly that branch. It is reported as the system working: a real detector drove
a real dodge, a gate that did not exist eight days ago measured the separation that resulted, and
the number came back a breach. It is not a pass, it is not "nearly a pass," and it is not softened
by anything else in this file.

## What this ranks — and what it is careful *not* to claim

**R4 (escape geometry) is ranked next by this measurement**, exactly as §7 pre-registered. Three
facts travel with that ranking, and the third is a correction of a claim I made earlier today and
withdrew.

1. **The warning time was zero, and R4 cannot manufacture warning that never existed.** The nadir
   camera's half-footprint reaches 2.48 m along-track at this encounter's 4.03 m depth, against a
   **12 m** policy threat cylinder — the sensor horizon is ~5× smaller than the horizon the policy
   is written for. Price any R4 proposal against the measured **0.175 s of lead and ~0.4 s of
   in-image dwell** (2 frames at 5 Hz), not against the 12 m cylinder, and gate it on **lead time as
   well as CPA** — a green CPA bought on 0.175 s of lead is bought by luck.
2. **Nothing in the repo gates whether an avoidance command moved the vehicle at all.** Four
   accepted dodges commanded 10 m of divert and achieved **0.018 m** of lateral displacement
   (0.054 m over the following 2 s). Across all three live flights the same measurement reads
   0.182 m (61 maneuvers), 0.418 m (19), 0.054 m (4) — every one `verdict: accepted`, every ledger
   closed. Whether this breach is an autonomy result or an ArduCopter GUIDED-acceptance / tuning
   artifact is **unknown**, and no `WPNAV_*` / `GUID_*` parameter is set anywhere in `config/`.
   Answer that before spending a session on control-law geometry.
3. **Do NOT conclude from this take that the historical reversal mechanism is superseded.** It is
   true and checkable here that R2 rejected candidate 0° — the full reversal — on all four dodges
   ("swept path clears tree by only −1.97 m"), so the escape order that produced the two ~5 cm
   strikes did not fly this time. It does **not** follow that warning time is the cause and escape
   geometry is not. That inference was drawn earlier on 2026-08-25 and **retracted the same day**:
   it generalises a single 4-tick encounter in which 0° happened to be tree-blocked, and on the two
   earlier logs 0° *was* chosen (61 and 19 maneuvers), yielding setpoints with 0.02–0.36 m of
   cross-track out of 10.00 m — half of them commanding the vehicle *forward along its own track*.
   Warning time and escape direction are **confounded across the three flights** (long warning +
   degenerate direction on 08-18/08-23; short warning + non-degenerate direction on 08-25). **No
   causal claim about the breach mechanism is supported by any flight flown to date.** Resolve it
   offline before booking a re-fly, and pair R4 with at least one of: threat persistence (one empty
   frame currently ends an encounter), sensor horizon, or flight speed.

## What already passed on this same take

Recorded so the failure is not read as a broken flight, and *not* offered as a counterweight to it:

* **Detector**: `frames_detected_on` 1301 / `ndvi_msgs_received` 1302 = **99.92 %** against a 90 %
  floor; the single loss is one `dropped_no_intrinsics` startup frame. `boxes_total` 2, `n_stale_dropped` 0.
* **R2, live for the first time**: 4 of 4 accepted dodges, swept tree clearances 1.393 / 1.756 /
  1.340 / 1.857 m, all ≥ the 1.0 m bar, with 8 candidates rejected for clearing a tree by too little.
  Flown path: 0 `is_safe_3d` violations across 1858 points.
* **Coverage ledger**: 720 covered / 0 debt, 1858 path points, 116 at-risk cells recovered across
  the 4 diverts. No cell was silently skipped by the avoidance.
* **Clock**: 0 domain violations, `gz_clock_stream`.
* **The GT-CPA gate machinery itself, first live use**: truth coverage 1858/1858 ticks, 610/610
  landed `set_pose` calls scored, the freeze debit priced from the flight's own stamps, and the
  estimator split (−0.2028 m) reported separately from the safety number. The gate did the one job
  it was built for — it produced a number that the flight could fail.

**Read the detector rate adversarially.** 99.92 % is green on top of a take where the camera had a
bird in frame on **2 of 1301 frames**. This is the second instance of the pinned lesson: gates on
VALUES cannot catch GEOMETRY. Do not narrow that floor on the strength of this take, and never quote
it as evidence the perception half is sufficient — it measured throughput, not sight.
`detected_before_closest: true` is technically earned here and operationally worthless; quote it only
with the 0.175 s attached.

## Reproducing the number (read this before you re-run the gate)

The shipped invocation on the committed tree does **not** print the breach:

```
$ python3 scripts/check_live_flight_log.py eval/results/live_flight_log_20260825T210402Z.json \
      --truth eval/results/bird_drive_20260825T210030Z_applied.jsonl
AMBIGUOUS TAKE: ... 1 OTHER applied log(s) also overlap this flight's sim-time window
(bird_drive_20260823T073836Z_applied.jsonl)  ->  INVALID, exit 1, no CPA line at all
```

Gazebo sim time restarts near 0 every run, so any two takes overlap trivially and `--truth` is not
permitted to override the ambiguity. The CPA above is reproduced by scoring this log against a
results directory containing **only this take's** `bird_drive_20260825T210030Z{,_applied}` track
(`check_file(path, truth=…, results_dir=…)`; `main()` hard-codes `RESULTS_DIR`, so the CLI cannot).
The consequence is a live one and belongs with this finding: **a schema-2 breach currently cannot be
acknowledged through CI**, which runs with no `--truth` — so the record shape for this evidence is a
`product-lead` call that must be made *before* any pin is ever considered.

### DO NOT DELETE THIS FILE, WHATEVER THE GATE TELLS YOU

Because the truth join fails above, the gate never computes a CPA, and
`breach = cpa_m is not None and cpa_m < bar` is therefore **False**. That routes it into the
stale-marker branch, which prints, on the real tree, today:

> a stale acknowledgement marker `live_flight_log_20260825T210402Z.SAFETY_FINDING.md` is present
> beside a log **that does not breach CPA**. An acknowledgement beside a passing log pre-authorises
> the next regression on this file; **delete the marker.**

**That instruction is wrong and it is the most dangerous line the gate can emit.** This log breaches
at 0.0067 m. The gate is reporting *"we could not compute a breach"* as *"there was no breach"* —
the absent-denominator failure this project has been burned by before, now attached to a remediation
that destroys the written finding beside a 6.7 mm bird strike. Filed as a safety bug (QA G55); the
fix is to make that branch reachable only when CPA was actually measured. Until it lands, an operator
who obeys the printed instruction deletes this file and the log then reads as ordinary paperwork.

## Status, unambiguously

**INVALID.** Land R4 — and resolve the warning-time / escape-direction confound above before
assuming R4 is sufficient — then re-fly. This log is not the Week-6 artifact, must never be quoted
as a green avoidance flight, and the marker beside it does not change its verdict by one bit.

Full record: `docs/runbooks/AVOIDANCE_REAL_DETECTION.md` §6 / §6a / §7 (binding at flight time);
`docs/DECISIONS.md` ADR-013 amendment 12 + addendum (the S1 class and the two historical breaches),
amendment 14 (GT-CPA is the gated number), amendment 17 (the BIRD axis of the join, HOLD as CONTEXT),
ADR-009 (the detector evidence contract) and ADR-015 (the bird geometry this take was the first to
fly). The dated ADR-013 amendment for **this** take is OWED and not yet written — this marker is
written first, beside the evidence, so the log never sits unexplained for a single day. Sibling
markers, both ACKNOWLEDGED and both historical: `live_flight_log_20260818T144711Z.SAFETY_FINDING.md`,
`live_flight_log_20260823T004031Z.SAFETY_FINDING.md`.
