"""Protocol-independent EPICS command-history primitives.

The controls are open-loop, so EPICS contributes timestamped commands rather
than measured motor state. Stage type and model-coordinate conversion belong
to the catalog and simulation model respectively.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from math import pi
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import urlopen


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


def _archiver_timestamp(moment: datetime) -> str:
    """Timestamp format used by PyDM/TRACE's Archiver Appliance requests."""

    if moment.tzinfo is None:
        raise ValueError("Archiver query window must use timezone-aware datetimes")
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


class PyDMArchiverClient:
    """Command history fetched through the Archiver Appliance REST API used by TRACE.

    TRACE uses `PYDM_ARCHIVER_URL` as the base URL and queries
    `/retrieval/data/getData.json?pv=...&from=...&to=...`. This client uses
    that same path, avoiding `archapp`'s built-in `psctlws01` hostname when a
    gateway URL is available from the user's normal SLAC/PCDS environment.
    """

    def __init__(
        self,
        *,
        start: datetime,
        end: datetime,
        base_url: str | None = None,
        opener=urlopen,
    ):
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Archiver query window must use timezone-aware datetimes")
        url = base_url or os.environ.get("PYDM_ARCHIVER_URL")
        if not url:
            raise ValueError(
                "PYDM_ARCHIVER_URL is required for PyDMArchiverClient. Use the same "
                "Archiver URL shown in TRACE's Archive URL field."
            )
        self._base_url = url.rstrip("/")
        self._start = start
        self._end = end
        self._opener = opener

    def commands(self, mapping: MotorPvMap) -> list[MotorCommand]:
        """Fetch one PV from the REST endpoint and convert it into commands."""

        query = urlencode(
            {
                "pv": mapping.command_pv,
                "from": _archiver_timestamp(self._start),
                "to": _archiver_timestamp(self._end),
            }
        )
        url = f"{self._base_url}/retrieval/data/getData.json?{query}"
        try:
            with self._opener(url, timeout=15.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except OSError as exc:
            raise ConnectionError(f"Could not reach archiver URL {self._base_url!r}: {exc}") from exc
        if not payload:
            return []
        data = payload[0].get("data", [])
        return [
            MotorCommand(
                mapping.joint_name,
                datetime.fromtimestamp(float(point["secs"]), tz=timezone.utc),
                float(point["val"]),
            )
            for point in data
        ]


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