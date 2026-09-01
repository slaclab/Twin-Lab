"""Real-time (or scaled) playback of recorded open-loop motor commands.

Recorded commands are discrete, timestamped set-points, not continuous
samples. Playback ramps continuously from one commanded set-point to the
next at the stage's real datasheet max speed (see `JointTrack.max_speed`,
config/stage-catalog.yaml), rather than jumping instantly - but where along
that ramp the motor actually was is still not measured (no encoders), so
this is a best-effort reconstruction, not observed motion. See docs/repo
memory `controls-epics-integration.md` for why "current position" derived
from EPICS is an ESTIMATE anchored to an unresolved per-power-cycle offset
(`home_position` below), not a measurement.
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import json
import time
from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from math import copysign, pi
from pathlib import Path

import yaml

from .epics import CommandHistoryClient, MotorCommand, MotorPvMap, RecordedEpicsClient, to_sdf_position
from .paths import resolve_repo_path


@dataclass
class JointTrack:
    """One joint's sorted command history, in Drake units, with a home offset.

    `max_speed` (Drake units/s: m/s for prismatic, rad/s for revolute) caps
    how fast `position_at()` lets the position change between one command
    and the next. Defaults to `inf` (instant zero-order hold) for joints
    whose real max speed isn't known.
    """

    joint_name: str
    joint_type: str
    commands: list[MotorCommand]
    home_position: float = 0.0
    max_speed: float = float("inf")
    speed_fraction: float = 1.0

    @property
    def effective_max_speed(self) -> float:
        """Datasheet max speed derated by the current travel-speed fraction."""

        return self.max_speed * self.speed_fraction

    def _target_at(self, index: int) -> float:
        return self.home_position + to_sdf_position(self.commands[index].commanded, self.joint_type)

    def position_at(self, moment: datetime) -> float:
        """Drake position for this joint at `moment`.

        Before the first recorded command, holds `home_position` unchanged.
        After a command lands, ramps at `max_speed` toward its target and
        holds there once reached - continuous motion, not an instant jump,
        but still just a reconstruction from open-loop set-points.
        """

        if not self.commands:
            return self.home_position
        timestamps = [item.timestamp for item in self.commands]
        index = bisect_right(timestamps, moment) - 1
        if index < 0:
            return self.home_position
        target = self._target_at(index)
        speed = self.effective_max_speed
        if speed == float("inf"):
            return target
        start = self._target_at(index - 1) if index > 0 else self.home_position
        # A zero fraction means the stage is held still, not moved instantly.
        if speed <= 0.0:
            return start
        elapsed = max((moment - self.commands[index].timestamp).total_seconds(), 0.0)
        max_delta = speed * elapsed
        delta = target - start
        if abs(delta) <= max_delta:
            return target
        return start + copysign(max_delta, delta)


def build_tracks(
    client: CommandHistoryClient,
    mappings: dict[str, MotorPvMap],
    joint_types: dict[str, str],
    home_positions: dict[str, float] | None = None,
    max_speeds: dict[str, float] | None = None,
) -> dict[str, JointTrack]:
    """Fetch each joint's archived command history and sort it for playback."""

    homes = home_positions or {}
    speeds = max_speeds or {}
    tracks: dict[str, JointTrack] = {}
    for joint_name, mapping in mappings.items():
        commands = sorted(client.commands(mapping), key=lambda item: item.timestamp)
        tracks[joint_name] = JointTrack(
            joint_name=joint_name,
            joint_type=joint_types[joint_name],
            commands=commands,
            home_position=homes.get(joint_name, 0.0),
            max_speed=speeds.get(joint_name, float("inf")),
        )
    return tracks


