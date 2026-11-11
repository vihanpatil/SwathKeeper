# The gates tool on SwathKeeper's own flights, 2026-11-10

The first time `swathkeeper-gates` judged a flight of this project. Twenty ArduPilot DataFlash logs written by the
`fieldguard-sim` container on 2026-11-10 (SITL, ArduCopter V4.8.0-dev 9895756d, the pinned firmware), copied out
read-only: `00000045.BIN` to `00000064.BIN`. By the logs' own GPS clocks and the session that flew them, `00000046` to
`00000064` (19:41Z to 20:35Z) are runs of a head-on encounter batch, one pass each, that deliberately cycles the
commanded mission speed `WP_SPD` through 4.0, 5.0 and 6.0 m/s; `00000045` (19:36Z) is a batch run killed mid-flight.
**These are unbooked experiments:** `WP_SPD` here is an experiment parameter, and the project's committed booking is
5.0 m/s (ADR-020 am. 3). Tool: 0.2.0, installed from GitHub at the pushed branch.

**What a verdict here does NOT say.** A DataFlash log carries no bird, so nothing below says whether a dodge cleared
its bird. That is the project's own GT-CPA gate, on the JSON flight log, and all three historic live avoidance flights
breached it (CLAUDE.md, the safety asterisk). These bars judge the vehicle's envelope only.

**How the bars were written.** `bars.yaml` (sha256 `539aefde…6a1e`) was written from the committed design
(`config/field_polygon.json`, ADR-006) and from the PRIMARY log's parameters and firmware banner only, before any
flight data of any of the twenty logs was read. Disclosed: the primary was fixed by rule beforehand as the most recent
completed log, `00000064.BIN` (GPS start 20:35:36Z, a 4.0 m/s batch run), "completed" being judged from file size and
modification time; the `min_n` sample rates (5 Hz GPS, 10 Hz POS and XKF4, two EKF cores) come from earlier project
knowledge; the three MSG rows read for the banner include "Arming motors". Registered post-hoc (the logs existed
first), each run pinned to its log. Six bars: speed in AUTO against the primary's `WP_SPD` plus 10 %, GNSS quality
while armed, designed modes only, the committed field polygon plus 15 m with a 20 m altitude cap while armed, the EKF
velocity ratio while armed, and no ERR rows. The armed scope uses `assume: [arming_before_first_arm_row]`: these logs
start at arming (LOG_DISARMED 0) and their only ARM row is the disarm.
**Erratum, not edited because the file is hash-pinned:** the speed bar's provenance text calls `WP_SPD` "the booked
mission speed". It is the speed the primary run was COMMANDED to fly; none of these runs carries a booking.

**Primary flight, `00000064.BIN` (`verdict_00000064.json`):** `gates: pass · 5/6 measured · 1 assumed (post-hoc)`,
exit 0. 81.3 s, no dropped writes, no log holes; AUTO, a 4.95 s GUIDED window, AUTO; one disarm row. Speed in AUTO
peaked at 3.993 m/s against the commanded 4.0; the geofence margin is 4.960 m, set by altitude (20 m less the 15.04 m
the mission climbs to, so it follows from the design); the EKF velocity ratio peaked at 0.19; `no_errors` reads could
not tell (the zero-ERR reading is cited for 4.5.x releases only).

**The same bars on all twenty (`batch.json`): 7 pass, 12 fail, 1 could not tell.**
- **The 12 fails are correct measurements against a bar that encodes ONE commanded speed.** 8 logs carry `WP_SPD` 4.0,
  6 carry 5.0 and 6 carry 6.0, each as a constant; the bar's 4.4 m/s ceiling came from the primary, so every 5.0 and
  6.0 flight exceeds it, and the speed bar is the only red in those 12 verdicts. The AUTO maxima are 3.932 to 4.008,
  5.002 to 5.008 and 5.996 to 6.003 m/s: no flight exceeded its own commanded speed by more than 0.2 %. That is a
  post-hoc reading, not a verdict. Against the project's COMMITTED booking of 5.0 m/s and its own 10 % check
  (5.5 m/s), the six 6.0 m/s flights did fly outside the booking, by design, as an experiment. The verdict prints each
  log's `WP_SPD` beside the limit, but a bar cannot take its limit from the log's own parameter: `limit` is a number in
  the bars file. A sweep needs one bars file per commanded speed today.
- **The could-not-tell is `00000045.BIN`:** 21.5 s, no ARM row at all, so the armed-scoped bars cannot be judged; the
  assumption does not cover a log with no ARM row.
- On the 19 flights with a disarm row: GNSS 19 of 19 pass, geofence 19 of 19 (margin 4.960 m each), EKF 19 of 19
  (0.08 to 0.37). `designed_modes_only`: 20 of 20; every full flight is AUTO, GUIDED, AUTO with a GUIDED window of
  4.86 to 6.09 s. No log contains an RTL or LAND row (the missions land in AUTO), so that bar's RTL and LAND entries
  were never exercised. `no_errors`: could not tell on 20 of 20. No log has a dropped write or a log hole, and DSF is
  present in all of them, so that absence is measured.

