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
gate D3), pass `--acq-range-m` plus `--fx`/`--cy` from the live `camera_info`, and re-run for exit 0.

    exit 0  PASS and BOOKABLE      (full live input set, margin >= 1.3)
    exit 1  FAIL                   (a check failed -- do not book, at this speed)
    exit 2  REFUSAL                (nothing was decided: no --speed, garbage input, or half a live
                                    intrinsic set. Never confusable with a verdict about the sensor)
    exit 3  PASS but NOT BOOKABLE  (config-sourced inputs -- the design is sound, the sensor is
                                    unmeasured)

**EXIT 0 IS UNREACHABLE WITHOUT LIVE INPUTS IN EVERY MODE, INCLUDING `--sweep`.** That is the
property, and it is pinned by test. An earlier version returned 0 from `--sweep` whenever any speed
passed, on config numbers -- while FORWARD_DEPTH_SENSOR.md instructed the sweep as a HOST
precondition and published "exit 0 = book the flight". One exit code, two meanings, is precisely
what the 2026-08-25 booking cost this project.

INPUT IS VALIDATED, NOT LAUNDERED. `--acq-range-m 100` (beyond the 60 m far clip) and even `inf`
used to produce exit 0 BOOKABLE; `--speed nan` used to exit 1, i.e. a typo read as a conclusion
about the hardware. Every malformed input is now exit 2.

INTRINSICS COME AS A SET. `--fx` sets the acquisition range and `--cy` sets the band coverage, so
mixing a live `fx` with a config `cy` is a 2x-optimistic answer assembled from two different
cameras. They must be given together (both off the SAME `camera_info`: K[0] and K[5]) or not at all.
`cx` is taken from the config's `image_width_px/2` and enters only the frame-corner far-clip bound;
its source is labelled in the report.

USE
    python3 scripts/predict_forward_lead.py --speed 5.0                       # design check (3)
    python3 scripts/predict_forward_lead.py --speed 5.0 \
            --fx 520.01 --cy 240.0 --acq-range-m 38.4                          # bookable check (0)
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
    MIN_RESOLVING_RADIUS_PX, acquisition_range_m, band_covered_from_m,
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

SCHEMA_VERSION = "1.1"          # 1.0 -> 1.1: top-level verdict on sweeps, corner far-clip, cx/cy

# Sane bounds for a live intrinsic. Not tuning knobs -- a rejection window wide enough that no real
# camera_info falls outside it and narrow enough that a transcription slip (a pasted `0`, a negative,
# a `nan` from an empty field) cannot become a verdict.
FX_RANGE_PX = (1.0, 1.0e5)
CY_RANGE_PX = (1.0, 1.0e4)


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


def validate_report(rep: dict) -> dict:
    """Raise unless `rep` is a well-formed booking-gate artifact. Called before the tool writes a
    `--json` file and by the host test that reads `eval/results/booking_gate_*.json`, so a malformed
    artifact cannot be produced OR silently consumed -- this file is what authorises a flight."""
    missing = [k for k in ("schema_version", "tool", "gate", "verdict") if k not in rep]
    if missing:
        raise ValueError(f"booking-gate artifact is missing top-level key(s): {missing}")
    v = rep["verdict"]
    for k in ("pass", "bookable"):
        if not isinstance(v.get(k), bool):
            raise ValueError(f"booking-gate verdict.{k} must be a bool, got {v.get(k)!r}")
    if "sweep" in rep:
        if not rep["sweep"]:
            raise ValueError("booking-gate sweep artifact carries no rows")
    else:
        for k in ("sensor", "encounter", "plant", "budget", "checks"):
            if k not in rep:
                raise ValueError(f"booking-gate artifact is missing '{k}'")
    return rep


