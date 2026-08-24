# ACKNOWLEDGED SAFETY FINDING — closest approach 0.0518 m (ADR-013 amendment 12, S1)

**This log is kept as recorded history. It is NOT evidence of a safe flight.**

`scripts/check_live_flight_log.py` reports this file as **ACKNOWLEDGED**, not VALID, because of
this marker. Delete the marker and the checker fails hard, which is the correct behaviour for any
*new* flight that flies this close.

## The number

| | |
|---|---|
| closest point of approach (horizontal) | **0.0518 m** to `demo_bird_0` |
| policy bar (`PolicyParams.min_bird_clearance_m`) | **3.00 m** |
| breach factor | ~58x inside the bar |
| detections / maneuvers | 19 / 19, every one `verdict: accepted` |
| coverage ledger | 720 covered / 0 debt |
| every other gate at the time | green |

## Why it was invisible

The policy already refuses to place a *setpoint* within `min_bird_clearance_m` of a threat, and all
19 setpoints honoured it. Nothing in the pipeline computed the distance actually **flown**, so
"19/19 maneuvers vetted" — a claim about setpoints — read as a claim about separation. The runbook's
proof standard asked whether avoidance was *exercised*; it was, and the exercise revealed that the
loop's success metric did not exist.

From the first accepted DIVERT (range 9.27 m) the vehicle gained **45 mm** across-track over six
ticks while closing 9.31 m along-track, still at 6.57 m/s at closest approach — moving away from its
own dodge target, because candidate 0° (straight away from the threat) is a full reversal, the one
escape ownship momentum forbids in a head-on closure with 1.56 s of cylinder warning.

## Not a one-off

`live_flight_log_20260818T144711Z.json` — a different flight five days earlier, on executor code that
predates the latch/relatch machinery entirely — reproduces the same failure at **CPA 0.0597 m**
against the same static bird. Two independent flights, same mode. The gap is in the control law, not
in the logging added afterwards.

## What is being done

* **R1 (this change, shipped):** CPA is now computed by `check_live_flight_log.py` for every log on
  every run and printed whether or not it is in breach — the metric now exists.
* **R2 / R3 / R5:** control-law changes (`lateral_tree_margin_m`, a degenerate-range flag and
  relatch refusal, an ArduPilot `FENCE_*` backstop) are deliberately held behind their own live
  gate — the next avoidance flight, which must assert `CPA >= min_bird_clearance_m`, every
  `swept_tree_clearance_m >= 1.0`, and no relatch below 1.0 m range.
* Pinned bit-for-bit in `tests/fieldguard_planning/test_degenerate_range_avoidance.py` (36 tests).
  The paired xfail that stood for this bar has been retired — on a frozen artifact it could never
  activate — and the bar is now enforced live by `check_live_flight_log.py` plus this marker; the
  retirement is pinned in
  `test_the_bird_clearance_bar_this_log_missed_is_carried_by_a_live_gate_and_a_marker`.

Full record: `docs/DECISIONS.md`, ADR-013 amendment 12.
