# Avoidance with the REAL detector — one take *(runbook; the Week-6 deliverable)*

The flight this project has been building toward: the drone dodges a bird **it detected**, not a
bird we injected. It is the `FULL_PIPELINE_DEMO.md` bringup **plus one shell** — the avoidance node
with `--detect`, which puts the ADOPTED ADR-003 am. 7 NDVI blob detector on the `detection_source`
seam under ADR-009's contract (`stamp_s` staleness gate, range from the **apparent-size ray**, never
ground-plane projection).

**One take, two artifacts** — both are the point, neither substitutes for the other:

| artifact | claim it supports | its gate |
|---|---|---|
| `eval/results/live_flight_log_<UTC>.json` (schema 2) | detect → avoid, at a measured separation | `scripts/check_live_flight_log.py --truth …` |
| `eval/results/clips/real_flight_<UTC>/` + its heatmap | the NDVI map is where it says it is | `scripts/check_tree_positions.py` |

> **Status: this procedure has NEVER BEEN FLOWN.** Every command below is verified offline (host
> test suite, `fly_pipeline.sh --dry-run`, and an offline replay of the seam over the adopted clip).
> Verified offline is not flown; the first execution of this runbook is the flight it describes.
> Numbers marked *(offline)* are predictions to compare the flight against, not results.

### Where this sits among the runbooks
| runbook | what it flies |
|---|---|
| [`FULL_PIPELINE_DEMO.md`](FULL_PIPELINE_DEMO.md) | the NDVI chain end to end, no avoidance node. **Canonical for bringup**: the seven pane one-liners live there and only there, byte-diffed against `scripts/fly_pipeline.sh` by `tests/test_fly_pipeline.py`. |
| [`AVOIDANCE_DEMO.md`](AVOIDANCE_DEMO.md) | the scripted `--demo` bird — the deterministic regression arm and the A/B against perception (ADR-013 am. 2). Its **bringup half is superseded** by this file; its `--demo` procedure is not. |
| **this file** | both at once: a real detection off the real render driving the real avoidance loop. |

This runbook deliberately does **not** re-spell the seven pane one-liners. One source of truth per
command: they live in `FULL_PIPELINE_DEMO.md`, `fly_pipeline.sh` runs them, and a second copy here
would be a second thing to drift.

---

## 0. Preconditions — all of these are HOST-side and cost no Docker session

### 0a. The image must carry scipy (multi-hour — do this days before, not at session time)
`sim/docker/Dockerfile` installs `python3-scipy`, because `scipy.ndimage` **is** the morphology the
adopted detector was scored with; a numpy reimplementation would be a different detector wearing
ADR-003 am. 7's verdict. Check first — if this prints a version, skip the rebuild:

```bash
docker exec fieldguard-sim python3 -c "import scipy; print(scipy.__version__)"
```

If it fails (or the container predates `--shm-size=1g`, ADR-013 am. 9):

```bash
bash scripts/sim_docker_build.sh      # rebuild the fieldguard-sim image (multi-hour)
bash scripts/sim_docker_run.sh        # recreate the container from the new image (adds --shm-size=1g)
```

If your session **pulls** the GHCR image instead of building locally, that image needs rebuilding
and pushing too (`sim-image.yml`'s push trigger is commented out — it needs a manual
`workflow_dispatch`). `fly_pipeline.sh up` refuses to open a single pane until `import scipy.ndimage`
works inside the container, so a stale image costs ~200 ms instead of 90 s into a booked take.

### 0b. Predictor precheck — will a bird be in frame at all? **This is the abort gate**
The 2026-08-21 demo take flew the whole boustrophedon with all three birds airborne and produced
**0 bird-visible frames out of 454**. Two host gates now stand between that and a booked session;
both are ~1 s and neither needs Docker (`config/birds/farm_world_birds.json` names them, and they
must be re-run after ANY edit to that file, `config/missions/boustrophedon.waypoints`,
`config/field_polygon.json` or `config/ndvi_camera.json`):

```bash
# gate 1 — CAMERA: will the birds be IN FRAME? Run it at the cadence AND SPEED you actually expect.
python3 scripts/predict_bird_visibility.py --fps 5.0 --speed 9.4

# gate 2 — AVOIDANCE: does a bird still sit inside the policy's threat cylinder?
python3 -m pytest tests/fieldguard_planning/test_bird_geometry_contract.py -q
```

