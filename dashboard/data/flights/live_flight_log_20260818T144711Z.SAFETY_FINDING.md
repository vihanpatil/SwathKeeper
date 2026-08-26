# ACKNOWLEDGED SAFETY FINDING — closest approach 0.0597 m (ADR-013 amendment 12, S1)

**This log is kept as recorded history. It is NOT evidence of a safe flight.**

`scripts/check_live_flight_log.py` reports this file as **ACKNOWLEDGED**, not VALID, because of
this marker.

## The number

| | |
|---|---|
| closest point of approach (horizontal) | **0.0597 m** to `demo_bird_0` |
| policy bar (`PolicyParams.min_bird_clearance_m`) | **3.00 m** |
| detections / maneuvers | 61 / 61 |
| coverage ledger | 513 covered / 207 debt (honest debt, ADR-002 v1 bar) |

## Why this marker exists separately from the 2026-08-23 one

Amendment 12 was written against the 2026-08-23 encounter. This log — five days earlier, and on
executor code that predates the latch/relatch machinery (its event stream has no `latch` or
`relatch` kinds at all) — was found in breach by R1's very first run over the committed evidence
set, at **0.0597 m** against the same static `demo_bird_0` at (30, 30, 15).

That matters for how S1 is read: the closest-approach gap is **not** an artifact of the re-latch
logic introduced later, and not a one-off of a single encounter. Two independent flights, five days
and one executor revision apart, flew ~6 cm from the threat with every gate green. The defect is in
the control law's escape geometry, which is what R2/R3 address behind the next avoidance flight's
gate.

Full record: `docs/DECISIONS.md`, ADR-013 amendment 12 (S1), and the sibling marker
`live_flight_log_20260823T004031Z.SAFETY_FINDING.md`.
