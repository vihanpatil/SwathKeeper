# SwathKeeper — Build Log

Chronological record of what shipped, what broke, and what each phase taught. Newest first.
This is the *narrative* companion to `docs/DECISIONS.md` (the why) and `docs/ROADMAP.md` (the now).
Full session records live in `docs/archive/` and the runbooks in `docs/runbooks/`.

---

## 2026-08-26 — the replay answers what the flight could not, and the answer fires the tripwire everyone had pre-signed

**Ruling 001's item 1 executed offline, in one session, through six adversarial QA rounds.** The
~50-line point-mass replay the red team asked for became `eval/point_mass.py` + `replay_point_mass.py`
(deliberately not a gate), a jerk/accel/velocity-limited reproduction of AC_PosControl's input
shaping with every constant cited to ArduPilot source at the pinned SHA — and it took the "84
maneuvers, 0.5–4 % compliance" headline apart into three different answers:

- **2026-08-23: the command path worked.** The tiny displacement is what ArduCopter *defaults*
  predict for a short window — fitted effective lateral accel **1.05 m/s²** against the 2.5
  default (one admissible axis, ESTIMATED; the attitude/motor lag the point mass omits is the
  transfer-gap register's first number).
- **2026-08-18: the command path did nothing.** Commanded 10 m south for 61 ticks; flew 14.5 m
  *north*. No plant fits at any admissible tick period. Cause not isolatable offline —
  mode-switch-never-happened, frame error, and plant are all consistent — so the next schema-2
  flight records the achieved flight mode per tick.
- **2026-08-25: the flagship window cannot tell.** 0.434 s of GUIDED separates the hypotheses by
  5 mm — 0.56 telemetry quanta. Reported as EVIDENCE INSUFFICIENT, which the tool's first draft
  printed as a confident positive until QA caught it (the G55 family, again).

**The counterfactual sweep retired R4-as-candidate-ordering before a line of it was built:** the
0° reversal never resolves at any lead × plant; the earliest *physically* resolving lead on the
flown encounter is **1.25 s** against the 0.175 s the sensor gave (2.00 s through the policy's
XY-only tree vet — a third confound, now separated and named for R4's sizing).

**And the tripwire fired: `speed_at_which_nadir_becomes_safe = None`.** Eighty-one cells, three
plants up to the physical ANGLE_MAX ceiling, and not one clears 3.00 m — because bird_0 closes at
its own 6.0 m/s, capping warning at 0.41 s *from a hover*. Nadir has 2.48 m of forward sensing and
needs 17.8–38.8. QA hand-reproduced every number, attacked it with altitude, axis choice and a 45°
tilt-limit hypothesis, and cleared it for quoting; it stayed bit-identical through every later fix
round. Per ADR-017's pre-written contingency, **the second forward-facing sensor is promoted from
growth path to scope, the tilt stays rejected**, and the sequencing (Week 7 first vs sensor first)
escalates to the user — Ruling 001's "one re-fly then Week 7" is voided by measurement, since no
nadir re-fly can pass the bar it would be flown against.

**The same session landed the rest of the ratified bundle, each piece QA'd red-first:**
`MIS_RESTART 0` pinned into the param file every DDS bringup loads; `predict_bird_visibility.py
--speed` REQUIRED (the §0b gate now honestly refuses every speed the vehicle actually flies on
this geometry — and its "faster is conservative" justification measured *false*: visibility is
non-monotone in speed via lane-arrival aliasing); threat-clear hysteresis with a bounded,
evidence-sized GUIDED ceiling after QA proved the unbounded version could silently stall the
mission forever on a flickering detection; the swath half-width derived from `camera_info`
(6.886 m, not 7.5 — the committed missions knowingly carry a 1.228 m inter-lane strip until the
re-plan). And the criterion-2 study closed the comparison arm with the session's cleanest
measurement: **the RGB R channel is the NDVI Red band bit-for-bit**, so the "second sensor" never
was one — while at its honest ceiling RGB matches the adopted detector's safety numbers exactly
and loses 3.1×/27× on precision to a trunk-vs-bird material collision only the thermal band
separates. ADOPT re-confirmed against a *working* arm, gap +0.000. **RETIRE-ARM.**

**Two latent defects fell out of the QA rounds, both in things that were already "done":** the
legacy CPA path measured *vertices*, not the path — `cov_bird_at_turnaround`, the one scenario
fixture that passed the CPA bar, was a direct hit reading as 7.00 m (fixed red-first; historical
breaches deepen 0.0597→0.0393 / 0.0518→0.0391 with verdicts byte-identical) — and with segment
geometry the demoted monocular estimator turns out to agree with ground truth at CPA to **3.3 mm**;
the 20 cm "error" that helped justify its demotion was the gate's geometry, not the estimator.

Suites 888 → **1028 + 902** (one red: the pre-registered CI evidence gate, standing until the
clean re-fly). Session direction record: Ruling 001 RATIFIED (ADR-016), nadir DECIDED (ADR-017),
tripwire FIRED (ADR-017 am. 1). The full anatomy is in ADR-016 am. 1–2, ADR-013 am. 19, and the
ADR-003 closure.

## 2026-08-25 — the loop closes on a bird the drone found itself, and the gate written the day before fails the take

**THE FLIGHT HAPPENED.** For the first time in this project, the avoidance loop ran on a bird that
nothing injected: an NDVI frame off the real render, the ADR-003-adopted blob detector on the node's
`detection_source`, a range from the apparent-size ray, a latched setpoint, GUIDED. Four maneuvers,
one encounter, zero stale detections dropped, zero clock-domain violations, the coverage ledger
closing **720 covered / 0 debt**.

**And the take is INVALID.** `gt_cpa_m` **0.0067 m** horizontal to `bird_0` at tick 991
(`t_sim` 202.775 s) against a 3.00 m bar — drone at z 15.03, bird at 11.00, 4.03 m of vertical
separation, inside the ±6 m threat band. A 2-tick / 0.161 s clock stall prices a **1.1277 m** freeze
debit on top, so the gated number reads **−1.1210 m**. Exit 1. That is the pre-registered outcome of
the runbook's §7, written down before the flight precisely so it could not be reinterpreted after it,
and the record follows §6a to the letter: the breach gets its marker file and deliberately **no** pin
in `ACKNOWLEDGED_BREACH_STEMS`, so the take stands INVALID until it is re-flown behind R4 (escape
geometry, still open).

The thing worth saying out loud: **the gate that failed this flight did not exist the day before it.**
It was built on 2026-08-24, torn apart adversarially five times in that same session, and the process
that built it wrote the prediction that it would fail. A safety gate you only trust when it is green is not
a safety gate. This one failed its own project's flagship flight on day one and cost the take — which
is the entire point of having built it.

### What the flight did prove

- **The seam is real and it is exact.** Re-scoring the clip offline and pushing the boxes back through
  `src/fieldguard_planning/ndvi_detect.box_to_detection` reproduces the flight log's own logged
  `Detection.position_enu` to **1 micrometre**, agreeing on all 1301 in-window frames — across
  jammy's scipy 1.8.0 in the air versus 1.13.1 on the host. That closes ADR-013's "transfer verified
  on ONE scipy version" caveat with a third version measured in flight.
- **Detector rate, first in-air measurement: 1301 / 1302 = 99.9232 %** against the 0.90 floor. The
  single loss is `dropped_no_intrinsics=1`, the startup-ordering transient the constant's comment
  predicted. Floor deliberately **not** narrowed at n=1.
- **R2 flew and was not vacuous.** Four accepted maneuvers with swept tree clearances
  1.393 / 1.756 / 1.340 / 1.857 m against the new 1.0 m margin, and 8 candidate rejections behind
  them. Flown path: **0 `is_safe_3d` violations over 1858 points**. R3 missed activating by **15 mm** —
  the 18.90 m reversal carried `trigger_range` 1.015 m against a `degenerate_range_m` of 1.0.
- **The NDVI half is the best on record.** 3310 frames stitched, 649 painting at **5.0 Hz flat** →
  **720 / 720 cells imaged**, 0 unimaged. `check_tree_positions.py`: **18/18 imaged, 11/18
  canopy-grade, median lift +0.5562**, every one of the 11 positive cells within 2.0 m of a tree
  centre, PASS. The ADR-003-adopted 2026-08-23 clip re-measured the same day for a like-for-like reads
  18/18, **9/18**, **+0.5402** — this take beats it on both. The throughput fix held for a third
  independent flight: 100 % delivery on both bands, the 8 MiB DDS profile reaching all four segments.
- **The threshold's false-positive study is half done.** Across all 3310 frames — 1.02 gigapixels —
  the darkest non-bird pixel is **−0.4406 on every single frame**, and **zero** pixels anywhere fall
  below −0.50. The warmest bird pixel is −0.6697. So −0.61 sits in a 0.229-wide empty band and any
  value inside it is bit-identical on this clip. The background half is characterised; the **range**
  half is not (the threshold has only ever been exercised at ~4 m depth, on a 47 px bird), so −0.61
  stays **PROVISIONAL**.

### The breach is not the control law's alone, and that is the expensive finding

Reconstructing the encounter tick by tick says the loop never had a chance to work. `bird_0` patrols
lane x=15 at z=11; the drone flies the same lane southbound at 8.4 m/s, closing at **14.4 m/s**. The
**first detection arrived on the CPA tick itself**: sensor lead time **0.175 s**, policy lead time
**0.000 s**. Latch at 991, re-latch at 992 with the away-vector sign-flipped in 0.123 s as the drone
passed over the bird, recommand at 993, re-latch at 994, resume at 995 on `threat_cleared` — because
one empty frame replaced the latest detection, not because anything went stale. GUIDED authority
window: **0.434 s**. Lateral displacement achieved against a 10 m command: **0.018 m**.
**The avoidance loop moved the vehicle 1.8 cm.**

The detector is not implicated. Ground truth says `bird_0` was truly inside the threat cylinder on 16
ticks, 7 of which the camera captured a frame for — and **2** of those had the bird inside the image.
The detector produced a box on exactly those 2: TP 2 / FP 0 / FN 0, precision 1.000, recall 1.000,
per-bird-track FNR 0.000. It converted every opportunity it was given. `eval/score.py` still returned
**EVIDENCE INSUFFICIENT** and it was right to: a denominator of 2 frames and 1 of 3 birds is not
evidence, and the guard that refuses to score it is the same evidence floor that caught the
zero-denominator ADOPT bug. ADR-003's ADOPT is therefore **neither challenged nor confirmed** by this
flight.

The cause is footprint geometry. The mount is **nadir**; at the encounter's 4.03 m depth the camera
images about **4.0 %** of the threat cylinder's cross-section, and its half-width reaches the 12 m
policy radius only at 19.5 m of depth — far outside the ±6 m band the policy cares about. The five
missed in-cylinder frames were 1.4–7.8 m outside the image edge. A `--backtest` run of
`scripts/predict_bird_visibility.py` reproduces the whole thing independently: 2 / 0 / 0 in view.
**No escape geometry can buy back warning time the sensor never had** — so R4 is now ranked, exactly
as the pre-registration said it would be, but it must be priced against 0.175 s of lead and 0.4 s of
dwell rather than against a 12 m cylinder, and it cannot be the only fix.

**And the abort gate would have caught it.** `predict_bird_visibility.py` PASSes at its
`DEFAULT_SPEED_MPS = 3.0` default and **FAILs at `--speed 8` and `--speed 9.4`**; the encounter was
flown at ~9.4 m/s. The constant's provenance string cites a runbook that contains no speed figure at
all. A 3 m/s default booked a session that could only ever produce a 2-frame encounter. That default,
not the detector and not the threshold, is the cheapest thing standing between here and a re-fly.

### Again: a gate that measures values cannot see geometry

A green **99.92 %** detect rate sat on top of a flight where the detector saw a bird on 2 of 1301
frames. The camera was pointed correctly, the pixels were correct, every counter was in range, and
the vehicle still flew through a bird. This is the same failure class as ADR-007 amendment 5's
horizon-facing mount, which passed every value gate in the project while looking at the sky, and the
lesson has not changed: **each geometry assumption needs its own geometry gate**, and value gates must
never be read as covering one.

### The evidence nearly ate itself

Teardown step 2 was skipped, so `record_node` was **still writing frames 22 minutes after the flight
ended** — caught only because two `ls` calls a minute apart returned different counts. It was
recovered through the shipped teardown path rather than an offline rebuild (`ClipWriter` opens
`poses.jsonl` with `"w"`, so rebuilding would have truncated the evidence), and finalize printed a
genuine meta block: 3310 frames, 671 airborne, 5.0 Hz. Cost: **2639 post-landing parked frames**, 80 %
of the clip by count. They are harmless — all below the ground plane, all zero-update — but
`num_frames` 3310 is now 22 minutes of a parked drone. **Quote 671 airborne / 649 painting.** Nothing
in `status`, in the launcher, or in the gate noticed; the safety verdict scored complete without ever
needing the clip.

`drive_birds.py` was still appending to the take's only bird ground truth as well, growing
1348 → 2202 records during review. The breach itself is immutable (the log is append-only, tick 991
re-measures identically), but denominators around it moved, so some of the gate's printed counts
cannot be reproduced by re-running it. Freeze the driver before anything is re-scored.

Two smaller true things. The schema-1.1 clock anchor flew for the first time and the runbook's
"should sit near 0.039 s" was a **floor, not a constant** — measured median **0.0526 s** over 596
ticks, p95 0.105. And the two-half acknowledgement contract cannot currently run on this take at all:
CI invokes the gate without `--truth`, and committing this take's applied track makes two candidates
overlap, so the log goes INVALID for "ambiguous truth track" and **the CPA breach is never printed**.
The record shape is a decision owed before the marker is written.

---

## 2026-08-25 — the docs get a front door, and this log stops lying by omission

No code, no config, no flight state changed. A reader-first pass over the documentation: `README.md`
rewritten as the front door (one heatmap, the differentiator in a paragraph, a status table with the
open items visible, and every headline number naming the file that proves it), `docs/README.md`
rewritten as a routing map that says which of the three document *kinds* to trust, and two files that
had **stopped being runbooks** — a frozen gate record and a plan that was never a procedure — moved
into `docs/archive/` with banners. Stubs stay at their old paths, because `DECISIONS.md` is
append-only and a path an ADR once linked has to stay reachable forever.

Two things worth keeping from it. The open half of the archived sim-CI plan was **booked into the
ROADMAP cut log before the file moved** — archiving open work without recording the deferral is
exactly the failure that log exists to prevent. And this file had a quieter version of the same bug:
it promised the full narrative and stopped at 2026-08-21, three sessions early, while `ROADMAP.md`
and `DECISIONS.md` had moved on without it. The two entries below are that fix, written from the ADRs
rather than from memory.

---

## 2026-08-24 — the whole offline half of real-detection avoidance lands, and the gate that will judge it is torn apart five times

Four things shipped in one session, and not one of them is *done* by this project's own definition:
"landed offline" is a claim about the host suite, not about the vehicle. Every piece below waits on
the same single flight.

**The seam.** The ADOPTED detector moved verbatim into one home —
`src/fieldguard_planning/ndvi_detect.py`, with `eval/blob.py` deleted rather than shimmed — and was
wired onto the avoidance node's `detection_source` under ADR-009: stamped detections with a staleness
gate, bird range from the apparent-size ray, never the ground-plane projection that is fail-dangerous
at altitude. One clock end to end: absolute Gazebo sim seconds, a >0.5 s-future tripwire, and a
refuse-to-start if no `/clock` reading ever arrives. The claim that mattered most is that the move is
**provably neutral** — re-scoring the adopted clip through its new home reproduces
`detections_ndvi.json` bit-identically (1256 frames, 24 boxes) and the ADOPT verdict with identical
numbers. A rewrite wearing amendment 7's verdict would have cost a flight to re-earn it.

**R2 and R3, priced instead of guessed.** `lateral_tree_margin_m` 0.0 → 1.0 and a refusal to re-latch
on a degenerate range reading, swept over **11,856 degenerate cases**: HOLD rate 5.64 % → 15.66 %,
minimum accepted swept tree clearance 0.000 → **1.000 m**, sub-metre tail 28.1 % → **0 %** — and the
flown encounter still dodges 19/19. The cost is stated in the same breath as the benefit, because a
refusal is not a dodge: the executor now says **REFUSED — zero displacement, honours no clearance
bar**, and the HOLD it falls through to logs its own bird clearance so the gate can report that as
ungated context, never as a verdict. Escape geometry (R4) is deliberately not in this.

**The safety bar moves onto ground truth.** Closest approach is now measured against the birds'
applied-pose truth, read through the same functions ADR-003's labels use; the monocular
detection-CPA is demoted to a labelled estimator check and can never gate again. Both historical
breach logs still read ACKNOWLEDGED, byte-identically. And acknowledgement now costs **two halves** —
the marker file beside the log *and* the log's stem pinned in the gate's source, a reviewed diff —
precisely so the runbook's own remedy for a breach cannot double as a one-file way to turn a new bird
strike green.

**The runbook.** `docs/runbooks/AVOIDANCE_REAL_DETECTION.md`: seven panes plus the detector shell,
both preflights, evidence-first teardown, the exact scoring line, and a written pre-registration.

**Then the gate was read adversarially five times, and mostly lost.** Six findings in the first pass,
one of them critical: a 0.8 s frozen clock is 5.6 m of bird motion, and a true **0.0000 m** strike
was reported as a **3.5000 m PASS**. Seven more in the third round, the sharpest being that the
ground-truth number was a true lower bound on the *drone* axis and still a vertex **sample** on the
bird's — a bird driven through a hovering drone between two ticks scored 3.8067 m VALID and now
scores **0.0000 m BREACH**. Every finding was reproduced with a probe against the real code before it
was believed, and every fix pinned by a test **run against the pre-fix file and seen to fail**. Suite
**530 passed / 2 skipped / 2 xfailed → 877 / 2 / 0**: one xfail was promoted to a plain assertion
when R2 landed, the other honestly retired, because it asserted that a *frozen artifact* would one
day become safe and so could never activate.

**The offline dry run, which is the flight's comparison set and not its result:** 8 of 1256 frames
would have produced an in-cylinder threat — bookable, not a dodge storm — range error against truth
median **1.65 m** / max **3.67 m**, materially worse than the single case the adoption quoted, and
detector wall time p95 **4.8 ms** against a 200 ms tick, so perception will not block the executor.

**Pre-registered in writing, before the take:** R2 and R3 do not fix the escape geometry, so the
flight may honestly **FAIL its own gate**. If it breaches, the marker gets written and the pin does
**not** — the take stands at INVALID, exit 1. That is the correct record for a flight that breached
and can be re-flown, and it is the measurement that ranks escape geometry next.

---

## 2026-08-22/23 — three threads close in two days, and a gate written afterwards calls two green flights bird strikes

### The transport was the bottleneck all along (ADR-013 amendments 7-9)

Two rounds of counters before any lever: every lost frame got a name, and **three of four candidate
levers died to instrumentation instead of to flights**. Round 3 found the mechanism and source-verified
it in Fast DDS 2.6.11 — every large sample fragments at **65,384 B even over shared memory**, the
default shared-memory segment holds **8 fragment slots** against the 10 / 15 / 19 fragments an
NIR / RGB / NDVI sample needs, and on overflow the transport **silently discards and reports success**.
One 8 MiB segment later (`config/dds/fg_fastdds.xml` plus `--shm-size=1g` at container re-create),
delivery on both bands reads **100.0 %** and painting cadence goes **0.4767 Hz → 5.0 Hz**.

The flagship take that followed painted 624 frames at exactly **5.00 Hz** — all 623 inter-frame gaps
0.200 s — and imaged **720 of 720 cells: the first full-grid, correctly georeferenced map in the
project's history**, 18/18 trees imaged, 14 canopy-grade. It also reversed two of round 2's own
conclusions out loud: run-age decay never existed (it was segment exhaustion wearing a clock's
clothes), and the long mission out-yields the short one at **1.4× cells/min** because it spreads
frames over new ground.

### ADR-003 criterion 3: CLOSED — ADOPT NDVI-direct, on the real render (amendment 7)

The detection decision this project had deferred since the spec, closed with numbers on *measured*
labels: **per-bird-track FNR 0.000** against a ≤ 0.1 bar, **every bird detected before its closest
approach**, precision 0.708 / recall 0.850 (TP 17 / FP 7 / FN 3) over 20 visible bird-frames, 3/3
birds. The competing arm scored 0.000 across the board and that is **not** RGB's ceiling — its
birdness test is inverted on this world, documented and deliberately left untouched.

What makes it defensible is the order the blockers fell in, each measured closed before the next was
named: geometry (ADR-015), throughput (amendments 6-9), then ground truth — the render lagged the
labels by 0.12-0.81 s, invisible at 0.41 Hz and only measurable at 5, so the annotator had to replay
the driver's own step function instead of interpolating a continuous path, and the harness now
refuses to score an estimate. A classical blob detector is the adopted answer, and the synthetic
0.445 precision bar stands as the number any learned model must beat before it earns a place.

### The ledger closes 720 / 0 — and then QA reads the same flight (amendments 11-12)

The avoidance loop's first run on the current stack: 19 detections → 1 takeover (AUTO→GUIDED at
waypoint 6, trigger range 9.27 m) → **19/19 maneuvers vetted `accepted`, 0 rejected** → resume on
`threat_cleared`, ledger **covered 720 / debt 0**, the partition summing to exactly 720. The
2026-08-18 run had closed 513/207; this was the first full closure.

Then the adversarial pass measured the one number nobody had: **closest approach to the bird was
0.0518 m against the policy's own 3.00 m bar, with every gate green.** From the first accepted divert
the vehicle gained **45 mm** across-track in six ticks while closing 9.3 m along-track, still doing
6.57 m/s at closest approach — because candidate 0°, straight away, is a full reversal, the one
escape ownship momentum forbids in a head-on closure. Nothing in the pipeline computed closest
approach at all: "19/19 vetted" was a claim about *setpoints* that had been quietly reading as a
claim about *separation*.

That number became a gate the same day, and its first pass over committed evidence found the
2026-08-18 flight had breached too — **0.0597 m**, five days and one executor revision earlier,
against the same static bird. The second log is what proves the cause is the escape geometry rather
than the re-latch logic. Both are kept and marked ACKNOWLEDGED — recorded history, never a passing
flight — and the control-law fixes were held back for their own live gate instead of shipping on the
strength of a replay.

**The lesson, and it is the best interview answer this project has:** a loop can pass every gate it
owns and still be missing the gate that measures what it is for.

---

## 2026-08-21 (third entry) — a flight-free session: two gates, one geometry fix, and the number that says whether to book the next Docker session

Deliberately no container, no flight, no ROS. Everything below runs on the host in seconds, and the
point of the session was that the *previous* one — a full Docker session, a clean 454-frame flight —
produced **0 bird-visible frames** and nobody could have known beforehand. So: build the thing that
knows beforehand.

**`scripts/predict_bird_visibility.py`.** Mission × bird config × the same `ndvi_georef` projection
→ "will any bird be in frame, for how many frames", in under a second. It earns trust by
reproduction, not by inspection: replay the demo take's own poses and it returns that flight's
measured numbers exactly — **0 of 454**, closest approach **14.15 m**, nearest miss **341.2 px** —
and agrees with `label_from_sim.py` on all **1,362 frame×bird decisions**. Predicting the same
mission from *pure config* at the rate that take actually sampled (0.407 Hz) gives medians
**0 / 0 / 1**: the measured zero was the most likely outcome, not bad luck.

**What it found is that "the birds are too high" was two different problems.** bird_0 was
**STRUCTURAL** — patrolling x=20, a fixed 5.0 m off the nearest lane, **1.81 m outside the frame
edge at its best moment, at 0 of 55 driver-start offsets**. No cadence, speed or luck reaches it.
bird_1 and bird_2 were **TIMING** — they do cross the lanes, just rarely. That split matters because
the two need opposite fixes, and ADR-003 amendment 1 had read as though only "lower the birds" could
help. It also corrected that amendment's own arithmetic: the 4.31 m half-width it compared against is
the *along-track* axis; cross-track is **3.23 m**, so the miss was bigger than recorded, not smaller.

**ADR-015: the fix is a patrol line, not an altitude.** Lowering the birds was measured and refused —
at 2-3 m AGL every bird sits 12-13 m under cruise, twice outside the ±6 m avoidance threat cylinder,
which trades priority #1 for priority #2. The real finding: for a lane-**perpendicular** bird the two
gates are mutually exclusive (median frames 10/6/4/3/3 at z=6/8/9/10/11 — the 5-frame floor needs
z ≤ 8, the cylinder needs z ≥ 9). A lane-**parallel** bird has cross-track offset 0 and satisfies
both. So bird_0's line moved onto the x=15 lane at 11 m and took the threat role; bird_1 took its
8 m. Altitude multiset {6, 8, 11} **identical before and after** — a reassignment, not a lowered
flock. Predictor now says **PASS at 3 m/s** (medians 8/6/11, nothing structural — and *only* at
3 m/s: it FAILs from 5 m/s up, which is why `--speed` became required with no default on 2026-08-25,
ADR-016); the near-miss is unchanged
at **4.00 m**, and it got *harder*: the threat bird now patrols down orchard row 0, so the policy
rejects its own preferred 0° dodge ("clears tree by only −1.11 m") and takes +45°. The nominal world
finally reaches the "avoidance must never create a new collision" branch only a hand-built scenario
used to. SDF diff: exactly two `<pose>` lines.

**`scripts/check_tree_positions.py`.** The tree-check that caught the horizon-facing mount was never
code — the 2026-08-18 figures came from an ad-hoc look. It is now a gate: exit 1 when a positive-NDVI
cell sits farther than 2 m from every tree centre. The bar is measured, not chosen (every post-fix
clip puts 100 % of its positive cells at 1.7678 m; the three horizon-mount clips put 100 % of theirs
at 6.4-11.9 m — the 2 m bar sits in an empty gap). Twelve tests reproduce all five published clip
figures exactly and reject the three bad ones.

**The honest limit, which is the whole point of writing it down.** At the demo take's actual 0.407 Hz
the new geometry predicts **0 / 0 / 1 — identical to the old.** Geometry raised the ceiling (total
median 14 → 25 frames at the 5 Hz tick) and removed the bird no throughput could reach; it did not on
its own make the ADR-003 re-run scoreable. Recording throughput is still the binding constraint. The
difference is that the next Docker session can now be *priced before it is spent* — one command, one
second — and one re-fly with a bird in frame clears four blockers at once.

**Adversarial pass** (before any of it was believed): both gates re-run independently on all five
clips and the flown take; mutation-tested — a swapped quaternion in the backtest manufactures 289
phantom sightings, a widened displacement bar lets all three horizon-mount clips through, and the
pinned tests catch both. Four ADR numbers were measured wrong and corrected: the cylinder-dwell row
(quoted from two different sampling settings), alternative 2's altitude range (it claimed structural
at z=2…12; z ≤ 4 *is* visible — that case is alternative 1, not a third option), alternative 6's
dwell/closest, and an independence claim the one-projection refactor had quietly made untrue.

