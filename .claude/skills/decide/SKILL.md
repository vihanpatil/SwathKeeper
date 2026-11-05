---
name: decide
description: Record a decision in docs/DECISIONS.md the house way — or, if it is critical, write the options memo instead
argument-hint: "<ADR number or 'new'> <one-line subject>"
---

Decision: $ARGUMENTS

## 1. Is it critical? Decide this first.
CRITICAL = direction, a scope pivot, spends a Docker/sim session, outward-facing, or something the
owner lives with for months. If critical, **do NOT decide and do NOT write to DECISIONS.md.**
Produce the options memo (one page) and hand it to the main session to put to the owner:
- **Question** — one sentence.
- **Options actually considered** — each with its steelman (the strongest honest case for it).
- **Recommendation** — one, with the reason in a sentence.
- **Price paid** — what is cut or deferred if the recommendation is taken.
- **Tripwire** — the measured result that would reverse it.
The owner's style: options explained first, then ONE question. Run the five lenses as a checklist:
CEO (motion or progress?), CTO (sound for both B and C?), CSO (survives cross-examination?), CFO
(highest-value spend, what is NOT done?), CPO (who is the user — "adoption" is fiction until an
external conversation exists).

## 2. Build-level: decide and record.
- `docs/DECISIONS.md` is **APPEND-ONLY**. Never edit a committed body; correct by amendment.
- Amendment: append at the end of the file, ≤ 10 lines:
  `### ADR-NNN amendment N (<YYYY-MM-DD>, <what>)` — the decision, the rejected alternative, the
  one-sentence reason, the gate or number that backs it.
- A decision reads `confirmation-pending` until a live gate flips it to `CONFIRMED live <date>`.
- **A new ADR needs a cut**, recorded in `docs/ROADMAP.md` "Cut / deferred log" in the SAME change.
  No cut, no ADR — make it an amendment or don't make it.
- Disagreements between roles: `lead` wins for v1; record the losing alternative as the tradeoff.
