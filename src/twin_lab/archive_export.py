"""Export real EPICS archiver data to a local JSON recording file.

Run this on whatever machine actually has `archapp` + PCDS network access
(e.g. a SLAC-issued computer on-site or on VPN) - it makes the one real
archiver call, and writes a plain JSON file. Nothing else in this repo
(playback, `LiveFileSource`, the Meshcat viewer) needs that access itself;
they only ever read the file this produces. See README "Recreating a real
EPICS session" and `epics_playback.LiveFileSource`.

There are two separate entry points, deliberately not one command with a
mode flag - a one-time export for offline replay and a continuous live
mirror are used for very different purposes in practice (post-session
analysis vs. watching an experiment run), so keeping them as separate
commands (mirroring `slac-stage-cad` vs. `slac-live-feed`) keeps each one's
help text and arguments free of the other's:
  - `main` -> `slac-export-session`: one-shot, fixed --start/--end window.
  - `main_live` -> `slac-export-live`: continuous, re-exports a trailing
    window until stopped.

Both are written for mechanical engineers who don't know EPICS or the
controls GUI: they ask plain questions (approximate start/end time), show
what they are about to do before doing it, report per-joint results
(including which joints came back with no data - a likely sign of a
mistyped window, not necessarily a bug), and turn common failures (archapp
missing, no network) into a plain-English explanation instead of a Python
traceback. Pass `--pv-names` to label joints by their EPICS PV instead of
this repo's chain/axis naming, if that's more familiar (e.g. for a controls
engineer who knows this assembly's PV table better than its joint refs).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .epics import CommandHistoryClient, MotorCommand
from .epics_playback import load_command_map

OnJoint = Callable[[str, str, str, str, int], None]

_DATE_TIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %I:%M:%S %p",
    "%Y-%m-%d %I:%M %p",
    "%Y-%m-%d %I:%M:%S%p",
    "%Y-%m-%d %I:%M%p",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %I:%M:%S%p",
    "%m/%d/%Y %I:%M%p",
]
_TIME_ONLY_FORMATS = [
    "%H:%M:%S",
    "%H:%M",
    "%I:%M:%S %p",
    "%I:%M %p",
    "%I:%M:%S%p",
    "%I:%M%p",
]


def parse_moment(text: str, *, reference: datetime | None = None) -> datetime:
    """Parse a timestamp typed by a person, in several everyday formats.

    Accepts ISO-8601 ("2026-08-26T15:52:00-07:00"), "2026-08-26 3:52pm",
    "08/26/2026 15:52", or a bare time like "3:52pm" (assumed to be on the
    same date as `reference`, or today if `reference` is not given). A
    string with no UTC offset is assumed to be in the local system timezone,
    since that's what someone reading a wall clock would type.
    """

    cleaned = text.strip()
    if not cleaned:
        raise ValueError("that was empty")
    normalized = cleaned.upper() if ("am" in cleaned.lower() or "pm" in cleaned.lower()) else cleaned

    moment: datetime | None
    try:
        moment = datetime.fromisoformat(cleaned)
    except ValueError:
        moment = None

    if moment is None:
        for fmt in _DATE_TIME_FORMATS:
            try:
                moment = datetime.strptime(normalized, fmt)
                break
            except ValueError:
                continue

    if moment is None:
        base = reference if reference is not None else datetime.now().astimezone()
        for fmt in _TIME_ONLY_FORMATS:
            try:
                parsed_time = datetime.strptime(normalized, fmt).time()
                moment = datetime.combine(base.date(), parsed_time, tzinfo=base.tzinfo)
                break
            except ValueError:
                continue

    if moment is None:
        raise ValueError(
            f"'{text}' isn't a time format I recognize. Try e.g. '2026-08-26 15:52', "
            "'2026-08-26 3:52pm', or just '3:52pm' for a time today."
        )

    if moment.tzinfo is None:
        moment = moment.astimezone()
    return moment


@dataclass(frozen=True)
class JointDescription:
    """A joint from a command-map YAML, in plain-English terms for progress output."""

    joint_key: str
    chain_name: str
    axis_label: str
    command_pv: str

    @property
    def display_name(self) -> str:
        return f"{self.chain_name} {self.axis_label} ({self.joint_key})"


def describe_joints(command_map_path: str | Path) -> list[JointDescription]:
    """Every ready-to-export joint in a command-map YAML, with human-readable labels."""

    data = yaml.safe_load(Path(command_map_path).read_text(encoding="utf-8"))
    joints: list[JointDescription] = []
    for chain_name, axes in data["joints"].items():
        for axis_label, spec in axes.items():
            command_pv = spec.get("command_pv")
            if command_pv is None:
                continue
            joints.append(JointDescription(str(spec["ref"]), str(chain_name), str(axis_label), str(command_pv)))
    return joints


def _default_client_factory(start: datetime, end: datetime) -> CommandHistoryClient:
    # REST needs only PCDS network access, so it works without the archapp/conda setup.
    from .epics import ArchiveRestClient

    return ArchiveRestClient(start=start, end=end, initial_lookback=timedelta(days=1))


def _fetch_commands(
    command_map_path: str | Path,
    start: datetime,
    end: datetime,
    client_factory,
    on_joint: OnJoint | None = None,
) -> list[MotorCommand]:
    mappings, _ = load_command_map(command_map_path)
    labels = {item.joint_key: item for item in describe_joints(command_map_path)}
    client = client_factory(start, end)
    commands: list[MotorCommand] = []
    for joint_key, mapping in mappings.items():
        found = client.commands(mapping)
        commands.extend(found)
        if on_joint is not None:
            label = labels.get(joint_key)
            chain_name = label.chain_name if label else ""
            axis_label = label.axis_label if label else ""
            command_pv = label.command_pv if label else mapping.command_pv
            on_joint(joint_key, chain_name, axis_label, command_pv, len(found))
    return commands


def _write_recording(path: Path, commands: list[MotorCommand]) -> None:
    """Write the JSON recording format `load_recorded_commands` reads.

    Creates the output directory if needed, and writes to a temp file then
    renames it into place so a concurrent reader (`LiveFileSource` watching
    this same path) never sees a half-written file.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
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
    on_joint: OnJoint | None = None,
) -> int:
    """One-shot export of a fixed time window. Returns the number of commands written."""

    factory = client_factory or _default_client_factory
    commands = _fetch_commands(command_map_path, start, end, factory, on_joint)
    _write_recording(Path(output_path), commands)
    return len(commands)