---

## 2026-08-21 (second entry) — the demo take: one command, a full mission, the best tree evidence yet, and a bird check that was never exercised

### 04:58-05:16Z — the flight

The first flight anybody flew through `scripts/fly_pipeline.sh` as a *user* rather than as its
author. Seven shells' worth of bringup — Gazebo, the sensor bridge, the micro-ROS agent before SITL
(the golden rule), the fuser, the recorder, the altitude-gated birds — came up under one command,
gated, in one window, and the flight itself was typed at the MAVProxy prompt the way a demo flight
always is. Full boustrophedon, not the two-lane test mission. It worked. That is the whole story of
the launcher, and it is worth writing down that the first time it was used in anger, the toil it was
built to remove stayed removed.

Clip: `eval/results/clips/real_flight_20260821T045848Z` — **454 frames, 410 of 720 cells imaged**,
`dropped_pair_count` 0, no stale pose pairs. Bird sidecar `bird_drive_20260821T050635Z.json`; the
driver's altitude gate fired on its own at takeoff (first airborne frame at sim 430.8 s, driver
`t0_sim` 437.92 s), so the birds were alive and moving for the whole imaging window.

### The tree half: PASS, and the best canopy evidence in the project

No tree-check script had ever existed — the 2026-08-18 numbers came from an ad-hoc look. So the
method was reconstructed and then **pinned by reproducing all three published figures exactly**
before it was allowed to judge anything new: flight 6 at 5/8, flight 7 at 5/6, and the "+0.87
typical lift" that `README.md` and this log both quote, which recomputes to **+0.869196** pooled.
Every tree centre sits on a 2.5 m grid corner, so its r=1.3 m canopy straddles the **four** cells
sharing that corner — that quad is the tree's cell set, and it is what makes the historical
denominators 8 and 6 rather than 6 and 5.

