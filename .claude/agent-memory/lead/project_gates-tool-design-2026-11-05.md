---
name: gates-tool-design-2026-11-05
description: Option-C step 1 design note (docs/design/GATES_TOOL_DESIGN.md) — Revision 2 after QA G211-G227 (2026-11-05): the calls easy to forget, the demo-log blindness ledger, the rule-4 consequence that the demo may print "could not tell", the tests:src dilution caveat
metadata:
  type: project
---
Design note for `src/swathkeeper_gates/`: rev 1 written 2026-11-05, QA said "do not build as written" (G211-G227),
**Revision 2 landed the same day** with every finding ACCEPTED (G215 + 5 cuts ACCEPTED-AS-CUT), none rejected.
Merged as PR #38 (main 5a31261, 2026-11-05). **Built + scored 2026-11-05 → ADR-023** ([[adr023-gates-tool-built]]).

**Why:** ADR-022 am. 4 (direction C). QA's measured log facts (DFReader silently skipping a zeroed 400 kB block,
NKF9 = EKF2 core 1, Plane GPS only as I=1, PyYAML duplicate keys) showed rev 1 would print wrong PASSes.

**How to apply:**
- **Demo log:** Tarot X4 `.bin`, ArduPilot/MethodicConfigurator @3d14a143, sha256 a4dc0050…9108, 5,197,824 B,
  GPL-3.0 → never committed, fetched by pinned URL. **Limits come from the LOG's PARM** (FENCE_RADIUS 150,
  FENCE_ALT_MAX 120, LOIT_SPEED 1250 cm/s, BATT_LOW_VOLT 18.6), NOT the template (which says FENCE_RADIUS 350).
- **Blindness:** B1/B5/B7/B8 not blind. QA also saw first rows of BAT (24.34 V), XKF4, GPS Spd, POS. Still never
  read a min/max of BAT, XKF4, in-Loiter speed or B6 margin before bars are committed.
- **Rule 4 (no inference):** arming initial state stays ABSENT; zero-ERR `events` was CITED in step 2 (ADR-023) → EMPTY
  only for release V4.5.x + LOG_BACKEND_TYPE 1, so the Tarot B8 reads PASS and its badge is `pass 8/8` (superseded below).
  Consequences pre-registered: demo bars use `armed: null`; demo B8 (must) reads EI → demo badge `could not tell`
  unless ERR semantics get cited. Report it; do not demote B8 after the fact.
- **Demo is `(post-hoc)`** (log pinned in sidecar, flown 2024-08-05). v1 records dates, never asserts them.
- **QA's public sentence had a clause rev 2 made false** (limits "from the template"); §10 keeps QA verbatim plus
  the corrected clause. Re-check outward copy against the design whenever a ruling moves a limit's source.
- **tests:src** is measured over `src/**/*.py` since am. 4 (state.sh, gates.sh, CLAUDE.md updated 2026-11-05;
  ratio unchanged at 3.84 because src/ holds only fieldguard_planning today). Projected 3.43 with the tool;
  MEASURED after step 2: 3.33 (fieldguard-only 3.97) — dilution, quote both.
- Gate-tool tests go directly in `tests/`; CI's `planning-and-eval` needs `pip install -e .[ardupilot]`.
- `.claude/skills/ship/SKILL.md:15` still says `src/fieldguard_planning/*.py` — not yet updated (2026-11-05).
See [[project_direction-c-ruling-2026-11-05]].
