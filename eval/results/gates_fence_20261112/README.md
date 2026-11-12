# The fence a `containment` bar reads from the log: measurement and pre-registered predictions, 2026-11-12

Tool 0.3.0 judges a `containment` bar with `source: log` against the FENCE_* PARM rows and the home (ORGN Type 1) row
with no lost-write rule. ADR-023 amendment 4 left that open; the owner ruled on 2026-11-12 that the fence gets the rule
a parameter-following limit has. This directory holds what was measured before any rule was written and what the ruled
rule is predicted to read. **It was committed before any 0.4.0 source change.** No log bytes are stored here.

## Measured before the rule (63 logs: the 40-log public corpus, the project's 20 SITL logs, the 3 examples)

56 logs are judged (7 corpus logs are refused by the adapter).

| The log's fence, as 0.3.0 reads it | logs |
|---|---|
| PRESENT, home PRESENT | 3: corpus 05, corpus 06, the Tarot X4 example |
| ABSENT: FENCE_ENABLE 0 | 45: 24 corpus, all 20 SITL, `plane_nofix` |
| ABSENT: FENCE_ENABLE / FENCE_TYPE not logged | 7: 6 corpus, `pymavlink_test_bin` |
| ABSENT: polygon bit only | 1: corpus 17 |

- No FENCE_* parameter changes value in any log, and none has a non-finite FENCE_* row.
- On all three logs with a fence, each used FENCE_* name has one row (the startup dump), there is one ORGN Type 1 row,
  and at least one position sample comes before those rows: 1 on corpus 05 and 06, 2 on the Tarot.
- The Tarot has one drop interval, 15 writes in [709.278081, 710.1837] s. Its four used FENCE_* rows
  (709.371834 to 709.371975 s) and its only ORGN Type 1 row (709.37919 s) are inside it. Corpus 05 and 06 have no drop
  interval and no log hole.
- ORGN is written with `AP::logger().WriteBlock` (`AP_AHRS::Write_Origin`, ArduPilot @ Copter-4.5.5): a non-critical
  write that can be dropped and counted in DSF.Dp, like a PARM row. `AP_Arming_Copter::arm` re-sets home right after
  it tells the logger the vehicle is armed.

## The ruled rule, in brief (lead, two rounds, after QA's design attack G380 to G392)

For each position sample, each thing the bar takes from the log is unknown ("pre") at or before its first row, and
unsure where a DSF drop interval or a log hole (a, b) has a <= t and b >= the latest row strictly before t. The
cylinder takes FENCE_ENABLE, FENCE_TYPE, FENCE_RADIUS and home; the altitude cap takes FENCE_ENABLE, FENCE_TYPE and
FENCE_ALT_MAX, and is also unknown where RelHomeAlt has no value (before the first ORGN Type 1 row). A sample with an
unjudged quantity is not judged for it; any such sample makes the bar read could not tell unless a judged sample
violates. n counts segments whose two ends are both judged. **No declared assumption reaches the fence in 0.4.0**: the
closed set of assumptions is unchanged.

## Predictions (P1 to P7)

`predict.py` derives the counts below from the logs with the 0.3.0 adapter; `predict.json` is its output.

| Log, unscoped `source: log` bar | 0.3.0 | 0.4.0 predicted | n | samples not judged |
|---|---|---|---|---|
| Tarot X4 `geofence` | PASS | could not tell | 1419 -> 0 | 1420 of 1420 |
| corpus 05 `fence` | PASS | could not tell | 222 -> 221 | 1 of 223 |
| corpus 06 `fence` | PASS | could not tell | 1580 -> 1579 | 1 of 1581 |

- **P1, `examples/tarot_x4`.** `geofence` reads could not tell, n 0, measured null. Its note carries exactly:
  `fence not usable on 1420 sample(s): cylinder: 2 at or before the first row of FENCE_ENABLE, FENCE_TYPE, FENCE_RADIUS, home (ORGN Type 1), t in [709.279, 709.379] s; cylinder: 1418 where a loss meets [previous row, sample] of FENCE_ENABLE, FENCE_TYPE, FENCE_RADIUS, home (ORGN Type 1) and may hide a row (15 firmware-dropped writes in [709.278, 710.184] s (DSF.Dp)), t in [709.479, 851.179] s; altitude cap: 2 at or before the first row of FENCE_ENABLE, FENCE_TYPE, FENCE_ALT_MAX, home (ORGN Type 1), t in [709.279, 709.379] s; altitude cap: 1418 where a loss meets [previous row, sample] of FENCE_ENABLE, FENCE_TYPE, FENCE_ALT_MAX and may hide a row (15 firmware-dropped writes in [709.278, 710.184] s (DSF.Dp)), t in [709.479, 851.179] s`
  and no "judged across" line. `alt_floor` keeps its verdict, n and measured value; only the reworded position note
  moves in its note. The other six results are identical leaf by leaf. Badge
  `gates: could not tell · 6/8 measured (post-hoc)`, exit code 1, both as the 0.3.0 run except for the count.
- **P2, the other two examples.** `plane_nofix`: no verdict, n, badge (`gates: fail · 1/5 measured (post-hoc)`) or exit
  code moves; the fence reason text changes where it prints. `pymavlink_test_bin`: no result leaf moves; badge
  `gates: could not tell · 3/6 measured (post-hoc)`; only `streams.position.note` is reworded.
- **P3, the corpus probes** (`../gates_corpus_20261110/probe.py`, `probe_assume.py`). 130 -> 128 and 180 -> 178
  measurable verdicts of 495. The two that move are the `fence` bar on corpus 05 and 06 (table above), each with
  `fence not usable on 1 sample(s): cylinder: 1 at or before the first row of FENCE_ENABLE, FENCE_TYPE, FENCE_RADIUS, home (ORGN Type 1), t in [T, T] s; altitude cap: 1 at or before the first row of FENCE_ENABLE, FENCE_TYPE, FENCE_ALT_MAX, home (ORGN Type 1), t in [T, T] s`,
  T = 69.523 on 05 and 236.969 on 06. No other verdict, n, badge or exit code moves.
- **P4, no key reaches the fence.** A bars file that declares `limit_before_first_parm_row` reads the same on a
  `source: log` fence as one that does not. (Pinned by a unit test, not by a file here.)
- **P5.** Corpus 05 and 06 read as in P3 under any bars file.
- **P6, the 20 SITL logs** (`../gates_dogfood_20261110/`, all three bars files). No verdict, n, badge or exit code
  moves: their fence is ABSENT and their containment bar is `source: yaml`.
- **P7.** In every other verdict only the tool version and two reworded texts move: the position note about RelHomeAlt
  before the first ORGN Type 1 row, and the reason printed for FENCE_ENABLE 0.

What a prediction here does not say: nothing about whether a vehicle stayed inside a fence. A could-not-tell is the
tool declining to read a fence it cannot be sure of.

Files: `predict.py`, `predict.json`.