**This clip: 12/18 trees imaged, 8 canopy-grade, median lift +0.8692 — against a +0.8692 baseline,
dead on to four decimals, and 8 canopy-grade against a previous best of 6.** The strongest result is
one nobody had thought to measure: **all 9 positive-NDVI cells in the entire 410-cell map sit at
exactly 1.7678 m from a tree centre** — precisely a 2.5 m cell's centre-to-corner distance. Zero
canopy signal anywhere a tree is not; zero false positives in 410 cells. A 6 m sweep around each
soil-grade tree turns up no displaced canopy cell either, so those are genuine non-detections rather
than the mislocation class ADR-007 amendment 5 fixed.

**"Best to date" needed checking, and the check changed the claim.** Three earlier clips imaged
*more* cells (697, 586, 450) and *more* trees (17, 16, 15) — and returned **zero** canopy-grade
trees, with 100 % of their positive cells sitting **6.4-11.9 m** from the nearest tree. That is the
horizon-facing-mount signature, drawn as a plausible map. Every post-fix clip puts 100 % of its
positive cells at 1.7678 m. The lesson is blunt and now written into the runbook's own bar:
**`cells_imaged` is not the metric.** A wrong camera fills the grid faster than a right one.

### The bird half: not failed — NEVER EXERCISED

