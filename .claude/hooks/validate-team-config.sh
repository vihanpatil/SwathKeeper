#!/usr/bin/env bash
# PostToolUse (Edit|Write) hook: when a team-config file changes, run the config validator.
# Exit 0 = fine / not a team-config file; exit 2 = validator failed (stderr is fed back as the reason).
# Never calls bare `python3` -- on this host it is the Xcode stub; uses the project venv or skips.
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
input="$(cat)"
if command -v jq >/dev/null 2>&1; then
  path="$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)"
else
  path="$(printf '%s' "$input" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
fi
[ -n "$path" ] || exit 0
rel="${path#"$ROOT"/}"
case "$rel" in
  .claude/agents/*|.claude/skills/*|.claude/settings.json) ;;
  *) exit 0 ;;
esac
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || { echo "[validate-team-config] no .venv -- validator skipped (uv venv --python /opt/homebrew/bin/python3.12 .venv)"; exit 0; }
out="$("$PY" "$ROOT/scripts/validate_agents.py" 2>&1)"; rc=$?
if [ "$rc" -ne 0 ]; then
  printf '%s\n' "$out" >&2
  exit 2
fi
printf '%s\n' "$out"
exit 0
