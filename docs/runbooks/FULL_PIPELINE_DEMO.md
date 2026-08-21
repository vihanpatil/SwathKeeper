# Full Pipeline Demo — the SwathKeeper showpiece *(runbook)*

**Canonical for the recorded flight.** Any doc that needs a flight recorded points here rather than
repeating the procedure — `NDVI_VALIDATION.md` is the ADR-007 gate record and does exactly that.

## One command: `scripts/fly_pipeline.sh`

The seven shells below are wrapped by a host-side launcher — **one tmux session (`swathkeeper`),
one window per shell**, each pane running that shell's `docker exec` one-liner *byte-identical* to
this document (verified mechanically: all nine one-liners here, including the Shell-0 apt line,
match the launcher's payload strings character for character). This doc stays the reference; the
script is the wrapper. Read it here, run it there.

```bash
scripts/fly_pipeline.sh              # up (default): preflight -> gated bringup -> attaches you
scripts/fly_pipeline.sh status       # session + live gate re-checks + the fly recipe
scripts/fly_pipeline.sh birds        # start the birds NOW, bypassing the altitude gate
scripts/fly_pipeline.sh down         # SIGINT the recorder FIRST, wait for finalize, then stop
scripts/fly_pipeline.sh test-flight  # scripted REGRESSION GATE (see below) — not the demo path
scripts/fly_pipeline.sh --dry-run up # print every docker/tmux command, run nothing
scripts/fly_pipeline.sh --gate-geometry up   # + the mount-geometry gate after the bridge
```

What it adds over copy-paste is the **ordering and the gates** — Gazebo's four `fg/sensor`
advertisements, the four `/fg/sensor` ROS 2 topics, the **mandatory** render-alive probe (which on
DEGRADED restarts Gazebo + the bridge and re-probes, twice, then refuses to fly), and UDP 2019
bound before SITL boots. Two things `up` deliberately does **not** do: **it never flies** (no `arm`,
no `mode`, no `wp load` is ever sent — SITL stays an interactive pane and the fly recipe below is
displayed in a pane beside it; the one scripted exception is `test-flight`, described next, which
demo and recording flights never use), and **birds never start before arming** (the birds pane polls
`/ap/pose/filtered` and launches `drive_birds.py --rate 2` itself once altitude > 10 m). See
ADR-013.

**`test-flight` is the pre-demo regression gate — run it the day before you record, never as the
demo.** It is the one place this launcher flies: same `up`, same gates, then it pipes the SITL pane
to a log and waits (bounded, 240 s) for *all three* readiness lines — `DDS: Initialization passed`,
`EKF3 IMU… tilt alignment complete`, `GPS 1: detected` — before sending a key. Then it types the
recipe below verbatim on the short test mission (`config/missions/test_2lane.waypoints`, ~2 sim-min;
the first live run flew it in 192 s and finished the whole gate in 253 s — budget ~5 min, not the
~10 estimated from RTF 0.2), retries once on `Arm: Accels inconsistent` after 30 s, watches ARMED →
`Reached command` → disarm, and on disarm runs the recorder-first `down`, the host-side stitch, and
writes `eval/results/testflight_gate_<UTC>.json` — timestamps, each gate's evidence line, frames
recorded, the altitude the birds fired themselves at, finalize confirmation, stitch exit, plus pane
tails on failure. The birds are *not* special-cased: their own altitude gate firing is part of what
is being tested. It aborts nonzero with a one-line cause, and its trap tears down recorder-first and
force-kills any surviving sim process even on Ctrl-C. **First live run PASSED: 2026-08-18T22:16:18Z,
253 s end to end** — `eval/results/testflight_gate_20260818T222031Z.json`.

**Since 2026-08-19 the gate also has an evidence floor**, because flying the mission is not the same
as recording one: the 2 Hz throughput measurement that night flew an identical mission, recorded
**3 frames and 1 of 720 cells — and this gate said PASS**, which is useless as the
throughput-collapse regression it exists to be. The last gate is now on the yield, read from the
clip's own `meta.json` and `heatmap/heatmap.json`: **`frames_recorded ≥ 12` and `cells_imaged ≥ 40`**,
or FAIL. Both numbers are **floors derived from n=2** — the only two test-flights that exist (the
48-frame / 291-cell baseline clears them by 4.0× / 7.3×; the 3-frame / 1-cell collapse fails both
decisively) — low enough that ordinary variance on a busy laptop cannot flake them, high enough to
catch any collapse within 4× of the measured one. They are floors, not targets, and they should rise
once more than one healthy run exists. A flight that fails *only* the floor still tears down
recorder-first, stitches, and writes the full record — `result: FAIL`, `failed_phase:
evidence-yield`, the failure naming the floor, plus the new `cells_imaged` and `evidence_floor`
fields (record schema 1.1). The floor logic is exercised offline against both committed gate records
in `tests/test_fly_pipeline.py`; **it has never run live — the next `test-flight` is its first live
exercise.** The same pass fixed the pane capture that made the 2 Hz run so hard to diagnose:
`capture-pane` renders the whole 80×24 pane grid, so a quiet pane's output sits at the *top* and a
plain `tail` returned the blank rows underneath it — which is why `pane_tails["ndvi"]` is empty in
both committed records. Tails now drop blank rows before tailing, so the ndvi node's
`fused_count` / `dropped_pair_count` heartbeats reach the record: the one signal that separates
"fusion never fused" from "the recorder dropped what fusion produced".

**`up` refuses to start on top of a bringup that is already running in the container** — a manual
session in other tabs, or a tmux session that was killed without `down`. Every gate above is a
*liveness* gate, so leftovers make all of them pass instantly against the wrong processes while the
second micro-ROS agent quietly loses the bind on UDP 2019. `status` says so explicitly when it sees
green gates with no session; `docker restart fieldguard-sim` clears the container.

> **Verification status: the launcher has flown.** `test-flight` completed a live unattended run on
> 2026-08-18 in 253 s, result PASS — gate record `eval/results/testflight_gate_20260818T222031Z.json`,
> clip `eval/results/clips/real_flight_20260818T221641Z` (48 frames, 42 with RGB, **0 stale-pose
> pairs**), stitch exit 0. Proven in that one run, with the record's own evidence lines as the
> receipt: all four bringup gates firing against a real container (Gazebo advertisements 8 s,
> ROS 2 crossover 12 s, **render-alive probe 19 s, passed on attempt 1**, UDP 2019 at 22 s); the
> DDS + EKF3 + GPS readiness wait completing at 38 s before a single key was sent; the recipe typed
> on `test_2lane`; ARMED, 12 `Reached command` lines, DISARMED; **the birds pane firing its own
> altitude gate at 15.0 m** after waiting through `-0.0 m` and `7.52 m`; and the recorder-first
> teardown reporting *"finalize confirmed; session killed; survivors force-killed"*. Every timeout
> in the script now has a measured margin: readiness 38 s of 240, arm ~0 s of 90, first waypoint
> 15 s of 300, whole flight 192 s of the 1500 s budget.
>
> Still unproven, and worth watching on the first real demo flight: the **render-alive DEGRADED
> restart path** (the probe has never yet failed, so `restart_world` has never run), the
> already-running **refusal** actually refusing (its trigger was observed — `status` showed three
> green gates against a live manual bringup with no session — but `up` has not been made to refuse),
> the `NOTHING RECORDED` and finalize-timeout branches of `down`, and the accels-inconsistent arm
> retry. Also unproven at scale: this gate flew the 2-lane mission for 192 s and recorded 48 frames;
> the demo flight is ~5 sim-minutes and the runbook budgets 35-45 min end to end, which is where the
> known recording-throughput limit bites and where a long-lived Gazebo has degraded before.
>
> Before the live run this was verified by `bash -n` and `shellcheck` clean; `--dry-run` for every
> subcommand, confirmed to leave no trace (no Docker call, no tmux server, not even a temp file); a
> throwaway tmux session exercising the real functions — `keep_output`, `window_failed`,
> `send_ctrl_c`, `gate`, the `-J` capture — against live, dying, and missing windows; and a
> mechanical byte-for-byte diff of all nine pane payloads against this document. An adversarial QA
> pass on 2026-08-18 found and fixed seven defects that way, the largest being the missing
> already-running check above; a second pass after the live run fixed two more (ADR-013 amendment 3).

The whole manual, shell-by-shell path is below and remains the source of truth.

---

One flight, end to end: an autonomous boustrophedon survey over the farm world, scripted birds
flying their committed trajectories, the dual-band NDVI camera fusing in real time, every frame
recorded with a stamp-paired pose, and — after landing — the offline stitch that turns the flight
into a georeferenced crop-health heatmap on the same cell grid the coverage ledger uses.

Every command below is a **host-side one-liner** (each runs `docker exec` into the running
`fieldguard-sim` container) — one terminal tab per shell. **The shell numbers are stable IDs, not
the start order:** start them in the order the sections appear below — 0, 1, 2, 3, 4, 6, 7, fly,
then 5 (the birds go last, after takeoff). Total wall time: **~35-45 min** — budget ~1/RTF of the
sim-time flight, and the software-rendered sim runs at RTF ≈ 0.2 on a ~5-sim-minute mission.

**Not in this flight:** the reactive-avoidance node. This runbook is the NDVI chain end to end; the
avoidance loop is its own run with its own runbook (`AVOIDANCE_DEMO.md`).

**Shell 0 — is the container up?**
```bash
docker ps --filter name=fieldguard-sim
```
If it's not listed: `bash scripts/sim_docker_run.sh` first. If the container was *recreated* (not
just re-entered), re-install the three bridge runtime deps (apt state is container-ephemeral while
`/root/ardu_ws` persists — see `NDVI_VALIDATION.md` session log):
```bash
docker exec fieldguard-sim bash -c 'apt-get update -qq && apt-get install -y -qq ros-humble-actuator-msgs ros-humble-gps-msgs ros-humble-vision-msgs'
```
These three are baked into `sim/docker/Dockerfile` as of 2026-08-18, so on an image rebuilt since
then this is a no-op — run it either way, it costs a second and a missing one crashes Shell 2.