**0 bird-visible frames out of 454.** Verified twice independently: a from-scratch projection of
each frame's recorded bird positions through the clip's own intrinsics, and the harness's own
`label_from_sim.py`, which printed `454 frames, 0 visible bird-boxes`. Closest any bird came all
flight: **14.15 m** slant range, ≈341 px outside the image edge.

The cause is geometry, and it is structural. A nadir camera at 15 m over birds at 6 / 8 / 11 m AGL
sees a footprint *at bird altitude* of only 4.9×3.7 to 11.1×8.3 m — against a **15 m lane pitch**.
The ground plane tiles; the bird-altitude plane does not. bird_0 patrols x=20, a fixed 5.0 m from
lane x=15, so it is outside the frame on every single pass, every flight, deterministically. Nobody
had measured this because nobody had had a full-coverage clip to measure it on. **No number of extra
frames fixes it** — which makes it the first item in a long time that is not a throughput problem.

Per the runbook's own Gate-2 discipline ("do not treat this as a pass by just dropping the bird
check"), this clip cannot close the bird half of the proof standard, and it is recorded as
unmet-and-unexercised with the frustum numbers attached rather than quietly dropped.

### ADR-003 criterion 3: EVIDENCE INSUFFICIENT — and the harness that would have said otherwise

The real-render re-run this clip was supposed to unblock ran cleanly end to end and produced nothing
to score, so precision / recall / FNR / per-bird-track FNR are **undefined** against the synthetic
0.445 bar. Not a confirmation, not a refutation. The premise is intact — the real render keeps
ADR-003's class ordering with a *wider* margin than the spike (canopy +0.531 > trunk −0.026 > soil
−0.429 > bird −0.789; bird-vs-soil gap **0.360** against ~0.23 synthetic) — but the *threshold
values* are calibrated to the synthetic clip's absolute scale and saturate on the real one:
`ndvi < 0.05` passes **100 % of pixels on 438 of 454 frames** against real soil at −0.4377.