@dataclass
class PlaybackClock:
    """Maps wall-clock time to a point in recorded session time, at a fixed rate.

    `record_start` is the fixed original start of the replay window. Pausing,
    resuming, changing speed, and restarting only move the internal anchor
    used by `current_moment()` - they never change `record_start` itself, so
    `restart()` can always seek back to the true beginning of the recording.
    """

    record_start: datetime
    speed: float = 1.0
    _wall_anchor: float = field(default=0.0, init=False, repr=False)
    _moment_anchor: datetime = field(default=None, init=False, repr=False)  # type: ignore[assignment]
    _paused: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.record_start.tzinfo is None:
            raise ValueError("PlaybackClock.record_start must be timezone-aware")
        if self.speed <= 0:
            raise ValueError("PlaybackClock.speed must be positive")
        self._wall_anchor = time.monotonic()
        self._moment_anchor = self.record_start

    @property
    def is_paused(self) -> bool:
        return self._paused

    def current_moment(self, now: float | None = None) -> datetime:
        """Recorded-session timestamp corresponding to the current wall clock."""

        if self._paused:
            return self._moment_anchor
        elapsed = (now if now is not None else time.monotonic()) - self._wall_anchor
        return self._moment_anchor + timedelta(seconds=elapsed * self.speed)

    def set_speed(self, speed: float, now: float | None = None) -> None:
        """Change playback rate without jumping the current recorded moment."""

        if speed <= 0:
            raise ValueError("PlaybackClock.speed must be positive")
        self._moment_anchor = self.current_moment(now)
        self._wall_anchor = now if now is not None else time.monotonic()
        self.speed = speed

    def pause(self, now: float | None = None) -> None:
        """Freeze `current_moment()` at whatever it is right now."""

        if not self._paused:
            self._moment_anchor = self.current_moment(now)
            self._paused = True

    def resume(self, now: float | None = None) -> None:
        """Continue advancing from wherever playback was paused."""

        if self._paused:
            self._wall_anchor = now if now is not None else time.monotonic()
            self._paused = False

    def restart(self, now: float | None = None) -> None:
        """Seek back to `record_start`, keeping the current speed/pause state."""

        self._moment_anchor = self.record_start
        self._wall_anchor = now if now is not None else time.monotonic()

    def seek(self, moment: datetime, now: float | None = None) -> None:
        """Jump to `moment` in recorded time, keeping the current speed/pause state."""

        if moment.tzinfo is None:
            raise ValueError("PlaybackClock.seek requires a timezone-aware moment")
        self._moment_anchor = moment
        self._wall_anchor = now if now is not None else time.monotonic()


class PlaybackSource:
    """Drives per-joint positions from a fixed set of tracks, keyed by a clock."""

    def __init__(
        self,
        tracks: dict[str, JointTrack],
        clock: PlaybackClock,
        record_end: datetime | None = None,
    ):
        self._tracks = tracks
        self._clock = clock
        self._record_end = record_end

    @property
    def record_start(self) -> datetime:
        return self._clock.record_start

    @property
    def record_end(self) -> datetime | None:
        """End of the replay window, when one was given - needed to scrub or finish."""

        return self._record_end

    @property
    def joint_names(self) -> frozenset[str]:
        """Every joint this source can drive."""

        return frozenset(self._tracks)

    @property
    def has_commands(self) -> bool:
        """Whether any track holds a recorded command, i.e. anything will move."""

        return any(track.commands for track in self._tracks.values())

    @property
    def speed(self) -> float:
        return self._clock.speed

    @property
    def is_paused(self) -> bool:
        return self._clock.is_paused

    def set_speed(self, speed: float, now: float | None = None) -> None:
        self._clock.set_speed(speed, now)

    @property
    def travel_fraction(self) -> float:
        """Fraction of each stage's datasheet max speed currently allowed."""

        return next(iter(self._tracks.values())).speed_fraction if self._tracks else 1.0

    def set_travel_fraction(self, fraction: float) -> None:
        """Derate every joint's travel speed to `fraction` of its datasheet max."""

        for track in self._tracks.values():
            track.speed_fraction = fraction

    def pause(self, now: float | None = None) -> None:
        self._clock.pause(now)

    def resume(self, now: float | None = None) -> None:
        self._clock.resume(now)

    def restart(self, now: float | None = None) -> None:
        self._clock.restart(now)

    def positions(self, now: float | None = None) -> dict[str, float]:
        """Current joint_name -> Drake position for every tracked joint."""

        moment = self._clock.current_moment(now)
        return {name: track.position_at(moment) for name, track in self._tracks.items()}

    def current_moment(self, now: float | None = None) -> datetime:
        """Where in the recorded session playback currently is, capped at its end."""

        moment = self._clock.current_moment(now)
        if self._record_end is not None:
            return min(moment, self._record_end)
        return moment

    def progress_fraction(self, now: float | None = None) -> float | None:
        """How far through the window playback is, or None without a known end."""

        span = self._span_s()
        if span is None:
            return None
        elapsed = (self.current_moment(now) - self._clock.record_start).total_seconds()
        return min(max(elapsed / span, 0.0), 1.0)

    def seek_fraction(self, fraction: float, now: float | None = None) -> None:
        """Jump to `fraction` of the way through the window (0.0 to 1.0)."""

        span = self._span_s()
        if span is None:
            return
        offset = min(max(fraction, 0.0), 1.0) * span
        self._clock.seek(self._clock.record_start + timedelta(seconds=offset), now)

    def is_complete(self, now: float | None = None) -> bool:
        """True once the clock has run past the end of the replay window."""

        if self._record_end is None:
            return False
        return self.current_moment(now) >= self._record_end

    def _span_s(self) -> float | None:
        if self._record_end is None:
            return None
        span = (self._record_end - self._clock.record_start).total_seconds()
        return span if span > 0 else None

    def is_finished(self, now: float | None = None) -> bool:
        """True once every track's position has reached its last commanded target."""

        moment = self._clock.current_moment(now)
        for track in self._tracks.values():
            if not track.commands:
                continue
            if track.position_at(moment) != track._target_at(len(track.commands) - 1):
                return False
        return True


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


