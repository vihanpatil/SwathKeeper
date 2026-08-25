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
