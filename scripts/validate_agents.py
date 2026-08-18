#!/usr/bin/env python3
"""Validate the SwathKeeper tiger-team configuration.

Checks agent frontmatter (name/description/model/color/memory), settings.json validity,
and that the expected project structure exists. Run locally (`python scripts/validate_agents.py`,
from ANY directory -- see REPO_ROOT below) or in CI. Exits non-zero on any error so CI fails
loudly on a broken config.
"""
import glob
import json
import re
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
EXPECTED_DIRS = ["src", "sim", "config", "scripts", "eval", "tests", "docs", ".claude/agents"]

try:
    import yaml
except ImportError:
    print("::error::PyYAML not installed. Run: pip install pyyaml")
    sys.exit(2)


def rel(path) -> str:
    """Repo-relative display path, so messages read identically from any cwd."""
    return Path(path).resolve().relative_to(REPO_ROOT).as_posix()


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
    body = m.group(2).strip()

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

# settings.json must be valid JSON if present
settings = REPO_ROOT / ".claude" / "settings.json"
if settings.exists():
    try:
        json.loads(settings.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"{rel(settings)}: invalid JSON: {e}")

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
      f"settings.json valid, project structure present.")