QA (G352 to G356) recounted all twenty verdicts and re-derived MODE and ARM rows, AUTO speed, armed altitude and the
EKF ratio with raw pymavlink on `00000064`, `00000047` and `00000063`: every value equals the tool's, including n.
The logs themselves are not committed (75.0 MB); `batch.json` records each one's sha256 and size. They live in the sim
container's volume at `/root/ardu_ws/src/ardupilot/logs/`.

## Addendum 2026-11-11: the same 20 flights, with a ceiling that follows each log's own WP_SPD (tool 0.3.0)

The first gap named above, that a bar cannot take its limit from the log's own parameter, is closed in tool 0.3.0.
This is the run that was fixed before that tool existed.

**What was registered, and when.** `bars_param.yaml` (sha256 `8d69c04250776978d89f495bafce48172700324c4b2739413616b338a31ff3dc`)
and `bars_param_key.yaml` (sha256 `e6fa82d568be3f67b3c06120b8cadbe1fa1436d5652a0f2433e0950726e2367d`) were committed
in c57bcf8 and pushed before a 0.3.0 tool existed to run them; 0.2.0 refuses both. They are the 2026-11-10 file with
one change: the literal 4.4 m/s ceiling becomes two bars that follow PARM `WP_SPD`. The second file differs from the
first only by declaring `limit_before_first_parm_row`. Not blind: the 2026-11-10 run had already printed each log's
`WP_SPD` and its fastest AUTO sample. Each run was registered post-hoc with its own sidecar pinning its log; the two
committed sidecars pin the primary, `00000064.BIN`.

| Bar | Severity | Limit | Accepted `WP_SPD` |
|---|---|---|---|
| `speed_ceiling_auto` | must | 1.1 x `WP_SPD` | 1.0 to 5.0 m/s, the committed booking (ADR-020 am. 3) |
| `speed_commanded_auto` | should | 1.1 x `WP_SPD` | 1.0 to 6.0 m/s, the whole unbooked sweep |

**Results, all 20 logs, no flight FAILs in either file.**

| Commanded `WP_SPD` | Logs | `speed_ceiling_auto` (must) | `speed_commanded_auto` (should) | Fastest AUTO sample | File reads |
|---|---|---|---|---|---|
| 4.0 m/s | 8 (45 46 49 52 55 58 61 64) | PASS against 4.4; log 52 could not tell without the key | the same | 4.008 (log 58) | pass on 6 without the key, 7 with it; log 45 could not tell |
| 5.0 m/s | 6 (47 50 53 56 59 62) | PASS against 5.5 | PASS against 5.5 | 5.008 (log 47) | pass on 6 |
| 6.0 m/s | 6 (48 51 54 57 60 63) | could not tell: 6.0 is outside 1.0 to 5.0 | PASS against 6.6000000000000005 | 6.003 (log 57) | could not tell on 6, exit 1 |

| File | pass | fail | could not tell |
|---|---|---|---|
| `bars.yaml`, literal 4.4 m/s (2026-11-10, tool 0.2.0) | 7 | 12 | 1 |
| `bars_param.yaml` | 12 | 0 | 8 |
| `bars_param_key.yaml` | 13 | 0 | 7 |

The primary, `00000064.BIN`, reads `gates: pass · 6/7 measured · 1 assumed (post-hoc)` and with the key
`gates: pass · 6/7 measured · 2 assumed (post-hoc)`. Its speed note: `limit 4.4 = 1.1 x WP_SPD 4 (PARM row at
t=29.088 s); n=382; worst 3.993`.

**What it shows.**

- The 12 FAILs of 2026-11-10 were a literal limit meeting a swept parameter. On all 12 logs the `should` bar now
  reads PASS: no flight exceeded 1.1 x its own commanded speed, and the fastest sample is within 0.2 % of the command
  in every group.
- The six 6.0 m/s flights do not turn green. Their `WP_SPD` is outside the range the `must` bar accepts, so that bar
  reads could not tell and the file exits 1. That is the committed 5.0 m/s booking stated as a bar: the tool does not
  call an out-of-range configuration a violation, and it does not let it pass.
- Log 52 reads could not tell without the key because ONE GPS sample, at speed 0.0, carries the same timestamp as
  `WP_SPD`'s first PARM row (t=29.824188 s). Nothing before a parameter's first row is judged unless the bars file
  says so. With the key it passes on n=377. That is 1 log in 20.
- Log 45, the killed run, passes both speed bars on n=108 and still reads could not tell, because its armed-scoped
  bars have no ARM row to stand on, as on 2026-11-10.
- None of the 20 logs has a drop interval or a log hole, so the rule that a lost write may hide a parameter change is
  not exercised here. It is exercised on the public corpus (`../gates_corpus_20261110/README.md`, addendum).

**What it does not show.** Nothing about bird clearance. A PASS on the `should` bar says a flight stayed within 10 %
of the speed it was commanded, not that the speed was booked. Still open, as above: `no_errors` reads could not
tell on all 20, and a log with no ARM row cannot stand an armed scope.

QA recounted every figure here from the verdict files and re-derived the speed bar on logs 48, 52 and 58 from the
raw bytes with pymavlink: sample counts, the worst sample and the PARM row times match the tool.

Files: `bars_param.yaml`, `bars_param_key.yaml`, their sidecars, `verdict_param_00000064.json`,
`verdict_param_key_00000064.json`, `batch_param.json` (both files, all 20 logs, every bar).
