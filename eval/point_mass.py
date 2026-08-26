#!/usr/bin/env python3
"""A jerk/accel/velocity-limited POINT-MASS model of ArduCopter in GUIDED position mode.

WHY THIS EXISTS (ADR-016 / Council Ruling 001). Across the three committed live flights, 84
accepted avoidance maneuvers commanded ~10 m lateral diverts and the aircraft displaced 0.18 /
0.42 / 0.05 m. Nothing in the repo could say whether that is (a) a broken command path, (b) bad
candidate ordering, (c) too little warning time, or (d) exactly what an un-tuned ArduCopter does
inside a sub-second GUIDED window. Those four are confounded on flown evidence. This model is the
instrument that separates them offline: drive it with the SAME setpoints the executor really sent,
over the SAME window, and see whether the plant alone explains the displacement.

WHAT IT MODELS -- and only this. AC_PosControl's KINEMATIC INPUT SHAPING, which is what actually
bounds a copter's response to a position target:
  * a sqrt (stopping-distance) position->velocity controller, `PSC_NE_POS_P` and `a_max`;
  * a velocity cap;
  * an acceleration cap applied to the horizontal VECTOR (so a dodge competes with the deceleration
    of the cruise leg for one shared budget -- that coupling is a real and load-bearing effect);
  * a jerk cap on the rate of change of that acceleration vector.
Horizontal (NE) and vertical (U) are shaped independently, as ArduPilot does.

WHICH CODE PATH -- traced, not assumed, at the pinned firmware SHA. `/ap/cmd_gps_pose` ->
AP_DDS_External_Control::handle_global_position_control -> AP_ExternalControl_Copter::
set_global_position -> Copter::set_target_location -> ModeGuided::set_destination(Location). There
`use_wpnav_for_position_control()` reads GUID_OPTIONS bit 6, which is CLEAR at the default 0, so the
command takes the AC_PosControl path (`pos_control_start`), NOT the AC_WPNav S-curve path. But
`pva_control_start()` then seeds PosControl's limits FROM AC_WPNav's parameters:
`NE_set_max_speed_accel_m(wp_nav->get_default_speed_NE_ms(), wp_nav->get_wp_acceleration_mss())`.
So the effective limits are the WPNAV_* speeds/accels with the PSC_* jerk -- which is neither of the
two "obvious" answers, and is why `GUIDED_DEFAULT` below mixes the two families. (Sources per
constant, below; all fetched at ArduPilot 9895756d874ec9128d50918f6747a83706f4e221, the SHA
CLAUDE.md pins.)

WHAT IT DELIBERATELY DOES NOT MODEL -- the transfer-gap register's first entries. Each of these
makes the model OPTIMISTIC (the real aircraft is slower than this), so a counterfactual that fails
here fails on the real vehicle too, and one that passes here is an upper bound, never a promise:
  1. ATTITUDE DYNAMICS. A multirotor produces lateral acceleration by leaning; the roll/pitch loop
     takes ~0.2-0.4 s to establish a new lean angle. Modelled here as instantaneous within the jerk
     cap.
  2. MOTOR / THRUST LAG and battery sag -- the actuator is a first-order lag, not a delta.
  3. EKF / TELEMETRY LAG. The position the controller acts on is an estimate, delayed and smoothed;
     `/ap/pose/filtered` is what the executor sees, and it is not the true state.
  4. WIND AND AERO DRAG. Zero here. Drag opposes an accelerating dodge and helps a brake.
  5. MODE-SWITCH LATENCY. AUTO->GUIDED via /ap/mode_switch is instantaneous here; on the real
     vehicle the service call, the mode change and the first honoured setpoint are not free.
  6. YAW. The model is a point; the real vehicle yaws, and a yawing multirotor's camera footprint
     (the thing that produces the detections) rotates with it.
  7. THE ATTITUDE-LIMIT INTERACTION. `ANGLE_MAX` (30 deg -> 5.55 m/s^2) is offered as a separate
     limit set, not folded in as a hard ceiling on the default sets.

STDLIB ONLY and no ROS: this is an offline study model, importable by `eval/replay_point_mass.py`
and by `tests/test_point_mass_replay.py` with nothing installed.
"""
import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

