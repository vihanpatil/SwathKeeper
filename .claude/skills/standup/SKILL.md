---
name: standup
description: Open a SwathKeeper work session — one goal, one failure condition, the lane that drives
argument-hint: "[optional focus]"
---

Run a tight standup for SwathKeeper. Decision-oriented, no status theater.

## Current state (injected)
!`"${CLAUDE_PROJECT_DIR}/scripts/state.sh" 2>&1 || echo "(scripts/state.sh failed or is missing — read docs/ROADMAP.md 'Where we are' + 'Next up' instead)"`

## Steps
1. **`lead` sets the goal.** From the state above, `docs/ROADMAP.md` "Next up" and
   `.claude/agent-memory/lead/MEMORY.md`: ONE sentence for this session's goal, the ONE outcome
   that would make it a failure, and the roadmap milestone it ladders to. Nothing is added without
   something cut.
2. **`lead` flags architecture risk** in at most 3 bullets (check the tail of `docs/DECISIONS.md`),
   or says "no architecture risk for this goal". Never invent one.
3. **Everyone else is silent unless blocking.** `software-engineer`, `platform-engineer`,
   `qa-safety-reviewer`, `narrative-lead` speak only for a genuine blocker or dependency on today's
   goal.
4. **Critical-call check.** If the goal needs an owner decision (direction, scope pivot, a Docker/sim
   session, anything outward-facing), say so in one line — the options memo comes before any work.

## Output
At most 8 lines: Goal · Failure condition · Milestone · Architecture risk · Blockers (if any) ·
First action. Then ask which lane drives, and proceed.

Focus for this session (may be empty): $ARGUMENTS