Then the part that matters more than the verdict. **`eval/score.py` would have printed
`-> ADOPT (a) NDVI-direct` on that empty ground truth.** With TP=FP=FN=0 every rate guard yields
0.000, and the decision rule read four zeros as a clean sweep. Reproduced live, same inputs, pre-fix
file vs post-fix file: `ADOPT` before, `EVIDENCE INSUFFICIENT` after. Anyone running `run_spike.sh`
and reading the last line would have closed a load-bearing ADR on **zero** evidence. A rate needs a
denominator, so the denominator is now checked before the rates are consulted. Two more found in the
same pass: `label_from_sim.py` never derived `range_m` on real clips, so the closest-approach lookup
hit its `1e9` fallback and silently redefined the safety-critical per-bird-track FNR from "detected
before closest approach" to "detected on first sight"; and `baseline_rgb.py` KeyError-ed on any clip
with partial RGB (243 of 454 here), killing the spike runner outright. All three fixed, 10 tests
pinning them (`tests/fieldguard_planning/test_score_evidence.py`, suite 291 → 301).

One more left deliberately unfixed and flagged in the file instead: `baseline_rgb.py`'s "birdness =
bright + achromatic" is a property of the *synthetic* clip's white birds. This world's birds are
**dark** against **bright** soil (measured modal soil pixel (138, 161, 115), min-channel 115 above
the 110 threshold), so the arm is inverted here. Flipping it is one character and the wrong thing to
do blind — the threshold needs recalibrating against a clip that actually contains a visible bird,
which is the same clip criterion 3 is waiting on.

### What it cost, and the honest footnote

The full-mission fuser telemetry landed for the first time: 4257 sensor ticks → 962 RGB frames
(22.6 %) → 634 fused (65.9 %) → 454 recorded (71.6 %) = **10.7 % end to end**, `dropped_pair_count`
0, with 328 unpaired frames (34.1 % of arrivals) landing squarely inside ADR-013 amendment 6a's
33-41 % band — the two-stage loss confirmed at 5× the duration of the flights that found it.

And the footnote the frame count hides: **only 51 of those 454 frames painted a cell.** 403 painted
nothing, 401 of them parked at home before arm and after land; just 42 were above 12 m. All 6
unimaged trees have 24/24 of their quad cells inside the 310 unimaged, so the misses are pure
coverage. The map is a 51-effective-frame artifact that happens to be the best one yet — which is
either encouraging or alarming depending on the day, and is worth reporting as painting frames from
here on rather than as a recorded-frame count that reads five times better than the work it did.

---

## 2026-08-21 — three merged PRs that never reached `main`, counters that ended the guesswork, and 5.1× the evidence

### 02:36-03:13Z — the stacked-merge trap, and PR #22

