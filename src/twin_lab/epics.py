"""Protocol-independent EPICS command-history primitives.

The controls are open-loop, so EPICS contributes timestamped commands rather
than measured motor state. Stage type and model-coordinate conversion belong
to the catalog and simulation model respectively.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import pi
from typing import Protocol


@dataclass(frozen=True)
class MotorPvMap:
    """Map one normalized Twin-Lab joint to its command PV."""

    joint_name: str
    command_pv: str


@dataclass(frozen=True)
class MotorCommand:
    """One timestamped open-loop motor command in controls units."""

    joint_name: str
    timestamp: datetime
    commanded: float

    def age_s(self, now: datetime | None = None) -> float:
        """Return command age, rejecting naive timestamps."""

        current = now or datetime.now(timezone.utc)
        timestamp = self.timestamp
        if timestamp.tzinfo is None:
            raise ValueError("Motor command timestamps must include a timezone")
        return max((current - timestamp).total_seconds(), 0.0)


class CommandHistoryClient(Protocol):
    """Minimal command-history interface required by the simulation."""

    def commands(self, mapping: MotorPvMap) -> list[MotorCommand]: ...


class RecordedEpicsClient:
    """Read commands from an in-memory recorded stream."""

    def __init__(self, commands: list[MotorCommand]):
        self._commands = commands

    def commands(self, mapping: MotorPvMap) -> list[MotorCommand]:
        """Return commands for a mapped joint in recorded order."""

        return [item for item in self._commands if item.joint_name == mapping.joint_name]


def to_sdf_position(controls_value: float, joint_type: str) -> float:
    """Convert catalog-typed controls units to Drake's internal units."""

    if joint_type == "prismatic":
        return float(controls_value) * 0.001
    if joint_type == "revolute":
        return float(controls_value) * pi / 180.0
    raise ValueError(f"Unsupported catalog joint type: {joint_type!r}")


def require_recent_commands(
    commands: list[MotorCommand],
    *,
    max_age_s: float,
    now: datetime | None = None,
) -> list[MotorCommand]:
    """Return recent commands; this does not claim physical motor position."""

    for item in commands:
        if item.timestamp.tzinfo is None:
            raise ValueError("Motor command timestamps must include a timezone")
        if item.age_s(now) > max_age_s:
            raise ValueError(f"Motor command is stale: {item.joint_name}")
    return list(commands)