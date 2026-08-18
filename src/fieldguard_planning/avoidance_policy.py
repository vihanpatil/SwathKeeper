"""Reactive-avoidance DECISION policy (Weeks 3-4 core loop, workstream 2) -- the "when and where to
dodge" brain.

Boundary (see `avoidance_types.py`): this module consumes an abstract `Detection` (a dynamic-obstacle
estimate in world-ENU, decoupled from NDVI pixels) + a `DroneState` + the static-obstacle `GeofenceMap`
and produces a single `AvoidanceManeuver` with a `Decision` in {PROCEED, DIVERT, HOLD}. It decides;
the executor (`avoidance_executor.py`, flight-software-engineer, ADR-006) commands the setpoint over
`/ap/cmd_gps_pose` and reconciles coverage debt. Interface is deliberately narrow (detection ->
maneuver) and stdlib-only, so the whole decision layer is unit-testable on a bare interpreter with no
sim, no ROS 2, no pixels.

This is a DEFENSIBLE v1 policy, not a tuned model. Every threshold is an explicit, documented,
tunable parameter (see `AvoidancePolicy.__init__`) so an interviewer can see exactly what triggers a
dodge and why. The safety posture is asymmetric on purpose (ADR-003): a missed bird is a safety bug,
a wasteful dodge is cheap -- so the threat test is generous and the setpoint gate is strict.

SAFETY GUARANTEE (the load-bearing invariant this module upholds):
  A DIVERT maneuver is emitted ONLY with a setpoint that has passed, in this order:
    1. `geofence.is_safe_3d(setpoint, vertical_margin_m, alt_bounds)`  -- HARD 3D gate (ADR-006):
       outside every tree's 3D volume AND inside the altitude envelope. The executor re-checks this
       as a backstop and falls back to HOLD on rejection; we never hand it an unvetted setpoint.
    2. swept-path lateral tree clearance: the segment drone->setpoint stays clear of every tree's
       XY exclusion column (`geofence.segment_clearance`). Rationale: a dodge that *sweeps through*
       a tree column is safe today only by the altitude exemption (cruise 15 m >> 5.5 m canopy band);
       keeping horizontal clearance means the reactive maneuver never *relies* on that exemption, so
       an unexpected altitude loss mid-dodge is not a strike. This is what makes the `geo_avoid_into_tree`
       scenario dodge away from row 2 instead of steering the naive away-from-bird path through it.
    3. field-polygon containment (if a polygon is supplied) with an inward margin -- a dodge must not
       leave the surveyed field.
    4. it actually increases separation from the triggering bird and keeps a minimum clearance from
       every other in-cylinder bird.
  If NO candidate direction passes all four, the policy returns HOLD (hover in GUIDED) rather than
  emit a setpoint it cannot prove safe. HOLD is the correct answer to "boxed in", not a failure.

Dependency: stdlib only (math) + sibling contract modules. No numpy, no ROS 2.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import List, Optional, Sequence, Tuple

from fieldguard_planning.avoidance_types import (
    AvoidanceManeuver,
    Decision,
    Detection,
    DroneState,
)
from fieldguard_planning.geofence import GeofenceMap

XY = Tuple[float, float]
ENU = Tuple[float, float, float]

# Candidate dodge directions, as rotations (degrees, CCW) applied to the primary "away-from-bird"
# heading. 0 = straight away (best); +/-45 and +/-90 are progressively more lateral escapes. All of
# these strictly INCREASE separation from the triggering bird (for a perpendicular move, new_dist^2 =
# d0^2 + divert^2 > d0^2), so trying them in order degrades gracefully from "ideal" to "still safe".
# 180 (straight toward the bird) is deliberately excluded. Ordered by preference.
_CANDIDATE_ANGLES_DEG: Tuple[float, ...] = (0.0, 45.0, -45.0, 90.0, -90.0, 135.0, -135.0)


@dataclass(frozen=True)
class PolicyParams:
    """Every knob the policy exposes, with the v1 default and its rationale. Frozen so a decision is
    always taken against an explicit, logged parameter set (goes into the maneuver `debug` dict).

    Threat model = a proximity CYLINDER around the drone:
      * `threat_radius_m`   -- horizontal radius; a bird within it is a candidate threat.
      * `vertical_threat_m` -- half-height; only birds within this |dz| of the drone are threats
        (a bird 9 m below cruise is not on a collision course this frame). Generous by design.
    Detection carries no velocity (it is a single-frame estimate), so v1 does NOT compute a closing
    RATE -- it conservatively treats any bird inside the cylinder as a threat. A true closing-bearing
    test needs track-level velocity and is a documented future refinement, not a v1 gate: suppressing
    a bird to look clever is exactly the failure mode ADR-003 warns against.
    """
    cruise_alt_m: float = 15.0          # divert setpoints are placed at this altitude (world-ENU U)
    threat_radius_m: float = 12.0       # horizontal threat cylinder radius
    vertical_threat_m: float = 6.0      # threat cylinder half-height (|bird_z - drone_z|)
    divert_distance_m: float = 10.0     # lateral distance of the dodge setpoint from the drone
    lateral_tree_margin_m: float = 0.0  # required swept-path clearance beyond each tree obstacle_radius_m
    min_bird_clearance_m: float = 3.0   # setpoint must stay at least this far (XY) from every threat
    vertical_margin_m: float = 1.0      # passed to is_safe_3d (canopy band buffer)
    alt_min_m: float = 2.0              # altitude envelope floor (is_safe_3d alt_bounds)
    alt_max_m: float = 30.0             # altitude envelope ceiling
    field_margin_m: float = 1.0         # inward margin from the field polygon boundary for a setpoint
    min_confidence: float = 0.0         # ignore detections below this confidence (0.0 = trust all)
    # Staleness gate: a stamped detection older than this (vs the `now_s` passed to decide) is
    # treated as ABSENT — a frame from the past is not evidence about the world now, and acting on
    # it can trigger a phantom dodge or mask a live threat. None = gate OFF (v1 default: the --demo
    # bird and scripted sources do not stamp yet). The gate only fires when it can actually compute
    # an age (gate on AND now_s given AND detection stamped); otherwise it fails OPEN, because
    # silently dropping unstamped detections would disable avoidance for every current source.
    max_detection_age_s: Optional[float] = None

    @property
    def alt_bounds(self) -> Tuple[float, float]:
        return (self.alt_min_m, self.alt_max_m)


# ----------------------------------------------------------------------------- geometry helpers
def _norm(v: XY) -> float:
    return math.hypot(v[0], v[1])


def _unit(v: XY) -> Optional[XY]:
    n = _norm(v)
    if n < 1e-9:
        return None
    return (v[0] / n, v[1] / n)


def _rotate(v: XY, deg: float) -> XY:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return (v[0] * c - v[1] * s, v[0] * s + v[1] * c)


def _point_in_polygon(px: float, py: float, poly: Sequence[XY]) -> bool:
    """Ray-casting point-in-polygon (same convention as coverage._point_in_polygon; reimplemented
    locally so this module has no cross-dependency on coverage.py)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_edge_distance(px: float, py: float, poly: Sequence[XY]) -> float:
    """Min distance from (px,py) to any polygon edge -- used to enforce an inward margin."""
    best = math.inf
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        if seg == 0.0:
            d = math.hypot(px - ax, py - ay)
        else:
            t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
            d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
        best = min(best, d)
    return best


