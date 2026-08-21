# Sim CI — the Headless Docker/Gazebo CI Chain *(runbook; born Weeks 5-6, devops-reliability-engineer)*

**Status (2026-08-18): written and reviewed, never run.** The 2-3-day timebox has not started. Its
one external prerequisite — a live-verified render — is now satisfied (`NDVI_VALIDATION.md`, gates
0-3 green), so every step in "What needs the human" below is unblocked and still open.

Promoted from the Weeks 3-4 "deferred, non-blocking"
line (`docs/ROADMAP.md`) by an external review: *"The genuinely impressive missing piece is the
deferred headless Docker/Gazebo CI job... promote it to Week 5-6, budget 2-3 days, and timebox it
hard."* This doc is the committed plan plus an honest account of what got built vs. what still needs a
human. **Owner: `devops-reliability-engineer`.** Does not edit `docs/ROADMAP.md` — `product-lead` owns
that file; see the one-paragraph status at the bottom of this doc for them to paste in.

> **Update 2026-08-18: `sim-image.yml` is GREEN — the image build half of this doc's crux is
> resolved.** Run 32208264797 (watched `workflow_dispatch`): whole job 27m18s on hosted
> `ubuntu-latest`, colcon 14 packages in 13m53s at `-j2` with no OOM, waf copter 1m32s, image pushed
> to `ghcr.io/vihanpatil/fieldguard-sim` (`:latest` + commit-SHA tag) — the first image this
> workflow ever published. Every prior run had died at `Dockerfile.ci`'s first ROS-sourcing RUN
> layer: Docker's default `/bin/sh` is dash, which cannot source ROS's bash-only setup files
> (`SHELL ["/bin/bash", "-c"]` fixed it), and the next layer down then hit rosdep installing
> against the base image's emptied apt lists (in-layer `apt-get update` fixed that). The
> disk/OOM/time fears below turned out fine for the **build** after the workflow's free-disk step
> (~25GB reclaimed). Still true and still open: the **headless-render smoke flight** ("What needs
> the human" steps 2-4, `ci.yml`'s `build-test-sim`) has never run — the render-path verdict below
> stands. The self-hosted-runner fallback was not needed.

## Feasibility verdict on headless-render CI on GitHub-hosted runners (the crux question)

**Short answer: full Gazebo Harmonic + ArduPilot SITL + ROS 2, with real camera/thermal sensor
rendering, on a GitHub-hosted runner is not proven feasible — and there is no known precedent for it,
including from the authoritative upstream maintainers of these exact components.** This is not a guess;
it's grounded in three checks run before writing any YAML:

1. **`ArduPilot/ardupilot_gazebo`'s own CI** (`.github/workflows/ubuntu-build.yml`, `ccpcheck.yml`,
   `ccplint.yml`) runs on `ubuntu-22.04` hosted runners but is **build + lint + static-analysis only**
   — it compiles the plugin against an apt-installed Gazebo, with `ccache`, and stops. It never
   launches Gazebo or ArduPilot SITL. If the team that owns the plugin doesn't run a live sim on hosted
   runners, that's the strongest available signal about what's actually load-bearing here.
2. **`ArduPilot/ardupilot`'s own SITL autotest CI** (`test_sitl_copter.yml` etc.) *does* run real
   flights on hosted `ubuntu-22.04` runners — but that's **plain built-in SITL physics, no Gazebo, no
   rendering**, in a prebuilt `ardupilot-dev-base` container with `ccache` and a test matrix split into
   groups to fit the time budget. This is good evidence that **SITL flight alone is hosted-runner
   feasible**; it says nothing about Gazebo rendering.
3. **Resource math**: `docs/runbooks/SIM_BRINGUP.md`'s own documented minimum spec is **≥6 CPUs, ≥8GB RAM,
   ≥40GB disk**, and the workspace build has **already OOM'd once** at higher parallelism on a Docker
   Desktop config *more generously resourced* than that minimum. GitHub-hosted public `ubuntu-latest`
   runners are **4 vCPU / 16GB RAM / 14GB SSD** — the disk figure alone (14GB vs. a documented 40GB
   minimum, before any Gazebo world assets or a multi-GB pulled image) is close to disqualifying for a
   from-scratch build, and tight even for pulling a prebuilt image on top of a repo checkout.

**Conclusion, stated plainly (no oversell):** baking the pinned-SHA workspace into an image and
publishing it decouples the *build* from every CI run, which is the right fix for the resource
math above — but whether the resulting image, once pulled onto a hosted runner, can actually
**initialize Gazebo's headless render path (EGL + software OpenGL) and fly** is genuinely unverified
and unprecedented even by upstream. This session had no live Docker/Gazebo runner to test that
end-to-end, so the honest status is: **implemented and locally reviewed, gated to manual dispatch, not
claimed green.**

