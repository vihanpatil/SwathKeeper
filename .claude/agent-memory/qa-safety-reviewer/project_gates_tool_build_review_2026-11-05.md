---
name: gates-tool-build-review-2026-11-05
description: QA round on the BUILT swathkeeper_gates (option C step 2, uncommitted on feat/gates-tool-build) — G228-G254; 5 blockers (window adjacency, sub-floor skips, no-measurement channels, B7 over holes, antimeridian), measured on real + mutated logs
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
