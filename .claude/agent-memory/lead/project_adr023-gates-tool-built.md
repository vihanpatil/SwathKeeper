---
name: adr023-gates-tool-built
description: ADR-023 (2026-11-05) — option C step 2 BUILT + SCORED; the ERR/ARM firmware citation and its reach ruling, the G260 log_holes INTERSECTION rule, the G257 Dp-rise open item, and the dilution caveat on tests:src 3.33
metadata:
  type: project
---
**ADR-023** (appended to docs/DECISIONS.md 2026-11-05) records `src/swathkeeper_gates/` built and scored on three
public logs (Tarot `pass 8/8`, ArduPlane `fail 1/5`, test.BIN `could not tell 3/6`, all post-hoc). Uncommitted on
`feat/gates-tool-build` at writing → PR #39 (owner merges). Cut with it: PX4 adapter + `[px4]` extra, the LOG_DISARMED
arming-inference note (G252), the Plane B7 bar (G243).

**Why:** the design note (rev 2) was the pre-registration; deltas live in the ADR, never in the design body.

**How to apply:**
- **ERR citation (lead RULING, source read at tag Copter-4.5.5):** `Write_Error` → `WriteCriticalBlock` →
  `AP_Logger_File::_WritePrioritisedBlock`; only counted loss is `_dropped` = DSF.Dp; silent gates stop EVERY stream.
  Zero ERR rows = EMPTY only for release `V4.5.<n>` (no -dev/-beta/-rc) + PARM LOG_BACKEND_TYPE logged, constant, == 1,
  any vehicle (shared libraries/); else ABSENT. Widening it to 4.6+/other backends needs a NEW source read, not a vibe.
- **ARM is event-only** (`Log_Write_Arm/Disarm`); under LOG_DISARMED=0 the arm row is refused (set_vehicle_armed runs
  after the write) — explains the Tarot's lone disarm row; initial arming state stays ABSENT (rule 4).
- **G260 rule:** `log_holes` = byte holes ∪ the INTERSECTION of fired gaps across position/gnss/battery. A hole in all
  raw streams = the logger; in one = that sensor. The intersection is what makes the ERR premise ("silent gates stop
  every stream") hold — a byte-only reading broke D3. No raw stream PRESENT → B7/B8 EI. Don't "simplify" it to a union.
- **G257 OPEN (v1.1 call owed):** Dp-rise intervals are excluded by B8 only; a MODE row lost in a Dp rise is invisible
  to B7 and mode-scoped bars (notes print it). Treating Dp-rise as a hole costs the Tarot B7 EI → `could not tell` —
  that flips the demo badge, so it is a call with outward consequences: price it before step 6's posts.
- **tests:src 3.33 is dilution** (27,189 / 8,173); fieldguard-only 3.97 (was 3.84). Quote both, always.
- Stale 3.84 quotes left (not mine to edit 2026-11-05): `.claude/agents/lead.md:56`, `software-engineer.md:49`,
  `skills/evidence-discipline/SKILL.md:47`, `skills/ship/SKILL.md:16`; design §0 line 37 is pre-registration (leave it).
See [[gates-tool-design-2026-11-05]], [[project_direction-c-ruling-2026-11-05]].