GitHub reported #18, #19, #20 and #21 all **MERGED** inside four minutes. `main` had two of them.
#19 (the disproven 2 Hz lever) was opened against `feat/one-command-launcher-and-docs` and #21 (the
doc unification) against `feat/recording-throughput-2hz` — a stack, each PR based on the branch
below it. Merging a stacked PR lands it on **its base**, not on `main`: once #18 went to `main`
first, the two above it merged green into branches `main` no longer tracked, and their content was
stranded with four green badges saying otherwise. A merged PR list is not an answer to "is it on
`main`" — `git log origin/main` is, and that is the check this repo now owes itself before writing
"current as of PR #N" anywhere. Recovery was one branch: `fix/land-pr19-21` merged
`origin/feat/recording-throughput-2hz` (which carried #21 on top of #19) into a branch off `main`
and landed as **PR #22** at 03:13:42Z. Nothing was cherry-picked and no history was rewritten, which
is why the negative-result commit `01bb3af` still reads as its own decision rather than as a
footnote to someone else's.

### The fuser stops depending on a console that scrolls away (ADR-013 amendment 5)

The 2 Hz collapse two days earlier was disproven but never *root-caused*, for one reason:
`fused_count` / `dropped_pair_count` existed only as log heartbeats, so no artifact separated
"fusion never fused" from "the recorder dropped what fusion produced". The fuser now publishes its
counters to a **1 Hz atomically-replaced JSON sidecar** written from an rclpy timer — never from the
image path — and `clip_recorder.finalize()` folds the last reading into the clip's own `meta.json`
as `fuser` (schema 1.1 → 1.2). The per-band counters (`red_frames`, `nir_frames`,
`camera_info_frames`) ride `registerCallback` on the `message_filters` subscribers that already
deserialise those messages: no second subscription, no second copy of a 640×480 frame.

A file and not a ROS 2 topic, deliberately. A bridged high-rate stream has already starved this
exact pipeline 8× (the `/clock` finding), a stats topic's delivery depends on the very executor it
is measuring, and it dies with its publisher — while a file survives whichever node dies first,
which is precisely the case that must not read as silence. Absence is reported as `present: false`
**with no counter keys at all**: a fabricated `fused_count: 0` is indistinguishable from a real
starve, the same shape of lie amendment 4 closed in the gate. A frozen sidecar keeps its real
numbers and is stamped `stats_age_s` / `stats_stale` instead of being passed off as current.

### The annotator stops refusing frames that were never wrong (ADR-012 amendment 1)

`eval/annotate_real_clip.py` flagged every pre-driver-start frame unshippable — 17 of 105 on the
last real clip — and that blocked the ADR-003 real-render re-run. The bug was ordering inside
`pose_at`: `t_s % tN` ran *before* the `t_s <= t0` hold, and `-15 % 20 == 5` in Python, so a frame
recorded 15 s before the driver started was labelled at the t=5 midpoint. The old refusal was the
right call on the old behaviour — a confident wrong position is worse than no position.

The fix is one clause, the wrap is now forward-only, and it lives in `pose_at` — the single
interpolation the driver and the annotator share by import — so the bird that was moved and the bird
that gets labelled cannot describe different positions. It is *correct*, not merely convenient,
because the birds are `<static>` models spawned at `waypoints[0]` and `drive_birds.py` is their only
writer: between world load and the first `set_pose` each bird demonstrably sits at its t=0 waypoint.
Verified three ways instead of asserted — the generator emits `waypoints[0]` as the spawn pose, the
committed SDF carries those exact poses (bird_0 `20.0 5.0 8.0 0 0 1.5708` against config
`x 20, y 5, z 8, yaw 90°`), and a repo-wide grep finds no second writer of a bird pose. Deliberately
**not** symmetric: the far end still wraps, because a running driver really does keep ticking
`pose_at` forever and the run sidecar records a start with no stop, so clamping that end would
invent evidence about when the birds quit. Frames recorded after the driver *exits* stay
undetectable — documented, not papered over with a speculative flag.

### 03:22-03:45Z — four flights, one variable at a time

Same `test_2lane` mission, same gate, four consecutive `fly_pipeline.sh test-flight` runs.
`camera_info_frames` is the control: it comes off the same RGB sensor tick as the image band, so a
flat column proves all four saw the same exposure window.

| # | config | cinfo | red (of ticks) | fused | recorded | cells |
|---|---|---|---|---|---|---|
| F1 | baseline, unchanged (5 Hz) | 692 | 73 (10.5 %) | 45 | 17 | 158 / 720 |
| F2 | + lever A (bridge QoS) | 699 | 126 (18.0 %) | 78 | 41 | 125 / 720 |
| F3 | + lever B (preview gated) | 696 | 113 (16.2 %) | 76 | 36 | 150 / 720 |
| **F4** | **A + B** | 698 | **217 (31.1 %)** | **129** | **86** | **368 / 720** |

**F1 paid for the whole session.** The amendment-5 counters flew for the first time, climbed rather
than sitting at 0 (closing the `registerCallback` risk flagged when they were written), and named
the starving stage on the first flight: `red_frames` 73 against 692 `camera_info` messages **off the
same sensor tick**, `dropped_pair_count` **0**. That single row kills both surviving explanations —
the camera is not under-rendering and the stale-pair guard is not eating pairs — leaving a
payload-size-dependent transport loss on the RGB image band alone. A lever-hunt became a
measurement.

Both levers were kept; nothing was reverted. **A**: the `ros_gz` bridge publishes RELIABLE while
every consumer subscribes BEST_EFFORT, so the reliable half was retransmission machinery for ~900 KB
samples nobody wanted retransmitted. It is **not settable in the bridge yaml** at the pinned SHA —
`bridge_config.cpp:28-36` declares nine keys, none of them QoS, and `parseEntry` silently ignores
the rest, so a `qos:` block there would look configured and do nothing, the worst failure mode
available — but it is a per-topic ROS parameter, now on the Shell-2 one-liner and verified bound
before it flew (the image topics report BEST_EFFORT while `camera_info`, deliberately untouched,
still reports RELIABLE — the control proving the parameter and not the environment did it).
**B**: `/fg/ndvi/preview` is human-only and nothing in the repo subscribes to it, yet every fused
frame paid a colormap over 307 k px, two 921,600 B copies and a no-reader serialize-and-write — on
the one executor whose next job was draining the RGB subscription F1 had just named. Now guarded by
`get_subscription_count()`: work removed, feature intact.

Read it honestly. Recorded frames are up **5.1×** and cells imaged **2.3×** against the same day's
baseline, and 368/720 beats the previous all-time valid 2-lane best (291 off 48 frames, 2026-08-18).
It is not solved. Two things were deliberately *not* claimed: the amendment-4 evidence floor was
left at 12 frames / 40 cells rather than raised to match the new yield, because one healthy run at a
new config is how a floor buys flakiness instead of detection; and **lever A's own flight imaged
fewer cells than baseline (125 vs 158) on 2.4× the frames** — not a regression but the trap in
judging this work by `cells_imaged` at n=1, since its extra frames landed while the vehicle was slow
(three mid-climb at the origin, five stacked at the far-end turn at x≈75) where frames buy no new
cells. The position-independent metric is `red_frames / camera_info_frames`, and it moved
monotonically on every arm.

### The adversarial pass — what the same four artifacts say that the write-ups did not

A qa-safety-reviewer pass re-derived every number from the gate records and clip `meta.json` files
(all four reproduce exactly), mutation-tested the load-bearing behaviour rather than trusting green
tests — breaking the staleness marker fails exactly the two staleness pins, fabricating zeros for an
absent sidecar fails exactly the two absence pins, and reverting the `pose_at` clause fails exactly
the three clamp pins, each restored byte-identically after — and found three things.

One is a live footgun in the new instrumentation: `write_fuser_stats` promised in its own docstring
that instrumentation can never take a flight down, but caught only `OSError`. It runs on a 1 Hz
rclpy timer, so an escaping exception kills the fusion node mid-flight, and the way in is one line
away — `json.dumps(np.int64(5))` raises `TypeError`, numpy is everywhere in this package, and the
obvious next counter to add (`zero_denom_count`) is computed by it. Widened to
`(OSError, TypeError, ValueError)`, with the numpy case pinned in the test that makes the claim.

The second is the more interesting one. `_on_pair` has exactly two outcomes, so
`red_frames − fused_count − dropped_pair_count` is precisely the red frames the
`ApproximateTimeSynchronizer` never handed over — they reached the node and never found a NIR
partner inside the 50 ms slop. That is **28 / 48 / 37 / 88** across the four flights: 33-41 % of
every red frame that survived transport, flat across both levers because neither touched pairing.
The full F4 chain is `698 ticks → 217 red (31.1 %) → 129 fused (59.4 % of red) → 86 recorded
(66.7 % of fused)` = **12.3 % end to end**. So `dropped_pair_count: 0` only ever meant the *guard*
rejected nothing; it was never evidence that pairing was lossless, and the next lever on item 1 is
not necessarily another transport lever (ADR-013 amendment 6a). Mechanism agrees with the transport
diagnosis rather than competing with it: NIR is mono16 at 614,400 B and lands ~3 Hz while RGB is
rgb8 at 921,600 B and lands 1.6 Hz even after both levers, so most red frames simply have no NIR
neighbour close enough.

The third is bookkeeping that a doc-honesty repo should not need told twice: `main` was described as
"current as of PR #17" while `origin/main` stood at PR #22; ROADMAP item 1 was headlined "largely
closed" one paragraph above its own "it is *not* solved"; the bridge yaml credited `ros_gz`'s `ros2`
branch when the pinned checkout is `humble` at `9d7f8c7` (`ros2` is `ardupilot_gazebo`'s branch, and
that conflation still sits in an agent-memory file); a source citation quoted `KeepLast(10)` where
the source reads `KeepLast(queue_size)`; and the 6 → 42 survey-frame figure was reproducible only if
you guessed the threshold, so it now states it. All corrected in place. Suite: **291 green, 2
skipped** (258 + 33), `shellcheck` and `bash -n` clean on the launcher, and the launcher's nine pane
payloads still byte-match the runbook — the parity test that made it safe to edit `fly_pipeline.sh`
for lever A at all.

---

## 2026-08-18 (late night) — `fly_pipeline.sh` replaces the 7-shell bringup, and the first scripted test-flight gate PASSES

The seven copy-pasted terminal tabs of `docs/runbooks/FULL_PIPELINE_DEMO.md` collapsed into one
host-side tmux session (ADR-013): `scripts/fly_pipeline.sh`, one window per runbook shell, each pane
running that shell's `docker exec` one-liner **byte-identical** to the runbook (mechanically diffed,
all nine lines) — the only thing added is ordering and a **gate between every stage** (Gazebo's four
`/fg/sensor` advertisements, the ROS 2 crossover, the render-alive probe, UDP 2019 bound before SITL
boots). A qa-safety-reviewer adversarial pass refused to accept that the gates prove anything, on
the grounds that every one of them is a *liveness* gate — it cannot tell whose process it found —
and proved the point live: running `status` against an already-running manual bringup returned
three green gates and no tmux session, the exact stale-bringup clash the happy path would never
have surfaced. `up` now refuses to start on any surviving sim process instead of double-publishing
into it.
Then the one scripted flight mode this ADR allows — `fly_pipeline.sh test-flight` (ADR-013
amendment 2), a regression gate, not a flight path — ran for real and **PASSED on its first attempt**:
`eval/results/testflight_gate_20260818T222031Z.json` — 253 s unattended, every gate green, the
birds pane self-started at its altitude gate (15.0 m), teardown went recorder-first, the host-side
stitch exited 0 over a 48-frame clip with 0 stale-pose pairs. Suite 246 → 270 green (24 launcher
tests in `tests/test_fly_pipeline.py`, later 33 as the evidence floor landed — **279 green, 2
skipped** by session end) — and CI was not running any of them: `discover -s
tests/fieldguard_planning` never walks `tests/`, so a second discover was added. The ROADMAP's
test-count line said **131**, a number last true on 2026-08-05 and carried unchanged through the
sessions that tripled it; corrected in the same pass, and worth naming rather than quietly
overwriting — a stale metric in a living doc is the failure mode this repo claims not to have.
Docs decision: against a four-direction options artifact, the user picked **D · Heatmap Neutral**,
built by an in-repo generator rather than an external tool (ADR-014). An adversarial QA pass on the
generator found four defects the exit code could not: a wrapped body line beginning `#5→#8)` parsed
as a page-title `<h1>` mid-ADR (python-markdown allows `#` with no space; GitHub does not — the
renderer now follows GitHub and a heading-parity gate fails the build on any future divergence),
broken intra-repo `.md` links passing silently, the print stylesheet losing to the dark rule on
specificity so an Auto + dark-OS reader printed a black page, and one unbreakable
`eval/results/...json` path widening every page at 375 px.