def evaluate(mission_speed_mps: float, *, fx_px: Optional[float] = None,
             cy_px: Optional[float] = None, acq_range_m: Optional[float] = None,
             depth_config: Path = DEPTH_CONFIG,
             birds_config: Path = BIRDS_CONFIG) -> dict:
    """One (sensor config, mission speed) pair -> the full gate report.

    `fx_px`+`cy_px` (a SET -- both or neither) and `acq_range_m` are the LIVE overrides. Passing
    none is a design check; passing all is what ADR-019 item 6 requires before a flight is booked
    (`verdict.bookable`). Raises ValueError on anything unusable rather than returning a verdict:
    the caller turns that into exit 2, which is a refusal and not a statement about the sensor."""
    cfg = json.loads(Path(depth_config).read_text())
    cam, gate_cfg = cfg["camera"], cfg["booking_gate"]

    _positive_finite("--speed / mission_speed_mps", mission_speed_mps)

    if (fx_px is None) != (cy_px is None):
        raise ValueError(
            "fx and cy are a SET: give both (off the SAME live camera_info -- K[0] and K[5]) or "
            "neither. fx sets the acquisition range and cy sets the threat-band coverage, so a "
            "live fx against a config cy is a 2x-optimistic answer assembled from two cameras.")
    live_intrinsics = fx_px is not None
    fx_source = ("live camera_info (--fx/--cy)" if live_intrinsics
                 else "config/depth_camera.json")
    fx = _positive_finite("--fx", fx_px, hi=FX_RANGE_PX[1], lo=FX_RANGE_PX[0]) if live_intrinsics \
        else _fx_from(cam)
    cy = _positive_finite("--cy", cy_px, hi=CY_RANGE_PX[1], lo=CY_RANGE_PX[0]) if live_intrinsics \
        else cam["image_height_px"] / 2.0
    # cx enters ONLY the frame-corner far-clip bound below; its source is reported, not assumed.
    cx = cam["image_width_px"] / 2.0

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

    # The gz far cull is applied to the EUCLIDEAN length of the camera-space point while the value
    # stored is the pinhole Z-DEPTH, so the effective Z-depth horizon shrinks by |ray| off-axis:
    # 1.17x at the horizontal frame edge, 1.26x at the corner. Quoting the on-axis 60 m as the
    # headroom over a 46.80 m acquisition bound overstates it by an order of magnitude.
    corner_ray = math.sqrt(1.0 + (cx / fx) ** 2 + (cy / fx) ** 2)
    far_corner_m = far_m / corner_ray

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
    # than WPNAV_SPD's 10 m/s default is flown with a LOWER speed cap, which is a different plant.
    # The 3.00 m escape never reaches that cap, so t_req is invariant -- shown, not claimed.
    capped_plant = replace(GUIDED_DEFAULT, name=f"guided_default@v_max={mission_speed_mps:g}",
                           v_max_ne_mps=min(GUIDED_DEFAULT.v_max_ne_mps, float(mission_speed_mps)))
    t_req_capped_s = time_to_displace_s(bar_m, capped_plant)

    band_from_m = band_covered_from_m(fx, cy, band_half_m)
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
                    f"FRAME CORNER (far clip {far_m:g} m culled on Euclidean slant range, "
                    f"|ray| {corner_ray:.3f}x on-axis). Headroom "
                    f"{100.0 * (far_corner_m - acq_m) / acq_m:.1f} % -- NOT the "
                    f"{100.0 * (far_m - acq_m) / acq_m:.0f} % the on-axis clip suggests")},
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
            "fx_px": round(fx, 4), "fx_source": fx_source,
            "cy_px": cy, "cy_source": fx_source,
            "cx_px": cx, "cx_source": "config/depth_camera.json image_width_px/2 (enters only the "
                                      "frame-corner far-clip bound)",
            "live_intrinsics": live_intrinsics,
            "update_rate_hz": cam["update_rate_hz"],
            "clip_far_m": far_m,
            "clip_far_at_frame_corner_m": round(far_corner_m, 3),
            "clip_semantics": ("value = pinhole Z-depth; the NEAR cull is on Z-depth, the FAR cull "
                               "on EUCLIDEAN slant range (gz-rendering8 depth_camera_fs.glsl), so "
                               "the effective Z horizon shrinks by |ray| off-axis"),
            "min_resolving_radius_px": MIN_RESOLVING_RADIUS_PX,
            "geometric_acquisition_range_m": round(geometric_acq_m, 3),
            "acquisition_range_m": round(acq_m, 3), "acquisition_range_source": acq_source,
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
            "required_lead_s": round(required_lead_s, 4),
            "available_lead_s": round(lead_s, 4),
            "margin": round(margin, 4),
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
            "why_not_bookable": (None if bookable else
                                 ("one or more checks failed" if not passed else
                                  "inputs are config-sourced; ADR-019 item 6 requires the forward "
                                  "horizon and intrinsics to come from the sensor's own live "
                                  "camera_info and a measured render horizon")),
        },
    }