Vec3 = Tuple[float, float, float]

# Standard gravity, for the ANGLE_MAX -> lateral-acceleration ceiling. CODATA/ISO 80000 value.
G_M_S2 = 9.80665

# ---------------------------------------------------------------------------------------------
# PLANT LIMITS. Every number below is a DEFAULT read out of ArduPilot source at the pinned SHA
# 9895756d874ec9128d50918f6747a83706f4e221 (CLAUDE.md), because this project pins NO WPNAV_*,
# GUID_*, PSC_* or ANGLE_MAX override anywhere: config/sitl_params/dds_udp.parm sets DDS_ENABLE and
# DDS_UDP_PORT and nothing else. So these ARE the numbers that flew on all three logged encounters.
# Doctrine (ADR-016): physical parameters come from the vehicle, never from prose -- hence the URL
# and the source symbol on every line rather than a remembered parameter name. Note also that the
# names moved in this firmware (WPNAV_SPEED -> WPNAV_SPD, WPNAV_ACCEL -> WPNAV_ACC,
# PSC_JERK_XY -> PSC_NE_JERK): a tutorial's parameter list would have edited knobs that do not exist.
# ---------------------------------------------------------------------------------------------
_AC_WPNAV_CPP = ("https://raw.githubusercontent.com/ArduPilot/ardupilot/"
                 "9895756d874ec9128d50918f6747a83706f4e221/libraries/AC_WPNav/AC_WPNav.cpp")
_AC_WPNAV_H = ("https://raw.githubusercontent.com/ArduPilot/ardupilot/"
               "9895756d874ec9128d50918f6747a83706f4e221/libraries/AC_WPNav/AC_WPNav.h")
_AC_POSCONTROL_H = ("https://raw.githubusercontent.com/ArduPilot/ardupilot/"
                    "9895756d874ec9128d50918f6747a83706f4e221/libraries/AC_AttitudeControl/"
                    "AC_PosControl.h")
_AC_POSCONTROL_CPP = ("https://raw.githubusercontent.com/ArduPilot/ardupilot/"
                      "9895756d874ec9128d50918f6747a83706f4e221/libraries/AC_AttitudeControl/"
                      "AC_PosControl.cpp")
_AC_ATTITUDE_CPP = ("https://raw.githubusercontent.com/ArduPilot/ardupilot/"
                    "9895756d874ec9128d50918f6747a83706f4e221/libraries/AC_AttitudeControl/"
                    "AC_AttitudeControl.cpp")
_MODE_GUIDED_CPP = ("https://raw.githubusercontent.com/ArduPilot/ardupilot/"
                    "9895756d874ec9128d50918f6747a83706f4e221/ArduCopter/mode_guided.cpp")


@dataclass(frozen=True)
class PlantLimits:
    """One hypothesis about what bounded the vehicle. Frozen so a result always names its plant."""
    name: str
    v_max_ne_mps: float
    a_max_ne_mps2: float
    jerk_ne_mps3: float
    v_max_up_mps: float
    v_max_down_mps: float
    a_max_u_mps2: float
    jerk_u_mps3: float
    pos_p: float
    provenance: str

    def as_dict(self) -> dict:
        return {"name": self.name, "v_max_ne_mps": self.v_max_ne_mps,
                "a_max_ne_mps2": self.a_max_ne_mps2, "jerk_ne_mps3": self.jerk_ne_mps3,
                "v_max_up_mps": self.v_max_up_mps, "v_max_down_mps": self.v_max_down_mps,
                "a_max_u_mps2": self.a_max_u_mps2, "jerk_u_mps3": self.jerk_u_mps3,
                "pos_p": self.pos_p, "provenance": self.provenance}