def load_joint_chains(path: str | Path) -> dict[str, str]:
    """Map each joint `ref` in a command-map YAML to its chain (top-level) name.

    Joints missing a `command_pv` are included too - this is only about
    naming, not about what's ready to replay.
    """

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return {
        spec["ref"]: str(stack_name)
        for stack_name, joints in data["joints"].items()
        for spec in joints.values()
    }


def sdf_joint_name(chain_name: str, joint_key: str) -> str:
    """The compiled SDF joint name for one command-map joint.

    Mirrors `sdf_compiler`'s own naming exactly: `{chain}_{stage_ref}_{axis}`,
    slugified the same way (`sdf_compiler._safe_name`) - this is the bridge
    needed to drive `collision.CollisionModel.set_positions()` (which takes
    SDF joint names) from playback/live joint keys (which are bare stage
    refs like "A047", or "stage_ref:axis" like "A067:x" for compound
    chains). Verified against the real exported SDF's joint names.
    """

    from .sdf_compiler import _safe_name

    stage_ref, _, axis_name = joint_key.partition(":")
    if not axis_name:
        axis_name = "motion"
    return _safe_name(f"{chain_name}_{stage_ref}_{axis_name}")


def load_sdf_joint_names(command_map_path: str | Path) -> dict[str, str]:
    """joint_key -> compiled SDF joint name, for every joint in a command-map YAML."""

    chains = load_joint_chains(command_map_path)
    return {joint_key: sdf_joint_name(chain, joint_key) for joint_key, chain in chains.items()}


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


def load_max_speeds(inventory_path: str | Path, joint_refs: list[str]) -> dict[str, float]:
    """Max speed (Drake units/s) for each joint, from the stage catalog's datasheet specs.

    Looks up each joint's stage instance (stripping a compound "stage_ref:axis"
    suffix down to the bare stage ref) and its catalog `max_speed`. Joints
    whose catalog stage has no known max speed fall back to `inf` - the
    original instant zero-order hold.
    """

    inventory_file = resolve_repo_path(inventory_path).resolve()
    inventory = yaml.safe_load(inventory_file.read_text(encoding="utf-8"))
    catalog_path = resolve_repo_path(inventory["stage_catalog"], relative_to=inventory_file.parent)
    catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))["stages"]
    stage_by_ref = {str(item["ref"]): item["catalog"] for item in inventory["stage_instances"]}

    speeds: dict[str, float] = {}
    for joint_ref in joint_refs:
        stage_ref = joint_ref.split(":", 1)[0]
        catalog_id = stage_by_ref.get(stage_ref)
        max_speed = catalog.get(catalog_id, {}).get("max_speed") if catalog_id else None
        speeds[joint_ref] = float(max_speed) if max_speed is not None else float("inf")
    return speeds


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
    # A window with no commands still describes a real assembly, so it renders statically
    # at the reviewed home rather than refusing to open.
    if session_start is None:
        session_start = datetime.now(timezone.utc)
    homes = load_home_positions(inventory_path, list(mappings))
    max_speeds = load_max_speeds(inventory_path, list(mappings))
    tracks = build_tracks(RecordedEpicsClient(commands), mappings, joint_types, homes, max_speeds)
    clock = PlaybackClock(record_start=session_start, speed=speed)
    record_end = max((item.timestamp for item in commands), default=None)
    return PlaybackSource(tracks, clock, record_end)


