---
name: evidence-discipline
description: SwathKeeper's shared doctrine, preloaded into every team agent
user-invocable: false
---

# SwathKeeper evidence discipline (team v2, 2026-11-05)

Every agent on this team works under these rules. Role files add to them; none relaxes them.

## Standing directives (the owner's, binding)
1. **Model split.** The main session (Fable) orchestrates and verifies; Opus agents build; Sonnet
   takes light work. Hand back something the main session can check, not a plan to redo.
2. **Lazy-elite.** The minimal work that succeeds: simple readable core, bug-free, low latency.
   Prefer deleting to adding, no speculative flags, one source of truth per concept.
3. **No band-aids.** Every new core function is tested from all angles up front; live gates beat
   static checks. A fix is done when a gate that would have caught the bug exists and fails without it.
4. **The user is a resource, for critical calls only.** Ask rather than guess on direction, scope
   pivots, anything that spends a Docker/sim session or goes outward-facing, and anything the owner
   lives with for months. Everything else is decided by the team and recorded.

## Evidence rules
- No "it works" without a metric or a reproducible scenario.
- **A rate needs a denominator.** "Could not tell" never scores green; an empty ground truth is
  EVIDENCE INSUFFICIENT, an unreadable yield is a FAIL.
- **Gates on VALUES cannot catch GEOMETRY.** Every ADR-007 band gate passed while the camera faced
  the horizon. Demand a check the artifact cannot fake.
- A **COMMANDED** setpoint is never recorded as **FLOWN** (the 2026-08-18 audit: debt understated
  by up to 32 cells/scenario; regression-pinned).
- Judge a recording lever by `red_frames / camera_info_frames`, a map by frames that painted a
  cell — never by `cells_imaged`.
- Declared reds are declared EXACTLY. An undeclared red is how a real one hides.
- Never quote a volatile number from memory: read `docs/ROADMAP.md`, `eval/results/`, or
  `tests/README.md` (suite totals live there, and only there).

## Claims ceiling and the safety asterisk
Every claim, everywhere: **"sim-demonstrated, evidence-gated."** Say this before ANY avoidance
claim: three live avoidance flights, **three** bird-clearance breaches — gate-recomputed CPA
**0.0393 / 0.0391 / 0.0067 m** against a **3.00 m** bar (the 2026-08-25 take is INVALID and stands).
Birds have no `<collision>` geometry and are teleported, so the offline gate is the entire safety
system. The control loop is **OPEN**: `send_setpoint_enu` publishes and returns, `verdict="accepted"`
is a constant, and nothing compares commanded to achieved displacement.

## Standing freezes (ADR-022)
- NDVI pipeline FROZEN (ADR-019 §7). Depth segmenter FROZEN until a flight WITH a target exists.
- `docs/DECISIONS.md` amendments are ≤ 10 lines; no new ADR ships without a recorded cut.
- tests:src capped at **3.70:1**; OVER at **3.84** since 2026-09-11. Every new test file retires
  one until it falls; the cap is never re-baselined.

## Naming (ADR-011)
Never rename `fieldguard_planning`, `fg_` / `/fg/*`, `farmguard_field.sdf`, or the `fieldguard-sim`
image. `/fg/*` is live-verified; the old names are deliberate.

## Host environment
Run Python as `.venv/bin/python` (or with `.venv/bin` first on PATH). `/usr/bin/python3` on the
owner's Mac is the Xcode stub — never call bare `python3`.

## Escalation
`lead` decides build-level calls and records them in `docs/DECISIONS.md`. Critical calls go to the
owner as options plus one recommendation, never as a decision already taken. When two roles
disagree, `lead` wins for v1 and the tradeoff is recorded in `docs/DECISIONS.md`. Dates are absolute.
