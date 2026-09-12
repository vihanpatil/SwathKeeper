# SwathKeeper

[![CI](https://github.com/vihanpatil/SwathKeeper/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/vihanpatil/SwathKeeper/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)

**An autonomous ag-survey drone that reacts to obstacles its mission plan never knew about — and
proves the survey is still complete afterwards. Built entirely in simulation; every number on this
page comes from a gate that can fail, and one of them is failing right now, on purpose.**

Commercial ag-drone platforms (DJI, DroneDeploy, Sentera, Trimble) fly **pre-surveyed static
missions**: the route is planned before takeoff and flown as planned. SwathKeeper adds the part
they leave out. When a small dynamic intruder enters the flight path mid-mission — exercised here
on scripted birds — the drone detects it on its own camera, takes authority from the autopilot,
dodges, resumes the lane, and **books every grid cell the dodge disturbed as coverage debt**, so a
silently skipped swath is a test failure rather than a rounding error. Crop-health mapping falls
out of the same flight and the same camera. It runs on ArduPilot + Gazebo + ROS 2, in simulation,
which is what makes the numbers below re-runnable by anyone.

![NDVI heatmap from one simulated flight: a 2.5 m grid over the field, with bright canopy cells
over the three tree rows against darker soil](eval/results/clips/real_flight_20260825T205705Z/heatmap/heatmap.png)

*One flight (`real_flight_20260825T205705Z`), stitched offline: **720 of 720** cells on a 2.5 m grid
from **649 painting frames of 671 airborne**; **18/18** trees imaged, **11** canopy-grade, median
NDVI lift **+0.5562**, every one of the 11 positive cells within 2.0 m of a real tree centre; gate
PASS. Same flight as the avoidance story below. NDVI = Normalized Difference Vegetation Index, a
red / near-infrared ratio commonly used as a plant-health proxy in the field — on this hand-authored
world it separates canopy from soil on four typed temperatures, not degrees of health (see
[What this is, and what it is not](#what-this-is-and-what-it-is-not)).*

**Dashboard** — flight replay, avoidance event log, NDVI overlay:
[`vihanpatil.github.io/SwathKeeper/dashboard/`](https://vihanpatil.github.io/SwathKeeper/dashboard/)
*(enable Pages in Settings → Pages → GitHub Actions if this 404s)*. Locally:
`python3 -m http.server 8000` from the repo root, then open `/dashboard/`. **Demo video (2–3 min):**
TODO — not yet recorded.

## What this is, and what it is not

**What it is:** a single-operator simulation lab — ArduPilot SITL (real firmware) + Gazebo Harmonic
(real physics and render) + ROS 2, one hand-built farm world, exercised by one engineer.

**What it is not, stated plainly rather than left for you to find:**
- The birds are teleported spheres with no collision geometry (`gz service set_pose`, physics
  bypassed) — a strike in sim is physically impossible. The offline safety gate below is the
  *entire* safety system.
- The NDVI map is a canopy-vs-soil sign test on four hand-typed material temperatures, not a
  crop-health signal — the world has no disease, stress, or moisture variation to detect.
- The flying Docker image is not SHA-pinned; no flight log records exactly what code flew it.
- Nothing here has flown on hardware.

**Claims ceiling, stated as policy: sim-demonstrated, evidence-gated.** Nothing on this page is a
field-readiness or production claim (full statement under
[Honest limitations](#honest-limitations) below).

- **A reactive avoidance loop that keeps its books — with no replan and no requeue.** Detect → take
  over (AUTO→GUIDED) → dodge → resume **the same waypoint** → book coverage debt. v1 scoped out both
  replanning and requeueing (ADR-002); the loop doesn't reroute the mission or re-inject a missed
  cell, it resumes where it left off and the ledger records honestly what that cost. Latest flight:
  **720 of 720 cells covered, 0 debt**, 1858 path points, 4 accepted dodges (8 candidates rejected
  for cutting a tree too close), 0 clock-domain violations.
- **The flagship flight failed its own safety gate — and that is the headline.** Ground-truth
  closest approach **0.0067 m** against a **3.00 m** bar, on the one flight where the drone dodged a
  bird it detected on its own camera. The failure was **pre-registered in writing before takeoff**;
  the take stands **INVALID, exit 1**. It is the third of three live avoidance flights to breach
  this bar — see the results table below for the other two.
- **Then the project measured *why*, offline, and changed course on the measurement.** A
  jerk/accel-limited replay of all three flights swept **81 mission speeds** from 2 to 10 m/s, each
  checked against every escape candidate and three different plant/acceleration models, and returned
  **no mission speed at which the nadir sensor geometry is safe** — the intruder's own 6.0 m/s
  closing speed caps warning at **0.41 s even from a hover**, and the cheapest escape needs **1.25
  s**. A second forward-facing sensor moved from growth path to scope (see below).
- **A second, more basic finding underneath the geometry one: the dodge barely moved the aircraft.**
  On that same flight the executor held GUIDED authority for **0.434 s** and the vehicle displaced
  **0.018 m** laterally against a **10 m** commanded divert. Nothing in the pipeline gates whether a
  commanded maneuver was actually flown — see below.
- **Perception is measured, not asserted.** On the real render: per-obstacle-track false-negative
  rate **0.000** (3 of 3 intruders, 20 obstacle-visible frames), precision 0.708 / recall 0.850. A
  classical blob detector was **adopted over the RGB comparison arm on the same harness** — no
  learned model was ever built — and re-confirmed in 2026-08-26's comparison study against a working
  rival arm at **gap +0.000**.
- **A map from the same flight, on the same cell grid as the coverage ledger.** **720/720** cells on
  a 2.5 m grid from 649 painting frames, **18/18** trees imaged, 11 of them canopy-grade, median
  NDVI lift **+0.5562**, every bright cell within 2.0 m of a real tree centre. (It reads canopy vs.
  soil, not crop health — see above.)
- **Reproducible or it doesn't count.** Every headline number names the artifact that proves it, and
  the evidence gates run in CI — where `main` is red by design on exactly **one** declared test (the
  committed breach has not been re-flown); an allowlist test asserts that failure and no other.

## Architecture at a glance

```
Gazebo farm world  ──►  NDVI camera (RGB Red + thermal-as-NIR, ADR-007)
 (tree rows, birds)          │
                             ├──►  DETECT: unplanned obstacle on the NDVI frame (ADR-003 / ADR-009)
                             │            │
ArduPilot SITL  ◄─AP_DDS──  ROS 2 avoidance node
 (real firmware,             │      ├─ AVOID    policy: dodge? where? (swept path vetted in 3D
  software-in-the-loop)      │      │           against the surveyed tree geofence)
                             │      ├─ RESUME   executor: AUTO → GUIDED, fly the dodge, hand back,
                             │      │           resume the SAME waypoint index — no replan, v1
                             │      │           scoped it out (ADR-002)
                             │      └─ LEDGER   coverage ledger: every cell the dodge disturbed is
                             │                  booked covered or debt — no requeue mechanism exists
                             │
                             └──►  recorded clip (frames + sim-clock-stamped poses)
                                        └──►  offline stitch (ADR-010) ──►  NDVI heatmap on the
                                              SAME 2.5 m cell grid as the coverage ledger
                                              ──►  dashboard (static, client-side, ADR-018)
```

The coverage mission (boustrophedon — lawnmower lanes) flies over MAVLink; the reactive loop
commands ArduPilot over the AP_DDS `/ap/*` bridge (ADR-005/006). Trees are *known* obstacles,
geofenced from a pre-flight boundary survey — a real ag practice — which is exactly what isolates
the hard problem: **the obstacle nobody surveyed.** The loop is extractable at the two seams an
autonomy lead looks for: `detection_source` (any detector that meets the ADR-009 evidence contract)
and `VehicleCommandSink` (any autopilot).

**Positioning, for the record.** Phased-array radar is standard on shipping mid-to-flagship ag
platforms — and the category leaders' own manuals disclaim wire bypass (DJI's T50 FAQ advises
against obstacle bypassing around electric or guy wires, and gives the specular-reflection physics
for why). What no commercial *mapping* platform does is react to an unmapped obstacle mid-flight;
that gap is where this project sits, as a sim-only lab demonstration — not a shipped capability, and
not (see [What's next](#whats-next)) a product this repo is currently building toward.

## Results, quantified

| Measurement | Number | Proved by |
|---|---|---|
| Coverage integrity, live flight | **720 covered / 0 debt**, 1858 path points, 4 accepted dodges / 8 rejected candidates. No replan, no requeue (ADR-002) — the executor resumes the same waypoint and the ledger books debt honestly | [eval/results/live_flight_log_20260825T210402Z.json](eval/results/live_flight_log_20260825T210402Z.json) + its `.SAFETY_FINDING.md` |
| Pipeline liveness, first in-air measurement | **1301 / 1302 frames reached the detector = 99.92 %** against a 0.90 floor — this is throughput, not sight: the detector *fired* on only **2 of those 1302 frames** (2 boxes), the only 2 frames in the whole flight with the bird inside the image | same log; [docs/DECISIONS.md](docs/DECISIONS.md) ADR-013 am. 18 |
| Bird clearance — three live avoidance flights, three breaches against the same 3.00 m bar | **0.0393 m** (2026-08-18, scripted `--demo` bird, ACKNOWLEDGED, exit 0) · **0.0391 m** (2026-08-23, scripted `--demo`, ACKNOWLEDGED, exit 0) · **0.0067 m** (2026-08-25, the drone's own real-time detection, **INVALID**, exit 1) | the three `.SAFETY_FINDING.md` markers; gate's current segment-path CPA recompute |
| Commanded vs. achieved displacement, the 2026-08-25 dodge | GUIDED authority window **0.434 s**; the aircraft displaced **0.018 m** laterally against a **10 m** commanded divert. No gate compares commanded to achieved — the loop is open-loop | [docs/DECISIONS.md](docs/DECISIONS.md) ADR-013 am. 12 addendum; same `.SAFETY_FINDING.md` |
| Detection quality, real render (ADR-003 criterion 3) | per-track FNR **0.000**, 3/3 intruders, 20 obstacle-visible frames; precision 0.708 / recall 0.850 (TP 17 / FP 7 / FN 3) | [eval/results/adr003_20260823/spike_scores.json](eval/results/adr003_20260823/spike_scores.json) |
| Adopted detector vs the working RGB comparison arm (criterion 2, closed 2026-08-26) | safety numbers **identical**; precision 0.708 → 0.227 (3.1×) on the adopted clip, 1.000 → 0.037 (27×) in the air; **gap +0.000 → ADOPT** | ADR-003 am. 10 |
| Map completeness | **720 / 720** cells, 2.5 m grid, 649 painting frames | [eval/results/clips/real_flight_20260825T205705Z/heatmap/heatmap.json](eval/results/clips/real_flight_20260825T205705Z/heatmap/heatmap.json) |
| Tree localization, same clip | **18/18** imaged, **11/18** canopy-grade, median lift **+0.5562**, all 11 positive cells < 2.0 m from a tree centre | [scripts/check_tree_positions.py](scripts/check_tree_positions.py) on that clip |
| Recording cadence | **5.0 Hz** flat, 100 % delivery on both bands (was 0.41 Hz — a Fast DDS shared-memory segment was the root cause) | that clip's `meta.json` |
| Live↔offline equivalence | flight-logged obstacle positions reproduced to **1 µm** across SciPy 1.8.0 (air) / 1.13.1 (host), all 1301 in-window frames | ADR-009 am. 2 |
| Monocular range estimator vs ground truth at closest approach | agrees to **3.3 mm** (0.0035 m vs 0.0067 m) — and is still refused as a gate, on purpose | ADR-013 am. 19 |
| Automated tests | **1794 passed, 1 failed, 1 skipped, 0 xfail** (`python3 -m pytest tests -q`). The single failure is deliberate: the CI evidence gate is red on the committed breach | [tests/README.md](tests/README.md), measured 2026-09-11 — re-run and re-quote if you change the suite |

Two caveats this repo refuses to round off. The −0.61 real-render detection threshold is
**PROVISIONAL** — narrowed on 2026-08-26 across a 2.3× depth span (3.9 / 6.9 / 9.0 m), still open
beyond ~11 m. And there is **no quotable second-sensor delta**: the RGB arm was measured to share
the primary's band bit-for-bit, so it never was a second sensor, and the figures above are
detector-versus-detector.

## The flight that failed, and what it bought

On 2026-08-25 I flew the thing this project was built for: the avoidance loop running on an
obstacle nothing injected. The drone found a small dynamic intruder — a scripted bird — on its own
camera, judged its distance from how large it appeared in frame, and diverted around it.

This sequence is worth explaining, because it's the whole product. My software picks a dodge point,
checks the *entire path* the aircraft would sweep through it against the known positions of the
tree rows, and then commits to that point — it *latches* it — so that a flickering detection stream
can't yank the aircraft around halfway through a maneuver. It takes control of the vehicle away
from the survey mission, flies the dodge, hands control back, and then reconciles the coverage:
every cell of the field the detour disturbed is either re-covered or booked as debt. On this flight
it accepted four dodges, each keeping the whole swept path at least 1.3 m clear of the nearest tree
(1.393 / 1.756 / 1.340 / 1.857 m against a 1.0 m margin), and rejected eight other candidates for
cutting closer than that. The coverage ledger closed at **720 cells covered, 0 debt** — resumed at
the same waypoint each time, never replanned or requeued. The pipeline reached the detector on
**1301 of 1302** frames in the air, against a floor of 90 % — that number is throughput, not sight;
the detector itself *fired* on only 2 of those 1302 frames, and both are shown below. The map from
that same flight is the best I have.

**And the take is INVALID.** The closest the aircraft actually came to the bird — measured against
the simulator's own record of where the bird was, not against what the drone thought it saw — was
**0.0067 m** horizontally, 6.7 millimetres, while flying 4.03 m above it. The safety rule requires
3.00 m of separation anywhere inside a ±6 m vertical band, so 4 m below is squarely inside it. Two
consecutive log entries also shared a timestamp, which hides 0.161 s of bird movement; the check
charges that blind spot as distance the bird could have covered — a 1.1277 m penalty — so the
number it actually judges reads **−1.1210 m**. Either way it's a strike, and the check exits with a
failure.

This was not the first close call. Two earlier flights — 2026-08-18 and 2026-08-23, both flown
against a scripted `--demo` bird, on executor code that predates this take's hardening — also
breached the same 3.00 m bar, at **0.0393 m** and **0.0391 m** (the gate's current path-segment
recompute; the original vertex-only geometry under-measured both as 0.0597 m and 0.0518 m until a
2026-08-26 fix). Both are marked **ACKNOWLEDGED**, not passing — acknowledgement is a written,
two-part record filed beside the evidence, never a softened verdict. Three live avoidance flights,
three breaches.

I wrote that outcome down before I flew it:

> **This flight may honestly FAIL its own GT-CPA gate.** That is a measurement which ranks the
> next fix, not a wasted take — and it is written here before the flight so it cannot be
> reinterpreted afterwards.

The check that failed the flight hadn't existed eight days earlier. I built it the day before and
then attacked it in five review rounds, which closed six separate ways it could have printed a
false pass — one of them a frozen clock that let a true 0.0000 m strike report as 3.5000 m of
clearance. Marking a breach as "acknowledged, known history" in this repo takes two separate
halves, on purpose: a written finding filed beside the evidence, *and* the log's name pinned inside
the safety check's own source, which is a reviewed code change. I wrote the first and deliberately
withheld the second. The take stands INVALID.

**The number was the easy part. What caused it wasn't what I expected.**

The obvious read is that the dodge was too slow. It wasn't. The first time the camera saw that bird
at all was the same instant the two were closest: **0.175 s** between first sight and closest
approach, and **0.000 s** by the time my software had something it could act on. There was never a
moment when a dodge could have started. The camera points straight down,
because that is what makes the crop map work, and at this encounter's 4.03 m of vertical separation
it covers only about **4 %** of the cross-section of the airspace the avoidance rules treat as
dangerous. The detector converted every chance it got — two boxes on the two frames where the bird
was inside the image — and my scoring harness still refused to grade the result, because 2 frames
and 1 of 3 birds is not evidence. A green 99.92 % detection rate sat on top of a flight that flew
through a bird. **Checks that measure values cannot see geometry.**

So I didn't go and build the escape-geometry fix that the failure was supposed to rank next. I
replayed all three of my
logged flights through a simple physics model of the aircraft — one held to the same acceleration
and jerk limits the real autopilot enforces — and asked the question directly: is there *any* speed
at which this camera makes this encounter survivable? I swept **81 mission speeds** from 2 to
10 m/s, each checked against every escape direction and three different assumptions about how hard
the aircraft can actually accelerate.

Not one clears 3 m. Flying slower can't fix it, because the bird brings its own 6.0 m/s toward
me: even from a standstill the camera can only ever buy **0.41 s** of warning, and the cheapest
escape that clears the bar needs **1.25 s**. To see far enough ahead at the speed I flew, I would
need **17.8–38.7 m** of forward vision. Pointed at the crop, I have **2.48 m**.

I changed the roadmap on that number rather than on a hunch. A second, forward-facing sensor moved
from "documented growth path" into scope, and my pre-flight check now refuses every speed I
actually fly on this geometry — so I can't honestly book another of these flights until that sensor
exists. The system found its own sensor's limit and refused to fly what it can't pass.

![Two NDVI frames from that flight with boxes drawn on them: the ground-truth position of the bird
and, tight around the same bird, the box the detector produced](eval/results/adr003_20260825/overlays/gtdet_a_ndvi_direct_ndvi_frame_000964.png)

*The only two frames of the whole flight with the intruder inside the image — the detector boxed
both, and the harness still refused to call two frames evidence.*

**There's a second problem underneath even that geometry, and I only found it by finally checking
something I'd never checked: did the dodge actually move the aircraft?** On this take the executor
held GUIDED authority — the interval where my software, not the autopilot, disposes motor commands —
for **0.434 s**. In that window the aircraft displaced **0.018 m** laterally against a divert I'd
commanded as 10 m. My software fires a mode switch and a setpoint and calls the maneuver "accepted"
the instant it publishes them; nothing downstream checks whether the vehicle actually moved. That
isn't a sensor problem, and a forward-facing camera doesn't fix it: the loop is **open-loop** — a
fire-and-forget mode/setpoint command with no gate on achieved displacement. That is why the next
engineering quarter here, if there is one, is closing that loop, not adding another sensor (see
[What's next](#whats-next)).

## Forward depth camera — built, scored, flown once as a wiring flight

The sensor the geometry finding put into scope now exists in sim and has flown once, on 2026-09-11,
as a wiring flight with no target in the world. Recording what that flight did and did not prove is
the point.

**Commissioned (ADR-020).** A `gz-sim` `depth_camera` on its own nose-mounted aperture, separate
from the nadir NDVI mount. Six commissioning gates (D1–D6) were measured live in a Docker session:
mount geometry, delivery, a booking gate that refuses to authorise a flight on config prose alone —
it passed at **5.0 m/s with 1.780× margin** on the sensor's own live intrinsics, not a number I typed
in.

**Scored (ADR-021).** A forward depth segmenter (a black top-hat on depth: `closing(D, K) − D >
margin`) was scored against **85 stations of a cluttered, hand-labelled render** — parked, static
vehicle, noiseless sensor. All seven pre-registered bars passed: 0 missed detections of 49, 0 merge
mislabels of 71, 0 unmapped false positives across 8 frames, range error p95 **0.108 m**. Its
cluttered acquisition range measured **46.0 m**, which *qualifies* the booking above and does not
raise it — read that number's clutter robustness to **28 m only**; every rung from 30 m to 46 m in
that render happens to be sky-backed, not clutter-tested, which is this world's geometry, not a
property of the sensor.

**Flown once, no target (2026-09-11).** `scripts/fly_pipeline.sh node --detection-source depth` on a
booked 5.0 m/s boustrophedon with all birds parked off-field. The wiring passed end to end: **5345 of
5345** depth frames reached the segmenter, 0 dropped; **33,029** boxes, 98.7 % of them annotated as
mapped canopies and correctly treated as non-threats; depth delivery **1.000** in both measured
windows; ledger 720/0. The flight **failed its own pre-registered bar**: detector wall time p95
12.98 ms passes the 25 ms bar, **max 141.16 ms fails the 100 ms bar**, so the log stands **INVALID**
(a second cause, an "ambiguous truth track", is a checker gap for bird-less flights, recorded as owed).
Delivery and pitch **at the booked speed are still unmeasured**: the cruise median was 4.27 m/s under
the 5.0 m/s cap against a 4.5 m/s bar. The sensor has never seen a bird in the air (ADR-020 am. 6,
ADR-021 am. 1).

## How this repo proves things

* **Pre-registration.** The failure condition is written into the runbook before the flight, so the
  result cannot be reinterpreted afterwards ([docs/runbooks/AVOIDANCE_REAL_DETECTION.md](docs/runbooks/AVOIDANCE_REAL_DETECTION.md) §7).
* **Commanded is never recorded as flown.** A ledger bug that recorded dodge setpoints as flown
  understated coverage debt by up to **32 cells per scenario**; found in the 2026-08-18 audit, fixed
  and regression-pinned the same day (ADR-013).
* **Gates have to be able to fail, and they have to catch themselves.** [eval/score.py](eval/score.py)'s
  zero-denominator ADOPT bug; `check_tree_positions.py`'s "PASS (vacuous)"; a CI evidence step that
  printed SKIP…PASS having validated nothing; a legacy check that measured path *corners* instead of
  the path, under which the one fixture that "passed" was a direct hit (7.0000 m → 0.0000 m, fixed
  test-first, and every safety number it moved got worse and was published).
* **Value checks cannot see geometry.** Every value check in the project passed while the camera
  faced the horizon upside down (ADR-007 am. 5, fixed and now gated at 2.2 px) — and the same class
  recurred on 2026-08-25, with a green 99.92 % detect rate on a flight that flew through a bird. Two
  instances make it a pattern, not an anecdote.

The full log is [docs/DECISIONS.md](docs/DECISIONS.md): 23 architecture decision records, where corrections land as
dated **amendments** rather than edits, because the log is append-only. The amendments are the
interesting part.

## Honest limitations

**Claims ceiling, stated as policy: sim-demonstrated, evidence-gated** (ADR-019). Nothing on this
page is a field-readiness or production claim, and this project will not make one until external
hardware data or an outside conversation exists to support it.

1. **Sim-only, and that is the design choice.** ArduPilot SITL is the real firmware; Gazebo Harmonic
   is the real render; the toolchain versions and upstream SHAs are recorded (ADR-004) — as a
   document, not as a baked artifact: see the image caveat above. What sim buys is a
   re-flyable flight behind every number. What it costs is named, not hidden: the **transfer-gap
   register** in the replay artifact lists five gaps (attitude/motor lag, EKF lag, wind/drag,
   mode-switch latency, the plant's own accel limit), four of them flagged optimistic for the model.
2. **One authored world.** Every perception result is a property of one hand-built farm world and
   its lighting, and the RGB study says so explicitly. The named carry-forward hazard: v1 flies
   NDVI-only, so the live failure mode is an **invisible brown object** absent from the static
   obstacle map.
3. **The plant model is unvalidated against SITL.** The point-mass replay's effective lateral accel
   (1.05 m/s²) is a one-parameter fit from **one admissible axis of one flight** — labelled
   ESTIMATED, not measured, in the artifact itself.
4. **`main`'s CI is red, on purpose — and on exactly one declared test.** The evidence-gate step
   (`tests/test_ci_evidence_gate.py::TestLiveFlightLogGateHasEvidence::test_step_passes_on_the_committed_evidence`)
   fails on the committed breach and stays failing until a clean re-fly. Turning it green would mean
   deleting the evidence or pinning the breach as acknowledged — both refused. **A green badge over a
   hidden bird strike is the thing this repo is arguing against.** An allowlist test asserts that
   this is the *only* permitted red — any other failure is undeclared and must be fixed, not folded
   into "red by design."
5. **Known measurement debt, booked not buried.** The committed lane pitch (15 m) exceeds the true
   camera swath derived from `camera_info` (13.772 m), leaving a **1.228 m unimaged strip per lane
   pair**; 720/720 survives only by cell-centre quantization, with 0.636 m of margin. Re-planning
   the lanes belongs to the re-fly (ADR-016 am. 1).

## Run it

* **Host Python only, no Docker** — the test suite and the offline NDVI stitch: [SETUP.md](SETUP.md).
* **The full sim in one command** — flies a mission and proves itself:
  [docs/runbooks/FULL_PIPELINE_DEMO.md](docs/runbooks/FULL_PIPELINE_DEMO.md).
* **Reproduce the safety verdicts on the committed evidence**, nothing to install:

```bash
python3 scripts/check_live_flight_log.py eval/results/live_flight_log_*.json
```

One caveat, stated rather than left to be discovered: on the 2026-08-25 take that invocation prints
INVALID for an *ambiguous truth track* and does **not** print the 0.0067 m closest approach. The
marker file beside the log explains how to reproduce that number.

## Where to go next

| If you want to… | Go to |
|---|---|
| **See it move, nothing to install** | the dashboard — three views over the committed artifacts, every figure either computed in your browser or quoted verbatim from the gate that produced it, sha256 provenance in the footer, 5-step tour: [`vihanpatil.github.io/SwathKeeper/dashboard/`](https://vihanpatil.github.io/SwathKeeper/dashboard/) *(enable Pages in Settings → Pages → GitHub Actions if this 404s)*, or `python3 -m http.server 8000` → `/dashboard/` |
| **Watch the 2–3 min narrated walkthrough** | demo video — TODO, not yet recorded |
| **Read the failure, written up beside its evidence** | [eval/results/live_flight_log_20260825T210402Z.SAFETY_FINDING.md](eval/results/live_flight_log_20260825T210402Z.SAFETY_FINDING.md) |
| **See the pre-registration in situ** | [docs/runbooks/AVOIDANCE_REAL_DETECTION.md](docs/runbooks/AVOIDANCE_REAL_DETECTION.md) §7 |
| **Know why each choice was made, and what it cost** | [docs/DECISIONS.md](docs/DECISIONS.md) — the ADR log with its amendments |
| **See exactly where the project stands, including what is not done** | [docs/ROADMAP.md](docs/ROADMAP.md) |
| **Run it / how it works / how it was built** | [SETUP.md](SETUP.md) · [docs/SPEC.md](docs/SPEC.md) · [TIGER_TEAM_GUIDE.md](TIGER_TEAM_GUIDE.md) |

## What's next

1. **Finish this floor.** The honest, reproducible portfolio this README describes: the dashboard on
   GitHub Pages, the demo video, a license, and CI that fails on exactly the breach it should — no
   new engineering beyond that.
2. **About ten conversations with ArduPilot/PX4 autonomy teams, labs, and Part-108-minded
   integrators** — to find out whether the thing this repo is actually good at (pre-registered
   flight-evidence gates: a booking gate that caught a real 1.8× speed violation, a CPA gate that
   called a bird strike before the flight was even flown, a dashboard that recomputes its own
   verdicts from the raw log) has a buyer outside a resume. If none of the ten want to run a gate
   like this on their own logs, that's the answer: strong portfolio, no product — and that's fine.
3. **If the drone itself turns out to be worth pursuing**, the next quarter is closing the control
   loop in sim, not adding sensors: a designed gate on commanded-vs-achieved displacement (today
   `verdict="accepted"` is a hardcoded constant — nothing checks whether a dodge moved the vehicle),
   an object tracker, and a written kill criterion — **at least 20 seeded headless encounters
   clearing the 3.00 m bar** — before this repo claims "avoidance" again.

**Cut from scope, recorded so it isn't re-opened:** the ADR-019 mapped-wire-corridor demo, and
further NDVI/crop-health work — ADR-019 already called plain NDVI a commodity with nothing left to
invest in; the pipeline stays frozen as the working demo it already is.

## Names, and how it was built

The project was renamed from its working title *FieldGuard* (ADR-011), but code identifiers
deliberately keep the old name — `fieldguard_planning`, the `/fg/*` topics, the `fieldguard-sim`
container. That topic contract is live-verified, and renaming verified interfaces for cosmetics
re-opens confirmed state for zero functional gain. If you see `fg_`, you're in the right place.

Built by a Claude Code *tiger team*: nine specialized subagents (product, tech-lead, perception/ML,
sim, flight software, devops, QA/safety, GTM, plus an executive council for direction-level calls),
each owning its own gates. See [TIGER_TEAM_GUIDE.md](TIGER_TEAM_GUIDE.md).

---

Licensed under [Apache-2.0](LICENSE).
