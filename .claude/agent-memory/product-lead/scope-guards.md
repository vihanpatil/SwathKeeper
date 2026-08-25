---
name: scope-guards
description: Standing product-lead scope guard (survives the dropped deadline) + the recorded cuts, incl. the 2026-08-24 R4/R5, criterion-2 and no-tracker cuts
metadata:
  type: project
---

**Standing call, in force for the rest of the project: DO NOT ADD SCOPE. GUARD THE EXITS.** Nothing
is added without something cut in the same breath. Every `/standup` is measured against protecting
the Week-7 demo + dashboard exit, not feature count.

**Why:** the original framing came from the 2026-08-05 external review, whose blunt headline was
that the failure mode is *slippage into no demo*, not under-scoping. The ~7-8-week hard deadline was
**dropped 2026-08-18** — the calendar pressure is gone, **the guard is not**. See [[phase]].

**How to apply:** first question on any proposed work is "does this need to exist for v1?" If yes,
name what gets cut to make room. Recorded cuts (the canonical list is `docs/ROADMAP.md`'s
cut/deferred log — add new ones there with date + reason):

- **No YOLOv8 bolt-on for resume keywords (2026-08-05).** The classical blob baseline cleared the
  safety bar and has since been ADOPTED on the real render (ADR-003 am. 7). Only legitimate
  opening: a learned detector that beats it on the same harness, honest before/after.
- **No retrofitted startup / "billion-dollar" narrative (2026-08-05).** Sim-only, solo,
  portfolio-honest framing is the asset; inflating it turns ADR honesty into an interview red flag.
- **No code-identifier rename (2026-08-18, ADR-011).** `fieldguard_planning`, `/fg/*` etc. stay.
- **Safety scope bounded to R2/R3 for v1 (2026-08-24).** ADR-013 am. 12 ranked five fixes; R1
  shipped, R2 + R3 landed offline 2026-08-24 and fly on the next avoidance flight. **R4**
  (reversal-preferring candidate order) and **R5** (ArduPilot `FENCE_*` backstop + lanes moved
  inboard) stay recorded-open, NOT v1 blockers — R4 needs closing geometry v1 does not have, and R5
  is a second boundary authority bolted on beside a working one. They are the classic "while we're
  in there" and are refused on sight until R2/R3 have flown.
- **Criterion 2's RGB pixel study deferred behind the avoidance flight (2026-08-24).** Perception
  wanted it in-session; my call. The flight live-gates four landed things and criterion 2 gates none
  of them; the study is offline, ~1 h, and its clip already exists, so deferring costs ordering and
  nothing else. Owed a `docs/DECISIONS.md` tradeoff entry.
- **No detection tracker in v1 (2026-08-24).** `track_id` stays `None` and there is no second
  staleness expiry: the policy's threat test is per-frame, the executor latches on geometry, and
  ageing detections out is `max_detection_age_s`'s job alone. A tracker that exists to look
  sophisticated is untested state.
- **Docs-cleanup session bounded to staleness + the newcomer path (2026-08-25).** The living/
  runbooks/archive taxonomy is good and stays; the problem was staleness and a missing front door.
  Refused in the same breath: renaming `fieldguard`/`fg` identifiers (ADR-011), a docs restructure,
  and any code change beyond `scripts/build_docs_site.py`'s doc list. **Ruled against archiving
  `docs/runbooks/SIM_BRINGUP.md`** despite its superseded manual-flight half: it is the only home of
  the image + colcon-workspace build detail, `SETUP.md` delegates to it, and `DECISIONS.md` states it
  "must stay the single audited source". Archived instead (stub left at the old path, because
  `DECISIONS.md` is append-only and links both): `NDVI_VALIDATION.md` (closed gate record) and
  `SIM_CI.md` (plan + feasibility verdict, smoke half never run — its open items owed one ROADMAP
  deferral line).
- **Closing a gate's own defects is NOT scope creep (2026-08-24).** When QA's adversarial pass shows
  the certifier can print a false PASS, fixing it is the price of the flight, not an addition to it —
  a take scored by a lying gate is the "clean flight yielding nothing scoreable" failure.
