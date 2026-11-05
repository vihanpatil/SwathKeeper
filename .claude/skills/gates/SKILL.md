---
name: gates
description: Run every host-side evidence gate and print the numbers table
disable-model-invocation: false
---

## Gate run (injected)
!`"${CLAUDE_PROJECT_DIR}/scripts/gates.sh" 2>&1; echo "gates.sh exit=$?"`

## Report
1. Print the `gate | result | expected` table above **verbatim** — no rounding, no reordering, no
   dropped rows.
2. Then ONE verdict line: `GATES MATCH (exit 0)` when every gate is in its expected state — the ONE
   declared red included — or `GATES MISMATCH (exit N): <the rows that differ>`.
3. A red that is not the declared one is a finding, not noise: name it first. If the script is
   missing or crashed, say exactly that; never reconstruct the table by hand.

## Never
- Re-quote suite totals into any doc from this output. Totals move only after re-running all three
  commands in `tests/README.md`, re-quoted at every home or none (`/ship` covers it).
- Call this "CI is green". It is the host-side mirror; say what only the runner exercises.