---

## Shell 1 — Gazebo (the world)

```bash
docker exec -it fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && export GZ_SIM_RESOURCE_PATH="${GZ_SIM_RESOURCE_PATH:-}:/root/ardu_ws/install/ardupilot_gazebo/share" && gz sim -v4 -s -r --headless-rendering /workspace/fieldguard/sim/worlds/farmguard_field.sdf'
```
*What's happening:* the farm world loads headless — 18 calibrated-temperature trees, 3 bird
models, the drone with its ADR-007 dual-band camera pair (RGB Red + thermal-as-synthetic-NIR).
*Look for:* ~40 `Loaded system … Thermal` lines (the per-visual temperature authoring), all four
`fg/sensor/*` advertisements, **no** `Actor skin mesh` warnings (the pre-ADR-012 bug), no
`Failed to load a world`.

## Shell 2 — the sensor bridge (Gazebo → ROS 2)

```bash
docker exec -it fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && ros2 run ros_gz_bridge parameter_bridge --ros-args -p config_file:=/workspace/fieldguard/sim/bridge/fg_sensor_bridge.yaml'
```
*What's happening:* the locked `/fg/*` contract crosses into ROS 2.
*Look for:* **four** `Creating GZ->ROS Bridge` lines (the sensor topics only — the recorder reads
the sim clock natively via gz-transport, deliberately NOT through this bridge: Gazebo's /clock is
~350 msgs/s and bridging it starved the image pipeline, measured live). A missing-library crash
here means the Shell-0 apt step was skipped.

