"""Protocol-independent EPICS command-history primitives.

The controls are open-loop, so EPICS contributes timestamped commands rather
than measured motor state. Stage type and model-coordinate conversion belong
to the catalog and simulation model respectively.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import pi
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import urlopen

ARCHIVE_RETRIEVAL_URL = "https://pswww.slac.stanford.edu/archiveviewer/retrieval/data/getData.json"


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


class ArchiverBackend(Protocol):
    """The one archapp.interactive.EpicsArchive method this module relies on."""

    def get(self, pv_name: str, xarray: bool = True): ...  # noqa: ANN401


class ArchiverEpicsClient:
    """Command history backed by the PCDS archiver appliance.

    Wraps `archapp.interactive.EpicsArchive` (see
    https://github.com/pcdshub/archapp), which is only importable inside the
    PCDS conda environment. Pass an explicit `backend` to use this outside
    that environment or in tests.
    """

    def __init__(
        self,
        *,
        start: datetime,
        end: datetime,
        backend: ArchiverBackend | None = None,
        source_tz: timezone = timezone.utc,
    ):
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Archiver query window must use timezone-aware datetimes")
        if backend is None:
            try:
                from archapp.interactive import EpicsArchive  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ImportError(
                    "archapp is required for ArchiverEpicsClient. Source the PCDS "
                    "conda env (see https://github.com/pcdshub/archapp), or pass an "
                    "explicit `backend=` for testing/outside that environment."
                ) from exc
            backend = EpicsArchive()
        self._backend = backend
        self._start = start
        self._end = end
        self._source_tz = source_tz

    def commands(self, mapping: MotorPvMap) -> list[MotorCommand]:
        """Fetch and window one PV's archived values into MotorCommands."""

        dataset = self._backend.get(mapping.command_pv, xarray=True)
        try:
            timestamps = dataset["time"].values
            values = dataset["vals"].values
        except KeyError as exc:
            # archapp swallows its own connection failures (prints "No connection
            # to archiver..." to stdout) and returns a dataset with no variables
            # at all, rather than raising - this turns that into something
            # catchable and diagnosable instead of a confusing bare KeyError.
            raise ConnectionError(
                f"The archiver returned no data for {mapping.command_pv!r} - this usually "
                "means it could not be reached (check PCDS network/VPN), not that the PV "
                "has no history."
            ) from exc
        result = []
        for raw_timestamp, raw_value in zip(timestamps, values):
            moment = self._to_aware(raw_timestamp)
            if self._start <= moment <= self._end:
                result.append(MotorCommand(mapping.joint_name, moment, float(raw_value)))
        return result

    def _to_aware(self, raw_timestamp) -> datetime:  # noqa: ANN001
        """Convert a numpy datetime64 (assumed naive, in `source_tz`) to aware UTC."""

        moment = datetime.fromtimestamp(raw_timestamp.astype("datetime64[s]").astype(int), tz=timezone.utc)
        if self._source_tz != timezone.utc:
            moment = moment.replace(tzinfo=self._source_tz).astimezone(timezone.utc)
        return moment


class ArchiveRestClient:
    """Command history read straight from the Archive Viewer REST endpoint.

    Needs only the standard library plus PCDS network access (on-site or VPN),
    so it works in environments where `archapp` cannot be installed. Returns
    the same `MotorCommand` list as `ArchiverEpicsClient`.
    """

    def __init__(
        self,
        *,
        start: datetime,
        end: datetime,
        url: str = ARCHIVE_RETRIEVAL_URL,
        timeout_s: float = 30.0,
        initial_lookback: timedelta = timedelta(),
    ):
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Archiver query window must use timezone-aware datetimes")
        if start > end:
            raise ValueError("Archiver query window must start before it ends")
        self._start = start
        self._end = end
        self._url = url
        self._timeout_s = timeout_s
        self._initial_lookback = initial_lookback

    def commands(self, mapping: MotorPvMap) -> list[MotorCommand]:
        """Fetch and window one PV's archived values into MotorCommands."""

        payload = self._fetch(mapping.command_pv, self._start - self._initial_lookback, self._end)
        if not payload:
            return []
        points = []
        for point in payload[0].get("data", []):
            moment = datetime.fromtimestamp(
                point["secs"] + point.get("nanos", 0) / 1e9, tz=timezone.utc
            )
            points.append(MotorCommand(mapping.joint_name, moment, float(point["val"])))
        previous = [point for point in points if point.timestamp < self._start]
        result = (
            [MotorCommand(mapping.joint_name, self._start, previous[-1].commanded)] if previous else []
        )
        result.extend(point for point in points if self._start <= point.timestamp <= self._end)
        return result

    def _fetch(self, pv_name: str, start: datetime, end: datetime) -> list:
        query = urlencode(
            {
                "pv": pv_name,
                "from": _archive_timestamp(start),
                "to": _archive_timestamp(end),
            },
            quote_via=quote,
        )
        url = f"{self._url}?{query}&donotchunk"
        try:
            with urlopen(url, timeout=self._timeout_s) as response:  # noqa: S310
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 403:
                raise ConnectionError(
                    f"The archiver refused the request for {pv_name!r} (HTTP 403). This "
                    "usually means you are not on the PCDS network - connect to the SLAC "
                    "VPN (or work on-site) and try again."
                ) from exc
            raise ConnectionError(
                f"The archiver returned HTTP {exc.code} for {pv_name!r}."
            ) from exc
        except URLError as exc:
            raise ConnectionError(
                f"Could not reach the archiver at {self._url} - check PCDS network/VPN."
            ) from exc


def _archive_timestamp(moment: datetime) -> str:
    """Format an aware datetime as the UTC millisecond stamp the archiver expects."""

    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{moment.microsecond // 1000:03d}Z"
    )


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