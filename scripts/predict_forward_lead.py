#!/usr/bin/env python3
"""THE ADR-019 BOOKING GATE: does the forward depth camera buy enough lead to clear the 3.00 m bar?

Answers in ~0.2 s, on the host, with no Docker session -- and nothing may book the dodge flight
until it says PASS on LIVE-MEASURED inputs.

WHY THIS EXISTS (Council Ruling 002 tripwire (a), ADR-019 item 6, ratified 2026-08-26). The
R-series discipline -- "an honest FAIL ranks the next fix" -- was right for discovery and is over.
The next avoidance take is DESIGNED TO PASS: "if it books under this gate and still fails, that is
a PLANT-MODEL finding (TG register) -> Ruling 003 before any second attempt, not another re-fly."
This tool is the thing that decides whether it books.

WHY A SIBLING OF `predict_bird_visibility.py` AND NOT A FLAG ON IT. Three reasons, in order of
weight: (1) that tool's exit code already MEANS "the birds are/are not in the nadir frame", and the
2026-08-25 take is what a second meaning on one exit code costs -- exit 2 was added there precisely
to stop "I had no speed" reading as "the birds are visible"; (2) ADR-019 item 7 FREEZES all NDVI
work for the duration of this push, and the nadir predictor is NDVI's tool; (3) this gate's inputs
(`eval/point_mass`, `PolicyParams`, `config/depth_camera.json`) are all new dependencies the nadir
tool has no business acquiring. Same house style, separate tool, separate verdict.

WHAT IT COMPUTES -- and every number is IMPORTED from whoever owns it, never restated:
  bar          `avoidance_policy.PolicyParams.min_bird_clearance_m`        3.00 m
  plant        `eval/point_mass.GUIDED_DEFAULT`                            ADR-019 names this plant
  t_req        `eval/point_mass.time_to_displace_s(bar, plant)`            the ONE plant model
  bird speed   `check_live_flight_log.max_bird_speed_m_s(...)`             from the birds config
  frame period `config/depth_camera.json camera.update_rate_hz`
  tick latency `config/depth_camera.json booking_gate.control_tick_latency_s` (measured, n=1855)
  margin       `config/depth_camera.json booking_gate.lead_margin_factor`  1.3, from ADR-019

    need_s     = t_req + (1/rate + control_tick)      time from "photons hit the sensor" to "3.00 m"
    lead_s     = acq_range_m / (mission_speed + bird_speed)      what the geometry actually gives
    margin     = lead_s / need_s          PASS iff margin >= 1.3

THE MISSION-SPEED CAP IS A CHECK, NOT A NOTE (QA finding G127, closed 2026-09-07). A mission flown
at `v` is flown with WP_SPD = v (the waypoint speed at ADR-004's pinned SHA, in m/s), i.e. a plant
whose velocity limit is `v` -- and below ~3.86 m/s
the 3.00 m escape RUNS INTO that limit, so `t_req` lengthens and the headline margin (computed on the
uncapped plant) overstates the escape it describes. Until this check existed the tool printed
`NOTE: ... MOVES t_req to 5.326 s ... Re-derive before booking` and then exited **0 BOOKABLE** on the
same run: an instruction to a human sitting on the exit code that says the human need not act.
Measured on the booked live set (acq 46.0 m): below **0.788 m/s** the printed margin clears 1.3x
while the cap-honest one does not (0.6 m/s: printed 2.810x, cap-honest 1.064x). `checks` now carries
`escape_survives_mission_speed_cap` -- the SAME margin bar re-run against the capped plant -- so the
verdict has to hold under both readings. Above the cap the two are identical and the check restates
`lead_margin`; it can never fail a speed the uncapped reading would not. Note the cap-honest margin
is NON-MONOTONE in speed (it peaks near 2.61 m/s at 2.106x and falls both ways), which is why it is
gated rather than reasoned about.

THE CONSERVATIVE READING OF "1.3x", stated because the other one is defensible and gives a
different answer: pipeline latency is inside the multiplied quantity (`1.3 * (t_req + latency)`),
not subtracted from the available lead before multiplying (`lead - latency >= 1.3 * t_req`). The
second form is more lenient -- it passes 10.0 m/s where this one fails it -- and the gate exists to
stop a flight being booked on optimism, so the stricter reading wins. Named here so nobody has to
reverse-engineer which one produced a published margin.

WHY IT REFUSES TO CALL A CONFIG-SOURCED PASS "BOOKABLE" (exit 3). ADR-019 item 6 says the forward
horizon comes "from the new sensor's own `camera_info`, never from config prose". The default
acquisition range in this tool is a GEOMETRIC UPPER BOUND -- pinhole optics times the adopted
morphology's 2.0 px floor -- and gz runs `SetAntiAliasing(2)` on the depth camera, whose effect on a
4-px target at 46 m nobody has measured. So a run on config numbers is a DESIGN check, and it exits
3: not FAIL, not bookable. Measure the horizon in the render (docs/runbooks/FORWARD_DEPTH_SENSOR.md
gate D3), pass `--acq-range-m` plus the six live `camera_info` numbers, and re-run for exit 0.

    exit 0  PASS and BOOKABLE      (single --speed, full live input set, margin >= 1.3)
    exit 1  FAIL                   (a check failed -- do not book, at this speed)
    exit 2  REFUSAL                (nothing was decided: no --speed, garbage input, or part of a
                                    live intrinsic set. Never confusable with a verdict about the
                                    sensor)
    exit 3  PASS but NOT BOOKABLE  (config-sourced inputs, or a --sweep in which SOME row passes --
                                    the design is sound, the flight is not authorised)

A `--sweep` in which NO row passes exits 1, not 3: "PASS but not bookable" beside "no mission speed
in this range passes" would be one code carrying two meanings, which is the defect this whole file
is shaped around. So the sweep's exit is not unconditional -- the unconditional property is the one
below, that it can never be 0.

**EXIT 0 IS UNREACHABLE FROM `--sweep` AT ALL, AND UNREACHABLE ANYWHERE WITHOUT LIVE INPUTS.** That
is the property, and it is pinned by test. A SWEEP CHOOSES A MISSION SPEED; A SINGLE `--speed` RUN
AUTHORISES ONE. The first version returned 0 from `--sweep` whenever any speed passed, on config
numbers; the second required every swept row to pass on live inputs, which still let `--sweep
4:5:1` exit 0 -- an authorisation whose subject is a RANGE, printed as a table, while
FORWARD_DEPTH_SENSOR.md publishes "exit 0 = book the flight" and the flight is flown at one speed.
One exit code, two meanings, is precisely what the 2026-08-25 booking cost this project. The rows
of a sweep artifact carry `bookable: false` for the same reason, and `validate_report` REFUSES a
sweep artifact whose rows claim otherwise.

INPUT IS VALIDATED, NOT LAUNDERED. `--acq-range-m 100` (beyond the 60 m far clip) and even `inf`
used to produce exit 0 BOOKABLE; `--speed nan` used to exit 1, i.e. a typo read as a conclusion
about the hardware. Every malformed input is now exit 2.

INTRINSICS COME AS A SET OF SIX, OFF ONE `camera_info` MESSAGE. `fx` sets the acquisition range,
`fy`+`cy` set the band coverage, and `fx,fy,cx,cy,W,H` together set the frame-corner far-clip bound
-- so one live number beside one config number is an answer assembled from two different cameras.
Give all six (`K[0]`, `K[4]`, `K[2]`, `K[5]`, `width`, `height` of the SAME message) or none; any
part of the set is exit 2. And since the world SDF is GENERATED from `config/depth_camera.json`, a
live `WxH` that disagrees with the config's is not a discrepancy to average over -- it means the
wrong camera is being read, or the world is stale. Also exit 2.

THE FRAME-CORNER BOUND USES THE FARTHEST CORNER, NOT THE PRINCIPAL POINT. `|ray|` is built from
`max(cx, W-1-cx)/fx` and `max(cy, H-1-cy)/fy`: the pixel with the LONGEST slant ray, which is the
first one gz culls. The version this replaced used `cy/fx` for the vertical term -- it divided by
the wrong focal length, it assumed the principal point was the frame centre, and it never looked at
the farther half of the frame. At a live `cy` of 120 it published a 50.14 m corner horizon where the
true one is 44.05 m, and exited 0 BOOKABLE on a 50.0 m acquisition range (QA probe C, reproduced
2026-09-06). Every one of those three errors was optimistic in the same direction, which is why this
paragraph exists and why `--fy`, `--cx`, `--width` and `--height` are not optional.

USE
    python3 scripts/predict_forward_lead.py --speed 5.0                       # design check (3)
    python3 scripts/predict_forward_lead.py --speed 5.0 \
            --fx 520.0058046927554 --fy 520.0058046927553 --cx 320 --cy 240 \
            --width 640 --height 480 \
            --acq-range-m 46.0 --acq-optical-prefix-m 58.0                     # bookable check (0)
    python3 scripts/predict_forward_lead.py --sweep 2:10:0.5                   # pick a speed
    python3 scripts/predict_forward_lead.py --speed 5.0 --json eval/results/booking_gate.json

Dependency: stdlib only.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import replace
from pathlib import Path
from typing import List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "eval"))

from check_live_flight_log import max_bird_speed_m_s                    # noqa: E402
from fieldguard_planning.avoidance_policy import PolicyParams           # noqa: E402
from fieldguard_planning.depth_detect import (                          # noqa: E402
    MIN_RESOLVING_RADIUS_PX, acquisition_range_m, band_covered_from_m, corner_ray_ratio,
)
from point_mass import (                                                # noqa: E402
    GUIDED_DEFAULT, PLANTS, max_displacement_m, time_to_displace_s,
)

DEPTH_CONFIG = REPO_ROOT / "config" / "depth_camera.json"
BIRDS_CONFIG = REPO_ROOT / "config" / "birds" / "farm_world_birds.json"

EXIT_PASS_BOOKABLE = 0
EXIT_FAIL = 1
EXIT_REFUSED = 2
EXIT_PASS_NOT_BOOKABLE = 3

# Written into every sweep verdict -- the top-level one AND each row -- so the reason travels with
# the artifact instead of living only in the terminal the sweep was run in.
SWEEP_AUTHORISES_NOTHING = ("a sweep CHOOSES a mission speed and authorises nothing: exit 0 and "
                            "bookable:true come only from a single --speed run on the full live "
                            "input set (FORWARD_DEPTH_SENSOR.md gate D4)")

SCHEMA_VERSION = "1.3"          # 1.0 -> 1.1: top-level verdict on sweeps, corner far-clip, cx/cy
                                # 1.1 -> 1.2: fy/W/H + their sources, the farthest-corner bound it
                                #             actually used, and whether the booked acquisition
                                #             range was CLAMPED from a longer optical prefix
                                # 1.2 -> 1.3: a REPO-RELATIVE config path beside the absolute one,
                                #             and the four intrinsics at FULL precision beside the
                                #             4-dp ones (QA 2026-09-07). Purely additive: every 1.2
                                #             field is still written, so a 1.2 reader loses nothing.
READABLE_SCHEMA_VERSIONS = ("1.0", "1.1", "1.2", "1.3")

# The sensor fields each schema level PROMISES. Cumulative: a 1.3 artifact owes 1.2's as well.
# Checked by `validate_report` per version, so the committed 2026-09-07 artifact -- written before
# these existed -- stays readable AS a 1.2 artifact rather than being retroactively malformed.
SENSOR_FIELDS_1_2 = ("fy_px", "fy_source", "image_width_px", "image_height_px", "image_size_source",
                     "clip_far_at_frame_corner_m", "clip_far_corner_ray_ratio",
                     "clip_far_corner_pixel_uv", "acquisition_optical_prefix_m",
                     "acquisition_clamped_from_optical_prefix")
SENSOR_FIELDS_1_3 = ("config_relpath", "fx_px_exact", "fy_px_exact", "cx_px_exact", "cy_px_exact")

# Sane bounds for a live intrinsic. Not tuning knobs -- a rejection window wide enough that no real
# camera_info falls outside it and narrow enough that a transcription slip (a pasted `0`, a negative,
# a `nan` from an empty field) cannot become a verdict.
FX_RANGE_PX = (1.0, 1.0e5)
CXY_RANGE_PX = (1.0, 1.0e4)
WH_RANGE_PX = (2.0, 1.0e5)

# The live input set: every one of these comes off the SAME camera_info message, named by the field
# it is read from. Order is the order they are quoted in refusals.
LIVE_INTRINSIC_FIELDS = (("fx", "K[0]"), ("fy", "K[4]"), ("cx", "K[2]"), ("cy", "K[5]"),
                         ("width", "width"), ("height", "height"))


def _repo_relpath(path: Path) -> Optional[str]:
    """`<repo>/config/depth_camera.json` -> `config/depth_camera.json`; None for anything outside
    this repo. Schema 1.3: the artifact's `config` field is an absolute path carrying a home
    directory that is meaningless on any other machine, and a reader cannot tell from it whether
    the gate read THIS repo's config or a copy."""
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return None


