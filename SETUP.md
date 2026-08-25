# Setup — run SwathKeeper on your machine

The front door: clone, build a container, and finish at **one command that flies a mission and
proves itself with evidence**. Everything heavy — ROS 2 Humble, Gazebo Harmonic, ArduPilot SITL —
lives inside an Ubuntu 22.04 Docker image (ADR-004), so your host only has to run Docker, `bash`,
`tmux` and `python3`. What the system *is* and why it exists: [`README.md`](README.md). The deep
build steps stay canonical in [`docs/runbooks/SIM_BRINGUP.md`](docs/runbooks/SIM_BRINGUP.md) — this
page points into that runbook rather than repeating it.

**Not ready for a 30-90 minute image build?** §0 is a no-Docker tier: the same gates CI runs, on
nothing but a `python3` — the test suite, this repo's two acknowledged safety findings, the
tree-position gate on a committed real flight, and an NDVI heatmap you generate yourself. Sections
1-7 are the full sim.

> **Verified on exactly one host: macOS on Apple Silicon with Docker Desktop.** Every other host
> below is *expected to work, not verified*. The container is identical everywhere, so the risk
> sits in Docker's host integration, not in the stack — but nobody has run it, and this repo does
> not claim what it hasn't measured.

## 0. Try it in five minutes — no Docker

Host-side Python, nothing else. Steps (a), (c) and the first three commands of (e) are **literally
what CI runs on every push** — the `planning-and-eval` job in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml), same commands, same committed fixtures. (b)
is those same two test roots in one `pytest` invocation; the stitch, (d) and (f) are host tools CI
doesn't run. **About a minute of compute** in total, plus one `pip install`, measured on the verified
host (macOS, Apple Silicon, Python 3.9.6, 2026-08-25) — every output below is quoted from that run,
abridged where marked.

**(a) The test suite — no install.**

```bash
python3 -m unittest discover -s tests -p 'test_*.py'          # host-side launcher + CI-config tests
python3 -m unittest discover -s tests/fieldguard_planning     # planning, safety, gate logic
```

```
Ran 57 tests in 6.760s
OK
Ran 822 tests in 13.040s
OK (skipped=2)
```

Two roots because `discover -s tests/fieldguard_planning` never walks `tests/test_*.py` — CI runs
both for exactly that reason. **The honest caveat, measured on a clean Python 3.12 venv with nothing
installed:** only the *first* command is truly install-free there. Ten of the second's modules import
numpy and fail to load with `ModuleNotFoundError: No module named 'numpy'` (the command exits 1); the
other 614 tests still run green, and step (b) clears the ten — on Python 3.11+, see its floor note.

**(b) Install the pins, run everything at once.** **Needs Python 3.11+** (read the note below first).

```bash
python3 -m pip install -r requirements-eval.txt   # numpy 2.5.1, scipy 1.18.0, markdown 3.9
python3 -m pytest tests -q
```

```
877 passed, 2 skipped in 20.76s
```

**The floor, measured:** `numpy==2.5.1` publishes nothing for Python < 3.11, so on this host's stock
`python3` (3.9.6) the install stops at `ERROR: No matching distribution found`. Use a 3.11+
interpreter — e.g. `python3.12 -m venv .venv && source .venv/bin/activate`, then the two commands
above. The `877 passed` line was produced on the 3.9 host against an older numpy/scipy that were
already present: the *suite* is green on 3.9, the *pins* are not installable there.
`requirements-eval.txt` is the one home for Python pins (the simulation stack's own pins live in
`CLAUDE.md`); CI installs the same file, at Python 3.12, *before* it runs any test. Suite totals have
one home too — [`tests/README.md`](tests/README.md); this page quotes them.

**(c) The honesty demo — the repo gating its own failures.**

```bash
python3 scripts/check_live_flight_log.py eval/results/live_flight_log_*.json
```

