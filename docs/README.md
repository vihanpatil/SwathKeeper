# SwathKeeper docs — read me first

**New here?** Start at the [repo README](../README.md) for what this is, then
[`SETUP.md`](../SETUP.md) to run it. This folder is for when you want to judge the engineering:
read [`SPEC.md`](SPEC.md), then [`ROADMAP.md`](ROADMAP.md), then [`DECISIONS.md`](DECISIONS.md).

Three kinds of document live here, and the kind tells you how much to trust it.

**Living** (always current — if these disagree with anything else, these win):
- [`SPEC.md`](SPEC.md) — **what the system is**: the architecture as built, the interfaces it is
  built on, and the assumptions each part is allowed to make. Read this first if you want the shape.
- [`ROADMAP.md`](ROADMAP.md) — **where it actually stands today**, what is next in order, the traps
  learned the expensive way, and a cut log of everything deliberately *not* built. The only file
  allowed to answer "is it done?".
- [`DECISIONS.md`](DECISIONS.md) — **why it is built this way**: every non-trivial choice with the
  alternative that lost and a one-line reason (ADR log). Append-only, so corrections land as dated
  amendments and you can watch a decision get reopened, re-measured, and closed. The most
  interesting file in the repo.
- [`BUILD_LOG.md`](BUILD_LOG.md) — **the narrative**: what shipped, what broke, and what the break
  taught. Read it when you want the story rather than the state.

**Runbooks** (`runbooks/` — operational, run inside the Docker sim session; four, and you run all
four):
- [`runbooks/SIM_BRINGUP.md`](runbooks/SIM_BRINGUP.md) — **how to rebuild the environment from
  scratch**: image, ROS 2 workspace, ArduPilot with `--enable-DDS`, and the four macOS gotchas.
  You need this once, or when a layer breaks. To *fly*, use `scripts/fly_pipeline.sh` instead.
- [`runbooks/FULL_PIPELINE_DEMO.md`](runbooks/FULL_PIPELINE_DEMO.md) — **the showpiece flight**:
  survey + birds + live NDVI + recording + heatmap, shell by shell, wrapped by one launcher command.
  This is the flight that produces the artifacts everything else is measured on.
- [`runbooks/AVOIDANCE_REAL_DETECTION.md`](runbooks/AVOIDANCE_REAL_DETECTION.md) — **the take where
  the drone dodges a bird it detected itself**: both preflights, the human-flown rule, evidence-first
  teardown, and the post-flight safety gate. It carries a pre-registered expectation, written before
  the flight, that this flight may honestly fail its own gate. Worth reading even if you never run it.
- [`runbooks/AVOIDANCE_DEMO.md`](runbooks/AVOIDANCE_DEMO.md) — **the deterministic regression arm**:
  `avoidance_node --demo` with scripted birds, for checking the loop still behaves without paying
  for perception. Its bringup half is superseded — its own banner says which half is which. Read that
  banner first for the other reason: both of this repo's ACKNOWLEDGED bird-clearance breaches were
  flown on this arm, the escape geometry behind them is still open, and **a re-run is expected to
  breach again** — the banner carries the CPA bar and the two-half rule for what to do when it does.

**Historical** (`archive/` — frozen records, kept because live docs and committed ADRs cite them;
plus [`SPIKE_ndvi_vs_rgb.md`](SPIKE_ndvi_vs_rgb.md), the closed ADR-003 spike, left outside
`archive/` only because ADR-003's committed text links it by that path):
- [`archive/NDVI_VALIDATION.md`](archive/NDVI_VALIDATION.md) — the ADR-007 gate record: four gates
  green (0 on 2026-08-05, 1-3 on 2026-08-18) and the two bugs found live. Archived 2026-08-25.
- [`archive/SIM_CI.md`](archive/SIM_CI.md) — the headless sim-CI plan and its honest verdict that
  rendering Gazebo on a hosted runner is unproven. Became ADR-008. Archived 2026-08-25.
- [`archive/WEEK3_VALIDATION.md`](archive/WEEK3_VALIDATION.md) — the session that first put the
  whole stack in the air (three gates passed 2026-08-05) and confirmed ADR-005 and ADR-006.
- [`archive/tiger_team_playbook.md`](archive/tiger_team_playbook.md) — the generic playbook this
  repo's agent team was adapted from; see [`TIGER_TEAM_GUIDE.md`](../TIGER_TEAM_GUIDE.md).

Stubs remain at the two archived runbooks' old paths so older links keep resolving —
`DECISIONS.md` is append-only, so a path it once linked has to stay reachable forever.