## One-time gate after mount/world/georef changes: geometry

```bash
docker exec -it fieldguard-sim bash /workspace/fieldguard/scripts/verify_mount_geometry.sh
```
Asserts the camera's actual view agrees with the georef transform to within 15 px (canopy of a
known tree vs its predicted pixel). The mount flew FIVE flights aimed at the horizon before this
gate existed — values-only gates cannot catch geometry.

## Pre-flight probe — is the render actually alive? (30 seconds, do NOT skip)

```bash
docker exec -it fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && PYTHONPATH=/workspace/fieldguard/src:$PYTHONPATH python3 /workspace/fieldguard/scripts/check_render_alive.py'
```
*What's happening:* one RGB frame is checked for the sky-flat render-degradation signature
(channel-balanced near-white). A long-lived Gazebo instance can silently degrade after hours of
software rendering + reconnects — topics stay alive, pixels go blank, and a whole flight records
plausible-looking nothing (it happened; the 2026-08-18 session lost a flight to it).
*Look for:* `ALIVE: green-dominant world in view`. On `DEGRADED`: restart Shell 1, re-probe.
**Rule of thumb: restart Gazebo before every recording flight rather than trusting an instance
that has been up for hours.**

## Shell 3 — the micro-ROS agent (start BEFORE SITL — the golden rule)