def build_playback_from_archive(
    start: datetime,
    end: datetime,
    command_map_path: str | Path,
    inventory_path: str | Path,
    *,
    speed: float = 1.0,
) -> PlaybackSource:
    """Wire a real archiver time window into a ready-to-drive PlaybackSource.

    Needs PCDS network access (on-site or VPN), but no archapp install.
    """

    from .epics import ArchiveRestClient

    mappings, joint_types = load_command_map(command_map_path)
    homes = load_home_positions(inventory_path, list(mappings))
    max_speeds = load_max_speeds(inventory_path, list(mappings))
    client = ArchiveRestClient(start=start, end=end, initial_lookback=timedelta(days=1))
    tracks = build_tracks(client, mappings, joint_types, homes, max_speeds)
    clock = PlaybackClock(record_start=start, speed=speed)
    return PlaybackSource(tracks, clock, end)


class OngoingArchivePlaybackSource:
    """Replay an archive window from a fixed start, extending it at 1x wall time.

    This is the bridge mode between historical playback and a true live feed:
    the user chooses the start moment, the source advances forward from there
    in real time, and each poll extends the archive query up to the current
    pseudo-live moment. It intentionally does not expose the finite playback
    pause, restart, seek, or playback-speed controls; continuous playback has
    its own stop/resume feed controls instead.
    """

    def __init__(
        self,
        mappings: dict[str, MotorPvMap],
        joint_types: dict[str, str],
        record_start: datetime,
        home_positions: dict[str, float] | None = None,
        *,
        max_speeds: dict[str, float] | None = None,
        poll_period_s: float = 2.0,
        client_factory=None,
    ) -> None:
        if record_start.tzinfo is None:
            raise ValueError("Ongoing archive playback start must be timezone-aware")
        self._mappings = mappings
        self._joint_types = joint_types
        self._clock = PlaybackClock(record_start=record_start, speed=1.0)
        self._homes = home_positions or {}
        self._max_speeds = max_speeds or {}
        self._poll_period_s = poll_period_s
        self._client_factory = client_factory or _default_ongoing_archiver_factory
        self._tracks: dict[str, JointTrack] = self._empty_tracks()
        self._last_poll = float("-inf")
        self._pending_refresh: Future[dict[str, JointTrack]] | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="twin-lab-ongoing")
        self._travel_fraction = 1.0

    @property
    def record_start(self) -> datetime:
        return self._clock.record_start

    @property
    def record_end(self) -> None:
        return None

    @property
    def is_ongoing_playback(self) -> bool:
        return True

    @property
    def joint_names(self) -> frozenset[str]:
        return frozenset(self._tracks)

    @property
    def has_commands(self) -> bool:
        return any(track.commands for track in self._tracks.values())

    @property
    def travel_fraction(self) -> float:
        return self._travel_fraction

    def set_travel_fraction(self, fraction: float) -> None:
        """Derate every joint's travel speed to `fraction` of its datasheet max."""

        self._travel_fraction = fraction
        for track in self._tracks.values():
            track.speed_fraction = fraction

    @property
    def is_stopped(self) -> bool:
        return self._clock.is_paused

    def stop_feed(self, now: float | None = None) -> None:
        """Stop continuous playback at the current archive timestamp."""

        self._clock.pause(now)

    def resume_feed(self, now: float | None = None) -> None:
        """Continue continuous playback from the timestamp where it was stopped."""

        self._clock.resume(now)

    def current_moment(self, now: float | None = None) -> datetime:
        return self._clock.current_moment(now)

    def is_complete(self, now: float | None = None) -> bool:
        return False

    def positions(self, now: float | None = None) -> dict[str, float]:
        moment_wall = now if now is not None else time.monotonic()
        self._complete_refresh()
        if not self.is_stopped and self._pending_refresh is None:
            if moment_wall - self._last_poll >= self._poll_period_s:
                self._start_refresh(moment_wall)
        moment = self.current_moment(moment_wall)
        return {name: track.position_at(moment) for name, track in self._tracks.items()}

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _start_refresh(self, now: float) -> None:
        end = self.current_moment(now)
        self._pending_refresh = self._executor.submit(self._fetch_tracks, end)
        self._last_poll = now

    def _fetch_tracks(self, end: datetime) -> dict[str, JointTrack]:
        client = self._client_factory(self.record_start, end)
        return build_tracks(client, self._mappings, self._joint_types, self._homes, self._max_speeds)

    def _complete_refresh(self) -> None:
        if self._pending_refresh is None or not self._pending_refresh.done():
            return
        self._tracks = self._pending_refresh.result()
        self._pending_refresh = None
        self.set_travel_fraction(self._travel_fraction)

    def _empty_tracks(self) -> dict[str, JointTrack]:
        return {
            name: JointTrack(
                name,
                self._joint_types[name],
                [],
                self._homes.get(name, 0.0),
                self._max_speeds.get(name, float("inf")),
            )
            for name in self._mappings
        }


