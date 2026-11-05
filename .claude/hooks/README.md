# Hooks (team v2, 2026-11-05)

Two project hooks, both pipe-tested on the host. **Wiring them into `.claude/settings.json` is an
owner step** — editing that file from inside a Claude Code session is refused as self-modification,
so the agent team cannot do it for you. Apply once with:

```bash
jq '.hooks = input' .claude/settings.json .claude/hooks/settings.hooks.json > /tmp/sk_settings.json && mv /tmp/sk_settings.json .claude/settings.json
```

then start a new session (the settings watcher only picks up files that existed at session start).

| hook | event | what it does |
|---|---|---|
| `session-start.sh` | `SessionStart` | prints `scripts/state.sh` (branch, PRs + CI, Pages, Docker, host python, outreach count, tests:src, roadmap date) into the model's context, so every session opens on the measured truth |
| `validate-team-config.sh` | `PostToolUse` on `Edit\|Write` | when the edited file is under `.claude/agents/`, `.claude/skills/` or is `.claude/settings.json`, runs `scripts/validate_agents.py` with the project venv; exit 2 (blocking, stderr = reason) on a broken config, exit 0 otherwise. Never calls bare `python3` (the Xcode stub on this host). |

Both scripts resolve the repo from `CLAUDE_PROJECT_DIR` and degrade to a one-line notice rather than
failing when something is missing. `scripts/validate_agents.py` checks that every `command` hook in
`settings.json` points at an existing executable, so a stale path fails CI's `validate-config` job.
