"""Export real EPICS archiver data to a local JSON recording file.

Run this on whatever machine actually has `archapp` + PCDS network access
(e.g. a SLAC-issued computer on-site or on VPN) - it makes the one real
archiver call, and writes a plain JSON file. Nothing else in this repo
(playback, `LiveFileSource`, the Meshcat viewer) needs that access itself;
they only ever read the file this produces. See README "EPICS archiver
access" and `epics_playback.LiveFileSource`.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .epics import CommandHistoryClient, MotorCommand
from .epics_playback import load_command_map


def parse_moment(text: str) -> datetime:
    """Parse a timestamp someone typed: ISO-8601, with or without a UTC offset.

    A bare (no-offset) string is assumed to be in the local system timezone,
    since that's what someone reading a wall clock would type.
    """

    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment


def _default_client_factory(start: datetime, end: datetime) -> CommandHistoryClient:
    from .epics import ArchiverEpicsClient

    return ArchiverEpicsClient(start=start, end=end)


def _fetch_commands(command_map_path, start, end, client_factory) -> list[MotorCommand]:
    mappings, _ = load_command_map(command_map_path)
    client = client_factory(start, end)
    commands: list[MotorCommand] = []
    for mapping in mappings.values():
        commands.extend(client.commands(mapping))
    return commands


def _write_recording(path: Path, commands: list[MotorCommand]) -> None:
    """Write the JSON recording format `load_recorded_commands` reads.

    Writes to a temp file and renames it into place so a concurrent reader
    (`LiveFileSource` watching this same path) never sees a half-written file.
    """

    payload = {
        "commands": [
            {
                "joint": item.joint_name,
                "timestamp": item.timestamp.isoformat(),
                "commanded": item.commanded,
            }
            for item in commands
        ]
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def export_session(
    start: datetime,
    end: datetime,
    command_map_path: str | Path,
    output_path: str | Path,
    *,
    client_factory=None,
) -> int:
    """One-shot export of a fixed time window. Returns the number of commands written."""

    factory = client_factory or _default_client_factory
    commands = _fetch_commands(command_map_path, start, end, factory)
    _write_recording(Path(output_path), commands)
    return len(commands)


def follow_session(
    command_map_path: str | Path,
    output_path: str | Path,
    *,
    lookback_s: float = 30.0,
    poll_period_s: float = 2.0,
    client_factory=None,
    iterations: int | None = None,
) -> None:
    """Continuously re-export a trailing window - the file `LiveFileSource` tails.

    Runs until interrupted (Ctrl-C) unless `iterations` caps the loop (tests).
    """

    factory = client_factory or _default_client_factory
    count = 0
    while iterations is None or count < iterations:
        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=lookback_s)
        commands = _fetch_commands(command_map_path, start, end, factory)
        _write_recording(Path(output_path), commands)
        count += 1
        if iterations is None or count < iterations:
            time.sleep(poll_period_s)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Export real EPICS archiver data to a local JSON recording file. Run "
        "this on a machine with archapp + PCDS network access (e.g. your SLAC-issued "
        "computer on-site or on VPN)."
    )
    parser.add_argument(
        "--command-map",
        default="config/crystal-stack-command-map.yaml",
        help="Joint-to-PV map to export",
    )
    parser.add_argument("--out", required=True, help="Output JSON recording file path")
    parser.add_argument("--start", help="ISO-8601 start of a fixed window to export (one-shot mode)")
    parser.add_argument("--end", help="ISO-8601 end of a fixed window to export (one-shot mode)")
    parser.add_argument(
        "--follow",
        action="store_true",
        help="Keep running, re-exporting a trailing window every --poll-period-s "
        "(for `slac-live-feed --live-file` to tail)",
    )
    parser.add_argument("--lookback-s", type=float, default=30.0)
    parser.add_argument("--poll-period-s", type=float, default=2.0)
    args = parser.parse_args()

    if args.follow:
        if args.start or args.end:
            raise SystemExit("--follow exports a live trailing window; it doesn't take --start/--end")
        print(
            f"Exporting a trailing {args.lookback_s}s window to {args.out} every "
            f"{args.poll_period_s}s. Press Ctrl-C to stop."
        )
        try:
            follow_session(
                args.command_map,
                args.out,
                lookback_s=args.lookback_s,
                poll_period_s=args.poll_period_s,
            )
        except KeyboardInterrupt:
            print("\nStopped.")
        return

    start_text = args.start or input("Start time (e.g. 2026-08-26 15:52): ").strip()
    end_text = args.end or input("End time (e.g. 2026-08-26 15:57): ").strip()
    start = parse_moment(start_text)
    end = parse_moment(end_text)
    count = export_session(start, end, args.command_map, args.out)
    print(f"Wrote {count} command(s) to {args.out}")


if __name__ == "__main__":
    main()
