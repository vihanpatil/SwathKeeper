---
name: outreach-kit-adr022-market-test
description: The private ADR-022 outreach kit (docs/outreach/, gitignored) built 2026-09-11 for the ~10-conversation market test of the pre-registered evidence-gate METHOD, plus a new story-bank entry (the booking-gate catch) not yet folded into safety-asterisk-and-story-bank.md
metadata:
  type: project
---

## The kit (private, never committed)

Built 2026-09-11 on `feat/depth-segmenter` per direct task instructions (not a standing session).
Lives at `docs/outreach/` — added to `.gitignore` (`docs/outreach/` line, with a one-line comment)
because these are working drafts for real outreach, not portfolio artifacts. Four files:
`OUTREACH_MESSAGE.md` (3 variants ≤150 words: forum/Discord post, maintainer/lab DM, integrator
email), `ONE_PAGE_EXPLAINER.md` (≤450 words), `TARGETS.md` (11 public channels/orgs across 3
segments — ArduPilot/PX4 dev communities, maintainers+labs, Part 108/BVLOS operators — no private
individuals, no scraping), `TRACKER.md` (10-row log with the ADR-022 kill criterion pinned at top
and a strict INTERESTED rule: only a handed-over log or a scheduled follow-up counts, never a
compliment).

**Why this exists / how to use it next time:** this is the actual go-to-market instrument for
ADR-022's decision (see [[portfolio-decision-2026-09-10]]) — "test the market for the METHOD, not
the drone, with ~10 conversations, kill criterion 0/10 → stop." If asked to run or update the
outreach round, this is the place to look first; don't recreate it. The kit's own numbers must be
re-verified against source before reuse if more than ~2 weeks have passed (these decay fast, same
rule as [[headline-metrics]]).

## New story-bank entry: the booking-gate catch (not yet in [[safety-asterisk-and-story-bank]])

A **fourth "gate catches itself" story**, distinct from stories 0/0b/0c/1 already logged, and one of
the three catches this outreach kit leads with everywhere:

**The booking gate caught a speed violation the flight-wide average would have hidden.** On the
2026-08-25 take, `check_live_flight_log.py --booking` against a hypothetical 5.0 m/s booking shows
the **whole-flight median 3.417 m/s = 0.683× would PASS**, while the **actual encounter window**
(takeover→resume, the only interval that matters for a dodge) flew at **9.012 m/s = 1.802× — FAILS**.
Source: `docs/DECISIONS.md` ADR-020 amendment 3 ("QA reproduced the defect on the committed
2026-08-25 take"); raw figures also in
`tests/fieldguard_planning/fixtures/check_live_flight_log_committed_output.txt` lines 26-27. Pinned
by `TestTheCommittedTakeIsTheRegression` — the test asserts the *disagreement* between the two
statistics, not just a value.

So-what: **the right denominator is the encounter window, not the whole flight** — a per-flight
average is exactly the kind of green number that hides a local violation, and this is a second,
independent instance of the same "value gates can't see structure" lesson as ADR-007 am. 5 (mount)
and the 2026-08-25 detector-rate story (0b/story 2 in the story bank). Worth folding into
[[safety-asterisk-and-story-bank]] as a numbered story next time that file is touched — flagged here
rather than done now to keep this session's edit footprint small (light-narrative-lane discipline).

## Numbers used in the kit, each with its committed source (re-verified 2026-09-11)

- CPA **0.0067 m** vs **3.00 m** bar, 2026-08-25, INVALID — `eval/results/live_flight_log_20260825T210402Z.json`
  + `.SAFETY_FINDING.md`; pre-registered in `docs/runbooks/AVOIDANCE_REAL_DETECTION.md` §7.
- Three flights, three breaches, same 3.00 m bar: **0.0393 m** (2026-08-18, ACKNOWLEDGED) /
  **0.0391 m** (2026-08-23, ACKNOWLEDGED) / **0.0067 m** (2026-08-25, INVALID) — the current
  segment-path CPA recompute, all three now disclosed per the ADR-022 honesty widening. The older
  0.0518/0.0597 m pair in [[headline-metrics]] is the pre-2026-08-26 vertex-only geometry — superseded,
  don't quote those two numbers again.
- Booking catch: **9.012 m/s (1.802×)** vs **3.417 m/s (0.683×)** against a **5.0 m/s** booking —
  `docs/DECISIONS.md` ADR-020 amendment 3.
- Displacement: **0.018 m** lateral (`cross-course dodge +0.0182 m`) against a **10 m** commanded
  divert, **0.434 s** GUIDED authority window — `eval/results/live_flight_log_20260825T210402Z.SAFETY_FINDING.md`;
  same figure already logged in [[headline-metrics]].
- CI: red on exactly one declared test
  (`tests/test_ci_evidence_gate.py::TestLiveFlightLogGateHasEvidence::test_step_passes_on_the_committed_evidence`),
  both the test file and `.github/workflows/ci.yml`'s allowlist confirmed to exist 2026-09-11.

## Process note

No Bash tool was available in this session (tool list was Read/Edit/Write/WebSearch/WebFetch/Grep/
Glob only), so the task's requested `git status --short docs/outreach` / `git check-ignore
docs/outreach/TRACKER.md` verification could **not** be executed — only reasoned about by reading
the `.gitignore` pattern. Flag this to whoever has shell access next, same as the "no Bash tool"
note in [[portfolio-decision-2026-09-10]] — this appears to be a recurring environment constraint
for this agent, not a one-off.
