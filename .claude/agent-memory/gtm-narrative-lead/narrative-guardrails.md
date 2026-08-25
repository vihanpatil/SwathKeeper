---
name: narrative-guardrails
description: How to write SwathKeeper's outward-facing docs — honesty rules, lean style, and the doc parts that are pinned by tests or a link gate
metadata:
  type: feedback
---

Write the front door lean, and never round an open item up to closed.

**Why:** the repo's stated ethos is HONESTY IS THE PRODUCT — the safety asterisk and the
pre-registered "this flight may fail its own gate" are the *selling points*, and an inflated claim a
hiring manager catches costs more than a modest true one. The user's standing directives are
lazy-elite (minimal words that land the differentiator) and no band-aids (every cited metric traces
to a live gate or a real eval run, re-verified at each use).

**How to apply:**
- Pull every number fresh from `docs/ROADMAP.md` "Where we are" and the artifact file in
  `eval/results/` — never from a prior session's memory or the previous README. See
  [[headline-metrics]] for the current set and its two forbidden numbers.
- State status as a table with the open items visible (dashboard not started; the live gate not yet
  flown), not as prose that implies more progress than exists.
- Expand acronyms on first use (NDVI, SITL, CPA, FNR, ADR) — the front door is read by
  non-roboticists. Keep insider war-story prose out of README; it belongs in `docs/BUILD_LOG.md`.
- Never rename `fieldguard`/`fg_`/`farmguard` code identifiers (ADR-011); explain the code-name
  split once, at the front door, and move on.
- **Before editing any doc:** parts of the docs are load-bearing for tests. `tests/test_fly_pipeline.py`
  byte-diffs FULL_PIPELINE_DEMO.md's pane one-liners against the launcher, and
  `test_check_live_flight_log.py::test_the_runbook_tells_the_operator_about_BOTH_halves` greps
  **three** docs (AVOIDANCE_REAL_DETECTION.md, AVOIDANCE_DEMO.md, docs/ROADMAP.md) for
  `.SAFETY_FINDING.md` **and** `ACKNOWLEDGED_BREACH_STEMS`; since 2026-08-25 it asserts each file
  exists instead of skipping, so a move fails loudly. Keep the ADR citation of that test's *name*
  intact — DECISIONS.md is append-only. `scripts/build_docs_site.py` hard-fails CI on any intra-repo
  link that resolves to nothing — so only link paths that exist, and re-run it after doc moves.
- **The safety asterisk must live on the doc that can PRODUCE the breach**, not only at the front
  door. Found 2026-08-25: README + SETUP carried it loudly while AVOIDANCE_DEMO.md — the arm both
  acknowledged breaches were actually flown on — had zero mentions of CPA, and the docs routing map
  described it in reassuring "deterministic regression arm" language. Route + asterisk travel together.
- **A metric quoted in more than one file needs a named home**, or the copies drift: `tests/README.md`
  said 279 while README said 877 and cited it as the proof. `tests/README.md` is now the home.
- One source of truth per topic: README does NOT duplicate SETUP.md's run steps; it routes. Route to a
  *file*, not to a named section of someone else's file — a section name you don't own can vanish.
- `docs/BUILD_LOG.md` house style: **no markdown links**, only backticked paths (keeps the link gate
  out of a narrative file). `build_docs_site.py` checks `<a href>` targets AND that the rendered
  heading count equals the ATX heading count — so never leave a text line directly above a `---`
  rule (Markdown turns it into a setext heading and the build fails as "heading drift").
- Image **alt text is a claim too**. It was the one place a draft README overclaimed (2026-08-25).
