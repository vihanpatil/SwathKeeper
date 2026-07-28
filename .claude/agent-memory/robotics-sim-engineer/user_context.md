---
name: user-context
description: Who the developer is and their machine setup, relevant to how sim bringup work should be scoped.
metadata:
  type: user
---

Solo engineer (Vihan Patil) building FieldGuard as a portfolio project, ~7-8 week hard deadline
before a Europe trip. Develops on **macOS, Apple Silicon (arm64)**, with Docker Desktop installed.
Native Linux/ROS 2/Gazebo is not available — all sim work happens inside a Docker/Ubuntu container,
which shapes almost every setup recommendation (see [[macos_arm64_bringup_gotchas]]). Runs the
project through a "tiger team" of Claude Code subagents (this role is one of eight); coordinate
version pins and interface contracts with `tech-lead` and `devops-reliability-engineer` rather than
deciding those unilaterally.

How to apply: prefer container-first, headless-first solutions by default; don't propose native
macOS installs or GUI-dependent workflows as the primary path for this developer.
