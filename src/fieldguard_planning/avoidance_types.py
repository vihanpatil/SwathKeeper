"""Shared contract types for the reactive-avoidance loop (Weeks 3-4, the core).

This module is the interface boundary between:
  - the **decision policy** (perception-ml-engineer, `avoidance_policy.py`) — decides *when/where* to
    dodge given a detection + geofence + coverage state, and
  - the **executor** (flight-software-engineer, `avoidance_executor.py`) — takes control per ADR-006
    (AUTO->GUIDED->setpoint->AUTO), executes the maneuver, resumes, and books coverage-debt.

Frame convention (ADR-005 / ADR-006): all positions are **world-ENU metres** relative to the field
home origin (`config/field_polygon.json`). The executor commands GUIDED setpoints via
`/ap/cmd_gps_pose` with `frame_id="map"` (world-ENU); see ADR-006. Stdlib-only by design so the whole
loop stays unit-testable on a bare interpreter (matches `tests/fieldguard_planning`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Decision(str, Enum):
    """What the avoidance policy decided for the current frame."""
    PROCEED = "proceed"   # no threat — stay on the coverage mission, no takeover
    DIVERT = "divert"     # threat — take control and fly to `setpoint_enu`, then resume
    HOLD = "hold"         # threat, but no safe divert found — hover in GUIDED, do not proceed


@dataclass(frozen=True)
class Detection:
    """A dynamic-obstacle (bird) detection, expressed in world-ENU metres.

    Upstream this is produced from the NDVI blob detector (ADR-003, `eval/baseline_ndvi.py`) plus a
    range/projection estimate; the policy consumes this abstraction, not raw pixels, so it stays
    testable without the sim.
    """
    position_enu: tuple[float, float, float]   # estimated bird position (E, N, U) metres
    frame_id: int                              # source frame index (for logging / per-track metrics)
    confidence: float = 1.0                    # detector confidence in [0, 1]
    track_id: Optional[str] = None             # stable id across frames if available (e.g. "bird_0")
    source: str = "ndvi_blob"                  # provenance tag for the event log


@dataclass(frozen=True)
class DroneState:
    """Minimal ownship state the policy/executor need, world-ENU."""
    position_enu: tuple[float, float, float]   # (E, N, U) metres
    heading_rad: float                         # yaw, ENU convention (0 = +E, CCW positive)
    current_wp_index: int                      # the coverage waypoint the mission is heading to
    ground_speed_mps: float = 0.0


@dataclass
class AvoidanceManeuver:
    """Policy output -> executor input. The single object handed across the boundary.

    Invariant the executor MUST enforce before acting: when `decision is Decision.DIVERT`,
    `setpoint_enu` is non-None AND has already been vetted by the 3D geofence gate
    (`geofence.is_safe_3d`). The executor re-checks it as a safety backstop and falls back to HOLD on
    rejection — it never flies an unvetted setpoint (ADR-006 safety requirement).
    """
    decision: Decision
    setpoint_enu: Optional[tuple[float, float, float]] = None  # GUIDED target (world-ENU); None unless DIVERT
    reason: str = ""                                           # human-readable, for the event log
    triggering_detection: Optional[Detection] = None
    # Free-form structured context for logging / QA assertions (e.g. clearance margins, threat range).
    debug: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.decision is Decision.DIVERT and self.setpoint_enu is None:
            raise ValueError("DIVERT maneuver must carry a setpoint_enu")
        if self.decision is not Decision.DIVERT and self.setpoint_enu is not None:
            raise ValueError(f"{self.decision} maneuver must not carry a setpoint_enu")
