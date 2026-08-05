---
name: reference-pinned-versions
description: Where each layer of FieldGuard's pinned-version info lives (CLAUDE.md, requirements-eval.txt, ADR-004)
metadata:
  type: reference
---

Pinned-version info is split across layers, don't duplicate, point to the source:
- ArduPilot/Gazebo/ROS 2/ardupilot_gazebo/SITL_Models branches + exact firmware SHAs: `CLAUDE.md`
  "Pinned versions" section (ADR-004, owned by robotics-sim-engineer + devops). Ubuntu 22.04 in
  Docker — this whole stack is not natively supported on macOS, hence devops runs Python-only tooling
  natively but defers Docker/Gazebo work to the human-operated container (see `sim/README.md`).
- Eval-harness Python deps (numpy, scipy): `requirements-eval.txt` at repo root, devops-owned.
  Pinned to numpy==2.5.1, scipy==1.18.0 as of 2026-08-04 — verified installable + working on Python
  3.12.12 and confirmed to have manylinux cp312 x86_64 wheels on PyPI (matches ubuntu-latest CI).
  `tests/fieldguard_planning/` deliberately has NO requirements file — it's stdlib-only, that's a
  documented feature (zero install step for the planning test suite).
- `validate-config` CI job's `pyyaml` (used only by `scripts/validate_agents.py`) is still installed
  unpinned inline (`pip install pyyaml`) — left as-is per an explicit Week 2 instruction to keep that
  job "intact"; flagged as a follow-up to pin later, not yet done.
