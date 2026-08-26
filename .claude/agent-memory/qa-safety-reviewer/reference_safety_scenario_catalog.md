---
name: reference-safety-scenario-catalog
description: Where the SwathKeeper safety scenarios, regression files, flight-log gates (legacy + schema 2) and truth-track evidence live, and how to run them; plus the ADR-019 forward-depth probe set (exit-contract collision, mount-matrix mutants, resolvability sweep, gz-source verification)
metadata:
  type: reference
---

SwathKeeper safety scaffolding, owned by qa-safety-reviewer. Grows session over session — add new
files here, don't reset. Open gaps: [[project-open-safety-gaps]].

**Scenario layer (Week 2 origin)**
- Scenario specs (YAML, one per scenario, `name:` == filename): `eval/scenarios/*.yaml`
- Spec FORMAT + the coverage-debt ledger invariant (prose contract): `eval/scenarios/README.md`
- Generator that produces `eval/scenarios/<name>/flight_log.json`: `eval/scenarios/generate_flight_logs.py`
- Coverage grid + `check_ledger` invariant (executable): `src/fieldguard_planning/coverage.py`
- Self-activating assertions (skip until the scenario's `flight_log.json` exists, then go live with
  zero edits): `tests/fieldguard_planning/test_safety_scenarios_pending.py` — 4 of the scenarios now
  have logs and are live; the remaining skips are `det_bird_crosses_path`, `det_bird_over_low_ndvi`.

**Flight-log evidence gate — TWO VERSIONS since 2026-08-24 (`scripts/check_live_flight_log.py`)**
- **Legacy path** (log has NO `run` key) — **CLOSED LIST since round 5, 2026-08-24**: ledger validity
  + CPA measured against the LOGGED DETECTIONS, and a log reaches it ONLY if `legacy_pinned(path)`:
  stem in `PRE_SEAM_LEGACY_STEMS` (unanchored — CI copies the two historical logs into tmp trees) or
  the SHAPE `<repo>/eval/scenarios/<name>/flight_log.json`. Anything else with no `run` block is
  INVALID ("fault or tampering"). Note the pin is a property of the FILE, never the contents.
  Tests: `test_check_live_flight_log.py`.
- **Schema-2 path** (`run.schema_version >= 2`, written by `avoidance_node.build_run_block`): clock
  domain + knob floors + R2 swept-tree clearance + R3 degenerate re-latch (R3.7 exhaustion + R3.8
  reject-reading) + detector floor + CPA measured against the BIRD GROUND-TRUTH TRACK on BOTH axes.
  Tests: `test_check_live_flight_log_schema2.py` (160 as of 2026-08-24 round 3).
  A `run` block with an unreadable or sub-2 `schema_version` is INVALID, never demoted to legacy —
  the demotion would be a downgrade attack onto the weaker CPA.
- **The GT-CPA join is TWO passes since round 3** and `gt_cpa_m` is the min over both: pass 1 scores
  each TICK's bird candidates against both bounding drone segments; pass 2 (`pose_windows`) scores
  every landed `set_pose` call against the drone sub-segment its own in-effect window covers. Own
  denominators: `truth coverage K/N ticks` (drone axis) and `truth poses scored K/N` (bird axis) —
  they measure different things and tick coverage reads 100 % regardless.
- **CI evidence-gate config tests**: `tests/test_ci_evidence_gate.py` extracts the real `run:` body
  out of `.github/workflows/ci.yml` (indentation walk, no PyYAML) and executes it. CI's host-side
  discovery is now `-p 'test_*.py'`, not one filename.
- **Truth track** = `scripts/drive_birds.py`'s `eval/results/bird_drive_<stamp>_applied.jsonl`, read
  through `drive_birds.read_applied_log/applied_sim_span` + `annotate_real_clip.applied_timeline/
  pose_from_applied` — the SAME readers the ADR-003 labels use, imported not re-implemented.
  `--truth <path>`, or auto-discovery by sim-span overlap (sidecar-first; exactly one candidate or
  it refuses). No truth track for an `ndvi_blob` flight = INVALID, including when the flight logged
  zero detections: that is what a MISSED bird looks like.
- Detection-derived CPA survives as `detection_cpa_m` + `range_estimate_error_at_cpa_m`, labelled
  ESTIMATOR CHECK, NOT A SAFETY GATE.
- **THE TWO CPA IMPLEMENTATIONS DISAGREE AND THE LEGACY ONE IS OPTIMISTIC (measured 2026-08-26).**
  `closest_approach()` (legacy path) minimises over PATH VERTICES; `ground_truth_cpa` (schema 2)
  minimises over SEGMENTS since G22. Same bytes, both ways: scenario fixtures 7.0000→**0.0000**,
  1.0000→**0.0000**, 0.0000→0.0000, 1.0000→1.0000; historical logs 0.0597→0.0393 and
  0.0518→0.0391. So the closed legacy list is exactly the artifact set still scored by the weaker
  geometry, and `cov_bird_at_turnaround` — the only fixture that PASSES — is a direct hit. See G61.
