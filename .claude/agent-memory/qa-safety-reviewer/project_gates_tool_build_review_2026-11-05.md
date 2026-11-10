---
name: gates-tool-build-review-2026-11-05
description: QA rounds on the BUILT swathkeeper_gates — G228-G325 (step 2, step 5, README, v0.2.0 G257 rule round 7); 5 blockers (window adjacency, sub-floor skips, no-measurement channels, B7 over holes, antimeridian), measured on real + mutated logs
metadata:
  type: project
---

Reviewed 2026-11-05 (UTC date already 2026-11-06), build of docs/design/GATES_TOOL_DESIGN.md rev 2. Continues
[[gates-tool-design-review-2026-11-05]] (G211-G227). Gaps G228-G254.

**Blockers (each reproduced, observed vs expected):**
- G228 adjacent scope windows ([a,b),[b,c) for two in-scope modes) split B6 segments (`prev[2]==w`) and B5 runs:
  concave chord on the mode switch PASS margin 10.001 m (control FAILs); 8 s outage reads 4.0 s PASS.
- G229 interior skips under the 1 s floor invisible: zeroing ONE MODE row on the Tarot -> B7 PASS, B2 NA "measured";
  zeroing 20 kB -> `gates: pass 8/8` exit 0, bytes_skipped 20,022. Clean logs' bytes_skipped (10/51/24) are ALL tail
  bytes (QA walker: 0 interior skips), so one number conflates tail junk with lost rows.
- G230 no-measurement channels judged as values: Plane GPS Status 0 / 0 sats on all 263 rows, a speed ceiling reads
  `gates: pass 1/1` exit 0 (1.749 m/s); Plane XKF4 SS=0, FS=128 on all 2,638 rows -> committed B4 PASS. With the
  Plane's 3 reds declared, the run exits 0 `pass` and its only PASS is that B4 (G241: needs >=1 MUST PASS).
- G231 B7 checks holes only BETWEEN MODE rows: an 11.4 s hole after the last MODE row -> PASS.
- G232 antimeridian: square straddling lon 180, track 300 m outside -> PASS +100 m.