def _default_ongoing_archiver_factory(start: datetime, end: datetime) -> CommandHistoryClient:
    from .epics import ArchiveRestClient

    return ArchiveRestClient(start=start, end=end, initial_lookback=timedelta(days=1))


def build_ongoing_playback_from_archive(
    start: datetime,
    command_map_path: str | Path,
    inventory_path: str | Path,
    *,
    poll_period_s: float = 2.0,
) -> OngoingArchivePlaybackSource:
    """Wire a start-only archive replay into a pseudo-live source."""

    mappings, joint_types = load_command_map(command_map_path)
    homes = load_home_positions(inventory_path, list(mappings))
    max_speeds = load_max_speeds(inventory_path, list(mappings))
    return OngoingArchivePlaybackSource(
        mappings,
        joint_types,
        start,
        homes,
        max_speeds=max_speeds,
        poll_period_s=poll_period_s,
    )


class LiveArchiveSource:
    """Mirror real motor commands by re-polling the archiver's trailing edge.

    This is NOT a low-latency Channel Access feed - it re-queries the archiver
    appliance for `[now - lookback_s, now]` every `poll_period_s`. The archiver
    itself only trails the real hardware by a second or two, and that lag is
    an accepted tradeoff here for reusing the one archived-data path playback
    already has, instead of adding a second EPICS client stack (pyepics/
    caproto) just for live monitoring.

    Exposes the same `joint_names` / `positions()` shape as `PlaybackSource`
    so `stage_cad_viewer.view_stage_cad()` can't tell them apart, but has no
    speed/pause/restart - live mirroring always runs at 1x, following
    whatever is happening on the real hardware right now.
    """

    def __init__(
        self,
        mappings: dict[str, MotorPvMap],
        joint_types: dict[str, str],
        home_positions: dict[str, float] | None = None,
        *,
        max_speeds: dict[str, float] | None = None,
        lookback_s: float = 30.0,
        poll_period_s: float = 2.0,
        client_factory=None,
    ) -> None:
        self._mappings = mappings
        self._joint_types = joint_types
        self._homes = home_positions or {}
        self._max_speeds = max_speeds or {}
        self._lookback_s = lookback_s
        self._poll_period_s = poll_period_s
        self._client_factory = client_factory or _default_archiver_factory
        self._tracks: dict[str, JointTrack] = {
            name: JointTrack(
                name,
                joint_types[name],
                [],
                self._homes.get(name, 0.0),
                self._max_speeds.get(name, float("inf")),
            )
            for name in mappings
        }
        self._last_poll = float("-inf")
        self._travel_fraction = 1.0

    @property
    def joint_names(self) -> frozenset[str]:
        return frozenset(self._tracks)

    @property
    def travel_fraction(self) -> float:
        return self._travel_fraction

    def set_travel_fraction(self, fraction: float) -> None:
        """Derate every joint's travel speed to `fraction` of its datasheet max."""

        self._travel_fraction = fraction
        for track in self._tracks.values():
            track.speed_fraction = fraction

    def _refresh(self, now: float) -> None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=self._lookback_s)
        client = self._client_factory(start, end)
        self._tracks = build_tracks(
            client, self._mappings, self._joint_types, self._homes, self._max_speeds
        )
        self.set_travel_fraction(self._travel_fraction)
        self._last_poll = now

    def positions(self, now: float | None = None) -> dict[str, float]:
        """Latest known joint_name -> Drake position, re-polling if the lookback window is stale."""

        moment_wall = now if now is not None else time.monotonic()
        if moment_wall - self._last_poll >= self._poll_period_s:
            self._refresh(moment_wall)
        reference = datetime.now(timezone.utc)
        return {name: track.position_at(reference) for name, track in self._tracks.items()}

    def current_moment(self, now: float | None = None) -> datetime:
        """Live mirroring always sits at the present, not a point in a recording."""

        return datetime.now(timezone.utc)


