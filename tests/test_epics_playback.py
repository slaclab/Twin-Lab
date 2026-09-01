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
    LiveArchiveSource,
    LiveFileSource,
    OngoingArchivePlaybackSource,
    PlaybackClock,
    PlaybackSource,
    build_playback_from_recording,
    build_tracks,
    load_command_map,
    load_home_positions,
    load_joint_chains,
    load_max_speeds,
    load_recorded_commands,
    load_sdf_joint_names,
    sdf_joint_name,
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


def test_track_ramps_continuously_at_max_speed_then_holds() -> None:
    # 0 -> 0.010 m over a command landing at t=0; capped at 0.002 m/s, so it
    # should take 5s to arrive, not jump there instantly.
    commands = [_command("j", 0, 10.0)]
    track = JointTrack("j", "prismatic", commands, home_position=0.0, max_speed=0.002)

    assert track.position_at(T0) == pytest.approx(0.0)
    assert track.position_at(T0 + timedelta(seconds=2)) == pytest.approx(0.004)
    assert track.position_at(T0 + timedelta(seconds=5)) == pytest.approx(0.010)
    # Held at the target well past the ramp, not overshooting.
    assert track.position_at(T0 + timedelta(seconds=50)) == pytest.approx(0.010)


def test_track_ramp_direction_is_signed() -> None:
    commands = [_command("j", 0, 10.0), _command("j", 10, -10.0)]
    track = JointTrack("j", "prismatic", commands, max_speed=0.002)

    # Second command ramps back down from +0.010 toward -0.010 (delta 0.020m),
    # capped at 0.002 m/s -> 10s to arrive.
    assert track.position_at(T0 + timedelta(seconds=15)) == pytest.approx(0.000)
    assert track.position_at(T0 + timedelta(seconds=20)) == pytest.approx(-0.010)


def test_playback_source_is_finished_waits_for_ramp_to_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: 0.0)
    commands = [_command("j", 0, 10.0)]
    tracks = {"j": JointTrack("j", "prismatic", commands, max_speed=0.001)}
    source = PlaybackSource(tracks, PlaybackClock(record_start=T0))

    # 0.010m at 0.001 m/s takes 10s; right after the command it isn't finished yet.
    assert source.is_finished(now=1.0) is False
    assert source.is_finished(now=15.0) is True


def test_build_tracks_sorts_out_of_order_commands() -> None:
    client = RecordedEpicsClient([_command("j", 10, 20.0), _command("j", 0, 10.0)])
    mapping = {"j": MotorPvMap("j", "J:VAL")}

    tracks = build_tracks(client, mapping, {"j": "prismatic"})

    assert [c.commanded for c in tracks["j"].commands] == [10.0, 20.0]


def test_playback_clock_advances_with_speed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time = [0.0]
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: fake_time[0])

    clock = PlaybackClock(record_start=T0, speed=2.0)
    fake_time[0] = 3.0

    assert clock.current_moment() == T0 + timedelta(seconds=6)


def test_playback_clock_set_speed_does_not_jump(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time = [0.0]
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: fake_time[0])

    clock = PlaybackClock(record_start=T0, speed=1.0)
    fake_time[0] = 4.0
    before = clock.current_moment()
    clock.set_speed(0.25)

    assert clock.current_moment() == before


def test_playback_clock_pause_freezes_and_resume_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time = [0.0]
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: fake_time[0])

    clock = PlaybackClock(record_start=T0, speed=1.0)
    fake_time[0] = 5.0
    clock.pause()
    assert clock.is_paused is True
    frozen = clock.current_moment()
    fake_time[0] = 50.0
    # Time passing while paused must not move the recorded moment.
    assert clock.current_moment() == frozen

    clock.resume()
    fake_time[0] = 53.0
    assert clock.is_paused is False
    assert clock.current_moment() == frozen + timedelta(seconds=3)


def test_playback_clock_restart_seeks_to_record_start(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time = [0.0]
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: fake_time[0])

    clock = PlaybackClock(record_start=T0, speed=2.0)
    fake_time[0] = 10.0
    clock.set_speed(0.5)
    clock.restart()
    fake_time[0] = 12.0

    assert clock.current_moment() == T0 + timedelta(seconds=1)