- Committed flight logs and `bird_drive_*` are gitignore EXCEPTIONS, so tests may read them but
  should skip if absent.
- Degenerate-range / vet-margin regressions off the 2026-08-23 demo:
  `tests/fieldguard_planning/test_degenerate_range_avoidance.py` + `test_degenerate_relatch_refusal.py`.

**Conventions worth reusing**
- `test_CURRENT_*` pins today's behaviour including where it is wrong and names the recommendation
  that must break it. `test_WANT_*` (`@unittest.expectedFailure`) flips to a RED unittest run the
  moment a fix makes it true — but a WANT on a FROZEN artifact can never activate and is a
  permanent xfail wearing a tripwire's clothes; retire those rather than carry them.
- **pytest treats an unexpected success as xpass (not red)** — always also run
  `python3 -m unittest discover -s tests/fieldguard_planning`.
- **Mutation check every new gate** (this is what proved the schema-2 work): copy the gate to
  `scratchpad/`, apply one-line mutations (drop the vertical scoping, gate R3 on the flag instead of
  the number, fall back to detections when truth is missing, waive gates with a marker...),
  pre-import the mutant as the module name the test file imports, run the test module. 12/12 mutants
  killed on 2026-08-24; a surviving mutant is a gate nobody is holding.
- Adversarial fixture rule learned the hard way: a truth track with ONE `set_pose` tick has no
  measured RTF, so its sim bracket collapses to a point and overlaps nothing. Build fixtures with
  >= 2 driver ticks.