def format_report(rep: dict) -> str:
    s, e, p, b, v = (rep["sensor"], rep["encounter"], rep["plant"], rep["budget"], rep["verdict"])
    L = [
        "SwathKeeper forward-sensor BOOKING GATE (ADR-019 item 6)",
        f"  sensor    fx={s['fx_px']:.2f} cy={s['cy_px']:.0f} px @ {s['update_rate_hz']:g} Hz, "
        f"far clip {s['clip_far_m']:g} m on-axis / "
        f"{s['clip_far_at_frame_corner_m']:.2f} m at the frame corner   [{s['fx_source']}]",
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
        L.append(f"  NOTE: flying at {e['mission_speed_mps']:g} m/s caps the plant's speed and "
                 f"MOVES t_req to {p['t_req_s_at_mission_speed_cap']:.3f} s -- the verdict above "
                 f"uses the uncapped {p['t_req_s']:.3f} s. Re-derive before booking.")
    else:
        L.append(f"  (a {e['mission_speed_mps']:g} m/s speed cap does not change t_req: the 3 m "
                 f"escape never reaches the velocity limit -- checked, not assumed)")
    if not v["pass"]:
        L.append(f"  VERDICT: FAIL -- DO NOT BOOK at {e['mission_speed_mps']:g} m/s. Slow the "
                 f"mission, or measure a longer horizon, and re-run. Reading the failing check "
                 f"tells you which.")
    elif v["bookable"]:
        L.append(f"  VERDICT: PASS and BOOKABLE at {e['mission_speed_mps']:g} m/s -- margin "
                 f"{b['margin']:.3f}x on live-measured inputs.")
    else:
        L.append(f"  VERDICT: PASS but NOT BOOKABLE -- {v['why_not_bookable']}. This is a DESIGN "
                 f"check: the geometry works. Measure the render horizon "
                 f"(docs/runbooks/FORWARD_DEPTH_SENSOR.md gate D3), pass --fx AND --cy (same "
                 f"camera_info message) AND --acq-range-m, and re-run for a bookable verdict.")
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
    ap.add_argument("--fx", type=float, default=None,
                    help="focal length px, K[0] of the LIVE /fg/depth/camera_info. Must be given "
                         "WITH --cy, off the same message.")
    ap.add_argument("--cy", type=float, default=None,
                    help="principal-point row px, K[5] of the same LIVE camera_info. fx sets the "
                         "acquisition range and cy sets the band coverage, so mixing a live fx "
                         "with a config cy is a 2x-optimistic answer from two different cameras.")
    ap.add_argument("--acq-range-m", type=float, default=None,
                    help="MEASURED acquisition range from the render (FORWARD_DEPTH_SENSOR.md gate "
                         "D3). Without it the tool uses the geometric upper bound and no verdict "
                         "is bookable.")
    ap.add_argument("--sweep", type=_parse_sweep, default=None, metavar="LO:HI:STEP",
                    help="print the margin across a mission-speed range instead of one verdict "
                         "(e.g. 2:10:0.5). Bookability is judged exactly as in single-speed mode: "
                         "exit 0 needs the full live input set, whatever the rows say.")
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

    kw = dict(fx_px=args.fx, cy_px=args.cy, acq_range_m=args.acq_range_m)
    speeds = args.sweep if args.sweep is not None else [args.speed]
    try:
        reps = [evaluate(v, **kw) for v in speeds]
    except ValueError as exc:
        # Every unusable input lands here and exits 2. It is NEVER exit 1: "I cannot evaluate this"
        # and "the sensor is insufficient" are different claims, and a typo must not produce the
        # second one.
        print(f"[predict_forward_lead] REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    # Bookability is a property of the INPUT SET, identical in both modes -- this is the whole
    # C1 fix. An earlier version returned 0 from --sweep whenever any row passed, on config numbers,
    # while two runbooks published "exit 0 = book the flight".
    live_inputs = bool(reps[0]["sensor"]["live_intrinsics"]) and args.acq_range_m is not None
    any_pass = any(r["verdict"]["pass"] for r in reps)
    # QA round-2 N1: exit 0 additionally requires EVERY evaluated speed to pass. In single-speed
    # mode all == any; in a sweep, "some speed in this range is bookable" is a choosing claim,
    # not an authorising one -- and the mixed live sweep was the one path that exited 0 beside
    # FAIL rows with no caveat. A sweep chooses; a single --speed run authorises (gate D4).
    all_pass = all(r["verdict"]["pass"] for r in reps)
    bookable = all_pass and live_inputs
    exit_code = (EXIT_PASS_BOOKABLE if bookable else
                 EXIT_PASS_NOT_BOOKABLE if any_pass else EXIT_FAIL)

    if args.sweep is not None:
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
            row = ("BOOKABLE" if (r["verdict"]["pass"] and live_inputs)
                   else "PASS*" if r["verdict"]["pass"] else "FAIL")
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
        if not live_inputs:
            print("  PASS* = passes the margin bar but is NOT BOOKABLE: these rows are computed "
                  "from config/depth_camera.json. ADR-019 item 6 wants the horizon and intrinsics "
                  "from the sensor's own live camera_info (FORWARD_DEPTH_SENSOR.md gates D1/D3). "
                  "This sweep is for CHOOSING a mission speed, not for authorising a flight.")
        elif not all_pass:
            print("  exit 0 withheld: at least one swept speed FAILs, and a sweep authorises "
                  "nothing. Choose a speed from the passing rows, then authorise it with a "
                  "single --speed run at that speed (gate D4).")
        report = {
            "schema_version": SCHEMA_VERSION,
            "tool": "scripts/predict_forward_lead.py --sweep",
            "gate": "ADR-019 item 6 (Council Ruling 002 tripwire (a)) -- the booking gate",
            "sweep": reps,
            "verdict": {
                "pass": any_pass,
                "bookable": bookable,
                "exit_code": exit_code,
                "fastest_passing_speed_mps": (None if best is None
                                              else best["encounter"]["mission_speed_mps"]),
                "why_not_bookable": (None if bookable else
                                     ("no speed in the swept range passes" if not any_pass else
                                      "at least one swept speed FAILs -- a sweep chooses, a "
                                      "single --speed run authorises (gate D4)" if live_inputs else
                                      "inputs are config-sourced; ADR-019 item 6 requires the "
                                      "forward horizon and intrinsics to come from the sensor's "
                                      "own live camera_info and a measured render horizon")),
            },
        }
    else:
        report = reps[0]
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