def _fx_from(cam: dict) -> float:
    return (cam["image_width_px"] / 2.0) / math.tan(cam["horizontal_fov_rad"] / 2.0)


def _positive_finite(name: str, value: float, hi: Optional[float] = None,
                     lo: float = 0.0) -> float:
    v = float(value)
    if not math.isfinite(v) or v <= lo:
        raise ValueError(f"{name} must be a finite number greater than {lo:g}, got {value!r}. "
                         f"This is a REFUSAL, not a verdict: nothing was measured about the sensor.")
    if hi is not None and v > hi:
        raise ValueError(f"{name} must be <= {hi:g}, got {v:g}.")
    return v


def _positive_int(name: str, value: float, hi: float, lo: float) -> int:
    """`camera_info.width`/`.height` are uint32. A non-integral one is a transcription error, and it
    would silently move the frame-corner bound, so it is refused rather than rounded."""
    v = _positive_finite(name, value, hi=hi, lo=lo)
    if v != int(v):
        raise ValueError(f"{name} must be a whole number of pixels (camera_info width/height are "
                         f"uint32), got {value!r}. REFUSED, not rounded: it moves the frame-corner "
                         f"far-clip bound.")
    return int(v)


def validate_report(rep: dict) -> dict:
    """Raise unless `rep` is a well-formed booking-gate artifact. Called before the tool writes a
    `--json` file and by the host test that reads `eval/results/booking_gate_*.json`, so a malformed
    artifact cannot be produced OR silently consumed -- this file is what authorises a flight."""
    missing = [k for k in ("schema_version", "tool", "gate", "verdict") if k not in rep]
    if missing:
        raise ValueError(f"booking-gate artifact is missing top-level key(s): {missing}")
    ver = rep["schema_version"]
    if ver not in READABLE_SCHEMA_VERSIONS:
        raise ValueError(f"booking-gate artifact schema_version {ver!r} is not one this reader "
                         f"knows ({', '.join(READABLE_SCHEMA_VERSIONS)}). Refusing to interpret an "
                         f"artifact whose field meanings it cannot vouch for.")
    v = rep["verdict"]
    if not isinstance(v, dict):
        raise ValueError(f"booking-gate verdict must be an object, got {type(v).__name__}")
    for k in ("pass", "bookable"):
        if not isinstance(v.get(k), bool):
            raise ValueError(f"booking-gate verdict.{k} must be a bool, got {v.get(k)!r}")
    if "sweep" in rep:
        if not rep["sweep"]:
            raise ValueError("booking-gate sweep artifact carries no rows")
        # RECURSE. A sweep's rows ARE booking-gate reports -- same schema, same required fields --
        # and "the list is non-empty" was the whole check, so a sweep could carry rows with none of
        # schema 1.2's clamp fields and validate clean. Absence of `..._clamped_from_optical_prefix`
        # reads as `false` to a human, which is the one direction that turns a scene artifact into
        # a horizon.
        for i, row in enumerate(rep["sweep"]):
            if not isinstance(row, dict):
                raise ValueError(f"booking-gate sweep row {i} is {type(row).__name__}, not a "
                                 f"report")
            try:
                validate_report(row)
            except ValueError as exc:
                raise ValueError(f"booking-gate sweep row {i} is not a valid report: {exc}") from exc
            if row["verdict"]["bookable"]:
                raise ValueError(f"booking-gate sweep row {i} claims bookable:true -- "
                                 f"{SWEEP_AUTHORISES_NOTHING}")
        if v["bookable"]:
            raise ValueError(f"booking-gate sweep artifact claims bookable:true -- "
                             f"{SWEEP_AUTHORISES_NOTHING}")
    else:
        for k in ("sensor", "encounter", "plant", "budget", "checks"):
            if k not in rep:
                raise ValueError(f"booking-gate artifact is missing '{k}'")
        # 1.2's whole point is that the CLAMP and the bound it was clamped against are on the
        # record; an artifact that calls itself 1.2 without them is worse than a 1.1 one, because a
        # reader would take the absence of `..._clamped_from_optical_prefix` for `false`. 1.3 adds
        # the repo-relative config path and the full-precision intrinsics ON TOP -- required only
        # OF a 1.3 artifact, so the committed 1.2 one is not made malformed in hindsight.
        need = (SENSOR_FIELDS_1_2 if ver in ("1.2", "1.3") else ()) \
            + (SENSOR_FIELDS_1_3 if ver == "1.3" else ())
        absent = [k for k in need if k not in rep["sensor"]]
        if absent:
            raise ValueError(f"schema {ver} booking-gate artifact is missing sensor field(s): "
                             f"{absent}")
    return rep


