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