# ----------------------------------------------------------------------------- the policy
class AvoidancePolicy:
    """Stateless (per-call) reactive-avoidance decision policy. Construct once with tunables, then
    call `decide` per frame. `decide` is pure: same inputs -> same maneuver, so it is trivially
    unit-testable and its output is fully reproducible in a flight log."""

    def __init__(
        self,
        *,
        cruise_alt_m: float = 15.0,
        threat_radius_m: float = 12.0,
        vertical_threat_m: float = 6.0,
        divert_distance_m: float = 10.0,
        lateral_tree_margin_m: float = 0.0,
        min_bird_clearance_m: float = 3.0,
        vertical_margin_m: float = 1.0,
        alt_min_m: float = 2.0,
        alt_max_m: float = 30.0,
        field_margin_m: float = 1.0,
        min_confidence: float = 0.0,
        max_detection_age_s: Optional[float] = None,
        field_polygon: Optional[Sequence[XY]] = None,
    ) -> None:
        self.params = PolicyParams(
            cruise_alt_m=cruise_alt_m,
            threat_radius_m=threat_radius_m,
            vertical_threat_m=vertical_threat_m,
            divert_distance_m=divert_distance_m,
            lateral_tree_margin_m=lateral_tree_margin_m,
            min_bird_clearance_m=min_bird_clearance_m,
            vertical_margin_m=vertical_margin_m,
            alt_min_m=alt_min_m,
            alt_max_m=alt_max_m,
            field_margin_m=field_margin_m,
            min_confidence=min_confidence,
            max_detection_age_s=max_detection_age_s,
        )
        self.field_polygon: Optional[List[XY]] = (
            [(float(x), float(y)) for x, y in field_polygon] if field_polygon else None
        )

    # -- public API ----------------------------------------------------------
    def decide(
        self,
        detection: Optional[Detection],
        drone: DroneState,
        geofence: GeofenceMap,
        *,
        now_s: Optional[float] = None,
        **overrides,
    ) -> AvoidanceManeuver:
        """Decide the maneuver for a single detection (or None). Convenience wrapper over
        `decide_multi`. `overrides` may set any `PolicyParams` field for this call only. `now_s` is
        the caller's current time on the same clock as `Detection.stamp_s` (only used by the
        staleness gate; None = gate cannot fire)."""
        detections = [detection] if detection is not None else []
        return self.decide_multi(detections, drone, geofence, now_s=now_s, **overrides)

    def decide_multi(
        self,
        detections: Sequence[Detection],
        drone: DroneState,
        geofence: GeofenceMap,
        *,
        now_s: Optional[float] = None,
        **overrides,
    ) -> AvoidanceManeuver:
        """Decide the maneuver given zero or more simultaneous detections. The nearest in-cylinder
        bird is the trigger and sets the dodge direction; every in-cylinder bird constrains which
        candidate setpoints are acceptable (a dodge away from bird A must not steer into bird B).

        `now_s` is passed IN rather than read from a wall clock so `decide` stays pure (same inputs
        -> same maneuver) and staleness decisions replay exactly from a flight log."""
        p = replace(self.params, **overrides) if overrides else self.params

        # Staleness gate first: a known-stale detection is treated as ABSENT before any threat
        # geometry runs, so an old frame can neither trigger a phantom dodge nor sit in the threat
        # set constraining the dodge away from a live bird.
        fresh, stale = self._split_stale(detections, now_s, p)

        threats = self._threats(fresh, drone, p)
        if not threats:
            if detections and not fresh:
                # Every detection this frame was dropped as stale -> detection-free frame. Called
                # out explicitly so the event log shows WHY the policy proceeded.
                reason = (f"all detection(s) stale (age > {p.max_detection_age_s:g} s) "
                          f"-- treated as absent")
            elif fresh:
                reason = "detection(s) outside threat cylinder"
            else:
                reason = "no in-cylinder threat"
            maneuver = AvoidanceManeuver(
                decision=Decision.PROCEED,
                reason=reason,
                debug={
                    "n_detections": len(detections),
                    "threat_radius_m": p.threat_radius_m,
                    "vertical_threat_m": p.vertical_threat_m,
                },
            )
        else:
            # Trigger = nearest threat (smallest horizontal range).
            trigger, trigger_range = min(threats, key=lambda t: t[1])
            maneuver = self._plan_divert(trigger, [t for t, _ in threats], drone, geofence, p)
            # Attach shared diagnostics for the event log (CLAUDE.md instrumentation rule).
            maneuver.triggering_detection = trigger
            maneuver.debug.setdefault("trigger_range_m", round(trigger_range, 3))
            maneuver.debug.setdefault("n_threats", len(threats))
            maneuver.debug.setdefault(
                "threat_ids", [t.track_id or f"det@{t.frame_id}" for t, _ in threats]
            )
        if stale:
            # Always log what the staleness gate dropped, whatever the decision -- a stale frame
            # silently vanishing is exactly the observability gap this gate exists to close.
            maneuver.debug.setdefault("n_stale_dropped", len(stale))
            maneuver.debug.setdefault(
                "stale_ids", [t.track_id or f"det@{t.frame_id}" for t in stale]
            )
            maneuver.debug.setdefault("max_detection_age_s", p.max_detection_age_s)
        return maneuver

    # -- internals -----------------------------------------------------------
    @staticmethod
    def _split_stale(
        detections: Sequence[Detection], now_s: Optional[float], p: PolicyParams
    ) -> Tuple[List[Detection], List[Detection]]:
        """Split detections into (fresh, stale) under the staleness gate. The gate only fires when
        it can actually compute an age: `max_detection_age_s` set (gate on) AND `now_s` supplied AND
        the detection stamped. An UNSTAMPED detection is kept even with the gate on -- the --demo
        bird and scripted sources do not stamp yet (`Detection.stamp_s` is None), and dropping them
        would silently disable avoidance for every current source. Fail OPEN on missing data, fail
        SAFE (treat as absent) only on provably stale data."""
        if p.max_detection_age_s is None or now_s is None:
            return list(detections), []
        fresh: List[Detection] = []
        stale: List[Detection] = []
        for det in detections:
            if det.stamp_s is not None and (now_s - det.stamp_s) > p.max_detection_age_s:
                stale.append(det)
            else:
                fresh.append(det)
        return fresh, stale

    def _threats(
        self, detections: Sequence[Detection], drone: DroneState, p: PolicyParams
    ) -> List[Tuple[Detection, float]]:
        """Detections inside the threat cylinder, paired with horizontal range. Confidence floor is
        applied here (default 0.0 = keep everything)."""
        dx0, dy0, dz0 = drone.position_enu
        out: List[Tuple[Detection, float]] = []
        for det in detections:
            if det.confidence < p.min_confidence:
                continue
            bx, by, bz = det.position_enu
            hrange = math.hypot(bx - dx0, by - dy0)
            if hrange <= p.threat_radius_m and abs(bz - dz0) <= p.vertical_threat_m:
                out.append((det, hrange))
        return out

    def _plan_divert(
        self,
        trigger: Detection,
        threats: Sequence[Detection],
        drone: DroneState,
        geofence: GeofenceMap,
        p: PolicyParams,
    ) -> AvoidanceManeuver:
        drone_xy: XY = (drone.position_enu[0], drone.position_enu[1])
        trig_xy: XY = (trigger.position_enu[0], trigger.position_enu[1])

        # Primary "away" direction: from bird to drone. Degenerate (bird directly under the drone)
        # -> dodge perpendicular to the drone's heading (its track), a sensible sidestep.
        away = _unit((drone_xy[0] - trig_xy[0], drone_xy[1] - trig_xy[1]))
        if away is None:
            away = (math.cos(drone.heading_rad + math.pi / 2.0),
                    math.sin(drone.heading_rad + math.pi / 2.0))

        rejected: List[dict] = []
        for angle in _CANDIDATE_ANGLES_DEG:
            direction = _rotate(away, angle)
            sp_xy: XY = (drone_xy[0] + direction[0] * p.divert_distance_m,
                         drone_xy[1] + direction[1] * p.divert_distance_m)
            setpoint: ENU = (sp_xy[0], sp_xy[1], p.cruise_alt_m)

            verdict = self._vet(setpoint, drone_xy, threats, geofence, p)
            if verdict is None:
                # accepted
                clearance = geofence.segment_clearance(drone_xy, sp_xy).clearance_m
                return AvoidanceManeuver(
                    decision=Decision.DIVERT,
                    setpoint_enu=setpoint,
                    reason=(f"divert {angle:+.0f} deg from away-vector, {p.divert_distance_m:.0f} m "
                            f"lateral at {p.cruise_alt_m:.0f} m; swept-path tree clearance "
                            f"{clearance:.2f} m"),
                    debug={
                        "candidate_angle_deg": angle,
                        "away_unit": (round(away[0], 3), round(away[1], 3)),
                        "swept_tree_clearance_m": round(clearance, 3),
                        "candidates_rejected": rejected,
                        "params": _params_dict(p),
                    },
                )
            rejected.append({"angle_deg": angle, "why": verdict})

        # Nothing safe -> HOLD (never emit an unvetted setpoint).
        return AvoidanceManeuver(
            decision=Decision.HOLD,
            reason=(f"no safe divert among {len(_CANDIDATE_ANGLES_DEG)} candidate directions "
                    f"(boxed in by trees / field edge / other birds) -- holding in GUIDED"),
            debug={
                "candidates_rejected": rejected,
                "away_unit": (round(away[0], 3), round(away[1], 3)),
                "params": _params_dict(p),
            },
        )

    def _vet(
        self,
        setpoint: ENU,
        drone_xy: XY,
        threats: Sequence[Detection],
        geofence: GeofenceMap,
        p: PolicyParams,
    ) -> Optional[str]:
        """Return None if `setpoint` passes every safety gate, else a short reason string (for the
        rejected-candidate log). Gate order matches the module-docstring guarantee."""
        sp_xy: XY = (setpoint[0], setpoint[1])

        # 1. HARD 3D gate (ADR-006): tree volumes + altitude envelope.
        if not geofence.is_safe_3d(setpoint, p.vertical_margin_m, p.alt_bounds):
            return "is_safe_3d rejected (tree volume or altitude envelope)"

        # 2. Swept-path lateral tree clearance: the whole dodge stays clear of tree XY columns.
        seg = geofence.segment_clearance(drone_xy, sp_xy)
        if seg.clearance_m < p.lateral_tree_margin_m:
            return (f"swept path clears tree by only {seg.clearance_m:.2f} m "
                    f"(< {p.lateral_tree_margin_m:.2f} m required)")

        # 3. Field-polygon containment with inward margin.
        if self.field_polygon is not None:
            if not _point_in_polygon(sp_xy[0], sp_xy[1], self.field_polygon):
                return "setpoint outside field polygon"
            edge = _point_edge_distance(sp_xy[0], sp_xy[1], self.field_polygon)
            if edge < p.field_margin_m:
                return f"setpoint {edge:.2f} m from field edge (< {p.field_margin_m:.2f} m margin)"

        # 4. Increases separation from every threat, keeps min clearance from all.
        for det in threats:
            bx, by, _ = det.position_enu
            new_d = math.hypot(sp_xy[0] - bx, sp_xy[1] - by)
            if new_d < p.min_bird_clearance_m:
                return (f"setpoint would sit {new_d:.2f} m from bird "
                        f"{det.track_id or det.frame_id} (< {p.min_bird_clearance_m:.2f} m)")
            cur_d = math.hypot(drone_xy[0] - bx, drone_xy[1] - by)
            if new_d < cur_d - 1e-6:
                return (f"setpoint moves CLOSER to bird {det.track_id or det.frame_id} "
                        f"({cur_d:.2f} -> {new_d:.2f} m)")
        return None


def _params_dict(p: PolicyParams) -> dict:
    return {
        "cruise_alt_m": p.cruise_alt_m,
        "threat_radius_m": p.threat_radius_m,
        "vertical_threat_m": p.vertical_threat_m,
        "divert_distance_m": p.divert_distance_m,
        "lateral_tree_margin_m": p.lateral_tree_margin_m,
        "min_bird_clearance_m": p.min_bird_clearance_m,
        "vertical_margin_m": p.vertical_margin_m,
        "alt_bounds": list(p.alt_bounds),
        "field_margin_m": p.field_margin_m,
        "min_confidence": p.min_confidence,
        "max_detection_age_s": p.max_detection_age_s,
    }
