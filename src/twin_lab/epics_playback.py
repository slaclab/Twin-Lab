"""Real-time (or scaled) playback of recorded open-loop motor commands.

Recorded commands are discrete, timestamped set-points, not continuous
samples, so playback holds the last commanded value between two commands
(zero-order hold) rather than interpolating a physically unknown in-between
motion. See docs/repo memory `controls-epics-integration.md` for why
"current position" derived from EPICS is an ESTIMATE anchored to an
unresolved per-power-cycle offset (`home_position` below), not a measurement.
"""

from __future__ import annotations

import json
import time
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from math import pi
from pathlib import Path

import yaml

from .epics import CommandHistoryClient, MotorCommand, MotorPvMap, RecordedEpicsClient, to_sdf_position


@dataclass
class JointTrack:
    """One joint's sorted command history, in Drake units, with a home offset."""

    joint_name: str
    joint_type: str
    commands: list[MotorCommand]
    home_position: float = 0.0

    def position_at(self, moment: datetime) -> float:
        """Zero-order-hold Drake position for this joint at `moment`.

        Before the first recorded command, holds `home_position` unchanged.
        """

        if not self.commands:
            return self.home_position
        timestamps = [item.timestamp for item in self.commands]
        index = bisect_right(timestamps, moment) - 1
        if index < 0:
            return self.home_position
        return self.home_position + to_sdf_position(self.commands[index].commanded, self.joint_type)


def build_tracks(
    client: CommandHistoryClient,
    mappings: dict[str, MotorPvMap],
    joint_types: dict[str, str],
    home_positions: dict[str, float] | None = None,
) -> dict[str, JointTrack]:
    """Fetch each joint's archived command history and sort it for playback."""

    homes = home_positions or {}
    tracks: dict[str, JointTrack] = {}
    for joint_name, mapping in mappings.items():
        commands = sorted(client.commands(mapping), key=lambda item: item.timestamp)
        tracks[joint_name] = JointTrack(
            joint_name=joint_name,
            joint_type=joint_types[joint_name],
            commands=commands,
            home_position=homes.get(joint_name, 0.0),
        )
    return tracks


@dataclass
class PlaybackClock:
    """Maps wall-clock time to a point in recorded session time, at a fixed rate."""

    session_start: datetime
    speed: float = 1.0
    _wall_start: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.session_start.tzinfo is None:
            raise ValueError("PlaybackClock.session_start must be timezone-aware")
        if self.speed <= 0:
            raise ValueError("PlaybackClock.speed must be positive")
        self._wall_start = time.monotonic()

    def current_moment(self, now: float | None = None) -> datetime:
        """Recorded-session timestamp corresponding to the current wall clock."""

        elapsed = (now if now is not None else time.monotonic()) - self._wall_start
        return self.session_start + timedelta(seconds=elapsed * self.speed)

    def set_speed(self, speed: float, now: float | None = None) -> None:
        """Change playback rate without jumping the current recorded moment."""

        if speed <= 0:
            raise ValueError("PlaybackClock.speed must be positive")
        anchor = now if now is not None else time.monotonic()
        self.session_start = self.current_moment(anchor)
        self._wall_start = anchor
        self.speed = speed


class PlaybackSource:
    """Drives per-joint positions from a fixed set of tracks, keyed by a clock."""

    def __init__(self, tracks: dict[str, JointTrack], clock: PlaybackClock):
        self._tracks = tracks
        self._clock = clock

    @property
    def joint_names(self) -> frozenset[str]:
        """Every joint this source can drive."""

        return frozenset(self._tracks)

    def positions(self, now: float | None = None) -> dict[str, float]:
        """Current joint_name -> Drake position for every tracked joint."""

        moment = self._clock.current_moment(now)
        return {name: track.position_at(moment) for name, track in self._tracks.items()}

    def is_finished(self, now: float | None = None) -> bool:
        """True once every track has passed its last recorded command."""

        moment = self._clock.current_moment(now)
        return all(
            not track.commands or moment >= track.commands[-1].timestamp
            for track in self._tracks.values()
        )


def load_command_map(path: str | Path) -> tuple[dict[str, MotorPvMap], dict[str, str]]:
    """Load a crystal-stack-command-map YAML (see config/) into PV mappings.

    Raises ValueError listing every joint still missing a `command_pv`,
    rather than silently skipping it - playback with a partial joint set
    would render a misleading recreation of the session.
    """

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    mappings: dict[str, MotorPvMap] = {}
    joint_types: dict[str, str] = {}
    missing: list[str] = []
    for stack_name, joints in data["joints"].items():
        for axis_name, spec in joints.items():
            ref = spec["ref"]
            command_pv = spec.get("command_pv")
            if command_pv is None:
                missing.append(f"{stack_name}:{axis_name} ({ref})")
                continue
            mappings[ref] = MotorPvMap(joint_name=ref, command_pv=command_pv)
            joint_types[ref] = spec["joint_type"]
    if missing:
        raise ValueError("command_pv is not filled in for: " + ", ".join(missing))
    return mappings, joint_types


def load_home_positions(inventory_path: str | Path, joint_names: list[str]) -> dict[str, float]:
    """Home position (Drake units) for each joint, from `joint_limit_overrides`.

    Joints without an override default to 0.0. This assumes today's reviewed
    inventory home coincides with the arbitrary controller-startup pose the
    session's commands are relative to (no limit-switch homing was done this
    session, so that assumption is not independently verified).
    """

    data = yaml.safe_load(Path(inventory_path).read_text(encoding="utf-8"))
    overrides = data.get("joint_limit_overrides", {})
    homes: dict[str, float] = {}
    for joint in joint_names:
        override = overrides.get(joint, {})
        home = override.get("home", 0.0)
        unit = override.get("unit", "meter")
        if unit == "degree":
            homes[joint] = float(home) * pi / 180.0
        elif unit == "meter":
            homes[joint] = float(home)
        else:
            raise ValueError(f"Unsupported joint_limit_overrides unit: {unit!r}")
    return homes


def load_recorded_commands(path: str | Path) -> tuple[datetime | None, list[MotorCommand]]:
    """Load a JSON recording: `{"commands": [{joint, timestamp, commanded}, ...]}`.

    `timestamp` must be an ISO-8601 string with a UTC offset. This is a stand-in
    for a real archiver pull - useful for demos/tests without archapp access.
    """

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    commands = [
        MotorCommand(item["joint"], datetime.fromisoformat(item["timestamp"]), float(item["commanded"]))
        for item in data["commands"]
    ]
    for command in commands:
        if command.timestamp.tzinfo is None:
            raise ValueError(f"Recorded command timestamp must include a timezone: {command}")
    session_start = min((item.timestamp for item in commands), default=None)
    return session_start, commands


def build_playback_from_recording(
    recording_path: str | Path,
    command_map_path: str | Path,
    inventory_path: str | Path,
    *,
    speed: float = 1.0,
) -> PlaybackSource:
    """Wire a recorded-commands JSON file into a ready-to-drive PlaybackSource."""

    mappings, joint_types = load_command_map(command_map_path)
    session_start, commands = load_recorded_commands(recording_path)
    if session_start is None:
        raise ValueError(f"No recorded commands in {recording_path}")
    homes = load_home_positions(inventory_path, list(mappings))
    tracks = build_tracks(RecordedEpicsClient(commands), mappings, joint_types, homes)
    clock = PlaybackClock(session_start=session_start, speed=speed)
    return PlaybackSource(tracks, clock)
