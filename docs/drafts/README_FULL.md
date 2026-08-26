# DRAFT — full README text for review (2026-08-26)

**Status: DRAFT. Nothing here has been applied to `README.md`.** This is the complete replacement
text, written to the contract in `docs/drafts/README_SKELETON.md`. §A is verbatim-frozen; §B is the
approved first-person arc; everything else is written to its stated intent, sources and length.

**Two mechanical notes for the apply step** (both are consequences of this file living under
`docs/`, not editorial choices):

* **Repo paths are backticked here; they become markdown links when applied to `README.md`.**
  `scripts/build_docs_site.py` resolves intra-repo links relative to the *source file's* directory,
  so `eval/results/…` written from `docs/drafts/` is a broken link and hard-fails the docs build.
  From `README.md` at the repo root, the same relative paths resolve. Link every backticked path
  that names a file a reader would want to open.
* **The two image lines are in fenced blocks**, for the same reason plus alt-text fidelity — paste
  them unfenced. Both assets are git-tracked (`.gitignore` allowlists `heatmap/` and the eight
  2026-08-25 overlay PNGs), so a fresh clone renders them.

Everything from the next heading down is the README.

# SwathKeeper

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

```markdown
![NDVI crop-health map from one simulated flight: a 2.5 m grid over the field, with bright canopy
cells over the three tree rows against darker soil](eval/results/clips/real_flight_20260825T205705Z/heatmap/heatmap.png)
```

*One flight (`real_flight_20260825T205705Z`), stitched offline: **720 of 720** cells on a 2.5 m grid
from **649 painting frames of 671 airborne**; **18/18** trees imaged, **11** canopy-grade, median
NDVI lift **+0.5562**, every one of the 11 positive cells within 2.0 m of a real tree centre; gate
PASS. Same flight as the avoidance story below. NDVI = Normalized Difference Vegetation Index, a
red / near-infrared ratio that reads as plant health.*

**Dashboard** — flight replay, avoidance event log, NDVI overlay: *GitHub Pages not enabled yet
(placeholder: `https://<user>.github.io/<repo>/dashboard/`)*. Locally: `python3 -m http.server 8000`
from the repo root, then open `/dashboard/`. **Demo video (2–3 min):** TODO — not yet recorded.

- **A reactive avoidance loop that keeps its books.** Detect → take over (AUTO→GUIDED) → dodge →
  resume → reconcile coverage. Latest flight: **720 of 720 cells covered, 0 debt**, 1858 path
  points, **116 at-risk cells recovered across 4 diverts**, 0 clock-domain violations.
- **The flagship flight failed its own safety gate — and that is the headline.** Ground-truth
  closest approach **0.0067 m** against a **3.00 m** bar. The failure was **pre-registered in
  writing before takeoff**; the take stands **INVALID, exit 1**, and it is not softened anywhere in
  this repo.
- **Then the project measured *why*, offline, and changed course on the measurement.** A
  jerk/accel-limited replay of all three flights swept 81 cells (2–10 m/s × every escape candidate ×
  3 plant models) and returned **no mission speed at which the nadir sensor geometry is safe** —
  the intruder's own 6.0 m/s closing speed caps warning at **0.41 s even from a hover**, and the
  cheapest escape needs **1.25 s**. A second forward-facing sensor moved from growth path to scope.
- **Perception is measured, not asserted.** On the real render: per-obstacle-track false-negative
  rate **0.000** (3 of 3 intruders, 20 obstacle-visible frames), precision 0.708 / recall 0.850. A
  classical blob detector was **adopted over a learned model** because it won on the same harness —
  and re-confirmed in 2026-08-26's comparison study against a working rival arm at **gap +0.000**.
- **A crop-health map from the same flight, on the same cell grid as the coverage ledger.**
  **720/720** cells on a 2.5 m grid from 649 painting frames, **18/18** trees imaged, 11 of them
  canopy-grade, median NDVI lift **+0.5562**, every bright cell within 2.0 m of a real tree centre.
- **Reproducible or it doesn't count.** Every headline number names the artifact that proves it, and
  the evidence gates run in CI — where `main` is currently **red by design**, because the committed
  breach has not been re-flown.

## Architecture at a glance

