---
name: toolchain-version-pins
description: FieldGuard sim toolchain pins confirmed for ADR-004 (ROS 2 Humble + Gazebo Harmonic + ardupilot_gz) and the reasoning behind the ArduPilot SITL branch choice.
metadata:
  type: project
---

Confirmed (2026-07-27, via ArduPilot's own `ardupilot_gz` docs + the Feb 2026
`aerial-autonomy-stack` reference, which independently pins the same ROS 2/Gazebo combo) that
ADR-004's provisional pin — **ROS 2 Humble + Gazebo Harmonic**, in a Docker/Ubuntu 22.04 container
— is correct and should be accepted as-is. No landscape shift found; this is still ArduPilot's
primary documented/CI-tested stack as of mid-2026. See [[macos_arm64_bringup_gotchas]] for the
Apple-Silicon-specific execution risk on top of this pin.

Exact component pins (from `ardupilot_gz`'s own `ros2_gz.repos`, the source ArduPilot documents):
- `ardupilot_gz` (github.com/ArduPilot/ardupilot_gz) — branch `main`
- `ardupilot_gazebo` (github.com/ArduPilot/ardupilot_gazebo) — branch `ros2` (not `main` — the ROS 2
  integration lives on a separate branch of this repo, easy to miss)
- `ros_gz`, `sdformat_urdf`, `micro-ROS-Agent` — all branch `humble`
- `SITL_Models` (github.com/ArduPilot/SITL_Models) — branch `main`
- ArduPilot firmware itself (github.com/ArduPilot/ardupilot) — pinned to branch **`master`**, not a
  stable Copter-4.x tag.

**Why master, not a stable tag, for the ArduPilot firmware pin:** `ardupilot_gz`'s own CI tracks
ArduPilot `master`, because the AP_DDS (ROS 2 DDS bridge) surface evolves in step with master. A
several-months-old stable tag (e.g. Copter-4.6.3, which is what the `aerial-autonomy-stack`
reference paper uses for its own PX4/ArduPilot pins) risks a DDS topic/message mismatch against a
current `ardupilot_gz`. Recommendation given to the human: pin to a **specific commit SHA on
master**, captured right after the Week 1 build first goes green, rather than either a floating
branch or an old stable tag — reproducible, and matches what upstream actually tests against.

How to apply: when asked to help debug a DDS/topic-shape mismatch, check this reasoning before
suggesting "just use a stable Copter release" — that's the alternative that was deliberately
rejected here, and reintroducing it would reopen the exact ABI-mismatch risk this pin was chosen to
avoid.

Source of truth once the human pastes the resolved SHAs: `CLAUDE.md` "Pinned versions" section.
This memory explains the *reasoning*; treat `CLAUDE.md` as authoritative for the *current* pinned
SHA if the two ever disagree.
