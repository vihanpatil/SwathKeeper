---
name: forward-depth-booking-gate
description: The ADR-019/020 forward depth camera — /fg/depth/* topics, the Euclidean-far-cull vs Z-depth asymmetry that sets the 47.56 m corner horizon, the booking gate's six-number live CLI contract, the ONE corner-ray primitive, and why a sweep can never authorise a flight
metadata:
  type: project
---

The second aperture (forward `depth_camera`, ADR-019, commissioned live 2026-09-06 as ADR-020
am. 1). It is what buys detection lead time the nadir NDVI camera geometrically cannot.

**Why:** nadir gives ~0.4 s of warning (see [[flight-20260825-lead-time]]) and ADR-017 am. 1 measured
that NO nadir mission speed is safe; the forward sensor is the fix, and no dodge flight books
without `scripts/predict_forward_lead.py` exiting **0** on live-measured inputs.

**How to apply:**

* **Topics:** `/fg/depth/image` (32FC1, pinhole **Z-depth in metres**, 640x480x4 = 19 SHM
  fragments) and `/fg/depth/camera_info`. The camera_info topic name is **DERIVED, not declared** —
  `DepthCameraSensor::Load` never reads `<camera_info_topic>`; gz pops the last segment of
  `<topic>` and appends `/camera_info`. Emitting that element would be dead config that looks live.
* **The two culls are NOT symmetric, and this is the fact everything downstream turns on.** gz culls
  NEAR on the stored Z-depth but FAR on the **Euclidean** length of the camera-space point, while
  the value stored is Z-depth. So the effective Z horizon is `far / |ray|`, shortest at the frame
  corner: with `far` 60 m and this mount's live intrinsics that is **47.56 m**, not 60. Measured in
  the render (D2 CULL, 57.99 m at |ray| 1.034), not only source-read.
* **`|ray| = sqrt(1 + (max(cx, W-1-cx)/fx)^2 + (max(cy, H-1-cy)/fy)^2)` — the FARTHEST corner.** Not
  `cx`/`cy` (an off-centre principal point makes the near corner give a longer, unmeasurable
  horizon), not `/fx` for the vertical term, and W/H must come off the same live camera_info. All
  three errors are optimistic; QA probe C (2026-09-06) found the old spelling exiting **0 BOOKABLE**
  at a live `cy` of 120 against a 50.14 m bound where the truth is 44.05 m. It used to live in
  **three** hand-written copies (three gates, three interpreters, three input sources) — and two of
  the three were wrong at once, so "deliberate duplication, pinned equal by test" was tried and
  measured: it drifts. Since 2026-09-07 there is **ONE**:
  `fieldguard_planning.depth_detect.corner_ray_ratio(width_px, height_px, fx, fy, cx, cy)`, imported
  by `predict_forward_lead.py`, `check_depth_mount.py` (re-exported, so
  `check_depth_mount.corner_ray_ratio` still resolves) and the in-render
  `verify_depth_mount_geometry.sh` off `/workspace/fieldguard/src`. It raises on `fx<=0`/`fy<=0`/a
  frame under 2 px — the .sh calls it inside its parse `try` so a degenerate live set falls back to
  config instead of exiting 1, which its exit table sells as a MOUNT failure. It lives in `src/`
  because that is the only tree all three gates can import.
* **The threat band's binding half-extent is `min(cy, H-1-cy)`, not `cy`** (fixed 2026-09-07). The
  ±6 m band is symmetric about the optical axis, so it must fit ABOVE and BELOW it: 240 rows above
  cy=240 but only **239** below, in a 480-row frame. `band_covered_from_m(fy, cy, H, band_half)`.
  The published number moved **13.00 → 13.05 m** (13.0545 exactly). Verdict-invariant here (33 m of
  slack under the required horizon) and unbounded in general — at cy=400 the honest range is 5x
  what `cy` alone prints, always in the optimistic direction.
* **The booking gate's live input set is SIX numbers off ONE camera_info** (`--fx` K[0], `--fy` K[4],
  `--cx` K[2], `--cy` K[5], `--width`, `--height`) plus `--acq-range-m`. Any part of the set, or a
  live `WxH` that disagrees with `config/depth_camera.json` (which *generates* the world SDF), is
  exit **2** — a refusal, never a statement about the sensor.
* **`--sweep` CHOOSES a speed and authorises nothing: it exits 3 however live its inputs** (1 if no
  row passes), its rows print `PASS*` and never `BOOKABLE`, and both the artifact's top-level
  verdict and every row carry `bookable: false` — `validate_report` refuses a sweep that claims
  otherwise and recurses into the rows with the same schema-1.2 field requirement. Two earlier
  spellings leaked exit 0 out of a mode whose subject is a RANGE of speeds: "any row passed" (on
  config numbers), then "every row passed on live inputs" (`--sweep 4:5:1` exited 0 saying nothing
  about which speed would be flown). Only a single `--speed` run on the full live set authorises.
* **`--acq-range-m` takes D3's BOOKABLE range, never its optical prefix** (ADR-020 am. 1): in a
  sky-backed noiseless scene the optics out-resolve any far clip, so the prefix is a resolvability
  FLOOR that says more about the scene than the horizon. Schema **1.2** records the prefix and
  whether the booked number was clamped from it. Live 2026-09-06 at 5.0 m/s: 46.0 m -> exit 0,
  margin **1.780x**; 58.0 m (prefix) -> exit 1 on the corner check alone, at every speed.
* **A booking authorises ONE SPEED and the flight has to be flown at it** — the launcher injects it
  and `check_live_flight_log --booking` measures it back off the poses. See
  [[booking-speed-enforcement]]; the artifact schema is **1.3** since 2026-09-07 and `checks` carries
  a fourth entry, `escape_survives_mission_speed_cap`.
* **The committed D4 artifact is `eval/results/booking_gate_20260907T064136Z.json`** (un-ignored in
  `.gitignore`, read by a hard-asserting host test, `tests/fieldguard_planning/
  test_booking_gate_artifact.py`): 5.0 m/s, margin 1.780x, acq 46.0 m clamped from a 58.0 m prefix,
  exit 0. Its **`band_covered_from_m` says 13.00 m and today's code says 13.055** — it predates the
  half-extent fix. Verdict-invariant, pinned as a named drift rather than regenerated: re-running D4
  writes a NEW timestamped file and the ratified one is the record of what authorised the flight.
* **The CLI is copy-pasted, not generated, in two other files** — the command line
  `verify_depth_mount_geometry.sh` prints after a passing D3, and
  `docs/runbooks/AVOIDANCE_REAL_DETECTION.md` §0f. Any change to the gate's flags must move them
  too, or the operator pastes a set that refuses on flight day.

See [[node-topic-map]] for the rest of the sensor/topic map and [[plant-model-and-confound]] for the
plant this gate's `t_req` comes from.
