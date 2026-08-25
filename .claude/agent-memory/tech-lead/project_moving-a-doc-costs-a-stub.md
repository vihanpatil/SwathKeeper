---
name: moving-a-doc-costs-a-stub
description: Three constraints that bind any future docs move in this repo — append-only DECISIONS.md forces stubs, build_docs_site.py is the only doc-integrity gate, and a doc-grepping test that SKIPS on a missing file is not a pin
metadata:
  type: project
---

Moving or renaming any Markdown file here has three costs that are not visible from the file itself.
Established while archiving `NDVI_VALIDATION.md` and `SIM_CI.md` on 2026-08-25.

**1. A stub is mandatory at the old path if `docs/DECISIONS.md` ever linked it.** That file is
append-only by rule (see [[adr-log-must-track-the-gate]]), so a path it links must keep resolving
forever — you cannot fix the link, only the target. Same for `.github/workflows/*` comments, which
are cheap to edit but easy to miss. A stub is one H1 + where it went + why.

**2. `scripts/build_docs_site.py` is the repo's ONLY automated doc-integrity gate, and it runs in
CI.** It hard-fails on (a) any intra-repo link that resolves to nothing and (b) heading drift
(source heading count vs rendered). It also cross-checks its `GROUPS` list against everything on
disk under `docs/` plus the three root docs, so an unlisted `.md` silently lands in an
auto-generated "Other documents" group. Rule: update `GROUPS`, then run it and require exit 0 —
before writing any doc that links the moved file.

**Why:** a docs move that skips either step goes red on the next push, in a job nobody associates
with editing prose.

**How to apply:** treat `python3 scripts/build_docs_site.py` as part of the edit, not part of
review. Convention set 2026-08-25: live docs get the direct new path; code/CI comments and
append-only text are allowed to resolve through the stub (one hop), because editing 25 source
comments for a prose link is churn.

**3. A doc-grepping test that `skip`s on a missing file is not a pin — it is a vacuum.**
`tests/fieldguard_planning/test_check_live_flight_log.py` greps
`docs/runbooks/AVOIDANCE_REAL_DETECTION.md` for `.SAFETY_FINDING.md` and `ACKNOWLEDGED_BREACH_STEMS`,
but skips if the file is absent — so moving that runbook would have vacated the safety-acknowledgement
check silently instead of going red. **Why:** same failure mode as the CI evidence step that printed
SKIP…PASS having validated nothing (ADR-013 am. 16 era) — a green with no denominator.
**How to apply:** after any doc move, do not trust the suite total; re-run the specific grep test with
`-v` and confirm it says PASSED, not SKIPPED. And when writing a new doc-pinning test, make a missing
file FAIL.
