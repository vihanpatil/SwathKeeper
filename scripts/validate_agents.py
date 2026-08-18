#!/usr/bin/env python3
"""Validate the SwathKeeper tiger-team configuration.

Checks agent frontmatter (name/description/model/color/memory), settings.json validity,
and that the expected project structure exists. Run locally (`python scripts/validate_agents.py`)
or in CI. Exits non-zero on any error so CI fails loudly on a broken config.
"""
import glob
import json
import os
import re
import sys

try:
    import yaml
except ImportError:
    print("::error::PyYAML not installed. Run: pip install pyyaml")
    sys.exit(2)

VALID_MODELS = {"opus", "sonnet", "haiku", "fable", "inherit"}
VALID_COLORS = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"}
VALID_MEMORY = {"user", "project", "local"}
EXPECTED_DIRS = ["src", "sim", "config", "scripts", "eval", "tests", "docs", ".claude/agents"]

errors = []
names = {}

agent_files = sorted(glob.glob(".claude/agents/*.md"))
if not agent_files:
    errors.append("no agent files found under .claude/agents/")

for f in agent_files:
    text = open(f, encoding="utf-8").read()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        errors.append(f"{f}: missing or malformed YAML frontmatter")
        continue
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        errors.append(f"{f}: YAML parse error: {e}")
        continue
    body = m.group(2).strip()

    name = data.get("name", "")
    if not re.fullmatch(r"[a-z0-9-]+", str(name)):
        errors.append(f"{f}: bad/missing name {name!r} (lowercase letters, digits, hyphens only)")
    if name in names:
        errors.append(f"{f}: duplicate name {name!r} (also in {names[name]})")
    names[name] = f

    if not data.get("description"):
        errors.append(f"{f}: missing required 'description'")

    model = data.get("model")
    if model and model not in VALID_MODELS and not str(model).startswith("claude-"):
        errors.append(f"{f}: invalid model {model!r}")

    color = data.get("color")
    if color and color not in VALID_COLORS:
        errors.append(f"{f}: invalid color {color!r}")

    memory = data.get("memory")
    if memory and memory not in VALID_MEMORY:
        errors.append(f"{f}: invalid memory scope {memory!r}")

    if not body:
        errors.append(f"{f}: empty system prompt body")

# settings.json must be valid JSON if present
settings = ".claude/settings.json"
if os.path.exists(settings):
    try:
        json.load(open(settings, encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"{settings}: invalid JSON: {e}")

# expected structure
for d in EXPECTED_DIRS:
    if not os.path.isdir(d):
        errors.append(f"missing expected directory: {d}/")

if errors:
    print("SwathKeeper config validation FAILED:")
    for e in errors:
        print(f"  ::error::{e}")
    sys.exit(1)

print(f"SwathKeeper config OK: {len(agent_files)} agents validated, "
      f"settings.json valid, project structure present.")
