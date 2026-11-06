#!/usr/bin/env bash
# The Action's run step (action.yml), as a file so tests/test_ci_evidence_gate.py can execute it against a stub
# tool and the real one. Inputs arrive as environment variables: LOG, BARS, OUT (required), DECLARED, PREREG
# (optional, empty = not passed). Outputs go to $GITHUB_OUTPUT (exit-code, badge, verdict) BEFORE the exit, so a
# caller's later `if: always()` step can read them even when this step is red.
#
# The exit code is the tool's, untouched. 1 and 2 fail the step. Nothing here maps them to 0.
set -euo pipefail

: "${LOG:?LOG (the flight log path) is required}"
: "${BARS:?BARS (the bars YAML path) is required}"
: "${OUT:?OUT (where to write the verdict) is required}"

args=(run --log "$LOG" --bars "$BARS" --out "$OUT")
[ -n "${DECLARED:-}" ] && args+=(--declared "$DECLARED")
[ -n "${PREREG:-}" ] && args+=(--prereg "$PREREG")

rc=0
swathkeeper-gates "${args[@]}" || rc=$?

# The badge from the verdict the tool just wrote. On exit 2 with an unwritable --out there is no file: the
# tool's reason went to stderr above, and the badge is the §5 word for that outcome.
badge="gates: refused"
if [ -f "$OUT" ]; then
  badge="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["badge"])' "$OUT" 2>/dev/null || echo "gates: refused")"
fi

{
  echo "exit-code=$rc"
  echo "badge=$badge"
  echo "verdict=$OUT"
} >> "${GITHUB_OUTPUT:-/dev/null}"
echo "[swathkeeper-gates] $badge (exit $rc) -> $OUT"
exit "$rc"
