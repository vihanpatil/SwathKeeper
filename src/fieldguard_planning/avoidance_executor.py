"""Reactive-avoidance EXECUTOR (Weeks 3-4, the core loop) -- ADR-006.

This module is the other half of the boundary defined in `avoidance_types.py`: the **decision
policy** (perception-ml-engineer, `avoidance_policy.py`) decides *when/where* to dodge; THIS module
takes that decision, takes control of the vehicle, executes it, resumes the mission, and books
coverage-debt so no field cell is ever silently dropped.

Per ADR-006 the maneuver shape is fixed: `AUTO -> GUIDED -> one 3D-vetted setpoint -> GUIDED -> AUTO`,
with `MIS_RESTART=0` making AUTO resume the SAME next waypoint it was flying toward when interrupted
(confirmed on the real stack 2026-08-05). ADR-006's "**one** setpoint" is enforced here, not upstream:
the policy is pure and recomputes its dodge every tick, so this module LATCHES the first accepted
setpoint of an encounter and re-commands that same point until the threat clears (see design note 3).
Per ADR-002 v1 is "avoid, return to next waypoint" -- this module does NOT requeue/reorder mission
waypoints; it books any coverage the detour cost as EXPLICIT debt via `coverage.py`, which is the
documented, well-scoped stretch goal (full reconciliation) left undone on purpose.

Design notes on the guarantees this file exists to make impossible-by-construction:

1. **Never fly an unvetted DISPLACEMENT.** Every point this module is about to command the vehicle
   to MOVE to is re-vetted on the tick it is commanded, against BOTH halves of what makes a dodge
   target safe: `GeofenceMap.is_safe_3d` (trees + altitude envelope) and the policy's own
   `min_bird_clearance_m` from the threats logged with this decision
   (`debug["threat_positions_enu"]`). This is the safety BACKSTOP, not the primary check. On
   rejection the executor falls back to HOLD and never sends the rejected point to the vehicle.
   The bird half exists because the geofence half cannot see a bird at all, and a LATCHED point is
   only ever vetted against where the birds were on the tick it was latched (QA round 2, 2026-08-24:
   an R3 refusal re-commanded a latch that had become 1.000 m from the bird, against the policy's
   own 3.00 m bar, with no gate_reject). The bar is read from `debug["params"]` -- the value the
   POLICY flew for that decision, not a second literal here. A maneuver carrying no params did not
   come from this policy and gets no bird check (fail OPEN on missing data, the same doctrine as the
   missing `range_degenerate` flag below); every real maneuver carries them.

   **A HOLD IS EXEMPT, BY CONSTRUCTION, AND THAT IS THE HONEST SCOPE OF THIS GUARANTEE.** A HOLD
   commands `drone_state.position_enu` -- where the vehicle already is. Zero displacement: it
   chooses no point, so there is no point to vet, and it cannot honour a clearance bar any more than
   standing still can. Where that bites (QA round 3, 2026-08-24, finding 2): the R3-refusal branch
   is only entered when `range_degenerate` is True, i.e. the vehicle is already within
   `degenerate_range_m` of the bird, so the HOLD setpoint is inside `min_bird_clearance_m` BY
   CONSTRUCTION -- measured at 41 of 10,000 random control ticks, closest 0.288 m. Rejecting the
   divert and holding can therefore leave the commanded separation WORSE than the point that was
   rejected, and no wording here may imply otherwise. Choosing a point that IS outside the bar is
   escape geometry, which this executor does not do: **R4, open and deliberately uncut.** What a
   HOLD does guarantee is narrower and still worth having -- it never flies a point the control law
   forbids. `_handle_hold` logs `bird_clearance_m` on every hold so the artifact shows how close
   holds got, and `check_live_flight_log.gate_r2_r3` reports the minimum as CONTEXT, never gated.
2. **Never silently drop a coverage cell.** `finalize()` builds the terminal coverage ledger from the
   ACTUAL flown path (`self.flown_path`, single source of truth -- every position the vehicle
   actually reported occupying, nominal or mid-maneuver; commanded setpoints are NEVER recorded as
   flown -- see `_handle_divert`) by running it through the exact same
   `coverage.coverage_from_path` the nominal-mission baseline uses. Because every canonical grid cell
   is visited exactly once in that computation, the P1 partition invariant
   (`coverage.check_ledger`) holds BY CONSTRUCTION -- there is no code path that can produce a cell
   silently absent from the ledger; the worst that can happen is a cell landing in `debt`, which is
   the explicitly-allowed ADR-002 v1 outcome.
3. **Command ONE dodge point per encounter, not one per tick.** The policy is a pure function of the
   current detection + ownship state, so it legitimately returns a different setpoint every tick --
   the dodge is anchored to the drone and slides forward with it; re-commanding each of those walked
   the target around (visibly jumpy on film, and one live log showed a ~6 m outlier before it snapped
   back). See `RELATCH_THRESHOLD_M` for the measured per-tick drift. The fix is
   deliberately EXECUTOR-side so the policy stays pure and independently testable: the first accepted
   (3D-vetted) DIVERT setpoint is LATCHED and re-commanded for the rest of the encounter, and only a
   policy setpoint further than `RELATCH_THRESHOLD_M` away -- a genuinely moving threat, not
   recompute drift -- can re-latch, and only if it passes the same 3D re-vet. Latch lifecycle is the
   encounter: set on the first accepted divert, cleared on resume alongside `_wp_at_takeover`.
   Latching never bypasses guarantee 1 -- every DISPLACEMENT handed to the sink, latched or fresh,
   is re-vetted on the tick it is commanded.
   R3 (ADR-013 am. 12): a re-latch is additionally REFUSED on a tick the policy flagged
   `debug["range_degenerate"]`. Below `PolicyParams.degenerate_range_m` the setpoint jump is the
   away-vector's NOISE, not the threat moving -- the flown 2026-08-23 encounter re-latched on a
   20.9 m jump produced by a static bird the vehicle had crossed. The refusal keeps flying the
   already-vetted latched point and is logged as `latch_action: relatch_refused_degenerate`, so R3
   doing its job is visible in the log rather than inferred from a missing `relatch` event. The kept
   point is re-vetted this tick like every other -- and that is the whole of the claim: a refusal
   declines an alternative the policy vetted against the CURRENT bird positions in favour of one
   vetted against older ones, so it is guarantee 1 (now both halves, above) that keeps it honest.
   When the kept latch has drifted inside `min_bird_clearance_m` of a threat, the refusal declines
   to command it and HOLDs instead -- which is a refusal to fly a forbidden point, NOT a safer
   alternative to it (guarantee 1's HOLD paragraph: at degenerate range the hold is inside the bar
   too, and can be nearer than the point refused).
   SCOPE on that path, stated so it is a deferral and not a blind spot: rejecting the LATCHED point
   also kills the latch (otherwise every remaining tick re-rejects the same dead point instead of
   latching a fresh vetted one), and a FIRST latch at degenerate range is permitted by design -- so
   the next tick may latch the same noise-driven setpoint fresh. On that one path R3 buys a tick,
   not a refusal. Widening it means deciding what to fly INSTEAD, which is escape geometry: R4,
   open.
4. **One empty frame does not end an encounter -- and no encounter runs forever.** The hand-back to
   AUTO needs `RESUME_CLEAR_TICKS` CONSECUTIVE clear ticks, not one. Until 2026-08-25 the threat
   test was per-frame instantaneous, and the first real-detection take's GUIDED window closed on
   `threat_cleared` 0.434 s after it opened -- the tick after the detector's last box. A detector
   that misses one frame (3 FN in n=20 visible bird-frames, ADR-003 am. 7) would hand the mission
   back toward a bird still in the cylinder, ~0.2 s into a dodge the vehicle has barely begun. While
   the counter is armed the executor stays in GUIDED and commands NOTHING, so the vehicle keeps
   flying the already-vetted latched point; every waiting tick logs `resume_pending`, so the delay
   is readable in the artifact instead of inferred from a late resume.

   A "clear" tick is PROCEED **with readable evidence**: a tick whose detections were all thrown
   away by the ADR-009 staleness gate (`debug["n_stale_dropped"]`) resets the counter like a threat
   tick does. Unreadable evidence is not evidence of absence, and this note claims ABSENCE
   persistence -- the 2026-08-24 QA probe (every detection 60 s stale -> 20 PROCEEDs with the bird
   squarely in the cylinder) is exactly the stream that would otherwise certify a clear sky.

   **THE COUNTER MUST HAVE A CEILING, and that is the load-bearing half.** Resetting on every threat
   tick means a detection duty cycle of one-in-`RESUME_CLEAR_TICKS` ticks or denser NEVER reaches
   the count: measured on the real executor, a `DIVERT, PROCEED, PROCEED` stream repeated 30 times
   gives 90 ticks, 1 takeover, **0 resumes**, locked in GUIDED with the rest of the field booking as
   coverage debt -- and `resume_pending` cycling 1,2,1,2 forever, so the artifact of a locked flight
   reads healthy (QA C1, 2026-08-25). `GUIDED_CEILING_TICKS` bounds it: the executor hands back with
   `trigger="guided_ceiling"`, never `threat_cleared`, and the event carries `ticks_in_guided` +
   `ceiling_ticks` so no reader can mistake a backstop for a cleared threat. This does NOT decline
   to avoid: the policy is untouched and threat ENTRY is instantaneous, so a threat that is still
   there re-takes-over on the very next DIVERT tick and latches a freshly vetted point. What the
   ceiling breaks is a stuck STATE, not the dodge -- and it is a legibility fix, not a cure: under a
   SUSTAINED duty cycle the survey is still starved (measured, 1-in-3 flicker: 6 of 1200 ticks in
   AUTO), the difference being that the log now says so instead of looking like an ordinary flight.
   Fixing the starvation is a detector problem, not an executor one.

   This note owns ABSENCE persistence and nothing else: entry stays instantaneous, detection AGEING
   stays with `PolicyParams.max_detection_age_s`, and candidate selection stays with the policy --
   one concept, one owner.

Vehicle interaction is behind the `VehicleCommandSink` seam so this stays sim-agnostic and
unit-testable on a bare interpreter; the real ROS 2 binding (`/ap/mode_switch`,
`/ap/cmd_gps_pose`, both locked in ADR-005/ADR-006) is a later adapter that implements this
interface -- NOT built here.

Dependency: stdlib only (dataclasses, typing, math not even needed) -- same discipline as
`geofence.py` / `coverage.py`, so this runs without a venv or the Docker/Gazebo/ROS 2 stack.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from .avoidance_types import AvoidanceManeuver, Decision, DroneState
from .coverage import CELL_COVERED, CELL_DEBT, CoverageCell, coverage_from_path
from .geofence import GeofenceMap

# Flight-mode strings as they appear in the event log / ADR-006. Not an enum on purpose: the real
# ROS 2 adapter will pass these straight through to ardupilot_msgs/ModeSwitch, which is string-typed.
MODE_AUTO = "AUTO"
MODE_GUIDED = "GUIDED"

DEFAULT_VERTICAL_MARGIN_M = 1.0  # matches geofence.is_safe_3d default

# Setpoint-latch escape hatch: how far a NEW policy setpoint must sit from the currently latched one
# before the executor believes the threat actually moved and re-latches (rather than treating the
# delta as the policy's per-tick recompute drift and ignoring it). Re-latching is still gated on the
# same 3D re-vet -- this constant only decides WHICH point gets vetted, never whether it gets vetted.
# Sized against measured data, not taste: replaying the four eval/scenarios missions through the real
# policy, the per-tick delta between consecutive DIVERT setpoints inside one encounter is dominated
# by the ownship step (exactly 2.00 m on a straight lane -- the dodge is anchored to the drone, so it
# slides forward with it), while genuine re-plans (dodge flipping side, turnaround geometry) jump
# 3.2-35 m. 3.0 m sits in that gap: it absorbs the slide, and every real re-plan still gets through.
# It is the tuning knob if demo footage is still twitchy -- raising it also swallows the ~3-4 m
# turnaround swings, at the cost of flying a staler dodge through the turn.
RELATCH_THRESHOLD_M = 3.0

# THREAT-PERSISTENCE HYSTERESIS (design note 4): how many CONSECUTIVE clear ticks end an encounter
# and hand the mission back. 1 would be the pre-2026-08-25 behaviour: one empty frame resumed.
# Sized, not chosen: the ADOPT evidence for the real detector is 3 FN in n=20 visible bird-frames
# (ADR-003 am. 7), so a single-frame hole inside an encounter is ordinary and two in a row is not.
#
# WHAT 3 TICKS IS IN SECONDS -- measured, and NOT the nominal arithmetic. The flown tick period is a
# median 0.160 s (n=1855 stamped ticks, 2026-08-25 `run.tick_stamp_sim_s`; p95 0.186, max 0.253), so
# 3 ticks is **0.48 s**, not the 0.6 s a nominal 5 Hz CONTROL_HZ implies. The loop also runs FASTER
# than the 5 Hz camera (~6.25 Hz measured), so ticks and frames are not 1:1: 0.48 s spans ~2.4 frame
# periods, i.e. this covers ONE missed frame plus jitter, not two. Quote the measured number.
# The ceiling on it is `PolicyParams.max_detection_age_s` (1.0 s): waiting longer than the policy
# keeps a detection alive would mean holding GUIDED on evidence it has already declared ABSENT. Both
# the nominal (0.6 s, the conservative floor, static test) and the flown (0.48 s, the flight-log
# gate's own measured check) sit inside it.
RESUME_CLEAR_TICKS = 3

# THE BACKSTOP ON THE HYSTERESIS (design note 4, QA C1). Max ticks one encounter may hold GUIDED
# before the executor hands the mission back regardless, with `trigger="guided_ceiling"`.
# Sized off the encounter EVIDENCE, not taste, and counted the way `_ticks_in_guided()` counts --
# INCLUSIVE of both the takeover tick and the resume tick (QA N3: `resume_tick - takeover_tick` is
# one short of what this constant is compared against). Longest GUIDED window ever flown: **62**
# ticks (2026-08-18, takeover 3528 -> resume 3589); the other two are 20 (2026-08-23) and 5
# (2026-08-25). 5x the longest ever flown is ~50 s at the measured 0.160 s tick -- far beyond any
# genuine encounter this world can produce (the demo bird lingers 12 s; scripted birds transit in
# seconds), so it cannot fire on a real dodge, and it still bounds the stuck state at under a
# minute. `test_the_longest_encounter_ever_flown_is_nowhere_near_the_ceiling` re-derives the 62 from
# the committed logs rather than trusting this comment. It is a BACKSTOP, not a control parameter:
# if it ever fires, the flight log says so and something upstream (a duty-cycled detector, an
# all-stale detection stream) needs fixing.
GUIDED_CEILING_TICKS = 5 * 62


def _dist_3d(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    """Euclidean distance between two world-ENU points. 3D on purpose: an altitude-only jump in the
    commanded dodge is just as jumpy on film as a lateral one. `** 0.5` keeps this module math-free
    (stdlib-only discipline, same as `geofence.py` / `coverage.py`)."""
    dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return (dx * dx + dy * dy + dz * dz) ** 0.5


def _threat_positions(maneuver: AvoidanceManeuver) -> List[Tuple[Tuple[float, float, float], str]]:
    """[(position_enu, id)] for every in-cylinder threat this decision was taken against.

    The policy writes `debug["threat_positions_enu"]` alongside `debug["threat_ids"]` (same list,
    same order) precisely so this backstop can see EVERY threat rather than only the trigger -- a
    dodge away from bird A must not be re-commanded into bird B. Falls back to the triggering
    detection when the maneuver carries no threat block (a hand-built maneuver / a pre-R3 caller),
    and to [] when it carries neither."""
    positions = maneuver.debug.get("threat_positions_enu")
    ids = maneuver.debug.get("threat_ids") or []
    out: List[Tuple[Tuple[float, float, float], str]] = []
    if isinstance(positions, (list, tuple)):
        for i, pos in enumerate(positions):
            if not isinstance(pos, (list, tuple)) or len(pos) < 2:
                continue
            try:                       # a malformed entry did not come from this policy: skip it
                xyz = (float(pos[0]), float(pos[1]), float(pos[2]) if len(pos) > 2 else 0.0)
            except (TypeError, ValueError):
                continue               # never raise inside the control loop
            out.append((xyz, str(ids[i]) if i < len(ids) else "?"))
    if out:
        return out
    det = maneuver.triggering_detection
    return [] if det is None else [(det.position_enu, det.track_id or f"det@{det.frame_id}")]


def _nearest_threat(point_enu: Tuple[float, float, float],
                    maneuver: AvoidanceManeuver) -> Optional[Tuple[float, str]]:
    """(horizontal distance from `point_enu` to the nearest threat, that threat's id), or None when
    this maneuver names no threat at all. HORIZONTAL, matching the axis the policy's own
    `min_bird_clearance_m` gate is expressed in (ADR-009: a bird's z is the estimate we cannot
    trust, so folding it in could only manufacture clearance)."""
    best: Optional[Tuple[float, str]] = None
    for pos, threat_id in _threat_positions(maneuver):
        dx, dy = point_enu[0] - pos[0], point_enu[1] - pos[1]
        d = (dx * dx + dy * dy) ** 0.5
        if best is None or d < best[0]:
            best = (d, threat_id)
    return best


def _flown_bird_clearance_bar(maneuver: AvoidanceManeuver) -> Optional[float]:
    """`min_bird_clearance_m` as the POLICY logged it for THIS decision, or None if this maneuver
    carries no params. One home for the number (`PolicyParams`), read out of the decision itself, so
    a replayed log is checked against the bar it was flown under rather than today's."""
    params = maneuver.debug.get("params")
    bar = params.get("min_bird_clearance_m") if isinstance(params, dict) else None
    return float(bar) if isinstance(bar, (int, float)) and not isinstance(bar, bool) else None


# --------------------------------------------------------------------------------------------------
# Vehicle abstraction -- the seam the real ROS 2 adapter (mode_switch service + /ap/cmd_gps_pose)
# implements later. Kept minimal and 1:1 with what ADR-006 actually needs the executor to do.
# --------------------------------------------------------------------------------------------------
@runtime_checkable
class VehicleCommandSink(Protocol):
    """Everything the executor needs from "the vehicle." A real implementation wraps the AP_DDS
    topics/services locked in ADR-005/ADR-006:
      - set_mode("GUIDED"/"AUTO")   -> /ap/mode_switch (ardupilot_msgs/ModeSwitch)
      - send_setpoint_enu((e,n,u))  -> /ap/cmd_gps_pose (ardupilot_msgs/GlobalPosition), frame_id="map",
                                        ONLY honored in GUIDED+armed (ADR-006 ready_for_external_control)
      - current_waypoint()          -> read back AUTO's current mission index (no AP_DDS service exists
                                        for this at the pinned SHA -- ADR-006 "why no waypoint-index
                                        juggling"; a real adapter likely tracks this from mission-item
                                        reached events / MAVLink rather than a clean getter)
    """

    def set_mode(self, mode: str) -> None: ...

    def send_setpoint_enu(self, point_enu: Tuple[float, float, float]) -> None: ...

    def current_waypoint(self) -> int: ...


class SimulatedVehicleSink:
    """Reference / test-double implementation of `VehicleCommandSink`. NOT a ROS 2 / MAVLink
    adapter -- it models exactly the one behavior ADR-006 confirmed on the real stack and nothing
    else: entering GUIDED and sending setpoints does not change what AUTO reports as its current
    mission waypoint, so re-entering AUTO resumes the SAME next waypoint (MIS_RESTART=0). A test
    harness drives `current_wp_index` directly (as the mission tracker/AUTO would) between executor
    calls; the executor and this sink never mutate it themselves.
    """

    def __init__(self, initial_wp_index: int = 0):
        self.mode: str = MODE_AUTO
        self.current_wp_index: int = initial_wp_index
        self.setpoints_sent: List[Tuple[float, float, float]] = []
        self.mode_history: List[str] = [MODE_AUTO]

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.mode_history.append(mode)

    def send_setpoint_enu(self, point_enu: Tuple[float, float, float]) -> None:
        if self.mode != MODE_GUIDED:
            raise RuntimeError(
                f"send_setpoint_enu called while mode={self.mode!r}; ADR-006: /ap/cmd_gps_pose is "
                f"only honored in GUIDED+armed (ready_for_external_control) -- refusing to pretend "
                f"this would fly.")
        self.setpoints_sent.append(point_enu)

    def current_waypoint(self) -> int:
        return self.current_wp_index


# --------------------------------------------------------------------------------------------------
# Coverage-debt bookkeeping support types
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class LedgerRecord:
    cell_id: str
    status: str  # coverage.CELL_COVERED | coverage.CELL_DEBT

    def to_dict(self) -> dict:
        return {"cell_id": self.cell_id, "status": self.status}


@dataclass
class DivertAudit:
    """Best-effort, LOGGING-ONLY record of which cells were "in the shadow" of one accepted divert
    (cells within swath of the vehicle's position at takeover). This is NOT the source of truth for
    the terminal ledger -- `finalize()` recomputes coverage from the real flown path independently --
    it exists purely so a human/QA reading the event log can see *why* a given cell ended up debt or
    was still covered, per CLAUDE.md's "log every avoidance event and every requeued cell" rule."""
    tick: int
    track_id: Optional[str]
    at_risk_cell_ids: List[str]


class AvoidanceExecutor:
    """Sim-agnostic ADR-006 state machine: consumes one `AvoidanceManeuver` + `DroneState` per
    control-loop tick, drives a `VehicleCommandSink`, and books coverage-debt.

    Usage: call `step(drone_state, maneuver)` once per tick for the whole flight (nominal mission
    ticks pass `Decision.PROCEED`; the policy substitutes DIVERT/HOLD when it decides to act), then
    call `finalize()` once at the end to get the terminal coverage ledger + full event log -- this is
    exactly the shape of `eval/scenarios/<name>/flight_log.json`.
    """

    def __init__(
        self,
        geofence: GeofenceMap,
        cells: Sequence[CoverageCell],
        sink: VehicleCommandSink,
        swath_half_width_m: float,
        alt_bounds: Optional[Tuple[float, float]] = None,
        vertical_margin_m: float = DEFAULT_VERTICAL_MARGIN_M,
        resume_clear_ticks: int = RESUME_CLEAR_TICKS,
        guided_ceiling_ticks: int = GUIDED_CEILING_TICKS,
    ):
        self.geofence = geofence
        self.cells: List[CoverageCell] = list(cells)
        self.sink = sink
        self.swath_half_width_m = swath_half_width_m
        self.alt_bounds = alt_bounds
        self.vertical_margin_m = vertical_margin_m
        self.resume_clear_ticks = int(resume_clear_ticks)
        self.guided_ceiling_ticks = int(guided_ceiling_ticks)
        # Rejected loudly at construction, not silently absorbed: `resume_clear_ticks` 0 or negative
        # restores the pre-2026-08-25 instantaneous resume while the log still advertises hysteresis,
        # and a ceiling below the hysteresis makes every encounter end on the backstop.
        if self.resume_clear_ticks < 1:
            raise ValueError(f"resume_clear_ticks must be >= 1 (got {resume_clear_ticks}); 1 is the "
                             f"instantaneous pre-hysteresis behaviour and below 1 is meaningless")
        if self.guided_ceiling_ticks < self.resume_clear_ticks:
            raise ValueError(f"guided_ceiling_ticks {self.guided_ceiling_ticks} is below "
                             f"resume_clear_ticks {self.resume_clear_ticks}: the backstop would fire "
                             f"before the hysteresis could ever complete, so no encounter could end "
                             f"on `threat_cleared`")

        self.mode: str = MODE_AUTO
        self.flown_path: List[Tuple[float, float, float]] = []
        self.event_log: List[dict] = []
        self.coverage_ledger: List[dict] = []          # populated by finalize()
        self.requeue_events: List[dict] = []            # populated by finalize()

        self._tick: int = 0
        self._divert_audits: List[DivertAudit] = []
        self._finalized = False
        # Latching state: the waypoint we were flying to when we took control, or None if not
        # currently in a maneuver. Set on takeover, consumed + cleared on the single resume.
        self._wp_at_takeover: Optional[int] = None
        # The one dodge point this encounter is flying (design note 3), or None if no DIVERT setpoint
        # has been accepted yet. Same lifecycle as `_wp_at_takeover`: set on the first accepted
        # divert, cleared on the single resume, so the NEXT encounter latches fresh.
        self._latched_setpoint: Optional[Tuple[float, float, float]] = None
        # Consecutive clear ticks so far -- the hysteresis counter (design note 4).
        self._clear_ticks: int = 0
        # Tick this encounter took control on, or None in AUTO. Same lifecycle as the latch; it is
        # what the GUIDED ceiling measures against.
        self._guided_since_tick: Optional[int] = None

    # -- logging -------------------------------------------------------------------------------
    def _log(self, kind: str, **detail) -> None:
        self.event_log.append({"seq": len(self.event_log), "tick": self._tick, "kind": kind, **detail})

    def _log_detection(self, maneuver: AvoidanceManeuver) -> None:
        det = maneuver.triggering_detection
        if det is None:
            return
        self._log(
            "detection",
            track_id=det.track_id,
            frame_id=det.frame_id,
            confidence=det.confidence,
            position_enu=det.position_enu,
            source=det.source,
            decision=maneuver.decision.value,
        )

    def _record_position(self, point_enu: Tuple[float, float, float]) -> None:
        self.flown_path.append(point_enu)

    def _at_risk_cells(self, point_enu: Tuple[float, float, float]) -> List[str]:
        """Cells within one swath width of `point_enu` -- the audit-only "what was this patch of
        field about to get imaged for" helper. O(n_cells); fine at this project's grid sizes
        (hundreds of cells, single-digit dodges per scenario)."""
        x, y = point_enu[0], point_enu[1]
        out = []
        for cell in self.cells:
            dx, dy = cell.cx_m - x, cell.cy_m - y
            if (dx * dx + dy * dy) ** 0.5 <= self.swath_half_width_m:
                out.append(cell.cell_id)
        return out

    # -- public step API -------------------------------------------------------------------------
    def step(self, drone_state: DroneState, maneuver: AvoidanceManeuver) -> None:
        if self._finalized:
            raise RuntimeError("step() called after finalize(); this executor instance is done")
        self._tick += 1
        self._log_detection(maneuver)
        # Hysteresis counter: a clear tick counts toward ending the encounter; any threat tick
        # (DIVERT or HOLD) and any tick whose evidence was thrown away as stale puts it back to zero.
        self._clear_ticks = self._clear_ticks + 1 if self._is_clear_tick(maneuver) else 0
        if maneuver.decision is Decision.PROCEED:
            self._handle_proceed(drone_state, maneuver)
        elif maneuver.decision is Decision.HOLD:
            self._handle_hold(drone_state, maneuver)
        elif maneuver.decision is Decision.DIVERT:
            self._handle_divert(drone_state, maneuver)
        else:  # pragma: no cover -- Decision is a closed enum; defensive only
            raise ValueError(f"unhandled Decision: {maneuver.decision!r}")
        # BACKSTOP LAST, and the ordering is load-bearing (QA N1, 2026-08-25). Run at the TOP of the
        # tick it fired BEFORE the decision handler, so a ceiling expiry landing on a DIVERT tick
        # emitted set_mode(AUTO) -> set_mode(GUIDED) -> send_setpoint inside ONE control callback:
        # `Ros2VehicleSink.set_mode` is a non-blocking `call_async`, and its own comment states the
        # invariant that breaks -- "AvoidanceExecutor asserts the mode exactly ONCE per takeover and
        # once per hand-back and nothing re-sends a rejected switch". Two racing ModeSwitch calls in
        # one callback is exactly the shape that let a failed GUIDED takeover pass silently. At the
        # BOTTOM the tick's decision is executed first and the hand-back is the tick's only mode
        # switch; the still-present threat re-takes-over on the NEXT tick with a fresh vetted latch.
        self._enforce_guided_ceiling()

    @staticmethod
    def _stale_detail(maneuver: AvoidanceManeuver) -> dict:
        """`{"debug": {...}}` naming what the ADR-009 staleness gate threw away this tick, or `{}`.

        The gate can silently disable avoidance for a WHOLE flight -- a systematic clock offset or a
        render stall ages every detection out, the policy returns PROCEED on every tick, and nothing
        ever reaches the DIVERT branch that used to be the only carrier of `debug`. The one counter
        that exists to reveal it (`check_live_flight_log.stale_dropped_total`) then read 0, which is
        also what "no bird was ever seen" reads -- opposite diagnoses, identical artifact (QA round
        2, 2026-08-24). Written only when something was actually dropped, so a healthy flight pays
        nothing per tick."""
        n = maneuver.debug.get("n_stale_dropped")
        if not n:
            return {}
        return {"debug": {"n_stale_dropped": n, "stale_ids": maneuver.debug.get("stale_ids"),
                          "max_detection_age_s": maneuver.debug.get("max_detection_age_s")}}

    @staticmethod
    def _is_clear_tick(maneuver: AvoidanceManeuver) -> bool:
        """A tick that counts toward ending the encounter: PROCEED **on readable evidence**.

        A PROCEED whose detections were all aged out by the ADR-009 staleness gate is the policy
        saying "I cannot see", not "nothing is there" (design note 4). Counting it would let a frozen
        render or a clock offset certify a clear sky -- the exact stream the 2026-08-24 QA probe
        produced with a bird squarely inside the cylinder. The stale count is the policy's own,
        already on the maneuver; nothing is recomputed here."""
        return (maneuver.decision is Decision.PROCEED
                and not maneuver.debug.get("n_stale_dropped"))

    def _resume(self, trigger: str, **detail) -> None:
        """The ONE hand-back to AUTO, whichever rule fired (ADR-006: MIS_RESTART=0 resumes the same
        next waypoint). `trigger` is load-bearing: a ceiling-forced hand-back logged as
        `threat_cleared` would be the artifact lying about why the mission resumed."""
        self.sink.set_mode(MODE_AUTO)
        self.mode = MODE_AUTO
        resumed_wp = self.sink.current_waypoint()
        self._log("resume", trigger=trigger, resumed_wp_index=resumed_wp,
                  wp_index_at_takeover=self._wp_at_takeover,
                  resumed_same_waypoint=(resumed_wp == self._wp_at_takeover),
                  latched_setpoint_enu=self._latched_setpoint,
                  clear_ticks_required=self.resume_clear_ticks,
                  ticks_in_guided=self._ticks_in_guided(), **detail)
        self._wp_at_takeover = None
        self._latched_setpoint = None       # encounter over -- the next one latches fresh
        self._guided_since_tick = None
        self._clear_ticks = 0

    def _ticks_in_guided(self) -> Optional[int]:
        """How long this encounter has held GUIDED, counting the current tick. None in AUTO."""
        if self._guided_since_tick is None:
            return None
        return self._tick - self._guided_since_tick + 1

    def _enforce_guided_ceiling(self) -> None:
        """Design note 4's backstop: no encounter holds GUIDED forever. ~10 lines, unconditional,
        and it runs BEFORE this tick's decision so a threat tick cannot keep deferring it."""
        held = self._ticks_in_guided()
        if held is None or held < self.guided_ceiling_ticks:
            return
        self._resume(
            "guided_ceiling", ceiling_ticks=self.guided_ceiling_ticks,
            reason=(f"held GUIDED for {held} ticks without {self.resume_clear_ticks} consecutive "
                    f"clear ticks -- handing the mission back on the BACKSTOP, not on a cleared "
                    f"threat. A detection duty cycle denser than 1-in-{self.resume_clear_ticks} "
                    f"ticks, or an all-stale detection stream, resets the hysteresis counter every "
                    f"time and would otherwise hold GUIDED for the rest of the flight (QA C1). "
                    f"Avoidance is NOT disabled: entry is instantaneous, so a threat still present "
                    f"takes over again on the next DIVERT tick with a freshly vetted point."))

    # -- decision handlers -----------------------------------------------------------------------
    def _handle_proceed(self, drone_state: DroneState, maneuver: AvoidanceManeuver) -> None:
        pending: Optional[dict] = None
        if self.mode == MODE_GUIDED and self._clear_ticks < self.resume_clear_ticks:
            # Not yet: absence has not persisted long enough to be a cleared threat (design note 4).
            # We stay in GUIDED and command nothing, so the vehicle keeps flying the already-vetted
            # dodge it was last given. `_enforce_guided_ceiling` bounds how long this can last.
            pending = {"clear_ticks": self._clear_ticks, "required": self.resume_clear_ticks,
                       "ticks_in_guided": self._ticks_in_guided(),
                       "ceiling_ticks": self.guided_ceiling_ticks}
        elif self.mode == MODE_GUIDED:
            self._resume("threat_cleared")
        self._record_position(drone_state.position_enu)
        self._log("proceed", position_enu=drone_state.position_enu,
                  wp_index=drone_state.current_wp_index,
                  **({"resume_pending": pending} if pending else {}),
                  **self._stale_detail(maneuver))

    def _handle_hold(self, drone_state: DroneState, maneuver: AvoidanceManeuver, *,
                     reason: Optional[str] = None) -> None:
        if self.mode != MODE_GUIDED:
            wp_at_takeover = drone_state.current_wp_index
            self._wp_at_takeover = wp_at_takeover
            self._guided_since_tick = self._tick        # starts the GUIDED ceiling's clock
            self.sink.set_mode(MODE_GUIDED)
            self.mode = MODE_GUIDED
            self._log("takeover", reason="hold", from_mode=MODE_AUTO, to_mode=MODE_GUIDED,
                      wp_index_at_takeover=wp_at_takeover,
                      track_id=self._track_id(maneuver))
        # Hover at the vehicle's own current position -- ZERO displacement. This is not a vetted
        # point and does not claim to be one (guarantee 1's HOLD paragraph): it is the vehicle's own
        # position, so there is nothing to choose and no bar it can honour. Coverage does NOT
        # advance: this position was already recorded (or will be, at most once) -- do not
        # double-count it against the ledger's swath computation beyond what a stationary hover
        # legitimately images.
        self.sink.send_setpoint_enu(drone_state.position_enu)
        self._record_position(drone_state.position_enu)
        # How close the hold itself is to the nearest threat this decision names. NOT a gate -- a
        # HOLD honours no bar -- but the artifact must show the number rather than leave the
        # question to an argument (QA round 3, 2026-08-24, finding 2). None when the maneuver names
        # no threat, e.g. a hand-built HOLD or a geofence-only reject.
        near = _nearest_threat(drone_state.position_enu, maneuver)
        self._log("hold", position_enu=drone_state.position_enu,
                  reason=reason or maneuver.reason, track_id=self._track_id(maneuver),
                  bird_clearance_m=(None if near is None else round(near[0], 3)),
                  bird_track_id=(None if near is None else near[1]),
                  min_bird_clearance_m=_flown_bird_clearance_bar(maneuver),
                  **self._stale_detail(maneuver))

    def _handle_divert(self, drone_state: DroneState, maneuver: AvoidanceManeuver) -> None:
        policy_setpoint = maneuver.setpoint_enu
        assert policy_setpoint is not None  # AvoidanceManeuver.__post_init__ guarantees this for DIVERT

        # SETPOINT LATCH (design note 3): pick WHICH point this tick commands before vetting it.
        # No latch yet -> the policy's point becomes the latch candidate. Latched already -> keep
        # re-commanding the latched point and ignore the policy's per-tick recompute drift, UNLESS
        # the policy has moved further than RELATCH_THRESHOLD_M (a genuinely moving threat), which
        # makes it a re-latch candidate. `latch_action is None` means "re-commanding the latch".
        latched = self._latched_setpoint
        offset_m: Optional[float] = None
        relatch_refused = False
        if latched is None:
            setpoint, latch_action = policy_setpoint, "latch"
        else:
            offset_m = _dist_3d(policy_setpoint, latched)
            if offset_m <= RELATCH_THRESHOLD_M:
                setpoint, latch_action = latched, None
            elif maneuver.debug.get("range_degenerate"):
                # R3: the jump is big enough to look like a moving threat, but the policy computed
                # it at a trigger range where the away-vector's DIRECTION is noise. Keep the
                # already-vetted latch; do not chase the noise. (A FIRST latch at degenerate range
                # is still permitted -- am. 12 scoped R3 to re-latch, and refusing the first latch
                # would mean not dodging at all.)
                setpoint, latch_action = latched, None
                relatch_refused = True
            else:
                setpoint, latch_action = policy_setpoint, "relatch"
        # What the event log calls this tick's latch handling. A refusal leaves `latch_action` None
        # -- no latch/relatch event, no state change -- so this label is the ONLY place R3 shows up,
        # and it must therefore always be written, on the reject path too.
        latch_label = ("relatch_refused_degenerate" if relatch_refused
                       else latch_action or "recommand_latched")

        # SAFETY BACKSTOP (ADR-006): re-vet whatever point we are about to command -- fresh, re-latch
        # candidate, or the latched point on its Nth re-command -- regardless of what the policy
        # already checked. The latch is a smoothing rule, never a way to skip this gate. Reject ->
        # HOLD. Never call sink.send_setpoint_enu on a rejected point.
        #
        # TWO halves, because the geofence half cannot see a bird (guarantee 1). Trees do not move,
        # so re-vetting a latch against them is nearly free; BIRDS do, and a latched point is only
        # ever bird-vetted against where they were when it was latched. The bird half is what stops
        # a re-command -- including an R3 refusal's -- from flying a point the policy would refuse
        # to place today. A FRESH policy setpoint passes it by construction (the policy applies the
        # same bar to the same threats), so this costs an honest dodge nothing.
        safe = self.geofence.is_safe_3d(
            setpoint, vertical_margin_m=self.vertical_margin_m, alt_bounds=self.alt_bounds)
        near = _nearest_threat(setpoint, maneuver)
        bar = _flown_bird_clearance_bar(maneuver)
        bird_reject = near is not None and bar is not None and near[0] < bar
        if not safe or bird_reject:
            unsafe_obstacle = (self.geofence.unsafe_obstacle_3d(setpoint, self.vertical_margin_m)
                               if not safe else None)
            self._log(
                "gate_reject", setpoint_enu=setpoint,
                obstacle_id=unsafe_obstacle.id if unsafe_obstacle else None,
                bird_clearance_m=(None if near is None else round(near[0], 3)),
                bird_track_id=(None if near is None else near[1]),
                min_bird_clearance_m=bar,
                # Say what a rejection IS. It is a refusal to fly a forbidden point, not the
                # selection of a safer one: the executor has no escape geometry (R4, open), so it
                # commands zero displacement instead. At degenerate range the vehicle is already
                # inside the bar, so the hold can be NEARER the bird than the point just refused --
                # calling that "falling back to HOLD" read as though HOLD were the safer option
                # (QA round 3, 2026-08-24, finding 2).
                reason=("DIVERT setpoint failed the 3D geofence/altitude re-vet and is REFUSED. No "
                        "vetted alternative exists this tick, so the executor commands zero "
                        "displacement (HOLD) -- a refusal to fly a forbidden point, not a safer "
                        "point. Choosing one is escape geometry: R4, open."
                        if not safe else
                        f"DIVERT setpoint sits {near[0]:.3f} m from bird {near[1]}, inside the "
                        f"policy's own min_bird_clearance_m {bar:.2f} m, and is REFUSED. No vetted "
                        f"alternative exists this tick, so the executor commands zero displacement "
                        f"(HOLD). A HOLD honours NO clearance bar -- at degenerate range the "
                        f"vehicle is inside the bar by construction and the hold can be nearer the "
                        f"bird than the point just refused (see the hold event's own "
                        f"bird_clearance_m). Choosing a point that IS outside the bar is escape "
                        f"geometry: R4, open."),
                policy_reason=maneuver.reason, track_id=self._track_id(maneuver),
                latch_action=latch_label,
            )
            # A rejected fresh/re-latch candidate leaves any existing latch intact -- the point we
            # are already flying is still vetted and still good. But if the LATCHED point itself
            # just failed, it is no longer flyable: drop it, or every remaining tick of this
            # encounter re-rejects the same dead point instead of latching a fresh vetted one.
            if latch_action is None:
                self._latched_setpoint = None
            self._handle_hold(drone_state, maneuver,
                              reason=f"gate_reject:{maneuver.reason or 'unvetted'}")
            return

        if self.mode != MODE_GUIDED:
            wp_at_takeover = drone_state.current_wp_index
            self._wp_at_takeover = wp_at_takeover      # one takeover per threat encounter
            self._guided_since_tick = self._tick       # starts the GUIDED ceiling's clock
            self.sink.set_mode(MODE_GUIDED)
            self.mode = MODE_GUIDED
            self._log("takeover", reason="divert", from_mode=MODE_AUTO, to_mode=MODE_GUIDED,
                      wp_index_at_takeover=wp_at_takeover, track_id=self._track_id(maneuver))

        # The candidate survived the backstop -- only now does it become (or replace) the latch.
        if latch_action is not None:
            self._log(latch_action, setpoint_enu=setpoint, previous_setpoint_enu=latched,
                      offset_m=offset_m, relatch_threshold_m=RELATCH_THRESHOLD_M,
                      reason=("first vetted dodge of this encounter; re-commanded until it clears"
                              if latch_action == "latch" else
                              "policy setpoint moved beyond the re-latch threshold and re-vetted safe"),
                      track_id=self._track_id(maneuver))
            self._latched_setpoint = setpoint

        self._record_position(drone_state.position_enu)  # where the drone ACTUALLY is this tick
        self.sink.send_setpoint_enu(setpoint)            # (re)command the vetted dodge target
        # The commanded setpoint is deliberately NOT recorded into flown_path: a command is not a
        # position. Recording it let a never-visited cell finalize as COVERED (found 2026-08-18) --
        # the exact silent-coverage lie this module exists to prevent. If the vehicle really flies
        # to the setpoint, the next tick's drone_state records it; if the threat clears first, the
        # cell under the setpoint honestly books as debt. Regression:
        # test_commanded_but_unflown_setpoint_does_not_cover (tests/.../test_avoidance_executor.py).
        self._log("maneuver", decision="divert", setpoint_enu=setpoint, verdict="accepted",
                  debug=maneuver.debug, policy_reason=maneuver.reason,
                  track_id=self._track_id(maneuver),
                  # What the policy wanted this tick vs what we actually flew: equal on the latching
                  # tick, and on later ticks this is the paper trail for the ignored drift.
                  policy_setpoint_enu=policy_setpoint,
                  latch_action=latch_label)

        # Audit-only: which cells were "in the shadow" of this divert, for the event log / a human
        # reading it later. finalize() is the actual source of truth for coverage status.
        self._divert_audits.append(DivertAudit(
            tick=self._tick, track_id=self._track_id(maneuver),
            at_risk_cell_ids=self._at_risk_cells(drone_state.position_enu),
        ))

        # STAY in GUIDED holding this dodge until the threat clears. The single hand-back to AUTO is
        # done in _handle_proceed when the policy next returns PROCEED -- NOT here every tick. This is
        # what stops the 5 Hz GUIDED<->AUTO thrash: take over once, hold, resume once (ADR-006 v1).

    @staticmethod
    def _track_id(maneuver: AvoidanceManeuver) -> Optional[str]:
        det = maneuver.triggering_detection
        return det.track_id if det is not None else None

    # -- finalize: THE coverage-debt bookkeeping -------------------------------------------------
    def finalize(self) -> List[dict]:
        """Build the terminal coverage ledger from the ACTUAL flown path -- the single source of
        truth, computed with the exact same `coverage.coverage_from_path` the nominal-mission
        baseline uses. Every canonical cell in `self.cells` is visited exactly once here, so the
        P1 partition invariant (`coverage.check_ledger`) holds by construction: there is no branch
        that can leave a cell out of the ledger. A cell not imaged by the final flown path becomes
        EXPLICIT `debt` (ADR-002 v1 bar), never silently absent.

        Idempotent: safe to call more than once (returns the same ledger), but `step()` may not be
        called again afterward.
        """
        if self._finalized:
            # True idempotency: without this guard a second call re-appended every "debt" event and
            # a duplicate "divert_audit_summary" to the event log, quietly falsifying the docstring.
            return self.coverage_ledger
        flown_xy = [(p[0], p[1]) for p in self.flown_path]
        covered_map: Dict[str, bool] = coverage_from_path(self.cells, flown_xy, self.swath_half_width_m)

        ledger: List[dict] = []
        for cell in self.cells:
            hit = covered_map.get(cell.cell_id, False)
            status = CELL_COVERED if hit else CELL_DEBT
            ledger.append(LedgerRecord(cell.cell_id, status).to_dict())
            if status == CELL_DEBT:
                self._log("debt", cell_id=cell.cell_id,
                          reason="not imaged by final flown path (ADR-002 v1: explicit debt, not dropped)")

        # Audit cross-reference: for every cell flagged "at risk" during a divert, note in the
        # log + requeue_events whether the final flown path still covered it (i.e. a later leg of
        # the SAME resumed mission naturally re-imaged it -- not a v1 requeue mechanism, just an
        # honest report of what actually happened).
        requeue_events: List[dict] = []
        final_status = {r["cell_id"]: r["status"] for r in ledger}
        for audit in self._divert_audits:
            for cell_id in audit.at_risk_cell_ids:
                if final_status.get(cell_id) == CELL_COVERED:
                    requeue_events.append({"cell_id": cell_id, "t_s": float(audit.tick)})
        self._log("divert_audit_summary",
                  n_diverts=len(self._divert_audits),
                  n_at_risk_cells_recovered=len(requeue_events))

        self.coverage_ledger = ledger
        self.requeue_events = requeue_events
        self._finalized = True
        return ledger

    # -- convenience -------------------------------------------------------------------------------
    def executor_params(self) -> dict:
        """The knobs the EXECUTOR flew, read off the instance rather than off the module constants.

        The counterpart to `run.policy_params`: those are the bars the policy vetted against, these
        are the rules that decided when to take control back. They must be in the artifact even on a
        flight with no encounter at all -- otherwise "this flight used 3-tick hysteresis" is only
        provable from a resume event that an encounter-free flight never writes (QA F-condition,
        2026-08-25). `swath_half_width_m` is deliberately NOT duplicated here: it has been a
        top-level key of this log since Week 2 and moving it would break every reader."""
        return {
            "resume_clear_ticks": self.resume_clear_ticks,
            "guided_ceiling_ticks": self.guided_ceiling_ticks,
            "relatch_threshold_m": RELATCH_THRESHOLD_M,
            "vertical_margin_m": self.vertical_margin_m,
        }

    def flight_log(self, scenario: str, seed: int, cell_size_m: float,
                   detection: Optional[dict] = None) -> dict:
        """Assemble the `eval/scenarios/<name>/flight_log.json` contract (see
        `tests/fieldguard_planning/test_safety_scenarios_pending.py` module docstring / eval/scenarios
        /README.md -- keep in sync). Call after `finalize()`."""
        if not self._finalized:
            raise RuntimeError("call finalize() before flight_log()")
        log = {
            "scenario": scenario,
            "seed": seed,
            "cell_size_m": cell_size_m,
            "swath_half_width_m": self.swath_half_width_m,
            "executor_params": self.executor_params(),
            "flown_path_enu": [list(p) for p in self.flown_path],
            "coverage_ledger": self.coverage_ledger,
            "requeue_events": self.requeue_events,
            "events": self.event_log,
        }
        if detection is not None:
            log["detection"] = detection
        return log
