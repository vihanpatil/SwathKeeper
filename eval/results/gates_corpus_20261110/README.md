# Corpus measurability probe, 2026-11-10

How often can `swathkeeper-gates` tell? 40 public DataFlash logs: 26 from 13 public GitHub repositories (pinned by
commit) and 14 SITL logs from https://autotest.ardupilot.org/ at ArduPilot commit 524baa92 (those URLs are mutable;
each log's sha256 is recorded). The probe files label logs by SOURCE (`github`, `sitl-autotest`); `classification.json`
labels each by its own CONTENT (SIM records, a synthetic banner, a board banner): the 26 GitHub-sourced logs are 15
real hardware, 2 SITL, 2 synthetic teaching fixtures and 7 unclassified (of the 19 judged: 11 / 2 / 2 / 4). Fifteen loose-limit probe bars per log, one per kind and scope, so PASS or FAIL means
the bar was MEASURABLE on that log and EVIDENCE_INSUFFICIENT / NOT_APPLICABLE means the tool could not tell. The
mode-scoped bar uses each log's dominant mode; `modes_seen` allows only the modes that log used; `modes_any` allows
every transition. No log bytes are stored here.

| File | What it is |
|---|---|
| `manifest.json` | every log: url, sha256, size, population |
| `probe_v010.json` | the released 0.1.0 (GitHub install at ecbe20c): 32 judged, 8 refused (7 pre-2015 format, 1 adapter crash) |
| `probe_v020.json` | 0.2.0, no `assume` key: 33 judged, 7 refused (the crash is fixed) |
| `probe_v020_assume.json` | 0.2.0 with `assume: [arming_before_first_arm_row]` declared |
| `probe_whatif_armed.json` | a SCRATCH copy of 0.1.0 patched to treat the stretch before the first ARM row as the opposite of that row, run before the feature was built (10 bars + 4 armed). Not the tool. |
| `classification.json`, `classify.py` | each log's content class and the evidence for it (QA G343) |
| `summary_*.txt` | the aggregates below, per bar and SOURCE population |
| `fetch.py`, `find_gh.py`, `probe.py`, `probe_assume.py`, `summarise.py` | how the corpus and the numbers were made |

| Measured | 0.1.0 | 0.2.0 | 0.2.0 + key |
|---|---|---|---|
| verdicts measurable (15 bars) | 130 / 480 | 130 / 495 | 180 / 495 |
| armed-scoped verdicts measurable | 1 / 160 | 1 / 165 | 51 / 75 on the 15 logs with ARM rows; 0 / 90 on the 18 without (pre-registered: exactly 0) |
| `modes_seen` on GitHub-sourced logs | 10 / 18 | 5 / 19 | 5 / 19 |
| `modes_any` on GitHub-sourced logs | 10 / 18 | 12 / 19 | 12 / 19 |
| `no_errors` reading PASS | 0 / 32 | 0 / 33 | 0 / 33 |

Dropped writes, by content class: 6 of the 10 real-hardware logs that count them (DSF present) carry a drop interval, as do
both SITL logs found on GitHub; none of the 14 autotest logs does; 7 of those 8 drop only at startup. The five logs that lost
`modes_seen` to the rule are three hardware and two SITL. Armed verdicts with the key, on logs with ARM rows: hardware 15/20,
SITL 33/45, synthetic 3/10. The whole-log speed bar is voided by a gap at the START of the log (no GPS fix yet) on 8 of the 14
autotest logs; two hardware logs lose it to mid-log holes. `events` is PRESENT on 18 logs; `no_errors` FAILs on 17 (15 SITL, 2
hardware).

Limits of this measurement: a convenience sample, not a representative one (several hardware logs are demos or fixtures;
one SITL autotest run; ArduCopter-heavy); the dominant-mode pick flatters the mode-scoped bar; limits are loose by design,
so nothing here says a vehicle behaved.
