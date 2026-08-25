# SwathKeeper 🛸🌾

> An autonomous survey drone that mows a crop field lane by lane, dodges obstacles that move into
> its path mid-flight, and keeps an honest ledger of the ground each dodge cost it — plus a
> crop-health map from the same camera.

It runs **entirely in simulation** (ArduPilot + Gazebo + ROS 2), and that is a design choice, not a
shortcut: every number on this page comes from a flight anyone can re-fly, gated by a script that
can fail. A *swath* is one pass of a coverage survey — SwathKeeper's thesis is **keeping the swath**:
the survey stays provably complete even when the flight plan doesn't survive contact with the world.

![NDVI crop-health map from a simulated flight: 720 of 720 grid cells imaged, with canopy-bright
cells over 9 of the 18 tree positions against orange soil](eval/results/clips/real_flight_20260823T073644Z/heatmap/heatmap.png)

*One flight (`real_flight_20260823T073644Z`), stitched offline: **720 of 720** cells on the 2.5 m
grid, **18/18** trees imaged — **9/18** of them canopy-grade, median NDVI lift **+0.5402** — and every
one of its 12 positive cells sits within 2 m of a real tree centre. NDVI = Normalized Difference
Vegetation Index, a red / near-infrared ratio that reads as plant health. Artifact:*
[`eval/results/clips/real_flight_20260823T073644Z/heatmap/`](eval/results/clips/real_flight_20260823T073644Z/heatmap/heatmap.json)

## Why this is different

Commercial ag-drone platforms (DJI, DroneDeploy, Sentera/John Deere, Trimble) fly **pre-surveyed
static missions**: the route is planned before takeoff and flown as planned. SwathKeeper adds the
thing they don't — **live reactive avoidance of unplanned dynamic obstacles, with coverage
integrity**. When the drone dodges, every cell the dodge disturbed is either still covered or
explicitly booked as coverage **debt**; a silently-skipped cell is a *test failure*, not a rounding
error. Crop-health mapping falls out of the same flight and the same camera.