def evaluate(mission_speed_mps: float, *, fx_px: Optional[float] = None,
             fy_px: Optional[float] = None, cx_px: Optional[float] = None,
             cy_px: Optional[float] = None, width_px: Optional[float] = None,
             height_px: Optional[float] = None, acq_range_m: Optional[float] = None,
             acq_optical_prefix_m: Optional[float] = None,
             depth_config: Path = DEPTH_CONFIG,
             birds_config: Path = BIRDS_CONFIG) -> dict:
    """One (sensor config, mission speed) pair -> the full gate report.

    The six intrinsics are a SET -- all or none, off ONE live `camera_info` -- and with
    `acq_range_m` they are what ADR-019 item 6 requires before a flight is booked
    (`verdict.bookable`). Passing none of them is a design check. Raises ValueError on anything
    unusable rather than returning a verdict: the caller turns that into exit 2, which is a refusal
    and not a statement about the sensor."""
    cfg = json.loads(Path(depth_config).read_text())
    cam, gate_cfg = cfg["camera"], cfg["booking_gate"]

    _positive_finite("--speed / mission_speed_mps", mission_speed_mps)

    given = {"fx": fx_px, "fy": fy_px, "cx": cx_px, "cy": cy_px,
             "width": width_px, "height": height_px}
    supplied = [k for k, _ in LIVE_INTRINSIC_FIELDS if given[k] is not None]
    if supplied and len(supplied) != len(given):
        missing = [f"--{k} ({field})" for k, field in LIVE_INTRINSIC_FIELDS if given[k] is None]
        raise ValueError(
            f"the live intrinsics are a SET OF SIX, all off the SAME camera_info message: "
            f"{', '.join(f'--{k} ({f})' for k, f in LIVE_INTRINSIC_FIELDS)}. Got "
            f"{', '.join('--' + k for k in supplied)}; MISSING {', '.join(missing)}. fx sets the "
            f"acquisition range, fy and cy set the threat-band coverage, and all six set the "
            f"frame-corner far-clip bound -- so a live number beside a config number is an answer "
            f"assembled from two different cameras. Give all six or none. REFUSED (exit 2).")
    live_intrinsics = bool(supplied)
    src = ("live camera_info (--fx/--fy/--cx/--cy/--width/--height, one message)" if live_intrinsics
           else "config/depth_camera.json")
    cfg_w, cfg_h = int(cam["image_width_px"]), int(cam["image_height_px"])
    if live_intrinsics:
        fx = _positive_finite("--fx", fx_px, hi=FX_RANGE_PX[1], lo=FX_RANGE_PX[0])
        fy = _positive_finite("--fy", fy_px, hi=FX_RANGE_PX[1], lo=FX_RANGE_PX[0])
        cx = _positive_finite("--cx", cx_px, hi=CXY_RANGE_PX[1], lo=CXY_RANGE_PX[0])
        cy = _positive_finite("--cy", cy_px, hi=CXY_RANGE_PX[1], lo=CXY_RANGE_PX[0])
        img_w = _positive_int("--width", width_px, hi=WH_RANGE_PX[1], lo=WH_RANGE_PX[0])
        img_h = _positive_int("--height", height_px, hi=WH_RANGE_PX[1], lo=WH_RANGE_PX[0])
        # The world SDF is GENERATED from config/depth_camera.json (gen_farm_world.py), so the live
        # frame size and the config's cannot legitimately differ. If they do, the number being read
        # is not this sensor's -- wrong topic, wrong camera, or a world built from an older config.
        # Refuse; do not prefer one over the other, because either choice would be a guess.
        if (img_w, img_h) != (cfg_w, cfg_h):
            raise ValueError(
                f"live camera_info says {img_w}x{img_h} px but {Path(depth_config).name} says "
                f"{cfg_w}x{cfg_h} px (camera.image_width_px/image_height_px). The world SDF is "
                f"GENERATED from that config, so these cannot honestly differ: you are reading a "
                f"different camera, or the world was built from an older config. Nothing here is "
                f"reconcilable by picking one. REFUSED (exit 2).")
        if cx > img_w - 1 or cy > img_h - 1:
            raise ValueError(
                f"principal point ({cx:g}, {cy:g}) lies outside the {img_w}x{img_h} frame "
                f"(valid pixel indices 0..{img_w - 1}, 0..{img_h - 1}). That is a transcription "
                f"error, not a camera. REFUSED (exit 2).")
    else:
        fx = fy = _fx_from(cam)         # square pixels: the config carries one FOV (see its note)
        cx, cy = cfg_w / 2.0, cfg_h / 2.0
        img_w, img_h = cfg_w, cfg_h

    bird_radius_m = max(b["physical_radius_m"]
                        for b in json.loads(Path(birds_config).read_text())["birds"])
    geometric_acq_m = acquisition_range_m(fx, bird_radius_m)
    far_m = float(cam["clip_far_m"])
    if acq_range_m is not None:
        # One message for every bad horizon, and it always NAMES THE CLIP -- `inf` and `100` are the
        # same mistake, and a refusal that does not say what the bound is makes the operator guess.
        acq_m = float(acq_range_m)
        if not math.isfinite(acq_m) or acq_m <= 0.0 or acq_m > far_m:
            raise ValueError(
                f"--acq-range-m must be a finite measurement in (0, {far_m:g}] m -- the sensor's "
                f"own far clip is {far_m:g} m (config/depth_camera.json camera.clip_far_m) and gz "
                f"writes +inf past that plane, so nothing can be measured beyond it. Got "
                f"{acq_range_m!r}: a transcription error, not a horizon. REFUSED (exit 2).")
        acq_source = "live render measurement (--acq-range-m)"
    else:
        acq_m = geometric_acq_m
        acq_source = "geometric upper bound (pinhole x adopted morphology)"

    # THE CLAMP, ON THE RECORD (schema 1.2). D3 prints two numbers -- the optical PREFIX and the
    # BOOKABLE range clamped to the frame-corner bound (ADR-020 am. 1) -- and only the second one
    # may be booked. Until 1.2 the artifact said `acquisition_range_source: live render measurement`
    # with no way to tell whether it was the clamped number or the raw prefix.
    prefix_m: Optional[float] = None
    clamped = False
    if acq_optical_prefix_m is not None:
        if acq_range_m is None:
            raise ValueError(
                "--acq-optical-prefix-m without --acq-range-m records a LIVE measurement beside a "
                "CONFIG-sourced acquisition range, which is the mixed-source answer this tool "
                "refuses everywhere else. The prefix documents what the bookable number was "
                "clamped FROM; give both or neither. REFUSED (exit 2).")
        prefix_m = float(acq_optical_prefix_m)
        if not math.isfinite(prefix_m) or prefix_m <= 0.0 or prefix_m > far_m:
            raise ValueError(
                f"--acq-optical-prefix-m must be a finite measured range in (0, {far_m:g}] m (the "
                f"sweep cannot see past the {far_m:g} m far clip). Got {acq_optical_prefix_m!r}. "
                f"REFUSED (exit 2).")
        if prefix_m < acq_m - 1e-9:
            raise ValueError(
                f"--acq-range-m {acq_m:g} m EXCEEDS the optical prefix {prefix_m:g} m it is "
                f"supposed to have been clamped from. The bookable range is the longest prefix "
                f"range inside the corner bound (ADR-020 am. 1), so it can never be longer than "
                f"the prefix: one of the two numbers was mis-transcribed, and booking on the "
                f"larger one is exactly the optimism this gate exists to stop. REFUSED (exit 2).")
        clamped = prefix_m > acq_m + 1e-9

    # The gz far cull is applied to the EUCLIDEAN length of the camera-space point while the value
    # stored is the pinhole Z-DEPTH, so the effective Z-depth horizon shrinks by |ray| off-axis:
    # 1.17x at the horizontal frame edge, 1.26x at the corner. Quoting the on-axis 60 m as the
    # headroom over a 46.80 m acquisition bound overstates it by an order of magnitude.
    #
    # THE FARTHEST CORNER (QA probe C, 2026-09-06 -- the formula this replaced was
    # `sqrt(1 + (cx/fx)^2 + (cy/fx)^2)`, wrong in three ways at once and optimistic in all three).
    # The ratio itself is `depth_detect.corner_ray_ratio`, which is the ONE copy: the three gates
    # that need it run on three interpreters with three input sources, and hand-written copies is
    # how two of them came to be wrong at the same time. Only the REPORTING of which pixel it is
    # lives here -- W and H are the live message's, cross-checked against the config above.
    du_px, dv_px = max(cx, (img_w - 1) - cx), max(cy, (img_h - 1) - cy)
    corner_u = 0.0 if cx >= (img_w - 1) - cx else float(img_w - 1)
    corner_v = 0.0 if cy >= (img_h - 1) - cy else float(img_h - 1)
    corner_ray = corner_ray_ratio(img_w, img_h, fx, fy, cx, cy)
    far_corner_m = far_m / corner_ray
    if clamped:
        # `acquisition_range_source` is the field a reader reaches for first, so it carries the
        # clamp itself rather than only pointing at the fields below it.
        acq_source += (f" -- CLAMPED to the {far_corner_m:.2f} m frame-corner bound from a "
                       f"{prefix_m:g} m optical prefix (ADR-020 am. 1)")

    policy = PolicyParams()
    bar_m = float(policy.min_bird_clearance_m)
    band_half_m = float(policy.vertical_threat_m)
    bird_speed_mps = max_bird_speed_m_s(Path(birds_config))
    closing_mps = float(mission_speed_mps) + bird_speed_mps

    margin_factor = float(gate_cfg["lead_margin_factor"])
    frame_period_s = 1.0 / float(cam["update_rate_hz"])
    tick_s = float(gate_cfg["control_tick_latency_s"])
    latency_s = frame_period_s + tick_s

    t_req_s = time_to_displace_s(bar_m, GUIDED_DEFAULT)
    if t_req_s is None:                     # unreachable for a 3 m bar; refuse rather than crash
        raise ValueError(f"{GUIDED_DEFAULT.name} cannot displace {bar_m} m at all")
    need_s = t_req_s + latency_s
    required_lead_s = margin_factor * need_s
    lead_s = acq_m / closing_mps
    margin = lead_s / need_s

    # The ADR-016 am. 2 tuning-override concern, priced instead of assumed: a mission flown slower
    # than WP_SPD's 10 m/s default is flown with a LOWER speed cap, which is a different plant.
    # At the booked 5.0 m/s the 3.00 m escape never reaches that cap, so t_req is invariant -- but
    # below ~3.86 m/s it does, and this is a CHECK rather than a note (G127; see the docstring).
    capped_plant = replace(GUIDED_DEFAULT, name=f"guided_default@v_max={mission_speed_mps:g}",
                           v_max_ne_mps=min(GUIDED_DEFAULT.v_max_ne_mps, float(mission_speed_mps)))
    t_req_capped_s = time_to_displace_s(bar_m, capped_plant)
    need_capped_s = None if t_req_capped_s is None else t_req_capped_s + latency_s
    margin_capped = None if need_capped_s is None else lead_s / need_capped_s
    # ONE printed value for one quantity. The check detail and the NOTE in `format_report` both
    # read this, so the report can never carry 0.922x in one line and 0.921x in another (the
    # `.3f` of a raw float vs the `.3f` of its own 4-dp rounding). The `ok` below compares the
    # UNROUNDED number: rounding before a bar is how a 1.29996x reads as a pass.
    margin_capped_shown = None if margin_capped is None else round(margin_capped, 4)
    cap_binds = t_req_capped_s is not None and t_req_capped_s > t_req_s + 1e-9

    # fy, not fx: the band is a VERTICAL extent. They are equal to 1 ULP on this mount, which is a
    # fact about the mount and not a licence to pass the horizontal focal length to a vertical one.
    # H goes in too, because the binding half-extent is min(cy, H-1-cy) -- the band is symmetric
    # about the axis, so it must fit on the SHORT side of the frame as well.
    band_from_m = band_covered_from_m(fy, cy, img_h, band_half_m)
    escape_at_lead_m = max_displacement_m(max(0.0, lead_s - latency_s), GUIDED_DEFAULT)

    checks = [
        {"name": "lead_margin",
         "ok": margin >= margin_factor,
         "detail": (f"{lead_s:.3f} s available vs {need_s:.3f} s needed = {margin:.3f}x "
                    f"(bar {margin_factor:.2f}x)")},
        {"name": "band_in_frame_at_acquisition",
         "ok": band_from_m <= acq_m,
         "detail": (f"the +/-{band_half_m:g} m threat band is in frame from {band_from_m:.2f} m, "
                    f"acquisition is at {acq_m:.2f} m")},
        {"name": "acquisition_within_corner_far_clip",
         "ok": acq_m <= far_corner_m,
         "detail": (f"acquisition {acq_m:.2f} m vs the {far_corner_m:.2f} m Z-depth horizon at the "
                    f"FARTHEST FRAME CORNER, pixel ({corner_u:.0f}, {corner_v:.0f}) = "
                    f"({du_px:.0f}, {dv_px:.0f}) px off the principal point of a "
                    f"{img_w}x{img_h} frame (far clip {far_m:g} m culled on Euclidean slant range, "
                    f"|ray| {corner_ray:.3f}x on-axis). Headroom "
                    f"{100.0 * (far_corner_m - acq_m) / acq_m:.1f} % -- NOT the "
                    f"{100.0 * (far_m - acq_m) / acq_m:.0f} % the on-axis clip suggests")},
        # G127. The same margin bar, re-run against the plant the MISSION SPEED implies. Flying at
        # v means WP_SPD = v, and below ~3.86 m/s the 3.00 m escape runs into that limit, so
        # the headline margin describes an escape the vehicle cannot make. This used to be a NOTE
        # printed on an exit-0 line ("Re-derive before booking") -- an instruction to a human,
        # underneath the exit code that says no action is needed.
        {"name": "escape_survives_mission_speed_cap",
         "ok": margin_capped is not None and margin_capped >= margin_factor,
         "detail": (
             (f"flying at {mission_speed_mps:g} m/s means WP_SPD = {mission_speed_mps:g} m/s, "
              f"and the {bar_m:.2f} m escape is UNREACHABLE under that cap within point_mass's 60 s "
              f"horizon: there is no escape to book at this speed") if t_req_capped_s is None else
             (f"the {mission_speed_mps:g} m/s mission cap lengthens the escape: t_req "
              f"{t_req_s:.3f} -> {t_req_capped_s:.3f} s, so the cap-honest margin is "
              f"{margin_capped_shown:.3f}x against the {margin_factor:.2f}x bar (the headline "
              f"{margin:.3f}x is computed on the UNCAPPED plant)") if cap_binds else
             (f"a {mission_speed_mps:g} m/s cap does not bind: the {bar_m:.2f} m escape never "
              f"reaches the velocity limit, t_req is {t_req_s:.3f} s either way and the cap-honest "
              f"margin {margin_capped_shown:.3f}x IS the headline margin -- checked, not "
              f"assumed"))},
    ]
    # NOT a check. `escape_at_available_lead_m` is algebraically implied by `margin` -- an earlier
    # version listed it as a gate and claimed it cross-checked the plant model in the forward
    # direction, which is structurally impossible: `time_to_displace_s` IS a bisection on
    # `max_displacement_m`, so a mutant scaling displacement 3x moves both together (measured: t_req
    # 1.79 -> 1.00 s with the "cross-check" still green). The real independent pin is against the
    # ANALYTIC closed forms, in tests/fieldguard_planning/test_predict_forward_lead.py. This number
    # survives only because it states the bar in metres, which reads better than a ratio.
    passed = all(c["ok"] for c in checks)
    bookable = passed and live_intrinsics and acq_range_m is not None

    return {
        "schema_version": SCHEMA_VERSION,
        "tool": "scripts/predict_forward_lead.py",
        "gate": "ADR-019 item 6 (Council Ruling 002 tripwire (a)) -- the booking gate",
        "sensor": {
            "config": str(depth_config),
            # SCHEMA 1.3. `config` is an ABSOLUTE path, so the artifact records a home directory
            # that means nothing on any other machine; this is the same file named the way the
            # repo names it. None when the config is not inside this repo (a test fixture, an
            # out-of-tree copy) -- there is no repo-relative name for it, and inventing one would
            # be worse than saying so.
            "config_relpath": _repo_relpath(depth_config),
            # SCHEMA 1.3. `fx_px`/`fy_px` are rounded to 4 dp for reading; these are the numbers
            # the gate actually computed with, as STRINGS so that no reader or re-writer can round
            # them a second time (`float(s)` recovers them exactly). The live fx/fy differ in the
            # 13th digit on this mount -- a difference 4 dp cannot show -- and an operator
            # cross-checking the artifact against a live camera_info needs to match digit for digit.
            "fx_px_exact": repr(fx), "fy_px_exact": repr(fy),
            "cx_px_exact": repr(cx), "cy_px_exact": repr(cy),
            "fx_px": round(fx, 4), "fx_source": src,
            "fy_px": round(fy, 4), "fy_source": src,
            "cx_px": cx, "cx_source": src,
            "cy_px": cy, "cy_source": src,
            "image_width_px": img_w, "image_height_px": img_h, "image_size_source": src,
            "image_size_cross_check": (
                f"live {img_w}x{img_h} == config {cfg_w}x{cfg_h}; a mismatch is a REFUSAL (the "
                f"world SDF is generated from that config, so it means the wrong camera was read)"
                if live_intrinsics else
                f"n/a -- config-sourced run ({cfg_w}x{cfg_h}); nothing live to cross-check"),
            "live_intrinsics": live_intrinsics,
            "update_rate_hz": cam["update_rate_hz"],
            "clip_far_m": far_m,
            "clip_far_at_frame_corner_m": round(far_corner_m, 3),
            "clip_far_corner_ray_ratio": round(corner_ray, 6),
            "clip_far_corner_pixel_uv": [corner_u, corner_v],
            "clip_far_corner_offset_px": [du_px, dv_px],
            "clip_far_corner_rule": ("|ray| = sqrt(1 + (max(cx, W-1-cx)/fx)^2 + "
                                     "(max(cy, H-1-cy)/fy)^2) -- the FARTHEST corner from the "
                                     "principal point, the first pixel gz culls"),
            "clip_semantics": ("value = pinhole Z-depth; the NEAR cull is on Z-depth, the FAR cull "
                               "on EUCLIDEAN slant range (gz-rendering8 depth_camera_fs.glsl), so "
                               "the effective Z horizon shrinks by |ray| off-axis"),
            "min_resolving_radius_px": MIN_RESOLVING_RADIUS_PX,
            "geometric_acquisition_range_m": round(geometric_acq_m, 3),
            "acquisition_range_m": round(acq_m, 3), "acquisition_range_source": acq_source,
            "acquisition_optical_prefix_m": prefix_m,
            "acquisition_clamped_from_optical_prefix": clamped,
            "acquisition_clamp_bound_m": (round(far_corner_m, 3) if clamped else None),
            "acquisition_clamp_note": (
                f"D3's optical prefix was {prefix_m:g} m; the BOOKED range is {acq_m:g} m, the "
                f"longest swept prefix range inside the {far_corner_m:.2f} m frame-corner Z-depth "
                f"horizon (ADR-020 am. 1). The clamp is applied UPSTREAM, in gate D3; this field "
                f"records that the number handed to the gate was a clamped one and against which "
                f"bound" if clamped else
                "no optical prefix was given (or it equals the booked range), so this run records "
                "no clamp. An unclamped LIVE acquisition range should equal D3's prefix; if D3 "
                "clamped and the prefix is not passed here, the artifact cannot say so"),
            "band_covered_from_m": round(band_from_m, 3),
        },
        "encounter": {
            "mission_speed_mps": float(mission_speed_mps),
            "bird_speed_mps": round(bird_speed_mps, 4),
            "bird_speed_source": f"max over {birds_config.name} (check_live_flight_log."
                                 f"max_bird_speed_m_s -- the fastest bird, not today's threat)",
            "closing_speed_mps": round(closing_mps, 4),
            "bird_radius_m": bird_radius_m,
        },
        "plant": {
            "name": GUIDED_DEFAULT.name,
            "a_max_ne_mps2": GUIDED_DEFAULT.a_max_ne_mps2,
            "jerk_ne_mps3": GUIDED_DEFAULT.jerk_ne_mps3,
            "t_req_s": round(t_req_s, 4),
            "t_req_s_at_mission_speed_cap": (None if t_req_capped_s is None
                                             else round(t_req_capped_s, 4)),
            "speed_cap_changes_t_req": (t_req_capped_s is not None
                                        and abs(t_req_capped_s - t_req_s) > 1e-6),
            "mission_speed_cap_is_checked": ("escape_survives_mission_speed_cap in `checks` -- the "
                                             "margin bar re-run against the capped plant (G127); "
                                             "these two numbers are no longer decoration"),
            "context_other_plants": {p.name: round(time_to_displace_s(bar_m, p) or float("nan"), 4)
                                     for p in PLANTS},
        },
        "budget": {
            "bar_m": bar_m,
            "lead_margin_factor": margin_factor,
            "frame_period_s": round(frame_period_s, 4),
            "control_tick_latency_s": tick_s,
            "pipeline_latency_s": round(latency_s, 4),
            "need_s": round(need_s, 4),
            "need_s_at_mission_speed_cap": (None if need_capped_s is None
                                            else round(need_capped_s, 4)),
            "required_lead_s": round(required_lead_s, 4),
            "available_lead_s": round(lead_s, 4),
            "margin": round(margin, 4),
            "margin_at_mission_speed_cap": margin_capped_shown,
            "required_horizon_m": round(required_lead_s * closing_mps, 3),
            "acq_range_headroom_frac": round(1.0 - (required_lead_s * closing_mps) / acq_m, 4),
            "escape_at_available_lead_m": round(escape_at_lead_m, 3),
            "escape_at_available_lead_note": ("the bar restated in metres. ALGEBRAICALLY IMPLIED by "
                                              "`margin` (same plant, same numbers) -- not a check "
                                              "and not a cross-check; see the comment above the "
                                              "checks list."),
            "unmodelled": ("AUTO->GUIDED mode-switch latency (TG-5) is NOT in this budget and is "
                           "unmeasured; every eval/point_mass omission (attitude lag, motor lag, "
                           "EKF lag, wind/drag) makes the plant OPTIMISTIC. The margin is an upper "
                           "bound on safety, never a promise."),
        },
        "checks": checks,
        "verdict": {
            "pass": passed,
            "bookable": bookable,
            "exit_code": (EXIT_PASS_BOOKABLE if bookable else
                          EXIT_FAIL if not passed else EXIT_PASS_NOT_BOOKABLE),
            # THE CAUSE, NOT A CAUSE (QA finding G131, 2026-09-07). Live intrinsics with no
            # --acq-range-m used to print "inputs are config-sourced", which sends the operator
            # back to `ros2 topic echo camera_info` -- the one input they already have -- instead
            # of to gate D3, the render measurement they are actually missing. Two different
            # missing halves, two different sentences.
            "why_not_bookable": (
                None if bookable else
                "one or more checks failed" if not passed else
                ("live intrinsics given but no --acq-range-m (D3): the six live camera_info "
                 "numbers are NECESSARY and NOT SUFFICIENT -- the forward horizon is a separate "
                 "measured render horizon (docs/runbooks/FORWARD_DEPTH_SENSOR.md gate D3), and "
                 "without it this run used the geometric upper bound computed on the host from "
                 "config/depth_camera.json, which is booking on config prose"
                 if live_intrinsics else
                 "inputs are config-sourced; ADR-019 item 6 requires the forward horizon and "
                 "intrinsics to come from the sensor's own live camera_info and a measured render "
                 "horizon")),
        },
    }


