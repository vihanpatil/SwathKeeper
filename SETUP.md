# Setup — run SwathKeeper on your machine

The front door: clone, build a container, and finish at **one command that flies a mission and
proves itself with evidence**. Everything heavy — ROS 2 Humble, Gazebo Harmonic, ArduPilot SITL —
lives inside an Ubuntu 22.04 Docker image (ADR-004), so your host only has to run Docker, `bash`,
`tmux` and `python3`. What the system *is* and why it exists: [`README.md`](README.md). The deep
build steps stay canonical in [`docs/runbooks/SIM_BRINGUP.md`](docs/runbooks/SIM_BRINGUP.md) — this
page points into that runbook rather than repeating it.

> **Verified on exactly one host: macOS on Apple Silicon with Docker Desktop.** Every other host
> below is *expected to work, not verified*. The container is identical everywhere, so the risk
> sits in Docker's host integration, not in the stack — but nobody has run it, and this repo does
> not claim what it hasn't measured.

## 1. Host prerequisites

Every host needs **Docker sized to ≥6 CPUs, ≥8 GB RAM, ≥40 GB free disk** (SIM_BRINGUP §1 — a ROS 2
desktop install, Gazebo and ArduPilot build artifacts reach 15-20 GB before any world assets), plus
`git`, `tmux` and `python3` **on the host** (the verified host runs 3.9; CI pins 3.12). `tmux` is not
optional: the launcher is a host-side tmux session, one window per sim process. Then, once cloned:

```bash
python3 -m pip install -r requirements-eval.txt   # numpy/scipy for the host-side stitch
```

| Host | Docker | tmux | Notes |
|---|---|---|---|
| **macOS, Apple Silicon** — verified | Docker Desktop; set the sizing in Settings → Resources | `brew install tmux` | Image builds arm64 natively; see the fallback below. |
| macOS, Intel | Docker Desktop, same sizing | `brew install tmux` | Native amd64. No GPU passthrough here either. |
| Linux (x86_64 or arm64) | Docker Engine — no resource sliders, the host's own CPU/RAM apply | `sudo apt install tmux` | Stay on the containerized path; the scripts assume it. |
| Windows 11 + WSL2 | Docker Desktop on the WSL2 backend, integration enabled for your distro | `sudo apt install tmux` inside the distro | Clone and run **inside** the WSL2 filesystem (`~/…`, never `/mnt/c/…`), from a WSL bash shell — not PowerShell. |

