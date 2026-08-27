from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import json
import math
from pathlib import Path

import yaml

from twin_lab.epics import MotorCommand, MotorPvMap, RecordedEpicsClient
from twin_lab.epics_playback import (
    JointTrack,
    PlaybackClock,
    PlaybackSource,
    build_playback_from_recording,
    build_tracks,
    load_command_map,
    load_home_positions,
    load_recorded_commands,
)


T0 = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)


def _command(joint: str, offset_s: float, value: float) -> MotorCommand:
    return MotorCommand(joint, T0 + timedelta(seconds=offset_s), value)


def test_track_holds_home_before_first_command() -> None:
    track = JointTrack("j", "prismatic", [_command("j", 5, 10.0)], home_position=0.5)

    assert track.position_at(T0) == pytest.approx(0.5)


def test_track_zero_order_holds_between_commands() -> None:
    commands = [_command("j", 0, 10.0), _command("j", 10, 20.0)]
    track = JointTrack("j", "prismatic", commands)

    assert track.position_at(T0 + timedelta(seconds=4)) == pytest.approx(0.010)
    assert track.position_at(T0 + timedelta(seconds=15)) == pytest.approx(0.020)


def test_build_tracks_sorts_out_of_order_commands() -> None:
    client = RecordedEpicsClient([_command("j", 10, 20.0), _command("j", 0, 10.0)])
    mapping = {"j": MotorPvMap("j", "J:VAL")}

    tracks = build_tracks(client, mapping, {"j": "prismatic"})

    assert [c.commanded for c in tracks["j"].commands] == [10.0, 20.0]


def test_playback_clock_advances_with_speed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time = [0.0]
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: fake_time[0])

    clock = PlaybackClock(session_start=T0, speed=2.0)
    fake_time[0] = 3.0

    assert clock.current_moment() == T0 + timedelta(seconds=6)


def test_playback_clock_set_speed_does_not_jump(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time = [0.0]
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: fake_time[0])

    clock = PlaybackClock(session_start=T0, speed=1.0)
    fake_time[0] = 4.0
    before = clock.current_moment()
    clock.set_speed(0.25)

    assert clock.current_moment() == before


def test_playback_source_reports_positions_and_finished(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: 0.0)
    commands = [_command("j", 0, 10.0), _command("j", 10, 20.0)]
    tracks = {"j": JointTrack("j", "prismatic", commands)}
    clock = PlaybackClock(session_start=T0 + timedelta(seconds=10))
    source = PlaybackSource(tracks, clock)

    assert source.positions(now=0.0) == pytest.approx({"j": 0.020})
    assert source.is_finished(now=0.0) is True


def test_playback_clock_rejects_naive_start() -> None:
    with pytest.raises(ValueError, match="timezone"):
        PlaybackClock(session_start=datetime(2026, 8, 26))


def test_load_command_map_raises_on_missing_pv(tmp_path) -> None:
    path = tmp_path / "map.yaml"
    path.write_text(
        "joints:\n  Stack:\n    x: {ref: A1, joint_type: prismatic, command_pv: null}\n"
    )

    with pytest.raises(ValueError, match="A1"):
        load_command_map(path)


def test_load_command_map_reads_filled_entries(tmp_path) -> None:
    path = tmp_path / "map.yaml"
    path.write_text(
        "joints:\n"
        "  Stack:\n"
        "    x: {ref: A1, joint_type: prismatic, command_pv: 'IOC:STACK:X'}\n"
    )

    mappings, joint_types = load_command_map(path)

    assert mappings["A1"].command_pv == "IOC:STACK:X"
    assert joint_types["A1"] == "prismatic"


def test_real_crystal_stack_command_map_is_fully_filled_in() -> None:
    mappings, joint_types = load_command_map("config/crystal-stack-command-map.yaml")

    assert mappings["A047"].command_pv == "POLYCAP:CRY:N:SWI"
    assert joint_types["A047"] == "revolute"
    assert len(mappings) == 12