Measured 2026-08-25 on the committed config: gate 1 **FAIL, exit 1** at `--speed 9.4` — medians
**2 / 2 / 3** frames in view (bird_0 / bird_1 / bird_2) over the 55-offset driver-start phase sweep,
all three below the 5-frame floor; gate 2 **17 passed**. **That FAIL is correct and it is the
current state of the world:** the geometry only clears the floor at 3 m/s (medians 8 / 6 / 11, the
number ADR-015 published and every doc quoted), and the vehicle does not fly 3 m/s.

**`--fps` and `--speed` are the honest inputs, and together they are the whole gate.**
- `--speed` is **REQUIRED and has no default** (ADR-016). It used to default to 3.0 m/s from a doc
  containing no speed figure, and that default is what booked the 2026-08-25 take: PASS on paper,
  2 bird-visible frames in the air. Measure it — the 2026-08-25 take's own poses give a median
  **8.5 m/s** (peak 10.9) through the encounter window.
  **The response is NOT monotone in speed** — measured at 0.5 m/s steps, per-bird medians rise with
  speed in several places and the failing-bird count drops 2 → 1 between 3.5 and 4.0 m/s (lane-
  arrival phase aliasing: the sweep phases the BIRD, not the vehicle's arrival at a lane). The
  PASS/FAIL verdict does not invert between 1.0 and 6.0 m/s on this config, so "run it at the speed
  you will fly" still holds — but **do not** reason "fast is the conservative end". If the speed is
  uncertain, run the range.
- `--fps` is frame *opportunity*: the NDVI rate the avoidance node will actually consume. Since
  ADR-013 am. 9 (Fast DDS SHM segment fix) that is the full **5.0 Hz** sensor tick, measured flat on
  F9 and on the flagship take. If your last clip's cadence was lower, pass **that** number.

**ABORT RULE — no argument, no exceptions:** if `predict_bird_visibility.py` exits nonzero (any bird
below the 5-frame median floor), **do not book the session.** At the old 0.407 Hz throughput the same
committed geometry returns medians **1 / 0 / 1 and exit 1** *(re-measured 2026-08-24 at `--fps 0.41`)*
— that is the state that produced four unscoreable clips in a row. Fix throughput or geometry first,
re-run the predictor, then book. Reading `limited_by` tells you which: `STRUCTURAL` means no cadence
can ever help (move the patrol line, ADR-015), `TIMING` means throughput **or speed** — all three
birds read TIMING at 9.4 m/s, and slowing the survey is as legitimate a fix as moving a bird.
**Exit 2 is a refusal, not a pass:** no `--speed`, or an unannotated clip under `--backtest`. It is
deliberately neither 0 nor 1 so a caller can never read "I had no speed" as "the birds are visible".
**As of 2026-08-25 this gate FAILs on the committed geometry at any speed the vehicle actually
flies**, so booking the next detection take needs a geometry or speed change first — which is the
re-fly's business (ADR-016 sequencing: the offline point-mass replay comes before it).

### 0c. Detector transfer check — does the ADOPTED detector behave the same in the image?
jammy ships scipy **1.8.0**, `requirements-eval.txt` pins **1.18.0**, dev hosts run **1.13.1**. The
ADOPT verdict was earned on one of them. Re-score the adopted clip *inside the container* and demand
bit-identical boxes (the repo is bind-mounted, so the container writes where the host reads — no
`docker cp`):

```bash
docker exec fieldguard-sim bash -c 'cd /workspace/fieldguard && PYTHONPATH=src:$PYTHONPATH python3 eval/baseline_ndvi.py --clip eval/results/clips/real_flight_20260823T073644Z --out eval/results/transfer_check_incontainer.json'

python3 - <<'EOF'
import json
a = json.load(open("eval/results/adr003_20260823/detections_ndvi.json"))["frames"]
b = json.load(open("eval/results/transfer_check_incontainer.json"))["frames"]
print("IDENTICAL — the ADOPTED detector transferred" if a == b else "DIFFERENT — DO NOT FLY")
EOF
```

Expect **24 boxes over 1256 frames** at `thresh=-0.61 / min_area=6 / max_area=5000` (the committed
artifact's own numbers, verified on disk). **Any difference is a scipy-version behaviour change: the
ADOPTED verdict did not transfer, and the flight does not fly until that is understood.**

### 0d. Geometry gate — only after a mount, vehicle-SDF or georef change
```bash
docker exec -it fieldguard-sim bash /workspace/fieldguard/scripts/verify_mount_geometry.sh
```
Asserts the camera's actual view agrees with the georef transform (last measured **2.2 px** against a
15 px bar). The mount flew five flights aimed at the horizon while every values-only gate stayed
green (ADR-007 am. 5). `scripts/fly_pipeline.sh --gate-geometry up` runs it inline; standalone is
better, because it launches a second rendering Gazebo on the machine you are about to keep quiet.

### 0e. Keep the host quiet
Software rendering in Docker is CPU-starved by construction. Builds, test suites and parallel agents
have cost this project >90 % of a flight's frames, twice. Close them before `up`, not after.

---

## 1. Bringup — `fly_pipeline.sh up` (7 panes), then the 8th shell

```bash
scripts/fly_pipeline.sh up          # gazebo, bridge, agent, sitl(+recipe pane), ndvi, record, birds
```

That is the whole bringup: the golden order (micro-ROS agent **before** SITL), the four `/fg/sensor`
advertisement + ROS 2 crossover gates, the **mandatory** render-alive probe, UDP 2019 bound before
SITL boots, the scipy tripwire from 0a, and the refusal to start on top of a bringup that is already
live in the container. `up` **never flies**. Details and per-pane expectations:
[`FULL_PIPELINE_DEMO.md`](FULL_PIPELINE_DEMO.md).

**The birds are real trajectories, not a stand-in.** The `birds` pane polls `/ap/pose/filtered` and
launches `python3 /workspace/fieldguard/scripts/drive_birds.py --rate 2` by itself once altitude
> 10 m — never before (set_pose traffic is jitter the EKF cannot tolerate while aligning). It
replays the committed `config/birds/farm_world_birds.json` waypoints on **sim time**, and it writes
this flight's **bird ground truth**: `eval/results/bird_drive_<UTC>_applied.jsonl`, one record per
`set_pose` call that actually landed. That file is the input to the safety gate in §5 — without it
the flight cannot be scored. Manual override, only when airborne: `scripts/fly_pipeline.sh birds`.

**Shell 8 — the avoidance node with the real detector.** Deliberately a plain `docker exec` and
**not** a `fly_pipeline.sh` pane: the node writes its flight log in a `finally` after `rclpy.spin`,
and teardown's `pkill` would destroy the evidence the flight exists to produce. ADR-013's own rule is
that the launcher wraps one-liners that have already flown — this one has not.

```bash
docker exec -it fieldguard-sim bash -c 'source /root/ardu_ws/install/setup.bash && export FASTRTPS_DEFAULT_PROFILES_FILE=/workspace/fieldguard/config/dds/fg_fastdds.xml && cd /workspace/fieldguard && PYTHONPATH=src:$PYTHONPATH python3 -m fieldguard_planning.avoidance_node --detect'
```

> `PYTHONPATH=src:$PYTHONPATH`, **not** `PYTHONPATH=src` — a bare assignment replaces ROS 2's own
> path and you get `ModuleNotFoundError: No module named 'rclpy'`. The DDS profile matters here too:
> this node subscribes to the 1.2 MB fused frames, and the SHM segment fix (ADR-013 am. 9) is what
> took delivery to 100 %.

**Four startup lines are the contract. The node refuses to fly without the first one:**

| line | why it matters |
|---|---|
| `detection source: ndvi_blob` | the real detector is armed (`demo_virtual` or `none` means it is not) |
| `gz clock live at sim t=… — detector armed` | **one clock**, absolute Gazebo sim seconds. No `/clock` reading in 10 s → **exit 3** and no flight. Without it there is no staleness gate, no stamp-paired pose, and no sim-time axis to score against ground truth — all three failures are silent in the air. |
| `detector armed with LIVE intrinsics: 640x480 fx=… (from /fg/ndvi/camera_info)` | intrinsics come from the message, never from `config/ndvi_camera.json` — the config is what we asked for, the message is what we got. No detection happens before this line. |
| `WARNING: --ndvi-thresh -0.61 is the PROVISIONAL ADR-003 am. 7 default` | **expected, on stderr, every flight.** −0.61 is the gate-2 bird/soil pixel midpoint. ADOPT means the detector *works* (n=20 bird-frames, 7 FP / 3 FN, 8 of 20 labels ambiguous, per-bird-track FNR 0.000) — it is **not** a characterisation of where the threshold belongs. Lifting PROVISIONAL needs the false-positive study, not another passing run. Fly the default; the value and its provenance are recorded in the flight log (`run.detector.thresh_provisional: true`). |

Other exits: `--detect` on an image without scipy → **exit 2** with the rebuild command (there is
deliberately no numpy fallback); `--detect --demo` together → **exit 2** (a flight has ONE detection
source, and a log mixing a virtual bird with real detections could be scored against neither kind of
truth). Overrides exist (`--ndvi-thresh`, `--min-area`, `--max-area`) and passing any threshold
explicitly clears the PROVISIONAL flag in the log; the policy's safety bars are **not** reachable
from this command line — they have one home in `PolicyParams`, which is also where the gate reads
them, so a flag here could let the gate and the control law disagree silently.

## 2. Fly it — human-flown, at the MAVProxy prompt (ADR-013)

**The rule:** `up` never arms, never changes mode, never loads a mission. The one scripted flight
mode in this project is `fly_pipeline.sh test-flight`, and it is a **pre-demo regression gate, not a
flight path** (ADR-013 am. 2). Demo and recording flights — this one included — are flown by a human
at the prompt. Delegating a specific take is the user's call to make explicitly, and it gets its own
dated note in `docs/DECISIONS.md` (am. 10, am. 11); it is not this runbook's default.

In the `sitl` window, **wait for all three** before touching anything:
`DDS: Initialization passed`, `EKF3 IMU0/IMU1 tilt alignment complete`, `GPS 1: detected u-blox`.
Arming during the post-boot CPU spike earns `Arm: Accels inconsistent` — wait 30 s, retry.

Then, at the prompt (the recipe pane beside SITL prints these verbatim):

```
wp load /workspace/fieldguard/config/missions/boustrophedon.waypoints
param set MIS_RESTART 0
param set AUTO_OPTIONS 3
wp set 1
mode guided
mode auto
arm throttle
```

## 3. What you should see — and what invalidates the take mid-flight

- **Shell 8**: a `[status t=… sim=…]` heartbeat every ~2 s carrying a *sim* clock value, then on an
  encounter `set_mode GUIDED` → `cmd_gps_pose <- ENU(…)` → `set_mode AUTO`.
- **`sim=NO CLOCK` in the heartbeat**: the gz clock stream died mid-flight. Detections then age out
  and the loop PROCEEDs — never a sign flip — but the flight's sim-time axis has holes and its
  GT-CPA coverage will show them.
- **`CLOCK DOMAIN VIOLATION`**: **stop and read it.** Detection stamps and `now_s` are not on the
  same clock; the flight-log gate fails any log with a nonzero violation count, correctly.
- **Gazebo**: the drone leaves the lane, sidesteps, resumes the lawnmower pattern.
- **`record` pane**: `recorded N frames …` climbing at ~5 Hz. **`birds` pane**: `poses ok=N
  failed=…` — `--rate 2` achieves ~1.3 Hz on this stack (the gz round-trips overrun the sleep
  floor), which is expected and is not a fault.
- **What to expect from the detector *(offline, over the adopted clip)*:** an in-cylinder threat on
  **8 of 1256 frames** (~1.2 % of airborne frames) in roughly 3 clusters — so ~2-3 encounters, not a
  dodge storm. Three of those eight are `bird_1` **pulled into the cylinder by the range bias**: the
  0.15 m radius prior deliberately under-reads range, which is conservative for range and *not*
  conservative for the `|dz| ≤ 6 m` cylinder test, because it shrinks `|dz|` too. Expect at least one
  dodge against a bird that is genuinely below you.

## 4. EVIDENCE-FIRST TEARDOWN — this order, no shortcuts

1. **Ctrl-C Shell 8 FIRST** and wait for
   `wrote flight log -> …/eval/results/live_flight_log_<UTC>.json`.
   Nothing else may be stopped until that line appears. `fly_pipeline.sh down` does not know about
   this shell; a `docker restart` or a `pkill` here loses the entire flight log.
2. **Then** `scripts/fly_pipeline.sh down` — already recorder-first, waits for `clip finalized` (the
   step that converts the raw in-flight dumps to schema PNGs and writes `meta.json`), then prints the
   host-side stitch command with the real clip path.
3. **Before the next `up`, confirm Shell 8 is really gone**:
   `docker exec fieldguard-sim ps -eo args= | grep avoidance_node`.
   `up`'s already-running refusal greps for the Gazebo/bridge/agent/SITL/ndvi/record/birds processes
   — `avoidance_node` is **not** on that list, so a survivor would not be caught by it. Known gap,
   documented rather than papered over; `docker restart fieldguard-sim` clears everything.

## 5. Post-flight gates — every one names its script

Capture the three paths once, and **eyeball them**: the two historical ACKNOWLEDGED logs live in the
same directory as the new one.

```bash
LOG=$(ls -t eval/results/live_flight_log_*.json | head -1)
CLIP=$(ls -td eval/results/clips/real_flight_*/ | head -1)
ls -t eval/results/bird_drive_*_applied.jsonl | head -5     # ONE of these belongs to this take
TRUTH=$(ls -t eval/results/bird_drive_*_applied.jsonl | head -1)
printf 'log:   %s\ntruth: %s\nclip:  %s\n' "$LOG" "$TRUTH" "${CLIP%/}"
```

**`head -1` is a guess, and this take may have produced two applied logs.** An aborted takeoff
(`Arm: Accels inconsistent` → retry, §2) or the `fly_pipeline.sh birds` override (§1) restarts
`drive_birds.py`, which opens a NEW applied log — and `head -1` then picks the one covering only the
tail of the flight. Every earlier tick would be answered from the birds' config **spawn** poses, and
bird_0 spawns 4 m below cruise directly under mission lane x=15: that fabricates a ~0 m breach or
hides a real one. The gate refuses to guess for you — with an explicit `--truth` it still counts the
other candidates and fails **`AMBIGUOUS TAKE`**, naming them. If it does: identify the log whose sim
window covers the whole flight, move the others out of `eval/results/`, re-run.

**Committed truth tracks always overlap a fresh take's sim window** (Gazebo sim time restarts near
0 every run), so the span scan alone cannot disambiguate — that is what `TRUTH_BINDINGS` in
`scripts/check_live_flight_log.py` is for. To score a take whose evidence will be committed: add
one line binding the flight-log stem to its `bird_drive_*_applied.jsonl` filename, **in the same
diff as the evidence**, then score. The pin is the disambiguation; never move committed safety
evidence out of the tree to get past the scan (one forgotten restore is a lost truth track).

