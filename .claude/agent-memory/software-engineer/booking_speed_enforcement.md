---
name: booking-speed-enforcement
description: The booking↔flown-speed binding (QA G128/G135/G138) — the parameter is WP_SPD in m/s not WPNAV_SPEED in cm/s, the TWO gated medians (whole flight AND encounter window) and why the first one cannot see the failure, the launcher reading through load_booking, the measured 2026-08-25 numbers
metadata:
  type: project
---

Two halves of one hole, both closed 2026-09-07: a booking authorises **one mission speed**, and
until this landed nothing set it and nothing checked it.

**Why:** `eval/results/booking_gate_20260907T064136Z.json` says BOOKABLE at **5.0 m/s** (margin
1.780x). No waypoint-speed parameter existed anywhere in the repo, so ArduCopter's default flew every
mission — the 2026-09-06 scripted test-flight peaked at **10.576 m/s**, where the same gate exits
**1** (margin 1.216x). A dodge take flown faster than booked is not the authorised take, and the
evidence gate printed a green GT-CPA either way.

**THE PARAMETER IS `WP_SPD`, IN m/s** — not `WPNAV_SPEED` in cm/s (QA G135, 2026-09-07; the first
cut of this feature typed the wrong name, in units wrong by 100x, and four artifacts asserted the
take was booked while MAVProxy rejected the line and the vehicle flew its default). Sourced at
ADR-004's pinned ArduPilot SHA `9895756d874e`, re-read them if the pin moves:
`ArduCopter/Parameters.cpp:368-370` = `// @Group: WP_` / `GOBJECTPTR(wp_nav, "WP_", AC_WPNav)`;
`AC_WPNav.cpp:17` = `// 0 was SPEED` (WPNAV_SPEED is RETIRED at this SHA); `AC_WPNav.cpp:49-56` =
`@Param: SPD / @Units: m/s / @Range: 0.10 20.00`; `AC_WPNav.cpp:8` = `WP_SPD_DEFAULT 10.0f`, the
speed an unbooked flight flies. **Never assert an ArduPilot parameter name by reasoning from this
repo's own comments** — `WPNAV_SPD`/`WPNAV_ACC` in `eval/point_mass.py` are shorthand prose, not
parameters. `curl` the two files at the pinned SHA; it costs seconds.

**How to apply:**

* **`check_live_flight_log.py --booking <booking_gate_*.json>`**, or a `<log-stem>.booking.json`
  sidecar beside the log (`booking_path_for`, resolved exactly like `marker_path_for`). The FLAG is
  the contract; the sidecar is the convenience and is named off the **log's stem** because that is
  the only join key that exists and it survives the log being copied into a tmp tree. Both present
  and disagreeing on speed = `TWO BOOKINGS FOR ONE TAKE` → INVALID (the `AMBIGUOUS TAKE` doctrine).
* **`fly_pipeline.sh --booking` writes `eval/results/live_flight_booking_<UTC>.json`
  (`kind: "live_flight_booking"`) — that is a bringup POINTER, not an authorisation** (artifact path
  + booked speed + recipe line, stamped with the BRINGUP time). `load_booking` refuses it BY NAME and
  prints the artifact it names; reading it would let a two-field JSON book a flight.
* **Only an artifact that exited 0 may be bound.** `load_booking` runs
  `predict_forward_lead.validate_report` (lazy import — pfl imports `max_bird_speed_m_s` from the
  gate at module scope, so the gate may only import back inside a function) and then requires
  `verdict.bookable`. A `--sweep` or a config-sourced exit-3 design check authorises nothing.
* **TWO gated medians, one bar (`booked * 1.10`): the whole flight AND each encounter window.**
  Horizontal ground speed from the log's own `flown_path_enu` + `run.tick_stamp_sim_s` — no new
  instrumentation, and the parameter that was supposed to be set cannot vouch for itself. Per-STEP
  predicate (both ends `z > 1.0 m`, dt > 0), not a contiguous window: a take with two airborne runs
  would otherwise fold the parked gap into the median, optimistically. 10 % because the waypoint
  speed is a **cap** that transients cross.
  **The whole-flight median CANNOT see the failure it exists for (QA G138, 2026-09-07)** — on a
  boustrophedon most airborne ticks are turnarounds, so the 2026-08-25 take reads **3.417 m/s
  (0.683x a 5.0 booking, a comfortable pass)** while its one encounter (takeover 991 → resume 995,
  4 steps, 0.434 s) ran at a median **9.012 m/s = 1.802x booked**, a speed at which the booking gate
  exits 1. That flip is regression-pinned on the REAL committed artifacts in
  `TestTheCommittedTakeIsTheRegression`. `encounter_windows(log, n_ticks)` delimits the window from
  the flight's own takeover/resume events — **no ±N padding**, because a window nobody logged is a
  window somebody chose and this one is gated; a re-latch inside an open encounter does not open a
  second window, and an unclosed takeover runs to the last tick. `airborne_ground_speed` takes an
  optional inclusive 1-based `tick_range`, so ONE function serves both statistics.
  **Optional for the launcher, mandatory for a dodge take**: no booking + an armed detector prints a
  loud WARNING (never a failure — that would redden two committed flights); `detector.source ==
  'none'` (the NDVI survey) gets a plain note. A booking bound to a log whose speed is unmeasurable,
  or to a pre-seam legacy log (no `run` block ⇒ no time axis at all), is INVALID: unverifiable is not
  verified. A speed failure lands in `problems`, so a SAFETY_FINDING marker can never acknowledge it.
