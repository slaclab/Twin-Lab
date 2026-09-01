from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from twin_lab.epics import (
    ArchiverEpicsClient,
    ArchiveRestClient,
    MotorCommand,
    MotorPvMap,
    RecordedEpicsClient,
    require_recent_commands,
    to_sdf_position,
)

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def test_controls_value_converts_to_sdf_position() -> None:
    mapping = MotorPvMap("detector::x", "DET:X:VAL")

    assert to_sdf_position(125.0, "prismatic") == pytest.approx(0.125)
    assert mapping.command_pv == "DET:X:VAL"


def test_recorded_client_returns_latest_observation() -> None:
    mapping = MotorPvMap("stage::x", "X:VAL")
    command = MotorCommand("stage::x", NOW, commanded=0.1)

    assert RecordedEpicsClient([command]).commands(mapping) == [command]


def test_recent_commands_fail_closed_when_stale() -> None:
    fresh = MotorCommand("fresh", NOW, commanded=0.1)
    stale = MotorCommand("stale", NOW - timedelta(seconds=5), commanded=0.2)

    with pytest.raises(ValueError, match="stale"):
        require_recent_commands([fresh, stale], max_age_s=1.0, now=NOW)


def test_catalog_typed_commands_convert_to_sdf_coordinates() -> None:
    assert to_sdf_position(125.0, "prismatic") == pytest.approx(0.125)
    assert to_sdf_position(45.0, "revolute") == pytest.approx(0.7853981633974483)


def test_naive_command_timestamp_is_rejected() -> None:
    command = MotorCommand("stage::x", datetime(2026, 8, 18, 12), commanded=0.1)

    with pytest.raises(ValueError, match="timezone"):
        require_recent_commands([command], max_age_s=1.0, now=NOW)


def test_archiver_client_reports_unreachable_archiver_as_connection_error() -> None:
    """archapp swallows its own connection failures and returns a dataset with no
    variables at all (rather than raising) - this must surface as a diagnosable
    ConnectionError, not a bare KeyError that looks like a code bug.
    """

    class BrokenBackend:
        def get(self, pv_name: str, xarray: bool = True):
            return {}  # no "time"/"vals" - what archapp returns when it can't connect

    client = ArchiverEpicsClient(start=NOW, end=NOW, backend=BrokenBackend())

    with pytest.raises(ConnectionError, match="could not be reached"):
        client.commands(MotorPvMap("stage::x", "STAGE:X:VAL"))


# Shape captured from a real POLYCAP:CRY:N:X query against the archiver.
_ARCHIVE_PAYLOAD = [
    {
        "meta": {"name": "POLYCAP:CRY:N:X", "EGU": "mm", "PREC": "3"},
        "data": [
            {"secs": 1787782441, "val": 2.0, "nanos": 563924530, "severity": 0, "status": 0},
            {"secs": 1787782563, "val": 0.0, "nanos": 879580942, "severity": 0, "status": 0},
        ],
    }
]

_WINDOW_START = datetime(2026, 8, 24, tzinfo=timezone.utc)
_WINDOW_END = datetime(2026, 8, 31, tzinfo=timezone.utc)


def _rest_client_returning(payload, **kwargs):
    client = ArchiveRestClient(start=_WINDOW_START, end=_WINDOW_END, **kwargs)
    client._fetch = lambda pv_name: payload  # type: ignore[method-assign]
    return client


def test_rest_client_parses_archiver_points_into_commands() -> None:
    client = _rest_client_returning(_ARCHIVE_PAYLOAD)

    commands = client.commands(MotorPvMap("A050", "POLYCAP:CRY:N:X"))

    assert [item.commanded for item in commands] == [2.0, 0.0]
    assert all(item.joint_name == "A050" for item in commands)
    assert all(item.timestamp.tzinfo is not None for item in commands)


def test_rest_client_drops_points_outside_the_requested_window() -> None:
    client = ArchiveRestClient(start=_WINDOW_START, end=_WINDOW_START)
    client._fetch = lambda pv_name: _ARCHIVE_PAYLOAD  # type: ignore[method-assign]

    assert client.commands(MotorPvMap("A050", "POLYCAP:CRY:N:X")) == []


def test_rest_client_returns_nothing_for_a_pv_with_no_history() -> None:
    client = _rest_client_returning([])

    assert client.commands(MotorPvMap("A050", "POLYCAP:CRY:N:X")) == []


def test_rest_client_rejects_naive_and_backwards_windows() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ArchiveRestClient(start=datetime(2026, 8, 24), end=_WINDOW_END)

    with pytest.raises(ValueError, match="start before it ends"):
        ArchiveRestClient(start=_WINDOW_END, end=_WINDOW_START)