*(The `birds` pane also prints the exact `--truth` line on its own Ctrl-C, including the sim window
the truth track covers — but `down` kills the session a few seconds later, so read it then or use
the command above.)*

**Gate 1 — safety, on the flight log (schema 2):**
```bash
python3 scripts/check_live_flight_log.py "$LOG" --truth "$TRUTH"
```
`--truth` applies to **every** log on the command line, so score one flight at a time. Omit it and
the gate auto-discovers by sim-time overlap, refusing on 0 or >1 candidates — Gazebo sim time
restarts near 0 every run, so picking the wrong log yields a full flight of confident spawn-pose
"truth". What it prints, whatever the verdict:

- **`gt_cpa_m` — the measured number.** Horizontal closest approach to the bird's own applied-pose
  track, scoped to the policy's `vertical_threat_m` (±6 m) band, bar = `min_bird_clearance_m`
  (3.0 m), read live from `PolicyParams` so gate and control law cannot drift. Neither body is
  vertex-sampled: the drone is the flown **polyline**, not its 5 Hz vertices, and every landed
  `set_pose` call is scored over **its own in-effect window** rather than at tick instants (a bird
  driven through a hovering drone between two ticks read 3.8067 m → VALID on a 0.0000 m strike).
  `joined via tick_sample|pose_window` names which pass produced the number. Ambiguity inside a
  `set_pose` bracket resolves to the **nearer** candidate: uncertainty must not buy clearance.