def test_playback_source_reports_positions_and_finished(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: 0.0)
    commands = [_command("j", 0, 10.0), _command("j", 10, 20.0)]
    tracks = {"j": JointTrack("j", "prismatic", commands)}
    clock = PlaybackClock(record_start=T0 + timedelta(seconds=10))
    source = PlaybackSource(tracks, clock)

    assert source.positions(now=0.0) == pytest.approx({"j": 0.020})
    assert source.is_finished(now=0.0) is True


def test_playback_source_pause_resume_restart_delegate_to_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_time = [0.0]
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: fake_time[0])
    tracks: dict[str, JointTrack] = {}
    source = PlaybackSource(tracks, PlaybackClock(record_start=T0, speed=1.0))

    assert source.speed == pytest.approx(1.0)
    assert source.is_paused is False

    source.set_speed(2.0)
    assert source.speed == pytest.approx(2.0)

    source.pause()
    assert source.is_paused is True

    source.resume()
    assert source.is_paused is False

    source.restart()
    assert source.positions(now=0.0) == {}


def test_playback_clock_rejects_naive_start() -> None:
    with pytest.raises(ValueError, match="timezone"):
        PlaybackClock(record_start=datetime(2026, 8, 26))


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
    assert mappings["A040"].command_pv == "POLYCAP:DET:Z"
    assert mappings["A067:x"].command_pv == "POLYCAP:PC:N:X"
    assert mappings["A065:z"].command_pv == "POLYCAP:PC:N:Z"
    assert joint_types["A067:x"] == "prismatic"
    assert len(mappings) == 19  # 12 crystal + 1 detector + 3 polycap stacks x 2 axes


def test_sdf_joint_name_matches_the_real_compiled_sdf() -> None:
    chains = load_joint_chains("config/crystal-stack-command-map.yaml")

    assert sdf_joint_name(chains["A047"], "A047") == "north_crystal_a047_motion"
    assert sdf_joint_name(chains["A040"], "A040") == "detector_a040_motion"
    assert sdf_joint_name(chains["A067:x"], "A067:x") == "north_polycap_a067_x"
    assert sdf_joint_name(chains["A065:z"], "A065:z") == "north_polycap_a065_z"
    assert sdf_joint_name(chains["A058:x"], "A058:x") == "south_polycap_a058_x"


def test_load_sdf_joint_names_covers_every_command_map_joint() -> None:
    sdf_names = load_sdf_joint_names("config/crystal-stack-command-map.yaml")

    assert sdf_names["A053"] == "south_crystal_a053_motion"
    assert sdf_names["A061:x"] == "middle_polycap_a061_x"
    # Every name here should be one the real compiled SDF actually has.
    real_sdf = Path(
        "exports/DSG-000040389.43841-stage-stack.collision/dsg_000040389_43841_stage_stack.sdf"
    ).read_text()
    for name in sdf_names.values():
        assert f'name="{name}"' in real_sdf, f"{name} not found in the compiled SDF"


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


def test_load_max_speeds_from_real_stage_catalog() -> None:
    speeds = load_max_speeds(
        "cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml",
        ["A050", "A048", "A067:x", "A040"],
    )

    assert speeds["A050"] == pytest.approx(0.01)  # SXA0750-R01-R-BM, 10 mm/s
    assert speeds["A048"] == pytest.approx(0.3490659, rel=1e-4)  # RA04A-W01, 20 deg/s
    assert speeds["A067:x"] == pytest.approx(0.005)  # YA04A-R102-RRN-BM, 5 mm/s
    assert speeds["A040"] == pytest.approx(0.01)  # VT-50L-C0014, 10 mm/s


def test_load_recorded_commands_rejects_naive_timestamp(tmp_path) -> None:
    path = tmp_path / "session.json"
    path.write_text(
        '{"commands": [{"joint": "j", "timestamp": "2026-08-26T10:00:00", "commanded": 1.0}]}'
    )

    with pytest.raises(ValueError, match="timezone"):
        load_recorded_commands(path)


def test_scrubbing_seeks_within_the_window_and_reports_progress() -> None:
    """The bottom scrubber is a percentage of the replay window, both ways."""

    clock = PlaybackClock(record_start=T0)
    source = PlaybackSource({}, clock, T0 + timedelta(seconds=100))
    wall = clock._wall_anchor

    source.seek_fraction(0.25, now=wall)
    assert source.current_moment(now=wall) == T0 + timedelta(seconds=25)
    assert source.progress_fraction(now=wall) == pytest.approx(0.25)

    # Out-of-range requests clamp rather than running off the end of the window.
    source.seek_fraction(1.5, now=wall)
    assert source.current_moment(now=wall) == T0 + timedelta(seconds=100)
    assert source.progress_fraction(now=wall) == pytest.approx(1.0)


