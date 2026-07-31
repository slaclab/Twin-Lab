"""Unified viewer where manual sliders drive both the render and clearance reporting.

The stage-CAD viewer computes poses by hand for speed. This viewer instead drives
a Drake plant compiled from the same reviewed inventory, so the geometry on screen
and the geometry being checked for interference are the same kinematics.
"""

from __future__ import annotations

import csv
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from .collision import CollisionModel
from .paths import EXPORT_ROOT, resolve_repo_path, review_artifact_stem

WARN_LABEL = "Clearance warning band (mm)"
AUTO_RANGE_LABEL = "Auto motion range (% of travel)"
AUTO_PERIOD_LABEL = "Auto motion period (s)"
COLLISION_ON = "Collision detection: ON (click to disable)"
COLLISION_OFF = "Collision detection: OFF (click to enable)"
ANIMATION_ON = "Animation: ON (click to stop)"
ANIMATION_OFF = "Animation: OFF (click to start)"
STATUS_RGB = {
    "clear": [0.13, 0.42, 0.18],
    "close": [0.72, 0.60, 0.05],
    "interference": [0.60, 0.08, 0.08],
}
# Drake's own sky gradient, restored when clearance checking is switched off.
DEFAULT_TOP_RGB = [0.53, 0.81, 0.98]
DEFAULT_BOTTOM_RGB = [0.10, 0.10, 0.44]
OFFENDER_LIMIT = 3


@dataclass(frozen=True)
class SliderJoint:
    """One SDF joint presented in millimetres or degrees around its logical home."""

    joint_name: str
    stack: str
    stage_ref: str
    joint_type: str
    sdf_lower: float
    sdf_upper: float
    logical_offset: float
    reviewed_home: float

    @property
    def scale(self) -> float:
        return 1000.0 if self.joint_type == "prismatic" else 180.0 / math.pi

    @property
    def unit(self) -> str:
        return "mm" if self.joint_type == "prismatic" else "deg"

    @property
    def label(self) -> str:
        return f"{self.stack} / {self.stage_ref} {self.joint_name} ({self.unit})"

    def to_sdf(self, slider_value: float) -> float:
        return slider_value / self.scale - self.logical_offset

    def slider_bounds(self) -> tuple[float, float, float]:
        lower = (self.sdf_lower + self.logical_offset) * self.scale
        upper = (self.sdf_upper + self.logical_offset) * self.scale
        return lower, upper, self.reviewed_home * self.scale


def read_joint_metadata(package_dir: Path) -> list[SliderJoint]:
    """Read the compiled joint table so sliders match the reviewed operating window."""

    with (package_dir / "joint_metadata.csv").open(encoding="utf-8") as stream:
        return [
            SliderJoint(
                joint_name=row["joint_name"],
                stack=row["stack"],
                stage_ref=row["stage_ref"],
                joint_type=row["type"],
                sdf_lower=float(row["sdf_lower"]),
                sdf_upper=float(row["sdf_upper"]),
                logical_offset=float(row["logical_home_offset"]),
                reviewed_home=float(row["reviewed_home"]),
            )
            for row in csv.DictReader(stream)
        ]


