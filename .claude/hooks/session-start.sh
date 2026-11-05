#!/usr/bin/env bash
# SessionStart hook: print the one-screen repo state brief so every session opens on the truth.
# stdout of a SessionStart hook is added to the model's context. Never fails the session.
ROOT="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
if [ -x "$ROOT/scripts/state.sh" ]; then
  "$ROOT/scripts/state.sh" 2>&1 || true
else
  echo "[session-start] scripts/state.sh missing or not executable -- run it by hand once it exists."
fi
exit 0
