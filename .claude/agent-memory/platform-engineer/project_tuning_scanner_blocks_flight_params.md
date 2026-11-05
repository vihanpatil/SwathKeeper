---
name: tuning-scanner-blocks-flight-params
description: Any WPNAV_/PSC_/GUID_/ANGLE_MAX param anywhere in the repo (even in prose) fails the point-mass study's validity scanner — there is no placement that avoids it
metadata:
  type: project
---

`eval/replay_point_mass.py::_tuning_override_scan` fails `tests/test_point_mass_replay.py::TestTuningScanner::test_the_real_repo_is_clean_and_carries_the_sitl_warrant` on **any** token
starting `WPNAV_`, `GUID_`, `PSC_`, `ANGLE_MAX`, `ATC_ANGLE_MAX` found in:
`**/*.parm`, or as `param set <KEY>` in `scripts/*.sh`, `scripts/*.py`, `docs/runbooks/*.md` —
**including inside comments and prose** (a sentence saying "no `param set WPNAV_SPD` exists" trips it).

**Why:** the point-mass replay study's plant constants ARE ArduCopter firmware defaults
(`PM.GUIDED_DEFAULT.v_max_ne_mps = 10.0` is WPNAV_SPEED's default). The scan is the only thing
standing between "these are defaults" and a silently void study; it was added as QA finding M5 and
survived a mutation test, so it is deliberately broad.

**How to apply:** before adding a flight parameter anywhere, know that *no* placement avoids the
scanner — a `.parm` file is flagged the same way as a typed MAVProxy line. The scanner has to learn
about the new parameter (a named, warranted allowlist entry so an *unknown* param still fails); do
not evade it by splitting the literal string across a `printf`, and do not touch it without the
owner of `eval/replay_point_mass.py`. Real ArduPilot names are `WPNAV_SPEED` / `WPNAV_ACCEL`;
`WPNAV_SPD` / `WPNAV_ACC` in this repo's comments are shorthand, not parameters.

First hit 2026-09-07 by the launcher's `--booking` → `param set WPNAV_SPEED <cm/s>` injection
([[booking-speed-enforcement]]).
