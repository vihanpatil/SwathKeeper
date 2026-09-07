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