def run_collision_viewer(
    package_dir: str | Path,
    *,
    warn_mm: float = 5.0,
    ignore_file: str | Path | None = None,
    label_source: str | Path | None = None,
    fps: float = 30.0,
) -> None:
    """Drive the compiled assembly from sliders and report clearance at every pose."""

    from pydrake.geometry import Meshcat, MeshcatParams

    from .scene import load_scene
    from .stage_cad_viewer import _wsl_ipv4_address

    package = Path(package_dir).resolve()
    sdf_path = next(
        path for path in sorted(package.glob("*.sdf")) if not path.stem.endswith("_matlab")
    )
    joints = read_joint_metadata(package)

    params = MeshcatParams(host="*")
    wsl_address = _wsl_ipv4_address()
    if wsl_address is not None:
        params.web_url_pattern = f"http://{wsl_address}:{{port}}"
    meshcat = Meshcat(params)

    print(f"Collision viewer: {meshcat.web_url()}")
    print(f"Model: {sdf_path}")
    print("Loading collision geometry into Drake; the viewer stays blank until this finishes.")
    load_start = time.monotonic()
    scene = load_scene(sdf_path, meshcat=meshcat)
    model = CollisionModel(scene, _read_ignored(ignore_file), _read_part_labels(label_source))
    print(
        f"Loaded {_proximity_geometry_count(model)} collision geometries "
        f"in {time.monotonic() - load_start:.0f} s"
    )

    for joint in joints:
        lower, upper, home = joint.slider_bounds()
        meshcat.AddSlider(joint.label, lower, upper, 0.05, home)
    meshcat.AddSlider(WARN_LABEL, 0.0, 50.0, 0.5, warn_mm)
    meshcat.AddSlider(AUTO_RANGE_LABEL, 0.0, 100.0, 1.0, 25.0)
    meshcat.AddSlider(AUTO_PERIOD_LABEL, 2.0, 60.0, 0.5, 12.0)
    meshcat.AddButton("Reset to home")
    meshcat.AddButton("Log clearance report")
    meshcat.AddButton("Stop viewer", "Escape")
    # Added after the fixed buttons so the offender readout always stays below them.
    toggles = _set_toggles(meshcat, [], collision_on=True, animating=False)

    print(f"{len(joints)} joints")
    print("Background: GREEN clear, YELLOW inside the warning band, RED touching.")
    print("Click 'Collision detection' to turn checking off and use this as a plain viewer.")
    print("Click 'Animation' to cycle every joint about its reviewed home.")
    print("Press Escape in Meshcat or Ctrl-C here to stop.")

    frame_period = 1.0 / max(fps, 1.0)
    reset_clicks = 0
    log_clicks = 0
    collision_clicks = 0
    animation_clicks = 0
    collision_on = True
    animating = False
    phase = 0.0
    previous_tick = time.monotonic()
    previous_pose: tuple[list[float], float] | None = None
    previous_status: str | None = None
    readout: list[str] = []
    previous_summary = ""
    while meshcat.GetButtonClicks("Stop viewer") == 0:
        tick = time.monotonic()
        elapsed = tick - previous_tick
        previous_tick = tick

        new_collision = meshcat.GetButtonClicks(toggles[0])
        new_animation = meshcat.GetButtonClicks(toggles[1])
        new_reset = meshcat.GetButtonClicks("Reset to home")
        wanted_collision = collision_on ^ (new_collision != collision_clicks)
        wanted_animating = animating ^ (new_animation != animation_clicks)
        if new_reset != reset_clicks:
            reset_clicks = new_reset
            wanted_animating = False
            phase = 0.0
            for joint in joints:
                meshcat.SetSliderValue(joint.label, joint.slider_bounds()[2])

        if (wanted_collision, wanted_animating) != (collision_on, animating):
            if wanted_collision != collision_on:
                print(f"Collision detection {'ON' if wanted_collision else 'OFF'}.")
            if not wanted_collision:
                _reset_status(meshcat)
            collision_on, animating = wanted_collision, wanted_animating
            toggles = _set_toggles(
                meshcat, toggles + readout, collision_on=collision_on, animating=animating
            )
            readout = []
            collision_clicks = 0
            animation_clicks = 0
            previous_pose = None
            previous_status = None
            previous_summary = ""

        if animating:
            period = max(meshcat.GetSliderValue(AUTO_PERIOD_LABEL), 0.1)
            span_fraction = meshcat.GetSliderValue(AUTO_RANGE_LABEL) / 100.0
            phase = math.fmod(phase + 2.0 * math.pi * elapsed / period, 2.0 * math.pi)
            for index, joint in enumerate(joints):
                lower, upper, home = joint.slider_bounds()
                amplitude = max(min(home - lower, upper - home), 0.0) * span_fraction
                offset = 2.0 * math.pi * index / max(len(joints), 1)
                meshcat.SetSliderValue(joint.label, home + amplitude * math.sin(phase + offset))

        values = [meshcat.GetSliderValue(joint.label) for joint in joints]
        warn_m = max(meshcat.GetSliderValue(WARN_LABEL), 0.0) / 1000.0
        new_log = meshcat.GetButtonClicks("Log clearance report")
        pose = (values, warn_m)
        if pose != previous_pose or new_log != log_clicks:
            previous_pose = pose
            model.set_positions(
                {
                    joint.joint_name: joint.to_sdf(value)
                    for joint, value in zip(joints, values, strict=True)
                }
            )
            scene.diagram.ForcedPublish(model.context)
            if collision_on:
                report = model.report(warn_m=warn_m)
                if report.status != previous_status:
                    previous_status = report.status
                    _set_status(meshcat, report.status)
                readout = _set_offender_readout(meshcat, report, readout)
                if new_log != log_clicks:
                    log_clicks = new_log
                    _print_report(report)
                elif report.summary() != previous_summary:
                    previous_summary = report.summary()
                    print(report.summary())
            else:
                log_clicks = new_log
        time.sleep(frame_period if animating else 0.1)


def _set_toggles(meshcat, previous: list[str], *, collision_on: bool, animating: bool) -> list[str]:
    """Meshcat has no checkbox, so relabelled buttons carry the on/off state.

    The offender readout is torn down with them because dat.GUI only appends, and the
    toggles have to end up above it again.
    """

    for name in previous:
        meshcat.DeleteButton(name)
    labels = [
        COLLISION_ON if collision_on else COLLISION_OFF,
        ANIMATION_ON if animating else ANIMATION_OFF,
    ]
    for name in labels:
        meshcat.AddButton(name)
    return labels


def _reset_status(meshcat) -> None:
    meshcat.SetProperty("/Background/<object>", "top_color", DEFAULT_TOP_RGB)
    meshcat.SetProperty("/Background/<object>", "bottom_color", DEFAULT_BOTTOM_RGB)


