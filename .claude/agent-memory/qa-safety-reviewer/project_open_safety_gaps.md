---
name: project-open-safety-gaps
description: Standing to-break list of open SwathKeeper safety gaps, ranked by consequence, current as of 2026-08-24 (through fix round 5)
metadata:
  type: project
---

Standing safety-hunt list. Recheck before any sign-off; close/append as they resolve. Scenario and
regression locations: [[reference-safety-scenario-catalog]].

**OPENED 2026-08-24 ROUND-5 VERIFICATION (the run-block ratchet round; G34 and G35 VERIFIED FIXED
and moved down. Nothing found that flips a verdict UNSAFE; the three below are ranked by what they
cost the next flight.)**
- **G36 — the NEXT take cannot be scored without moving committed evidence out of the way, and the
  runbook's own gate-1 command is the one that fails.** MEASURED on the real committed track:
  `eval/results` carries exactly ONE applied truth log (`bird_drive_20260823T073836Z_applied.jsonl`,
  sim span **110.408..263.842**) and it is COMMITTED. The next `--detect` take writes a second whose
  span overlaps (Gazebo sim time restarts near 0 every run — the checker's own docstring says so), so
  `truth_candidates` returns 2 and the gate refuses **on both invocations**: CI's (no `--truth`) with
  "ambiguous truth track", and the runbook §5 `--truth "$TRUTH"` one with `AMBIGUOUS TAKE` (round 3
  deliberately made `--truth` non-bypassing, G23). A CLEAN take reads INVALID. Probe:
  `scratchpad/qa_r5_ambiguity.py` — real track + a synthesised next take, control (old sidecar moved
  aside) scores VALID. **Fails CLOSED, so it is not a false green** — the risk is the mid-session
  pressure to weaken the guard. **How to apply:** cheapest fix is procedural and needs no code —
  §0/§5 gain "move `eval/results/bird_drive_2026082*` into a subdir before the take"; the runbook
  currently says the opposite ("Omit `--truth` and the gate auto-discovers... refusing on 0 or >1"),
  which reads as if passing `--truth` avoids it.
- **G37 (message text) — the gate's own "no acknowledgement" message is the last voice that does not
  say "not for a new flight".** `acknowledgement_problem`'s third branch
  (`scripts/check_live_flight_log.py:339-345`) leads with "If this is recorded history that cannot be
  re-flown, add both, citing the finding, **exactly as the two historical logs did**" and only then
  "if it is a new flight, the flight failed". That is the same sentence shape that made ROADMAP:127 a
  finding in round 4. ROADMAP:140-147, DECISIONS:1905-1915 and runbook §6a now all say *marker only,
  do NOT add the pin, stand INVALID*; the failure message the operator actually reads at that moment
  does not. Bounded by the pin being a reviewed diff, so it cannot silently flip a verdict — but this
  is a SOLO project and the reviewer is the pilot. One clause, when the file is next open.
- **G38 (public claim) — `README.md` is the front door and it is stale in the unsafe direction.**
  Untouched since 2026-08-21 (`git log -1 -- README.md` = f97a1e2). Line 41-42 sells the avoidance
  loop as "demonstrated live... the dodge setpoint 3D-vetted" with **no mention that both historical
  avoidance flights breached bird clearance at ~5 cm** and are ACKNOWLEDGED SAFETY FINDINGS in CI;
  line 49 claims "279 green, 2 skipped — 248 in tests/fieldguard_planning" against a measured
  877/2 + 822 + 57; lines 39-40 still call ADR-003's deciding clip "a synthetic stand-in, the
  real-render re-run is next" after criterion 3 CLOSED/ADOPT (committed 859c1fd). Not a gate, so not
  verdict-flipping — but it is the one file a hiring manager reads, and "the honesty is the product"
  is a line on the same page.

**OPENED 2026-08-24 ROUND-4 VERIFICATION (the acknowledgement ratchet round; G30 and G32 VERIFIED
FIXED and moved down; G34/G35 now CLOSED by round 5 — see below).**
- **G34 [CLOSED round 5, VERIFIED — see the round-5 block] — the two-half ratchet guards the ACKNOWLEDGEMENT, not the GATE SELECTION: deleting the
  `run` key downgrades a truth-gated flight to the legacy detection-referenced path, and the result
  is VALID/exit 0 — stronger than the ACKNOWLEDGED the old marker bought, for a cheaper edit.**
  `run_block_problem` returns None when `run` is ABSENT (`scripts/check_live_flight_log.py:388`);
  round 3 closed `schema_version: 1` and an unreadable version, not the missing key. PROVEN on one
  artifact: a real-detector flight driven through a bird whose detector missed at CPA reads
  `gt_cpa_m 0.0000 m / CPA BREACH / INVALID / exit 1` as schema 2 and
  `CPA NO-CPA-EVIDENCE ... VALID / exit 0` with `del log["run"]` and nothing else changed. It is
  PINNED as intended behaviour by `test_a_log_with_no_run_block_takes_the_legacy_path_untouched`
  (test_check_live_flight_log_schema2.py:248), so closing it means changing that test.
  **RE-PROVEN 2026-08-24 at the session's final gate**, on a synthesised schema-2 log scored against
  a driven truth track: `gt_cpa_m 0.0000 m -> INVALID` with the `run` block, `VALID / CPA
  NO-CPA-EVIDENCE / exit 0` after `del log["run"]` and nothing else. So the honest answer to "can a
  new strike still reach green CI" is: NOT via a marker file (closed), YES via the selector.
  **Realizability: deliberate edit only** — the repo is bind-mounted into the container
  (`sim_docker_run.sh:21`), so the node is always the working tree and always writes `run`; a stale
  image fails `--detect` closed with `return 2`. **How to apply:** the lazy-elite close reuses the
  allowlist already there — both pinned stems ARE the only legacy logs (verified), so "a log with no
  `run` block is INVALID unless its stem is in `ACKNOWLEDGED_BREACH_STEMS`" is one condition and
  costs the two historical logs nothing. Do it when the checker is next opened, not as a band-aid.
  **CLOSED AND INDEPENDENTLY VERIFIED 2026-08-24 (round 5).** `run_block_problem(log, path)` now
  refuses any unpinned log with no `run` block. My probe, on fixtures I built (node's own
  `build_run_block`, a driven truth track, bird 5 cm from the drone, ZERO detections logged):
  schema 2 -> `CPA BREACH / INVALID`; `del log["run"]` -> `INVALID`, messages exactly
  `[headline, refusal]` (it never scores the weaker metric), `main()` exit 1. Rebinding
  `run_block_problem` to the pre-fix rule on the SAME bytes reproduces `VALID / CPA
  NO-CPA-EVIDENCE` — the fix is load-bearing. Three unpinned no-run names all INVALID; both
  historical logs byte-identical (stdout AND stderr, 4 invocations incl. the default glob) against
  the **pre-session HEAD** checker, exit 0 ACKNOWLEDGED; scenario fixtures 3 INVALID + 1 VALID,
  exit 1; regenerating them is a byte no-op so CI's regenerate+diff stays green; the literal CI
  evidence step in a POST-COMMIT tree prints `matched: 2` and exits 0. Known and accepted by design:
  the stem pin is unanchored (a file NAMED `live_flight_log_20260818T144711Z.json` anywhere takes
  legacy) and the fixture pin is by SHAPE (any `eval/scenarios/<anything>/flight_log.json`) — both
  deliberate-edit-only, and CI never points the checker at `eval/scenarios/`.
- **G35 (doc) [CLOSED round 5] — the dangerous ROADMAP sentence is gone.** ROADMAP:140-147 now reads
  "write the marker ... and **do NOT add the pin** ... the take **stands at INVALID / exit 1**", which
  agrees with runbook §6a and DECISIONS:1905. DECISIONS am. 17 residual 4 and 6 are marked CLOSED and
  the "Still OWED" runbook line is now "LANDED"; the suite figures in ROADMAP:56-61 match the measured
  877/2 + 822 + 57. **Residual, and it is the same shape as the original defect: the doc-drift
  tripwire is STILL ONE FILE DEEP** — `test_the_runbook_tells_the_operator_about_BOTH_halves`
  (test_check_live_flight_log.py:468) greps only `AVOIDANCE_REAL_DETECTION.md`, so ROADMAP was fixed
  by hand twice and is pinned by nothing. Cheapest close: add ROADMAP to that same test's file list
  (assert it names `ACKNOWLEDGED_BREACH_STEMS` and does NOT contain "exactly as the two historical
  logs did"). See also G37 — the gate's own message still carries that phrase.
  Historical detail, kept:
  What the doc pass fixed: `DECISIONS.md:2486-2491` now records the two-step contract by name
  (`ACKNOWLEDGED_BREACH_STEMS`), and ROADMAP:49-52 now says the amendments **are written**.
  **What survives, ranked:**
  * **`ROADMAP.md:127-128` — the operator-facing instruction that reopens the hole.** "a breaching
    flight is INVALID and gets a `SAFETY_FINDING.md` marker citing the finding, **exactly as the two
    historical logs did**". The two historical logs have BOTH halves, so "exactly as" now literally
    prescribes adding the pin — a green CI on a new bird strike, self-authored, in the doc CLAUDE.md
    calls current truth. Runbook §6a says the opposite ("write the marker, do NOT add the pin, let
    it stand INVALID") and the gate's own failure text says "THE FLIGHT FAILED". Three documents,
    three instructions, one moment. **This is the only doc line that can flip a CI verdict.**
  * `DECISIONS.md:2496` says the runbook §6 row is "Still OWED" — it was updated 23 min BEFORE that
    sentence was written (§6 + new §6a), and the code round's own
    `test_the_runbook_tells_the_operator_about_BOTH_halves` proves it. `DECISIONS.md:2529`
    residual 4 still says the hold line "has no denominator and disappears silently" — it has one
    and it does not. FOURTH round the ADR log describes the pre-fix gate.
  * `DECISIONS.md:1899` "a breaching NEW flight ... does NOT get a `SAFETY_FINDING.md` marker" vs
    runbook §6a "write the marker". Same verdict either way, so cosmetic — but it is the third
    different instruction.
  * ROADMAP:123 + 158-159 still say the amendments are owed and "DECISIONS.md stops at 2026-08-23",
    contradicting ROADMAP:49-52 inside the same file; ROADMAP:121-123 still lists the four round-3
    findings as "the remaining precondition" (all four fixed); ROADMAP:54-57 quotes 860/2 + 805
    (measured now: 870/2 + 815 + 57).
  **How to apply:** the doc-drift tripwire the round shipped is ONE FILE DEEP (it greps only
  `AVOIDANCE_REAL_DETECTION.md`). Widen it to ROADMAP + DECISIONS, or the fifth round inherits this.

**CLOSED 2026-08-24 ROUND-4 VERIFICATION (independent probes; pre-fix reconstructed by monkeypatching
`acknowledgement_problem` back to marker-only, so the comparison isolates the one changed function —
no shadow repo, no symlinks into the working tree)**
- **G30 (marker ratchet) — CLOSED, on BOTH paths.** Acknowledging now needs the marker AND the stem
  in `ACKNOWLEDGED_BREACH_STEMS`. Probes: the REAL 2026-08-23 breaching log copied to
  `live_flight_log_20260901T120000Z.json` + a marker -> INVALID/exit 1 naming the unpinned stem
  ("HALF an acknowledgement ... THE FLIGHT FAILED"); pin without marker -> INVALID ("is MISSING");
  neither -> INVALID naming both; both -> ACKNOWLEDGED, never VALID; both + a broken clock ->
  INVALID ("NOT acknowledgeable"). Same five on a synthesised schema-2 breach scored against a
  driven truth track. PRE-FIX on identical evidence: ACKNOWLEDGED / exit 0 — the hole reproduced on
  both paths. Historical logs BYTE-IDENTICAL (stdout AND stderr, all three invocations incl. the
  default glob), exit 0. Allowlist is exactly the two stems and its contents are pinned by a test.
  Residual: **G34** (the selection layer, not the acknowledgement layer).
- **G32 (hold line) — CLOSED.** `holds with a threat=N of M hold(s) [CONTEXT, NEVER GATED]` prints on
  every schema-2 log including `0 of 0` (verified end-to-end on a VALID log). A hold event missing
  the `bird_clearance_m` KEY is a hard problem naming count + first tick, and it fails the whole log;
  a None VALUE is correctly NOT drift (`_handle_hold` writes None when the decision names no threat,
  and `_log` preserves None kwargs verbatim — checked, so the rule cannot false-positive a real
  flight). Un-caught residual, minor: a WRONG-TYPE `bird_clearance_m` (string/dict) reads as "named
  no threat" and degrades to the honest `0 of M` branch rather than to drift — unmeasured, not green.
  **That residual is CLOSED round 5 and verified**: drift is now *absent KEY* **or** *present-but-
  unusable value*. Probed all five flavours (`"n/a"`, `{}`, `[1.0]`, `True`, key absent) -> INVALID
  "carry no USABLE bird_clearance_m", first tick named; an explicit `None` still VALID with
  `holds with a threat=1 of 2` printed, so it cannot false-positive a real flight
  (`_handle_hold` writes None when the decision names no threat).

**OPENED 2026-08-24 ROUND-3 VERIFICATION (adversarial re-run of the round-3 fixes; G25-G29 all
VERIFIED FIXED and moved down). New, ranked by consequence.**
- **G30 [CLOSED round 4 — see the round-4 block above] — a marker turns a NEW bird strike into a green CI, and nothing bounds the marker set.**
  `check_live_flight_log.main()` returns **0** for ACKNOWLEDGED, and the runbook
  (`AVOIDANCE_REAL_DETECTION.md` §6, "INVALID — `gt_cpa_m` breach") instructs the operator to add
  `<log-stem>.SAFETY_FINDING.md` to a breaching flight. R4 is open and the runbook *pre-registers*
  the next take as possibly breaching — so the documented remedy for a red CI is to make it green.
  Nothing anywhere asserts WHICH logs may be acknowledged: `grep -rn "n_acknowledged\|PASS WITH"
  tests/` returns nothing, and `git ls-files 'eval/results/*SAFETY_FINDING*'` is exactly 2 files
  (2026-08-18, 2026-08-23), both dated before today. **How to apply:** the cheap in-doctrine fix is a
  test pinning the acknowledged SET (two stems, both historical), so a third requires a deliberate
  edit with a reason. Do this BEFORE the first `--detect` take, not after it comes back breaching.
- **G31 — the clock gate's FALSE-POSITIVE rate is unmeasured, and a clock fault is
  un-acknowledgeable.** The freeze debit now crosses the whole 3.00 m bar at
  `3.00 / 7.0043 = 0.4286 s` of hidden sim time. `_gz_now` is fed by a `gz topic -e -t /clock`
  subprocess reader thread on a box this project has twice documented starving; a ~0.43 s sim
  (~0.71 s wall at RTF 0.605) reader stall makes the whole take a hard `gate_clock` INVALID that NO
  marker can acknowledge. Measured in the composition probe: 295 of 300 randomised 2-5 tick freezes
  became hard clock faults. This is the CORRECT conservative call (an unmeasured flight is not a
  safe flight) — the gap is that nobody has priced how often it fires on a healthy take, and it is
  not in the runbook's §6 booking table (only in §5 prose). **How to apply:** before booking, read
  `clock_block(readings=...)` from a dry run and count identical consecutive stamps at 5 Hz; add the
  freeze fault as its own row in the §6 table (procedural → cheapest re-fly).
- **G32 [CLOSED round 4 — see the round-4 block above] — the HOLD clearance line has no denominator and vanishes silently when empty.**
  `gate_r2_r3` prints `holds with a threat=N min hold-tick bird clearance X m [CONTEXT, NEVER
  GATED]` only `if hold_gaps:` — 50 hold events carrying no `bird_clearance_m` produce **no note and
  no problem** (verified). The reject path has a drift catch for exactly this (an unexplained
  `gate_reject` is a hard problem); the hold path has none, and there is no "N of M holds" ratio, so
  1-of-1 reads the same as 1-of-200. It cannot flip a verdict — but it is the one number that will
  quantify R4's gap on the first `--detect` take, and R4 is the open big one. **How to apply:**
  open item, not a blocker. Executor-side tests do pin the field, so only a checker-side regression
  is silent.
- **G33 [STILL OPEN after round 4 in a new form — see G35; the CONTROL_HZ/frozen_span_s/
  MAX_FROZEN_TICKS half IS fixed, all remaining hits are fix-record lines] — `docs/DECISIONS.md` is stale on the gate AGAIN, one round later; the doc/test
  contradiction moved rather than closed.** The round-2 `MAX_FROZEN_TICKS` lines are gone (good),
  but am. 15 now describes deleted code and prescribes unimplemented fixes: L2028
  `frozen_span_s = (N−1)/CONTROL_HZ`, L2035 `gt_cpa_gated_m −2.8034 m` (that print was replaced by
  `NOT COMPUTED`), L2151 `max(1/CONTROL_HZ, span_s/advanced)` — while
  `test_check_live_flight_log_schema2.py:488-490` asserts `MAX_FROZEN_TICKS`, `CONTROL_HZ =` and
  `frozen_span_s` are ABSENT from the checker. L2110-2158 still lists residuals 1-5 as "still
  standing" (all fixed this round) and L1852 says the `gate_reject` fields "are not yet gated" (R3.8
  gates them). **How to apply:** this is the SECOND round the ADR log has gone stale on the same
  gate — treat "amend the ADR" as part of the fix, not as follow-up.

**CLOSED 2026-08-24 ROUND-3 VERIFICATION (each re-proved by an independent probe against the FIXED
code, plus a mechanical back-out confirming the new tests go red pre-fix)**
- **G27 (bird-axis CPA)** — `pose_windows` + pass 2. My probe: hovering drone, bird driven through it
  at 7.0 m/s, driver at its measured 0.543 s cadence. At 1.00 s/tick phase 0.5 the pass-1-only
  (pre-fix) join reports **3.8010 m VALID**; the fixed join reports **0.0000 m BREACH** via
  `pose_window`. Lower bound re-falsified: 300 randomised trials + 200 three-bird interleaved-window
  trials against a densely sampled independent model = **0 over-reports**. On the real committed
  839-pose track the fix scores 838-839/839 at every cadence 0.121→1.00 s/tick (0.07 s runtime),
  where a tick-only pass would have missed 0.0 / 0.1 / 3.3 / 9.4 / 30.0 / 42.4 %.
- **G28 (freeze debit at a nominal rate)** — priced off the flight's own stamps. dt 0.50 s, 3-tick
  freeze: pre-fix 0.400 s → 2.8017 m (sub-bar, PASS); fixed 1.500 s → **10.5065 m → hard clock
  fault**. The WORST run is priced, not the longest (5-tick run hiding 0.2 s loses to a 2-tick run
  hiding 2.0 s). A debit at/over the bar now prints `gt_cpa_gated_m NOT COMPUTED` instead of a
  negative separation. `CONTROL_HZ`/`frozen_span_s`/`MAX_FROZEN_TICKS`: zero hits in the checker.
- **G25 (unvetted HOLD)** — fixed by HONESTY, not by R4, which is the right call. Every hold now logs
  `bird_clearance_m`/`bird_track_id`/`min_bird_clearance_m` (10,000-tick sweep: 2597/2597 holds
  carried the number, 332 inside the bar, closest **0.029 m**). The finding's geometry now logs
  reject 1.000 m and hold **0.400 m** on the events that made them. The reject reason no longer says
  "falling back to HOLD"; guarantee 1 is renamed "Never fly an unvetted DISPLACEMENT" with an
  explicit HOLD-IS-EXEMPT paragraph. Residual: **G32**.
- **G26 (R3.7 unreachable)** — R3.8 now reads the `gate_reject` events and reports
  `gate_rejects=N (bird-bar rejects=B, closest refused point X m from a bird)`; an unexplained reject
  (no `obstacle_id`, no sub-bar gap) is a hard problem, verified firing. R3.7 is restated as the
  exhaustion property and IS still reachable on a current-executor log via the documented fail-open
  path (a maneuver whose `debug` carries no `params` gets no bird check, is COMMANDED, and R3.7
  catches it — verified live). The policy always writes `params`, so on a real flight it stays
  defence-in-depth. Correct layering: executor fails OPEN on missing data, gate fails CLOSED.
- **G29 (CI CPA gate vacuous) — PREMISE WAS WRONG, and the real defect is fixed.** `.gitignore:48`
  re-includes `!eval/results/live_flight_log_*.json`; `git archive HEAD` into a clean tree + the
  literal ci.yml command matched **2** files and reported both ACKNOWLEDGED breaches, exit 0. So the
  gate has been running on real evidence every push since 2026-08-23. What WAS real: the step
  asserted no denominator. Fixed — pre-fix step body in an evidence-free tree prints
  `SKIP … PASS` and exits **0**; post-fix prints `matched: 0` and exits **1** (both run). The three
  breaching `eval/scenarios/*/flight_log.json` are correctly scoped OUT: all four fixtures are
  open-loop (`flown_path_enu` == `nominal_path()`, verified), regeneration is deterministic (3 runs
  byte-identical) and left all four CPA numbers unchanged (0.0000 / 7.0000 / 1.0000 / 1.0000 m).
  **The regenerated fixtures MUST be committed with the src/ changes or CI's regenerate+diff goes
  red on the first push.** See also **G12** (same files) and ADR-013 am. 16.

**OPENED 2026-08-24 ROUND 3 (adversarial verification of the round-2 fixes; G19-G24 all VERIFIED
FIXED and moved to history below). ALL FIVE NOW FIXED — see the round-3 verification block above.
Every one PROVEN with a probe against the fixed code.**
- **G25 — the R3 refusal's fall-through to HOLD commands a point NOBODY vets, and it can be closer
  to the bird than the point it just refused.** The round-2 fix added a bird half to the executor's
  backstop for the DIVERT candidate — but `_handle_hold` still calls
  `sink.send_setpoint_enu(drone_state.position_enu)` with neither half applied. In the R3-refusal
  branch `range_degenerate` is True, i.e. the drone is within `degenerate_range_m` (1.0 m) of the
  trigger bird BY CONSTRUCTION, so the HOLD is always inside the 3.00 m bar. Proven: refusal rejects
  a latch **1.000 m** from the bird and then commands **0.400 m**. Randomised sweep of 400 encounters
  x 25 ticks: **41 HOLD ticks commanded a point inside the bar, closest 0.288 m**, gated by nothing.
  The new guarantee-1 docstring ("Every point this module is about to command is re-vetted ...
  against BOTH halves") is false as written. `gt_cpa_m` still catches the flown proximity, so the
  artifact is not blind at the headline — the per-decision layer is.
- **G26 — R3.7 cannot fire on a log the current executor produced.** Same sweep, same 10,000 ticks,
  22 R3 refusals: **0** maneuver events commanding inside the bar, because `bird_reject` removes the
  `maneuver` event and writes a `gate_reject` instead — and `check_live_flight_log.py` never reads
  `gate_reject.bird_clearance_m` (grep it). So R3.7 is a REPLAY/defence-in-depth assertion for older
  or hand-edited logs, not the live half of the executor catch its docstring implies. All three
  R3.7 tests use hand-built `maneuver_event` fixtures; the one real-flight test mutates the log
  first. **How to apply:** state R3.7's scope, and gate the `gate_reject` fields the executor now
  writes — that is where the evidence moved.
- **G27 — `gt_cpa_m` scores the bird only at TICK instants, so a landed `set_pose` call whose whole
  in-effect window falls between two ticks is never scored — and `truth coverage` still reads
  100 %.** PROVEN false PASS with a HEALTHY clock, 0 violations, no freeze, 24/24 coverage: at a
  control-tick sim cadence of 0.70 s with the driver at its measured 1.84 calls/s/bird, the gate
  reports **`gt_cpa_m 3.8067 m` VALID** on an encounter where the bird was driven to **0.0000 m** —
  straight through the drone. Against the committed applied log (839 landed poses): 0.1 % of poses
  unscored at 0.331 s/tick, 3.2 % at 0.5 s, 9.3 % at 0.6 s, **29.6 % at 0.8 s** — the artifact
  prints `truth coverage 191/191 ticks` in every one. Today's margin is real (5 Hz wall x measured
  RTF 0.605 = 0.121 s sim/tick vs the 0.543 s driver interval, 4.5x) but unmeasured and unreported.
  **How to apply:** the honest fix is a second denominator (`truth_poses_scored K/N`), or score each
  landed call against the drone polyline over ITS in-effect window so the tick grid stops mattering.
- **G28 — the freeze debit is priced at the NOMINAL 5 Hz control rate, not the flight's own.**
  `frozen_span_s = (N-1)/CONTROL_HZ`. That is an upper bound only while the loop actually ticks at
  5 Hz wall; a starved loop makes it an UNDER-count. Measured: at 0.5 sim-s/tick a 3-tick freeze
  hides 1.00 s = 7.004 m of bird motion and the gate prices 0.400 s = 2.802 m (2.5x under). The
  derivation comment states the RTF>1 caveat but not the starved-loop one, which is the likelier
  half on this box — and the two failures are CORRELATED (a node sick enough to freeze its clock
  reader is a node that may be starved). `stamp_advance` already has `span_s`/`advanced`, so the
  measured mean sim-step is one division away and is never printed.
- **G29 — three of the four committed `eval/scenarios/*/flight_log.json` are in CPA breach and
  nothing runs the gate on them.** PRE-EXISTING at HEAD, not this round: `cov_bird_over_cell`
  **0.0000 m**, `cov_two_birds_simultaneous` **1.0000 m**, `geo_avoid_into_tree` **1.0000 m** (bar
  3.00 m); only `cov_bird_at_turnaround` passes at 7.0000 m. `.github/workflows/ci.yml:90` points
  the checker at `eval/results/*flight_log*.json`, which is gitignored — so in CI the glob matches
  nothing and the R1 CPA gate is vacuous. This is collected R4 escape-geometry evidence sitting
  unread. See also [[project-open-safety-gaps]] G12 (same files, stale margin).

**CLOSED 2026-08-24 ROUND 3 (verified by independent probe against the fixed code, not by
re-running the fix author's tests)**
- **G19 (frozen clock)** — `MAX_FROZEN_TICKS` deleted; `freeze_debit_m = frozen_span_s x
  max_bird_speed_m_s()` is subtracted from `gt_cpa_m` before the bar, and a debit >= the bar is a
  hard `gate_clock` fault (>= 4 ticks today). Probe: 5-tick freeze pre-fix printed a bare note,
  post-fix debits 5.6034 m and FAILS as a CLOCK fault. Residual: **G28**.
- **G20 (silent staleness kill)** — `_stale_detail` writes the drops onto proceed/hold;
  `gate_detector_ran` fails "drops > 0 AND 0 engagements". Probe (20 all-stale ticks through the
  real policy+executor): pre-fix `stale_dropped_total` **0** and no problem — and the note printed
  the WRONG honest diagnosis; post-fix **20** and `AVOIDANCE WAS DEAD`.
- **G21 (R3 commanding an unvetted point)** — executor bird backstop + R3.7. The 1.000 m command is
  gone. Residual: **G25**, **G26**.
- **G22 (vertex-sampled CPA)** — `_point_segment_xy_m` + both bounding segments. Hand case: the
  finding's 3.0008 m PASS is now **2.8200 m** BREACH. 300 randomised trials (tick dt 0.2-0.5 s,
  bird teleport 1.9-5.0 Hz) against a densely-sampled independent model: **0** over-reports.
  Residual on the BIRD axis only: **G27**.
- **G23 (`--truth` bypass)** — `truth_candidates` runs unconditionally; the two-overlapping-log
  probe now returns `AMBIGUOUS TAKE` naming the sibling. Pre-fix the same probe scored VALID at
  `answered_from_spawn 2/3`.
- **G24 (detector zero-check)** — `MIN_DETECT_RATE = 0.90` on `frames_detected_on /
  ndvi_msgs_received`. 1/1256 was VALID, is now `DETECTOR BARELY RAN`. Boundary nit: 1130/1256
  fails while PRINTING "90.0% (floor 90%)" — the raw counts are in the same line, so it is legible,
  but the sentence reads as self-contradictory.

**OPENED 2026-08-24 ROUND 2 — ALL SIX FIXED AND VERIFIED, kept for the pattern only**
- **G19 — `MAX_FROZEN_TICKS = 5` is sized against the WRONG denominator, and the residual is bigger
  than the bar it protects.** The bound was justified as "0.8 s, inside the 1.0 s ADR-009 staleness
  bound" — but a frozen `run.tick_stamp_sim_s` harms the TRUTH JOIN, whose scale is BIRD SPEED
  (bird_1 = 7.0 m/s → 5.6 m in 0.8 s, ~1.9x the 3.0 m clearance bar). Proven: a 5-tick freeze
  (`longest_frozen_run 5`, `gate_clock` problems **0**) turns a true **0.0000 m** strike into
  `gt_cpa_m 3.5000 m PASS` at truth coverage 45/45. **How to apply:** the G15 fix closed the
  all-frozen case and left a 0.8 s window that is strictly worse than the bar. Bound it by
  `min_bird_clearance_m / closing_speed` (~0.2 s → one repeat), or subtract
  `frozen_span x max_bird_speed` from `gt_cpa_m` before comparing.
- **G20 — the staleness gate can silently disable avoidance for a WHOLE flight, and
  `n_stale_dropped` reads 0 exactly then.** `n_stale_dropped` lives in `maneuver.debug`, but the
  executor copies `debug` only into ACCEPTED-DIVERT `maneuver` events; `_handle_proceed` logs a bare
  `proceed` event. All-stale → PROCEED → no detection event, no maneuver event, `n_stale_dropped=0`.
  Proven: 20 in-cylinder ticks, fresh → 20 detection + 20 maneuver events; every frame expired → 0
  and 0, `stale_dropped_total()` **0 in both**. `stale_dropped_total`'s own docstring claims the
  artifact can tell "every detection expired" from "no bird was ever seen"; it cannot. Runbook §6
  even mis-attributes the resulting vacuous pass to "a cadence/phase miss, not a code fault".
- **G21 — R3's re-latch refusal commands a setpoint the policy's own bird-clearance guarantee
  forbids.** The executor re-vet is `geofence.is_safe_3d` (trees/altitude only — and G3 says it
  cannot fire at cruise); nothing ever re-checks `min_bird_clearance_m`. Proven through the real
  policy+executor: refusal commanded a point **1.000 m** from the bird while the policy's fresh
  setpoint was **10.400 m** clear (bar 3.00 m). Pre-R3 that tick would have RE-LATCHED onto the
  bird-vetted point, so R3 adds a path where a safe alternative existed and was declined. The new
  `avoidance_executor.py` docstring "It cannot make anything less safe" cites guarantee 1
  (geofence), not guarantee 4 (bird clearance). **How to apply:** on a refusal, prefer HOLD when the
  latched point is inside `min_bird_clearance_m` of a current in-cylinder threat.
- **G22 — `gt_cpa_m` is a minimum over 5 Hz VERTICES, not over the flown path.** It never evaluates
  the drone between logged positions, nor (drone at tick i, bird at its POST-teleport pose). Drone
  step measured on the real 2026-08-23 log: p50 0.747 / p95 1.892 / **max 2.052 m**; bird teleport
  3.16 m (6 m/s at the measured ~1.9 Hz/bird driver rate). Proven false PASS with a HEALTHY clock:
  gate `3.0500 m PASS` vs true continuous `2.6332 m` BREACH, coverage 4/4, spawn 0. Fix is ~8 stdlib
  lines: point-to-SEGMENT over consecutive `flown_path_enu` pairs.
- **G23 — `--truth` bypasses the "exactly one overlapping candidate" guard entirely**
  (`resolve_truth` never calls `truth_candidates` when `truth_arg` is given), and the runbook makes
  that the default path: §5 `TRUTH=$(ls -t eval/results/bird_drive_*_applied.jsonl | head -1)`.
  §1 documents `scripts/fly_pipeline.sh birds` (a `tmux respawn-window -k`) as a manual override,
  which produces a SECOND applied log for one flight; `ls -t` then picks the tail-only one and the
  first half of the flight is answered from bird SPAWN poses. Reported as `answered_from_spawn K/M`,
  never gated, and no sibling log is even mentioned. bird_0 spawns at (15, 5, 11) — 4 m below cruise
  and under mission lane x=15 — so this both fabricates and hides breaches.
- **G24 (minor) — `gate_detector_ran` is a zero-check, not a rate check.** `frames_detected_on == 0`
  is a hard INVALID but `1 of 1256` passes. ADR-013 am. 4's precedent is an evidence FLOOR; the
  natural shape here is `frames_detected_on / ndvi_msgs_received`.

**CLOSED 2026-08-24 (kept as history, do not re-open without evidence)**
- **G15/G16/G17/G18 — all closed and re-verified this session.** Frozen axis: `gate_clock` now
  requires the stamp axis to advance (but see **G19** for the residual). Detector never ran:
  `gate_detector_ran` makes `frames_detected_on == 0` a hard INVALID (but see **G24**). Invented
  spawn bird: `TruthTrack.unobserved_bird_ids` + `BirdTruth.from_spawn`, unobserved birds omitted
  and named (but see **G23** for the wrong-log variant that survives). Staleness floor:
  `PolicyParams.max_detection_age_s` is 1.0 with ONE home, `avoidance_node.MAX_DETECTION_AGE_S`
  deleted, and `gate_staleness`'s upper branch is live (but see **G20**).
- **G1 — nothing measures ACHIEVED separation.** Closed twice over: R1 put detection-CPA in
  `check_live_flight_log.py` (2026-08-23), and the schema-2 gate now measures CPA against the bird
  GROUND-TRUTH track for real-detector flights. The 0.0518 m / 0.0597 m historical breaches stand,
  ACKNOWLEDGED by their markers. **The control-law half is NOT fixed — see G4' below.**
- **G2 — zero tree margin.** `lateral_tree_margin_m` 0.0 -> 1.0, one home in `PolicyParams`, read
  by the gate from that same dataclass. Priced: HOLD 5.64 % -> 15.66 % on an 11,856-case sweep.
- **G4 (half) — degenerate-range re-latch.** R3 refuses a RE-LATCH below `degenerate_range_m` 1.0.

**G4' — R4 IS THE OPEN ONE, AND IT IS THE BIG ONE.** The escape geometry is unchanged: 18 of 19
replayed ticks still take candidate 0 deg (straight reversal), the escape ownship momentum forbids.
R2/R3 do not touch it. **How to apply:** the next avoidance flight may honestly FAIL its own GT-CPA
gate; that is a pre-registered measurement ranking R4 next, not a wasted take. A breaching new
flight is INVALID and needs a `SAFETY_FINDING.md` marker citing the finding.

**G3 — `is_safe_3d` cannot fire in the flown configuration.** Every v1 setpoint is pinned to
`cruise_alt_m` 15.0; the tallest tree volume tops out at 4.8 m; `alt_bounds` is (2, 30). Gate 1 AND
the executor's ADR-006 backstop return True for every XY, including a trunk. "0 gate_reject events"
means *could not fire*, not *nothing was wrong*. **How to apply:** treat any descent feature as
re-arming an untested gate, not reusing a proven one.

**G5 — no independent geofence backstop, and the mission rides the boundary.** No ArduPilot
`FENCE_*` parameter is set anywhere, so the ONLY boundary protection is policy setpoint containment.
Mission lanes x=0/x=75 lie ON the field polygon; 118 of 984 flown points in the 2026-08-23 log were
outside it (worst 0.073 m). Accepted dodges stay inside only because the polygon is CONVEX (the vet
checks the setpoint, never the swept path).

**G8 — the R2 gate's scope is narrower than its name.** It asserts the clearance the POLICY vetted
on each accepted tick. The LATCHED point's swept path is never re-vetted as ownship moves (the
executor re-vets the POINT via `is_safe_3d`, which G3 says cannot fire). Named deferral, not a
claim — stated in the gate's own docstring.

**G9 — a FIRST latch at degenerate range is still permitted.** R3 was scoped to re-latch by
ADR-013 am. 12, because refusing the first latch would mean not dodging at all. So the first
commanded dodge of an encounter can still be built from an away-vector whose direction is noise.

**G10 — separation over an UNTRUTHED window is unmeasured, and only partly gated.** The schema-2
gate fails a flight whose *encounter* ticks lack ground truth, and prints
`truth coverage N/M ticks` always — but a flight with, say, 40 % coverage and no events in the gap
still scores VALID. If the driver dies mid-flight, the quiet window is not clean, it is unmeasured.
**How to apply:** read the coverage rate before believing a green GT-CPA.

**G11 — the missed-detection signal is reported, never gated.** The gate prints "bird truly inside
the threat cylinder on N tick(s); the loop engaged on M of them". It is deliberately not a gate: a
bird BEHIND the drone is invisible to a forward-facing camera, so gating it would measure geometry.
**How to apply:** a large N-minus-M on the first real-detector flight is the FNR finding, and it
will only be visible if someone reads that line.

**G12 — `eval/scenarios/*/flight_log.json` were generated at `lateral_tree_margin_m` 0.0.** Nothing
regenerates or diffs them, and the legacy path keeps them VALID. They describe the OLD control law
and must not be quoted as current behaviour.

**G13 — PRICED 2026-08-24, and it is bookable.** The phantom-dodge rate over the am.7 clip is
**8/1256 frames (0.64 %), 8/645 airborne (1.24 %)**, in ~3 clusters. But 3 of those 8 are `bird_1`
LIFTED into the ±6 m cylinder by the 0.15 m radius prior: under-ranging is conservative for range
and NOT conservative for the cylinder test, because it shrinks |dz| too. -0.61 stays PROVISIONAL
(7 FP at n=20); lifting it needs the FP characterisation.

**G15 — a FROZEN gz clock turns a real CPA breach into a pass, and nothing checks that
`tick_stamp_sim_s` advances.** Proven 2026-08-24 on one flown path + the real committed truth
track: frozen stamps -> VALID `gt_cpa_m 3.4490 m`; advancing stamps -> INVALID breach
`2.0402 m`. Truth coverage reads **200/200 either way**. `run.clock` still says
`gz_clock_stream / readings 5000 / violations 0`. The clock-domain tripwire only fires when a
detection exists during the freeze (8/1256 frames), so the freeze is silent ~99 % of the time.
**How to apply:** never accept a green `gt_cpa_m` without checking the stamp axis moved.

**G16 — a flight where the detector never ran scores VALID and the gate says nothing.**
`run.detector.counters` (`frames_detected_on`, `dropped_no_intrinsics`, `dropped_no_pose_pair`,
`dropped_stale_pose_pair`) is written by the node and read by NOTHING. Proven: a log with
`dropped_no_intrinsics: 1200 / frames_detected_on: 0` -> VALID. The node refuses to start without a
gz clock but NOT without `/fg/ndvi/camera_info`. R2/R3 say `PASS (vacuous)`; the detector has no
such sentence. **This is the newest vacuous-green and it sits on the take's headline claim.**

**G17 — `TruthTrack.candidates_at` fabricates spawn-pose truth unconditionally and counts it as
coverage.** `unknown_bird_ids` is a ONE-DIRECTIONAL set difference (timeline − config), so a bird
the truth log never drove is silently pinned at its config spawn pose for the whole flight. Proven
twice: bird_0 with zero landed calls -> `truth coverage 200/200`, fabricated `gt_cpa_m 0.0000`; and
100 ticks entirely BEFORE the track's first landed call -> `ticks_with_truth 100/100`. **bird_0 is
the ONLY bird the ±6 m vertical scoping ever gates** (z=11 vs cruise 15; bird_1 |dz|=7, bird_2
|dz|=9), so it is exactly the bird whose fabrication decides every verdict. The "exactly one
overlapping candidate" guard fails precisely when this session's driver wrote no log.

**G18 — the ADR-009 staleness bound has no enforceable floor.** `PolicyParams.max_detection_age_s`
is still `None`; the flown 1.0 s lives in `avoidance_node.MAX_DETECTION_AGE_S`. So
`gate_staleness`'s upper-bound branch is DEAD CODE — proven: a log flown at 3600.0 s scores VALID.
The gate only asserts "is a number". One-knob-two-homes, the exact drift the R2 `**params`
restructure was done to make impossible. Fix is one line in `PolicyParams`.

**G14 — the detector's border trim biases range the un-conservative way.** `close_iter >= 1` erodes
with `border_value=0`, so a bird straddling the frame edge is measured 1 px small and the
apparent-size ray reads it ~2-5 % FARTHER than it is (the 0.15 m radius prior biases the other way).
Small, one-sided, worth one line in the ADR beside the prior.

**v1 bar reminder (ADR-002):** coverage debt > 0 is ALLOWED — but every dropped cell must be
EXPLICIT in the ledger, never absent. `debt_count == 0` is a separate stretch assertion.
