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

1. **Never fly an unvetted setpoint.** Every DIVERT setpoint is re-vetted through
   `GeofenceMap.is_safe_3d` here, even though the policy is supposed to have already vetted it --
   this is the safety BACKSTOP, not the primary check. On rejection the executor falls back to HOLD
   (hover in GUIDED at the vehicle's last known-safe position) and never sends the rejected point to
   the vehicle.
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
   Latching never bypasses guarantee 1 -- every point handed to the sink, latched or fresh, is
   re-vetted on the tick it is commanded.

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


def _dist_3d(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    """Euclidean distance between two world-ENU points. 3D on purpose: an altitude-only jump in the
    commanded dodge is just as jumpy on film as a lateral one. `** 0.5` keeps this module math-free
    (stdlib-only discipline, same as `geofence.py` / `coverage.py`)."""
    dx, dy, dz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return (dx * dx + dy * dy + dz * dz) ** 0.5


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
    ):
        self.geofence = geofence
        self.cells: List[CoverageCell] = list(cells)
        self.sink = sink
        self.swath_half_width_m = swath_half_width_m
        self.alt_bounds = alt_bounds
        self.vertical_margin_m = vertical_margin_m

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
        if maneuver.decision is Decision.PROCEED:
            self._handle_proceed(drone_state)
        elif maneuver.decision is Decision.HOLD:
            self._handle_hold(drone_state, maneuver)
        elif maneuver.decision is Decision.DIVERT:
            self._handle_divert(drone_state, maneuver)
        else:  # pragma: no cover -- Decision is a closed enum; defensive only
            raise ValueError(f"unhandled Decision: {maneuver.decision!r}")

    # -- decision handlers -----------------------------------------------------------------------
    def _handle_proceed(self, drone_state: DroneState) -> None:
        if self.mode == MODE_GUIDED:
            # Threat cleared -> the SINGLE hand-back after a maneuver (ADR-006: MIS_RESTART=0 resumes
            # the same next waypoint). Not a per-tick toggle -- we only get here once the policy stops
            # returning DIVERT/HOLD.
            self.sink.set_mode(MODE_AUTO)
            self.mode = MODE_AUTO
            resumed_wp = self.sink.current_waypoint()
            self._log("resume", trigger="threat_cleared", resumed_wp_index=resumed_wp,
                      wp_index_at_takeover=self._wp_at_takeover,
                      resumed_same_waypoint=(resumed_wp == self._wp_at_takeover),
                      latched_setpoint_enu=self._latched_setpoint)
            self._wp_at_takeover = None
            self._latched_setpoint = None   # encounter over -- the next one latches fresh
        self._record_position(drone_state.position_enu)
        self._log("proceed", position_enu=drone_state.position_enu,
                  wp_index=drone_state.current_wp_index)

    def _handle_hold(self, drone_state: DroneState, maneuver: AvoidanceManeuver, *,
                     reason: Optional[str] = None) -> None:
        if self.mode != MODE_GUIDED:
            wp_at_takeover = drone_state.current_wp_index
            self._wp_at_takeover = wp_at_takeover
            self.sink.set_mode(MODE_GUIDED)
            self.mode = MODE_GUIDED
            self._log("takeover", reason="hold", from_mode=MODE_AUTO, to_mode=MODE_GUIDED,
                      wp_index_at_takeover=wp_at_takeover,
                      track_id=self._track_id(maneuver))
        # Hover at the vehicle's own (already-safe) current position -- never fly a new, unvetted
        # point while holding. Coverage does NOT advance: this position was already recorded (or
        # will be, at most once) -- do not double-count it against the ledger's swath computation
        # beyond what a stationary hover legitimately images.
        self.sink.send_setpoint_enu(drone_state.position_enu)
        self._record_position(drone_state.position_enu)
        self._log("hold", position_enu=drone_state.position_enu,
                  reason=reason or maneuver.reason, track_id=self._track_id(maneuver))

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
        if latched is None:
            setpoint, latch_action = policy_setpoint, "latch"
        else:
            offset_m = _dist_3d(policy_setpoint, latched)
            if offset_m > RELATCH_THRESHOLD_M:
                setpoint, latch_action = policy_setpoint, "relatch"
            else:
                setpoint, latch_action = latched, None

        # SAFETY BACKSTOP (ADR-006): re-vet whatever point we are about to command -- fresh, re-latch
        # candidate, or the latched point on its Nth re-command -- regardless of what the policy
        # already checked. The latch is a smoothing rule, never a way to skip this gate. Reject ->
        # HOLD. Never call sink.send_setpoint_enu on a rejected point.
        safe = self.geofence.is_safe_3d(
            setpoint, vertical_margin_m=self.vertical_margin_m, alt_bounds=self.alt_bounds)
        if not safe:
            unsafe_obstacle = self.geofence.unsafe_obstacle_3d(setpoint, self.vertical_margin_m)
            self._log(
                "gate_reject", setpoint_enu=setpoint,
                obstacle_id=unsafe_obstacle.id if unsafe_obstacle else None,
                reason="DIVERT setpoint failed 3D geofence/altitude re-vet; falling back to HOLD",
                policy_reason=maneuver.reason, track_id=self._track_id(maneuver),
                latch_action=latch_action or "recommand_latched",
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
                  latch_action=latch_action or "recommand_latched")

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
            "flown_path_enu": [list(p) for p in self.flown_path],
            "coverage_ledger": self.coverage_ledger,
            "requeue_events": self.requeue_events,
            "events": self.event_log,
        }
        if detection is not None:
            log["detection"] = detection
        return log