```bash
docker exec -it fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && ros2 run micro_ros_agent micro_ros_agent udp4 --port 2019'
```
*What's happening:* the DDS doorway ArduPilot's ROS 2 interface walks through. It must be
listening before SITL boots or the `/ap/*` topics never appear.
*Look for:* `running... port: 2019`, then a burst of `create_*` lines once SITL starts.

## Shell 4 — ArduPilot SITL + MAVProxy

```bash
docker exec -it fieldguard-sim bash -c 'cd /root/ardu_ws/src/ardupilot && export PATH="$PWD/Tools/autotest:$PATH" && sim_vehicle.py -v ArduCopter -f gazebo-iris --model JSON --enable-DDS --add-param-file=/workspace/fieldguard/config/sitl_params/dds_udp.parm'
```
*What's happening:* the real ArduPilot flight stack boots against Gazebo physics (`--enable-DDS`
and the param file are load-bearing — without them, zero `/ap/*` topics, silently).
*Look for:* `DDS: Initialization passed`, `EKF3 IMU0/IMU1 tilt alignment complete`,
`GPS 1: detected u-blox`. **Wait for all of those before flying** — arming during the post-boot
CPU spike earns `Arm: Accels inconsistent` (if you get it anyway: wait 30 s, retry).

## Shell 6 — the NDVI fusion node (start it BEFORE Shell 7)

```bash
docker exec -it fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && cd /workspace/fieldguard && PYTHONPATH=src:$PYTHONPATH python3 -m fieldguard_planning.ndvi_node'
```
*What's happening:* Red + synthetic-NIR frames pair by stamp and fuse into the authoritative
`/fg/ndvi/image` (NDVI = (NIR−Red)/(NIR+Red), per pixel, live). That topic's stamp is the georef
anchor the recorder pairs poses against, so this node must be up before Shell 7 starts.
*Look for:* `fieldguard_ndvi up`, then `fused_count=…` heartbeats once the camera renders.
`dropped_pair_count` should stay ~0.

## Shell 7 — the clip recorder (the evidence)

```bash
docker exec -it fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && cd /workspace/fieldguard && PYTHONPATH=src:$PYTHONPATH python3 -m fieldguard_planning.record_node --out /workspace/fieldguard/eval/results/clips/real_flight_$(date -u +%Y%m%dT%H%M%SZ)'
```
*What's happening:* every fused frame is written in the spike schema with a pose selected by
**gz-clock stamp pairing** — the recorder streams Gazebo's clock natively (a `gz topic`
subprocess, zero bridge load) and matches each frame's own stamp against gz-tagged poses, so
render bursts can't mislabel frames (the lesson of the first recorded flight, whose canopy landed
meters down-track and put 0/18 trees at their true spots).
*Look for:* `live intrinsics locked` (that line is ADR-007 follow-up-5 evidence) and the
**absence** of the arrival-fallback warning. Heartbeats:
`recorded N frames (M with rgb, K stale-pose flagged)` — K near zero.