**Measured, re-derivable:** Tarot numbers agree to 3 dp via raw pymavlink + struct (2.421/591, 23.482/1419, 0.009/1420,
115.743, 140.333 = last DSF 850.516509 - first 710.1837). Tarot B1's worst sample is PRE-HOME (709.279 s < ORGN 709.379).
Tarot LOG_BACKEND_TYPE 1. Plane STABILIZE entered with MODE.Rsn 2 (GCS command) -> its B7 FAIL is author-constructed.
YAML 1.1: `022`->18, `1:00`->60, `0x12`, `1_8.6` all load. Committed verdicts reproduce byte-for-byte on results.
18 of 26 QA mutants survive (Q5 alone flips the Plane's headline B5 FAIL to PASS with 42/42 tests green).

**Method that worked (reuse):** shadow tree under scratchpad (rsync src/swathkeeper_gates + test_gates_*.py, symlink
src/fieldguard_planning) — tests insert REPO_ROOT/src first so the shadow wins; never mutate the repo. Run probes with
`python -I -B` so no __pycache__ lands in tests/. Own DataFlash walker (FMT 0x80, 89 B) for byte surgery: rename an FMT
name (DSF->DSX, ERR->ERX) to strip a type without changing lengths.

**Why:** the tool's verdict is the product; each blocker is a green a stranger would publish.
**How to apply:** next round, re-run qa/probes.py, geo_probes.py, yaml_probes.py and the m1-m9 Tarot copies as the
red-first set; check the fixes add a regression per G and that G243's outward-copy corrections landed.

## Round 2 (re-check of the fix round, 2026-11-05 local / 2026-11-06 UTC) — G255-G265, verdict DO NOT SHIP until G255+G256
All 27 first-round G's re-probed CLOSED (G242/G245 = deletions, closed by grep). Committed verdicts reproduce
key-for-key; Tarot B1 re-derived 0.014676 m @709.479, n 1418 (2 pre-home: 709.2787, 709.3787 < ORGN 709.3792).
Byte accounting interior+trailing == size - decoded on 3 fixtures + 8 mutants (QA walker). 51 tests 0 skips both runners.
- G255 MAJOR safety: `_run_end` `b >= prev` cuts the first in-scope GNSS run after a hole that ENDS at that row:
  5.0 s outage reads PASS 4.800 vs max 4.9 (gap ends at scope start; same-tick stamps = SITL lockstep). Fix
  `prev <= a < nxt` verified in shadow (FAIL 5.0, suite green). Probe qa/r2/runend.py.
- G256 MAJOR vacuous green: instance with EVERY row filtered (XKF4 core 1 SS 0; GPS inst 1 never fixed) vanishes ->
  PASS on the rest; ONE measured row -> EI. Result note never names exclusions (stream note only). qa/r2/core.py.
- G257 MAJOR open item: Dp-rise intervals excluded by B8 only; B7 (MODE = critical block, lost only via counted drops)
  and every series bar judge across them silently. Tarot Dp 0->15 in [709.278,710.184] holds the first MODE row;
  cadence shows no contract-row loss there. Recommend per-result note + ADR line for v1.
- MINOR: G258 B7 ignores the >1 s mode prefix (PASS while neighbour bar says "mode unknown 8 s"); G259 four
  surviving boundary mutants (Status>=2, prefix >=, point-hole x>a, B8 n w/o holes); G260 gnss gaps in log_holes
  turn a GPS dropout into all-EI; G261 Tarot header "twelve pairs" (draft had SIX), test.BIN "1.05 s" vs
  duration_s 0.974661; G262 FMT cols>format -> IndexError internal error; G263 import wall exact-match only
  (concat/strip bypass); G264 CLAUDE.md ratio 3.84 stale (now 27,101/8,123 = 3.34); G265 record before a byte
  skip decoded with garbage (half-zeroed POS -> fence FAIL; red, never green).
**Lesson:** the first-round report's non-blocker G list was not saved — save every G one-liner next time.
Builder's 103/103 is true of its own mutant set; 5 of my 8 boundary mutants survived (HM4-HM8).

## Round 3 — option C step 5 (ADR-023 am. 1: Action + badge + `gates-tool` CI job), reviewed 2026-11-05 — G266-G276
Commit 663e40c on feat/gates-tool-action. Verdict: NOT DONE until G266 (+G267, G268).
- G266 BLOCKER vacuous: checker diffs results{id,verdict,n}+badge+exit = 26 of 363 Tarot leaves. Fabricated committed
  measured (B2 2.421->12.4, a number ADR-023 publishes), bar.limit, severity, note, integrity.drop_intervals erased,
  verdict.bars.sha256 zeroed, streams state -> all rc 0. Fresh 3.10 vs committed 3.12 differ in ONLY source.path +
  tool.python (also allowlist.run_date_utc on another day) -> full diff minus those 3 keys is free.
- G267 MAJOR: edit bars.yaml (B2 12.5->50) + recompute sidecar bars_sha256, verdict.json untouched -> green; the checker
  docstring ("a sidecar re-registered after the fact fails here") and the test-class docstring ("the one artifact") are false.
- G268 MAJOR: run.sh reads badge from a STALE --out when the tool exits w/o writing (argparse refusal on LOG=-flight.bin,
  read-only verdict.json): outputs exit-code=2 badge "gates: pass · 8/8". Fix rm -f "$OUT" first, --log="$LOG".
- MINOR: G269 empty input -> exit 1, no outputs; G270 newline in OUT injects GITHUB_OUTPUT lines (exit-code=0 appended);
  G271 denominator = count of SOURCE.json (dir w/o SOURCE.json slips both gates; tarot dir = plane copy -> 3/3);
  G272 file:// url fetched under the job's curl flags, 8-hex short SHAs in urls; G273 17/38 mutants survive the new
  tests (size-only sha check, process-rc half, prereg/refusal/3-way-pin checks, plane assertion `|| true`, curl -f regex
  satisfied by a COMMENT, badge colours fail/cnt->green); G274 escape() leaves `"` -> label quote breaks SVG.
- NOTE: G275 claims clean of vehicle-safety wording; "every committed verdict"/"cannot drift from the number" overstate
  until G266. G276 CI-only semantics (composite outputs on failure self-tested by the plane assertion; fail-safe).
**Method (reuse):** qa5/tools/{mut.py,tmut.py,probes.py,fulldiff.py} in the session scratchpad; independent shadow git
repo (rsync minus .venv/.git, `git init`) so `_tracked` works; remote-use simulated by `git archive HEAD` into
`_actions/<owner>/<repo>/<ref>/` + offline `uv pip install`. Leaf-level full diff is the cheapest killer of projection gates.

## Round 4 — re-attack of the step-5 fix 9b355fa (2026-11-05) — G277-G281; G266-G274 CLOSED as designed
- G277 MAJOR: leaf diff over PARSED JSON with Python == is laundered from the committed side: duplicate keys
  (json.loads keeps the LAST; the file shows the false value first: measured 12.4, alt_floor EI, a fail badge), smuggled
  path-collision keys ("results[1].measured", "integrity.dsf_dropped_max" at top level), types (1418.0, exit false),
  dropped/retyped empty containers -> all rc 0. Fix proven in shadow: committed text == json.dumps(fresh w/ excluded
  leaves carried over, indent=1)+"\n" (all 9 committed JSON files are already canonical) -> 12/13 red, control green.
  Write mutants with the tool's serialisation (ensure_ascii=True) or the byte check "catches" them for the wrong reason.
- MINOR: G278 excluded leaves are free text (tool.python "…certified safe", source.path) and droppable; the four are the
  right four (only source.path + tool.python differ 3.10 vs 3.12) -> pattern-check them, fetch to the url basename.
  G279 PINNED_URL passes `<40hex>/../master/x.bin` (curl squashes it to a BRANCH path, url_effective verified), any owner,
  ?query#frag. G280 extra files inside an example dir unchecked. G281 8/33 new source mutants survive (EXCLUDED widened
  by a non-measured key, committed-extra-leaf, ABSENT==None, short-sha url, stale-refuse line, badge flatten, `"` escape,
  demo --proto-redir); 3 round-1 survivors are equivalent (size-only, fresh-prereg, zero-examples).
