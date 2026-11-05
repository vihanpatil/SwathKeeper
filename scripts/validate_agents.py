#!/usr/bin/env python3
"""Validate the SwathKeeper tiger-team configuration.

Checks agent frontmatter (name/description/model/color/memory/effort, known fields only, every
`skills:` entry resolves), skill frontmatter (.claude/skills/*/SKILL.md: name == directory,
description, known fields only), settings.json validity (and that every `command` hook's script
exists and is executable), and that the expected project structure exists. Run locally
(`python scripts/validate_agents.py`, from ANY directory -- see REPO_ROOT below) or in CI. Exits non-zero on any error so CI fails
loudly on a broken config.
"""
import glob
import json
import os
import re
import shlex
import sys
from pathlib import Path

# Every path below resolves from THIS FILE's location, never the caller's cwd. CI happens to run
# `python scripts/validate_agents.py` from the repo root, but a human or a hook invoking it by
# absolute path from somewhere else used to get a wall of bogus "missing expected directory"
# errors -- and, in a directory that happens to share the layout, could have validated the WRONG
# repo's agents and printed a green PASS (2026-08-18 audit finding).
REPO_ROOT = Path(__file__).resolve().parent.parent

VALID_MODELS = {"opus", "sonnet", "haiku", "fable", "inherit"}
VALID_COLORS = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"}
VALID_MEMORY = {"user", "project", "local"}
VALID_EFFORT = {"low", "medium", "high", "xhigh", "max"}
EXPECTED_DIRS = ["src", "sim", "config", "scripts", "eval", "tests", "docs", ".claude/agents",
                 ".claude/skills"]
# Claude Code IGNORES unknown frontmatter fields silently -- a typo'd `efort:` or `skils:` would just
# vanish, leaving an agent running without the setting its author believes it has. So an unknown
# field is an ERROR here, not a warning.
KNOWN_AGENT_FIELDS = {
    "name", "description", "tools", "disallowedTools", "model", "permissionMode", "maxTurns",
    "skills", "mcpServers", "hooks", "memory", "background", "effort", "isolation", "color",
    "initialPrompt", "autoCompactWindow", "omitClaudeMd", "experimental",
}
KNOWN_SKILL_FIELDS = {
    "name", "description", "when_to_use", "argument-hint", "arguments", "disable-model-invocation",
    "user-invocable", "allowed-tools", "disallowed-tools", "model", "effort", "context", "agent",
    "background", "hooks", "paths", "shell",
}
# A hook command that starts with one of these runs the NEXT token as its script.
HOOK_INTERPRETERS = {"bash", "sh", "zsh", "python", "python3", "node", "env"}

try:
    import yaml
except ImportError:
    print("::error::PyYAML not installed. Run: pip install pyyaml")
    sys.exit(2)


def rel(path) -> str:
    """Repo-relative display path, so messages read identically from any cwd."""
    return Path(path).resolve().relative_to(REPO_ROOT).as_posix()


def frontmatter(path):
    """(data, body) for a `---`-fenced YAML frontmatter file, or None after recording an error."""
    text = Path(path).read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.S)
    if not m:
        errors.append(f"{rel(path)}: missing or malformed YAML frontmatter")
        return None
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        errors.append(f"{rel(path)}: YAML parse error: {e}")
        return None
    if not isinstance(data, dict):
        errors.append(f"{rel(path)}: frontmatter is not a YAML mapping")
        return None
    return data, m.group(2).strip()


def as_list(value):
    """A frontmatter list field may be a YAML list or a comma-separated string."""
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split(",") if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value]
    return [str(value)]


errors = []
names = {}

agent_files = sorted(glob.glob(str(REPO_ROOT / ".claude" / "agents" / "*.md")))
if not agent_files:
    errors.append("no agent files found under .claude/agents/")

for f in agent_files:
    text = Path(f).read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        errors.append(f"{rel(f)}: missing or malformed YAML frontmatter")
        continue
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        errors.append(f"{rel(f)}: YAML parse error: {e}")
        continue
    if not isinstance(data, dict):
        errors.append(f"{rel(f)}: frontmatter is not a YAML mapping")
        continue
    body = m.group(2).strip()

    for key in sorted(set(data) - KNOWN_AGENT_FIELDS):
        errors.append(f"{rel(f)}: unknown frontmatter field {key!r} (Claude Code would ignore it "
                      f"silently; known: {', '.join(sorted(KNOWN_AGENT_FIELDS))})")

    effort = data.get("effort")
    if effort is not None and effort not in VALID_EFFORT:
        errors.append(f"{rel(f)}: invalid effort {effort!r} (one of {sorted(VALID_EFFORT)})")

    for skill in as_list(data.get("skills")):
        if not (REPO_ROOT / ".claude" / "skills" / skill / "SKILL.md").is_file():
            errors.append(f"{rel(f)}: skills entry {skill!r} has no .claude/skills/{skill}/SKILL.md")

    name = data.get("name", "")
    if not re.fullmatch(r"[a-z0-9-]+", str(name)):
        errors.append(f"{rel(f)}: bad/missing name {name!r} (lowercase letters, digits, hyphens only)")
    if name in names:
        errors.append(f"{rel(f)}: duplicate name {name!r} (also in {rel(names[name])})")
    names[name] = f

    if not data.get("description"):
        errors.append(f"{rel(f)}: missing required 'description'")

    model = data.get("model")
    if model and model not in VALID_MODELS and not str(model).startswith("claude-"):
        errors.append(f"{rel(f)}: invalid model {model!r}")

    color = data.get("color")
    if color and color not in VALID_COLORS:
        errors.append(f"{rel(f)}: invalid color {color!r}")

    memory = data.get("memory")
    if memory and memory not in VALID_MEMORY:
        errors.append(f"{rel(f)}: invalid memory scope {memory!r}")

    if not body:
        errors.append(f"{rel(f)}: empty system prompt body")

