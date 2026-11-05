---
name: booking-speed-enforcement
description: How a booked mission speed reaches the air (launcher --booking) and the two-sidecar split agreed with the flight-log gate, 2026-09-07
metadata:
  type: project
---

The depth commissioning booked a dodge take at 5.0 m/s and **nothing enforced it** — the fly recipe
set no `WPNAV_SPEED`, so flights ran ArduCopter's default (10.58 m/s peak, 2026-09-06 test-flight),
a speed at which the same booking gate exits 1. Closed 2026-09-07 from two sides at once:

* **devops (mine):** `scripts/fly_pipeline.sh --booking <booking_gate_*.json>` (env
  `SWATHKEEPER_BOOKING`) reads the artifact through the GATE'S OWN `load_booking` and injects
  `param set WP_SPD <m/s>` into the recipe. **The parameter is `WP_SPD`, in m/s** — the first cut
  typed `WPNAV_SPEED <cm/s>`, a name RETIRED at ADR-004's pinned ArduPilot SHA, so MAVProxy
  rejected the line and the take flew the 10 m/s default while four artifacts claimed 5.0 (QA
  G135). OPTIONAL (NDVI/demo book nothing), MANDATORY for a dodge take.
* **flight-software (parallel):** `check_live_flight_log.py --booking` measures the flown MEDIAN
  airborne ground speed from the log's own poses against the booked one (tolerance 1.10).

**Two sidecars, on purpose — do not "unify" them:**
* launcher writes `eval/results/live_flight_booking_<UTC>.json` at **bringup** (a note of what this
  bringup booked: artifact path, speed, recipe line). It CANNOT use the log stem — the avoidance
  node stamps its log minutes later, so the stem does not exist yet.
* the gate reads `<log-stem>.booking.json` beside the log (a **copy of the booking artifact**,
  validated by `predict_forward_lead.validate_report`) or the explicit `--booking` flag, which is
  the contract. The launcher's sidecar is how an operator recovers the artifact path for it.

**How to apply:** the injected line is the *only* speed enforcement before takeoff and it is typed
at the prompt, i.e. skippable — the post-flight flown-vs-booked gate is what makes that acceptable.
Setting WPNAV_SPEED also caps the GUIDED escape's NE velocity, which the booking gate already models
(`plant.t_req_s_at_mission_speed_cap`, `speed_cap_changes_t_req`); it does not bind at 5.0 m/s.
Adding the parameter trips the point-mass validity scanner — see
[[tuning-scanner-blocks-flight-params]].
