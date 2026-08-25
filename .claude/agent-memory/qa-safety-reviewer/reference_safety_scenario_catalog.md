---
name: reference-safety-scenario-catalog
description: Where the SwathKeeper safety scenarios, regression files, flight-log gates (legacy + schema 2) and truth-track evidence live, and how to run them
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
