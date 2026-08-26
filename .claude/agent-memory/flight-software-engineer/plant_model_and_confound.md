---
name: plant-model-and-confound
description: What the 2026-08-25 point-mass replay measured — the real ArduCopter GUIDED command path (GUID_OPTIONS=0 takes PosControl seeded from WPNAV), the effective accel limit (1.05-1.85 vs 2.5 default), which flights the command path actually moved, and the ADR-017 speed sweep answer (no safe speed exists)
metadata:
  type: project
---

Built 2026-08-25 as ADR-016 / Council Ruling 001's confound-resolver: `eval/point_mass.py` (the
plant) + `eval/replay_point_mass.py` (the study) + `tests/test_point_mass_replay.py`. It replays the
three committed live flights through a jerk/accel/velocity-limited point mass to separate candidate
ordering, warning time and plant compliance.

**THE COMMAND PATH, traced at the pinned firmware SHA — and it is neither of the two obvious
answers.** `/ap/cmd_gps_pose` -> `AP_DDS_External_Control::handle_global_position_control` ->
`AP_ExternalControl_Copter::set_global_position` -> `Copter::set_target_location` ->
`ModeGuided::set_destination(Location)`. There `use_wpnav_for_position_control()` reads GUID_OPTIONS
bit 6, **CLEAR at the default 0**, so the command takes the **AC_PosControl** path — but
`pva_control_start()` immediately seeds PosControl's limits **from AC_WPNav's parameters**
(`NE_set_max_speed_accel_m(wp_nav->get_default_speed_NE_ms(), wp_nav->get_wp_acceleration_mss())`,
mode_guided.cpp ~255-260). So the limits that actually flew are:
WPNAV_SPD **10 m/s**, WPNAV_ACC **2.5 m/s^2**, WPNAV_SPD_UP 2.5, WPNAV_SPD_DN 1.5, WPNAV_ACC_Z 1.0,
with PosControl's own **PSC_NE_JERK 5 m/s^3** and PSC_NE_POS_P 1.0. ANGLE_MAX 30 deg -> the physical
ceiling a = g*tan(30) = **5.66 m/s^2**. WPNAV_JERK (1.0, the minimum of its range) is **NOT** on this
path — it only shapes AC_WPNav's S-curve. Parameter names moved in this firmware:
WPNAV_SPEED->WPNAV_SPD, WPNAV_ACCEL->WPNAV_ACC, PSC_JERK_XY->PSC_NE_JERK.

**Q1 — THE HEADLINE, after adversarial QA (2026-08-26): "the command path demonstrably MOVED the
aircraft on 08-23; demonstrably did NOT on 08-18; 08-25's 0.434 s window CANNOT TELL."** Scored as
three rival hypotheses (H_broken = the command did nothing / H_plant = default-limited point mass /
H_compliant = reached the setpoint) against the displacement projected on the COMMANDED direction,
replaying the setpoints actually sent.
* **2026-08-23: FIT.** rms 0.50 m against 21.8 m of travel (2.3 %) at 0.16 s/tick. The vehicle
  decelerated from ~9.5 m/s exactly as an accel-limited plant does.
* **2026-08-25: UNANSWERABLE, and this is the finding, not a caveat.** rms says 1.5 % but the
  0.434 s window separates H_plant from H_broken by **5 mm = 0.56 telemetry quanta**. The flown ENU
  axes are quantised by the geodetic round-trip at **E 0.009078 m / N 0.011131 m** on all three
  flights, so the famous "0.018 m displacement" is 2 LSBs. The two command modes return OPPOSITE
  argmins off the same telemetry — which IS what "cannot tell" looks like. A low rms on a window
  where every hypothesis tracks the path to within the quantum is evidence for none of them.
* **2026-08-18: NO-FIT under every plant, every tick period 0.05-0.40 s AND every entry-velocity
  window 0.3-2.0 s** (best ADMISSIBLE cell 40.3 %; the 14.2 % "best" sits at dt 0.05 s, which
  implies a 17.6 m/s cruise against WPNAV_SPD 10 — inadmissible). Commanded 10 m south for 61
  ticks, the vehicle flew **14.5 m NORTH**. Not plant-limited; the command appears to have had no
  effect (mode switch not honoured is the obvious unverified candidate). **Do not pool it with the
  other two** — "84 maneuvers / 0.5-4 %" mixes two different failure modes.
* **Effective accel limit: the vehicle behaved as if a_max_NE = 1.05 m/s^2 against the 2.5 m/s^2
  default.** ESTIMATED, from ONE admissible axis of ONE flight (08-23 @ 0.20 s/tick). The 1.85
  upper endpoint originally published came from that flight's 0.16 s axis, which implies a
  **12.31 m/s** cruise against WPNAV_SPD 10 — an axis the plant forbids. **Time axes are now
  admissibility-filtered**: implied cruise = p99 step / dt must be ≤ WPNAV_SPD, calibrated against
  the one real-clock flight, which scores **1.01×** on that heuristic (so 1.23× is a solid
  exclusion, not a borderline one). Inadmissible axes stay visible, never aggregated.
* **POSCONTROL_BARE IS RULED OUT BY THE FLIGHTS, not just by the source trace:** its 5.0 m/s speed
  cap forbids the 9.16-9.52 m/s the vehicle demonstrably held (rms 1.08 m vs 0.06 m on 08-25).
