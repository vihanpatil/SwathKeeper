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

## Addendum 2026-11-11: parameter-following limits (tool 0.3.0)

Tool 0.3.0 lets a `series_bound` limit follow the log's own parameter (`limit: {param, scale?, accept}`) and adds a
second declared assumption, `limit_before_first_parm_row`. `probe_param.py` was committed in c57bcf8, before a 0.3.0
tool existed to run it. It puts four unscoped bars on every log: a ground-speed ceiling at 1.1 x `WPNAV_SPEED` (cm/s,
scale 0.011, accepted 100 to 2000), the same at 1.1 x `WP_SPD` (m/s, accepted 1 to 20), a battery floor at
`BATT_LOW_VOLT` (accepted 5 to 60) and an EKF velocity-ratio ceiling at `FS_EKF_THRESH` (accepted 0.5 to 1.0). The
limits are realistic, so a FAIL is a measurement against that parameter in every mode, not a finding about a vehicle.

| | without the key | with `limit_before_first_parm_row` |
|---|---|---|
| judged logs / refused | 33 / 7 | 33 / 7 |
| measurable verdicts (PASS or FAIL) | 23 of 132 | 36 of 132 |
| `speed_wpnav` PASS / FAIL / could not tell | 3 / 1 / 29 | 7 / 1 / 25 |
| `speed_wp` | 0 / 0 / 33 | 0 / 0 / 33 |
| `batt_low` | 11 / 3 / 19 | 16 / 3 / 14 |
| `ekf_thresh` | 4 / 1 / 28 | 8 / 1 / 24 |
| could-not-tell verdicts whose only cause is the limit's (too few samples set aside) | 14 | 1 |

- The key changed 13 verdicts, all from could not tell to PASS: ten on logs 01, 02, 08 and 09, whose startup drop
  interval overlaps the parameter dump, and three on logs 17 and 23, which have samples at or before the parameter's
  first row. The key applied on 29 logs; on 4 no followed parameter has a row.
- What stays could not tell with the key (96 verdicts; a verdict can name several causes, the two ABSENT causes are
  exclusive): the bar's stream is ABSENT in 37; the log does not carry the named parameter in 32; a gap or hole in
  scope in 26; a loss that may hide a parameter row in 6; fewer samples than `min_n` in 5; `BATT_LOW_VOLT` 0, outside
  `accept`, in 2 (Rover autotest logs 38 and 39).
- `WPNAV_SPEED` is on 13 logs (values 500 and 1000) and `WP_SPD` on 12 (value 10.0), never both. The `WP_SPD` bar
  was measurable on none of its 12 logs: velocity is ABSENT on 5 (no GPS rows) and the other 7 have a gap or hole in
  scope. They are autotest logs that start at boot, the cause ranked first in the 2026-11-10 probe.
- Log 33 (an autotest that raises `BATT_LOW_VOLT` from 10.5 to 11.5 about 2 s in) reads FAIL against 11.5 with the
  lowest sample 9.595 V: the tool followed the change. QA re-derived it with raw pymavlink.
- Regression on the 2026-11-10 probes: `probe.py` and `probe_assume.py` re-run on 0.3.0 give 130 and 180 measurable
  verdicts of 495, as on 0.2.0. Leaf by leaf, no verdict, n, exit code or badge differs. In each run 26 notes
  changed: 25 lost their dropped-writes line on a could-not-tell bar that judged nothing because a stream or the fence
  it needs is ABSENT, and one transition bar on
  log 03 now says its startup row is judged from an unknown mode, because the first drop interval starts on that row's
  tick. Median periods and three or four GNSS outage spans moved in their last digit (0.3.0 puts every time on the
  1 microsecond grid).

Files: `probe_param.py`, `probe_param_nokey.json`, `probe_param_key.json`, `summarise_param.py`, `summary_param.txt`.
