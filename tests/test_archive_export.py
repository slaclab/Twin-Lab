from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from twin_lab.archive_export import (
    JointDescription,
    _default_client_factory,
    _default_output_path,
    _diagnose_error,
    _joint_progress_printer,
    describe_joints,
    export_session,
    follow_session,
    parse_moment,
)
from twin_lab.epics import ArchiveRestClient, MotorCommand, RecordedEpicsClient

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


def test_parse_moment_accepts_everyday_formats_a_mechanical_engineer_would_type() -> None:
    assert parse_moment("2026-08-26 3:52pm").time() == parse_moment("2026-08-26 15:52").time()
    assert parse_moment("08/26/2026 3:52 PM").time() == parse_moment("2026-08-26 15:52").time()
    assert parse_moment("2026-08-26 15:52").date() == datetime(2026, 8, 26).date()


def test_parse_moment_bare_time_uses_reference_date() -> None:
    reference = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)

    moment = parse_moment("3:52pm", reference=reference)

    assert moment.date() == reference.date()
    assert moment.hour == 15
    assert moment.minute == 52
    assert moment.tzinfo == reference.tzinfo


def test_parse_moment_rejects_gibberish_with_a_helpful_message() -> None:
    with pytest.raises(ValueError, match="isn't a time format"):
        parse_moment("whenever it happened")


def test_describe_joints_gives_plain_english_labels(tmp_path) -> None:
    command_map = tmp_path / "map.yaml"
    command_map.write_text(
        "joints:\n"
        "  North Crystal:\n"
        "    x: {ref: A050, joint_type: prismatic, command_pv: 'A050:VAL'}\n"
        "    y: {ref: A049, joint_type: prismatic, command_pv: null}\n"
    )

    joints = describe_joints(command_map)

    assert joints == [JointDescription("A050", "North Crystal", "x", "A050:VAL")]
    assert joints[0].display_name == "North Crystal x (A050)"


def test_diagnose_error_recognizes_missing_archapp() -> None:
    message = _diagnose_error(ImportError("No module named 'archapp'"))

    assert "uv sync --all-extras" in message


def test_diagnose_error_recognizes_network_failure() -> None:
    message = _diagnose_error(ConnectionError("Name or service not known"))

    assert "PCDS network" in message
    assert "ARCHAPP_HOSTNAME" in message


def test_default_client_factory_uses_rest_client() -> None:
    client = _default_client_factory(T0, T0 + timedelta(seconds=1))

    assert isinstance(client, ArchiveRestClient)


def test_diagnose_error_explains_403_as_missing_vpn() -> None:
    message = _diagnose_error(ConnectionError("refused the request (HTTP 403)"))

    assert "VPN" in message


def test_diagnose_error_falls_back_to_plain_exception_text() -> None:
    message = _diagnose_error(ValueError("something odd"))

    assert "ValueError" in message
    assert "something odd" in message


def test_default_output_path_is_deterministic_from_start_time() -> None:
    start = datetime(2026, 8, 26, 15, 52, tzinfo=timezone.utc)

    assert _default_output_path(start) == Path("recordings") / "session-20260826T1552.json"


def test_joint_progress_printer_toggles_between_joint_and_pv_labels(capsys) -> None:
    joint_style = _joint_progress_printer(pv_names=False)
    pv_style = _joint_progress_printer(pv_names=True)

    joint_style("A050", "North Crystal", "x", "POLYCAP:CRY:N:X", 3)
    pv_style("A050", "North Crystal", "x", "POLYCAP:CRY:N:X", 3)

    out = capsys.readouterr().out
    assert "North Crystal x (A050)" in out
    assert "POLYCAP:CRY:N:X" in out


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


def test_export_session_reports_per_joint_progress_including_zero_counts(tmp_path) -> None:
    commands = [MotorCommand("A050", T0 + timedelta(seconds=10), 2.0)]
    command_map = tmp_path / "map.yaml"
    command_map.write_text(
        "joints:\n"
        "  North Crystal:\n"
        "    x: {ref: A050, joint_type: prismatic, command_pv: 'A050:VAL'}\n"
        "    pivot: {ref: A047, joint_type: revolute, command_pv: 'A047:VAL'}\n"
    )
    output = tmp_path / "session.json"
    reported: list[tuple[str, str, str, str, int]] = []

    export_session(
        T0,
        T0 + timedelta(seconds=30),
        command_map,
        output,
        client_factory=_fake_factory_for(commands),
        on_joint=lambda *args: reported.append(args),
    )

    assert ("A050", "North Crystal", "x", "A050:VAL", 1) in reported
    assert ("A047", "North Crystal", "pivot", "A047:VAL", 0) in reported


def test_export_session_creates_missing_output_directory(tmp_path) -> None:
    command_map = tmp_path / "map.yaml"
    command_map.write_text(
        "joints:\n  Stack:\n    x: {ref: A050, joint_type: prismatic, command_pv: 'A050:VAL'}\n"
    )
    output = tmp_path / "nested" / "does" / "not" / "exist" / "session.json"

    export_session(
        T0, T0 + timedelta(seconds=30), command_map, output, client_factory=_fake_factory_for([])
    )

    assert output.exists()
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
