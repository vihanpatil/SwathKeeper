---
name: phase
description: Current SwathKeeper phase (Week 6 — the 2026-08-25 take FLEW and breached as pre-registered; R4 is now #1) and the booking bar for flights
metadata:
  type: project
---

**As of 2026-08-25: Week 6 — THE TAKE FLEW, and it breached exactly as pre-registered.**
Seam + R2 + detector (99.92 % in air) + ledger (720/0) all live-gated green; `gt_cpa_m` **0.0067 m**
to bird_0 at 4.03 m vertical, gated −1.1210 m vs the 3.00 m bar → **INVALID stands** (marker written,
pin deliberately withheld). Diagnosis is geometry, not the detector: 7 in-cylinder frames → 2
in-image, sensor lead 0.175 s, policy lead 0.000 s. **R4 escape geometry is now #1 by measurement**,
paid for by deferring the doc fix-list and item 2's short arm (cut logged in ROADMAP 2026-08-25).
Three things I owe a call on: the record shape for committing breach evidence (CI can't pass
`--truth`; committing the track makes the take *ambiguous* and the CPA never prints), whether the
camera stays **nadir** (lead time vs the whole NDVI half — ask the user, don't guess), and fixing
`predict_bird_visibility.py`'s `DEFAULT_SPEED_MPS` 3.0 before any re-fly is booked.
*(An earlier 2026-08-25 docs-cleanup session changed no engineering state. Scope ruling: [[scope-guards]].)*
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
1. **R4 escape geometry**, re-scoped against 0.175 s of lead (not the 12 m cylinder), gated on lead
   time as well as CPA — then the re-fly. Fix the predictor's speed default first.
2. Item 2's long arm now EXISTS (the take was a full boustrophedon, best-ever tree gate 11/18
   canopy-grade); only the short `test_2lane` arm remains, and it is deferred behind R4.
3. Criterion 2's offline RGB pixel study (its input — 3310 RGB PNGs — rode this take for free).
   −0.61's **background** FP half is now closed; the **range** half needs birds at 3+ distinct ranges.
4. Doc long-tail — deferred behind R4, except the two load-bearing wrong facts (published 8/6/11
   medians are the 3 m/s figure; the gate's note says "forward-facing camera" but the mount is nadir).
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
predictor first **at the speed the mission will fly** (2026-08-25: PASS at the 3 m/s default, FAIL at
the flown 9.4 — that default booked a 2-frame encounter), and pre-register the expected outcome. The
2026-08-25 pre-registration paid off exactly as intended: the take failed its own gate and that is
reported as the system working, never spun as a pass. Also: **run teardown and freeze the bird driver
before scoring** — skipping both cost this take reproducible denominators and nearly its clip.