def test_load_home_positions_converts_degrees_and_defaults_to_zero(tmp_path) -> None:
    path = tmp_path / "inventory.yaml"
    path.write_text(
        "joint_limit_overrides:\n"
        "  A048: {unit: degree, limits: [150, 210], home: 180}\n"
        "  A004: {unit: meter, limits: [0.0, 0.008], home: 0.003}\n"
    )

    homes = load_home_positions(path, ["A048", "A004", "A050"])

    assert homes["A048"] == pytest.approx(3.141592653589793)
    assert homes["A004"] == pytest.approx(0.003)
    assert homes["A050"] == pytest.approx(0.0)


def test_load_recorded_commands_rejects_naive_timestamp(tmp_path) -> None:
    path = tmp_path / "session.json"
    path.write_text(
        '{"commands": [{"joint": "j", "timestamp": "2026-08-26T10:00:00", "commanded": 1.0}]}'
    )

    with pytest.raises(ValueError, match="timezone"):
        load_recorded_commands(path)


def test_full_crystal_stack_playback_recreates_a_reasonable_session(tmp_path) -> None:
    """End-to-end regression covering the manual dry-run: real command map +
    real inventory homes + a synthetic small-movement recording for a subset
    of the 12 crystal-stack joints, replayed through the whole pipeline.
    Checks the recreated motion is zero-order-held, starts/settles at the
    right values, and stays within each joint's reviewed operating limits.
    """

    session_start = datetime(2026, 8, 26, 17, 0, tzinfo=timezone.utc)
    # (joint ref, seconds after session start, commanded value in controls units)
    steps = [
        ("A050", 0, 0.0), ("A050", 30, 2.0), ("A050", 150, -1.5),  # North x, mm
        ("A049", 0, 0.0), ("A049", 40, -1.0),  # North y, mm
        ("A048", 0, 0.0), ("A048", 50, 0.5),  # North swivel, deg
        ("A047", 0, 0.0), ("A047", 180, -0.2),  # North pivot, deg
        ("A052", 0, 0.0), ("A052", 80, -0.25),  # South pivot, deg
        ("A053", 0, 0.0), ("A053", 70, 0.3),  # South swivel, deg
    ]
    recording = tmp_path / "session.json"
    recording.write_text(
        json.dumps(
            {
                "commands": [
                    {
                        "joint": joint,
                        "timestamp": (session_start + timedelta(seconds=offset)).isoformat(),
                        "commanded": value,
                    }
                    for joint, offset, value in steps
                ]
            }
        )
    )

    playback = build_playback_from_recording(
        recording,
        "config/crystal-stack-command-map.yaml",
        "cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml",
        speed=1.0,
    )

    inventory = yaml.safe_load(
        Path("cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml").read_text()
    )
    overrides = inventory["joint_limit_overrides"]

    def reviewed_limits(ref: str) -> tuple[float, float]:
        lo, hi = overrides[ref]["limits"]
        if overrides[ref].get("unit") == "degree":
            return math.radians(lo), math.radians(hi)
        return lo, hi

    wall_start = playback._clock._wall_start  # test drives the clock deterministically
    before_first_command = playback.positions(now=wall_start)
    # North swivel (A048) is mounted at 180deg home; before any command its
    # position must be that reviewed home, not zero.
    assert before_first_command["A048"] == pytest.approx(math.pi)

    mid_session = playback.positions(now=wall_start + 60)
    # A050 has stepped past its second command (t=30s) by t=60s.
    assert mid_session["A050"] == pytest.approx(0.002)
    # A047 hasn't reached its only real step (t=180s) yet, so it still holds home.
    assert mid_session["A047"] == pytest.approx(0.0)

    end_of_session = playback.positions(now=wall_start + 300)
    assert playback.is_finished(now=wall_start + 300)
    for ref, value in end_of_session.items():
        if ref not in overrides:
            continue
        lo, hi = reviewed_limits(ref)
        assert lo <= value <= hi, f"{ref} at {value} is outside reviewed limits ({lo}, {hi})"