**Lesson:** a projection gate fixed to a full leaf diff still trusts the parser; the cheapest complete gate is BYTES.

## Round 5 — sign-off pass on 53228e1 (2026-11-05) — G282-G286; G277-G281 CLOSED
- All 17 + 16 + url mutants red on the checker except extra-file (caught by the G280 tree test). The byte gate holds
  against dup keys, smuggled keys, types, empty containers, BOM, upper-hex.
- G282 MINOR: "byte-identical" is really text-identical. `Path.read_text()` uses universal newlines, so CRLF and lone-CR
  verdict files pass the checker AND the tree test. Fix: read_bytes().decode("utf-8").
- G283 MINOR: the shapes accept python 3.8.0 / 3.99.999, PyYAML 6.0 (below the >=6.0.3 pin), date 9999-99-99.
  Want: ^3\.(10|12)\.\d+$, a fresh value that matches the matrix leg, a PEP 440 check against the range, a real date.
- G284 MINOR (the residual by design, now reproduced): a tool bug committed together with regenerated verdicts is
  green. I halved every `measured` in an installed scratch copy and regenerated -> 3/3 rc 0, and Tarot B3 then reads
  PASS with min 11.74 V under an 18.6 V floor. Cheap fixes: a semantic check (PASS => measured on the right side of the
  limit) and a tree test pinning ADR-023's published values.
- NOTE: the checker alone accepts any owner and Unicode `\w` homoglyphs; only the tree test's exact url pin catches them.
**Method:** qa7/tools/{mut3.py, treemut.py, wrongtool.py}. mut.run now builds fetched/<name>/<url basename>.