# THE AS-FLOWN HYPOTHESIS. GUIDED position target at GUID_OPTIONS=0 -> AC_PosControl shaping seeded
# from AC_WPNav's parameters (mode_guided.cpp `pva_control_start`, lines 255-260).
GUIDED_DEFAULT = PlantLimits(
    name="guided_default",
    v_max_ne_mps=10.0,      # WPNAV_SPD  WP_SPD_DEFAULT 10.0 m/s        AC_WPNav.cpp:8
    a_max_ne_mps2=2.5,      # WPNAV_ACC  WPNAV_ACCELERATION_MS 2.5       AC_WPNav.h:15
    jerk_ne_mps3=5.0,       # PSC_NE_JERK POSCONTROL_JERK_NE_MSSS 5.0    AC_PosControl.h:20
    v_max_up_mps=2.5,       # WPNAV_SPD_UP  WP_SPD_UP_DEFAULT 2.5        AC_WPNav.cpp:12
    v_max_down_mps=1.5,     # WPNAV_SPD_DN  WP_SPD_DOWN_DEFAULT 1.5      AC_WPNav.cpp:13
    a_max_u_mps2=1.0,       # WPNAV_ACC_Z   WP_ACC_Z_DEFAULT 1.0         AC_WPNav.cpp:14
    jerk_u_mps3=5.0,        # PSC_D_JERK  POSCONTROL_JERK_D_MSSS 5.0     AC_PosControl.h:30
    pos_p=1.0,              # PSC_NE_POS_P  POSCONTROL_NE_POS_P 1.0 (Copter branch)
                            #                                            AC_PosControl.cpp:63
    provenance=(f"GUIDED position target with GUID_OPTIONS=0 takes the AC_PosControl path "
                f"(ModeGuided::use_wpnav_for_position_control() false -> pos_control_start), and "
                f"pva_control_start seeds PosControl's NE/D speed+accel FROM AC_WPNav's params "
                f"({_MODE_GUIDED_CPP} lines 255-260). Speeds/accels: {_AC_WPNAV_CPP} and "
                f"{_AC_WPNAV_H}. Jerks and position P gain: {_AC_POSCONTROL_H}, "
                f"{_AC_POSCONTROL_CPP}. No WPNAV_*/GUID_*/PSC_* override exists in this repo."))

# THE ALTERNATIVE HYPOTHESIS, kept because it is the one a reader who has NOT traced
# `pva_control_start` would reach for: AC_PosControl's own constructor defaults, which are what
# would bound the vehicle if the wp_nav seeding did not happen. Running both is how the fit gets to
# choose instead of the author.
POSCONTROL_BARE = PlantLimits(
    name="poscontrol_bare",
    v_max_ne_mps=5.0,       # POSCONTROL_SPEED_MS 5.0                    AC_PosControl.h:25
    a_max_ne_mps2=1.0,      # POSCONTROL_ACCEL_NE_MSS 1.0                AC_PosControl.h:19
    jerk_ne_mps3=5.0,       # POSCONTROL_JERK_NE_MSSS 5.0                AC_PosControl.h:20
    v_max_up_mps=2.5,       # POSCONTROL_SPEED_UP_MS 2.5                 AC_PosControl.h:27
    v_max_down_mps=1.5,     # POSCONTROL_SPEED_DOWN_MS 1.5               AC_PosControl.h:26
    a_max_u_mps2=2.5,       # POSCONTROL_ACCEL_D_MSS 2.5                 AC_PosControl.h:29
    jerk_u_mps3=5.0,        # POSCONTROL_JERK_D_MSSS 5.0                 AC_PosControl.h:30
    pos_p=1.0,              # POSCONTROL_NE_POS_P 1.0                    AC_PosControl.cpp:63
    provenance=(f"AC_PosControl's own constructor defaults, i.e. the limits that would apply if "
                f"pva_control_start did NOT overwrite them from AC_WPNav. Retained as a rival "
                f"hypothesis so the flown data selects between them: {_AC_POSCONTROL_H}, "
                f"{_AC_POSCONTROL_CPP}."))

