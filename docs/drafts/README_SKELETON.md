# DRAFT — README skeleton for user review (2026-08-26, revision 2)

**Status: DRAFT. Nothing here has been applied to `README.md`.** This is a section-by-section plan
plus two voice samples. Written for the audience the user chose: **robotics / autonomy hiring
managers first**.

**Review state:**

* **§A (title, hook, headline bullets) — APPROVED AS-IS AND FROZEN** by the user, 2026-08-26.
  Project voice is deliberate: anyone landing on the repo should see what the product is before
  they see anything about the author. Do not re-voice §A.
* **§B (the measured-limits arc) — REVISED in this pass:** rewritten in **first person** ("this is
  my work, revised and worked on week after week"), plus a readability sweep so a non-specialist
  can follow exactly what happened without thinning out the technical detail. Every number and
  source is unchanged.
* **Final voice split for the README: project voice for §A and all descriptive sections; first
  person for §B and (recommended, see C.11) "What I'd do next".**

**House rules observed in this draft** (from `.claude/agent-memory/gtm-narrative-lead/narrative-guardrails.md`):
paths are backticked, not linked, so this draft cannot trip `scripts/build_docs_site.py`'s link gate
while it lives in `docs/drafts/`; no `---` rules (heading-drift trap); every rate carries its
denominator; "small dynamic intruder, exercised on scripted birds" instead of a bird-avoidance
product claim; no startup narrative.

## 0. Reading order for the reviewer

* §A below — the opening 90 seconds. **Frozen; shown for reference only.**
* §B below — the 2026-08-25 / 2026-08-26 measured-limits arc. **This is the section to react to.**
* §C — intent + metric sourcing + target length for every other section.
* §D — what could not be sourced.

## §A — FROZEN (approved 2026-08-26): the opening 90 seconds

### A.1 Title line

```markdown
# SwathKeeper

**An autonomous ag-survey drone that reacts to obstacles its mission plan never knew about — and
proves the survey is still complete afterwards. Built entirely in simulation; every number on this
page comes from a gate that can fail, and one of them is failing right now, on purpose.**
```

### A.2 Hook paragraph (one paragraph, ~110 words)

```markdown
Commercial ag-drone platforms (DJI, DroneDeploy, Sentera, Trimble) fly **pre-surveyed static
missions**: the route is planned before takeoff and flown as planned. SwathKeeper adds the part
they leave out. When a small dynamic intruder enters the flight path mid-mission — exercised here
on scripted birds — the drone detects it on its own camera, takes authority from the autopilot,
dodges, resumes the lane, and **books every grid cell the dodge disturbed as coverage debt**, so a
silently skipped swath is a test failure rather than a rounding error. Crop-health mapping falls
out of the same flight and the same camera. It runs on ArduPilot + Gazebo + ROS 2, in simulation,
which is what makes the numbers below re-runnable by anyone.
```

### A.3 Headline bullets (6)

```markdown
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
```

## §B — REVISED: the measured-limits arc, first person

Proposed placement: immediately after the results table. **Target 560–620 words** — up from the
450–500 of revision 1, because the plain-language explanations cost words. It is the longest
section in the README on purpose. If it has to come down, cut the tree-clearance sentence in
paragraph 2 and the six-false-PASS clause in paragraph 5 first; both are recoverable from the ADR
log and neither carries the arc.

```markdown
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
it covers only about **4 %** of the volume the avoidance rules treat as dangerous. The detector
converted every chance it got — two boxes on the two frames where the bird was inside the image —
and my scoring harness still refused to grade the result, because 2 frames and 1 of 3 birds is not
evidence. A green 99.92 % detection rate sat on top of a flight that flew through a bird.
**Checks that measure values cannot see geometry.**

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
```

### Reviewer notes on §B

* **The lean-in line.** I went with *"The number was the easy part. What caused it was not what I
  expected."* It promises a surprise without naming the reader's job. Alternates, if you want a
  different register: *"The failure is the headline. What it taught is the story."* (your candidate,
  more declarative) / *"A breach is a number. The cause took a session to find."* (drier) /
  *"Then the question worth more than the number: why."* (closest to your first candidate).
* **Jargon audit — what changed and why.** "latched a divert" → the sequence is spelled out in
  paragraph 2 with *latches* introduced as the technical term for a plain-language behaviour it has
  already described. "Swept clearance" → "keeping the whole swept path clear of the nearest tree."
  "AUTO→GUIDED" → "takes control of the vehicle away from the survey mission… hands control back"
  (the mode names now live only in §A's bullet and the architecture diagram, where they belong).
  "Gated number / freeze debit" → "the number it actually judges" and "charges that blind spot as
  distance the bird could have covered." "Policy lead" → "by the time my software had something it
  could act on." "Exit 1" → "exits with a failure." "Tick" is gone
  entirely. "Point-mass model" → "a simple physics model of the aircraft… held to the same
  acceleration and jerk limits the real autopilot enforces." "Plant models" → "three different
  assumptions about how hard the aircraft can actually accelerate."
* **One fact moved earlier, and it didn't get softened:** the 4.03 m of vertical separation now appears *at* the
  6.7 mm number instead of two paragraphs later. Revision 1 buried it, and "passed 6.7 mm from the
  bird" alone reads as a 3-D near-miss. It was a horizontal overflight inside the rule's vertical
  band; both halves are now stated in the same sentence. Do not split them again.
* Every honesty constraint from revision 1 survives: "four dodges were accepted," never "avoided";
  the ledger and the breach are explicitly the *same* flight; 4 % is the measured fraction at this
  encounter's depth, not a sensor spec; no claim anywhere that avoidance is verified on the real
  render.

**Sources for every number in §B** (re-verify each before publishing):

| Number | Where it is proved |
|---|---|
| 0.0067 m horizontal / 4.03 m vertical / ±6 m band / −1.1210 m / 1.1277 m penalty / INVALID | `eval/results/live_flight_log_20260825T210402Z.SAFETY_FINDING.md`; `docs/DECISIONS.md` ADR-013 am. 18 |
| 1301/1302 frames vs a 0.90 floor | same marker, "What already passed on this same take" |
| 4 dodges, swept clearances 1.393/1.756/1.340/1.857 m, 1.0 m margin, 8 rejections | same marker; ADR-013 am. 18 |
| 720 covered / 0 debt | same marker |
| runbook §7 pre-registration quote (verbatim) | `docs/runbooks/AVOIDANCE_REAL_DETECTION.md` §7 (quoted in the marker) |
| six false-pass findings, incl. the frozen clock reporting 0.0000 m as 3.5000 m | `docs/DECISIONS.md` ADR-013 am. 15 |
| two-half acknowledgement | ADR-013 am. 17; runbook §6a |
| 0.175 s / 0.000 s lead; ~4 % of the threat volume; 2 boxes on 2 frames | marker; `docs/BUILD_LOG.md` 2026-08-25 |
| harness refused to grade it (EVIDENCE INSUFFICIENT) | `docs/DECISIONS.md` ADR-003 am. 9 |
| 81 combinations, no safe speed, 0.4132 s, 1.25 s, 2.480 m, 17.752–38.748 m | `eval/results/replay_point_mass_20260826T160218Z.json` → `verdict.q3`; ADR-017 am. 1 |
| forward sensor promoted to scope; §0b refuses every flown speed | ADR-017 am. 1; ADR-016 am. 1; `docs/ROADMAP.md` Next-up 1 |

## §C — Section-by-section skeleton (intent, sources, length)

### C.1 Title + hook — FROZEN in §A

*Intent:* in ten seconds, the reader knows what it is, what's different, and that the numbers are
gated. **Project voice. Target: title + 1 paragraph, ≤120 words.**

### C.2 Hero visual + one-click demo

*Intent:* the only image above the fold. It must be a *result*, not a screenshot of software
running. Directly beneath it: two links, **Dashboard (live, GitHub Pages)** and **Demo video
(2–3 min)**, so a hiring manager who reads nothing else still sees the thing move.

*Artifact recommendation (decision for the user):* switch the hero image from the current
`real_flight_20260823T073644Z` heatmap to
`eval/results/clips/real_flight_20260825T205705Z/heatmap/heatmap.png` — it is the better map
(18/18 imaged, 11/18 canopy-grade, +0.5562 vs 9/18, +0.5402) **and** it is the same flight as the
avoidance story, so the whole README becomes one flight told honestly instead of two clips stitched
for convenience.

*Caption must carry:* 720/720 cells on a 2.5 m grid from **649 painting frames of 671 airborne**
(never 3310 — 2639 are post-landing parked frames), 18/18 trees imaged, 11 canopy-grade, median
lift +0.5562, all 11 positive cells <2.0 m from a tree centre, gate PASS. NDVI expanded on first
use. **Alt text is a claim too** — describe only what the image shows.

*Optional second image, lower on the page (beside §B or §C.5):* the same-flight detection overlay
`eval/results/adr003_20260825/overlays/gtdet_a_ndvi_direct_ndvi_frame_000964.png` — committed, and
it shows the detector's box on the intruder. **Must be a `gtdet_*` frame; see §D.3 for why a
ground-truth-only still of frame 965 would misrepresent the detector.** Both images are tracked in
git; §D.4 lists the local-only assets the README may never link.

**Project voice. Target: 1 image + 3-line caption + 2 links. ≤90 words.**

### C.3 Headline bullets — FROZEN in §A

*Intent:* the 90-second skim in full. Six bullets, each ending in a number with a denominator.
**Target: 6 bullets, ≤45 words each.**

### C.4 Architecture at a glance

*Intent:* show that the differentiator is a **loop**, not a feature list — and where the seam is.
Keep the existing ASCII diagram (it works), but retitle the avoidance branch so the four verbs are
unmissable: **detect → avoid → replan → requeue**. A paragraph underneath explains the operator
assumption: trees are *known* obstacles from a pre-flight boundary survey (a real ag practice),
which is exactly what isolates the hard problem — the obstacle nobody surveyed. One sentence names
the extractable seams (`detection_source`, `VehicleCommandSink`) because that is what an autonomy
lead looks for. This is where `AUTO`/`GUIDED` get introduced by name, since §B no longer uses them.

*Cites:* no metrics; ADR-001, ADR-005/006, ADR-009, ADR-010 by number only.
**Project voice. Target: diagram + 2 short paragraphs, ≤160 words.**

### C.5 Results, quantified

*Intent:* one table, every row `measurement | number with denominator | file that proves it`. This
is the section a skimmer screenshots.

Rows, with sources:

| Row | Number | Source to cite |
|---|---|---|
| Coverage integrity, live flight | 720 covered / 0 debt; 116 at-risk cells recovered across 4 diverts; 1858 path points | `eval/results/live_flight_log_20260825T210402Z.json` + its `SAFETY_FINDING.md` |
| Detector rate, first in-air measurement | 1301 / 1302 frames = 99.92 % vs a 0.90 floor | same log; ADR-013 am. 18 |
| Bird clearance on that flight | **0.0067 m horizontal at 4.03 m vertical, vs a 3.00 m bar — INVALID**, reported as the system working | `live_flight_log_20260825T210402Z.SAFETY_FINDING.md` |
| Detection quality, real render (ADR-003 criterion 3) | per-track FNR **0.000**, 3/3 intruders, 20 obstacle-visible frames; precision 0.708 / recall 0.850 (TP 17 / FP 7 / FN 3) | `eval/results/adr003_20260823/spike_scores.json` |
| Detector vs the working RGB comparison arm (criterion 2, closed 2026-08-26) | safety numbers **identical**; precision 0.708 → 0.227 (3.1×) on the adopted clip, 1.000 → 0.037 (27×) in the air; **gap +0.000 → ADOPT** | ADR-003 am. 10; `eval/rgb_pixel_study.py` artifacts |
| Map completeness | 720 / 720 cells, 2.5 m grid, 649 painting frames | `eval/results/clips/real_flight_20260825T205705Z/heatmap/heatmap.json` |
| Tree localization | 18/18 imaged, 11/18 canopy-grade, median lift +0.5562, all 11 positive cells <2.0 m | `scripts/check_tree_positions.py` on that clip |
| Recording cadence | 5.0 Hz flat, 100 % delivery both bands (was 0.41 Hz — Fast DDS shared-memory segment was the root cause) | that clip's `meta.json` |
| Live↔offline equivalence | flight-logged obstacle positions reproduced to **1 µm** across SciPy 1.8.0 (air) / 1.13.1 (host), all 1301 in-window frames | ADR-009 am. 2 |
| Monocular range estimator vs ground truth at CPA | agrees to **3.3 mm** (0.0035 m vs 0.0067 m) — and is still refused as a gate, on purpose | ADR-013 am. 19 |
| Automated tests | **TODO — needs one re-measured number**, see §D | `tests/README.md` (the declared single home) |

*Below the table, two caveats stated in the repo's own words:* the −0.61 detection threshold is
**PROVISIONAL** (narrowed 2026-08-26 across a 2.3× depth span, open beyond ~11 m), and there is
**no quotable second-sensor delta** — the RGB arm was measured to share the primary's band bit-for-bit,
so it never was a second sensor.

**Project voice. Target: 1 table (≤11 rows) + 2 sentences. ≤200 words of prose.**

### C.6 The flight that failed, and what it bought — DRAFTED in §B

*Intent:* convert the project's worst-looking fact into its strongest signal, in the author's own
voice. **First person. Target 560–620 words.** Read it aloud before shipping.

### C.7 How this repo proves things (the evidence culture)

*Intent:* generalise §B from one incident into a *practice*, in four bullets a reader can quote back.
No new numbers except the ones already earned.

Bullets, each one sentence + its receipt:

* **Pre-registration.** The failure condition is written in the runbook before the flight, so the
  result cannot be reinterpreted afterwards (`docs/runbooks/AVOIDANCE_REAL_DETECTION.md` §7).
* **Commanded is never recorded as flown.** A ledger bug that recorded dodge setpoints as flown
  understated coverage debt by up to **32 cells per scenario**; fixed and regression-pinned the same
  day (ADR-013; the 2026-08-18 audit).
* **Gates have to be able to fail, and they have to catch themselves.** `eval/score.py`'s
  zero-denominator ADOPT bug; `check_tree_positions.py`'s "PASS (vacuous)"; a CI evidence step that
  printed SKIP…PASS having validated nothing; a legacy check that measured path *corners* instead of
  the path, under which the one fixture that "passed" was a direct hit (7.0000 m → 0.0000 m, fixed
  test-first).
* **Value checks cannot see geometry.** Every value check in the project passed while the camera
  faced the horizon upside down (ADR-007 am. 5, fixed and now gated at 2.2 px) — and the same class
  recurred on 2026-08-25 with a green 99.92 % detect rate on a flight that flew through a bird.
  Two instances make it a pattern, not an anecdote.

Close with one line routing to `docs/DECISIONS.md`: ~19 ADRs, corrections landing as dated
**amendments** rather than edits, because the log is append-only.

**Project voice (the practice, not the anecdote). Target: 4 bullets + 1 routing line. ≤220 words.**

### C.8 Honest limitations

*Intent:* pre-empt every objection a sharp interviewer would raise, in roughly the order a reader
will think of them, and turn two of them into features. A limitations section a hiring manager believes is
worth more than a claim they have to check.

Content, in order:

1. **Sim-only, and that is the design choice.** ArduPilot SITL is the real firmware; Gazebo Harmonic
   is the real render; the toolchain is version- and SHA-pinned (ADR-004). What sim buys: a
   re-flyable flight behind every number. What it costs is named, not hidden — the **transfer-gap
   register** in the replay artifact lists five gaps (attitude/motor lag, EKF lag, wind/drag,
   mode-switch latency, the plant's own accel limit), four of them flagged *optimistic for the model*.
2. **One authored world.** All perception results are properties of one hand-built farm world and its
   lighting; the RGB study says so explicitly. The named carry-forward hazard: v1 flies NDVI-only, so
   the live failure mode is an **invisible brown object** that is not in the static obstacle map.
3. **The plant model is unvalidated against SITL.** The point-mass replay's effective lateral accel
   (1.05 m/s²) is a one-parameter fit from **one admissible axis of one flight** — labelled ESTIMATED,
   not measured, in the artifact itself.
4. **`main`'s CI is red, on purpose.** The evidence gate fails on the committed breach and will stay
   failing until a clean re-fly. Making it green would require either deleting the evidence or
   pinning the breach as acknowledged — both refused. **A green badge over a hidden bird strike is
   the thing this repo is arguing against.**
5. **Known measurement debt, booked not buried.** The committed lane pitch (15 m) exceeds the true
   camera swath derived from `camera_info` (13.772 m), leaving a **1.228 m unimaged strip per lane
   pair**; 720/720 survives only by cell-centre quantization with 0.636 m of margin, and re-planning
   the lanes belongs to the re-fly (ADR-016 am. 1).

**Target: 5 short items. ≤260 words.** Do not soften item 4 — it is a feature.

### C.9 Run it

*Intent:* route, don't duplicate. Three tiers, each a single line: (a) host-only Python, no Docker —
the test suite and the offline stitch; (b) the full sim in one command via `scripts/fly_pipeline.sh`;
(c) reproduce the safety verdicts on committed evidence in one command. Route to a **file**
(`SETUP.md`, `docs/runbooks/FULL_PIPELINE_DEMO.md`), never to a section inside someone else's file.

*One command worth inlining* (it is the whole thesis in 80 characters):

```bash
python3 scripts/check_live_flight_log.py eval/results/live_flight_log_*.json
```

plus the honest caveat the 2026-08-25 marker already records: the shipped invocation prints
INVALID for an ambiguous truth track and does **not** print the 0.0067 m CPA — the marker file
explains how to reproduce it. Say that; do not let a reader discover it.

**Target: 3 lines + 1 code block. ≤110 words.**

### C.10 Where to go next (links plan)

| Destination | Why a hiring manager clicks it |
|---|---|
| **Dashboard** (GitHub Pages, one click, nothing to install) | flight replay, avoidance event log, NDVI overlay — the three ADR-018 views |
| **Demo video** (2–3 min, narrated) | the loop, the map, the breach, the redirect |
| `docs/DECISIONS.md` | the ADR log — the single best interview artifact in the repo |
| `docs/ROADMAP.md` | exactly where it stands, including what is not done |
| `eval/results/…SAFETY_FINDING.md` (the 2026-08-25 marker) | the failure, written up beside its evidence |
| `docs/runbooks/AVOIDANCE_REAL_DETECTION.md` | the pre-registration, in situ |
| `SETUP.md` / `docs/SPEC.md` / `TIGER_TEAM_GUIDE.md` | run it / how it works / how it was built |

**Target: 1 table, ≤7 rows.**

### C.11 What I'd do next

*Intent:* prove the roadmap is real and ordered by measurement, not by appetite. Must match
`docs/ROADMAP.md` Next-up exactly.

**Voice recommendation — YES, first person, matching §B.** The heading already says "What *I'd* do
next," it is the only other section making a personal commitment, and putting it in project voice
immediately after a first-person §B would read as two authors. Flagging it as a call for the user:
if you'd rather keep first person strictly to §B, rename this section "Next" and write it in project
voice — but don't leave the current heading with impersonal prose under it.

Three items, one line each:

1. **A second, forward-facing detection sensor** beside the nadir survey camera — promoted from
   growth path to scope by the no-safe-speed measurement, and specced against the replay's own
   number (17.8–38.7 m of forward horizon at the flown speed; a forward tilt of the single camera
   is rejected, because it would trade a validated survey instrument for warning time).
2. **One clean re-fly** behind that sensor, gated on **warning time as well as clearance** — a
   passing clearance number bought on 0.175 s of warning is bought by luck.
3. **Extract the core.** Policy / executor / ledger are verified stdlib-pure with real seams; the
   extraction is priced at roughly five focused sessions and deliberately starts **only after** a
   clean pass, because publishing a component whose headline safety claim is a documented failure
   inverts the story.

**Target: 3 lines. ≤120 words.**

### C.12 Footer: names, and how it was built

*Intent:* two short paragraphs, same substance as the current README — the
SwathKeeper/`fieldguard` code-identifier split (ADR-011, one honest line: renaming live-verified
interfaces for cosmetics re-opens confirmed state for zero gain), and the tiger-team note.

**Project voice. Target: ≤80 words.**

## §D — Facts I could not source, or that need a decision before publishing

1. **Test-suite count is contradictory in the tree.** `tests/README.md` (the declared single home)
   says **877 passed / 2 skipped / 0 xfail** and 822 in `tests/fieldguard_planning`;
   `docs/BUILD_LOG.md` 2026-08-26 says suites went **888 → 1028 + 902** with one red by design.
   The README must quote ONE re-measured number from the named home. Left as **TODO** in §C.5.
2. **Dashboard URL and screenshot do not exist yet** — the dashboard is being built concurrently
   (ADR-018) and there is no `dashboard/` path in the tree as of this draft. Every dashboard link
   above is a placeholder.
3. **RESOLVED this revision — same-flight detection overlays now exist AND are committed.**
   `eval/results/adr003_20260825/overlays/` holds 8 PNGs (`gt_ndvi`/`gt_rgb` for frames 000964 and
   000965, plus the `gtdet_a_ndvi_direct_{ndvi,rgb}` pairs); `.gitignore` now allowlists them, so a
   fresh clone gets them. Those two frames are *the* two frames in the whole flight where the bird
   was inside the image — the same two the detector boxed. **This is the second README image, and
   it must be a `gtdet_*` still:** on frame 965 the ground-truth box sits ~15 px off the rendered
   bird (applied-pose render lag, IoU 0.511) while the detector's box is tight, so a GT-only crop
   would read as a miss. Frame 964 (IoU 0.826) is the safe single frame. Suggested caption — and
   it's the honest one: *"the only two frames of the flight with the intruder inside the image —
   the detector boxed both, and the harness still refused to call two frames evidence."*
4. **Embed rule, learned the hard way this session: only reference artifacts a fresh clone will
   have.** Two assets that exist on the build machine are **not** in git — the 2026-08-23 overlay
   PNGs (`adr003_*/overlays/` is gitignored) and every clip's `frames/rgb/*.png` (only `meta.json`,
   `poses.jsonl` and `heatmap/` are tracked). They are fine as *video source footage*, because the
   rendered video is the deliverable, but the README must not link or embed them. The hero heatmap
   and the 8 allowlisted overlays are safe.
5. **No GIF exists.** The "one-GIF demo" idea from the original GTM mandate has no source footage
   without either a dashboard screen capture or a Gazebo session. Recommendation: the hero stays a
   still heatmap and the motion lives in the dashboard + video links.
6. **Repo stars / visibility claims** (Ruling 001 cites "0 stars, no description after 30 days") are
   council-record facts, not repo artifacts — do not put them in the README.
</content>
</invoke>
