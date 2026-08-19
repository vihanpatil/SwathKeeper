# SwathKeeper docs — read me first

Three kinds of documents live here. Know which kind you're holding:

**Living** (always current — if these disagree with anything else, these win):
- [`SPEC.md`](SPEC.md) — what the system is and how it's built
- [`ROADMAP.md`](ROADMAP.md) — where we are and what's next
- [`DECISIONS.md`](DECISIONS.md) — every non-trivial choice, with the rejected alternative (ADR log; interview script)
- [`BUILD_LOG.md`](BUILD_LOG.md) — chronological narrative: what shipped, what broke, what it taught

**Runbooks** (`runbooks/` — operational, executed in Docker sessions; named by function):
- [`runbooks/SIM_BRINGUP.md`](runbooks/SIM_BRINGUP.md) — build the image, bring up Gazebo → micro-ROS agent → SITL (in that order)
- [`runbooks/AVOIDANCE_DEMO.md`](runbooks/AVOIDANCE_DEMO.md) — reproduce the live reactive-avoidance demo
- [`runbooks/NDVI_VALIDATION.md`](runbooks/NDVI_VALIDATION.md) — the ADR-007 gate record: all four gates ✅ (0: 2026-08-05; 1-3: 2026-08-18) + session logs
- [`runbooks/FULL_PIPELINE_DEMO.md`](runbooks/FULL_PIPELINE_DEMO.md) — THE showpiece: survey + birds + live NDVI + recording + heatmap, shell by shell
- [`runbooks/SIM_CI.md`](runbooks/SIM_CI.md) — the headless sim-CI chain: image build, dispatch, cut-list

**Historical** (`archive/` — records, deliberately frozen; plus `docs/SPIKE_ndvi_vs_rgb.md` — the
closed ADR-003 spike, left outside `archive/` because ADR-003 links it by that path):
- [`archive/WEEK3_VALIDATION.md`](archive/WEEK3_VALIDATION.md) — the Week-3 gate session record (all 3 gates passed 2026-08-05)
- [`archive/tiger_team_playbook.md`](archive/tiger_team_playbook.md) — the original pre-project playbook