- **`gt_cpa_gated_m` — printed only if the sim clock stalled**, and then it is what meets the bar.
  A frozen `tick_stamp_sim_s` re-dates the bird, never the drone, so the join can only over-report
  separation. The freeze is priced off the flight's **own stamps** — the gap between the frozen
  value and the next stamp that advanced, i.e. the sim seconds that run really hides — times the
  fastest scripted bird (7.00 m/s); no nominal tick rate enters it. A stall long enough to hide the
  whole 3.0 m bar is not debited at all: it fails as a **clock** fault, since nothing about
  separation was measured, and that one is not acknowledgeable at all (§6a acknowledges a recorded
  *separation finding*, never a broken log).
- **`detection_cpa_m` — labelled ESTIMATOR CHECK, never a gate**, beside
  `range_estimate_error_at_cpa_m`. A monocular estimate may not referee itself.
- **Two coverage denominators, and they measure different things.** *truth coverage `N/M` ticks* is
  the drone axis; *truth poses scored `N/M`* is the bird axis (landed `set_pose` calls inside the
  flight window that a stamped drone segment covered). Tick coverage reads 100 % whether or not a
  bird pose was ever looked at, so read both. Partial coverage still passes; the uncovered window is
  *unmeasured*, not clean.
- **R2** (every accepted dodge cleared `lateral_tree_margin_m` = 1.0 m), **R3** (no re-latch below
  `degenerate_range_m` = 1.0 m, gated on the number, not on the flag), **R3.7 / R3.8** — the two
  halves of the executor's bird backstop: **R3.8** reads the `gate_reject` events the backstop
  writes (`gate_rejects=N (bird-bar rejects=B, closest refused point X m)` — that is the backstop
  *working*, and a reject that names neither an obstacle nor a sub-bar bird gap is a hard failure),
  while **R3.7** is the exhaustion property (no accepted `maneuver` may record a setpoint inside the
  bar — on a log this executor produced it is unreachable, so a breach means the backstop did not
  fire). Plus the clock block (`gz_clock_stream`, 0 violations, one tick stamp per flown-path point).