# THE PHYSICAL CEILING. Not a default -- the most a correctly tuned multirotor of this class could
# ever do without changing the airframe: lateral accel from the maximum permitted lean angle,
# a = g*tan(ANGLE_MAX). Jerk at the top of the parameter's own documented range. This is the
# "tuned-up" arm of the plant-limit sweep, and it is the number a counterfactual must beat to be
# dismissed as "unreachable at ANY tuning", which is exactly what the ADR-017 speed doctrine needs.
ANGLE_MAX_DEG = 30.0        # ANGLE_MAX  AC_ATTITUDE_CONTROL_ANGLE_MAX_DEFAULT 30.0 deg
#                            AC_AttitudeControl.CPP:25-26 (the #ifndef/#define pair) -- NOT the .h,
#                            which is where the first draft of this comment sent the reader. It is
#                            the one constant here that is not a firmware DEFAULT but a physical
#                            ceiling, so its citation has to survive being checked.
ANGLE_MAX_CEILING = PlantLimits(
    name="angle_max_ceiling",
    v_max_ne_mps=10.0,                                # WPNAV_SPD, unchanged
    a_max_ne_mps2=G_M_S2 * math.tan(math.radians(ANGLE_MAX_DEG)),   # 5.66 m/s^2
    jerk_ne_mps3=20.0,      # top of the JERK parameter's documented @Range 1-20  AC_WPNav.cpp:31-37
    v_max_up_mps=2.5,
    v_max_down_mps=1.5,
    a_max_u_mps2=2.5,
    jerk_u_mps3=20.0,
    pos_p=1.0,
    provenance=(f"NOT a default: the airframe/attitude ceiling. a_max = g*tan(ANGLE_MAX) with "
                f"ANGLE_MAX's default 30 deg ({_AC_ATTITUDE_CPP} lines 25-26) and g = {G_M_S2}; "
                f"jerk at the top of the JERK parameter @Range 1-20 ({_AC_WPNAV_CPP} lines 31-37). "
                f"Nothing tuned inside the flight controller can beat this without raising "
                f"ANGLE_MAX, so a maneuver this arm cannot fly is unreachable by tuning."))

PLANTS = (GUIDED_DEFAULT, POSCONTROL_BARE, ANGLE_MAX_CEILING)
PLANTS_BY_NAME = {p.name: p for p in PLANTS}


# ------------------------------------------------------------------------------------ the model
def sqrt_controller(error_m: float, pos_p: float, a_max: float) -> float:
    """ArduPilot's `sqrt_controller` (AP_Math/control.cpp): the position->velocity law that makes a
    copter arrive at a target with zero velocity instead of overshooting it.

    Linear (`pos_p * error`) close in, sqrt (`sqrt(2*a*(e - linear_dist/2))`) further out, joined so
    that the two agree at `linear_dist = a_max / pos_p^2`. Scalar and sign-preserving.

    Reimplemented rather than approximated by a plain P gain because the sqrt branch IS the reason a
    10 m divert command does not produce a 10 m/s velocity step: the demanded speed is bounded by
    what the accel limit can subsequently arrest."""
    if a_max <= 0.0:
        return error_m * pos_p
    if pos_p <= 0.0:
        return math.copysign(math.sqrt(2.0 * a_max * abs(error_m)), error_m)
    linear_dist = a_max / (pos_p * pos_p)
    if abs(error_m) <= linear_dist:
        return error_m * pos_p
    return math.copysign(math.sqrt(2.0 * a_max * (abs(error_m) - linear_dist / 2.0)), error_m)