**The render is unavoidable for this job.** The vehicle model this smoke flies is
`iris_with_gimbal_ndvi`, which carries the ADR-007 RGB+thermal sensor pair, and Gazebo renders every
attached sensor whether or not anything subscribes. So the "flight-only smoke needs no camera
render" scope reduction (`Dockerfile.ci` / `ci_sim_smoke.sh` comments) avoids only the ROS 2/DDS
bridge and `ndvi_node`, not the ogre2 path. Cut-list item 6 is the escape hatch.

**Realistic fallback if hosted runners can't do it:** a **self-hosted runner** registered against the
same machine/Docker config already proven in `docs/archive/WEEK3_VALIDATION.md` (the human's own Docker
Desktop session, or a cloud VM with the documented minimum spec). This sidesteps the resource ceiling
entirely because it's the same environment already known to work — the cost is an operational one (a
machine has to be online to pick up the job), which is a reasonable tradeoff to document for a
portfolio CI but is **not implemented here** — it needs a persistently-available machine, which is the
human's call, not a code change.

## What was implemented this session (no live runner available)

| Artifact | What it does | Verified how |
|---|---|---|
| `sim/docker/Dockerfile.ci` | Bakes ROS 2 Humble + Gazebo Harmonic + `ardupilot_gazebo`/`ardupilot_gz` + ArduPilot SITL (pinned to the **exact commit SHAs** in `CLAUDE.md`, not floating branches) into image layers, `--enable-DDS` deliberately **excluded** (see cut-list #1) | Manual review only. **Not built** in this session — see "What needs the human" |
| `.github/workflows/sim-image.yml` | Builds `Dockerfile.ci`, pushes to GHCR (`ghcr.io/<owner>/fieldguard-sim`). Manual dispatch or on Dockerfile/pin changes — **decoupled from every push**, which is the direct fix for "CI shouldn't rebuild from scratch every run" | `actionlint` clean. Never executed (no live runner/GHCR credentials in this session) |
| `scripts/gen_boustrophedon.py` (reused, unchanged) | Generates the short scripted mission: `--width 20 --height 30 --spacing 15 --alt 15` → 2 lanes, 4 coverage waypoints, 7 mission items | **Executed locally**: 7 mission items / 4 coverage waypoints across 2 lanes, re-verified 2026-08-18. Same generator, same home lat/lon, same 15 m lane spacing as the 6-lane mission — but `--height 30` vs `60` makes the lanes half as long, so it is **not** a prefix of that file (rows 3-4 differ) |
| `scripts/ci_sim_smoke.py` | Non-interactive pymavlink driver: connect → EKF settle → one-time FRAME_CLASS/TYPE+reboot (the documented `docs/runbooks/SIM_BRINGUP.md` §6 gotcha) → upload mission → AUTO+arm → poll `MISSION_ITEM_REACHED` → wait disarm → write a JSON summary | **QGC-WPL parser + waypoint-counting logic executed and checked locally** against the real generated mission file (4/4 coverage waypoints, correctly excluding the home placeholder row). **The live MAVLink control flow itself is UNVERIFIED** — no SITL to connect to in this session |
| `scripts/ci_sim_smoke.sh` | Orchestrates `gz sim --headless-rendering` + `sim_vehicle.py --no-mavproxy` (reuses the exact entry point already proven interactively, not a hand-rolled binary invocation) + the Python driver, with timeouts and cleanup traps | `bash -n` syntax-checked. **Never run** — needs a live container |
| `scripts/check_sim_smoke.py` | Regression gate: reads the JSON summary, fails the build on any missed waypoint, un-armed, un-disarmed, timeout, or driver error | **Fully unit-verified locally** — 5 fixture JSONs (clean pass, missed waypoint, driver error, never-disarmed/timeout, missing file) all produce the expected exit code and failure reasons. This is the one artifact in this list with the same "run it, don't just write it" discipline applied to every other CI gate in this repo |
| `.github/workflows/ci.yml` `build-test-sim` job | Pulls the GHCR image, runs the smoke script + gate, uploads artifacts. **Gated to `workflow_dispatch` only** — will not run on every push until a human confirms one green run | `actionlint` clean. Never executed |

**Never claim green without proof** (standing rule for this role): none of the above has run against a
live Gazebo/SITL process. Every piece that *could* be exercised without one — the mission generator,
the WPL parser, the regression-gate script — was actually run, not just read for plausibility. Every
piece that needs a live process is explicitly marked unverified in its own file header, with the
single riskiest unverified assumption called out inline (the `tcp:127.0.0.1:5760` default connection
port for SITL without MAVProxy — flagged as the first thing to check if the driver can't connect).

## What needs the human (in order)

1. **Build `Dockerfile.ci` once, locally**, on the already-proven Docker Desktop setup
   (`docker build -f sim/docker/Dockerfile.ci -t fieldguard-sim:ci .`, after building
   `sim/docker/Dockerfile` first). Watch for: disk usage, whether the colcon build OOMs at `-j2`, and
   whether the non-interactive `./waf configure --board sitl && ./waf copter` step produces a binary
   that boots and flies like the one already proven in `docs/archive/WEEK3_VALIDATION.md`.
2. **Run `scripts/ci_sim_smoke.sh` inside that image**, manually, watching the raw logs. This is where
   the unverified assumptions (SITL's default port, the FRAME_CLASS/TYPE reboot timing, `gz sim
   --headless-rendering` actually initializing on this host) get resolved. Fix forward in the script
   itself — the structure (driver writes JSON, gate script grades it) should not need to change even if
   the MAVLink sequencing does. **Sequencing note — satisfied 2026-08-18:** this step used to wait on
   the render-verification session (thermal kill-switch, pixel smoke test). Those gates are green
   (`NDVI_VALIDATION.md`), so the render is known to load on this stack and this smoke job is
   unblocked.
3. **Manually trigger `sim-image.yml`** (`workflow_dispatch`) on the actual repo, and separately
   **manually trigger `ci.yml`'s `build-test-sim` job**, to learn whether the hosted-runner resource
   math above (§ Feasibility verdict) is actually disqualifying or just tight. If it fails on disk/OOM/
   timeout, that confirms the fallback (self-hosted runner) is the real next step, not a bigger hosted
   tier (GitHub doesn't currently offer more disk on the same free/standard tier for a portfolio repo).
4. Only after a **confirmed green run**, flip `build-test-sim`'s `if: github.event_name ==
   'workflow_dispatch'` to run on every push/PR (or `main`-only, human's call) — per this role's
   standing feedback: never claim CI is green from a plausible-looking YAML change; verify, then widen
   the gate.

## Timebox breakdown (2-3 days, hard cap — per the review's explicit instruction)

| Day | Scope | Done this session? |
|---|---|---|
| **1** | `Dockerfile.ci` (pinned SHAs, workspace baked in, DDS excluded) + `sim-image.yml` (GHCR publish, decoupled from push cadence) | ✅ written + `actionlint`-clean; ⏳ never built/run (needs the human, step 1 above) |
| **2** | Scripted mission (reuse `gen_boustrophedon.py`, no new flags) + non-interactive driver (`ci_sim_smoke.py`/`.sh`) + regression gate (`check_sim_smoke.py`) + wire `build-test-sim` into `ci.yml`, manual-dispatch-gated | ✅ written; mission generator + WPL parser + gate script **actually executed and verified**; live MAVLink flow ⏳ unverified (needs the human, step 2 above) |
| **3 (buffer)** | Human runs steps 1-4 above, fixes whatever breaks (something will — this stack has broken in a new way at every prior gate: 6 bugs at Week 3's Docker session alone), flips the trigger once green | Not done — explicitly the human's slot, held open on purpose rather than guessed at |

**If Day 3 isn't enough**, that is the timebox working as intended, not a failure: stop, ship what's
green (even if that's "the image builds and boots SITL, but the mission driver needs another pass"),
and apply the cut-list below rather than let this bleed into Week 6's NDVI-pipeline work — the review's
whole point was "Weeks 5-6 slipping is the #1 project risk."

## Cut-list (apply in this order if the timebox runs long)

1. **Cut the CI job from running automatically at all.** Ship `Dockerfile.ci` + the scripts as
   documented, human-runnable infrastructure (`docs/runbooks/SIM_BRINGUP.md`-style, run by hand in the
   container) without a working hosted-runner CI trigger. The resume-relevant claim becomes "a
   reproducible headless-sim image + a scripted regression-gated smoke test exist and run
   reproducibly" rather than "GitHub Actions runs it on every push" — still real, still defensible,
   just honestly scoped to what a hosted runner can actually do. This is the single biggest,
   highest-leverage cut if the resource math in the Feasibility verdict turns out to be disqualifying.
2. **Cut `--enable-DDS` / the ROS 2 avoidance loop from the CI smoke entirely** (already the default
   scope decision, not just a fallback — see `Dockerfile.ci`'s own header). The avoidance loop is
   already unit-tested sim-agnostically in the no-Docker `planning-and-eval` job; the Gazebo job's only
   remaining job is proving "the built asset pipeline (world, mission, SITL, pinned versions) actually
   boots and flies," which doesn't need DDS.
3. **Cut Docker image hardening** (non-root user, multi-stage build, minimized layers). Ship a
   single-stage, root-user image — exactly what `sim/docker/Dockerfile` (the Week 1 image) already is,
   consistent with this repo's existing risk posture, not a new regression.
4. **Cut `ccache` persistence across CI runs** (GH Actions `actions/cache` wiring for `~/.ccache`).
   `ccache` is still installed and on `PATH` (helps local iterative rebuilds); just accept a cold cache
   on every `sim-image.yml` run rather than spending time wiring cross-run cache persistence.
5. **Cut the eval-gate hook entirely for now** (see below) — it was never going to be built this
   iteration; this line exists so a future pass doesn't have to rediscover that it's still open.
6. **If camera rendering makes even the flight-only smoke unreliable/too slow in CI** (a real risk —
   the vehicle model carries a live RGB+thermal sensor pair, see "The render is unavoidable" above):
   temporarily comment out `farmguard_field.sdf`'s `fg_sensor_mount` link/joint for a **CI-only**
   copy of the world (e.g. `sim/worlds/farmguard_field_ci_smoke.sdf`, generated or hand-trimmed), so
   this job proves flight/world/build integration without paying the render cost at all, while the
   real render stays exercised only in the human's Docker sessions. Not built now — only reach for
   this if item 2 above (a confirmed-green run) shows rendering is actually the blocker, not a
   hypothetical one.

## Eval-gate hook (not built — explicitly deferred, not silently forgotten)

The task asked for a hook, not an implementation. **Cleared 2026-08-18:** the render is
live-verified — gates 0-3 green, real-render clips recorded (`NDVI_VALIDATION.md`). The hook is
therefore buildable: `build-test-sim` runs `CLIP=<clip dir> bash eval/run_spike.sh` against a real
clip (already a drop-in per `sim/spike/README.md`'s schema — a deliberate design choice at spike
time, not new work) and gates on FNR regression via `scripts/check_spike_regression.py`. Still not
implemented: it waits only on one green `build-test-sim` run (step 2 above). Left as a comment in
`ci.yml` at the `build-test-sim` job.

## Resource sanity (for whoever runs this next)

Budget a full local `Dockerfile.ci` build at **30-90+ minutes**, and expect the first attempt to fail
on something new (6 bugs surfaced at the Week-3 Docker session alone). Don't schedule it right before
a demo. Host spec is `SIM_BRINGUP.md`'s ≥6 CPU / ≥8 GB / ≥40 GB, plus several GB of image layers on
top.

## One-paragraph status for `product-lead` to paste into `docs/ROADMAP.md`

> **Weeks 5-6 CI (2026-08-05, devops-reliability-engineer):** promoted from deferred to committed per
> external review, hard-timeboxed at 2-3 days (`docs/runbooks/SIM_CI.md`). Implemented everything
> verifiable without a live Docker/Gazebo runner: `sim/docker/Dockerfile.ci` (pinned-SHA workspace
> baked into image layers, DDS/ROS2-avoidance-loop deliberately excluded from this scope),
> `.github/workflows/sim-image.yml` (GHCR publish, decoupled from per-push cadence), a non-interactive
> 2-lane scripted smoke mission (`scripts/ci_sim_smoke.{sh,py}`, reusing the existing mission generator
> unchanged) and a fully unit-verified regression gate (`scripts/check_sim_smoke.py` — 5/5 fixture
> cases pass/fail correctly). Wired into `ci.yml`'s `build-test-sim` job, **manual-dispatch-only until a
> human confirms one green run** — none of the live-Gazebo/SITL pieces have executed yet in this
> session. Honest feasibility verdict, grounded in the upstream `ardupilot_gazebo`/`ardupilot` projects'
> own CI (they build/lint-only or run plain-SITL-no-Gazebo on hosted runners — full Gazebo rendering on
> a GitHub-hosted runner has no known precedent): this **may not fit GitHub-hosted runner resources**
> (14GB disk vs. our own documented 40GB minimum); the fallback is a self-hosted runner, not implemented
> here. Cut-list is explicit if Day 3 isn't enough — see the doc.