### 2026-08-19 02:07Z — the recording-throughput lever, measured and **disproven**

ROADMAP item 1's first lever was `camera.update_rate_hz` 5 → 2: halve the render+transport load and
the starved software-rendered pipeline should *deliver* a larger fraction of frames (at 3 m/s and a
13.8 m footprint, 2 Hz still over-samples). It was a good hypothesis. It is wrong — and the run that
killed it took under four minutes.

| | 5 Hz baseline (22:16Z) | 2 Hz (02:07Z) |
|---|---|---|
| fused frames recorded | **48** (42 with rgb) | **3** (3 with rgb) |
| recorder exposure window, sim time | 133.2 s (sim 11.4 → 144.6) | ~128.9 s (sim ~10.6 → 139.5) |
| frames expected at the configured rate | 666 | ~258 |
| **delivered fraction** | **7.2 %** | **1.2 %** |
| delivered per sim-second | 0.360 | 0.023 |
| **cells imaged** | **291 / 720** | **1 / 720** |
| stale-pose pairs | 0 | 0 |
| soil cells (mean NDVI) | 281 at −0.438 | 1 at −0.438 |
| canopy-like cells (> +0.3) | 6 (max +0.478) | 0 |
| mission flown | 12 "Reached command" | 12 "Reached command" |
| flight wall time (arm → disarm) | 192 s | 177 s |
| gate wall time | 253 s | 233 s |
| RTF (bird anchor → last frame) | 0.561 | 0.585 |

Sources: `eval/results/testflight_gate_20260818T222031Z.json` and
`eval/results/testflight_gate_20260819T021136Z.json`, their clips' `meta.json` / `poses.jsonl` /
`heatmap/heatmap.json`, and the two `bird_drive_*.json` sidecars (the sim↔wall anchors the RTF and
the 2 Hz window estimate are computed from — that one window start is *derived*, from a recorder
that started 29 s before arming in **both** runs, not measured; every other number is read straight
off an artifact).

Read it honestly: this is not a marginal miss, it is a **16× regression**, and the quality arm
became unevaluable (one cell, at home, during the landing descent — all three frames arrived at sim
130.0 / 131.0 / 139.5 s, i.e. nothing at all was delivered during the traverse). Two controls say the
host was not the culprit: the mission flew identically (12 reached commands, birds self-started at
14.99 m vs 15.0 m, pose-call failures 10/522 vs 6/531) and the sim ran *marginally faster* in sim
time per wall second (RTF 0.585 vs 0.561) — so the render load did drop, exactly as the lever
predicted, and delivery fell anyway. The load relief was real; the throughput gain was imaginary.
The best available explanation is that delivery on this stack is **bursty, not steadily
rate-limited**: 9 of the baseline's 47 inter-frame gaps are ≤ 0.4 s and 4 are exactly 0.2 s, so the
pipeline does briefly run at the 5 Hz ceiling and harvests whole bursts — and a 2 Hz ceiling
(0.5 s) cannot harvest a burst at all. That accounts for part of the drop, not for a 16×, and the
honest position is that the mechanism is **unproven on n=1**. The verdict does not depend on it:
under the project's own rule (keep the change only if the delivered fraction improves materially
with no quality regression), nothing in this data keeps 2 Hz. Config and world are back at 5.0 —
the SDF regenerated byte-identical to its committed state — with the measured basis now recorded in
`config/ndvi_camera.json`'s own `update_rate_note`, so the next person cannot re-derive this
hypothesis for free.

One instrumentation gap this exposed, worth fixing before the next throughput attempt: **no
artifact distinguishes "the fusion node never fused" from "the recorder dropped what it fused."**
`fused_count` / `dropped_pair_count` live only in the ndvi node's console, and `pane_tails["ndvi"]`
comes back empty in *both* gate records — so the one number that would have root-caused this run was
never captured. Persist the fuser's counters into the gate record (or the clip `meta.json`) and the
next lever gets diagnosed instead of guessed.

## 2026-08-18 (night) — Gates 1-3 green, five bugs deep, and the first honest heatmap

The batched session ran to the end — and became the project's best story. Gates 1-3 all passed
live (bridge; canopy 0.854 > soil 0.212 > bird 0.040 across 996 frames with the ADR-012 birds
moving; clean avoidance takeover/resume on the NDVI model, ledger valid at 513/207). Then six
recorded flights peeled five real bugs off the pipeline, each invisible to the value-gates:
1. **Arrival-paired poses** mislabeled frames under render bursts (0/18 trees despite a
   plausible map) → gz-clock stamp pairing + per-frame residuals + stitch skipping flagged frames.
2. **Bridging the sim clock** (~350 msg/s) starved image serialization ~8× → native gz-transport
   clock stream.
3. A **shallow fusion pairing queue** (10) flushed stamps before partners arrived under load →
   queue 60 + the host-quiet rule (parallel agent workloads on the host were eating the sim).
4. A **long-lived render instance silently degraded** to sky-flat frames in both bands →
   `scripts/check_render_alive.py` pre-flight probe + restart-Gazebo-per-flight rule.
5. **The sensor mount had faced the horizon, upside-down, since ADR-007 was authored** — Gazebo
   cameras look along sensor +X; the rpy was derived Z-forward. Found by the tree-position check;
   root-caused with a landmark-oracle world (after learning `<static>` doesn't propagate into
   nested includes — crash-tumbling test vehicles produced hours of contradictions);
   fixed and now GATED: `scripts/verify_mount_geometry.sh`, canopy centroid within 2.2 px of the
   georef prediction.
Flights 6-7 on the corrected mount produced the first heatmaps that survive cross-examination:
every imaged tree at its true position, +0.87 typical NDVI lift, soil dead on the physics
prediction. Evidence committed past the gitignore (level-by-level exceptions). Remaining:
fused-frame recording THROUGHPUT (truth proven; coverage per flight still partial — first lever:
camera 5→2 Hz), then the ADR-003 real-render re-run (annotator needs a pre-driver-start clamp).
The meta-lesson, now everywhere in the docs: gates that measure values cannot catch geometry;
every artifact needs a check against ground truth it cannot fake.