class PointMass:
    """A vehicle reduced to (position, velocity, acceleration) under a position setpoint.

    One `step(dt, target)` per integration tick. The setpoint is held between calls (zero-order
    hold), exactly as a GUIDED position target is held between the executor's 5 Hz re-commands."""

    def __init__(self, pos: Sequence[float], vel: Sequence[float], limits: PlantLimits):
        self.pos = [float(pos[0]), float(pos[1]), float(pos[2])]
        self.vel = [float(vel[0]), float(vel[1]), float(vel[2])]
        self.acc = [0.0, 0.0, 0.0]
        self.lim = limits

    def step(self, dt: float, target: Sequence[float]) -> None:
        if dt <= 0.0:
            return
        lim = self.lim
        # --- horizontal (NE), shaped as a VECTOR so a dodge and a deceleration share one budget ---
        ex, ey = float(target[0]) - self.pos[0], float(target[1]) - self.pos[1]
        dist = math.hypot(ex, ey)
        v_des = min(lim.v_max_ne_mps, sqrt_controller(dist, lim.pos_p, lim.a_max_ne_mps2))
        ux, uy = (ex / dist, ey / dist) if dist > 1e-9 else (0.0, 0.0)
        ax, ay = self._shape2((v_des * ux, v_des * uy), (self.vel[0], self.vel[1]),
                              (self.acc[0], self.acc[1]), dt,
                              lim.a_max_ne_mps2, lim.jerk_ne_mps3)
        # --- vertical (U), its own limits and an asymmetric speed cap (climb slower than descent) -
        ez = float(target[2]) - self.pos[2]
        vz_des = sqrt_controller(ez, lim.pos_p, lim.a_max_u_mps2)
        vz_des = max(-lim.v_max_down_mps, min(lim.v_max_up_mps, vz_des))
        (az,) = self._shape1(vz_des, self.vel[2], self.acc[2], dt,
                             lim.a_max_u_mps2, lim.jerk_u_mps3)

        # The acceleration RAMPS across the step, from `self.acc` to the newly shaped value, because
        # that is what a jerk limit means. Integrating it as if the new value applied for the whole
        # step is a first-order error and it is not small here: it over-predicts the jerk-limited
        # start -- the regime every sub-second dodge in this study lives in -- by j*dt*t/2, measured
        # as +7.6 % on the j*t^3/6 closed form at t = 0.1 s. Trapezoid on acceleration, then
        # trapezoid on velocity, makes both closed forms exact to integration precision.
        acc = [ax, ay, az]
        new = [self.vel[i] + 0.5 * (self.acc[i] + acc[i]) * dt for i in range(3)]
        speed = math.hypot(new[0], new[1])
        if speed > lim.v_max_ne_mps and speed > 0.0:
            k = lim.v_max_ne_mps / speed
            new[0] *= k
            new[1] *= k
        new[2] = max(-lim.v_max_down_mps, min(lim.v_max_up_mps, new[2]))
        for i in range(3):
            self.pos[i] += 0.5 * (self.vel[i] + new[i]) * dt
        self.vel = new
        self.acc = acc

    @staticmethod
    def _shape2(v_des, v, a_prev, dt: float, a_max: float, jerk: float):
        """Acceleration command for a 2-D axis pair: drive velocity to `v_des`, jerk- and
        magnitude-limited. This is AC_PosControl's `shape_vel_accel` structure.

        THE ACCELERATION TARGET IS ITSELF A SQRT CONTROLLER, on the VELOCITY error, with the jerk
        limit as its second-order bound and `jerk / a_max` as its gain. Not decoration: a naive
        `(v_des - v) / dt` demand saturates at `a_max` for every step until the velocity error
        vanishes, which makes the loop bang-bang -- and a bang-bang accel that can only slew at
        5 m/s^3 needs 1.9 s to reverse, so it overshoots and never settles. Measured, before this
        was fixed: commanded to a point 10.8 m away, the model overshot to 13.7 m and was still
        limit-cycling +/-0.5 m at t = 20 s. Every counterfactual clearance would have inherited
        that oscillation. The sqrt law ANTICIPATES the reversal -- it demands only the acceleration
        the jerk limit can still take back to zero in time -- so the vehicle arrives and stays.

        Jerk-limit first, magnitude-cap second, and that ORDER is safe rather than lucky: the accel
        cap is a convex disc that already contains `a_prev`, and projection onto a convex set is
        non-expansive, so clamping can only shorten the step it just took."""
        dvx, dvy = v_des[0] - v[0], v_des[1] - v[1]
        dmag = math.hypot(dvx, dvy)
        gain = (jerk / a_max) if a_max > 0.0 else 0.0
        want = min(sqrt_controller(dmag, gain, jerk), dmag / dt if dt > 0.0 else math.inf)
        ux, uy = (dvx / dmag, dvy / dmag) if dmag > 1e-12 else (0.0, 0.0)
        ax, ay = want * ux, want * uy
        dax, day = ax - a_prev[0], ay - a_prev[1]
        dmag_a = math.hypot(dax, day)
        jmax = jerk * dt
        if dmag_a > jmax > 0.0:
            k = jmax / dmag_a
            dax, day = dax * k, day * k
        ax, ay = a_prev[0] + dax, a_prev[1] + day
        amag = math.hypot(ax, ay)
        if amag > a_max and amag > 0.0:
            k = a_max / amag
            ax, ay = ax * k, ay * k
        return ax, ay

    @staticmethod
    def _shape1(v_des: float, v: float, a_prev: float, dt: float, a_max: float, jerk: float):
        """The 1-D (vertical) form of `_shape2`, same law."""
        dv = v_des - v
        gain = (jerk / a_max) if a_max > 0.0 else 0.0
        want = sqrt_controller(dv, gain, jerk)
        if dt > 0.0:
            want = max(-abs(dv) / dt, min(abs(dv) / dt, want))
        da = want - a_prev
        jmax = jerk * dt
        if abs(da) > jmax:
            da = math.copysign(jmax, da)
        a = a_prev + da
        if abs(a) > a_max:
            a = math.copysign(a_max, a)
        return (a,)


