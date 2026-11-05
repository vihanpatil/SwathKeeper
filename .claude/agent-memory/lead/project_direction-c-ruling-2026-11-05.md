---
name: direction-c-ruling-2026-11-05
description: 2026-11-05 owner ruled ADR-022 step 4 = C (build the evidence-gate method tool now; market test = ten public posts of it; B deferred not cut) — recorded as ADR-022 amendment 4, NOT 2
metadata:
  type: project
---

**2026-11-05: the owner ruled C** — build the pre-registered evidence-gate method as an installable
tool now (contract, one foreign `.bin`/ULog adapter, YAML bars + pre-registration hash, JSON verdict +
exit codes, declared-red allowlist, Action + badge on a log we did not write). Market test becomes
**ten public posts of the working tool**; kill criterion fixed before post 1: 0 of 10 yields a real
log or a scheduled follow-up → "strong portfolio, no product", stop. **B deferred indefinitely, not
cut.** Video demoted to optional. Recorded as **ADR-022 amendment 4** — the main session asked for
"amendment 2", but am. 2 and 3 already exist (R8, 2026-09-11); numbering follows the file, not the brief.

**Why:** owner cannot be hands-on; ADR-022's sequence stalled 8 weeks on owner-side steps (0/10
conversations, video unrecorded). The tool is the only thing a stranger can install and the only
path the team can automate without a sim session.

**How to apply:** refuse work only B would use. Packaging (my build-level call): `src/swathkeeper_gates/`,
own pyproject, stdlib + PyYAML, never imported by `fieldguard_planning`, never depends on `scripts/`
(check_live_flight_log.py is 4,310 lines tied to drive_birds/annotate_real_clip). Its src and tests both
count in tests:src — land src before tests. Supersedes the "zero code" clause in [[adr022-direction-reset]].
