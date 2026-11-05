---
name: docs-claims-get-measured
description: Doc claims get the same treatment as CI steps — run the command on a machine matching the reader's, and re-check handed-down facts against docs/DECISIONS.md before quoting them
metadata:
  type: feedback
---

A sentence in a doc is a gate that can silently be wrong. Before writing "this works / this is
install-free / this is the current state", run it on an environment matching the *reader's*, and
check any fact handed to you in a task brief against the repo record.

**Why:** the standing directive on this project is *HONESTY IS THE PRODUCT — no claim without a
metric*. Two concrete instances, both on 2026-08-25:
- `SETUP.md` and `tests/README.md` claimed `unittest discover -s tests/fieldguard_planning` "needs
  no install at all". On the *verified host* that is true only because numpy is already installed;
  on a clean 3.12 venv it exits 1 (ten modules import numpy at module scope, and unittest's loader
  reports ERRORs, not skips). The claim survived because nobody ran it the way a new reader would.
- A task brief asked me to write "full-mission recording decay unproven" into a tool's output.
  `docs/DECISIONS.md` ADR-013 **am. 10** had already retired run-age decay with a measurement
  (dead-flat 5.00 Hz over a full boustrophedon). The brief was one amendment stale; the doc got the
  current truth and the discrepancy was reported back.

**How to apply:** for any doc or user-facing string — (1) reproduce the reader's environment, not
yours (a bare venv at CI's pinned Python is the cheapest proxy); (2) quote real stdout and mark
where it is abridged; (3) grep `docs/DECISIONS.md` for the relevant ADR/amendment before repeating
a number someone handed you, and say so if you deviate from the brief. Same discipline as
[[feedback-bug-hunter-not-yaml-author]], applied to prose.
