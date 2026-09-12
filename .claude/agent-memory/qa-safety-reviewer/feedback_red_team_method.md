---
name: feedback-red-team-method
description: How to red-team a SwathKeeper evaluation — the failure patterns that recur when I or another agent grade this project, learned from the 2026-08-25 strategic re-evaluation pass
metadata:
  type: feedback
---

When attacking an evaluation of this project (mine or another agent's), these patterns recur. Check
them before accepting any finding, including my own.

**1. n=1 encounter re-ranks the roadmap.** Every avoidance conclusion so far has been drawn from ONE
encounter on ONE flight. There are three live flight logs
(`eval/results/live_flight_log_2026{0818T144711Z,0823T004031Z,0825T210402Z}.json`) with 61 / 19 / 4
maneuvers. Any claim about the breach mechanism must be re-run across all three before it is
believed. I got this wrong myself once (see G53 retraction in [[project-open-safety-gaps]]).

**Why:** the three flights differ on TWO variables at once — warning time and escape direction — so
single-flight causal claims are confounded by construction.
**How to apply:** before accepting "X is the mechanism", index `flown_path_enu` by tick over the
takeover→resume window and compare commanded setpoint to achieved displacement on all three.

**2. The gates measure the decision layer only.** The whole harness (`check_live_flight_log.py`,
CPA, ledger, R2/R3) certifies whether a setpoint was *vetted*. Nothing certifies whether the vehicle
*moved*. Ask "and then what did the aircraft do?" of every green result.
**Why:** this is the project's own named enemy (vacuous green) one layer up, and it survived four
adversarial rounds and a four-part strategic evaluation undetected.

**3. A remedy must be run, not reasoned.** Two of the strongest-sounding recommendations in the
2026-08-25 evaluation dissolved when executed: substituting the physically-derived swath
(6.923 m for 7.5 m) leaves the ledger at 720/720 debt 0, and "derive covered from painted cells"
is a no-op on that flight (heatmap already 720/720) while converting recorder loss into phantom
coverage debt on partial clips.
**How to apply:** `PYTHONPATH=src python3 -c ...` the proposed fix against a committed artifact
before ranking it. It takes a minute and it has changed the ranking twice.

**4. Severity inflation on documented-open assumptions.** `coverage.py`'s swath docstring, the
`generate_flight_logs.py` det_* deferral, ADR-007's NIR caveat — all are flagged in the repo in
plain text. Restating them as discoveries makes the review look productive and the project look
worse than it is. Cite the existing flag and grade only the NEW content (usually: the number).

**5. Sourcing: check whether the cited source says the thing.** In the 2026-08-25 pass the ASSURE
67 % figure was cited to the A68 report (it is A18, 2019 flight tests) and paired against a >99 %
claim for a LATER product generation; the ASDC survey was cited for +58.7 % acreage while the same
survey's −59 % unit-sales collapse went unmentioned; PX4-Avoidance's archival was read as "the ROS 2
transition never completed" when the repo is ROS 1 Noetic only and died in the ROS 1 EOL wave.
**How to apply:** follow the URL, and specifically look for the datum in the source that cuts the
other way.

**6. A SPECULATIVE finding will be acted on anyway — verify it or say DO NOT ACT.** Added
2026-08-26 after I caused a regression. In the point-mass replay review I filed m8 ("the fixed
counterfactual horizon manufactures deferrals at long lead") as a MINOR one-liner from reading the
code, without recomputing. It was **wrong** — under a fixed absolute end a longer lead buys MORE
flying time, and the long-lead deferrals were genuine retreats. The builder fixed it faithfully,
and the fix made the simulation stop before the encounter at leads >= 2.0 s: 72 of 429 cells moved,
32 flipped, and the new band-free honesty field went from 0.50 m to 12.55 m on one cell — the same
vacuous-green shape I had just made them fix, relocated from vertical to temporal scoping (G76).
**Why:** every finding I file gets implemented; there is no second reviewer between me and the
diff. Severity does not protect anyone — MINOR items get fixed too, and a fix to a non-problem is
pure risk.
**How to apply:** run the two-line recomputation before filing, or label the item
`UNVERIFIED — do not act, confirm first` in the finding itself. Cheapest form: re-score the same
artifact under the current rule and the proposed rule and diff the verdicts; if nothing moves, the
finding is cosmetic and should say so.

**7. In a MULTI-BUILDER session the prose desynchronises from the code, and the ADR is where it
lands.** Added 2026-09-07 (ADR-020 commissioning close, 3 builders on one tree). Every measured
NUMBER survived my checks; four separate defects were all sentences: the ADR named a residual that
a sibling builder had already fixed (`corner_ray_ratio`'s third copy), named the wrong home file for
the new primitive, described three importers as "deliberate duplication", and asserted a `--sweep`
exit contract the code does not implement — while the tool printed the same wrong contract in its
own footer on the one run where it is wrong. The runbook meanwhile published a bookable-range RULE
no ADR contains and the gate does not compute.
**Why:** each builder writes its report from the tree as it was when it started, and the
append-only ADR is written last from those reports, not from the tree. Nobody re-greps.
**How to apply:** for a doc-consistency lens on a multi-builder tree, do not diff prose against the
builders' reports — diff prose against the CODE: grep every named identifier, run every quoted CLI
and compare the exit code, and re-run the tool that wrote every committed artifact and diff it
field-by-field. Two of the four defects above were found by running a command the doc said would do
something else.

**8. A FIRMWARE identifier typed at a prompt is a CITATION — fetch it at the pinned SHA.** Added
2026-09-07. The booking-enforcement build injected `param set WPNAV_SPEED 500` into the fly recipe;
at the pinned ArduPilot SHA the parameter is `WP_SPD`, in **m/s**, `@Range 0.10 20.00`
(`GOBJECTPTR(wp_nav, "WP_", AC_WPNav)` in `ArduCopter/Parameters.cpp`; `AP_Float _wp_speed_ms` in
`AC_WPNav.h`). Wrong name AND wrong units by 100×, so the whole pre-flight half of the feature was a
no-op that printed `BOOKED 5.0 m/s` on four artifacts. The builder's report *named* this as a
judgment call ("parameter name is WPNAV_SPEED, not the repo's WPNAV_SPD shorthand") and reasoned it
instead of fetching it — and the repo's own ADR log already contained the counter-evidence.
**Why:** this project's plant constants are all sourced with pinned-SHA URLs (`eval/point_mass.py`);
the one identifier that leaves the host and enters the *vehicle* was the one nobody sourced. The
same family as G70 (a constant cited to a header that does not contain it) and G46.
**How to apply:** when a diff adds a string that will be typed at a MAVProxy/ROS prompt, WebFetch the
owning source file at the CLAUDE.md pinned SHA and quote the `@Param`/`@Units`/`@Range` block before
grading anything else. Then check the second-order effect: here, correcting the name to `WP_SPD`
would have silenced `_tuning_override_scan`'s `WPNAV_`-prefixed detector — the fix creates the
vacuous green unless both land in one diff.

**9. WHEN A NEW VALUE JOINS AN ENUM, THE FINDING IS IN THE BRANCHES THAT DID NOT GET UPDATED — and
they are reachable by grepping the OLD members.** Added 2026-09-07 (depth-source wiring, G157/G158).
The build added `DET_DEPTH_BLOB` to `scripts/check_live_flight_log.py` and carefully wired it into
the new mislabel rule twelve lines below. `grep -n "DET_NDVI_BLOB\|DET_DEMO_VIRTUAL\|
DETECTOR_SOURCES"` on the same file returned nine hits; asking "what does a `depth_blob` log do
HERE?" of each one found, in about a minute, that `gate_booked_speed:1813
is_avoidance = source in (DET_NDVI_BLOB, DET_DEMO_VIRTUAL)` tells the ONE take type the ADR-020
booking gate exists to authorise that it is *"not an avoidance take ... and needs none"*, and that
`gate_detector_ran`'s `DETECTOR NEVER RAN` check — the repo's only net for "camera_info never
arrived" — is unreachable for the new source.
**Why:** an added enum member is grep-able; the branches that silently EXCLUDE it are not, because
they name the old members and read as complete. Both defects here point the same way (a new sensor
exempted from a check that exists for it), which is the fail-DANGEROUS direction.
**How to apply:** on any diff that widens a set of named constants, grep the OLD members across the
whole repo, not the new one, and read every hit as a question. Then ask the second-order version:
"when the follow-on diff promotes the new member into the main list, what breaks?" — here,
`gate_detector_ran` would report *"counters missing for ['ndvi_msgs_received']"* on a depth block,
so the landmine is already laid for the next session.

**7. Multi-builder rounds leak at the HANDOFF, not inside the file.** Measured 2026-09-10: four
builders on disjoint files produced clean, well-tested work inside their own scope and **five of the
cross-file edits they each wrote out in full went nowhere** — `dashboard/README.md`,
`AVOIDANCE_REAL_DETECTION.md` §4, `depth_segment.py:5`, `DEPTH_SEGMENTER_DESIGN.md:17`,
`AIRBORNE_Z_M` in two files. Every one was correctly diagnosed and correctly written up; none had an
owner. Two builders independently wrote the SAME handoff (the prototype reference) and it still did
not land.
**Why:** "report the edit instead of making it" is the right rule for concurrency and a guaranteed
drop unless someone sweeps the handoffs at the end.
**How to apply:** before grading anything else in a multi-builder round, collect every "HANDOFF" and
"COULD NOT" item and grep for it FIRST — it is the cheapest finding density in the review, and a
deleted file still referenced or a doc made false by someone else's change is a MAJOR by the rubric.

**8. Grade the number the round ITSELF introduced, hardest.** The stale numbers a round fixes are
easy; the ones it creates are invisible because they look freshly measured. Two landed on
2026-09-10: `README.md` "22 ADRs" (actual 23 — inherited from a handoff quoting the audit's
pre-ADR-022 count) and `CLAUDE.md` "tests:src is capped at 3.45:1 (today's ratio)" (measured 3.69:1
in the same tree — 3.45 was HEAD's).
**How to apply:** for every NEW count/ratio/date in a doc of record, run the one-line command that
produces it (`grep -c`, `wc -l`, `git rev-parse`) rather than reading the sentence.

**9. Outward-facing copy drifts by DROPPING a qualifier, and always in the flattering direction.**
Measured 2026-09-11 on the ADR-022 outreach kit: the builder's own memory file correctly wrote
"against a *hypothetical* 5.0 m/s booking" and the message said "the mission **was booked** at
5.0 m/s"; the repo's own marker says two flights breached "with every gate green" and the message
said "on three flights the gates **caught** real failures". Neither was invented — both are a true
sentence with the inconvenient half removed.
**Why:** prose has no gate. A number can be recomputed from an artifact; a *premise* ("the mission
was booked", "the gate caught it") is a claim about provenance and history that no test checks, and
it is exactly what a reader who opens the repo will check first.
**How to apply:** for every outward claim, ask WHO and WHEN, not just WHAT — which gate, written on
what date, relative to the flight date? Then grep the artifact for the qualifier ("hypothetical",
"reproduced", "would have", "every gate green") and make sure it survived into the copy. On this
round that single question produced the two highest-consequence findings, and both made the copy
stronger, not weaker.

**10. `docs/**` publishes. Draft ≠ private.** `scripts/build_docs_site.py` walks `docs/**/*.md` and
files nothing lists land under "Other documents" — so `docs/drafts/DEMO_VIDEO_SCRIPT.md` is served at
`.../docs/docs/drafts/DEMO_VIDEO_SCRIPT.html` (200, verified) with its "should sell the product"
stage direction intact. A private working file belongs in a gitignored path (the outreach kit did
this right: `.gitignore:117`), never in `docs/drafts/`.
**How to apply:** when reviewing any doc for a claims ceiling, curl the published URL rather than
assuming "drafts" means unpublished; and scan the whole published set, not just the changed file.


**11. A sampling-based gate's COMPLETENESS claim is a measurement, not an argument.** When a round
ships "we also sample X, so a Y shorter than the step cannot slip through" (ADR-022 am. 2, R8), the
sentence is the finding to attack. Build an ANALYTIC ground truth for the same predicate (for a
straight leg vs a cylinder: intersect the XY chord interval with the z-band interval — both are
convex in the leg parameter, so it is exact and fast), then differential-test thousands of
boundary-biased cases through the REAL input pipeline. On R8 that turned a confident prose claim
into "57 of 2,500 sloped legs pass, worst 18.6 cm inside the exclusion cylinder", and the level-leg
control (0/2,500) named the exact regime the claim fails in — the one the round had just added.
**Why:** the builder's own graze test was a LEVEL leg, so it proved the mechanism worked in the one
geometry where it could not fail. A hand-picked fixture cannot measure a rate.
**How to apply:** any new gate with a step/tolerance/resolution constant — mutate that constant to
an absurd value and see if ANY test dies. On R8, `SAMPLE_STEP_M` 0.5 -> 1e9 left all 22 tests green.


**12. A DECLARATION's falsifier set is graded on ANTI-CORRELATION with the failure it guards.**
Added 2026-09-11 (`--no-birds`, ADR-020 am. 7). When a flag lets an operator remove a ground-truth
family from a safety verdict, the build will ship a list of "things that refuse the declaration" and
that list will be the reviewed artifact. Do not check whether the falsifiers WORK (they did — 17/17
mutants died). Check what they are all made of. Here all four read the DETECTOR's output — an
avoidance event, a `detection` event, a named bird track, a reviewed pin — so every one of them goes
silent in exactly the case the removed gate exists for: the bird the detector MISSED. Measured by
taking the 0.0067 m strike log, deleting its detector-side events and zeroing `boxes_total` (= the
artifact a total-FN flight writes by itself) and scoring it `--no-birds`: **VALID, exit 0**.
**Why:** a falsifier list is written from the failures the team has SEEN, and this project has only
ever seen the detector work. **How to apply:** for each falsifier ask "which subsystem writes this
evidence?" If every answer is the same subsystem, the declaration is unfalsifiable whenever that
subsystem fails — and the fix is a falsifier from a DIFFERENT source. Here: wall clock (the one
clock Gazebo does not restart) separated the two cases by 3.5 min vs 16.5 days on the real
artifacts. Second half of the same question: the falsifier's own CONSTANTS. `threat_cylinder` reads
the flight's knobs verbatim, so shrinking `threat_radius_m` to 0.1 shrinks the falsifier —
"a falsifier may not shrink with the flown knobs" is the rule, `max(flown, default)` is the fix.