## Round 6 — the package README `src/swathkeeper_gates/README.md` before step 6 (2026-11-09) — G286-G307
Verdict SHIP-AFTER-FIXES. Measured with the stranger venv (ecbe20c) on tarot/plane + in-process FlightLog mutation.
- G286 BLOCKER: `@main` install + Action fail TODAY (main 5a31261 has no pyproject; PRs #39/#40 OPEN; uv rc 1). The
  README's outputs came from ref feat/gates-tool-action, not @main. Gate the posts on the merge order.
- G287 BLOCKER: decision rules omit two `j["blind"]` EI causes (mode unknown >1.0 s before first MODE row; no POS/GPS/BAT
  witness). FIRES ON A COMMITTED LOG: plane.bin prefix 1.281 s -> any mode-scoped bar and B7 `[*,*]` read EI.
- MAJOR: G288 armed:true is EI on 3/3 public logs (scope reaches before first ARM row; by the adapter's own citation,
  on essentially every log); G289 ERR EMPTY is a lead RULING for any vehicle/any 4.5.n, README calls it a citation;
  G290 FENCE polygon bit/min-alt never judged; G291 G257's cost (Tarot -> could not tell) dropped; G292 "the method that
  caught that" (2 of 3 breaches flew under green gates); G293 Tarot bars re-registered after a registered verdict,
  sidecar+verdict committed together, "142 s low hover" clause dropped; G294 n is segments/transitions/seconds, not
  samples; G295 exit row 0 matched by a vacuous run (exit 1); G296 an unpinned after-the-fact sidecar gets the CLEANEST badge.
- MINOR G297-G307: `sha256sum -c` (use `-c -`), uv needs a venv, inspect-vs-run message, no_errors note variant,
  "byte for byte" minus 3 leaves / 363 vs CI's 391, badge counts matched only, "Never run on" mood, Action lacks checkout,
  gnss span wording, pyproject readme links break in METADATA.
**Method (reuse):** probe in-process with `swathkeeper_gates.adapters.load` + `copy.deepcopy(log)` and mutate one
stream (shift MODE t_s[0], set raw streams ABSENT) — cheaper than byte surgery for decision-order claims. Diff the
README's own code blocks against a literal re-run (sed the yaml block out, sha it, run it).
- Round 6b re-check (2026-11-09, README now 264 lines): 20/22 CLOSED, G286 copy closed but merge-order gated, G288 OPEN
  (test.BIN has NO ARM rows, not "only the disarm"). NEW: G308 MAJOR `python3 -m venv` on stock macOS = Xcode 3.9.6 <
  requires-python 3.10; G309 MINOR "pre-registered to fail" (it said MAY fail); G310 MINOR Plane mode-bar numbers are a
  QA probe not a committed verdict, "base range" undefined. Walkthrough re-run: all 5 outputs byte-identical, yaml 185074…

## Round 7 — v0.2.0 G257 "flip" (uncommitted, feat/gates-tool-dp-rule), 2026-11-10 — G311-G325, DO NOT SHIP until G311+G312
Rule: per DSF.Dp interval [a,b] the mode is unsure over U=[a, first MODE row > b); R1 B7 skips spanning transitions + blind;
R2 sure/wide double pass (FAIL iff sure FAIL, PASS iff both); R3 armed EI if a drop ends after first ARM row.
- G311 BLOCKER false green: U is clipped to the OBSERVED armed base (wide pass + `_judge` gate), but arming before the
  first ARM row is ABSENT (rule 4). Drop before first ARM, mode in U unknown -> PASS / NA where truth can FAIL (P1:
  lone-DISARM-first then ARM = LOG_DISARMED=0 re-arm; P1c ARM+DISARM both dropped). Builder's `early` subtests PIN it.
  Fix proven (qa311/fixG311b): wide U clipped to [t0,t1), gate on armed U [t0,first) -> only those 2 subtests red,
  0 verdict changes on 8 corpus drop logs x ~25 bars. Deviation (b)'s rationale is backwards.
- G312 BLOCKER false green, REGRESSION, real public log 01: R1 throws away a CERTAIN violation (entering a mode no
  allowed pair enters, observed MODE row) when `from` spans a drop -> should-bar FAIL -> EI -> run exit 1 -> 0 "pass".
  Fix: judge a spanning transition on `to` alone (no (f,to) allowed => FAIL). The v0.1 byte-hole test (Q7, line ~220)
  pins the same information loss across holes.
- MAJOR: G313 same-tick (MODE/ARM row stamped AT a or b) R1 half-open vs unsure()'s t>b; R3 b==first PASS; file order
  resolves it. G314 byte holes hide MODE rows too, never fed to unsure() (pre-existing, PASS). G315 multi-interval
  untested (M16/M17 survive; 03/08/09 carry 2-3). G316 zero-length [t0,t0] untested (M18/M19 survive; 08/09).
  G317 M1 (R3 straddle), M7 (B7 blind over windows), M12 (gate on drop not U) survive, each EI->PASS. G318 PASS prints
  the SURE (optimistic) worst. G319 package README still v0.1 (Version 0.1.0, judged-across rule, Tarot pass 8/8 exit 0).
  G320 R1 blindness fires on `[["*","*"]]` -> all 5 orchestrator-measured flips are on a tautology (truth PASS).
  G321 R5: DSF-absent logs PASS silently (2/6 corpus) with no "loss not measured" note.
- MINOR: G322 B7 FAIL note "startup judged" when skipped; G323 negative Dp interval "-5 writes"; G324 notes lost
  (M9/M10/M20); G325 CI no longer exercises the Action's success path on a real log.
Re-derived with raw pymavlink (qa311/tools/rederive.py): Tarot 591/709/2.421, 01 817/1047/9.581, 08 216/272/1.042,
09 194/693/1.124, 14 965/1136 -- all equal the tool. Examples: 3/3 byte-reproduce on fetched_0110 (checker rc 0).
Drop-free regression: 0 changes over ~140 extended bars on 8 drop-free corpus logs + builder panel.
**Method:** qa311/{shadow,v010 (git archive HEAD src + current tests),mutA,fixG311b,fixG312}; probes p1-p4 + ext.py.
**Lesson:** a sure/wide soundness proof is only as good as the BASE it clips to -- check every clip against the
contract's own ABSENT rules; and "skip what is unsure" can discard what is CERTAIN (the `to` of an observed row).

## Round 8 — re-check of the G311-G325 fixes (2026-11-10) — G326-G333; SHIP-AFTER-FIXES (G326 + G319)
CLOSED: G311-G318, G320-G325 (all round-1 repros re-run; log 01 B7 FAIL exit 1 again; 26/28 mutants killed incl.
re-anchored M1/M2/M7/M9/M10/M12/M13/M16-M20). G255 mutant still dies on the rescoped (unscoped) pin. OPEN: G319 README.
- G326 BLOCKER false green: B7 case (iii) (some lost `from` allowed, some not) is skipped, but blindness only fires for
  losses in BASE -- an armed B7 + mode scope whose cutting loss is outside the armed base (hole in a disarmed stretch,
  or a drop before the first ARM row) reads PASS. Fix proven (qa326/fixG326): (iii) appends the cut to j["blind"];
  suite green, 0 changes over 312 corpus bars.
- G327 MAJOR (pre-existing, the R3 ruling): armed_windows trusts the ARM sequence; DISARM, [hole], DISARM (LOG_DISARMED=0
  re-arm refused) leaves the 2nd flight "disarmed" -> PASS. Corpus: 0/15 same-state pairs, 1/15 hole after first ARM.
- MINOR: G329 PASS note lead quotes the sure worst while measured is the wide one; G330 UNKNOWN(n) never a candidate
  `from`; G331 Ni (B7 [*,*] across a hole) + Nm (Dp reset to 0) unpinned; G332 CI walkthrough pins input not output.

## Round 9 — sign-off on the G257 drop rule commit (2026-11-10) — G334-G338; SHIP (KNOWN-OPEN G327, G333)
G326/G329/G330/G331/G332 CLOSED (N1/N2 EI, control PASS; unscoped (iii)/(ii) neighbours EI; log 01 FAIL exit 1;
walkthrough re-run on 0.2.0 byte-identical to README incl. inspect 5,635 B; 3/3 examples byte-reproduce). G319 CLOSED
(README rewritten) with minors. "<start>" deletion from G320's check is EQUIVALENT: not ok(<start>,b) => not
ok(UNKNOWN(?),b) since the sentinel matches only "*" (its mutant survives, as an equivalent must).
- G334 MINOR test gap: sentinel removed from the three-way candidates only survives; non-equivalent (armed B7[LOITER],
  enumerated allowed set, hole outside base: PASS vs EI).
- G335 MINOR: DSF-ABSENT note "judged as if no MODE or ARM row was lost" sits beside "a log hole may hide a MODE row"
  on the same result; README "the verdict is unchanged" is false when the log has a hole.
- G336 MINOR README: blind list (c) omits the G326 cause; rule 5 "a log hole in scope -> EI" false for a [*,*] B7.
- G337 MINOR README: "has run on exactly the three public logs" / "never exercised on a mid-flight Dp rise" are false
  after the 40-log corpus probe (log 03 has Dp rises at 129 s and 208 s); install line still names 0.1.0 (dated).
- G338 commit hygiene: stage root README.md (badge) with it; the other session's fieldguard_planning, check_live_
  flight_log.py, fly_pipeline.sh, dashboard/data/field.json and tests/fieldguard_planning must stay out.

## Round 10 — the DECLARED arming assumption (uncommitted on 9e42cfa), 2026-11-10 — G339-G342; SHIP-AFTER-FIXES (G339)
Rule: `assume: [arming_before_first_arm_row]` -> prefix = opposite of first ARM row; U_arm = same-state pairs + [a, next
row > b) for losses with b >= t_1 + (key only) [t0, b_max] for losses with a < t_1; sure/wide combine; B7 blind if differ.
- G339 MAJOR same-tick: `pre` uses a < t_1. A loss starting AT the first ARM row's tick: first ARM -> red in the assumed-
  disarmed prefix reads PASS (false green); first DISARM -> FAIL (false red). Fix a <= first (mutant X1 survives, suite
  green, both cases -> EI). Pin qa339/tools/a2.py.
- NOTES: G340 X8 (base = sure arming) survives, argued equivalent; G341 deviation (c) sound but B7 is monotone, so the
  general combine is equally sound and tighter (defer); G342 what the README must say (applied = arming PRESENT, holes
  < max(1 s, 5p) are not losses, DSF-absent logs report no pre-first drops, green badge carries "· k assumed").
Measured: no false green in (3) both directions, straddle, b == t_1, two pre losses, ARM-ARM, no-row (word for word,
applied false), ArmState 2, overlapping mode/arming U, gnss/no_events cut at U. 0 changes over 156 unarmed corpus bars vs
9e42cfa; streams/integrity/source identical with/without the key; refusal assumptions []. Raw-pymavlink re-derivation
of sure/wide n and worst on 01 (first disarm), 06, 33, 29 (first arm), 14 (pre drop + 458 s hole) all equal the tool.
14/16 QA mutants killed; G334 pin still kills the sentinel mutant with the hole moved before the first ARM row.

## Round 11 — final check before committing the assumption + publishing the corpus docs (2026-11-10) — G343-G351
Code: SHIP (G339 closed for both first-row states; corpus/22 inspect exit 0, mode ABSENT, all 26 mode-dependent bars EI
by rule 1, with and without the key; README assume example re-run char-for-char; A2 text verbatim; 3/3 examples).
Docs: SHIP-AFTER-FIXES. Every probe number reproduced from probe_*.json EXCEPT:
- G343 MAJOR: "hardware" = population github, but 01/02 are SITL (SIM/SIM2 records, "RC Protocol: SITL") and 21/22 are
  synthetic fixtures (banner "synthetic teaching fixture"). 2 of the 8 drop logs are SITL; "hardware 28/40" = 10 SITL +
  3 synthetic + 15/20 board-string hardware. Classify by SIM records / banner, never by where a log was found.
- G344 "14 GitHub repositories" -> 13; G345 "17 logs carry ERR rows" -> 18 (17 FAIL; 10 FAILs are ECode-0-only SITL rows);
  G346 the 2 hardware speed-bar voids are mid-log logger holes (07, 14), not a start gap; G347 am.2 /18 vs record /19;
  G348 "78/78 mutants" is not QA's tally and am.2 omits G326; G349 README rule-5 exception false for armed B7, note
  scope, DSF-ABSENT "verdict unchanged" (G335 residual); G350 "pre-registered before the build" unsupported; G351
  BUILD_LOG "one real flight and no outside log" self-contradicts.
**Lesson:** a population label is a claim; check it in the bytes (SIM records, MSG banner) before counting by it.

## Round 12 — the dogfood record eval/results/gates_dogfood_20261110 (20 SITL logs 00000045-64), 2026-11-10 — G352-G356
Every count reproduced from the 20 verdict JSONs (7 pass / 12 fail / 1 could not tell; batch.json 0/20 rows disagree;
log sha256s match the copies; WP_SPD 8/6/6; ranges 3.932-4.008, 5.002-5.008, 5.996-6.003; GUIDED 4.86-6.09 s; margin
4.960 x19; EKF 0.08-0.37; 0 drops/holes). Raw pymavlink on 64, 47, 63: speed 3.993/5.008/5.996, margin 4.960, SV
0.19/0.23/0.14, n 382/748/1498 all equal. Polygon = config rectangle +15 m to 7 dp. Only red in the 12 = the speed bar.
- G352 MAJOR claims: the batch is an UNBOOKED speed sweep (encounter_batch.sh --speeds -> fly_pipeline ENC_SPEED "explicit
  WP_SPD for an UNBOOKED experiment"); the committed booking is 5.0 (ADR-020 am. 3). bars.yaml + README call WP_SPD "the
  booking"; the 6.0 flights exceed booked x1.10 = 5.5, so "not about the vehicle" overstates. Fix the README only
  (editing registered bars text breaks the pin).
- G353 "within 0.2 % in every flight" false for 45 (3.932, -1.7 %); G354 "76 MB" = 75.0 MB; G355 no RTL/LAND row ever
  flown (end-mode entries unexercised); G356 blind defensible, disclose primary-choice basis + a-priori sample rates.
