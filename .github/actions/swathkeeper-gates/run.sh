#!/usr/bin/env bash
# The Action's run step (action.yml), as a file so tests/test_ci_evidence_gate.py can execute it against a stub
# tool and the real one. Inputs arrive as environment variables: LOG, BARS, OUT (required), DECLARED, PREREG
# (optional, empty = not passed). Outputs go to $GITHUB_OUTPUT (exit-code, badge, verdict) BEFORE the exit -- on
# EVERY path, refusals included -- so a caller's later `if: always()` step can read them even when this step is red.
#
# The exit code is the tool's, untouched. 1 and 2 fail the step. Nothing here maps them to 0. A refusal raised
# HERE (a missing input, a line break in a path, a stale file at --out that cannot be removed) is the tool's own
# word for "could not judge": exit 2, badge `gates: refused`.
set -euo pipefail

refuse() {
  local safe_out="${OUT:-}"
  safe_out="${safe_out//$'\n'/ }"; safe_out="${safe_out//$'\r'/ }"   # never echo a line break into the outputs file
  {
    echo "exit-code=2"
    echo "badge=gates: refused"
    echo "verdict=$safe_out"
  } >> "${GITHUB_OUTPUT:-/dev/null}"
  echo "[swathkeeper-gates] refused: $1" >&2
  exit 2
}

for v in LOG BARS OUT; do
  [ -n "${!v:-}" ] || refuse "input $v is required (GitHub does not enforce a composite input's required: true)"
done
case "${LOG}${BARS}${OUT}${DECLARED:-}${PREREG:-}" in
  *$'\n'*|*$'\r'*) refuse "a path input contains a line break (it would forge a second output line)";;
esac
# A verdict left at --out by an EARLIER run would be read as this run's if the tool refuses before writing
# (QA G268): remove it first, and refuse if it will not go.
if [ -e "$OUT" ]; then
  rm -f -- "$OUT" 2>/dev/null || true
  [ ! -e "$OUT" ] || refuse "a stale file at --out $OUT could not be removed"
fi

args=(run "--log=$LOG" "--bars=$BARS" "--out=$OUT")      # --opt=value: a path starting with '-' is still a path
[ -n "${DECLARED:-}" ] && args+=("--declared=$DECLARED")
[ -n "${PREREG:-}" ] && args+=("--prereg=$PREREG")

rc=0
swathkeeper-gates "${args[@]}" || rc=$?

# The badge from the verdict the tool just wrote. On exit 2 with an unwritable --out there is no file: the
# tool's reason went to stderr above, and the badge is the §5 word for that outcome.
badge="gates: refused"
if [ -f "$OUT" ]; then
  badge="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["badge"])' "$OUT" 2>/dev/null || echo "gates: refused")"
fi
badge="${badge//$'\r'/ }"; badge="${badge//$'\n'/ }"   # a badge is one line; a crafted verdict must not forge a second output

{
  echo "exit-code=$rc"
  echo "badge=$badge"
  echo "verdict=$OUT"
} >> "${GITHUB_OUTPUT:-/dev/null}"
echo "[swathkeeper-gates] $badge (exit $rc) -> $OUT"
exit "$rc"
