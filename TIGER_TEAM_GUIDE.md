# SwathKeeper Tiger Team — Setup, Use & Maintenance Guide

> **Just browsing?** This file is the *process* behind the repo, not the drone system: SwathKeeper
> is built by one engineer running one orchestrating Claude Code session that directs five
> specialised subagents (lead, software, platform, QA/safety, narrative), and this is how that team
> is configured and run. For the system itself go to [`README.md`](README.md); to run it,
> [`SETUP.md`](SETUP.md). Nothing here is needed to build or fly the sim.

If you read nothing else: run `/standup` to open a session, `/gates` before claiming anything,
`/ship` to open a PR. Everything else is detail.

## 0. What this is

A version-controlled Claude Code team: five subagents in `.claude/agents/`, five project skills in
`.claude/skills/`, and two hooks scripted under `.claude/hooks/` (the owner wires them into
`.claude/settings.json` once — see `.claude/hooks/README.md`; a session may not edit its own settings). The main session (Fable) plans,
orchestrates and verifies; it does not build. **Opus builds**, and takes every correctness-critical
call; **Sonnet** takes the one light lane. That split is the owner's standing directive.

| Agent | Model / effort | Owns |
|---|---|---|
| `lead` | opus / high | `docs/ROADMAP.md`, `docs/DECISIONS.md`, `docs/SPEC.md`, architecture and the `/fg/*` `/ap/*` contracts; the v1 tiebreaker on build-level calls |
| `software-engineer` | opus | `src/fieldguard_planning/`, `eval/`, the `scripts/check_*.py` gate tooling, `dashboard/` (and, under ADR-022 option C, the log contract, adapters, YAML bars, JSON verdicts, the GitHub Action) |
| `platform-engineer` | opus | `sim/`, the Docker image + GHCR, `scripts/fly_pipeline.sh`, `.github/workflows`, Pages, the host environment (`.venv` via uv), headless/automation paths |
| `qa-safety-reviewer` | opus / high | adversarial review before any "done", any flight, any published verdict |
| `narrative-lead` | sonnet | README, docs-site prose, demo-video script and assets, outreach drafts, resume bullets; no Bash |

## 1. Skills and hooks

| Name | Kind | What it does |
|---|---|---|
| `evidence-discipline` | skill, preloaded into all five agents (`skills:`), not user-invocable | the shared doctrine: directives, evidence rules, safety asterisk, claims ceiling, freezes, ADR-011 naming, host python, escalation |
| `/standup` | skill | opens a session on the truth: injects `scripts/state.sh`, states the one goal and its failure condition |
| `/gates` | skill | runs `scripts/gates.sh` — every host-side CI gate locally, printed as gate \| result \| expected, including the one declared red |
| `/ship` | skill | pre-PR checklist: gates, suite totals re-quoted at all three homes, the tests:src ratio, a house-style commit, push, `gh pr create`. Never merges |
| `/decide` | skill, preloaded into `lead` | records an ADR amendment (≤ 10 lines) or a new ADR with its cut, or writes the options memo for a critical call |
| `SessionStart` | hook (`.claude/hooks/session-start.sh`; owner-wired) | runs `scripts/state.sh` — a one-screen brief (branch, PRs, CI, Pages, Docker, host python, outreach, tests:src, roadmap date) |
| `PostToolUse` | hook (`.claude/hooks/validate-team-config.sh`; owner-wired) | on Edit/Write of `.claude/agents/*`, `.claude/skills/*` or `.claude/settings.json`, runs `scripts/validate_agents.py` (agents, skills, `skills:` references) and blocks on failure |

## 2. Use

- **Open with `/standup`.** The session goal ladders up to the roadmap's current step.
- **Name a lane** — `@lead scope this`, or in prose `As software-engineer, …`. `@` guarantees the
  agent runs; prose usually delegates. `claude --agent qa-safety-reviewer` runs a whole session as
  one role.
- **`/gates` before claiming anything.** No "it works" without a metric; a gate whose result differs
  from its expected state is the finding.
- **`/ship` to open a PR.** The owner merges.
- **Escalation.** When two lanes disagree, `lead` decides build-level calls and records the losing
  alternative in `docs/DECISIONS.md` (that log is interview material). **Critical calls** —
  direction, scope pivots, anything that spends a sim session or faces outward, anything lived with
  for months — go to the owner: `lead` writes an options memo with a recommendation via `/decide`,
  and the main session puts **one** question to the owner.

## 3. Maintenance

- **`CLAUDE.md` stays short.** It loads into every agent; deep detail belongs in `docs/`, shared
  doctrine in `evidence-discipline`.
- **Agent memory is committed** under `.claude/agent-memory/<agent>/`, so knowledge is reviewable in
  diffs. Prune it like any other doc.
- **Edit `description:` to change when an agent is used**, its body to change how it behaves. The
  validator (a CI gate) and, once wired, the `PostToolUse` hook keep the config valid.
- **Re-verify the schema** at <https://code.claude.com/docs/en/sub-agents> before any big change to
  agents, skills or hooks.

## 4. Name map and history

Historical docs, ADRs and agent memory use the old names; read them through this map.

| Old (2026-07-27 → 2026-11-05) | New |
|---|---|
| `product-lead`, `tech-lead`, `exec-council` | `lead` |
| `flight-software-engineer`, `perception-ml-engineer` | `software-engineer` |
| `robotics-sim-engineer`, `devops-reliability-engineer` | `platform-engineer` |
| `qa-safety-reviewer` | `qa-safety-reviewer` |
| `gtm-narrative-lead` | `narrative-lead` |
| `.claude/commands/standup.md` | `.claude/skills/standup/` |

The team started on 2026-07-27 as eight agents retargeted from a generic solo-founder playbook
([`docs/archive/tiger_team_playbook.md`](docs/archive/tiger_team_playbook.md)); `exec-council` was
added on 2026-08-25 for direction-level rulings. On 2026-11-05 it was consolidated to five: one
orchestrating session plus five lanes is the smallest team that keeps product/architecture, build,
platform, adversarial review and narrative as separate voices. The shared doctrine moved into one
preloaded skill, so each agent body is role-specific and short. Memory directories were merged the
same way; the original entries keep their dates and old role names.