# skills: .claude/skills/<name>/SKILL.md
skill_dirs = sorted(d for d in (REPO_ROOT / ".claude" / "skills").glob("*") if d.is_dir())
skills_validated = 0
for d in skill_dirs:
    sk = d / "SKILL.md"
    if not sk.is_file():
        errors.append(f"{rel(d)}/: skill directory without SKILL.md")
        continue
    skills_validated += 1
    parsed = frontmatter(sk)
    if parsed is None:
        continue
    data, _body = parsed
    if "name" in data and str(data["name"]) != d.name:
        errors.append(f"{rel(sk)}: name {data['name']!r} != its directory {d.name!r}")
    if not data.get("description"):
        errors.append(f"{rel(sk)}: missing required 'description'")
    for key in sorted(set(data) - KNOWN_SKILL_FIELDS):
        errors.append(f"{rel(sk)}: unknown frontmatter field {key!r} (Claude Code would ignore it "
                      f"silently; known: {', '.join(sorted(KNOWN_SKILL_FIELDS))})")
    effort = data.get("effort")
    if effort is not None and effort not in VALID_EFFORT:
        errors.append(f"{rel(sk)}: invalid effort {effort!r} (one of {sorted(VALID_EFFORT)})")


def hook_script(command):
    """The script path a `command` hook runs, with ${CLAUDE_PROJECT_DIR} expanded; None if the
    command is a bare PATH program (no '/' in it), which has no file of ours to check."""
    expanded = (command.replace("${CLAUDE_PROJECT_DIR}", str(REPO_ROOT))
                       .replace("$CLAUDE_PROJECT_DIR", str(REPO_ROOT)))
    try:
        tokens = shlex.split(expanded)
    except ValueError:
        tokens = expanded.split()
    while tokens and (tokens[0] in HOOK_INTERPRETERS or re.fullmatch(r"\w+=.*", tokens[0])):
        tokens = tokens[1:]
        while tokens and tokens[0].startswith("-"):   # interpreter flags: bash -e, env -i
            tokens = tokens[1:]
    if not tokens or "/" not in tokens[0]:
        return None
    path = Path(tokens[0])
    return path if path.is_absolute() else REPO_ROOT / path


# settings.json must be valid JSON if present; its command hooks must point at runnable scripts
settings = REPO_ROOT / ".claude" / "settings.json"
if settings.exists():
    try:
        settings_data = json.loads(settings.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"{rel(settings)}: invalid JSON: {e}")
        settings_data = {}
    hooks = settings_data.get("hooks") if isinstance(settings_data, dict) else None
    if hooks is not None and not isinstance(hooks, dict):
        errors.append(f"{rel(settings)}: 'hooks' must be an object keyed by event name")
    elif hooks:
        for event, groups in hooks.items():
            for group in groups if isinstance(groups, list) else []:
                for hook in (group.get("hooks") or []) if isinstance(group, dict) else []:
                    if not isinstance(hook, dict) or hook.get("type") != "command":
                        continue
                    script = hook_script(str(hook.get("command", "")))
                    if script is None:
                        continue
                    shown = (Path(os.path.normpath(script)).relative_to(REPO_ROOT).as_posix()
                             if str(script).startswith(str(REPO_ROOT)) else str(script))
                    if not script.is_file():
                        errors.append(f"{rel(settings)}: {event} hook script {shown} does not exist")
                    elif not os.access(script, os.X_OK):
                        errors.append(f"{rel(settings)}: {event} hook script {shown} is not "
                                      f"executable (chmod +x)")

# expected structure
for d in EXPECTED_DIRS:
    if not (REPO_ROOT / d).is_dir():
        errors.append(f"missing expected directory: {d}/")

if errors:
    print("SwathKeeper config validation FAILED:")
    for e in errors:
        print(f"  ::error::{e}")
    sys.exit(1)

print(f"SwathKeeper config OK: {len(agent_files)} agents validated, "
      f"{skills_validated} skills validated, settings.json valid, project structure present.")
