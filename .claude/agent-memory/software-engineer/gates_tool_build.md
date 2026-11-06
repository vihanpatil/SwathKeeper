---
name: gates-tool-build
description: Option C step 2 (2026-11-05) — what is non-obvious about src/swathkeeper_gates and pymavlink's DFReader, the design points the build had to read conservatively, and the line-budget reality
metadata:
  type: project
---

Built 2026-11-05 on `feat/gates-tool-build` per docs/design/GATES_TOOL_DESIGN.md rev 2 (uncommitted at hand-back;
the orchestrator commits after QA). PX4 adapter OUT (D1). Verify against the code before relying on any of this.

**DFReader 2.4.50 facts the adapter depends on (read from its source, not docs):**
- Sequential `recv_msg()` after construction walks the file from offset 0 independent of the index; `m.fmt.len`
  includes the 3-byte header, so `bytes_skipped = size - sum(fmt.len)` (DFReader keeps no counter).
- It applies FORMAT-CHAR multipliers (c/C/e/E x0.01, L x1e-7) and NEVER FMTU multipliers, so a value column
  stored as a bare int would be silently raw: the adapter marks it ABSENT ("units unknown").
- It prints diagnostics to stdout (`print(ex)`), so `inspect`'s JSON needs `redirect_stdout(sys.stderr)`.
- `DFReader.mav_type` defaults to Plane; never use it. Mode tables are `mavutil.mode_mapping_acm/apm/rover/sub`.
- pymavlink's own `tests/test.BIN` has NO VER but its MSG banner says "ArduPlane V3.8.2-dev", so the design's
  "vehicle from MSG/VER" rule RESOLVES it (the step-2 brief expected ABSENT; the design rule won).

**Conservative readings the design left open (all in the step-2 report):** gap rule edges count per bar but not
for log-level holes; B7 transitions across a log hole are not judged; arming's ABSENT prefix makes any
armed:true scope that reaches it EI; mode windows start at the first MODE row (no prefix rule); home with >1
distinct ORGN Type 1 is ABSENT; EKF2+EKF3 both logged is ABSENT; ERR EMPTY only at 4.5.x for every vehicle.

**Line budget reality:** the design estimated bars+loader 250 lines; the five kinds + closed schema came to ~440
(src 1,141 vs the 950 estimate). Everything else fit its estimate. Ratio after: 3.37 (under 3.70).

**Adding tests reds `tests/test_suite_totals_one_home.py` x2 (and so KNOWN_RED)** until README.md, SETUP.md and
tests/README.md re-quote the totals — expected; the orchestrator owns the re-quote.

**Fix round 2026-11-05 (QA G228-G254, all applied; src 1,269, tests 781, ratio 3.34):**
- DFReader's Cython indexer prints "bad header ..." PER BYTE at the C level: `redirect_stderr` cannot silence it;
  the adapter dup2's fds 1/2 to devnull for the parse (`_mute`). A subprocess test asserts stderr == "".
- Byte skips are located exactly: a decoded record starts at `r.offset - m.fmt.len`; != the previous end = a skip,
  recorded as a hole [last clock row, next clock row] however short (QA zeroed ONE 14-byte MODE row and a whole
  Tarot run still read pass). The three real logs skip only TRAILING bytes (10 / 51 / 24), so no real hole.
- QA's kill rule: a mutant is killed only if the NAMED test reports FAIL (AssertionError). A KeyError/TypeError
  is ERROR and does not count, so write assertions with `.get(...)` / `str(...)` that degrade into a FAIL.
- `pytest tests -k gates` without `.venv/bin` first on PATH reds tests/test_fly_pipeline.py (its launcher spawns
  `python3` = homebrew, no numpy): environmental, not a regression.
- Round 3 (2026-11-05, supersedes round 2's byte-only ruling): `log_holes` = byte holes UNION the INTERSECTION of
  fired interior gaps over every PRESENT raw-stream instance (position, gnss, battery). A gap in all of them is the
  logger (the ERR citation's silent gates stop every stream: the intersection is what makes D3's EMPTY premise hold);
  a gap in one is that sensor (QA's objection to the old union). velocity/ekf are filtered, never take part. No raw
  stream PRESENT -> B7/B8 EI ("no unfiltered series stream (POS/GPS/BAT) to witness logger liveness"). The G257 Dp
  note is tested against the scope's BASE range (accepted): a dropped MODE row there could move a mode scope.

Related: [[feedback-red-first-fixtures]], [[evidence_consumption_seams]].
