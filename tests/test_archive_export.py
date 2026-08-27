from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from twin_lab.archive_export import (
    export_session,
    follow_session,
    parse_moment,
)
from twin_lab.epics import MotorCommand, RecordedEpicsClient

T0 = datetime(2026, 8, 26, 22, 52, tzinfo=timezone.utc)


def _fake_factory_for(commands: list[MotorCommand]):
    def factory(start: datetime, end: datetime) -> RecordedEpicsClient:
        return RecordedEpicsClient(
            [item for item in commands if start <= item.timestamp <= end]
        )

    return factory


def test_parse_moment_accepts_offset_and_bare_strings() -> None:
    with_offset = parse_moment("2026-08-26T15:52:00-07:00")
    assert with_offset.tzinfo is not None
    assert with_offset.utcoffset() == timedelta(hours=-7)

    bare = parse_moment("2026-08-26 15:52:00")
    assert bare.tzinfo is not None  # localized rather than left naive


def test_export_session_writes_expected_commands(tmp_path) -> None:
    commands = [
        MotorCommand("A050", T0 + timedelta(seconds=10), 2.0),
        MotorCommand("A047", T0 + timedelta(seconds=20), -0.2),
    ]
    command_map = tmp_path / "map.yaml"
    command_map.write_text(
        "joints:\n"
        "  Stack:\n"
        "    x: {ref: A050, joint_type: prismatic, command_pv: 'A050:VAL'}\n"
        "    pivot: {ref: A047, joint_type: revolute, command_pv: 'A047:VAL'}\n"
    )
    output = tmp_path / "session.json"

    count = export_session(
        T0,
        T0 + timedelta(seconds=30),
        command_map,
        output,
        client_factory=_fake_factory_for(commands),
    )

    assert count == 2
    payload = json.loads(output.read_text())
    joints = {item["joint"] for item in payload["commands"]}
    assert joints == {"A050", "A047"}


def test_export_session_writes_atomically_no_leftover_tmp_file(tmp_path) -> None:
    command_map = tmp_path / "map.yaml"
    command_map.write_text(
        "joints:\n  Stack:\n    x: {ref: A050, joint_type: prismatic, command_pv: 'A050:VAL'}\n"
    )
    output = tmp_path / "session.json"

    export_session(
        T0, T0 + timedelta(seconds=30), command_map, output, client_factory=_fake_factory_for([])
    )

    assert output.exists()
    assert not output.with_suffix(output.suffix + ".tmp").exists()


def test_follow_session_rewrites_file_each_iteration(tmp_path) -> None:
    command_map = tmp_path / "map.yaml"
    command_map.write_text(
        "joints:\n  Stack:\n    x: {ref: A050, joint_type: prismatic, command_pv: 'A050:VAL'}\n"
    )
    output = tmp_path / "live.json"
    poll_count = [0]

    def factory(start: datetime, end: datetime) -> RecordedEpicsClient:
        poll_count[0] += 1
        return RecordedEpicsClient([MotorCommand("A050", end - timedelta(seconds=1), float(poll_count[0]))])

    follow_session(
        command_map,
        output,
        lookback_s=5.0,
        poll_period_s=0.0,
        client_factory=factory,
        iterations=3,
    )

    assert poll_count[0] == 3
    payload = json.loads(output.read_text())
    assert payload["commands"][0]["commanded"] == pytest.approx(3.0)