* **The 0.54 % compliance figure is 2/3 CRUISE LEAK.** `d·cmd` decomposes exactly into a cross-track
  dodge term and the along-track cruise leg seen through the angle between the command and the
  track normal. On 08-25: +0.0541 m = **+0.0182 m real dodge** + 0.0360 m of the −3.95 m cruise leg
  through a 0.52° misalignment. Quote cross-track, never along-command.

**A REAL MODELLING TRAP, found by building this.** The 2026-08-18 log predates the latch: every tick
re-placed the setpoint at `drone_xy + 10 m * away_unit` from wherever the vehicle then was, so the
commanded point **receded 34.5 m** over the window. Replaying that schedule through a plant that
OBEYS makes it chase its own target. The study therefore runs two command modes (`as_commanded`,
primary and faithful; `latched_first`, state-independent) and reports both.

**Q2 — HOW MUCH LEAD AN ESCAPE NEEDS. Report it TWICE or it is wrong.** On the 2026-08-25
encounter the earliest **PHYSICALLY** resolving lead is **1.25 s** (angle_max_ceiling,
sidestep_ahead ±90) and the earliest **LEGALLY** resolving lead is **2.0 s** — against 0.175 s of
sensor lead measured. The 60 % gap is the policy's own swept-path tree vet, which is **XY-only**
(`GeofenceMap.segment_clearance`; `is_safe_3d` is the altitude-aware query): on lane x=15 the drone
sits up to 1.99 m inside an orchard exclusion column while flying 15 m over a 3.5 m canopy, so even
BRAKE is booked illegal at leads 0.5-1.75 s. **Take the PHYSICAL number for a sensor-horizon spec**
— quoting the legal one overstates the requirement by 60 %.
Three other things a cell must survive to count:
* **COVER THE ENCOUNTER.** The bird arrives at a fixed sim instant, so a counterfactual window must
  CONTAIN it. An equal-duration-after-the-command horizon (a fix for a QA finding that was itself
  wrong, retracted) ended a lead-3.0 cell 0.434 s past takeover on 08-25 — before the bird arrived
  — and 32 cells flipped to "resolved" off encounters that were never simulated. That is the same
  vacuous green as the band-exit bug, relocated from vertical to temporal scoping. The end is
  ABSOLUTE; longer leads simulate LONGER, and `all_cells_cover_flown_cpa` asserts it.
* **PASSED** — the bird must end up behind. Retreating from a static obstacle opens distance while
  DEFERRING the encounter; 65 cells on 08-25 alone clear the bar that way.
* **IN BAND** — `ground_truth_cpa` is vertically scoped, so a CLIMB that leaves the ±6 m band mid-
  encounter reports the last in-band instant as its CPA. Measured: climb cells reported 5.35 /
  14.77 / 14.34 / 28.08 m while the true horizontal minimum to bird_0 was 0.78 / 0.17 / **0.014** /
  0.50 m. That is exactly ADR-013 am. 18's pre-registered vacuous green, and it would have promoted
  "climb" into the resolving list off a 14 mm pass. Band exits are now BAND-EXIT, never clearance,
  and every row prints `min_horizontal_threat_m` (worst..best) beside the scoped CPA.

**Q3 — THE ADR-017 SPEED SWEEP: THERE IS NO SAFE SPEED. Tripwire FIRES.** Nadir half-footprint at
the threat bird's own 4.03 m depth is **2.480 m along-track** (from the take's LIVE camera_info,
fx 520.006, 640x480 — reproduces ADR-013 am. 18 exactly). bird_0 closes head-on at 6.002 m/s on the
same lane, so:
* max lead = 2.480 / (v_mission + 6.002); at 2-10 m/s that is 0.31 -> 0.155 s;
* best lateral escape in that lead is **0.099 -> 0.012 m** at the ANGLE_MAX ceiling, against a 3.00 m
  bar. Not one cell of the sweep clears, on any plant.
* **It is not fixable by slowing down: the closing speed floor is the BIRD's own 6 m/s**, which caps
  lead at 0.413 s even from a hover, worth 0.228 m of escape.
* What the geometry would have to supply instead: **27.3 m of forward sensing at 9.2 m/s** (14.3 m
  even at 2 m/s) for the default plant; 17.8 m at the ANGLE_MAX ceiling.
* A climb needs 1.97 m to leave the ±6 m band = 1.35-2.08 s, also far beyond the lead, and its
  "pass" would print NONE-IN-BAND anyway.
* **Three attacks on the verdict, all survived and carried IN the artifact** (`tripwire.
  robustness_attacks`): (a) sweeping ALTITUDE across the whole ±6 m band buys at most **0.654 m** at
  the band edge, 4.59x short, and the ceiling plant would need **11.39 m** of depth — outside the
  band, where the pair is not a threat by the policy's own definition; (b) the along-track axis is
  taken as max(half_x, half_y), which is OPTIMISTIC and therefore conservative for a NEGATIVE
  verdict (the pessimistic reading is 1.86 m); (c) ANGLE_MAX raised to 45° gives **0.2351 m** at the
  hover lead, **12.8x** short.

**WHAT MAY BE QUOTED.** Q3 is CONFIRMED by adversarial QA and may be quoted as measured. Q1 and Q2
are quotable only in the corrected forms above — the pre-2026-08-26 versions printed "the command
path moved the aircraft on 3 of 5 windows" (counting an unanswerable window as True), let a MARGINAL
window print FIT, credited climb band-exits as clearances, and reported only the legal lead.

Related: [[flight-20260825-lead-time]], [[node-topic-map]], [[detection-seam]]