- **A/B the SAME artifact against the REAL committed truth track** — this is what found G15/G17.
  Build a node-shaped log with `avoidance_node.build_run_block` + `_params_dict(PolicyParams())`,
  point `check_file(path, truth=...)` at `eval/results/bird_drive_20260823T073836Z_applied.jsonl`
  (860 records, sim 110.408..263.842), then vary ONE input (freeze the tick stamps; drop one bird
  from the truth records; move the tick span before the track's start). A gate that returns a
  different verdict for the same flown path is a gate measuring the wrong thing. Cheap: no ROS 2,
  no Docker, ~1 s.
- **Every counter the node writes but nothing reads is a candidate vacuous-green.** `grep` the
  artifact's field names against the whole repo; if the only hits are the writer's own unit tests,
  the gate cannot see it (that is G16).
- **A counter that reads 0 when it matters is worse than no counter.** Do not check that a counter
  EXISTS; drive the failure it is supposed to witness and read the number. `n_stale_dropped` rides
  `maneuver.debug`, which the executor copies only into accepted-DIVERT events — so the all-stale
  case (PROCEED) reports 0, identical to "no bird was ever seen" (G20).
- **Every numeric BOUND a gate adds needs its denominator interrogated.** Ask what physical quantity
  the harm scales with, not what other constant happens to be nearby. `MAX_FROZEN_TICKS = 5` was
  derived from the 1.0 s staleness bound; the harm is a bad truth join and scales with BIRD SPEED,
  so the permitted residual (5.6 m) exceeds the 3.0 m bar it guards (G19). Probe shape: run the same
  flown path at the bound and one tick under it, and look for a verdict flip.
- **A gate that samples must be asked what it does BETWEEN samples.** `gt_cpa_m` minimises over 5 Hz
  vertices; compare it against a dense recomputation of the same continuous geometry (drone linear
  between logged points, bird held at each teleport pose). The gap is the gate's real softness
  (measured 0.42 m at the bar with a healthy clock, G22).
- **Read a gate's ESCAPE HATCHES, not just its assertions.** An explicit `--truth` skips
  `truth_candidates()` outright, so the "exactly one overlapping log" guard is dead in the runbook's
  own documented invocation (G23). `inspect.getsource` on the resolver is the fastest way to see it.

- **VERIFY A FIX ROUND WITH A SHADOW REPO, never by re-running the fix author's tests.** Build
  `<scratch>/prefixrepo/{scripts/,src->,config->,eval->}`, drop the pre-fix file in `scripts/`, and
  import it as a module: `check_live_flight_log.py` derives `REPO_ROOT` from its own `__file__`, so
  symlinking `src`/`config`/`eval` back to the real repo gives a working pre-fix checker with zero
  edits to the working tree. Same trick for the package: copy `src/fieldguard_planning/*.py` to
  `<scratch>/prepkg/fieldguard_planning/` and swap in the two pre-fix modules. Run the SAME probe
  against both and diff the verdicts. Never `git stash` a working tree you were told not to touch.
- **A "lower bound" claim is falsifiable — falsify it randomly.** For `gt_cpa_m`, generate a few
  hundred random drone polylines x bird step-trajectories, compute the continuous minimum by dense
  sampling of an INDEPENDENT model, and assert `gate <= true + eps`. 300 trials found 0 over-reports
  on the drone axis (G22 closed) and pointed straight at the axis the fix did NOT close: the bird is
  still sampled only at tick instants (G27).
- **Sweep the CADENCE, not just the geometry.** Both surviving CPA gaps (G27, G28) are invisible at
  the nominal 5 Hz and appear as soon as the control tick's SIM period is varied. Any gate carrying
  a rate constant (`CONTROL_HZ`) should be run at 0.12 / 0.2 / 0.5 / 0.7 / 1.0 s per tick and the
  verdict watched for a flip. Reference numbers: 5 Hz wall x measured RTF 0.605 = 0.121 s sim/tick;
  the driver lands 1.84 calls/s/bird = 0.543 s between poses; RTF measured 0.94..0.51 within one take.
- **When a fix converts a BREACH into a REJECT, check where the evidence went.** The round-2 R3 fix
  removed the `maneuver` event that its own new gate (R3.7) reads, and wrote the numbers onto a
  `gate_reject` event nothing parses (G26). Probe shape: sweep hundreds of random encounters through
  the real policy+executor and COUNT how many times the gate's own failure branch can fire.
- **REPRODUCE THE CI ENVIRONMENT BEFORE CLAIMING A CI GLOB IS EMPTY.** Round-3 finding 4 asserted
  "eval/results/ is gitignored, so in CI the glob matches nothing" from reading `.gitignore` line 21
  and stopping. Line 48 re-includes `!eval/results/live_flight_log_*.json` and TWO logs are committed
  under it, so the gate had been running on real evidence every push since 2026-08-23. The premise
  was wrong and the proposed remedy would have been wrong twice. Cost of doing it right: one command
  — `git archive HEAD -o head.tar && tar -x -C <clean dir>`, then run the literal step there. Do this
  for every claim about what CI *sees*, not what the repo *contains*.
- **Test the COMPOSITION of two gates, not just each one.** Round 3 fixed the bird-axis join (F1) and
  the freeze debit (F5) separately; nobody had run them together. Probe: log a FROZEN stamp axis while
  the vehicle and birds keep moving at their TRUE times, then assert
  `gt_cpa_m - freeze_debit_m <= true continuous CPA` or a hard clock fault. 300 trials: 0 violations,
  295 hard clock faults, 5 raw over-reports correctly priced. `scratchpad/qa_compose_probe.py`.
- **A monotone two-pointer join needs interleaved inputs to break.** Pass 2 walks a globally sorted
  window list against a segment list with a pointer that only moves forward. One bird cannot exercise
  it; drive all THREE at different cadences (0.12-1.4 s) so windows interleave, then re-assert the
  lower bound. 200 trials, 0 over-reports. `scratchpad/qa_twopointer_probe.py`.
- **MONKEYPATCH THE ONE CHANGED FUNCTION instead of building a shadow repo.** For a single-function
  fix, reconstruct pre-fix behaviour by rebinding it on the imported module
  (`chk.acknowledgement_problem = prefix_ack`), capture `main()` through
  `redirect_stdout/redirect_stderr`, and byte-compare. Isolates exactly the delta, needs no
  filesystem, and cannot damage the tree. `scratchpad/qa_r4_ack_probe.py`.
  **HARD-WON, 2026-08-24: never `ln -s` into a path under the repo.** `ln -sfn <target> <dir>/eval/results`
  where `<dir>/eval` was already a symlink to the REAL `eval/` created `eval/results/results` inside
  the repo AND replaced `eval/annotate_real_clip.py` with a self-symlink, destroying the file
  (recovered with `git checkout --`, it was tracked and unmodified). Build shadow trees with `cp`,
  or do not build them at all.
- **A ratchet on the ACKNOWLEDGEMENT is not a ratchet on the GATE SELECTION.** After hardening how a
  breach gets forgiven, ask what chooses the strong gate at all and whether its ABSENCE is checked.
  Here: `run` present -> truth-gated CPA; `run` deleted -> legacy detection-referenced CPA -> VALID
  (G34). Probe shape: score one artifact both ways and diff the verdict, changing nothing but the
  selector.
- **REPRODUCE "WHAT CI WILL SEE AFTER THIS COMMIT", not what HEAD contains.** When the whole session
  is uncommitted, `git archive HEAD` reproduces the WRONG tree. Build the post-commit tree instead:
  copy `git ls-files` + `git ls-files --others --exclude-standard` out of the WORKING tree into a
  clean dir (python `shutil.copy2`, ~360 files, <1 s), extract the literal `run:` body of the CI step
  by indentation walk, and `subprocess.run(["bash","-c",step], cwd=tree)`. 2026-08-24 final gate:
  `matched: 2`, both ACKNOWLEDGED, exit 0. Also the only way to catch a marker that is tracked in the
  tree but not re-included by `.gitignore` (`!eval/results/live_flight_log_*.SAFETY_FINDING.md`,
  line 53 — the `*.json` re-include on line 48 does NOT cover it, and without it CI would go red on
  HISTORY the moment a pin without its marker became INVALID).
- **A DOC-DRIFT TRIPWIRE IS ONLY AS WIDE AS ITS FILE LIST.** Round 4 pinned the runbook against
  re-drift (`assertIn("ACKNOWLEDGED_BREACH_STEMS", runbook_text)`) and the same round left
  `ROADMAP.md:127` instructing the operator to do "exactly as the two historical logs did" — i.e.
  the bypass. When a fix's failure mode is documentation, grep the constant across `docs/` and assert
  on EVERY file that tells an operator what to do at that moment, not just the one you edited.
- **TWO PROOFS PER FIX ROUND, both cheap, and they answer different questions.** (1) Rebind the ONE
  changed function to its pre-fix behaviour and re-score the SAME bytes — proves the hole was real
  (round 5: `run_block_problem` rebound to "absent -> legacy" turned the same INVALID artifact back
  into `VALID / CPA NO-CPA-EVIDENCE`). (2) Mutate the SHIPPED file in a `cp` shadow tree and count
  reds — proves a test is holding it. Round-5 mutants, 4/4 killed: ratchet backed out (3 red),
  hold-drift widening backed out (5), fixture-SHAPE half removed (9), STEM half removed (20).
  `scratchpad/qa_r5_probe.py` + `qa_r5_mutation.py`. Note the shadow tree has no `.git`, so
  `test_markers_are_git_allowlisted_so_ci_sees_them` errors there — expected, not a mutant.
- **Back a fix out MECHANICALLY, in a shadow copy, and count which tests go red.** One 30-line script
  copying `scripts/ src/ eval/ tests/ config/ sim/` into a tmp tree and applying a one-line string
  mutation per fix reproduces the whole no-band-aids proof in ~10 s and does not touch the working
  tree. Round 3: F1 5 red, F5 3 red, F7 3 red, F3 1 red, baseline OK. `scratchpad/qa_mutation.py`.

- **DISSECT A BREACH WITHOUT THE CLIP: rebuild the camera geometry from three artifacts.** The
  flight log has positions + `run.detector.intrinsics` (LIVE camera_info) but no orientation; the
  clip's `poses.jsonl` has `quat_wxyz` + `stamp_sim_s` and needs no `meta.json`; the applied log has
  the bird. Join by stamp, then `predict_bird_visibility.look_at_bird` / `frame_geometry` +
  `ndvi_georef.project_world_point` give in-frame / px-outside-edge / miss-in-metres per frame.
  Cross-check that the count of clip frames inside `min..max(tick_stamp_sim_s)` equals the
  detector's `frames_detected_on` — on 2026-08-25 both read **1301**, which also fixes the frame-id
  offset between the two subscribers (clip 964/965 ↔ detector 795/796). Then reconstruct the logged
  detection end-to-end: project the TRUE bird, build the box at the true radius, push it through
  `ndvi_detect.box_to_detection` — it reproduced the flown detections to 0.6-15 cm, and the residual
  is exactly the 0.15/0.18 radius-prior under-ranging (|dz| 4.030 → 3.372 m).
- **RE-RUN THE GATE YOURSELF; the orchestrator's headline may come from an environment you do not
  have.** `check_file(path, truth=..., results_dir=<scratchdir>)` is the only way to point the
  resolver somewhere else — `main()` hard-codes `RESULTS_DIR`, so the CLI cannot. On 2026-08-25 the
  shipped CLI on the real tree printed NO CPA at all (ambiguous truth track short-circuits
  `resolve_truth` → `None`); the quoted numbers only exist with the other applied log out of the way.
- **BEFORE BLAMING THE DETECTOR, COUNT THE FRAMES THE BIRD WAS ACTUALLY IN.** `--backtest` on an
  annotated clip is the same arithmetic and reproduces history: the 2026-08-23 clip scores
  2/5/13 frames-in-view (bird_0/1/2) = 20 total against the detector's 20 detected frames. Recall on
  available frames has been 100 % on both takes; the missed-bird signal is footprint, not sensitivity.

**Run everything (stdlib only, no venv/ROS 2)**
```
python3 -m unittest discover -s tests/fieldguard_planning        # canonical CI job; WANT tests bite here
python3 -m unittest discover -s tests -p 'test_*.py'             # second CI job, host-side (widened round 3)
python3 -m pytest tests/ -q                                       # both at once
```
Baseline 2026-08-24 after ROUND 5 (re-measured independently, both runners): pytest **877 passed /
2 skipped / 0 xfailed / 0 xpassed** (~20 s); unittest discover `-s tests/fieldguard_planning`
**Ran 822, OK (skipped=2)**; host-side `-s tests -t tests -p 'test_*.py'` **Ran 57, OK**
(822 + 57 = 879 = 877 + 2). ROADMAP:56-61 and DECISIONS am. 17 both quote these exact numbers —
verified, no stale figure left in either. Round-4 baseline was 870/2 + 815 + 57.
**Acknowledgement contract as shipped** (`scripts/check_live_flight_log.py`
`acknowledgement_problem`): exit 0 on a breach needs BOTH `<stem>.SAFETY_FINDING.md` AND
`<stem> in ACKNOWLEDGED_BREACH_STEMS`. Probe both paths — legacy AND schema-2 — with five states
(neither / marker only / pin only / both / both + a second gate failure); the fifth must print
"NOT acknowledgeable". Reconstruct pre-fix by rebinding the one function; the hole reproduces as
ACKNOWLEDGED/exit 0 on identical evidence.
**SIXTH state, added 2026-08-25 — probe it every time from now on: marker present + CPA NOT
COMPUTED.** That is the G55 branch, and it is the one an operator meets by default on the committed
tree (truth ambiguity, G47). Expected today: the gate says the log *"does not breach CPA"* and tells
you to **delete the marker** — on a take that flew 0.0067 m from a bird. Reproduce by running the
shipped CLI on `live_flight_log_20260825T210402Z.json` with its marker in place; the correct verdict
is only visible via `check_file(..., results_dir=<scratchdir holding only that take's track>)`.
**MARKER CENSUS (keep current):** three `eval/results/*.SAFETY_FINDING.md` files now. Two are
ACKNOWLEDGED history and pinned (2026-08-18 0.0597 m, 2026-08-23 0.0518 m). The third —
`live_flight_log_20260825T210402Z.SAFETY_FINDING.md`, written 2026-08-25 — is **marker-only by
design** (runbook §6a: after a NEW breach write the marker, do NOT add the pin, the take stands
INVALID/exit 1 until re-flown after R4). `ACKNOWLEDGED_BREACH_STEMS` stays two long. Anyone who
finds it three long without a reviewed ADR amendment has found a defect.
Previous baselines: 860/2/0 after round 3 (805 + 57); 833/2/0 after round 2 (783 + 52). The 2 skips are the self-activating
`test_safety_scenarios_pending.py` ones (`det_bird_crosses_path`, `det_bird_over_low_ndvi`) — still
pending, they go live the moment those scenarios drop a `flight_log.json`.
Earlier baseline for reference: 805/2/0 before the round-2 fixes. (Session start was 530/2/2, both xfails retired/promoted — the tree moved a
lot under concurrent agents, so re-measure rather than quoting a handoff's number.)
Equivalence gate re-verified the same day: `eval/baseline_ndvi.py` on
`eval/results/clips/real_flight_20260823T073644Z` reproduces `adr003_20260823/detections_ndvi.json`
bit-identically (1256 frames / 24 boxes / thresh -0.61) and `eval/score.py` reproduces
`spike_scores.json` exactly, ADOPT included, after the detector moved to
`src/fieldguard_planning/ndvi_detect.py`.

Detection FNR metric everything routes through: `eval/score.py` (`per_bird_track_fnr`).

## BEHAVIOURAL-MUTATION HARNESS (adopted 2026-08-25, use it for every "proven red pre-fix" claim)
A full `git show HEAD:<file>` revert usually yields an **ImportError** — a symbol-absence red, which
proves nothing about behaviour. Instead copy `src/ tests/ config/ scripts/ docs/ eval/*.py
eval/scenarios/` into a scratch dir (skip `eval/results`, it is 12 GB) and apply the SMALLEST
mutation that restores the old BEHAVIOUR while keeping every new symbol exported. Then diff the
failing-test set against an unmutated sandbox baseline (`comm -23`), so a pre-existing sandbox
failure cannot be mistaken for a catch. Mutations that worked on the ADR-016 bundle:
* hysteresis → force `self.resume_clear_ticks = 1` in `AvoidanceExecutor.__init__` (6 tests red,
  incl. `test_a_single_empty_frame_does_not_resume`);
* predictor → `--speed` `default=REFERENCE_SPEED_MPS` (3 red) and, separately, the verdict line
  back to `{v['statistic']}` without the speed (1 red);
* swath → `DEFAULT_SWATH_HALF_WIDTH_M = 7.5` (2 red) and the wrong image axis
  `image_width_px` in `derive_swath_half_width_m` (4 red);
* MIS_RESTART → `git show HEAD:config/sitl_params/dds_udp.parm` (1 red, right message) and dropping
  `--add-param-file` from `scripts/run_farm_mission.sh` (site subTest red).
**REVIEWING AN OFFLINE PIXEL STUDY (criterion-2 RGB study, 2026-08-26) — the three probes that
mattered.** (1) *Re-pick the frames yourself.* The band-independence check only ran on 2 bird frames
per clip; re-running the NDVI inversion `n = (R/255)(1+NDVI)/(1-NDVI)` on frames I chose (first,
quartiles, last, plus non-bird ones) is what showed it collapses **93 distinct R x 144 distinct NDVI
-> 3 distinct rho_nir**. That collapse is the actual proof the bands are shared; my first objection
(a flat-shaded world would collapse trivially) was REFUTED by measuring the input diversity, so
measure it before raising it. The code clinches it anyway: `ndvi_fusion.rescale_red` is
`red_u8/255.0`. (2) *Check whether "authored" means authored.* The three reconstructed values are
`gate2_summary.json`'s `mean_rho_nir` (MEASURED: 0.040333/0.211666/0.854167), not its
`calibrated_rho_nir` (AUTHORED: 0.05/0.20/0.85) — a self-consistency check wearing an independent
check's label. (3) *Run the detector on the runner-up feature.* GRVI ranks **8th of 12** on the
study's own pixel table (ExG and G-B dominate it on both axes), which looks damning until you run
them through the same blob detector: G-B gives per-bird-track FNR **0.333** (loses a whole bird)
while GRVI gives 0.000, and ExG ties GRVI. **Pixel-level dominance is not detector-level safety** —
always re-run the arm, never rank features off the table alone.

**PHASE MATTERS in any "at most one X per tick" test (2026-08-26).** The pin for the GUIDED
ceiling's double `set_mode` nearly shipped vacuous: with a 1-in-3 duty cycle the DIVERT ticks are
1, 4, 7 ..., so only a ceiling ≡ 1 mod 3 expires ON a DIVERT tick and exposes the defect. Measured
against the broken placement: ceiling 9 -> max 1 switch/tick (PASSES), 10 -> 2 (catches), 11 -> 1
(PASSES), 310 -> 2 (catches). The shipped test asserts `ceiling % 3 == 1` inline and runs two such
ceilings. Whenever a test drives a periodic stream to a threshold, state the phase relationship as
an assertion, and sweep every residue before believing a green.

**Re-derive evidence figures in the test, never quote them.** `GUIDED_CEILING_TICKS` is sized at
5 x the longest GUIDED window ever flown; the test now globs `eval/results/live_flight_log_*.json`,
pairs takeover->resume and counts INCLUSIVELY (the same count `_ticks_in_guided()` reports), giving
62 -- not the 61 a delta gives. Both mutations go red: undersizing the ceiling to 5*61, and
reverting the derivation to the exclusive count.

**The mutations that found NOTHING are the finding:** `avoidance_node.py:431` swath back to `7.5`
and deleting `gen_boustrophedon.py`'s strip report both break ZERO tests (see G59).

**Suite baselines measured 2026-08-25 on the ADR-016 bundle** (all three runners, host python3.9):
`pytest tests -q` → 942 passed / 1 failed / 2 skipped; `unittest discover -s tests/fieldguard_planning`
→ 852 OK / 2 skipped; `unittest discover -s tests -p 'test_*.py'` → 93 run / 1 failure. The single
failure in both top-level runners is the pre-registered
`test_ci_evidence_gate.TestLiveFlightLogGateHasEvidence.test_step_passes_on_the_committed_evidence`
(the 08-25 take is INVALID by design). Note `pytest tests` and `unittest discover -s tests` are NOT
the same population — pytest collects the fieldguard_planning subtree too; quote which you ran.

**Scenario-fixture regeneration check** (`python3 eval/scenarios/generate_flight_logs.py`): it is
byte-idempotent, so re-run it and `shasum -a 256 eval/scenarios/*/flight_log.json` before/after to
prove a claimed regeneration is deterministic. To prove a regeneration is EVENTS-ONLY, compare each
top-level key's `sha256(json.dumps(..., sort_keys=True))` against `git show HEAD:<path>` — the
2026-08-25 hysteresis regeneration changed `events` alone (resume shifted exactly +2 ticks, 2
`resume_pending` proceeds added per scenario; `coverage_ledger`/`flown_path_enu`/`requeue_events`/
`swath_half_width_m` identical, debt 144/720 in all four). Do NOT compare gate output by copying
logs to a scratch path: `check_live_flight_log.py` whitelists `eval/scenarios/*/flight_log.json`
by path (`PRE_SEAM_LEGACY_STEMS`), so a moved copy fails "NO 'run' BLOCK" for the wrong reason.

## REVIEWING AN OFFLINE STUDY TOOL (added 2026-08-26, from the point-mass confound-resolver)
A study in `eval/` has no pass/fail bar, so the usual gate probes do not apply. What worked:
- **Write the reference side yourself.** A model verified against ANOTHER function in the same
  module proves consistency, not correctness. For `eval/point_mass.py` I wrote a from-scratch
  `a = min(j*t, a_max)`, v-clipped, 200 k-step integrator and compared: 7.5e-6 relative on all
  three plants. That is what makes "the physics is fine" a finding instead of a shrug. Then assert
  `simulate() <= max_displacement_m()` (the bound must hold) and halve `integration_dt_s` to show
  convergence. `scratchpad/probe_physics.py`.
- **Follow EVERY provenance URL, at the pinned SHA, with `curl`.** Six of seven constants were
  exactly where the comment said (`AC_WPNav.cpp:8` WP_SPD_DEFAULT 10.0, `AC_WPNav.h:15`
  WPNAV_ACCELERATION_MS 2.5, `AC_PosControl.h:19/20/25-30`, `AC_PosControl.cpp:63`
  POSCONTROL_NE_POS_P 1.0, `mode_guided.cpp:252-260` pva_control_start,
  `Parameters.cpp:825` GUID_OPTIONS default 0, `mode.h:1213` WPNavUsedForPosControl = 1<<6). The
  seventh, ANGLE_MAX, cited a header that does not contain the string (G70). One `curl` each.
- **Also fetch the params the SIM applies that the repo does not contain.**
  `sim_vehicle.py -f gazebo-iris` loads `Tools/autotest/default_params/{copter,gazebo-iris}.parm`
  BEFORE `--add-param-file`. Neither sets WPNAV_*/PSC_*/GUID_*/ANGLE_MAX at 9895756d — checked, so
  the firmware code defaults really did fly. A repo-only `.parm` scan cannot tell you this (G68).
- **Ask what the tool does with FEWER inputs than expected, not just more.** The replay refuses
  loudly on 2 encounters and silently drops 0 (G64). Probe shape: delete the `resume` event from a
  real log, run the CLI on it alone, read the exit code and grep the artifact for the log's name.
- **When a metric is vertically or otherwise SCOPED, recompute it unscoped per row.** The scoped
  CPA said 14.34 m; the unscoped minimum to the same bird was 0.014 m (G63). The tool already
  computed the unscoped number and threw it away — grep the artifact for fields nothing reads.
- **Sweep the estimator's own window, not just the model's parameters.** `velocity_at`'s 0.6 s
  window on a staircase log gave a 3.3x spread in entry speed and a 26 m swing in the hypothesis
  built on it (G66). Any least-squares-over-a-window helper deserves this.
- **Cross-check a robustness sweep's winning cell against a physical bound.** The tick-period sweep
  reported its best fit at a dt implying a 17.6 m/s cruise against a 10 m/s velocity cap (G67).
- **Behavioural mutants for a study**: 15 applied to `eval/point_mass.py` + `eval/replay_point_mass.py`
  in a `cp` sandbox (`scratchpad/build_sandbox.py` + `run_mut.py`), 13 killed. The killers worth
  reusing: forward-Euler on velocity or position (2 red — the trapezoid pin is real), `(v_des-v)/dt`
  bang-bang accel (4 red incl. `test_the_approach_does_not_limit_cycle`), plain-P position law
  (1 red), per-axis instead of vector accel cap (2 red), dropping the jerk ramp from the closed form
  (2 red), each plant constant (1 red). **The two survivors ARE the findings**: dropping
  `and r["setpoint_legal"]` from `_cf_summary`, and neutering `_tuning_override_scan`.
- **Prove a run-time "CHECKED, not asserted" scan actually fires** — write the trigger file into the
  SANDBOX (never the real `config/`), sweep the syntaxes a real `.parm` uses (space, comma, equals,
  tab, indented, lowercase, trailing comment), and delete it. An if/else test that passes on both
  branches proves nothing.

**Live tick rate, for any test that divides by `CONTROL_HZ`:** the flown median sim-time tick dt is
**0.160 s (6.25 ticks/sim-s)**, not the nominal 0.200 — measured from
`eval/results/live_flight_log_20260825T210402Z.json`'s `run.tick_stamp_sim_s` (1855 deltas, p05
0.063, p95 0.186, max 0.253). Any "N ticks = N/5 seconds" claim is ~25 % optimistic (G58).

## ADR-019 forward depth sensor — reusable probes (built 2026-08-26 review)

Host-only, all ~seconds, no container. Everything below reproduced against the uncommitted build;
gaps they exposed are G78-G89 in [[project-open-safety-gaps]].

- **Exit-contract collision probe (the one that matters):**
  `python3 scripts/predict_forward_lead.py --sweep 2:10:1; echo $?` -> **0**, the tool's own
  `EXIT_PASS_BOOKABLE`, on config-only inputs. Compare `--speed 5.0` -> 3. Any tool with a mode
  switch that shares an exit-code namespace deserves this two-line probe.
- **Unbounded "live" override probe:** `--speed 5 --fx 520.0058 --acq-range-m 100` -> exit 0
  BOOKABLE on a 60 m far clip. Then `--acq-range-m inf`, `--speed nan|inf|0|-10`. A flag that
  launders config into "live" by its mere presence is honour-system, not a gate.
- **Mutation set for a mount extrinsic (4 mutants, all killed, ~10 s):** swap the composition ORDER
  in `optical_to_body_matrix` (`OPTICAL_TO_SENSOR @ R` instead of `R @ OPTICAL_TO_SENSOR`) — this is
  the good one, because at the FORWARD mount's identity rpy both orders agree, so it is caught ONLY
  by the nadir cross-check `test_formula_reproduces_the_live_verified_nadir_extrinsic` + the static
  gate. That is the proof the cross-check is load-bearing rather than decorative. Also:
  `OPTICAL_TO_SENSOR = I`; `band_covered_from_m` -> `cy/fy`; `margin` -> the lenient form;
  `bookable = passed`. Back up to scratchpad and `cp` back — two of the three files are untracked,
  so `git checkout` will not restore them.
- **Vacuity probe for any "two functions cross-check each other" claim:** replace the primitive with
  a monotone-but-wrong body (`return 3.0*t*t` for `max_displacement_m`) and see whether the
  cross-check test stays green. It did (G80) — `time_to_displace_s` is bisection ON
  `max_displacement_m`, so they are one function.
- **2.0 px resolvability floor, re-measured independently:** filled disc on a 61x61 grid through
  `ndvi_detect.detect_blobs(mask, 6, 5000)`, sub-pixel offsets swept 0..0.5 in 0.02 steps in both
  axes (676 placements, the full fundamental domain by lattice symmetry). r=2.00 survives every
  placement, r=1.99 fails at (0,0). The builder's constant reproduces exactly and is if anything
  slightly conservative. Note the floor is measured against the NDVI detector's morphology for a
  segmenter that does not exist yet.
- **World byte-reproducibility:** `python3 scripts/gen_farm_world.py --world-out $SCRATCH/regen.sdf
  --obstacles-out $SCRATCH/regen_obstacles.json` then `diff`. ALWAYS pass `--obstacles-out` to a
  scratch path: the generator rewrites `config/static_obstacles.json` in place by default.
- **gz source citations are checkable in ~60 s** and were all correct at the pinned branches:
  `curl raw.githubusercontent.com/gazebosim/gz-sensors/gz-sensors8/src/{CameraSensor,DepthCameraSensor}.cc`
  and `gz-rendering/gz-rendering8/ogre2/src/{Ogre2DepthCamera.cc,media/materials/programs/GLSL/depth_camera_fs.glsl}`.
  Verified: `CameraSensor.cc:662-676` pops the last `<topic>` segment; `DepthCameraSensor.cc:249`
  calls base `Sensor::Load` (never `CameraSensor::Load`, so `<camera_info_topic>` is dead for this
  type); `:401` `SetAntiAliasing(2)` hardcoded with a `\todo`; `:561` `Update()` early-returns on
  `!HasDepthConnections() && !HasPointConnections()`; the point-cloud publisher IS advertised
  unconditionally at Load; `Ogre2DepthCamera.cc:103,106` `dataMaxVal=+INF_D / dataMinVal=-INF_D`;
  the shader stores `point.x = -viewSpacePos.z` (Z-depth) and culls on `length(point) > far` —
  Euclidean far, but Z-depth NEAR (`point.x < near`), an asymmetry the config does not mention.
  Consequence worth keeping: the effective far horizon is `60/|ray_dir|`, so **47.6 m at the frame
  corner** against a 46.80 m acquisition bound — 1.6 % margin, not the 22 % the on-axis reading
  suggests.

### Probe hygiene: `__pycache__` can serve a stale mutant (learned the hard way 2026-08-26)

**Always run mutation rounds with `PYTHONDONTWRITEBYTECODE=1`, or `find src -name __pycache__ -exec
rm -rf {} +` between mutants.** Two of my depth-sensor mutations were same-byte-length edits
(`fy_px / cy_px` -> `cy_px / fy_px`; `= 2.0` -> `= 1.8`) applied within the same mtime second as the
restore, so CPython's (mtime-seconds, size) pyc-invalidation check considered the cached bytecode
valid and the gate ran the PREVIOUS mutant. It produced a plausible, wrong "the gate catches this"
result twice. **The tell that saved it: measure the CLEAN baseline's failure count inside the same
probe** — mine came back 1 when it should have been 0. Every mutation harness in this repo should
print the unmutated baseline first and assert it is green.