def follow_session(
    command_map_path: str | Path,
    output_path: str | Path,
    *,
    lookback_s: float = 30.0,
    poll_period_s: float = 2.0,
    client_factory=None,
    on_joint: OnJoint | None = None,
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
        commands = _fetch_commands(command_map_path, start, end, factory, on_joint)
        _write_recording(Path(output_path), commands)
        count += 1
        if iterations is None or count < iterations:
            time.sleep(poll_period_s)


def _default_output_path(start: datetime) -> Path:
    return Path("recordings") / f"session-{start.strftime('%Y%m%dT%H%M')}.json"


def _diagnose_error(exc: Exception) -> str:
    """Turn a likely archiver-connection failure into a plain-English next step."""

    text = str(exc)
    if isinstance(exc, ImportError) or "archapp" in text.lower():
        return (
            "Could not reach the EPICS archiver: the 'archapp' package isn't installed.\n"
            "This is a one-time setup - run:\n"
            "  uv sync --all-extras\n"
            "then try this command again."
        )
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        if "403" in text:
            return (
                "The EPICS archiver refused the request (HTTP 403).\n"
                "This means you're reaching the server but aren't recognized as being on "
                "the PCDS network - connect to the SLAC VPN (or work on-site) and try again."
            )
        return (
            "Could not reach the EPICS archiver over the network.\n"
            "Make sure you're on the PCDS network (on-site or connected to the VPN).\n"
            "If you ARE on VPN and this still fails to resolve a hostname (e.g. "
            "'name resolution' or 'non-existent domain' in the details below), the "
            "archiver's default hostname ('psctlws01') may not be the right one for your "
            "connection - ask the controls team for the correct one, then set it with:\n"
            "  ARCHAPP_HOSTNAME=the-right-hostname uv run slac-export-session ...\n"
            f"(Details: {exc})"
        )
    return (
        "Something went wrong while talking to the EPICS archiver:\n"
        f"  {type(exc).__name__}: {exc}\n"
        "If this keeps happening, check with the controls team."
    )


def _print_joint_progress(
    joint_key: str, chain_name: str, axis_label: str, command_pv: str, count: int, *, pv_names: bool = False
) -> None:
    if pv_names:
        label = command_pv
    else:
        label = f"{chain_name} {axis_label} ({joint_key})" if chain_name else joint_key
    if count == 0:
        print(f"  ! {label}: no data found in this window")
    else:
        print(f"  - {label}: {count} command(s)")


def _joint_progress_printer(*, pv_names: bool) -> OnJoint:
    """Bind the `--pv-names` choice into a plain 5-arg `on_joint` callback."""

    def printer(joint_key: str, chain_name: str, axis_label: str, command_pv: str, count: int) -> None:
        _print_joint_progress(joint_key, chain_name, axis_label, command_pv, count, pv_names=pv_names)

    return printer


def _confirm(prompt: str) -> bool:
    try:
        answer = input(f"{prompt} [Y/n]: ").strip().lower()
    except EOFError:
        return True
    return answer in ("", "y", "yes")


def _prompt_moment(label: str, provided: str | None, *, reference: datetime | None = None) -> datetime:
    if provided:
        try:
            return parse_moment(provided, reference=reference)
        except ValueError as exc:
            print(f"Could not understand '{provided}' as a time: {exc}")
    while True:
        try:
            text = input(f"{label} (e.g. '2026-08-26 3:52pm', or just '3:52pm' for today): ")
        except EOFError:
            raise SystemExit(
                f"No {label.lower()} was given, and there's no terminal available to ask for "
                "one. Pass --start/--end explicitly instead."
            ) from None
        try:
            return parse_moment(text, reference=reference)
        except ValueError as exc:
            print(f"Sorry, could not understand that: {exc}")


def _add_common_args(parser) -> None:  # noqa: ANN001
    parser.add_argument(
        "--command-map",
        default="config/crystal-stack-command-map.yaml",
        help="Joint-to-PV map to export (default: the crystal-stack map)",
    )
    parser.add_argument(
        "--pv-names",
        action="store_true",
        help="Label joints by their EPICS PV instead of this repo's chain/axis naming "
        "(e.g. 'POLYCAP:CRY:N:X' instead of 'North Crystal x (A050)')",
    )


def main() -> None:
    """`slac-export-session`: one-shot export of a fixed time window, for later replay."""

    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Pull real motor position data from the EPICS archiver for a fixed time window "
            "and save it as a file the simulator can play back. No EPICS or controls-GUI "
            "knowledge needed beyond roughly when the motion happened. For continuously "
            "mirroring live hardware instead, use `slac-export-live`."
        )
    )
    _add_common_args(parser)
    parser.add_argument(
        "--out", help="Output JSON recording file path (default: recordings/session-<start>.json)"
    )
    parser.add_argument("--start", help="Start of the time window, e.g. '2026-08-26 3:52pm'")
    parser.add_argument("--end", help="End of the time window, e.g. '2026-08-26 3:57pm'")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    joints = _load_joints_or_exit(args.command_map)
    on_joint = _joint_progress_printer(pv_names=args.pv_names)

    print(
        "This pulls real motor position data from the EPICS archiver for a time window "
        "you choose, and saves it as a file the simulator can play back.\n"
    )
    start = _prompt_moment("Start time", args.start)
    end = _prompt_moment("End time", args.end, reference=start)
    while end <= start:
        print("End time must be after the start time - try again.")
        end = _prompt_moment("End time", None, reference=start)

    out = Path(args.out) if args.out else _default_output_path(start)

    print()
    print("About to export:")
    print(f"  Joint map:    {args.command_map} ({len(joints)} joint(s))")
    print(f"  Time window:  {start.isoformat()}  to  {end.isoformat()}  (duration {end - start})")
    print(f"  Output file:  {out}")
    print()
    if not args.yes and not _confirm("Continue?"):
        print("Cancelled - nothing was exported.")
        return

    print("\nConnecting to the EPICS archiver...")
    try:
        count = export_session(start, end, args.command_map, out, on_joint=on_joint)
    except Exception as exc:
        raise SystemExit(_diagnose_error(exc)) from exc

    print(f"\nWrote {count} command(s) across {len(joints)} joint(s) to {out}")
    if count == 0:
        print(
            "No commands were found for any joint in that window - double check the start/end "
            "times, or ask the controls team whether anything actually moved then."
        )
    print("\nTo play this back in the simulator:")
    print(
        "  uv run slac-stage-cad cad/DSG-000040389/reviews/43841-stage-stack.inventory.yaml \\\n"
        f"    --playback-recording {out}"
    )