## 2026-08-18 (evening) — First Gate-1 attempt: one blocker fixed live, one real bug found

The batched Docker session started. Gazebo came up healthy (thermal on all 36 visuals, four
`/fg/sensor/*` topics advertised), but the `ros_gz` bridge crashed on missing
`libactuator_msgs...so`: the bridge's *optional* build-time deps are hard runtime deps, rosdep had
installed them at workspace-build time, and apt state is container-ephemeral while the workspace
volume persists. Fixed live (3 apt packages), verified (bridge creates all 4 GZ→ROS bridges),
pinned into the Dockerfile. Then a live scene-graph query exposed a latent Week-2 bug: **the bird
actors have never rendered** — skinless `<actor>` link-visuals don't enter Harmonic's ogre2 scene
(0 bird entities in `scene/info`). Never noticed because the avoidance demo injects bird
positions, not pixels. Gate 2's bird check + real-render detection were blocked on the fix,
which landed the same night (ADR-012): birds → static models (per-visual thermal works there,
unlike actor skins) + `scripts/drive_birds.py` interpolating the unchanged trajectory JSON through
`set_pose` at the camera rate. Verified in-container on a renamed-world copy: 3 birds in the
render scene (was 0), driver placed bird_0 trajectory-exact. Gazebo must be relaunched to pick up
the regenerated world. Full details: `docs/archive/NDVI_VALIDATION.md` session log.

## 2026-08-18 — The audit, the rename, and Phase A1 hardening

A 5-auditor sweep (docs / code / sim / eval-CI / state-vs-claims) after a 13-day pause found the
foundation solid but the process rusting: **CI had been silently red for 12 days** (tests ran before
the numpy install, so the seed-42 FNR safety gate never executed on the branch), the **coverage
ledger had an honesty bug** (commanded dodge setpoints recorded as flown — a never-visited cell
could finalize COVERED; scenario logs understated debt by up to 32 cells), and the **2026-08-05
live-demo flight log had been silently clobbered** by a later idle run. One session repaired
committed scope, nothing added without a cut:

- CI un-redded + 2 new gates (scenario-log drift, flight-log evidence validity). The drift gate
  caught two real regressions on its first day: a stale-params drift and a **cross-platform libm
  ulp divergence** (macOS vs glibc disagree in the last bit of the bearing-sweep trig — logs now
  round floats to 1e-9 so byte-identity is platform-independent).
- Ledger honesty restored: fix + regression test (proven to fail against the old code) + honestly
  regenerated logs (`cov_bird_at_turnaround` 118→144 debt, `geo_avoid_into_tree` 112→144).
- `scripts/stitch_ndvi.py` (ADR-010): the offline georeferenced stitch — exit criterion 1 became
  producible in a single Docker session. Georef pitch/roll proven correct by new hand-derived
  tilted-pose fixtures (no bug found — the math was right, now it's pinned).
- ADR-009 detector contract locked before the Week-6 detector: `Detection.stamp_s` + staleness
  gate; bird position from apparent-size ray, never ground-plane projection (which would place a
  flying bird at z=0, *outside* the threat cylinder — fail-dangerous).
- Flight logs timestamped + CI-validated; evidence can no longer be silently destroyed.
- Test suite 94 → 131; pytest un-broken repo-wide (a tests `__init__.py` shadowed the source package).
- PR #13 merged (10 commits) — public main current again.
- **Project renamed FieldGuard → SwathKeeper** (ADR-011): docs/branding renamed; code identifiers
  (`fieldguard_planning`, `fg_`/`/fg/*`, `farmguard_field.sdf`, `fieldguard-sim` image) deliberately
  kept. Docs restructured reader-first: `docs/runbooks/` (by function, not week number),
  `docs/archive/` (historical records), this build log, `docs/README.md` index.

## 2026-08-05 — Week 5 kickoff: ADR-007 lands, Gate 0 GREEN

The NDVI phase's one architecture risk — *can the pinned Gazebo Harmonic + ogre2 stack render a
second band at all?* — was retired the right way: ADR-007 (RGB camera Red channel + **Gazebo
thermal sensor repurposed as synthetic NIR**, fused in a ROS 2 node) passed external review, and
the kill-switch gate ran FIRST in Docker before any temperature authoring: `gz-sim-thermal-system`
loads, the world loads with the two-sensor mount, all four `/fg/sensor/*` topics present. One real
failure en route: the mount joint's parent-link name was wrong twice before
`iris_with_gimbal::base_link` resolved (the `<include merge="true">` flattening — full record in
`docs/archive/NDVI_VALIDATION.md`). NDVI fusion + georef stitch math shipped sim-agnostic and
unit-tested. Scope guards recorded: no YOLOv8 keyword-chasing, no startup cosplay
(`docs/ROADMAP.md` cut log). Remaining live-verification debt batched into ONE session: Gates 1-3 +
ADR-003 real-render re-run.

## 2026-08-05 — Weeks 3-4: the core loop, live

The differentiator ran end-to-end on the real stack: during a boustrophedon survey the drone
detected the scripted bird, took over (`/ap/mode_switch`→GUIDED), flew a 3D-vetted dodge
(`/ap/cmd_gps_pose`), held clear, resumed AUTO at the same waypoint (`MIS_RESTART=0`), finished the
survey — one clean takeover/resume, no thrash. Built sim-agnostic first (policy + executor +
coverage-debt ledger, pure stdlib Python, QA's adversarial scenarios green), then bound to ROS 2
by a thin adapter. ADR-005 (the `/ap/*` topic contract) and ADR-006 (we own the maneuver;
AUTO→GUIDED→AUTO) both **confirmed live**. The three Docker gates (farm world flies, AP_DDS
publishes per contract, resume behavior) passed in one session — record archived at
`docs/archive/WEEK3_VALIDATION.md`. Six real bringup bugs found + fixed en route (bash-3.2 array,
colcon `set -u`, MAVProxy, `future`, `micro_ros_msgs`, and the big one — SITL builds DDS OUT
unless `--enable-DDS`).

## 2026-08-04 — Weeks 1-2: foundation + the detection decision

Full ArduPilot + Gazebo + ROS 2 workspace built from source in Docker (pinned SHAs in `CLAUDE.md`
— captured at the first green Gazebo flight, the real reproducibility anchor). A generated
boustrophedon mission flew fully autonomously (takeoff, 6-lane sweep, RTL). The farm world shipped
(18 static trees, 3 scripted birds) with the mission unchanged byte-for-byte. AP_DDS enabled
explicitly with the non-obvious catches documented (frame_id lies on `/ap/pose|twist/filtered`;
`eeprom.bin` persists params). The NDVI-vs-RGB question was closed by measurement, not opinion:
ADR-003 — detect NDVI-direct; the classical blob baseline hit per-bird-track FNR 0.000 on the
fixed-seed synthetic clip, so no trained model was justified. The permanent `eval/` harness was
born from that spike. QA defined the coverage-debt invariant (720-cell canonical grid; every cell
terminates `covered`|`debt`; absence IS the bug) — the invariant everything since is measured against.

## 2026-07-27 — Kickoff

Scope confirmed (avoidance-with-coverage-integrity first, NDVI second, dashboard last-and-light);
sim-only decided (ADR-000); toolchain pinned (ADR-004: Ubuntu 22.04 in Docker, ROS 2 Humble,
Gazebo Harmonic, `ardupilot_gazebo` `ros2` branch); tiger team of 8 subagents stood up
(`TIGER_TEAM_GUIDE.md`); original playbook archived at `docs/archive/tiger_team_playbook.md`.