def _default_archiver_factory(start: datetime, end: datetime) -> CommandHistoryClient:
    from .epics import ArchiveRestClient

    return ArchiveRestClient(start=start, end=end)


def build_live_source(
    command_map_path: str | Path,
    inventory_path: str | Path,
    *,
    lookback_s: float = 30.0,
    poll_period_s: float = 2.0,
) -> LiveArchiveSource:
    """Wire the crystal-stack command map into a ready-to-poll LiveArchiveSource."""

    mappings, joint_types = load_command_map(command_map_path)
    homes = load_home_positions(inventory_path, list(mappings))
    max_speeds = load_max_speeds(inventory_path, list(mappings))
    return LiveArchiveSource(
        mappings,
        joint_types,
        homes,
        max_speeds=max_speeds,
        lookback_s=lookback_s,
        poll_period_s=poll_period_s,
    )


class LiveFileSource:
    """Mirror a recording JSON file that something else keeps refreshing.

    Workaround for environments (like this dev sandbox) that cannot reach the
    PCDS archiver at all - no `archapp`, no network route. Point this at a
    JSON recording file (the same format `load_recorded_commands` reads) that
    some other process, running wherever `archapp` *is* available, overwrites
    on a schedule (cron + scp/rsync to a shared/synced path, a small relay
    script, etc). This class re-reads the file automatically whenever its
    mtime changes - no manual re-import/drag-and-drop needed on this side
    once that exporter exists. Same shape as `PlaybackSource`/
    `LiveArchiveSource` (`joint_names`, `positions()`), so
    `stage_cad_viewer.view_stage_cad()` can't tell it apart from either.
    """

    def __init__(
        self,
        path: str | Path,
        mappings: dict[str, MotorPvMap],
        joint_types: dict[str, str],
        home_positions: dict[str, float] | None = None,
        *,
        max_speeds: dict[str, float] | None = None,
        poll_period_s: float = 1.0,
    ) -> None:
        self._path = Path(path)
        self._mappings = mappings
        self._joint_types = joint_types
        self._homes = home_positions or {}
        self._max_speeds = max_speeds or {}
        self._poll_period_s = poll_period_s
        self._tracks: dict[str, JointTrack] = {
            name: JointTrack(
                name,
                joint_types[name],
                [],
                self._homes.get(name, 0.0),
                self._max_speeds.get(name, float("inf")),
            )
            for name in mappings
        }
        self._last_mtime: float | None = None
        self._last_check = float("-inf")
        self._travel_fraction = 1.0

    @property
    def joint_names(self) -> frozenset[str]:
        return frozenset(self._mappings)

    @property
    def travel_fraction(self) -> float:
        return self._travel_fraction

    def set_travel_fraction(self, fraction: float) -> None:
        """Derate every joint's travel speed to `fraction` of its datasheet max."""

        self._travel_fraction = fraction
        for track in self._tracks.values():
            track.speed_fraction = fraction

    def _maybe_reload(self, now: float) -> None:
        if now - self._last_check < self._poll_period_s:
            return
        self._last_check = now
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime == self._last_mtime:
            return
        self._last_mtime = mtime
        _, commands = load_recorded_commands(self._path)
        self._tracks = build_tracks(
            RecordedEpicsClient(commands),
            self._mappings,
            self._joint_types,
            self._homes,
            self._max_speeds,
        )
        self.set_travel_fraction(self._travel_fraction)

    def positions(self, now: float | None = None) -> dict[str, float]:
        """Latest known joint_name -> Drake position, reloading the file if it changed."""

        moment_wall = now if now is not None else time.monotonic()
        self._maybe_reload(moment_wall)
        reference = datetime.now(timezone.utc)
        return {name: track.position_at(reference) for name, track in self._tracks.items()}

    def current_moment(self, now: float | None = None) -> datetime:
        """Live mirroring always sits at the present, not a point in a recording."""

        return datetime.now(timezone.utc)


def build_live_file_source(
    path: str | Path,
    command_map_path: str | Path,
    inventory_path: str | Path,
    *,
    poll_period_s: float = 1.0,
) -> LiveFileSource:
    """Wire the crystal-stack command map into a ready-to-watch LiveFileSource."""

    mappings, joint_types = load_command_map(command_map_path)
    homes = load_home_positions(inventory_path, list(mappings))
    max_speeds = load_max_speeds(inventory_path, list(mappings))
    return LiveFileSource(
        path, mappings, joint_types, homes, max_speeds=max_speeds, poll_period_s=poll_period_s
    )