```
[check_live_flight_log] ACKNOWLEDGED SAFETY FINDING: eval/results/live_flight_log_20260823T004031Z.json
    - covered=720 debt=0 path_points=984 | CPA 0.0518 m to demo_bird_0 (bar: min_bird_clearance_m 3.00 m) -- FLEW CLOSER THAN THE POLICY WILL COMMAND.
    - acknowledged by live_flight_log_20260823T004031Z.SAFETY_FINDING.md -- recorded history, kept as evidence, NOT a passing flight
[check_live_flight_log] PASS WITH 2 ACKNOWLEDGED SAFETY FINDING(S): 0 of 2 log(s) clean.
```

*(abridged: the second finding — the 2026-08-18 flight, CPA 0.0597 m, 513 covered / 207 debt — prints
the same three lines above this tail.)* Both flights passed every gate that existed on their day, and
a **later** gate measured what none of them had: the distance actually flown past the bird — 0.0518 m
and 0.0597 m against a 3.00 m bar. Both logs are kept and marked, neither counts as a pass, and the
fix that matters (escape geometry) is deliberately still open. The exit code is 0 only because each
finding has a reviewed `.SAFETY_FINDING.md` marker beside it. CI runs this same command and
**hard-fails if the glob matches zero files** — a gate with no denominator does not score green here.

**(d) The real-flight evidence — canopy signal where the trees actually are.**

```bash
python3 scripts/check_tree_positions.py eval/results/clips/real_flight_20260823T073644Z
```

```
  1256 frames | 720/720 cells imaged | soil modal NDVI -0.437688 on 375 cells
  IMAGED 18/18   CANOPY-GRADE 9/18   MEDIAN LIFT +0.5402
  DISPLACEMENT: all 12 positive cells within 2.0 m of a tree centre.
[check_tree_positions] PASS: canopy signal is where the trees are.
```

*(abridged: it also prints a row per tree — cell, sample count, NDVI, lift, verdict.)* That clip is
committed (its `meta.json`, `poses.jsonl` and stitched heatmap — not the raw frames), so this reads a
**real Gazebo flight** without flying one. The gate fails on any positive cell more than 2.0 m from a
tree centre: a heatmap that merely *looks* green cannot pass it.

**(e) Make your own artifact — clip → scores → regression gate → heatmap.**

```bash
python3 sim/spike/gen_spike_clip.py --seed 42 --out sim/spike/out/spike_seed42
CLIP=sim/spike/out/spike_seed42 bash eval/run_spike.sh
python3 scripts/check_spike_regression.py eval/results/spike_scores.json
python3 scripts/stitch_ndvi.py --clip sim/spike/out/spike_seed42
```

```
[gen_spike_clip] SYNTHETIC STAND-IN clip (not a Gazebo render) -- seed=42 duration=30.0s fps=10
  -> ADOPT (a) NDVI-direct. It clears the per-bird FNR bar and is within 0.1 FNR of RGB
  CAVEAT: SYNTHETIC clip -- validates the HARNESS and gives a first signal
[check_spike_regression] a_ndvi_direct.precision = 0.4454 (bar: >= 0.4)
[check_spike_regression] PASS: no regression on the fixed-seed spike baseline.
stitched 300 frames (SYNTHETIC, seed=42, 227 painting @ 10.0 Hz) -> 168/720 cells imaged
```

*(abridged: four commands, one line each of many — the scoring step prints a full per-bird table.)*
Open `sim/spike/out/spike_seed42/heatmap/heatmap.png`. It is **synthetic and says so at every step** —
a 30 s stand-in clip that exists to prove the harness, which is why it paints 168 of 720 cells and not
the README's 720. Seed 42 makes it byte-reproducible: that is the whole point of the regression gate
above, which fails if the detector's numbers move. 17.2 s for all four commands.

**(f) Planning a real flight starts here.**

```bash
python3 scripts/predict_bird_visibility.py --fps 5.0
```

```
  VERDICT: PASS -- every bird clears the 5-frame floor (median frames in view over the phase sweep).
```

*(abridged: the full report is a per-bird table — footprint at each bird's altitude, frames in view
over a 55-phase sweep, and whether a miss is TIMING or STRUCTURAL.)* ~1 s, and it exists because a
whole Docker session was once spent on a mission that returned **0 bird-visible frames out of 454** —
geometry nobody had checked. It answers "is this flight worth the session?" before the session is
booked. Everything after this section is that session.

