---
name: project-open-safety-gaps
description: Standing to-break list of open SwathKeeper safety gaps, ranked by consequence, current as of 2026-08-26 (G43-G55 breaching take; G56-G60 + G74 CLOSED; G61-G73 point-mass replay; G75 stale published CPA figures after the segment back-port; G76 the criterion-2 RGB study's ADOPT gap is not reproducible from the committed detections_rgb.json)
metadata:
  type: project
---

Standing safety-hunt list. Recheck before any sign-off; close/append as they resolve. Scenario and
regression locations: [[reference-safety-scenario-catalog]]. Which artifact proves which published
number: [[reference-docs-evidence-chain]].

**RE-VERIFIED 2026-08-26 (fix round, `replay_point_mass_20260826T152528Z.json`): G61-G73 ARE ALL
CLOSED — every one re-probed against the fixed code, not by re-running the builder's tests. THE
LOAD-BEARING CHECK: the `tripwire` block is BIT-IDENTICAL to my independently-validated pre-fix
artifact except for one ADDED key (`robustness_attacks`), and `verdict.q3` is byte-for-byte
unchanged — so the already-quoted tripwire result was not disturbed by any of the fixes, including
the `v_entry_mps` deletion. Suites: pytest 1015/1(pre-registered)/2, unittest 897 OK, 61/61 replay
tests. MUTATION: 15 mutants, **14 killed**, and BOTH previously-surviving mutants are now caught
(`legality_guard_gone` -> 2 red incl. a test named for it; `scanner_parm_dead`/`scanner_paramset_dead`
-> 1 and 2 red). The one survivor is message text only (rewording the GUIDED-LOCK reason string
breaks nothing; the machinery IS held — dropping `logs_skipped` or the exit-2 branch both go red).
Highlights worth not re-deriving: C1 verified fixed at the source (`cov_bird_at_turnaround`
`closest_approach` 7.0000 -> **0.0000**, the direct hit is now visible, and a fly-THROUGH property
test pins the two CPA paths together); C3's band audit reproduces my independent numbers exactly
(climb lead 2.0 guided_default band-free min **0.7829 m** vs my 0.78); the robustness attacks
reproduce mine to 4 dp (0.6539 m / 4.59x, depth needed 11.39 m, 45 deg -> 0.2351 m / 12.76x); the
scanner fires on all 8 planted surfaces incl. `param set` in scripts/*.sh, scripts/*.py and
docs/runbooks/*.md, and correctly does NOT fire on `param set MIS_RESTART`.**

- **G76 — I CAUSED THIS ONE. My finding m8 was WRONG and the fix built on it is a regression:
  at leads >= 2.0 s the counterfactual now STOPS SIMULATING BEFORE THE ENCOUNTER.** I claimed the
  old fixed-end horizon (`t_resume + 3 s`) "manufactured deferrals" at long lead. It did not — under
  a fixed absolute end a longer lead buys MORE flying time, and re-checking the pre-fix artifact the
  lead-3.0 deferrals were genuine retreats. The fix made the horizon a fixed DURATION from each
  cell's own command (`t_end = t_cmd + horizon_s`, `replay_point_mass.py:888,913`), but the bird
  arrives at a fixed ABSOLUTE time — so a cell at lead L is only simulated to
  `t_takeover + (horizon_s - L)`, and at L = 3.0 s with horizon_s = 3.434 s that is 0.434 s past
  takeover. MEASURED on the 08-25 sweep, shipped rule vs a takeover-anchored end: **72 of 429 cells
  change their honesty number or verdict and 32 flip `resolved` False -> True.** Worst: `climb` /
  `brake` at lead 3.0 `poscontrol_bare` report `min_horizontal_threat_m` **12.5514 m** where the
  encounter-covering window gives **0.5037 m** — i.e. **C3's exact defect relocated from VERTICAL
  scoping to TEMPORAL scoping, in the very field added to prevent it.** **The two headline leads are
  UNAFFECTED** (physical 1.25 s / legal 2.00 s, same per-plant breakdown under both rules — verified
  by recomputation), so nothing quotable is wrong; the long-lead half of the table is.
  **How to apply:** `t_end = max(t_cmd, t_takeover) + horizon_s`, and pin it with a test that a
  cell's window always contains the flown-CPA instant. Lesson for me: I flagged m8 as MINOR and
  speculative and it was still acted on — say "UNVERIFIED, do not act" out loud, or verify it.
- **G77 — the admissibility filter M4 added is applied to the robustness SWEEP and not to the two
  DECLARED axes, and the difference is the number TG-5 publishes.** `admissible_dt_floor_s` for
  `live_flight_log_20260823T004031Z` is **0.197 s** (p99 step 1.9699 m/tick / WPNAV_SPD 10), so the
  declared `assumed_dt_0.16s` axis implies a **12.312 m/s** cruise and is inadmissible by the tool's
  own rule — yet it stays in `verdict.q1.rows` with a FIT verdict, is counted in
  `fit_verdict_counts`, and is the **sole source of the 1.85 endpoint** of
  `fitted_a_max_ne_mps2_range [1.05, 1.85]`. The admissible-only figure is **1.05 m/s2, one axis of
  one flight**. No row carries an admissibility field, so a reader cannot see it. Calibration in
  the tool's favour: the one flight with a real clock scores 10.099/10.0 = **1.01x**, so the
  heuristic is only mildly over-strict and 08-23's 1.23x is a solid exclusion. Bounded: 08-23's
  own verdict is unchanged on the admissible axis, so `command_path_worked` does not move.

**OPENED 2026-08-26 — ADVERSARIAL REVIEW OF THE POINT-MASS CONFOUND-RESOLVER
(`eval/point_mass.py`, `eval/replay_point_mass.py`, `tests/test_point_mass_replay.py`,
`eval/results/replay_point_mass_20260826T002121Z.json`). The tool's PHYSICS and its Q3 TRIPWIRE are
sound and hand-reproducible — every number I re-derived matched to 4 dp, and the "no safe speed"
answer survives three robustness attacks the report does not make. The defects are in what the
artifact SAYS around those numbers. Ranked by consequence.**
- **G61 — THE COMMITTED SAFETY GATE REPORTS 7.00 m ON A FIXTURE THAT FLIES STRAIGHT THROUGH THE
  BIRD. Pre-existing, not a replay defect; the replay's own numbers are what exposed it.**
  `closest_approach()` (`scripts/check_live_flight_log.py:408-434`) is a min over PATH VERTICES only
  — no segment interpolation, no vertical scoping. MEASURED, vertex vs point-to-segment on the same
  bytes: `eval/scenarios/cov_bird_at_turnaround/flight_log.json` **7.0000 → 0.0000 m** (the 15 m
  turnaround segment (15,58)→(30,58) passes through the detection at (22,58); nearest vertices 7 m
  and 8 m away, segment length 15 m against a p95 of 2 m); `cov_two_birds_simultaneous`
  **1.0000 → 0.0000**; `cov_bird_over_cell` 0.0000 → 0.0000; `geo_avoid_into_tree` 1.0000 → 1.0000;
  `live_flight_log_20260818T144711Z` **0.0597 → 0.0393**; `live_flight_log_20260823T004031Z`
  **0.0518 → 0.0391**. `cov_bird_at_turnaround` is the ONE fixture that passes the CPA bar and it is
  a direct hit — the degenerate-geometry family, blind exactly where the scenario was authored to
  look. The optimistic values are PINNED by `test_reproduces_the_flown_encounters_cpa`
  (`tests/fieldguard_planning/test_check_live_flight_log.py:200-209`) and quoted in DECISIONS:1920,
  :2304 and README. G22's `_point_segment_xy_m` fix went into the schema-2 `ground_truth_cpa` and was
  never back-ported to the legacy path, which round 5 turned into a CLOSED LIST — so the closed list
  is exactly the set of artifacts still scored by the optimistic geometry. **How to apply:** point
  `closest_approach` at `_point_segment_xy_m` over consecutive path pairs (~6 lines, the function is
  already imported in the same file), regenerate the fixtures, and expect
  `cov_bird_at_turnaround` to flip to BREACH — that flip IS the fix's proof.
- **G62 — THE REPLAY'S Q1 HEADLINE ANSWERS THE WINDOW IT DECLARED UNANSWERABLE.**
  `command_path_worked = winner != "H_broken_m"` (`eval/replay_point_mass.py:543`) is computed with
  no reference to `discriminating`, so the 2026-08-25 row — whose own `fit_verdict` is
  **"EVIDENCE INSUFFICIENT -- window too short to separate H_plant from H_broken"**, separation
  0.0051 m = **0.56 telemetry quanta**, power NOT DISCRIMINATING — still lands in
  `command_path_worked_by_flight` as **True** and in the printed line *"THE COMMAND PATH MOVED THE
  AIRCRAFT on 3 of 5 windows … {…20260825…: True}"*. Same inversion as G55: "we could not tell"
  printed as a positive finding. Worse, the tool's OTHER command mode on the same flight —
  `latched_first`, which is what the executor actually did on 08-25 (one latch, two relatches) —
  reports `H_broken` nearest, `command_path_worked False`, and the confident string
  **"FIT … [MARGINAL: hypotheses only 4.1 telemetry quanta apart]"**. Two modes, opposite signs, and
  the verdict block silently keeps only `CMD_PRIMARY`. **How to apply:** gate
  `command_path_worked` on `discriminating` (None/UNKNOWN otherwise), and make the headline print
  the denominator of ANSWERABLE windows, not of replayed ones.
- **G63 — A "CLIMB" RESOLUTION IS A BAND-EXIT WEARING A CLEARANCE NUMBER — the exact vacuous green
  ADR-013 am. 18 pre-registered in writing.** `cleared`/`resolved` (`replay_point_mass.py:766-769`)
  inherit `ground_truth_cpa`'s ±`vertical_threat_m` scoping, and `band_exit` is only True when the
  CPA is None, so a PARTIAL band exit scores the last in-band instant as if it were the closest
  approach. MEASURED on the 08-25 sweep, in-band CPA vs the true minimum horizontal separation to
  the SAME bird: `climb` lead 2.0 `guided_default` **5.35 m reported / 0.78 m actual** (at dz 7.4 m);
  `poscontrol_bare` **14.77 / 0.17 m**; `angle_max_ceiling` **14.34 / 0.014 m** (1.4 cm, at dz
  14.5 m); lead 3.0 `poscontrol_bare` **28.08 / 0.50 m**. `climb` is therefore listed in
  `verdict.q2.rows[…].resolving_candidates` for the encounter and printed as `climb True 2.00 5.351`
  in the stdout table. The lateral candidates are honest (dz stays 4.00 m, in-band == unscoped).
  The discriminator already exists per row and is discarded: `min_horizontal_any_band_m`. Note that
  claiming a climb as an escape also rests on the bird's z, which ADR-009 decided not to trust.
  **How to apply:** a cell whose vertical separation ever leaves the band must print BAND-EXIT with
  the unscoped minimum beside it and must not enter `resolving_candidates`.
- **G64 — A FLIGHT THAT NEVER RESUMED IS SILENTLY ABSENT FROM THE STUDY, AND THE RUN STILL EXITS 0.**
  `load_encounter` returns None when there is no takeover/resume PAIR or no maneuver
  (`replay_point_mass.py:196-198, 229-230`) and `build_report` does `if enc is None: continue`
  (:1021-1022). REPRODUCED: the real 08-23 log with its `resume` event deleted → `load_encounter`
  None; the CLI on that log alone → **exit 0**, `flights: []`, `verdict.q1.rows: []`,
  `plant_explains_n_of [0,0]`, `command_path_worked_n_of [0,0]`, Q3 "NOT COMPUTED", and the skipped
  log's name appears NOWHERE in the artifact. That shape is precisely **G56** (the new
  `RESUME_CLEAR_TICKS = 3` hysteresis can pin the vehicle in GUIDED for the rest of the flight → an
  unmatched takeover), i.e. the instrument goes blind on the failure the same session just created.
  The author DID think about too many encounters (>1 takeover raises a ValueError naming the count)
  and not about too few — absence is the bug, again. `main()` returns 2 only when the GLOB is empty,
  never when every log was skipped. **How to apply:** carry a `skipped: [{stem, reason}]` list into
  the artifact and print it; treat "0 encounters replayed" as a refusal, not a report.
- **G65 — Q2's "earliest resolving lead 2.00 s on all plants" is set by the TREE VET, not by lead
  time, on the plant that matters most.** `_setpoint_legal` (:786-812) uses the XY-only
  `GeofenceMap.segment_clearance` against `lateral_tree_margin_m` 1.0, and the swept path starts at
  the vehicle's OWN position — which on lane x=15 (orchard row 0) is up to **1.99 m inside** the
  exclusion radius, so even `brake` (setpoint == current position) is booked illegal at leads
  0.5-1.75 s. MEASURED: on `angle_max_ceiling` the encounter is genuinely resolved (bar met AND bird
  passed) at lead **1.25 s** (`sidestep_ahead_±90`, CPA 3.33/3.40 m) and at 1.5/1.75 s by eight more
  cells — every one discarded as `setpoint_legal: false`. `min_resolving_lead_by_plant_s` reports
  2.0 for all three. `geofence.py:156-157` says in its own comment that the XY query is a cruise
  query and `is_safe_3d` is the altitude-aware one; the escapes being refused are at 15 m over a
  3.5 m canopy. So the confound-resolver leaves a THIRD confound unseparated (lead time vs candidate
  ordering vs the policy's lateral tree margin), and the difference is 2.00 vs 1.25 s = 60 % on the
  required sensor horizon a second-sensor spec would be written against. **Mutation proof that
  nobody is holding this:** deleting `and r["setpoint_legal"]` from `_cf_summary` (:1125) breaks
  **zero** tests.
- **G66 — the 08-18 entry velocity is an artefact of the estimator's window, and H_broken is built
  on it.** `velocity_at(..., window_s=0.6)` on a staircase: the 08-18 pre-takeover 0.6 s window
  holds 4 samples and **2 distinct positions** (the flight is 83 % zero-steps; pose updates every
  ~2.5 ticks). MEASURED |v| at windows 0.3/0.6/1.0/2.0/4.0 s = **3.006 / 0.902 / 0.859 / 1.252 /
  1.360 m/s** — a 3.3× spread — and the H_broken it produces swings **−36.67 → −10.48 m** against an
  observed −14.54 m. At a 2 s window H_broken is −15.27 m, i.e. "the vehicle just carried on at its
  pre-takeover cruise" explains 08-18 to **0.73 m**. The NO-FIT verdict does not flip (it gets
  stronger), but the printed `entry speed 0.90 m/s` is not a measurement of that flight. 08-23 and
  08-25 are stable (<5 % across 0.3-1.0 s windows) — the defect is specific to the staircase log.
- **G67 — the tick-period robustness sweep's reported BEST cell is physically impossible, and
  nothing in the tool notices.** 08-18's best is quoted at **dt 0.05 s / 14.75 % / PARTIAL**; at that
  period the flight's own p99 step (0.8798 m/tick) implies a **17.6 m/s** cruise against WPNAV_SPD
  10 m/s, and 08-23's dt-0.05 row reports an entry speed of **26.96 m/s**. The tool computes
  `implied_cruise_speed_mps` in `step_diagnostic` for the two declared axes and never applies it to
  the sweep. Admissible rows (dt ≥ 0.10, from a single 0.8906 m tick step ÷ 10 m/s ≥ 0.089 s) give
  08-18 **58.9-62.8 %** — so the NO-FIT is stronger than advertised and the quoted figure comes from
  a cell the plant forbids. Same family as "never rest a claim on a boundary": the optimum sits on
  the sweep's own lower edge.
- **G68 — the TUNING OVERRIDE scan looks in the one place this project does NOT set parameters, and
  no test proves it fires.** `_tuning_override_scan` (:1150-1173) globs `config/**/*.parm` only. The
  documented override channel here is the MAVProxy prompt: `scripts/fly_pipeline.sh:459-460` and
  `scripts/run_farm_mission.sh:69-71` already `param set MIS_RESTART/AUTO_OPTIONS/DISARM_DELAY`, and
  **the ADR-017 speed doctrine's natural implementation is `param set WPNAV_SPD <n>` in exactly that
  block** — after which the study is void and the scan still prints "CHECKED at run time: no
  override". Second unchecked surface: SITL frame defaults. VERIFIED BY ME at the pinned SHA that
  `Tools/autotest/default_params/copter.parm` and `gazebo-iris.parm` set **no** `WPNAV_*`/`PSC_*`/
  `GUID_*`/`ANGLE_MAX` — so the conclusion holds today, but that warrant lives in this memory, not
  in the tool. The scan itself is GOOD: it fires on 9 syntax variants (space/comma/equals/tab/
  indented/lowercase/trailing-comment, WPNAV_/PSC_/GUID_/ANGLE_MAX) — proven in a sandbox. But
  `test_the_defaults_assumption_is_checked_against_the_repo_not_asserted` is an if/else that passes
  on either branch: **neutering the detector breaks zero tests.**
- **G69 — two thirds of 08-25's "observed compliance" is the cruise leg.** `observed_along_cmd_
  window_m` **+0.0541 m** projects onto `cmd_unit` (−1.0, −0.0091). Decomposed: the x term (the real
  cross-track dodge) is **+0.0182 m**; the y term is **+0.0360 m**, which is the ongoing −3.95 m
  cruise leaking through a 0.52° misalignment. `observed_compliance_window_pct 0.541 %` must not be
  quoted as what the dodge achieved; G54's 0.054 m / 0.018 m figures remain the honest ones.
- **G70 (minor, doctrinally loud) — the one constant that is NOT a firmware default carries a
  dangling URL.** `point_mass.py:155-156` cites `AC_AttitudeControl.h:26` for
  `AC_ATTITUDE_CONTROL_ANGLE_MAX_DEFAULT 30.0`. At the pinned SHA the string "ANGLE_MAX" does not
  appear in that header at all; the define is at **AC_AttitudeControl.cpp:26**. Value verified
  correct (and `AP_GROUPINFO("ANGLE_MAX", 24, …, AC_ATTITUDE_CONTROL_ANGLE_MAX_DEFAULT)` at
  AC_AttitudeControl.cpp:164). Same family as G46's `DEFAULT_SPEED_MPS` citing a file with no speed
  in it — in the bundle whose own doctrine paragraph is "physical parameters come from the vehicle,
  never from prose".
- **G71 (minor) — the telemetry has TWO quanta and the discriminating-power denominator silently
  uses the smaller.** MEASURED on all three flights: E/x = **0.009078 m**, N/y = **0.011131 m**
  (separate lat/lon round-trips). `_position_quantum_m` pools both axes and returns the min, while
  the displacement being tested is projected onto the COMMAND direction — which is pure N on 08-18
  and 08-23 and pure E on 08-25. The right axis is used on 08-25 by luck. The docstring's "0.009078
  on all three flights, whose next step size up is exactly 5x that" is wrong twice (the next step up
  is 1.227× — the other axis). The MARGINAL 4.14-quanta row is 3.5 % from flipping to EVIDENCE
  INSUFFICIENT.
- **G72 (minor, latent) — `max_displacement_m`'s `v_entry_mps` term is not velocity-capped and
  double-counts.** It adds `v_entry*T` flat and then computes the from-rest profile on top, never
  re-checking `v_max_ne`. MEASURED against an independent fine integration: v0 = 3 m/s → **5.229 m
  claimed vs 3.729 m true**; v0 = 9 m/s → **14.076 vs 9.576**. No caller passes a non-zero entry
  velocity today (`tripwire` and `time_to_displace_s` both use 0) and no test covers it — so it is
  dead-but-wrong, and "what lead does a MOVING vehicle need" is the next question anyone asks of
  this module.
- **G73 (minor) — three smaller ones, all one-liners.** (a) `_bird_xy`'s docstring claims "nearest
  candidate … uncertainty never buys clearance" and the code takes `positions[0]`, which is the
  `pose_from_applied` answer, not the nearest (bounded: it feeds the away-vector and `_passed_bird`,
  never the CPA). (b) `sensor_horizon_m`'s `axis_taken` says it exists "so a mount rotation cannot
  silently swap them" and then takes `max(hx, hy)` — which IS the silent swap; correct today
  (`predict_bird_visibility.py:43` confirms the 640-px axis is along-track) and optimistic, so
  conservative for a negative verdict, but wrong the moment a forward sensor is modelled. (c) TG-5
  labels the fitted `a_max` **MEASURED** while both endpoints of the 1.05-1.85 range come from ONE
  schema-1 flight under two ASSUMED tick periods — the module's own rule is "Nothing from a
  schema-1 log is ever labelled measured". (d) the `CMD_*` comment justifies `as_commanded` as
  primary with "rms of 0.62 m … versus 1.11 m" and the shipped artifact says 1.3185/3.8112 (dt 0.20)
  and 0.4955/1.0976 (dt 0.16) — stale numbers under the choice that decides 08-25's verdict.
  (e) the counterfactual horizon is `t_resume + 3 s`, anchored to the REAL resume, so the simulated
  duration is 15.2 s (08-18) / 6.8 s (08-23) / 3.4 s (08-25): leads are not comparable across
  flights, and at leads ≥ 2.5 s on 08-25 the encounter simply falls outside the horizon and is
  booked as a "deferral".

**WHAT THE REPLAY GOT RIGHT AND MUST NOT BE RE-LITIGATED (verified independently 2026-08-26,
recorded so a later round does not re-spend the time):** the integrator matches an independently
written fine integration to **7.5e-6 relative** on all three plants; `simulate` never beats the
closed-form bound by more than 8.3e-6 m; the 5 ms step is converged (5e-6 m); `sqrt_controller`
matches the two-branch AP_Math form exactly; **every plant constant + `GUID_OPTIONS` default 0 +
`WPNavUsedForPosControl = 1<<6` + `pva_control_start`'s WPNav seeding + "WPNAV_JERK 1.0 is NOT on
this path" verified at ArduPilot 9895756d**; the whole Q3 tripwire arithmetic hand-reproduced
(0.4132 s / 0.2278 m / 27.25-38.75-17.75 m / climb 2.084-1.528-1.350 s); the artifact regenerates
bit-identically modulo `generated_utc`; the tool is genuinely not-a-gate (output gitignored by
`.gitignore:21`, zero references in `.github/` or `scripts/`, exit 0 or 2 only, no bar); and
**13 of 15 behavioural mutants were killed** (the two survivors are G65 and G68).

**OPENED 2026-08-25 (b) — ADVERSARIAL REVIEW OF THE ADR-016 "cheap honesty fixes" BUNDLE
(MIS_RESTART pin / `--speed` required / threat-clear hysteresis / derived swath). All four items
are real fixes and all four regression claims were proven RED against the pre-fix code by
behavioural mutation. These are what the bundle OPENED or left open.**

> **ALL FIVE (G56-G60) CLOSED and RE-VERIFIED 2026-08-25 (b, round 2).** `GUIDED_CEILING_TICKS = 305`
> at the top of `step()`; `_is_clear_tick` requires PROCEED **and** no `n_stale_dropped`; the design
> note quotes the measured 0.48 s; an AST test evaluates the node's actual swath expression; the
> docs and six agent files carry `--speed`; the monotonicity claim is reworded to "NOT monotone".
> Closure evidence (all mine, all mutation-proved): `_enforce_guided_ceiling` neutered → 6 tests red;
> `_is_clear_tick` staleness ignored → 2 red; node swath → `7.5` / `derive(20.0)` / `7.4999` → 2 red
> each; `gate_encounter_closure` neutered → 6 red, severity downgraded → 2 red; `CRUISE_ALT_M`
> 15→16 → 2 red. Committed-gate stdout byte-identical (only the script's own filename differs when
> run from a temp copy), exit 1 both sides. **What CLOSED does not mean here:** the ceiling BOUNDS
> the stall, it does not prevent it — 1200 ticks of a 1-in-3 duty cycle gives 4 takeovers, 3
> `guided_ceiling` resumes and **6 of 1200 ticks in AUTO**. That is the accepted residual; the gate
> now NOTEs each ceiling resume and FAILs a terminal unmatched takeover, so it can never be silent.

- **G76 — the criterion-2 RGB study's ADOPT-gap headline is not reproducible from the committed
  artifacts, and two of its numbers are mislabelled.** Study is otherwise sound (verdicts: RGB's
  honest ceiling / ADOPT re-confirmed / RETIRE-ARM). Three defects, none changing a verdict:
  (a) `eval/results/adr003_20260823/detections_rgb.json` is still the OLD min-channel run, so
  `score.py` on the committed evidence prints **gap -0.850, arm FNR 1.000** — the number the study
  retires. The claimed "gap +0.000" reproduces only after re-running `baseline_rgb.py` (I did: 75
  detections, gap +0.000, ADOPT). Regenerate the committed detections or the evidence chain is
  broken. (b) The band-independence values are gate2's MEASURED `mean_rho_nir`, not the AUTHORED
  `calibrated_rho_nir` — the word "authored" appears in `eval/rgb_pixel_study.py`'s docstring, in
  `results.json.band_independence.method`, and in a TEST NAME
  (`test_ndvi_inverts_against_the_rgb_red_channel_to_the_authored_materials`). (c) "460x GRVI's
  false-positive rate" is **482.3x**; 460 comes from dividing by `G_minus_R`'s best_fpr
  (6.568e-06) instead of GRVI's (6.274e-06) — adjacent rows in the feature table. Repeated in
  `eval/rgb_pixel_study.py` VERDICT, `eval/baseline_rgb.py`'s docstring, and perception's memory.

- **G75 — THE CPA SEGMENT BACK-PORT MOVED FIVE PUBLISHED NUMBERS AND THE DOCS STILL QUOTE THE OLD
  ONES.** `closest_approach()` now measures the flown PATH, not its vertices. Independently
  reproduced (vertex-only vs segment, same artifacts): `cov_bird_at_turnaround` **7.0000 → 0.0000**
  (the ONE fixture that cleared the 3 m bar was a fly-through), `cov_two_birds` 1.0000 → 0.0000,
  live 2026-08-18 **0.0597 → 0.0393**, live 2026-08-23 **0.0518 → 0.0391**, and the 08-25 take's
  `detection_cpa_m` **0.2096 → 0.0035** with `range_estimate_error_at_cpa_m` **−0.2028 → +0.0033**.
  Verdicts and exit codes on all three committed logs are UNCHANGED (only the numbers move) and CI
  is colour-invariant (`ci.yml`'s glob is `eval/results/*flight_log*.json`; the fixtures are not
  scored by CI). **The defect is the published figures that now contradict the tool**: living docs
  `.github/workflows/ci.yml:108` ("all four CPA numbers bit-identical -- 0.0000 / 7.0000 / 1.0000 /
  1.0000"), `eval/scenarios/README.md:147`, and the acknowledgement marker
  `eval/results/live_flight_log_20260825T210402Z.SAFETY_FINDING.md:24,108` — that marker is one of
  the two halves of the breach-acknowledgement contract and a reader re-runs the gate in 2 s.
  Append-only history needing a dated amendment instead: `docs/DECISIONS.md:1920`, `:2304`,
  `:2668-2669`, `:2787`. **And the interpretation inverts, which is the part that is not
  bookkeeping:** am. 12's text argues the estimator "earned its demotion" from a 20 cm disagreement
  with ground truth; corrected, the monocular apparent-size ray agrees to **3.3 mm**. The demotion
  may still be right (a MISS at closest approach produces no detection at all — an argument
  independent of the number), but the cited evidence no longer says what it is quoted as saying.
  Note am. 16's actual load-bearing claim SURVIVES: CPA depends only on `flown_path_enu` +
  detections, both byte-identical across the regeneration, so "bit-identical across a control-law
  change" still holds — only the values are stale.

- **G74 — CLOSED 2026-08-26.** `_enforce_guided_ceiling()` moved to the BOTTOM of `step()`; verified
  max 1 `set_mode` per tick across an exhaustive sweep of ceilings 4..39 (every mod-3 phase) at both
  1-in-3 and 1-in-2 duty cycles, and moving it back to the top turns
  `test_no_tick_ever_emits_more_than_one_mode_switch` red on BOTH its sub-cases plus
  `test_the_ceiling_restarts_the_encounter_it_does_not_disable_avoidance`. **Keep the lesson: that
  pin was nearly vacuous.** A ceiling whose expiry lands on a PROCEED tick shows max 1 switch/tick
  even at the broken top placement — measured, ceilings 9 and 11 both PASS against the defect,
  only ceilings ≡ 1 mod 3 catch it. The shipped test asserts `ceiling % 3 == 1` inline and runs two
  such ceilings. **Any future "no more than one X per tick" test must state and assert its phase.**
  Original finding: THE CEILING'S HAND-BACK ISSUES TWO MODE SWITCHES INSIDE ONE CONTROL TICK.
  `_enforce_guided_ceiling()` runs at the TOP of `step()`, so when the ceiling expires on a DIVERT
  tick the same callback does `set_mode(AUTO)` → `set_mode(GUIDED)` → `send_setpoint_enu(...)`.
  REPRODUCED with a spy sink: all three calls inside one `step()`. `Ros2VehicleSink.set_mode` is
  **non-blocking `call_async`** (`src/fieldguard_planning/ros2_adapter.py:~156`), and that file's own
  comment states the executor "asserts the mode exactly ONCE per takeover and once per hand-back and
  nothing re-sends a rejected switch" — the ceiling path breaks that invariant, and the failure it
  guards against is a setpoint stream published while ArduPilot is actually in AUTO. **Fix is free:**
  move `_enforce_guided_ceiling()` to the BOTTOM of `step()`. MEASURED on the same duty cycle: zero
  ticks with more than one mode switch, resume at tick 305, re-takeover at 307. The "top" placement
  is also UNPINNED — moving it below the decision handler breaks **zero** tests, so the design note's
  "running it here rather than inside a handler is what makes it unconditional" is prose, not a
  gated property (it is unconditional at either end of `step()`, since it sits outside the branches).
  Minor riders: the sizing comment says "61 ticks" but `ticks_in_guided` is INCLUSIVE, so that
  encounter reports **62** — and the test hardcodes `longest_flown = 61` rather than deriving it
  from the committed logs; `gate_encounter_closure` is wired only into `check_schema2`, so a legacy
  log (the four fixtures, and any future self-activating pending scenario) gets no closure check;
  and the UNCLOSED-ENCOUNTER text names only the duty-cycle cause, while an operator tearing down
  mid-dodge produces the identical signature.

- **G56 — CLOSED (see above). THE NEW RESUME HYSTERESIS CAN PIN THE VEHICLE IN GUIDED FOR THE REST OF THE FLIGHT, and
  no gate, test or event can see it.** `AvoidanceExecutor._handle_proceed` needs
  `RESUME_CLEAR_TICKS = 3` CONSECUTIVE PROCEED ticks; any DIVERT/HOLD zeroes the counter. So ANY
  detection duty cycle ≥ 1-in-3 ticks (a flickering bird at the FOV edge; 15 % FN is the ADOPTED
  detector's own rate) means the counter never reaches 3. REPRODUCED: feed `"dpp" * 30` →
  **90 ticks, 1 takeover, 0 resumes, mode GUIDED at the end**; the same input at
  `resume_clear_ticks=1` (pre-fix) gives 30 resumes. The mission never resumes, the remaining field
  books as debt, and the vehicle hovers on a latched dodge point. There is no max-GUIDED bound, no
  `guided_ticks` counter (`resume_pending` resets to 1,2,1,2… so the log looks healthy), and
  `check_live_flight_log.py` has NO takeover↔resume pairing check at all (`ENCOUNTER_KINDS` at
  :258 does not even contain `resume`). Worse, `test_the_gap_resets_the_clear_counter`
  (tests/…/test_avoidance_executor.py) pins the lock-in as CORRECT behaviour without bounding it.
  **How to apply:** ask for a GUIDED-tick ceiling with an explicit `resume(trigger=…)` or a
  `guided_ticks` field, and a gate that fails an unmatched takeover, before the re-fly.
- **G57 — a tick on which the staleness gate threw away EVERY detection counts as a "clear" tick.**
  REPRODUCED: DIVERT, then 3 PROCEEDs each carrying `debug.n_stale_dropped = 2` → `resume` with
  `trigger: "threat_cleared"`, and the resume event records nothing about the discards. Unreadable
  evidence is being booked as confirmed absence — the mirror image of the "stale detection treated
  as live" family. Pre-existing in effect (1 tick pre-fix) but design note 4 now explicitly claims
  to own "ABSENCE persistence", so this is the place to fix it: a stale-drop tick should reset the
  counter, or the resume must carry `n_stale_ticks`.
- **G58 — the hysteresis's advertised 0.6 s is 0.48 s in the air, and the ceiling test cannot
  see it.** `test_the_default_cannot_outlast_the_policys_own_staleness_gate` asserts
  `RESUME_CLEAR_TICKS / CONTROL_HZ ≤ max_detection_age_s` using the NOMINAL 5 Hz. Measured on
  `eval/results/live_flight_log_20260825T210402Z.json`: 1855 tick dts, **median 0.160 s** (6.25
  ticks/sim-s), p05 0.063, max 0.253. So 3 ticks = 0.48 s median / 0.19 s at p05, and the design
  note's premise "one missed 5 Hz frame is exactly one clear tick" is false — the control loop
  outruns the camera, so a 2-frame detector hole can already reach 3 clear ticks. The inequality's
  conclusion survives at the worst measured dt (0.76 s < 1.0 s); its stated MEANING does not.
  Same family as the pinned VALUES-vs-GEOMETRY lesson.
- **G59 — the half of the swath fix that actually flies is untested.** `avoidance_node` now calls
  `derive_swath_half_width_m(CRUISE_ALT_M)` (:431) and that value is what lands in every live
  flight log's `swath_half_width_m` and coverage ledger. MUTATION PROOF: replacing it with the old
  `7.5` literal breaks **zero** tests across both runners. The new `TestSwathComesFromTheCamera`
  pins `coverage.DEFAULT_SWATH_HALF_WIDTH_M`, which the node never reads. Second homes that
  survived: `eval/scenarios/generate_flight_logs.py:35 SWATH_HALF_M = 7.5` (disclosed in
  eval/scenarios/README.md, so a deferral not a hole — but it will diverge silently the day
  `ndvi_camera.json` moves) and `avoidance_node.CRUISE_ALT_M = 15.0` vs
  `field_polygon.mission_altitude_m = 15.0` (two homes for the altitude the derivation hangs on).
  Math independently verified: fx 520.006 px, depth 14.92 m, cross-track half **6.886077 m**,
  along-track 9.181 m, 1.228 m inter-lane strip, 0.636 m quantization margin, 720/720 unchanged.
- **G60 — the abort gate's "monotonic in speed" justification is FALSE.**
  `predict_bird_visibility.py`'s docstring, runbook §0b and `scripts/README.md` all justify "when
  unsure pass the FAST end" with "speed only removes frames from view". MEASURED on the committed
  config (0.1 m/s sweep, 1.0–20.0 m/s, `--fps 5.0`): bird_1's median frames-in-view goes **0 at
  8.0 m/s → 3 at 8.5 m/s**; bird_2 **3 at 9.4 → 4 at 11**; failing-bird count goes **2 at 3.5 m/s →
  1 at 4.0 m/s**. No PASS→FAIL→PASS inversion was found in 1.0–6.0 @ 0.1 m/s, so the RULE survives
  on this config while its stated REASON does not. Cause is aliasing: speed shifts the drone's
  arrival phase at each lane against the scripted bird's patrol, and the 55-offset sweep only
  phases the BIRD. **How to apply:** the doc must say "empirically non-monotone; sweep, do not
  assume", or the tool should sweep speed itself.

**OPENED 2026-08-25 — FIRST REAL-DETECTION AVOIDANCE TAKE FLEW AND BREACHED
(`live_flight_log_20260825T210402Z`, gt_cpa_m 0.0067 m to bird_0 at tick 991 / t_sim 202.775,
vertical sep 4.03 m, gated −1.1210 m vs the 3.00 m bar). Exactly the runbook §7 pre-registration.
These are the gaps the flight MEASURED. Ranked by consequence.**
- **G55 — THE GATE PRINTS AN INSTRUCTION TO DELETE THE SAFETY EVIDENCE ON A BREACHING LOG.** Found
  2026-08-25 while writing this take's marker; nobody else caught it because it only appears once a
  marker EXISTS beside a log whose truth resolution failed. `check_schema2` computes
  `breach = cpa_m is not None and cpa_m < bar` (`scripts/check_live_flight_log.py:1610`). When
  `resolve_truth` fails — ambiguity (G47), no track, unreadable track — `cpa_m` is None, `breach` is
  **False**, and the `elif marker.exists()` branch (:1631-1634) fires:
  *"a stale acknowledgement marker ... is present beside a log **that does not breach CPA**. An
  acknowledgement beside a passing log pre-authorises the next regression on this file; **delete the
  marker**."* REPRODUCED verbatim on the real 2026-08-25 take, which flew **0.0067 m** from a bird.
  The verdict stays INVALID/exit 1 so it is not a false green — the defect is the **remediation
  text**: an operator who follows it destroys the written finding beside a 6.7 mm bird strike, after
  which the log reads "no acknowledgement" and looks like ordinary paperwork. This is the pinned
  "a rate needs a denominator" lesson in its most dangerous form yet: **absence of a COMPUTED breach
  is being reported as absence of a breach.** "We could not tell" is being printed as "it did not
  breach". **How to apply:** the stale-marker branch must be reachable only when CPA was actually
  MEASURED and passed. Guard it on `cpa_m is not None` (and say "CPA NOT MEASURED — the marker is
  neither confirmed nor stale" otherwise). Compounds G47: on the committed tree, truth resolution
  fails for EVERY schema-2 take, so this is the branch the next operator meets by default. Prove any
  fix red-first against the real take + its marker.
- **G43 — THE SENSOR HORIZON IS 2.48 m AND THE POLICY'S THREAT HORIZON IS 12 m; warning time at the
  flown speed was ZERO.** Nadir camera (`ndvi_georef` extrinsic quat_wxyz=(0,1,0,0)), bird_0 4.03 m
  below cruise → footprint at the bird's depth is 4.96 × 3.72 m. Closing speed 14.4 m/s (drone
  8.4 m/s south, bird ~6 m/s north, both on lane x=15). MEASURED: 7 NDVI frames captured while
  bird_0 was truly in the threat cylinder, **2** with the bird inside the image, **2** detections —
  first detection reached the policy AT the CPA tick. R4 escape geometry cannot use warning that does
  not exist. **How to apply:** any R4 proposal must be priced against the 0.34 s dwell, not against
  the 12 m cylinder; the real levers are slower flight, a wider/forward FOV, or threat persistence.
- **G44 — NO THREAT HYSTERESIS: one empty frame ends an encounter.** `NdviDetectionSource.on_frame`
  REPLACES `_latest`, so a frame with no boxes clears the threat; the staleness gate never gets to
  fire. MEASURED: takeover tick 991 → resume tick 995 = **0.434 s of GUIDED**, lateral displacement
  **0.018 m** (0.054 m over the next 2 s). Four accepted maneuvers moved the vehicle 1.8 cm.
- **G45 — R3 missed by 15 mm.** `relatch_refused_degenerate=0` is NOT a clean sheet: tick 991 was
  degenerate (trigger_range 0.21 m) but was a FIRST latch (permitted by design); the 18.90 m setpoint
  reversal at tick 992 had trigger_range **1.015 m** against `degenerate_range_m` **1.0 m**. The knob
  is 1.5 % away from having caught the exact event it exists for. Probe the knob's denominator.
- **G46 — ADR-015's camera gate is green only at a speed the vehicle has never flown.**
  `predict_bird_visibility.DEFAULT_SPEED_MPS = 3.0` cites "WPNAV_SPEED as flown
  (docs/runbooks/SIM_BRINGUP.md)" — that file contains no speed at all. MEASURED cruise (z>13 m) p50
  3.84 / p90 **9.19** / max **12.52** m/s. `--speed 8` → **FAIL, exit 1, 3 of 3 birds below the
  5-frame floor**; medians 2/0/4 at 8 m/s and 2/2/3 at 9.2 m/s against the published 8/6/11. The
  flight measured **2/0/0**. The abort gate (runbook §0b) has been passing on the wrong mission.
- **G47 — a schema-2 breach CANNOT be acknowledged, because CI cannot pass `--truth`.** ci.yml runs
  `check_live_flight_log.py "${logs[@]}"` with no truth argument. `bird_drive_*_applied.jsonl` is a
  gitignore exception and the 2026-08-23 track is committed, so ANY newly committed applied log makes
  ≥2 candidates overlap → `ambiguous truth track` → a HARD problem that no marker+pin can clear, and
  the CPA is never even printed. REPRODUCED both ways (scratch `results_dir`, `truth=None`). The
  marker/pin contract was built for the legacy path and has never been exercised on a schema-2 log.
- **G48 — the truth track kept growing after the gate ran.** `bird_drive_20260825T210030Z_applied.jsonl`
  went 1348 → 2202 records (310 KB → 548 KB) DURING this review; the driver kept teleporting birds to
  sim ~992 s while the flight ended at 303.7 s. Headline numbers re-verified stable (0.0067 /
  −1.1210 / 610-610 / 16 / 4), but `truth landed set_pose calls per bird` moved 489/478/485 →
  655/625/644: a printed count whose denominator is the whole track, not the flight. Also **278 of
  2202 set_pose calls failed (12.6 %)**, 0 of them within ±7.5 s of the CPA.
- **G49 — the gate explains the missed-detection signal with the WRONG mechanism.** Its note says "a
  bird behind the drone is invisible to a forward-facing camera". The mount is NADIR. The correct
  reason is footprint-at-depth, which points at a different fix; the wrong reason retires the
  question. Same family as a vacuous green: an explanation nobody checked.
- **G50 — `n_at_risk_cells_recovered: 116` describes a maneuver the vehicle did not perform.** Ledger
  itself is honest (720 covered / 0 debt, all flown), but the divert-audit headline is computed off a
  COMMANDED divert that produced 1.8 cm of displacement. Safe direction, still a commanded-vs-flown
  number in a headline.
- **G51 — the suite is RED on the working tree and the acknowledgement test gates on the DEMOTED
  metric.** MEASURED 2026-08-25: `pytest tests -q` = **1 failed / 876 passed / 2 skipped**, not the
  published 877/2/0. `TestAcknowledgementMarkersOnRealEvidence::test_every_breaching_committed_log_
  has_BOTH_halves_of_an_acknowledgement` (tests/fieldguard_planning/test_check_live_flight_log.py:437)
  globs the REAL `eval/results/` and fires on the untracked take. Three defects in one test: (a) it
  scores with `closest_approach` = detection-CPA, which ADR-013 am. 14 demoted to "ESTIMATOR CHECK,
  NOT A SAFETY GATE" — it reports 0.2096 m where GT-CPA says 0.0067 m; (b) `cpa is None → continue`,
  so a flight whose detector saw NOTHING while the bird passed at 5 cm is silently exempt — the
  missed-detection family, un-gated in the test layer; (c) its failure message demands BOTH halves,
  i.e. it prescribes the pin that am. 17 and runbook §6a say never to add for a re-flyable take
  (G37's family, in the loudest voice — the one an operator reads at a red suite).
- **G52 — the two DETECTION scenarios have been PENDING since Week 3-4 and the generator cannot
  produce them.** `eval/scenarios/det_bird_crosses_path.yaml` and `det_bird_over_low_ndvi.yaml` exist;
  `generate_flight_logs.py`'s `SCENARIOS` dict (line 45) has no entry for either, so the two
  self-activating skips in `test_safety_scenarios_pending.py` (:123, :128) have never once activated.
  The scenario family with ZERO executable coverage is exactly the family the 2026-08-25 take proved
  binding. `test_ci_evidence_gate.py`'s "every scenario has a committed fixture" uses *generator*
  scenarios as its denominator, so the two authored-but-unbuilt ones are outside its reach.
- **G53 — RETRACTED 2026-08-25 (red-team pass). I was WRONG; do not repeat this claim.** I had
  written that R4-as-candidate-ordering was "falsified" because on all four maneuvers of the
  2026-08-25 take candidate 0° was rejected by R2 and the vehicle still made 0.0067 m. That
  generalises one 4-tick encounter in which 0° happened to be tree-blocked. Re-measured across the
  two EARLIER logs, which I had not opened: on `live_flight_log_20260818T144711Z` (61 maneuvers) and
  `live_flight_log_20260823T004031Z` (19 maneuvers) candidate **0° was chosen**, and 0° in a head-on
  closure yields a setpoint whose CROSS-TRACK component is **0.02–0.36 m out of 10.00 m** — half of
  them command the vehicle FORWARD along its own track (tick 3588 dy **+9.99 m**; tick 341 dy
  **+9.99 m**) and are logged `verdict: accepted`. `test_R4_is_still_open`'s docstring already names
  the true mechanism ("in a head-on closure is a full reversal — the escape ownship momentum
  forbids"). **How to apply:** R4 is NOT superseded by warning time. Warning time and escape
  direction are CONFOUNDED across the three flights (long warning + degenerate direction on 08-18 /
  08-23; short warning + non-degenerate direction on 08-25) and no causal claim about the breach
  mechanism is currently supported by any flight. Resolve it offline before spending a session.
- **G54 — NOTHING IN THE REPO GATES WHETHER AN AVOIDANCE COMMAND MOVED THE VEHICLE, and measured
  compliance is 0.5–4 %.** Commanded vs achieved, all three live flights (`flown_path_enu` indexed
  by tick, GUIDED window from the takeover/resume events):
  08-18, 61 maneuvers, ~61 ticks in GUIDED, |setpoint−pos| 10.00 m → lateral excursion **0.182 m**;
  08-23, 19 maneuvers → **0.418 m**; 08-25, 4 maneuvers → **0.054 m**. Every one is
  `verdict: accepted`, ledger 720/0, "19/19 vetted". Compliance does not improve with more warning
  time (61 ticks bought less than 19). No `dwell`/`converg`/`setpoint_reached`/`maneuver_complete`
  concept exists anywhere in `src/`. **This is the highest-order vacuous green in the project: the
  entire gate suite certifies DECISIONS while the actuator does approximately nothing.**
  **How to apply:** the missing verification layer is at the ACTUATION boundary, not the perception
  one — log and gate `maneuver_executed` + achieved displacement, exactly as a COMMANDED setpoint is
  already refused as FLOWN coverage. Also: no param file sets `WPNAV_*`/`GUID_*` (only `DDS_ENABLE`,
  `DDS_UDP_PORT` in `config/sitl_params/dds_udp.parm`), so it is still UNKNOWN whether the breach is
  an autonomy result or an ArduCopter SITL default-tuning / GUIDED-acceptance artifact. Answer that
  before ranking any control-law work.
- **UNMEASURED, not clean, on this take:** phantom dodges (bird_1 — the dry run's phantom source,
  lifted into the ±6 m band by the 0.15/0.18 radius prior — was in frame on **0** of 1301 frames);
  the executor's bird backstop (`gate_rejects=0`); HOLD clearance (`0 of 0 holds`); R3's refusal
  branch; swept-path re-vet as ownship moves (S2).

**OPENED 2026-08-25 — DOCS-REVAMP AUDIT (the front door got honest; the shelf behind it did not).
No verdict-flipping defect. Ranked by which reader gets hurt.**
- **G39 — the asterisk stops at the front door: `docs/runbooks/AVOIDANCE_DEMO.md` is the arm that
  PRODUCED both acknowledged bird strikes and it never says so.** Both breach logs are
  `eval/results/live_flight_log_<UTC>.json` (scenario `live_run`) and §"On Ctrl-C" of that runbook is
  what writes them. MEASURED: `grep -in "CPA|breach|0.0518|0.0597|SAFETY_FINDING|clearance"` on
  AVOIDANCE_DEMO.md returns **zero hits**. The 2026-08-25 revamp promoted it onto docs/README.md's
  four-runbook shelf described as "the deterministic regression arm ... for checking the loop still
  behaves" — reassuring language routing a reader to the one runbook they can run today, with no
  pre-registration that a breach is expected (R4 open) and no pointer to the two-half
  acknowledgement rule, which lives only in AVOIDANCE_REAL_DETECTION.md §6a. README.md and SETUP.md
  both carry the asterisk loudly, so this is a routing gap, not a lie. **How to apply:** one
  blockquote in AVOIDANCE_DEMO.md's existing PARTLY-SUPERSEDED banner + one clause in
  docs/README.md's description. Same shape as G35 — a doc-drift tripwire that is one file deep.
- **G40 — README.md cites `tests/README.md` as the proof of "877 passed, 2 skipped, 0 xfail" and
  that file says 279.** MEASURED today: `pytest tests -q` = 877/2 (0 xfail); `discover -s
  tests/fieldguard_planning` = 822 OK (skipped=2); `discover -s tests -p 'test_*.py'` = 57 OK.
  tests/README.md still says 248 / 33 / 279, and its second command (`-p 'test_fly_pipeline.py'`)
  now collects **52**, not 33 — `tests/test_ci_evidence_gate.py` is invisible to it. The revamped
  front door therefore links a number to a source that contradicts it. Nothing gates any of the
  three numbers.
- **G41 — `requirements-eval.txt:4-5` still claims the planning suite "stays runnable on a bare
  Python interpreter with zero install step, in CI or on a demo machine".** INDEPENDENTLY
  FALSIFIED 2026-08-25 on a fresh `python3.12 -m venv` (pip only): `discover -s
  tests/fieldguard_planning` -> **Ran 614, FAILED (errors=10, skipped=17), exit 1**, all ten
  `ModuleNotFoundError: No module named 'numpy'`. Only `discover -s tests -p 'test_*.py'` (57, OK)
  is genuinely install-free. SETUP.md §0/§3 were corrected this session; the requirements header was
  not, and the "in CI" half is doubly wrong — ci.yml installs the pins BEFORE the suite on purpose.
- **G38 — CLOSED 2026-08-25, VERIFIED.** The stale README is rewritten: the two ~5 cm breaches are a
  ⚠️ status row plus a "safety story, told straight" section with the reproducing command; escape
  geometry is stated as deliberately open in three places; the synthetic-stand-in caveat is gone and
  the real-render ADOPT numbers are sourced to `eval/results/adr003_20260823/spike_scores.json`
  (verified field-by-field). Residual is G40 only.

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