*(Full debt **reconciliation** — re-fly every missed cell — is a documented stretch goal, ADR-002 in
the [decision log](docs/DECISIONS.md); ADR = architecture decision record. v1 ships "avoid, return to
next waypoint" plus honest debt.)*

## Status — 2026-08-25

| Piece | State |
|---|---|
| Reactive avoidance loop (detect → dodge → resume → book debt) | ✅ live on the real stack since 2026-08-05; latest flight closed the ledger **720 covered / 0 debt**, 19/19 dodges vetted |
| Bird clearance on those flights | ⚠️ **two ACKNOWLEDGED SAFETY FINDINGS** — closest approach 0.0518 m and 0.0597 m against a 3.00 m bar. Recorded as history, *not* as passes (see below) |
| Control-law fixes (1 m tree margin; no re-latch on a degenerate range) + a ground-truth safety gate | 🟡 landed offline 2026-08-24; **await one live-gated flight**, pre-registered as possibly failing that gate. The escape geometry behind both breaches is deliberately still open |
| NDVI mapping pipeline | ✅ closed — 5.0 Hz recording cadence, first full-grid map (720/720 cells), tree-position gate PASS |
| Detector choice on the real render | ✅ **ADOPT NDVI-direct** (ADR-003 criterion 3 closed 2026-08-23) — birds found on the NDVI frame itself by a classical blob detector; no trained model justified yet |
| NDVI-vs-RGB second-sensor comparison arm | 🟡 open — ADR-003 criterion 2, deferred behind the flight above; its RGB baseline is measuring an inverted signal, so it has **no quotable number yet** |
| Farmer-facing dashboard + demo video | ⏳ not started — deliberately last. It's the proof, not the point |
| Automated tests | ✅ **877 passed, 2 skipped, 0 xfail** — nothing parked as an expected failure |

### The safety story, told straight

The avoidance loop works: it detects, takes over from the mission (AUTO → GUIDED), dodges, resumes,
and books what it missed — 19 of 19 dodge setpoints vetted against the tree geofence and the bird
clearance bar. Then a gate added *after* those flights measured something nobody had measured: the
distance actually **flown** past the bird. CPA (closest point of approach) came out at **0.0518 m**
and **0.0597 m** on two independent flights, against a 3.00 m bar — roughly 58× inside it, while
every gate at the time was green. Vetting the *setpoints* had been silently reading as a claim about
*separation*.

Both logs are kept, both are marked **ACKNOWLEDGED — recorded history, not evidence of a safe
flight**, and acknowledging one deliberately costs a reviewed diff on the safety gate so an operator
cannot green their own bird strike in a single file. What landed 2026-08-24 is narrower than the
finding: two control-law fixes (a 1 m lateral margin around trees; a refusal to re-latch on a
degenerate range reading) plus the ground-truth CPA gate itself. **The escape geometry that caused
both breaches is deliberately still open** — fixing it needs closing geometry v1 does not have. So the
one flight those fixes await is **pre-registered as possibly failing its own gate**, and failing it is
the point: that measurement is what ranks escape geometry as the next fix. See
[`live_flight_log_20260823T004031Z.SAFETY_FINDING.md`](eval/results/live_flight_log_20260823T004031Z.SAFETY_FINDING.md)
and [`docs/DECISIONS.md`](docs/DECISIONS.md) ADR-013 amendment 12. You can reproduce both verdicts on
the committed evidence in one command:

```bash
python3 scripts/check_live_flight_log.py eval/results/live_flight_log_*.json
```

## Headline metrics — every number names the file that proves it

| Measurement | Number | Source |
|---|---|---|
| Bird detection, **real render** — per-bird-track FNR (false-negative rate) | **0.000** — every bird detected before its closest approach; precision 0.708 / recall 0.850 (TP 17 / FP 7 / FN 3) over 20 bird-visible frames, 3/3 birds | [`eval/results/adr003_20260823/spike_scores.json`](eval/results/adr003_20260823/spike_scores.json) |
| Map completeness | **720 / 720** cells imaged, 2.5 m grid | [`heatmap.json`](eval/results/clips/real_flight_20260823T073644Z/heatmap/heatmap.json) |
| Recording cadence (was the pipeline's bottleneck at 0.41 Hz) | **5.0 Hz** flat, 100 % delivery on both bands | [`meta.json`](eval/results/clips/real_flight_20260823T073644Z/meta.json) |
| Tree localization — the clip above, `real_flight_20260823T073644Z` | **18 / 18** trees imaged, **9 / 18** canopy-grade, median NDVI lift **+0.5402**; gate PASS — it fails on any positive cell more than 2 m from a tree centre | [`scripts/check_tree_positions.py`](scripts/check_tree_positions.py), run on that clip |
| Canopy contrast over soil — best take, a **different, earlier flight** (2026-08-21) | median NDVI lift **+0.8692**, but that take imaged only 12 / 18 trees, 8 canopy-grade | pinned in [`tests/fieldguard_planning/test_check_tree_positions.py`](tests/fieldguard_planning/test_check_tree_positions.py) |
| Coverage integrity, live flight | **720 covered / 0 debt**, 19 / 19 dodges vetted | [`docs/DECISIONS.md`](docs/DECISIONS.md), ADR-013 amendment 11 |
| Bird clearance, live flight | **0.0518 m / 0.0597 m** vs a 3.00 m bar — ACKNOWLEDGED findings, not passes | the two `*.SAFETY_FINDING.md` markers |
| Automated tests | **877 passed, 2 skipped, 0 xfail** | [`tests/README.md`](tests/README.md) |

Two caveats this repo refuses to round off: the real-render detection threshold (−0.61) is still
**PROVISIONAL** at n = 20 pending false-positive characterisation, and the RGB comparison arm's
"1.000 FNR" measures an **inverted** birdness signal on this world — it is not RGB's ceiling and is
never quoted as one.

## How it works

```
Gazebo farm world  ──►  NDVI camera (RGB Red + thermal-as-NIR, ADR-007)
 (tree rows, birds)          │
                             ├──►  detector: dynamic obstacle on the NDVI frame (ADR-003/009)
                             │            │
ArduPilot SITL  ◄─AP_DDS──  ROS 2 avoidance node
 (real firmware,             │      ├─ policy: dodge? where? (3D-vetted against the tree geofence)
  software-in-the-loop)      │      └─ executor: AUTO→GUIDED, resume, book coverage debt
                             │
                             └──►  recorded clip (frames + sim-clock-stamped poses)
                                        └──►  offline stitch (ADR-010) ──►  NDVI heatmap on the
                                              SAME 2.5 m cell grid as the coverage ledger
                                              ──►  dashboard (not started)
```

The coverage mission (boustrophedon, i.e. lawnmower lanes) flies over MAVLink; the reactive loop
commands ArduPilot over the AP_DDS `/ap/*` bridge (ADR-005/006). Trees are *known* static obstacles
from a pre-flight boundary survey — a real ag assumption — which is what isolates the genuinely hard
problem: the obstacle nobody surveyed.

## Where to go next

| If you want to… | Go to |
|---|---|
| **Try it in a few minutes** — Python only, no Docker | [`SETUP.md`](SETUP.md) — the test suite runs on the host and is the same check CI runs; the offline stitch is host-only |
| **Run the full sim** — one command that flies a mission and proves itself | [`SETUP.md`](SETUP.md), then [`docs/runbooks/FULL_PIPELINE_DEMO.md`](docs/runbooks/FULL_PIPELINE_DEMO.md) |
| **See the flight that's next** | [`docs/runbooks/AVOIDANCE_REAL_DETECTION.md`](docs/runbooks/AVOIDANCE_REAL_DETECTION.md) |
| **Understand how it works** | [`docs/SPEC.md`](docs/SPEC.md) |
| **Know why each choice was made** (and what lost) | [`docs/DECISIONS.md`](docs/DECISIONS.md) — the ADR log, corrections landing as dated amendments |
| **See exactly where the project stands** | [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| **Browse everything** | [`docs/README.md`](docs/README.md) |

## Repo layout

```
src/        Python planning core: coverage, policy, executor, NDVI fusion + detector
sim/        Gazebo farm world, sensor models, Docker image
config/     field polygon, missions, bird trajectories, camera + DDS settings
scripts/    bringup, the fly_pipeline launcher, stitching, and the evidence gates
eval/       evaluation harness, metrics, and committed flight/clip evidence
tests/      877 regression + safety tests (host-side; no Docker needed)
docs/       SPEC, ROADMAP, DECISIONS, BUILD_LOG, runbooks, archive
```

**A note on names:** the project was renamed from its working title *FieldGuard* (ADR-011), but code
identifiers deliberately keep the old name — `fieldguard_planning`, the `/fg/*` topics, the
`fieldguard-sim` container. That topic contract is live-verified, and renaming verified interfaces
for cosmetics re-opens confirmed state for zero functional gain. If you see `fg_`, you're in the
right place.

**How this repo was built:** by a Claude Code *tiger team* — eight specialized subagents (product,
tech-lead, perception/ML, sim, flight software, devops, QA/safety, GTM), each owning its own gates.
See [`TIGER_TEAM_GUIDE.md`](TIGER_TEAM_GUIDE.md).