def _fmt_x(v: Optional[float]) -> str:
    """A margin, or the honest word for one that does not exist (the capped plant cannot make the
    escape at all)."""
    return "UNREACHABLE" if v is None else f"{v:.3f}x"


def format_report(rep: dict) -> str:
    s, e, p, b, v = (rep["sensor"], rep["encounter"], rep["plant"], rep["budget"], rep["verdict"])
    L = [
        "SwathKeeper forward-sensor BOOKING GATE (ADR-019 item 6)",
        f"  sensor    fx={s['fx_px']:.2f} fy={s['fy_px']:.2f} c=({s['cx_px']:.0f},"
        f"{s['cy_px']:.0f}) px in {s['image_width_px']}x{s['image_height_px']} @ "
        f"{s['update_rate_hz']:g} Hz, far clip {s['clip_far_m']:g} m on-axis / "
        f"{s['clip_far_at_frame_corner_m']:.2f} m at the farthest corner "
        f"({s['clip_far_corner_pixel_uv'][0]:.0f},{s['clip_far_corner_pixel_uv'][1]:.0f})   "
        f"[{s['fx_source']}]",
        f"  horizon   acquisition {s['acquisition_range_m']:.2f} m "
        f"(a {e['bird_radius_m']:g} m bird at {s['min_resolving_radius_px']:g} px radius); "
        f"threat band in frame from {s['band_covered_from_m']:.2f} m",
        f"            [{s['acquisition_range_source']}]",
        f"  encounter mission {e['mission_speed_mps']:.2f} + bird {e['bird_speed_mps']:.2f} = "
        f"closing {e['closing_speed_mps']:.2f} m/s (head-on, the worst case)",
        f"  plant     {p['name']}: a_max {p['a_max_ne_mps2']:g} m/s^2, jerk "
        f"{p['jerk_ne_mps3']:g} m/s^3 -> {p['t_req_s']:.3f} s to move {b['bar_m']:.2f} m",
        f"  budget    need {p['t_req_s']:.3f} s escape + {b['pipeline_latency_s']:.3f} s pipeline "
        f"({b['frame_period_s']:.3f} frame + {b['control_tick_latency_s']:.3f} tick) = "
        f"{b['need_s']:.3f} s; x{b['lead_margin_factor']:.2f} = {b['required_lead_s']:.3f} s",
        "",
    ]
    for c in rep["checks"]:
        L.append(f"  {'PASS' if c['ok'] else 'FAIL'}  {c['name']}: {c['detail']}")
    L += [
        "",
        f"  available lead {b['available_lead_s']:.3f} s  =  MARGIN {b['margin']:.3f}x  "
        f"(bar {b['lead_margin_factor']:.2f}x)",
        f"  required forward horizon at this speed: {b['required_horizon_m']:.2f} m "
        f"(the sensor gives {s['acquisition_range_m']:.2f} m -> "
        f"{100.0 * b['acq_range_headroom_frac']:.1f} % headroom)",
    ]
    if p["speed_cap_changes_t_req"]:
        # No longer an instruction to the operator: `escape_survives_mission_speed_cap` above has
        # already gated this reading, so the line reports what the gate did rather than asking for
        # a re-derivation underneath an exit code that says none is needed (G127).
        L.append(f"  NOTE: flying at {e['mission_speed_mps']:g} m/s caps the plant's speed and "
                 f"MOVES t_req to {p['t_req_s_at_mission_speed_cap']:.3f} s -- the headline margin "
                 f"above uses the uncapped {p['t_req_s']:.3f} s. The cap-honest margin is "
                 f"{_fmt_x(b['margin_at_mission_speed_cap'])} and is GATED by "
                 f"escape_survives_mission_speed_cap.")
    else:
        L.append(f"  (a {e['mission_speed_mps']:g} m/s speed cap does not change t_req: the 3 m "
                 f"escape never reaches the velocity limit -- checked, not assumed)")
    if not v["pass"]:
        # NO DIRECTION IS PRESCRIBED HERE. This line used to say "slow the mission, or measure a
        # longer horizon" -- and both of those can be the FAILING direction: past 47.56 m a longer
        # horizon fails the corner check, and below ~0.79 m/s a slower mission fails the speed cap.
        # G60's family. Name the failing checks; let the operator read them.
        L.append(f"  VERDICT: FAIL -- DO NOT BOOK at {e['mission_speed_mps']:g} m/s. Failing: "
                 f"{', '.join(c['name'] for c in rep['checks'] if not c['ok'])}. Read those "
                 f"detail lines: neither knob is monotone in the VERDICT, so a slower mission or a "
                 f"longer horizon can each be the direction that fails.")
    elif v["bookable"]:
        L.append(f"  VERDICT: PASS and BOOKABLE at {e['mission_speed_mps']:g} m/s -- margin "
                 f"{b['margin']:.3f}x on live-measured inputs.")
    else:
        L.append(f"  VERDICT: PASS but NOT BOOKABLE -- {v['why_not_bookable']}. This is a DESIGN "
                 f"check: the geometry works. Measure the render horizon "
                 f"(docs/runbooks/FORWARD_DEPTH_SENSOR.md gate D3), pass all six live intrinsics "
                 f"(--fx --fy --cx --cy --width --height, one camera_info message) AND "
                 f"--acq-range-m, and re-run for a bookable verdict.")
    L.append(f"  {b['unmodelled']}")
    return "\n".join(L)