**arm64 vs amd64:** Apple Silicon and arm64 Linux build the image natively, which is the fast path.
That combination (Humble + Harmonic + `ardupilot_gazebo`'s C++ plugin) is far more commonly tested
on amd64, so if `rosdep install` or the plugin build fails on missing arm64 packages, rebuild with
`scripts/sim_docker_build.sh --amd64` — emulated and slower, but a known-working escape hatch.
Full context: SIM_BRINGUP's "Known macOS gotchas" #2.

## 2. Clone, build the image, start the container

```bash
git clone https://github.com/vihanpatil/SwathKeeper.git
cd SwathKeeper
scripts/sim_docker_build.sh      # add --amd64 if arm64 package resolution breaks
scripts/sim_docker_run.sh        # creates (or re-attaches to) the 'fieldguard-sim' container
```

Yes, `fieldguard`: the project was renamed from its working title, and the code identifiers,
container name and `/fg/*` topics deliberately kept the old one because the topic contract is
live-verified against it (ADR-011). Don't rename them.

## 3. One-time: build the workspace inside the container

Follow [SIM_BRINGUP §3](docs/runbooks/SIM_BRINGUP.md) — `vcs import`, `rosdep install`, then
`colcon build --packages-up-to ardupilot_gz_bringup` — and then **run §6b once by hand**. Both
matter before step 4. The workspace build is the long pole: budget **30-90+ minutes** for the image
plus this build (`docs/runbooks/SIM_CI.md` sizes the same work) and expect the first attempt to fail
on something and need one retry. And the first `--enable-DDS` SITL build is a multi-minute waf
recompile that the launcher's 240-second readiness gate will not sit through. Do both once, by
hand, and every run after is one command.

None of this is needed to run the tests or stitch an existing clip — those are pure host-side
Python: `python3 -m unittest discover -s tests/fieldguard_planning` needs no install at all
(see [`tests/README.md`](tests/README.md)).

## 4. The payoff: prove the whole pipeline works

Leave the container shell (the launcher runs on the **host**) and run the regression gate:

```bash
./scripts/fly_pipeline.sh test-flight
```

It brings up the seven sim processes in gated order — world, sensor bridge, micro-ROS agent, SITL,
NDVI fusion, recorder, altitude-gated birds — refuses to fly past a **mandatory render-alive probe**,
waits for the DDS, EKF and GPS readiness lines before sending a single key, types the short two-lane
mission at the MAVProxy prompt, watches ARMED → `Reached command` → disarm, tears down
recorder-first, stitches the clip on the host, and finally judges what the flight actually
*recorded*.

**About 5 minutes** (the two runs on record took 253 s and 233 s), plus a couple of minutes the
first time while preflight installs the bridge's runtime deps. PASS ends like this:

```
[fly_pipeline] gate PASSED: render alive
[fly_pipeline] TEST-FLIGHT PASSED — gate record: .../eval/results/testflight_gate_<UTC>.json
```

Any failure exits nonzero with one line naming the phase it died in, and still writes the record.
Two artifacts land in the repo:

- `eval/results/testflight_gate_<UTC>.json` — result, one evidence line per gate, `frames_recorded`,
  `cells_imaged`, the evidence floor it was judged against, the altitude the birds fired themselves
  at, stitch exit, and the pane tails.
- `eval/results/clips/real_flight_<UTC>/` — the clip, with `heatmap/heatmap.png` and `heatmap.json`:
  the georeferenced NDVI map, on the same cell grid the coverage ledger uses.

A PASS means the whole stack genuinely works on your machine. It is a *floor*, not a good flight:
the bars are derived from the only two runs on record, and sit low enough that a busy laptop can't
flake them.

## 5. Fly it yourself

```bash
./scripts/fly_pipeline.sh up       # same gated bringup, then attaches you. It never flies.
```

The `sitl` window carries MAVProxy with the **fly recipe displayed in the pane beside it**: wait for
`DDS: Initialization passed`, `EKF3 … tilt alignment complete` and `GPS 1: detected`, type the
recipe, then watch `Reached command` march through the lanes. The birds launch themselves once you
climb past 10 m. After RTL and disarm, `./scripts/fly_pipeline.sh down` SIGINTs the recorder first,
waits for finalize, and prints the stitch command. Also: `status` (session + live gate re-checks),
`birds` (manual override), `--dry-run` (print every command, run none). The shell-by-shell reference
this launcher wraps is [`docs/runbooks/FULL_PIPELINE_DEMO.md`](docs/runbooks/FULL_PIPELINE_DEMO.md).

## 6. Two things that will bite you

- **No GPU passthrough into Docker Desktop on macOS** (SIM_BRINGUP gotcha #1). Gazebo
  software-renders (llvmpipe); measured real-time factor runs ≈ 0.17-0.6, so a 5-sim-minute survey
  costs roughly 8-30 wall minutes. Physics and correctness are unaffected; only your clock is.
- **Keep the host quiet while recording.** Proven twice: with builds, test suites or parallel agents
  running, the camera bands drop frames, fusion pairing starves, and the recorder can lose >90% of
  the flight. Symptoms are a crawling `fused_count`, birds failing past ~20%, and recorder
  heartbeats minutes apart.

## 7. When it breaks

| Symptom | Fix |
|---|---|
| `docker info` errors | Docker isn't running — start it, then retry. |
| `up` refuses: a bringup is already live | A previous session was killed without `down`: `docker restart fieldguard-sim`. |
| Bridge dies on a missing library | Re-run `up`; its preflight installs the three container-ephemeral ROS deps. |
| Gazebo prints `Failed to load a world` | `GZ_SIM_RESOURCE_PATH` — SIM_BRINGUP §5. |
| `rosdep`/plugin build fails on arm64 | Rebuild with `scripts/sim_docker_build.sh --amd64`. |
| No `/ap/*` topics ever appear | The micro-ROS agent must be listening *before* SITL starts — SIM_BRINGUP §6b. |

Anything else: SIM_BRINGUP's gotchas list first, then the runbooks in
[`docs/README.md`](docs/README.md).