def main_live() -> None:
    """`slac-export-live`: continuously mirror a trailing window, for watching a live run.

    Kept as a separate command from `slac-export-session` on purpose: a one-time
    export for offline replay and a continuous live mirror serve very different
    workflows in practice (post-session analysis vs. watching an experiment run
    happen), so each gets its own focused command instead of one command with a
    mode flag to remember - the same split as `slac-stage-cad` vs. `slac-live-feed`.
    """

    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Continuously mirror real EPICS motor commands into a local file, for watching "
            "the simulator track live hardware during an experiment run. For a one-time "
            "export of a fixed past time window instead, use `slac-export-session`."
        )
    )
    _add_common_args(parser)
    parser.add_argument(
        "--out",
        default=str(Path("recordings") / "live.json"),
        help="Output JSON file to keep refreshing (default: recordings/live.json)",
    )
    parser.add_argument(
        "--lookback-s",
        type=float,
        default=30.0,
        help="How far back each refresh looks for the latest command per joint",
    )
    parser.add_argument(
        "--poll-period-s",
        type=float,
        default=2.0,
        help="How often to refresh (the archiver itself trails real hardware by roughly "
        "this much already, so shorter than ~1-2s buys little)",
    )
    args = parser.parse_args()

    joints = _load_joints_or_exit(args.command_map)
    on_joint = _joint_progress_printer(pv_names=args.pv_names)
    out = Path(args.out)

    print(
        f"This will continuously mirror the last {args.lookback_s:.0f}s of real motor "
        f"commands into {out}, refreshing every {args.poll_period_s:.0f}s, tracking "
        f"{len(joints)} joint(s), until you stop it with Ctrl-C."
    )
    print(
        "Point `uv run slac-live-feed --live-file "
        f"{out}` (in another terminal, or another machine that can read this path) at it "
        "to watch the simulator follow along.\n"
    )
    try:
        follow_session(
            args.command_map,
            out,
            lookback_s=args.lookback_s,
            poll_period_s=args.poll_period_s,
            on_joint=on_joint,
        )
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        raise SystemExit(_diagnose_error(exc)) from exc


def _load_joints_or_exit(command_map_path: str | Path) -> list[JointDescription]:
    try:
        joints = describe_joints(command_map_path)
    except Exception as exc:
        raise SystemExit(f"Could not read the joint map at {command_map_path}: {exc}") from exc
    if not joints:
        raise SystemExit(
            f"{command_map_path} has no joints with a command_pv filled in - nothing to export."
        )
    return joints


if __name__ == "__main__":
    main()