- **`holds with a threat=N of M hold(s) [CONTEXT, NEVER GATED]: min hold-tick bird clearance X m`.**
  Printed on **every** schema-2 log, with its denominator, including `0 of 0` — a take that measured
  nothing about hold separation says so rather than falling silent. A HOLD commands the vehicle's
  **own current position** — zero displacement — so it chooses no point and
  honours no clearance bar; guarantee 1 covers commanded *displacement* only. Below
  `degenerate_range_m` the vehicle is inside the 3.0 m bar by construction, so a hold inside the bar
  there is the **pre-registered signature of R4 (escape geometry) being open**, not a new finding —
  and a rejection can leave the commanded separation *worse* than the point it refused. Expect this
  line on any take with a close encounter; book R4, do not re-fly. A hold event that carries **no
  `bird_clearance_m` key at all** is a hard failure, not a quiet zero: the executor writes that field
  on every hold (`None` when the decision named no threat), so its absence is field drift and the
  hold count would keep rising with nothing behind it.
- **detector counters with a rate**: `frames_detected_on / ndvi_msgs_received` against a stated
  floor, and `n_stale_dropped` against the number of ticks the loop engaged on.
- **`R2/R3 PASS (vacuous): 0 accepted dodges to check`** — in those words, when nothing was dodged.
  §6 has the three-way diagnosis; the numbers above pick between them.

