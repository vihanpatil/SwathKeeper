---
name: phase
description: Current SwathKeeper phase (Week 6 — the offline half landed 2026-08-24, everything now waits on ONE avoidance flight) and the booking bar for that flight
metadata:
  type: project
---

**As of 2026-08-24: Week 6 — the offline half is DONE; the whole phase now waits on ONE flight.**
(The ~7-8-week hard deadline was **dropped 2026-08-18** — quality over calendar. The scope guard
survives it: [[scope-guards]].)

**What closed, so it is never re-opened as "next up":**
- Weeks 1-2 sim foundation, Weeks 3-4 avoidance loop — complete, live; ledger closed 720/0
  (ADR-013 am. 11).
- **Week 5 NDVI: closed.** Four ADR-007 gates green; mount geometry corrected + gated.
- **Recording throughput: CLOSED 2026-08-22** (am. 9). Fast DDS SHM segment was the root cause;
  5.0 Hz flat, first 720/720 map. Do NOT retry `update_rate_hz` 5 → 2 (disproven, 16× worse).
- **ADR-003 criterion 3: CLOSED 2026-08-23** (am. 7) — ADOPT NDVI-direct, per-bird FNR 0.000.
  −0.61 stays PROVISIONAL pending FP characterisation.
- **2026-08-24 — four things landed OFFLINE in one session:** the detector on the
  `detection_source` seam (ADR-009), R2 (`lateral_tree_margin_m` 1.0) + R3 (degenerate re-latch
  refusal), the GT-CPA gate (ground truth replaces self-referential detection-CPA; legacy logs keep
  their verdict on a versioned branch), and the combined runbook
  `docs/runbooks/AVOIDANCE_REAL_DETECTION.md`. Suite 530/2/2 → **805 green / 2 skipped / 0 xfailed**.
  None of it is *done*: every piece awaits the same live gate.

**Open, in order (`docs/ROADMAP.md` "Next up" is the live truth; this is orientation):**
1. **The next avoidance flight.** ONE take live-gates all four landed pieces AND exercises the last
   un-exercised half of the proof standard (avoidance has only ever fired on a scripted `--demo`
   bird). Two preconditions: the image must be rebuilt with `python3-scipy` (multi-hour), and QA's
   2026-08-24 findings 1/3/4/5 must close first — see the booking bar below.
2. Full boustrophedon + short-vs-long evidence study on the FINAL config — the long arm rides item
   1's take for free (that runbook flies the full boustrophedon), so only the short arm is extra.
3. Criterion 2's offline RGB pixel study (deferred 2026-08-24 by my call) + lifting −0.61's
   PROVISIONAL flag.
4. Doc long-tail — the **owed ADR amendments** for 2026-08-24 first: DECISIONS.md stops at
   2026-08-23, so ROADMAP.md is currently the only record of what landed, which is backwards.
5. Week 7 — dashboard, demo video, GTM. The exit being guarded.

**The booking bar, learned 2026-08-24 — this is the durable part:** a Docker session is priced on
the *artifact*, and an artifact is worthless if the gate that scores it can print a false PASS. QA's
adversarial pass found six findings in the freshly-built GT-CPA gate (1 critical, 4 major), each
reproduced with a probe — e.g. a 0.8 s frozen clock turning a true 0.0000 m CPA into a 3.5000 m
PASS. So **"the code is landed" is not the booking bar; "the gate cannot lie" is.** Closing them is
not new scope — it is the no-band-aids rule applied to the certifier.

**How to apply:** flights need the user at the controls, so a session goal is agent-doable offline
work unless it is explicitly prepping/booking a flight. Book a user-flown Docker session only when
ONE take clears several blockers at once (that pattern has now paid off twice), run the host
predictor first (refuse on medians 0/0/1), and pre-register the expected outcome — this flight may
honestly FAIL its own GT-CPA gate, which ranks R4 next rather than wasting the take.