def test_playback_reports_complete_only_past_the_window_end() -> None:
    clock = PlaybackClock(record_start=T0)
    source = PlaybackSource({}, clock, T0 + timedelta(seconds=10))
    wall = clock._wall_anchor

    assert source.is_complete(now=wall) is False
    assert source.is_complete(now=wall + 11) is True
    assert source.current_moment(now=wall + 11) == T0 + timedelta(seconds=10)
    assert source.current_moment(now=wall + 100) == T0 + timedelta(seconds=10)

    source.restart(now=wall + 11)
    assert source.is_complete(now=wall + 11) is False


def test_playback_without_a_known_end_never_completes_or_scrubs() -> None:
    source = PlaybackSource({}, PlaybackClock(record_start=T0))

    assert source.record_end is None
    assert source.progress_fraction() is None
    assert source.is_complete() is False


def test_travel_fraction_derates_ramp_speed_and_zero_holds_still() -> None:
    """The GUI slider is a percentage of each stage's datasheet max speed."""

    commands = [_command("j", 0, 0.0), _command("j", 10, 10.0)]
    track = JointTrack("j", "prismatic", commands, max_speed=0.002)

    track.speed_fraction = 0.5
    assert track.effective_max_speed == pytest.approx(0.001)
    # Half speed covers half the distance of the full-speed ramp in the same time.
    assert track.position_at(T0 + timedelta(seconds=12)) == pytest.approx(0.002)

    track.speed_fraction = 0.0
    assert track.position_at(T0 + timedelta(seconds=12)) == pytest.approx(0.0)


def test_playback_source_applies_travel_fraction_to_every_joint() -> None:
    tracks = {
        "a": JointTrack("a", "prismatic", [], max_speed=0.01),
        "b": JointTrack("b", "revolute", [], max_speed=0.5),
    }
    source = PlaybackSource(tracks, PlaybackClock(record_start=T0))

    source.set_travel_fraction(0.25)

    assert source.travel_fraction == pytest.approx(0.25)
    assert tracks["a"].effective_max_speed == pytest.approx(0.0025)
    assert tracks["b"].effective_max_speed == pytest.approx(0.125)


def test_empty_recording_still_builds_a_static_playback(tmp_path) -> None:
    """An empty window is a real answer ("nothing moved"), and the assembly is
    known from CAD regardless, so this must render statically rather than refuse
    to open the viewer.
    """

    recording = tmp_path / "empty.json"
    recording.write_text(json.dumps({"commands": []}))

    playback = build_playback_from_recording(
        recording,
        "config/crystal-stack-command-map.yaml",
        "cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml",
    )

    assert playback.has_commands is False
    assert playback.joint_names  # every mapped joint is still present, just idle
    positions = playback.positions()
    assert positions["A050"] == pytest.approx(0.0)
    # A048's reviewed home is 180 deg, so "static" must mean the reviewed home, not zero.
    assert positions["A048"] == pytest.approx(math.pi)


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

    wall_start = playback._clock._wall_anchor  # test drives the clock deterministically
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


def test_live_archive_source_repolls_only_after_poll_period(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_time = [0.0]
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: fake_time[0])
    poll_count = [0]

    def fake_factory(start: datetime, end: datetime) -> RecordedEpicsClient:
        poll_count[0] += 1
        # The "live" value ratchets up each poll, standing in for new commands
        # having landed in the archiver since the last one.
        return RecordedEpicsClient([MotorCommand("j", end - timedelta(seconds=1), float(poll_count[0]))])

    source = LiveArchiveSource(
        {"j": MotorPvMap("j", "J:VAL")},
        {"j": "prismatic"},
        poll_period_s=2.0,
        client_factory=fake_factory,
    )

    first = source.positions(now=0.0)
    assert poll_count[0] == 1
    # Still inside the poll period: no new archiver query, same cached value.
    second = source.positions(now=1.0)
    assert poll_count[0] == 1
    assert second == first
    # Past the poll period: re-queries and picks up the "new" value.
    fake_time[0] = 2.5
    third = source.positions(now=2.5)
    assert poll_count[0] == 2
    assert third["j"] != first["j"]