# The integration step. 5 ms is ~2 orders below the 0.2 s command tick and ~1 order below
# ArduCopter's own 400 Hz main loop, so the model's answer is set by the LIMITS, not by the
# discretisation; tests/test_point_mass_replay.py pins the closed-form agreement that shows it.
DEFAULT_INTEGRATION_DT_S = 0.005


def simulate(start_pos: Sequence[float],
             start_vel: Sequence[float],
             commands: Sequence[Tuple[float, Vec3]],
             t_start: float,
             t_end: float,
             limits: PlantLimits,
             sample_dt_s: float = 0.05,
             integration_dt_s: float = DEFAULT_INTEGRATION_DT_S,
             sample_times: Optional[Sequence[float]] = None) -> List[Tuple[float, Vec3]]:
    """Fly the point mass from `t_start` to `t_end` under a zero-order-held setpoint schedule.

    `commands` is [(absolute time, target ENU)] in ascending time; the target in force is the last
    one whose time has passed. A command schedule that starts AFTER `t_start` means the vehicle
    coasts ballistically until then -- which is how "what if the warning had come earlier/later"
    is expressed, and why `commands` is a schedule rather than a single target.

    Returns [(t, (x, y, z))] at `sample_times` when given, else every `sample_dt_s`; `t_start` is
    always the first entry and `t_end` always the last. That sample series is fed straight to
    `check_live_flight_log.ground_truth_cpa` as a synthetic `flown_path_enu` + `tick_stamp_sim_s`
    pair, so the counterfactual is scored by the SAME CPA math as a real flight -- no second
    geometry implementation anywhere in this study. `sample_times` exists because the plant fit
    compares against telemetry at the flight's own tick instants, and a nearest-sample lookup on a
    0.02 s grid would inject ~0.1 m of phantom error at 9 m/s -- five times the quantity being
    measured on the 2026-08-25 window."""
    veh = PointMass(start_pos, start_vel, limits)
    sched = sorted(commands, key=lambda c: c[0])
    want = sorted(t for t in (sample_times if sample_times is not None else ())
                  if t_start < t < t_end)
    out: List[Tuple[float, Vec3]] = [(t_start, (veh.pos[0], veh.pos[1], veh.pos[2]))]
    t = t_start
    next_sample = t_start + sample_dt_s
    idx = wi = 0
    target: Optional[Vec3] = None
    while idx < len(sched) and sched[idx][0] <= t_start:
        target = sched[idx][1]
        idx += 1
    # Every command instant and every requested sample instant SPLITS an integration step, so the
    # step budget has to allow for them or a long window would silently terminate early and report
    # a truncated position under the right timestamp.
    max_steps = (int((t_end - t_start) / integration_dt_s) + len(sched) + len(want) + 16
                 if t_end > t_start else 0)
    guard = 0
    while t < t_end - 1e-12 and guard <= max_steps:
        guard += 1
        step = min(integration_dt_s, t_end - t)
        # Do not step past the next command or the next requested sample: a setpoint must take
        # effect at its own instant, and a sample must be read at its own instant.
        if idx < len(sched) and sched[idx][0] < t + step:
            step = max(sched[idx][0] - t, 1e-9)
        if wi < len(want) and want[wi] < t + step:
            step = max(want[wi] - t, 1e-9)
        if target is None:
            # No command yet -> ballistic coast at the entry velocity (no drag; see the module
            # docstring's transfer-gap register). This is the honest "the command never arrived"
            # baseline, and it is also hypothesis H_broken in the plant fit.
            for i in range(3):
                veh.pos[i] += veh.vel[i] * step
        else:
            veh.step(step, target)
        t += step
        while idx < len(sched) and sched[idx][0] <= t + 1e-12:
            target = sched[idx][1]
            idx += 1
        while wi < len(want) and want[wi] <= t + 1e-9:
            out.append((want[wi], (veh.pos[0], veh.pos[1], veh.pos[2])))
            wi += 1
        if sample_times is None:
            while next_sample <= t + 1e-9 and next_sample <= t_end + 1e-9:
                out.append((next_sample, (veh.pos[0], veh.pos[1], veh.pos[2])))
                next_sample += sample_dt_s
    if out[-1][0] < t_end - 1e-9:
        out.append((t_end, (veh.pos[0], veh.pos[1], veh.pos[2])))
    return out


