"""Protocol-independent EPICS integration primitives.

The live transport is deliberately not part of this module.  EPICS channel
access, recorded history, and tests can all produce the same observations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Protocol


@dataclass(frozen=True)
class MotorPvMap:
    """Map one normalized Twin-Lab joint to its controls PVs."""

    joint_name: str
    command_pv: str
    readback_pv: str
    done_pv: str | None = None
    stop_pv: str | None = None
    low_limit_pv: str | None = None
    high_limit_pv: str | None = None
    home_status_pv: str | None = None
    units: str = ""
    scale_to_sdf: float = 1.0
    offset_to_sdf: float = 0.0


@dataclass(frozen=True)
class MotorObservation:
    """One timestamped, normalized motor observation."""

    joint_name: str
    timestamp: datetime
    readback: float | None
    commanded: float | None = None
    moving: bool | None = None
    low_limit: bool | None = None
    high_limit: bool | None = None
    homed: bool | None = None
    alarm: str | None = None
    connected: bool = True

    def age_s(self, now: datetime | None = None) -> float:
        """Return observation age, rejecting naive timestamps."""

        current = now or datetime.now(timezone.utc)
        timestamp = self.timestamp
        if timestamp.tzinfo is None:
            raise ValueError("Motor observation timestamps must include a timezone")
        return max((current - timestamp).total_seconds(), 0.0)

    def is_usable(self, *, max_age_s: float, now: datetime | None = None) -> bool:
        """Whether this observation is connected, fresh, and has a readback."""

        return self.connected and self.readback is not None and self.age_s(now) <= max_age_s


class ReadOnlyEpicsClient(Protocol):
    """Minimal read-only transport required by the simulation."""

    def observe(self, mapping: MotorPvMap) -> MotorObservation: ...


class RecordedEpicsClient:
    """Read observations from an in-memory recorded stream."""

    def __init__(self, observations: list[MotorObservation]):
        self._observations = {item.joint_name: item for item in observations}

    def observe(self, mapping: MotorPvMap) -> MotorObservation:
        """Return the latest recorded observation for a mapped joint."""

        try:
            return self._observations[mapping.joint_name]
        except KeyError as error:
            raise KeyError(f"No recorded observation for '{mapping.joint_name}'") from error


def to_sdf_position(mapping: MotorPvMap, controls_value: float) -> float:
    """Convert a controls engineering value into the SDF joint coordinate."""

    return float(controls_value) * mapping.scale_to_sdf + mapping.offset_to_sdf


def require_fresh_observations(
    observations: list[MotorObservation],
    mappings: Mapping[str, MotorPvMap],
    *,
    max_age_s: float,
    now: datetime | None = None,
) -> dict[str, float]:
    """Return usable SDF positions or fail closed when state is incomplete."""

    unusable = [
        item.joint_name
        for item in observations
        if not item.is_usable(max_age_s=max_age_s, now=now)
    ]
    if unusable:
        names = ", ".join(sorted(unusable))
        raise ValueError(f"Motor state is missing, stale, or disconnected: {names}")
    missing_mappings = sorted({item.joint_name for item in observations} - set(mappings))
    if missing_mappings:
        names = ", ".join(missing_mappings)
        raise ValueError(f"No PV-to-SDF mapping for: {names}")
    return {
        item.joint_name: to_sdf_position(mappings[item.joint_name], float(item.readback))
        for item in observations
    }