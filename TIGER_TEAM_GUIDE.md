# FieldGuard Tiger Team — Setup, Use & Maintenance Guide

This guide turns the generic solo-founder tiger-team playbook into a **working, version-controlled
Claude Code team tailored to FieldGuard**. It covers what was built, how to set it up, how to run
the team day to day, how to maintain it as the project grows, and the improvements made over the
raw playbook (with reasons).

If you read nothing else: run `/standup` to start a session, then talk to roles by name
(`As tech-lead, …`) or `@`-mention them. Everything else is detail.

---

## 0. What this is (and what changed from the playbook)

The playbook is a generic 7-role solo-founder team written for a RAG/agent web app. FieldGuard is a
ROS 2 / Gazebo / ArduPilot **robotics simulation** project. So the roles were **retargeted, not
pasted**, and the team was wired up as real Claude Code subagents per the current
[sub-agents docs](https://code.claude.com/docs/en/sub-agents) (schema verified July 2026).

**The eight agents** (`.claude/agents/`):

| Agent | Playbook origin | What changed for FieldGuard |
|---|---|---|
| `product-lead` | Product/Program Lead | Tailored to the 7-8 week deadline, the confirmed priority order, and the "decide as you build" spikes. Holds `docs/ROADMAP.md`; wins scope ties. |
| `tech-lead` | Tech Lead/Architect | Owns the ROS 2 node/topic interface contracts and `docs/DECISIONS.md`; points at the `aerial-autonomy-stack` reference. |
| `perception-ml-engineer` | **AI/ML Engineer (was RAG-centric)** | **Fully retargeted** from RAG pipelines to robotics perception: NDVI-frame detection, the NDVI-vs-RGB spike, avoidance decision policy, and the evaluation harness. |
| `robotics-sim-engineer` | **NEW (supplemental)** | Added because the sim environment (Gazebo world, `ardupilot_gazebo`, SITL bringup, NDVI camera, bird actors) is big enough to need a dedicated owner. |
| `flight-software-engineer` | **Full-Stack Engineer** | Retargeted from React/Node to ROS 2 app code: coverage planner, the reactive avoidance + coverage-debt loop (the core), NDVI mapping, and the light dashboard last. |
| `devops-reliability-engineer` | DevOps/Reliability | Retargeted from cloud-free-tier cost to **local-sim reproducibility, headless CI, and demo-artifact recording**. |
| `qa-safety-reviewer` | QA/Security & Safety | Given teeth for a safety-relevant autonomous system: false negatives, silently-skipped cells, geofence breaches, confidently-wrong perception. |
| `gtm-narrative-lead` | GTM/Narrative | Tailored to the FieldGuard story, metric-backed resume bullets, and mining `docs/DECISIONS.md` for interview answers. |

Plus: `/standup` slash command, `CLAUDE.md` project context (loads into every agent), a permission
allowlist, a living roadmap, a decision log, a README skeleton, and a project directory scaffold.

---

## 1. Setup

### 1.1 Prerequisites
- **Claude Code** installed and working in this directory
  (`/Users/vihanpatil/personal/projects/auto-drone-sim`).
- **Git** — already initialized here. Version control is not optional for this workflow: the docs
  explicitly recommend checking `.claude/agents/` into VC so the team is reviewable and improvable.
- The actual robotics toolchain (ROS 2, Gazebo, ArduPilot SITL) is **not needed to use the team** —
  the agents will help you install and pin it. It's needed to run the drone sim they build.

### 1.2 One-time steps
1. **Restart Claude Code once.** The `.claude/agents/` directory was created during this session.
   Claude Code's file watcher only covers directories that existed at session start, so the agents
   load reliably after one restart. (New files added to an already-watched dir are picked up live.)
2. **Verify the team loaded.** In a fresh session, ask:
   `List the FieldGuard subagents available and their models.`
   You should see all eight. If any are missing, restart once more.
3. **Optional — make the first commit** (the scaffold is ready to version):
   ```bash
   git add -A && git commit -m "Scaffold FieldGuard tiger team + project structure"
   ```
   (`git commit` is set to *ask* for permission in `.claude/settings.json`, so nothing commits
   without your say-so.)
4. **Confirm your model access.** Agents are assigned `opus` (judgment-heavy roles) or `sonnet`
   (execution-heavy roles). If your plan can't use one, Claude Code silently falls back to your
   session model — no error — but see §4.3 to change them explicitly.

### 1.3 What lives where
```
.claude/agents/*.md      the eight tiger-team subagents (the team)
.claude/commands/standup.md   the /standup session opener
.claude/settings.json    permission allowlist + subagent nesting cap
CLAUDE.md                always-loaded project context (every agent reads this)
docs/SPEC.md             the full project spec (copied in so agents can read it)
docs/ROADMAP.md          living phased plan — product-lead updates each standup
docs/DECISIONS.md        ADR-lite tradeoff log — interview material
docs/tiger_team_playbook.md   the original playbook, for reference
README.md                public-facing readme (gtm-narrative-lead owns it)
src/ sim/ config/ scripts/ eval/ tests/   project scaffold with per-dir READMEs
```

---

## 2. Use — running the team day to day

### 2.1 Start every work session with a standup
```
/standup
```
This runs the playbook cadence, tightened: the `product-lead` states the one goal and the failure
condition, the `tech-lead` flags architecture risk, everyone else stays silent unless blocking. It
reads `docs/ROADMAP.md` so the goal always ladders up to a milestone. Keep it under ~10 minutes —
the command is written to resist status theater.

### 2.2 Three ways to invoke a role
Per the docs, these escalate from suggestion to guarantee:
1. **Natural language** — `As the tech-lead, review this ROS 2 interface.` Claude usually delegates.
2. **`@`-mention** — `@perception-ml-engineer scope the NDVI-vs-RGB spike.` Guarantees that agent runs.
3. **Whole session as a role** (advanced) — launch Claude Code with that persona as the main thread:
   ```bash
   claude --agent qa-safety-reviewer
   ```
   Useful for a dedicated safety-review pass.

### 2.3 A typical week, mapped to roles
- **Weeks 1-2 (stand up the sim + spike):** `robotics-sim-engineer` pins versions and gets a mission
  flying; `perception-ml-engineer` runs the NDVI-vs-RGB spike and records the decision;
  `flight-software-engineer` builds the boustrophedon planner. `tech-lead` locks the interface contracts.
- **Weeks 3-4 (the core loop):** `perception-ml-engineer` (detector + avoidance policy) and
  `flight-software-engineer` (avoidance executor + coverage-debt replanning) build the differentiator;
  `qa-safety-reviewer` attacks it continuously.
- **Weeks 5-6 (NDVI mapping + comparison arm):** mapping and the second-sensor quantification.
- **Week 7 (narrative):** `gtm-narrative-lead` writes the README, resume bullets, and demo;
  `devops-reliability-engineer` records the demo and greens CI.
- **Week 8:** buffer, safety sign-off, tagged demo-ready commit.

### 2.4 Working the tradeoff/escalation rule (free interview material)
When two roles disagree, the `product-lead` decides for v1 — **but write the disagreement into
`docs/DECISIONS.md`** with the alternative and why it lost. Do this in the moment; that log is
literally the script for "why did you build it this way?" Ask the `gtm-narrative-lead` to mine it in
Week 7.

### 2.5 Good delegation habits
- **Isolate verbose work.** "Have `devops-reliability-engineer` run the sim smoke test and report
  only failures" keeps logs out of your main context (that's the whole point of subagents).
- **Parallelize independent lanes.** Sim setup, perception spike, and planner scaffolding don't
  depend on each other early — spin them up together.
- **Chain roles.** "Use `qa-safety-reviewer` to find avoidance failures, then `flight-software-engineer`
  to fix them."
- **Let agents keep notes.** Every engineering/QA agent has `memory: project` (see §3.2) — ask them
  to check memory before starting and save what they learned after.

---

## 3. Maintenance — keeping the team healthy as the project grows

### 3.1 Keep `CLAUDE.md` current
`CLAUDE.md` loads into **every** agent, so stale content there misinforms the whole team. When you
pin versions, change architecture, or move phase, update it. It is intentionally short — resist
bloating it; deep detail belongs in `docs/`.

### 3.2 Agent memory (`memory: project`)
Six agents have persistent per-project memory (`product-lead`, `tech-lead`, `perception-ml-engineer`,
`robotics-sim-engineer`, `flight-software-engineer`, `devops-reliability-engineer`, `qa-safety-reviewer`,
`gtm-narrative-lead` — all of them). Memory lives in `.claude/agent-memory/<agent-name>/` and is
committed to version control, so knowledge (pinned versions, gotchas, metric baselines, safety
scenarios) persists across sessions and is reviewable in diffs.
- Prompt them to use it: *"Check your memory for what we decided about X."* / *"Save what you learned."*
- If memory drifts or gets noisy, open the files and prune them like any other doc.
- To disable it for an agent, remove the `memory:` line from its frontmatter.

### 3.3 Editing and adding agents
- Agent files are plain Markdown + YAML frontmatter. Edit the body to sharpen a role's behavior;
  edit `description` to change *when* Claude auto-delegates (include "use proactively" to encourage it).
- Changes to existing files are picked up within a few seconds — **no restart**. Creating the *first*
  file in a new agents directory needs a restart (already done for this project).
- Keep `name:` values unique across the tree. Run `/doctor` in an interactive terminal if you suspect
  duplicates.
- Adding a role later (e.g. a `data-engineer` if the NDVI data volume grows) is just a new `.md` file.

### 3.4 Tune the permission allowlist
`.claude/settings.json` pre-approves routine ROS 2 / colcon / test / read-only git commands so you
aren't prompted constantly, while `git push`/`git commit`/`docker compose down` are set to *ask* and
destructive commands (`rm -rf`, `git reset --hard`, `git clean`) and secret reads are denied. As the
team settles into real commands, add the ones you trust to `allow`. Keep anything irreversible in
`ask` or `deny`. (In an interactive terminal, the `/permissions` UI helps; you can also just edit the JSON.)

### 3.5 Keep the docs alive
- `docs/ROADMAP.md` — update "Current status" and the cut/deferred log each standup.
- `docs/DECISIONS.md` — append an ADR whenever a real choice is made; fill in ADR-003 after the spike.
- These aren't bureaucracy — they're the artifacts that make the project interview-defensible.

### 3.6 Re-verify the schema periodically
The subagent frontmatter schema evolves. Before a big change to the agent files, re-check
`https://code.claude.com/docs/en/sub-agents` (the playbook itself warns about this). This scaffold
matches the schema as of July 2026.

---

## 4. Improvement suggestions (made, and optional)

### 4.1 Improvements already baked in (with the reason)
1. **Retargeted the AI/ML role from RAG to robotics perception.** The playbook's role assumed vector
   RAG; FieldGuard needs NDVI-frame detection, an avoidance decision policy, and an eval harness.
   Leaving it RAG-shaped would have produced confidently-wrong advice — the single most important fix.
2. **Added a dedicated `robotics-sim-engineer`.** The Gazebo/SITL/world/sensor setup is a large,
   distinct workstream; folding it into "full-stack" would have overloaded one role and hurt parallelism.
3. **Split engineering into three lanes (sim / perception / flight-software)** so independent work runs
   in parallel with stable interface contracts — this is what makes the team *scalable*.
4. **Elevated `qa-safety-reviewer` for a safety-critical system** with FieldGuard-specific failure modes
   (false negatives, silently-skipped cells, geofence breaches) instead of generic QA.
5. **Retargeted DevOps to reproducibility + headless CI + demo recording** — a local sim has no cloud
   bill, but it absolutely has environment-drift and demo-day-flakiness risk.
6. **Made evaluation a first-class mandate** ("no 'it works' without a metric") and gave it a home in
   `eval/` — this rigor is the strongest interview signal and directly serves the second-sensor arm.
7. **Formalized the escalation rule into `docs/DECISIONS.md`** so documented tradeoffs actually get
   captured as interview material instead of being lost in chat.
8. **Turned the standup cadence into a `/standup` command**, project context into `CLAUDE.md`, and the
   plan into a living `ROADMAP.md` — repeatable and version-controlled rather than ad hoc.
9. **Assigned models by role** (opus for judgment/architecture/safety, sonnet for execution) to balance
   quality against cost — the playbook's own DevOps ethos applied to the team itself.
10. **Persistent per-project memory** on every agent so the team compounds knowledge across sessions.

### 4.2 Optional next steps you might consider
- **CI provider now vs later:** stand up a minimal GitHub Actions workflow (build + headless smoke +
  eval) as soon as the sim runs headless — green CI on a portfolio repo is a strong signal.
  `devops-reliability-engineer` can scaffold it.
- **A `/eval` command** that runs the harness and prints the metric table, once `eval/` exists —
  makes "show me the numbers" a one-liner.
- **A `/demo` command** that runs the recorded demo scenario end to end before an interview.
- **Rename the project** from the working title "FieldGuard" if a better name emerges — the spec
  invites this; do it before the README goes public.
- **Diagram the architecture** (the tech-lead can produce a Mermaid diagram for the README) — hiring
  managers read diagrams faster than prose.

### 4.3 If you want to change model assignments
Edit the `model:` line in any agent file. Valid values: `opus`, `sonnet`, `haiku`, `fable`, a full
model ID, or `inherit` (match your session). To make every agent follow your session model, set each
to `inherit`. Lowering judgment roles to `sonnet` cuts cost; raising execution roles to `opus` raises
quality. There's no wrong answer — it's a cost/quality dial.

---

## 5. Quick reference

| I want to… | Do this |
|---|---|
| Start a work session | `/standup` |
| Get an architecture opinion | `As tech-lead, …` or `@tech-lead …` |
| Guarantee a specific role runs | `@<agent-name> …` |
| Run a whole session as one role | `claude --agent qa-safety-reviewer` |
| See the plan / current phase | open `docs/ROADMAP.md` |
| Record a design tradeoff | append to `docs/DECISIONS.md` (tech-lead) |
| Change when an agent auto-runs | edit its `description:` frontmatter |
| Change an agent's behavior | edit its Markdown body |
| Reduce permission prompts | add commands to `allow` in `.claude/settings.json` |
| Persist team knowledge | agents use `.claude/agent-memory/` (committed) |

---

*Built from `docs/tiger_team_playbook.md`, tailored to `docs/SPEC.md`. Subagent schema verified
against the official Claude Code sub-agents documentation, July 2026.*