def max_displacement_m(duration_s: float, limits: PlantLimits) -> float:
    """Greatest distance this plant can move along ONE axis in `duration_s`, FROM REST, applying
    full authority the whole time.

    A closed-form upper bound with no controller in it at all -- no sqrt controller, no target, no
    competing deceleration demand -- so it answers "could ANY escape have done it?" rather than
    "did this candidate do it?". Jerk ramp to `a_max`, then constant `a_max`, then the velocity cap:
        t1 = a_max / jerk;  s(t) = jerk*t^3/6                       for t <= t1
        s(t) = s(t1) + v(t1)*(t-t1) + a_max*(t-t1)^2/2              after, until v hits v_max
        s(t) = ... + v_max*(remaining)                              once capped.

    FROM REST, and there is no entry-velocity parameter, deliberately. An earlier version took one
    and was wrong twice over: it added `v_entry * duration` on top of the from-rest profile (which
    double-counts, since the accel profile already starts from that velocity) and it fed the
    unshifted `v` into the velocity-cap test (so the cap bit at the wrong time) -- measured 5.229 m
    claimed against 3.729 m true at v0 = 3 m/s. Nothing needed it: every caller asks the LATERAL
    question, and the vehicle's lateral velocity at the moment a dodge is commanded is zero by
    construction (it is flying along its lane). A parameter that is wrong and unused is worse than
    absent, because the next reader will use it.

    This is the function the ADR-017 speed doctrine reads: the bar is 3.00 m of lateral separation
    and this is the most lateral separation physics allows in the lead the sensor can give."""
    if duration_s <= 0.0:
        return 0.0
    j, a_max, v_max = limits.jerk_ne_mps3, limits.a_max_ne_mps2, limits.v_max_ne_mps
    t1 = a_max / j if j > 0.0 else 0.0
    if duration_s <= t1:
        return j * duration_s ** 3 / 6.0
    s = j * t1 ** 3 / 6.0
    v = 0.5 * j * t1 * t1                        # speed at the end of the jerk ramp
    rem = duration_s - t1
    # Time until the velocity cap bites, after which displacement is linear in time.
    t_cap = max(0.0, (v_max - v) / a_max) if a_max > 0.0 else math.inf
    if rem <= t_cap:
        return s + v * rem + 0.5 * a_max * rem * rem
    s += v * t_cap + 0.5 * a_max * t_cap * t_cap
    return s + v_max * (rem - t_cap)


def time_to_displace_s(target_m: float, limits: PlantLimits,
                       t_max_s: float = 60.0) -> Optional[float]:
    """Inverse of `max_displacement_m`: the shortest time in which this plant can move `target_m`
    from rest at full authority, or None if it cannot inside `t_max_s`. Bisection on a monotone
    function.

    This is the number the mount decision needs stated as a REQUIREMENT: multiply it by the closing
    speed and you have the sensor horizon the geometry must supply."""
    if target_m <= 0.0:
        return 0.0
    if max_displacement_m(t_max_s, limits) < target_m:
        return None
    lo, hi = 0.0, t_max_s
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if max_displacement_m(mid, limits) < target_m:
            lo = mid
        else:
            hi = mid
    return hi