## 1. Host prerequisites

Every host needs **Docker sized to ≥6 CPUs, ≥8 GB RAM, ≥40 GB free disk** (SIM_BRINGUP §1 — a ROS 2
desktop install, Gazebo and ArduPilot build artifacts reach 15-20 GB before any world assets), plus
`git`, `tmux` and `python3` **on the host** (CI pins 3.12; the pins below need **3.11+** — §0(b)).
`tmux` is not optional: the launcher is a host-side tmux session, one window per sim process. Then,
once cloned:

```bash
python3 -m pip install -r requirements-eval.txt   # numpy/scipy for the host-side stitch; Python 3.11+
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

**If your image or container predates 2026-08-24, rebuild and recreate.** Two changes landed that a
re-attach cannot pick up:

- **`python3-scipy` in the image** (2026-08-24). `scipy.ndimage` *is* the morphology inside the
  adopted NDVI blob detector, so an older image cannot run `avoidance_node --detect` at all.
  `fly_pipeline.sh up` refuses on it by design — `scipy is missing inside 'fieldguard-sim' — this
  image predates the python3-scipy line in sim/docker/Dockerfile` — and prints the exact commands
  below. Don't `pip install` around it inside the running container: that hides the drift and burns
  the next session too.
- **`--shm-size=1g` on the container** (2026-08-22). Fast DDS carries every `/fg/*` image over shared
  memory, and the enlarged segments that took recording from 0.41 Hz to a flat 5.0 Hz don't fit
  Docker's default 64 MB. It is **creation-time only** — there is no `docker update` for it, and
  `sim_docker_run.sh` re-*attaches* an existing container instead of recreating it. Nothing gates
  this one at bringup; where it shows up is the clip's own `meta.json` `dds` block, which records
  `shm_capacity_bytes` and every participant's segment size.

```bash
docker rm fieldguard-sim          # only if that container already exists
bash scripts/sim_docker_build.sh
bash scripts/sim_docker_run.sh
```

The §3 workspace build is **not** lost by that `docker rm`: it lives on the named volume
`fieldguard_ardu_ws`, not in the container.

## 3. One-time: build the workspace inside the container

Follow [SIM_BRINGUP §3](docs/runbooks/SIM_BRINGUP.md) — `vcs import`, `rosdep install`, then
`colcon build --packages-up-to ardupilot_gz_bringup` — and then **run §6b once by hand**. Both
matter before step 4. The workspace build is the long pole: budget **30-90+ minutes** for the image
plus this build (`docs/archive/SIM_CI.md` sizes the same work) and expect the first attempt to fail
on something and need one retry. And the first `--enable-DDS` SITL build is a multi-minute waf
recompile that the launcher's 240-second readiness gate will not sit through. Do both once, by
hand, and every run after is one command.

None of this is needed for §0 — the tests, the evidence gates and the offline stitch are pure
host-side Python (see [`tests/README.md`](tests/README.md)).

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
| `up` refuses: `scipy is missing inside 'fieldguard-sim'` — or a clip's `meta.json` `dds` block shows a 64 MB shm | Image/container predates 2026-08-24 (`python3-scipy`) or 2026-08-22 (`--shm-size=1g`). Rebuild **and** `docker rm` the container — §2. |
| Bridge dies on a missing library | Re-run `up`; its preflight installs the three container-ephemeral ROS deps. |
| Gazebo prints `Failed to load a world` | `GZ_SIM_RESOURCE_PATH` — SIM_BRINGUP §5. |
| `rosdep`/plugin build fails on arm64 | Rebuild with `scripts/sim_docker_build.sh --amd64`. |
| No `/ap/*` topics ever appear | The micro-ROS agent must be listening *before* SITL starts — SIM_BRINGUP §6b. |

Anything else: SIM_BRINGUP's gotchas list first, then the runbooks in
[`docs/README.md`](docs/README.md).