* **The one real avoidance take, measured: `live_flight_log_20260825T210402Z` flew median 3.417 /
  p90 9.006 / max 12.523 m/s** (1103 of 1857 steps scored, 1106/1858 ticks airborne, 129.1 s of sim
  time). Against a 5.0 m/s booking the gate would PASS it. Re-evaluating the booking at those
  speeds: 3.417 → 2.051x exit 0, 9.006 → **1.335x exit 0**, 10.0 → 1.257x exit 1, 12.523 → exit 1.
  The tail was the clue and it was right: p90 9.006 = 1.801x and max 12.523 = 2.505x booked, and the
  encounter really did land in the tail. p90/max stay printed-not-gated (a p90 on a boustrophedon is
  turnaround geometry, not a violated cap), and the ENCOUNTER-window median is the gated version of
  that concern.
* **The mission-speed cap is now a CHECK in the booking gate** (`escape_survives_mission_speed_cap`,
  QA G127): the 1.3x bar re-run against the plant a `WP_SPD` of `--speed` implies. Below
  **0.788 m/s** on the booked live set the tool used to print PASS/BOOKABLE plus
  `NOTE: ... Re-derive before booking` — an instruction to a human under the exit code saying none
  was needed (0.6 m/s: headline 2.810x, cap-honest 1.064x). The cap-honest margin is **non-monotone**
  (peaks ~2.61 m/s at 2.106x). Above ~3.86 m/s the two readings are identical, so it can never fail
  a speed the uncapped reading would not. **5.0 m/s is unaffected.**
* **Booking-gate artifact schema is 1.3** (additive over 1.2): `sensor.config_relpath` (null outside
  the repo) and `fx_px_exact`/`fy_px_exact`/`cx_px_exact`/`cy_px_exact` as **strings** so no reader
  can re-round them. `validate_report` requires 1.3's fields only OF a 1.3 artifact, so the committed
  1.2 one stays valid untouched — it is the record of what authorised the flight and is never
  regenerated.
* **`AIRBORNE_Z_M = 1.0` now exists in THREE places** — `clip_recorder` (the owner, but it imports
  numpy and the gate is stdlib-only), `build_dashboard_data.airborne_window` (which imports the gate,
  so the gate cannot import it back), and `check_live_flight_log`. Pinned equal by
  `test_check_live_flight_log_booking.py`. If a fourth appears, move it to a stdlib-only `src/`
  module instead.
* **The launcher reads a booking through the GATE'S OWN `load_booking`** (QA G137) — one definition
  of "does this authorise a flight", so the pre-flight and post-flight ends cannot accept different
  sets. There is deliberately **no weaker fallback**: an unimportable gate is a refusal, because
  only a dodge take passes `--booking` and a booking nothing can validate authorises nothing. The
  reader's stdout is the ONLY parsed stream and stderr is never merged into it (QA G136: `2>&1` +
  positional `read` + `printf %s` once put `param set WPNAV_SPEED import _imp # builtin` into the
  recipe under `PYTHONVERBOSE=1`); the last two lines are taken and hard-validated as a decimal.
* **The tuning scanner (`replay_point_mass._tuning_override_scan`) flags any
  `param set WP_*`/`WPNAV_*`/`GUID_*`/`PSC_*` even in PROSE**, and `WP_` was added when the booked
  line landed. `WP_SPD` is now the repo's ONE **warranted** override (`WARRANTED_OVERRIDES`, keyed
  by parameter NAME, never by path): the scan reports it with its consequence (a booked flight's
  `v_max_ne_mps` is its booked speed, not 10.0) instead of claiming the repo is clean, and any other
  key still produces the loud statement. All three replayed encounters predate the booking, so
  `eval/point_mass.py`'s constants are still what flew on them. Write "the waypoint-speed parameter"
  in prose to avoid a false hit. See [[forward-depth-booking-gate]] for the gate itself and
  [[evidence-consumption-seams]] for the other gate functions to call.