## Fly it — Shell 4's MAVProxy prompt

```
wp load /workspace/fieldguard/config/missions/boustrophedon.waypoints
param set MIS_RESTART 0
param set AUTO_OPTIONS 3
wp set 1
mode guided
mode auto
arm throttle
```
*What's happening:* the generated lawnmower mission loads; the guided→auto bounce forces a fresh
AUTO entry at item 1 (re-entering AUTO after a finished mission is otherwise a no-op — learned
live); `AUTO_OPTIONS 3` lets AUTO take off armed.
*Look for:* `ARMED`, `height 15`, then `Reached command #N` marching through the lanes.

## Shell 5 — the birds (start AFTER `height 15`)

```bash
docker exec -it fieldguard-sim bash -c 'python3 /workspace/fieldguard/scripts/drive_birds.py --rate 2'
```
*What's happening:* the three bird models fly their committed JSON trajectories on **sim time**
(ADR-012) — correct at any real-time factor.
*Look for:* `sim-time mode … (RTF-proof)`, heartbeats `poses ok=N failed=0-ish`. Started after
arming on purpose: its service traffic adds jitter the EKF can't tolerate while aligning.

## After RTL + disarm

1. **Ctrl-C Shell 7 first.** Finalize converts the in-flight raw RGB dumps to schema PNGs
   (give it a minute), writes `meta.json` (`synthetic: false`), and prints the stitch command.
2. Ctrl-C the rest at leisure. Don't idle for ages first — parked frames add nothing.
3. **Stitch, on the host** (repo root, no container needed):

        python3 scripts/stitch_ndvi.py --clip eval/results/clips/<the dir Shell 7 printed>

    *Look for:* `cells imaged` in the low hundreds (the best valid clip is 291/720 — recording
    throughput, not coverage, is the limit; `docs/ROADMAP.md` "Next up") and few stale-pose skips.
    Then open `heatmap/heatmap.png`.

4. **ADR-003 re-confirmation on the real render** (still on the host). `run_spike.sh` takes no
    argument — it reads `CLIP` from the environment, so a bare invocation silently re-scores the
    *synthetic* clip and labels the numbers real:

        CLIP=eval/results/clips/<the same dir> bash eval/run_spike.sh

5. **Commit the evidence, not the bulk:** `meta.json`, `poses.jsonl`, `heatmap/*`, and a handful of
    sample frames — never the full `.npy` set. `.gitignore` already carries un-ignore rules for
    exactly those paths, so a plain `git add` works. (The 2026-08-05 clobber lesson: evidence that
    isn't committed doesn't exist.)

## Performance rule: keep the host quiet during the flight

The sim is CPU-starved by construction (software rendering in Docker). Measured 2026-08-18: with
heavy host workloads running (builds, test suites, parallel agents), the camera pipeline drops
frames per-band, the fusion pairing starves, and the recorder can lose >90% of the flight. Close
heavy apps, pause CI-ish work, and don't run local builds while recording. Symptoms it's
happening anyway: Shell 6's `fused_count` crawling, Shell 5's failed-call counter climbing past
~20%, Shell 7 heartbeats minutes apart.

## The proof standard (what makes this demo honest)

A pretty heatmap is not the bar. The bar: **the 18 trees appear at their 18 known positions**
(`config/static_obstacles.json`) as high-NDVI cells against the negative-NDVI soil, and the birds'
committed patrol zones show as low-NDVI track marks. The first recorded flight LOOKED right and
failed exactly this check — which is the whole SwathKeeper story: a survey artifact is only
trusted when it can be cross-examined against ground truth, whether that's coverage debt in the
ledger or trees in the heatmap.