def _set_status(meshcat, status: str) -> None:
    """Paint the whole viewport by clearance state so the pose is readable at a glance."""

    color = STATUS_RGB[status]
    # Meshcat wants the property on the Background's object, not the group path.
    meshcat.SetProperty("/Background/<object>", "top_color", color)
    meshcat.SetProperty("/Background/<object>", "bottom_color", color)
    print(status.upper())


def _offender_labels(report) -> list[str]:
    """Name the worst part pairs as Meshcat control labels, worst first.

    Distances are deliberately left out so the labels only change when the offending
    pairs change; a live number would rebuild the controls on every slider step.
    """

    if report.status == "clear":
        return [f"clear: nothing within {report.warn_m * 1000:.0f} mm"]
    heading = "TOUCHING" if report.status == "interference" else "CLOSE"
    labels = []
    for index, item in enumerate(report.offenders(OFFENDER_LIMIT), start=1):
        first, second = report.labeled_parts(item)
        labels.append(f"{heading} {index}: {first} <-> {second}")
    return labels


def _set_offender_readout(meshcat, report, previous: list[str]) -> list[str]:
    """Republish the offending part IDs as buttons, the only text Meshcat can show."""

    labels = _offender_labels(report)
    if labels == previous:
        return previous
    for name in previous:
        meshcat.DeleteButton(name)
    for name in labels:
        meshcat.AddButton(name)
    return labels


def _read_ignored(ignore_file: str | Path | None) -> frozenset[tuple[str, str]]:
    if ignore_file is None:
        return frozenset()
    from .collision import read_ignored_pairs

    return read_ignored_pairs(ignore_file)


def _read_part_labels(label_source: str | Path | None) -> dict[str, str]:
    if label_source is None:
        return {}
    from .collision import read_part_labels

    return read_part_labels(label_source)


def _needs_recompile(package_dir: Path) -> bool:
    """Rebuild packages predating the OBJ-visual fix; Meshcat silently skips STL visuals."""

    metadata = package_dir / "joint_metadata.csv"
    if not metadata.exists():
        return True
    if "reviewed_home" not in metadata.read_text(encoding="utf-8").partition("\n")[0]:
        return True
    sdf_path = next(
        (path for path in sorted(package_dir.glob("*.sdf")) if not path.stem.endswith("_matlab")),
        None,
    )
    return sdf_path is None or ".stl</uri>" in sdf_path.read_text(encoding="utf-8")


def _proximity_geometry_count(model: CollisionModel) -> int:
    from pydrake.geometry import QueryObject, Role

    scene_context = model.scene.scene_graph.GetMyContextFromRoot(model.context)
    query = cast(QueryObject, model.scene.scene_graph.get_query_output_port().Eval(scene_context))
    return query.inspector().NumGeometriesWithRole(Role.kProximity)


def _print_report(report) -> None:
    print(f"\n--- clearance report ({report.warn_m * 1000:.1f} mm band) ---")
    if not report.clearances:
        print("  nothing within the warning band")
    for item in report.clearances[:25]:
        state = "TOUCH" if item.distance_m <= 0.0 else "close"
        first, second = report.described(item)
        part_a, part_b = report.labeled_parts(item)
        print(
            f"  {state} {item.distance_m * 1000:+8.2f} mm  {part_a} <-> {part_b}"
            f"   ({first}  <->  {second})"
        )
    print(
        f"  {len(report.touching)} touching, {len(report.warnings)} within band, "
        f"{len(report.clearances)} reported"
    )


def main() -> None:
    import argparse

    from .sdf_compiler import compile_sdf_package
    from .stage_cad_viewer import prepare_stage_cad

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage_inventory")
    parser.add_argument("--package-dir", type=Path)
    parser.add_argument("--warn-mm", type=float, default=5.0)
    parser.add_argument(
        "--ignore-file",
        type=Path,
        help="YAML holding an `ignored_pairs` block; defaults to the stage inventory itself",
    )
    parser.add_argument(
        "--collision-mode",
        choices=("hull", "convex"),
        default="convex",
        help="convex runs CoACD once and caches it; hull is fast but overestimates volume",
    )
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument(
        "--decomposition-workers",
        type=int,
        default=None,
        help="Parallel CoACD workers for the one-time convex build",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="Animation frame rate; raise for smoother motion (e.g. 120)",
    )
    args = parser.parse_args()

    inventory = resolve_repo_path(args.stage_inventory).resolve()
    scene_path = prepare_stage_cad(inventory, rebuild=args.rebuild)
    package_dir = args.package_dir or EXPORT_ROOT / f"{review_artifact_stem(inventory)}.collision"
    if args.rebuild or _needs_recompile(package_dir):
        print(f"Compiling collision package into {package_dir}")
        compile_sdf_package(
            scene_path,
            package_dir,
            include_collisions=True,
            collision_mode=args.collision_mode,
            decomposition_workers=args.decomposition_workers,
            archive=False,
        )
    try:
        run_collision_viewer(
            package_dir,
            warn_mm=args.warn_mm,
            ignore_file=args.ignore_file or inventory,
            label_source=inventory,
            fps=args.fps,
        )
    except KeyboardInterrupt:
        print("\nCollision viewer stopped.")


if __name__ == "__main__":
    main()