def test_ongoing_archive_playback_extends_window_without_playback_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: 0.0)
    commands = [_command("j", 1.0, 5.0), _command("j", 3.0, 9.0)]
    windows: list[tuple[datetime, datetime]] = []

    class WindowedClient:
        def __init__(self, start: datetime, end: datetime):
            self.start = start
            self.end = end

        def commands(self, mapping: MotorPvMap) -> list[MotorCommand]:
            return [
                command
                for command in commands
                if command.joint_name == mapping.joint_name and self.start <= command.timestamp <= self.end
            ]

    def factory(start: datetime, end: datetime) -> WindowedClient:
        windows.append((start, end))
        return WindowedClient(start, end)

    source = OngoingArchivePlaybackSource(
        {"j": MotorPvMap("j", "J:VAL")},
        {"j": "prismatic"},
        T0,
        poll_period_s=2.0,
        client_factory=factory,
    )

    assert source.record_end is None
    assert source.is_complete() is False
    assert not hasattr(source, "set_speed")
    assert not hasattr(source, "pause")
    assert not hasattr(source, "seek_fraction")
    assert hasattr(source, "stop_feed")
    assert hasattr(source, "resume_feed")

    assert source.positions(now=0.0)["j"] == pytest.approx(0.0)
    assert windows == [(T0, T0)]
    # Still inside the poll period: the source keeps the cached tracks.
    assert source.positions(now=1.0)["j"] == pytest.approx(0.0)
    assert len(windows) == 1

    assert source.positions(now=2.5)["j"] == pytest.approx(0.005)
    assert windows[-1] == (T0, T0 + timedelta(seconds=2.5))
    assert source.has_commands is True


def test_ongoing_archive_playback_stop_and_resume_are_distinct_from_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("twin_lab.epics_playback.time.monotonic", lambda: 0.0)
    poll_count = [0]

    def factory(start: datetime, end: datetime) -> RecordedEpicsClient:
        poll_count[0] += 1
        return RecordedEpicsClient([MotorCommand("j", end, float(poll_count[0]))])

    source = OngoingArchivePlaybackSource(
        {"j": MotorPvMap("j", "J:VAL")},
        {"j": "prismatic"},
        T0,
        poll_period_s=1.0,
        client_factory=factory,
    )

    source.positions(now=2.0)
    source.stop_feed(now=2.0)

    assert source.is_stopped is True
    assert source.current_moment(now=20.0) == T0 + timedelta(seconds=2.0)
    source.positions(now=20.0)
    assert poll_count[0] == 1

    source.resume_feed(now=20.0)

    assert source.is_stopped is False
    assert source.current_moment(now=23.0) == T0 + timedelta(seconds=5.0)
    source.positions(now=23.0)
    assert poll_count[0] == 2


def test_live_file_source_reloads_only_when_file_changes(tmp_path) -> None:
    path = tmp_path / "live.json"
    now = datetime.now(timezone.utc)

    def write(value: float) -> None:
        path.write_text(
            json.dumps(
                {
                    "commands": [
                        {"joint": "j", "timestamp": now.isoformat(), "commanded": value}
                    ]
                }
            )
        )

    write(1.0)
    source = LiveFileSource(
        path, {"j": MotorPvMap("j", "J:VAL")}, {"j": "prismatic"}, poll_period_s=0.0
    )

    first = source.positions()
    assert first["j"] == pytest.approx(0.001)

    # No file change: still the same value even though poll_period_s is 0 (always checks).
    unchanged = source.positions()
    assert unchanged == first

    write(5.0)
    # mtime resolution can be coarse; force it forward so the reload is detected.
    new_mtime = path.stat().st_mtime + 1.0
    import os

    os.utime(path, (new_mtime, new_mtime))
    updated = source.positions()
    assert updated["j"] == pytest.approx(0.005)


def test_live_file_source_missing_file_holds_home(tmp_path) -> None:
    source = LiveFileSource(
        tmp_path / "does-not-exist.json",
        {"j": MotorPvMap("j", "J:VAL")},
        {"j": "prismatic"},
        {"j": 0.25},
    )

    assert source.positions()["j"] == pytest.approx(0.25)