**Gate 2 — the map, on the clip.** Stitch first (offline, ADR-010), then run the tree gate:
```bash
python3 scripts/stitch_ndvi.py --clip "${CLIP%/}"
python3 scripts/check_tree_positions.py "${CLIP%/}"
```
`check_tree_positions.py` is **the** tree gate: it prints the per-tree table (imaged / canopy-grade /
NDVI lift) and **exits 1 on the georef-displacement signature** — any positive-NDVI cell farther than
2 m from every tree centre. Post-mount-fix clips put 100 % of theirs at exactly 1.7678 m; the
horizon-facing mount put its at 6.4-11.9 m off a *full-looking* 697/720 grid, which is how a
misplaced map gets caught. Ignore the older liveness-style check (`gz topic -l | grep
model/tree_row0_0`) wherever you meet it: the birds and trees are **static** models and advertise no
pose topics, so it can only ever prove that a name exists.

**Then** the ADR-003 re-score on the new clip, if this take is also being used as detector evidence —
`FULL_PIPELINE_DEMO.md` §4 owns that procedure (`CLIP=… bash eval/run_spike.sh`; the bare invocation
silently re-scores the *synthetic* clip).

**Commit the evidence, not the bulk**: `meta.json`, `poses.jsonl`, `heatmap/*`, the flight log, the
`bird_drive_*` sidecar + applied log, and a handful of sample frames. `.gitignore` already carries
un-ignore rules for exactly those paths. Evidence that isn't committed doesn't exist.