def _parse_sweep(spec: str) -> List[float]:
    try:
        lo, hi, step = (float(x) for x in spec.split(":"))
    except ValueError:
        raise argparse.ArgumentTypeError(f"--sweep wants LO:HI:STEP, got {spec!r}")
    if step <= 0 or hi < lo:
        raise argparse.ArgumentTypeError(f"--sweep needs LO <= HI and STEP > 0, got {spec!r}")
    n = int(math.floor((hi - lo) / step + 1e-9))
    return [round(lo + k * step, 6) for k in range(n + 1)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--speed", type=float, default=None,
                    help="mission ground speed m/s. REQUIRED (no default, ADR-016): the verdict "
                         "turns on it and nothing in this repo pins a mission speed.")
    live = ap.add_argument_group(
        "live camera_info (a SET OF SIX -- all off ONE /fg/depth/camera_info message, or none)",
        "fx sets the acquisition range, fy+cy set the threat-band coverage, and all six set the "
        "frame-corner far-clip bound. Any part of the set is a REFUSAL (exit 2), and live "
        "width/height that disagree with config/depth_camera.json are a refusal too: the world SDF "
        "is generated from that config, so a mismatch means the wrong camera is being read.")
    live.add_argument("--fx", type=float, default=None, help="K[0] of the LIVE camera_info")
    live.add_argument("--fy", type=float, default=None,
                      help="K[4], same message. The VERTICAL focal length -- it, not fx, divides "
                           "the vertical term of the frame-corner ray")
    live.add_argument("--cx", type=float, default=None, help="K[2], same message")
    live.add_argument("--cy", type=float, default=None, help="K[5], same message")
    live.add_argument("--width", type=float, default=None,
                      help="camera_info.width px, same message (never config: the corner bound "
                           "needs the frame's own far edge)")
    live.add_argument("--height", type=float, default=None,
                      help="camera_info.height px, same message")
    ap.add_argument("--acq-range-m", type=float, default=None,
                    help="MEASURED acquisition range from the render (FORWARD_DEPTH_SENSOR.md gate "
                         "D3) -- its BOOKABLE number, never the optical prefix. Without it the "
                         "tool uses the geometric upper bound and no verdict is bookable.")
    ap.add_argument("--acq-optical-prefix-m", type=float, default=None,
                    help="informational: D3's OPTICAL PREFIX, the number --acq-range-m was clamped "
                         "from (ADR-020 am. 1). Recorded verbatim in the artifact so a reader can "
                         "tell a clamped booking range from an unclamped one. Needs "
                         "--acq-range-m, and must be >= it.")
    ap.add_argument("--sweep", type=_parse_sweep, default=None, metavar="LO:HI:STEP",
                    help="print the margin across a mission-speed range instead of one verdict "
                         "(e.g. 2:10:0.5). CHOOSES a speed; authorises nothing. NEVER exits 0, "
                         "however live the inputs -- 3 when some row passes, 1 when none does. "
                         "Exit 0 comes only from a single --speed run at the speed you picked.")
    ap.add_argument("--json", type=Path, default=None, help="also write the full report as JSON")
    args = ap.parse_args(argv)

    if args.sweep is None and args.speed is None:
        # A refusal, distinct from PASS (0), FAIL (1) and PASS-not-bookable (3): the same doctrine
        # `predict_bird_visibility.py` adopted after a 3.0 m/s default booked a flight the vehicle
        # then flew at ~9 m/s. No mission file or pinned param in this repo carries a speed.
        ap.error("--speed is REQUIRED (no default). The verdict turns on it and nothing in this "
                 "repo pins a mission speed; measure it off your last flight's poses, or run "
                 "--sweep LO:HI:STEP to choose one. Exit 2 means 'I was not told', which is not "
                 "the same as 'the sensor is not enough'.")

    kw = dict(fx_px=args.fx, fy_px=args.fy, cx_px=args.cx, cy_px=args.cy,
              width_px=args.width, height_px=args.height,
              acq_range_m=args.acq_range_m, acq_optical_prefix_m=args.acq_optical_prefix_m)
    speeds = args.sweep if args.sweep is not None else [args.speed]
    try:
        reps = [evaluate(v, **kw) for v in speeds]
    except ValueError as exc:
        # Every unusable input lands here and exits 2. It is NEVER exit 1: "I cannot evaluate this"
        # and "the sensor is insufficient" are different claims, and a typo must not produce the
        # second one.
        print(f"[predict_forward_lead] REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    # Bookability is a property of the INPUT SET *and* of the MODE. Live inputs are necessary
    # everywhere; a single --speed run is necessary on top of that, because a sweep's subject is a
    # RANGE of speeds and a flight is flown at one.
    live_inputs = bool(reps[0]["sensor"]["live_intrinsics"]) and args.acq_range_m is not None
    any_pass = any(r["verdict"]["pass"] for r in reps)

    if args.sweep is not None:
        # THE RULE, in three lines: a sweep never authorises. Not on live inputs, not when every
        # swept speed passes, not when the range is a single point -- exit 0 is unreachable from
        # here, and each row says so in the artifact as well as in the verdict above it.
        exit_code = EXIT_PASS_NOT_BOOKABLE if any_pass else EXIT_FAIL
        for r in reps:
            rv = r["verdict"]
            rv["bookable"] = False
            rv["exit_code"] = EXIT_PASS_NOT_BOOKABLE if rv["pass"] else EXIT_FAIL
            rv["why_not_bookable"] = (("one or more checks failed; " if not rv["pass"] else "")
                                      + SWEEP_AUTHORISES_NOTHING)
        head = reps[0]
        print("SwathKeeper forward-sensor booking-gate SWEEP (ADR-019 item 6)")
        print(f"  acquisition {head['sensor']['acquisition_range_m']:.2f} m "
              f"[{head['sensor']['acquisition_range_source']}]; need "
              f"{head['budget']['need_s']:.3f} s; bar "
              f"{head['budget']['lead_margin_factor']:.2f}x")
        print(f"  {'speed':>6} {'closing':>8} {'lead s':>8} {'margin':>7} {'horizon m':>10} "
              f"{'headroom':>9}  verdict")
        for r in reps:
            b, e = r["budget"], r["encounter"]
            # PASS*, never BOOKABLE: the row label is what an operator reads off the table, and
            # the runbooks equate that word with "book the flight".
            row = "PASS*" if r["verdict"]["pass"] else "FAIL"
            print(f"  {e['mission_speed_mps']:6.2f} {e['closing_speed_mps']:8.2f} "
                  f"{b['available_lead_s']:8.3f} {b['margin']:7.3f} "
                  f"{b['required_horizon_m']:10.2f} "
                  f"{100.0 * b['acq_range_headroom_frac']:8.1f}%  {row}")
        best = max((r for r in reps if r["verdict"]["pass"]),
                   key=lambda r: r["encounter"]["mission_speed_mps"], default=None)
        if best is not None:
            print(f"  fastest passing mission speed: "
                  f"{best['encounter']['mission_speed_mps']:g} m/s at margin "
                  f"{best['budget']['margin']:.3f}x. Slower is not automatically safer for the "
                  f"OTHER gates -- ADR-016 am. 1 measured the bird-visibility response non-monotone "
                  f"in speed, so re-run those at whatever speed you pick.")
        else:
            print("  NO mission speed in this range passes. Do not book; lengthen the horizon.")
        print("  PASS* = clears the margin bar at that speed, and NOTHING MORE. This sweep is for "
              "CHOOSING a mission speed; it authorises no flight, CANNOT EXIT 0 in any mode or on "
              "any inputs, and exits 3 when some row passes / 1 when none does. Pick a speed, then "
              "authorise THAT speed with a single --speed run on the full live input set "
              "(FORWARD_DEPTH_SENSOR.md gate D4).")
        if not live_inputs:
            print("  ...and these rows come from config/depth_camera.json, so they would not be "
                  "BOOKABLE even from a single --speed run: ADR-019 item 6 wants the horizon and "
                  "intrinsics from the sensor's own live camera_info (gates D1/D3).")
        report = {
            "schema_version": SCHEMA_VERSION,
            "tool": "scripts/predict_forward_lead.py --sweep",
            "gate": "ADR-019 item 6 (Council Ruling 002 tripwire (a)) -- the booking gate",
            "sweep": reps,
            "verdict": {
                "pass": any_pass,
                "bookable": False,
                "exit_code": exit_code,
                "fastest_passing_speed_mps": (None if best is None
                                              else best["encounter"]["mission_speed_mps"]),
                "why_not_bookable": (("no speed in the swept range passes; " if not any_pass else "")
                                     + SWEEP_AUTHORISES_NOTHING
                                     + ("" if live_inputs else
                                        "; and these rows are config-sourced, which ADR-019 item 6 "
                                        "would refuse on its own")),
            },
        }
    else:
        # Single speed: the verdict `evaluate` already computed IS the answer -- one row, one
        # speed, one exit code, and `bookable` there already requires the full live input set.
        report = reps[0]
        exit_code = report["verdict"]["exit_code"]
        print(format_report(report))

    if args.json is not None:
        validate_report(report)         # never write an artifact a reader could not trust
        if str(args.json) != "/dev/null":
            args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=1) + "\n")
        print(f"  json -> {args.json}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