```
Gazebo farm world  ──►  NDVI camera (RGB Red + thermal-as-NIR, ADR-007)
 (tree rows, birds)          │
                             ├──►  DETECT: unplanned obstacle on the NDVI frame (ADR-003 / ADR-009)
                             │            │
ArduPilot SITL  ◄─AP_DDS──  ROS 2 avoidance node
 (real firmware,             │      ├─ AVOID    policy: dodge? where? (swept path vetted in 3D
  software-in-the-loop)      │      │           against the surveyed tree geofence)
                             │      ├─ REPLAN   executor: AUTO → GUIDED, fly it, hand back, resume
                             │      └─ REQUEUE  ledger: every cell the dodge disturbed is re-covered
                             │                  or booked as coverage debt
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
that gap is where this project sits. Wire corridors here are **scoped future work, as mapped
infrastructure** (ADR-019) — not a capability this repo demonstrates.

## Results, quantified

| Measurement | Number | Proved by |
|---|---|---|
| Coverage integrity, live flight | **720 covered / 0 debt**; 116 at-risk cells recovered across 4 diverts; 1858 path points | `eval/results/live_flight_log_20260825T210402Z.json` + its `.SAFETY_FINDING.md` |
| Detector rate, first in-air measurement | **1301 / 1302 frames = 99.92 %** against a 0.90 floor | same log; `docs/DECISIONS.md` ADR-013 am. 18 |
| Bird clearance on that same flight | **0.0067 m horizontal at 4.03 m vertical, against a 3.00 m bar — INVALID.** Reported as the system working | `eval/results/live_flight_log_20260825T210402Z.SAFETY_FINDING.md` |
| Detection quality, real render (ADR-003 criterion 3) | per-track FNR **0.000**, 3/3 intruders, 20 obstacle-visible frames; precision 0.708 / recall 0.850 (TP 17 / FP 7 / FN 3) | `eval/results/adr003_20260823/spike_scores.json` |
| Adopted detector vs the working RGB comparison arm (criterion 2, closed 2026-08-26) | safety numbers **identical**; precision 0.708 → 0.227 (3.1×) on the adopted clip, 1.000 → 0.037 (27×) in the air; **gap +0.000 → ADOPT** | ADR-003 am. 10 |
| Map completeness | **720 / 720** cells, 2.5 m grid, 649 painting frames | `eval/results/clips/real_flight_20260825T205705Z/heatmap/heatmap.json` |
| Tree localization, same clip | **18/18** imaged, **11/18** canopy-grade, median lift **+0.5562**, all 11 positive cells < 2.0 m from a tree centre | `scripts/check_tree_positions.py` on that clip |
| Recording cadence | **5.0 Hz** flat, 100 % delivery on both bands (was 0.41 Hz — a Fast DDS shared-memory segment was the root cause) | that clip's `meta.json` |
| Live↔offline equivalence | flight-logged obstacle positions reproduced to **1 µm** across SciPy 1.8.0 (air) / 1.13.1 (host), all 1301 in-window frames | ADR-009 am. 2 |
| Monocular range estimator vs ground truth at closest approach | agrees to **3.3 mm** (0.0035 m vs 0.0067 m) — and is still refused as a gate, on purpose | ADR-013 am. 19 |
| Automated tests | **1058 passed, 1 failed, 2 skipped, 0 xfail** (`python3 -m pytest tests -q`). The single failure is deliberate: the CI evidence gate is red on the committed breach | `tests/README.md`, measured 2026-08-26 — re-run and re-quote if you change the suite |

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
cutting closer than that. The coverage ledger closed at **720 cells covered, 0 debt**. The detector
ran on **1301 of 1302** frames in the air, against a floor of 90 %. The crop-health map from that
same flight is the best I have.

**And the take is INVALID.** The closest the aircraft actually came to the bird — measured against
the simulator's own record of where the bird was, not against what the drone thought it saw — was
**0.0067 m** horizontally, 6.7 millimetres, while flying 4.03 m above it. The safety rule requires
3.00 m of separation anywhere inside a ±6 m vertical band, so 4 m below is squarely inside it. Two
consecutive log entries also shared a timestamp, which hides 0.161 s of bird movement; the check
charges that blind spot as distance the bird could have covered — a 1.1277 m penalty — so the
number it actually judges reads **−1.1210 m**. Either way it's a strike, and the check exits with a
failure.

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
at which this camera makes this encounter survivable? **81 combinations** — mission speeds from 2
to 10 m/s, every escape direction, three different assumptions about how hard the aircraft can
actually accelerate.

Not one clears 3 m. Flying slower can't fix it, because the bird brings its own 6.0 m/s toward
me: even from a standstill the camera can only ever buy **0.41 s** of warning, and the cheapest
escape that clears the bar needs **1.25 s**. To see far enough ahead at the speed I flew, I would
need **17.8–38.7 m** of forward vision. Pointed at the crop, I have **2.48 m**.

I changed the roadmap on that number rather than on a hunch. A second, forward-facing sensor moved
from "documented growth path" into scope, and my pre-flight check now refuses every speed I
actually fly on this geometry — so I can't honestly book another of these flights until that sensor
exists. The system found its own sensor's limit and refused to fly what it can't pass.

```markdown
![Two NDVI frames from that flight with boxes drawn on them: the ground-truth position of the bird
and, tight around the same bird, the box the detector produced](eval/results/adr003_20260825/overlays/gtdet_a_ndvi_direct_ndvi_frame_000964.png)
```

*The only two frames of the whole flight with the intruder inside the image — the detector boxed
both, and the harness still refused to call two frames evidence.*

## How this repo proves things

* **Pre-registration.** The failure condition is written into the runbook before the flight, so the
  result cannot be reinterpreted afterwards (`docs/runbooks/AVOIDANCE_REAL_DETECTION.md` §7).
* **Commanded is never recorded as flown.** A ledger bug that recorded dodge setpoints as flown
  understated coverage debt by up to **32 cells per scenario**; found in the 2026-08-18 audit, fixed
  and regression-pinned the same day (ADR-013).
* **Gates have to be able to fail, and they have to catch themselves.** `eval/score.py`'s
  zero-denominator ADOPT bug; `check_tree_positions.py`'s "PASS (vacuous)"; a CI evidence step that
  printed SKIP…PASS having validated nothing; a legacy check that measured path *corners* instead of
  the path, under which the one fixture that "passed" was a direct hit (7.0000 m → 0.0000 m, fixed
  test-first, and every safety number it moved got worse and was published).
* **Value checks cannot see geometry.** Every value check in the project passed while the camera
  faced the horizon upside down (ADR-007 am. 5, fixed and now gated at 2.2 px) — and the same class
  recurred on 2026-08-25, with a green 99.92 % detect rate on a flight that flew through a bird. Two
  instances make it a pattern, not an anecdote.

The full log is `docs/DECISIONS.md`: 19 architecture decision records, where corrections land as
dated **amendments** rather than edits, because the log is append-only. The amendments are the
interesting part.

## Honest limitations

**Claims ceiling, stated as policy: sim-demonstrated, evidence-gated** (ADR-019). Nothing on this
page is a field-readiness or production claim, and this project will not make one until external
hardware data or an outside conversation exists to support it.

1. **Sim-only, and that is the design choice.** ArduPilot SITL is the real firmware; Gazebo Harmonic
   is the real render; the toolchain is version- and SHA-pinned (ADR-004). What sim buys is a
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
4. **`main`'s CI is red, on purpose.** The evidence gate fails on the committed breach and stays
   failing until a clean re-fly. Turning it green would mean deleting the evidence or pinning the
   breach as acknowledged — both refused. **A green badge over a hidden bird strike is the thing
   this repo is arguing against.**
5. **Known measurement debt, booked not buried.** The committed lane pitch (15 m) exceeds the true
   camera swath derived from `camera_info` (13.772 m), leaving a **1.228 m unimaged strip per lane
   pair**; 720/720 survives only by cell-centre quantization, with 0.636 m of margin. Re-planning
   the lanes belongs to the re-fly (ADR-016 am. 1).

## Run it

* **Host Python only, no Docker** — the test suite and the offline NDVI stitch: `SETUP.md`.
* **The full sim in one command** — flies a mission and proves itself:
  `docs/runbooks/FULL_PIPELINE_DEMO.md`.
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
| **See it move, nothing to install** | the dashboard — three views over the committed artifacts, every figure computed in your browser, sha256 provenance in the footer, 5-step tour. *Pages not enabled yet;* run `python3 -m http.server 8000` and open `/dashboard/` |
| **Watch the 2–3 min narrated walkthrough** | demo video — TODO, not yet recorded |
| **Read the failure, written up beside its evidence** | `eval/results/live_flight_log_20260825T210402Z.SAFETY_FINDING.md` |
| **See the pre-registration in situ** | `docs/runbooks/AVOIDANCE_REAL_DETECTION.md` §7 |
| **Know why each choice was made, and what it cost** | `docs/DECISIONS.md` — the ADR log with its amendments |
| **See exactly where the project stands, including what is not done** | `docs/ROADMAP.md` |
| **Run it / how it works / how it was built** | `SETUP.md` · `docs/SPEC.md` · `TIGER_TEAM_GUIDE.md` |

## What I'd do next

1. **A forward-facing depth camera, on its own aperture**, beside the nadir survey camera — specced
   by the replay rather than by appetite: ≥1.25 s of physically-resolving lead, 17.8–38.7 m of
   forward horizon at the speeds I actually fly. Tilting the single camera stays rejected; it would
   trade a validated survey instrument for warning time.
2. **Then one bird dodge that clears the 3.00 m bar** — booked only once the offline predictor,
   reading the new sensor's own `camera_info`, clears that bar with ≥1.3× lead margin on the
   conservative plant. The gate exists to end failure theater: the next take is *designed* to pass.
3. **Then a mapped-wire corridor demo** — wires as a fresh per-field survey, never an external GIS
   layer, with metres of buffer because catenary sag moves 0.15–1.4 m across the design temperature
   swing. No camera wire detection is promised. (The ratified program: `docs/DECISIONS.md` ADR-019.)

## Names, and how it was built

The project was renamed from its working title *FieldGuard* (ADR-011), but code identifiers
deliberately keep the old name — `fieldguard_planning`, the `/fg/*` topics, the `fieldguard-sim`
container. That topic contract is live-verified, and renaming verified interfaces for cosmetics
re-opens confirmed state for zero functional gain. If you see `fg_`, you're in the right place.

Built by a Claude Code *tiger team*: eight specialized subagents (product, tech-lead, perception/ML,
sim, flight software, devops, QA/safety, GTM), each owning its own gates. See `TIGER_TEAM_GUIDE.md`.