## 6. Reading the verdicts — what each one means for booking a re-fly

| verdict | what it means | re-fly? |
|---|---|---|
| **VALID**, `gt_cpa_m ≥ 3.0`, R2/R3 non-vacuous, truth coverage high | the take did what it was booked for: a real detection drove a real dodge at a measured separation | **No.** This is the Week-6 artifact. |
| **VALID** with `R2/R3 PASS (vacuous): 0 accepted dodges` and/or `gt_cpa_m NONE-IN-BAND` | the loop never engaged — no bird ever entered the threat band. The gate passed because it measured nothing, and says so | **Yes, for the avoidance half.** Read the two numbers printed beside it *before* deciding why (below); do not assume a phase miss. The NDVI half of the take still stands if gate 2 passes. |
| **INVALID — "no truth track"** / clock violations / missing R2/R3 fields | procedural, not a result: the driver never ran, the log was scored against another take, teardown order was broken, or the node was killed before it wrote | **Yes — the cheapest kind.** Nothing in the code is wrong; fix the procedure (§1, §4) and re-fly. |
| **INVALID — `gt_cpa_m` breach** | a real safety finding of the S1 class, and the **pre-registered** possible outcome below | **Not for a green, and there is no one-file way to make it one.** Land R4 first, then re-fly. Keep the log and write the finding up (§6a) — but expect this take to stay **INVALID / exit 1** until it is re-flown. |
| **INVALID — "HALF an acknowledgement"** | one of the two acknowledgement halves is present and the other is not — the gate names which | Fix the acknowledgement (§6a), not the flight. This verdict is about the paperwork; the CPA breach printed above it is the finding. |
| **ACKNOWLEDGED SAFETY FINDING** | recorded history, kept as evidence, **not** a passing flight (stderr, its own word, exit 0) | n/a — never quote it as a green flight. Only the two historical logs are in this state. |
| **`check_tree_positions.py` exit 1** | canopy drawn where no tree exists: the NDVI half of this take is void whatever the cell count says | **Yes**, and run §0d `verify_mount_geometry.sh` *before* booking it. |

**Diagnosing a vacuous pass — the artifact tells you which, so do not guess.** Three different
faults produce "the loop never engaged", and they need three different fixes:

- `n_stale_dropped=N over 0 detection event(s)` with **N > 0** → **not vacuous, DEAD.** Every
  detection expired before the policy could act on it, and the gate fails the log
  (`AVOIDANCE WAS DEAD`). Cause is the clock, not the geometry: a sub-second offset between the
  frame stamps and `now_s` reads as fresh in the domain tripwire (it only fires on stamps in the
  *future*) and as expired in the staleness gate. Fix the clock, re-fly.
- `detect rate` below the printed floor, or `boxes_total 0` → the **detect** half. Check the
  `frames_detected_on / ndvi_msgs_received` rate and the `dropped_*` counters in the same line:
  `no_intrinsics` means `/fg/ndvi/camera_info` was late (bringup order, §1), `no_pose_pair` means
  the PoseBuffer starved.
- `boxes_total > 0`, `0 stale drops`, loop engaged on 0 ticks → **the honest phase miss**: the
  detector saw birds and every one fell outside the threat cylinder. The gate says so in those
  words. This is the one that re-runs §0b and re-flies.

