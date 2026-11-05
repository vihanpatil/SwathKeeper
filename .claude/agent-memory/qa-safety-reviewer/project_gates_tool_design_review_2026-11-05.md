---
name: gates-tool-design-review-2026-11-05
description: QA review of docs/design/GATES_TOOL_DESIGN.md (swathkeeper_gates, ADR-022 am.4 option C) before build — G211-G227, measured on the real public logs; what was exposed of the blind demo bars
metadata:
  type: project
---

Reviewed 2026-11-05, design-only (nothing built). Gaps continue from G210.

**Measured facts (pymavlink 2.4.50 / pyulog 1.3.0, own downloads, sha256 all match the design's):**
- Tarot X4 demo: GPS **709 rows** ~5 Hz (design §4 says "4 sparse GNSS samples" — false). DSF.Dp **15**
  (cumulative; all lost by 710.18 s, armed, pre-takeoff). LOG_DISARMED 0. No ARM-arm record, only the
  disarm (836.27 s); EV 15/28/11 corroborate. MODE row at log start is a logger write. XKF4 cores C=0,1
  with a `PI` primary column. Log PARM **FENCE_RADIUS 150** vs template `24_safety_setup.param` **350**
  (comment: "start with a 150m fence radius"). LOIT_SPEED 1250 (WPNAV_SPEED 500 does not govern
  AltHold/Loiter). BATT_LOW_TIMER 10, BATT_FS_VOLTSRC 0. No per-type TimeUS reversal.
- ArduPlane negative log: GPS logged ONLY as instance **I=1** (GPS_PRIMARY=1) -> "instance 0" makes
  gnss ABSENT; no POS, no ORGN; FMTU non-monotone (so a monotone check over ALL types refuses it).
- pymavlink test.BIN: EKF2 core 0 = NKF4, core 1 = **NKF9**, no `C` column; no ARM, no VER.
- DFReader: default mav_type FIXED_WING (DFReader.py:791); a zeroed 400 kB mid-log block -> "Skipped
  400014 bad bytes", exit 0, records 99,521 -> 91,839, an **11.3 s hole** in POS/BAT/GPS/XKF4.
- pyulog log_level is raw ASCII (52 WARNING, 54 INFO) -> "level <= 3" never matches.
- PyYAML safe_load: duplicate key keeps LAST (`limit: 18.6` then `limit: 0` -> 0); NO/ON -> bools; 1e3 -> str.
- CI planning-and-eval installs requirements-eval.txt only (numpy, scipy, markdown): no PyYAML, no
  pymavlink, no package install — the design's "no CI edit" is false.

**Blindness exposure by QA (disclose in §4):** first-row BAT.Volt 24.34 V (pre-takeoff), first XKF4 rows
both cores, first GPS row Spd 0.021, POS first row, PARM values above. No min/max of any blind bar read.

**Gaps:** CRITICAL G211 holes/drops invisible (no gap rule, bytes_skipped, DSF, ULog dropouts; B6 chord
across a hole is unlabelled inference); G212 min_n unfloored + B8 EMPTY PASS on n=0; G213 mode names
unvalidated -> vacuous NA (typo, Norway, default Plane map); G214 NKF9/GPS-instance/BAT-instance hide
failures; G215 stat/op freedom (inverted bars, quantiles, worst-window ordering, rule-3/4 swap mutant
survives the plan); G216 NaN never violates. MAJOR G217 PX4 log_level; G218 YAML duplicate keys;
G219 prereg optional + badge implies registration (ADR-022 am.4 says "committed BEFORE the run and
checked"); G220 demo limits contradict the log (fence 350 vs 150, WPNAV vs LOIT, B3 != failsafe);
G221 false §4 ledger fact; G222 badge `pass` on 1 PASS + 7 EI and `fail` on an honest all-EI log;
G223 CI deps; G224 step-5 asserts exit code only. MINOR G225 refusal list gaps / GPS-time leap /
`armed:false`; G226 B6 alt_max + polygon bit; G227 tests:src CLAUDE.md vs ADR wording.

**Why:** the tool's verdict is the product; every hole ships to strangers' logs.
**How to apply:** when the build lands, re-run each measured fact above as a red-first regression;
grade the demo post's wording against G219-G222.