### 6a. Acknowledging a breach takes TWO halves — and you cannot do it alone at the prompt

An **ACKNOWLEDGED** breach needs **both** of these, and the gate says which one is missing:

1. **`<log-stem>.SAFETY_FINDING.md` beside the log** — the written finding, in the directory the
   evidence lives in, so whoever meets the log later gets the reason with the verdict;
2. **the log stem pinned in `ACKNOWLEDGED_BREACH_STEMS`** in `scripts/check_live_flight_log.py` — a
   reviewed diff on the safety gate itself.

Marker without pin, or pin without marker, is **INVALID**: half an acknowledgement acknowledges
nothing.

**Why it costs a code review (2026-08-24).** Until this round the marker file alone did it — so the
instruction *this runbook* gave after a breach ("keep the log, add the marker") was also the way to
turn a **new** bird strike into a green CI run: one `touch` in a gitignored directory, by whoever
flew it, with nobody else in the loop. §7 pre-registers this take as *possibly breaching* and R4 is
open, so that was the expected next event, not a hypothesis. The number a safety gate reports may
not be silenced by a file that nobody reviewed.

**So, in practice, after a real breach:** write the marker, do **not** add the pin, and let the take
stand at **INVALID / exit 1**. That is the correct record for a flight that breached — the two
pinned stems are *historical* logs that cannot be re-flown, and the list is meant to stay two long.
Adding a third is a deliberate, reviewed decision about recorded history, never a step in a
post-flight checklist.

## 7. PRE-REGISTERED EXPECTATION — read this before you read the result

R2 (`lateral_tree_margin_m` 1.0 m) and R3 (degenerate re-latch refusal) fly for the first time here.
**R4 does not.** The reversal-preferring candidate order that produced the two historical ~5 cm bird
strikes is unchanged, and ADR-015's threat bird passes nearly overhead. **This flight may honestly
FAIL its own GT-CPA gate.** That is a measurement which ranks R4 next, not a wasted take — and it is
written here *before* the flight so it cannot be reinterpreted afterwards.

## 8. Known gaps — deliberate, named, not blind spots

- The latched setpoint's **swept path is not re-vetted** as ownship moves (the executor re-vets the
  *point* via `is_safe_3d`, which is structurally unreachable at 15 m cruise — QA finding S2).
- A **first** latch at degenerate range is still permitted; R3 scopes the refusal to *re*-latch.
- **A HOLD honours no clearance bar, and cannot** (S5, re-stated honestly in QA round 3). It commands
  the vehicle's own position — zero displacement — so there is no point to vet. In the R3-refusal
  branch the vehicle is inside `degenerate_range_m` by construction, so the hold is inside the 3.0 m
  bird bar too and can be *nearer* the bird than the setpoint just refused (measured: reject at
  1.000 m, hold at 0.400 m; 41 of 10,000 random control ticks held inside the bar, closest 0.288 m).
  The executor logs `bird_clearance_m` on every hold and the gate prints the minimum as CONTEXT.
  **Commanding a point that IS outside the bar is escape geometry — R4, open and uncut.**
- The detector has **no tracker** (`track_id` is null) and **no confidence model** (always 1.0).
  Frame-to-frame association is not built; the policy's threat test is per-frame.
- **Watch the re-latch count.** Monocular range error measured offline at median 1.65 m / max 3.67 m
  can exceed the executor's `RELATCH_THRESHOLD_M` of 3.0 m; an offline replay of the flown encounter
  produced 2 re-latches in 5 maneuvers. If the flight shows re-latch spam, the lever is
  `RELATCH_THRESHOLD_M` or a tracker — decide on the measurement, not now.
- `-0.61` stays **PROVISIONAL** (§1). The border row/column of the image is structurally invisible to
  this detector (the morphology's closing erodes with `border_value=0`), so a bird straddling the
  frame edge reads ~1 px small and is ranged slightly *farther* than it is — small, one-sided, and
  the opposite bias to the 0.15 m radius prior.
- The applied-pose log's schema 1.1 (`clock_wall_s`, which measures the ~39 ms `/clock` poll instead
  of assuming it away) has **never been flown**. On the first one, `clock_wall_s - tick_wall_s`
  should sit near 0.039 s.
